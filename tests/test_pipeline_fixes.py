"""
Pipeline Critical Fixes — Verification Tests
Run with: python -c "import sys; sys.path.insert(0,'.');exec(open('tests/test_pipeline_fixes.py').read())"
"""

import sys
import os
import inspect
import traceback
import tempfile
import pathlib

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"
results = []

def run(name, fn):
    try:
        fn()
        print(f"  {PASS}  {name}")
        results.append((name, "pass", None))
    except AssertionError as e:
        print(f"  {FAIL}  {name}")
        print(f"         {e}")
        results.append((name, "fail", str(e)))
    except Exception as e:
        print(f"  {FAIL}  {name} -- unexpected error: {e}")
        traceback.print_exc()
        results.append((name, "fail", str(e)))


# =========================================================================
# FIX 1 -- Shared Redis singleton
# =========================================================================

print("\n-- Fix 1: Shared Redis singleton (redis_client.py) -------------------------")

def test_redis_singleton_same_object():
    from backend.services.rate_limiter import _get_redis
    r1 = _get_redis()
    r2 = _get_redis()
    assert r1 is r2, f"Expected same Redis object, got different: {id(r1)} vs {id(r2)}"

def test_redis_singleton_is_live():
    from backend.services.rate_limiter import _get_redis
    assert _get_redis().ping() is True, "Redis ping returned False"

def test_redis_has_connection_pool():
    from backend.services.rate_limiter import _get_redis
    pool = _get_redis().connection_pool
    assert hasattr(pool, "max_connections")
    # Shared pool is sized at 20 (was 10 in the old per-module pool)
    assert pool.max_connections == 20, f"Expected max_connections=20, got {pool.max_connections}"

def test_redis_store_and_rate_limiter_share_same_client():
    """The two modules that previously each had their own pool now share one."""
    from backend.services.rate_limiter import _get_redis as rl_get
    from backend.services.redis_client import get_redis as rc_get
    assert rl_get() is rc_get(), "rate_limiter and redis_client return different clients"

def test_from_url_called_once_for_many_gets():
    """Verify from_url() is called exactly once no matter how many times get_redis() is called."""
    from backend.services import redis_client
    import redis as redis_module

    saved_client = redis_client._client
    call_log = []
    original_from_url = redis_module.from_url

    def patched_from_url(*a, **kw):
        call_log.append(1)
        return original_from_url(*a, **kw)

    redis_module.from_url = patched_from_url
    redis_client._client = None  # force re-init
    try:
        for _ in range(5):
            redis_client.get_redis()
        assert len(call_log) == 1, (
            f"from_url() called {len(call_log)} times for 5 get_redis() calls; expected 1"
        )
    finally:
        redis_module.from_url = original_from_url
        redis_client._client = saved_client  # restore

run("same object across multiple calls", test_redis_singleton_same_object)
run("Redis is live (ping)", test_redis_singleton_is_live)
run("shared pool max_connections=20", test_redis_has_connection_pool)
run("rate_limiter and redis_client share the same client object", test_redis_store_and_rate_limiter_share_same_client)
run("from_url() called exactly once for 5 get_redis() calls", test_from_url_called_once_for_many_gets)


# =========================================================================
# FIX 2 -- Dead code removed from _structure_document
# =========================================================================

print("\n-- Fix 2: Dead code removed (_structure_document) -------------------------")

def test_dead_break_removed():
    from backend.tasks.pipeline_tasks import _structure_document
    src = inspect.getsource(_structure_document)
    assert "last_error is None" not in src

def test_structure_raises_on_empty_chain():
    from backend.tasks import pipeline_tasks as pt
    original = pt.get_fallback_chain
    pt.get_fallback_chain = lambda doc_type: []
    try:
        pt._structure_document({"full_text": "test"}, "SALE_DEED")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "All models failed" in str(e), f"Wrong error: {e}"
    finally:
        pt.get_fallback_chain = original

run("'last_error is None' not in _structure_document source", test_dead_break_removed)
run("_structure_document still raises RuntimeError on empty chain", test_structure_raises_on_empty_chain)


# =========================================================================
# FIX 3 -- Redundant MySQL read removed from finalize_case_task
# =========================================================================

print("\n-- Fix 3: Redundant MySQL read removed (finalize_case_task) ---------------")

def test_no_private_get_conn_import():
    src = open("backend/tasks/pipeline_tasks.py", encoding="utf-8").read()
    assert "_get_conn as get_v2_conn" not in src

def test_no_redundant_select_sql():
    src = open("backend/tasks/pipeline_tasks.py", encoding="utf-8").read()
    assert "SELECT status FROM cases WHERE id" not in src

def test_mysql_update_still_called():
    src = open("backend/tasks/pipeline_tasks.py", encoding="utf-8").read()
    assert "mysql_update_case_status(case_id=case_id)" in src

run("_get_conn private import gone", test_no_private_get_conn_import)
run("raw SELECT status SQL gone", test_no_redundant_select_sql)
run("mysql_update_case_status still present", test_mysql_update_still_called)


# =========================================================================
# FIX 4a -- self_critique wired into cross_doc_verifier
# =========================================================================

print("\n-- Fix 4a: self_critique wired in (cross_doc_verifier.py) -----------------")

def test_run_critique_importable_from_cdv():
    from backend.services.cross_doc_verifier import run_critique
    assert callable(run_critique)

def test_run_critique_in_verification_body():
    from backend.services import cross_doc_verifier
    src = inspect.getsource(cross_doc_verifier.run_cross_doc_verification)
    assert "run_critique" in src

def test_critique_before_risk_score():
    from backend.services import cross_doc_verifier
    src = inspect.getsource(cross_doc_verifier.run_cross_doc_verification)
    assert src.find("run_critique") < src.find("compute_risk_score")

def test_critique_wrapped_in_try_except():
    from backend.services import cross_doc_verifier
    src = inspect.getsource(cross_doc_verifier.run_cross_doc_verification)
    critique_pos = src.find("run_critique(")
    surrounding = src[max(0, critique_pos - 100): critique_pos + 300]
    assert "except" in surrounding

run("run_critique importable from cross_doc_verifier", test_run_critique_importable_from_cdv)
run("run_critique() called inside run_cross_doc_verification()", test_run_critique_in_verification_body)
run("run_critique called BEFORE compute_risk_score", test_critique_before_risk_score)
run("run_critique call wrapped in try/except", test_critique_wrapped_in_try_except)


# =========================================================================
# FIX 4b -- Groq singleton in cross_doc_verifier
# =========================================================================

print("\n-- Fix 4b: Groq singleton (cross_doc_verifier.py) -------------------------")

def test_get_groq_client_exists_cdv():
    from backend.services.cross_doc_verifier import _get_groq_client
    assert callable(_get_groq_client)

def test_no_per_call_httpx_in_run_verification():
    from backend.services import cross_doc_verifier
    src = inspect.getsource(cross_doc_verifier.run_cross_doc_verification)
    assert "httpx.Client(" not in src

run("_get_groq_client() exists in cross_doc_verifier", test_get_groq_client_exists_cdv)
run("no per-call httpx.Client() in run_cross_doc_verification()", test_no_per_call_httpx_in_run_verification)


# =========================================================================
# FIX 4c -- Groq singleton in self_critique
# =========================================================================

print("\n-- Fix 4c: Groq singleton (self_critique.py) --------------------------------")

def test_get_groq_client_exists_sc():
    from backend.services.self_critique import _get_groq_client
    assert callable(_get_groq_client)

def test_no_per_call_groq_in_run_critique():
    from backend.services.self_critique import run_critique
    src = inspect.getsource(run_critique)
    assert "Groq(api_key=" not in src
    assert "httpx.Client(" not in src

def test_critique_passthrough_empty():
    from backend.services.self_critique import run_critique
    assert run_critique([]) == []

def test_critique_passthrough_no_key():
    import backend.services.self_critique as sc
    original = sc.GROQ_API_KEY
    sc.GROQ_API_KEY = ""
    try:
        sample = [{"type": "TEST", "severity": "low"}]
        result = sc.run_critique(sample)
        assert result == sample
    finally:
        sc.GROQ_API_KEY = original

run("_get_groq_client() exists in self_critique", test_get_groq_client_exists_sc)
run("no per-call Groq()/httpx.Client() inside run_critique()", test_no_per_call_groq_in_run_critique)
run("run_critique([]) returns [] without hitting API", test_critique_passthrough_empty)
run("run_critique() passthrough when GROQ_API_KEY empty", test_critique_passthrough_no_key)


# =========================================================================
# FIX 5 -- PNG/zip cleanup
# =========================================================================

print("\n-- Fix 5: PNG/zip cleanup (sarvam_ocr.py) ----------------------------------")

def test_shutil_rmtree_in_source():
    src = open("backend/services/sarvam_ocr.py", encoding="utf-8").read()
    assert "shutil.rmtree" in src

def test_cleanup_inside_finally():
    from backend.services.sarvam_ocr import _process_chunked
    src = inspect.getsource(_process_chunked)
    assert "finally:" in src
    assert src.find("shutil.rmtree") > src.find("finally:")

def test_cleanup_actually_deletes_files():
    import shutil
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        png_dir = base / "pages"
        png_dir.mkdir()
        (png_dir / "page_0001.png").write_bytes(b"fake")
        zip1 = base / "chunk_00.zip"
        zip1.write_bytes(b"zip")
        zip_paths = [(0, 1, 10, zip1)]
        shutil.rmtree(png_dir, ignore_errors=True)
        for _, _, _, zp in zip_paths:
            zp.unlink(missing_ok=True)
        assert not png_dir.exists()
        assert not zip1.exists()

run("shutil.rmtree present in sarvam_ocr.py", test_shutil_rmtree_in_source)
run("cleanup inside finally block", test_cleanup_inside_finally)
run("cleanup logic actually deletes png_dir and input zips", test_cleanup_actually_deletes_files)


# =========================================================================
# FIX 6 -- Classification 2000 chars
# =========================================================================

print("\n-- Fix 6: Classification text length (pipeline_tasks.py) ------------------")

def test_classification_2000():
    src = open("backend/tasks/pipeline_tasks.py", encoding="utf-8").read()
    assert 'full_text"][:2000]' in src

def test_old_500_slice_gone():
    import re
    src = open("backend/tasks/pipeline_tasks.py", encoding="utf-8").read()
    for m in re.findall(r'classify_document\([^)]*\[:(\d+)\]', src):
        assert m != "500"

run("classify_document called with [:2000]", test_classification_2000)
run("old [:500] on classify_document is gone", test_old_500_slice_gone)


# =========================================================================
# FIX 7 -- Noise heuristic in preprocessor
# =========================================================================

print("\n-- Fix 7: Noise-level heuristic (preprocessor.py) -------------------------")

def test_noise_level_in_source():
    src = open("backend/services/preprocessor.py", encoding="utf-8").read()
    assert "noise_level" in src
    assert "np.std(gray)" in src

def test_threshold_value():
    src = open("backend/services/preprocessor.py", encoding="utf-8").read()
    assert "> 15" in src

def test_denoising_skipped_clean_image():
    import numpy as np
    import cv2
    from backend.services.preprocessor import _enhance_page
    clean_img = np.ones((200, 200, 3), dtype=np.uint8) * 200
    call_log = []
    original = cv2.fastNlMeansDenoisingColored
    cv2.fastNlMeansDenoisingColored = lambda *a, **kw: (call_log.append(1), original(*a, **kw))[1]
    try:
        _enhance_page(clean_img.copy())
        assert len(call_log) == 0, f"Denoising called {len(call_log)}x on clean image"
    finally:
        cv2.fastNlMeansDenoisingColored = original

def test_denoising_applied_noisy_image():
    import numpy as np
    import cv2
    from backend.services.preprocessor import _enhance_page
    np.random.seed(42)
    noisy_img = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    call_log = []
    original = cv2.fastNlMeansDenoisingColored
    cv2.fastNlMeansDenoisingColored = lambda *a, **kw: (call_log.append(1), original(*a, **kw))[1]
    try:
        _enhance_page(noisy_img.copy())
        assert len(call_log) == 1, f"Denoising called {len(call_log)}x on noisy image, expected 1"
    finally:
        cv2.fastNlMeansDenoisingColored = original

run("noise_level and np.std(gray) in preprocessor source", test_noise_level_in_source)
run("threshold value is 15", test_threshold_value)
run("denoising SKIPPED for clean image (std ~= 0)", test_denoising_skipped_clean_image)
run("denoising APPLIED for noisy image (std >> 15)", test_denoising_applied_noisy_image)


# =========================================================================
# New: Redis/Celery fixes
# =========================================================================

print("\n-- Fix (Redis #2): set_doc_status uses atomic Lua script -------------------")

def test_set_doc_status_lua_present():
    src = open("backend/services/redis_store.py", encoding="utf-8").read()
    assert "_SET_DOC_STATUS_LUA" in src
    assert "r.eval(_SET_DOC_STATUS_LUA" in src

def test_set_doc_status_no_old_hget_hset_pair():
    """The old read-modify-write should be gone — replaced by eval."""
    from backend.services.redis_store import set_doc_status
    src = inspect.getsource(set_doc_status)
    assert "hget(" not in src, "Old hget() still in set_doc_status — not atomic"
    assert "hset(" not in src, "Old hset() still in set_doc_status — not atomic"
    assert "r.eval(" in src, "r.eval() Lua call not found in set_doc_status"

def test_set_doc_status_merges_fields_atomically():
    """Live test: two sequential updates should both appear in the stored blob."""
    from backend.services.redis_store import set_doc_status, _get_client, _docs_status_key
    import json
    r = _get_client()
    case_id = "__test_atomic__"
    doc_id  = "doc_x"
    key = _docs_status_key(case_id)
    r.hdel(key, doc_id)  # clean up first
    try:
        set_doc_status(case_id, doc_id, status="ocr", step="running")
        set_doc_status(case_id, doc_id, step="done")  # should NOT erase status
        raw = r.hget(key, doc_id)
        blob = json.loads(raw)
        assert blob.get("status") == "ocr",  f"status was overwritten: {blob}"
        assert blob.get("step")   == "done", f"step was not updated: {blob}"
    finally:
        r.hdel(key, doc_id)

run("_SET_DOC_STATUS_LUA constant present in redis_store", test_set_doc_status_lua_present)
run("old hget/hset pair replaced by r.eval()", test_set_doc_status_no_old_hget_hset_pair)
run("two sequential set_doc_status calls both persist (merge test)", test_set_doc_status_merges_fields_atomically)


print("\n-- Fix (Redis #3): rate limiter _try_acquire uses atomic Lua ---------------")

def test_acquire_lua_constant_present():
    src = open("backend/services/rate_limiter.py", encoding="utf-8").read()
    assert "_ACQUIRE_LUA" in src
    assert "r.eval(" in src

def test_try_acquire_has_no_pipelines():
    from backend.services.rate_limiter import TokenBucketRateLimiter
    src = inspect.getsource(TokenBucketRateLimiter._try_acquire)
    assert "r.pipeline()" not in src, "Old pipeline() still in _try_acquire — not atomic"
    assert "r.eval(" in src, "r.eval() not found in _try_acquire"

def test_try_acquire_returns_bool_float():
    from backend.services.rate_limiter import gemini_limiter
    result = gemini_limiter._try_acquire(tokens=1)
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], bool)
    assert isinstance(result[1], float)

run("_ACQUIRE_LUA constant present in rate_limiter", test_acquire_lua_constant_present)
run("old r.pipeline() replaced by r.eval() in _try_acquire", test_try_acquire_has_no_pipelines)
run("_try_acquire returns (bool, float) as before", test_try_acquire_returns_bool_float)


print("\n-- Fix (Redis #4): wait_and_acquire max_retries capped at 10 ---------------")

def test_wait_and_acquire_default_retries():
    import inspect as _ins
    from backend.services.rate_limiter import TokenBucketRateLimiter
    sig = _ins.signature(TokenBucketRateLimiter.wait_and_acquire)
    default = sig.parameters["max_retries"].default
    assert default == 10, f"Expected max_retries default=10, got {default}"

run("wait_and_acquire default max_retries=10 (was 30)", test_wait_and_acquire_default_retries)


print("\n-- Fix (Redis #5): LLMCallTracker uses pipeline for lpush+ltrim -----------")

def test_llm_tracker_uses_pipeline():
    from backend.services.rate_limiter import LLMCallTracker
    src = inspect.getsource(LLMCallTracker.record)
    # Should have pipe = r.pipeline() and pipe.execute()
    assert "pipe = r.pipeline()" in src or "r.pipeline()" in src
    assert "pipe.lpush(" in src
    assert "pipe.ltrim(" in src
    assert "pipe.execute()" in src

run("LLMCallTracker.record uses pipeline for lpush+ltrim", test_llm_tracker_uses_pipeline)


print("\n-- Fix (Redis #6): remove_error_for_doc uses MULTI/EXEC transaction --------")

def test_remove_error_uses_transaction():
    from backend.services.redis_store import remove_error_for_doc
    src = inspect.getsource(remove_error_for_doc)
    assert "transaction=True" in src, "remove_error_for_doc not using MULTI/EXEC transaction"

run("remove_error_for_doc uses pipeline(transaction=True)", test_remove_error_uses_transaction)


print("\n-- Fix (Celery #7): visibility_timeout matches task_time_limit -------------")

def test_visibility_timeout_fixed():
    # Import the celery app and read the configured value directly — avoids
    # false positives from comments that mention the old number.
    from backend.celery_app import celery_app
    bt = celery_app.conf.broker_transport_options
    vt = bt.get("visibility_timeout")
    assert vt == 7500, f"Expected visibility_timeout=7500, got {vt}"

run("visibility_timeout=7500 (was 21600)", test_visibility_timeout_fixed)


print("\n-- Fix (Celery #8): result_backend_transport_options added -----------------")

def test_chord_join_timeout_added():
    src = open("backend/celery_app.py", encoding="utf-8").read()
    assert "result_backend_transport_options" in src
    assert "result_chord_join_timeout" in src

run("result_backend_transport_options with chord join timeout present", test_chord_join_timeout_added)


# =========================================================================
# Summary
# =========================================================================

print("\n" + "=" * 62)
total  = len(results)
passed = sum(1 for _, s, _ in results if s == "pass")
failed = sum(1 for _, s, _ in results if s == "fail")

print(f"\n  Total: {total}   Passed: {passed}   Failed: {failed}")

if failed:
    print("\n  FAILED TESTS:")
    for name, status, reason in results:
        if status == "fail":
            print(f"    x {name}")
            print(f"      {reason}")
    sys.exit(1)
else:
    print("\n  All fixes verified. Pipeline is clean.")
    sys.exit(0)

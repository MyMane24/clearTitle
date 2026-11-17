"""Manual chain rebuild dispatch and queue failure handling."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.routers.results import build_title_chain


class TestChainRoute(unittest.IsolatedAsyncioTestCase):
    async def test_manual_rebuild_forces_build_and_marks_running_before_dispatch(self):
        with (
            patch("backend.routers.results._enforce_access"),
            patch("backend.database.repositories.agent_repo.set_agent_status") as status,
            patch("backend.workers.title_chain_tasks.run_case_analysis_task.apply_async") as queue,
        ):
            queue.side_effect = lambda **kwargs: status.assert_called_once_with(
                case_id="CASE1", status="running"
            )
            result = await build_title_chain("CASE1", None)
        queue.assert_called_once_with(args=["CASE1"], kwargs={"force": True})
        self.assertEqual(result["status"], "queued")

    async def test_queue_failure_sets_error_and_returns_retryable_response(self):
        with (
            patch("backend.routers.results._enforce_access"),
            patch("backend.database.repositories.agent_repo.set_agent_status") as status,
            patch(
                "backend.workers.title_chain_tasks.run_case_analysis_task.apply_async",
                side_effect=RuntimeError("broker unavailable"),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await build_title_chain("CASE1", None)
        status.assert_called_with(case_id="CASE1", status="error")
        self.assertEqual(raised.exception.status_code, 503)

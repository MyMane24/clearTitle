"""Estimated model cost of a verification run, for the hard per-run cost cap.

Prices come from ``genai-prices`` (installed with Pydantic AI). Per-token rates
are taken at a small request size, so totals summed over many calls are not
priced at a large-request tier. An unknown model returns None and the cap is
not applied (logged once).
"""

from __future__ import annotations

from functools import cache

from pydantic_ai.usage import RunUsage

from backend.config import CLEARTITLE_AGENT_PROVIDER
from backend.logger import get_logger

logger = get_logger(__name__)

_PROVIDERS = {"openai": "openai", "luna": "openai", "gemini": "google"}
_PROBE = 1000


class CostLimitError(RuntimeError):
    """The run's estimated cost passed VERIFY_RUN_COST_LIMIT_USD."""


@cache
def _rates(model_name: str) -> tuple[float, float, float] | None:
    """USD per token for (input, cached input, output), or None if unknown."""
    try:
        from genai_prices import Usage, calc_price

        provider = _PROVIDERS.get((CLEARTITLE_AGENT_PROVIDER or "openai").lower(), "openai")
        model = model_name.strip().lower().replace(" ", "-")

        def price(**usage: int) -> float:
            result = calc_price(Usage(**usage), model_ref=model, provider_id=provider)
            return float(result.total_price) / _PROBE

        return (
            price(input_tokens=_PROBE),
            price(input_tokens=_PROBE, cache_read_tokens=_PROBE),
            price(output_tokens=_PROBE),
        )
    except Exception as error:
        logger.warning("no price data for model %r; cost cap not applied: %s", model_name, error)
        return None


def estimate_cost(usage: RunUsage, model_name: str) -> float | None:
    """Estimated USD cost of ``usage`` on ``model_name``, or None if prices are unknown."""
    rates = _rates(model_name)
    if rates is None:
        return None
    full, cached, output = rates
    uncached = max(0, usage.input_tokens - usage.cache_read_tokens)
    return uncached * full + usage.cache_read_tokens * cached + usage.output_tokens * output

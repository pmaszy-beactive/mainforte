"""Approximate USD cost of ai-proxy usage. The proxy meters tokens, not dollars, so we price
locally from a small table — good enough for the admin usage view, not an invoice."""
from __future__ import annotations

# model -> (USD per 1M input tokens, USD per 1M output tokens)
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
}
_DEFAULT_PRICE = (3.00, 15.00)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICES_PER_MILLION.get(model, _DEFAULT_PRICE)
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

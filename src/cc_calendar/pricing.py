"""Per-model token prices used to estimate cost when a session has no `cost-state` record.

Prices are USD per million tokens (Anthropic first-party API rates). Cache writes are
billed at 1.25x input (5-minute TTL) and cache reads at 0.1x input unless overridden.
Update this table when new models ship.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float | None = None
    context: int = 1_000_000

    @property
    def cache_write(self) -> float:
        return self.input * 1.25

    @property
    def cache_read_rate(self) -> float:
        return self.cache_read if self.cache_read is not None else self.input * 0.1


# Longest prefix wins, so more specific ids must come before their families.
PRICES: list[tuple[str, Price]] = [
    ("claude-fable-5-1", Price(10.0, 50.0, cache_read=0.25)),
    ("claude-mythos-5-1", Price(10.0, 50.0, cache_read=0.25)),
    ("claude-fable-5", Price(10.0, 50.0)),
    ("claude-mythos-5", Price(10.0, 50.0)),
    ("claude-opus-5-5", Price(4.0, 20.0, cache_read=0.20)),
    ("claude-opus-5", Price(5.0, 25.0)),
    ("claude-opus-4-8", Price(5.0, 25.0)),
    ("claude-opus-4-7", Price(5.0, 25.0)),
    ("claude-opus-4-6", Price(5.0, 25.0)),
    ("claude-opus-4-5", Price(5.0, 25.0, context=200_000)),
    ("claude-opus-4", Price(15.0, 75.0, context=200_000)),
    ("claude-sonnet-5-5", Price(2.0, 10.0, cache_read=0.20)),
    ("claude-sonnet-5", Price(2.0, 10.0)),
    ("claude-sonnet-4", Price(3.0, 15.0)),
    ("claude-haiku-4-5", Price(1.0, 5.0, context=200_000)),
    ("claude-3-5-haiku", Price(0.8, 4.0, context=200_000)),
]


def price_for(model: str | None) -> Price | None:
    if not model:
        return None
    model = model.split("[")[0]
    best: tuple[int, Price] | None = None
    for prefix, price in PRICES:
        if model.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), price)
    return best[1] if best else None


def estimate_cost(model: str | None, usage: dict) -> float:
    price = price_for(model)
    if price is None:
        return 0.0
    return (
        usage.get("input_tokens", 0) * price.input
        + usage.get("output_tokens", 0) * price.output
        + usage.get("cache_creation_input_tokens", 0) * price.cache_write
        + usage.get("cache_read_input_tokens", 0) * price.cache_read_rate
    ) / 1_000_000


def context_window(model: str | None) -> int:
    price = price_for(model)
    return price.context if price else 200_000

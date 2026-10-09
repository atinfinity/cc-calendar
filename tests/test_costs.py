import pytest
from conftest import BASE, LogBuilder, basic_session

from cc_calendar.costs import cost_breakdown
from cc_calendar.parser import DENSITY_BUCKET_MS, SessionAcc
from cc_calendar.pricing import PRICES, cost_parts, estimate_cost

T0 = int(BASE.timestamp() * 1000)
MIN = 60_000
HOUR = 60 * MIN


def feed(builder: LogBuilder) -> SessionAcc:
    s = SessionAcc(session_id=builder.sid, path="x.jsonl", project_dir="p")
    for r in builder.records:
        s.feed(r)
    return s


def session_with_subagent() -> SessionAcc:
    """Sonnet in the main session at 0:01 and 2:00, a Haiku subagent at 0:10."""
    b = LogBuilder("s-costs")
    b.prompt(0, "Do it")
    usage = {"input_tokens": 1000, "cache_creation_input_tokens": 2000}
    b.assistant(1, [], msg_id="m1", output_tokens=500, usage=usage)
    b.assistant(120, [], msg_id="m2", output_tokens=100, stop_reason="end_turn")
    s = feed(b)
    agent = LogBuilder("s-costs")
    agent.assistant(10, [], msg_id="x1", model="claude-haiku-4-5", output_tokens=40)
    for r in agent.records:
        s.feed_subagent("a1", "agent-a1.jsonl", r)
    return s


def test_cost_parts_sum_to_estimate():
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
    }
    assert cost_parts("claude-sonnet-5-5", usage) == pytest.approx((2.0, 10.0, 2.5, 0.2))
    assert sum(cost_parts("claude-sonnet-5-5", usage)) == estimate_cost("claude-sonnet-5-5", usage)
    assert cost_parts("unknown-model", usage) == (0.0, 0.0, 0.0, 0.0)


def test_session_cost_breakdown_by_bucket_and_model():
    s = session_with_subagent()
    buckets = s.cost_breakdown()
    first = T0 // DENSITY_BUCKET_MS
    assert sorted(buckets) == [first, first + 1, first + 12]
    assert buckets[first]["claude-sonnet-5-5"][:4] == [1000, 500, 2000, 1000]
    # The subagent's request counts under its own model.
    assert list(buckets[first + 1]) == ["claude-haiku-4-5"]
    total = sum(sum(row[4:]) for b in buckets.values() for row in b.values())
    assert total == pytest.approx(s.cost()[0])


def test_cost_breakdown_per_model_and_day():
    s = session_with_subagent()
    d = cost_breakdown([s], [(T0, T0 + HOUR), (T0 + HOUR, T0 + 3 * HOUR)])
    assert d["sessions"] == 1 and d["recorded"] == 0 and d["estimated"]
    assert [m["model"] for m in d["models"]] == ["claude-sonnet-5-5", "claude-haiku-4-5"]
    sonnet = d["models"][0]
    assert sonnet["tokens"] == [1100, 600, 2000, 2000]
    assert sonnet["cost"][1] == pytest.approx(600 * 10 / 1e6, abs=1e-4)
    assert d["days"][0]["tokens"] == [1100, 540, 2000, 2000]
    assert d["days"][1]["tokens"] == [100, 100, 0, 1000]
    total = sum(sum(m["cost"]) for m in d["models"])
    assert total == pytest.approx(s.cost()[0], abs=1e-3)


def test_cost_breakdown_cuts_to_the_range():
    s = session_with_subagent()
    d = cost_breakdown([s], [(T0 + HOUR, T0 + 3 * HOUR)])
    assert [m["model"] for m in d["models"]] == ["claude-sonnet-5-5"]
    d = cost_breakdown([s], [(T0 + 5 * HOUR, T0 + 6 * HOUR)])
    assert d["sessions"] == 0 and d["models"] == [] and not d["estimated"]
    assert d["days"] == [{"tokens": [0, 0, 0, 0], "cost": [0.0, 0.0, 0.0, 0.0]}]


def test_recorded_cost_is_split_by_the_estimate():
    b = basic_session()
    estimate = feed(b).cost()[0]
    b.meta("cost-state", totalCostUSD=round(estimate * 2, 6))
    d = cost_breakdown([feed(b)], [(T0, T0 + HOUR)])
    assert d["recorded"] == 1 and not d["estimated"]
    total = sum(sum(m["cost"]) for m in d["models"])
    assert total == pytest.approx(estimate * 2, abs=1e-3)


def test_usage_splits_main_thread_and_subagents():
    s = session_with_subagent()
    d = cost_breakdown([s], [(T0, T0 + HOUR), (T0 + HOUR, T0 + 3 * HOUR)])
    rows = {(u["model"], u["agent"]): u for u in d["usage"]}
    assert set(rows) == {("claude-sonnet-5-5", False), ("claude-haiku-4-5", True)}
    main = rows["claude-sonnet-5-5", False]
    assert main["tokens"] == [1100, 600, 2000, 2000]
    assert main["scaled"] == main["tokens"]  # estimated: no scaling
    assert main["cost"] == pytest.approx(sum(d["models"][0]["cost"]), abs=1e-3)
    assert sum(u["cost"] for u in d["usage"]) == pytest.approx(s.cost()[0], abs=1e-3)
    # Only the range's requests count.
    d = cost_breakdown([s], [(T0 + HOUR, T0 + 3 * HOUR)])
    assert [(u["model"], u["agent"], u["tokens"]) for u in d["usage"]] == [
        ("claude-sonnet-5-5", False, [100, 100, 0, 1000])
    ]


def test_usage_reprices_on_the_recorded_footing():
    b = basic_session()
    estimate = feed(b).cost()[0]
    b.meta("cost-state", totalCostUSD=round(estimate * 2, 6))
    d = cost_breakdown([feed(b)], [(T0, T0 + HOUR)])
    (u,) = d["usage"]
    assert u["scaled"] == pytest.approx([2 * n for n in u["tokens"]], abs=0.01)
    assert u["cost"] == pytest.approx(estimate * 2, abs=1e-3)
    # Re-pricing at the same model's rates gives back the recorded cost.
    rates = next(p["rates"] for p in d["prices"] if p["model"] == "claude-sonnet-5-5")
    repriced = sum(n * r / 1e6 for n, r in zip(u["scaled"], rates, strict=True))
    assert repriced == pytest.approx(u["cost"], abs=1e-3)


def test_prices_list_every_model_in_the_table():
    d = cost_breakdown([], [(T0, T0 + HOUR)])
    assert d["usage"] == []
    assert [p["model"] for p in d["prices"]] == [m for m, _ in PRICES]
    sonnet = next(p for p in d["prices"] if p["model"] == "claude-sonnet-5-5")
    assert sonnet["rates"] == pytest.approx([2.0, 10.0, 2.5, 0.2])

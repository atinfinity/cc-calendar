import pytest
from conftest import BASE, LogBuilder
from fastapi.testclient import TestClient

from cc_calendar.costs import cost_breakdown
from cc_calendar.parser import SessionAcc
from cc_calendar.pricing import recache_cost
from cc_calendar.server import create_app

T0 = int(BASE.timestamp() * 1000)
MIN = 60_000


def cached(read: int, write: int, ttl: str | None = "1h") -> dict:
    """Usage of a request that read `read` tokens from the cache and wrote `write` to it."""
    u = {"input_tokens": 10, "cache_read_input_tokens": read, "cache_creation_input_tokens": write}
    if ttl is not None:
        u["cache_creation"] = {
            "ephemeral_5m_input_tokens": write if ttl == "5m" else 0,
            "ephemeral_1h_input_tokens": write if ttl == "1h" else 0,
        }
    return u


def feed(b: LogBuilder, agents: dict[str, LogBuilder] | None = None) -> SessionAcc:
    s = SessionAcc(session_id=b.sid, path="x.jsonl", project_dir="p")
    for r in b.records:
        s.feed(r)
    for aid, a in (agents or {}).items():
        for r in a.records:
            s.feed_subagent(aid, f"agent-{aid}.jsonl", r)
    return s


def test_counts_only_gaps_longer_than_the_cache_lifetime():
    b = LogBuilder("s-idle")
    b.prompt(0, "Start")
    b.assistant(1, [], msg_id="m1", usage=cached(0, 50_000))
    # 40 minutes later: the 1-hour cache is still warm.
    b.assistant(41, [], msg_id="m2", usage=cached(50_000, 2_000))
    # 90 minutes later the cache has expired and the context is written again.
    b.assistant(131, [], msg_id="m3", usage=cached(5_000, 50_000))
    s = feed(b)
    # Only what the previous request had cached (52k) and was not read again (5k) counts.
    tokens = 52_000 - 5_000
    cost = recache_cost("claude-sonnet-5-5", tokens)
    assert s.idle_recaches() == [[T0 + 131 * MIN, tokens, cost]]
    assert s.idle_recache_cost() == pytest.approx(tokens * (2.5 - 0.2) / 1e6)


def test_assumes_five_minutes_without_a_cache_lifetime():
    b = LogBuilder("s-idle")
    b.prompt(0, "Start")
    b.assistant(1, [], msg_id="m1", usage=cached(0, 20_000, ttl=None))
    b.assistant(5, [], msg_id="m2", usage=cached(0, 20_000, ttl=None))  # 4 minutes: warm
    b.assistant(15, [], msg_id="m3", usage=cached(0, 30_000, ttl=None))
    s = feed(b)
    assert [r[1] for r in s.idle_recaches()] == [20_000]


def test_a_warm_cache_after_a_gap_costs_nothing():
    b = LogBuilder("s-idle")
    b.prompt(0, "Start")
    b.assistant(1, [], msg_id="m1", usage=cached(0, 20_000, ttl="5m"))
    # Longer than 5 minutes, yet the cache was read: nothing was rewritten.
    b.assistant(8, [], msg_id="m2", usage=cached(20_000, 500, ttl="5m"))
    assert feed(b).idle_recaches() == []


def test_threads_are_measured_on_their_own():
    b = LogBuilder("s-idle")
    b.prompt(0, "Start")
    b.assistant(1, [], msg_id="m1", usage=cached(0, 40_000))
    b.assistant(70, [], msg_id="m2", usage=cached(0, 40_000))  # 69 minutes after m1
    # A subagent writes a 5-minute cache and waits 10 minutes between two requests. Its
    # requests between m1 and m2 do not shorten the main thread's gap.
    a = LogBuilder("s-idle")
    a.assistant(2, [], msg_id="x1", usage=cached(0, 8_000, ttl="5m"))
    a.assistant(12, [], msg_id="x2", usage=cached(0, 9_000, ttl="5m"))
    a.assistant(14, [], msg_id="x3", usage=cached(9_000, 1_000, ttl="5m"))
    s = feed(b, {"a1": a})
    assert [(r[0], r[1]) for r in s.idle_recaches()] == [
        (T0 + 12 * MIN, 8_000),
        (T0 + 70 * MIN, 40_000),
    ]


def test_compactions_and_model_switches_are_left_out():
    b = LogBuilder("s-idle")
    b.prompt(0, "Start")
    b.assistant(1, [], msg_id="m1", usage=cached(0, 40_000, ttl="5m"))
    b._base("system", 20, subtype="compact_boundary")
    b.assistant(21, [], msg_id="m2", usage=cached(0, 6_000, ttl="5m"))
    b.assistant(40, [], msg_id="m3", model="claude-opus-4-7", usage=cached(0, 7_000, ttl="5m"))
    assert feed(b).idle_recaches() == []


def test_cost_breakdown_adds_up_idle_recaches_in_range():
    b = LogBuilder("s-idle")
    b.prompt(0, "Start")
    b.assistant(1, [], msg_id="m1", usage=cached(0, 10_000, ttl="5m"))
    b.assistant(20, [], msg_id="m2", usage=cached(0, 10_000, ttl="5m"))
    b.assistant(40, [], msg_id="m3", usage=cached(0, 10_000, ttl="5m"))
    s = feed(b)
    d = cost_breakdown([s], [(T0, T0 + 30 * MIN)])
    assert d["idle_recache"] == {
        "cost": round(recache_cost("claude-sonnet-5-5", 10_000), 4),
        "tokens": 10_000,
        "requests": 1,
        "sessions": 1,
    }
    d = cost_breakdown([s], [(T0, T0 + 30 * MIN), (T0 + 30 * MIN, T0 + 60 * MIN)])
    assert d["idle_recache"]["requests"] == 2
    d = cost_breakdown([s], [(T0 + 60 * MIN, T0 + 90 * MIN)])
    assert d["idle_recache"] == {"cost": 0.0, "tokens": 0, "requests": 0, "sessions": 0}


def test_api_reports_idle_recache(claude_dir):
    with TestClient(create_app(claude_dir, watch=False), base_url="http://127.0.0.1") as c:
        sessions = c.get("/api/sessions").json()["sessions"]
        assert all(s["idle_recache"] == 0 for s in sessions)
        d = c.get("/api/sessions/s-basic").json()
        assert d["idle_recache_requests"] == 0 and d["idle_recache_tokens"] == 0

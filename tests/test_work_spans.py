"""Working vs waiting time per session (SessionAcc.work_spans / work_stats)."""

from conftest import BASE, LogBuilder, continuation
from fastapi.testclient import TestClient

from cc_calendar.parser import SessionAcc, clip_spans
from cc_calendar.server import create_app

T0 = int(BASE.timestamp() * 1000)
MIN = 60_000
GAP = 15 * MIN


def m(minute: float) -> int:
    return T0 + round(minute * MIN)


def feed(builder: LogBuilder) -> SessionAcc:
    s = SessionAcc(session_id=builder.sid, path="x.jsonl", project_dir="p")
    for r in builder.records:
        s.feed(r)
    return s


def reply(b: LogBuilder, minute: float, msg_id: str) -> None:
    b.assistant(minute, [{"type": "text", "text": "ok"}], msg_id=msg_id, stop_reason="end_turn")


def test_working_and_waiting():
    b = LogBuilder("s")
    b.prompt(0, "first")
    reply(b, 4, "m1")
    b.turn_end(5, duration=5)
    b.prompt(7, "second")  # you took 2 minutes to reply
    reply(b, 9, "m2")
    b.turn_end(10, duration=3)
    b.prompt(14, "third")  # 4 minutes
    reply(b, 15, "m3")
    b.turn_end(15, duration=1)
    st = feed(b).work_stats(GAP)
    assert st["working"] == [[m(0), m(5)], [m(7), m(10)], [m(14), m(15)]]
    assert st["waiting"] == [[m(5), m(7)], [m(10), m(14)]]
    assert st["working_ms"] == 9 * MIN
    assert st["waiting_ms"] == 6 * MIN
    assert st["reply_median_ms"] == 3 * MIN


def test_long_waits_are_not_waiting():
    # Past the idle threshold you were away, as the active time splits there too.
    b = LogBuilder("s")
    b.prompt(0, "first")
    reply(b, 1, "m1")
    b.turn_end(1, duration=1)
    b.prompt(40, "back")
    reply(b, 41, "m2")
    b.turn_end(41, duration=1)
    s = feed(b)
    assert s.work_stats(GAP)["waiting"] == []
    assert s.work_stats(GAP)["reply_median_ms"] is None
    assert s.work_stats(60 * MIN)["waiting"] == [[m(1), m(40)]]


def test_interrupted_and_unfinished_turns():
    b = LogBuilder("s")
    b.prompt(0, "go")
    b.tool_use(1, "t1", "Bash", {"command": "sleep 100"}, msg_id="m1")
    b.interrupt(3)  # no turn_duration: the turn ends at the interrupt
    b.prompt(4, "try again")
    b.assistant(6, [{"type": "text", "text": "working"}], msg_id="m2")
    # Still running (or the process died): the turn counts up to its latest record.
    st = feed(b).work_stats(GAP)
    assert st["working"] == [[m(0), m(3)], [m(4), m(6)]]
    assert st["waiting"] == [[m(3), m(4)]]


def test_local_command_without_turn_end():
    # /model writes no turn_duration and gets no reply; it still answers Claude's last turn.
    b = LogBuilder("s")
    b.prompt(0, "go")
    reply(b, 1, "m1")
    b.turn_end(1, duration=1)
    b.command(3, "/model", "opus")
    b.prompt(5, "now with opus")
    reply(b, 6, "m2")
    b.turn_end(6, duration=1)
    st = feed(b).work_stats(GAP)
    assert st["working"] == [[m(0), m(1)], [m(5), m(6)]]
    assert st["waiting"] == [[m(1), m(3)], [m(3), m(5)]]


def test_turn_start_from_duration():
    # A prompt queued mid-turn starts the next turn without a prompt record: durationMs tells
    # when it started, and the gap before it is not a wait for you.
    b = LogBuilder("s")
    b.prompt(0, "go")
    reply(b, 2, "m1")
    b.turn_end(2, duration=2)
    reply(b, 5, "m2")
    b.turn_end(5, duration=2)
    st = feed(b).work_stats(GAP)
    assert st["working"] == [[m(0), m(2)], [m(3), m(5)]]
    assert st["waiting"] == []


def test_turn_end_without_duration_uses_its_prompt():
    b = LogBuilder("s")
    b.prompt(0, "go")
    reply(b, 2, "m1")
    b.turn_end(2)
    assert feed(b).work_stats(GAP)["working"] == [[m(0), m(2)]]


def test_background_task_gap_is_working():
    b = LogBuilder("s")
    b.prompt(0, "start a background agent")
    reply(b, 1, "m1")
    b.turn_end(1, pending_background=1, duration=1)
    b.notification(6, "bg1")  # the agent finished; Claude picks its result up
    reply(b, 7, "m2")
    b.turn_end(7, duration=1)
    b.prompt(9, "thanks")
    reply(b, 10, "m3")
    b.turn_end(10, duration=1)
    st = feed(b).work_stats(GAP)
    assert st["working"] == [[m(0), m(7)], [m(9), m(10)]]
    assert st["waiting"] == [[m(7), m(9)]]


def test_working_is_cut_to_active_segments():
    # A tool call that runs 40 minutes without a record is not active time, nor working time.
    b = LogBuilder("s")
    b.prompt(0, "run the long job")
    b.tool_use(1, "t1", "Bash", {"command": "make all"}, msg_id="m1")
    b.tool_result(40, "t1", "done")
    reply(b, 41, "m2")
    b.turn_end(41, duration=41)
    s = feed(b)
    assert s.work_stats(GAP)["working"] == [[m(0), m(1)], [m(40), m(41)]]
    assert s.work_stats(60 * MIN)["working"] == [[m(0), m(41)]]


def test_sidechain_records_do_not_start_turns():
    b = LogBuilder("s")
    b.prompt(0, "go")
    reply(b, 1, "m1")
    b.turn_end(1, duration=1)
    side = b.prompt(2, "subagent prompt")
    side["isSidechain"] = True
    b.prompt(3, "next")
    reply(b, 4, "m2")
    b.turn_end(4, duration=1)
    assert feed(b).work_stats(GAP)["waiting"] == [[m(1), m(3)]]


def test_continuation_head_is_not_counted():
    prev = LogBuilder("s-old")
    prev.prompt(0, "first")
    reply(prev, 1, "o1")
    prev.turn_end(2, duration=2)
    nxt = continuation(prev, "s-new")
    nxt.prompt(7, "carry on")  # 5 minutes after the copied turn, which is not this session's
    reply(nxt, 8, "n1")
    nxt.turn_end(8, duration=1)
    st = feed(nxt).work_stats(GAP)
    assert st["working"] == [[m(7), m(8)]]
    assert st["waiting"] == []


def test_clip_spans():
    segs = [[0, 10], [20, 30]]
    assert clip_spans([[5, 25]], segs) == [[5, 10], [20, 25]]
    assert clip_spans([[0, 5], [5, 8], [12, 15]], segs) == [[0, 8]]
    assert clip_spans([[31, 40]], segs) == []


def test_summary_payload(claude_dir):
    with TestClient(create_app(claude_dir, watch=False), base_url="http://127.0.0.1") as client:
        items = {s["id"]: s for s in client.get("/api/sessions").json()["sessions"]}
    basic = items["s-basic"]
    assert basic["working"] == [[m(0), m(5)]]
    assert basic["working_ms"] == 5 * MIN
    assert basic["waiting"] == [] and basic["waiting_ms"] == 0
    assert basic["reply_median_ms"] is None
    # s-next starts with a copy of s-prev under s-prev's ID; only its own turn counts.
    assert items["s-next"]["working"] == [[m(200), m(201)]]
    # s-prev was interrupted mid-turn.
    assert items["s-prev"]["working"] == [[m(120), m(122)]]

"""Write a fictional ~/.claude directory for demos and README screenshots.

    uv run python scripts/demo_data.py /tmp/cc-demo
    uv run cc-calendar --claude-dir /tmp/cc-demo

Every project, prompt and file name here is made up. The week shown is
Mon 28 Sep - Sun 4 Oct 2026 (UTC); see NOW for the moment it is captured at.
"""

from __future__ import annotations

import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cc_calendar.pricing import estimate_cost

WEEK = datetime(2026, 9, 28, tzinfo=UTC)
NOW = datetime(2026, 10, 2, 15, 25, tzinfo=UTC)  # Friday afternoon


def session_id(i: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cc-calendar-demo/{i}"))


RUNNING_SESSION = session_id(14)

PROJECTS = {
    "acme-web": ["src/app/page.tsx", "src/components/Cart.tsx", "src/lib/api.ts", "src/styles.css"],
    "data-pipeline": ["pipeline/ingest.py", "pipeline/transform.py", "tests/test_ingest.py"],
    "cli-tool": ["src/main.rs", "src/config.rs", "src/commands/sync.rs", "Cargo.toml"],
    "infra": ["terraform/main.tf", "terraform/variables.tf", ".github/workflows/deploy.yml"],
    "docs-site": ["docs/getting-started.md", "docs/api.md", "mkdocs.yml"],
}
TEST_COMMANDS = {
    "acme-web": "npm test",
    "data-pipeline": "uv run pytest -q",
    "cli-tool": "cargo test",
    "infra": "terraform plan",
    "docs-site": "mkdocs build --strict",
}

# day, start (HH:MM), project, title, prompts, model, extras
SESSIONS = [
    (
        0,
        "09:10",
        "acme-web",
        "Fix cart total rounding",
        [
            "The cart total is off by a cent for some discounts. Find out why and fix it.",
            "Add a regression test for the 3-for-2 case too.",
        ],
        "opus",
        {"commit": ["Fix rounding in cart totals"]},
    ),
    (
        0,
        "10:40",
        "data-pipeline",
        "Speed up nightly ingest",
        [
            "Profile pipeline/ingest.py, the nightly job takes 40 minutes now.",
            "Batch the inserts as you suggested.",
            "Run the full test suite.",
        ],
        "opus",
        {"commit": ["Batch inserts in ingest"], "agent": "Profile the ingest job"},
    ),
    (
        0,
        "14:05",
        "docs-site",
        "Document the sync command",
        ["Write a docs page for `cli-tool sync` based on the source."],
        "sonnet",
        {"commit": ["Add sync command docs"]},
    ),
    (
        0,
        "15:30",
        "cli-tool",
        "Add --dry-run to sync",
        [
            "Add a --dry-run flag to the sync command.",
            "Print a summary table at the end.",
            "Make the table respect NO_COLOR.",
        ],
        "opus",
        {"commit": ["Add --dry-run to sync"], "lunch": 1},
    ),
    (
        1,
        "08:50",
        "infra",
        "Move staging to the new VPC",
        [
            "Plan the move of staging to vpc-new. Don't apply anything.",
            "Looks good, update the workflow so staging deploys use it.",
        ],
        "opus",
        {"commit": ["Point staging at the new VPC"], "pr": 42},
    ),
    (
        1,
        "11:15",
        "acme-web",
        "Checkout page redesign",
        [
            "Implement the new checkout layout from the spec in docs/checkout.md.",
            "Use the existing Button component.",
            "Mobile layout is broken below 400px.",
            "Now the summary card overlaps the footer.",
        ],
        "opus",
        {
            "commit": ["New checkout layout", "Fix checkout on narrow screens"],
            "lunch": 2,
            "agent": "Find layout components",
            "error": 1,
            "compact": 3,
        },
    ),
    (
        1,
        "16:20",
        "data-pipeline",
        "Investigate flaky test",
        ["test_ingest_retries fails about once in ten runs. Why?"],
        "sonnet",
        {"interrupt": True},
    ),
    (
        2,
        "09:30",
        "cli-tool",
        "Config file migration",
        [
            "Config v1 files should be migrated to v2 on load, with a backup.",
            "Add tests for a v1 file with comments.",
        ],
        "opus",
        {"commit": ["Migrate v1 config files on load"]},
    ),
    (
        2,
        "13:10",
        "acme-web",
        "Upgrade to the new router",
        [
            "Upgrade the app to the new router API. Start with the product pages.",
            "Continue with account pages.",
            "And the remaining pages.",
            "Run the e2e tests.",
        ],
        "opus",
        {
            "commit": ["Migrate product pages to new router", "Migrate remaining pages"],
            "agent": "List pages using the old router",
            "pr": 118,
        },
    ),
    (
        3,
        "10:00",
        "docs-site",
        "Fix broken links",
        ["mkdocs reports broken links, fix them all."],
        "haiku",
        {"commit": ["Fix broken links"]},
    ),
    (
        3,
        "10:45",
        "data-pipeline",
        "Add schema validation",
        [
            "Validate incoming records against schemas/record.json"
            " and route bad rows to a dead-letter table.",
            "Count the rejected rows in the job summary.",
        ],
        "opus",
        {"commit": ["Validate records against schema"], "lunch": 1},
    ),
    (
        3,
        "15:00",
        "infra",
        "Rotate CI credentials",
        ["Update the deploy workflow to use OIDC instead of the long-lived key."],
        "sonnet",
        {"commit": ["Use OIDC in deploy workflow"]},
    ),
    (
        4,
        "09:05",
        "cli-tool",
        "Release 1.4.0",
        ["Prepare the 1.4.0 release: changelog, version bump.", "Tag it."],
        "sonnet",
        {"commit": ["Release 1.4.0"]},
    ),
    (
        4,
        "13:30",
        "acme-web",
        "Product search with filters",
        [
            "Add filters for price and brand to product search.",
            "Persist the filters in the URL.",
            "Debounce the search input.",
            "Add loading skeletons.",
        ],
        "opus",
        {"commit": ["Add search filters", "Keep filters in the URL"], "agent": "Review search API"},
    ),
    # Runs alongside "Upgrade to the new router", so the two share Wednesday afternoon.
    (
        2,
        "13:50",
        "infra",
        "Review Terraform drift",
        ["Compare terraform state with what is deployed and list the drift."],
        "sonnet",
        {},
    ),
]
MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-4-5"}


class Writer:
    def __init__(self, sid: str, cwd: str, branch: str, rng: random.Random):
        self.sid, self.cwd, self.branch, self.rng = sid, cwd, branch, rng
        self.records: list[dict] = []
        self.n = 0
        self.context = 18_000

    def rec(self, rtype: str, t: datetime, **extra) -> dict:
        self.n += 1
        r = {
            "type": rtype,
            "uuid": f"{self.sid}-{self.n}",
            "sessionId": self.sid,
            "timestamp": t.isoformat().replace("+00:00", "Z"),
            "cwd": self.cwd,
            "gitBranch": self.branch,
            "version": "2.1.0",
            **extra,
        }
        self.records.append(r)
        return r

    def prompt(self, t: datetime, text: str) -> None:
        self.rec("user", t, origin={"kind": "human"}, message={"role": "user", "content": text})

    def assistant(self, t: datetime, blocks: list[dict], model: str, stop: str) -> dict:
        self.context += self.rng.randint(1_500, 7_000)
        usage = {
            "input_tokens": self.rng.randint(2, 40),
            "output_tokens": self.rng.randint(80, 2_400),
            "cache_read_input_tokens": self.context,
            "cache_creation_input_tokens": self.rng.randint(800, 6_000),
        }
        msg = {
            "id": f"msg-{self.sid}-{self.n}",
            "role": "assistant",
            "model": model,
            "content": blocks,
            "stop_reason": stop,
            "usage": usage,
        }
        self.rec("assistant", t, message=msg)
        return usage

    def tool(
        self, t: datetime, model: str, name: str, inp: dict, output: str, tur: dict | None = None
    ):
        tid = f"tool-{self.sid}-{self.n}"
        usage = self.assistant(
            t, [{"type": "tool_use", "id": tid, "name": name, "input": inp}], model, "tool_use"
        )
        self.rec(
            "user",
            t + timedelta(seconds=self.rng.randint(2, 40)),
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": output,
                        "is_error": False,
                    }
                ],
            },
            toolUseResult=tur or {"stdout": output},
        )
        return tid, usage

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in self.records))


def build_session(i: int, spec: tuple, root: Path, rng: random.Random) -> None:
    day, start, project, title, prompts, model_key, extras = spec
    sid = session_id(i)
    cwd = f"/home/dev/{project}"
    proj_dir = root / "projects" / cwd.replace("/", "-")
    model = MODELS[model_key]
    w = Writer(sid, cwd, "main", rng)
    files = PROJECTS[project]
    hh, mm = map(int, start.split(":"))
    t = WEEK + timedelta(days=day, hours=hh, minutes=mm)
    running = sid == RUNNING_SESSION
    usages: list[tuple[str, dict]] = []
    commits = list(extras.get("commit", []))
    added = removed = 0

    for p_idx, text in enumerate(prompts):
        if p_idx and extras.get("lunch") == p_idx:
            t += timedelta(minutes=rng.randint(55, 80))  # a break splits the bar
        if p_idx and extras.get("compact") == p_idx:
            w.rec("system", t, subtype="compact_boundary")
            t += timedelta(seconds=30)
        w.prompt(t, text)
        steps = rng.randint(5, 14)
        for s in range(steps):
            t += timedelta(seconds=rng.randint(30, 200))
            kind = rng.choices(["Read", "Grep", "Edit", "Bash", "Write"], [5, 2, 5, 3, 1])[0]
            f = rng.choice(files)
            if kind == "Read":
                inp, out = {"file_path": f"{cwd}/{f}"}, "…"
            elif kind == "Grep":
                inp, out = {"pattern": rng.choice(["TODO", "def ", "export ", "fn "])}, f"{f}:12"
            elif kind == "Bash":
                inp, out = {"command": TEST_COMMANDS[project], "description": "Run tests"}, "ok"
            else:
                inp, out = {"file_path": f"{cwd}/{f}", "old_string": "a", "new_string": "b"}, "ok"
                added += rng.randint(3, 60)
                removed += rng.randint(0, 25)
            _, u = w.tool(t, model, kind, inp, out)
            usages.append((model, u))
            if s == 2 and extras.get("error") == p_idx:
                w.rec(
                    "assistant",
                    t,
                    isApiErrorMessage=True,
                    message={
                        "role": "assistant",
                        "model": "<synthetic>",
                        "content": [{"type": "text", "text": "API Error: 529 Overloaded"}],
                    },
                )
            if p_idx == 0 and s == 1 and extras.get("agent"):
                usages += subagent(w, t, model, extras["agent"], proj_dir, rng)
        if commits and (p_idx == len(prompts) - 1 or rng.random() < 0.5):
            subject = commits.pop(0)
            sha = f"{rng.getrandbits(28):07x}"
            t += timedelta(seconds=40)
            _, u = w.tool(
                t,
                model,
                "Bash",
                {"command": f'git commit -am "{subject}"'},
                f"[main {sha}] {subject}\n 3 files changed",
            )
            usages.append((model, u))
        if p_idx == len(prompts) - 1 and extras.get("pr"):
            n = extras["pr"]
            w.records.append(
                {
                    "type": "pr-link",
                    "sessionId": sid,
                    "prNumber": n,
                    "prUrl": f"https://github.com/example/{project}/pull/{n}",
                    "prRepository": f"example/{project}",
                }
            )
        t += timedelta(seconds=rng.randint(20, 90))
        if extras.get("interrupt") and p_idx == len(prompts) - 1:
            w.rec(
                "user",
                t,
                message={
                    "role": "user",
                    "content": [{"type": "text", "text": "[Request interrupted by user]"}],
                },
            )
            break
        if running and p_idx == len(prompts) - 1:
            break  # still working on the last request
        u = w.assistant(t, [{"type": "text", "text": "Done."}], model, "end_turn")
        usages.append((model, u))
        w.rec("system", t, subtype="turn_duration", pendingBackgroundAgentCount=0)
        t += timedelta(minutes=rng.randint(3, 15))

    w.records.append({"type": "ai-title", "sessionId": sid, "aiTitle": title})
    if not running and not extras.get("interrupt"):
        cost = sum(estimate_cost(m, u) for m, u in usages)
        w.records.append(
            {
                "type": "cost-state",
                "sessionId": sid,
                "totalCostUSD": round(cost, 4),
                "totalLinesAdded": added,
                "totalLinesRemoved": removed,
            }
        )
    w.write(proj_dir / f"{sid}.jsonl")


def subagent(
    w: Writer, t: datetime, parent_model: str, description: str, proj_dir: Path, rng: random.Random
):
    """An Explore subagent launched from the main transcript."""
    aid = f"a{w.sid[:8]}{w.n:04d}"
    model = MODELS["haiku"]
    sub = Writer(w.sid, w.cwd, w.branch, rng)
    sub.n = 10_000
    st = t
    usages = []
    for _ in range(rng.randint(4, 9)):
        st += timedelta(seconds=rng.randint(10, 50))
        _, u = sub.tool(st, model, rng.choice(["Read", "Grep", "Glob"]), {"pattern": "*"}, "…")
        usages.append((model, u))
    usages.append(
        (model, sub.assistant(st, [{"type": "text", "text": "Summary"}], model, "end_turn"))
    )
    for r in sub.records:
        r["isSidechain"] = True
    sub.write(proj_dir / w.sid / "subagents" / f"agent-{aid}.jsonl")
    tid, u = w.tool(
        t,
        parent_model,
        "Agent",
        {"description": description, "subagent_type": "Explore", "prompt": description},
        "Summary",
        {"agentId": aid, "status": "completed", "resolvedModel": model},
    )
    (proj_dir / w.sid / "subagents" / f"agent-{aid}.meta.json").write_text(
        json.dumps({"agentType": "Explore", "description": description, "toolUseId": tid})
    )
    return usages + [(parent_model, u)]


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "cc-demo")
    if (root / "projects").exists():
        sys.exit(f"{root} already has a projects/ directory; pick an empty path")
    rng = random.Random(7)
    for i, spec in enumerate(SESSIONS, 1):
        build_session(i, spec, root, rng)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    print(f"wrote {len(SESSIONS)} sessions to {root}")


if __name__ == "__main__":
    main()

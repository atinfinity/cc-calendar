"""FastAPI app: JSON API, server-sent events, and the static frontend."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from watchfiles import awatch

from . import __version__, gitinfo
from .logview import build_entries
from .parser import SessionAcc
from .store import Store

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
SEARCH_TEXT_LIMIT = 4000
# Always revalidate: without this, browsers cache ES modules heuristically and keep
# running stale code after an upgrade.
NO_CACHE = {"Cache-Control": "no-cache"}


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response


def project_name(s: SessionAcc) -> str:
    if s.cwd:
        return Path(s.cwd).name or s.cwd
    return s.project_dir.lstrip("-").rsplit("-", 1)[-1]


def summary(s: SessionAcc, live: dict | None, gap_ms: int, continued_from: str | None) -> dict:
    status, _ = s.state(live)
    cost, estimated = s.cost()
    models = s.models()
    search = " ".join([s.title(), *(p["text"][:300] for p in s.prompts)])[:SEARCH_TEXT_LIMIT]
    return {
        "id": s.session_id,
        "title": s.title(),
        "project": s.cwd or s.project_dir,
        "project_name": project_name(s),
        "branch": s.git_branch,
        "status": status,
        "start": s.start,
        "end": s.end,
        "segments": s.segments(gap_ms),
        "density": s.density(),
        "prompt_count": len(s.prompts),
        "tokens": s.tokens(),
        "cost": round(cost, 4),
        "cost_estimated": estimated,
        "model": models[0] if models else None,
        "continued_in": s.continued_in,
        "continued_from": continued_from,
        "search": search,
    }


def detail(s: SessionAcc, live: dict | None, gap_ms: int, continued_from: str | None) -> dict:
    out = summary(s, live, gap_ms, continued_from)
    _, checks = s.state(live)
    commits = gitinfo.resolve_commits(s.commits)
    checks["committed"] = gitinfo.working_tree_clean(s.cwd)
    prompts = [dict(p, commits=[]) for p in s.prompts]
    for c in commits:
        owner = None
        for p in prompts:
            if p["ts"] is not None and c.get("ts") is not None and p["ts"] <= c["ts"]:
                owner = p
        if owner is not None:
            owner["commits"].append(c.get("sha") or c.get("subject"))
    out.update(
        {
            "cwd": s.cwd,
            "models": s.models(),
            "permission_mode": s.permission_mode,
            "context_pct": s.context_pct(),
            "checks": checks,
            "prompts": prompts,
            "commits": commits,
            "files": [{"path": p, "count": n} for p, n in s.files.most_common()],
            "prs": list(s.prs.values()),
            "subagents": sorted(
                (sa.to_dict() for sa in s.subagents.values()), key=lambda d: d["start"] or 0
            ),
            "background": list(s.background.values()),
            "cost_state": {
                k: s.cost_state.get(k)
                for k in ("totalDuration", "totalLinesAdded", "totalLinesRemoved", "modelUsage")
            }
            if s.cost_state
            else None,
            "version": s.version,
        }
    )
    return out


class Broadcaster:
    def __init__(self) -> None:
        self.queues: set[asyncio.Queue] = set()

    def publish(self, payload: dict) -> None:
        for q in list(self.queues):
            q.put_nowait(payload)


def create_app(claude_dir: Path, watch: bool = True) -> FastAPI:
    store = Store(claude_dir)
    broadcaster = Broadcaster()

    async def watcher() -> None:
        targets = [str(p) for p in (store.projects_dir, store.sessions_dir) if p.is_dir()]
        if not targets:
            return
        async for changes in awatch(*targets, recursive=True):
            changed: set[str] = set()
            live_changed = False
            for _, raw in changes:
                path = Path(raw)
                if path.parent == store.sessions_dir:
                    live_changed = True
                    continue
                if path.suffix == ".jsonl" or path.name.endswith(".meta.json"):
                    sid = await asyncio.to_thread(store.update_file, path)
                    if sid:
                        changed.add(sid)
            if changed or live_changed:
                broadcaster.publish({"sessions": sorted(changed), "live": live_changed})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(store.scan)
        task = asyncio.create_task(watcher()) if watch else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="cc-calendar", version=__version__, lifespan=lifespan)
    app.state.store = store

    def get_session(sid: str) -> SessionAcc:
        s = store.sessions.get(sid)
        if s is None:
            raise HTTPException(404, "session not found")
        return s

    @app.get("/api/sessions")
    def list_sessions(gap: int = Query(15, ge=1, le=24 * 60)) -> dict:
        live = store.live_sessions()
        cont = store.continued_from()
        with store.lock:
            items = [
                summary(s, live.get(s.session_id), gap * 60_000, cont.get(s.session_id))
                for s in store.sessions.values()
                if s.start is not None
            ]
        return {"sessions": items, "claude_dir": str(claude_dir)}

    @app.get("/api/sessions/{sid}")
    def session_detail(sid: str, gap: int = Query(15, ge=1, le=24 * 60)) -> dict:
        live = store.live_sessions()
        with store.lock:
            s = get_session(sid)
            return detail(s, live.get(sid), gap * 60_000, store.continued_from().get(sid))

    @app.get("/api/sessions/{sid}/log")
    def session_log(
        sid: str,
        agent: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(300, ge=1, le=2000),
    ) -> dict:
        s = get_session(sid)
        if agent:
            sa = s.subagents.get(agent)
            if sa is None or sa.path is None:
                raise HTTPException(404, "subagent log not found")
            path, filter_sid = Path(sa.path), None
        else:
            path, filter_sid = Path(s.path), sid
        try:
            entries = build_entries(path, filter_sid)
        except OSError as e:
            raise HTTPException(404, "log file not readable") from e
        return {
            "total": len(entries),
            "offset": offset,
            "entries": entries[offset : offset + limit],
        }

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        queue: asyncio.Queue = asyncio.Queue()
        broadcaster.queues.add(queue)

        async def stream():
            try:
                yield "retry: 3000\n\n"
                while not await request.is_disconnected():
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(payload)}\n\n"
            finally:
                broadcaster.queues.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers=NO_CACHE)

    app.mount("/static", NoCacheStaticFiles(directory=STATIC), name="static")
    return app

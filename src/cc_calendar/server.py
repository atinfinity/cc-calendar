"""FastAPI app: JSON API, server-sent events, and the static frontend."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
import threading
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from watchfiles import awatch

from . import __version__, gitinfo, update
from .costs import cost_breakdown
from .expensive import expensive_requests
from .logview import build_entries, find_entries, log_events
from .notes import NOTE_LIMIT, TAGS_PER_SESSION, Notes, NotesUnavailable
from .parser import SessionAcc
from .prcosts import Attribution, pr_costs
from .search import MIN_QUERY, SearchIndex, snippet
from .stats import log_stats
from .store import ClaudeDir, Store
from .tools import tool_usage

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
SEARCH_TEXT_LIMIT = 4000
QUERY_LIMIT = 500
# Always revalidate: without this, browsers cache ES modules heuristically and keep
# running stale code after an upgrade.
NO_CACHE = {"Cache-Control": "no-cache"}
# Reject requests whose Host is not loopback: a page on another site could otherwise
# rebind its domain to 127.0.0.1 (DNS rebinding) and read transcripts through the browser.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
# Transcripts can hold HTML and Markdown that point anywhere (`![](https://…)`, a style with
# url(…)). Let the browser load nothing from other origins, so viewing a log never contacts
# another host.
CSP = "; ".join(
    [
        "default-src 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
        "frame-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
)


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response


def project_name(s: SessionAcc) -> str:
    if s.cwd:
        return Path(s.cwd).name or s.cwd
    return s.project_dir.lstrip("-").rsplit("-", 1)[-1]


def summary(
    s: SessionAcc, live: dict | None, gap_ms: int, continued_from: str | None, notes: Notes
) -> dict:
    status, _ = s.state(live)
    cost, estimated = s.cost()
    models = s.models()
    cache_hit, cache_saved = s.cache_stats()
    search = " ".join([s.title(), *(p["text"][:300] for p in s.prompts)])[:SEARCH_TEXT_LIMIT]
    return {
        "id": s.session_id,
        "title": s.title(),
        "project": s.cwd or s.project_dir,
        "project_name": project_name(s),
        "source": s.source,
        "branch": s.git_branch,
        "status": status,
        "start": s.start,
        "end": s.end,
        "segments": s.segments(gap_ms),
        # working, waiting (spans), working_ms, waiting_ms, reply_median_ms
        **s.work_stats(gap_ms),
        "density": s.density(),
        "cost_density": s.cost_density(),
        "marks": s.marks(),
        "prompt_count": len(s.prompts),
        "tokens": s.tokens(),
        "cost": round(cost, 4),
        "cost_estimated": estimated,
        "cost_basis": s.cost_basis(),
        "cache_hit": cache_hit,
        "cache_saved": round(cache_saved, 4),
        "idle_recache": round(s.idle_recache_cost(), 4),  # estimate, see SessionAcc.idle_recaches
        **s.context_stats(),  # context_avg, context_peak, context_over, context_bloated
        "model": models[0] if models else None,
        "effort": s.effort(),
        "version": s.version,  # Claude Code version
        "commit_list": [
            {"ts": c.get("ts"), "sha": c.get("sha"), "subject": c.get("subject")}
            for c in gitinfo.resolve_commits(s.commits)
        ],
        "pr_list": [{"number": pr.get("number"), "url": pr["url"]} for pr in s.prs.values()],
        "files_changed": len(s.files),
        **s.lines_changed(),
        "friction": s.friction(),
        "repo_url": gitinfo.repo_url(s.cwd),
        "continued_in": s.continued_in,
        "continued_from": continued_from,
        "search": search,
        **notes.get(s.session_id),  # note, tags, rating
    }


def detail(
    s: SessionAcc, live: dict | None, gap_ms: int, continued_from: str | None, notes: Notes
) -> dict:
    out = summary(s, live, gap_ms, continued_from, notes)
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
    recaches = s.idle_recaches()
    out.update(
        {
            "cwd": s.cwd,
            "models": s.models(),
            "efforts": s.effort_mix(),
            "compactions": s.compactions,
            "permission_mode": s.permission_mode,
            "context_pct": s.context_pct(),
            "idle_recache_requests": len(recaches),
            "idle_recache_tokens": sum(n for _, n, _ in recaches),
            "context": s.context_chart(),
            "checks": checks,
            "prompts": prompts,
            "commits": commits,
            "files": [{"path": p, "count": n} for p, n in s.files.most_common()],
            "prs": list(s.prs.values()),
            "subagents": sorted(
                (sa.to_dict() for sa in s.subagents.values()), key=lambda d: d["start"] or 0
            ),
            "background": list(s.background.values()),
            # A continuation's own share: its record carries over its predecessor's totals.
            "cost_state": {
                k: own.get(k) for k in ("totalDuration", "totalLinesAdded", "totalLinesRemoved")
            }
            if (own := s.own_cost_state())
            else None,
        }
    )
    return out


class ToolsQuery(BaseModel):
    start: int
    end: int
    sessions: list[str] = Field(max_length=100_000)


class CostsQuery(BaseModel):
    bounds: list[tuple[int, int]] = Field(min_length=1, max_length=400)  # [start, end) per day
    sessions: list[str] = Field(max_length=100_000)


class RequestsQuery(ToolsQuery):
    limit: int = Field(50, ge=1, le=500)


class PrsQuery(BaseModel):
    sessions: list[str] = Field(max_length=100_000)
    gap: int = Field(15, ge=1, le=24 * 60)  # minutes, as for /api/sessions


class NotesUpdate(BaseModel):
    note: str = Field("", max_length=NOTE_LIMIT * 2)  # checked exactly after trimming
    tags: list[str] = Field(default_factory=list, max_length=TAGS_PER_SESSION * 5)
    # One of notes.RATINGS, "" to clear it, or left out to keep it.
    rating: str | None = Field(None, max_length=20)


def same_origin_json(request: Request) -> None:
    """Guard for writes: a page on another site must not be able to change notes.

    Requiring a JSON body makes browsers send a CORS preflight, which this server never
    answers with permission; an Origin other than this server is refused outright.
    """
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "expected application/json")
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).hostname not in ALLOWED_HOSTS):
        raise HTTPException(403, "cross-origin request refused")


class Broadcaster:
    def __init__(self) -> None:
        self.queues: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.closed = False

    def publish(self, payload: dict | None) -> None:
        for q in list(self.queues):
            q.put_nowait(payload)

    def close(self) -> None:
        """End the event streams. The server waits for open connections before it exits,
        and a stream never ends on its own. Safe to call from a signal handler."""
        self.closed = True
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.publish, None)


def open_index(path: Path | None) -> SearchIndex | None:
    """The full-text index at `path`, else in memory; None if this SQLite cannot do it."""
    try:
        return SearchIndex(path)
    except (OSError, sqlite3.Error) as e:
        if path is not None:
            log.warning("keeping the search index in memory: cannot open %s: %s", path, e)
    try:
        return SearchIndex(None)
    except sqlite3.Error as e:  # no FTS5 or no trigram tokenizer (SQLite < 3.34)
        log.warning("full-text search unavailable: %s", e)
        return None


def create_app(
    dirs: Path | list[ClaudeDir],
    watch: bool = True,
    notes_path: Path | None = None,
    index_path: Path | None = None,
    update_check: bool = False,
) -> FastAPI:
    """`notes_path=None` and `index_path=None` keep notes and the search index in memory only
    (used by tests). `update_check` asks PyPI for the latest release at start and once a day."""
    store = Store(dirs, open_index(index_path))
    notes = Notes(notes_path)
    broadcaster = Broadcaster()
    sessions_dirs = {d.sessions_dir for d in store.dirs}

    async def watcher() -> None:
        targets = [
            str(p) for d in store.dirs for p in (d.projects_dir, d.sessions_dir) if p.is_dir()
        ]
        if not targets:
            return
        async for changes in awatch(*targets, recursive=True):
            changed: set[str] = set()
            live_changed = False
            for _, raw in changes:
                path = Path(raw)
                if path.parent in sessions_dirs:
                    live_changed = True
                    continue
                if path.suffix == ".jsonl" or path.name.endswith(".meta.json"):
                    sid = await asyncio.to_thread(store.update_file, path)
                    if sid:
                        changed.add(sid)
                        # Its continuation's cost is counted from its last cost record.
                        s = store.sessions.get(sid)
                        if s is not None and s.continued_in:
                            changed.add(s.continued_in)
            if changed or live_changed:
                broadcaster.publish({"sessions": sorted(changed), "live": live_changed})

    latest: dict[str, str] = {}

    async def fetch_latest() -> str | None:
        # A daemon thread, not asyncio.to_thread: shutdown would wait for a slow request.
        loop = asyncio.get_running_loop()
        done: asyncio.Future[str | None] = loop.create_future()

        def work() -> None:
            version = update.fetch_latest()
            with suppress(RuntimeError):  # the loop has closed
                loop.call_soon_threadsafe(lambda: done.done() or done.set_result(version))

        threading.Thread(target=work, daemon=True).start()
        return await done

    async def check_updates() -> None:
        while True:
            version = await fetch_latest()
            if version and version != latest.get("version"):
                latest["version"] = version
                if update.newer(version):
                    print(
                        f"cc-calendar: {version} is available (running {__version__}); "
                        f"see {update.UPDATE_DOCS}",
                        file=sys.stderr,
                    )
            await asyncio.sleep(update.CHECK_EVERY_S)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(store.scan)
        tasks = [asyncio.create_task(watcher())] if watch else []
        if update_check:
            tasks.append(asyncio.create_task(check_updates()))
        yield
        for task in tasks:
            task.cancel()
        if store.index is not None:
            store.index.close()

    app = FastAPI(title="cc-calendar", version=__version__, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.middleware("http")
    async def content_security_policy(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        return response

    app.state.store = store
    app.state.notes = notes
    app.state.broadcaster = broadcaster

    def get_session(sid: str) -> SessionAcc:
        s = store.sessions.get(sid)
        if s is None:
            raise HTTPException(404, "session not found")
        return s

    @app.get("/api/sessions")
    def list_sessions(gap: int = Query(15, ge=1, le=24 * 60)) -> dict:
        live = store.live_sessions()
        cont = store.continued_from()
        notes.refresh()
        with store.lock:
            items = [
                summary(s, live.get(s.session_id), gap * 60_000, cont.get(s.session_id), notes)
                for s in store.sessions.values()
                if s.start is not None
            ]
        return {
            "sessions": items,
            "claude_dirs": [{"name": d.name, "path": str(d.path)} for d in store.dirs],
            "version": __version__,
            "update": update.newer(latest.get("version")),  # a later release on PyPI
            "tags": notes.all_tags(),
            "notes_error": notes.error,
        }

    @app.get("/api/search")
    def search(q: str = Query(..., max_length=QUERY_LIMIT)) -> dict:
        """Sessions whose transcripts contain `q`: per session, the number of matching
        messages, tool calls and outputs (and how many of them are in subagents), and the
        first of them."""
        if store.index is None:
            raise HTTPException(503, "full-text search needs SQLite 3.34 or later with FTS5")
        found = store.index.search(q)
        hits: dict[str, dict] = {}
        with store.lock:
            for f in found:
                s = store.sessions.get(f.session_id)
                if s is None:
                    continue
                # Hits in another copy of the session would not be in the log the viewer opens.
                sa = s.subagents.get(f.agent_id) if f.agent_id else None
                if f.path != (sa.path if f.agent_id else s.path):
                    continue
                hit = hits.get(f.session_id)
                count = f.count + (hit["count"] if hit else 0)
                in_subagents = (f.count if f.agent_id else 0) + (hit["in_subagents"] if hit else 0)
                if hit is None or (f.ts is not None and (hit["ts"] is None or f.ts < hit["ts"])):
                    hit = {
                        "ts": f.ts,
                        "kind": f.kind,
                        "name": f.name,
                        "agent": f.agent_id,
                        "snippet": snippet(f.text, q),
                    }
                hit["count"] = count
                hit["in_subagents"] = in_subagents
                hits[f.session_id] = hit
        # While transcripts are still being indexed, the hits are incomplete.
        return {"query": q, "min_length": MIN_QUERY, "pending": store.index.pending(), "hits": hits}

    @app.get("/api/sessions/{sid}")
    def session_detail(sid: str, gap: int = Query(15, ge=1, le=24 * 60)) -> dict:
        live = store.live_sessions()
        notes.refresh()
        with store.lock:
            s = get_session(sid)
            out = detail(s, live.get(sid), gap * 60_000, store.continued_from().get(sid), notes)
        out["also_in"] = store.also_in(sid)
        return out

    @app.put("/api/sessions/{sid}/notes", dependencies=[Depends(same_origin_json)])
    async def update_notes(sid: str, body: NotesUpdate) -> dict:
        get_session(sid)
        try:
            out = await asyncio.to_thread(notes.set, sid, body.note, body.tags, body.rating)
        except NotesUnavailable as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except OSError as e:
            raise HTTPException(500, f"could not save notes: {e}") from e
        # Other open tabs reload the list and this session's details.
        broadcaster.publish({"sessions": [sid], "live": False})
        return out

    def log_path(sid: str, agent: str | None) -> tuple[Path, str | None]:
        s = get_session(sid)
        if not agent:
            return Path(s.path), sid
        sa = s.subagents.get(agent)
        if sa is None or sa.path is None:
            raise HTTPException(404, "subagent log not found")
        return Path(sa.path), None

    @app.get("/api/sessions/{sid}/stats")
    def session_stats(sid: str, agent: str | None = None) -> dict:
        path, filter_sid = log_path(sid, agent)
        try:
            return log_stats(path, filter_sid)
        except OSError as e:
            raise HTTPException(404, "log file not readable") from e

    @app.get("/api/sessions/{sid}/log")
    def session_log(
        sid: str,
        agent: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(300, ge=1, le=2000),
        q: str | None = Query(None, max_length=QUERY_LIMIT),
    ) -> dict:
        path, filter_sid = log_path(sid, agent)
        try:
            entries = build_entries(path, filter_sid)
        except OSError as e:
            raise HTTPException(404, "log file not readable") from e
        out = {
            "total": len(entries),
            "offset": offset,
            "entries": entries[offset : offset + limit],
        }
        if offset == 0:
            # Lets the viewer jump to an event that is not loaded yet.
            out["events"] = log_events(entries)
            if q:
                # Where a full-text search matched, to jump there.
                out["matches"] = find_entries(entries, q)
        return out

    # POST: the filtered session ids can be too many for a query string.
    @app.post("/api/tools")
    def tools(q: ToolsQuery) -> dict:
        with store.lock:
            picked = [store.sessions[i] for i in q.sessions if i in store.sessions]
            return tool_usage(picked, q.start, q.end)

    @app.post("/api/costs")
    def costs(q: CostsQuery) -> dict:
        with store.lock:
            picked = [store.sessions[i] for i in q.sessions if i in store.sessions]
            return cost_breakdown(picked, q.bounds)

    @app.post("/api/requests")
    def requests(q: RequestsQuery) -> dict:
        """The costliest prompts sent in the range, among the given sessions."""
        with store.lock:
            picked = [store.sessions[i] for i in q.sessions if i in store.sessions]
            return expensive_requests(picked, q.start, q.end, q.limit)

    @app.post("/api/prs")
    def prs(q: PrsQuery) -> dict:
        """Pull requests the given sessions worked on, with cost, time and commits over all
        their sessions, and what the given sessions did for no PR."""
        with store.lock:
            attr = Attribution(store.sessions, store.continued_from(), q.gap * 60_000)
            return pr_costs(attr, q.sessions)

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        queue: asyncio.Queue = asyncio.Queue()
        broadcaster.queues.add(queue)
        broadcaster.loop = asyncio.get_running_loop()

        async def stream():
            try:
                yield "retry: 3000\n\n"
                while not broadcaster.closed and not await request.is_disconnected():
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if payload is None:  # shutting down
                        break
                    yield f"data: {json.dumps(payload)}\n\n"
            finally:
                broadcaster.queues.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers=NO_CACHE)

    app.mount("/static", NoCacheStaticFiles(directory=STATIC), name="static")
    return app

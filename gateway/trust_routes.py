"""Trust routes (#711). Contract: docs/contract.md, "Trust: audit verification and the
live event stream". Thin wrappers over `store.trust`.

- GET  /v1/kitchens/{kitchen_id}/audit/verify        (`kitchen:read`)
- GET  /v1/kitchens/{kitchen_id}/audit/chain?limit=  (`kitchen:read`): the newest entries
  with their chain hashes, for the Trust screen
- POST /v1/kitchens/{kitchen_id}/audit/demo-tamper   (a person, role approver; demo kitchen only)
- POST /v1/kitchens/{kitchen_id}/audit/demo-restore  (the same)
- GET  /v1/kitchens/{kitchen_id}/events              (`kitchen:read`, server-sent events)

The event stream is one MongoDB change stream per connection. The store's iterator is
synchronous (it waits up to `POLL_MS` for a change), so each step runs on a worker thread
of this module's own pool: an open stream never holds the event loop or a thread of the
pool the other routes use. The change stream is closed when the response ends, for any
reason: the client left, the lifetime is over, the gateway stops.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal

import anyio
from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from pymongo.errors import PyMongoError

from gateway.service import GatewayError
from store import audit, trust

POLL_MS = 1000          # how long one step waits for a change
PING_SECONDS = 5        # a `: ping` comment after this long without a message
MAX_SECONDS = 600       # a stream ends after this long; the client connects again
MAX_STREAMS = 16        # open streams per gateway process; one more gets 503

EVENT_NAME = {"proposals": "proposal", "approvals": "approval", "audit_log": "audit"}
_DONE = object()


# ---- verify, tamper, restore ----------------------------------------------------------

CHAIN_DEFAULT, CHAIN_MAX = 20, 100


def chain_rows(gw, kitchen_id: str, limit: str | None) -> dict:
    """This kitchen's newest `limit` audit entries with their place in the hash chain,
    oldest first. `event` is the entry as `GET /audit` answers it. The hashes are the
    stored ones: a tampered entry still shows its old hash, and `verify` finds the break."""
    try:
        count = CHAIN_DEFAULT if limit is None else int(limit)
    except ValueError:
        count = 0
    if not 1 <= count <= CHAIN_MAX:
        raise GatewayError(422, "INVALID_REQUEST", f"limit: a whole number from 1 to {CHAIN_MAX}")
    return {"entries": [{"seq": entry["seq"], "prev_hash": entry["prev_hash"], "hash": entry["hash"],
                         "event": _document(gw, "audit_log", entry)}
                        for entry in trust.chain_entries(gw.db, kitchen_id, count)]}


def _key(body: dict) -> str:
    key = body.get("idempotency_key")
    if not isinstance(key, str) or not key.strip():
        raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
    return key.strip()


def _person(human: str | None) -> str:
    if not human:
        raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can run the tamper demo")
    return human


def _demo_only() -> GatewayError:
    return GatewayError(403, "DEMO_ONLY", "the tamper demo only runs on the synthetic demo kitchen")


def _event_id(kind: str, kitchen_id: str, key: str) -> str:
    return f"{kind}:" + hashlib.sha256(f"{kitchen_id}\n{key}".encode()).hexdigest()[:32]


def _stored(gw, kitchen_id: str, event_id: str) -> dict | None:
    """The audit entry an earlier call with this key wrote, if any: the replay."""
    entry = gw.db.audit_log.find_one({"event.event_id": event_id, "server.kitchen_id": kitchen_id})
    return entry["event"] if entry else None


def _record(gw, kitchen_id: str, event_id: str, kind: str, human: str, seq: int) -> None:
    """Who ran the demo, as an audit entry. It is written after the edit, so the edited
    row is an older one and this entry never is the row that was tampered."""
    audit.append_event(gw.db, {"event_id": event_id, "kind": kind, "actor": human, "tampered_seq": seq},
                       {"kitchen_id": kitchen_id, "at": gw.now().isoformat()})


def demo_tamper(gw, kitchen_id: str, body: dict, *, human: str | None) -> dict:
    human, key = _person(human), _key(body)
    event_id = _event_id("audit-demo-tamper", kitchen_id, key)
    replay = _stored(gw, kitchen_id, event_id)
    if replay:
        return {"seq": replay["tampered_seq"], "tampered": True}
    try:
        result = trust.tamper(gw.db, kitchen_id)
    except PermissionError:
        raise _demo_only() from None
    except ValueError as exc:
        # store.trust has two refusals, both a ValueError: one row at a time, and nothing to edit.
        if "already tampered" in str(exc):
            raise GatewayError(409, "ALREADY_TAMPERED", "a row is already tampered; restore it first") from None
        raise GatewayError(409, "NOTHING_TO_TAMPER", "the demo kitchen has no audit entries yet") from None
    _record(gw, kitchen_id, event_id, "audit_demo_tamper", human, result["seq"])
    return result


def demo_restore(gw, kitchen_id: str, body: dict, *, human: str | None) -> dict:
    human, key = _person(human), _key(body)
    event_id = _event_id("audit-demo-restore", kitchen_id, key)
    replay = _stored(gw, kitchen_id, event_id)
    if replay:
        return {"seq": replay["tampered_seq"], "restored": True}
    try:
        result = trust.restore(gw.db, kitchen_id)
    except PermissionError:
        raise _demo_only() from None
    if result["restored"]:
        _record(gw, kitchen_id, event_id, "audit_demo_restore", human, result["seq"])
    return result


# ---- the event stream -----------------------------------------------------------------

def _json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:f}"
    return str(value)        # ObjectId, Decimal128


def _document(gw, collection: str, doc: dict) -> dict:
    """The row as the matching read route answers it."""
    if collection == "audit_log":       # a `GET /audit` entry
        return {"seq": doc["seq"], **doc["event"], "at": (doc.get("server") or {}).get("at")}
    if collection == "approvals":       # the approval row
        return {"approval_id": doc["_id"], **{key: value for key, value in doc.items() if key != "_id"}}
    try:                                # `GET /proposals/{id}`
        return gw._proposal_out(doc)
    except Exception:
        # A proposal whose offer cannot be read still arrives, with what is certain; the
        # client loads the full row from `GET /proposals/{id}`.
        return {"proposal_id": doc["_id"], "status": doc.get("status")}


def message(gw, item: dict) -> str:
    """One change as a server-sent event."""
    data = {"operation": item["operation"],
            "document": _document(gw, item["collection"], item["document"])}
    return f"event: {EVENT_NAME[item['collection']]}\ndata: {json.dumps(data, default=_json)}\n\n"


class Streams:
    """The open streams of one gateway process: a cap, and the threads they wait on."""

    def __init__(self):
        self.open = 0
        self._lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = None

    def take(self) -> None:
        with self._lock:
            if self.open >= MAX_STREAMS:
                raise GatewayError(503, "EVENTS_UNAVAILABLE", "too many open event streams; try again later")
            self.open += 1

    def give_back(self) -> None:
        with self._lock:
            self.open -= 1

    def pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._pool is None:
                # One thread per stream that waits, and room for the ones that close.
                self._pool = ThreadPoolExecutor(max_workers=MAX_STREAMS + 4, thread_name_prefix="trust-events")
            return self._pool


class KitchenStream:
    """One connection's change stream. `step` and `close` never run at the same time."""

    def __init__(self, gw, events):
        self._gw, self._events = gw, events
        self._lock, self._closed = threading.Lock(), False

    def step(self):
        """The next message text, None when nothing happened, `_DONE` when the stream ended."""
        with self._lock:
            if self._closed:
                return _DONE
            try:
                item = next(self._events, _DONE)
            except PyMongoError:
                return _DONE        # the change stream died: end; the client connects again
        if item is None or item is _DONE:
            return item
        return message(self._gw, item)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._events.close()
                except PyMongoError:
                    pass


class EventStreamResponse(StreamingResponse):
    """A `text/event-stream` that ends when the client leaves or after `MAX_SECONDS`, and
    then always closes its change stream, also when it never sent a byte."""

    def __init__(self, stream: KitchenStream, streams: Streams):
        self._stream, self._streams = stream, streams
        super().__init__(self._chunks(), media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def _chunks(self):
        loop, pool = asyncio.get_running_loop(), self._streams.pool()
        end = time.monotonic() + MAX_SECONDS
        yield ": connected\n\n"
        sent = time.monotonic()
        while time.monotonic() < end:
            chunk = await loop.run_in_executor(pool, self._stream.step)
            if chunk is _DONE:
                return
            if chunk is None:
                if time.monotonic() - sent < PING_SECONDS:
                    continue
                chunk = ": ping\n\n"
            yield chunk
            sent = time.monotonic()

    async def __call__(self, scope, receive, send) -> None:
        async def until_disconnect(cancel_scope) -> None:
            while (await receive())["type"] != "http.disconnect":
                pass
            cancel_scope.cancel()

        try:
            async with anyio.create_task_group() as group:
                group.start_soon(until_disconnect, group.cancel_scope)
                try:
                    await self.stream_response(send)
                except OSError:
                    pass                # the client is gone
                group.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                await asyncio.get_running_loop().run_in_executor(self._streams.pool(), self._stream.close)
            self._streams.give_back()


def open_events(gw, streams: Streams, kitchen_id: str) -> EventStreamResponse:
    streams.take()
    try:
        events = trust.watch_kitchen(gw.db, kitchen_id, max_await_ms=POLL_MS)
    except (PyMongoError, NotImplementedError, TypeError):
        # A standalone MongoDB (and mongomock) has no change streams; Atlas has them.
        # Never the driver's message: it can name hosts and collections.
        streams.give_back()
        raise GatewayError(503, "EVENTS_UNAVAILABLE",
                           "the event stream needs MongoDB change streams (a replica set)") from None
    except BaseException:
        streams.give_back()
        raise
    return EventStreamResponse(KitchenStream(gw, events), streams)


def mount_trust(app: FastAPI, gw, principal, body) -> None:
    k = "/v1/kitchens/{kitchen_id}"
    app.state.trust_streams = streams = Streams()

    @app.get(k + "/audit/verify")
    def audit_verify(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return trust.verify(gw().db, kitchen_id)

    @app.get(k + "/audit/chain")
    def audit_chain(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return chain_rows(gw(), kitchen_id, request.query_params.get("limit"))

    @app.post(k + "/audit/demo-tamper")
    async def audit_demo_tamper(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        data = await body(request)
        return await run_in_threadpool(demo_tamper, gw(), kitchen_id, data, human=who.human)

    @app.post(k + "/audit/demo-restore")
    async def audit_demo_restore(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        data = await body(request)
        return await run_in_threadpool(demo_restore, gw(), kitchen_id, data, human=who.human)

    @app.get(k + "/events")
    def events(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return open_events(gw(), streams, kitchen_id)

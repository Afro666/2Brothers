"""HTTP gateway (FastAPI). Routes from docs/contract.md; logic lives in gateway/service.py.

Auth (demo): two bearer tokens from the server's environment.
- GATEWAY_AGENT_TOKEN: the Buyer agent and other services. Can read, propose and use the
  /tools routes. Can never approve.
- GATEWAY_HUMAN_TOKEN: the web app's signed-in person; `X-User` names who.
Only a person approves or rejects: a signed-in session (or this shared token in the open
demo), or a personal approval token (gateway/approval_tokens.py). Agent and kitchen tokens
get 403 HUMAN_SESSION_REQUIRED.
Run: `two-brothers-gateway` (uvicorn on 0.0.0.0:8000). Never logs keys or bodies.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from datetime import datetime
from decimal import InvalidOperation
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from gateway.service import Gateway, GatewayError
from gateway.valio_client import ValioBusy
from gateway.request_docs import (ChangeProposalRequest, CreateNeedRequest, GetOfferRequest,
                                  PlaceOrderRequest, RequestApprovalRequest, SearchProductsRequest,
                                  SimulateOrderRequest, document_body)

DEFAULT_KITCHEN = "demo-kitchen"


ALL_SCOPES = frozenset({"kitchen:read", "kitchen:propose"})

_AUDIT_FIELDS = frozenset({"event_id", "run_id", "type", "tool", "arguments", "result"})
_AUDIT_TYPES = frozenset({"tool_call_started", "tool_call_finished"})
_AUDIT_ID = 200


def _client_audit_event(raw) -> dict:
    """The agent's audit event, checked against the contract's six fields."""
    if not isinstance(raw, dict):
        raise GatewayError(422, "INVALID_REQUEST", "body must be a JSON object")
    unknown = set(raw) - _AUDIT_FIELDS
    if unknown:
        raise GatewayError(422, "INVALID_REQUEST", "unknown audit field: " + ", ".join(sorted(unknown)))
    event_id = raw.get("event_id")
    if not isinstance(event_id, str) or not event_id or len(event_id) > _AUDIT_ID:
        raise GatewayError(422, "INVALID_REQUEST",
                           f"event_id must be a nonempty string of at most {_AUDIT_ID} characters")
    kind = raw.get("type")
    if not isinstance(kind, str) or kind not in _AUDIT_TYPES:
        raise GatewayError(422, "INVALID_REQUEST",
                           "type must be tool_call_started or tool_call_finished")
    for field in ("run_id", "tool"):
        if field in raw:
            value = raw[field]
            if not isinstance(value, str) or len(value) > _AUDIT_ID:
                raise GatewayError(422, "INVALID_REQUEST",
                                   f"{field} must be a string of at most {_AUDIT_ID} characters")
    for field in ("arguments", "result"):
        if field in raw and raw[field] is not None and not isinstance(raw[field], dict):
            raise GatewayError(422, "INVALID_REQUEST", f"{field} must be an object")
    return raw


class Principal:
    """kind: human | agent | token | personal. `kitchen_id` None = any kitchen (server env tokens).

    `personal` is a personal approval token (gateway/approval_tokens.py): one person, read
    plus approve and reject only. It is not `human`, so every other person-only route
    (`who.human`) refuses it, and it holds only kitchen:read, so it never proposes."""

    def __init__(self, kind: str, name: str, kitchen_id: str | None = None,
                 scopes: frozenset = ALL_SCOPES, role: str = "approver", via: str | None = None,
                 token_id: str | None = None, expires_at: str | None = None):
        self.kind, self.name, self.kitchen_id, self.scopes = kind, name, kitchen_id, frozenset(scopes)
        self.role = role          # people only: approver, chef or viewer (#270)
        # human: "session" (cookie, a real account) or "shared_token" (the open demo's stand-in)
        self.via, self.token_id, self.expires_at = via, token_id, expires_at

    def need(self, scope: str, kitchen_id: str | None = None) -> None:
        """403 unless this caller holds `scope` for `kitchen_id`."""
        if self.kind == "personal" and scope not in self.scopes:
            raise GatewayError(403, "SCOPE_REQUIRED", f"a personal approval token can read, approve and "
                                                      f"reject only; it never proposes ({scope})")
        if self.kind != "human" and scope not in self.scopes:
            raise GatewayError(403, "SCOPE_REQUIRED", f"this token lacks {scope}")
        if self.kind == "human" and scope in ("kitchen:propose", "kitchen:write") and self.role == "viewer":
            raise GatewayError(403, "ROLE_REQUIRED", "a viewer can read, not change or ask")
        if kitchen_id is not None and self.kitchen_id is not None and kitchen_id != self.kitchen_id:
            raise GatewayError(403, "KITCHEN_SCOPE", "this token belongs to another kitchen")

    def need_supplier(self, scope: str) -> None:
        """A supplier's view across kitchens (#599). A caller bound to one kitchen (its
        people, its tokens) never reads it: consent names the supplier, not other kitchens.
        Until supplier accounts exist, only unbound server sessions (the demo) pass."""
        self.need(scope)
        if self.kitchen_id is not None:
            raise GatewayError(403, "SCOPE_REQUIRED", "a kitchen's session cannot read a supplier's view")

    @property
    def human(self) -> str | None:
        """The name of a person who may approve, reject and manage tokens; else None."""
        if self.kind == "human" and self.role != "approver":
            raise GatewayError(403, "ROLE_REQUIRED", "only an approver can do this")
        return self.name if self.kind == "human" else None

    @property
    def approver(self) -> str | None:
        """Who approves or rejects: a signed-in approver, or the person of a personal approval
        token whose account is still an approver. Agents and kitchen tokens: None."""
        if self.kind == "personal":
            if self.role != "approver":
                raise GatewayError(403, "ROLE_REQUIRED", "only an approver can do this")
            return self.name
        return self.human

    @property
    def via_audit(self) -> dict:
        """Audit fields for an approve or reject made with a personal token; never its value."""
        return {"via": self.via, "token_id": self.token_id} if self.kind == "personal" else {}


def _token_matches(given: str, env: str) -> bool:
    expected = os.environ.get(env, "")
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


SIGNED_IN_PERSON = "a signed-in person"      # in place of an email, for the open demo (#1577)


def _env_principal(request: Request, token: str) -> Principal:
    # GATEWAY_REQUIRE_LOGIN=true: the shared human token stops working; people sign in (#270).
    require_login = os.environ.get("GATEWAY_REQUIRE_LOGIN", "").lower() == "true"
    if token and not require_login and _token_matches(token, "GATEWAY_HUMAN_TOKEN"):
        user = (request.headers.get("x-user") or "").strip()[:100]
        if not user:
            raise GatewayError(401, "UNAUTHENTICATED", "X-User names the person")
        return Principal("human", user, via="shared_token")
    if token and _token_matches(token, "GATEWAY_AGENT_TOKEN"):
        return Principal("agent", "buyer-agent")
    raise GatewayError(401, "UNAUTHENTICATED", "a valid bearer token is required")


REFUSAL_WINDOW = 60.0          # seconds: one audit row per repeated refusal (#853)


def create_app(gateway: Gateway | None = None, *, buyer_worker=None, shelf_worker=None,
               delivery_note_worker=None, menu_photo_worker=None, buying_note_worker=None, price_list_worker=None, explanation_worker=None, label_photo_worker=None, brief_worker=None,
               split_worker=None) -> FastAPI:
    from gateway.buyer_worker import Breaker
    buyer_breaker = Breaker()        # one per app: a timeout skips the model for 2 minutes
    split_breaker = Breaker()        # the same for the split of several products (#1375), its own
    app = FastAPI(
        title="Kitchen Buyer gateway", version="0.1.0",
        description=("REST and MCP gateway between a kitchen's Buyer agent and its suppliers. "
                     "The engine sizes every quantity, a person approves every order, every step is audited. "
                     "Why it is built this way: docs/choices.md. Field-level rules: docs/contract.md."),
        # Behind Caddy the gateway lives under /api (people) and /gateway (agents with a bearer token).
        servers=[{"url": "/api", "description": "demo site, as a person"},
                 {"url": "/gateway", "description": "agents, with a bearer token"},
                 {"url": "/", "description": "local run"}],
        docs_url=None, redoc_url=None)

    @app.get("/docs", include_in_schema=False)
    async def _docs() -> HTMLResponse:
        # A relative spec URL, so /api/docs loads /api/openapi.json and not the web app's /openapi.json (#278).
        return get_swagger_ui_html(openapi_url="openapi.json", title="Kitchen Buyer gateway - API")
    state: dict[str, Gateway] = {}

    def gw() -> Gateway:
        if gateway is not None:
            return gateway
        if "gw" not in state:
            from gateway.valio_client import ValioClient
            from store.db import get_db
            state["gw"] = Gateway(get_db(), ValioClient())
        return state["gw"]

    refusals_seen: dict[tuple, float] = {}

    def _audit_refusal(request: Request, who: Principal, code: str) -> None:
        """#853: the path's kitchen only when that kitchen exists (a caller cannot create log
        rows for made-up kitchens), else the caller's own; the same refusal (caller, code,
        method, route template, kitchen) at most once a minute, so a loop cannot flood a
        kitchen's log. #863: the template, not the raw path, so varied ids are one key."""
        named = request.path_params.get("kitchen_id")
        target = named if named and gw().db.kitchens.find_one({"_id": named}, {"_id": 1}) else kitchen(who)
        route = getattr(request.scope.get("route"), "path", None) or request.url.path
        key = (who.name, code, request.method, route, target)
        now = time.monotonic()
        if now - refusals_seen.get(key, -REFUSAL_WINDOW) < REFUSAL_WINDOW:
            return
        if len(refusals_seen) > 10_000:
            for stale in [k for k, t in refusals_seen.items() if now - t >= REFUSAL_WINDOW]:
                del refusals_seen[stale]
            if len(refusals_seen) > 10_000:
                refusals_seen.clear()
        refusals_seen[key] = now
        gw()._audit(target, "refused", who.name, code=code, method=request.method,
                    route=route, path=request.url.path)

    @app.exception_handler(GatewayError)
    async def _error(request: Request, exc: GatewayError) -> JSONResponse:
        # #548: every refusal of a token or agent is audit evidence, also when a caller skips
        # the Buyer and calls the gateway directly. People's 403s are UI guards, not attacks.
        who = getattr(request.state, "who", None)
        if exc.status == 403 and who is not None and who.kind != "human":
            try:
                _audit_refusal(request, who, exc.code)
            except Exception:
                pass                # a failed audit write never turns a refusal into a 500
        return JSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": exc.message, **exc.extra}})

    @app.exception_handler(ValioBusy)   # #1237: Valio rests after a 429, or our queue is too long
    async def _supplier_busy(_: Request, exc: ValioBusy) -> JSONResponse:
        return JSONResponse(status_code=503, headers={"Retry-After": str(exc.retry_after)},
                            content={"error": {"code": "SUPPLIER_BUSY", "message": str(exc),
                                               "retry_after_s": exc.retry_after}})   # #1286

    @app.exception_handler(ValueError)
    async def _invalid(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "message": str(exc)[:200]}})

    @app.exception_handler(InvalidOperation)   # Decimal("abc"): an ArithmeticError, not a ValueError
    async def _invalid_number(_: Request, exc: InvalidOperation) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "message": "a number field is not a number"}})

    def principal(request: Request) -> Principal:
        who = _resolve(request)
        request.state.who = who            # the error handler audits a token's refusals (#548)
        return who

    def _resolve(request: Request) -> Principal:
        """The session cookie of a signed-in person first, then the server env tokens (Buyer
        worker, open-demo stand-in), then kitchen API tokens."""
        from gateway import users
        person = users.session_user(gw().db, request.cookies.get(users.COOKIE))
        if person is not None:
            return Principal("human", person["email"], person["kitchen_id"], role=person["role"], via="session")
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        try:
            return _env_principal(request, token)
        except GatewayError:
            pass
        from gateway import approval_tokens, tokens
        if token.startswith(approval_tokens.PREFIX):
            found = approval_tokens.verify(gw().db, token, gw().now())
            if found is None:
                raise GatewayError(401, "UNAUTHENTICATED", "this approval token is expired, revoked or unknown")
            doc, user = found
            return Principal("personal", user["_id"], doc["kitchen_id"], frozenset({"kitchen:read"}),
                             role=user["role"], via=approval_tokens.VIA, token_id=doc["_id"],
                             expires_at=approval_tokens._iso(doc["expires_at"]))
        doc = tokens.verify(gw().db, token)
        if doc is None:
            raise GatewayError(401, "UNAUTHENTICATED", "a valid bearer token is required")
        return Principal("token", f"token:{doc['name']}", doc["kitchen_id"], frozenset(doc["scopes"]))

    app.state.verify_token = lambda token: __import__("gateway.tokens", fromlist=["verify"]).verify(gw().db, token)
    app.state.verify_approval_token = lambda token: __import__(
        "gateway.approval_tokens", fromlist=["verify"]).verify(gw().db, token, gw().now())

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except ValueError:
            raise GatewayError(422, "INVALID_JSON", "body must be a JSON object") from None
        if not isinstance(data, dict):
            raise GatewayError(422, "INVALID_JSON", "body must be a JSON object")
        return data

    # ---- sign-in (#270) ---------------------------------------------------------------
    def _auth_error(exc) -> GatewayError:
        return GatewayError(exc.status, exc.code, str(exc))

    @app.post("/v1/auth/login")
    async def login(request: Request):
        from gateway import users
        data = await body(request)
        users.seed_user(gw().db, os.environ.get("DEMO_USER_EMAIL"), os.environ.get("DEMO_USER_PASSWORD"),
                        os.environ.get("GATEWAY_KITCHEN_ID", DEFAULT_KITCHEN))
        try:
            person, token = users.login(gw().db, data.get("email"), data.get("password"))
        except users.AuthError as exc:
            raise _auth_error(exc) from None
        response = JSONResponse(person)
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(users.COOKIE, token, max_age=int(users.SESSION_TTL.total_seconds()),
                            httponly=True, secure=https, samesite="strict", path="/")
        # An all-kitchens account (users.py) signs in to the default kitchen's log.
        gw()._audit(person["kitchen_id"] or os.environ.get("GATEWAY_KITCHEN_ID", DEFAULT_KITCHEN),
                    "signed_in", person["email"])
        return response

    @app.post("/v1/auth/logout")
    def logout(request: Request):
        from gateway import users
        users.logout(gw().db, request.cookies.get(users.COOKIE))
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(users.COOKIE, path="/")
        return response

    @app.get("/v1/me")
    def me(who: Principal = Depends(principal)):
        person = who.kind in ("human", "personal")
        out = {"kind": who.kind, "name": who.name, "role": who.role if person else None,
               "kitchen_id": who.kitchen_id, "can_approve": person and who.role == "approver",
               "scopes": sorted(who.scopes) if who.kind != "human" else None}
        if who.kind == "personal":
            out.update(via=who.via, token_id=who.token_id, expires_at=who.expires_at)
        return out

    @app.post("/v1/auth/change-password")
    async def change_password(request: Request):
        from gateway import users
        token = request.cookies.get(users.COOKIE)
        person = users.session_user(gw().db, token)
        if person is None:
            raise GatewayError(401, "UNAUTHENTICATED", "sign in first")
        data = await body(request)
        try:
            users.change_password(gw().db, person["email"], data.get("current_password"),
                                  data.get("new_password"), keep_token=token)
        except users.AuthError as exc:
            raise _auth_error(exc) from None
        gw()._audit(person["kitchen_id"] or os.environ.get("GATEWAY_KITCHEN_ID", DEFAULT_KITCHEN),
                    "password_changed", person["email"])
        return {"changed": True}

    @app.get("/.well-known/jwks.json")
    def jwks():
        """The public key that signs every offer (#290). No token needed: it is public."""
        from gateway import signing
        return signing.jwks(gw().db)

    @app.get("/health")
    def health() -> dict:
        """Public and cheap (#1188): never calls Valio, never opens the database. Mode and a
        yes/no from the last call the gateway made; no host, key or upstream text."""
        built = gateway if gateway is not None else state.get("gw")
        valio = getattr(built, "valio", None)
        if valio is None:       # no request served yet: the server builds a real client on the first one
            return {"status": "ok", "valio_api": "live", "valio_reachable": None, "valio_checked_at": None}
        at = getattr(valio, "last_checked_at", None)
        reachable = getattr(valio, "last_reachable", None)
        return {"status": "ok", "valio_api": "live" if getattr(valio, "live", False) is True else "mock",
                "valio_reachable": reachable if isinstance(reachable, bool) else None,
                "valio_checked_at": at.isoformat() if isinstance(at, datetime) else None}

    # ---- kitchen side -------------------------------------------------------------
    k = "/v1/kitchens/{kitchen_id}"

    @app.post(k + "/proposals")
    async def create_proposal(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose", kitchen_id)
        data = await body(request)
        data.pop("buyer_down", None)          # set by the gateway only, never by the client
        # Gateway work that can call Valio runs in a worker thread: the limiter's wait
        # (Gate.acquire, a blocking sleep) must never freeze the event loop (#1280).
        if 'needs' in data:
            return await run_in_threadpool(gw().create_proposal, kitchen_id, data, who.name)   # list body (#1375)
        if 'text' in data and 'product_ids' not in data:
            several = gw().prepare_several(kitchen_id, data)
            if several is not None:
                return several.get("replay") or await split_and_propose(kitchen_id, data, several["day"], who.name)
            # A request the kitchen's allergen rule removes ends here, with the reason (#974):
            # the Buyer would only see what the rule left and propose another kind of product.
            refused = await run_in_threadpool(gw().refuse_excluded, kitchen_id, data, who.name)
            if refused is not None:
                return refused
            from gateway.buyer_worker import run_buyer
            if buyer_breaker.is_open():
                data["buyer_down"] = True     # the model timed out under 2 minutes ago: parser now
            else:
                try:
                    out = await (buyer_worker or run_buyer)(kitchen_id, data)
                    buyer_breaker.reset()
                    return out
                except GatewayError as exc:
                    # Fall back to the deterministic parser (#276) only when the Buyer is not
                    # there at all. An ambiguous failure (it may have made a proposal) must be
                    # reconciled first, never answered with a second proposal.
                    not_configured = exc.code == "BUYER_UNAVAILABLE" and "fallback_safe" not in exc.extra
                    if not (not_configured or exc.extra.get("fallback_safe") is True):
                        raise
                    if exc.code == "BUYER_TIMEOUT":
                        buyer_breaker.trip()
                        data["buyer_down"] = True
        return await run_in_threadpool(gw().create_proposal, kitchen_id, data, who.name)

    async def split_and_propose(kitchen_id: str, data: dict, day: str, actor: str) -> dict:
        """Several products in one text (#1375): Nemotron splits it, plain code checks the
        split (the model never sets a quantity), and the needs go as one list body. The model
        off, slow or out of its schema: the plain-code split. A split that fails the check is
        refused with the sentence of #288."""
        import asyncio
        from gateway import split
        from gateway.buyer_worker import SPLIT_SECONDS, run_split
        from gateway.parse import ONE_PRODUCT, ParseError
        text, reply, split_by = data["text"], None, "rules"
        if not split_breaker.is_open():
            try:
                reply = await asyncio.wait_for((split_worker or run_split)(kitchen_id, text), SPLIT_SECONDS + 1)
                split_breaker.reset()
            except asyncio.TimeoutError:
                split_breaker.trip()          # the next texts skip the model for 2 minutes
            except Exception:
                reply = None                  # never upstream text in an answer: the rules split
        try:
            if reply is not None:
                try:
                    needs, split_by = split.check(text, reply), "model"
                except ParseError:
                    # The sentence of before (#288), never the model's words.
                    raise GatewayError(422, "CANNOT_READ_REQUEST", ONE_PRODUCT) from None
            else:
                needs = split.rules_split(text)
        except ParseError as exc:
            raise GatewayError(422, "CANNOT_READ_REQUEST", str(exc)) from None
        body = {"needs": needs, "requested_date": day, "idempotency_key": data["idempotency_key"], "text": text}
        if data.get("event") is True:
            body["event"] = True
        return await run_in_threadpool(gw()._create_list, kitchen_id, body, actor, split_by=split_by)

    @app.get(k + "/proposals")
    def list_proposals(kitchen_id: str, cursor: str | None = None, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().proposal_page(kitchen_id, cursor=cursor)

    @app.get(k + "/catalog/products")
    def catalog_products(kitchen_id: str, ids: str = "", who: Principal = Depends(principal)):
        """Product rows by code, in the order asked (#304): for screens that hold codes."""
        who.need("kitchen:read", kitchen_id)
        codes = [c.strip() for c in ids.split(",") if c.strip()]
        if not 1 <= len(codes) <= 200:
            raise GatewayError(422, "INVALID_REQUEST", "ids is 1 to 200 product codes, comma-separated")
        from store.products import get_products
        return {"products": get_products(gw().db, codes, kitchen_id)}

    @app.get(k + "/label-checks")
    def label_checks(kitchen_id: str, who: Principal = Depends(principal)):
        who.need('kitchen:read', kitchen_id)
        from monitor.labels import checks, verify, LABEL
        from store.products import get_products
        rows = get_products(gw().db, ['462535', '462576', '462775'], kitchen_id)
        negative = verify({'product_id': 'synthetic-negative-control',
            'vendor': 'Synthetic Unregistered Demo Producer Oy'}, LABEL, now=gw().now())
        return {'checks': checks(rows, now=gw().now()), 'negative_control': {**negative, 'synthetic': True}}

    @app.get(k + "/proposals/{proposal_id}")
    def get_proposal(kitchen_id: str, proposal_id: str, background_tasks: BackgroundTasks,
                     explanation_language: Literal['en', 'fi'] | None = None, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        proposal = gw().get_proposal(kitchen_id, proposal_id)
        if explanation_language is not None:
            from gateway.explanations import enrich
            try:
                return enrich(gw(), kitchen_id, proposal, explanation_language, background_tasks,
                              who.name, explanation_worker)
            except Exception as exc:
                logging.getLogger(__name__).warning('explanation enrich failed proposal_id=%s error=%s',
                                                    proposal_id, type(exc).__name__)
                return {**proposal, 'explanation': None}
        return proposal

    @app.get(k + "/proposals/{proposal_id}/addable")
    def addable(kitchen_id: str, proposal_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().addable(kitchen_id, proposal_id)

    @app.post(k + "/proposals/{proposal_id}/approve")
    async def approve(kitchen_id: str, proposal_id: str, request: Request, who: Principal = Depends(principal)):
        # A person: a signed-in approver, or a personal approval token (decision 2026-11-14).
        who.need("kitchen:read", kitchen_id)
        return await run_in_threadpool(gw().approve, kitchen_id, proposal_id, await body(request),
                                       human=who.approver, via=who.via_audit)

    @app.post(k + "/proposals/{proposal_id}/reject")
    async def reject(kitchen_id: str, proposal_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().reject(kitchen_id, proposal_id, await body(request), human=who.approver,
                           via=who.via_audit)

    @app.post(k + "/proposals/{proposal_id}/choose-option")
    async def choose_option(kitchen_id: str, proposal_id: str, request: Request,
                            who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        from gateway import options
        return await run_in_threadpool(options.choose, gw(), kitchen_id, proposal_id, await body(request),
                                       human=who.human)

    @app.post(k + "/proposals/{proposal_id}/change", openapi_extra=document_body(ChangeProposalRequest))
    async def change_proposal(kitchen_id: str, proposal_id: str, request: Request,
                              who: Principal = Depends(principal)):
        # A person or an agent may change a proposal (#303); only a person approves it.
        who.need("kitchen:propose", kitchen_id)
        from gateway import change
        return await run_in_threadpool(change.change, gw(), kitchen_id, proposal_id, await body(request),
                                       actor=who.name, person=who.name if who.kind == "human" else None)

    @app.post(k + "/recalls/{event_id}/dismiss")
    async def dismiss_recall(kitchen_id: str, event_id: str, request: Request, who: Principal = Depends(principal)):
        who.need('kitchen:read', kitchen_id)
        return gw().dismiss_recall(kitchen_id, event_id, await body(request), human=who.human)

    @app.post(k + "/needs", openapi_extra=document_body(CreateNeedRequest))
    async def create_need(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose", kitchen_id)
        return gw().create_need(kitchen_id, await body(request), who.name)

    @app.get(k + "/orders")
    def list_orders(kitchen_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return {"orders": gw().list_orders(kitchen_id)}

    @app.get(k + "/orders/{order_id}")
    def get_order(kitchen_id: str, order_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().get_order(kitchen_id, order_id)

    # ---- unknown send (#291): a person records what happened; never a resend -------
    @app.get(k + "/orders/{order_id}/resolution")
    def order_resolution(kitchen_id: str, order_id: str, who: Principal = Depends(principal)):
        from gateway import resolve
        who.need("kitchen:read", kitchen_id)
        return resolve.lookup(gw(), kitchen_id, order_id, human=who.human)

    @app.post(k + "/orders/{order_id}/resolve")
    async def resolve_order(kitchen_id: str, order_id: str, request: Request, who: Principal = Depends(principal)):
        from gateway import resolve
        who.need("kitchen:read", kitchen_id)
        return resolve.resolve(gw(), kitchen_id, order_id, await body(request), human=who.human)

    @app.get(k + "/forecast-accuracy")
    def forecast_accuracy(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        q = request.query_params
        if not q.get("from") or not q.get("to"):
            raise GatewayError(422, "INVALID_REQUEST", "from and to (YYYY-MM-DD) are required")
        return gw().forecast_accuracy(kitchen_id, q["from"], q["to"])

    @app.get(k + "/forecast")
    def forecast(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        q = request.query_params
        if not q.get("from") or not q.get("to"):
            raise GatewayError(422, "INVALID_REQUEST", "from and to (YYYY-MM-DD) are required")
        return gw().forecast(kitchen_id, q["from"], q["to"])

    # ---- earned auto-approve (#299): off by default, only after the learning period ----
    @app.get(k + "/auto-approve")
    def auto_approve_status(kitchen_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        from gateway import autoapprove
        return autoapprove.status(gw().db, kitchen_id, gw().now())

    @app.put(k + "/auto-approve")
    async def auto_approve_set(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        from gateway import autoapprove
        if not who.human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only an approver can change auto-approve")
        data = await body(request)
        try:
            out = autoapprove.configure(gw().db, kitchen_id, enabled=data.get("enabled"),
                                        limit_eur=data.get("limit_eur"), person=who.human, now=gw().now())
        except autoapprove.AutoApproveError as exc:
            raise GatewayError(exc.status, exc.code, str(exc)) from None
        gw()._audit(kitchen_id, "auto_approve_changed", who.human, enabled=out["enabled"], limit_eur=out["limit_eur"])
        return autoapprove.status(gw().db, kitchen_id, gw().now())

    @app.get(k + "/permissions")
    def permissions_matrix(kitchen_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        from gateway import permissions
        from gateway import autoapprove
        return permissions.matrix(autoapprove.settings(gw().db, kitchen_id))

    @app.get(k + "/audit")
    def audit(kitchen_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return {"events": gw().audit_log(kitchen_id)}

    # ---- API tokens (#271): a person creates and revokes them; tokens never approve ----
    def made_by_for(who: Principal, row: dict) -> dict:
        """The open demo is everyone at once (#1577): it sees who made a kitchen token or a
        webhook only when that was the open demo's own name. A signed-in person's email is
        shown to signed-in people of the kitchen only."""
        if who.via == "session" or row.get("created_by") == who.human:
            return row
        return {**row, "created_by": SIGNED_IN_PERSON}

    @app.post(k + "/tokens")
    async def create_token(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)   # the person must belong to this kitchen
        from gateway import tokens
        who.need("kitchen:read", kitchen_id)        # a session is bound to its kitchen
        if not who.human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can create a token")
        data = await body(request)
        try:
            out = tokens.create(gw().db, kitchen_id, data.get("name"), data.get("scopes"), who.human)
        except tokens.TokenError as exc:
            raise GatewayError(422, "INVALID_REQUEST", str(exc)) from None
        gw()._audit(kitchen_id, "token_created", who.human, token_id=out["token_id"],
                    name=out["name"], scopes=out["scopes"])
        return out

    @app.get(k + "/tokens")
    def list_tokens(kitchen_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)   # the person must belong to this kitchen
        from gateway import tokens
        who.need("kitchen:read", kitchen_id)
        if not who.human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can list tokens")
        return {"tokens": [made_by_for(who, t) for t in tokens.list_tokens(gw().db, kitchen_id)]}

    @app.delete(k + "/tokens/{token_id}")
    def revoke_token(kitchen_id: str, token_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)   # the person must belong to this kitchen
        from gateway import tokens
        who.need("kitchen:read", kitchen_id)
        if not who.human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can revoke a token")
        out = tokens.revoke(gw().db, kitchen_id, token_id)
        if out is None:
            raise GatewayError(404, "TOKEN_NOT_FOUND", "no such token")
        gw()._audit(kitchen_id, "token_revoked", who.human, token_id=token_id)
        return made_by_for(who, out)

    # ---- Personal approval tokens (decision 2026-11-14): a person approves from chat ----
    @app.post(k + "/approval-tokens")
    async def create_approval_token(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        from gateway import approval_tokens
        who.need("kitchen:read", kitchen_id)        # a session is bound to its kitchen
        if who.kind != "human":
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a signed-in person can create an approval token")
        person = approval_token_owner(who, kitchen_id)
        data = await body(request)
        try:
            out = approval_tokens.create(gw().db, person, kitchen_id, person, hours=data.get("hours"),
                                         name=data.get("name"), now=gw().now())
        except approval_tokens.ApprovalTokenError as exc:
            raise GatewayError(exc.status, exc.code, str(exc)) from None
        for old in out.pop("capped", []):
            gw()._audit(kitchen_id, "approval_token_revoked", person, token_id=old, person=person,
                        reason=approval_tokens.CAP_REASON)
        gw()._audit(kitchen_id, "approval_token_created", person, token_id=out["token_id"],
                    person=out["person"], expires_at=out["expires_at"])
        return out

    def approval_token_owner(who: Principal, kitchen_id: str) -> str:
        """Whose approval tokens this caller makes, lists and revokes: a signed-in person's
        own email, or `open-demo` for the open demo's shared token (decision 2026-11-14 18:08
        UTC, #1446), in the open demo's kitchen only. The open demo never sees or revokes a
        real person's token (#1575): every query is filtered by this person."""
        from gateway import approval_tokens
        person = who.human                          # ROLE_REQUIRED for a chef or a viewer
        if who.via == "session":
            return person
        if who.via == "shared_token" and approval_tokens.open_demo_on():
            if kitchen_id != approval_tokens.open_demo_kitchen():
                raise GatewayError(403, "KITCHEN_SCOPE", "the open demo has approval tokens in its own kitchen only")
            return approval_tokens.OPEN_DEMO
        raise GatewayError(403, "PERSONAL_TOKEN_NEEDS_SIGN_IN",
                           "sign in with your own account to manage your approval tokens")

    def approval_token_admin(who: Principal, kitchen_id: str) -> str:
        who.need("kitchen:read", kitchen_id)
        if not who.human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can manage approval tokens")
        return approval_token_owner(who, kitchen_id)

    @app.get(k + "/approval-tokens")
    def list_approval_tokens(kitchen_id: str, who: Principal = Depends(principal)):
        from gateway import approval_tokens
        person = approval_token_admin(who, kitchen_id)
        return {"tokens": approval_tokens.list_tokens(gw().db, kitchen_id, person=person)}

    @app.delete(k + "/approval-tokens/{token_id}")
    def revoke_approval_token(kitchen_id: str, token_id: str, who: Principal = Depends(principal)):
        from gateway import approval_tokens
        person = approval_token_admin(who, kitchen_id)
        out = approval_tokens.revoke(gw().db, kitchen_id, token_id, gw().now(), person=person)
        if out is None:
            raise GatewayError(404, "TOKEN_NOT_FOUND", "no such approval token")
        gw()._audit(kitchen_id, "approval_token_revoked", person, token_id=token_id, person=out["person"])
        return out

    # ---- Webhooks (#277): an approver registers them; the secret is shown once ---------
    def hook_admin(who: Principal, kitchen_id: str) -> str:
        who.need("kitchen:read", kitchen_id)        # a session is bound to its kitchen
        if not who.human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can manage webhooks")
        return who.human

    def hook_or_404(kitchen_id: str, webhook_id: str) -> dict:
        from gateway import webhooks
        hook = webhooks.get(gw().db, kitchen_id, webhook_id)
        if hook is None:
            raise GatewayError(404, "WEBHOOK_NOT_FOUND", "no such webhook")
        return hook

    @app.post(k + "/webhooks")
    async def create_webhook(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        from gateway import webhooks
        person = hook_admin(who, kitchen_id)
        data = await body(request)
        try:
            out = webhooks.register(gw().db, kitchen_id, data.get("url"), data.get("events"), person)
        except webhooks.WebhookError as exc:
            raise GatewayError(422, "INVALID_REQUEST", str(exc)) from None
        gw()._audit(kitchen_id, "webhook_created", person, webhook_id=out["webhook_id"],
                    url=out["url"], events=out["events"])
        return out

    @app.get(k + "/webhooks")
    def list_webhooks(kitchen_id: str, who: Principal = Depends(principal)):
        from gateway import webhooks
        hook_admin(who, kitchen_id)
        return {"webhooks": [made_by_for(who, h) for h in webhooks.list_hooks(gw().db, kitchen_id)],
                "events": list(webhooks.EVENTS)}

    @app.delete(k + "/webhooks/{webhook_id}")
    def delete_webhook(kitchen_id: str, webhook_id: str, who: Principal = Depends(principal)):
        from gateway import webhooks
        person = hook_admin(who, kitchen_id)
        out = webhooks.delete(gw().db, kitchen_id, webhook_id)
        if out is None:
            raise GatewayError(404, "WEBHOOK_NOT_FOUND", "no such webhook")
        gw()._audit(kitchen_id, "webhook_deleted", person, webhook_id=webhook_id)
        return {**made_by_for(who, out), "deleted": True}

    @app.post(k + "/webhooks/{webhook_id}/test")
    def test_webhook(kitchen_id: str, webhook_id: str, who: Principal = Depends(principal)):
        """One signed `ping`, one attempt, so the person sees the result at once."""
        from gateway import webhooks
        hook_admin(who, kitchen_id)
        hook_or_404(kitchen_id, webhook_id)
        rows = webhooks.deliver(gw().db, kitchen_id, webhooks.PING, {"webhook_id": webhook_id},
                                hook_id=webhook_id, attempts=1)
        if not rows:
            raise GatewayError(502, "WEBHOOK_TEST_FAILED", "the ping could not be sent")
        return rows[0]

    @app.get(k + "/webhooks/{webhook_id}/deliveries")
    def webhook_deliveries(kitchen_id: str, webhook_id: str, who: Principal = Depends(principal)):
        from gateway import webhooks
        hook_admin(who, kitchen_id)
        hook_or_404(kitchen_id, webhook_id)
        return {"deliveries": webhooks.deliveries(gw().db, kitchen_id, webhook_id)}

    # ---- Buyer agent tools (one kitchen per agent token in the demo) ----------------
    def kitchen(who: Principal | None = None) -> str:
        """A kitchen API token acts for its own kitchen; the server agent token for the default."""
        if who is not None and who.kitchen_id is not None:
            return who.kitchen_id
        return os.environ.get("GATEWAY_KITCHEN_ID", DEFAULT_KITCHEN)

    @app.post("/tools/search_products", openapi_extra=document_body(SearchProductsRequest))
    async def search(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read")
        data = await body(request)
        limit = data.get("limit", 20)
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise GatewayError(422, "INVALID_REQUEST", "limit: 1 to 50")
        need_id = data.get("need_id")
        if need_id is not None and not isinstance(need_id, str):
            raise GatewayError(422, "INVALID_REQUEST", "need_id must be a string")
        mode = data.get("mode")      # the Catalog page's "Search by meaning" switch (#1382)
        if mode is not None and mode not in ("text", "hybrid"):
            raise GatewayError(422, "INVALID_REQUEST", 'mode: "text" or "hybrid"')
        return await run_in_threadpool(gw().tool_search, kitchen(who), data.get("query") or "",
                                       data.get("filters") or {}, limit, need_id, mode)

    @app.post("/tools/get_offer", openapi_extra=document_body(GetOfferRequest))
    async def get_offer(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return await run_in_threadpool(gw().tool_get_offer, kitchen(who), await body(request))

    @app.post("/tools/simulate_order", openapi_extra=document_body(SimulateOrderRequest))
    async def simulate(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return gw().tool_simulate(kitchen(who), await body(request))

    @app.post("/tools/request_approval", openapi_extra=document_body(RequestApprovalRequest))
    async def request_approval(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return gw().tool_request_approval(kitchen(who), await body(request), who.name)

    @app.post("/tools/place_order", openapi_extra=document_body(PlaceOrderRequest))
    async def place_order(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return gw().tool_place_order(kitchen(who), await body(request))

    @app.get("/tools/get_order_status")
    def order_status(order_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read")
        order = gw().get_order(kitchen(who), order_id)
        return {"order_id": order["order_id"], "status": order["status"], "outcome": order["outcome"],
                # #1768: the Buyer must not read RECORDED / CONFIRMED as "the supplier has it"
                "supplier_outcome": order["supplier_outcome"], "supplier_note": order["supplier_note"]}

    @app.get("/tools/get_audit_log")
    def audit_tool(run_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read")
        from store.audit import list_events
        return {"events": [e["event"] for e in list_events(gw().db, run_id=run_id, kitchen_id=kitchen(who))]}

    @app.post("/tools/change_proposal")
    async def change_tool(request: Request, who: Principal = Depends(principal)):
        """The MCP `change_proposal` tool (#303): the kitchen route's code for the caller's kitchen."""
        who.need("kitchen:propose")
        data = await body(request)
        proposal_id = data.pop("proposal_id", None)
        if not isinstance(proposal_id, str) or not proposal_id:
            raise GatewayError(422, "INVALID_REQUEST", "proposal_id is required")
        from gateway import change
        return await run_in_threadpool(change.change, gw(), kitchen(who), proposal_id, data, actor=who.name,
                                       person=who.name if who.kind == "human" else None)

    @app.post("/audit/events")
    async def audit_ingest(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        from store.audit import AuditConflict, append_event
        event = _client_audit_event(await body(request))
        kitchen_id = kitchen(who)
        client_event_id = event["event_id"]
        stored_event = {**event, "event_id": f"agent:{kitchen_id}:{client_event_id}"}
        try:
            append_event(gw().db, stored_event, {"kitchen_id": kitchen_id, "principal": who.name,
                                                 "at": gw().now().isoformat()})
        except AuditConflict:
            raise GatewayError(409, "IDEMPOTENCY_CONFLICT", "event_id reused with other content") from None
        return {"event_id": client_event_id, "stored": True}

    # Standing-order drift (#377): kitchen and supplier views.
    from gateway.product_page import mount_product_page   # one product's page (#1603)
    mount_product_page(app, gw, principal)
    from gateway.drift_routes import mount_drift
    mount_drift(app, gw, principal)
    from gateway.supplier_routes import mount_supplier   # the wholesaler's demand view (#33)
    mount_supplier(app, gw, principal)
    from gateway.brief import mount_brief
    mount_brief(app, gw, principal, brief_worker)
    from gateway.buying_note import mount_buying_note   # Nemotron's note for the supplier's planner (#1176)
    mount_buying_note(app, gw, principal, buying_note_worker)
    from gateway.nutrition_routes import mount_nutrition   # label nutrition per recipe, day and order
    mount_nutrition(app, gw, principal)
    from gateway.memory import mount_memory   # what a kitchen calls things: aliases, unknown items
    mount_memory(app, gw, principal, body)
    from gateway.supplier_offers import mount_supplier_offers   # the selling agent's suggestions (#374)
    mount_supplier_offers(app, gw, principal, body)

    # Trust (#711): audit chain verify, the tamper demo, the live event stream.
    from gateway.trust_routes import mount_trust
    mount_trust(app, gw, principal, body)

    # Model usage (#365): what the Buyer's model used for a kitchen, summed over its runs.
    from gateway.model_usage import mount_model_usage
    mount_model_usage(app, gw, principal)

    # Atlas facts (#1383): vectors, index states, time series, audit chain, for the About page.
    from gateway.atlas_routes import mount_atlas
    mount_atlas(app, gw, principal)

    # Onboarding lookup (#375): Context.dev brand lookup for the sign-up form.
    from gateway.onboarding import mount_onboarding
    mount_onboarding(app, principal, body)

    # Brand logos (product pictures): reads the brand_logos rows; never calls Context.dev.
    from gateway.brand_logos import mount_brand_logos
    mount_brand_logos(app, gw, principal)

    # Recall list and "check now" (#358): views over the monitor's holds and replacements.
    from gateway.recalls_view import mount_recalls
    mount_recalls(app, gw, principal, body)

    # Kitchen planning routes (#74): stock, products, recipes, menu plans, suppliers, demand.
    from gateway.kitchen_routes import register as register_kitchen_routes
    register_kitchen_routes(app, gw, principal, body)
    from gateway.learned import mount_learned   # learned facts for one kitchen (#1305-#1307)
    mount_learned(app, gw, principal, body)

    # Count from a shelf photo (#373): Nemotron VL reads it in the worker; stores no count.
    from gateway.stock_photo import mount_stock_photo
    mount_stock_photo(app, gw, principal, shelf_worker)

    # Check a delivery from a photo of its note (#362): read in the worker; save the facts.
    from gateway.delivery_note import mount_delivery_note
    mount_delivery_note(app, gw, principal, delivery_note_worker)
    # One-tap "it all arrived" (#1304): a chef or approver's own observation, no stock change.
    from gateway.received import mount_received
    mount_received(app, gw, principal, body)
    from gateway.menu_photo import mount_menu_photo
    mount_menu_photo(app, gw, principal, menu_photo_worker)
    from gateway.price_list_photo import mount_price_list_photo   # a supplier's price list from a photo (#1174)
    mount_price_list_photo(app, gw, principal, price_list_worker)
    from gateway.label_photo import mount_label_photo   # a package's allergen label from a photo (#1175)
    mount_label_photo(app, gw, principal, label_photo_worker)

    # Remote MCP (#280): the same Buyer tools over HTTP at /mcp, agent token only.
    from gateway.mcp_http import mount_mcp
    mount_mcp(app)
    # Agent discovery (#293): /.well-known/agent-card.json and /llms.txt, built from this app.
    from gateway.discovery import mount_discovery
    mount_discovery(app)
    return app


def main() -> None:
    import uvicorn
    uvicorn.run("gateway.app:create_app", factory=True, host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")), access_log=False,
                # An open event stream (#711) must not hold a restart: after this long uvicorn
                # cancels what still runs, and the stream closes its change stream.
                timeout_graceful_shutdown=3)

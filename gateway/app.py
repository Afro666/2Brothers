"""HTTP gateway (FastAPI). Routes from docs/contract.md; logic lives in gateway/service.py.

Auth (demo): two bearer tokens from the server's environment.
- GATEWAY_AGENT_TOKEN: the Buyer agent and other services. Can read, propose and use the
  /tools routes. Can never approve.
- GATEWAY_HUMAN_TOKEN: the web app's signed-in person; `X-User` names who. Only this
  token may approve or reject (403 HUMAN_SESSION_REQUIRED otherwise).
Run: `two-brothers-gateway` (uvicorn on 0.0.0.0:8000). Never logs keys or bodies.
"""

from __future__ import annotations

import hmac
import os
import time
from decimal import InvalidOperation
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from gateway.service import Gateway, GatewayError

DEFAULT_KITCHEN = "demo-kitchen"


ALL_SCOPES = frozenset({"kitchen:read", "kitchen:propose"})


class Principal:
    """kind: human | agent | token. `kitchen_id` None = any kitchen (server env tokens)."""

    def __init__(self, kind: str, name: str, kitchen_id: str | None = None,
                 scopes: frozenset = ALL_SCOPES, role: str = "approver"):
        self.kind, self.name, self.kitchen_id, self.scopes = kind, name, kitchen_id, frozenset(scopes)
        self.role = role          # people only: approver, chef or viewer (#270)

    def need(self, scope: str, kitchen_id: str | None = None) -> None:
        """403 unless this caller holds `scope` for `kitchen_id`."""
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


def _token_matches(given: str, env: str) -> bool:
    expected = os.environ.get(env, "")
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def _env_principal(request: Request, token: str) -> Principal:
    # GATEWAY_REQUIRE_LOGIN=true: the shared human token stops working; people sign in (#270).
    require_login = os.environ.get("GATEWAY_REQUIRE_LOGIN", "").lower() == "true"
    if token and not require_login and _token_matches(token, "GATEWAY_HUMAN_TOKEN"):
        user = (request.headers.get("x-user") or "").strip()[:100]
        if not user:
            raise GatewayError(401, "UNAUTHENTICATED", "X-User names the person")
        return Principal("human", user)
    if token and _token_matches(token, "GATEWAY_AGENT_TOKEN"):
        return Principal("agent", "buyer-agent")
    raise GatewayError(401, "UNAUTHENTICATED", "a valid bearer token is required")


REFUSAL_WINDOW = 60.0          # seconds: one audit row per repeated refusal (#853)


def create_app(gateway: Gateway | None = None, *, buyer_worker=None, shelf_worker=None) -> FastAPI:
    app = FastAPI(
        title="Trusted Kitchen Buyer gateway", version="0.1.0",
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
        return get_swagger_ui_html(openapi_url="openapi.json", title="Trusted Kitchen Buyer gateway - API")
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
        gw()._audit(target, "refused", who.name, code=code, method=request.method, path=request.url.path)

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
            return Principal("human", person["email"], person["kitchen_id"], role=person["role"])
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        try:
            return _env_principal(request, token)
        except GatewayError:
            pass
        from gateway import tokens
        doc = tokens.verify(gw().db, token)
        if doc is None:
            raise GatewayError(401, "UNAUTHENTICATED", "a valid bearer token is required")
        return Principal("token", f"token:{doc['name']}", doc["kitchen_id"], frozenset(doc["scopes"]))

    app.state.verify_token = lambda token: __import__("gateway.tokens", fromlist=["verify"]).verify(gw().db, token)

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
        gw()._audit(person["kitchen_id"], "signed_in", person["email"])
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
        return {"kind": who.kind, "name": who.name, "role": who.role if who.kind == "human" else None,
                "kitchen_id": who.kitchen_id, "can_approve": who.kind == "human" and who.role == "approver",
                "scopes": sorted(who.scopes) if who.kind != "human" else None}

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
        gw()._audit(person["kitchen_id"], "password_changed", person["email"])
        return {"changed": True}

    @app.get("/.well-known/jwks.json")
    def jwks():
        """The public key that signs every offer (#290). No token needed: it is public."""
        from gateway import signing
        return signing.jwks(gw().db)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # ---- kitchen side -------------------------------------------------------------
    k = "/v1/kitchens/{kitchen_id}"

    @app.post(k + "/proposals")
    async def create_proposal(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose", kitchen_id)
        data = await body(request)
        if 'text' in data and 'product_ids' not in data:
            from gateway.buyer_worker import run_buyer
            try:
                return await (buyer_worker or run_buyer)(kitchen_id, data)
            except GatewayError as exc:
                # Fall back to the deterministic parser (#276) only when the Buyer is not
                # there at all. An ambiguous failure (it may have made a proposal) must be
                # reconciled first, never answered with a second proposal.
                not_configured = exc.code == "BUYER_UNAVAILABLE" and "fallback_safe" not in exc.extra
                if not (not_configured or exc.extra.get("fallback_safe") is True):
                    raise
        return gw().create_proposal(kitchen_id, data, who.name)

    @app.get(k + "/proposals")
    def list_proposals(kitchen_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return {"proposals": gw().list_proposals(kitchen_id)}

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
    def get_proposal(kitchen_id: str, proposal_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().get_proposal(kitchen_id, proposal_id)

    @app.get(k + "/proposals/{proposal_id}/addable")
    def addable(kitchen_id: str, proposal_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().addable(kitchen_id, proposal_id)

    @app.post(k + "/proposals/{proposal_id}/approve")
    async def approve(kitchen_id: str, proposal_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().approve(kitchen_id, proposal_id, await body(request), human=who.human)

    @app.post(k + "/proposals/{proposal_id}/reject")
    async def reject(kitchen_id: str, proposal_id: str, request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return gw().reject(kitchen_id, proposal_id, await body(request), human=who.human)

    @app.post(k + "/proposals/{proposal_id}/choose-option")
    async def choose_option(kitchen_id: str, proposal_id: str, request: Request,
                            who: Principal = Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        from gateway import options
        return options.choose(gw(), kitchen_id, proposal_id, await body(request), human=who.human)

    @app.post(k + "/recalls/{event_id}/dismiss")
    async def dismiss_recall(kitchen_id: str, event_id: str, request: Request, who: Principal = Depends(principal)):
        who.need('kitchen:read', kitchen_id)
        return gw().dismiss_recall(kitchen_id, event_id, await body(request), human=who.human)

    @app.post(k + "/needs")
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
        return {"tokens": tokens.list_tokens(gw().db, kitchen_id)}

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
        return {"webhooks": webhooks.list_hooks(gw().db, kitchen_id), "events": list(webhooks.EVENTS)}

    @app.delete(k + "/webhooks/{webhook_id}")
    def delete_webhook(kitchen_id: str, webhook_id: str, who: Principal = Depends(principal)):
        from gateway import webhooks
        person = hook_admin(who, kitchen_id)
        out = webhooks.delete(gw().db, kitchen_id, webhook_id)
        if out is None:
            raise GatewayError(404, "WEBHOOK_NOT_FOUND", "no such webhook")
        gw()._audit(kitchen_id, "webhook_deleted", person, webhook_id=webhook_id)
        return {**out, "deleted": True}

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

    @app.post("/tools/search_products")
    async def search(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:read")
        data = await body(request)
        limit = data.get("limit", 20)
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise GatewayError(422, "INVALID_REQUEST", "limit: 1 to 50")
        need_id = data.get("need_id")
        if need_id is not None and not isinstance(need_id, str):
            raise GatewayError(422, "INVALID_REQUEST", "need_id must be a string")
        return gw().tool_search(kitchen(who), data.get("query") or "", data.get("filters") or {}, limit, need_id)

    @app.post("/tools/get_offer")
    async def get_offer(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return gw().tool_get_offer(kitchen(who), await body(request))

    @app.post("/tools/simulate_order")
    async def simulate(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return gw().tool_simulate(kitchen(who), await body(request))

    @app.post("/tools/request_approval")
    async def request_approval(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return gw().tool_request_approval(kitchen(who), await body(request), who.name)

    @app.post("/tools/place_order")
    async def place_order(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        return gw().tool_place_order(kitchen(who), await body(request))

    @app.get("/tools/get_order_status")
    def order_status(order_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read")
        order = gw().get_order(kitchen(who), order_id)
        return {"order_id": order["order_id"], "status": order["status"], "outcome": order["outcome"]}

    @app.get("/tools/get_audit_log")
    def audit_tool(run_id: str, who: Principal = Depends(principal)):
        who.need("kitchen:read")
        from store.audit import list_events
        return {"events": [e["event"] for e in list_events(gw().db, run_id=run_id, kitchen_id=kitchen(who))]}

    @app.post("/audit/events")
    async def audit_ingest(request: Request, who: Principal = Depends(principal)):
        who.need("kitchen:propose")
        from store.audit import AuditConflict, append_event
        event = await body(request)
        try:
            entry = append_event(gw().db, event, {"kitchen_id": kitchen(who), "principal": who.name,
                                                      "at": gw().now().isoformat()})
        except AuditConflict:
            raise GatewayError(409, "IDEMPOTENCY_CONFLICT", "event_id reused with other content") from None
        return {"event_id": entry["event"]["event_id"], "stored": True}

    # Standing-order drift (#377): kitchen and supplier views.
    from gateway.drift_routes import mount_drift
    mount_drift(app, gw, principal)
    from gateway.supplier_routes import mount_supplier   # the wholesaler's demand view (#33)
    mount_supplier(app, gw, principal)
    from gateway.supplier_offers import mount_supplier_offers   # the selling agent's suggestions (#374)
    mount_supplier_offers(app, gw, principal, body)

    # Trust (#711): audit chain verify, the tamper demo, the live event stream.
    from gateway.trust_routes import mount_trust
    mount_trust(app, gw, principal, body)

    # Onboarding lookup (#375): Context.dev brand lookup for the sign-up form.
    from gateway.onboarding import mount_onboarding
    mount_onboarding(app, principal, body)

    # Recall list and "check now" (#358): views over the monitor's holds and replacements.
    from gateway.recalls_view import mount_recalls
    mount_recalls(app, gw, principal, body)

    # Kitchen planning routes (#74): stock, products, recipes, menu plans, suppliers, demand.
    from gateway.kitchen_routes import register as register_kitchen_routes
    register_kitchen_routes(app, gw, principal, body)

    # Count from a shelf photo (#373): Nemotron VL reads it in the worker; stores no count.
    from gateway.stock_photo import mount_stock_photo
    mount_stock_photo(app, gw, principal, shelf_worker)

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

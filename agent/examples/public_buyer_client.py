"""Buyer gateway client; running this file makes live proposal-flow writes.

Public references: /llms.txt and /gateway/openapi.json on the site below.
Set BUYER_TOKEN and BUYER_KITCHEN_ID in the environment before running.
buyer-state.json guards against duplicate runs. Never delete it to retry an
uncertain write: first reconcile through the documented proposal list/detail
or audit reads. This client deliberately performs no automatic retries.
"""

import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


BASE = "https://31-22-104-201.sslip.io/gateway"
STATE = Path("buyer-state.json")


class ClientError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer credential to a redirect destination.
        return None


def require_id(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ClientError("Gateway response lacks a documented identifier; reconcile state.")
    return value


def main():
    if STATE.exists():
        raise ClientError(
            "A previous run exists in buyer-state.json. Reconcile it before any new writes; "
            "this client will not repeat the flow."
        )
    token = os.environ.get("BUYER_TOKEN")
    kitchen = os.environ.get("BUYER_KITCHEN_ID")
    if not token or not kitchen:
        raise ClientError("Set BUYER_TOKEN and BUYER_KITCHEN_ID at runtime.")

    opener = urllib.request.build_opener(NoRedirect())
    state = {"run_id": str(uuid.uuid4()), "stage": "starting"}
    # Exclusive creation also prevents two invocations from starting together.
    with STATE.open("x", encoding="utf-8") as handle:
        json.dump(state, handle)

    def save(stage, **fields):
        state.update(fields)
        state["stage"] = stage
        # Only locally generated keys and documented IDs are persisted; no token.
        with STATE.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)

    def request(method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        try:
            req = urllib.request.Request(
                BASE + path, data=data, method=method,
                headers={"Authorization": "Bearer " + token,
                         "Accept": "application/json", "Content-Type": "application/json"},
            )
            with opener.open(req, timeout=45) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise ClientError("Unexpected gateway response; reconcile state before retrying.")
            return result
        except urllib.error.HTTPError as exc:
            # Do not expose server bodies, headers, URLs, or exception strings.
            raise ClientError(
                "Gateway returned HTTP %d. No retry was made; reconcile state." % exc.code
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ClientError(
                "Gateway transport or JSON failure. Outcome may be uncertain; "
                "read gateway state before retrying."
            ) from None

    def post(stage, path, body):
        key = state["run_id"] + ":" + stage
        save(stage + "_in_flight", idempotency_key=key)
        return request("POST", path, dict(body, idempotency_key=key))

    request("GET", "/v1/me")
    kitchen_path = "/v1/kitchens/" + urllib.parse.quote(kitchen, safe="")
    need = post("create_need", kitchen_path + "/needs", {
        "quantity": "1000", "unit": "L", "requested_date": "2026-11-16",
        "text": "1,000 L of lactose-free milk, delivery by Monday 2026-11-16",
    })
    need_id = require_id(need, "need_id")
    save("need_created", need_id=need_id)
    search = request("POST", "/tools/search_products", {
        "query": "lactose-free milk", "need_id": need_id, "filters": {}, "limit": 20,
    })
    products = search.get("products")
    if not isinstance(products, list):
        raise ClientError("Search response has no documented products list.")
    # Search defines relevance; need_id limits products to the stored measure.
    # Only explicitly on-time candidates are submitted. Unknown is not on-time.
    ids = list(dict.fromkeys(
        require_id(p, "product_id") for p in products
        if isinstance(p, dict) and p.get("can_arrive") is True
    ))
    if not ids:
        save("no_on_time_candidates")
        raise ClientError("No search candidates explicitly can arrive by 2026-11-16; no proposal created.")
    offer = post("get_offer", "/tools/get_offer", {"need_id": need_id, "product_ids": ids})
    offer_id = require_id(offer, "offer_id")
    save("offer_created", offer_id=offer_id)
    simulation = post("simulate_order", "/tools/simulate_order", {"offer_id": offer_id})
    mandate = simulation.get("mandate")
    if not isinstance(mandate, dict) or not isinstance(mandate.get("reasons"), list):
        raise ClientError("Simulation lacks documented mandate/reasons; no proposal requested.")
    verdict = mandate.get("verdict")
    report = {"need_id": need_id, "offer_id": offer_id, "verdict": verdict,
              "reasons": mandate["reasons"], "expected_total": simulation.get("expected_total"),
              "excluded": simulation.get("excluded", [])}
    if verdict == "REFUSED":
        save("refused")
        report.update(proposal_id=None, status="REFUSED")
    elif verdict == "NEEDS_APPROVAL":
        proposal = post("request_approval", "/tools/request_approval", {"offer_id": offer_id})
        proposal_id = require_id(proposal, "proposal_id")
        save("proposal_created", proposal_id=proposal_id)
        if proposal.get("status") != "PENDING":
            raise ClientError("Unexpected proposal status; reconcile the saved proposal ID.")
        report.update(proposal_id=proposal_id, status=proposal["status"])
    else:
        raise ClientError("Unrecognized mandate verdict; no proposal requested.")
    # Defensive redaction if a server ever echoes a credential in report fields.
    print(json.dumps(report, ensure_ascii=True, indent=2).replace(token, "[REDACTED]"))


if __name__ == "__main__":
    try:
        main()
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception:
        # Never emit tracebacks or arbitrary exception data containing credentials.
        print("Client failed; reconcile buyer-state.json before retrying.", file=sys.stderr)
        sys.exit(1)

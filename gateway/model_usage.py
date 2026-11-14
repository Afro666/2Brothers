"""Model usage route (#365). Contract: docs/contract.md, "Model usage".

- GET /v1/kitchens/{kitchen_id}/model-usage (`kitchen:read`): how much the Buyer agent
  used its model for this kitchen. A thin wrapper over `store.agent_runs.usage_totals`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI

from store import agent_runs

MODEL = "nemotron-3.5-super-vl"     # the same value as `buyer_model` on a proposal answer (agent/service.py)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:       # a client without `tz_aware` reads UTC as a naive datetime
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def model_usage(db, kitchen_id: str) -> dict:
    totals = agent_runs.usage_totals(db, kitchen_id)
    return {"model": MODEL, "since": _iso(totals["since"]),
            "runs": totals["runs"], "finished_runs": totals["finished_runs"],
            "runs_without_usage": totals["runs_without_usage"],
            "model_calls": totals["calls"], "prompt_tokens": totals["prompt_tokens"],
            "completion_tokens": totals["completion_tokens"],
            "reasoning_tokens": totals["reasoning_tokens"],
            "model_seconds": f"{totals['seconds']:.1f}",
            "last_run_at": _iso(totals["last_run_at"])}


def mount_model_usage(app: FastAPI, gw, principal) -> None:
    @app.get("/v1/kitchens/{kitchen_id}/model-usage")
    def usage(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return model_usage(gw().db, kitchen_id)

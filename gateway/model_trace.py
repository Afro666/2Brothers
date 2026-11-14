"""What the model did (#1197, docs/contract.md "What the model did: `model_trace`").

A trace holds counts and codes: which tool the model asked for, a cleaned summary of its
arguments, how many rows came back, the verdict or reason code. It never holds a key, the
system prompt, text the model wrote, a price, a quantity or another kitchen's data.
`build` makes one from a run; `clean` checks one that came from outside (a supplier).
"""

from __future__ import annotations

import math
import re

MODEL = "nemotron-3.5-super-vl"
MAX_STEPS = 40
QUERY_MAX = 60
MODEL_MAX = 100
BUYER_TOOLS = ("search_products", "get_offer", "simulate_order", "request_approval", "place_order",
               "get_order_status", "get_audit_log")
TOOLS = BUYER_TOOLS + ("invalid", "shortlist", "pick")
READERS = ("buyer", "parser", "seller")
MADE_BY = ("model", "rule")
BY = ("model", "code")
COUNTS = ("calls", "failed", "prompt_tokens", "completion_tokens", "reasoning_tokens")
STEP_INTS = ("products", "count")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,39}")
_NOT_QUERY = re.compile(r"[^\w\s-]|_")


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _seconds(value) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    return round(float(value), 3) if ok else 0


def clean_query(value) -> str | None:
    """The search words: letters, digits, spaces and `-` only, at most 60 characters."""
    if not isinstance(value, str):
        return None
    text = " ".join(_NOT_QUERY.sub("", value).split())[:QUERY_MAX].strip()
    return text or None


def step(tool: str, *, by: str = "model", attempt: int = 1, query=None, products=None, count=None,
         code=None) -> dict:
    out = {"by": by if by in BY else "code", "attempt": attempt if attempt in (1, 2) else 1,
           "tool": tool if tool in TOOLS else "invalid"}
    if out["tool"] == "search_products" and clean_query(query):
        out["query"] = clean_query(query)
    for key, value in (("products", products), ("count", count)):
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            out[key] = value
    if isinstance(code, str) and _CODE.fullmatch(code):
        out["code"] = code
    return out


def build(*, reader: str, made_by: str, usage: dict | None = None, thinking=None, steps=(),
          attempts: int = 1, model: str | None = MODEL) -> dict:
    usage = usage if isinstance(usage, dict) else {}
    steps = list(steps)
    return {"made_by": made_by, "reader": reader, "model": model,
            "thinking": thinking if isinstance(thinking, bool) else None,
            **{key: _count(usage.get(key)) for key in COUNTS},
            "seconds": _seconds(usage.get("seconds")), "attempts": attempts,
            "truncated": len(steps) > MAX_STEPS, "steps": steps[:MAX_STEPS]}


def parser_trace() -> dict:
    """The gateway's parser read the request: no model ran, so no steps."""
    return build(reader="parser", made_by="rule", model=None, attempts=0)


def _int(value, name: str, top: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or (top is not None and value > top):
        raise ValueError(f"model_trace.{name}: a whole number of 0 or more")
    return value


def _clean_step(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("model_trace.steps: each step is an object")
    if raw.get("tool") not in TOOLS or raw.get("by", "model") not in BY:
        raise ValueError("model_trace.steps: unknown tool or by")
    out = {"by": raw.get("by", "model"), "attempt": _int(raw.get("attempt", 1), "attempt", 2) or 1,
           "tool": raw["tool"]}
    if "query" in raw:
        query = clean_query(raw["query"])
        if raw["tool"] != "search_products" or query is None or query != raw["query"]:
            raise ValueError("model_trace.steps.query: only on search_products, cleaned search words")
        out["query"] = query
    for key in STEP_INTS:
        if key in raw:
            out[key] = _int(raw[key], "steps." + key)
    if "code" in raw:
        if not isinstance(raw["code"], str) or not _CODE.fullmatch(raw["code"]):
            raise ValueError("model_trace.steps.code: a code such as NEEDS_APPROVAL")
        out["code"] = raw["code"]
    return out


def clean(value) -> dict:
    """A trace from outside, checked: only the contract's fields; ValueError when one is wrong."""
    if not isinstance(value, dict):
        raise ValueError("model_trace: an object")
    if value.get("made_by") not in MADE_BY or value.get("reader") not in READERS:
        raise ValueError("model_trace: made_by model or rule; reader buyer, parser or seller")
    model = value.get("model")
    if model is not None and (not isinstance(model, str) or not 0 < len(model) <= MODEL_MAX):
        raise ValueError("model_trace.model: a model name or null")
    thinking = value.get("thinking")
    if thinking is not None and not isinstance(thinking, bool):
        raise ValueError("model_trace.thinking: true, false or null")
    seconds = value.get("seconds", 0)
    if (not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds)
            or seconds < 0):
        raise ValueError("model_trace.seconds: a number of 0 or more")
    truncated = value.get("truncated", False)
    if not isinstance(truncated, bool):
        raise ValueError("model_trace.truncated: true or false")
    steps = value.get("steps", [])
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ValueError(f"model_trace.steps: a list of at most {MAX_STEPS}")
    return {"made_by": value["made_by"], "reader": value["reader"], "model": model, "thinking": thinking,
            **{key: _int(value.get(key, 0), key) for key in COUNTS},
            "seconds": round(float(seconds), 3), "attempts": _int(value.get("attempts", 1), "attempts", 2),
            "truncated": truncated, "steps": [_clean_step(raw) for raw in steps]}


def stored(value) -> dict | None:
    """A stored trace as it is served: checked again, None when it does not pass."""
    if value is None:
        return None
    try:
        return clean(value)
    except ValueError:
        return None

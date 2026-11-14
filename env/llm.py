"""LLM buyer for Kitchen Week (issue #120).

    python -m env.run --policy llm-deepseek --seed 1
    python -m env.run --policy llm-kimi --seeds 5 --kitchen hotel

On each day with a delivery tomorrow the model gets the observation JSON and must
answer with one JSON action. No tools, no memory between days: everything it needs is
in the observation. Transcripts go to env/out/llm/ (git-ignored). Standard library
only; keys come from the environment or the repo's .env and are never logged.
"""

import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

VERDA = "https://inference.verda.com/v1"
NEMOTRON = "https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1"
MODELS = {  # name: (base url, key variable, model id, extra request fields)
    "deepseek": (VERDA, "VERDA_API_KEY", "deepseek-4-1-flash-1017", {}),
    "kimi": (VERDA, "VERDA_API_KEY", "kimi-k3-1-pro", {}),
    "nemotron": (NEMOTRON, "VERDA_INFERENCE_KEY", "nemotron-3.5-super-vl", {}),
    # Same model with thinking off; `/no_think` and reasoning budgets are ignored here.
    "nemotron-nothink": (NEMOTRON, "VERDA_INFERENCE_KEY", "nemotron-3.5-super-vl",
                         {"chat_template_kwargs": {"enable_thinking": False}}),
}

SYSTEM = """You are the purchasing agent of a professional kitchen in Finland that buys from
the wholesaler Valio Aimo. Each afternoon you decide what to order for tomorrow's delivery.

Units: stock, lots and recipes are in the product's kitchen unit (L, KG or PCS). Orders are
in whole sales units; one sales unit holds `pack` kitchen units and costs `price_eur`.
Expected use of a product on a day = forecast covers x quantity per cover in each recipe on
that day's menu (recipe shares: main dishes and sides as listed). Stock is used oldest
first; a lot is thrown away after its `last_day`. Deliveries only happen on
`delivery_weekdays` (0 = Monday); what you order now arrives tomorrow at 06:00.

Score for the week = revenue from guests served - food eaten - food thrown away - leftover
stock at the end - delivery fees - penalties. A guest is lost when a key ingredient of the
dish is missing, which costs far more than the ingredient. Read `valio_notices`: Valio
cannot deliver those products on those dates.

Mandate: an order total over `auto_limit_eur` needs "request_approval": true; never send
one over `hard_cap_eur`. An order under `mov_eur` pays `delivery_fee_eur`. Only order
products listed in `products`.

Answer with only one JSON object, no prose:
{"order": {"<product_id>": <whole sales units>, ...}, "request_approval": <true|false>}
Use {"order": {}} to order nothing."""


def _load_key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    root = Path(__file__).resolve().parent.parent
    candidates = [root / ".env"]
    try:  # a git worktree: also look in the main checkout
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        if common:
            candidates.append((root / common).resolve().parent / ".env")
    except (OSError, subprocess.SubprocessError):
        pass
    for env in candidates:
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith(name + "="):
                    value = line.split("=", 1)[1].strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    return value
    raise RuntimeError(f"{name} is not set (environment or .env)")


def _units(value):
    """A model's quantity -> whole units, or None when it is not a finite number.
    Booleans are not quantities (in Python, True == 1)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number)


def parse_action(text: str, products) -> tuple:
    """Model text -> (action, problem or None). Never trusts the model's types."""
    text = text or ""
    if "{" not in text:
        return {}, "no JSON object"
    # Decode every top-level JSON object (prose and fences may hold braces too);
    # the last one with an "order" key is the answer, else the last object.
    decoder, found, pos = json.JSONDecoder(), [], text.find("{")
    while pos != -1:
        try:
            obj, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        pos = text.find("{", end)
    if not found:
        return {}, "invalid JSON"
    raw = next((o for o in reversed(found) if "order" in o), found[-1])
    if not isinstance(raw, dict):
        return {}, "not an object"
    raw_order = raw.get("order")
    if raw_order is None:
        raw_order = {}
    if not isinstance(raw_order, dict):
        return {}, "order is not an object"
    order, problems = {}, []
    for pid, units in raw_order.items():
        n = _units(units)
        if n is None:
            problems.append(f"invalid quantity for {pid}")
            continue
        if n != float(units):
            problems.append(f"fractional quantity for {pid} rounded down")
        if n > 0:
            order[str(pid)] = n
    unknown = [p for p in order if p not in products]
    if unknown:
        problems.append(f"unknown products {unknown}")  # kept: the env refuses and penalises them
    return ({"order": order, "request_approval": raw.get("request_approval") is True},
            "; ".join(problems) or None)


class LLMPolicy:
    # Reasoning models think before they answer: at 4k tokens Kimi returned empty content,
    # at 16k Nemotron did; Nemotron needs ~20k (one call took 20.5k tokens, 42 s).
    def __init__(self, model: str, out: Path = Path("env/out/llm"), max_tokens: int = 64000):
        self.name = model
        self.base, self.key_name, self.model, self.extra = MODELS[model]
        self.out, self.max_tokens = out, max_tokens
        self.key = None
        self.log = None

    # run.py calls begin/end around each episode
    def begin(self, env) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / f"{self.name}-{env.kitchen_type}-seed{env.seed}.jsonl"
        self.log = open(path, "w", encoding="utf-8", newline="\n")
        self.calls = self.tokens = self.problems = 0

    def end(self, env) -> None:
        if self.log:
            # finished is False when the episode raised mid-week (run.py ends it in a finally)
            self._write({"finished": env.today >= env.end, "report": env.report(), "events": env.score.events,
                         "calls": self.calls, "tokens": self.tokens, "problems": self.problems})
            self.log.close()
            self.log = None

    def __call__(self, env, obs) -> dict:
        if not obs["order_for"]:
            return {}
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(obs, separators=(",", ":"))}]
        self.finish = None
        text, usage = self._complete(messages)
        action, problem = parse_action(text, obs["products"])
        if self.finish == "length":
            problem = "ran out of tokens" + (f"; {problem}" if problem else "")
        self.calls += 1
        self.tokens += usage
        self.problems += problem is not None
        self._write({"today": obs["today"], "order_for": obs["order_for"], "observation": obs,
                     "reply": text, "finish_reason": self.finish, "action": action, "problem": problem})
        return action

    def _write(self, row) -> None:
        if self.log:
            line = json.dumps(row, ensure_ascii=False)
            if self.key:  # the model could echo anything; never persist the key
                for form in {self.key, json.dumps(self.key, ensure_ascii=False)[1:-1]}:
                    line = line.replace(form, "[REDACTED]")
            self.log.write(line + "\n")
            self.log.flush()

    def _complete(self, messages) -> tuple:
        if self.key is None:
            self.key = _load_key(self.key_name)
        body = json.dumps({"model": self.model, "messages": messages, "temperature": 0,
                           "max_tokens": self.max_tokens, **self.extra}).encode()
        for attempt in range(4):
            req = urllib.request.Request(
                self.base + "/chat/completions", data=body, method="POST",
                headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                         "User-Agent": "2brothers-kitchenweek/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    d = json.load(r)
                self.finish = d["choices"][0].get("finish_reason")
                return (d["choices"][0]["message"].get("content") or "",
                        d.get("usage", {}).get("total_tokens", 0))
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500 or attempt == 3:
                    raise RuntimeError(f"{self.model}: HTTP {e.code}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise RuntimeError(f"{self.model}: network error") from None
            time.sleep(2 ** attempt)


LLM_POLICIES = {f"llm-{m}": (lambda m=m: LLMPolicy(m)) for m in MODELS}

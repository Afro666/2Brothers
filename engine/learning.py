"""Pure learned facts from chef corrections and delivery observations (#1305-#1307)."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median


_WEEKS = timedelta(weeks=8)
_RATIO_MIN = Decimal("0.3")
_RATIO_MAX = Decimal("1.5")
_NO_CHANGE_LOW = Decimal("0.95")
_NO_CHANGE_HIGH = Decimal("1.05")
_RATIO_KINDS = {"qty_changed", "line_removed"}
_RATIO_REASONS = {"TOO_MUCH", "TOO_LITTLE"}
_DECLINE_REASONS = {"TOO_MUCH", "OTHER", None}


def _number(value) -> Decimal | None:
    """Trust JSON-like numbers and decimal strings, but never booleans or non-finite values."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _finite_float(value) -> float | None:
    """Convert a finite Decimal to a finite JSON number."""
    number = _number(value)
    if number is None:
        return None
    try:
        result = float(number)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date(value) -> date | None:
    """Read an ISO calendar date or timestamp without consulting a clock or timezone database."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None


def _in_window(when: date, today: date) -> bool:
    return today - _WEEKS <= when <= today


def _scoped_rows(rows, kitchen_id, product_id):
    for index, row in enumerate(rows or []):
        if not isinstance(row, dict) or row.get("product_id") != product_id:
            continue
        kitchen = row.get("kitchen_id")
        if kitchen is not None and kitchen != kitchen_id:
            continue
        yield index, row


def _feedback_identity(row: dict) -> str:
    feedback_id = row.get("feedback_id")
    if feedback_id is not None and feedback_id != "":
        return f"feedback:{feedback_id}"
    parts = (row.get("proposal_id"), row.get("ts"), row.get("kind"),
             row.get("product_id"), row.get("from_qty"), row.get("to_qty"))
    return "feedback:" + "|".join("" if part is None else str(part) for part in parts)


def _evidence(when: list[date], rows: int) -> dict:
    first, last = min(when), max(when)
    return {"rows": rows, "from": first.isoformat(), "to": last.isoformat(),
            "last": last.isoformat()}


def correction_ratio_fact(kitchen_id, product_id, name, rows, today, algo="v1") -> dict | None:
    """Learn a median correction against the trusted unlearned forecast, not the shown quantity."""
    day = _date(today)
    if day is None:
        return None

    qualifying: list[tuple[date, int, Decimal, dict]] = []
    for index, row in _scoped_rows(rows, kitchen_id, product_id):
        kind = row.get("kind")
        if kind not in _RATIO_KINDS or row.get("reason") not in _RATIO_REASONS:
            continue
        if row.get("approved") is not True:
            continue
        when = _date(row.get("ts"))
        if when is None or not _in_window(when, day):
            continue
        outcome = row.get("outcome")
        if isinstance(outcome, dict) and outcome.get("ran_out") is True:
            continue
        context = row.get("context")
        if not isinstance(context, dict):
            continue
        need = _number(context.get("forecast_need"))
        if need is None or need <= 0:
            continue
        if kind == "line_removed":
            ratio = Decimal(0)
        else:
            to_qty = _number(row.get("to_qty"))
            if to_qty is None:
                continue
            ratio = to_qty / need
        if not ratio.is_finite():
            continue
        qualifying.append((when, index, ratio, row))

    if len(qualifying) < 3:
        return None
    qualifying.sort(key=lambda item: (item[0], item[1]))
    recent = qualifying[-8:]
    raw = median([item[2] for item in recent])
    if raw < _NO_CHANGE_LOW or raw > _NO_CHANGE_HIGH:
        raw_value = _finite_float(raw)
        value = _finite_float(min(_RATIO_MAX, max(_RATIO_MIN, raw)))
        if raw_value is None or value is None:
            return None
        evidence = _evidence([item[0] for item in recent], len(recent))
        ids = [_feedback_identity(item[3]) for item in recent]
        return {
            "id": fact_id(kitchen_id, "CORRECTION_RATIO", product_id, algo, ids),
            "kind": "CORRECTION_RATIO",
            "product_id": product_id,
            "supplier_id": None,
            "name": name,
            "value": value,
            "raw_value": raw_value,
            "applicable": _RATIO_MIN <= raw <= _RATIO_MAX,
            "evidence": evidence,
            # The first day of this evidence version: the newest row that formed it, so
            # the same evidence gives the same `since` every day (contract, "Learned facts").
            "since": evidence["last"],
            "active": True,
        }
    return None


def declined_product_fact(kitchen_id, product_id, name, rows, today, algo="v1") -> dict | None:
    """Count repeated removals after the latest explicit addition, which resets the history."""
    day = _date(today)
    if day is None:
        return None

    ordered: list[tuple[date, int, dict]] = []
    for index, row in _scoped_rows(rows, kitchen_id, product_id):
        when = _date(row.get("ts"))
        if when is not None:
            ordered.append((when, index, row))
    ordered.sort(key=lambda item: (item[0], item[1]))

    removals: list[tuple[date, dict]] = []
    for when, _, row in ordered:
        if row.get("kind") == "line_added":
            removals = []
        elif row.get("kind") == "line_removed" and row.get("reason") in _DECLINE_REASONS:
            removals.append((when, row))
    if len(removals) < 3:
        return None

    ids = [_feedback_identity(row) for _, row in removals]
    evidence = _evidence([when for when, _ in removals], len(removals))
    return {
        "id": fact_id(kitchen_id, "DECLINED_PRODUCT", product_id, algo, ids),
        "kind": "DECLINED_PRODUCT",
        "product_id": product_id,
        "supplier_id": None,
        "name": name,
        "value": 1,
        "evidence": evidence,
        "since": evidence["last"],
        "active": True,
    }


def _revision(value) -> int:
    number = _number(value)
    if number is None or number < 0 or number != number.to_integral_value():
        return 0
    return int(number)


def _current_observations(observations, kitchen_id) -> list[dict]:
    current: dict[str, tuple[int, int, dict]] = {}
    for index, observation in enumerate(observations or []):
        if not isinstance(observation, dict):
            continue
        kitchen = observation.get("kitchen_id")
        if kitchen is not None and kitchen != kitchen_id:
            continue
        order_id = observation.get("order_id")
        if order_id is None or order_id == "":
            continue
        revision = _revision(observation.get("revision"))
        key = str(order_id)
        previous = current.get(key)
        if previous is None or revision >= previous[0]:
            current[key] = (revision, index, observation)
    return list(current.values())


def _observation_date(observation: dict) -> date | None:
    return _date(observation.get("delivery_date")) or _date(observation.get("checked_at"))


def _line_supplier(line: dict, order_supplier):
    supplier = line.get("supplier_id")
    return order_supplier if supplier is None else supplier


def _supplier_lines(observation: dict, supplier_id) -> list[dict]:
    top = observation.get("supplier_id")
    lines = observation.get("lines")
    if not isinstance(lines, list):
        return []
    return [line for line in lines
            if isinstance(line, dict) and _line_supplier(line, top) == supplier_id]


def _belongs_to_supplier(observation: dict, supplier_id) -> bool:
    if observation.get("supplier_id") == supplier_id:
        return True
    return bool(_supplier_lines(observation, supplier_id))


def _order_identity(observation: dict, revision: int) -> str:
    return f"order:{observation.get('order_id')}:{revision}"


def _lead_times(observations: list[dict]) -> list[int]:
    values = []
    for observation in observations:
        delivered = _date(observation.get("delivery_date"))
        ordered = _date(observation.get("ordered_at"))
        if delivered is None or ordered is None:
            continue
        days = (delivered - ordered).days
        if days >= 0:
            values.append(days)
    return values


def supplier_facts(kitchen_id, supplier_id, name, observations, today, algo="v1") -> list[dict]:
    """Build delivery lateness and fill facts from one current observation per order."""
    day = _date(today)
    if day is None:
        return []

    eligible = []
    for revision, index, observation in _current_observations(observations, kitchen_id):
        when = _observation_date(observation)
        if when is None or not _in_window(when, day):
            continue
        if not _belongs_to_supplier(observation, supplier_id):
            continue
        eligible.append((when, index, revision, observation))
    if len(eligible) < 5:
        return []
    eligible.sort(key=lambda item: (item[0], item[1]))

    evidence = _evidence([item[0] for item in eligible], len(eligible))
    identities = [_order_identity(item[3], item[2]) for item in eligible]
    current = [item[3] for item in eligible]
    facts = []

    known_lateness = []
    for observation in current:
        days_late = _number(observation.get("days_late"))
        if days_late is not None:
            known_lateness.append(days_late)
    if known_lateness:
        on_time = sum(1 for days_late in known_lateness if days_late <= 0)
        on_time_rate = Decimal(on_time) / Decimal(len(known_lateness))
        late_values = [days_late for days_late in known_lateness if days_late > 0]
        mean_days_late = (sum(late_values, Decimal(0)) / Decimal(len(late_values))
                          if late_values else Decimal(0))
        rate_value = _finite_float(on_time_rate)
        late_value = _finite_float(mean_days_late)
        if rate_value is not None and late_value is not None:
            lead_times = _lead_times(current)
            if lead_times:
                mean_lead = sum(lead_times) / len(lead_times)
                variance = sum((value - mean_lead) ** 2 for value in lead_times) / len(lead_times)
                sigma_lead = math.sqrt(max(variance, 0.0))
                if not math.isfinite(mean_lead) or not math.isfinite(sigma_lead):
                    mean_lead = sigma_lead = None
            else:
                mean_lead = sigma_lead = None
            facts.append({
                "id": fact_id(kitchen_id, "SUPPLIER_LATE", supplier_id, algo, identities),
                "kind": "SUPPLIER_LATE",
                "product_id": None,
                "supplier_id": supplier_id,
                "name": name,
                "value": late_value,
                "mean_days_late": late_value,
                "on_time_rate": rate_value,
                "deliveries": len(eligible),
                "mean_lead_time": mean_lead,
                "sigma_lead_time": sigma_lead,
                "evidence": evidence,
                "since": evidence["last"],
                "active": True,
            })

    ordered_total = Decimal(0)
    delivered_total = Decimal(0)
    usable_lines = 0
    for observation in current:
        for line in _supplier_lines(observation, supplier_id):
            ordered = _number(line.get("ordered"))
            delivered = _number(line.get("delivered"))
            if ordered is None or delivered is None or ordered <= 0:
                continue
            ordered_unit = line.get("ordered_unit", line.get("unit"))
            delivered_unit = line.get("delivered_unit", line.get("unit"))
            if ordered_unit is None or delivered_unit is None or ordered_unit != delivered_unit:
                continue
            ordered_total += ordered
            delivered_total += delivered
            usable_lines += 1
    if usable_lines and ordered_total > 0:
        fill_rate = min(Decimal(1), max(Decimal(0), delivered_total / ordered_total))
        fill_value = _finite_float(fill_rate)
        if fill_value is not None:
            facts.append({
                "id": fact_id(kitchen_id, "SUPPLIER_SHORT", supplier_id, algo, identities),
                "kind": "SUPPLIER_SHORT",
                "product_id": None,
                "supplier_id": supplier_id,
                "name": name,
                "value": fill_value,
                "fill_rate": fill_value,
                "evidence": evidence,
                "since": evidence["last"],
                "active": True,
            })
    return facts


def _identity(value) -> str:
    if isinstance(value, dict):
        feedback_id = value.get("feedback_id")
        if feedback_id is not None and feedback_id != "":
            return f"feedback:{feedback_id}"
        order_id = value.get("order_id")
        if order_id is not None and order_id != "":
            return f"order:{order_id}:{_revision(value.get('revision'))}"
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    if isinstance(value, (list, tuple)):
        return "order:" + ":".join(_identity(part) for part in value)
    return str(value)


def fact_id(kitchen_id, kind, entity_id, algo, evidence_ids) -> str:
    """Hash only identity and evidence, so page reads and clocks cannot create a version."""
    if isinstance(evidence_ids, (str, dict)):
        evidence_ids = [evidence_ids]
    identities = sorted({_identity(value) for value in evidence_ids or []})
    payload = json.dumps([str(kitchen_id), str(kind), str(entity_id), str(algo), identities],
                         ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).digest()[:16]
    token = base64.b32encode(digest).decode("ascii").rstrip("=")
    return f"lf_{token}"


def _decimal_string(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def apply_ratio(need, fact, unit=None) -> tuple[Decimal, dict | None]:
    """Apply an active, in-band ratio and describe the adjustment for the plan line.

    When ``unit`` is given it is carried into the info dict, as the contract's
    ``learned`` object expects.
    """
    need_value = _number(need)
    if need_value is None or not isinstance(fact, dict):
        return need, None
    if fact.get("active") is not True or fact.get("applicable") is not True:
        return need_value, None
    if fact.get("kind") != "CORRECTION_RATIO":
        return need_value, None
    ratio = _number(fact.get("value"))
    if ratio is None or ratio <= 0:
        return need_value, None
    adjusted = need_value * ratio
    ratio_value = _finite_float(ratio)
    if not adjusted.is_finite() or ratio_value is None:
        return need_value, None
    evidence = fact.get("evidence")
    info = {
        "fact_id": fact.get("id"),
        "from_qty": _decimal_string(need_value),
        "to_qty": _decimal_string(adjusted),
        "ratio": ratio_value,
        "evidence": dict(evidence) if isinstance(evidence, dict) else evidence,
    }
    if unit is not None:
        info["unit"] = unit
    return adjusted, info

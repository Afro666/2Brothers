"""Pure learning rules for recurring chef corrections."""

from statistics import median


def _learnable(row: dict) -> bool:
    """A cut followed by a shortage is evidence against the cut, not a habit."""
    return not row.get("ran_out", False)


def correction_ratio(rows: list, product_id: str):
    """Learn a robust quantity multiplier only from repeated habitual corrections."""
    ratios = []
    for row in rows:
        if not _learnable(row) or row.get("product_id") != product_id:
            continue
        if row.get("kind") not in ("qty_changed", "line_removed"):
            continue
        if row.get("reason") not in ("TOO_MUCH", "TOO_LITTLE"):
            continue
        # Against the unlearned quantity (the product's stored forecast_need), so a correction
        # that was already applied is not learned again on top of itself.
        before = row.get("base_qty") or row.get("from_qty", 0)
        if before <= 0:
            continue
        ratios.append(0.0 if row["kind"] == "line_removed" else row["to_qty"] / before)
    if len(ratios) < 3:
        return None
    ratio = min(1.5, max(0.3, median(ratios[-8:])))
    return None if 0.95 <= ratio <= 1.05 else ratio


def declined(rows: list) -> set:
    """Stop proposing products the chef repeatedly removes, except for stock cuts."""
    removals = {}
    for row in rows:
        if not _learnable(row) or row.get("kind") != "line_removed":
            continue
        if row.get("reason") not in ("TOO_MUCH", "OTHER", None):
            continue
        pid = row["product_id"]
        removals[pid] = removals.get(pid, 0) + 1
    return {pid for pid, count in removals.items() if count >= 3}

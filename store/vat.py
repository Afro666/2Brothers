"""Give catalog rows loaded before #1603 their VAT fields, from the stored raw record.

    python -m store.vat            # counts what would change; writes nothing
    python -m store.vat --apply    # sets vat_code, vat_rate, vat_source (safe to run again)

It also rewrites a `vat_source` of the old free text ("Valio product data, vatCode") to the
enum of #1609: `catalog` when the rate is known, else null.

Only Valio catalog rows (`source: "valio"`) are read; own products keep the rate the kitchen
entered. The rule is `store.products.vat`: the same as a fresh `python -m store.loader`.
"""

from __future__ import annotations

import argparse

from store.products import VAT_SOURCE, vat

BATCH = 1000


def backfill(db, apply: bool = False) -> dict:
    """{checked, changed, known, unknown}. With `apply`, writes the changed rows: one
    `update_many` per VAT code and batch of codes (there are only a handful of codes)."""
    counts = {"checked": 0, "changed": 0, "known": 0, "unknown": 0}
    todo: dict[tuple, list] = {}
    fields = {"raw.synkkaData.vatCode": 1, "vat_code": 1, "vat_rate": 1, "vat_source": 1}
    for doc in db.products.find({"source": "valio"}, fields):
        counts["checked"] += 1
        code, rate = vat(((doc.get("raw") or {}).get("synkkaData") or {}).get("vatCode"))
        counts["known" if rate is not None else "unknown"] += 1
        want = {"vat_code": code, "vat_rate": rate, "vat_source": VAT_SOURCE if rate is not None else None}
        if any(key not in doc or doc[key] != value for key, value in want.items()):
            counts["changed"] += 1
            todo.setdefault((code, rate, want["vat_source"]), []).append(doc["_id"])
    if apply:
        for (code, rate, source), ids in todo.items():
            for start in range(0, len(ids), BATCH):
                db.products.update_many({"_id": {"$in": ids[start:start + BATCH]}, "source": "valio"},
                                        {"$set": {"vat_code": code, "vat_rate": rate, "vat_source": source}})
    return counts


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the fields (default: count only)")
    args = parser.parse_args(argv)
    from store.db import get_db
    counts = backfill(get_db(), apply=args.apply)
    print(f"{counts['checked']} catalog rows: {counts['known']} with a known VAT rate, "
          f"{counts['unknown']} unknown; {counts['changed']} "
          + ("changed" if args.apply else "would change (add --apply to write)"))


if __name__ == "__main__":
    main()

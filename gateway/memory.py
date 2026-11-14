"""What a kitchen calls things (Aron, 14 Nov): the tool remembers.

- An **alias** links a kitchen's own phrase ("house milk", "talon maito") to one product. A
  person sets it once; after that a request with that phrase goes to that product first.
- An **unknown item** is a phrase somebody asked for that matched nothing. It is kept with a
  count, so a person can link it to a product or add it as an own product later. Nothing is
  invented for it: no price, no unit, no allergens.

The pattern comes from Aron's food-logging app: confirmed items are remembered per user and
reused by name. Per kitchen here; another kitchen's words mean nothing to this one.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re

from fastapi import Depends, Request

MAX_PHRASE = 80


def normalise(phrase: str) -> str:
    """Lower case, punctuation to spaces, single spaces. Letters of any language stay."""
    text = re.sub(r"[^\w\s%]", " ", str(phrase or "").lower(), flags=re.UNICODE)
    return " ".join(text.replace("_", " ").split())[:MAX_PHRASE]


class MemoryError(ValueError):
    pass


def set_alias(db, kitchen_id: str, phrase: str, product_id: str, person: str) -> dict:
    key = normalise(phrase)
    if len(key) < 2:
        raise MemoryError("the phrase needs at least 2 characters")
    product = db.products.find_one({"_id": str(product_id)}, {"names": 1, "kitchen_id": 1, "source": 1})
    if product is None or (product.get("source") == "own" and product.get("kitchen_id") != kitchen_id):
        raise MemoryError("no such product for this kitchen")
    now = datetime.now(timezone.utc)
    db.kitchen_aliases.update_one(
        {"_id": f"{kitchen_id}:{key}"},
        {"$set": {"kitchen_id": kitchen_id, "phrase": key, "product_id": str(product_id),
                  "set_by": person, "set_at": now},
         "$setOnInsert": {"uses": 0}}, upsert=True)
    db.unknown_items.delete_one({"_id": f"{kitchen_id}:{key}"})      # it is known now
    return {"phrase": key, "product_id": str(product_id),
            "product_name": (product.get("names") or {}).get("en"), "set_by": person}


def remove_alias(db, kitchen_id: str, phrase: str) -> bool:
    return db.kitchen_aliases.delete_one({"_id": f"{kitchen_id}:{normalise(phrase)}"}).deleted_count == 1


def list_aliases(db, kitchen_id: str) -> list[dict]:
    rows = list(db.kitchen_aliases.find({"kitchen_id": kitchen_id}).sort("phrase", 1))
    names = {d["_id"]: (d.get("names") or {}).get("en")
             for d in db.products.find({"_id": {"$in": [r["product_id"] for r in rows]}}, {"names": 1})} if rows else {}
    return [{"phrase": r["phrase"], "product_id": r["product_id"], "product_name": names.get(r["product_id"]),
             "set_by": r.get("set_by"), "uses": r.get("uses", 0)} for r in rows]


def lookup(db, kitchen_id: str, query: str, *, count_use: bool = False) -> str | None:
    """The product this kitchen means by `query`: the whole query, or the longest alias phrase
    inside it ("house milk" in "1000 l house milk"). None when there is none."""
    key = normalise(query)
    if not key:
        return None
    hit = db.kitchen_aliases.find_one({"_id": f"{kitchen_id}:{key}"})
    if hit is None:
        padded = f" {key} "
        inside = [a for a in db.kitchen_aliases.find({"kitchen_id": kitchen_id})
                  if f" {a['phrase']} " in padded]
        hit = max(inside, key=lambda a: len(a["phrase"]), default=None)
    if hit is None:
        return None
    if count_use:
        db.kitchen_aliases.update_one({"_id": hit["_id"]}, {"$inc": {"uses": 1}})
    return hit["product_id"]


def note_unknown(db, kitchen_id: str, phrase: str) -> None:
    """Somebody asked for this and nothing matched: remember the words, never invent data."""
    key = normalise(phrase)
    if len(key) < 2:
        return
    now = datetime.now(timezone.utc)
    db.unknown_items.update_one({"_id": f"{kitchen_id}:{key}"},
                                {"$set": {"kitchen_id": kitchen_id, "phrase": key, "last_asked": now},
                                 "$setOnInsert": {"first_asked": now}, "$inc": {"times": 1}}, upsert=True)


def list_unknown(db, kitchen_id: str) -> list[dict]:
    return [{"phrase": r["phrase"], "times": r.get("times", 1),
             "first_asked": r["first_asked"].isoformat() if r.get("first_asked") else None,
             "last_asked": r["last_asked"].isoformat() if r.get("last_asked") else None}
            for r in db.unknown_items.find({"kitchen_id": kitchen_id}).sort("times", -1).limit(100)]


def forget_unknown(db, kitchen_id: str, phrase: str) -> bool:
    return db.unknown_items.delete_one({"_id": f"{kitchen_id}:{normalise(phrase)}"}).deleted_count == 1


def mount_memory(app, gw, principal, body) -> None:
    from gateway.service import GatewayError
    k = "/v1/kitchens/{kitchen_id}"

    @app.get(k + "/aliases")
    def aliases(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return {"aliases": list_aliases(gw().db, kitchen_id), "unknown_items": list_unknown(gw().db, kitchen_id)}

    @app.put(k + "/aliases")
    async def put_alias(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:write", kitchen_id)
        data = await body(request)
        try:
            out = set_alias(gw().db, kitchen_id, data.get("phrase"), data.get("product_id"), who.name)
        except MemoryError as exc:
            raise GatewayError(422, "INVALID_REQUEST", str(exc)) from None
        gw()._audit(kitchen_id, "alias_set", who.name, phrase=out["phrase"], product_id=out["product_id"])
        return out

    @app.delete(k + "/aliases")
    def delete_alias(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:write", kitchen_id)
        phrase = request.query_params.get("phrase", "")
        removed = remove_alias(gw().db, kitchen_id, phrase) or forget_unknown(gw().db, kitchen_id, phrase)
        if not removed:
            raise GatewayError(404, "NOT_FOUND", "no such phrase")
        gw()._audit(kitchen_id, "alias_removed", who.name, phrase=normalise(phrase))
        return {"deleted": True}

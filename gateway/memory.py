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


SUGGESTIONS = 3
NEW_SUGGESTIONS_PER_CALL = 3      # free embedding tier: 3 query embeddings a minute


def suggest(db, kitchen_id: str, phrase: str, *, injected=None) -> tuple[list[dict] | None, str]:
    """The nearest catalog products for words that matched nothing, and how they were found:
    "meaning" (vector search over the 17,546 product vectors) or "words" (text search, when
    the embedding service is not there or over its limit). Only a suggestion: a person links
    one, or none. It can never change an order, so it may use meaning even while the order
    search runs on words only (SEARCH_HYBRID off). None when the search failed (Mongo or
    Atlas Search briefly away), so the caller stores nothing and tries again later."""
    rows, how = [], "words"
    try:
        if injected is not None:
            rows = injected(db, phrase, {}, SUGGESTIONS, kitchen_id=kitchen_id)
        else:
            import time
            from gateway import catalog_search
            from store.search import search_products
            text = (phrase or "").strip().lower()
            resting = time.monotonic() < catalog_search._state["skip_until"] and text not in catalog_search._vectors
            try:
                if resting:                # the embedding service rests after a failure: no new call
                    raise RuntimeError("embedding cooldown")
                rows = search_products(db, phrase, {}, SUGGESTIONS, kitchen_id=kitchen_id,
                                       hybrid=True, embedder=catalog_search._query_embedder())
                how = "meaning"
            except ValueError:
                return [], "words"
            except Exception:              # no key, limit, timeout, no index: words instead
                if not resting:
                    catalog_search._state["skip_until"] = time.monotonic() + catalog_search.COOLDOWN_S
                rows = search_products(db, phrase, {}, SUGGESTIONS, kitchen_id=kitchen_id)
    except Exception:                      # the search itself failed: not "nothing found"
        return None, "words"
    ids = [str(r["product_id"]) for r in rows[:SUGGESTIONS] if r.get("product_id")]
    names = {d["_id"]: (d.get("names") or {}).get("en")
             for d in db.products.find({"_id": {"$in": ids}}, {"names": 1})} if ids else {}
    return [{"product_id": pid, "product_name": names.get(pid)} for pid in ids], how


def list_unknown(db, kitchen_id: str, *, injected=None, with_suggestions: bool = False) -> list[dict]:
    """Unknown phrases, most asked first. With suggestions: up to NEW_SUGGESTIONS_PER_CALL
    phrases without stored suggestions get them now (kept on the row, so the next call is free)."""
    rows = list(db.unknown_items.find({"kitchen_id": kitchen_id}).sort("times", -1).limit(100))
    if with_suggestions:
        fresh = 0
        for r in rows:
            if "suggestions" in r or fresh >= NEW_SUGGESTIONS_PER_CALL:
                continue
            found, how = suggest(db, kitchen_id, r["phrase"], injected=injected)
            fresh += 1
            if found is None:              # search failed: leave the row unsuggested, retry next call
                continue
            db.unknown_items.update_one({"_id": r["_id"]}, {"$set": {"suggestions": found, "suggested_by": how}})
            r["suggestions"], r["suggested_by"] = found, how
    out = []
    for r in rows:
        item = {"phrase": r["phrase"], "times": r.get("times", 1),
                "first_asked": r["first_asked"].isoformat() if r.get("first_asked") else None,
                "last_asked": r["last_asked"].isoformat() if r.get("last_asked") else None}
        if with_suggestions:
            item["suggestions"] = r.get("suggestions")          # None: not looked up yet
            item["suggested_by"] = r.get("suggested_by")
        out.append(item)
    return out


def forget_unknown(db, kitchen_id: str, phrase: str) -> bool:
    return db.unknown_items.delete_one({"_id": f"{kitchen_id}:{normalise(phrase)}"}).deleted_count == 1


def mount_memory(app, gw, principal, body) -> None:
    from gateway.service import GatewayError
    k = "/v1/kitchens/{kitchen_id}"

    @app.get(k + "/aliases")
    def aliases(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return {"aliases": list_aliases(gw().db, kitchen_id),
                "unknown_items": list_unknown(gw().db, kitchen_id, injected=gw()._search, with_suggestions=True)}

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

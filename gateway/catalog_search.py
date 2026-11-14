"""The catalog search the gateway uses: text, or text plus meaning (hybrid).

Hybrid search (store/search.py, Atlas Vector Search with `$rankFusion`) is OFF unless
`SEARCH_HYBRID=true`. When it is on, the query is embedded with a short timeout and no
retry. Any failure of the vector side (no key, a rate limit, a slow answer, no vector
index yet) falls back to the plain text search, silently: a search must never fail
because of it. The answer says which one ran.

The embedding service on a free tier allows 3 requests a minute, so a query's vector is
kept in memory for the life of the process, and after a failure hybrid is not tried
again for a while.
"""

from __future__ import annotations

import os
import time

QUERY_TIMEOUT_S = 2.0      # cap on the query embedding call
COOLDOWN_S = 60.0          # after a failed hybrid search, use text only for this long
CACHE_SIZE = 256

_vectors: dict[str, list[float]] = {}
_state = {"skip_until": 0.0}


def enabled() -> bool:
    return (os.environ.get("SEARCH_HYBRID") or "").strip().lower() in ("1", "true", "yes", "on")


def reset() -> None:
    """Forget cached query vectors and the cooldown (tests, and after a config change)."""
    _vectors.clear()
    _state["skip_until"] = 0.0


def _query_embedder(now=time.monotonic):
    """An embedder for one query: cached, at most `QUERY_TIMEOUT_S`, never retried."""
    import httpx

    from store import embeddings

    def no_retry(seconds):
        raise embeddings.EmbeddingError("embedding request failed: rate-limited")

    def post(url, **kwargs):
        return httpx.post(url, **{**kwargs, "timeout": QUERY_TIMEOUT_S})

    def embed(texts, input_type):
        out = []
        for text in texts:
            key = text.strip().lower()
            if key not in _vectors:
                if len(_vectors) >= CACHE_SIZE:
                    _vectors.pop(next(iter(_vectors)))
                _vectors[key] = embeddings.embed([text], input_type, post=post, sleep=no_retry)[0]
            out.append(_vectors[key])
        return out

    return embed


def search(db, query: str, filters: dict | None, limit: int, kitchen_id: str | None = None,
           *, injected=None, now=time.monotonic, hybrid_ok: bool = True) -> tuple[list[dict], str]:
    """`(rows, kind)`: the best matches and which search gave them, "text" or "hybrid".

    `injected` is the gateway's own search function (tests and offline runs): it is used
    as it is and counts as "text". `hybrid_ok=False` asks for the text search only: a
    search inside one category needs no meaning search and must not spend an embedding call.

    While hybrid rests after a failure, a query whose vector is kept in memory still runs
    hybrid: it needs no new call to the embedding service.
    """
    if injected is not None:
        return injected(db, query, filters or {}, limit, kitchen_id=kitchen_id), "text"
    from store.search import search_products

    text = (query or "").strip()
    resting = now() < _state["skip_until"] and text.lower() not in _vectors
    if hybrid_ok and enabled() and text and not resting:
        try:
            rows = search_products(db, query, filters or {}, limit, kitchen_id=kitchen_id,
                                   hybrid=True, embedder=_query_embedder())
            return rows, "hybrid"
        except ValueError:
            raise              # a bad filter or limit is the caller's error in either search
        except Exception:      # no key, 429, timeout, no vector index: never fail the search
            _state["skip_until"] = now() + COOLDOWN_S
    return search_products(db, query, filters or {}, limit, kitchen_id=kitchen_id), "text"

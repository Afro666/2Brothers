"""The bot's two outside doors (#1330): Telegram's Bot API and our own gateway.

Both are thin: one HTTP call per method, no retries of a write. The bot is a client of the
public gateway API with a kitchen token, like any other agent. That token never approves.
"""
from __future__ import annotations

import base64
import uuid

import httpx


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, http: httpx.Client | None = None):
        self._base = f"https://api.telegram.org/bot{token}"
        self._files = f"https://api.telegram.org/file/bot{token}"
        self._http = http or httpx.Client(timeout=httpx.Timeout(40.0, connect=10.0))

    def call(self, method: str, **params):
        body = {k: v for k, v in params.items() if v is not None}
        try:
            data = self._http.post(f"{self._base}/{method}", json=body).json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never the URL in a message or a log: it holds the bot token.
            raise TelegramError(f"{method}: {type(exc).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('error_code')} {data.get('description')}")
        return data["result"]

    def updates(self, offset: int | None, wait: int = 25) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=wait, allowed_updates=["message", "callback_query"])

    def send(self, chat_id: int, text: str, markup: dict | None = None, silent: bool = False) -> int:
        sent = self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup,
                         disable_notification=silent or None, link_preview_options={"is_disabled": True})
        return sent["message_id"]

    def edit(self, chat_id: int, message_id: int, text: str, markup: dict | None = None) -> None:
        try:
            self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML",
                      reply_markup=markup, link_preview_options={"is_disabled": True})
        except TelegramError as exc:
            if "message is not modified" not in str(exc):     # the same text again is not a fault
                raise

    def answer(self, callback_id: str, text: str | None = None) -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def typing(self, chat_id: int) -> None:
        self.call("sendChatAction", chat_id=chat_id, action="typing")

    def download(self, file_id: str, limit: int = 2 * 1024 * 1024) -> bytes:
        info = self.call("getFile", file_id=file_id)
        if int(info.get("file_size") or 0) > limit:
            raise TelegramError("getFile: the file is too large")
        try:
            response = self._http.get(f"{self._files}/{info['file_path']}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError(f"download: {type(exc).__name__}") from None
        return response.content


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}")
        self.status, self.code, self.message = status, code, message


class Gateway:
    """The kitchen's side of the gateway API (docs/contract.md), for one kitchen."""

    def __init__(self, base_url: str, token: str, kitchen_id: str, http: httpx.Client | None = None):
        self.kitchen_id = kitchen_id
        self._root = f"{base_url.rstrip('/')}/v1/kitchens/{kitchen_id}"
        self._headers = {"Authorization": f"Bearer {token}"}
        # The Buyer can take most of a minute on a busy model endpoint.
        self._http = http or httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0))

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._http.request(method, f"{self._root}{path}", headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise GatewayError(0, "NETWORK", f"The gateway did not answer ({type(exc).__name__}).") from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            error = data.get("error") if isinstance(data, dict) else None
            error = error if isinstance(error, dict) else {}
            raise GatewayError(response.status_code, str(error.get("code") or "ERROR"),
                               str(error.get("message") or "The gateway refused the request."))
        return data

    def ask(self, text: str, requested_date: str) -> dict:
        """Free text to the Buyer. `requested_date` is used only when the text names no day."""
        return self._call("POST", "/proposals", json={"text": text, "requested_date": requested_date,
                                                      "idempotency_key": f"tg-{uuid.uuid4().hex}"})

    def plan(self, first_day: str, last_day: str, delivery_day: str) -> dict:
        """Everything the menu plan needs in the window, net of counted stock: one proposal,
        quoted for `delivery_day`."""
        return self._call("POST", "/proposals", json={"from": first_day, "to": last_day,
                                                      "requested_date": delivery_day,
                                                      "idempotency_key": f"tg-{uuid.uuid4().hex}"})

    def proposal(self, proposal_id: str) -> dict:
        return self._call("GET", f"/proposals/{proposal_id}")

    def brief(self, when: str, lang: str = "en") -> dict:
        """The kitchen's morning or evening brief (contract: #1332). A read: it makes no order."""
        return self._call("GET", "/brief", params={"when": when, "lang": lang})

    def shelf_photo(self, image: bytes) -> dict:
        """Nemotron reads one shelf photo into a count to confirm. The route stores nothing."""
        return self._call("POST", "/stock/photo", json={"image_base64": base64.b64encode(image).decode("ascii")})

    def save_counts(self, counts: list[dict], counted_at: str, key: str) -> dict:
        """Store a count a person confirmed. The same key stores once."""
        return self._call("POST", "/stock-counts", json={"idempotency_key": key, "counted_at": counted_at,
                                                         "source": "manual", "counts": counts})

    def waiting(self) -> list[dict]:
        """The proposals that wait for a person's approval, newest first."""
        found = self._call("GET", "/proposals").get("proposals") or []
        return [p for p in found if p.get("status") == "READY"]

    def change(self, proposal_id: str, product_id: str, new_quantity: str) -> dict:
        return self._call("POST", f"/proposals/{proposal_id}/change",
                          json={"idempotency_key": f"tg-{uuid.uuid4().hex}",
                                "lines": [{"product_id": product_id, "quantity": new_quantity}]})

    def products(self, product_ids: list[str], lang: str = "en") -> dict[str, dict]:
        """product_id -> {"name", "lot"}. A product the gateway does not know is left out, never
        invented. `lot` is the step a quantity moves in (the engine rounds up to it)."""
        ids = list(dict.fromkeys(str(p) for p in product_ids))
        out: dict[str, dict] = {}
        for start in range(0, len(ids), 200):
            try:
                rows = self._call("GET", "/catalog/products", params={"ids": ",".join(ids[start:start + 200])})
            except GatewayError:
                continue        # names are a comfort: the order is still shown, with the code
            for row in rows.get("products") or []:
                names = row.get("names") or {}
                name = names.get(lang) or names.get("en") or names.get("fi")
                out[str(row.get("product_id"))] = {"name": " ".join(str(name).split()) if name else None,
                                                   "lot": row.get("lot_size")}
        return out


class SpeechError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


class Speech:
    """The internal Whisper service (#1331). It only turns a voice message into text."""

    def __init__(self, base_url: str, http: httpx.Client | None = None):
        self._url = f"{base_url.rstrip('/')}/transcribe"
        self._http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0))

    def text(self, audio: bytes) -> str:
        try:
            response = self._http.post(self._url, content=audio, headers={"Content-Type": "audio/ogg"})
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise SpeechError("STT_UNAVAILABLE", "I cannot listen right now. Type the request instead.") from None
        if response.status_code >= 400:
            error = data.get("error") or {}
            raise SpeechError(str(error.get("code") or "ERROR"), str(error.get("message") or "I did not catch that."))
        return str(data.get("text") or "").strip()

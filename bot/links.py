"""Which Telegram chats may talk to the kitchen's bot (#1330).

A chat is linked with a one-time code that an operator makes on the server
(`python -m bot.links`). The list is a small JSON file in the bot's own volume: it holds chat
ids and nothing else. Only `store/` talks to Mongo, and this is not kitchen data.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path

CODE_MINUTES = 30


NOTES_KEPT = 200


class Links:
    def __init__(self, path: str | os.PathLike | None = None, clock=time.time):
        self._path = Path(path or os.environ.get("BOT_DATA_DIR", ".bot")) / "links.json"
        self._clock = clock
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {"codes": dict(data.get("codes") or {}), "chats": dict(data.get("chats") or {}),
                "briefs": list(data.get("briefs") or []),
                "notes": dict(data.get("notes") or {})}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_bytes(json.dumps(data, indent=1).encode("utf-8"))
        os.replace(tmp, self._path)

    def new_code(self) -> str:
        with self._lock:
            data = self._read()
            now = self._clock()
            data["codes"] = {c: t for c, t in data["codes"].items() if t > now}
            code = secrets.token_urlsafe(9)
            data["codes"][code] = now + CODE_MINUTES * 60
            self._write(data)
            return code

    def redeem(self, code: str, chat_id: int, who: str) -> bool:
        """True when the code was good. A code works once; a wrong or old one changes nothing."""
        with self._lock:
            data = self._read()
            expires = data["codes"].get(code)
            if expires is None or expires <= self._clock():
                return False
            del data["codes"][code]
            data["chats"][str(chat_id)] = {"who": who, "linked_at": int(self._clock())}
            self._write(data)
            return True

    def linked(self, chat_id: int) -> bool:
        return str(chat_id) in self._read()["chats"]

    def mark_sent(self, slot: str) -> bool:
        """True the first time a brief slot ("2026-11-14 morning") is marked; False after that,
        also across a restart."""
        with self._lock:
            data = self._read()
            sent = data.get("briefs") or []
            if slot in sent:
                return False
            data["briefs"] = (sent + [slot])[-8:]
            self._write(data)
            return True

    def note(self, key: str, value: dict) -> None:
        """Remember which message shows what ("summary:<chat>:<proposal>", "brief:<chat>"), so a
        change still updates it after a restart of the bot. The newest NOTES_KEPT are kept."""
        with self._lock:
            data = self._read()
            data["notes"].pop(key, None)
            data["notes"][key] = value
            for old in list(data["notes"])[:-NOTES_KEPT]:
                del data["notes"][old]
            self._write(data)

    def noted(self, key: str) -> dict | None:
        return self._read()["notes"].get(key)

    def chats(self) -> list[int]:
        return [int(c) for c in self._read()["chats"]]


def main(argv: list[str] | None = None) -> int:
    """Print a one-time link for a new chat: `python -m bot.links <bot username>`."""
    argv = sys.argv[1:] if argv is None else argv
    code = Links().new_code()
    username = argv[0].lstrip("@") if argv else os.environ.get("BOT_USERNAME", "")
    print(f"https://t.me/{username}?start={code}" if username else f"/start {code}")
    print(f"It works once, for {CODE_MINUTES} minutes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

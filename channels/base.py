"""The seam between the notebook and whatever app the messages arrive through.

A channel does three things and nothing else:

    external_id(payload)  -> a stable string for one conversation
    text_of(payload)      -> the words the person typed
    send(external_id, t)  -> put words in front of that person

Everything else, every rule about money and dates and reminders, lives behind
the HTTP calls in brain.py. Telegram is the only channel implemented today.
WhatsApp would be a second file here, not a rewrite, but note that WhatsApp
forbids free-form messages outside a 24-hour window after the user's last
message, so its reminders would have to be reshaped into approved templates.
That constraint belongs to the adapter, which is exactly why the seam exists.

The id is namespaced (`tg:<chat>`, later `wa:<number>`) so one binding table
can hold both without the two ever colliding on a bare number.
"""

import json
import os
import threading

BINDINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bindings.json")


class BindingStore:
    """Which conversation owns which book.

    Kept in a plain JSON file rather than in Walrus on purpose. This is routing,
    not memory: it is written and rewritten constantly, it is worthless to a
    competitor, and losing it costs one message to re-bind.

    One chat, one book for now. A shop with two branches is a real case and
    would need a way to pick between them, which is a menu, not a data model.
    """

    def __init__(self, path=None):
        self.path = path or BINDINGS_PATH
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as fh:
                rows = json.load(fh)
            return rows if isinstance(rows, dict) else {}
        except (ValueError, OSError):
            # A corrupted routing table must not stop the bot. Re-binding is one
            # message; refusing to start is an outage.
            return {}

    def _save(self, rows):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self, external_id):
        with self.lock:
            return self._load().get(external_id)

    def all(self):
        with self.lock:
            return self._load()

    def bind(self, external_id, passkey, pack_id="", lang=""):
        with self.lock:
            rows = self._load()
            rows[external_id] = {"passkey": passkey, "pack_id": pack_id,
                                 "lang": lang, "channel": external_id.split(":")[0]}
            self._save(rows)
            return rows[external_id]

    def unbind(self, external_id):
        with self.lock:
            rows = self._load()
            had = rows.pop(external_id, None)
            self._save(rows)
            return had is not None


class Channel:
    """What every adapter has to provide. Not an abstract base class on purpose:
    the reminder runner only needs `send`, and a half-built second channel should
    be able to exist without implementing a chat loop it does not have yet."""

    name = "none"

    def external_id(self, payload):
        raise NotImplementedError

    def text_of(self, payload):
        raise NotImplementedError

    def send(self, external_id, text):
        raise NotImplementedError

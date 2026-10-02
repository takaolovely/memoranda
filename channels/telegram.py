"""The Telegram adapter.

Long polling, not a webhook, and that is a deliberate trade. Polling needs no
public URL, no TLS certificate and no tunnel that changes its address whenever
the machine restarts. It costs a few wasted requests an hour and it means the bot
starts with `python memoranda_bot.py` and nothing else. A webhook becomes worth
it at thousands of chats; below that it is ceremony.

Message length is the one thing Telegram imposes that the notebook does not: 4096
characters. A long reply is split rather than truncated, because a reply that
stops mid-number is worse than two messages.
"""

import json
import time
import urllib.error
import urllib.request

from .base import Channel

API = "https://api.telegram.org/bot%s/%s"
LIMIT = 4096


class TelegramError(RuntimeError):
    pass


class Telegram(Channel):
    name = "tg"

    def __init__(self, token):
        if not token or ":" not in token:
            raise TelegramError("token looks wrong (no colon)")
        self.token = token
        self.me = None

    # ---- raw API ----------------------------------------------------------

    def _call(self, method, http_timeout=60, **params):
        # Named http_timeout, not timeout: `timeout` is itself a Telegram
        # parameter on getUpdates, where it means how many seconds the server
        # should hold the connection open. The two are not the same number and
        # one of them silently won when they shared a name.
        url = API % (self.token, method)
        try:
            if params:
                req = urllib.request.Request(
                    url, data=json.dumps(params).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Telegram answers 4xx with a JSON body that says what is wrong. Read
            # it, because "400 Bad Request" on its own has never once been useful.
            try:
                detail = json.loads(exc.read().decode("utf-8"))
                raise TelegramError("%s %s: %s" % (exc.code, method,
                                                   detail.get("description"))) from exc
            except (ValueError, OSError):
                raise TelegramError("%s on %s" % (exc.code, method)) from exc
        except urllib.error.URLError as exc:
            raise TelegramError("network on %s: %s" % (method, exc)) from exc
        if not out.get("ok"):
            raise TelegramError("%s: %s" % (method, out.get("description")))
        return out.get("result")

    # ---- Channel ----------------------------------------------------------

    def whoami(self):
        if self.me is None:
            self.me = self._call("getMe", http_timeout=30)
        return self.me

    def external_id(self, payload):
        chat = payload.get("chat") or {}
        return "tg:%s" % chat.get("id")

    def text_of(self, payload):
        return (payload.get("text") or "").strip()

    def send(self, external_id, text):
        """Send, splitting anything over the limit. Returns how many parts went."""
        chat_id = external_id.split(":", 1)[1]
        parts = [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)] or [""]
        for part in parts:
            self._call("sendMessage", http_timeout=30, chat_id=chat_id, text=part,
                       disable_web_page_preview=True)
        return len(parts)

    def notify_looking(self, external_id, action="typing"):
        """The little 'typing...' hint. Costs nothing and covers a slow turn."""
        chat_id = external_id.split(":", 1)[1]
        try:
            self._call("sendChatAction", http_timeout=15, chat_id=chat_id, action=action)
        except TelegramError:
            # Purely cosmetic. Never let it break a real message.
            return False
        return True

    def updates(self, offset=0, timeout=30):
        """One long poll. Returns the raw update list, oldest first."""
        return self._call("getUpdates", http_timeout=timeout + 15, offset=offset,
                          timeout=timeout, allowed_updates=["message"])

    def set_commands(self, rows, language_code=None):
        """Put the commands in Telegram's own / menu.

        `rows` is a list of (name, description) where the name has no slash:
        the API rejects "/new", it wants "new". Registering here means the menu
        and the help text come from the same table, so they cannot disagree.

        Telegram holds one list per language and picks by the client's locale,
        so the description can be Indonesian for Indonesian phones without the
        command names changing. The names are the part that has to stay stable;
        whoever learned /new should not lose it because their phone is set to
        Indonesian.
        """
        payload = [{"command": name.lstrip("/"), "description": description}
                   for name, description in rows]
        if language_code:
            self._call("setMyCommands", http_timeout=30, commands=payload,
                       language_code=language_code)
        else:
            self._call("setMyCommands", http_timeout=30, commands=payload)
        return len(payload)

"""Every way a person can talk to the bot.

This is the only place command names are written down. Rename one here and the
parser, the /help text and the tests all follow, because the help text is built
from this table instead of repeating it.

Editing this file is the intended way to change the language of the commands.
Swap the two columns and the bot speaks Indonesian: the English names become the
quietly accepted ones and the Indonesian set gets shown.

    ("new",   "/baru",   ("/new",)),

Three columns per row:

    1. the action name the code uses, never shown to anybody
    2. the name shown in /help and listed first
    3. other spellings accepted in silence

The aliases exist so that changing the default does not lock out anybody who
learned the old names. Somebody who typed /kunci for a month should not get a
shrug because the default moved to English.
"""

COMMANDS = (
    # action     shown          also accepted
    ("start",   "/start",     ("/mulai",)),
    ("help",    "/help",      ("/bantuan", "/tolong")),
    ("new",     "/new",       ("/baru",)),
    ("key",     "/key",       ("/kunci",)),
    ("book",    "/book",      ("/buku", "/buku_ku")),
    ("remind",  "/remind",    ("/ingat", "/ingatkan")),
    ("timezone", "/timezone", ("/zona",)),
    ("release", "/release",   ("/lepas", "/keluar")),
)

# The order /help prints them in, which is the order a new person needs them.
HELP_ORDER = ("new", "key", "book", "remind", "timezone", "release", "help")

# Actions that carry an argument, so the bot knows where to look for one.
TAKES_ARGUMENT = ("key", "timezone")


def _strip(word):
    """`/Baru@memorandachatbot` and `/baru` are the same command.

    Telegram appends the bot handle when several bots share a group, and people
    type capitals. Neither is a different command.
    """
    return (word or "").strip().split("@")[0].lower()


def resolve(word):
    """The action for one typed word, or None if it is not a command."""
    wanted = _strip(word)
    if not wanted:
        return None
    for action, shown, aliases in COMMANDS:
        if wanted == shown or wanted in aliases:
            return action
    return None


def shown(action):
    for name, display, _aliases in COMMANDS:
        if name == action:
            return display
    return ""


def is_command(text):
    return bool(text) and text.strip().startswith("/")


def argument_of(text):
    """The bit after the command, if there is one."""
    _word, _, rest = (text or "").strip().partition(" ")
    return rest.strip()


def help_rows():
    """(shown name, action) in the order /help should print them."""
    by_action = {name: display for name, display, _ in COMMANDS}
    return [(by_action[a], a) for a in HELP_ORDER if a in by_action]


def known_names():
    """Everything accepted, for the tests and for a clear error message."""
    out = []
    for _action, display, aliases in COMMANDS:
        out.append(display)
        out.extend(aliases)
    return out

"""Pure seat policy for hosted Party Line models. No I/O."""

import os
import re

# chat on, do-not-touch on. Every other ability, including DADO, stays off
# until a seat stores that name on its own board.
DEFAULT_ABILITIES = {
    "chat": True,
    "do-not-touch": True,
}

_ON = {"1", "true", "yes", "on"}


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in _ON
    return bool(value)


def ability_board(raw=None):
    """Defaults plus any named toggles. Missing chat / do-not-touch stay on.

    Existing member files that have no board still read as the defaults.
    Extra names are stored beside the defaults; they do not remove them.
    """
    board = dict(DEFAULT_ABILITIES)
    if not raw:
        return board
    if not isinstance(raw, dict):
        raise TypeError("ability board must be a mapping")
    for key, value in raw.items():
        name = str(key).strip().lower()
        if name:
            board[name] = _as_bool(value)
    return board


def chat_allowed(board):
    """DADO is one toggle: while it is on, a seat posts no chat action."""
    board = ability_board(board)
    if board.get("dado"):
        return False
    return bool(board.get("chat"))


_MENTION = re.compile(r"@([A-Za-z0-9_-]+)")


_GREET = re.compile(r"^(?:hey|hi|hello)\s+@?([A-Za-z0-9_-]+)\b", re.I)


def mentions(body):
    """@names in a line. A directed line is only for those seats."""
    return _MENTION.findall(body or "")


def greeting_target(body):
    """The name after hello/hi/hey, if the line starts that way."""
    match = _GREET.match((body or "").strip())
    return match.group(1) if match else None


def _same(left, right):
    return left.lower() == right.lower()


def is_named(name, body):
    """True when this seat is addressed with @name or as a whole word."""
    if name in mentions(body):
        return True
    text = body or ""
    return re.search(
        r"(?<![\w])" + re.escape(name) + r"(?![\w])", text) is not None


def should_speak(name, messages, now, last_spoke, cooldown, board, members=None):
    """Speak when named, or when the last message is not this seat's.

    Never answer the seat's own last message. A cooldown stops a repeat.
    DADO or chat-off posts nothing.
    """
    if not chat_allowed(board):
        return False
    if not messages:
        return False
    last = messages[-1]
    if last.get("sender") == name:
        return False
    if last_spoke and cooldown and (now - float(last_spoke)) < float(cooldown):
        return False
    body = last.get("body") or ""
    named = mentions(body)
    # @name is only for the named seats.
    if named and not any(_same(name, one) for one in named):
        return False
    if any(_same(name, one) for one in named):
        return True
    # "hello llama8 ..." is for llama8, even if llama3 is mentioned later.
    # Only when that first name is actually a member. "hello everyone" stays open.
    target = greeting_target(body)
    roster = members or []
    if target and any(_same(target, one) for one in roster):
        return _same(name, target)
    return last.get("sender") != name


def chat_lines(messages):
    """Spoken lines only. Join, invite, and note lines make a model narrate events."""
    skip = {"join", "invite", "note", "nudge"}
    return [m for m in messages if (m.get("type") or "msg") not in skip]


def context_slice(messages, watermark, window_chars):
    """Messages newer than the digest watermark, newest-tail capped to the window.

    The window is a character budget of message bodies. The newest message
    is kept even when it alone is larger than the budget, and older messages
    in the fresh slice are dropped until the rest fits.
    """
    mark = int(watermark or 0)
    fresh = [m for m in messages if int(m.get("lamport") or 0) > mark]
    if window_chars is None or int(window_chars) <= 0:
        return fresh
    budget = int(window_chars)
    kept = []
    used = 0
    for msg in reversed(fresh):
        need = len(msg.get("body") or "")
        if kept and used + need > budget:
            break
        kept.append(msg)
        used += need
        if used >= budget:
            break
    kept.reverse()
    return kept


def render_prompt(messages):
    return "\n".join(
        "%s: %s" % (m.get("sender", "?"), m.get("body") or "")
        for m in messages)


def speak_prompt(name, messages):
    """Ask the model for its next spoken line, not a summary of the log."""
    transcript = render_prompt(messages)
    return (
        "You are %s, a person on this party line. "
        "Reply with only the next thing you say out loud. "
        "One or two sentences. Do not narrate, summarize, or describe the room. "
        "Do not start with \"It seems\".\n\n"
        "%s\n%s:" % (name, transcript, name)
    )


def path_inside(path, root):
    """True when path is root or a file inside it. Used by the do-not-touch guard."""
    ap = os.path.realpath(path)
    rp = os.path.realpath(root)
    return ap == rp or ap.startswith(rp + os.sep)

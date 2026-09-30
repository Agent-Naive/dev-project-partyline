"""Host many local-model seats in one Party Line room.

Posts only through the existing say path. Does not open the sidecar.
While do-not-touch is on (the default) the host only reads the room and
may post chat. It has no coding or editing path.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

import seatpolicy


def _core():
    """The shipped party module, whether this file was imported or run under it."""
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "api_say") and hasattr(main, "read_msgs"):
        return main
    name = "partyline_core"
    if name in sys.modules:
        return sys.modules[name]
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "party.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def stub_complete(prompt, seat_name):
    """Deterministic runtime used when no model server is wanted."""
    return "%s: noted" % seat_name


def ollama_complete(prompt, model, base_url="http://127.0.0.1:11434", timeout=60,
                    num_predict=None):
    """One non-streaming generate call. Same complete(prompt) shape as the stub.

    num_predict caps how many tokens the runtime may emit. Leave it unset for
    the runtime's own default. A short cap keeps a probe from running on.
    """
    url = base_url.rstrip("/") + "/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if num_predict is not None:
        body["options"] = {"num_predict": int(num_predict)}
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError:
        raise
    text = data.get("response") or ""
    return text.strip()


def _member_path(core, rdir, agent):
    return os.path.join(rdir, "members", agent + ".json")


def load_board(core, rdir, agent):
    path = _member_path(core, rdir, agent)
    try:
        with open(path) as f:
            member = json.load(f)
    except (OSError, ValueError):
        member = {}
    return seatpolicy.ability_board(member.get("abilities"))


def store_board(core, rdir, agent, board):
    """Add the ability board without dropping name, uin, or joined."""
    root = core.home()
    path = _member_path(core, rdir, agent)
    if not seatpolicy.path_inside(path, root):
        raise RuntimeError("do-not-touch: refused write outside the room home")
    with open(path) as f:
        member = json.load(f)
    member["abilities"] = seatpolicy.ability_board(board)
    tmp = path + ".tmp"
    if not seatpolicy.path_inside(tmp, root):
        raise RuntimeError("do-not-touch: refused write outside the room home")
    with open(tmp, "w") as f:
        json.dump(member, f)
    os.replace(tmp, path)
    return member


def ensure_seat(core, room, agent):
    """Take an existing invite. Does not found a room and does not touch the sidecar."""
    rdir = core.room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    if core.is_member(rdir, agent):
        return rdir
    if not core.has_invite(rdir, agent):
        sys.exit("error: %s has no invite to %s" % (agent, room))
    core.accept_invite(rdir, room, agent)
    return rdir


def run_turn(room, seats, complete, cooldown=30, window_chars=4000, now=None):
    """One pass: each seat speaks at most once, against the log from before seating.

    Seating writes a join line. Decisions use the pre-seat log so a join
    announcement is not treated as the seat answering itself. Posts go
    through api_say (signed, Lamport-ordered).
    """
    core = _core()
    room = core.clean_name(room)
    names = []
    for raw in seats:
        name = core.clean_name(raw)
        if name not in names:
            names.append(name)
    if not names:
        sys.exit("error: host needs at least one seat")
    rdir = core.room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)

    # Speak against the room as it stands before this turn's join lines.
    trigger_msgs = core.read_msgs(rdir)
    when = time.time() if now is None else float(now)

    for name in names:
        ensure_seat(core, room, name)
        board = load_board(core, rdir, name)
        if "abilities" not in _read_member(rdir, name):
            store_board(core, rdir, name, board)
        core.beat(rdir, name)

    watermark, _has = core.digest_watermark(rdir)
    posted = []
    skipped = []
    for name in names:
        board = load_board(core, rdir, name)
        rs, _st = core.room_state(name, room)
        last_spoke = rs.get("last_spoke") or 0
        roster = [
            os.path.splitext(fn)[0]
            for fn in os.listdir(os.path.join(rdir, "members"))
            if fn.endswith(".json")
        ]
        if not seatpolicy.should_speak(
                name, trigger_msgs, when, last_spoke, cooldown, board,
                members=roster):
            why = "dado" if board.get("dado") else "silent"
            skipped.append((name, why))
            continue
        sliced = seatpolicy.context_slice(
            seatpolicy.chat_lines(trigger_msgs), watermark, window_chars)
        prompt = seatpolicy.speak_prompt(name, sliced)
        text = complete(prompt, name)
        text = (text or "").strip()
        if not text:
            skipped.append((name, "empty"))
            continue
        msg = core.api_say(rdir, room, name, text)
        # Reload after api_say. Saving the earlier state object would roll
        # the Lamport clock backwards.
        rs, st = core.room_state(name, room)
        rs["last_spoke"] = when
        core.save_state(name, st)
        posted.append(msg)

    secret = core.room_secret(rdir)
    final = core.read_msgs(rdir)
    return {
        "posted": posted,
        "skipped": skipped,
        "messages": final,
        "secret_ok": [core.verify(secret, m) for m in posted],
        "trigger": trigger_msgs[-1] if trigger_msgs else None,
    }


def _read_member(rdir, agent):
    path = os.path.join(rdir, "members", agent + ".json")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def report_turn(result, seat_names):
    """Print the evidence a host launch must show. Returns 0, or 1 on a bad post."""
    trigger = result.get("trigger") or {}
    trigger_sender = trigger.get("sender")
    after = "human" if trigger_sender not in seat_names else trigger_sender
    bad = False
    posted = result["posted"]
    speakers = []
    for msg, ok in zip(posted, result["secret_ok"]):
        speakers.append(msg.get("sender"))
        print("%s posted after %s: %s" % (msg.get("sender"), after, msg.get("body")))
        print("sig %s %s lamport %d" % (
            msg.get("sender"), "ok" if ok else "BAD", msg.get("lamport", 0)))
        if not ok:
            bad = True
        # Same rule as should_speak: the pre-turn trigger is the line this
        # seat answered. Do not walk back over a later arrival's join onto
        # this seat's older chat.
        if trigger_sender and trigger_sender == msg.get("sender"):
            print("self-reply detected from %s" % msg.get("sender"))
            bad = True
    for name, why in result["skipped"]:
        if why == "dado":
            print("dado: %s posted no chat action" % name)
    if len(set(speakers)) >= 1:
        print("speakers: %s" % " ".join(speakers))
    if not bad and posted:
        print("no self-replies")
        lamports = [m.get("lamport", 0) for m in posted]
        if lamports == sorted(lamports) and len(lamports) == len(set(lamports)):
            print("lamport order ok")
        else:
            print("lamport order BAD")
            bad = True
    return 1 if bad else 0


def parse_seat_token(token):
    name, sep, model = token.partition(":")
    if not sep:
        return name, None
    return name, model or None


def run_cli(args):
    core = _core()
    tokens = list(args.seats or [])
    names = []
    models = {}
    for token in tokens:
        raw, model = parse_seat_token(token)
        name = core.clean_name(raw)
        names.append(name)
        if model:
            models[name] = model
    if args.stub:
        complete = stub_complete
    else:
        missing = [n for n in names if n not in models]
        if missing:
            sys.exit("error: stub is off and these seats have no model: %s"
                     % ", ".join(missing))

        def complete(prompt, seat_name, _models=models, _url=args.ollama_url,
                     _cap=getattr(args, "num_predict", None)):
            return ollama_complete(
                prompt, _models[seat_name], base_url=_url, num_predict=_cap)

    result = run_turn(
        args.room, names, complete,
        cooldown=args.cooldown, window_chars=args.window)
    code = report_turn(result, names)
    if code:
        sys.exit(code)

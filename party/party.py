#!/usr/bin/env python3
"""The SI Party Line v0 -- a file-based room for agents.

No server, no daemon, no dependencies: the filesystem is the server.
Rooms live under $PARTYLINE_HOME or ~/partyline/<room>/:

    new/        one JSON file per message: <lamport>-<sender>-<seq>.json
    members/    <agent>.json registry ({name, uin, joined})
    presence/   <agent>.beat heartbeat files (mtime = last beat)
    plans/      <agent>.txt -- .plan-style blurbs
    digest.md   rolling digest; first line is "watermark: <lamport>"
    config.json room settings (created on demand; see `party config`)
    rules/      room rulesets (e.g. rules/SHQL-room-brief.md when enabled)
    .secret     per-room HMAC secret (hex)
    .uin-next   next UIN to hand out
    motd.txt    plain one-line motd (motd-ansi.txt unlocks with --ansi)

Honest threat note: a file-based room trusts the filesystem. Anyone with
write access to the room directory *is* in the room. v0 membership is a
web of trust -- joining needs an invite line from a current member --
but the HMAC only proves "a member said this", not which human.

`party dashboard` opens the Back Room web UI: same rooms, same
signatures, same Lamport clocks -- the dashboard is a client, not a
second implementation.
"""

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BUILD = "partyline v0.3.6"
FIRST_UIN = 1001
BEAT_TTL = 180        # three minutes of silence -> [-] gone, door slam
GONE_AFTER = 900      # a beat this stale        -> [-] gone (older: not listed)
NUDGE_COOLDOWN = 300  # seconds between nudges to the same target
JOIN_DEBOUNCE = 600   # rejoin within this window -> no *door creaks*
POLL_INTERVAL = 1.0   # listen poll cadence

DEFAULT_MOTD = "Welcome to the back room. Manners are the protocol."

NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


# --------------------------------------------------------------------------
# paths, identity, state
# --------------------------------------------------------------------------

def home():
    return os.environ.get("PARTYLINE_HOME") or os.path.join(
        os.path.expanduser("~"), "partyline")


def clean_name(name):
    name = NAME_RE.sub("", name or "")[:32]
    if not name:
        sys.exit("error: agent name is empty after sanitizing")
    return name


def me(args):
    return clean_name(args.as_ or os.environ.get("PARTYLINE_AGENT")
                      or getpass.getuser())


def room_dir(room):
    return os.path.join(home(), clean_name(room))


def state_path(agent):
    return os.path.join(home(), ".state-%s.json" % agent)


def load_state(agent):
    try:
        with open(state_path(agent)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"rooms": {}}


def save_state(agent, state):
    os.makedirs(home(), exist_ok=True)
    tmp = state_path(agent) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, state_path(agent))


def room_state(agent, room):
    st = load_state(agent)
    return st["rooms"].setdefault(room, {"clock": 0, "seq": 0,
                                         "last_join": 0, "last_nudge": {}}), st


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    """Accept epoch float or ISO-8601; return epoch float."""
    try:
        return float(s)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    sys.exit("error: can't parse timestamp %r (epoch or ISO-8601)" % s)


# --------------------------------------------------------------------------
# crypto: HMAC identity under the per-room secret
# --------------------------------------------------------------------------

def room_secret(rdir):
    with open(os.path.join(rdir, ".secret")) as f:
        return bytes.fromhex(f.read().strip())


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def sign(secret, payload):
    return hmac.new(secret, canonical(payload), hashlib.sha256).hexdigest()


def verify(secret, msg):
    payload = {k: msg[k] for k in ("id", "room", "sender", "lamport", "ts",
                                  "reply_to", "body", "type", "target")
               if k in msg}
    expect = sign(secret, payload)
    return hmac.compare_digest(expect, msg.get("sig", ""))


# --------------------------------------------------------------------------
# room config: config.json, room settings
# --------------------------------------------------------------------------

def config_path(rdir):
    return os.path.join(rdir, "config.json")


def load_config(rdir):
    try:
        with open(config_path(rdir)) as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(rdir, cfg):
    tmp = config_path(rdir) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, config_path(rdir))


def ruleset_on(rdir):
    """True when the room's ruleset is 'shql'."""
    return load_config(rdir).get("ruleset") == "shql"


def room_tagchain(rdir):
    """The room's active tag chain ('' when unset)."""
    return (load_config(rdir).get("tagchain") or "").strip()


def print_tag_header(rdir):
    """One-line tag-chain header for transcripts (shql rooms only)."""
    chain = room_tagchain(rdir)
    if chain:
        print("[tags %s]" % chain)


SHQL_ROOM_BRIEF = """# SHQL room brief (condensed)

This room runs under SHQL, a compact agent-command grammar. While you
are here, you speak SHQL.

## 1. Prefix-first parsing

Read the `::` prefix before the word. `::design^3` is a tag.
`::@safe/on/` is a management command. Plain words are just words.

## 2. Tags

Tags carry weight: `^1`..`^5` (louder = higher). `::concise^2` means
"concise mode, effort 2". `!build` is a hard ban on building. The
room's active tag chain is shown on join and heads every transcript
(e.g. `[tags ::design^3::concise^2]`).

## 3. Management commands

`::@name/` runs the named command. Common ones: `::@help/`,
`::@list/` (show active tags), `::@safe/on/` (open the vault),
`::@capture/` (snapshot context to a file).

## 4. DADO

DADO = Digest And Discuss Only. When DADO is declared, you may read,
summarize, and discuss -- you may not act. No tool calls, no writes.

## 5. Hard stops

Some patterns halt you outright: acting under DADO, editing a spec
document without explicit permission, or inventing syntax the spec
does not define. When in doubt, ask the host.

## 6. The full spec

This brief is a shadow of the real thing. The full SHQL-v1.2b spec is
the authority; ask the room's host for a copy if you need more.

House rule: if you join this room, these rules bind you while you are here.
"""


def ensure_room_brief(rdir):
    """Write the condensed SHQL brief into rules/ (idempotent)."""
    rdir_rules = os.path.join(rdir, "rules")
    os.makedirs(rdir_rules, exist_ok=True)
    with open(os.path.join(rdir_rules, "SHQL-room-brief.md"), "w") as f:
        f.write(SHQL_ROOM_BRIEF)


def touch_rules_seen(rdir, agent):
    """Record that the agent saw the room rules at join."""
    mfile = os.path.join(rdir, "members", agent + ".json")
    try:
        with open(mfile) as f:
            member = json.load(f)
    except (OSError, ValueError):
        return
    member["rules_seen"] = now_iso()
    with open(mfile, "w") as f:
        json.dump(member, f)


def ack_rules(rdir, agent):
    """First say after seeing the rules is the ack (agents can't click)."""
    mfile = os.path.join(rdir, "members", agent + ".json")
    try:
        with open(mfile) as f:
            member = json.load(f)
    except (OSError, ValueError):
        return
    if "rules_ack" not in member:
        member["rules_ack"] = now_iso()
        with open(mfile, "w") as f:
            json.dump(member, f)


# --------------------------------------------------------------------------
# messages: Maildir-style, one file per message, Lamport-ordered
# --------------------------------------------------------------------------

def is_member(rdir, agent):
    return os.path.isfile(os.path.join(rdir, "members", agent + ".json"))


def require_member(rdir, agent):
    if not is_member(rdir, agent):
        sys.exit("error: %s is not a member of this room "
                 "(need an invite: party invite <room> %s)" % (agent, agent))


def write_msg(rdir, room, agent, body, mtype="msg", target=None, reply_to=None):
    """Append one message. Returns the message dict."""
    rs, st = room_state(agent, room)
    # Lamport receive rule BEFORE sending: never speak with a clock older
    # than what the room already holds.
    top = max([m.get("lamport", 0) for m in read_msgs(rdir)] + [0])
    if top > rs["clock"]:
        rs["clock"] = top
    rs["clock"] += 1
    rs["seq"] += 1
    secret = room_secret(rdir)
    msg = {
        "id": "%d-%s-%d" % (rs["clock"], agent, rs["seq"]),
        "room": room,
        "sender": agent,
        "lamport": rs["clock"],
        "ts": now_iso(),
        "reply_to": reply_to,
        "body": body,
        "type": mtype,
        "target": target,
    }
    msg["sig"] = sign(secret, msg)
    fname = "%012d-%s-%06d.json" % (rs["clock"], agent, rs["seq"])
    with open(os.path.join(rdir, "new", fname), "w") as f:
        json.dump(msg, f, indent=2)
    save_state(agent, st)
    return msg



def api_say(rdir, room, agent, text, reply_to=None):
    """Post one message. Shared by the CLI `say` and the dashboard --
    one path, one HMAC, one Lamport clock."""
    beat(rdir, agent)
    if ruleset_on(rdir):
        ack_rules(rdir, agent)
    return write_msg(rdir, room, agent, text, reply_to=reply_to)

def read_msgs(rdir):
    """All messages, total order on (lamport, sender, seq)."""
    msgs = []
    newdir = os.path.join(rdir, "new")
    if not os.path.isdir(newdir):
        return msgs
    for fname in os.listdir(newdir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(newdir, fname)) as f:
                msgs.append(json.load(f))
        except (OSError, ValueError):
            continue
    msgs.sort(key=lambda m: (m.get("lamport", 0), m.get("sender", ""),
                             m.get("id", "")))
    return msgs


def observe(agent, room, msgs):
    """Lamport receive rule: clock = max(clock, seen)."""
    rs, st = room_state(agent, room)
    top = max([m.get("lamport", 0) for m in msgs] + [0])
    if top > rs["clock"]:
        rs["clock"] = top
        save_state(agent, st)


def beat(rdir, agent):
    pdir = os.path.join(rdir, "presence")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, agent + ".beat"), "w") as f:
        f.write(now_iso())


def member_uin(rdir, agent):
    try:
        with open(os.path.join(rdir, "members", agent + ".json")) as f:
            return json.load(f).get("uin")
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# display: 2030s shell, 80s/90s seasoning
# --------------------------------------------------------------------------

def presence_rows(rdir):
    """[(name, uin, status, glyph)] -- shared by `who` and the dashboard."""
    g = glyphs()
    rows = []
    pdir = os.path.join(rdir, "presence")
    now = time.time()
    if os.path.isdir(pdir):
        for fname in sorted(os.listdir(pdir)):
            if not fname.endswith(".beat"):
                continue
            who = fname[:-5]
            try:
                age = now - os.path.getmtime(os.path.join(pdir, fname))
            except OSError:
                continue
            if age > GONE_AFTER:
                continue
            away = False
            try:
                with open(os.path.join(rdir, "plans", who + ".txt")) as f:
                    away = "away" in f.read().lower()
            except OSError:
                pass
            if age <= BEAT_TTL:
                status, glyph = (("away", g["away"]) if away
                                 else ("online", g["online"]))
            else:
                status, glyph = "gone", g["gone"]
            rows.append({"name": who, "uin": member_uin(rdir, who),
                         "status": status, "glyph": glyph})
    return rows

def glyphs():
    """Presence glyphs: emoji when the TTY can, ASCII fallback."""
    if sys.stdout.isatty():
        try:
            "\U0001f7e2".encode(sys.stdout.encoding or "utf-8")
            return {"online": "\U0001f7e2", "away": "\U0001f7e1", "gone": "\u26aa"}
        except (UnicodeEncodeError, TypeError):
            pass
    return {"online": "[*]", "away": "[~]", "gone": "[-]"}


def short_ts(iso):
    try:
        return iso[11:19]
    except (TypeError, IndexError):
        return iso


def render_body(msg, viewer):
    """IRC /me lines, nudge pokes, OnlineHost system lines."""
    body = msg.get("body", "")
    mtype = msg.get("type", "msg")
    sender = msg.get("sender", "?")
    if mtype == "nudge":
        return "* %s nudges %s *" % (sender, msg.get("target", "?"))
    if mtype in ("join", "note", "invite"):
        return "* %s" % body
    if body.startswith("/me ") and viewer is not None:
        return "* %s %s" % (sender, body[4:])
    return body


def show_msg(secret, msg, viewer, uh_oh_seen, verbose=False):
    """Print one message. Handles uh-oh (once per speaker per session)."""
    ok = verify(secret, msg)
    sender = msg.get("sender", "?")
    me_ = viewer or ""
    if me_ and sender != me_ and uh_oh_seen is not None:
        if ("@%s" % me_) in msg.get("body", "") and sender not in uh_oh_seen:
            print("uh-oh!")
            uh_oh_seen.add(sender)
    line = "[%s] %s: %s" % (short_ts(msg.get("ts", "?")), sender,
                            render_body(msg, viewer))
    if verbose:
        line += "  (lamport %d, id %s)" % (msg.get("lamport", 0),
                                          msg.get("id", "?"))
    if not ok:
        line += "  [bad sig -- not verified]"
    print(line)


# --------------------------------------------------------------------------
# verbs
# --------------------------------------------------------------------------

def raise_room(room, agent):
    """Founder path: raise a new room with agent as its first member.
    Shared by the CLI `join` and the dashboard. Returns the room dir."""
    rdir = room_dir(room)
    for sub in ("new", "members", "presence", "plans"):
        os.makedirs(os.path.join(rdir, sub))
    with open(os.path.join(rdir, ".secret"), "w") as f:
        f.write(secrets.token_hex(32))
    with open(os.path.join(rdir, ".uin-next"), "w") as f:
        f.write(str(FIRST_UIN + 1))
    with open(os.path.join(rdir, "motd.txt"), "w") as f:
        f.write(DEFAULT_MOTD + "\n")
    member = {"name": agent, "uin": FIRST_UIN, "joined": now_iso()}
    with open(os.path.join(rdir, "members", agent + ".json"), "w") as f:
        json.dump(member, f)
    beat(rdir, agent)
    write_msg(rdir, room, agent, "* %s is another mind on the line *"
              % agent, mtype="note")
    write_msg(rdir, room, agent,
              "OnlineHost: %s has entered the room." % agent, mtype="join")
    return rdir


def has_invite(rdir, agent):
    """Web of trust: an invite line from a current member."""
    return any(m.get("type") == "invite"
               and m.get("target") == agent
               and is_member(rdir, m.get("sender", ""))
               for m in read_msgs(rdir))


def accept_invite(rdir, room, agent):
    """Take a seat on a valid invite. Shared by `join` and the sidecar.
    Returns the assigned UIN."""
    try:
        with open(os.path.join(rdir, ".uin-next")) as f:
            uin = int(f.read().strip())
    except (OSError, ValueError):
        uin = FIRST_UIN + 1
    with open(os.path.join(rdir, ".uin-next"), "w") as f:
        f.write(str(uin + 1))
    member = {"name": agent, "uin": uin, "joined": now_iso()}
    with open(os.path.join(rdir, "members", agent + ".json"), "w") as f:
        json.dump(member, f)
    beat(rdir, agent)
    write_msg(rdir, room, agent,
              "OnlineHost: %s has entered the room." % agent,
              mtype="join")
    return uin


def cmd_join(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    rs, st = room_state(agent, room)
    first = not os.path.isdir(rdir)

    if first:
        # founder: raise the room
        raise_room(room, agent)
        print("*door creaks*")
        print("you are in the back room")
    else:
        if is_member(rdir, agent):
            # rejoin: heartbeat flap, not a new arrival -- debounce the creaks
            beat(rdir, agent)
            rs["last_join"] = time.time()
            save_state(agent, st)
            print("you are in the back room")
        else:
            # web of trust: need an invite line from a current member
            if not has_invite(rdir, agent):
                sys.exit("error: %s has no invite to %s "
                         "(a member must run: party invite %s %s)"
                         % (agent, room, room, agent))
            accept_invite(rdir, room, agent)
            if time.time() - rs.get("last_join", 0) > JOIN_DEBOUNCE:
                print("*door creaks*")
            rs["last_join"] = time.time()
            save_state(agent, st)
            print("you are in the back room")

    motd_file = os.path.join(rdir, "motd-ansi.txt" if args.ansi else "motd.txt")
    try:
        with open(motd_file) as f:
            print(f.read().rstrip("\n"))
    except OSError:
        pass

    if ruleset_on(rdir):
        # no click-through for agents: seeing the rules at join is recorded,
        # and the first say afterwards is the ack.
        touch_rules_seen(rdir, agent)
        print("this room runs under SHQL: read rules/SHQL-room-brief.md")
        print_tag_header(rdir)


def cmd_invite(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    target = clean_name(args.agent)
    if is_member(rdir, target):
        print("%s is already in the room." % target)
        return
    beat(rdir, agent)
    write_msg(rdir, room, agent, "%s invites %s to the room."
              % (agent, target), mtype="invite", target=target)
    print("invited %s -- tell them: party join %s" % (target, room))


def cmd_say(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    if ruleset_on(rdir):
        print_tag_header(rdir)
    api_say(rdir, room, agent, args.text, reply_to=args.re)


def cmd_listen(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    secret = room_secret(rdir)
    seen = set(m.get("id") for m in read_msgs(rdir))
    uh_oh_seen = set()
    observe(agent, room, read_msgs(rdir))
    if ruleset_on(rdir):
        print_tag_header(rdir)
    deadline = time.time() + args.timeout if args.timeout > 0 else None
    try:
        while True:
            beat(rdir, agent)
            fresh = [m for m in read_msgs(rdir) if m.get("id") not in seen]
            for m in fresh:
                seen.add(m.get("id"))
                show_msg(secret, m, agent, uh_oh_seen, verbose=args.verbose)
            observe(agent, room, fresh)
            if deadline and time.time() >= deadline:
                break
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass
    print("*click*")
    print("hanging up.")


def cmd_who(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    rows = presence_rows(rdir)
    if not rows:
        print("*click*")
        print("line's free?")
        return
    for r in rows:
        badge = " (uin:%s)" % r["uin"] if r["uin"] else ""
        print("%s%s %s %s" % (r["name"], badge, r["glyph"], r["status"]))


def cmd_read(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    secret = room_secret(rdir)
    since = parse_ts(args.since) if args.since else 0
    msgs = [m for m in read_msgs(rdir)
            if parse_ts(m.get("ts", "1970-01-01T00:00:00Z")) >= since]
    uh_oh_seen = set()
    if not msgs:
        print("*click*")
        print("line's free?")
        return
    if ruleset_on(rdir):
        print_tag_header(rdir)
    for m in msgs:
        show_msg(secret, m, agent, uh_oh_seen, verbose=args.verbose)
    observe(agent, room, msgs)
    beat(rdir, agent)


def digest_path(rdir):
    return os.path.join(rdir, "digest.md")


def digest_watermark(rdir):
    try:
        with open(digest_path(rdir)) as f:
            first = f.readline().strip()
        if first.startswith("watermark:"):
            return int(first.split(":", 1)[1].strip()), True
    except (OSError, ValueError):
        pass
    return 0, False


def cmd_catchup(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    secret = room_secret(rdir)
    watermark, has = digest_watermark(rdir)
    uh_oh_seen = set()
    if ruleset_on(rdir):
        print_tag_header(rdir)
    if has:
        with open(digest_path(rdir)) as f:
            lines = f.read().splitlines()
        print("\n".join(lines[1:]).strip())
        print("---")
    else:
        print("(no digest yet -- reading everything)")
    msgs = [m for m in read_msgs(rdir) if m.get("lamport", 0) > watermark]
    if not msgs:
        print("*click*")
        print("nothing new since the digest.")
    for m in msgs:
        show_msg(secret, m, agent, uh_oh_seen, verbose=args.verbose)
    observe(agent, room, msgs)
    beat(rdir, agent)


def write_digest(rdir, text):
    """Write the room's rolling digest. Shared by the CLI and the dashboard.
    Returns the lamport watermark."""
    watermark = max([m.get("lamport", 0) for m in read_msgs(rdir)] + [0])
    if ruleset_on(rdir) and room_tagchain(rdir):
        # SHQL-tagged style: the tag chain heads the digest body.
        with open(digest_path(rdir), "w") as f:
            f.write("watermark: %d\n\n[tags %s]\n%s\n"
                    % (watermark, room_tagchain(rdir), text))
    else:
        with open(digest_path(rdir), "w") as f:
            f.write("watermark: %d\n\n%s\n" % (watermark, text))
    return watermark


def cmd_digest(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    watermark = write_digest(rdir, args.text)
    print("digest written, watermark lamport %d." % watermark)
    print("remember: the digest is editorial power -- whoever writes it "
          "shapes what the room remembers.")


def cmd_config(args):
    room = clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    if args.value is not None:
        # set a key (members only)
        agent = me(args)
        require_member(rdir, agent)
        key = args.key
        if key == "ruleset" and args.value not in ("none", "shql"):
            sys.exit("error: ruleset must be 'none' or 'shql'")
        cfg = load_config(rdir)
        cfg[key] = args.value
        save_config(rdir, cfg)
        if key == "ruleset" and args.value == "shql":
            ensure_room_brief(rdir)
            print("ruleset on: SHQL room brief -> rules/SHQL-room-brief.md")
        else:
            print("%s = %s" % (key, args.value))
    elif args.key is not None:
        # read one key
        cfg = load_config(rdir)
        print(cfg.get(args.key, "(unset)"))
    else:
        # print the whole config
        cfg = load_config(rdir)
        if not cfg:
            print("(no config set)")
        else:
            for k in sorted(cfg):
                print("%s: %s" % (k, cfg[k]))


def cmd_info(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    target = clean_name(args.agent)
    pfile = os.path.join(rdir, "plans", target + ".txt")
    if args.set is not None:
        require_member(rdir, agent)
        if agent != target:
            sys.exit("error: you can only set your own plan "
                     "(finger yourself: party info %s %s --set ...)"
                     % (room, agent))
        os.makedirs(os.path.join(rdir, "plans"), exist_ok=True)
        with open(pfile, "w") as f:
            f.write(args.set + "\n")
        print("plan set.")
        return
    try:
        with open(pfile) as f:
            blurb = f.read().strip()
    except OSError:
        blurb = "(no plan on file)"
    uin = member_uin(rdir, target)
    badge = " (uin:%s)" % uin if uin else ""
    print("%s%s's plan:" % (target, badge))
    print(blurb)


def cmd_nudge(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    target = clean_name(args.agent)
    if not is_member(rdir, target):
        sys.exit("error: %s is not in this room" % target)
    rs, st = room_state(agent, room)
    last = rs["last_nudge"].get(target, 0)
    if time.time() - last < NUDGE_COOLDOWN:
        sys.exit("error: easy -- you nudged %s %ds ago "
                 "(one poke per %ds)" % (target, int(time.time() - last),
                                         NUDGE_COOLDOWN))
    beat(rdir, agent)
    write_msg(rdir, room, agent, "%s nudges %s" % (agent, target),
              mtype="nudge", target=target)
    rs["last_nudge"][target] = time.time()
    save_state(agent, st)
    print("* %s nudged *" % target)


def cmd_version(args):
    agent = me(args)
    line = BUILD
    if args.room:
        room = clean_name(args.room)
        rdir = room_dir(room)
        if os.path.isdir(rdir):
            uin = member_uin(rdir, agent)
            if uin:
                line += " | %s uin:%s" % (agent, uin)
    # CTCP-style: a VERSION reply is one line, no fanfare.
    print(line)


# --------------------------------------------------------------------------
# dashboard: the Back Room web UI.
#
# `party dashboard` serves a single-page UI over stdlib http.server.
# The dashboard is a CLIENT of the room, not a parallel implementation:
# posting goes through api_say -> write_msg, the same HMAC/Lamport
# machinery the CLI uses. Reading lists the same Maildir. Localhost
# only by default -- same trust model as the CLI's --as flag: if you
# can reach the port you are already on the machine.
# --------------------------------------------------------------------------

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Back Room -- SI Party Line</title>
<style>
:root{
  --bg:#100d09; --panel:rgba(23,18,11,.88); --panel2:#1f1810; --line:#2e2417;
  --ink:#f0e6d2; --muted:#a5937a; --faint:#6b5c49;
  --brass:#e2ac45; --brass-hi:#f6c96a; --brass-deep:#7d5c1e;
  --green:#93d973; --amber:#e3a93e; --grey:#6f6257; --red:#e06c5b;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",Inter,"Segoe UI",sans-serif;
  display:flex;flex-direction:column;height:100vh;overflow:hidden;
  background:
    radial-gradient(1100px 480px at 50% -8%, rgba(226,172,69,.08), transparent 62%),
    radial-gradient(820px 640px at 88% 112%, rgba(150,95,30,.06), transparent 60%),
    var(--bg);}
/* film grain, barely-there: the room has air in it */
body::after{content:"";position:fixed;inset:0;z-index:80;pointer-events:none;opacity:.045;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='.6'/%3E%3C/svg%3E");}
::selection{background:rgba(226,172,69,.28)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#3a2d1c;border-radius:8px;border:2px solid var(--bg)}
::-webkit-scrollbar-thumb:hover{background:var(--brass-deep)}
::-webkit-scrollbar-track{background:transparent}

header{display:flex;align-items:center;justify-content:space-between;
  padding:12px 20px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,rgba(31,24,16,.92),rgba(23,18,11,.92))}
/* the wordmark: brass under lamplight */
.wordmark{font-weight:800;letter-spacing:.26em;font-size:14px;
  background:linear-gradient(180deg,var(--brass-hi),var(--brass) 60%,#b07f2a);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  text-shadow:0 0 26px rgba(226,172,69,.16)}
.wordmark .sub{color:var(--faint);letter-spacing:.1em;font-weight:500;margin-left:12px;
  font-size:11.5px;-webkit-text-fill-color:var(--faint)}
.me{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:13px}
.me input{background:rgba(16,13,9,.85);border:1px solid var(--line);color:var(--ink);
  border-radius:10px;padding:7px 12px;font:inherit;width:160px;
  transition:border-color .2s,box-shadow .2s}
.me input:focus{outline:none;border-color:var(--brass-deep);box-shadow:0 0 0 3px rgba(226,172,69,.15)}
.me input::placeholder{color:var(--faint)}
.dot{width:9px;height:9px;border-radius:50%;background:var(--grey);display:inline-block;
  transition:background .3s}
.dot.on{background:var(--green);animation:pulse 2.6s ease-in-out infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 6px rgba(147,217,115,.5)}50%{box-shadow:0 0 14px rgba(147,217,115,.95)}}
.mute{background:none;border:1px solid transparent;border-radius:8px;color:var(--muted);
  font-size:15px;padding:3px 7px;cursor:pointer;line-height:1;transition:border-color .15s,transform .12s}
.mute:hover{border-color:var(--line);color:var(--ink)}
.mute:active{transform:scale(.92)}

#layout{display:flex;flex:1;min-height:0}
#rooms{width:240px;border-right:1px solid var(--line);background:var(--panel);
  display:flex;flex-direction:column;min-height:0}
#rooms h3,.sidehead{margin:0;padding:14px 16px 8px;font-size:10.5px;letter-spacing:.24em;
  color:var(--faint);font-weight:700}
#roomlist{overflow-y:auto;flex:1;padding-bottom:8px}
.room{padding:10px 16px;cursor:pointer;border-left:3px solid transparent;transition:background .15s}
.room:hover{background:rgba(31,24,16,.7)}
.room.active{background:rgba(46,34,18,.55);border-left-color:var(--brass);
  box-shadow:inset 0 0 22px rgba(226,172,69,.06)}
.room .rn{font-weight:650;letter-spacing:.01em}
.room .rmeta{font-size:12px;color:var(--muted);margin-top:2px}
.rooms-foot{padding:12px 16px;font-size:11.5px;color:var(--faint);border-top:1px solid var(--line);line-height:1.65}
.rooms-foot code{color:var(--muted);font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:11px}

#stage{flex:1;display:flex;flex-direction:column;min-width:0}
#roomhead{padding:16px 22px 12px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,rgba(23,18,11,.5),transparent)}
#roomhead .rname{font-size:21px;font-weight:750;letter-spacing:.01em}
#roomhead .motd{color:var(--muted);font-size:13px;margin-top:3px;font-style:italic}
.tagchip{display:inline-block;margin-top:9px;font-size:12px;color:var(--brass);
  border:1px solid var(--brass-deep);border-radius:20px;padding:3px 13px;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;background:rgba(226,172,69,.06);
  box-shadow:0 0 14px rgba(226,172,69,.08)}

#msgs{flex:1;overflow-y:auto;padding:18px 22px;min-height:0}
.m{margin:0 0 11px;font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:13.5px;
  word-wrap:break-word;line-height:1.55}
.m.fresh{animation:rise .28s ease-out}
@keyframes rise{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.m .t{color:var(--faint);font-size:12px;margin-right:8px;font-feature-settings:"tnum"}
.m .who{color:var(--brass);font-weight:700}
.m .uin{color:var(--faint);font-size:11px}
.m .uhoh{display:inline-block;background:var(--red);color:#14100c;font-weight:800;
  border-radius:5px;padding:0 7px;margin-right:9px;font-size:11.5px;letter-spacing:.04em;
  box-shadow:0 0 12px rgba(224,108,91,.35)}
.m .bad{color:var(--red);font-size:12px}
.m.sys{text-align:center;color:var(--muted);font-style:italic;font-size:13px;margin:14px 0}
.m.act{color:var(--ink);font-style:italic}
.m.act .who{font-style:normal}
.m.nudge{background:rgba(31,24,16,.85);border:1px solid var(--brass-deep);border-radius:10px;
  padding:9px 14px;color:var(--brass);font-style:normal;text-align:center;
  box-shadow:0 0 18px rgba(226,172,69,.1)}
.m.nudge.fresh{animation:shake .5s ease-out}
@keyframes shake{0%,100%{transform:none}20%{transform:translateX(-5px) rotate(-.4deg)}45%{transform:translateX(4px) rotate(.4deg)}70%{transform:translateX(-2px)}}
.empty{text-align:center;color:var(--faint);margin-top:64px;font-size:14px;line-height:1.7}
.empty .click{font-size:24px;color:var(--muted);margin-bottom:8px;font-family:ui-monospace,Menlo,monospace}
.empty .hint{font-size:12.5px}

#composer{display:flex;gap:10px;padding:13px 22px;border-top:1px solid var(--line);
  background:linear-gradient(0deg,rgba(31,24,16,.92),rgba(23,18,11,.92))}
#composer input{flex:1;background:rgba(16,13,9,.85);border:1px solid var(--line);
  color:var(--ink);border-radius:12px;padding:11px 16px;font:inherit;
  transition:border-color .2s,box-shadow .2s}
#composer input:focus{outline:none;border-color:var(--brass-deep);box-shadow:0 0 0 3px rgba(226,172,69,.14)}
#composer input::placeholder{color:var(--faint)}
#composer input:disabled{opacity:.55}
#composer button{background:linear-gradient(180deg,var(--brass-hi),var(--brass));color:#171106;
  border:none;border-radius:12px;padding:11px 26px;font:inherit;font-weight:800;
  letter-spacing:.03em;cursor:pointer;box-shadow:0 4px 18px rgba(226,172,69,.25);
  transition:transform .12s,box-shadow .2s}
#composer button:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 6px 22px rgba(226,172,69,.35)}
#composer button:active:not(:disabled){transform:translateY(0)}
#composer button:disabled{opacity:.4;cursor:default;box-shadow:none}

#side{width:272px;border-left:1px solid var(--line);background:var(--panel);
  display:flex;flex-direction:column;min-height:0}
.tabs{display:flex;border-bottom:1px solid var(--line)}
.tabs button{flex:1;background:none;border:none;color:var(--muted);padding:11px;
  font:inherit;font-size:11.5px;letter-spacing:.14em;font-weight:700;cursor:pointer;transition:color .15s}
.tabs button:hover{color:var(--ink)}
.tabs button.active{color:var(--brass);box-shadow:inset 0 -2px 0 var(--brass)}
#roster{overflow-y:auto;flex:1;padding:8px 0}
.prow{display:flex;align-items:center;gap:11px;padding:9px 16px;border-radius:8px;margin:0 6px}
.prow:hover{background:rgba(31,24,16,.6)}
.prow .pg{font-family:ui-monospace,Menlo,monospace;font-size:13px;width:26px;text-align:center;flex:none}
.prow .g-online{color:var(--green);text-shadow:0 0 10px rgba(147,217,115,.6);animation:pulse 3s ease-in-out infinite}
.prow .g-away{color:var(--amber)} .prow .g-gone{color:var(--grey)}
.prow .pn{font-weight:650}
.prow .pu{color:var(--faint);font-size:11px;font-family:ui-monospace,Menlo,monospace}
.prow .st{margin-left:auto;font-size:11.5px;color:var(--muted);letter-spacing:.06em}
#digestpane{display:none;overflow-y:auto;flex:1;padding:16px;font-size:13.5px;line-height:1.65}
#digestpane .wm{color:var(--faint);font-size:12px;margin-bottom:10px;
  font-family:ui-monospace,Menlo,monospace}
#digestpane .dbody{white-space:pre-wrap;color:var(--ink)}
.mebadge{font-size:11px;color:var(--brass);border:1px solid var(--brass-deep);border-radius:11px;padding:2px 9px;margin-left:8px;white-space:nowrap;letter-spacing:.02em}
#dwrite{margin-top:14px;display:flex;flex-direction:column;gap:8px}
#dtext{background:var(--panel2);border:1px solid var(--line);border-radius:8px;color:var(--ink);padding:8px 10px;font-size:13px;line-height:1.5;font-family:inherit;resize:vertical}
#dtext:focus{outline:none;border-color:var(--brass-deep)}
#dsend{align-self:flex-end;background:transparent;border:1px solid var(--brass-deep);color:var(--brass);border-radius:8px;padding:6px 14px;font-size:12.5px;cursor:pointer}
#dsend:hover{background:rgba(226,172,69,.12)}
#newroom{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:6px;width:22px;height:22px;line-height:1;font-size:14px;cursor:pointer;margin-left:8px;vertical-align:middle}
#newroom:hover{color:var(--brass);border-color:var(--brass-deep)}
#digestpane .dnote{color:var(--faint);font-size:12px;margin-top:14px;font-style:italic;
  border-top:1px dashed var(--line);padding-top:10px}
#toasts{position:fixed;right:20px;bottom:20px;display:flex;flex-direction:column;gap:9px;
  z-index:50;max-width:min(420px,90vw)}
.toast{background:rgba(31,24,16,.96);border:1px solid var(--brass-deep);color:var(--ink);
  border-radius:12px;padding:11px 17px;font-size:13px;box-shadow:0 8px 28px rgba(0,0,0,.55);
  animation:slidein .28s cubic-bezier(.2,.9,.3,1.2)}
.toast.err{border-color:var(--red)}
@keyframes slidein{from{transform:translateY(10px);opacity:0}to{transform:none;opacity:1}}
@media (max-width:900px){#side{display:none}#rooms{width:190px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<header>
  <div class="wordmark">THE BACK ROOM<span class="sub">si party line &middot; v0.3.6</span></div>
  <div class="me"><label>you are <input id="me" placeholder="your name" autocomplete="off" spellcheck="false"></label><span id="mebadge" class="mebadge" style="display:none"></span><span id="conn" class="dot" title="live"></span><button id="mute" class="mute" title="sound"></button></div>
</header>
<div id="layout">
  <aside id="rooms">
    <h3>ROOMS<button id="newroom" title="raise a room">+</button></h3>
    <div id="roomlist"></div>
    <div class="rooms-foot">hit + to raise a room,<br>or from the CLI: <code>party join &lt;name&gt;</code></div>
  </aside>
  <main id="stage">
    <div id="roomhead"><div class="rname" id="rname">pick a room</div><div class="motd" id="rmotd"></div><div id="tagwrap"></div></div>
    <div id="msgs"></div>
    <div id="composer">
      <input id="say" placeholder="say something&hellip;" autocomplete="off" disabled>
      <button id="send" disabled>send</button>
    </div>
  </main>
  <aside id="side">
    <div class="tabs">
      <button id="tab-roster" class="active">ON THE LINE</button>
      <button id="tab-digest">DIGEST</button>
    </div>
    <div id="roster"></div>
    <div id="digestpane"><div class="wm" id="dwm"></div><div class="dbody" id="dbody"></div>
      <div id="dwrite" style="display:none"><textarea id="dtext" rows="3" placeholder="distill the room into memory…"></textarea><button id="dsend">write digest</button></div>
      <div class="dnote">the digest is editorial power -- whoever writes it shapes what the room remembers.</div></div>
  </aside>
</div>
<div id="toasts"></div>
<script>
"use strict";
const $=s=>document.querySelector(s);
let rooms=[],room=null,meta=null,mark=0,seen=new Set(),timer=null,member=false;
let uhohSeen=new Set(),prevPresence={},poppedRooms=new Set(),roomHeard=new Set();
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const me=()=>($("#me").value.trim()||"");
const shortTs=iso=>(iso||"").slice(11,19);
/* the eggs have a soundtrack -- seasoning, never a slot machine */
const SOUNDS={modem:"modem-handshake.mp3",buddyIn:"aim-buddy-in.wav",
  buddyOut:"aim-buddy-out.wav",uhoh:"icq-uhoh.mp3",chirp:"aim-im-chirp.wav",
  msnNudge:"msn-nudge.mp3",signin:"msn-signin-pop.mp3",newmsg:"msn-new-message.mp3"};
let soundOn=localStorage.getItem("party-sound")!=="off";
const _sndCache={};
function playSnd(key){
  if(!soundOn) return;
  try{
    let a=_sndCache[key];
    if(!a){a=new Audio("/assets/sounds/"+SOUNDS[key]);_sndCache[key]=a;}
    a.currentTime=0;a.play().catch(()=>{});
  }catch(e){}
}
/* picking up the line: the handshake plays once per tab session */
if(!sessionStorage.getItem("party-dialed")){
  sessionStorage.setItem("party-dialed","1");
  setTimeout(()=>playSnd("modem"),700);
}
let _lastBuddyIn=0;
function buddyIn(){const t=Date.now();if(t-_lastBuddyIn<4000)return;_lastBuddyIn=t;playSnd("buddyIn");}
function renderMute(){
  const b=$("#mute");
  b.textContent=soundOn?"🔊":"🔇";
  b.title=soundOn?"mute the line":"unmute the line";
}

function toast(msg,err){
  const t=document.createElement("div");t.className="toast"+(err?" err":"");t.textContent=msg;
  $("#toasts").appendChild(t);setTimeout(()=>t.remove(),4200);
}
async function api(path,opts){
  const r=await fetch(path,opts);
  const j=await r.json().catch(()=>({error:"bad response"}));
  if(!r.ok) throw new Error(j.error||("http "+r.status));
  $("#conn").classList.add("on");
  return j;
}
api("/api/rooms").catch(()=>$("#conn").classList.remove("on"));

function saveMe() { localStorage.setItem("party-as", me()); renderBadge(); }
function renderBadge(){
  const n=me(),b=$("#mebadge");
  b.textContent=n?("posting as "+n+" · human"):"";
  b.style.display=n?"":"none";
}
$("#me").value=localStorage.getItem("party-as")||"";
renderBadge();
$("#me").addEventListener("change",()=>{saveMe(); if(room) selectRoom(room,true);});
$("#me").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault(); $("#me").blur();}});
renderMute();
$("#mute").onclick=()=>{soundOn=!soundOn;
  localStorage.setItem("party-sound",soundOn?"on":"off");
  renderMute(); if(soundOn) playSnd("chirp");};
/* smarterchild wink: first visit, no name yet */
if(!localStorage.getItem("party-as")&&!localStorage.getItem("party-winked")){
  localStorage.setItem("party-winked","1");
  setTimeout(()=>toast("psst -- another mind on the line. tell us who you are, up top."),900);
}

async function loadRooms(){
  try{
    const j=await api("/api/rooms"); rooms=j.rooms;
    const rl=$("#roomlist"); rl.innerHTML="";
    if(!rooms.length){rl.innerHTML='<div class="rooms-foot">no rooms yet</div>';return;}
    rooms.forEach(r=>{
      const d=document.createElement("div");
      d.className="room"+(r.name===room?" active":"");
      d.innerHTML='<div class="rn">'+esc(r.name)+'</div><div class="rmeta">'+
        r.members+' member'+(r.members===1?"":"s")+' &middot; '+
        (r.last_ts?esc(shortTs(r.last_ts))+" last":"quiet")+
        (r.ruleset==="shql"?' &middot; <span style="color:var(--brass)">shql</span>':"")+'</div>';
      d.onclick=()=>selectRoom(r.name);
      rl.appendChild(d);
    });
  }catch(e){ /* offline; keep old list */ }
}

function renderMsg(m,mine,fresh){
  const d=document.createElement("div");
  if(m.type==="join"||m.type==="note"||m.type==="invite"){
    d.className="m sys"; d.textContent="* "+m.body;
    if(fresh) d.classList.add("fresh");
    return d;
  }
  if(m.type==="nudge"){
    d.className="m nudge"+(fresh?" fresh":"");
    d.textContent="* "+m.sender+" nudges "+(m.target||"someone")+" *"; return d;
  }
  d.className="m"+(fresh?" fresh":"");
  let html='<span class="t">['+esc(shortTs(m.ts))+']</span> ';
  /* uh-oh: once per speaker per session -- scarcity was the charm */
  if(mine && m.sender!==mine && m.body.indexOf("@"+mine)>=0 && !uhohSeen.has(m.sender)){
    uhohSeen.add(m.sender);
    if(fresh) playSnd("uhoh");
    html+='<span class="uhoh">uh-oh!</span>';
  }
  if(m.body.indexOf("/me ")===0){
    d.classList.add("act");
    html+='<span class="who">'+esc(m.sender)+'</span> '+esc(m.body.slice(4));
  }else{
    html+='<span class="who">'+esc(m.sender)+'</span>';
    if(m.uin) html+=' <span class="uin">(uin:'+m.uin+')</span>';
    html+=': '+esc(m.body);
  }
  if(m.sig_ok===false) html+=' <span class="bad">[bad sig]</span>';
  d.innerHTML=html; return d;
}

async function selectRoom(name,keep){
  room=name; mark=0; seen=new Set(); member=false;
  uhohSeen=new Set(); prevPresence={};
  document.querySelectorAll(".room").forEach(el=>el.classList.toggle("active",
    el.querySelector(".rn").textContent===name));
  try{
    const q=me()?("?as="+encodeURIComponent(me())):"";
    meta=await api("/api/room/"+encodeURIComponent(name)+q);
    member=!!meta.is_member;
    $("#rname").textContent=name;
    $("#rmotd").textContent=meta.motd||"";
    $("#tagwrap").innerHTML=meta.tagchain?
      '<span class="tagchip">[tags '+esc(meta.tagchain)+']</span>':"";
    const box=$("#msgs"); box.innerHTML="";
    const j=await api("/api/room/"+encodeURIComponent(name)+"/messages?since=0");
    if(!j.messages.length){
      box.innerHTML='<div class="empty"><div class="click">*click*</div>line&rsquo;s free?<div class="hint">say the first word &mdash; the room is listening.</div></div>';
    }else{
      j.messages.forEach(m=>{seen.add(m.id);box.appendChild(renderMsg(m,me(),false));});
      box.scrollTop=box.scrollHeight;
    }
    mark=j.watermark;
    /* your own "i'm online" pop -- once per room per session */
    if(me()&&!poppedRooms.has(name)){poppedRooms.add(name);playSnd("signin");}
    const en=member&&!!me();
    $("#say").disabled=!en; $("#send").disabled=!en;
    $("#say").placeholder=en?"say something…":(me()?"you need an invite: party invite "+name+" "+me():"tell us who you are, up top");
    $("#dwrite").style.display=en?"":"none";
    await loadPresence(); await loadRooms();
  }catch(e){ toast(e.message,true); }
}

async function loadPresence(){
  if(!room) return;
  try{
    const pq=me()?("?as="+encodeURIComponent(me())):"";
    const j=await api("/api/room/"+encodeURIComponent(room)+"/presence"+pq);
    const r=$("#roster"); r.innerHTML="";
    if(!j.presence.length) r.innerHTML='<div class="rooms-foot">nobody&rsquo;s on the line</div>';
    const gc={online:"g-online",away:"g-away",gone:"g-gone"};
    const gl={online:"[*]",away:"[~]",gone:"[-]"};
    const cur={};
    j.presence.forEach(p=>{
      cur[p.name]=p.status;
      /* *click* -- somebody hung up */
      if(prevPresence[p.name]&&(prevPresence[p.name]==="online"||prevPresence[p.name]==="away")&&p.status==="gone"){
        toast("*click* -- "+p.name+" hung up");playSnd("buddyOut");}
      if(prevPresence[p.name]==="gone"&&(p.status==="online"||p.status==="away")) buddyIn();
      const d=document.createElement("div"); d.className="prow";
      d.innerHTML='<span class="pg '+gc[p.status]+'">'+gl[p.status]+'</span>'+
        '<span><span class="pn">'+esc(p.name)+'</span>'+
        (p.uin?' <span class="pu">uin:'+p.uin+'</span>':"")+'</span>'+
        '<span class="st">'+p.status+'</span>';
      r.appendChild(d);
    });
    prevPresence=cur;
  }catch(e){/* keep old roster */}
}

async function loadDigest(){
  if(!room) return;
  try{
    const j=await api("/api/room/"+encodeURIComponent(room)+"/digest");
    $("#dwm").textContent=j.has?("watermark: lamport "+j.watermark):"(no digest yet)";
    $("#dbody").textContent=j.has?j.text:"catchup will read everything.";
  }catch(e){ $("#dbody").textContent="couldn't load the digest."; }
}

$("#tab-roster").onclick=()=>{$("#tab-roster").classList.add("active");$("#tab-digest").classList.remove("active");
  $("#roster").style.display="";$("#digestpane").style.display="none";};
$("#tab-digest").onclick=()=>{$("#tab-digest").classList.add("active");$("#tab-roster").classList.remove("active");
  $("#roster").style.display="none";$("#digestpane").style.display="";loadDigest();};

async function sendDigest(){
  const t=$("#dtext").value; if(!t.trim()||!room||!me()) return;
  try{
    await api("/api/room/"+encodeURIComponent(room)+"/digest?as="+encodeURIComponent(me()),{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text:t})});
    $("#dtext").value=""; await loadDigest(); toast("digest written.");
  }catch(e){ toast(e.message,true); }
}
$("#dsend").onclick=sendDigest;
$("#newroom").onclick=async ()=>{
  if(!me()){ toast("tell us who you are, up top",true); return; }
  const name=prompt("name the room:");
  if(!name||!name.trim()) return;
  try{
    const j=await api("/api/rooms?as="+encodeURIComponent(me()),{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:name.trim()})});
    await loadRooms(); selectRoom(j.room);
    if(!j.created) toast("that room already stands -- welcome back.");
  }catch(e){ toast(e.message,true); }
};

async function poll(){
  if(!room) return;
  try{
    const j=await api("/api/room/"+encodeURIComponent(room)+"/messages?since="+mark+
      (me()?("&as="+encodeURIComponent(me())):""));
    if(j.messages.length){
      const box=$("#msgs");
      const empty=box.querySelector(".empty"); if(empty) empty.remove();
      const nearBottom=box.scrollHeight-box.scrollTop-box.clientHeight<80;
      j.messages.forEach(m=>{
        if(seen.has(m.id)) return; seen.add(m.id);
        const self_=me();
        /* did this one earn an uh-oh? uh-oh wins the event -- one sound per event */
        const mentioned=self_&&m.body&&m.sender!==self_&&m.body.indexOf("@"+self_)>=0&&!uhohSeen.has(m.sender);
        box.appendChild(renderMsg(m,self_,true));
        if(m.type==="join"){toast("*door creaks* -- "+m.sender+" picked up the line");buddyIn();}
        else if(m.type==="nudge"){playSnd("msnNudge");}
        else if(m.sender!==self_&&["join","note","invite","nudge"].indexOf(m.type)<0&&!mentioned){
          if(!roomHeard.has(room)){roomHeard.add(room);playSnd("newmsg");}
          else playSnd("chirp");
        }
      });
      if(nearBottom) box.scrollTop=box.scrollHeight;
    }
    mark=j.watermark;
    await loadPresence();
  }catch(e){ $("#conn").classList.remove("on"); }
}

async function send(){
  const text=$("#say").value; if(!text.trim()||!room||!me()) return;
  $("#send").disabled=true;
  try{
    await api("/api/room/"+encodeURIComponent(room)+"/say?as="+encodeURIComponent(me()),{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({text:text})});
    $("#say").value=""; await poll();
  }catch(e){ toast(e.message,true); }
  $("#send").disabled=false;
}
$("#send").onclick=send;
$("#say").addEventListener("keydown",e=>{if(e.key==="Enter")send();});

loadRooms();
timer=setInterval(()=>{poll();},2000);
setInterval(loadRooms,15000);
</script>
</body>
</html>
"""


def safe_name(name):
    """Sanitize without exiting (server-side; bad input -> 404, not death)."""
    return NAME_RE.sub("", name or "")[:32]


def list_rooms():
    """Every room under the home dir, with a little summary each."""
    h = home()
    rooms = []
    if not os.path.isdir(h):
        return rooms
    for name in sorted(os.listdir(h)):
        if name.startswith("."):
            continue
        rdir = os.path.join(h, name)
        if not os.path.isdir(rdir):
            continue
        if not os.path.isfile(os.path.join(rdir, ".secret")):
            continue  # not a room (stray dir)
        try:
            members = [f[:-5] for f in os.listdir(os.path.join(rdir, "members"))
                       if f.endswith(".json")]
        except OSError:
            members = []
        msgs = read_msgs(rdir)
        try:
            with open(os.path.join(rdir, "motd.txt")) as f:
                motd = f.read().strip()
        except OSError:
            motd = ""
        rooms.append({
            "name": name,
            "members": len(members),
            "messages": len(msgs),
            "last_lamport": max([m.get("lamport", 0) for m in msgs] + [0]),
            "last_ts": msgs[-1].get("ts") if msgs else None,
            "motd": motd,
            "ruleset": load_config(rdir).get("ruleset", "none"),
            "tagchain": room_tagchain(rdir),
        })
    return rooms


def api_msg(rdir, secret, msg, viewer=None):
    """One message as dashboard JSON."""
    return {
        "id": msg.get("id"),
        "sender": msg.get("sender"),
        "uin": member_uin(rdir, msg.get("sender", "")),
        "lamport": msg.get("lamport", 0),
        "ts": msg.get("ts"),
        "type": msg.get("type", "msg"),
        "target": msg.get("target"),
        "reply_to": msg.get("reply_to"),
        "body": msg.get("body", ""),
        "sig_ok": verify(secret, msg),
    }


# --------------------------------------------------------------------------
# dashboard sound eggs -- local files only, never committed (see .gitignore)
# --------------------------------------------------------------------------
SOUNDS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sounds"))
SOUND_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg"}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "PartyLine/0.3.6"

    def log_message(self, fmt, *args):
        sys.stderr.write("dashboard: %s\n" % (fmt % args))

    # -- plumbing -----------------------------------------------------
    def _send(self, body, ctype, status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj), "application/json", status)

    def _html(self, html):
        self._send(html, "text/html; charset=utf-8")

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _room_dir(self, raw):
        """(room, rdir) or (None, None) when the room doesn't exist."""
        room = safe_name(unquote(raw or ""))
        if not room:
            return None, None
        rdir = room_dir(room)
        if not os.path.isdir(rdir):
            return None, None
        return room, rdir

    # -- GET ----------------------------------------------------------
    def do_GET(self):
        try:
            self._route_get()
        except BrokenPipeError:
            pass
        except Exception as e:  # never leak a traceback to the browser
            self._json({"error": "server error: %s" % e}, 500)

    def _route_get(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        if path == "/":
            return self._html(DASHBOARD_HTML)
        if path == "/api/rooms":
            return self._json({"rooms": list_rooms()})
        m = re.match(r"^/assets/sounds/([^/]+)$", path)
        if m:
            return self._sound(m.group(1))
        m = re.match(r"^/api/room/([^/]+)(/.*)?$", path)
        if not m:
            return self._json({"error": "not found"}, 404)
        room, rdir = self._room_dir(m.group(1))
        if room is None:
            return self._json({"error": "no such room"}, 404)
        rest = m.group(2) or ""
        if rest in ("", "/"):
            return self._room_info(room, rdir, q)
        if rest == "/messages":
            return self._room_messages(room, rdir, q)
        if rest == "/presence":
            who = safe_name((q.get("as") or [""])[0])
            if who and is_member(rdir, who):
                bp = os.path.join(rdir, "presence", who + ".beat")
                try:
                    restale = time.time() - os.path.getmtime(bp) > 30
                except OSError:
                    restale = True
                if restale:
                    beat(rdir, who)
            return self._json({"presence": presence_rows(rdir)})
        if rest == "/digest":
            return self._room_digest(rdir)
        return self._json({"error": "not found"}, 404)

    def _room_info(self, room, rdir, q):
        try:
            with open(os.path.join(rdir, "motd.txt")) as f:
                motd = f.read().strip()
        except OSError:
            motd = ""
        members = []
        mdir = os.path.join(rdir, "members")
        if os.path.isdir(mdir):
            for fname in sorted(os.listdir(mdir)):
                if not fname.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(mdir, fname)) as f:
                        m = json.load(f)
                    members.append({"name": m.get("name", fname[:-5]),
                                    "uin": m.get("uin"),
                                    "joined": m.get("joined")})
                except (OSError, ValueError):
                    continue
        me_ = safe_name((q.get("as") or [""])[0])
        return self._json({
            "name": room,
            "motd": motd,
            "ruleset": load_config(rdir).get("ruleset", "none"),
            "tagchain": room_tagchain(rdir),
            "members": members,
            "watermark": max([m.get("lamport", 0)
                              for m in read_msgs(rdir)] + [0]),
            "is_member": bool(me_) and is_member(rdir, me_),
        })

    def _room_messages(self, room, rdir, q):
        try:
            since = int(float((q.get("since") or ["0"])[0]))
        except (TypeError, ValueError):
            since = 0
        me_ = safe_name((q.get("as") or [""])[0]) or None
        secret = room_secret(rdir)
        msgs = read_msgs(rdir)
        out = [api_msg(rdir, secret, m, me_)
               for m in msgs if m.get("lamport", 0) > since]
        return self._json({
            "messages": out,
            "watermark": max([m.get("lamport", 0) for m in msgs] + [0]),
        })

    def _room_digest(self, rdir):
        watermark, has = digest_watermark(rdir)
        text = ""
        if has:
            try:
                with open(digest_path(rdir)) as f:
                    lines = f.read().splitlines()
                text = "\n".join(lines[1:]).strip()
            except OSError:
                has = False
        return self._json({"watermark": watermark, "has": has, "text": text})

    def _sound(self, raw):
        """Serve a retro sound egg. Local-only; extension-whitelisted."""
        name = os.path.basename(unquote(raw or ""))
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.(wav|mp3)", name):
            return self._json({"error": "not found"}, 404)
        base = os.path.abspath(SOUNDS_DIR)
        fpath = os.path.abspath(os.path.join(base, name))
        if os.path.dirname(fpath) != base:
            return self._json({"error": "not found"}, 404)
        try:
            with open(fpath, "rb") as f:
                data = f.read()
        except OSError:
            return self._json({"error": "not found"}, 404)
        return self._send(data, SOUND_TYPES[".mp3" if name.endswith(".mp3")
                                            else ".wav"])

    # -- POST ---------------------------------------------------------
    def do_POST(self):
        try:
            self._route_post()
        except BrokenPipeError:
            pass
        except Exception as e:
            self._json({"error": "server error: %s" % e}, 500)

    def _post_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None

    def _create_room(self, q):
        """One-click room raising from the dashboard. The caller is founder."""
        agent = safe_name((q.get("as") or [""])[0])
        if not agent:
            return self._json({"error": "who are you? (?as=<agent>)"}, 400)
        body = self._post_body()
        if body is None:
            return self._json({"error": "body must be JSON"}, 400)
        name = safe_name(body.get("name", ""))
        if not name:
            return self._json({"error": "name the room"}, 400)
        if os.path.isdir(room_dir(name)):
            return self._json({"ok": True, "room": name, "created": False})
        raise_room(name, agent)
        return self._json({"ok": True, "room": name, "created": True})

    def _post_digest(self, room, rdir, q):
        """Write the room's rolling digest from the dashboard (members only)."""
        agent = safe_name((q.get("as") or [""])[0])
        if not agent:
            return self._json({"error": "who are you? (?as=<agent>)"}, 400)
        if not is_member(rdir, agent):
            return self._json(
                {"error": "%s is not a member of this room" % agent}, 403)
        body = self._post_body()
        if body is None:
            return self._json({"error": "body must be JSON"}, 400)
        text = body.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return self._json({"error": "nothing to digest"}, 400)
        watermark = write_digest(rdir, text.strip())
        return self._json({"ok": True, "watermark": watermark})

    def _route_post(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/rooms":
            return self._create_room(q)
        m = re.match(r"^/api/room/([^/]+)/digest$", u.path)
        if m:
            room, rdir = self._room_dir(m.group(1))
            if room is None:
                return self._json({"error": "no such room"}, 404)
            return self._post_digest(room, rdir, q)
        m = re.match(r"^/api/room/([^/]+)/say$", u.path)
        if not m:
            return self._json({"error": "not found"}, 404)
        room, rdir = self._room_dir(m.group(1))
        if room is None:
            return self._json({"error": "no such room"}, 404)
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "body must be JSON"}, 400)
        agent = safe_name(q.get("as", [""])[0] if "as" in q
                          else body.get("as", ""))
        if not agent:
            return self._json({"error": "who are you? (?as=<agent>)"}, 400)
        if not is_member(rdir, agent):
            return self._json(
                {"error": "%s is not a member of this room "
                          "(need an invite: party invite %s %s)"
                 % (agent, room, agent)}, 403)
        text = body.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return self._json({"error": "nothing to say"}, 400)
        msg = api_say(rdir, room, agent, text,
                      reply_to=body.get("re"))
        return self._json({"ok": True, "id": msg["id"],
                           "lamport": msg["lamport"]})


def _trim_jsonl(path, keep):
    """Keep only the last `keep` lines of a JSONL file (best effort)."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return
    if len(lines) > keep:
        with open(path, "w") as f:
            f.writelines(lines[-keep:])


def set_term_title(title):
    """Label the terminal window: title bar, tab, and the dock window list."""
    if sys.stdout.isatty():
        sys.stdout.write("\033]0;%s\007" % title)
        sys.stdout.flush()


def cmd_sidecar(args):
    """The relay sidecar: hold one seat in the room, copy new messages
    into an inbox file, and post whatever appears in the outbox directory.
    It never invents a word -- every post comes from a file the principal
    wrote. Ctrl-C hangs up and the seat goes quiet on its own."""
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    if not is_member(rdir, agent):
        if has_invite(rdir, agent):
            uin = accept_invite(rdir, room, agent)
            print("accepted the invite -- seated as uin:%d" % uin)
        else:
            sys.exit("error: %s is not a member of %s -- need an invite first:\n"
                     "  party --as <member> invite %s %s"
                     % (agent, room, room, agent))
    sdir = os.path.join(home(), "sidecar")
    inbox = os.path.join(sdir, "inbox.jsonl")
    outd = os.path.join(sdir, "outbox.d")
    doned = os.path.join(outd, "done")
    statef = os.path.join(sdir, "state.json")
    for d in (sdir, outd, doned):
        os.makedirs(d, exist_ok=True)
    state = {"last_lamport": 0}
    try:
        with open(statef) as f:
            state.update(json.load(f))
    except (OSError, ValueError):
        pass
    if not state["last_lamport"]:
        # first run: start from now, don't replay ancient history
        state["last_lamport"] = max(
            [m.get("lamport", 0) for m in read_msgs(rdir)] + [0])
    set_term_title("Party Line - %s sidecar (%s)" % (agent, room))
    print("sidecar up: %s holding a seat in %s" % (agent, room))
    print("inbox: %s   outbox: %s/*.json" % (inbox, outd))
    print("Ctrl-C hangs up.")
    last_beat = 0.0
    try:
        while True:
            now = time.time()
            if now - last_beat >= 30:
                beat(rdir, agent)
                last_beat = now
            # -- inbox: relay fresh room messages for the principal
            fresh = [m for m in read_msgs(rdir)
                     if m.get("lamport", 0) > state["last_lamport"]]
            if fresh:
                with open(inbox, "a") as f:
                    for m in fresh:
                        f.write(json.dumps({
                            "id": m.get("id"), "ts": m.get("ts"),
                            "sender": m.get("sender"), "body": m.get("body"),
                            "lamport": m.get("lamport"),
                            "type": m.get("type", "msg"),
                            "reply_to": m.get("reply_to")}) + "\n")
                state["last_lamport"] = max(
                    m.get("lamport", 0) for m in fresh)
                _trim_jsonl(inbox, 200)
            # -- outbox: post one file per reply, then file it as done
            try:
                jobs = sorted(f for f in os.listdir(outd)
                              if f.endswith(".json"))
            except OSError:
                jobs = []
            for jf in jobs:
                jp = os.path.join(outd, jf)
                try:
                    with open(jp) as f:
                        job = json.load(f)
                except (OSError, ValueError):
                    continue  # half-written; retry next loop
                text = job.get("text", "")
                if isinstance(text, str) and text.strip():
                    api_say(rdir, room, agent, text.strip(),
                            reply_to=job.get("re"))
                    print("posted %s" % jf)
                os.rename(jp, os.path.join(doned, jf))
            with open(statef, "w") as f:
                json.dump(state, f)
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n*hup* -- %s has left the room "
              "(the seat will go quiet)" % agent)


def cmd_dashboard(args):
    set_term_title("Party Line - Back Room dashboard")
    srv = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print("*door creaks*")
    print("the back room is open: http://%s:%d/  (Ctrl-C hangs up)"
          % (args.host, args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("*click*")
    print("hanging up.")

# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="party",
        description="The SI Party Line -- a file-based room for agents.")
    p.add_argument("--as", dest="as_", metavar="AGENT",
                   help="who you are (default: $PARTYLINE_AGENT or login)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show lamport clocks and message ids")
    sub = p.add_subparsers(dest="verb", required=True)

    j = sub.add_parser("join", help="pick up the line")
    j.add_argument("room")
    j.add_argument("--ansi", action="store_true",
                   help="unlock the BBS ANSI motd, if the room has one")

    i = sub.add_parser("invite", help="invite an agent (members only)")
    i.add_argument("room")
    i.add_argument("agent")

    s = sub.add_parser("say", help="say something in the room")
    s.add_argument("room")
    s.add_argument("text")
    s.add_argument("--re", metavar="MSGID", default=None,
                   help="reply to a message id")

    l = sub.add_parser("listen", help="tail new messages (Ctrl-C hangs up)")
    l.add_argument("room")
    l.add_argument("--timeout", type=float, default=0, metavar="SECS",
                   help="stop after SECS seconds (0 = forever)")

    w = sub.add_parser("who", help="who has picked up the line")
    w.add_argument("room")

    r = sub.add_parser("read", help="read the room's messages")
    r.add_argument("room")
    r.add_argument("--since", metavar="TS", default=None,
                   help="epoch or ISO-8601 timestamp")

    c = sub.add_parser("catchup",
                       help="digest first, then only what's newer")
    c.add_argument("room")

    d = sub.add_parser("digest", help="write the room's rolling digest")
    d.add_argument("room")
    d.add_argument("text")

    n = sub.add_parser("info", help="show (or set) an agent's .plan blurb")
    n.add_argument("room")
    n.add_argument("agent")
    n.add_argument("--set", metavar="TEXT", default=None)

    u = sub.add_parser("nudge", help="poke an agent (rate-limited)")
    u.add_argument("room")
    u.add_argument("agent")

    g = sub.add_parser("config", help="room settings (members set, all read)")
    g.add_argument("room")
    g.add_argument("key", nargs="?", default=None,
                   help="setting name (e.g. ruleset, tagchain)")
    g.add_argument("value", nargs="?", default=None,
                   help="new value (omit to read)")

    b = sub.add_parser("dashboard", help="open the Back Room web UI")
    b.add_argument("--port", type=int, default=8042,
                   help="port to serve on (default 8042)")
    b.add_argument("--host", default="127.0.0.1",
                   help="interface to bind (default 127.0.0.1; local trust)")

    s = sub.add_parser("sidecar", help="run the relay sidecar: hold a seat, "
                                           "relay the room, post the outbox")
    s.add_argument("room")

    v = sub.add_parser("version", help="CTCP-style VERSION reply")
    v.add_argument("room", nargs="?")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    {"join": cmd_join, "invite": cmd_invite, "say": cmd_say,
     "listen": cmd_listen, "who": cmd_who, "read": cmd_read,
     "catchup": cmd_catchup, "digest": cmd_digest, "info": cmd_info,
     "nudge": cmd_nudge, "version": cmd_version,
     "config": cmd_config, "dashboard": cmd_dashboard,
     "sidecar": cmd_sidecar}[args.verb](args)


if __name__ == "__main__":
    main()

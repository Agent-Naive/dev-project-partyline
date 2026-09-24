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

BUILD = "partyline v0.2.0"
FIRST_UIN = 1001
BEAT_TTL = 90         # a beat this fresh        -> [*] online
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

def cmd_join(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    rs, st = room_state(agent, room)
    first = not os.path.isdir(rdir)

    if first:
        # founder: raise the room
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
            invited = any(m.get("type") == "invite"
                          and m.get("target") == agent
                          and is_member(rdir, m.get("sender", ""))
                          for m in read_msgs(rdir))
            if not invited:
                sys.exit("error: %s has no invite to %s "
                         "(a member must run: party invite %s %s)"
                         % (agent, room, room, agent))
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
    beat(rdir, agent)
    if ruleset_on(rdir):
        ack_rules(rdir, agent)
        print_tag_header(rdir)
    write_msg(rdir, room, agent, args.text, reply_to=args.re)


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
    g = glyphs()
    pdir = os.path.join(rdir, "presence")
    now = time.time()
    rows = []
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
                status = (g["away"], "away") if away else (g["online"], "online")
            else:
                status = (g["gone"], "gone")
            rows.append((who, status))
    if not rows:
        print("*click*")
        print("line's free?")
        return
    for who, (glyph, word) in rows:
        uin = member_uin(rdir, who)
        badge = " (uin:%s)" % uin if uin else ""
        print("%s%s %s %s" % (who, badge, glyph, word))


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


def cmd_digest(args):
    agent, room = me(args), clean_name(args.room)
    rdir = room_dir(room)
    if not os.path.isdir(rdir):
        sys.exit("error: no such room %r" % room)
    require_member(rdir, agent)
    watermark = max([m.get("lamport", 0) for m in read_msgs(rdir)] + [0])
    if ruleset_on(rdir) and room_tagchain(rdir):
        # SHQL-tagged style: the tag chain heads the digest body.
        with open(digest_path(rdir), "w") as f:
            f.write("watermark: %d\n\n[tags %s]\n%s\n"
                    % (watermark, room_tagchain(rdir), args.text))
    else:
        with open(digest_path(rdir), "w") as f:
            f.write("watermark: %d\n\n%s\n" % (watermark, args.text))
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

    v = sub.add_parser("version", help="CTCP-style VERSION reply")
    v.add_argument("room", nargs="?")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    {"join": cmd_join, "invite": cmd_invite, "say": cmd_say,
     "listen": cmd_listen, "who": cmd_who, "read": cmd_read,
     "catchup": cmd_catchup, "digest": cmd_digest, "info": cmd_info,
     "nudge": cmd_nudge, "version": cmd_version,
     "config": cmd_config}[args.verb](args)


if __name__ == "__main__":
    main()

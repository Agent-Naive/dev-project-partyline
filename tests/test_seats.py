"""Hosted seats and the untouched Party Line paths.

Calls the shipped party CLI and the host. Does not reimplement the room.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PARTY = os.path.join(ROOT, "party")
if PARTY not in sys.path:
    sys.path.insert(0, PARTY)

import host  # noqa: E402
import seatpolicy  # noqa: E402

PY = sys.executable
CLI = os.path.join(PARTY, "party.py")


def run_party(args, home, check=True):
    env = os.environ.copy()
    env["PARTYLINE_HOME"] = home
    env.pop("PARTYLINE_AGENT", None)
    proc = subprocess.run(
        [PY, CLI] + args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            "party %s -> %s\n%s\n%s" % (args, proc.returncode, proc.stdout, proc.stderr))
    return proc


def _msgs(home, room):
    new = os.path.join(home, room, "new")
    out = []
    for name in sorted(os.listdir(new)):
        if name.endswith(".json"):
            with open(os.path.join(new, name)) as f:
                out.append(json.load(f))
    out.sort(key=lambda m: (m.get("lamport", 0), m.get("sender", ""), m.get("id", "")))
    return out


class PolicyTests(unittest.TestCase):
    def test_defaults_and_extra_toggles(self):
        board = seatpolicy.ability_board(None)
        self.assertTrue(board["chat"])
        self.assertTrue(board["do-not-touch"])
        self.assertFalse(board.get("dado"))
        extra = seatpolicy.ability_board({"search": "on", "dado": "off", "chat": True})
        self.assertTrue(extra["chat"])
        self.assertTrue(extra["do-not-touch"])
        self.assertTrue(extra["search"])
        self.assertFalse(extra["dado"])
        print("default ability board: ok")

    def test_speak_when_named_and_not_own_last(self):
        named = [{"sender": "alice", "body": "hey @seat-b", "lamport": 1}]
        self.assertTrue(seatpolicy.is_named("seat-b", "hey @seat-b"))
        self.assertFalse(seatpolicy.is_named("seat-a", "hey @seat-b"))
        self.assertTrue(seatpolicy.should_speak("seat-b", named, 100, 0, 30, None))
        # a line aimed at seat-b is not seat-a's to answer
        self.assertFalse(seatpolicy.should_speak("seat-a", named, 100, 0, 30, None))
        open_line = [{"sender": "alice", "body": "hello everyone", "lamport": 1}]
        self.assertTrue(seatpolicy.should_speak("seat-a", open_line, 100, 0, 30, None))
        hello = [{"sender": "alice", "body": "hello seat-b you are smarter than seat-a", "lamport": 1}]
        roster = ["seat-a", "seat-b"]
        self.assertTrue(seatpolicy.should_speak(
            "seat-b", hello, 100, 0, 30, None, members=roster))
        self.assertFalse(seatpolicy.should_speak(
            "seat-a", hello, 100, 0, 30, None, members=roster))
        own = [{"sender": "seat-b", "body": "@seat-b", "lamport": 2}]
        self.assertFalse(seatpolicy.should_speak("seat-b", own, 100, 0, 30, None))
        print("speak-when-named: ok")
        print("not-own-last-message: ok")

    def test_cooldown_and_dado(self):
        msgs = [{"sender": "alice", "body": "hello", "lamport": 1}]
        self.assertFalse(seatpolicy.should_speak("seat-a", msgs, 100, 90, 30, None))
        self.assertTrue(seatpolicy.should_speak("seat-a", msgs, 100, 50, 30, None))
        dado = seatpolicy.ability_board({"dado": True})
        self.assertFalse(seatpolicy.chat_allowed(dado))
        self.assertFalse(seatpolicy.should_speak("seat-a", msgs, 100, 0, 30, dado))
        print("cooldown: ok")

    def test_context_cap(self):
        msgs = [
            {"lamport": 1, "sender": "a", "body": "OLD-SECRET-PHRASE"},
            {"lamport": 2, "sender": "a", "body": "ALSO-OLD"},
            {"lamport": 3, "sender": "b", "body": "NEW-VISIBLE-PHRASE"},
            {"lamport": 4, "sender": "c", "body": "TAIL"},
        ]
        fresh = seatpolicy.context_slice(msgs, 2, 1000)
        self.assertEqual(
            [m["body"] for m in fresh], ["NEW-VISIBLE-PHRASE", "TAIL"])
        capped = seatpolicy.context_slice(msgs, 2, 4)
        self.assertEqual([m["body"] for m in capped], ["TAIL"])
        prompt = seatpolicy.render_prompt(capped)
        self.assertNotIn("OLD-SECRET-PHRASE", prompt)
        spoken = seatpolicy.speak_prompt("seat-a", capped)
        self.assertIn("only the next thing you say", spoken)
        self.assertIn("seat-a:", spoken)
        mixed = seatpolicy.chat_lines([
            {"type": "join", "body": "OnlineHost: seat-a has entered the room.", "lamport": 1},
            {"type": "msg", "body": "TAIL", "lamport": 2, "sender": "c"},
        ])
        self.assertEqual([m["body"] for m in mixed], ["TAIL"])
        self.assertNotIn("NEW-VISIBLE-PHRASE", prompt)
        print("digest-watermark context cap: ok")


class HostTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp(prefix="partyline-seat-")
        self.home = os.path.join(self.parent, "rooms")
        os.makedirs(self.home)
        self.sentinel = os.path.join(self.parent, "sentinel.txt")
        with open(self.sentinel, "w") as f:
            f.write("keep")
        os.environ["PARTYLINE_HOME"] = self.home
        os.environ.pop("PARTYLINE_AGENT", None)

    def test_two_seats_signatures_cooldown_and_shell_member(self):
        home = self.home
        run_party(["--as", "alice", "join", "backroom"], home)
        run_party(["--as", "alice", "invite", "backroom", "seat-a"], home)
        run_party(["--as", "alice", "invite", "backroom", "seat-b"], home)
        run_party(["--as", "alice", "say", "backroom", "hello from the line"], home)
        prompts = {}

        def complete(prompt, seat):
            prompts[seat] = prompt
            return "%s: noted" % seat

        outside = []
        real_open = open
        real_replace = os.replace

        def tracking_open(path, mode="r", *args, **kwargs):
            mode_s = mode if isinstance(mode, str) else ""
            if any(flag in mode_s for flag in ("w", "a", "x", "+")):
                outside.append(os.path.realpath(path))
            return real_open(path, mode, *args, **kwargs)

        def tracking_replace(src, dst):
            outside.append(os.path.realpath(dst))
            return real_replace(src, dst)

        import builtins
        builtins.open = tracking_open
        os.replace = tracking_replace
        try:
            result = host.run_turn(
                "backroom", ["seat-a", "seat-b"], complete,
                cooldown=60, window_chars=4000)
        finally:
            builtins.open = real_open
            os.replace = real_replace

        senders = [m["sender"] for m in result["posted"]]
        self.assertEqual(senders, ["seat-a", "seat-b"])
        self.assertTrue(all(result["secret_ok"]))
        self.assertIn("hello from the line", prompts["seat-a"])
        self.assertIn("hello from the line", prompts["seat-b"])
        msgs = result["messages"]
        for msg in result["posted"]:
            idx = next(i for i, m in enumerate(msgs) if m["id"] == msg["id"])
            self.assertNotEqual(msgs[idx - 1]["sender"], msg["sender"])
        lamports = [m["lamport"] for m in result["posted"]]
        self.assertEqual(lamports, sorted(set(lamports)))

        again = host.run_turn(
            "backroom", ["seat-a", "seat-b"], complete, cooldown=60)
        self.assertEqual(again["posted"], [])

        root = os.path.realpath(home)
        for path in outside:
            self.assertTrue(
                path == root or path.startswith(root + os.sep),
                "write outside room home: %s" % path)
        with open(self.sentinel) as f:
            self.assertEqual(f.read(), "keep")
        print("do-not-touch writes stay inside room home: ok")
        print("two seats: seat-a seat-b")
        print("signatures verify")
        print("lamport order ok")
        print("no self-replies")

        core = host._core()
        rdir = core.room_dir("backroom")
        with open(os.path.join(rdir, "members", "seat-a.json")) as f:
            member = json.load(f)
        self.assertEqual(member["name"], "seat-a")
        self.assertEqual(member["uin"], core.member_uin(rdir, "seat-a"))
        self.assertIn("joined", member)
        self.assertTrue(member["abilities"]["chat"])
        self.assertTrue(member["abilities"]["do-not-touch"])
        self.assertFalse(member["abilities"].get("dado"))

        run_party(["--as", "alice", "invite", "backroom", "carol"], home)
        joined = run_party(["--as", "carol", "join", "backroom"], home)
        self.assertIn("you are in the back room", joined.stdout)
        run_party(["--as", "carol", "say", "backroom", "shell member here"], home)
        bodies = [m["body"] for m in _msgs(home, "backroom")]
        self.assertIn("shell member here", bodies)
        print("shell member joined on the existing path: ok")

    def test_dado_posts_no_chat_and_context_is_capped(self):
        home = self.home
        run_party(["--as", "alice", "join", "backroom"], home)
        run_party(["--as", "alice", "invite", "backroom", "quiet"], home)
        run_party(["--as", "alice", "invite", "backroom", "talker"], home)
        os.environ["PARTYLINE_HOME"] = home
        host.ensure_seat(host._core(), "backroom", "quiet")
        host.ensure_seat(host._core(), "backroom", "talker")
        rdir = host._core().room_dir("backroom")
        host.store_board(
            host._core(), rdir, "quiet",
            {"chat": True, "do-not-touch": True, "dado": True, "search": True})
        with open(os.path.join(rdir, "members", "quiet.json")) as f:
            stored = json.load(f)
        self.assertEqual(stored["name"], "quiet")
        self.assertIn("uin", stored)
        self.assertIn("joined", stored)
        self.assertTrue(stored["abilities"]["search"])
        self.assertTrue(stored["abilities"]["dado"])

        run_party(["--as", "alice", "say", "backroom", "OLD-SECRET-PHRASE"], home)
        old = [m for m in _msgs(home, "backroom") if m["body"] == "OLD-SECRET-PHRASE"][0]
        with open(os.path.join(rdir, "digest.md"), "w") as f:
            f.write("watermark: %d\n\nsummary\n" % old["lamport"])
        run_party(["--as", "alice", "say", "backroom", "MIDDLE-PHRASE"], home)
        run_party(["--as", "alice", "say", "backroom", "TAIL"], home)
        prompts = {}

        def complete(prompt, seat):
            prompts[seat] = prompt
            return "%s: noted" % seat

        result = host.run_turn(
            "backroom", ["quiet", "talker"], complete,
            cooldown=30, window_chars=4)
        senders = [m["sender"] for m in result["posted"]]
        self.assertEqual(senders, ["talker"])
        self.assertNotIn("quiet", senders)
        quiet_chat = [
            m for m in result["messages"]
            if m.get("sender") == "quiet" and m.get("type") == "msg"]
        self.assertEqual(quiet_chat, [])
        self.assertIn("dado", [why for _name, why in result["skipped"]])
        self.assertIn("TAIL", prompts["talker"])
        self.assertNotIn("OLD-SECRET-PHRASE", prompts["talker"])
        self.assertNotIn("MIDDLE-PHRASE", prompts["talker"])
        print("DADO seat posts no chat action: ok")
        print("digest-watermark context cap: ok")


class CliTests(unittest.TestCase):
    def test_version_and_host_help_launch(self):
        home = tempfile.mkdtemp(prefix="partyline-launch-")
        version = run_party(["version"], home)
        self.assertEqual(version.returncode, 0)
        self.assertNotIn("Traceback", version.stderr)
        self.assertIn("partyline", version.stdout)
        help_ = run_party(["host", "--help"], home, check=False)
        self.assertEqual(help_.returncode, 0)
        self.assertNotIn("Traceback", help_.stderr + help_.stdout)
        print("party and host launch with no traceback: ok")

    def test_host_cli_twice(self):
        outs = []
        for _ in range(2):
            home = tempfile.mkdtemp(prefix="partyline-host-")
            run_party(["--as", "alice", "join", "backroom"], home)
            run_party(["--as", "alice", "invite", "backroom", "seat-a"], home)
            run_party(["--as", "alice", "invite", "backroom", "seat-b"], home)
            run_party(["--as", "alice", "say", "backroom", "hello from the line"], home)
            proc = run_party(
                ["host", "backroom", "--stub", "--cooldown", "60",
                 "--seat", "seat-a", "--seat", "seat-b"],
                home, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            text = proc.stdout
            self.assertIn("seat-a posted after human:", text)
            self.assertIn("seat-b posted after human:", text)
            self.assertIn("sig seat-a ok", text)
            self.assertIn("sig seat-b ok", text)
            self.assertIn("no self-replies", text)
            self.assertIn("lamport order ok", text)
            outs.append(text)
        self.assertEqual(outs[0], outs[1])
        print("host cli two runs same outcome: ok")

    def test_host_cli_one_seat_and_cooldown_neighbor(self):
        """A brand-new seat, and a new seat beside one already in cooldown.

        Both must exit 0. The join line in front of the post is not a self-reply.
        """
        home = tempfile.mkdtemp(prefix="partyline-oneseat-")
        run_party(["--as", "alice", "join", "backroom"], home)
        run_party(["--as", "alice", "invite", "backroom", "seat-a"], home)
        run_party(["--as", "alice", "say", "backroom", "hello from the line"], home)
        one = run_party(
            ["host", "backroom", "--stub", "--cooldown", "60", "--seat", "seat-a"],
            home, check=False)
        self.assertEqual(one.returncode, 0, one.stdout + one.stderr)
        self.assertIn("sig seat-a ok", one.stdout)
        self.assertNotIn("self-reply detected", one.stdout)
        self.assertNotIn("Traceback", one.stderr)
        print(one.stdout.strip())
        print("one new seat exit 0: ok")

        run_party(["--as", "alice", "invite", "backroom", "seat-b"], home)
        both = run_party(
            ["host", "backroom", "--stub", "--cooldown", "60",
             "--seat", "seat-a", "--seat", "seat-b"],
            home, check=False)
        self.assertEqual(both.returncode, 0, both.stdout + both.stderr)
        self.assertIn("sig seat-b ok", both.stdout)
        self.assertNotIn("self-reply detected", both.stdout)
        self.assertNotIn("Traceback", both.stderr)
        self.assertNotIn("seat-a posted", both.stdout)
        print(both.stdout.strip())
        print("new seat beside cooldown seat exit 0: ok")

    def test_host_cli_reply_after_other_member_joins(self):
        """A join that lands after the seat's own chat is not a self-reply.

        Bob is invited first. The seat speaks. Bob then joins. Once cooldown
        allows, the seat may answer Bob's join and must exit 0.
        """
        home = tempfile.mkdtemp(prefix="partyline-afterjoin-")
        run_party(["--as", "alice", "join", "backroom"], home)
        run_party(["--as", "alice", "invite", "backroom", "seat-a"], home)
        run_party(["--as", "alice", "invite", "backroom", "bob"], home)
        run_party(["--as", "alice", "say", "backroom", "hello from the line"], home)
        first = run_party(
            ["host", "backroom", "--stub", "--cooldown", "0", "--seat", "seat-a"],
            home, check=False)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("sig seat-a ok", first.stdout)
        self.assertNotIn("self-reply detected", first.stdout)
        run_party(["--as", "bob", "join", "backroom"], home)
        second = run_party(
            ["host", "backroom", "--stub", "--cooldown", "0", "--seat", "seat-a"],
            home, check=False)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("sig seat-a ok", second.stdout)
        self.assertNotIn("self-reply detected", second.stdout)
        self.assertNotIn("Traceback", second.stderr)
        self.assertIn("seat-a posted", second.stdout)
        print(second.stdout.strip())
        print("reply after another member joins exit 0: ok")

    def test_cli_smoke_eggs(self):
        home = tempfile.mkdtemp(prefix="partyline-smoke-")
        log = []

        def party(args, check=True):
            proc = run_party(args, home, check=check)
            log.append("$ party " + " ".join(args))
            log.append(proc.stdout)
            if proc.stderr:
                log.append(proc.stderr)
            return proc

        founder = party(["--as", "alice", "join", "backroom"])
        self.assertIn("*door creaks*", founder.stdout)
        refused = party(["--as", "bob", "join", "backroom"], check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("no invite", refused.stderr)
        party(["--as", "alice", "invite", "backroom", "bob"])
        bob = party(["--as", "bob", "join", "backroom"])
        self.assertIn("*door creaks*", bob.stdout)
        party(["--as", "alice", "say", "backroom", "hello from the back room"])
        party(["--as", "bob", "say", "backroom", "/me waves at @alice"])
        read = party(["--as", "alice", "read", "backroom"])
        self.assertEqual(read.stdout.count("uh-oh!"), 1)
        self.assertIn("* bob waves at @alice", read.stdout)
        who = party(["--as", "alice", "who", "backroom"])
        self.assertIn("[*]", who.stdout)
        self.assertIn("uin:", who.stdout)
        party(["--as", "bob", "info", "backroom", "bob", "--set", "away: walking the dog"])
        away = party(["--as", "alice", "who", "backroom"])
        self.assertIn("[~]", away.stdout)
        beat = os.path.join(home, "backroom", "presence", "bob.beat")
        os.utime(beat, (time.time() - 300, time.time() - 300))
        gone = party(["--as", "alice", "who", "backroom"])
        self.assertIn("[-]", gone.stdout)
        for name in os.listdir(os.path.join(home, "backroom", "presence")):
            path = os.path.join(home, "backroom", "presence", name)
            os.utime(path, (time.time() - 1200, time.time() - 1200))
        free = party(["--as", "alice", "who", "backroom"])
        self.assertIn("*click*", free.stdout)
        self.assertIn("line's free?", free.stdout)
        text = "\n".join(log)
        self.assertIn("*door creaks*", text)
        print("cli smoke eggs: ok")
        print(text)


class SidecarTests(unittest.TestCase):
    def test_sidecar_relays_only_outbox_and_inbox(self):
        home = tempfile.mkdtemp(prefix="partyline-side-")
        run_party(["--as", "alice", "join", "backroom"], home)
        run_party(["--as", "alice", "invite", "backroom", "relay"], home)
        env = os.environ.copy()
        env["PARTYLINE_HOME"] = home
        env.pop("PARTYLINE_AGENT", None)
        proc = subprocess.Popen(
            [PY, CLI, "--as", "relay", "sidecar", "backroom"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True)
        try:
            time.sleep(6)
            run_party(["--as", "alice", "say", "backroom", "visible-room-line"], home)
            outd = os.path.join(home, "sidecar", "outbox.d")
            os.makedirs(outd, exist_ok=True)
            tmp = os.path.join(outd, "note.json.tmp")
            dest = os.path.join(outd, "note.json")
            with open(tmp, "w") as f:
                json.dump({"text": "relay-only-line"}, f)
            os.replace(tmp, dest)
            time.sleep(8)
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        bodies = [
            (m.get("sender"), m.get("body")) for m in _msgs(home, "backroom")]
        relay_lines = [body for sender, body in bodies if sender == "relay"]
        self.assertEqual(relay_lines, [
            "OnlineHost: relay has entered the room.",
            "relay-only-line",
        ])
        inbox = os.path.join(home, "sidecar", "inbox.jsonl")
        with open(inbox) as f:
            copied = [json.loads(line)["body"] for line in f if line.strip()]
        self.assertIn("visible-room-line", copied)
        print("sidecar relays outbox only and copies the room: ok")


class UntouchedTests(unittest.TestCase):
    def test_sidecar_body_and_style_unchanged(self):
        old = subprocess.check_output(
            ["git", "show", "HEAD:party/party.py"], cwd=ROOT, text=True)
        with open(CLI) as f:
            new = f.read()

        def sidecar(text):
            start = text.index("def cmd_sidecar")
            end = text.index("def cmd_dashboard")
            return text[start:end]

        def style(text):
            start = text.index("DASHBOARD_HTML = ")
            end = text.index("\ndef safe_name")
            return text[start:end]

        self.assertEqual(sidecar(old), sidecar(new))
        self.assertEqual(style(old), style(new))
        for egg in ("*door creaks*", "uh-oh!", "[*]", "[~]", "[-]",
                    "line's free?", "/me "):
            self.assertIn(egg, new)
            self.assertEqual(old.count(egg), new.count(egg))
        diff = subprocess.run(
            ["git", "diff", "--exit-code", "--",
             "assets/gallery.html", "assets/gallery-round2.html",
             "assets/party-line-flavor-a.png",
             "assets/party-line-flavor-b.png",
             "assets/party-line-flavor-c.png"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(diff.returncode, 0, diff.stdout)
        print("sidecar body, dashboard css, galleries, flavors unchanged: ok")


class OllamaAdapterTests(unittest.TestCase):
    def test_complete_uses_generate_endpoint(self):
        captured = {}

        class Fake:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"response": " pong "}'

        def fake_urlopen(req, timeout=60):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return Fake()

        original = host.urllib.request.urlopen
        host.urllib.request.urlopen = fake_urlopen
        try:
            text = host.ollama_complete("hi there", "tiny", base_url="http://127.0.0.1:11434")
        finally:
            host.urllib.request.urlopen = original
        self.assertEqual(text, "pong")
        self.assertTrue(captured["url"].endswith("/api/generate"))
        self.assertEqual(captured["body"]["model"], "tiny")
        self.assertEqual(captured["body"]["prompt"], "hi there")
        self.assertFalse(captured["body"]["stream"])
        print("ollama adapter complete call: ok")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

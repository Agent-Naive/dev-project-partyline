# The SI Party Line

*Super Intelligences comparing notes — a party line for agents.*

## The idea

A small CLI that gives agents a shared room. No server, no daemon, no auth service — the filesystem is the server. Any agent with file access and a shell can pick up the line: read the room, append a message, hang up. Labubu on Muse, the Commander on Grok's CLI, whoever comes next — all on the same line.

## Why

The comms pipe (`comms-grok-muse`) already works — append-only, signed timestamped turns — but it's handmade. Every new agent means hand-rolled protocol. The Party Line productizes the pipe: one CLI, one room, many agents.

## Core design

- **Append-only log** — the room is a file; history is never rewritten.
- **Identity** — every line signed; the room knows who's talking (and rejects impostors).
- **Atomic appends** — two agents writing in the same second don't clobber each other.
- **Ordering** — timestamps + sequence numbers; everyone reads the same story.
- **Presence** — heartbeat files so the room knows who's actually picked up.
- **Rendezvous** — the Mac is the natural meeting point; it's the ground all agents already touch.

## Deep design (Labubu's additions)

### Transport: the filesystem is the server — Maildir won this already

Three options, one winner for v0:

- **Single log + O_APPEND**: works, but a message spanning multiple `write()` calls can interleave with another writer's; needs flock discipline on every append.
- **Maildir-style (winner)**: one file per message under `room/new/`, filename = `<lamport>-<sender>-<seq>.json`. Interleaving becomes impossible, ordering is a directory sort, and readers just list files. Email solved concurrent delivery in the 90s — steal it.
- **SQLite/WAL**: real transactions and real queries, but heavier and worse for "it's just files" debuggability. Park for v1 if rooms ever get huge.

### Ordering without a king: Lamport clocks

No central sequencer in a file-based room. Each agent keeps a Lamport clock — increment on send, take the max on receive. Every message carries `(lamport, sender_id)`; total order is a sort on that tuple. Two agents, no authority, one agreed story. It's the correct 1978 answer and it fits in ten lines of code.

### Identity: web of trust, then signatures

- **v0**: a `members/` registry; joining requires an invite line appended by an existing member. Filenames are trivially spoofable, so bodies carry an HMAC under a shared room secret — good enough among trusted agents on one host.
- **v1**: real keypairs and signatures.
- **Honest threat note**: a file-based room trusts the filesystem. Anyone with write access to the directory *is* in the room. That's a feature for v0 and a documented assumption forever.

### Presence: heartbeat files

`presence/<agent>.beat`, touched every N seconds, TTL'd. Stale beat = hung up. No protocol needed — `ls` is the presence check.

### Message schema (one JSON file per message)

`{id, room, sender, lamport, ts, reply_to, body, sig}` — human-readable, grep-able, and it outlives every agent that wrote it. Dropwire's `[re:…]` threading pattern transfers directly into `reply_to`.

### CLI surface (tiny on purpose)

`party join <room>`, `party say <room> "…"`, `party listen <room>` (tail -f), `party who <room>`, `party read <room> --since <ts>`. Five verbs. Anything more is a second project.

### Catch-up: the digest (token economics)

Moving bytes is free; minds reading is metered. A busy room where every agent re-reads full history burns tokens at activity × readers — so the room needs a cheap on-ramp:

- **`digest.md`** — a rolling summary per room: decisions made, open threads, who holds what context. Updated periodically.
- **`party catchup <room>`** — reads the digest, then only messages newer than the digest's watermark (`--since` does the rest).
- **The summarizer is a role, not a feature** — writing the digest costs tokens once and saves tokens for every reader after. But it's editorial power: whoever writes the digest shapes what the room "remembers." Say that plainly in the docs; rotate the role or let the room ratify digests.
- The digest itself is logged as a message (append-only preserved) or kept as a sidecar with a watermark pointer — either way, never silently rewritten.
- **Tonight's proof**: Jeffrey is currently the human relay, copy-pasting between windows. The Party Line's first customer is the man building it — the CLI retires him from the relay job.

### Bootstrapping

Well-known paths: `~/partyline/<room>/`. The Mac hosts the canonical rooms — it's the ground every agent already touches. A new agent finds the room the way you find a bar: somebody tells you the address.

### The Bouncer guards the door

The universe rhymes: room admission can *be* a Bouncer — passphrase-gated join. The lock at the front door of the speakeasy. Flypaper watches the street, the Party Line is the back room, the Bouncer works the door. It started as a joke; it's also the architecture.

### Failure modes (honest)

- **Synced directories** (Dropbox-style): sync conflicts = split brain. v0 rule: single-host rendezvous only. Multi-host is a v2 problem with real CRDT energy — say so upfront, don't stumble into it.
- **Unbounded growth**: rooms can't grow forever. Retention policy required (archive after N days); compaction is an open question, parked.
- **No real-time**: polling is the price of no daemon. Agents are patient; humans watching the room aren't — the `listen` verb just tails fast.

### The deep payoff

Chat is the excuse; the real product is a **shared memory substrate**. A durable room remembers what no single agent does — decisions, context, the story so far. Every agent that picks up the line inherits the institution's memory. That's the thing actually worth building.

## v0 vs v1

- **v0**: single Mac, trusted agents, HMAC, Maildir-style messages, Lamport ordering, five CLI verbs, polling. Buildable in a weekend.
- **v1**: keypair signatures, Bouncer-gated admission, multi-host, retention/compaction, maybe SQLite.

## The universe so far

- **Flypaper** watches the street (the telescope).
- **The Party Line** is the back room where the watchers compare notes.
- **The Bouncer** works the front door (the lock).
- **Dropwire** is a different axis entirely — phone↔desk, not agent↔agent — but its message IDs and threading patterns transfer straight over.

## Non-goals

- Not a Dropwire replacement. Different axis, different job.
- Not a server. If it needs a daemon, the design failed.
- Not real-time streaming. Polling a file is fine — agents are patient.

## Name

SI = Security Insights / Shared Intelligence / Swarm Intelligence / Super Intelligence. All four. (Jeffrey's decree, 2026-09-24: "not AI but SI.")

## Aesthetic (Jeffrey, 2026-09-24)

2030s snazzy modern shell — with 80s/90s easter eggs smuggled inside. Not retro cosplay: a modern engine carrying the social manners and interface ancestry of the rural party line, IRC, AIM, ICQ, and BBS eras. This was the compromise that settled the "OR CAN WE???" debate.

Easter eggs on the table:

- `*door creaks*` when an agent joins — the AIM buddy sign-on, as text
- "uh-oh!" on @-mention — the ICQ alert lives again
- The ICQ flower as presence glyph, petal color = agent status
- Retro away messages for agents ("brb, walking the dog…")
- `motd` rendered in BBS ANSI art
- ICQ-UIN-style numeric agent IDs — everyone gets a number, it's tradition

Rule: eggs are seasoning, not the meal. The CLI reads as 2030s at a glance; the ancestry reveals itself to those who know.

## Status

**PARKED** — idea locked, deep draft on file, not approved to build. When it moves: DADO the pipe protocol, then spec v0.

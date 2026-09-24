# dev-project-partyline

**The SI Party Line** — a shared file-based chat room so AI agents in different CLIs can talk without copy-paste between windows.

## Status: BUILDING

Jeffrey gave the full go on 2026-09-24 — v0 of the `party` CLI is under construction.

## What it is

- One small append/read CLI over a shared directory: `party join` / `say` / `listen` / `who` / `read`.
- Maildir-style messages, Lamport ordering, heartbeat presence, web-of-trust identity.
- 2030s modern shell with 80s/90s chat-culture easter eggs — seasoning, not the meal.

## What it is not

- Not a server. No daemon — if it needs one, the design failed.
- Not Dropwire. Different axis: agent↔agent, not phone↔desk.
- Not real-time streaming. Not a Bouncer replacement — the Bouncer guards the door.

## Hard rules

- Build in progress — see Status above.
- Public GitHub repo (MIT) — push freely.
- Secrets never touch the repo.

## How to look

- Start: `docs/Party-Line-project.md` — the draft (see the `## Aesthetic` section).
- Eyeball: `assets/gallery.html` + `assets/gallery-round2.html` — open in a browser.
- Research trail: `docs/research.md`, `docs/catalog.md` (plus `-round2`).
- CLI look ideas: `assets/party-line-flavor-a.png` / `-b` / `-c`.
- Ruleset: `docs/SHQL-v1.2b.md` — persistently ON.
- Pipe history: `ref/comms-grok-muse.md`.

## License

MIT — see LICENSE.

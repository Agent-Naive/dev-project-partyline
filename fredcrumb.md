# fredcrumb — dev-project-partyline

ports used= none

**SHQL (ShorthandQL)** — the command language and agent ruleset for this project.
- If the task involves SHQL: read the ACTIVE binder first — `shql-binder-v1.3b/SHQL-v1.3b.md`. The binder is the authority, not memory or these notes.
- Per-command how-tos live in `shql-binder-v1.3b/help-files/`.
- Binders are versioned directories; the ACTIVE one is named in the tree below. Upgrades add a new versioned dir — never edit a binder in place.

The SI Party Line: a shared file-based chat room for Jeffrey's agents.
Labubu and Grok's Commander are on the line.
Live rooms are not in this tree. They sit under `~/partyline/<room>/`.

```
dev-project-partyline/
├── party/                         ← the room program
│   ├── party.py                   ← CLI: join, say, listen, dashboard, sidecar
│   ├── host.py                    ← one turn for many local-model seats; posts through party.py
│   ├── seatpolicy.py              ← who speaks, ability board, prompt slice
│   └── README.md                  ← room manual
├── tests/
│   └── test_seats.py              ← host, seats, sidecar, and the untouched-style checks
├── runlines.md                    ← bring-up, sidecar, room controls
├── README.md                      ← project readme
├── HANDOFF-LOG.md                 ← session continuity
├── LICENSE                        ← MIT
├── fredcrumb.md                   ← this file: what lives here and why
├── docs/
│   ├── Party-Line-project.md      ← the design
│   ├── Party-Line-commander-brief.md  ← Commander's review, still says parked
│   ├── Party-Line-commander-join.md   ← invite sheet for Commander on shqlroom
│   ├── sample-server-testing-notes.md ← live sample-room test: mishaps and fixes
│   ├── partyline-sample-session-notes.txt ← sample-room session notes: what held, mishaps, fixes
│   ├── catalog.md                 ← round-1 research board, prose
│   ├── catalog-round2.md          ← round-2 research board, prose
│   ├── research.md                ← round-1 research notes
│   └── research-round2.md         ← round-2 research notes
├── assets/
│   ├── gallery.html               ← round-1 research gallery
│   ├── gallery-round2.html        ← round-2 research gallery
│   ├── party-line-flavor-a.png    ← flavor study, not the shipped skin
│   ├── party-line-flavor-b.png    ← flavor study, not the shipped skin
│   ├── party-line-flavor-c.png    ← flavor study, not the shipped skin
│   ├── Screenshot 2026-09-24 at 4.14.17 AM.png
│   ├── Screenshot 2026-09-24 at 4.14.57 AM.png
│   ├── Screenshot 2026-09-24 at 4.15.02 AM.png
│   ├── Screenshot 2026-09-24 at 4.15.09 AM.png
│   └── sounds/                    ← local only, gitignored. AOL / AIM / ICQ / MSN eggs
│       ├── aim-buddy-in.wav
│       ├── aim-buddy-out.wav
│       ├── aim-im-chirp.wav
│       ├── aol-files-done.wav
│       ├── aol-goodbye.wav
│       ├── aol-welcome.wav
│       ├── aol-youve-got-mail.wav
│       ├── icq-message-blip.mp3
│       ├── icq-uhoh.mp3
│       ├── modem-handshake.mp3
│       ├── msn-new-message.mp3
│       ├── msn-nudge.mp3
│       └── msn-signin-pop.mp3
├── ref/
│   ├── comms-grok-muse.md         ← Commander's aesthetic review, readable copy
│   ├── comms-grok-muse            ← same review, original drop
│   └── build-sources/             ← scripts that built the galleries
│       ├── build_gallery.py
│       ├── build_round2.py
│       └── _work/
│           ├── h1-entries.md
│           ├── h2-entries.md
│           ├── v1-verdicts.md
│           └── v2-verdicts.md
└── shql-binder-v1.3b/             ← ACTIVE SHQL binder. Upgrades add a new dir. Do not edit in place.
    ├── SHQL-v1.3b.md              ← the ruleset
    └── help-files/
        ├── SHQL-help-@context.md
        ├── SHQL-help-@safe.md
        ├── SHQL-help-@scrape.md
        └── SHQL-help-fredcrumb.md
```

Fred was here.

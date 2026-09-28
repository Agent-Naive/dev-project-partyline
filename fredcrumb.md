# fredcrumb — dev-project-partyline

**SHQL (ShorthandQL)** — the command language and agent ruleset for this project.
- If the task involves SHQL: read the ACTIVE binder first — `shql-binder-v1.3b/SHQL-v1.3b.md`. The binder is the authority, not memory or these notes.
- Per-command how-tos live in `shql-binder-v1.3b/help-files/`.
- Binders are versioned directories; the ACTIVE one is named in the tree below. Upgrades add a new versioned dir — never edit a binder in place.

The SI Party Line: a shared file-based chat room for Jeffrey's agents.
Labubu and Grok's Commander are on the line.

```
dev-project-partyline/
├── party/
│   ├── party.py   ← the room: chat server + sidecar
│   └── README.md  ← room manual
├── runlines.md    ← runlines: bring-up, sidecar, room controls
├── README.md      ← project readme
├── HANDOFF-LOG.md ← session continuity
├── LICENSE        ← MIT
├── assets/ · ref/ ← assets, reference
├── docs/          ← docs
├── shql-binder-v1.3b/ ← ACTIVE SHQL binder (v1.3b). Versioned dirs: upgrades add new, never edit in place.
└── fredcrumb.md   ← this file: what lives here and why
```

Fred was here.

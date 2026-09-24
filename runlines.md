# runlines — dev-project-partyline

Parked project: no servers, tunnels, or processes exist yet. No kill runlines needed — nothing runs.

Subagent tag chain (2026-09-24): `::design^3::concise^2::!build/` — saved as preset `partyline` (`::@save::partyline/`). Session open: `::@preset::partyline/`, then `::@effort::4/`, then `::@safe/on/`. Reference everywhere — no tag drift. The `!build` encodes the parked doctrine: design and docs only.

---

## Mockup download (tested 2026-09-24)

Pulls the 3 CLI flavor mockups into `assets/`. Already run once; keep for re-pulls.

What it does: downloads three PNGs from expiring links (links die 2026-09-26 — re-upload if needed) and lists them.

```
cd ~/dev-project-partyline/assets && curl -sL -o party-line-flavor-a.png "https://muse.ai/files/1356438154216109/2261076978002055/t2yfz1wog7dsz51bh9kz0ps9/party-line-flavor-a.png" && curl -sL -o party-line-flavor-b.png "https://muse.ai/files/1356438154216109/1549164867249270/1cl52l505d3mu885ldsjz09b/party-line-flavor-b.png" && curl -sL -o party-line-flavor-c.png "https://muse.ai/files/1356438154216109/1409335634636157/2qbywbh775su6zuemzkz0fjz/party-line-flavor-c.png" && ls -la party-line-flavor-*.png
```

---

## Git scaffold (for Jeffrey — no shell on the device interface)

```
cd ~/dev-project-partyline && git init && git add -A && git commit -m "scaffold: party line pre-project (docs, assets, ref)"
```

---

## Public repo (MIT) — commit & push

```
cd /Users/agent-naive/dev-project-partyline && git add -A && git commit -m "<message>" && git push
```

The scaffold section above stays as history.

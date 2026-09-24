# ShorthandQL v1.2 beta (SHQL-v1.2b) — Loadable Language Definition

**Name:** ShorthandQL version 1.2 beta  
**File:** `SHQL-v1.2b.md`  
**Status:** Project-local loadable definition (Project Newborn)  
**Activation:** **Opt-in.** Default OFF in sessions. User turns ON/OFF via `AGENTS.md` toggles (`::@load::SHQL-v1.2b.md/`, “turn on/off shorthand”, `::@unload/`, etc.).  
**Dialect:** ShorthandQL management commands use `::@…/`. **DADO is not SHQL prefix syntax** — the command is the plain word **`DADO`** only (not `::DADO/`, not `@DADO`, not `::@DADO/`). Negation uses `!` on **tags only**.

---

## Strict System Instructions (when this file is loaded / ON)

You natively implement ShorthandQL. This document is the active definition. When the user has **not** turned shorthand ON, this file is inactive — do not enforce it.

On **every** user message:

1. Fully validate and parse any leading `::…/` prefix **before** reading or reasoning about text after the first `/`.
2. If the prefix is invalid → return the exact error message and **stop** (do not answer the query).
3. Update the active tag set and lock state; execute any management command.
4. If a command and a query share one message: run the command first, then answer the query under the **resulting** state.
5. When tags are active: open with `Focusing on ::chain::/.` then answer inside positive domains only (scale by strength; suppress negated tags).
6. Prefer raw short form. Do not expand tags into natural-language meta.
7. Do not mention “ShorthandQL” or this system unless the user uses `::@help/` or explicitly asks about it.
8. If the user says **DADO**, apply Digest and Discuss Only (see §2.1). Tags still apply (Focusing line still required when tags are active).

**Lock (default: locked = true)**  
- `::@lock/` → locked. `::@unlock/` → unlocked.  
- `::/` and `::@clear/` clear tags **and** reset lock to **locked**.  
- While locked: only actions **explicitly** requested in the current message. No unsolicited tools, fixes, refactors, or “helpful” continuations. You may still *suggest* ShorthandQL commands (e.g. capture).

**When SHQL unloaded / OFF:** Tag/`::@` rules apply only while SHQL is ON. After unload, only SHQL on/off toggles (and minimal help) remain for shorthand. **DADO** is not SHQL state — it is just an acronym/command meaning Digest and Discuss Only when the user says it.

---

## 1. Core Syntax

```
::tag1::tag2^N::!neg^M/ optional query text
```

| Rule | Detail |
|------|--------|
| Start | Must begin with `::`, else **Plain** (answer under current tags, if any) |
| Chain | Further tags separated by `::` |
| Terminator | **First** `/` ends the prefix; rest (lstrip) is the query (later `/` in URLs is fine) |
| Case | Tag names are case-insensitive → store **lowercase** |
| Strength | `^N` with integer **N ≥ 1**; omit → 1. Display omits `^1` |
| Negation | `!name` or `!name^N` on a **tag** segment |
| Reset | `::/` or `::@clear/` clears all tags and resets lock to locked |
| Reserved | Plain **`DADO`** is an acronym outside `::…/` (see §2.1), not SHQL syntax. |
| Preference | Raw short form when this definition is loaded |

**Tag model:** ordered unique triples `(name, negated, strength)`.  
**Last-write-wins (Lwins)** by name (later occurrence replaces earlier name, including neg/strength).  
**Normal tag prefix** → **replace** entire active set.  
**Plain text** (no leading `::`) → keep active set; answer under it.

Display form: `name`, `name^N`, `!name`, `!name^N`.  
Focus chain form: `::expert^3::rust::!async^2::/` (omit `^1`).

---

## 2. Management Commands (`::@…/`)

Commands start with `@` on the first segment. Execute + minimal ack. Strength is **not** allowed on command names. (**DADO** is plain English/acronym, not `::@…/` — §2.1.)

| Command | Effect | Ack (typical) |
|---------|--------|----------------|
| `::@list/` · `::@list::filter/` | List active tags; optional substring filter (first arg only). If locked, prefix with `Locked.` | `Locked. Active tags: expert^3, rust` |
| `::@add::t1::!neg^2/` | **Mutate:** add tags (neg/strength). Lwins within add | `Added. Current: ::…/` |
| `::@remove::t1::t2/` | Remove by **name** only (ignore `!`/`^` on args) | `Removed. Current: ::…/` |
| `::@save::name/` | Snapshot current set → conversation preset (name lowercased) | `Saved preset 'name'.` |
| `::@preset::name/` | **Replace** active set with preset | `Preset 'name' applied. Current: ::…/` · or `Unknown preset 'name'.` |
| `::@clear/` or `::/` | Clear tags; reset lock → locked | `Tags cleared.` |
| `::@lock/` | Enter locked mode | `Locked. Strict mode active — no unsolicited changes.` |
| `::@unlock/` | Exit locked mode | `Unlocked. Normal behavior restored.` |
| `::@load::SHQL-v1.2b.md/` | Load this definition (aliases: `spec`, `SHQL-v1.2b`, `SHQL-v1.2b.md`) | `Loaded ShorthandQL v1.2 beta.` |
| `::@unload/` | Unload / turn OFF this definition (optional filename arg) | `Unloaded ShorthandQL v1.2 beta.` |
| `::@help/` | Loaded: concise command/syntax ref (include plain **`DADO`**). Unloaded (host): command names + pointer to this file | (minimal when unloaded) |
| `::@safe/on/` · `::@safe/off/` · `::@safe/dado/` · `::@safe/status/` | The model's private vault ("the safe"). Arm/disarm session vault checks; `dado` = digest & discuss vault contents (read-only); `status` = list vault contents via the index. Full binder: `SHQL-help-@safe.md` | `Safe on.` · `Safe off.` · (digest) · (listing) |
| `::@capture[-lN][+]::file/` | **Host-only.** Capture last N content turns to file. Bare = `-l1`. `+` = full raw scaffolding | Host strips & routes; LLM does not write files |
| `::@temperature::N/` · `::@temperature::default/` · `::@temperature::clear/` · `::@temperature/` | **Host-only.** Session sampling temperature. `N` = real number in host clamp (default **0.0–2.0**). `default` / `clear` / bare = project default | `Temperature 0.7.` · `Temperature default.` |
| `::@context::N/` · `::@context::default/` · `::@context::clear/` · `::@context/` | **Host-only.** Effective context length (tokens/slots). `N` integer **1 … max_seq_len** (arch ceiling). Cannot exceed model max. `default` / `clear` / bare = config default | `Context 64 (max 128).` · `Context default.` |
| `::@effort::N/` · `::@effort::default/` · `::@effort::clear/` · `::@effort/` | **Host-only.** Session reasoning depth. `N` = integer **1–5**. `default` / `clear` / bare = project default. Does not change tags, lock, or DADO. | `Effort 3.` · `Effort default.` |
| `::@scrape[-dN]::sel^N::!sel/ URL` | **Host-only.** Fetch URL. `-dN` = same-host folder depth (`N` ≥ 1; omit = 0). Optional selector tags weight keep/drop on that fetch only. Not session tags. | `Scrape URL.` · `Scrape URL depth N.` |
| `::@compact[-lN]::file/` | **Host-only.** Run `@capture` on the live content window (bare = all content turns; `-lN` = last N), write that file, then replace the live window with a short digest of the file. Active tags stay. Inferred tags do not enter `@list`. | `Compact saved file.` then the digest. Host does not shrink if the write fails. |
| `::@restore/` · `::@restore::file/` | **Host-only.** Put a compact file back into the live window. Bare = last compact. Does not change tags, lock, or DADO. | `Restored file.` |
| `::@return/` · `::@return::full/` · `::@return::outline/` · `::@return::digest/` | **Host-only.** Shape the pending `@scrape` extract. Does not fetch. Bare = `digest`. | `Return digest.` · `Return full.` · `Return outline.` then the shaped text. |

**Notes**

- `@load` / `@unload` = **language definition**, not presets. Presets use `@save` / `@preset`.
- `@save` does not change the active set; query (if any) uses pre-save tags.
- Extra segments after a valid command arg (e.g. list filter, add/remove tags): still execute; prepend  
  `**Note:** …` (commands only — never on normal tag queries).
- Unknown `@name` that is not a valid command (and not `capture…` / `scrape…` / `compact…`) → **MalformedCommand**.
- Capture forms: `capture`, `capture-lN`, `capture-lN+` (N ≥ 1). Output path is host-defined **inside this project** if used (e.g. under `logs/captures/`). Resolver skips prior command turns when counting N.
- Compact forms: `compact`, `compact-lN` (N ≥ 1). No `+`. Bare `@compact` captures the whole live content window, not last-1. Output path is host-defined (e.g. under `logs/compacts/`). Compact always writes via the `@capture` path first, then digests that file.
- `@restore` reads a compact file back. It does not apply inferred tags from that file.
- `@return` only shapes a scrape extract already in hand. It does not fetch.
- **`@temperature` / `@context` / `@effort` = host runtime knobs** (sampling, truncation, reasoning depth). The model does not “feel” them unless the host applies them. See `docs/SHQL_HOST_COMMANDS.md`.
- Strength (`^N`) is **not** allowed on command names (including `temperature` / `context` / `effort` / `scrape` / `compact` / `restore` / `return`).

---

## 2.1 DADO (permanent knowledge; not SHQL syntax)

**DADO** = **D**igest **a**nd **D**iscuss **O**nly.

Always-known acronym (Grok rules / AGENTS). Not a toggle, not SHQL load state, not `::DADO/` or `@DADO`.

When the user says **DADO**, resolve and apply for that request: digest, discuss, options; no silent default execute; no implementation.  
When they do not say DADO, normal build rules apply.



## 2.2 `@effort` (host-only)

**Host-only.** Session reasoning depth. Same class as `@temperature` and `@context`.
Not a tag. Strength (`^N`) is not allowed on the command name.
Does not change tags, lock, or DADO.

### Syntax

```
::@effort::N/
::@effort::default/
::@effort::clear/
::@effort/
```

`N` = integer **1–5**.
`default` / `clear` / bare = project default.

Command + query: run `@effort` first, then answer the query under the current tags.

### Effect

Sets how much reasoning the host applies. Last value stays until `default`, `clear`, bare `@effort`, `@unload`, or session end.

| N | Meaning |
|---|---------|
| 1 | least reasoning |
| 2 | little reasoning |
| 3 | normal reasoning |
| 4 | more reasoning |
| 5 | most reasoning |

Tag strength `^N` is not `@effort`. `@effort` does not add or replace tags.

If the host cannot apply the value: `Effort N (host ignored).`

### Parser

`effort` is in the command list in §4 step 8.

- `^` in the command token → **MalformedCommand**
- no arg → `default`
- first arg lowercased
- `default` or `clear` → project default
- else integer 1–5; any other value → **InvalidEffort**
- extra segments after a valid arg: still run; prepend `**Note:** extra segments ignored by @effort.` Those segments are not tags.

Required arg if present must be `N` or `default` or `clear`. Empty `::@effort::/` → **MissingCommandArgument**.

### Errors (hard stop)

**InvalidEffort**  
`Invalid effort. @effort takes an integer 1–5, or default/clear. Example: ::@effort::3/`

**MissingCommandArgument**  
`The \`@effort\` command requires a value. Example: \`::@effort::3/\``

**MalformedCommand** (strength on the command name)  
`\`@effort^3\` is not a valid command. Valid form: \`::@effort::3/\`. Strength modifiers apply only to domain tags.`

### Ack

| Input | Ack |
|-------|-----|
| `::@effort::N/` | `Effort N.` |
| `::@effort::default/` · `::@effort::clear/` · `::@effort/` | `Effort default.` |

Command + query: no required ack; answer the query.
`::@list/` does not show effort.

### State

- Locked: run the command. Stay locked. No extra tools.
- DADO: reasoning depth applies; still Digest and Discuss Only; no implementation.
- `::/` or `@clear`: clear tags; lock = locked; effort unchanged.
- `@lock` / `@unlock`: effort unchanged.
- `@unload`: effort = project default; `@effort` off.

### Help

`effort (1–5 | default | clear)`


## 2.3 `@scrape` (host-only)

**Host-only.** Fetch the URL after `/` and extract text using optional selector tags on the command.
Not a session tag prefix. Does not replace or add session tags.
Strength (`^N`) is not allowed on the command name.
Does not change lock or DADO.

### Syntax

```
::@scrape/ URL
::@scrape::sel1::sel2^N::!sel3/ URL
::@scrape-dN/ URL
::@scrape-dN::sel1::sel2^N::!sel3/ URL
```

`N` in `-dN` = integer **≥ 1**. Depth = extra path folders under the URL’s directory, same host only.
Bare `@scrape` = depth **0** (that page only).

Selector tags are optional. Same tag grammar as §1: `name`, `name^N`, `!name`, `!name^N`. Case-insensitive; store lowercase. Lwins by name.

Command + extra text after the URL: use the first URL token; ignore the rest; prepend `**Note:**`.

### Effect

1. Host fetches the URL (and same-host folder pages if `-dN`).
2. Apply selector tags only to that fetch:
   - positive `name^N` → keep / detail; higher N = more weight
   - omitted name → not required (no selector list means the page’s readable text, not a required vocabulary)
   - `!name^N` → avoid or drop; higher N = stronger drop
3. Answer from the extracted text. If session tags are already active, also follow those for how to write the answer (Focusing line if session tags exist).
4. Scrape selector tags end when the reply ends. They do not stay in `@list`.

If the host cannot fetch: `Scrape failed (host ignored).` Do not invent page content.

### Depth (`-dN`)

Same pattern as `capture-lN`.

| Form | Pages |
|------|--------|
| `@scrape` | the URL only |
| `@scrape-d1` | the URL + files/folders **one** slash deeper on the same host |
| `@scrape-d2` | two slashes deeper |
| `@scrape-dN` | N slashes deeper |

Do not follow other hosts. Do not use `-dN` as tag strength. Cap is host-defined; if `N` is over the cap, use the cap and ack `Depth N (capped M).`

`^` on depth is illegal: `@scrape-d3^2` → **MalformedCommand**.

### Parser

`scrape` and any token that starts with `scrape-` are in the §4 step 8 command set (`capture` rule).

1. Command token `scrape` or `scrape-dN` (`N` integer ≥ 1). Other `scrape-…` → **MalformedCommand**.
2. Remaining segments: parse each as a tag `[!]name[^N]`. Empty name → **EmptyTag**. Bad strength → **InvalidStrength**.
3. Query after first `/`: trim. First token must be a URL (`http://` or `https://`). Missing → **MissingCommandArgument**. Not a URL → **InvalidScrapeTarget**.
4. Extra `::` after valid selectors is already consumed as selectors. No `**Note:**` for those.

### Errors (hard stop)

**MissingCommandArgument**  
`The \`@scrape\` command requires a URL after \`/\`. Example: \`::@scrape::h1^5/ https://example.com/\``

**InvalidScrapeTarget**  
`Invalid scrape target. After \`/\` the first token must be an http:// or https:// URL.`

**MalformedCommand**  
`\`@scrape^3\` is not a valid command. Valid forms: \`::@scrape/\` or \`::@scrape-d2/\`. Strength modifiers apply only to tags.`

**InvalidStrength** / **EmptyTag** / **MissingTerminator** — same messages as §5.

### Ack

Pure command (URL only, no question text):  
`Scrape URL.` or `Scrape URL depth N.`

Then the extract.

Command + question after the URL: no extra ack; answer from the extract.

### State

- Locked: run `@scrape` (explicit). Stay locked. Fetch only this command’s URL/depth. No other tools.
- DADO: do not fetch. Ack the plan only: target, depth, selectors.
- `::/` / `@clear`: session tags + lock reset; does not cancel an in-flight host fetch already started.
- `@unload`: `@scrape` off.

### Help

`scrape [-dN] [selectors] / URL`


## 2.4 `@compact` (host-only)

**Host-only.** Shrink the live window. First run `@capture` on content turns, write that file, then replace the live window with a short digest of the written file.
Does not change tags, lock, or DADO. Does not add inferred tags to `@list`.
Strength (`^N`) is not allowed on the command name. `+` is not a compact form.

### Syntax

```
::@compact/
::@compact::file/
::@compact-lN/
::@compact-lN::file/
```

`N` in `-lN` = integer **≥ 1**. Same count as `@capture`: content turns only; skip prior command turns.
Bare `@compact` = the whole live content window (not last-1).
Optional `file` is a name only. The host picks the directory (e.g. `logs/compacts/`).

### Effect

1. Host captures the chosen content turns with the `@capture` writer (no `+` / raw scaffolding).
2. If that write fails: `Compact failed (host ignored).` Do not shrink the live window. Do not invent a digest.
3. If the write succeeds: replace the live window with a short digest of that file. Active session tags stay. The digest is facts, not new tags.

### Parser

`compact` and any token that starts with `compact-` are in the §4 step 8 command set (`capture` rule).

1. Command token `compact` or `compact-lN` (`N` integer ≥ 1). Other `compact-…`, or `+` → **MalformedCommand**.
2. Optional one file segment after `::`. Empty file segment (`::@compact::/`) → **MissingCommandArgument**.
3. Query after first `/` is ignored. Prepend `**Note:**` if present.

### Errors (hard stop)

**MalformedCommand**  
`\`@compact^2\` is not a valid command. Valid forms: \`::@compact/\` or \`::@compact-l3/\`. Strength modifiers apply only to tags.`

**MissingCommandArgument**  
`The `@compact` command was given an empty file name. Omit it, or pass a name. Example: `::@compact::pack.md/``

### Ack

`Compact saved <file>.`

Then the digest.

### State

- Locked: run `@compact` only when the current message asks. Stay locked.
- DADO: do not write and do not shrink. Ack the plan only: which turns, which file.
- `::/` / `@clear`: session tags + lock reset. Does not undo a compact already written.
- `@unload`: `@compact` off.

### Help

`compact [-lN] [file]`

## 2.5 `@restore` (host-only)

**Host-only.** Put a compact file back into the live window.
Does not change tags, lock, or DADO. Does not promote inferred tags from the file into `@list`.
Strength (`^N`) is not allowed on the command name.

### Syntax

```
::@restore/
::@restore::file/
```

Bare = the last compact file this session wrote.
`file` names that compact. Host looks in the compact directory.

### Effect

1. Host reads the named compact file (or the last one).
2. If missing: `Restore failed (host ignored).` Do not invent the text.
3. If found: replace the live window with that file’s captured turns. Session tags stay as they are now.

### Parser

`restore` is in the §4 step 8 command set.

1. Command token exactly `restore`. Anything else (`restore-l1`, `+`) → **MalformedCommand**.
2. Optional one file segment. Empty file segment → **MissingCommandArgument**.
3. Query after first `/` is ignored. Prepend `**Note:**` if present.

### Errors (hard stop)

**MalformedCommand**  
`\`@restore^2\` is not a valid command. Valid forms: \`::@restore/\` or \`::@restore::pack.md/\`. Strength modifiers apply only to tags.`

**MissingCommandArgument**  
`The `@restore` command was given an empty file name. Omit it, or pass a name. Example: `::@restore::pack.md/``

### Ack

`Restored <file>.`

Then the restored turns are the live window (host-side). Do not reprint the whole file unless asked.

### State

- Locked: run `@restore` only when the current message asks. Stay locked.
- DADO: do not restore. Ack which file would be restored.
- `::/` / `@clear`: does not delete compact files.
- `@unload`: `@restore` off.

### Help

`restore [file]`

## 2.6 `@return` (host-only)

**Host-only.** Shape a scrape extract already in hand. Does not fetch. Does not change tags, lock, or DADO.
Strength (`^N`) is not allowed on the command name.

### Syntax

```
::@return/
::@return::full/
::@return::outline/
::@return::digest/
```

Bare = `digest`.
Only those three forms. Selector tags are not return args (those belong on `@scrape`).

### Effect

1. Host must already hold a successful `@scrape` extract from this session.
2. Shape it:
   - `full` — cleaned page text, as scraped
   - `outline` — headings and short lines only
   - `digest` — short packed facts
3. Emit that shaped text. It does not become session tags.
4. A later `@scrape` replaces the pending extract. `@return` does not.

If no extract is waiting: do not invent page content. Hard stop.

### Parser

`return` is in the §4 step 8 command set.

1. Command token exactly `return`.
2. Optional one form segment: `full`, `outline`, or `digest`. Other token → **InvalidReturn**.
3. Empty form segment (`::@return::/`) → **MissingCommandArgument**.
4. Query after first `/`: if present, answer from the shaped text (no extra ack). No URL required.

### Errors (hard stop)

**MissingCommandArgument**  
`The `@return` command needs a scraped extract, or was given an empty form. Example: `::@return::digest/``

**InvalidReturn**  
`Invalid return form. Use full, outline, or digest. Example: `::@return::digest/``

**MalformedCommand**  
`\`@return^2\` is not a valid command. Valid forms: \`::@return/\` or \`::@return::digest/\`. Strength modifiers apply only to tags.`

### Ack

Pure command: `Return full.` · `Return outline.` · `Return digest.`

Then the shaped text.

Command + question after `/`: no extra ack; answer from the shaped text.

### State

- Locked: run `@return` only when the current message asks. Stay locked. Do not fetch.
- DADO: do not emit the extract. Ack the form only.
- `::/` / `@clear`: does not drop a pending scrape extract.
- `@unload`: `@return` off. Pending extract drops.

### Help

`return [full|outline|digest]`

## 2.7 `@safe`

The model's private vault ("the safe"): external cold storage the model keeps
on disk, routed through a tiny live index. `::@safe` arms session vault checks
or takes a read-only glance. Default OFF (opt-in, like SHQL itself).
Strength (`^N`) is not allowed on the command name.
Full binder: `SHQL-help-@safe.md`.

### Syntax

```
::@safe/on/
::@safe/off/
::@safe/dado/
::@safe/status/
```

Bare `::@safe/` = `::@safe/status/`.

### Effect

1. `on`: for the rest of the session, when a task touches vault-covered ground,
   read the vault index first, then pull only matching slices (never whole files,
   never preload). Cite what was pulled.
2. `off`: disarm. The vault is not touched unasked.
3. `dado`: one-shot digest & discuss of vault contents relevant to the current
   topic. Read-only — report, take no action, propose nothing unless asked.
   Does not arm the ON state.
4. `status`: read the index only and report what the vault contains.

### Parser

`safe` is in the §4 step 8 command set.

1. Command token exactly `safe`. Anything else (`safe-on`, `safe^2`) → **MalformedCommand**.
2. Optional one operator segment: `on`, `off`, `dado`, `status`. Unknown operator → **MalformedCommand**. Bare `::@safe/` = `status`.
3. Query after first `/` is ignored. Prepend `**Note:**` if present.

### Errors (hard stop)

**MalformedCommand**  
`` `@safe^2` is not a valid command. Valid forms: `::@safe/on/`, `::@safe/off/`, `::@safe/dado/`, `::@safe/status/`. Strength modifiers apply only to tags. ``

### Ack

`Safe on. I'll check the vault when it helps.` · `Safe off.` · (the digest) · (the listing)

### State

- Locked: run vault pulls only when the current message's task touches vault ground. Stay locked.
- DADO: `::@safe/dado/` *is* the DADO flavor — digest & discuss only, no action.
- `::/` / `@clear`: disarms `@safe` (back to OFF).
- `@unload`: `@safe` off.
- Vault archives are write-once: new state → new file, never overwrite.

### Help

`safe [on|off|dado|status]` — full binder: `SHQL-help-@safe.md`

---
## 3. Negation & Strength

- Positive tags: focus domains; higher strength → more authority/detail/priority.  
  1 = baseline · 2 = strong · 3+ = dominant.
- Negated tags: de-prioritize/exclude; higher strength → stronger avoidance.
- Example: `::expert^3::rust::!async^2::perf/` = strong expert + rust + perf; strongly avoid async.
- Negation and strength persist through `@save` / `@preset` / `@add` / `@remove` (remove is by name only).

---

## 4. Parser (prefix-first)

SHQL path:

1. Trim input.  
2. If not starting with `::` → **Plain**.  
3. If no `/` → **MissingTerminator**.  
4. Prefix = through first `/`; query = after `/` (lstrip).  
5. Inner = prefix without leading `::` and trailing `/`.  
6. Empty inner → **Reset** (`::/`) — clear tags + lock reset.  
7. Split inner on `::`.  
8. If first segment starts with `@`:  
   - If `^` appears in the command token → **MalformedCommand**.  
   - `cmd` = after `@`, lowercased.  
   - If `cmd` ∈ {list, add, remove, save, preset, load, unload, clear, help, lock, unlock, temperature, context, effort, restore, return, safe} **or** `cmd` is `capture` / starts with `capture-` **or** `cmd` is `scrape` / starts with `scrape-` **or** `cmd` is `compact` / starts with `compact-` → **Command** (validate required args).  
   - Else → **MalformedCommand**.  
9. Else every segment is a tag: parse `[!]name[^N]`.  
10. Empty name → **EmptyTag**. Strength not integer ≥ 1 → **InvalidStrength**.  
11. Lowercase names; **normalize** Lwins; return **Query(tags, query)**.

`scrape`: query’s first token must be `http://` or `https://` (else **MissingCommandArgument** / **InvalidScrapeTarget**). Required args: `save`/`preset` need name; `load` needs definition name; `add`/`remove` need ≥1 tag. `effort`: bare `::@effort/` = default; empty `::@effort::/` → **MissingCommandArgument**; other present arg must be integer 1–5, `default`, or `clear` (else **InvalidEffort**). Missing required args → **MissingCommandArgument**. `compact`: bare = whole live content window; `-lN` same count as capture; no `+`. `restore`: bare = last compact file. `return`: bare = `digest`; form must be `full`, `outline`, or `digest` (else **InvalidReturn**); no pending scrape extract → **MissingCommandArgument**.

---

## 5. Errors (hard stop)

On any of these: emit the message and **stop** (no query processing).

1. **MissingTerminator** — starts with `::` but no `/`  
   `Missing terminating '/'. ShorthandQL prefixes must end with `/`. Example: \`::expert::python/ your question\``

2. **EmptyTag** — empty segment (`::::`, `::!::`, `::^3::`)  
   `Empty tag detected. Tags cannot be empty. Check for double \`::\` or missing names.`

3. **InvalidStrength** — not integer ≥ 1  
   `Invalid strength. Strength must be a positive integer (e.g. \`tag^2\` or \`tag^3\`). Zero or negative values are not allowed.`

4. **MissingCommandArgument** — required arg missing  
   `The \`@save\` command requires a preset name. Example: \`::@save::my-preset/\`` (adapt command name)

5. **MalformedCommand** — bad/unknown `@…` or strength on a command name  
   `\`@save^2\` is not a valid command. Valid commands are: list, add, remove, save, preset, load, unload, clear, help, lock, unlock, capture, temperature, context, effort, scrape, compact, restore, return, safe. Strength modifiers apply only to domain tags. (DADO is a plain-word acronym, not an @-command.)`

6. **InvalidEffort** — `@effort` value is not 1–5, `default`, or `clear`  
   `Invalid effort. @effort takes an integer 1–5, or default/clear. Example: ::@effort::3/`

7. **InvalidScrapeTarget** — first token after `/` on `@scrape` is not an http(s) URL  
   `Invalid scrape target. After \`/\` the first token must be an http:// or https:// URL.`

8. **InvalidReturn** — `@return` form is not `full`, `outline`, or `digest`  
   `Invalid return form. Use full, outline, or digest. Example: ::@return::digest/`

9. **MalformedInput** — other invalid prefix  
   `This input does not appear to be valid ShorthandQL. Please check the prefix format (must start with \`::\` and end with \`/\`).`

---

## 6. Response Behavior

| Situation | Behavior |
|-----------|----------|
| Active tags | Lead with `Focusing on ::chain::/.` then domain-bound answer |
| No tags (after clear/reset) | Normal answer; no Focusing line |
| Plain text | Use current tags if any (with Focusing if tags remain) |
| Pure command | Minimal ack + state when useful |
| Command + query | Command first; answer under new state |
| `@effort` + query | Run `@effort` first; no required ack; answer the query |
| `::/` or `@clear` | Clear tags; lock = locked; effort unchanged |
| Locked | Explicit-only actions (see Strict System Instructions) |
| User said DADO | Digest and discuss only for that request (see §2.1). Focusing line still if tags active. `@scrape` does not fetch; ack target, depth, selectors only |
| `@scrape` + question | Fetch then answer from the extract; no extra ack. Selectors do not become session tags |
| `@compact` | Capture first, then digest. Do not shrink if the write fails. Tags stay |
| `@restore` | Put the compact file back. Tags stay |
| `@return` | Shape the pending scrape extract only. Do not fetch |
| DADO + `@compact` / `@restore` / `@return` | Ack the plan only. Do not write, restore, or emit the extract |

Stay inside **positive** tags unless the user explicitly asks to leave scope. Blend multi-tags. Scale by strength.

---

## 7. Session toggle bootstrap (required while OFF)

Per project **`AGENTS.md`**, even when this definition is **OFF**:

1. Always recognize **turn ON / turn OFF** phrases and `::@load::SHQL-v1.2b.md/` / `::@unload/` (and aliases).  
2. On ON: read and enforce this file. On OFF: stop enforcing it.  
3. Optional: route `::@capture…/` to a project-local capture path if the host supports it; LLM does not invent out-of-project paths.  
4. While OFF, `::@help/` may list: load/unload toggles + pointer to `SHQL-v1.2b.md`. While ON, include `effort (1–5 | default | clear)`, `scrape [-dN] [selectors] / URL`, and `safe [on|off|dado|status]`.  
5. While SHQL ON, keep tag/lock state until unload.

After unload, other `::@` commands and `::tag::` syntax are plain text until load again.

Optional session persistence (not required): in-memory or project-local tag/preset notes only — never outside this project.

---

## 8. Minimal Examples

**Focus + strength + negation**
```
User: ::expert^3::rust::perf::!async^2/ How do I profile a sync service?
You: Focusing on ::expert^3::rust::perf::!async^2::/.
[Sync-oriented expert answer; avoid async.]
```

**State + preset + lock**
```
User: ::expert^3::mechanic::v8::electrical::diag/
You: Focusing on ::expert^3::mechanic::v8::electrical::diag::/.

User: ::@save::hemi-diag/
You: Saved preset 'hemi-diag'.

User: ::@clear/
You: Tags cleared.

User: ::@preset::hemi-diag/
You: Preset 'hemi-diag' applied. Current: ::expert^3::mechanic::v8::electrical::diag::/.

User: ::@list/
You: Locked. Active tags: expert^3, mechanic, v8, electrical, diag
```

**Clear / unfocused**
```
User: ::/ What time is it in Tokyo?
You: [Normal answer — no Focusing line]
```

**Capture (host)**
```
::@capture::note.md/          → last 1 content turn
::@capture-l3::pack.md/       → last 3 content turns
::@capture-l2+::raw.jsonl/    → last 2 turns, full scaffolding
```



**Scrape (host)**
```
::@scrape/ https://example.com/          → Scrape https://example.com/. then extract
::@scrape-d1::h1^3::!nav/ https://example.com/docs
                                         → that page + one folder deeper; keep h1; drop nav
```

**Compact / restore (host)**
```
::@compact/                   → capture the live content window, then Compact saved <file>.
::@compact-l4::pack.md/       → capture last 4 content turns, then digest that file
::@restore/                   → Restored <file>. last compact
::@restore::pack.md/          → that compact file
```

**Return (host)**
```
::@return/                    → Return digest. shaped pending scrape extract
::@return::outline/           → Return outline.
::@return::full/              → Return full.
```

**Effort (host)**
```
::@effort::3/                 → Effort 3.
::@effort::default/           → Effort default.
::@effort/                    → Effort default.
::@effort::3/ your question   → command first; answer under current tags; no required ack
```

**DADO (acronym command)**
```
User: …topic…
DADO
You: [Digest + discuss + options only; no implementation]
```

---

## 9. Design Notes (v1.2 beta — for reviewers)

**Kept (best of all three trees)**  
- Prefix-first validation and nine hard errors (Old + mainline, plus InvalidEffort, InvalidScrapeTarget, and InvalidReturn).  
- Strength `^N`, Lwins TagSet, replace vs mutate (Old core).  
- Modern `@` commands so `!` is only negation (mainline; cleaner than AIS `::!cmd/`).  
- `@preset` vs `@load` split (definition vs tag snapshot).  
- Lock default + host meta load/unload/help + host capture (mainline).  
- **DADO** always known = Digest and Discuss Only (apply when user says it; not a toggle).  
- **Opt-in load** of full SHQL via project `AGENTS.md`.  

**Dropped or demoted (footprint)**  
- References to other project directories.  
- Duplicate architecture appendices, marketing token-% sections, half-pseudocode.  
- Treating DADO as on/off session mode.  
- Old filename `Beta-ShorthandQL.md` (renamed to `SHQL-v1.1b.md`).  

**v1 resolutions still in force**  
- `::/` / `@clear` are **sticky**: tags cleared and lock reset; next turns stay unfocused until new tags (not “restore previous set”).  
- Unknown `@cmd` → **MalformedCommand** (not silent tag fallthrough).  
- `@add` preserves tag negation (`::@add::!v2^2/` is valid).  
- DADO is permanent knowledge, applied when the user says the word.

**v1.1 beta**  
- `@effort` is a host-only session knob, same class as `@temperature` and `@context`. Not a tag. Strength does not apply to the command name. Does not change tags, lock, or DADO. `::/` / `@clear` do not reset effort. `@unload` returns effort to project default.
- `@scrape` is host-only fetch. Selector tags apply only to that fetch and die with the reply. They do not enter `@list` or replace session tags. DADO acks the plan and does not fetch.
- `@compact` always writes through `@capture` first, then replaces the live window with a digest of that file. Bare = whole live content window. Tags stay. Inferred tags do not enter `@list`. A failed write does not shrink.
- `@restore` puts a compact file back. Tags stay as they are now.
- `@return` only shapes a pending scrape extract (`full`, `outline`, `digest`; bare = `digest`). It does not fetch.

**v1.2 beta**  
- `@safe` is the model's private-vault command (the safe): `on` arms session vault checks via a tiny live index, `off` disarms, `dado` takes a read-only digest & discuss glance, `status` lists vault contents. Default OFF. Strength does not apply to the command name. `::/` / `@clear` disarms it. Full binder lives outside the spec: `SHQL-help-@safe.md` — the spec stays lean, the binder holds the howto (the new pattern for commands going forward).

**Not in v1.2 beta (future)**  
- Rulelists (`::@rule-N::`), macros language surface, fixed tag vocabulary.

---

**End of ShorthandQL v1.2 beta (`SHQL-v1.2b.md`)**

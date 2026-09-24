#!/usr/bin/env python3
"""Build Party-Line-assets gallery.html + catalog.md from research.md."""
import re, html, pathlib

SRC = pathlib.Path.home() / "workspace/party-line-assets/research.md"
OUT = pathlib.Path.home() / "workspace/party-line-assets"
text = SRC.read_text()

# Split into category blocks on "## " headers (keep Gaps separate)
parts = re.split(r"(?m)^## ", text)
preamble = parts[0]
cat_blocks, gaps_block = [], ""
for p in parts[1:]:
    if p.lstrip().startswith("Gaps"):
        gaps_block = p
    else:
        cat_blocks.append(p)

def parse_entry(block):
    """block starts with 'N. Title...' then '- Image:', '- Source:', '- Why:' lines."""
    title_m = re.match(r"(\d+)\.\s*(.+)", block.strip().split("\n")[0])
    num = title_m.group(1) if title_m else "?"
    title = title_m.group(2).strip() if title_m else block.strip().split("\n")[0]
    img = re.search(r"(?m)^- Image:\s*(\S+)", block)
    src = re.search(r"(?m)^- Source:\s*(\S+)", block)
    why = re.search(r"(?m)^- Why:\s*(.+)", block)
    return {
        "num": num,
        "title": title,
        "img": img.group(1) if img else "",
        "src": src.group(1) if src else "",
        "why": why.group(1).strip() if why else "",
    }

categories = []
total = 0
for cb in cat_blocks:
    lines = cb.split("\n")
    cat_title = lines[0].strip()
    note = ""
    # capture blockquote notes right under the header
    for ln in lines[1:6]:
        if ln.strip().startswith(">"):
            note += ln.strip().lstrip(">").strip() + " "
    entry_blocks = re.split(r"(?m)^### ", cb)
    entries = [parse_entry(b) for b in entry_blocks[1:]]
    total += len(entries)
    categories.append({"title": cat_title, "note": note.strip(), "entries": entries})

def esc(s): return html.escape(s, quote=True)

def entries_of(cat): return cat["entries"]

# ---------- gallery.html ----------
cards = []
for cat in categories:
    cnum = re.match(r"(\d+)\.", cat["title"])
    cards.append(f'<section class="cat"><h2>{esc(cat["title"])} <span class="count">{len(cat["entries"])}</span></h2>')
    if cat["note"]:
        cards.append(f'<p class="catnote">{esc(cat["note"])}</p>')
    cards.append('<div class="grid">')
    for e in entries_of(cat):
        cards.append(
            '<figure class="card">'
            f'<div class="imgwrap"><img src="{esc(e["img"])}" alt="{esc(e["title"])}" loading="lazy" onerror="imgFail(this)"></div>'
            f'<figcaption><div class="t"><span class="num">#{e["num"]}</span> {esc(e["title"])}</div>'
            f'<p class="why">{esc(e["why"])}</p>'
            + (f'<a class="src" href="{esc(e["src"])}" target="_blank" rel="noopener">source ↗</a>' if e["src"] else "")
            + '</figcaption></figure>'
        )
    cards.append('</div></section>')

gaps_html = ""
if gaps_block:
    items = [ln.strip()[2:].strip() for ln in gaps_block.split("\n") if ln.strip().startswith("- ")]
    gaps_html = '<section class="cat"><h2>Wanted — gaps & next queries</h2><ul class="gaps">' + \
        "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul></section>"

gallery = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The SI Party Line — 80s/90s Chat Interface Visual Research</title>
<style>
:root{{--amber:#ffb000;--bg:#0b0b10;--panel:#14141c;--ink:#e8e2d4;--dim:#8a8578}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--ink);font-family:ui-monospace,Menlo,Consolas,monospace;margin:0;padding:2rem 1.5rem}}
header{{max-width:1100px;margin:0 auto 2rem}}
h1{{color:var(--amber);font-size:1.6rem;margin:0 0 .4rem}}
.sub{{color:var(--dim);font-size:.85rem;line-height:1.5}}
.cat{{max-width:1100px;margin:0 auto 2.5rem}}
.cat h2{{color:var(--amber);font-size:1.05rem;border-bottom:1px solid #2a2a35;padding-bottom:.4rem}}
.count{{color:var(--dim);font-size:.8rem}}
.catnote{{color:var(--dim);font-size:.8rem;font-style:italic}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:1rem;margin-top:1rem}}
.card{{background:var(--panel);border:1px solid #26262f;border-radius:8px;overflow:hidden;margin:0;display:flex;flex-direction:column}}
.imgwrap{{background:#000;min-height:150px;display:flex;align-items:center;justify-content:center}}
.imgwrap img{{max-width:100%;max-height:260px;object-fit:contain;display:block}}
.broken{{color:var(--dim);font-size:.75rem;text-align:center;padding:2rem 1rem}}
.broken a{{color:var(--amber)}}
figcaption{{padding:.7rem .8rem .9rem;font-size:.78rem}}
.t{{color:var(--ink);margin-bottom:.35rem;line-height:1.35}}
.num{{color:var(--amber)}}
.why{{color:var(--dim);margin:.2rem 0 .5rem;line-height:1.45}}
.src{{color:var(--amber);text-decoration:none;font-size:.75rem}}
.src:hover{{text-decoration:underline}}
.gaps li{{color:var(--dim);font-size:.82rem;margin-bottom:.35rem;line-height:1.5}}
footer{{max-width:1100px;margin:3rem auto 0;color:var(--dim);font-size:.75rem;border-top:1px solid #2a2a35;padding-top:1rem}}
</style></head><body>
<header><h1>☎ The SI Party Line — visual research</h1>
<p class="sub">{total} screenshots &amp; artifacts · 80s party lines → IRC → AOL → AIM → Netscape → ICQ → BBS ANSI<br>
URLs hotlinked as found; some CDN links may rot — every card links its source page. Every entry individually verified by viewing on 2026-09-24; mislabels fixed, dead entries dropped.</p></header>
{''.join(cards)}
{gaps_html}
<footer>Researched 2026-09-24 for the Party Line project · parked, not approved to build</footer>
<script>function imgFail(el){{var w=el.parentNode;var s=el.getAttribute('src');w.innerHTML='<div class="broken">image unavailable<div><a href="'+s+'" target="_blank" rel="noopener">try direct link ↗</a></div></div>';}}</script>
</body></html>"""

(OUT / "gallery.html").write_text(gallery)

# ---------- catalog.md ----------
cat_md = ["# The SI Party Line — Visual Research Catalog\n",
          f"*{total} entries · researched 2026-09-24, individually verified same day · images hotlinked in `gallery.html` (same folder)*\n"]
for cat in categories:
    cat_md.append(f"\n## {cat['title']}\n")
    if cat["note"]:
        cat_md.append(f"> {cat['note']}\n")
    for e in cat["entries"]:
        cat_md.append(f"\n### {e['num']}. {e['title']}\n")
        if e["img"]: cat_md.append(f"- Image: {e['img']}\n")
        if e["src"]: cat_md.append(f"- Source: {e['src']}\n")
        if e["why"]: cat_md.append(f"- Why: {e['why']}\n")
if gaps_block:
    cat_md.append("\n## Wanted — gaps & next queries\n")
    for ln in gaps_block.split("\n"):
        if ln.strip().startswith("- "):
            cat_md.append(ln + "\n")
(OUT / "catalog.md").write_text("".join(cat_md))
print(f"entries={total} gallery_bytes={len(gallery)}")

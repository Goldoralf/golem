#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LE SNAPSHOT : une page HTML qui dit où en est chaque entité de golem (docs/release-tool-plan.md §3, 2026-11-27).

Un panneau par entité (golem, Golem Engine, golem-fx, REAPER, contenu d'usine, coquille vide, golem.fm, golem-site,
golem-binaries, plugins tiers) : ce qui est ici, ce qui est publié, ce que golem épingle, un statut par ligne et ce qu'il
faut faire. Les valeurs viennent de tools/golem_inventory.py ; cette page ne fait que les montrer.

    tools/snapshot.py                 # écrit assets/.cache/snapshot/<date>.html et latest.html, dit le résumé
    tools/snapshot.py --offline       # sans réseau : les lignes « publié » restent grises
    tools/snapshot.py --json          # l'inventaire brut
    tools/snapshot.py --out FICHIER   # ailleurs

LECTURE SEULE : rien n'est modifié, ni ici ni dans les dépôts voisins. La page est autonome (aucune ressource externe) et
en anglais, comme tout ce que golem affiche. Rend 1 quand au moins une ligne est rouge : un script peut s'y fier.
"""
import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golem_inventory as inv                                            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PILL = {"ok": "aligned", "warn": "to watch", "bad": "behind", "na": "not read"}

# les couleurs de l'app (app/style.css) : la page est un outil du rack
CSS = """
:root{--bg:#0d0f12;--panel:#15191f;--panel2:#1c2129;--line:#262d37;--text:#e7ecf2;--muted:#8a94a3;--accent:#ff5a3c;
  --ok:#2ecc71;--warn:#ff9f43;--bad:#ff4d4d;--na:#5d6675;
  --ui:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
  color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font:14px/1.45 var(--ui);margin:0}
.wrap{max-width:1240px;margin:0 auto;padding:20px 16px 40px}
header.top{display:flex;flex-wrap:wrap;gap:18px 32px;align-items:flex-end;justify-content:space-between;
  border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:18px}
.brand{font:700 26px var(--mono);letter-spacing:-.02em}
.brand i{font-style:normal;color:var(--accent)}
.brand small{display:block;font:400 13px var(--ui);color:var(--muted);letter-spacing:0;margin-top:2px}
.sum{display:flex;flex-wrap:wrap;gap:10px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 14px;min-width:110px}
.kpi b{display:block;font:600 20px var(--mono);font-variant-numeric:tabular-nums}
.kpi span{font-size:12px;color:var(--muted)}
.kpi.bad b{color:var(--bad)}.kpi.warn b{color:var(--warn)}.kpi.ok b{color:var(--ok)}
.target{background:var(--panel2);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;
  padding:12px 16px;margin-bottom:20px}
.target h2{margin:0 0 6px;font:600 15px var(--ui)}
.target ol{margin:0;padding-left:20px;color:var(--text);font-size:13px}
.target li{margin:3px 0}.target li b{color:var(--accent);font-weight:600}
.target p{margin:0;color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}
@media (max-width:420px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-top:3px solid var(--na);border-radius:10px;overflow:hidden;
  display:flex;flex-direction:column;min-width:0}
.card.s-bad{border-top-color:var(--bad)}.card.s-warn{border-top-color:var(--warn)}.card.s-ok{border-top-color:var(--ok)}
.ch{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;padding:12px 14px 8px}
.ch h3{margin:0;font:600 16px var(--ui)}
.ch .role{display:block;color:var(--muted);font-size:12px;margin-top:1px}
.pill{flex:none;font:600 11px var(--ui);letter-spacing:.04em;text-transform:uppercase;border-radius:999px;padding:3px 9px;white-space:nowrap}
.pill.ok{background:rgba(46,204,113,.16);color:var(--ok)}.pill.warn{background:rgba(255,159,67,.16);color:var(--warn)}
.pill.bad{background:rgba(255,77,77,.18);color:var(--bad)}.pill.na{background:rgba(93,102,117,.25);color:var(--muted)}
.tbl{overflow-x:auto;padding:0 14px}
table{width:100%;border-collapse:collapse;font-size:13px}
td{text-align:left;padding:5px 6px;border-top:1px solid var(--line);vertical-align:top}
tr:first-child td{border-top:none}
td.l{color:var(--muted);white-space:nowrap}
td.v{font-family:var(--mono);font-size:12.5px;overflow-wrap:anywhere}
td.v small{display:block;font:400 12px var(--ui);color:var(--muted);margin-top:1px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-top:5px}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}.dot.na{background:var(--na)}
.todo{margin:10px 14px 14px;padding:9px 11px;background:var(--panel2);border-radius:6px;font-size:12.5px}
.todo.none{color:var(--muted)}.todo ul{margin:0;padding-left:16px}.todo li{margin:2px 0}
.foot{margin-top:22px;color:var(--muted);font-size:12px;display:flex;flex-wrap:wrap;gap:6px 18px;justify-content:space-between}
.legend{display:flex;flex-wrap:wrap;gap:12px}.legend .dot{margin:0 6px 0 0;vertical-align:0}
"""


def _e(s):
    return html.escape(str(s if s is not None else ""))


def card(ent):
    def line(r):
        note = f"<small>{_e(r['note'])}</small>" if r["note"] else ""
        return (f'<tr><td class="l">{_e(r["label"])}</td><td class="v">{_e(r["value"])}{note}</td>'
                f'<td><span class="dot {r["status"]}" title="{PILL[r["status"]]}"></span></td></tr>')

    rows = "".join(line(r) for r in ent["rows"])
    fixes = [r["fix"] for r in ent["rows"] if r["fix"] and r["status"] in ("bad", "warn")]
    todo = ('<div class="todo"><ul>' + "".join(f"<li>{_e(f)}</li>" for f in fixes) + "</ul></div>") if fixes else \
        '<div class="todo none">Nothing to do.</div>'
    return (f'<article class="card s-{ent["status"]}" id="{_e(ent["id"])}"><div class="ch"><div><h3>{_e(ent["name"])}</h3>'
            f'<span class="role">{_e(ent["role"])}</span></div><span class="pill {ent["status"]}">{PILL[ent["status"]]}</span></div>'
            f'<div class="tbl"><table>{rows}</table></div>{todo}</article>')


def render(data):
    """La page entière, autonome, depuis l'inventaire (tools/golem_inventory.collect)."""
    c = data["counts"]
    todo = data.get("todo") or []
    if todo:
        target = "<ol>" + "".join(f'<li><b>{_e(t["entity"])}</b> · {_e(t["fix"])}</li>' for t in todo) + "</ol>"
    else:
        target = "<p>Nothing is behind.</p>"
    off = " · offline: published versions not read" if data.get("offline") else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>golem snapshot</title><style>{CSS}</style></head><body><div class="wrap">
<header class="top"><div class="brand">/golem<i>_</i> snapshot
<small>Where every golem entity stands · read on {_e(data["made"])}{off}</small></div>
<div class="sum"><div class="kpi"><b>{_e(data.get("last_release") or "?")}</b><span>last release</span></div>
<div class="kpi bad"><b>{c["bad"]}</b><span>behind</span></div><div class="kpi warn"><b>{c["warn"]}</b><span>to watch</span></div>
<div class="kpi ok"><b>{c["ok"]}</b><span>aligned</span></div></div></header>
<section class="target"><h2>Before the next release</h2>{target}</section>
<div class="grid">{"".join(card(e) for e in data["entities"])}</div>
<div class="foot"><div class="legend"><span><span class="dot ok"></span>aligned</span>
<span><span class="dot warn"></span>to watch, or behind on purpose</span>
<span><span class="dot bad"></span>behind: fix before the release</span><span><span class="dot na"></span>not read, or not applicable</span></div>
<span>tools/snapshot.py · read-only · a delay kept on purpose is written in provision/pins-held.json</span></div>
</div></body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Where every golem entity stands: one HTML page.")
    ap.add_argument("--offline", action="store_true", help="no network read (published versions stay grey)")
    ap.add_argument("--json", action="store_true", help="print the raw inventory instead of writing the page")
    ap.add_argument("--out", help="write the page here (default: assets/.cache/snapshot/<date>.html and latest.html)")
    a = ap.parse_args(argv)
    data = inv.collect(inv.Ctx(offline=a.offline))
    if a.json:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        return 1 if data["counts"]["bad"] else 0
    page = render(data)
    if a.out:
        outs = [Path(a.out)]
    else:
        d = ROOT / "assets" / ".cache" / "snapshot"
        outs = [d / (data["made"][:10] + ".html"), d / "latest.html"]
    for o in outs:
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_text(page, encoding="utf-8")
    c = data["counts"]
    print(f"golem snapshot — last release {data.get('last_release') or '?'} — {c['bad']} behind, {c['warn']} to watch, {c['ok']} aligned")
    for t in data.get("todo") or []:
        print(f"  ✗ {t['entity']} · {t['label']}: {t['fix']}")
    print(f"→ {outs[-1]}")
    return 1 if c["bad"] else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Empaquette les DÉMOS D'USINE pour les publier une fois (docs/preset-preview.md §10, 2026-11-15).

Chaque golem rendait lui-même toutes les démos d'usine — une demi-heure de moteur pris, 67 Mo refaits partout. Elles
sont rendues UNE fois (sur le rack du mainteneur), empaquetées ici, publiées en asset de release (golem-binaries,
`factory-demos-vN`) ; un golem les télécharge (bridge/factory_demos.py) et ne rend que ce qui manque ou a changé. golem.fm
prend la même archive : une seule source.

Ce qui part : les démos des patchs d'usine (patch-factory-*), des lanes des presets d'usine (preset-factory-*), des
blocs drums/standard (block-factory-*, block-patch-factory-*), des sons claviers d'usine (sound-* de
sound_preview.factory_sounds) et des kits d'usine (kit-<id> de drum_preview.factory_kits). Jamais une démo de
l'utilisateur (ses presets Vital, ses kits importés, ses écoutes).

    ./tools/pack-factory-demos.py                 # -> assets/.cache/factory-demos/golem-factory-demos.tar + .json (index, sha256)
    ./tools/pack-factory-demos.py --publish factory-demos-v1   # + gh release create sur Goldoralf/golem-binaries
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REPO = "Goldoralf/golem-binaries"
NAME = "golem-factory-demos"


def factory_dirs():
    from bridge import config as C, sound_preview as SP, drum_preview as DP
    root = C.PREVIEWS_DIR
    prefixes = ("patch-factory-", "preset-factory-", "block-factory-", "block-patch-factory-")
    keep = {os.path.basename(SP.sound_dir(s)) for s in SP.factory_sounds()}
    keep |= {os.path.basename(DP.kit_dir(k)) for k in DP.factory_kits()}
    out = []
    for d in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if os.path.isdir(os.path.join(root, d)) and (d.startswith(prefixes) or d in keep):
            out.append(d)
    from bridge import factory
    return root, newest_per_patch(root, out, [f[:-5] for f in factory.catalog().get("patches") or []])


def newest_per_patch(root, dirs, patch_ids):
    """Un patch rendu sur une AUTRE entrée qu'avant (une carte changée, une entrée empruntée) garde son ancien dossier
    (`patch-<id>-in2` à côté de `patch-<id>`) : le lot n'emporte que le plus RÉCENT de chaque patch d'usine
    (2026-11-21), sinon il livrerait un rendu périmé à côté du bon."""
    def generated(d):
        try:
            return json.load(open(os.path.join(root, d, "preview.json"), encoding="utf-8")).get("generated") or ""
        except (OSError, ValueError):
            return ""
    out = list(dirs)
    for pid in patch_ids:
        mine = [d for d in dirs if re.fullmatch("patch-" + re.escape(pid) + r"(-in[0-9k]+)?", d)]
        if len(mine) > 1:
            newest = max(mine, key=generated)
            out = [d for d in out if d not in mine or d == newest]
    return out


_IN = re.compile(r"(-in[0-9k]+)?$")


def _sha_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _git(*args):
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _golem_fx_version():
    """La version de golem-fx que ce dépôt installe (provision/golem_fx.py, chargé par son chemin : hors paquet)."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("_gfx", os.path.join(ROOT, "provision", "golem_fx.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return str(mod.VERSION)
    except Exception:
        return None


def header(tag):
    """D'OÙ vient le lot (2026-11-21, demandé par golem.fm) : l'empreinte d'une démo suit le DOCUMENT, pas le moteur —
    un changement de golem-fx ou du catalogue change le son sans changer l'empreinte. Le lot dit donc avec quoi il a
    été rendu ; `rack_dirty` = des fichiers suivis modifiés au moment d'empaqueter (le commit ne dit alors pas tout)."""
    try:
        cat = json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json"), encoding="utf-8")).get("catalog_version")
    except (OSError, ValueError):
        cat = None
    return {"tag": tag, "rack_commit": _git("rev-parse", "HEAD") or None,
            "rack_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "catalog_version": cat, "golem_fx_version": _golem_fx_version()}


def di_refs(src=None):
    """Les DI et phrases MIDI de référence (library/di-refs) : {ref: {file, sha256, kind}} + ce que l'index nomme sans
    que le fichier existe (`missing` : la voix, tant qu'elle n'est pas enregistrée). Rend aussi les fichiers à poser."""
    src = src or os.path.join(ROOT, "library", "di-refs")
    try:
        refs = (json.load(open(os.path.join(src, "index.json"), encoding="utf-8")) or {}).get("refs") or {}
    except (OSError, ValueError):
        return {"refs": {}, "missing": []}, []
    out, missing, files = {}, [], [(os.path.join(src, "index.json"), "di-refs/index.json")]
    for ref, e in sorted(refs.items()):
        f = str((e or {}).get("file") or "")
        p = os.path.join(src, *f.split("/"))
        if not f or ".." in f.split("/") or not os.path.isfile(p):
            missing.append(ref)
            continue
        out[ref] = {"file": "di-refs/" + f, "sha256": _sha_file(p), "kind": e.get("kind") or "audio"}
        files.append((p, "di-refs/" + f))
    return {"refs": out, "missing": missing, "index": {"file": "di-refs/index.json", "sha256": _sha_file(files[0][0])}}, files


def documents():
    """Les DOCUMENTS d'usine tels que livrés (library/factory/** + history.json) : [{kind, id, file, sha256,
    fingerprint}]. `sha256` = les octets du fichier dans l'archive ; `fingerprint` = `preset_export.fingerprint` du
    fichier LIVRÉ (JSON seulement) — pas celle d'une démo, calculée sur le patch lié à la carte du rack qui rend."""
    from bridge import factory, preset_export
    docs, files = [], []
    for kind, names in sorted(factory.catalog().items()):
        sub, _dst, ext = factory.KINDS[kind]
        for fn in sorted(names):
            p = os.path.join(factory.SRC, sub, fn)
            arc = f"factory/{sub}/{fn}"
            fp = None
            if ext == ".json":
                try:
                    fp = preset_export.fingerprint(json.load(open(p, encoding="utf-8")))
                except (OSError, ValueError):
                    fp = None
            docs.append({"kind": kind, "id": fn[: -len(ext)], "file": arc, "sha256": _sha_file(p), "fingerprint": fp})
            files.append((p, arc))
    hist = None
    if os.path.isfile(factory.HISTORY):
        hist = {"file": "factory/history.json", "sha256": _sha_file(factory.HISTORY)}
        files.append((factory.HISTORY, "factory/history.json"))
    return docs, hist, files


def export_envelope(shipped, out):
    """L'ENVELOPPE D'EXPORT d'un preset d'usine pour le magasin de golem.fm (2026-11-21) : golem.fm range un preset
    sous la forme que le rack publie (`preset_export.build_export`) et y lit `deps[]` ; le fichier livré est le preset
    nu. On garde de l'export fait sur le rack de référence ce qui vaut pour TOUS : les deps (captures = liens
    TONE3000, fichiers d'usine marqués `factory`), la version du catalogue, `unresolved` s'il y en a. On en retire ce
    qui est de CE rack : `preset` (remplacé par le fichier LIVRÉ, sans liaison à une carte), `inputs`,
    `foot_context`, et les deps `preview` (les écoutes sont dans `renders[]`)."""
    from bridge import preset_export
    env = {"schema_version": out.get("schema_version"), "catalog_version": out.get("catalog_version"),
           "preset": shipped, "deps": [d for d in out.get("deps") or [] if d.get("kind") != "preview"],
           "preview_fingerprint": preset_export.fingerprint(shipped)}
    if out.get("unresolved"):
        env["unresolved"] = out["unresolved"]
    return env


def preset_exports(out_dir):
    """Écrit l'enveloppe de chaque preset d'usine dans `out_dir`/preset-exports ; rend ([{kind, id, file, sha256,
    fingerprint, deps, unresolved}], fichiers). L'export lit le preset POSÉ ici : retouché, ses deps ne seraient plus
    celles de l'original — `edited` le dit, et le lot ne se publie pas ainsi."""
    from bridge import factory, preset_export
    edited = {r["id"] for r in factory.edited() if r["kind"] == "presets"}
    docs, files = [], []
    os.makedirs(os.path.join(out_dir, "preset-exports"), exist_ok=True)
    for fn in sorted(factory.catalog().get("presets") or []):
        pid = fn[:-5]
        try:
            shipped = json.load(open(os.path.join(factory.SRC, "presets", fn), encoding="utf-8"))
            out, _blobs = preset_export.build_export(pid)
        except (OSError, ValueError):
            out = None
        if not out:
            continue
        env = export_envelope(shipped, out)
        p = os.path.join(out_dir, "preset-exports", fn)
        json.dump(env, open(p, "w", encoding="utf-8"), ensure_ascii=False, sort_keys=True)
        arc = f"factory/preset-exports/{fn}"
        docs.append({"kind": "preset-exports", "id": pid, "file": arc, "sha256": _sha_file(p),
                     "fingerprint": env["preview_fingerprint"], "deps": len(env["deps"]),
                     "unresolved": len(env.get("unresolved") or []), **({"edited": True} if pid in edited else {})})
        files.append((p, arc))
    return docs, files


def _clips(root, rel, owner, di, duration):
    """Les rendus d'un dossier de démo (son preview.json) : une ligne par scène."""
    try:
        e = json.load(open(os.path.join(root, *rel.split("/"), "preview.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for scene, path in sorted((e.get("scenes") or {}).items()):
        f = os.path.join(root, *rel.split("/"), os.path.basename(str(path)))
        if not os.path.isfile(f):
            continue
        ref = (e.get("refs") or {}).get(scene) or e.get("ref")
        out.append(dict(owner, scene=scene, file=f"{rel}/{os.path.basename(f)}", sha256=_sha_file(f),
                        duration=duration(f), di_ref=ref, di_sha256=(di.get(ref) or {}).get("sha256"),
                        fingerprint=e.get("fingerprint"), generated=e.get("generated"),
                        **({"made": e["made"], "from": e.get("from")} if e.get("made") else {})))
    return out


def renders(root, dirs, patch_ids, preset_ids, di, duration):
    """Chaque rendu d'un patch ou d'une lane de preset d'usine : [{kind, id, (lane, input), scene, file, sha256,
    duration, di_ref, di_sha256, fingerprint, generated}]. Un patch a un dossier par entrée (`patch-<id>[-in<k>]`)."""
    out = []
    for pid in sorted(patch_ids):
        for d in dirs:
            m = re.fullmatch("patch-" + re.escape(pid) + r"(?:-in([0-9k]+))?", d)
            if m:
                out += _clips(root, d, {"kind": "patch", "id": pid, "input": m.group(1) or "1"}, di, duration)
    for pid in sorted(preset_ids):
        base = os.path.join(root, "preset-" + pid)
        for lane in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            out += _clips(root, f"preset-{pid}/{lane}", {"kind": "preset", "id": pid, "lane": lane}, di, duration)
    return out


def coverage(patch_ids, rendered, why):
    """CHAQUE patch d'usine : ses scènes rendues, ou la raison de leur absence (`why(id)` -> texte ou None) — le site
    dit « à venir » plutôt que de montrer un trou. `stale` = le document a changé depuis le rendu."""
    out = []
    for pid in sorted(patch_ids):
        n = sum(1 for r in rendered if r["kind"] == "patch" and r["id"] == pid)
        reason, stale = why(pid, n)
        out.append({"id": pid, "renders": n, **({"reason": reason} if reason else {}), **({"stale": True} if stale else {})})
    return out


def _why(pid, n):
    """La raison lue là où le lot la lit (preview.plan) : DI de référence absente, rôle sans phrase, pas encore rendu."""
    from bridge import preview
    try:
        doc = json.load(open(os.path.join(ROOT, "library", "factory", "patches", pid + ".json"), encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    if doc.get("role") in preview.BATCH_ROLES_SKIPPED:
        return (None if n else "triggered samples: no phrase to play"), False
    try:
        in_key = preview.patch_input(pid)
        if not in_key:
            # pas d'entrée de son rôle sur la carte du rack qui rend : la démo est faite sur une entrée EMPRUNTÉE, par un
            # preset temporaire — on demande au même chemin si elle est à jour, sans rien rendre
            r = preview.render_patch_borrowed(pid, 0, dry=True)
            if r.get("status") == "stale":
                return None, bool(n)
            if r.get("reason") == "up to date":
                return None, False
            return (None if n else r.get("reason") or "not rendered"), False
        pl = preview.plan(preview.PATCH_PREFIX + pid, in_key=in_key)
    except Exception as e:                               # un patch qui ne se lie pas ici : dit, pas deviné
        return (None if n else f"not rendered ({type(e).__name__})"), False
    if isinstance(pl, str):
        return (None if n else pl), False
    if not n:
        return "not rendered yet", False
    return None, not preview._up_to_date(pl)


def block_keep(root):
    """Les démos de bloc qui correspondent à un bloc d'AUJOURD'HUI : {« block-x/10/standard »}. Un bloc d'usine qui a
    changé de nature (une boîte à rythmes devenue un Standard, 2026-11-21) laisse sa vieille démo dans le dossier :
    elle ne part pas."""
    from bridge import preview
    return {os.path.relpath(preview.block_dir(pid, sw), root).replace(os.sep, "/") + "/" + kind
            for pid, sw, kind, _b in preview.block_targets()}


def build(root, dirs, tag, out_dir):
    """Écrit l'archive et son index dans `out_dir` ; rend l'index. `items` reste ce qu'un golem pose dans
    library/previews (bridge/factory_demos.py ne lit que lui) ; le reste est pour golem.fm."""
    from bridge import factory, preview
    os.makedirs(out_dir, exist_ok=True)
    tar_path = os.path.join(out_dir, NAME + ".tar")
    index = {"name": NAME, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **header(tag), "items": {}}
    di, di_files = di_refs()
    docs, hist, doc_files = documents()
    exp_docs, exp_files = preset_exports(out_dir)
    docs, doc_files = docs + exp_docs, doc_files + exp_files
    blocks, dropped = block_keep(root), []
    with tarfile.open(tar_path, "w") as tf:                 # .opus déjà compressé : un tar simple
        for d in dirs:
            # les lanes d'un preset (preset-x/<lane>/) et les blocs (block-x/<switch>/) sont un niveau plus bas
            for sub, _ds, fs in sorted(os.walk(os.path.join(root, d))):
                rel = os.path.relpath(sub, root).replace(os.sep, "/")
                files = {}
                for f in sorted(fs):
                    p = os.path.join(sub, f)
                    if rel.startswith("block-") and f"{rel}/{f.rsplit('.', 1)[0]}" not in blocks:
                        dropped.append(f"{rel}/{f}")
                        continue
                    if not f.endswith((".wav", ".tmp", ".midi.txt")):
                        files[f] = _sha_file(p)
                        tf.add(p, arcname=f"{rel}/{f}")
                if files:
                    index["items"][rel] = files
        for p, arc in doc_files + di_files:
            tf.add(p, arcname=arc)
    patch_ids = [f[:-5] for f in factory.catalog().get("patches", [])]
    index["documents"], index["history"], index["di"] = docs, hist, di
    index["renders"] = renders(root, dirs, patch_ids, preview.factory_preset_ids(), di["refs"],
                               lambda f: preview._clip_duration(f))
    index["patches"] = coverage(patch_ids, index["renders"], _why)
    index["dropped_block_demos"] = dropped                # dites, pas tues : la démo d'un bloc qui n'existe plus
    index["sha256"] = _sha_file(tar_path)
    index["bytes"] = os.path.getsize(tar_path)
    idx_path = os.path.join(out_dir, NAME + ".json")
    json.dump(index, open(idx_path, "w"), indent=1)
    return index, tar_path, idx_path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "assets", ".cache", "factory-demos"))
    ap.add_argument("--tag", help="the tag written in the index when packing without publishing")
    ap.add_argument("--publish", metavar="TAG", help="publish to the golem-binaries release TAG (gh, not marked latest)")
    a = ap.parse_args()
    os.environ.setdefault("GOLEM_FACTORY_DEMOS", "0")
    root, dirs = factory_dirs()
    index, tar_path, idx_path = build(root, dirs, a.publish or a.tag, a.out)
    todo = [p for p in index["patches"] if p.get("reason") or p.get("stale")]
    print(f"{len(index['items'])} demo folders, {len(index['documents'])} factory documents, {len(index['di']['refs'])} "
          f"reference DIs, {len(index['renders'])} renders, {index['bytes'] / 1e6:.1f} MB -> {tar_path}")
    for p in todo:
        print(f"  {p['id']}: " + (p.get("reason") or "render older than the document (stale)"))
    for d in index["documents"]:
        if d["kind"] == "preset-exports" and (d.get("unresolved") or d.get("edited")):
            print(f"  ! preset {d['id']}: " + ("edited on this rack" if d.get("edited") else f"{d['unresolved']} unresolved asset(s)")
                  + " — its export is not the original's")
    if index["rack_dirty"]:
        print("  ! tracked files are modified: rack_commit does not describe this pack exactly")
    if a.publish:
        notes = (f"Factory content of golem, one set for the rack and golem.fm: {len(index['documents'])} documents, "
                 f"{len(index['renders'])} renders rendered once ({len(index['items'])} demo folders), "
                 f"{len(index['di']['refs'])} reference DIs. Downloaded by bridge/factory_demos.py; golem.fm reads the same archive.")
        subprocess.run(["gh", "release", "create", a.publish, "--repo", REPO, "--title", f"Factory demos ({a.publish})",
                        "--notes", notes, "--latest=false", tar_path, idx_path], check=True)
        print(f"published: https://github.com/{REPO}/releases/tag/{a.publish}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

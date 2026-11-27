#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LE KIT DE RÉFÉRENCE de la coquille vide (docs/release-tool-plan.md §3 bis, étape 2, 2026-11-27) : ce que la démo montre
et que le banc d'extraction n'a pas — le MATÉRIEL du rack de référence (carte Volt 276, clavier MPK Mini, batterie Alesis
Nitro) et la PRISE DE DÉMO de Library ▸ Tracks ▸ Recordings.

Avant : l'instantané d'usine montrait le matériel branché CE JOUR-LÀ sur le poste du développeur (un échange Nitro ↔ MPK
à la main, golem relancé, un instantané invalide si un appareil manquait), puis des scripts hors dépôt GREFFAIENT après
coup les lectures d'une vieille coquille — des pages Gear et Recordings jamais rendues au commit publié. La prise de démo,
dont le dossier n'existe plus sur le rack, ne survivait que dans la coquille déjà en ligne.

Maintenant : le kit est DÉCLARÉ (des fichiers), et l'extraction le REJOUE pendant le rendu — chaque lecture que le kit
couvre est servie au navigateur avec ses valeurs (les GET, et l'état du WebSocket), si bien que les pages, leurs ancres et
leurs captures sont celles du commit extrait, avec le matériel et la prise de référence. Les mêmes valeurs sont ensuite
écrites dans l'instantané. Rien n'est branché, rien n'est greffé à la main.

Deux fichiers, la même forme (une « couche ») :
  · tools/shell/reference-rack.json — le matériel (du texte, dans le dépôt) ;
  · <kit>/demo-take/take.json + media/ — la prise de démo et ses pistes déjà encodées (de l'audio : hors du dépôt,
    `GOLEM_SHELL_KIT`, défaut ~/golem-doc-work/reference).

Une couche :
  {"what": "…", "recorded": {"commit", "made", "how"},
   "rack": {"variant", "seen": […]},                     # le matériel déclaré (seulement la couche matériel)
   "set":   {"/api/soundcard": {"card": {…}, "usb": […]}},        # ces clés REMPLACENT celles de la lecture du banc
   "add":   {"/api/loops": {"key": "takes", "id": "dir", "entries": […]}},   # ces entrées s'AJOUTENT à une liste
   "whole": {"/api/loop-peaks/…": {…}},                  # la lecture ENTIÈRE (le banc ne l'a pas)
   "state": {"hotplug": {…}},                            # ces clés remplacent celles de l'état (WebSocket, /api/state)
   "media": {"/api/loop/…": {"file": "media/…", "type": "audio/ogg", "sha256": "…"}},
   "examples": {"<nom>": {"set": {…}, "state": {…}, "skip_gestures": true}}}   # ce qu'UN exemple montre en plus

Le reste d'une lecture vient du banc, donc du code extrait : une clé neuve du bridge apparaît d'elle-même. Ce que le kit
remplace peut vieillir : `shape_warnings` compare la FORME (les clés) d'une entrée du kit à celle d'une entrée que le banc
rend pour la même liste, et le dit dans SNAPSHOT.json — c'est le signal pour réenregistrer le kit, matériel branché.
"""
import copy
import hashlib
import json
import os
import shutil
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACK_FILE = os.path.join(ROOT, "tools", "shell", "reference-rack.json")


def kit_dir():
    return os.environ.get("GOLEM_SHELL_KIT") or os.path.expanduser("~/golem-doc-work/reference")


def _path(read):
    """Une lecture sans sa requête : « /api/inputmap?card=x » -> « /api/inputmap »."""
    return read.split("?", 1)[0]


class Overlay:
    """Des couches empilées. Vide, elle ne change rien : l'extraction est alors celle d'avant (le matériel du poste)."""

    def __init__(self, layers=()):
        self.layers = []          # [(couche, son dossier)]
        for layer, where in layers:
            self.add(layer, where)

    def add(self, layer, where=None):
        self.layers.append((layer, where))
        return self

    def __bool__(self):
        return bool(self.layers)

    @classmethod
    def load(cls, rack=RACK_FILE, kit=None, log=print):
        """Le matériel (le fichier du dépôt) et la prise de démo (le kit), s'ils existent ; chaque absent est DIT."""
        ov = cls()
        if rack and os.path.isfile(rack):
            with open(rack, encoding="utf-8") as f:
                ov.add(json.load(f), os.path.dirname(rack))
        elif rack:
            log("reference kit: no rack file (%s) — the hardware shown is this machine's" % rack)
        take = os.path.join(kit or kit_dir(), "demo-take", "take.json")
        if os.path.isfile(take):
            with open(take, encoding="utf-8") as f:
                layer = json.load(f)
            bad = _media_problems(layer, os.path.dirname(take))
            if bad:
                raise RuntimeError("reference kit: the demo take is damaged — " + "; ".join(bad[:3]))
            ov.add(layer, os.path.dirname(take))
        else:
            log("reference kit: no demo take (%s) — Recordings will be empty" % take)
        return ov

    # ── ce que le kit couvre ────────────────────────────────────────────────────────────────────────────────────────
    def _parts(self, example=None):
        for layer, _ in self.layers:
            yield layer
            ex = (layer.get("examples") or {}).get(example) if example else None
            if ex:
                yield ex

    def covers(self, read, example=None):
        p = _path(read)
        return any(read in (part.get("whole") or {}) or p in (part.get("set") or {}) or p in (part.get("add") or {})
                   for part in self._parts(example))

    def whole(self, read, example=None):
        for part in self._parts(example):
            if read in (part.get("whole") or {}):
                return copy.deepcopy(part["whole"][read])
        return None

    def read(self, read, live, example=None):
        """La lecture telle que la coquille la montre : celle du banc, avec ce que le kit remplace ou ajoute."""
        w = self.whole(read, example)
        if w is not None:
            return w
        if not isinstance(live, dict):
            return live
        out, p = copy.deepcopy(live), _path(read)
        for part in self._parts(example):
            spec = (part.get("add") or {}).get(p)
            if spec:
                have = {e.get(spec["id"]) for e in out.get(spec["key"]) or [] if isinstance(e, dict)}
                out[spec["key"]] = list(out.get(spec["key"]) or []) + [copy.deepcopy(e) for e in spec["entries"]
                                                                       if e.get(spec["id"]) not in have]
            for k, v in ((part.get("set") or {}).get(p) or {}).items():
                out[k] = copy.deepcopy(v)
        return out

    def state(self, st, example=None):
        if not isinstance(st, dict):
            return st
        out = copy.deepcopy(st)
        for part in self._parts(example):
            for k, v in (part.get("state") or {}).items():
                out[k] = copy.deepcopy(v)
        return out

    def skip_gestures(self, example):
        """Un exemple dont le geste demande l'appareil lui-même (« This is a drum module ») : le kit en porte le résultat."""
        return any((layer.get("examples") or {}).get(example, {}).get("skip_gestures") for layer, _ in self.layers)

    def rack(self):
        """Le matériel déclaré, ou None : {variant, seen, recorded}."""
        for layer, _ in self.layers:
            if layer.get("rack"):
                return dict(layer["rack"], recorded=layer.get("recorded"))
        return None

    def whole_reads(self):
        return sorted({r for layer, _ in self.layers for r in (layer.get("whole") or {})})

    def touched(self):
        """Les lectures (sans requête) que le kit modifie dans l'instantané de base."""
        return sorted({p for layer, _ in self.layers for p in list(layer.get("set") or {}) + list(layer.get("add") or {})})

    def media(self):
        """{adresse: (fichier source, type, sha256)} des fichiers audio du kit."""
        out = {}
        for layer, where in self.layers:
            for url, m in (layer.get("media") or {}).items():
                out[url] = (os.path.join(where or "", m["file"]), m.get("type") or "application/octet-stream", m.get("sha256"))
        return out

    def describe(self):
        """Ce que SNAPSHOT.json dit du kit (`reference_kit`) : d'où vient chaque couche, ce qu'elle couvre."""
        return [{"what": layer.get("what"), "recorded": layer.get("recorded"),
                 "reads": sorted(list(layer.get("set") or {}) + list(layer.get("add") or {}) + list(layer.get("whole") or {})),
                 "state": sorted(layer.get("state") or {}), "examples": sorted(layer.get("examples") or {}),
                 "media": len(layer.get("media") or {})} for layer, _ in self.layers]

    def shape_warnings(self, read, live):
        """Les entrées du kit qui n'ont plus la forme de celles que le banc rend (une clé en plus ou en moins)."""
        out, p = [], _path(read)
        if not isinstance(live, dict):
            return out
        for layer, _ in self.layers:
            lists = dict((layer.get("set") or {}).get(p) or {})
            spec = (layer.get("add") or {}).get(p)
            if spec:
                lists[spec["key"]] = spec["entries"]
            for key, mine in lists.items():
                theirs = [e for e in (live.get(key) if isinstance(live.get(key), list) else []) if isinstance(e, dict)]
                mine = [e for e in (mine if isinstance(mine, list) else []) if isinstance(e, dict)]
                if not theirs or not mine:
                    continue
                want = set().union(*(set(e) for e in theirs))
                for e in mine:
                    more, less = sorted(set(e) - want), sorted(want - set(e))
                    if more or less:
                        out.append("%s .%s: the kit's entry %r has %s%s — re-record the kit" % (
                            p, key, e.get("name") or e.get("dir") or e.get("id"),
                            ("keys the bench no longer returns: %s" % ", ".join(more)) if more else "",
                            ("%sno %s" % ("; " if more else "", ", ".join(less))) if less else ""))
                        break
        return out

    # ── l'instantané écrit ──────────────────────────────────────────────────────────────────────────────────────────
    def apply_to_snapshot(self, out_dir, res, out_path, log=print):
        """Passe les fichiers de base de l'instantané par le kit, écrit les lectures entières, copie l'audio.
        -> ({adresse: {file, type}} à ajouter aux médias, [avertissements de forme])."""
        warnings = []
        touched = set(self.touched())
        for read in list(res["written"]):
            if _path(read) not in touched:
                continue
            p = out_path(out_dir, read)
            with open(p, encoding="utf-8") as f:
                live = json.load(f)
            warnings += self.shape_warnings(read, live)
            new = self.state(self.read(read, live)) if _path(read) == "/api/state" else self.read(read, live)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(new, f, ensure_ascii=False, indent=1)
        if "/api/state" in res["written"] and "/api/state" not in touched:
            p = out_path(out_dir, "/api/state")
            with open(p, encoding="utf-8") as f:
                st = json.load(f)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.state(st), f, ensure_ascii=False, indent=1)
        for read in self.whole_reads():
            p = out_path(out_dir, read)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.whole(read), f, ensure_ascii=False, indent=1)
            if read not in res["written"]:
                res["written"].append(read)
        media = {}
        for url, (src, typ, sha) in self.media().items():
            rel = "media/" + urllib.parse.unquote(url.lstrip("/"))
            dst = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            media[url] = {"file": rel, "type": typ}
        if media:
            log("reference kit: %d audio file(s) of the demo take copied as they are" % len(media))
        return media, sorted(set(warnings))


def _media_problems(layer, where):
    bad = []
    for url, m in (layer.get("media") or {}).items():
        p = os.path.join(where, m["file"])
        if not os.path.isfile(p):
            bad.append("%s is missing" % m["file"])
        elif m.get("sha256") and _sha(p) != m["sha256"]:
            bad.append("%s is not the recorded file (sha256 differs)" % m["file"])
    return bad


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def take_from_snapshot(snapshot_dir, out_dir, how, out_path=None):
    """ENREGISTRE la prise de démo d'un instantané existant dans le kit : ses lectures (/api/loops, /api/loop-peaks/…)
    et ses pistes déjà encodées, telles quelles (le mainteneur, 2026-11-21 : « tu gardes les tracks enregistrées telles
    quelles »). Rend la couche écrite."""
    with open(os.path.join(snapshot_dir, "SNAPSHOT.json"), encoding="utf-8") as f:
        snap = json.load(f)

    if out_path is None:                                  # le nom de fichier d'une lecture : la règle de l'instantané
        import shell_snapshot
        out_path = shell_snapshot.out_path

    def read(r):
        with open(out_path(snapshot_dir, r), encoding="utf-8") as f:
            return json.load(f)
    takes = read("/api/loops").get("takes") or []
    if not takes:
        raise RuntimeError("no take in %s" % snapshot_dir)
    layer = {"what": "the demo take of Library ▸ Tracks ▸ Recordings, kept as recorded",
             "recorded": {"commit": snap.get("commit"), "made": snap.get("made"), "how": how},
             "add": {"/api/loops": {"key": "takes", "id": "dir", "entries": takes}}, "whole": {}, "media": {}}
    os.makedirs(os.path.join(out_dir, "media"), exist_ok=True)
    for t in takes:
        for name in t.get("files") or []:
            q = urllib.parse.quote(t["dir"] + "/" + name, safe="/")
            peaks, url = "/api/loop-peaks/" + q, "/api/loop/" + q
            layer["whole"][peaks] = read(peaks)
            m = snap["media"][url]
            rel = "media/" + t["dir"] + "/" + name
            dst = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(snapshot_dir, m["file"]), dst)
            layer["media"][url] = {"file": rel, "type": m.get("type"), "sha256": _sha(dst)}
    with open(os.path.join(out_dir, "take.json"), "w", encoding="utf-8") as f:
        json.dump(layer, f, ensure_ascii=False, indent=1)
    return layer


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if len(sys.argv) == 4 and sys.argv[1] == "--record-take":
        lay = take_from_snapshot(sys.argv[2], os.path.join(sys.argv[3], "demo-take"), "taken from the published snapshot")
        print("demo take recorded: %d track(s) -> %s" % (len(lay["media"]), os.path.join(sys.argv[3], "demo-take")))
    else:
        print("usage: shell_overlay.py --record-take <snapshot dir> <kit dir>", file=sys.stderr)
        sys.exit(2)

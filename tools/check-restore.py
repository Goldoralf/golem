#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie qu'une sauvegarde se RESTAURE — localement et depuis le vault golem.fm.

    ./tools/check-restore.py              # cycle local + vault (catégorie « banks », petite)
    ./tools/check-restore.py --kind presets
    ./tools/check-restore.py --local      # sans le vault (rack hors ligne)

POURQUOI CE SCRIPT EXISTE
Un vault qui POUSSE et ne RESTAURE pas ne se découvre qu'au pire moment : après la
réinstallation, quand il n'y a plus rien à côté. Pousser est facile à croire (ça répond 200) ;
le seul test qui vaut est de **supprimer** et de **récupérer**, puis de comparer les octets.

CE QU'IL FAIT VRAIMENT
1. construit une sauvegarde et note son sha256 ;
2. cycle LOCAL : crée un preset témoin, sauvegarde, SUPPRIME le témoin, analyse à blanc,
   applique, et vérifie que le témoin est revenu ;
3. cycle VAULT : pousse (ou laisse faire l'auto-push, qui part déjà à la construction),
   **efface le fichier local**, relit la liste distante, tire, et compare le sha256 — c'est la
   seule preuve qui compte ;
4. nettoie derrière lui **des deux côtés** : témoin, sauvegardes locales, et l'upload de test
   dans le vault — un outil de vérification ne doit pas grossir ce qu'il vérifie.

Il ne touche à rien d'autre : l'import est ADDITIF (stratégie « skip ») et prend lui-même une
sauvegarde pré-import pour le rollback.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
WITNESS = "zz-restore-witness"
# ⚠ TOUTE sauvegarde construite ici part AUSSI au vault quand l'auto-push est actif — y
# compris celle du cycle local, qui ne « parle » pourtant pas au vault. On retient donc chaque
# nom créé et on purge les deux côtés à la fin : nettoyer seulement ce qu'on a poussé
# explicitement laisse une trace à chaque passage.
CREATED = []


def call(path, body=None, method="POST"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BRIDGE + path, data=data,
                               headers={"Content-Type": "application/json"}, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=300)
        return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def ok(label, good, detail=""):
    print(f"  {'✓' if good else '✗'} {label}" + (f" — {detail}" if detail else ""))
    return good


def local_cycle():
    """Le témoin disparaît, puis revient. C'est tout ce qu'on demande à une restauration."""
    print("Cycle LOCAL")
    src = next((p for p in os.listdir(os.path.join(ROOT, "presets"))
                if p.endswith(".json") and not p.startswith(".")), None)
    if not src:
        return ok("un preset à cloner", False, "presets/ est vide")
    doc = json.load(open(os.path.join(ROOT, "presets", src)))
    doc["id"], doc["name"] = WITNESS, "ZZ restore witness"
    call("/api/preset", doc)
    _, bk = call("/api/backup", {"kind": "presets"})
    name = bk.get("file")
    CREATED.append(name)
    if not ok("sauvegarde construite", bool(name), name or json.dumps(bk)[:80]):
        return False
    call(f"/api/preset/{WITNESS}", method="DELETE")
    gone = not os.path.exists(os.path.join(ROOT, "presets", f"{WITNESS}.json"))
    ok("témoin supprimé", gone)
    _, plan = call("/api/import/inspect-local", {"file": name})
    if not ok("analyse à blanc", bool(plan.get("token")), plan.get("error") or ""):
        return False
    _, res = call("/api/import/apply", {"token": plan["token"], "strategy": "skip"})
    ok("appliquée", bool(res.get("ok")), "pré-import : " + str(res.get("preimport") or "—"))
    back = os.path.exists(os.path.join(ROOT, "presets", f"{WITNESS}.json"))
    good = ok("LE TÉMOIN EST REVENU", back)
    # ménage : le témoin, la sauvegarde de test et son pré-import
    call(f"/api/preset/{WITNESS}", method="DELETE")
    for f in (name, (res.get("preimport") or "")):
        p = os.path.join(ROOT, "backups", os.path.basename(f))
        if f and os.path.exists(p):
            os.remove(p)
    return good


def vault_cycle(kind):
    """Pousser prouve peu. Effacer, puis tirer, et comparer les octets : ça, ça prouve."""
    print("Cycle VAULT (golem.fm)")
    _, stt = call("/api/golemfm/status", method="GET")
    if not stt.get("authed"):
        return ok("rack appairé", False, json.dumps(stt)[:80])
    _, bk = call("/api/backup", {"kind": kind})
    name = bk.get("file")
    CREATED.append(name)
    local = os.path.join(ROOT, "backups", name or "")
    if not ok(f"sauvegarde « {kind} »", bool(name) and os.path.exists(local), name or ""):
        return False
    want = sha(local)
    # ⚠ `POST /api/backup` POUSSE DÉJÀ tout seul quand l'auto-push est actif (Settings ▸
    # Content) : repousser derrière renvoie « push already in progress » et ressemble à une
    # panne. On ne pousse à la main que si personne ne l'a fait.
    if bk.get("auto_push"):
        ok("push automatique déclenché par la sauvegarde", True)
    else:
        code, r = call(f"/api/backup/push/{name}")
        if not ok("push accepté", code == 200, json.dumps(r)[:80]):
            return False
    st = {}
    for _ in range(120):
        _, st = call("/api/backup/push/status", method="GET")
        if st.get("state") != "busy":
            break
        time.sleep(1)
    if not ok("push terminé", st.get("state") == "done", st.get("error") or ""):
        return False
    os.remove(local)                                   # LE point du test : plus rien en local
    sys.path.insert(0, ROOT)
    from bridge import golemfm
    lst = golemfm.list_remote()
    mine = next((b for b in (lst.get("backups") or []) if b.get("filename") == name), None)
    if not ok("présente dans le vault", bool(mine),
              f"{len(lst.get('backups') or [])} sauvegardes · "
              f"{round((lst.get('bytes') or 0) / 1e6, 1)} Mo utilisés"):
        return False
    code, r = call("/api/backup/pull", {"id": mine["id"]})
    ok("pull", code == 200, json.dumps(r, ensure_ascii=False)[:80])
    got = os.path.exists(local) and sha(local) == want
    good = ok("OCTET POUR OCTET IDENTIQUE", got, want[:24])
    # ménage COMPLET : local ET vault. Sans le second, chaque passage de ce script laisserait
    # une sauvegarde dans le coffre — un outil de vérification ne doit pas grossir ce qu'il
    # vérifie. (`DELETE /api/ext/backups/{id}` existait côté serveur ; le rack ne s'en servait
    # pas, donc rien de poussé n'était jamais repris.)
    if os.path.exists(local):
        os.remove(local)
    return good


def purge_remote():
    """Retire du vault tout ce que ce script y a fait monter. (`DELETE /api/ext/backups/{id}`
    existait côté serveur ; le rack ne s'en servait pas — donc rien de poussé n'était jamais
    repris, et le coffre ne pouvait que grossir.)"""
    sys.path.insert(0, ROOT)
    from bridge import golemfm
    n = 0
    for b in (golemfm.list_remote().get("backups") or []):
        if b.get("filename") in CREATED:
            code, _ = call(f"/api/backup/remote/{b['id']}", method="DELETE")
            n += code == 200
    if n:
        print(f"  · {n} sauvegarde(s) de test retirée(s) du vault")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="banks", help="catégorie poussée au vault (petite de préférence)")
    ap.add_argument("--local", action="store_true", help="sauter le vault (rack hors ligne)")
    a = ap.parse_args()
    try:
        urllib.request.urlopen(BRIDGE + "/api/state", timeout=5)
    except Exception:
        sys.exit("Le bridge ne répond pas — démarre GoleM d'abord.")
    good = local_cycle()
    if not a.local:
        print()
        good = vault_cycle(a.kind) and good
        purge_remote()
    print()
    print("  → une réinstallation est SÛRE : ce qui est parti revient à l'identique." if good
          else "  → NE PAS RÉINSTALLER tant que ça n'est pas vert.")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())

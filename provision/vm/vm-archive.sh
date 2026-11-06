#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Archiver / restaurer une VM de test (golem-vm, golem-win) hors de la machine — un disque externe par exemple.
#   ./provision/vm/vm-archive.sh export <vm> <dossier>   # la VM est ÉTEINTE proprement, puis copiée
#   ./provision/vm/vm-archive.sh import <dossier>/<vm>   # recrée la VM telle quelle (volumes, définition, snapshots)
# On ARCHIVE, on ne fait pas tourner depuis le disque externe : libvirt (démon système) n'a pas accès à /media/<user>,
# et un disque de VM sur de l'USB/NTFS serait lent et fragile. La VM tourne dans le pool `default`.
# Ce qui part : chaque volume du pool dont le nom commence par <vm> (disque, base qcow2, ISO de seed/autounattend),
# la définition (dumpxml), les snapshots (leurs XML ; leur contenu — disque + RAM — vit DANS le qcow2), le fichier
# d'identifiants ~/.cache/golem-vm/<vm>.credentials, et un MANIFEST avec les tailles et sha256.
# Une VM UEFI (golem-win) a aussi deux états HORS du pool, propriété de root : ses variables de firmware
# (/var/lib/libvirt/qemu/nvram/<vm>_VARS.fd : Secure Boot, entrées d'amorçage) et son TPM émulé
# (/var/lib/libvirt/swtpm/<uuid>/). Ils partent dans firmware/ (MANIFEST.firmware), lus et réécrits par
# le démon libvirt lui-même via un pool TRANSITOIRE posé sur leur dossier — toujours sans sudo.
set -euo pipefail
export LIBVIRT_DEFAULT_URI="${LIBVIRT_DEFAULT_URI:-qemu:///system}"
POOL=default
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/golem-vm"
die() { echo "✗ $*" >&2; exit 1; }
# un dossier de root vu par le démon libvirt : pool transitoire (rien de persistant), puis retiré
TMP_POOL=golem-archive-tmp
tmp_pool_on() {   # <dossier> [--build]
  virsh pool-destroy "$TMP_POOL" >/dev/null 2>&1 || true
  virsh pool-create-as "$TMP_POOL" dir --target "$1" ${2:-} >/dev/null
}
tmp_pool_off() { virsh pool-destroy "$TMP_POOL" >/dev/null 2>&1 || true; }
# les dossiers d'état hors pool d'une définition : « nvram <dossier> <fichier> » / « tpm <dossier> »
fw_dirs_of() {   # <domain.xml>
  python3 -I - "$1" <<'PY'
import os, sys, xml.etree.ElementTree as ET
d = ET.parse(sys.argv[1]).getroot()
nv = d.find("os/nvram")
if nv is not None and (nv.text or "").strip():
    p = nv.text.strip()
    print("nvram", os.path.dirname(p), os.path.basename(p))
for t in d.findall("devices/tpm"):
    b = t.find("backend")
    if b is not None and b.get("type") == "emulator":
        sub = "tpm2" if b.get("version", "2.0").startswith("2") else "tpm1.2"
        print("tpm", "/var/lib/libvirt/swtpm/%s/%s" % (d.findtext("uuid"), sub))
PY
}

vols_of() { virsh vol-list "$POOL" | awk 'NR>2 && $1!="" {print $1}' | grep -E "^$1([-.]|$)" || true; }

case "${1:-}" in
  export)
    VM="${2:-}"; DEST="${3:-}"
    [ -n "$VM" ] && [ -n "$DEST" ] || die "usage: $0 export <vm> <dossier>"
    virsh dominfo "$VM" >/dev/null 2>&1 || die "VM « $VM » inconnue"
    OUT="$DEST/$VM"; mkdir -p "$OUT/volumes" "$OUT/snapshots"
    if [ "$(virsh domstate "$VM")" != "shut off" ]; then
      echo "→ arrêt propre de $VM…"; virsh shutdown "$VM" >/dev/null
      for _ in $(seq 1 120); do [ "$(virsh domstate "$VM")" = "shut off" ] && break; sleep 2; done
      [ "$(virsh domstate "$VM")" = "shut off" ] || die "$VM ne s'est pas arrêtée en 4 min (virsh destroy à la main si elle est figée)"
    fi
    virsh dumpxml --inactive --security-info "$VM" > "$OUT/domain.xml"
    for s in $(virsh snapshot-list "$VM" --name --topological 2>/dev/null); do
      virsh snapshot-dumpxml "$VM" "$s" --security-info > "$OUT/snapshots/$s.xml"
    done
    virsh snapshot-current "$VM" --name > "$OUT/snapshots/.current" 2>/dev/null || true
    : > "$OUT/MANIFEST"
    # libvirt ne connaît pas d'office les couches que créent ses instantanés externes et ses retours en arrière : sans
    # relecture du dossier, le disque ACTIF et les couches des instantanés récents manquaient à l'archive (2026-10-16)
    virsh pool-refresh "$POOL" >/dev/null
    for v in $(vols_of "$VM"); do
      echo "→ volume $v…"
      virsh vol-download --pool "$POOL" "$v" "$OUT/volumes/$v.part" --sparse 2>/dev/null \
        || virsh vol-download --pool "$POOL" "$v" "$OUT/volumes/$v.part" \
        || die "volume $v : copie impossible — archive INCOMPLÈTE, rien n'est remplacé ni supprimé"
      mv "$OUT/volumes/$v.part" "$OUT/volumes/$v"
      echo "$(sha256sum "$OUT/volumes/$v" | cut -d' ' -f1)  $(stat -c%s "$OUT/volumes/$v")  $v" >> "$OUT/MANIFEST"
    done
    # firmware UEFI + TPM : hors du pool, lus par le démon (pool transitoire sur leur dossier)
    rm -rf "$OUT/firmware" "$OUT/NOTE"; : > "$OUT/MANIFEST.firmware"
    trap tmp_pool_off EXIT
    while read -r -u 3 kind dir file; do
      mkdir -p "$OUT/firmware/$kind"
      if ! tmp_pool_on "$dir" 2>/dev/null; then
        echo "⚠ $kind : $dir illisible — non archivé (voir NOTE)"; echo "$kind absent : $dir" >> "$OUT/NOTE"; continue
      fi
      files="$file"; [ "$kind" = tpm ] && files=$(virsh vol-list "$TMP_POOL" | awk 'NR>2 && $1!="" && $1 !~ /\.lock$/ {print $1}')
      for f in $files; do
        echo "→ $kind $f…"
        virsh vol-download --pool "$TMP_POOL" "$f" "$OUT/firmware/$kind/$f"
        echo "$(sha256sum "$OUT/firmware/$kind/$f" | cut -d' ' -f1)  $(stat -c%s "$OUT/firmware/$kind/$f")  $kind/$f  $dir" >> "$OUT/MANIFEST.firmware"
      done
      tmp_pool_off
    done 3< <(fw_dirs_of "$OUT/domain.xml")
    trap - EXIT
    [ -s "$OUT/MANIFEST.firmware" ] || rm -rf "$OUT/MANIFEST.firmware" "$OUT/firmware"
    {
      echo "$VM — archivée le $(date -Iseconds) depuis $(hostname) par provision/vm/vm-archive.sh"
      echo "Restaurer : provision/vm/vm-archive.sh import <ce dossier> (vérifie MANIFEST et MANIFEST.firmware)."
      echo "volumes/ : les volumes du pool « $POOL » (disque, calques des snapshots, ISO) ; domain.xml ; snapshots/."
      if [ -f "$OUT/MANIFEST.firmware" ]; then
        echo "firmware/ : variables UEFI (nvram) et/ou état du TPM émulé, réécrits à leur place par import."
        echo "Sans eux, libvirt recrée des variables vierges (Secure Boot gardé : clés du modèle) et un TPM neuf ;"
        echo "Windows démarre tant que BitLocker est coupé (manage-bde -status C:)."
      fi
    } >> "$OUT/NOTE"
    [ -f "$CACHE/$VM.credentials" ] && install -m 600 "$CACHE/$VM.credentials" "$OUT/credentials"
    # chaque fichier que la définition ou un instantané référence doit être dans l'archive
    for f in $(grep -ho "<source file='[^']*'" "$OUT/domain.xml" "$OUT"/snapshots/*.xml 2>/dev/null | sed "s/<source file='//; s/'$//" | sort -u); do
      case "$f" in *.iso) continue ;; esac
      [ -f "$OUT/volumes/$(basename "$f")" ] || die "$(basename "$f") est référencé par la VM mais absent de l'archive"
    done
    date -Iseconds > "$OUT/EXPORTED_AT"
    echo "✓ $VM archivée dans $OUT ($(du -sh "$OUT" | cut -f1)) — la VM est éteinte : $(dirname "$0")/vm.sh start pour la relancer"
    ;;

  import)
    SRC="${2:-}"; [ -d "$SRC/volumes" ] && [ -f "$SRC/domain.xml" ] || die "usage: $0 import <dossier>/<vm>"
    VM="$(basename "$SRC")"
    virsh dominfo "$VM" >/dev/null 2>&1 && die "la VM « $VM » existe déjà ici (destroy d'abord)"
    echo "→ vérification des volumes…"
    while read -r sum size name; do
      [ "$(sha256sum "$SRC/volumes/$name" | cut -d' ' -f1)" = "$sum" ] || die "$name : empreinte différente, archive abîmée"
    done < "$SRC/MANIFEST"
    # la BASE d'abord : le disque de travail est un qcow2 qui s'appuie dessus
    order="$(awk '{print $3}' "$SRC/MANIFEST" | grep -- '-base' || true) $(awk '{print $3}' "$SRC/MANIFEST" | grep -v -- '-base' || true)"
    for name in $order; do
      size=$(awk -v n="$name" '$3==n {print $2}' "$SRC/MANIFEST")
      fmt=raw; case "$name" in *.qcow2) fmt=qcow2 ;; esac
      echo "→ volume $name…"
      virsh vol-create-as "$POOL" "$name" "$size" --format "$fmt" >/dev/null
      virsh vol-upload --pool "$POOL" "$name" "$SRC/volumes/$name" --sparse 2>/dev/null \
        || virsh vol-upload --pool "$POOL" "$name" "$SRC/volumes/$name"
    done
    virsh pool-refresh "$POOL" >/dev/null
    # firmware UEFI + TPM AVANT la définition : sans eux libvirt repartirait d'un modèle vierge (le
    # TPM est alors neuf : Windows démarre si BitLocker est coupé, ce que win/autounattend.xml impose)
    if [ -f "$SRC/MANIFEST.firmware" ]; then
      while read -r sum size rel dir; do
        [ "$(sha256sum "$SRC/firmware/$rel" | cut -d' ' -f1)" = "$sum" ] || die "$rel : empreinte différente, archive abîmée"
      done < "$SRC/MANIFEST.firmware"
      trap tmp_pool_off EXIT
      while read -r -u 3 sum size rel dir; do
        echo "→ $rel → $dir"
        tmp_pool_on "$dir" --build      # le dossier du TPM n'existe pas encore sur un hôte neuf
        f="$(basename "$rel")"
        virsh vol-delete --pool "$TMP_POOL" "$f" >/dev/null 2>&1 || true
        virsh vol-create-as "$TMP_POOL" "$f" "$size" --format raw >/dev/null
        virsh vol-upload --pool "$TMP_POOL" "$f" "$SRC/firmware/$rel"
        tmp_pool_off                    # propriétaires : libvirt les remet (qemu, swtpm) au démarrage
      done 3< "$SRC/MANIFEST.firmware"
      trap - EXIT
    fi
    virsh define "$SRC/domain.xml" >/dev/null
    # PARENT AVANT ENFANT : libvirt refuse un snapshot dont le parent n'existe pas encore. L'ordre alphabétique des
    # fichiers ne le garantit pas — import du 2026-10-24 : « parent src-ready-win2 for moment installed-win not found »,
    # un seul snapshot recréé, et le `restore` suivant a fait tomber le démon libvirt (core dump). Ordre topologique
    # lu dans les XML (<parent><name>), un chemin avec espace compris (« HD Save » — import cassé le 2026-10-16).
    python3 - "$SRC/snapshots" <<'PYTOPO' | while IFS= read -r -d '' f; do
import glob, os, re, sys
d = sys.argv[1]
snaps = {}
for f in glob.glob(os.path.join(d, "*.xml")):
    x = open(f, encoding="utf-8").read()
    m = re.search(r"<parent>\s*<name>([^<]+)</name>", x)
    snaps[os.path.basename(f)[:-4]] = (f, m.group(1) if m else None)
done = set()
while len(done) < len(snaps):
    ready = sorted(n for n, (_f, par) in snaps.items() if n not in done and (par is None or par in done or par not in snaps))
    if not ready:                                   # un cycle (impossible en principe) : le reste tel quel
        ready = sorted(set(snaps) - done)
    for n in ready:
        done.add(n)
        sys.stdout.write(snaps[n][0] + "\0")
PYTOPO
      virsh snapshot-create "$VM" "$f" --redefine >/dev/null
    done
    cur="$(cat "$SRC/snapshots/.current" 2>/dev/null || true)"
    [ -n "$cur" ] && virsh snapshot-create "$VM" "$SRC/snapshots/$cur.xml" --redefine --current >/dev/null || true
    if [ -f "$SRC/credentials" ]; then mkdir -p "$CACHE"; install -m 600 "$SRC/credentials" "$CACHE/$VM.credentials"; fi
    echo "✓ $VM restaurée ($(virsh snapshot-list "$VM" --name | grep -c . || true) snapshot(s)) — vm.sh start / restore <snap>"
    ;;

  *) die "usage: $0 export <vm> <dossier> | import <dossier>/<vm>" ;;
esac

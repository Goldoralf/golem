#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# golem — VM de test d'install from-scratch (bloc B1 du plan de consolidation).
#
# Le cycle : snapshot « os-nu » → dérouler l'install → noter ce qui casse →
# restore → recommencer. C'est ce qui rend provision/ testable et rejouable.
#
#   ./provision/vm/vm.sh fetch        # télécharge l'image cloud de la distribution (~600 Mo, une fois)
#   ./provision/vm/vm.sh create       # crée + démarre la VM (cloud-init : compte de test, clé SSH)
#   ./provision/vm/vm.sh snap os-nu   # snapshot (VM à chaud, disque+RAM)
#   ./provision/vm/vm.sh restore os-nu
#   ./provision/vm/vm.sh ip           # IP de la VM (réseau NAT libvirt)
#   ./provision/vm/vm.sh ssh [cmd]    # shell (ou commande) dans la VM
#   ./provision/vm/vm.sh push         # rsync le repo golem → ~/golem dans la VM (sans .venv/assets)
#   ./provision/vm/vm.sh shot         # capture d'écran de la console (PNG) — vérif kiosk headless
#   ./provision/vm/vm.sh status | snaps | stop | start | destroy
#
# Distribution : GOLEM_VM_DISTRO=ubuntu (défaut, VM « golem-vm ») | debian12 | debian13 | mint22 — chaque
# distribution a SA VM (golem-vm-<distro>), on peut les garder côte à côte.
#   mint22 : Linux Mint n'a pas d'image cloud ; la VM est une Ubuntu 24.04 rendue « Mint » là où golem le voit
#            (provision/vm/mintify.sh : dépôt Mint, snapd retiré et bloqué, os-release linuxmint).
#
# Prérequis (une fois) : qemu-kvm libvirt-daemon-system libvirt-clients virtinst
# cloud-image-utils + être dans le groupe libvirt (relog, ou `sg libvirt -c ...`).
#
# Compte de test : GOLEM_VM_USER / GOLEM_VM_PASSWORD / GOLEM_VM_SSH_KEY (voir resolve_creds).
set -euo pipefail

DISTRO="${GOLEM_VM_DISTRO:-ubuntu}"
NOBLE_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
case "$DISTRO" in
  ubuntu)   VM=golem-vm;          IMG_URL="$NOBLE_URL"; OS_VARIANT=ubuntu24.04 ;;
  mint22)   VM=golem-vm-mint22;   IMG_URL="$NOBLE_URL"; OS_VARIANT=ubuntu24.04 ;;
  debian12) VM=golem-vm-debian12; OS_VARIANT=debian12
            IMG_URL="https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2" ;;
  debian13) VM=golem-vm-debian13; OS_VARIANT=debian13
            IMG_URL="https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2" ;;
  *) echo "✗ GOLEM_VM_DISTRO inconnue : $DISTRO (ubuntu | debian12 | debian13 | mint22)" >&2; exit 1 ;;
esac
RAM_MB=8192
VCPUS=6
DISK_GB=40
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/golem-vm"
BASE="$CACHE/$(basename "$IMG_URL")"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
export LIBVIRT_DEFAULT_URI="${LIBVIRT_DEFAULT_URI:-qemu:///system}"

die() { echo "✗ $*" >&2; exit 1; }

# ── Compte de test : rien de personnel dans le dépôt ──────────────────────────────────────
# Les gabarits portent des jetons @GOLEM_VM_…@, remplacés à `create` :
#   GOLEM_VM_USER      nom du compte (défaut « golem »)
#   GOLEM_VM_PASSWORD  mot de passe console (défaut : généré, affiché une fois)
#   GOLEM_VM_SSH_KEY   clé publique (le texte, ou le chemin d'un .pub ; défaut ~/.ssh/id_ed25519.pub)
# Le compte retenu est mémorisé dans $CACHE/<vm>.credentials (0600) : ssh/push/… le relisent,
# sans quoi une VM créée avec un autre nom ne serait plus joignable.
CREDS="$CACHE/$VM.credentials"

vm_user() {
  if [ -n "${GOLEM_VM_USER:-}" ]; then echo "$GOLEM_VM_USER"; return; fi
  if [ -f "$CREDS" ]; then sed -n 's/^user=//p' "$CREDS" | head -n1; return; fi
  echo golem
}

gen_password() {
  # pas de `tr </dev/urandom | head` : sous pipefail, le SIGPIPE de tr ferait échouer le script
  head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-16
}

ssh_pubkey() {
  local k="${GOLEM_VM_SSH_KEY:-$HOME/.ssh/id_ed25519.pub}"
  if [ -f "$k" ]; then head -n1 "$k"; elif [[ "$k" == ssh-* || "$k" == ecdsa-* ]]; then echo "$k"
  else die "pas de clé SSH publique ($k) — GOLEM_VM_SSH_KEY=<fichier .pub ou texte de la clé>"; fi
}

# Résout utilisateur + mot de passe pour une VM neuve, les mémorise, les affiche.
# Sortie : VM_USER, VM_PASSWORD
resolve_creds() {
  VM_USER="${GOLEM_VM_USER:-golem}"
  [[ "$VM_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "GOLEM_VM_USER invalide : $VM_USER"
  VM_PASSWORD="${GOLEM_VM_PASSWORD:-$(gen_password)}"
  # le mot de passe atterrit dans du YAML/XML : on refuse ce qu'il faudrait échapper
  [[ "$VM_PASSWORD" =~ ^[^\"\\\<\>\&\']+$ ]] || die "GOLEM_VM_PASSWORD : caractères \" \\ < > & ' refusés"
  mkdir -p "$CACHE"
  (umask 077; printf 'user=%s\npassword=%s\n' "$VM_USER" "$VM_PASSWORD" > "$CREDS")
  echo "→ compte de test : $VM_USER / $VM_PASSWORD   (mémorisé dans $CREDS)"
}

# gabarit → fichier, jetons remplacés (remplacement entre guillemets : « & » n'y est pas spécial)
render_template() {
  local src="$1" dst="$2" key="${3:-}" s
  s=$(<"$src")
  s=${s//@GOLEM_VM_USER@/"$VM_USER"}
  s=${s//@GOLEM_VM_PASSWORD@/"$VM_PASSWORD"}
  s=${s//@GOLEM_VM_SSH_KEY@/"$key"}
  printf '%s\n' "$s" > "$dst"
}

vm_ip() {
  # IP via le guest-agent (fiable) puis fallback lease DHCP
  virsh domifaddr "$VM" --source agent 2>/dev/null | awk '/ipv4/ && $4 !~ /^127\./ {sub(/\/.*/,"",$4); print $4; exit}' \
    || true
}

wait_ip() {
  local ip="" i
  for i in $(seq 1 60); do
    ip=$(vm_ip)
    [ -n "$ip" ] && { echo "$ip"; return 0; }
    sleep 2
  done
  die "pas d'IP après 120 s (virsh console $VM pour debug — login : $CREDS)"
}

# la base osinfo de l'hôte peut ne pas connaître une distribution récente (debian13) : virt-install refuse alors
# un --os-variant inconnu. Repli générique, sans conséquence pour une VM de test.
os_variant() {
  if command -v osinfo-query >/dev/null 2>&1 && ! osinfo-query os "short-id=$OS_VARIANT" 2>/dev/null | grep -q "$OS_VARIANT"; then
    echo linux2022
  else
    echo "$OS_VARIANT"
  fi
}

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

case "${1:-}" in
  fetch)
    mkdir -p "$CACHE"
    if [ -f "$BASE" ]; then echo "→ image déjà là : $BASE"; else
      echo "→ téléchargement $IMG_URL"
      curl -fL --progress-bar -o "$BASE.part" "$IMG_URL" && mv "$BASE.part" "$BASE"
    fi
    qemu-img info "$BASE" | head -3
    ;;

  create)
    # Tout passe par le démon libvirt (vol-create/vol-upload) → AUCUN sudo requis,
    # il suffit d'être dans le groupe libvirt.
    [ -f "$BASE" ] || die "image absente — lance d'abord: $0 fetch"
    virsh dominfo "$VM" >/dev/null 2>&1 && die "la VM existe déjà ($0 destroy pour repartir)"
    KEY=$(ssh_pubkey)                  # avant tout volume : une clé absente ne laisse rien derrière
    resolve_creds

    # 1) image de base dans le pool (une fois)
    if ! virsh vol-info --pool default "$VM-base.qcow2" >/dev/null 2>&1; then
      BASE_BYTES=$(stat -c%s "$BASE")
      virsh vol-create-as default "$VM-base.qcow2" "$BASE_BYTES" --format qcow2 >/dev/null
      echo "→ upload de l'image de base dans le pool libvirt…"
      virsh vol-upload --pool default "$VM-base.qcow2" "$BASE"
      virsh pool-refresh default >/dev/null
    fi

    # 2) disque de travail = overlay qcow2 sur la base
    virsh vol-create-as default "$VM.qcow2" "${DISK_GB}G" --format qcow2 \
      --backing-vol "$VM-base.qcow2" --backing-vol-format qcow2 >/dev/null

    # 3) seed cloud-init (compte de test + clé SSH, jetons du gabarit remplacés)
    SEED_CFG=$(mktemp)
    render_template "$HERE/cloud-init.yaml" "$SEED_CFG" "$KEY"
    cloud-localds "/tmp/$VM-seed.iso" "$SEED_CFG"
    rm -f "$SEED_CFG"
    SEED_BYTES=$(stat -c%s "/tmp/$VM-seed.iso")
    virsh vol-delete --pool default "$VM-seed.iso" >/dev/null 2>&1 || true
    virsh vol-create-as default "$VM-seed.iso" "$SEED_BYTES" --format raw >/dev/null
    virsh vol-upload --pool default "$VM-seed.iso" "/tmp/$VM-seed.iso"
    rm -f "/tmp/$VM-seed.iso"

    virt-install --name "$VM" --memory "$RAM_MB" --vcpus "$VCPUS" \
      --disk "vol=default/$VM.qcow2,bus=virtio" \
      --disk "vol=default/$VM-seed.iso,device=cdrom" \
      --os-variant "$(os_variant)" --import --network network=default,model=virtio \
      --graphics spice --video qxl --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
      --noautoconsole
    echo "→ VM démarrée, attente de l'IP (cloud-init fait son premier boot)…"
    IP=$(wait_ip)
    if [ "$DISTRO" = mint22 ]; then
      echo "→ cloud-init, puis la VM devient « Mint » (mintify.sh)…"
      for _ in $(seq 1 60); do ssh "${SSH_OPTS[@]}" -o ConnectTimeout=5 "$VM_USER@$IP" true 2>/dev/null && break; sleep 3; done
      ssh "${SSH_OPTS[@]}" "$VM_USER@$IP" 'cloud-init status --wait >/dev/null; sudo bash -s' < "$HERE/mintify.sh"
    fi
    echo "✓ $VM prête — IP $IP   (GOLEM_VM_DISTRO=$DISTRO $0 ssh pour entrer)"
    ;;

  ip)      vm_ip ;;
  status)  virsh dominfo "$VM" | grep -E 'State|CPU\(s\)|Max memory' ; echo "IP: $(vm_ip)" ;;
  snaps)   virsh snapshot-list "$VM" ;;

  snap)
    [ -n "${2:-}" ] || die "usage: $0 snap <nom>"
    virsh snapshot-create-as "$VM" "$2" --atomic
    echo "✓ snapshot « $2 » (disque+RAM, VM à chaud)"
    ;;

  restore)
    [ -n "${2:-}" ] || die "usage: $0 restore <nom>"
    virsh snapshot-revert "$VM" "$2" --running
    echo "✓ retour à « $2 » — IP: $(wait_ip)"
    ;;

  ssh)
    IP=$(vm_ip); [ -n "$IP" ] || IP=$(wait_ip)
    shift
    exec ssh "${SSH_OPTS[@]}" "$(vm_user)@$IP" "$@"
    ;;

  push)
    IP=$(vm_ip); [ -n "$IP" ] || IP=$(wait_ip)
    # Exclusions = ce qu'un git clone ne donnerait PAS : blobs téléchargeables
    # (assets NAM/IR, library/sfz) + secrets + artefacts locaux. Le reste de
    # library/ (catalogues JSON, .syx, .vital) est versionné → poussé.
    # ⚠ ON HONORE .gitignore. Sans ce filtre, rsync poussait AUSSI l'état local — config/
    # soundcard.json, .band.json, .mode.json, integrations.json (des clés !), auth-devices.json,
    # presets/.sandbox.json… La VM héritait donc exactement des mois d'état non documenté qu'elle
    # est censée révéler : le test ne pouvait pas répondre à sa propre question, et il expédiait
    # des secrets au passage. Avec `:- .gitignore`, ce qui part = ce qu'un `git clone` donnerait.
    # ⚠ `!.env.example` ne suffit PAS : dans un fichier de filtres rsync, « ! » n'est pas une
    # négation (c'est un ordre de vider la liste). Le gabarit doit donc être ré-inclus ICI, et
    # AVANT le filtre — rsync applique la première règle qui matche. Sans lui, `install.sh` ne
    # peut pas créer `.env` sur une machine neuve (trouvé le 2026-08-02, VM nue).
    rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
      --include='.env.example' \
      --filter=':- .gitignore' \
      --exclude .git --exclude .venv --exclude node_modules \
      --exclude 'assets/' --exclude 'library/sfz/' --exclude recordings \
      --exclude .env --exclude '__pycache__' \
      "$REPO/" "$(vm_user)@$IP:golem/"
    echo "✓ repo poussé → $(vm_user)@$IP:~/golem (assets + library/sfz exclus — fetch-assets les télécharge)"
    ;;

  shot)
    OUT="${2:-/tmp/$VM-screen.png}"
    virsh screenshot "$VM" "$OUT" >/dev/null
    echo "$OUT"
    ;;

  stop)    virsh shutdown "$VM" ;;
  start)   virsh start "$VM" && wait_ip ;;

  destroy)
    virsh destroy "$VM" 2>/dev/null || true
    virsh undefine "$VM" --snapshots-metadata --remove-all-storage
    rm -f "$CREDS"
    echo "✓ VM supprimée"
    ;;

  *)
    grep '^#   ' "$0" | sed 's/^#   //'
    ;;
esac

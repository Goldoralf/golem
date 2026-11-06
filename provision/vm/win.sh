#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# golem — VM WINDOWS 11 de test (portage desktop, docs/platforms.md).
#
# Le pendant de vm.sh : une vraie machine Windows (KVM, pas wine), installée SANS CLIC, pilotée
# en SSH depuis l'hôte, et qu'on remet à zéro à volonté.
#
#   ./provision/vm/win.sh fetch          # ISO Windows 11 Enterprise d'évaluation (8 Go, une fois) + OpenSSH
#   ./provision/vm/win.sh create         # crée la VM et déroule l'installation (~20-30 min, sans clic)
#   ./provision/vm/win.sh wait           # attend que la VM soit pilotable (SSH + C:\golem-ready.txt)
#   ./provision/vm/win.sh tools          # Python 3.12, REAPER 7.80, NAM VST3 0.7.13, ffmpeg, Node — puis redémarre
#   ./provision/vm/win.sh ssh [cmd]      # shell cmd.exe (ou commande) dans la VM
#   ./provision/vm/win.sh ps '<script>'  # une ligne PowerShell dans la VM
#   ./provision/vm/win.sh gui '<cmd>'    # lance <cmd> DANS LA SESSION GRAPHIQUE (Reaper, navigateur)
#   ./provision/vm/win.sh dialog [proc] [bouton]  # boîtes de dialogue d'un processus ; clique un bouton
#   ./provision/vm/win.sh push [ref]     # dépôt → C:\golem (arbre de travail, ou un commit/branche)
#   ./provision/vm/win.sh shot [png]     # capture d'écran de la console
#   ./provision/vm/win.sh view           # ouvre la console (virt-viewer) — pour un humain
#   ./provision/vm/win.sh snap <nom>     # fige l'état du disque (VM ÉTEINTE par la commande)
#   ./provision/vm/win.sh restore <nom>  # revient à cet état, redémarre
#   ./provision/vm/win.sh usb <vid:pid> [off]   # prête un appareil USB de l'hôte à la VM (carte son, clavier)
#   ./provision/vm/win.sh status | snaps | ip | stop | start | destroy
#
# Prérequis : les mêmes que vm.sh + swtpm (TPM émulé) + genisoimage. Aucun sudo : tout passe par
# le démon libvirt system, groupe `libvirt`.
#
# Compte de test : GOLEM_VM_USER / GOLEM_VM_PASSWORD / GOLEM_VM_SSH_KEY (voir resolve_creds).
# Hôte serré : GOLEM_VM_RAM_MB (8192) / GOLEM_VM_VCPUS (6) ; GOLEM_VM_ISO_DIR (~/.cache/golem-vm) range
# l'ISO ailleurs, GOLEM_VM_ISO_HTTP=1 la sert à QEMU en HTTP au lieu de la copier dans le pool (8 Go de moins sur /).
#
# ⚠ Ce que cette VM NE dit PAS : la latence, les décrochages, un gel du moteur à l'activation
# d'un bloc, le son à l'oreille. Elle valide le logiciel (lanceur, bridge, IPC, Reaper, plugins,
# rappel d'un preset, rendu hors ligne) ; le temps réel se mesure sur un Windows sans hyperviseur.
set -euo pipefail

VM=golem-win
RAM_MB="${GOLEM_VM_RAM_MB:-8192}"     # hôte serré (un rack qui joue, une autre VM) : GOLEM_VM_RAM_MB=6144
VCPUS="${GOLEM_VM_VCPUS:-6}"
DISK_GB=80                              # Windows 11 en demande 64 ; le qcow2 n'alloue que l'utilisé
WIN_URL="https://go.microsoft.com/fwlink/?LinkId=2382600&clcid=0x409&culture=en-us&country=us"
WIN_ISO_NAME="win11-ent-eval-26h2-x64-en-us.iso"
SSH_MSI_URL="https://github.com/PowerShell/Win32-OpenSSH/releases/download/10.0.0.0p2-Preview/OpenSSH-Win64-v10.0.0.0.msi"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/golem-vm"
# où vivent l'ISO (8 Go) et l'OpenSSH : un disque externe si / est juste (GOLEM_VM_ISO_DIR=/media/…/iso)
ISO_DIR="${GOLEM_VM_ISO_DIR:-$CACHE}"
WIN_ISO="$ISO_DIR/$WIN_ISO_NAME"
SSH_MSI="$ISO_DIR/$(basename "$SSH_MSI_URL")"
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
  # pas d'agent invité : l'adresse vient du bail DHCP du réseau NAT de libvirt
  virsh domifaddr "$VM" --source lease 2>/dev/null \
    | awk '/ipv4/ {sub(/\/.*/,"",$4); print $4; exit}' || true
}

wait_ip() {
  local ip="" i
  for i in $(seq 1 90); do
    ip=$(vm_ip)
    [ -n "$ip" ] && { echo "$ip"; return 0; }
    sleep 2
  done
  die "pas d'IP après 180 s ($0 shot pour voir l'écran)"
}

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
          -o ConnectTimeout=5 -o BatchMode=yes)

win_ssh() { local ip; ip=$(vm_ip); [ -n "$ip" ] || ip=$(wait_ip); ssh "${SSH_OPTS[@]}" "$(vm_user)@$ip" "$@"; }

# un fichier de l'hôte → un volume du pool libvirt (aucun sudo : c'est le démon qui écrit)
upload_vol() {
  local name="$1" src="$2"
  virsh vol-delete --pool default "$name" >/dev/null 2>&1 || true
  virsh vol-create-as default "$name" "$(stat -c%s "$src")" --format raw >/dev/null
  virsh vol-upload --pool default "$name" "$src"
}

# le serveur HTTP de l'ISO (GOLEM_VM_ISO_HTTP=1) : son PID, le port qu'il a choisi
ISO_PID="$CACHE/$VM-iso-http.pid"
ISO_PORT="$CACHE/$VM-iso-http.port"
iso_http_stop() {
  local pid
  pid=$(cat "$ISO_PID" 2>/dev/null || true)
  # on ne tue que NOTRE serveur : le PID doit encore porter iso-http.py (un PID se recycle)
  if [ -n "$pid" ] && grep -q iso-http.py "/proc/$pid/cmdline" 2>/dev/null; then kill "$pid" || true; fi
  rm -f "$ISO_PID" "$ISO_PORT"
}

vm_off() {
  [ "$(virsh domstate "$VM" 2>/dev/null)" = "shut off" ] && return 0
  virsh shutdown "$VM" >/dev/null
  local i
  for i in $(seq 1 60); do
    [ "$(virsh domstate "$VM")" = "shut off" ] && return 0
    sleep 2
  done
  die "la VM ne s'éteint pas (120 s) — $0 shot pour voir ce qu'elle attend"
}

case "${1:-}" in
  fetch)
    mkdir -p "$ISO_DIR"
    if [ -f "$WIN_ISO" ]; then echo "→ ISO déjà là : $WIN_ISO"; else
      echo "→ téléchargement de l'ISO Windows 11 Enterprise (évaluation 90 jours, ~8 Go)"
      curl -fL -C - --retry 5 --progress-bar -A "Mozilla/5.0" -o "$WIN_ISO.part" "$WIN_URL" \
        && mv "$WIN_ISO.part" "$WIN_ISO"
    fi
    if [ -f "$SSH_MSI" ]; then echo "→ OpenSSH déjà là : $SSH_MSI"; else
      curl -fL --retry 5 -sS -o "$SSH_MSI.part" "$SSH_MSI_URL" && mv "$SSH_MSI.part" "$SSH_MSI"
    fi
    ls -lh "$WIN_ISO" "$SSH_MSI"
    ;;

  create)
    [ -f "$WIN_ISO" ] && [ -f "$SSH_MSI" ] || die "ISO ou OpenSSH absent — lance d'abord : $0 fetch"
    virsh dominfo "$VM" >/dev/null 2>&1 && die "la VM existe déjà ($0 destroy pour repartir)"
    KEY=$(ssh_pubkey)
    resolve_creds

    # 1) l'ISO de réponse : autounattend.xml à la racine + de quoi rendre la machine pilotable
    STAGE=$(mktemp -d)
    trap 'rm -rf "$STAGE"' EXIT
    mkdir -p "$STAGE/root/golem"
    render_template "$HERE/win/autounattend.xml" "$STAGE/root/autounattend.xml"
    cp "$HERE/win/firstlogon.ps1" "$SSH_MSI" "$STAGE/root/golem/"
    printf '%s\n' "$KEY" > "$STAGE/root/golem/authorized_keys"
    # on grave le DOSSIER : passer les chemins un par un aplatit golem/ à la racine de l'ISO
    genisoimage -quiet -J -joliet-long -r -V GOLEMWIN -o "$STAGE/unattend.iso" "$STAGE/root"
    upload_vol "$VM-unattend.iso" "$STAGE/unattend.iso"

    # 2) l'ISO Windows : copiée dans le pool (une fois : 8 Go), OU servie en HTTP depuis là où
    #    elle est (GOLEM_VM_ISO_HTTP=1) quand / n'a pas la place — le pilote curl de QEMU la lit
    #    par morceaux sur 127.0.0.1, `wait` arrête le serveur à la fin de l'installation.
    if [ "${GOLEM_VM_ISO_HTTP:-0}" = 1 ]; then
      iso_http_stop
      rm -f "$ISO_PORT"
      setsid nohup python3 -I "$HERE/iso-http.py" "$WIN_ISO" "$ISO_PORT" >/dev/null 2>&1 < /dev/null &
      echo $! > "$ISO_PID"
      for _ in $(seq 1 50); do [ -s "$ISO_PORT" ] && break; sleep 0.2; done
      [ -s "$ISO_PORT" ] || die "le serveur HTTP de l'ISO n'a pas démarré"
      echo "→ ISO servie en HTTP : http://127.0.0.1:$(cat "$ISO_PORT")/$WIN_ISO_NAME (rien dans le pool)"
      DVD="device=cdrom,bus=sata,boot.order=2,type=network,driver.type=raw,source.protocol=http"
      DVD+=",source.name=/$WIN_ISO_NAME,source.host0.name=127.0.0.1,source.host0.port=$(cat "$ISO_PORT")"
    else
      if ! virsh vol-info --pool default "$WIN_ISO_NAME" >/dev/null 2>&1; then
        echo "→ upload de l'ISO Windows dans le pool libvirt…"
        upload_vol "$WIN_ISO_NAME" "$WIN_ISO"
      fi
      DVD="vol=default/$WIN_ISO_NAME,device=cdrom,bus=sata,boot.order=2"
    fi

    # 3) le disque
    virsh vol-create-as default "$VM.qcow2" "${DISK_GB}G" --format qcow2 >/dev/null

    # SATA + e1000e : pilotes fournis par Windows (voir autounattend.xml). `--osinfo win11` pose
    # UEFI + Secure Boot ; le TPM 2.0 est émulé par swtpm. Le disque est PREMIER à l'amorçage :
    # vide au premier boot, le firmware retombe sur le DVD ; installé, il ne le regarde plus.
    virt-install --name "$VM" --memory "$RAM_MB" --vcpus "$VCPUS" --cpu host-passthrough \
      --osinfo win11 --boot uefi \
      --disk "vol=default/$VM.qcow2,bus=sata,boot.order=1" \
      --disk "$DVD" \
      --disk "vol=default/$VM-unattend.iso,device=cdrom,bus=sata" \
      --network network=default,model=e1000e \
      --tpm backend.type=emulator,backend.version=2.0,model=tpm-crb \
      --graphics spice --video vga --sound ich9 \
      --import --noautoconsole

    # « Press any key to boot from CD or DVD… » : personne n'est devant, et sans touche le
    # firmware abandonne le DVD. On appuie pour lui pendant les 40 premières secondes.
    # ⚠ PAS Entrée ni Espace : l'écran « Installing Windows 11 » arrive avec son bouton Cancel
    # EN FOCUS (vu à la première installation, 2026-10-01) — une touche qui valide annulerait
    # l'installation qu'elle vient de démarrer. X ne valide rien.
    for _ in $(seq 1 40); do virsh send-key "$VM" KEY_X >/dev/null 2>&1 || true; sleep 1; done
    echo "→ installation lancée (20-30 min, sans clic). Suivre : $0 shot · $0 view"
    echo "  puis : $0 wait"
    ;;

  wait)
    # prête = firstlogon.ps1 est allé AU BOUT (le port 22 s'ouvre avant la fin du script)
    echo "→ attente de la VM (IP, SSH, C:\\golem-ready.txt)…"
    for _ in $(seq 1 "${2:-240}"); do
      ip=$(vm_ip)
      if [ -n "$ip" ] && ssh "${SSH_OPTS[@]}" "$(vm_user)@$ip" 'if exist C:\golem-ready.txt echo PRET' 2>/dev/null | grep -q PRET; then
        # l'installation est finie : les deux DVD ne servent plus, et un snapshot les embarquerait
        for t in $(virsh domblklist "$VM" --details | awk '$2 == "cdrom" {print $3}'); do
          # éjecter À CHAUD (un DVD SATA ne se débranche pas VM allumée), retirer de la définition
          virsh change-media "$VM" "$t" --eject --live >/dev/null 2>&1 || true
          virsh detach-disk "$VM" "$t" --config >/dev/null 2>&1 || true
        done
        iso_http_stop
        # …et leurs 8 Go quittent le pool (l'ISO reste dans $ISO_DIR : `create` la re-téléverse)
        virsh vol-delete --pool default "$WIN_ISO_NAME" >/dev/null 2>&1 || true
        virsh vol-delete --pool default "$VM-unattend.iso" >/dev/null 2>&1 || true
        echo "✓ $VM prête — IP $ip"; exit 0
      fi
      sleep 10
    done
    die "VM pas prête — $0 shot pour voir où en est l'installation"
    ;;

  ip)      vm_ip ;;
  status)  virsh dominfo "$VM" | grep -E 'State|CPU\(s\)|Max memory' ; echo "IP: $(vm_ip)" ;;
  snaps)   virsh snapshot-list "$VM" --parent ;;

  ssh)     shift; win_ssh "$@" ;;

  ps)
    # -EncodedCommand : le script traverse ssh ET cmd.exe sans qu'aucun des deux ne touche aux guillemets
    [ -n "${2:-}" ] || die "usage: $0 ps '<script PowerShell>'"
    enc=$(printf '%s' "\$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; $2" | iconv -t UTF-16LE | base64 -w0)
    win_ssh "powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $enc"
    ;;

  gui)
    # Une session SSH n'a PAS de bureau : Reaper lancé depuis SSH n'a ni fenêtre ni console
    # audio, et `shot` ne le voit pas. La commande est donc posée dans un fichier, puis exécutée
    # par une tâche planifiée « interactive » — dans la session ouverte par l'AutoLogon.
    [ -n "${2:-}" ] || die "usage: $0 gui '<commande>'"
    # Un fichier et une tâche PAR APPEL : cmd.exe lit un .cmd au fil de l'eau, donc réécrire
    # celui d'une commande encore en cours (le lanceur, qui ne rend pas la main) lui ferait
    # exécuter n'importe quoi à son retour — et une tâche déjà active ne se relance pas.
    id="golem-gui-$(date +%s%N | cut -c1-16)"
    printf '@echo off\r\nif exist C:\\golem cd /d C:\\golem\r\n%s\r\n' "$2" | win_ssh "more > C:\\$id.cmd"
    win_ssh "schtasks /create /tn $id /tr C:\\$id.cmd /sc once /st 00:00 /it /rl highest /f >nul 2>&1 & schtasks /run /tn $id >nul & echo $id"
    ;;

  dialog)
    # Les boîtes de dialogue d'un processus (REAPER par défaut), et de quoi cliquer un bouton :
    #   win.sh dialog                 -> les liste, avec leur texte
    #   win.sh dialog reaper '&No'    -> clique « No » (le & est le raccourci clavier du bouton)
    ip=$(vm_ip); [ -n "$ip" ] || ip=$(wait_ip)
    scp "${SSH_OPTS[@]}" -q "$HERE/win/dialog.ps1" "$(vm_user)@$ip:C:/golem-dialog.ps1"
    win_ssh 'del C:\golem-dialog.txt 2>nul' || true
    "$0" gui "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\golem-dialog.ps1 -Process ${2:-reaper} -Button \"${3:-}\"" >/dev/null
    for _ in $(seq 1 20); do
      win_ssh 'if exist C:\golem-dialog.txt echo OK' 2>/dev/null | grep -q OK && break; sleep 1
    done
    "$0" ps 'Get-Content C:\golem-dialog.txt -Encoding UTF8'
    ;;

  push)
    # Ce qui part = ce qu'un `git clone` donnerait (même règle que vm.sh push : jamais l'état
    # local ni les secrets). Sans argument : l'arbre de travail, suivi + non suivi non ignoré.
    # Avec une ref (commit, branche) : exactement ce commit. GOLEM_PUSH_REPO désigne un autre
    # clone — pour pousser la tête d'une PR sans la faire entrer dans ce dépôt.
    SRC="${GOLEM_PUSH_REPO:-$REPO}"
    win_ssh 'if exist C:\golem rmdir /s /q C:\golem' || true
    # ⚠ un GoleM qui tourne dans la VM verrouille ses fichiers : rmdir en laisse une partie SANS
    # erreur, et l'archive partait sur un dossier à moitié vidé (vécu le 2026-10-01 : venv détruit)
    if win_ssh 'if exist C:\golem (echo RESTE)' | grep -q RESTE; then
      echo "✗ C:\golem est encore là (fichiers verrouillés — GoleM ou REAPER tournent ?) : arrêter-les, puis relancer push" >&2
      exit 1
    fi
    win_ssh 'mkdir C:\golem'
    if [ -n "${2:-}" ]; then
      git -C "$SRC" archive --format=tar "$2" | win_ssh 'tar -xf - -C C:\golem'
      echo "✓ $2 ($(git -C "$SRC" rev-parse --short "$2")) → C:\\golem"
    else
      (cd "$SRC" && git ls-files -co --exclude-standard -z \
         | tar --null -T - --ignore-failed-read -cf -) | win_ssh 'tar -xf - -C C:\golem'
      echo "✓ arbre de travail → C:\\golem"
    fi
    ;;

  tools)
    # Python 3.12, REAPER, NAM VST3, ffmpeg (provision/vm/win/tools.ps1), puis un redémarrage :
    # le service sshd ne voit le nouveau PATH qu'après.
    ip=$(vm_ip); [ -n "$ip" ] || ip=$(wait_ip)
    scp "${SSH_OPTS[@]}" -q "$HERE/win/tools.ps1" "$(vm_user)@$ip:C:/golem-tools.ps1"
    win_ssh 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\golem-tools.ps1'
    win_ssh 'shutdown /r /t 0' || true
    sleep 20
    "$0" wait 60
    ;;

  shot)
    OUT="${2:-/tmp/$VM-screen.png}"
    virsh screenshot "$VM" "$OUT" >/dev/null
    echo "$OUT"
    ;;

  view)    exec virt-viewer -c "$LIBVIRT_DEFAULT_URI" "$VM" ;;

  snap)
    # libvirt 10.0 ne sait pas faire de snapshot À CHAUD d'une VM UEFI (firmware pflash) : on
    # éteint, et on fige le DISQUE. L'état courant devient une couche en lecture seule, la VM
    # continue sur un calque neuf.
    [ -n "${2:-}" ] || die "usage: $0 snap <nom>"
    vm_off
    # seulement le DISQUE : sans --diskspec, libvirt pose aussi un calque sur chaque DVD attaché
    virsh snapshot-create-as "$VM" "$2" --disk-only --atomic --diskspec sda,snapshot=external >/dev/null
    echo "✓ snapshot « $2 » (disque, VM éteinte) — $0 start pour reprendre"
    ;;

  restore)
    [ -n "${2:-}" ] || die "usage: $0 restore <nom>"
    virsh destroy "$VM" >/dev/null 2>&1 || true        # on jette l'état courant : pas d'arrêt propre à attendre
    virsh snapshot-revert "$VM" "$2"
    virsh start "$VM" >/dev/null
    echo "✓ retour à « $2 » — IP: $(wait_ip)"
    ;;

  usb)
    # Prête un appareil USB de l'hôte à la VM (ex. la carte son : 2b5a:0023). ⚠ L'hôte le PERD
    # tant qu'il est prêté — un Reaper qui tenait cette carte devient muet sans le dire
    # (CLAUDE.md : « Reaper ne sait pas dire que sa carte son a disparu »).
    [[ "${2:-}" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$ ]] || die "usage: $0 usb <vid:pid> [off]"
    XML=$(mktemp)
    printf "<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x%s'/><product id='0x%s'/></source></hostdev>\n" \
      "${2%%:*}" "${2##*:}" > "$XML"
    if [ "${3:-}" = off ]; then virsh detach-device "$VM" "$XML" --live && echo "✓ $2 rendu à l'hôte"
    else virsh attach-device "$VM" "$XML" --live && echo "✓ $2 prêté à la VM"; fi
    rm -f "$XML"
    ;;

  stop)    vm_off && echo "✓ VM éteinte" ;;
  start)   virsh start "$VM" && wait_ip ;;

  destroy)
    virsh destroy "$VM" 2>/dev/null || true
    # --nvram : une VM UEFI a un fichier de variables ; --tpm : et l'état de son TPM émulé
    virsh undefine "$VM" --snapshots-metadata --nvram --tpm
    # --remove-all-storage ne retire que le calque du HAUT : chaque snap et chaque restore en
    # laissent un dessous (chaîne mesurée le 2026-10-01 : 5 fichiers). On retire toute la chaîne.
    virsh pool-refresh default >/dev/null
    for v in $(virsh vol-list default | awk -v p="$VM" '$1 ~ "^" p "[.-]" {print $1}'); do
      virsh vol-delete --pool default "$v" >/dev/null
    done
    iso_http_stop
    rm -f "$CREDS"
    echo "✓ VM supprimée (l'ISO Windows reste dans $ISO_DIR)"
    ;;

  *)
    grep '^#   ' "$0" | sed 's/^#   //'
    ;;
esac

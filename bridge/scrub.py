# SPDX-License-Identifier: GPL-3.0-or-later
"""LE SCRUBBER des rapports (docs/diagnostics.md §3, §7.1) — bibliothèque standard SEULEMENT.

Sorti de bridge/diag.py le 2026-10-27 (lot D1) : l'installateur l'utilise aussi, chargé par son chemin (le bridge ne
tourne pas pendant une installation), comme il charge déjà bridge/reaper_license.py. Ce module ne sait RIEN du rack :
les listes à effacer (personnes, presets, chansons) lui sont DONNÉES — diag.Scrubber les lit sur le rack, l'installateur
y met ce qu'on a tapé pendant l'installation."""
import getpass
import hashlib
import os
import re
import socket

# audit 2026-11-04 (H2) : le jeton d'appareil (`secrets.token_urlsafe(32)`, 43 caractères base64url) voyage en `?token=`
# sur le WebSocket et uvicorn journalise ce chemin — `token=…` et toute suite base64url de 40+ caractères s'effacent
RX_TOKEN = re.compile(r"(gmt_[A-Za-z0-9_\-]+|Bearer\s+\S+|\b[0-9a-fA-F]{32,}\b|t3k_[A-Za-z0-9_\-]+"
                      r"|token=[A-Za-z0-9_\-%]{20,}|\b[A-Za-z0-9_\-]{40,}\b)")
RX_IP = re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|127\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
RX_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
# le dossier personnel sous les trois systèmes : /home/x (Linux), /Users/x (macOS), C:\Users\x (Windows, les deux barres)
RX_HOME = re.compile(r"/home/[^/\s\"']+|/Users/[^/\s\"']+|[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.IGNORECASE)
# UN .golem NE MÈNE À PERSONNE (song-sharing.md §2.8, 2026-10-11) : un rapport monte chez golem.fm ; un id de chanson
# (`bs:2`, `rs:<hex>`, ou sa forme de fichier `rs-<hex>.golem`) y relierait ce compte à une chanson et à une date —
# exactement le lien que golem.fm s'interdit de garder. Effacé AVANT `RX_TOKEN` (sinon « rs:<token> » reste lisible).
RX_SONG_ID = re.compile(r"(?<![\w:-])(?:bs|rs|us|ct)[:-][A-Za-z0-9_-]+")


def _song_id_sub(m):
    """`bs:2` → `<song-id>` ; mais `us-east-1`, `rs-232` ne sont pas des ids : une forme fichier (`-`) n'est effacée
    que si elle a la longueur d'un id tiré au hasard."""
    t = m.group(0)
    if t[2] == "-" and len(t) < 3 + 8:
        return t
    return "<song-id>"


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def norm(items):
    """≥ 3 caractères : « Ju » effacerait « juillet » ; un prénom de deux lettres reste un risque accepté et documenté
    (docs/diagnostics.md §2.5). Les plus LONGS d'abord."""
    return sorted({s.strip() for s in items or () if isinstance(s, str) and len(s.strip()) >= 3},
                  key=len, reverse=True)


class Scrubber:
    """Efface d'une chaîne ce qu'on sait devoir effacer. `known` = [(libellés, remplaçant)…] dans l'ordre de priorité ;
    `secrets` = des valeurs exactes (une clé tapée) remplacées par <secret> AVANT tout le reste ; `roots` = des dossiers
    remplacés par `~` (le dossier installé, le dossier personnel)."""

    def __init__(self, known=(), secrets=(), roots=()):
        self.user = _safe(getpass.getuser) or ""
        self.host = _safe(socket.gethostname) or ""
        self.home = os.path.expanduser("~")
        self.roots = [r for r in roots if r and len(r) > 1]
        self.secrets = sorted({s for s in secrets if isinstance(s, str) and len(s) >= 4}, key=len, reverse=True)
        # UNE regex, les libellés les plus LONGS d'abord : « Set Léa » doit devenir <preset> avant
        # que « Léa » ne le transforme en « Set <name> » (mesuré au test PII, 2026-09-13)
        self._ph = {}
        for items, ph in known:
            for it in norm(items):
                self._ph.setdefault(it.lower(), ph)
        self._rx_known = self._rx(sorted(self._ph, key=len, reverse=True))

    @staticmethod
    def _rx(items):
        """Frontières de mot OBLIGATOIRES : un libellé « Lea » (setlist de ce rack) effaçait le
        cœur de « unclean » → « unc<name>n » (attrapé par les tests le 2026-09-13). Un nom se
        remplace entier, jamais au milieu d'un mot."""
        if not items:
            return None
        return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(s) for s in items) + r")(?!\w)", re.IGNORECASE)

    def __call__(self, s):
        if not isinstance(s, str) or not s:
            return s
        for sec in self.secrets:
            if sec in s:
                s = s.replace(sec, "<secret>")
        for r in self.roots:
            if r in s:
                s = s.replace(r, "~")
        if self.home and self.home in s:
            s = s.replace(self.home, "~")
        s = RX_HOME.sub("~", s)
        s = RX_SONG_ID.sub(_song_id_sub, s)
        s = RX_TOKEN.sub("<token>", s)
        s = RX_IP.sub("<ip>", s)
        s = RX_MAC.sub("<mac>", s)
        if self.host and len(self.host) >= 3:
            s = re.sub(re.escape(self.host), "<host>", s, flags=re.IGNORECASE)
        if self.user and len(self.user) >= 3:
            s = re.sub(r"\b" + re.escape(self.user) + r"\b", "<user>", s, flags=re.IGNORECASE)
        if self._rx_known:
            s = self._rx_known.sub(lambda m: self._ph.get(m.group(0).lower(), "<name>"), s)
        return s

    def deep(self, v):
        """Scrubbe toutes les chaînes d'une structure (dicts, listes), clés comprises."""
        if isinstance(v, str):
            return self(v)
        if isinstance(v, dict):
            return {self(k) if isinstance(k, str) else k: self.deep(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.deep(x) for x in v]
        return v


# ── la signature d'une erreur (docs/diagnostics.md §7.3) ─────────────────────────────────────────────────────────
def normalize(line):
    """La forme normalisée d'une ligne d'erreur (docs/diagnostics.md §7.3, la MÊME règle pour le rack et l'installateur) : nombres → #, hexas et ids → *, chemins → leur nom de fichier,
    le texte entre guillemets retiré. Deux machines qui butent sur la même erreur donnent la même forme."""
    s = str(line or "").strip()
    s = re.sub(r"^\d\d:\d\d:\d\d\s+\[[^\]]*\]\s*", "", s)                 # l'horodatage et l'étape de la trace
    s = re.sub(r"\"[^\"]*\"|'[^']*'|«[^»]*»|“[^”]*”", "\"\"", s)
    s = re.sub(r"(?:[A-Za-z]:|~)?(?:[\\/][^\\/\s\"':]+)+", lambda m: re.split(r"[\\/]", m.group(0))[-1], s)
    s = re.sub(r"\b0x[0-9a-fA-F]+\b", "*", s)
    s = re.sub(r"\b[0-9a-fA-F]{8,}\b|\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b", "*", s)
    s = re.sub(r"\d+", "#", s)
    return re.sub(r"\s+", " ", s)[:200]


def sig(sig_src):
    return hashlib.sha256(sig_src.encode("utf-8")).hexdigest()[:12]

# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration UNIQUE du logging du bridge (audit 2026-08-12, prérequis lot 8).

Pourquoi ce module :
- le bridge tourne sous systemd : journald horodate déjà chaque ligne de stdout, et en dev
  uvicorn préfixe aussi — donc PAS d'asctime dans le format, on ne double pas l'horodatage ;
- un seul point de configuration : chaque module fait `from .golog import get` puis
  `log = get("<tag>")` — le tag reprend l'ancien préfixe entre crochets des print()
  (`[foot]` → logger `golem.foot`), le format l'affiche à sa place, sans double préfixe ;
- niveau INFO par défaut, DEBUG si la variable d'environnement GOLEM_DEBUG=1 ;
- AUCUN import de bridge ici (stdlib seulement) : config.py et store.py sont importés très
  tôt et ce module ne doit pas créer de cycle d'import.
"""
import logging
import os
import sys

_FORMAT = "%(name)s %(levelname).1s %(message)s"
_configured = False


def _configure():
    """Pose le handler sur le logger racine `golem` — une seule fois. Sortie = stdout
    (le flux historique des print, celui que journald et uvicorn affichent)."""
    global _configured
    if _configured:
        return
    root = logging.getLogger("golem")
    root.setLevel(logging.DEBUG if os.environ.get("GOLEM_DEBUG") == "1" else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.addHandler(_DiagHandler())     # lot 8 : chaque ERROR/EXCEPTION du bridge = un événement
    root.propagate = False      # ne pas remonter au root logger (double ligne sous uvicorn)
    _configured = True


def _exc_sig_src(name, exc_info):
    """La forme d'une exception pour sa signature (docs/diagnostics.md §7.3) : le logger, le TYPE de l'exception et la
    frame la plus profonde du bridge en `module:fonction` — ni le message (il porte des valeurs), ni un numéro de ligne
    (il bouge à chaque version, la signature doit survivre à un commit voisin)."""
    import traceback
    where = ""
    for fr in traceback.extract_tb(exc_info[2]):
        parts = fr.filename.replace("\\", "/").split("/")
        if "bridge" in parts:
            where = f"{parts[-1].rsplit('.', 1)[0]}:{fr.name}"
    return f"{name}|{type(exc_info[1]).__name__}|{where or '?'}"


class _DiagHandler(logging.Handler):
    """ERROR et au-dessus → `diag.trigger("error", …)` : l'événement entre dans la chronologie, et
    une TRACE (exc_info) déclenche un paquet `event` (docs/diagnostics.md §4.3). Import paresseux
    (ce module ne doit rien importer du bridge), garde anti-réentrance, jamais d'exception ici."""
    _busy = False

    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record):
        if _DiagHandler._busy or record.name.startswith("golem.diag"):
            return
        _DiagHandler._busy = True
        try:
            from . import diag
            msg = record.getMessage()
            name = record.name.replace("golem.", "", 1)
            if record.exc_info and record.exc_info[1] is not None:
                msg = f"{msg} — {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
                diag.trigger("error", logger=name, msg=msg, sig_src=_exc_sig_src(name, record.exc_info))
            else:
                diag.event("error", logger=name, msg=msg, sig_src=f"{name}: {msg}")
        except Exception:
            pass
        finally:
            _DiagHandler._busy = False


def get(name):
    """Rend le logger `golem.<name>` — <name> = l'ancien tag entre crochets des print()."""
    _configure()
    return logging.getLogger(f"golem.{name}")


_silent = None


def swallowed(e, note=None):
    """Un `except Exception: pass` qui laisse une TRACE (audit 2026-09-13, M5). Les cinq silences
    de la semaine avaient tous cette forme : l'exception est attendue, le geste peut continuer, mais
    personne ne sait qu'elle a eu lieu. Ici : niveau debug, logger `golem.silent`, adresse du site
    (fichier:ligne:fonction) lue sur la pile — grep-able, sans bruit en INFO."""
    global _silent
    if _silent is None:
        _silent = get("silent")
    if _silent.isEnabledFor(logging.DEBUG):
        f = sys._getframe(1)
        where = f"{os.path.basename(f.f_code.co_filename)}:{f.f_lineno}:{f.f_code.co_name}"
        _silent.debug(f"{where}{' ' + note if note else ''}: {e!r}")

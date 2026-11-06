# SPDX-License-Identifier: GPL-3.0-or-later
"""Les PHASES de l'écran d'installation et l'estimateur de temps (docs/installer.md §2, « Install »).

Une étape (source, system, profile, start…) est ce que le serveur lance ; une PHASE est ce que l'utilisateur lit :
« System packages », « Plugins built for golem »… — une étape en contient zéro, une ou plusieurs. Le module
de plateforme les déclare (P.PHASES) ; le script les annonce par des lignes-marqueurs, que le serveur retire du
journal affiché (2026-10-23 : l'écran montrait la trace brute du shell — les warnings de compilation font paniquer) :

    @@phase <id> [texte de sous-ligne]     passe à la phase <id> (les précédentes de la même étape sont finies)
    @@sub <texte>                          la sous-ligne de la phase en cours (« Prisma ✓ · PaulXStretch — 3 of 6 »)
    @@warn <retry-id>|<texte>              un manque NON fatal, dit sur la phase en cours ; retry-id vide = pas de ↻
    @@est-add <secondes>                   la phase en cours s'allonge d'autant (un plugin à compiler faute de binaire)
    @@progress <fait> <total>              l'avancement MESURÉ de la phase (Mo téléchargés) : son temps restant vient
                                           alors du débit observé, plus de la durée prévue (les sons, VM 2026-10-23 :
                                           31 min prévues à 1,85 Mo/s, 11 réelles à ~5 Mo/s — le réseau varie du simple
                                           au triple d'un jour à l'autre)

Une étape sans marqueur ouvre sa première phase dès qu'elle démarre. Une plateforme sans PHASES (Windows et macOS
aujourd'hui) a une phase par étape, sans estimation : l'écran montre alors le temps écoulé, pas un décompte.

L'ESTIMATION : chaque phase a sa durée mesurée (VM Ubuntu 24.04, 6 cœurs, 2026-10-23 — install complète 28 min) ;
l'estimateur la corrige par la VITESSE observée sur les phases finies (réel / prévu), bornée, et seulement quand
assez de prévu est passé pour qu'elle veuille dire quelque chose. La phase en cours compte pour ce qui lui reste,
jamais moins que quelques secondes : un décompte qui dit « 0 » pendant que la phase tourne encore ment.
"""
import time

MIN_LEARN_S = 90          # sous ce prévu cumulé, la vitesse observée est du bruit : on garde 1
SPEED_BOUNDS = (0.5, 3.0)
FLOOR_S = 10              # ce qu'il reste au moins à une phase qui tourne encore
PROGRESS_MIN_S = 15       # le débit mesuré ne remplace l'estimation qu'après ce temps de mesure…
PROGRESS_MIN = 0.03       # … et cette part de la phase faite


class Tracker:
    """L'état des phases, nourri par le serveur (début/fin d'étape, marqueurs). Pas de verrou : l'appelant tient le
    sien (server.LOCK). `now` injectable pour les tests."""

    def __init__(self, phases, steps, now=time.time):
        """phases : [{"id", "label", "step", "est"}] dans l'ordre ; vide → une phase par étape (steps)."""
        self.now = now
        if not phases:
            phases = [{"id": sid, "label": label, "step": sid, "est": None} for sid, label in steps]
        # learn=False : une phase qui dépend du RÉSEAU (apt, sons) n'apprend rien sur la vitesse de calcul de la machine,
        # et ne se règle pas sur elle (VM 2026-10-23 : un apt lent à 220 s gonflait la compilation de 30 %)
        self.ph = [{"id": p["id"], "label": p["label"], "step": p["step"], "est": p.get("est"), "learn": p.get("learn", True),
                    "state": "pending", "secs": None, "t0": None, "sub": "", "warns": [], "skipped": False,
                    "prog": None} for p in phases]
        self.t_start = None
        self.t_end = None

    # ── ce que le serveur appelle ─────────────────────────────────────────────────────────────────────────────
    def reset_unfinished(self):
        """Retry : ce qui n'a pas fini repart de zéro ; ce qui est fini le reste (ses avertissements aussi)."""
        for p in self.ph:
            if p["state"] not in ("ok", "warn"):
                p.update(state="pending", secs=None, t0=None, sub="", skipped=False, prog=None)
        self.t_end = None

    def step_started(self, sid):
        if self.t_start is None:
            self.t_start = self.now()
        mine = [p for p in self.ph if p["step"] == sid]
        if mine and not any(p["state"] == "running" for p in mine):
            first = next((p for p in mine if p["state"] == "pending"), None)
            if first:
                self._open(first)

    def step_ended(self, sid, ok):
        t = self.now()
        for p in self.ph:
            if p["step"] != sid:
                continue
            if p["state"] == "running":
                self._close(p, ok, t)
            elif p["state"] == "pending" and ok:
                # une phase sautée (déjà installé, pack non choisi) : finie, sans durée
                p.update(state="warn" if p["warns"] else "ok", secs=0, skipped=True)
        if not ok:
            return
        if all(p["state"] in ("ok", "warn") for p in self.ph):
            self.t_end = t

    def marker(self, line, sid):
        """Une ligne du journal : True si c'était un marqueur (le serveur ne l'affiche pas dans la trace)."""
        if not line.startswith("@@"):
            return False
        word, _, rest = line[2:].partition(" ")
        if word == "phase":
            pid, _, sub = rest.strip().partition(" ")
            self._switch(pid, sid, sub.strip())
        elif word == "sub":
            p = self.current()
            if p:
                p["sub"] = rest.strip()
        elif word == "est-add":
            # une compilation imprévue (précompilé indisponible) allonge la phase en cours de sa durée mesurée
            p = self.current()
            try:
                p and p.update(est=(p["est"] or 0) + float(rest.split()[0]))
            except (ValueError, IndexError):
                pass
        elif word == "progress":
            p = self.current()
            try:
                done, total = (float(x) for x in rest.split()[:2])
            except ValueError:
                return True
            if p and total > 0:
                first = p["prog"] or {"d0": done, "t0": self.now()}
                p["prog"] = {**first, "done": min(done, total), "total": total}
        elif word == "warn":
            retry, _, text = rest.partition("|")
            p = self.current() or next((x for x in reversed(self.ph) if x["step"] == sid), None)
            if p and text.strip():
                p["warns"].append({"text": text.strip(), "retry": retry.strip() or None})
        else:
            return False
        return True

    def warn_resolved(self, retry):
        """Un ↻ Try again réussi : l'avertissement disparaît ; la phase redevient ✓ s'il n'en reste aucun."""
        for p in self.ph:
            left = [w for w in p["warns"] if w["retry"] != retry]
            if len(left) != len(p["warns"]):
                p["warns"] = left
                if p["state"] == "warn" and not left:
                    p["state"] = "ok"

    # ── ce que l'écran lit ────────────────────────────────────────────────────────────────────────────────────
    def current(self):
        return next((p for p in self.ph if p["state"] == "running"), None)

    def speed(self):
        """réel / prévu sur les phases finies avec une estimation ; 1 tant qu'il n'y en a pas assez."""
        done = [p for p in self.ph if p["state"] in ("ok", "warn") and p["est"] and p["secs"] and p["learn"]]
        est = sum(p["est"] for p in done)
        real = sum(p["secs"] for p in done)
        if est < MIN_LEARN_S:
            return 1.0
        lo, hi = SPEED_BOUNDS
        return max(lo, min(hi, real / est))

    def public(self):
        t = self.now()
        k_cpu = self.speed()
        known = all(p["est"] is not None for p in self.ph)
        left = 0.0
        done_est = total_est = 0.0
        out = []
        for p in self.ph:
            q = {key: p[key] for key in ("id", "label", "state", "secs", "sub", "warns", "skipped")}
            if p["prog"]:
                q["progress"] = {"done": p["prog"]["done"], "total": p["prog"]["total"]}
            est = p["est"]
            k = k_cpu if p["learn"] else 1.0
            if p["state"] == "running":
                q["elapsed"] = round(t - p["t0"])
                measured = self._measured_left(p, t)
                if measured is not None:
                    q["left"] = round(max(FLOOR_S, measured))
                    left += q["left"]
                    total_est += est or 0
                    done_est += (est or 0) * p["prog"]["done"] / p["prog"]["total"]
                elif est is not None:
                    q["left"] = round(max(FLOOR_S, est * k - q["elapsed"]))
                    left += q["left"]
                    total_est += est
                    done_est += max(0.0, est - q["left"] / k)
            elif p["state"] == "pending":
                if est is not None:
                    q["est"] = round(est * k)
                    left += est * k
                    total_est += est
            elif est is not None:
                total_est += est
                done_est += est
            out.append(q)
        return {"phases": out,
                "started": self.t_start, "elapsed": round((self.t_end or t) - self.t_start) if self.t_start else None,
                "left": round(left) if known and self.t_start and not self.t_end else None,
                "progress": round(done_est / total_est, 3) if known and total_est else None,
                "total_est": round(sum(p["est"] * (k_cpu if p["learn"] else 1.0) for p in self.ph)) if known else None,
                "finished": self.t_end is not None}

    def _measured_left(self, p, t):
        """Le temps restant d'après l'avancement mesuré (@@progress), ou None tant qu'il ne dit rien de sûr."""
        g = p["prog"]
        if not g:
            return None
        dt, dd = t - g["t0"], g["done"] - g["d0"]
        if dt < PROGRESS_MIN_S or dd <= 0 or g["done"] / g["total"] < PROGRESS_MIN:
            return None
        return (g["total"] - g["done"]) / (dd / dt)

    # ── interne ───────────────────────────────────────────────────────────────────────────────────────────────
    def _open(self, p):
        p.update(state="running", t0=self.now(), secs=None, sub="", prog=None)

    def _close(self, p, ok, t):
        p["secs"] = round(t - (p["t0"] or t))
        p["state"] = ("warn" if p["warns"] else "ok") if ok else "fail"

    def _switch(self, pid, sid, sub):
        target = next((p for p in self.ph if p["id"] == pid), None)
        if target is None:
            return
        t = self.now()
        # les phases de la même étape AVANT la cible sont finies (en cours : fermée ; jamais ouverte : sautée)
        for p in self.ph:
            if p is target:
                break
            if p["step"] == target["step"]:
                if p["state"] == "running":
                    self._close(p, True, t)
                elif p["state"] == "pending":
                    p.update(state="warn" if p["warns"] else "ok", secs=0, skipped=True)
        if target["state"] != "running":
            self._open(target)
        target["sub"] = sub

# SPDX-License-Identifier: GPL-3.0-or-later
"""Uplink « tab follow » — BIDIRECTIONNEL depuis la v2.1.

MONTANT : pousse la position de lecture des backing tracks vers golem.fm
(la tablature défile sur le laptop en phase avec ce que joue le rack).
DESCENDANT : reçoit les commandes du laptop relayées par le serveur
({type:"cmd", cmd: seek|play|pause|toggle|loop, …}) et les applique via le
BackingControl — cliquer une mesure sur la tab = seek du rack, espace =
play/pause, boucle A/B = travail d'un passage.

Le rack est TOUJOURS client sortant (une page HTTPS ne peut pas ouvrir ws://
vers le rack — mixed content) ; le même socket porte les deux sens.

Connexion : ws(s)://<golemfm>/api/ext/golem/link, Bearer = jeton d'appareil
(scope follow:push), reconnexion à backoff (1→10 s), jeton relu à chaque
tentative ET pendant la connexion (changement de serveur/ré-appairage à chaud
= bascule en ≤5 s). Frames montantes {type:"pos", slug, playing, posMs, seq} :
~4,5 Hz en lecture (position EXTRAPOLÉE — le serveur reçoit du frais),
transition immédiate, silencieux à l'arrêt.
"""
import asyncio, json, time

from .golog import get
from .state import state

log = get("follow")

PUSH_EVERY_S = 0.22          # ~4,5 Hz en lecture
PUSH_KARAOKE_S = 0.1         # 10 Hz pendant un karaoké (le mainteneur, docs/karaoke.md §7) : les paroles suivent
IDLE_POLL_S = 0.2            # détection de transition à l'arrêt
RECONNECT_MAX_S = 10
LINK_HELD_S = 10        # un lien qui a tenu ça est un VRAI lien : le backoff repart de 1 s
# UN LIEN PAR GOLEM (golem.fm routes/follow.py golem_link, 2026-11-03) : le serveur range les liens par jeton d'appareil.
# 4409 « replaced by another connection of this golem » = le MÊME golem connecté deux fois (deux bridges qui partagent un
# jeton) : se reconnecter vite relancerait le ping-pong entre les deux — on le DIT (LINKED.why) et on réessaie lentement.
# (Avant ce déploiement, la prod gardait UN lien par COMPTE et fermait l'ancien en 1000 nu : le backoff ci-dessous.)
UPLINK_REPLACED = 4409
REPLACED_RETRY_S = 90

_backing_ctl = None          # BackingControl, injecté par app.py (commandes descendantes)
LINKED = {"ok": False, "t": None, "why": None}   # le lien est-il ouvert ? (bridge/boot_progress.py : écran de chargement ET pastille golem.fm de Settings)


def init(ctl):
    global _backing_ctl
    _backing_ctl = ctl


def _ws_url(base):
    if base.startswith("https://"):
        return "wss://" + base[8:] + "/api/ext/golem/link"
    if base.startswith("http://"):
        return "ws://" + base[7:] + "/api/ext/golem/link"
    return None


def _frame(seq):
    """Photo de l'état backing, position extrapolée si en lecture."""
    b = state.backing
    pos = float(b.get("pos") or 0.0)
    if b.get("playing") and b.get("t"):
        pos += max(0.0, time.time() - b["t"])
    # le SLUG golem.fm, jamais l'id d'une chanson .golem (lot 1.5) : la page de golem.fm suit par slug
    from . import golemfm
    out = {"type": "pos", "slug": golemfm.golemfm_slug(b.get("slug")), "playing": bool(b.get("playing")),
           "posMs": round(pos * 1000, 1), "seq": seq}
    # KARAOKÉ (docs/karaoke.md §2.2) : la trame dit QUOI joue — src, id, et le mix quand il change
    try:
        from . import karaoke
        out.update(karaoke.pos_fields(b.get("slug")))
    except Exception:
        pass
    # LE COMPTE D'UNE PRISE DE RIFF (docs/compo.md §12) : dit par le rack, au temps du fichier — la page
    # affiche ce chiffre, elle ne tient jamais sa propre horloge
    try:
        from . import compo
        rf = compo.riff_frame()
        if rf:
            out["compo"] = rf
        # AVANT LE TAP (§12 ter) : l'état du bed de chaque cible armée qui en porte un — « Other layers: ready »
        armed = compo.armed_frames()
        if armed:
            out["compo_armed"] = armed
    except Exception:
        pass
    return out


def _apply_cmd(msg):
    """Commande descendante (laptop -> rack). Best-effort : ctl absent = ignoré."""
    # COMPO (docs/compo.md §10) : « Follow Golem » arme le rack sur un morceau — par personne, en
    # mémoire, AVANT la garde du transport : cette commande ne dépend pas d'un backing chargé.
    from . import compo
    if compo.apply_cmd(msg):
        return
    # KARAOKÉ (docs/karaoke.md) : load / mix / stop / prefetch — un worker, le WS ne bloque jamais
    # le relais des paroles (lot 9) : `{"type":"cmd","cmd":"lyrics-get",…}`, comme toute commande du navigateur
    if msg.get("cmd") == "lyrics-get":
        from . import karaoke
        karaoke.lyrics_get(msg)
        return
    if str(msg.get("cmd") or "").startswith("karaoke-"):
        from . import karaoke
        if karaoke.handle(msg):
            log.info(f"cmd golem.fm: {msg.get('cmd')}")
        return
    ctl = _backing_ctl
    if ctl is None:
        return
    cmd = msg.get("cmd")
    # RIEN DE CHARGÉ, RIEN À JOUER (2026-10-06) : après un karaoke-stop, un `play` seul démarrait le
    # transport de Reaper à vide — rien ne sonnait, et le lecteur de golem.fm croyait la chanson partie
    if cmd in ("play", "toggle", "seek") and not (state.backing or {}).get("present"):
        log.info(f"cmd laptop ignorée : {cmd} (aucun backing chargé)")
        return
    if cmd == "seek" and msg.get("posMs") is not None:
        ctl.seek(float(msg["posMs"]) / 1000.0)
    elif cmd == "play":
        ctl.play()
    elif cmd == "pause":
        ctl.pause()
    elif cmd == "toggle":
        ctl.toggle()
    elif cmd == "loop":
        if msg.get("on") and msg.get("aMs") is not None and msg.get("bMs") is not None:
            ctl.loop(float(msg["aMs"]) / 1000.0, float(msg["bMs"]) / 1000.0)
        else:
            ctl.loop_off()
    log.info(f"cmd laptop: {cmd}")


async def _sender(ws, base, token, golemfm):
    """Boucle montante. Sort (return) si la config change — le caller reconnecte."""
    seq = 0
    last_sent = 0.0
    last_sig = None
    last_cfg_check = time.time()
    while True:
        if time.time() - last_cfg_check >= 5:
            last_cfg_check = time.time()
            if golemfm._cfg() != (base, token):
                log.info("config golem.fm changée — reconnexion")
                return
        b = state.backing
        playing = bool(b.get("playing"))
        from . import compo as _compo
        _rf = _compo.riff_frame()
        sig = (b.get("slug"), playing, bool(b.get("paused")),
               round(float(b.get("pos") or 0), 1), json.dumps(_rf, sort_keys=True) if _rf else None,
               json.dumps(_compo.armed_frames()))
        now = time.time()
        # les réponses et événements du karaoké (ready, fetching, ended, left…) : tels quels, dans l'ordre
        from . import karaoke as _karaoke
        for frame in _karaoke.drain():
            await ws.send(json.dumps(frame))
        every = PUSH_KARAOKE_S if _karaoke.active() else PUSH_EVERY_S
        if sig != last_sig or (playing and now - last_sent >= every):
            seq += 1
            await ws.send(json.dumps(_frame(seq)))
            last_sent = now
            last_sig = sig
        await asyncio.sleep(IDLE_POLL_S if not playing else 0.05)


async def _receiver(ws):
    """Boucle descendante : commandes du laptop."""
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if isinstance(msg, dict) and msg.get("type") == "cmd":
            _apply_cmd(msg)



async def run():
    """Tâche de fond (lancée par app._startup). Ne meurt jamais : dort si pas
    appairé, se reconnecte en backoff sinon."""
    import websockets
    from . import golemfm
    backoff = 1
    while True:
        base, token = golemfm._cfg()
        url = _ws_url(base) if base else None
        if not url or not token:
            await asyncio.sleep(10)          # pas configuré/appairé : on repassera
            continue
        opened = None
        try:
            async with websockets.connect(
                url, additional_headers={"Authorization": "Bearer " + token},
                open_timeout=8, ping_interval=20, ping_timeout=10,
            ) as ws:
                opened = time.time()
                if backoff == 1:             # en boucle de rejets, une ligne par tentative noyait le journal (1 220 en 5 min)
                    log.info("uplink connecté -> %s" % (url,))
                LINKED.update(ok=True, t=opened, why=None)
                state.touch()                    # la pastille golem.fm (Settings) suit le lien, pas seulement le boot
                try:                             # la file de soirée : dire où on en est (lot 5 Vocals)
                    from . import karaoke
                    karaoke.on_reconnect()
                except Exception as e:
                    log.warning(f"karaoké à la reconnexion : {e}")
                send_t = asyncio.create_task(_sender(ws, base, token, golemfm))
                recv_t = asyncio.create_task(_receiver(ws))
                # le premier qui sort (config changée / socket fermé) emporte l'autre
                done, pending = await asyncio.wait(
                    {send_t, recv_t}, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                for t in done:
                    exc = t.exception()
                    if exc is not None:
                        raise exc
            LINKED.update(ok=False, t=time.time())   # fermé proprement : le lien est tombé quand même
            state.touch()
            # UNE FERMETURE PROPRE ATTEND AUSSI (2026-11-03) : le serveur fermait chaque lien en 0,13 s (code 1000, sans
            # motif — un autre golem du même compte, la prod gardant alors un lien par compte) et la boucle se reconnectait SANS PAUSE : 1 220 connexions
            # en 5 min, un lien « up » quelques millisecondes, l'écran de chargement qui l'attrapait au vol (79 s).
            # Le backoff ne revient à 1 s qu'après un lien qui a TENU.
            held = time.time() - opened
            if held >= LINK_HELD_S:
                backoff = 1
            else:
                code, reason = getattr(ws, "close_code", None), getattr(ws, "close_reason", None) or ""
                log.warning(f"uplink fermé par le serveur après {held:.1f} s (code {code}{' — ' + reason if reason else ''}) "
                            f"— retry dans {backoff}s (golem.fm d'avant le lien par golem : un autre golem du même compte ?)")
                await asyncio.sleep(backoff)
                backoff = min(RECONNECT_MAX_S, backoff * 2)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LINKED.update(ok=False, t=time.time())
            if opened and time.time() - opened >= LINK_HELD_S:
                backoff = 1                      # le lien avait tenu : il vient de tomber, on revient vite
            state.touch()
            # ⚠ NOMMER les fermetures d'authentification. Un jeton émis AVANT l'ajout du scope
            # `follow:push` fait fermer le serveur en 4403 — et « uplink coupé (…) » ne dit
            # RIEN au musicien : la tablature ne défile pas, sans un mot d'explication.
            # Demandé par l'agent golem.fm (2026-08-03) ; il avait raison, c'était muet.
            code = getattr(getattr(e, "rcvd", None), "code", None) or getattr(e, "code", None)
            if code == UPLINK_REPLACED:
                LINKED.update(why="another connection of this golem took the link")
                state.touch()
                log.warning(f"uplink REMPLACÉ (4409) — une autre connexion de CE golem a pris le lien (deux bridges sur le même jeton ?) ; "
                            f"nouvel essai dans {REPLACED_RETRY_S} s")
                await asyncio.sleep(REPLACED_RETRY_S)
                continue
            if code == 4401:
                log.warning("REFUSÉ 4401 — jeton invalide ou révoqué : ré-appairer "
                            "(Settings ▸ Connect ▸ golem.fm)")
            elif code == 4403:
                log.warning("REFUSÉ 4403 — le jeton n'a pas le scope `follow:push` "
                            "(émis avant son ajout ?) : ré-appairer suffit")
            else:
                log.warning(f"uplink coupé ({e}) — retry dans {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(RECONNECT_MAX_S, backoff * 2)

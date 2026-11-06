// SPDX-License-Identifier: GPL-3.0-or-later
// GoleM — shell de l'app (topbar + routeur). Preact+htm, sans build.
import { html, render, useRoute, go, useRigState, useTopSlot, useTopAction, useActionHost, useTopIO, useRef, useState, useEffect, useAsync, cls, post } from './lib.js';
import { Icon } from './icons.js';
import { trackShellGeometry } from './shell-geom.js';
import { LivePage } from './page-live.js';
import { LoadingPage } from './page-loading.js';
import { FirstCheckPage } from './page-first-check.js';         // la vérification de première installation (docs/health.md §2)
import { demoStatus as firstCheckDemo } from './first-check-model.mjs';
import { showBoot, demoState } from './boot-model.mjs';
import { serviceBadges, withDemo } from './services-model.mjs';   // la pastille des services (⚙ → API → golem.fm / Tone3000)
import { healthDot } from './health-model.mjs';                  // le point de santé (docs/health.md §3) → Settings ▸ Health
import { LibraryPage } from './page-library.js';
import { SongsPage } from './page-songs.js';
import { DesignerPage } from './page-designer.js';
import { SystemePage } from './page-systeme.js';
import { watchErrors } from './ui-errors.mjs';             // les erreurs de l'app vers les rapports (docs/diagnostics.md §7.2)

// Topbar = 5 sections (décision 2026-07-30) : Live / Songs / Designer / Library / Settings —
// le flux d'une soirée : choisir, jouer, retoucher. Songs = CE QUE TU JOUES (presets, setlists,
// recordings — bientôt patches) ; Library = CE QUE TU POSSÈDES (l'inventaire). L'icône « liste
// musicale » a suivi Songs ; Library a pris l'archive. Icônes = SVG flat monochrome (currentColor).
const ICONS = {
  live: html`<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M8 5.5v13a1 1 0 0 0 1.5.87l10-6.5a1 1 0 0 0 0-1.74l-10-6.5A1 1 0 0 0 8 5.5Z"/></svg>`,
  designer: html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="2" x2="6" y1="14" y2="14"/><line x1="10" x2="14" y1="8" y2="8"/><line x1="18" x2="22" y1="16" y2="16"/></svg>`,
  songs: html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15V6"/><path d="M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"/><path d="M12 12H3"/><path d="M16 6H3"/><path d="M12 18H3"/></svg>`,
  library: html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>`,
  settings: html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="3"/></svg>`,
};
// Ordre : DU CHAUD AU FROID (décision 2026-07-31, l'ordre « flux de soirée » était un
// raisonnement de scène appliqué à un outil d'atelier). Live = maintenant · Designer = l'établi ·
// Songs = le répertoire · Library = l'inventaire. Songs et Library, les deux hubs de CONTENU,
// deviennent voisins ; Designer et Songs — le va-et-vient réel — aussi.
const NAV = [
  { id: 'live', route: 'live', label: 'Live' },
  { id: 'designer', route: 'designer', label: 'Designer' },
  { id: 'songs', route: 'songs', label: 'Songs' },
  { id: 'library', route: 'library', label: 'Library' },
  { id: 'settings', route: 'system', label: 'Settings' },
];
// route active -> quelle icône est allumée (les sous-pages des hubs allument leur hub)
const NAV_ACTIVE = { live: 'live', songs: 'songs', designer: 'designer',
  library: 'library', amps: 'library', foot: 'library', banks: 'library', setlists: 'songs',
  system: 'settings', systeme: 'settings', api: 'settings' };

// 'systeme' = alias legacy (anciens liens/bookmarks) -> même hub
const PAGES = { live: LivePage, songs: SongsPage, designer: DesignerPage, library: LibraryPage,
  system: SystemePage, systeme: SystemePage };

// Bandeau « bridge perdu » (Sprint 4.3) : visible seulement si le WS reste mort > 4 s —
// pas de flash au boot ni sur les micro-reconnexions ; les pages s'auto-réparent (useAsync).
function useLinkLost(wsUp) {
  const [lost, setLost] = useState(false);
  useEffect(() => {
    if (wsUp) { setLost(false); return; }
    const t = setTimeout(() => setLost(true), 4000);
    return () => clearTimeout(t);
  }, [wsUp]);
  return lost;
}

// La fenêtre du rack ne recharge jamais d'elle-même : quand les fichiers de l'app changent sous
// elle (un correctif livré), elle le DIT — bandeau, un tap recharge. Jamais de reload forcé : le
// brouillon du Designer vit dans la sandbox, mais un geste en cours n'a pas à être interrompu.
function useAppBuild(wsUp) {
  const [stale, setStale] = useState(false);
  const first = useRef(null);
  useEffect(() => {
    let alive = true;
    const check = () => fetch('/api/app-build').then(r => r.json()).then(d => {
      if (!alive || !d || !d.build) return;
      if (first.current == null) first.current = d.build;
      else if (d.build !== first.current) setStale(true);
    }).catch(() => {});
    check();
    const t = setInterval(check, 20000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  useEffect(() => { if (wsUp) fetch('/api/app-build').then(r => r.json()).then(d => {
    if (d && d.build && first.current != null && d.build !== first.current) setStale(true); }).catch(() => {}); }, [wsUp]);
  return stale;
}

// ── LE MODE SÉLECTION DU PIED SE MONTRE (2026-09-21) ──────────────────────────────────────────
// Appui long sur le switch 1 -> le pédalier tape un n° de slot à deux chiffres. Tant qu'il y est,
// les appuis de scène sont des CHIFFRES. Invisible, ce mode avalait le retour en B après un
// retour en A un peu appuyé (« le deuxième A->B accroche », Paper Kite) : la LED du pédalier
// disait B, le son restait en A. Bandeau GLOBAL (on peut être sur n'importe quelle page quand
// le pied part), avec sa sortie : Cancel, et le compte à rebours de l'abandon automatique.
// Le compte à rebours est LOCAL (relancé à chaque chiffre, comme le minuteur du bridge) : un
// téléphone n'a pas l'horloge du rack.
function FootSelect({ fs }) {
  const [left, setLeft] = useState(0);
  const key = fs ? (fs.digits || []).join(',') : null;
  useEffect(() => {
    if (!fs) return;
    const end = Date.now() + (fs.timeout_s || 8) * 1000;
    const tick = () => setLeft(Math.max(0, Math.ceil((end - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 250);
    return () => clearInterval(t);
  }, [key]);
  if (!fs) return '';
  const d = fs.digits || [];
  return html`<div class="fs-banner" role="status">
    <span class="fs-title">Slot entry</span>
    <span class="fs-hint">Tap two switches on the pedalboard (10 = 0) — scene switches type digits until then</span>
    <span class="fs-digits"><b>${d.length > 0 ? d[0] : '_'}</b><b>${d.length > 1 ? d[1] : '_'}</b></span>
    <span class="fs-left">${left} s</span>
    <button class="fs-cancel" onClick=${() => post('/api/foot/select/cancel', {}).catch(() => {})}>Cancel</button>
  </div>`;
}

// ── LA CARTE SON ACTIVE N'EST PAS BRANCHÉE (2026-09-21 : « affiche l'erreur à l'écran ») ──
// Le matin même : reaper.ini attendait l'AudioBox iTwo (adoptée pour la répète), la Volt était
// branchée — Reaper ouvrait sa propre boîte « ALSA: error opening input device » et l'écran du
// rack ne disait rien. Le bandeau nomme la carte attendue et propose chaque carte BRANCHÉE : le
// geste est le « Switch to it » de Settings ▸ Gear ▸ Soundcard (probe, reaper.ini, redémarrage du
// moteur ~10 s), jamais un basculement automatique — sur scène, une sortie qui change toute
// seule de carte est pire qu'un silence qu'on voit.
function CardMissing({ cards }) {
  const [busy, setBusy] = useState(null);
  // REPLIABLE (2026-10-27, tools/check-use.py) : le bandeau flotte au-dessus de la page et cachait ce qu'il y a dessous
  // (les filtres de Songs, le haut des tuiles de Live). Toucher son titre le réduit à une pastille ; la retoucher le rouvre.
  const [folded, setFolded] = useState(false);
  // Les boucles GoleM de REAPER se sont tues (bridge/monitors.py, 2026-10-05) : on ne sait RIEN de la
  // carte — le son passe peut-être encore — mais le rack ne pilote plus REAPER. Le dire tel quel.
  // Le bouton relance REAPER même FIGÉ (2026-10-05) : le bridge le détecte (thread principal muet 15 s),
  // le termine et le rouvre sur le projet de GoleM — d'où les ~20 s avant que l'état revienne.
  // JAMAIS DÉMARRÉES (2026-11-04, Mac) : une boîte de REAPER (Préférences d'un profil neuf, licence…) bloque son
  // __startup.lua — la cause est À L'ÉCRAN de REAPER, pas dans un journal : le dire.
  if (cards && cards.scripts_stalled) return html`<div class="cm-banner" role="alert">
    <span class="cm-title">⚠ ${cards.scripts_never_started ? "REAPER's golem scripts never started" : 'REAPER stopped listening'}</span>
    <span class="cm-hint">${cards.scripts_never_started
      ? 'A REAPER window is probably waiting for an answer (Preferences, licence, save): bring REAPER to the front and close it.'
      : "golem's scripts in REAPER have stopped: presets and scenes won't change."}
      ${cards.lua_error ? html`<br /><b>${cards.lua_error}</b>` : ''}</span>
    <button class="cm-switch" disabled=${busy === 'reaper'}
      title="close REAPER (forced if it no longer responds) and reopen golem's project — ~20 s"
      onClick=${() => { setBusy('reaper'); post('/api/system/reaper-restart', {}).catch(() => {});
                        setTimeout(() => setBusy(null), 45000); }}>
      ${busy === 'reaper' ? 'Restarting…' : 'Restart REAPER'}</button>
  </div>`;
  if (!cards || !cards.active || cards.active_present !== false) return '';
  const cands = cards.candidates || [];
  const adopt = id => {
    setBusy(id);
    post('/api/cards/adopt', { id }).catch(() => {});
    setTimeout(() => setBusy(null), 15000);        // le WS montre le retour ; filet si rien ne répond
  };
  if (folded) return html`<button class="cm-banner cm-folded" role="alert" title="no sound card — tap to see what to do"
    onClick=${() => setFolded(false)}><span class="cm-title">⚠ No sound card</span></button>`;
  return html`<div class="cm-banner" role="alert">
    <button class="cm-title cm-fold" title="fold this message — the screen under it stays usable"
      onClick=${() => setFolded(true)}>⚠ No sound card</button>
    <span class="cm-hint"><b>${cards.active_name || cards.active}</b> is not plugged in. ${cands.length ? 'Plug it back in, or switch:' : 'Plug it back in.'}</span>
    ${cands.map(c => html`<button class="cm-switch" disabled=${!!busy}
      title="switch the engine to this card — Reaper restarts (~10 s), the other card's setup is kept"
      onClick=${() => adopt(c.id)}>${busy === c.id ? 'Switching…' : 'Use ' + c.name}</button>`)}
  </div>`;
}

// ── CE QUE golem.fm VIENT DE POSER SUR LE RACK (2026-10-04, bridge/arrivals.py) ──────────────
// 168 packs installés par les jobs, et l'écran n'en montrait rien avant un rechargement complet.
// Les pages rechargent leur liste d'elles-mêmes (useRev) ; ce bandeau dit CE QUI est arrivé, une
// fois par rafale, quelques secondes. La notice déjà présente au premier état reçu (ouverture de
// l'app, reconnexion) est une vieille nouvelle : elle sert de référence, on ne la rejoue pas.
// UN GOLEM NEUF N'A AUCUNE CAPTURE (décision 2026-09-09) : ses blocs ampli et pédale sont retirés du rig et la guitare
// joue sans ampli — Live ne le disait pas (audit 2026-10-31, #5). Un bandeau, sur les pages où ça s'entend, mène au
// geste : TONE3000 d'abord s'il n'est pas branché, sinon Content ▸ Factory qui télécharge les captures d'usine.
// Replié d'un toucher pour la session (il flotte au-dessus de la page, comme CardMissing).
const CAP_PAGES = /^(live|designer|library\/tones\/(amps|pedals))/;
function CapturesMissing({ route, rev, locked }) {
  const { data: c } = useAsync(() => fetch('/api/factory/captures').then(r => r.json()).catch(() => null), [rev]);
  const [folded, setFolded] = useState(() => { try { return sessionStorage.getItem('golemCapFold') === '1'; } catch (e) { return false; } });
  if (locked || !c || !c.total || c.present >= c.total || !CAP_PAGES.test(route)) return '';
  if (c.download && c.download.phase && c.download.phase !== 'idle') return '';
  const fold = v => { setFolded(v); try { sessionStorage.setItem('golemCapFold', v ? '1' : '0'); } catch (e) { /* privé */ } };
  if (folded) return html`<button class="cm-banner cm-folded cap-banner" onClick=${() => fold(false)}
    title="amp and pedal captures are missing">⚠ No captures</button>`;
  const none = !c.present;
  return html`<div class="cm-banner cap-banner" role="status">
    <span class="cm-title" onClick=${() => fold(true)}>⚠ ${none ? 'No amp sound yet' : (c.total - c.present) + ' captures missing'}</span>
    <span class="cm-hint">${none ? 'golem ships without amp and pedal captures: those blocks stay silent.' : 'the blocks that use them stay silent.'}
      ${c.connected ? html` Download the <b>${c.total}</b> factory captures.` : html` Connect TONE3000 (free account), then download the <b>${c.total}</b> factory captures.`}</span>
    <button class="cm-switch" onClick=${() => go(c.connected ? 'system/content/factory' : 'system/connect/tone3000')}>
      ${c.connected ? 'Download ›' : 'Connect TONE3000 ›'}</button>
    <button class="an-close" aria-label="Fold" onClick=${() => fold(true)}>✕</button>
  </div>`;
}

function ArrivalNotice({ notice, locked }) {
  const [shown, setShown] = useState(null);
  const seen = useRef(undefined);
  const id = notice ? notice.id : notice;              // undefined = aucun état reçu encore
  useEffect(() => {
    if (id === undefined) return;
    if (seen.current === undefined) { seen.current = id; return; }
    if (!id || id === seen.current) return;
    seen.current = id;
    setShown(notice);
    const t = setTimeout(() => setShown(null), 6000);
    return () => clearTimeout(t);
  }, [id]);
  if (!shown || locked) return '';
  return html`<div class="an-banner" role="status">
    <span class="an-title">⤓ From golem.fm</span>
    <span class="an-text">${shown.text}</span>
    <button class="an-view" onClick=${() => { setShown(null); go(shown.route || 'library'); }}>View</button>
    <button class="an-close" aria-label="Dismiss" onClick=${() => setShown(null)}>✕</button>
  </div>`;
}

function App() {
  const route = useRoute();
  const rig = useRigState();
  // L'ÉCRAN DE CHARGEMENT (mockups/loading.html) remplace /live tant que le premier preset ne joue pas. « Open the
  // app anyway » (seulement quand quelque chose traîne) sort POUR CE démarrage (t0) ; un restart le ramène.
  const [bootSkip, setBootSkip] = useState(() => { try { return Number(sessionStorage.getItem('golemBootSkip')) || null; } catch (e) { return null; } });
  const [fcHide, setFcHide] = useState(false);      // la vérification de première installation, fermée pour cet écran
  const linkLost = useLinkLost(rig.wsUp);
  const appStale = useAppBuild(rig.wsUp);
  const slot = useTopSlot();                       // contrôles contextuels publiés par la page (ex. Designer)
  const action = useTopAction();                   // action contextuelle (+ Add, 💾 Save…)
  const actionHost = useActionHost();               // …rendue ICI, ou par la rangée du hub (Library)
  const io = useTopIO();                           // bouton ⇅ I/O de la Library
  // ── LE GROUPE COURANT (roadmap 0.c) ────────────────────────────────────────────────────
  // ⚠ LE SÉLECTEUR DE GROUPE A ÉTÉ RETIRÉ DE LA TOPBAR (décision 2026-09-07).
  //
  // Le groupe n'est pas un réglage du rig : c'est une DESTINATION, et elle ne répond qu'à
  // une question — « où va ce que j'enregistre ». Une topbar porte ce qui est vrai partout ;
  // le groupe n'est vrai qu'au moment du REC. Pire, un sélecteur armé en permanence à côté
  // de la nav est un sélecteur qu'on effleure au doigt : se tromper de groupe ne se voit pas
  // sur le moment, ça se découvre le lendemain, la répète rangée au mauvais endroit.
  //
  // Le réglage vit désormais là où il sert : la feuille du bloc REC (le bloc qui enregistre),
  // et le MODE le pose tout seul (`mode.band`) — Home vers l'espace perso, Rehearsal et Gig
  // vers le groupe. La correction après coup reste sur la carte de session (Recordings).
  //
  // Et surtout : un GoleM qui ne s'est JAMAIS connecté à golem.fm ne prononce pas le mot
  // « groupe ». La notion vient du cloud (`GET /api/ext/band`) ; sans roster, `/api/band`
  // rend `{band: null, bands: []}` et toute l'UI de groupe se tait d'elle-même.
  // deep-link d'onglet de hub : #/system/mode — et de SOUS-onglet : #/system/gear/sound
  const segs = route.split('/');
  const base = segs[0], sub = segs.slice(1).join('/');
  // Mode machine (docs/modes.md) : la surface UI suit le mode. Gig = pages
  // masquées (pas grisées) + verrou ; sortie = appui long 2 s sur le logo.
  const mode = ((rig && rig.state) || {}).mode || {};
  const pages = (mode.ui && mode.ui.pages) || null;      // null = tout visible
  const nav = pages ? NAV.filter(n => pages.includes(n.route)) : NAV;
  const gate = pages && !pages.includes(base) && base !== 'live';   // route interdite -> Live
  const active = gate ? 'live' : (NAV_ACTIVE[base] || 'live');
  const Page = gate ? LivePage : (PAGES[base] || LivePage);
  const hold = useRef(null);
  // SORTIE DU MODE VERROUILLÉ — appui long 2 s sur le logo. Version robuste au DOIGT (bug Gig
  // 2026-07-31) : l'ancienne annulait sur onPointerLeave, or un vrai doigt micro-bouge et sort
  // du logo (la leçon du drag de la timeline, rejouée ici) ; et sur tactile, Chromium déclenche
  // son MENU CONTEXTUEL à ~500 ms, qui coupe le flux pointer (pointercancel). Donc : écouteurs
  // FENÊTRE, tolérance de 14 px, et contextmenu neutralisé sur le logo. Un kiosk sans sortie
  // enferme l'utilisateur — c'est déjà arrivé (Alt+F4), ça ne doit jamais se rejouer.
  // `force` : depuis le BADGE DE MODE, l'appui long sort de N'IMPORTE quel mode (verrouillé ou
  // non) — c'est la cible naturelle (« je veux quitter Gig » → on presse « Gig »). Constaté la
  // nuit du 2026-07-31 : le mainteneur, enfermé, pressait le badge — qui n'écoutait rien. Le logo garde
  // son rôle historique (modes verrouillés seulement).
  const exitDown = (e, force) => {
    if (!force && (!mode.ui || !mode.ui.locked)) return;
    if (force && (!mode.id || mode.id === 'studio')) return;
    const el = e.currentTarget;
    el.classList.add('tb-holding');                       // retour visuel : « tiens bon, ça vient »
    const x0 = e.clientX, y0 = e.clientY;
    const cancel = () => { clearTimeout(hold.current); hold.current = null;
      el.classList.remove('tb-holding');
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', cancel);
      window.removeEventListener('pointercancel', cancel); };
    const move = ev => { if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > 14) cancel(); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', cancel);
    window.addEventListener('pointercancel', cancel);
    // ⚠ L'ÉCHAPPATOIRE DU KIOSK NE DOIT JAMAIS ÉCHOUER EN SILENCE (audit 2026-08-12) :
    // bridge muet = l'utilisateur restait enfermé sans un mot. L'alert est moche mais
    // VISIBLE, et le geste se retente tel quel.
    // ⚠ Et elle doit SAVOIR RÉPONDRE au bridge (2026-09-09, vécu sur Show) : une prise en cours
    // + un mode Home qui vise un autre espace = le bridge répond 409 « confirm required » — pas
    // une panne, une question. L'ancien code prenait tout non-2xx pour un bridge muet, et le mainteneur
    // restait dans Show avec un message faux. On pose la question, on renvoie `confirm`.
    const exitTo = body => fetch('/api/mode', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(async r => {
        if (r.ok) return;
        const j = await r.json().catch(() => ({}));
        if (r.status === 409 && j.needs_confirm && !body.confirm) {
          if (confirm((j.message || 'A take is in progress.') + '\nExit the mode anyway?')) return exitTo({ ...body, confirm: true });
          return;
        }
        throw new Error(j.error || ('HTTP ' + r.status));
      });
    hold.current = setTimeout(() => { cancel(); exitTo({ id: 'studio' })
      .catch(e => alert('Could not exit the mode — ' + (e && e.message && !/^HTTP/.test(e.message) ? e.message : 'the bridge did not answer') + '. Hold again to retry.'));
    }, 2000);
  };
  const bootDemo = (location.search.match(/[?&]boot=demo(?:&at=(\d+))?/) || null);   // DEV : l'écran sans redémarrer
  if (bootDemo) return html`<${LoadingPage} rig=${{ state: demoState(bootDemo[1]) }} linkLost=${false} onSkip=${() => {}} />`;
  // LA VÉRIFICATION DE PREMIÈRE INSTALLATION (docs/health.md §2) : une fois, à la fin du premier démarrage, à la place
  // de /live — jamais en mode verrouillé (on est sur scène), jamais après « Skip for now » (gardé par le bridge).
  // DEV : ?boot=firstcheck[&at=input|done] montre les écrans sans rack neuf (at=input : le geste des entrées).
  const fcDemo = (location.search.match(/[?&]boot=firstcheck(?:&at=(\w+))?/) || null);
  if (fcDemo) return html`<${FirstCheckPage} rig=${rig} demo=${firstCheckDemo(fcDemo[1])} onDone=${() => {}} />`;
  const fc = rig.state && rig.state.first_check;
  if (base === 'live' && fc && fc.pending && !fcHide && rig.state.boot && rig.state.boot.done && !(mode.ui && mode.ui.locked)
      && !showBoot(rig.state, bootSkip)) {
    return html`<${FirstCheckPage} rig=${rig} onDone=${() => setFcHide(true)} />`;
  }
  if (base === 'live' && rig.state && showBoot(rig.state, bootSkip)) {
    return html`<${LoadingPage} rig=${rig} linkLost=${linkLost}
      onSkip=${() => { const t0 = rig.state.boot.t0; try { sessionStorage.setItem('golemBootSkip', String(t0)); } catch (e) { /* privé */ } setBootSkip(t0); }} />`;
  }
  return html`
    <div class="shell" data-sect=${active}>
      ${linkLost ? html`<div class="link-lost">⚠ Bridge link lost — reconnecting… (pages retry on their own)</div>` : ''}
      <div class="tb-alerts">
        <${CardMissing} cards=${rig.state && rig.state.cards} />
        <${FootSelect} fs=${rig.state && rig.state.foot_select} />
        <${ArrivalNotice} notice=${rig.state && rig.state.notice} locked=${!!(mode.ui && mode.ui.locked)} />
        <${CapturesMissing} route=${segs.join('/')} rev=${rig.state && rig.state.library_rev} locked=${!!(mode.ui && mode.ui.locked)} />
      </div>
      ${appStale && !linkLost ? html`<button class="app-stale" onClick=${() => location.reload()}
        title="the app files changed on the rack — this screen still runs the previous version">⟳ New version installed — tap to reload</button>` : ''}
      <header class="topbar">
        <div class="tb-brand" data-doc="topbar.brand" onClick=${() => go('live')} title=${mode.ui && mode.ui.locked ? 'Hold 2 s to exit ' + mode.name + ' mode' : 'golem'}
          onPointerDown=${exitDown} onContextMenu=${e => e.preventDefault()}>
          ${/* SUR /live, LE « _ » BAT LA MESURE (2026-10-15) : un clignotement par temps, au tempo en cours —
                comme le voyant du BPM. Ailleurs, le curseur garde son rythme tranquille de 1,7 s. */''}
          <span class="tb-wordmark" aria-label="golem"
            style=${active === 'live' && ((rig && rig.state) || {}).tempo > 0 ? '--caret-dur:' + (60 / rig.state.tempo).toFixed(3) + 's' : ''}
            ><span class="s">/</span><span class="g">golem</span><span class="cur">_</span></span>
        </div>
        ${mode.id && mode.id !== 'studio' ? html`<span class="tb-mode tb-mode-exit" data-doc="topbar.mode"
          title=${'Hold 2 s to exit ' + mode.name + ' mode'}
          onPointerDown=${e => exitDown(e, true)} onContextMenu=${e => e.preventDefault()}>
          <${Icon} id=${mode.id} fallback=${mode.icon} /> ${mode.name}</span>` : ''}
        <nav class="tb-nav">
          ${nav.map(n => { const dot = n.id === 'settings' ? (serviceBadges(withDemo(rig.state)).settings || (healthDot(rig.state) || {}).badge) : null;
            return html`<a class=${cls('tb-navitem', active === n.id && 'on')} data-doc=${'nav.' + n.id} href=${'#/' + n.route}
              data-sect=${n.id} title=${n.label + (dot ? ' — something needs your attention in API' : '')} aria-label=${n.label}>${ICONS[n.id]}${dot ? html`<i class=${'svc-dot ' + dot}></i>` : ''}</a>`; })}
        </nav>
        <div class="tb-slot">${slot}</div>
        <div class="tb-right">
          ${/* PAS DE POINT DE SANTÉ DANS LA BARRE (2026-10-20 : « une pastille visible tout le temps — enlève-la
                partout ») : la santé se lit dans Settings ▸ System ▸ Health ; seul un ROUGE met une pastille sur ⚙ (healthDot). */''}
          ${io}
          ${actionHost === 'topbar' ? action : ''}
        </div>
      </header>
      <main class="page"><${Page} rig=${rig} sub=${sub} /></main>
    </div>`;
}

watchErrors('rack');
render(html`<${App} />`, document.getElementById('app'));
// fenêtre du poste de travail : elle retrouve sa taille (no-op sur le rack et dans un onglet
// ordinaire — la mémoire ne s'active que sur ?shell=, posé par provision/golem).
trackShellGeometry();

// SPDX-License-Identifier: GPL-3.0-or-later
// Utilitaires partagés de l'app GoleM (Preact+htm vendorisé, offline).
export { html, render } from './vendor/htm-preact-standalone.module.js';
export { useState, useEffect, useRef, useMemo, useCallback } from './vendor/htm-preact-standalone.module.js';
import { html, useState, useEffect } from './vendor/htm-preact-standalone.module.js';

// — API REST du bridge —
export async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    // l'erreur TRANSPORTE le corps : un 409 « confirm required » ou « duplicate ids » est une
    // réponse à lire, pas une panne. Sans ça « Switch to Rehearsal » affichait « /api/mode → 409 »
    // et n'ouvrait jamais la question (vécu 2026-09-09) — le corps était jeté ici même.
    const e = new Error(`${path} → ${r.status}`); e.status = r.status;
    e.body = await r.json().catch(() => null);
    throw e;
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r.text();
}
export const post = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export const del = (path) => api(path, { method: 'DELETE' });

// — chargement asynchrone AUTO-CICATRISANT (Sprint 4.3, D-P1-9) : un fetch qui échoue
// (bridge en cours de reload, WiFi du téléphone endormi…) est RE-TENTÉ toutes les 4 s tant
// que le composant vit — les ~18 pages qui restaient muettes se réparent toutes seules,
// le bandeau global du shell explique pourquoi pendant ce temps. —
export function useAsync(fn, deps = []) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const reload = () => { setErr(null); return Promise.resolve().then(fn).then(setData).catch(e => setErr(e)); };
  useEffect(() => {
    let ok = true, timer = null;
    const attempt = () => Promise.resolve().then(fn)
      .then(d => { if (ok) { setData(d); setErr(null); } })
      .catch(e => { if (ok) { setErr(e); timer = setTimeout(attempt, 4000); } });
    attempt();
    return () => { ok = false; timer && clearTimeout(timer); };
  }, deps);
  return { data, err, reload, setData };
}

// — garde de chargement : si le fetch a échoué, erreur visible + Retry (sinon Loading…).
//   Avec l'auto-retry de useAsync, le bouton est un raccourci « tout de suite ». —
export function LoadGuard({ err, reload, label = 'Loading…' }) {
  if (err) return html`<div class="load-guard err">
    <span>⚠ Bridge unreachable — retrying…</span>
    <button class="retry" onClick=${reload}>Retry now</button>
  </div>`;
  return html`<div class="load-guard muted">${label}</div>`;
}

// — cache module du catalogue (3 pages le chargent : Amps, Designer, SimList) —
let _catalog = null;
export function getCatalog() {
  if (!_catalog) _catalog = api('/api/catalog').catch(e => { _catalog = null; throw e; });
  return _catalog;
}
export function refreshCatalog() { _catalog = null; }   // après un install/suppression d'ampli

// — appui long (~450ms) ou clic droit = action secondaire (convention QC).
//   lpFired() = vrai si le dernier appui a déclenché le long-press (pour ignorer le clic qui suit).
let _lpTimer = null, _lpFired = false;
export const lpFired = () => _lpFired;
export const longPress = (cb, ms = 450) => ({
  onPointerDown: () => { _lpFired = false; _lpTimer = setTimeout(() => { _lpFired = true; cb(); }, ms); },
  onPointerUp: () => clearTimeout(_lpTimer),
  onPointerLeave: () => clearTimeout(_lpTimer),
  onContextMenu: e => { e.preventDefault(); cb(); },
});

// — CE QUI ARRIVE PAR LES JOBS (bridge/arrivals.py) : deux compteurs de l'état diffusé.
//   `library_rev` (tones, kits, synthés…) et `content_rev` (presets, patches, setlists). Une page
//   met `useRev('library_rev')` dans les deps de son useAsync : elle recharge quand golem.fm a posé
//   quelque chose, sans rechargement de l'app. Le catalogue en cache est jeté au même moment. —
const _revs = { library_rev: null, content_rev: null };
const _revSubs = new Set();
function _takeRevs(s) {
  let moved = false;
  for (const k of Object.keys(_revs)) {
    if (s[k] === undefined || s[k] === _revs[k]) continue;
    if (k === 'library_rev' && _revs[k] !== null) refreshCatalog();
    _revs[k] = s[k]; moved = true;
  }
  if (moved) _revSubs.forEach(f => f());
}
export function useRev(key) {
  const [v, setV] = useState(_revs[key]);
  useEffect(() => {
    const f = () => setV(_revs[key]);
    _revSubs.add(f); f();
    return () => { _revSubs.delete(f); };
  }, [key]);
  return v;
}

// — la FENÊTRE golem de l'ordinateur (docs/installer.md §4) : la coquille device.html (golem desktop) ou la fenêtre
// simple `golem ui`. Le WebSocket le dit au bridge (`?shell=`), qui fait suivre `profile` (desktop|server) à la
// fenêtre — il ne le croit que de l'ordinateur lui-même. null : un onglet, une tablette, un téléphone.
export function golemShell() {
  try {
    if (window.parent !== window) {
      const p = window.parent.location;              // même origine (la coquille est servie par le bridge)
      if (/\/app\/device\.html$/.test(p.pathname) && !/[?&]d=phone\b/.test(p.search)) return 'device';
      return null;
    }
  } catch (_) { return null; }
  return /[?&]shell=ui\b/.test(location.search) ? 'ui' : null;
}
// le panneau « Continue on a tablet » de la coquille (device.html expose window.golemTabletSheet) — null hors fenêtre
export function shellTabletSheet() {
  try {
    if (golemShell() !== 'device') return null;
    if (typeof window.parent.golemTabletSheet === 'function') return window.parent.golemTabletSheet;
    // une coquille d'AVANT (la fenêtre n'a rechargé que l'app, 2026-10-16) : son bouton 📱 fait la même chose — sans
    // ce repli, la fenêtre du PC proposait « Show on this computer », le geste de la tablette
    const b = window.parent.document.getElementById('tablet');
    return b ? () => b.click() : null;
  } catch (_) { return null; }
}

// — WebSocket d'état live (reconnexion auto) —
export function useRigState() {
  const [state, setState] = useState({ reaper_connected: false, preset_id: null, scene_id: null,
                                        voice_on: false, levels: { guitar: 0, voice: 0 }, tempo: 120 });
  const [wsUp, setWsUp] = useState(false);
  useEffect(() => {
    let ws, alive = true;
    const connect = () => {
      const q = new URLSearchParams();
      if (golemToken()) q.set('token', golemToken());
      if (golemShell()) q.set('shell', golemShell());
      ws = new WebSocket(`ws://${location.host}/ws` + (q.toString() ? '?' + q : ''));
      ws.onopen = () => setWsUp(true);
      ws.onmessage = e => {
        try {
          const s = JSON.parse(e.data);
          setBankBase(s.bank_base);      // la numérotation des banks suit le pédalier branché
          _takeRevs(s);
          setState(s);
        } catch (_) {}
      };
      ws.onclose = () => { setWsUp(false); if (alive) setTimeout(connect, 1500); };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => { alive = false; ws && ws.close(); };
  }, []);
  return { state, wsUp };
}

// — hash router —
export function useRoute() {
  const [route, setRoute] = useState(location.hash.slice(2) || 'live');
  useEffect(() => {
    const on = () => setRoute(location.hash.slice(2) || 'live');
    addEventListener('hashchange', on);
    return () => removeEventListener('hashchange', on);
  }, []);
  return route;
}
export const go = (r) => { location.hash = '#/' + r; };

// — ouverture d'un preset dans le Designer (posé par la Library, lu au montage du Designer) —
let _pendingPreset = null;
// id (« ✎ edit » de la Library) OU doc complet (draft : patch ouvert depuis Songs ▸ Patches,
// même chemin que le créateur IA) — le Designer distingue par le type.
let _pendingTab = null;
// `tab` (facultatif) : l'onglet du Designer à ouvrir avec le preset — 'cfg' quand on vient ajouter
// un bloc de service depuis une ligne de setlist (docs/setlists.md §9.9), sinon l'onglet courant.
// `action` : un geste à exécuter DÈS L'ARRIVÉE dans le Designer (« drumset » ouvre le tiroir de
// kit — 2026-09-20 : « on ne peut pas accéder à ce menu depuis /songs ▸ Patches »). Il passe
// par un canal à part, JAMAIS par le document : un marqueur posé sur le preset voyagerait dans le
// corps sauvegardé, et un champ de session finit toujours par devenir une vérité pour quelqu'un.
let _pendingAction = null;
export const openInDesigner = (idOrDoc, tab, action) => { _pendingPreset = idOrDoc; _pendingTab = tab || null;
  _pendingAction = action || null; go('designer'); };
export const takePendingPreset = () => { const id = _pendingPreset; _pendingPreset = null; return id; };
export const takePendingTab = () => { const t = _pendingTab; _pendingTab = null; return t; };
export const takePendingAction = () => { const a = _pendingAction; _pendingAction = null; return a; };
// — une page qui écrit un preset que le Designer tient en brouillon (ex. « New scene for this part » du
//   tableau des parties) lui laisse la MÊME mutation : le brouillon est en mémoire entre deux pages, et il
//   écraserait le fichier à sa prochaine sauvegarde (CLAUDE.md : le Designer édite la sandbox).
let _draftMuts = [];
export const queueDraftMutation = (pid, fn) => { _draftMuts.push({ pid, fn }); };
export const takeDraftMutations = pid => { const mine = _draftMuts.filter(m => m.pid === pid).map(m => m.fn); _draftMuts = []; return mine; };

// ÉCRIRE UN PRESET DEPUIS UNE AUTRE PAGE QUE LE DESIGNER — les trois gestes, en UN endroit (2026-10-07 :
// /live ▸ Assign les faisait, /songs pas du tout). `doc` = le preset muté, `mut` = la mutation : écrire le
// fichier, l'enfiler pour un Designer qui s'ouvrirait plus tard, et la rejouer dans la sandbox si un
// Designer porte CE preset maintenant — sinon sa prochaine audition écraserait le fichier (CLAUDE.md).
// Rend la réponse de POST /api/preset ({error} compris : l'appelant le DIT).
export async function savePresetEverywhere(doc, mut) {
  const postJ = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(b || {}) }).then(r => r.json());
  const r = await postJ('/api/preset', doc).catch(e => ({ error: String(e) }));
  if (r && r.error) return r;
  queueDraftMutation(doc.id, mut);
  const sb = await fetch('/api/sandbox').then(x => x.json()).catch(() => null);
  if (sb && sb.preset && sb.preset.id === doc.id) {
    const draft = structuredClone(sb.preset);
    mut(draft);
    await postJ('/api/sandbox_apply', { preset: draft, scene: sb.scene }).catch(() => {});
  }
  return r;
}

// — slot de topbar : une page publie ses contrôles contextuels (ex. Designer : preset+scènes+actions)
//   dans la barre du haut. Store module + hook d'abonnement pour le shell.
let _topSlot = null;
const _topSubs = new Set();
export function setTopSlot(vnode) { _topSlot = vnode; _topSubs.forEach(f => f()); }
export function useTopSlot() {
  const [, bump] = useState(0);
  useEffect(() => { const cb = () => bump(x => x + 1); _topSubs.add(cb); return () => _topSubs.delete(cb); }, []);
  return _topSlot;
}

// — AUTH distant (SECURITY.md) : ?auth=<invitation> du QR est ÉCHANGÉ (claim, usage
// unique) contre un token d'appareil, posé en cookie (couvre TOUS les fetch same-origin) +
// localStorage (survie). Repli : claim refusé = token direct (compat vieux QR / legacy).
// Sur le kiosk (127.0.0.1) tout ceci est inerte : le local est auto-authentifié.
const _setTok = tok => {
  localStorage.setItem('golem_token', tok);
  document.cookie = 'golem_token=' + tok + '; path=/; SameSite=Lax; max-age=31536000';
};
(async () => {
  try {
    const u = new URL(location.href);
    const t = u.searchParams.get('auth');
    if (t) {
      u.searchParams.delete('auth');
      history.replaceState(null, '', u.pathname + (u.searchParams.size ? '?' + u.searchParams : '') + u.hash);
      let tok = t;
      try {
        const r = await fetch('/api/auth/claim', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ invite: t }) });
        if (r.ok) tok = (await r.json()).token;
      } catch { /* bridge injoignable : on garde la valeur brute, le retry WS fera foi */ }
      _setTok(tok);
    } else {
      const tok = localStorage.getItem('golem_token');
      if (tok) document.cookie = 'golem_token=' + tok + '; path=/; SameSite=Lax; max-age=31536000';
    }
  } catch { /* vieux navigateur : tant pis, le kiosk local n'en a pas besoin */ }
  // — Golem Companion : un appareil kind=Phone n'arrive JAMAIS sur l'app complète
  //   (docs/devices-people.md). Échappatoire debug : ?desktop=1. Kiosk local : jamais routé.
  // — UN JETON QUE LE RACK NE RECONNAÎT PLUS SE DIT (docs/devices-people.md, lot B, 2026-09-15) :
  //   le téléphone du mainteneur présentait un vieux jeton, refusé en 403 à chaque reconnexion, et l'app
  //   s'ouvrait figée (en version bureau, faute de savoir que c'était un téléphone), sans un mot.
  try {
    const w = await fetch('/api/auth/whoami').then(r => r.json());
    if (w && !w.local && w.token === 'unknown') { location.replace('/app/unpaired.html'); return; }
    // ET UN APPAREIL JAMAIS APPAIRÉ ICI (2026-10-03) : le jeton se range sous l'ORIGINE — un téléphone appairé
    // sur 192.168.0.22 arrive sans jeton sur golem.local. Le rack refusait son flux en 403, l'app s'ouvrait
    // derrière un « OFFLINE » clignotant et rien ne répondait : on lui dit de s'appairer, comme ci-dessus.
    if (w && !w.local && w.token === 'none') { location.replace('/app/unpaired.html?new=1'); return; }
    if (w && !w.local) keepAwake();                     // le kiosk local gère son écran ; une tablette ou un téléphone, non
    if (!location.pathname.endsWith('/m.html') && new URL(location.href).searchParams.get('desktop') !== '1') {
      if (w && w.device && w.device.kind === 'Phone') location.replace('/app/m.html');
    }
  } catch { /* bridge injoignable : on laisse l'app se charger, elle a son LoadGuard */ }
})();
// la coquille lecture seule de golem.fm (?shell=ro, docs/shell.md) : un écran peut ne PAS RENDRE un contrôle d'édition
export const SHELL_RO = typeof document !== 'undefined' && document.documentElement.dataset.shell === 'ro';
export const golemToken = () => { try { return localStorage.getItem('golem_token') || ''; } catch { return ''; } };

// — L'ÉCRAN RESTE ALLUMÉ (docs/devices-people.md, lot E — 2026-09-15) ─────────────────────────────────
// Une tablette qui sert d'écran au rack, un téléphone sur le pupitre : la veille en plein morceau.
// ⚠ `navigator.wakeLock` n'existe QUE dans un contexte sécurisé (HTTPS ou localhost) : sur
// http://192.168.x.x il est absent, et le verrou du Companion ne faisait rien sur un vrai téléphone. Repli :
// une vidéo muette de 2 s en boucle (app/media/keepawake.*), le procédé des bibliothèques « no sleep » —
// jouée d'office (muette, l'autoplay est permis), sinon au premier toucher. Non vérifié sur tous les
// téléphones : c'est un repli, pas une garantie.
let _awake = false;
export function keepAwake() {
  if (_awake || typeof document === 'undefined') return;
  _awake = true;
  if (navigator.wakeLock) {
    const grab = () => { if (document.visibilityState === 'visible') navigator.wakeLock.request('screen').catch(() => {}); };
    grab(); document.addEventListener('visibilitychange', grab);
    return;
  }
  const v = document.createElement('video');
  v.setAttribute('playsinline', ''); v.setAttribute('aria-hidden', 'true'); v.muted = true; v.loop = true;
  v.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;opacity:0;pointer-events:none';
  v.innerHTML = '<source src="/app/media/keepawake.webm" type="video/webm"><source src="/app/media/keepawake.mp4" type="video/mp4">';
  const play = () => { v.play().catch(() => {}); };
  const mount = () => { if (!v.isConnected) document.body.appendChild(v); play(); };
  if (document.body) mount(); else addEventListener('DOMContentLoaded', mount, { once: true });
  ['pointerdown', 'touchstart'].forEach(ev => addEventListener(ev, play, { once: true, passive: true }));
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') play(); });
}

// — action contextuelle de topbar (à droite, avant l'avatar) : ex. 💾 Save de l'onglet API.
//   Store séparé du topSlot (le hub y publie déjà ses tabs) — même pattern d'abonnement.
let _topAction = null;
const _actSubs = new Set();
export function setTopAction(vnode) { _topAction = vnode; _actSubs.forEach(f => f()); }
// ── OÙ L'ACTION D'UNE PAGE S'AFFICHE (2026-09-18 : « l'onglet Tracks disparaît ») ──────────
// La topbar fait 1024 px et porte déjà la marque, le badge de mode, la nav de section et les ONGLETS
// du hub. Quand une page y ajoute son « + Add », la somme dépasse : `.tb-slot` ne coupait pas, il
// DÉBORDAIT, et les puces de droite se dessinaient PAR-DESSUS les derniers onglets — Tracks devenait
// illisible et surtout INCLIQUABLE (mesuré : débord +110 px dans la Library, +25 px dans Settings).
// Remède : un hub qui a sa propre rangée (Library) ACCUEILLE l'action de sa page, à côté de la
// recherche — « ajouter à ce qu'on regarde » va avec « chercher dans ce qu'on regarde ». La topbar
// garde l'action pour les pages sans rangée (Designer ▸ Save). Les pages, elles, ne changent pas :
// elles publient toujours dans `setTopAction`, c'est l'HÔTE qui décide où ça se rend.
let _actionHost = 'topbar';
export function setActionHost(h) { _actionHost = h === 'page' ? 'page' : 'topbar'; _actSubs.forEach(f => f()); }
export function useActionHost() {
  const [, bump] = useState(0);
  useEffect(() => { const cb = () => bump(x => x + 1); _actSubs.add(cb); return () => _actSubs.delete(cb); }, []);
  return _actionHost;
}
export function useTopAction() {
  const [, bump] = useState(0);
  useEffect(() => { const cb = () => bump(x => x + 1); _actSubs.add(cb); return () => _actSubs.delete(cb); }, []);
  return _topAction;
}

// — slot I/O de topbar (Library) : bouton ⇅ import/export, séparé de l'action (+ Add) pour coexister.
let _topIO = null;
const _ioSubs = new Set();
export function setTopIO(vnode) { _topIO = vnode; _ioSubs.forEach(f => f()); }
export function useTopIO() {
  const [, bump] = useState(0);
  useEffect(() => { const cb = () => bump(x => x + 1); _ioSubs.add(cb); return () => _ioSubs.delete(cb); }, []);
  return _topIO;
}

// — toolbar de sous-onglet (Library) : la page active publie sa recherche/filtres À DROITE de la barre
//   de sous-onglets (compact), pour supprimer la ligne .lib-head séparée. Même pattern d'abonnement.
let _subToolbar = null;
const _stbSubs = new Set();
export function setSubToolbar(vnode) { _subToolbar = vnode; _stbSubs.forEach(f => f()); }
export function useSubToolbar() {
  const [, bump] = useState(0);
  useEffect(() => { const cb = () => bump(x => x + 1); _stbSubs.add(cb); return () => _stbSubs.delete(cb); }, []);
  return _subToolbar;
}

// — hub à sous-onglets (Library, Settings) : publie ses tabs dans la topbar, rend l'onglet courant —
export function HubPage({ tabs, rig, initial, base, badges }) {
  // initial peut porter un SOUS-onglet : "sys/mode" -> onglet sys, sub "mode" passé à la page
  const [init0, ...initRest] = (initial || '').split('/');
  const subsub = initRest.join('/') || undefined;
  const [tab, setTab] = useState(init0 || tabs[0].id);
  // deep-link VIVANT : #/system/gear depuis une autre page du même hub doit
  // basculer l'onglet (liens croisés Mode ⇄ Soundcard, couture 2026-07-19)
  useEffect(() => { if (init0 && tabs.some(t => t.id === init0)) setTab(init0); }, [initial]);
  const Cur = (tabs.find(t => t.id === tab) || tabs[0]).Page;
  // un clic d'onglet ÉCRIT l'URL quand base est fourni (l'URL = source de vérité —
  // sinon un lien vers le hash courant ne déclenche rien : bug « Home non recliquable »)
  const pick = t => { if (base) go(base + '/' + t.id); else setTab(t.id); };
  useEffect(() => {
    setTopSlot(html`<div class="sys-tabs">
      ${tabs.map(t => html`<button class=${'sys-tab' + (t.id === tab ? ' on' : '')} data-doc=${'tab.' + t.id} onClick=${() => pick(t)}
        title=${badges && badges[t.id] ? 'something needs your attention here' : ''}>${t.label}${badges && badges[t.id] ? html`<i class=${'svc-dot ' + badges[t.id]}></i>` : ''}</button>`)}
    </div>`);
    return () => setTopSlot(null);
  }, [tab, initial, JSON.stringify(badges || {})]);   // la pastille suit le verdict (golem.fm revenu après l'ouverture)
  return html`
    <div class="hub-body">
      <div class="hub-scroll"><${Cur} rig=${rig} sub=${subsub} /></div>
    </div>`;
}

// — divers —
// GENRES (docs/genres.md, validé le 2026-10-06) : le style d'un PRESET = des FAMILLES, 0 à 2, ordonnées.
// Remplace les 20 styles à plat d'avant (djent, manouche, rap… : migrés en famille par le bridge, bridge/genres.py).
// ⚠ COPIE de config/genres.json (familles seulement) — tests/test_genres.py échoue si elles divergent. Les ids sont
// des clés d'échange avec golem.fm (propriétaire de la liste) ; seul le libellé s'affiche.
export const GENRE_FAMILIES = [
  ['metal', 'Metal'],
  ['rock', 'Rock'],
  ['punk', 'Punk & Hardcore'],
  ['pop', 'Pop'],
  ['electronic', 'Electronic'],
  ['hip-hop', 'Hip-hop'],
  ['rnb', 'R&B, Soul & Funk'],
  ['blues', 'Blues'],
  ['jazz', 'Jazz'],
  ['folk', 'Folk & Country'],
  ['latin', 'Latin'],
  ['caribbean', 'Reggae & Caribbean'],
  ['world', 'World'],
  ['classical', 'Classical'],
  ['screen', 'Stage & Screen'],
  ['experimental', 'Experimental'],
  ['other', 'Other'],
];
export const genreLabel = id => (GENRE_FAMILIES.find(f => f[0] === id) || [null, id || ''])[1];
// couleurs des tuiles Live par colonne (défaut ; override par preset.colors) — Live + Designer
export const LIVE_PALETTE = ['#3f7fd6', '#12a3a0', '#cc1f1f', '#7a2a52', '#2f5e23'];
export const pad2 = n => String(n).padStart(2, '0');

// — numéro de BANK affiché —
// Le rack compte ses slots depuis 0 ; les pédaliers, eux, numérotent leur afficheur comme ils
// l'entendent (la UnO2 depuis 1, la 1.0.4 depuis 0). L'écran doit montrer CE QUE MONTRE LE
// PÉDALIER : lire « 04 » au pied et « #03 » à l'écran, c'est une hésitation sur scène.
// ⚠ Ceci est un FORMATAGE, pas une renumérotation : sur le fil, PC = slot, toujours 0-18, et
// tout ce qui s'échange avec le bridge reste en slots. Le décalage vient de `state.bank_base`,
// donc du descripteur de l'appareil actif — ressouder l'autre puce ramène l'autre numérotation.
let _bankBase = 0;
export const setBankBase = (n) => { _bankBase = Number(n) || 0; };
export const bankNo = (slot) => pad2(Number(slot) + _bankBase);
export const cls = (...a) => a.filter(Boolean).join(' ');
export const esc = s => String(s == null ? '' : s);
// UN LIEN VENU D'AILLEURS (audit 2026-11-04, M7) : l'URL d'un tone (TONE3000, pack golem.fm) ou d'une connexion est une
// donnée tierce — htm la pose telle quelle, et un `javascript:` s'exécuterait au clic sur l'écran du rack (admin).
// Seuls http(s) passent ; sinon, aucun lien.
export const safeHref = s => /^https?:\/\//i.test(String(s == null ? '' : s).trim()) ? String(s).trim() : undefined;

// ENREGISTRER UN FICHIER (2026-10-12) : la fenêtre golem desktop est un Chrome en mode application — un
// téléchargement y faisait surgir la bulle de Chrome HORS de golem. Sur l'écran de la machine (client local), le bridge
// écrit donc le fichier dans ses Téléchargements (bridge/downloads.py) et l'appelant dit où ; ailleurs (tablette,
// téléphone), le navigateur télécharge sur CET appareil. `backup` = le nom d'une sauvegarde (copiée côté bridge, jamais
// relue en mémoire). Rend { where: chemin écrit | null (téléchargé par le navigateur) }.
let _localScreen = null;
export const isLocalScreen = () => _localScreen || (_localScreen =
  fetch('/api/auth/whoami').then(r => r.json()).then(d => !!(d && d.local)).catch(() => false));
// UN FICHIER QUE LE RACK SERT (prise, sample, groove, kit… — 2026-10-15 : la même règle PARTOUT) : sur l'écran de la
// machine, le bridge se le demande à lui-même et l'écrit dans les Téléchargements (POST /api/system/save-local-url) ;
// ailleurs, le navigateur le télécharge sur l'appareil. Dit où le fichier est arrivé (savedToast). `name` facultatif :
// sinon le nom que la route donne (Content-Disposition), ou la fin de l'adresse.
export async function saveUrl(url, name = '') {
  if (await isLocalScreen()) {
    const r = await fetch('/api/system/save-local-url', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, name }) }).then(x => x.json()).catch(() => null);
    if (r && r.ok) { savedToast('✓ Saved to ' + r.path); return { where: r.path }; }
    savedToast('✗ ' + ((r && r.error) || 'could not save the file'), true);
    return { where: null, error: (r && r.error) || 'failed' };
  }
  const a = document.createElement('a');
  a.href = url; if (name) a.download = name; else a.setAttribute('download', '');
  document.body.appendChild(a); a.click(); a.remove();
  return { where: null };
}
// un message bref en bas de l'écran (« ✓ Saved to … ») — DANS golem, jamais une bulle du navigateur
export function savedToast(msg, bad = false) {
  const el = document.createElement('div');
  el.className = 'gl-toast' + (bad ? ' bad' : '');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add('out'), 3200);
  setTimeout(() => el.remove(), 3700);
}
// un lien ⬇ qui passe par saveUrl : garde son href (clic milieu, accessibilité) mais n'ouvre jamais la bulle de Chrome
export const saveClick = (url, name = '') => e => { e.preventDefault(); saveUrl(url, name); };
export async function saveFile(name, { blob = null, backup = null } = {}) {
  if (await isLocalScreen()) {
    const r = backup
      ? await fetch('/api/backup/' + encodeURIComponent(backup) + '/save-local', { method: 'POST' }).then(x => x.json()).catch(() => null)
      : await fetch('/api/system/save-local?name=' + encodeURIComponent(name), { method: 'POST', body: blob }).then(x => x.json()).catch(() => null);
    if (r && r.ok) return { where: r.path };
  }
  const a = document.createElement('a');
  const url = backup ? '/api/backup/' + encodeURIComponent(backup) : URL.createObjectURL(blob);
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  if (!backup) setTimeout(() => URL.revokeObjectURL(url), 2000);
  return { where: null };
}

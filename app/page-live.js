// SPDX-License-Identifier: GPL-3.0-or-later
// Page Live (stage view) — miroir du FCB : rangée haute = 5 stomps, centre = BANK #NN + preset (◀▶),
// rangée basse = 5 scènes, bas = 2 pédales EXP + latence. Plein écran, pas de scroll. Cf. docs/QC UI/live-mockup.png.
// Preset LOOPER : la rangée haute devient le transport du looper (3 loops + stop-all + delete-all).
//
// ⚠ LA PAGE LIVE SE RETOURNE SELON LE MODE (décision 2026-07-30, contrat docs/archive/show-mode.md §6).
// `mode.ui.live` choisit la VUE : « pedalboard » = tout ce fichier, « timeline » = le pupitre
// (live-stageboard.js). Le mode Show montrait jusqu'ici le miroir du pédalier, ce qui n'était pas
// un mode Show — c'est ce qui rendait l'emplacement d'usine inutile. L'aiguillage est UNE donnée
// lue en tête de composant, pas un `if mode ==` disséminé.
import { html, useState, useEffect, useRef, useAsync, post, cls, esc, longPress, setTopAction, go, LIVE_PALETTE as PALETTE } from './lib.js';
import { Icon } from './icons.js';
// (la bande de GESTES — • tap, •• double, ▬ appui long — est RETIRÉE de /live, 2026-10-09 : « des petits pictos
// blancs dont on avait dit qu'on les enlevait ». La légende en phrases reste dans le Designer ▸ MIDI assign.)
import { ICON, NAME, SHORT, ARCH_NAME, hydrateBlockMeta, animClass, animPackOf, ensurePackCss, blockContent, SPECIAL_CAT } from './designer-model.js';
import { ChartLive } from './live-chart.js';
import { BankBar } from './live-bankbar.js';
import { StagePage } from './live-pages.js';   // les pages Répète et Concert (docs/live-pages.md)
import { useLiveTools, useViewOverride, modeViewKey, useLivePedals } from './live-tools.js';
import { loadVisuals, visualsReady, pedalSvg } from './golem-visuals.js';   // les pédales sur les stomps (L1)   // les outils du top menu et leurs panneaux (2026-10-15)

const EMPTY_SW = [6, 7, 8, 9, 10].map(n => ({ sw: n, blocks: [], whammy: false }));   // pédalier vide (aucun preset)

// Où lire l'ÉTAT VRAI d'un bloc de service posé sur un stomp (6-10). `state.stomps` ne convient
// pas : il dit « ce bloc est activé dans la scène », ce qui est TOUJOURS vrai pour un service
// scene-invariant. Ce qui bouge, c'est qu'il joue. Les clés `drums`/`samples` sont indexées par
// ID DE BLOC (plusieurs lanceurs peuvent coexister sur des switches différents) — d'où le bloc
// passé en argument, et pas seulement son type.
// la case vierge par défaut (2026-10-08) : l'animation et la couleur du SW4 de Paper Kite dans « Covers »
const EMPTY_ANIM = 'monster', EMPTY_COLOR = '#7a2a52';
// DIX MONSTRES (mockups/monsters.html, validée le 2026-10-11) : une case VIERGE prend le monstre de son
// numéro (#1 → m1 … #10 → m10) — même fond, même halo, seuls les yeux changent. Le pack reste « monster » pour les
// presets et golem.fm (docs/anim-packs.md) : un preset qui règle « monster » sur un switch garde m1, l'original.
const monsterOf = n => 'm' + (((Number(n) - 1) % 10 + 10) % 10 + 1);
// les yeux de plus des cyclopes (m4) et de la mouche (m6) : des calques, affichés par le CSS de la variante seulement
const MONSTER_LAYERS = html`<i class="mc2"></i><i class="mc3"></i><i class="mc4"></i>`;

const SVC_STATE = {
  standard: st => !!(st.standard && st.standard.playing),
  click:    st => !!(st.click && st.click.on),
  tuner:    st => !!(st.tuner && st.tuner.on),
  rec:      (st, b, recOn) => !!recOn,
  drums:    (st, b) => !!(((st.drums || {})[b.id]) || {}).playing,
  sample:   (st, b) => !!(((st.samples || {})[b.id]) || {}).playing,
};

// ── CE QUE LA TUILE VA LANCER ────────────────────────────────────────────────────────────
// « STANDARD » et « BACKING » ne disent pas QUOI. Sur scène c'est justement la seule chose
// qu'on a besoin de lire : on sait déjà que le switch lance un backing, on veut savoir lequel.
// On nomme ce que la tuile LANCERA (le morceau réglé dans le bloc), pas ce qui a joué en
// dernier — une tuile décrit son geste.
// ⚠ Par SWITCH, pas globalement : deux blocs `standard` sur deux switches peuvent porter deux
// morceaux différents, et un titre commun serait faux sur l'un des deux.
const songOf = (st, type, sw) => {
  if (type === 'backing-track') {
    const b = st.backing || {};
    const songs = b.songs || [];
    const s = songs.find(x => x.slug === b.slug) || songs[0];
    return s ? { title: s.title, by: s.artist } : null;
  }
  if (type === 'standard') {
    const e = (st.standard_switches || {})[sw] || (st.standard_switches || {})[String(sw)];
    const slug = ((e || {}).params || {}).standard || (st.standard_block || {}).standard;
    const m = slug && (st.standard_meta || {})[slug];
    return m ? { title: m.title, by: m.composer } : (slug ? { title: slug, by: '' } : null);
  }
  return null;
};

// une SCÈNE du morceau qui joue : `preset` null — envoyer le preset en faisait un rappel « sans ligne », qui
// effaçait la chanson (bandeau « no song · sounds only », 2026-10-09). Le pied le fait ainsi depuis le 2026-09-20.
const recall = (preset, scene) => post('/api/recall', preset ? { preset, scene } : { scene });
const toggleStomp = sw => post('/api/stomp', { switch: sw });
const looperOp = (op, slot) => post('/api/looper', { op, slot });
const backingOp = (op, extra) => post('/api/backing', { op, ...(extra || {}) });

// ── OÙ VA LE TAP DU RIFF, ET CE QUE DEVIENT LA PRISE (docs/compo.md §10-11) — dit sur la case RIFF elle-même
// (2026-10-29 : la cible armée et « Riff saved ✕ Drop » poussaient les boutons du top menu hors de l'écran). La case
// est là où le pied tape ; le top menu ne garde qu'une puce compacte quand la bank affichée n'a pas de case RIFF.
// Rend {cls, text, title, drop?} — `drop` = l'uid à jeter — ou null : la case dit alors l'état de golem.fm.
function riffNote(st, now) {
  const c = st.compo || {};
  const r = c.riff;
  const tg = Object.entries(c.targets || {});
  const fmOn = !!((((st.boot || {}).services || {}).fm || {}).configured);
  const many = tg.length > 1;
  if (r && (r.state === 'counting' || r.state === 'loading' || r.state === 'rec'))
    return { cls: 'rec', text: (r.state === 'rec' ? '● REC' : '… Riff') + (many ? ' · ' + r.person : ''),
             title: 'recording a riff for ' + r.person + ' — tap the Riff switch again to stop' };
  // sans golem.fm relié, le riff reste sur le golem : la case dit « kept on this golem › » (audit 31/10)
  if (r && r.state === 'held' && fmOn) {
    const left = r.until ? Math.max(0, Math.ceil(r.until - now / 1000)) : null;
    return { cls: 'held', text: 'Saved' + (left != null ? ' · ' + left + ' s' : ''), drop: r.uid,
             title: 'the riff leaves for golem.fm in ' + (left != null ? left + ' s' : '20 s') + ' — Drop keeps it on the rack, never sent' };
  }
  if (r && r.state === 'sending' && fmOn)
    return { cls: 'send', text: '→ golem.fm…', title: 'transcribing, then sending to golem.fm' };
  if (r && r.state === 'dropped')
    return { cls: 'quiet', text: 'Riff dropped', title: 'dropped: kept on the rack, never sent' };
  if (!tg.length) return null;
  if (many) return { cls: 'armed', text: '→ ' + tg.length + ' armed',
                     title: tg.map(([who, t]) => who + ': « ' + (t.title || t.id) + ' » (' + t.mode + ')').join(' · ') + ' — armed from golem.fm' };
  const [who, t] = tg[0];
  return { cls: t.blocked === 'quota' ? 'full' : 'armed', text: '→ ' + (t.title || t.id) + ' · ' + (t.blocked === 'quota' ? 'storage full' : t.mode),
           title: who + ' is armed from golem.fm: the next Riff tap writes into « ' + (t.title || t.id) + ' » (' + t.mode + ')'
             + (t.blocked === 'quota' ? ' — its golem.fm space is full, the riff would not be sent' : '') };
}
const dropRiff = (e, uid) => { e.stopPropagation(); post('/api/compo/drop', { uid }).catch(() => {}); };

// ── rangée LOOPER (remplace les stomps sur un preset looper) ──
// 3 tuiles-loop (état + progression) + ⏯ ALL + ✕ ALL (appui long). Couleurs d'ÉTAT fixes
// (rec rouge / dub orange / play vert) — la position est EXTRAPOLÉE entre deux frames WS (rAF).
// ⚠ Plus de carte de boucles EN DUR : elle vient du preset (docs/looper.md §1), servie par le
// rack dans `state.looper.slots` — {sw, src, label} par ligne. « GTR/VOX/SYN » a disparu avec
// la dérivation par entrée : deux boucles peuvent partager une source, et le LIBELLÉ est alors
// la seule chose qui les distingue (ces switches n'ont pas de LED d'état).
const LOOP_COLOR = { rec: '#e02020', dub: '#ff8c1a', play: '#2ecc71', stop: '#8a94a3', empty: '#8a94a3' };
const LOOP_ANIM = { rec: 'pulse', dub: 'ember', play: '', stop: '', empty: '' };

function LoopProgress({ looper }) {
  // barre de progression de la loop maîtresse, extrapolée côté client depuis la dernière frame
  const ref = useRef(null);
  const snap = useRef({ pos: 0, len: 0, at: 0 });
  snap.current = { pos: looper.pos || 0, len: looper.len || 0, at: performance.now() };
  useEffect(() => {
    let alive = true;
    const tick = () => {
      if (!alive) return;
      const { pos, len, at } = snap.current;
      if (ref.current) {
        const cur = len > 0 ? ((pos + (performance.now() - at) / 1000) % len) / len : 0;
        ref.current.style.width = (cur * 100).toFixed(1) + '%';
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return () => { alive = false; };
  }, []);
  return html`<div class="loop-prog"><div class="loop-prog-fill" ref=${ref}></div></div>`;
}

// ── UNE LIGNE À LA FOIS (maquette mockups/live-tiles-v2.html, 2026-10-14) : le tiers bas d'une case montre
// UN élément (instrument · son, ou effet), puis le suivant toutes les 1,5 s — rien ne glisse pendant qu'on lit, et
// la case ne déborde plus quel que soit le nombre de lanes. Un seul élément : affiché fixe.
// `hold` (index ≥ 0) : l'item TENU, sans défilement — la démo de golem.fm y met la lane qu'on entend (st.preview_lane,
// 2026-11-06 ; le bridge ne le pose jamais). Revenu à -1, le défilement reprend.
function Cycle({ items, ms = 1500, hold = -1 }) {
  const [k, setK] = useState(0);
  const n = items.length;
  const held = hold >= 0 && hold < n;
  useEffect(() => {
    if (n < 2 || held) return;
    const t = setInterval(() => setK(x => x + 1), ms);
    return () => clearInterval(t);
  }, [n, ms, held]);
  if (!n) return '';
  const at = held ? hold : k % n;
  const it = items[at];
  return html`<span class="lcy">${n > 1 ? html`<i class="lcy-n">${at + 1}/${n}</i>` : ''}
    <span class=${cls('lcy-it', it.off && 'off')} key=${held ? 'h' + at : k}>${it.tag ? html`<em class=${'li-tag ' + (it.cls || '')}>${it.tag}</em>` : ''}<b>${esc(it.t || '')}</b></span></span>`;
}

// ── LE LOOPER LISIBLE (maquette mockups/live-looper.html v2, 2026-10-13) : la position en ANNEAU, le chrono
// d'enregistrement, et l'horloge de mesure sur SW5. Tout est EXTRAPOLÉ entre deux trames WS (rAF), comme LoopProgress ;
// rien ne remplace la case ni ses classes — les animations des packs (animClass, calques) s'y posent toujours.
function LoopRing({ looper }) {
  const ref = useRef(null);
  const snap = useRef({ pos: 0, len: 0, at: 0 });
  snap.current = { pos: looper.pos || 0, len: looper.len || 0, at: performance.now() };
  useEffect(() => {
    let alive = true;
    const C = 100.5;                                     // 2πr, r = 16
    const tick = () => {
      if (!alive) return;
      const { pos, len, at } = snap.current;
      const f = len > 0 ? ((pos + (performance.now() - at) / 1000) % len) / len : 0;
      if (ref.current) ref.current.setAttribute('stroke-dashoffset', (C * (1 - f)).toFixed(1));
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return () => { alive = false; };
  }, []);
  return html`<svg class="loop-ring" viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" class="lr-bg" />
    <circle cx="20" cy="20" r="16" class="lr-fg" ref=${ref} stroke-dasharray="100.5" stroke-dashoffset="100.5" transform="rotate(-90 20 20)" /></svg>`;
}

function RecTimer({ since }) {
  const ref = useRef(null);
  useEffect(() => {
    let alive = true;
    const tick = () => {
      if (!alive) return;
      const t = Math.max(0, (performance.now() - since) / 1000);
      if (ref.current) ref.current.textContent = Math.floor(t / 60) + ':' + String(Math.floor(t % 60)).padStart(2, '0') + '.' + Math.floor((t % 1) * 10);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return () => { alive = false; };
  }, [since]);
  return html`<span class="loop-timer" ref=${ref}>0:00.0</span>`;
}

// l'horloge de la boucle maîtresse, en MESURES au tempo du preset : 4 lampes de temps + « mesure.temps / N bars »
function LoopClock({ looper, bpm }) {
  const lamps = useRef(null), txt = useRef(null);
  const snap = useRef({ pos: 0, len: 0, at: 0, bpm: 120 });
  snap.current = { pos: looper.pos || 0, len: looper.len || 0, at: performance.now(), bpm: bpm || 120 };
  useEffect(() => {
    let alive = true;
    const tick = () => {
      if (!alive) return;
      const { pos, len, at, bpm: b } = snap.current;
      const beat = 60 / b, bar = beat * 4;
      if (len > 0) {
        const p = (pos + (performance.now() - at) / 1000) % len;
        const bi = Math.floor(p / bar), be = Math.floor((p % bar) / beat);
        const nb = Math.max(1, Math.round(len / bar));
        if (txt.current) txt.current.innerHTML = `${bi + 1}.${be + 1} <small>/ ${nb} bar${nb > 1 ? 's' : ''} · ${len.toFixed(1)} s</small>`;
        if (lamps.current) [...lamps.current.children].forEach((el, k) => el.classList.toggle('on', k <= be));
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return () => { alive = false; };
  }, []);
  const none = !(looper.len > 0);
  return html`<span class="loop-clock"><span class="lc-beats" ref=${lamps}><i></i><i></i><i></i><i></i></span>
    <span class="lc-bar" ref=${txt}>${none ? html`— <small>no loop yet</small>` : ''}</span></span>`;
}

// ── BACKING TRACK : la tuile du switch portant le bloc « backing-track » devient le transport ──
// (parité pied↔écran : tap = play/pause, appui long = sheet chansons/restart/stop). La position est
// extrapolée entre deux frames WS comme le looper — mais SANS modulo (une chanson ne boucle pas).
function BackingProgress({ bk }) {
  const ref = useRef(null);
  const snap = useRef({ pos: 0, len: 0, at: 0, playing: false });
  snap.current = { pos: bk.pos || 0, len: bk.len || 0, at: performance.now(), playing: !!bk.playing };
  useEffect(() => {
    let alive = true;
    const tick = () => {
      if (!alive) return;
      const { pos, len, at, playing } = snap.current;
      if (ref.current) {
        const p = playing ? Math.min(len, pos + (performance.now() - at) / 1000) : pos;
        ref.current.style.width = (len > 0 ? (p / len) * 100 : 0).toFixed(1) + '%';
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return () => { alive = false; };
  }, []);
  return html`<div class="loop-prog"><div class="loop-prog-fill" ref=${ref}></div></div>`;
}

function BackingTile({ st, sw, color, vu, onSheet }) {
  const bk = st.backing || {};
  const loaded = !!bk.present;
  const song = (bk.songs || []).find(s => s.slug === bk.slug) || (bk.songs || [])[0] || null;
  const label = !loaded ? '⬇ not synced' : bk.playing ? '▶ PLAY' : bk.paused ? '⏸ PAUSE' : '■ READY';
  return html`<button class=${cls('lpad', 'backing', !loaded && 'dim', bk.playing && 'on')}
    style=${`--pc:${color};--vu:${vu}`}
    ...${longPress(onSheet)}
    onClick=${() => loaded && backingOp('toggle')}
    title="backing track — tap: play/pause · double-tap (foot): restart · hold: songs & stop">
    <span class="lpad-sw">#${sw}</span>
    ${/* ⚠ le glyphe DU BLOC, pas un choisi ici : « ♫ » était codé en dur alors que c'est
          l'identité de Vital au catalogue — deux blocs sans rapport portaient la même icône,
          et le backing en portait une autre (▶) sur la rangée des scènes. Une identité par
          bloc, la même partout. */''}
    <span class="lpad-ic">${ICON['backing-track'] || '▶'}</span>
    <span class="lpad-name">${song ? esc(song.title || song.slug) : 'backing'}</span>
    ${/* l'artiste sous le titre : cette tuile portait déjà le titre, pas de QUI c'était */''}
    ${song && song.artist ? html`<span class="lpad-song by"><i>${esc(song.artist)}</i></span>` : ''}
    <span class=${cls('loop-state', bk.playing ? 'play' : 'stop')}>${label}</span>
    ${loaded ? html`<${BackingProgress} bk=${bk} />` : ''}
  </button>`;
}

// sheet du backing (appui long sur la tuile) : chansons du preset (tap = charge), ⏮ restart, ■ stop.
function BackingSheet({ st, onClose }) {
  const bk = st.backing || {};
  const fmt = s => s ? Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0') : '';
  return html`<div class="live-picker" onClick=${onClose}>
    <div class="live-picker-card sm" onClick=${e => e.stopPropagation()}>
      <div class="live-picker-h"><b>♫ Backing</b><button class="close" style="position:static" onClick=${onClose}>×</button></div>
      <div class="bkg-sheet">
        ${(bk.songs || []).map(s => html`<button class=${cls('live-pick', s.slug === bk.slug && 'on')}
          onClick=${() => backingOp('select', { slug: s.slug })}>
          ${esc(s.title || s.slug)}<small class="muted"> ${esc(s.artist || '')}${s.duration_sec ? ' · ' + fmt(s.duration_sec) : ''}</small></button>`)}
        <div class="bkg-sheet-ctl">
          <button class="mini" onClick=${() => backingOp('restart')} title="restart from 0">⏮ Restart</button>
          <button class="mini" onClick=${() => backingOp('stop')} title="stop + rewind">■ Stop</button>
        </div>
      </div>
    </div>
  </div>`;
}

// ⚠ SW9 N'APPARTIENT PLUS AU LOOPER (carte validée le 2026-08-08) : « tout jouer / tout
// arrêter » descend en SW5, sur la rangée du bas — le geste qu'on fait sans regarder — et SW9
// redevient un vrai stomp. Un preset looper sans le moindre effet au pied n'avait pas de sens.
// La tuile de stomp vient du parent (`stompTile`) : une seule vérité pour les deux rangées.
// ── LE LOOPER SUR /live (docs/looper.md, amendement 2026-10-14 soir — maquette live-looper v3) ──────────────────
// Les boucles sont sur la rangée PROCHE du pied (SW 1-4), dans les grandes cases ; SW 5 garde le transport ; la rangée
// du fond redevient des stomps ordinaires (SW 6-9) et SW 10 « effacer tout ». Une case = un composant : le chrono
// d'enregistrement (un ref) vit dans la case.
function LoopTile({ st, i, vu, laneLbl }) {
  const lp = st.looper || {};
  const slots = lp.slots || [];
  // le DÉCOMPTE (une mesure de click avant la 1re boucle) : la case le dit et compte les temps
  const ci = lp.countin && lp.countin.slot === i ? lp.countin.beats : 0;
  if (ci > 0) {
    const s = slots[i] || {};
    const nm = s.label || (laneLbl ? laneLbl(s.src) : s.src) || ('loop ' + (i + 1));
    return html`<button class=${cls('lpad', 'loop', 'on', 'loop-ci')} style=${`--pc:#ff4d4d;--vu:${vu}`}
      onClick=${() => looperOp('tap', i)} title="count-in — the loop starts on the 1 · tap: cancel">
      <span class="lpad-sw">#${s.sw}</span><span class="lpad-name big">${esc(nm)}</span>
      <span class="loop-ci-n">${ci}</span>
      <span class="loop-state rec">● COUNT-IN</span><span class="loop-next">records on the 1 · tap: cancel</span>
    </button>`;
  }
  const anyLoop = (lp.len || 0) > 0;
  const recAt = useRef({});
  slots.forEach((s, k) => { if (s && s.state === 'rec') { if (!recAt.current[k]) recAt.current[k] = performance.now(); } else delete recAt.current[k]; });
  const slotTile = () => {
    const s = slots[i] || { state: 'empty', has: false };
    const stt = s.state || 'empty';
    const nm = s.label || (laneLbl ? laneLbl(s.src) : s.src) || ('loop ' + (i + 1));
    const color = LOOP_COLOR[stt];
    const anim = LOOP_ANIM[stt];
    const label = { empty: 'empty', rec: '● RECORDING', dub: '● OVERDUB', play: '▶ PLAYING', stop: '■ STOPPED' }[stt];
    // le GESTE SUIVANT, écrit dans la case (les gestes du pied ne changent pas : la page dit ce qu'ils font)
    const next = { empty: anyLoop ? 'tap: record' : 'tap: record — the first loop sets the length',
                   rec: 'tap: close the loop', dub: 'tap: back to play',
                   play: 'tap stop · 2× overdub · hold clear', stop: 'tap: play · hold: clear' }[stt];
    // la SOURCE en mots (« Keys », « Guitar 2 ») — l'id de lane (« keys-pads-1 ») n'est pas un nom
    const src = (() => { const m = String(s.src || '').match(/^([a-z-]+?)(?:-(\d+))?$/); if (!m) return '';
      const base = { 'keys-pads': 'Keys', keys: 'Keys', pads: 'Pads', guitar: 'Guitar', bass: 'Bass', voice: 'Voice', drums: 'Drums', line: 'Line' }[m[1]] || m[1];
      return base + (m[2] && m[2] !== '1' ? ' ' + m[2] : ''); })();
    return html`<button class=${cls('lpad', 'loop', stt === 'empty' && 'dim', (stt === 'play' || stt === 'rec' || stt === 'dub') && 'on', animClass(anim))}
      style=${`--pc:${color};--vu:${vu}`}
      ...${longPress(() => s.has || stt !== 'empty' ? looperOp('clear', i) : null)}
      onClick=${() => looperOp('tap', i)}
      title=${`loop ${nm} (records ${laneLbl ? laneLbl(s.src) : s.src}) — tap: empty→rec, rec→play, playing→stop · double-tap/⊕ = overdub · hold = clear`}>
      <span class="lpad-sw">#${s.sw}${s.master && stt !== 'empty' ? html`<b class="loop-master" title="this loop set the length of all">MASTER</b>` : ''}</span>
      <span class="lpad-name big">${esc(nm)}</span>
      ${src ? html`<span class="loop-src">${esc(src)}</span>` : ''}
      ${(stt === 'play' || stt === 'dub') && anyLoop ? html`<${LoopRing} looper=${lp} />` : ''}
      ${stt === 'rec' ? html`<${RecTimer} since=${recAt.current[i] || performance.now()} />` : ''}
      ${(stt === 'play' || stt === 'dub') ? html`<span class="loop-dub" onClick=${e => { e.stopPropagation(); looperOp('dub', i); }}
        title="overdub — stack a layer on this loop">⊕</span>` : ''}
      ${stt !== 'empty' ? html`<span class="loop-meter" title="what this loop plays"><i style=${'width:' + Math.round(Math.min(1, s.peak || 0) * 100) + '%'}></i></span>` : ''}
      <span class=${cls('loop-state', stt)}>${label}</span>
      <span class="loop-next">${next}</span>
    </button>`;
  };
  return slotTile();
}

function LoopClearTile({ st, vu }) {
  const anyLoop = ((st.looper || {}).len || 0) > 0;
  return html`<button class=${cls('lpad', 'loop', 'ctl', 'danger', !anyLoop && 'dim')} style=${`--pc:#e02020;--vu:${vu}`}
      ...${longPress(() => looperOp('clear_all'), 1200)}
      title="switch 10 — HOLD to delete all loops">
      <span class="lpad-sw">#10</span>
      <svg class="loop-clear-ic" viewBox="0 0 40 40"><circle cx="20" cy="20" r="16" /><text x="20" y="25.5" text-anchor="middle">✕</text></svg>
      <span class="lpad-name">Clear all</span><span class="loop-next">hold 1 s</span>
    </button>`;
}


export function LivePage({ rig }) {
  // aiguillage de vue — AVANT tout hook propre au pédalier (un composant ne peut pas appeler
  // ses hooks conditionnellement : la vue timeline est donc un composant à part entière,
  // avec ses propres hooks, pas une branche de rendu au milieu de celui-ci).
  //
  // ── LA VUE EST UNE CONSÉQUENCE, PLUS UN CHOIX (2026-08-04) ────────────────────────────────
  // Il y avait ici un sélecteur Pedalboard/Chart/Timeline dans la topbar. Il n'existait que
  // pour couvrir le seul cas non déclaré : un preset portant À LA FOIS un bloc Standard et un
  // bloc Arrangement — deux structures, deux chefs d'orchestre. Le reste du temps il ne servait
  // qu'à réparer un mauvais atterrissage, en scène, à la main.
  //
  // La doctrine du dépôt dit l'inverse (commit d9b9bff, blocs qui s'excluent) : « un preset EST
  // un morceau », et « empêcher l'état impossible vaut mieux que le gérer après coup ». Les deux
  // vues sont DÉJÀ revendiquées par des blocs — `standard` et `arrangement` sont tous deux
  // `unique` et `foot_scene_claim`. La vue en découle donc, et le bloc Standard porte le seul
  // arbitrage qui reste : son param `live_view` (tiroir ▸ Song), au cas où on veuille la grille
  // au mur mais le pédalier à l'écran.
  //
  // Le mode garde le dernier mot quand AUCUN bloc ne revendique (Show -> pupitre).
  const st = rig.state;
  // A preset may be installed outside this page; switching presets refreshes its scenes and blocks.
  const { data: presets } = useAsync(() => fetch('/api/presets').then(r => r.json()), [st.preset_id]);
  // ⚠ CORRIGÉ le 2026-08-04, le jour même : « bloc arrangement -> timeline » était FAUX, et le
  // commentaire du chef d'orchestre 40 lignes plus bas le disait déjà — « une pastille suffit
  // ici, ce qu'on veut au pied c'est où je suis / ce qui vient, PAS une timeline ». Un
  // arrangement n'est pas une partition à lire, c'est un chef qui bascule les scènes tout seul :
  // il n'a aucune raison de prendre l'écran. Une grille de standard, si.
  // Le pupitre reste ce pour quoi il a été fait — le batteur. Il se demande MORCEAU PAR MORCEAU
  // (`arrangement.params.live_view = "Timeline"`), ou par défaut dans la carte du mode (`ui.live`) :
  // depuis la fusion Show → Gig (docs/modes.md §7 bis, 2026-09-18) aucun mode d'usine ne le déclare,
  // et c'est bien ainsi — une soirée mélange des morceaux au pied et des morceaux à la grille.
  // ── LA GRILLE SUIT LE PIED (2026-08-07, demande) ─────────────────────────────────
  // `live_view: Chart` collait la grille à l'écran EN PERMANENCE, dès le rappel du preset : on
  // perdait ses stomps pendant tout le temps où on ne jouait pas le morceau. La grille ne sert
  // qu'à UN moment — pendant qu'il tourne. Elle suit donc l'état du lecteur : le switch qui
  // lance le standard bascule la vue, et l'arrêt rend le pédalier. Un seul geste, celui qu'on
  // fait déjà.
  // Le réglage du tiroir ne change pas de nature, il dit ce qu'il a toujours dit — QUELLE vue ce
  // preset veut : `Chart` = la grille pendant le morceau · `Pedalboard` = jamais, on garde ses
  // stomps (la grille est au mur, ou sur le téléphone du musicien).
  const stdP = st.standard_block || null;
  const stdPlaying = !!(st.standard && st.standard.playing);
  const arrV = ((st.arrangement || {}).present && (st.arrangement || {}).live_view) || null;
  // ── L'ARRANGEMENT SUIT LE LECTEUR (2026-09-24 : « quand je mets Play, je suis en aveugle ») ──
  // Même règle que la grille : PENDANT qu'un arrangement tourne (décompte compris), /live montre le
  // pupitre — la Timeline — et rend le pédalier à l'arrêt. La chanson peut dire non (`live_view =
  // Pedalboard` : je garde mes stomps, la pastille suffit) ou oui en permanence (`Timeline`). La
  // décision du 04/08 (« un chef, pas une partition ») était juste au pied ; elle ne l'est plus quand
  // c'est l'utilisateur qui lance, depuis Songs, pour voir ce que fait chaque partie.
  const arrRun = !!((st.arrangement || {}).running);
  // la vue du MODE (Settings ▸ Mode ▸ Live screen) est le défaut de TOUTES les branches : une chanson à grille Standard
  // retombait sur « pedalboard » en dur — 2026-10-15 : « en Timeline, si je clique sur une autre chanson, je
  // reviens au pédalier » (Chill Jazz porte « Rooftop Prowl »). La grille ne prend l'écran que PENDANT qu'elle joue.
  // … sauf si CET écran a basculé (bouton de vue des outils, le temps du mode — live-tools.js)
  const vOver = useViewOverride(modeViewKey(st));
  const mv = ((st.mode || {}).ui || {}).live;
  const modeView = vOver || (['timeline', 'rehearsal'].includes(mv) ? mv : 'pedalboard');
  // le PUPITRE que réclame un morceau qui tourne : la Répète si l'écran y est déjà, sinon le Concert (docs/live-pages.md)
  const stand = modeView === 'rehearsal' ? 'rehearsal' : 'timeline';
  const view = stdP && stdP.standard
      ? (stdP.live_view !== 'Pedalboard' && stdPlaying ? 'chart' : modeView)
    : arrV === 'Timeline' ? stand
    : (arrRun && arrV !== 'Pedalboard') ? stand
    : modeView;
  if (view === 'chart') return html`<${ChartLive} rig=${rig} presets=${presets} />`;
  if (view === 'timeline' || view === 'rehearsal') return html`<${StagePage} rig=${rig} page=${view} />`;
  return html`<${PedalboardLive} rig=${rig} presets=${presets} />`;
}

function PedalboardLive({ rig, presets }) {
  // LES PÉDALES SUR LES STOMPS (menu de vue ▸ « Pedals on the stomps ») : les moteurs de golem-fx, chargés à la demande
  const pedalsOn = useLivePedals();
  const [visOk, setVisOk] = useState(visualsReady());
  useEffect(() => { if (pedalsOn && !visOk) loadVisuals().then(() => setVisOk(true)).catch(() => {}); }, [pedalsOn]);
  const pedals = pedalsOn && visOk;
  // au boot kiosk direct sur /live le Designer n'est jamais passé : on hydrate ICON/NAME ici aussi
  useAsync(() => fetch('/api/effects').then(r => r.json()).then(d => { hydrateBlockMeta(d.effects || d, d); return d; }), []);
  const st = rig.state;
  const list = presets || [];
  // L'ESSAI (sandbox-try, docs/patches.md §19) n'est jamais dans la liste des presets : on va le chercher
  // tel que le rack le sert, pour que la barre de scènes et les tuiles soient celles de ce qui sonne.
  // …et un PATCH joué comme un preset (`patch:<id>`, docs/patches.md) non plus.
  const isTrial = st.preset_id === 'sandbox-try' || String(st.preset_id || '').startsWith('patch:');
  const { data: trial } = useAsync(() => isTrial
    ? fetch('/api/live/trial').then(r => r.ok ? r.json() : null).catch(() => null) : Promise.resolve(null), [st.preset_id, st.sandbox_rev]);
  const current = list.find(p => p.id === st.preset_id) || (isTrial && trial && trial.scenes ? trial : null);
  // UN CLAVIER ABSENT N'EST PAS UNE ALERTE DE SCÈNE (2026-10-13 : « ça prend trop de place, et ce n'est pas
  // vraiment une erreur quand la carte n'a pas assez d'entrées — les entrées paramétrées, elles, sont accessibles »).
  // La règle d'avant (portage desktop) ne masquait « KEYS UNPLUGGED » que sur un preset sans clavier ; depuis que
  // chaque preset d'usine a une lane Keys, la puce revenait sur tous. Elle ne revient plus : l'absence du clavier se
  // lit sur l'onglet de sa lane (Designer, USB orange) et dans Soundcard. ⚠ La sentinelle (golem_midi.lua) remonte
  // aussi « pedalboard mute » et « Whammy mute » (Reaper qui tient le MIDI de la carte) : CES alertes-là restent.
  const midiIssues = ((st.midi && st.midi.issues) || []).filter(i => !/keys[- ]controller/i.test(i));
  // une puce d'alerte mène à sa ligne de Health — sauf en mode verrouillé (voir la barre plus bas)
  const locked = !!(st.mode && st.mode.ui && st.mode.ui.locked);
  const toHealth = locked ? null : fid => () => go('system/sys/health/' + fid);
  const healthHint = locked ? '' : ' · tap: Health';
  const scenes = (current && current.scenes) || [];
  const colors = (current && current.colors) || {};   // override couleurs (preset.colors[sceneId|stompType])
  // labels des 3 slots looper = les ENTRÉES (même cascade que le Designer : nom preset > rôle patch >
  // défaut) — plus de GTR/VOX/SYN en dur (retour 2026-07-20)
  const _imap = st.inputmap || {};
  const _chainLbl = i => {
    const nm = (current && current.names) || {};
    if (nm[i]) return nm[i];
    if (i === 'k') return (_imap.midi && _imap.midi.label) || 'Keys';
    const e = (_imap.inputs || []).find(x => String(x.ch) === String(i) || String(x.ch).split('-').includes(String(i)));
    return (e && e.role !== 'none' && e.label) || 'Input ' + i;
  };
  const laneLbl = k => _chainLbl(k);
  const anims = (current && current.anims) || {};      // animation par tuile (preset.anims[sceneId|stompType])
  // packs non livrés : leur CSS se charge à la demande (docs/anim-packs.md)
  useEffect(() => { Object.values(anims).forEach(v => ensurePackCss(animPackOf(v))); },
    [Object.values(anims).join()]);
  const vu = (st.levels && (st.levels.in1 ?? st.levels.guitar)) || 0;     // niveau de jeu 0..1 (VU OSC, entrée 1) -> glow réactif
  const tunerOn = !!(st.tuner && st.tuner.on);
  const clickOn = !!(st.click && st.click.on);   // métronome : on/off DEPUIS LA SCÈNE (topbar Live)

  // BANK #NN, les flèches ◀▶ et les deux navigateurs vivent dans `live-bankbar.js` : la
  // navigation appartient à la PAGE, pas à cette vue — la grille et le pupitre l'affichent aussi.

  // Stomps = 5 positions FCB (6-10), chacune tient les blocs assignés (block.foot). st.stomps est clé par switch.
  const stompOn = st.stomps || {};
  const switches = (current && current.switches) || EMPTY_SW;
  const loopOn = !!((current && current.looper) || (st.looper && st.looper.enabled));
  // switch portant le bloc « backing-track » : sa tuile devient le TRANSPORT (comme le pied)
  const backingSw = switches.find(sw => (sw.blocks || []).some(b => b.type === 'backing-track'));
  const [bkgSheet, setBkgSheet] = useState(false);
  // la case RIFF de la bank affichée : elle dit la cible et la prise (riffNote) ; sans elle, une puce du top menu
  const riffSw = switches.find(sw => (sw.blocks || []).some(b => b.type === 'compo'));
  // les 20 s de fenêtre de drop se comptent à la seconde
  const riffHeld = ((st.compo || {}).riff || {}).state === 'held';
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!riffHeld) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [riffHeld]);

  // magnétophone (perf-rec) = réglage de MODE (off/manuel/auto, décision 2026-07-21) :
  // le déclenchement vit ICI, plus dans la Library. En AUTO, on enregistre dès l'entrée sur /live.
  const perfOn = !!(((st.mode || {}).services || {}).perfrec);
  const perfAuto = ((st.mode || {}).perfrec_mode || 'manual') === 'auto';
  const [perf, setPerf] = useState(null);
  // état LIVE via le WS (state.perf, poussé par le bridge) — le poll /api/perf reste en secours ;
  // le badge suit AUSSI un REC lancé au pied (bloc Rec / perf_foot), hors gating du mode.
  const perfSt = st.perf || perf || {};
  const recOn = !!perfSt.recording;
  const [, recTick] = useState(0);
  useEffect(() => {
    if (!recOn) return;
    const t = setInterval(() => recTick(x => x + 1), 1000);
    return () => clearInterval(t);
  }, [recOn]);
  const recSecs = recOn && perfSt.started_at
    ? Math.max(0, Math.floor((Date.now() - new Date(perfSt.started_at).getTime()) / 1000)) : 0;
  const recMmss = Math.floor(recSecs / 60) + ':' + String(recSecs % 60).padStart(2, '0');
  useEffect(() => {
    if (!perfOn) return;
    let alive = true;
    const load = () => fetch('/api/perf').then(r => r.json()).then(d => alive && setPerf(d)).catch(() => {});
    load();
    if (perfAuto) fetch('/api/perf').then(r => r.json()).then(d => { if (alive && !d.recording) post('/api/perf/start'); }).catch(() => {});
    const t = setInterval(load, 3000);
    return () => { alive = false; clearInterval(t); };
  }, [perfOn, perfAuto]);
  // ⚠ un REC refusé (place disque, veto de mode) répondait en silence : le bouton clignotait et
  // rien ne partait. Sur scène, « rien ne s'est passé » est le pire des retours — on affiche le
  // motif, qui est écrit pour être lu d'un mètre (bridge/disk.py).
  const [recErr, setRecErr] = useState('');
  useEffect(() => { if (!recErr) return; const t = setTimeout(() => setRecErr(''), 6000); return () => clearTimeout(t); }, [recErr]);
  // ⚠ `post()` JETTE sur un code d'erreur et jette AUSSI le corps : le motif du refus était
  // perdu, et l'écran n'affichait qu'« /api/perf/start → 507 ». On lit la réponse à la main.
  const toggleRec = () => fetch('/api/perf/' + (recOn ? 'stop' : 'start'), { method: 'POST' })
    .then(r => r.json().catch(() => ({})).then(d => setRecErr(r.ok ? '' : (d.error || 'recording refused'))))
    .catch(() => setRecErr('the rack did not answer'))
    .then(() => setTimeout(() => fetch('/api/perf').then(r => r.json()).then(setPerf).catch(() => {}), recOn ? 1200 : 400));

  // cluster d'actions LIVE dans la topbar (2026-07-24, charte agent UX : « banc de
  // switches » segmenté ancré à droite — actions d'état, PAS des onglets : remplissage plein).
  // + banc INFO assorti (latence / xruns) : lecture seule, même charte que le banc d'actions
  const arrSt = st.arrangement || {};
  // les outils du top menu (Mixer · Tuner · ✎ · Click · Lock · Rec) et leurs panneaux : live-tools.js, partagé avec la
  // vue Timeline. Le pédalier s'assigne ICI, sur la grille qu'on joue (docs/arrangement.md §4 bis).
  const tools = useLiveTools({ rig, st, view: 'pedalboard', presetId: isTrial ? null : st.preset_id,
    rec: { perfOn, on: recOn, toggle: toggleRec, title: recOn ? 'stop recording — save the take' : 'record the set' } });
  useEffect(() => {
    setTopAction(html`<div class="live-info">
      ${/* CHEF D'ORCHESTRE : la vue pédalier ne montrait RIEN de l'arrangement — un musicien en
            mode Pedalboard ne savait pas où il en était, alors que ses scènes basculaient toutes
            seules. Une pastille suffit ici : la page est déjà pleine, et ce qu'on veut au pied
            c'est « où je suis / ce qui vient », pas une timeline. */''}
      ${arrSt.present ? html`<span class=${cls('live-inf', 'live-arr', arrSt.running && 'on', !arrSt.running && !arrSt.counting && 'arr-ready')}
        title=${arrSt.counting ? 'count-in — the song starts at the end of it'
          : arrSt.running ? 'section ' + (arrSt.index + 1) + '/' + arrSt.count
              + (arrSt.next ? ' · next: ' + arrSt.next : ' · last one, it holds')
              + (arrSt.mode === 'foot' ? ' · tap the switch for the next one' : '')
          : 'arrangement ready — this song has ' + arrSt.count + ' sections that switch the scenes by themselves. Tap the arrangement switch (or ▶ Play) to start'}>
        ${/* PRÊT = le pictogramme seul, en vert (2026-10-15) ; l'infobulle dit ce qu'il veut dire */''}
        ▤${arrSt.counting ? ' count-in' : arrSt.running ? ' ' + (arrSt.name || '—') : ''}
        ${arrSt.running && arrSt.next ? html`<em>→ ${esc(arrSt.next)}</em>` : ''}
      </span>` : ''}
      ${/* PLUS DE BPM ICI (2026-10-20) : la barre de navigation le montre déjà, et le « _ » de /golem_ bat déjà —
            le top menu gagne la place de la lampe et du nombre */''}
      ${/* la latence, sans préfixe (2026-10-11 : « enlève juste le DEV ») : « 8.9 ms » partout, l'infobulle dit d'où
            vient le chiffre — mesure ALSA sur le rack, estimation de l'OS ailleurs ; le ⚡ du CPU boost reste */''}
      <span class="live-inf" title=${(st.audio_metrics && st.audio_metrics.platform ? (st.audio_metrics.source === 'reaper' ? 'input + output device latency reported by REAPER; physical loopback not measured' : 'nominal input + output buffer estimate') : 'round-trip latency from ALSA') + (st.cpu_boost ? ' · ⚡ CPU boost on (Gig / Show)' : '')}>${st.latency_ms != null ? st.latency_ms + ' ms' : '— ms'}${st.cpu_boost ? html` <b class="boost-ic" title="CPU boost on — follows the mode (Gig / Show)">⚡</b>` : ''}</span>
      ${/* UNE PUCE D'ALERTE MÈNE À SA LIGNE DE HEALTH (docs/assistant.md §3, mockups/health-fix.html) : le fait, son
            incident et son « Fix… » s'y trouvent. Jamais dans un mode verrouillé (Gig, Show) : un doigt qui frôle la
            barre ne doit pas faire quitter /live sur scène — la puce reste une information, son infobulle aussi. */''}
      ${st.audio && st.audio.ok === false ? html`<span class=${cls('live-inf warn', toHealth && 'tap')} onClick=${toHealth && toHealth('audio')}
        title=${(st.audio.why || 'audio stalled') + (st.audio.fix ? ' · ' + st.audio.fix : '') + healthHint}
        >⚠ ${st.audio.card ? 'NO CARD' : 'NO AUDIO'}${st.audio.fix && /waiting|recovering/.test(st.audio.fix) ? ' …' : ''}</span>` : ''}
      ${/* même raison que NO AUDIO : la sentinelle MIDI portait « lane Keys morte, masque
             midiins périmé » et sa réparation, sans que rien ne l'affiche. Un clavier muet se
             cherchait alors à la main, bloc par bloc. */''}
      ${st.midi && st.midi.ok === false && midiIssues.length ? html`<span class=${cls('live-inf warn', toHealth && 'tap')} onClick=${toHealth && toHealth('pedalboard')}
        title=${midiIssues.join(' · ') + (st.midi.fix ? ' — ' + st.midi.fix : '') + healthHint}
        >⚠ NO MIDI</span>` : ''}
      ${/* même famille : un ampli NAM ré-instancié VIDE (course avec son worker de chargement,
             2026-09-07) sonnait comme un boost sec, sur 4 scènes, et rien ne le disait. golem_rig
             relit en clair ce que chaque plugin a chargé, 2 s après le recall, et l'écrit ici. */''}
      ${st.rig_check && st.rig_check.ok === false ? html`<span class=${cls('live-inf warn', toHealth && 'tap')} onClick=${toHealth && toHealth('playing')}
        title=${(st.rig_check.issues || []).map(i => i.track + ': ' + i.kind + ' \u00ab ' + i.expected + ' \u00bb not loaded'
                 + (i.repaired ? ' \u2014 reloading' : '')).join(' \u00b7 ') + healthHint}
        >⚠ FX FILE</span>` : ''}
      ${/* une lane du preset demande une entrée que CETTE carte n'a pas : pas montée, et dit
            (input-map.md §7). Le preset est intact — choisir une autre entrée dans le Designer. */''}
      ${/* un recall REFUSÉ (compile) : le rack ne joue PAS ce qu'il affiche — dit ici, jamais en silence (audit 2026-09-13) */''}
      ${st.rig_error ? html`<span class=${cls('live-inf warn', toHealth && 'tap')} onClick=${toHealth && toHealth('playing')} title=${'last recall was refused: ' + st.rig_error + ' — fix the preset in the Designer' + healthHint}>⚠ RIG</span>` : ''}
      ${/* ⌂ (l'accueil) et ⚠ LANES ont quitté la barre (2026-10-11 : « on s'en fout ») : l'accueil se lit et se
            change dans Settings ▸ System, les lanes non montées se voient dans le Designer (onglet orange) */''}
      ${/* LE RIFF SE DIT SUR SA CASE (riffNote) : ici, UNE puce compacte seulement si la bank affichée n'a pas de
            case RIFF — la cible armée ou la prise, jamais les deux, jamais plus large que 120 px (le riff gardé n'y dit que
            ses secondes, à côté de Drop). Sans golem.fm
            relié, un riff gardé mène à l'appairage (2026-10-13 : le tuto RIFF « envoie sur golem.fm »). */''}
      ${!riffSw && (() => {
        const r = (st.compo || {}).riff;
        const fmOn = !!((((st.boot || {}).services || {}).fm || {}).configured);
        if (r && !fmOn && (r.state === 'held' || r.state === 'sending')) return html`<span class="live-inf compo tap"
            title="the riff is kept on this golem — link golem.fm to send it to your riffs" onClick=${() => go('system/connect/golemfm')}
            >🔥 Kept · <u>link ›</u></span>`;
        const n = riffNote(st, now);
        if (!n) return '';
        return html`<span class=${cls('live-inf compo', 'cn-' + n.cls)} title=${n.title}><b class="compo-t">🔥 ${esc(n.drop ? n.text.replace(/^Saved · /, '') : n.text.replace(/^→ /, ''))}</b>${n.drop
          ? html`<span class="compo-drop" role="button" title="Drop: keep it on the rack, never sent" onClick=${e => dropRiff(e, n.drop)}>✕</span>` : ''}</span>`; })()}
      ${/* une lane que CETTE carte ne peut pas prendre (la basse d'un preset de groupe, à la maison sur une
            carte à 2 entrées) : RETIRÉE de la barre (2026-10-07 : « trop d'informations — bass 1 off »).
            Un instrument absent n'est pas un état à surveiller sur scène ; le Designer le dit sur la lane
            (« not mounted »), là où on peut y faire quelque chose. */''}
      ${/* pédalier mesuré mais NON confirmé : il continue de marcher (le canal est le bon),
             on le signale sans crier. Avant, une sonde muette basculait en silence sur une autre
             puce, au canal différent — pédalier mort et aucun mot nulle part. */''}
      ${st.pedalboard && st.pedalboard.stale ? html`<span class=${cls('live-inf', toHealth && 'tap')} onClick=${toHealth && toHealth('pedalboard')}
        style="color:var(--accent)"
        title=${`${st.pedalboard.name || st.pedalboard.id}: measured earlier, but the last identity probe got no answer. Still in use — its MIDI channel is the right one.` + healthHint}
        >⚠ PEDAL?</span>` : ''}
      ${/* ÉCRÊTAGE D'ENTRÉE (2026-09-14) : la DI touchait 0 dBFS sur une prise entière et rien ne le
             disait — un gain de carte trop haut se règle au bouton, pas dans un preset. Visible 3 s
             après le dernier plateau. */''}
      ${Object.entries(st.clip || {}).filter(([, c]) => c.age < 3).map(([k, c]) => html`<span class="live-inf warn"
        title=${`input ${k.slice(2)} hits 0 dBFS (${c.count} time${c.count > 1 ? 's' : ''}) — the converter is clipping: lower the gain on the interface, not in the preset`}
        >⚠ IN ${k.slice(2)} CLIP</span>`)}
      ${/* plus de pastille « ⛓ <patch> » (2026-10-13) : le titre de la ligne de bank dit déjà quel patch joue —
            le même nom deux fois sur un écran de scène, c'est de la place perdue */''}
      ${st.preset_id === 'sandbox-try' ? html`<span class="live-inf" style="color:var(--accent)"
        title="a draft from the Designer is playing — scenes and stomps below are its own; it is not a preset and sits in no bank. Save it from the Designer to keep it."
        >⛓ trying${current && current.name ? ' · ' + esc(String(current.name).replace(/^⛓\s*/, '')) : ''}</span>` : ''}
      ${st.xruns_recent ? html`<span class=${cls('live-inf warn', toHealth && 'tap')} onClick=${toHealth && toHealth('dropouts')} title=${'audio dropouts in the last 10 min' + healthHint}>⚠ ${st.xruns_recent}</span>` : ''}
    </div>
    <div class="live-acts">${tools.buttons}
    </div>`);
  // ⚠ setTopAction est PUBLIÉ DEPUIS UN EFFET : ce qu'il montre ne change que si une dépendance
  // change. La pastille d'arrangement doit donc lister CE QU'ELLE AFFICHE — sans quoi elle reste
  // figée sur son premier rendu (ou absente), sans la moindre erreur. C'est le même piège que le
  // slot d'action écrasé par un hub : un effet ne se plaint jamais de ne pas s'être rejoué.
  }, [tunerOn, clickOn, st.live_lock, recOn, perfOn, st.latency_ms, st.xruns_recent,
      st.audio_metrics && st.audio_metrics.source, st.audio_metrics && st.audio_metrics.platform,
      st.audio && st.audio.ok, st.midi && st.midi.ok, midiIssues.join('|'), st.pedalboard && st.pedalboard.stale,
      st.rig_check && st.rig_check.t, st.cpu_boost, st.rig_error, locked,
      ...tools.deps,
      // la puce du riff : sans ces clés elle restait figée sur son premier rendu
      !!riffSw, JSON.stringify([(st.compo || {}).targets, (st.compo || {}).riff]),
      !!((((st.boot || {}).services || {}).fm || {}).configured), riffHeld && now,
      arrSt.present, arrSt.running, arrSt.counting, arrSt.name, arrSt.next, arrSt.index]);
  useEffect(() => () => setTopAction(null), []);

  // un panneau d'outil ouvert (Mixer, Tuner, ✎) prend la place de la grille, sous le top menu
  if (tools.view) return tools.view;
  // une ligne de pile : glyphe · nom · lane (GTR/BASS/VOX/KEYS ; services : BACK/REC/CLICK…)
  const LANE_TAG = { guitar: 'GTR', bass: 'BASS', voice: 'VOX', keys: 'KEYS', 'keys-pads': 'KEYS', pads: 'PADS', drums: 'DRUM', line: 'LINE', service: 'SVC' };
  const ROLE_GLYPH = { guitar: '▦', bass: '▦', voice: '◎', keys: '♫', 'keys-pads': '♫', pads: '▦', drums: '◍', line: '〜' };
  const Pile = lines => html`<span class=${cls('lpile', lines.length > 3 && 'scroll')} style=${`--n:${lines.length}`}>
    <span class="lpile-in">${lines.map(l => html`<span class=${cls('lpl', l.off && 'off')}>
      <i class="lpl-g">${l.g}</i><b class="lpl-t">${esc(l.t)}</b>${l.lane ? html`<em class=${'lpl-lane ' + (l.lane === 'voice' ? 'vox' : l.lane === 'service' ? 'svc' : l.lane === 'bass' ? 'bass' : l.lane === 'drums' ? 'drums' : (l.lane === 'keys' || l.lane === 'keys-pads' || l.lane === 'pads') ? 'keys' : 'gtr')}>${LANE_TAG[l.lane] || String(l.lane).toUpperCase()}</em>` : ''}
    </span>`)}</span></span>`;
  // ── LES CASES À BLOC SPÉCIAL (2026-10-08, maquette mockups/live-specials-scenes.html, variante 2) : un
  // switch qui ne porte QUE des blocs de service n'a plus l'air d'un stomp ni d'une scène — fond noir, cadre de la
  // couleur de sa catégorie, bandeau de titre (SONG, PLAYERS, REC, CLICK, TOOL). Une case qui mêle un effet et un
  // service reste un stomp : c'est l'effet qu'on y joue.
  const SPECIAL = SPECIAL_CAT;                     // la table partagée (designer-model.js)
  const specialOf = bs => (bs || []).length && bs.every(b => SPECIAL[b.type]) ? SPECIAL[bs[0].type] : null;
  const laneCls = l => l === 'voice' ? 'vox' : l === 'service' ? 'svc' : l === 'bass' ? 'bass' : l === 'drums' ? 'drums'
    : (l === 'keys' || l === 'keys-pads' || l === 'pads') ? 'keys' : 'gtr';
  // un bloc coupé dans la scène courante (scenes[].off = ids/types coupés) : sa ligne s'éteint
  const blockOffInScene = bk => { const sc = ((current && current.scenes) || []).find(x => x.id === st.scene_id) || {};
    const off = sc.off || []; return off.includes(bk.id) || off.includes(bk.type); };
  // le nom qui tient sur UNE ligne : l'archétype nommé (« Big Muff »), sinon le libellé de la capture
  // sans sa marque (« Electro-Harmonix Op-Amp Big Muff » -> « Op-Amp Big Muff »), sinon le nom
  // court du catalogue (« Tape », « PEQ ») — jamais une ellipse à deux mètres
  const pileName = bk => {
    if (bk.variant && ARCH_NAME[bk.variant]) return ARCH_NAME[bk.variant];
    const lb = String(bk.label || '').trim();
    if (lb && lb.length <= 16) return lb;
    if (lb) { const noBrand = lb.split(/\s+/).slice(1).join(' '); if (noBrand.length && noBrand.length <= 16) return noBrand; }
    return SHORT[bk.type] || (NAME[bk.type] || bk.type).split(' (')[0];
  };
  const stompTile = (sw, i) => {
        if (backingSw && sw.sw === backingSw.sw) {
          return html`<${BackingTile} st=${st} sw=${sw.sw} color=${colors[sw.sw] || PALETTE[i]} vu=${vu}
            onSheet=${() => setBkgSheet(true)} />`;
        }
        const used = (sw.blocks || []).length > 0;
        // ── UN BLOC DE SERVICE NE SE LIT PAS DANS `stomps` (2026-08-04) ────────────────────
        // `state.stomps` répond à « ce bloc est-il ACTIVÉ dans la scène ? » — dérivé du preset au
        // rappel (`_stomp_states`). Pour un FX c'est bien l'état. Pour un service scene-invariant
        // (standard, drums, sample, click…) c'est TOUJOURS vrai : le bloc est monté en permanence,
        // ce qui bouge c'est qu'il JOUE ou non. La tuile #10 d'un Standard était donc allumée dès
        // le rappel du preset et n'a jamais pu s'éteindre — mesuré : `standard.playing=false` avec
        // `stomps={'10':true}`. Elle n'était pas « collée après le stop », elle n'a jamais suivi.
        // La rangée des scènes (1-5) fait déjà cette lecture par service : on l'aligne ici.
        const svcB = (sw.blocks || []).find(b => SVC_STATE[b.type]);
        const on = used && (
            sw.whammy ? st.whammy_on
          : svcB ? SVC_STATE[svcB.type](st, svcB, recOn)
          : !!stompOn[sw.sw]);
        // vrais noms du catalogue ("Wah + Pedal"), pas les types bruts — l'état on/off est porté
        // par le fond + le contour (plus de dot : 4e canal redondant, illisible à 2 m)
        const name = sw.blocks.map(b => (NAME[b.type] || b.type).split(' (')[0]).join(' + ');
        // comme les scènes : l'anim reste sur le stomp OFF (atténuée en CSS via .dim) — identité, pas état
        // UNE CASE VIERGE a son animation par défaut (2026-10-08) : le « Monster » du SW4 de Paper Kite, sur sa
        // couleur — sauf si le preset en règle une pour ce switch
        const anim = used ? (anims[sw.sw] || '') : (anims[sw.sw] || EMPTY_ANIM);
        // ── LA PILE (maquette A, 2026-09-15) : un switch qui tient PLUSIEURS blocs (souvent de
        // lanes différentes : phaser guitare + PEQ voix) empile UNE LIGNE PAR BLOC — glyphe, nom,
        // étiquette de lane — au lieu de deux glyphes et d'un nom composé. L'état du switch reste
        // porté par le fond et le contour ; chaque ligne dit en plus si SON bloc est coupé dans la
        // scène. Au-delà de trois lignes, la pile défile toute seule (CSS, --n).
        // …et un switch à UN seul bloc prend la même pile (2026-09-15 : « c'est nice ») —
        // une seule grammaire sur la rangée, la lane se lit partout
        const pile = used;
        const sp = used ? specialOf(sw.blocks) : null;
        // case SPÉCIALE : la couleur de sa catégorie est aussi celle de son animation (--pc = --sc) ; pas de
        // pictogrammes de gestes (2026-10-08 : « des pictos blancs d'une ancienne version ») — le bandeau dit
        // ce qu'est la case, le nom ce qu'elle fait
        const dfltMonster = !used && !anims[sw.sw];          // le monstre par défaut : sa variante suit le numéro
        return html`<button class=${cls('lpad', 'stomp', !used && 'empty', used && !on && 'dim', on && 'on', sp && 'special', animClass(anim), dfltMonster && monsterOf(sw.sw))} data-doc=${'live.stomp.' + sw.sw}
          disabled=${!used} style=${sp ? `--pc:${sp[1]};--sc:${sp[1]};--vu:${vu}` : `--pc:${colors[sw.sw] || (used ? PALETTE[i] : EMPTY_COLOR)};--vu:${vu}`} onClick=${() => used && toggleStomp(sw.sw)}>
          ${dfltMonster ? MONSTER_LAYERS : ''}
          ${sp ? html`<span class="lpad-band">#${sw.sw} ${sp[0]}</span>` : ''}
          <span class="lpad-sw">#${sw.sw}</span>
          ${/* LE RIFF DIT S'IL ARRIVE CHEZ golem.fm (2026-10-14) : sans jeton, il reste sur le golem — le dire SUR la case,
                et mener à l'appairage par CE message (la case elle-même reste le geste de capture) */''}
          ${used && sw.blocks.some(b => b.type === 'compo') ? (() => {
            const fm = ((st.boot || {}).services || {}).fm || {};
            // LE DERNIER RIFF REFUSÉ, avec SA raison (bridge/uploader.refusal, codes lus chez golem.fm) — prime sur le ✓
            const fail = (st.compo || {}).riff_fail;
            const FAIL = { relink: 'relink golem.fm ›', space_gone: 'golem.fm space deleted', forbidden: 'no longer in this golem.fm space',
                           quota: 'golem.fm storage full', no_space: 'no golem.fm space attached', offline: 'golem.fm offline · kept on golem' };
            // LA CIBLE ARMÉE ET LA PRISE d'abord (riffNote) : c'est ce que le pied va faire — l'espace plein de la cible
            // armée y est dit (« storage full »), le tap serait refusé ; « Drop » est une vraie cible
            // de toucher qui ne passe pas le geste à la case (un doigt qui le rate ne relance pas une capture)
            const n = riffNote(st, now);
            if (n) return html`<span class=${cls('lriff-fm', 'rn-' + n.cls, n.drop && 'has-drop')} title=${n.title}>
                <span class="lriff-t">${n.text}</span>${n.drop
                ? html`<span class="lriff-drop" role="button" onClick=${e => dropRiff(e, n.drop)}>✕ Drop</span>` : ''}</span>`;
            if (fm.configured && fail) return html`<span class=${cls('lriff-fm', 'off')}
                onClick=${e => { e.stopPropagation(); if (fail.why === 'relink') go('system/connect/golemfm'); }}
                title=${'the last riff was not sent (' + fail.why + ') — it is kept on this golem'}>${FAIL[fail.why] || 'riff not sent · ' + fail.why}</span>`;
            return !fm.configured
              ? html`<span class="lriff-fm ok" onClick=${e => { e.stopPropagation(); go('library/tracks/recordings'); }}
                  title="riffs are kept on this golem, with your recordings — tap to see them">kept on this golem ›</span>`
              : fm.ok === false
              ? html`<span class="lriff-fm warn" title="golem.fm is not reachable — riffs are kept on the golem and sent later">golem.fm offline · kept on golem</span>`
              : html`<span class="lriff-fm ok" title="riffs land in your composer on golem.fm">→ golem.fm ✓</span>`; })() : ''}
          ${pile && !sp ? (() => {
            // ── LE STOMP DIT CE QU'IL FAIT (maquette live-tiles-v2, « Auto ») : le nom du switch en grand (son 1er effet,
            // « +N » s'il en fait plus), ON/OFF ; en bas, s'il ne touche qu'UN instrument, ses effets un par un (le musicien
            // seul cherche un effet) — sinon les instruments qu'il touche (en groupe, on cherche quelle partie change)
            const names = [...new Set(sw.blocks.map(pileName))];
            const lanes = [...new Set(sw.blocks.map(bk => bk.role || 'service'))];
            const fx = [...new Map(sw.blocks.map(bk => [pileName(bk) + '|' + bk.role, bk])).values()];
            const b0 = sw.blocks[0];
            return html`<span class="lst-state">${on ? 'ON' : 'OFF'}</span>
              <span class=${cls('lst-main', pedals && 'with-pedal')}>${pedals
                ? html`<span class="lst-pedal" aria-hidden="true"
                    dangerouslySetInnerHTML=${{ __html: pedalSvg({ type: b0.type, on: on && !blockOffInScene(b0), title: pileName(b0) }) }}></span>`
                : html`<i class="lst-ic">${ICON[b0.type] || '•'}</i>`}
                <b class="lst-name">${esc(names[0])}${names.length > 1 ? html`<small>+${names.length - 1}</small>` : ''}</b></span>
              <span class="lst-low">${lanes.length > 1
                ? html`<span class="lst-lanes">${lanes.map(l => html`<em class=${'li-tag ' + laneCls(l)}>${LANE_TAG[l] || String(l).toUpperCase()}</em>`)}</span>`
                : html`<${Cycle} items=${fx.map(bk => ({ tag: LANE_TAG[bk.role] || '', cls: laneCls(bk.role), t: pileName(bk), off: on && blockOffInScene(bk) }))} />`}</span>`; })()
          : pile ? Pile(sw.blocks.map(bk => ({ g: ICON[bk.type] || '•',
                                              // le nom qui tient sur une ligne : l'archétype nommé (« Big Muff »), sinon un libellé court, sinon le nom court du catalogue
                                              t: pileName(bk), lane: bk.role,
                                              off: on && blockOffInScene(bk) })))
          : used ? html`<span class="lpad-ic">${sw.blocks.slice(0, 2).map(bk => ICON[bk.type] || '•')}</span>` : ''}
          ${used && !pile ? html`<span class="lpad-name">${esc(name)}</span>` : ''}
          ${(() => { const g = svcB && songOf(st, svcB.type, sw.sw); return g ? html`<span class="lpad-song">
            <b>${esc(g.title)}</b>${g.by ? html`<i>${esc(g.by)}</i>` : ''}</span>` : ''; })()}
        </button>`;
  };

  return html`<div class=${cls('live2', loopOn && 'looping')}>
    ${/* le lien EN DIRECT avec le bridge (WebSocket), pas golem.fm ni Internet — et en anglais (règle 4) */''}
    ${!rig.wsUp && html`<div class="live-offline">⚠ OFFLINE — no live link to golem</div>`}
    ${/* même bande que OFFLINE : sur scène, un refus doit se lire d'un mètre, pas se deviner.
          `perf_error` couvre AUSSI le refus venu du PIED, qui n'a aucune réponse à afficher. */''}
    ${(recErr || st.perf_error) ? html`<div class="live-offline live-recerr">⚠ ${esc(recErr || st.perf_error)}</div>` : ''}
    <${BankBar} rig=${rig} presets=${list} trial=${isTrial ? current : null} badges=${recOn
      ? html`<span class="live2-badge rec-live" title="recording on this golem — the take lands in Library ▸ Tracks ▸ Recordings">● REC ${recMmss}</span>`
      : null} />

    ${/* ⚠ LA TUILE DE STOMP EST PARTAGÉE PAR LES DEUX RANGÉES. Depuis que le looper rend SW9
           (sa commande « tout jouer » descend en SW5, carte validée le 2026-08-08), la rangée
           looper doit savoir dessiner un stomp ORDINAIRE — sinon SW9 serait libre au pied et
           vide à l'écran. Une seule fonction, donc une seule vérité sur ce qu'est un stomp. */''}
    ${loopOn
    ? html`<div class="live2-row stomps looper" data-doc="live.stomps">
      ${switches.filter(sw => sw.sw !== 10).map((sw, i) => stompTile(sw, i))}
      ${backingSw && backingSw.sw === 10 ? stompTile(switches.find(x => x.sw === 10) || { sw: 10, blocks: [] }, 4)
        : html`<${LoopClearTile} st=${st} vu=${vu} />`}
    </div>`
    : html`<div class="live2-row stomps" data-doc="live.stomps">
      ${switches.map((sw, i) => stompTile(sw, i))}
    </div>`}
    ${''}


    <div class="live2-row scenes" data-doc="live.scenes">
      ${Array.from({ length: 5 }, (_, i) => {
        // une BOUCLE sur ce switch (SW 1-4, amendement du 2026-10-14) : la case est la boucle
        const loopIdx = loopOn ? ((st.looper || {}).slots || []).findIndex(x => x && x.sw === i + 1) : -1;
        if (loopIdx >= 0) return html`<${LoopTile} st=${st} i=${loopIdx} vu=${vu} laneLbl=${laneLbl} />`;
        // slot claimé par un bloc spécial (doctrine foot_scene_claim) : la tuile devient le SERVICE
        const claims = (st.scene_claims || {})[i + 1] || (st.scene_claims || {})[String(i + 1)] || [];
        // ⚠ SW5 EMPRUNTÉ PAR LE LOOPER (carte du 2026-08-08) : « tout jouer / tout arrêter » vit
        // sur la rangée du bas. Un claim explicite garde la priorité — le looper ne prend SW5 que
        // si personne ne l'a réclamé, exactement comme le bridge en décide (looper.SWITCHES).
        if (!claims.length && i + 1 === 5 && loopOn) {
          const lp = st.looper || {};
          const playing = (lp.slots || []).some(x => x && ['play', 'dub', 'rec'].includes(x.state));
          const any = (lp.len || 0) > 0;
          return html`<button class=${cls('lpad', 'scene', 'loop', 'ctl', !any && 'dim')}
            style=${`--pc:#3d9be9;--vu:${vu}`} onClick=${() => looperOp('toggle_all')}
            title="switch 5 — play / stop ALL loops together">
            <span class="lpad-sw">#5</span>
            ${/* le TRANSPORT, plus une « scène E » (maquette live-looper v2) : il porte le temps de la boucle maîtresse */''}
            <span class="loop-all">${playing ? '■' : '▶'} <em>ALL</em><small>${playing ? 'stop every loop' : 'play every loop'}</small></span>
            <${LoopClock} looper=${lp} bpm=${st.tempo} />
          </button>`;
        }
        if (claims.length) {
          const t = claims[0].type;
          // ⚠ L'ÉTAT PASSE PAR `SVC_STATE`, PAS PAR UNE CHAÎNE LOCALE. Cette rangée avait la
          // sienne, dupliquée — et elle OUBLIAIT standard/drums/sample : la tuile retombait sur
          // `st.stomps[sw]`, qui ne veut rien dire pour un service scene-invariant (il répond
          // « activé dans la scène », toujours vrai). Résultat : le Standard démarrait et la
          // tuile restait éteinte (mesuré le 2026-08-07 sur « ZZ Conflict »). Une table d'état
          // dans deux endroits, c'est un des deux qui finit périmé — la rangée haute l'utilisait
          // déjà, celle-ci s'en passait.
          const svc = SVC_STATE[t];
          const on = svc ? svc(st, claims[0], recOn)
                   : t === 'whammy-dt' ? !!st.whammy_on
                   // pédale MIDI générique : l'état vit dans midi_pedals, indexé par descripteur
                   : t === 'midi-pedal' ? !!(((st.midi_pedals || {})[claims[0].ref] || {}).on)
                   : t === 'backing-track' ? !!(st.backing && st.backing.playing)
                   // bloc de chaîne claimé (ex. clean-boost) : état = stomp de ce switch
                   : !!((st.stomps || {})[i + 1] || (st.stomps || {})[String(i + 1)]);
          const tap = t === 'tuner' ? () => post('/api/tuner', { on: !on })
                    : t === 'backing-track' ? () => st.backing.present && backingOp('toggle')
                    : () => post('/api/stomp', { switch: i + 1 });   // whammy-dt, rec… -> dispatch bridge
          const nm = t === 'tuner' ? 'TUNER' : t === 'whammy-dt' ? 'WHAMMY'
                   : t === 'midi-pedal' ? String(claims[0].label || 'PEDAL').toUpperCase()
                   : t === 'backing-track' ? 'BACKING' : t === 'rec' ? 'REC'
                   : t === 'clean-boost' ? 'BOOST' : String(t).toUpperCase();
          // couleur/anim du preset (clé = n° de switch, réglées dans Preset settings) —
          // couleur = identité, luminosité (on/dim) = état, comme le reste de la rangée
          const pc = colors[String(i + 1)] || colors[i + 1] || PALETTE[i];
          const anim = anims[String(i + 1)] || anims[i + 1] || '';   // idem scènes/stomps : l'anim vit aussi en OFF
          // ── LA PILE, TOUJOURS (2026-09-15) : un service SEUL sur la rangée des scènes (Click sur
          // SW4) était dessiné comme une scène — grande lettre D, nom en capitales — alors que SW5, qui
          // en porte deux, était en pile. Une seule grammaire pour « un switch tient des blocs », sur
          // les deux rangées ; la lettre reste aux vraies scènes. L'état et le nom sont ceux de CHAQUE
          // bloc (le REC qui enregistre bat en rouge ; le morceau qu'un backing/standard lancera).
          const svcOn = c => { const f = SVC_STATE[c.type]; return f ? f(st, c, recOn)
            : c.type === 'whammy-dt' ? !!st.whammy_on
            : c.type === 'midi-pedal' ? !!(((st.midi_pedals || {})[c.ref] || {}).on)
            : c.type === 'backing-track' ? !!(st.backing && st.backing.playing)
            : !!((st.stomps || {})[i + 1] || (st.stomps || {})[String(i + 1)]); };
          const svcName = c => { const g = songOf(st, c.type, i + 1);
            // le MORCEAU (switch de l'arrangement) : le geste tant qu'il ne tourne pas, la partie en cours ensuite
            if (c.type === 'arrangement') return (st.arrangement || {}).running ? ((st.arrangement || {}).name || 'Song') : 'Start the song';
            // L'ÉTAT RÉEL, lu sur le rack (2026-09-21) : la diode du pédalier est allumée par la PUCE,
            // elle peut mentir (prise refusée, stop depuis l'écran). Ici : le décompte, la prise, et
            // où en est le backing — ce qu'une diode ne dira jamais.
            const mmss = s => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
            if (c.type === 'rec') return st.perf_countin ? 'Count-in…' : (recOn ? 'Recording' : 'Rec');
            if (c.type === 'backing-track' && st.backing && st.backing.present && (st.backing.playing || st.backing.pos > 0.5))
              return ((g && g.title) || st.backing.title || 'Backing') + ' · ' + mmss(st.backing.pos || 0);
            return c.type === 'rec' ? (recOn ? 'Recording' : 'Rec')
              : g && g.title ? g.title
              : c.type === 'backing-track' ? (((st.backing || {}).title) || 'Backing')
              : c.type === 'midi-pedal' ? (c.label || 'Pedal') : pileName(c); };
          const anyOn = claims.some(svcOn) || (!!st.perf_countin && claims.some(c => c.type === 'rec'));
          const sp = specialOf(claims);
          return html`<button class=${cls('lpad', 'scene', 'claim', 'pile', anyOn && 'on', !anyOn && 'dim', sp && 'special', animClass(anim))}
            style=${sp ? `--pc:${sp[1]};--sc:${sp[1]};--vu:${vu}` : `--pc:${pc};--vu:${vu}`} onClick=${tap}
            title=${claims.map(c => svcName(c)).join(' + ') + ' — on switch ' + (i + 1) + ', in place of this scene slot (tap = ' + nm.toLowerCase() + ')'}>
            ${sp ? html`<span class="lpad-band">#${i + 1} ${sp[0]}</span>` : ''}
            <span class="lpad-sw">#${i + 1}</span>
            ${Pile(claims.map(c => ({ g: c.type === 'rec' && recOn ? html`<span class="lpl-rec"></span>` : (ICON[c.type] || '⊙'),
                                      t: svcName(c), lane: c.role || 'service', off: claims.length > 1 && !svcOn(c) })))}
          </button>`;
        }
        const s = scenes[i];
        // slot vide = fantôme : lettre à la même place/taille que les tuiles pleines, la rangée
        // reste comptable d'un coup d'œil (A B C D E) sans être bruyante
        if (!s) {
          // fantôme configurable (Preset settings, 2026-09-15) : couleur/anim par numéro de switch
          const gc = colors[String(i + 1)] || colors[i + 1] || EMPTY_COLOR, ga = anims[String(i + 1)] || anims[i + 1] || EMPTY_ANIM;
          const dfltMonster = !(anims[String(i + 1)] || anims[i + 1]);
          return html`<div class=${cls('lpad', 'scene', 'empty', animClass(ga), dfltMonster && monsterOf(i + 1))} style=${gc ? `--pc:${gc}` : ''}>
            ${dfltMonster ? MONSTER_LAYERS : ''}
            <span class="lpad-sw">#${i + 1}</span><span class="lpad-sc">${'ABCDE'[i]}</span></div>`;
        }
        const active = s.id === st.scene_id;
        // l'anim du preset reste sur la scène DÉSACTIVÉE aussi (atténuée en CSS via .dim) :
        // c'est l'identité visuelle de la tuile, pas un indicateur d'état
        const anim = anims[s.id] || '';
        // ── LA SCÈNE EST UN ACCORD (docs/band-scenes.md, lot 1) : lettre + nom du morceau en tête, puis
        // UNE LIGNE PAR LANE — l'état que la scène y choisit (« Pick · BASS »), ou, quand l'état n'a pas
        // d'autre nom que celui de la scène, le bloc qui fait l'identité de la lane (« Twin Reverb · GTR »).
        // Une lane mutée dans la scène est une ligne éteinte. Rien ne bouge au pied.
        const rows = s.lanes || [];
        // EN BOUCLANT, la scène est COMPACTE (maquette live-looper v2) : lettre + nom + UNE ligne qui résume ce qui
        // change — la même case, la même couleur, la même animation ; les trois lignes de lanes ne tiennent plus
        if (rows.length && loopOn) {
          const sum = rows.filter(r => !r.mute && r.state && !r.implicit).slice(0, 2)
            .map(r => (LANE_TAG[r.role] || String(r.role || '').toUpperCase()) + ' ' + r.state).join(' · ');
          return html`<button class=${cls('lpad', 'scene', 'acc', 'compact', !active && 'dim', active && 'on', animClass(anim))} data-doc=${'live.scene.' + s.id}
            style=${`--pc:${colors[s.id] || PALETTE[i]};--vu:${vu}`} onClick=${() => current && recall(null, s.id)}>
            <span class="lpad-sw">#${i + 1}</span>
            <span class="lpad-schead"><b>${s.id}</b><em>${esc(s.name || '')}</em></span>
            ${sum ? html`<span class="lsc-sum">${esc(sum)}</span>` : ''}
          </button>`;
        }
        if (rows.length) return html`<button class=${cls('lpad', 'scene', 'acc', !active && 'dim', active && 'on', animClass(anim))} data-doc=${'live.scene.' + s.id}
          style=${`--pc:${colors[s.id] || PALETTE[i]};--vu:${vu}`}
          onClick=${() => current && recall(null, s.id)}>
          <span class="lpad-sw">#${i + 1}</span>
          ${/* ── LETTRE ET NOM EN GRAND, LES INSTRUMENTS UN PAR UN EN BAS (maquette live-tiles-v2, 2026-10-14 : « trop
                d'infos sur ces cases » — la 6e lane d'un preset de groupe était coupée) */''}
          <span class="lsc-main"><b>${s.id}</b><em>${esc(s.name || '')}</em></span>
          <span class="lsc-low">${(() => { const per = {}, seen = {};
            rows.forEach(r => { per[r.role] = (per[r.role] || 0) + 1; });
            // la démo joue les lanes l'une après l'autre : la case de la scène active montre celle qu'on entend
            const hold = active && st.preview_lane ? rows.findIndex(r => r.id === st.preview_lane) : -1;
            return html`<${Cycle} hold=${hold} items=${rows.map(r => { seen[r.role] = (seen[r.role] || 0) + 1;
              return { tag: (LANE_TAG[r.role] || String(r.role || '').toUpperCase()) + (per[r.role] > 1 ? ' ' + seen[r.role] : ''),
                       cls: laneCls(r.role), t: r.mute ? 'silent' : (r.state && !r.implicit ? r.state : s.name || ''), off: r.mute }; })} />`; })()}</span>
          ${/* « LES INSTRUMENTS, PAS LES EFFETS » (2026-10-08) tient toujours : une entrée par lane, son SON quand la
                scène en choisit un qui a un nom, « silent » barré pour une lane coupée — mais une à la fois, en bas */''}
        </button>`;
        return html`<button class=${cls('lpad', 'scene', !active && 'dim', active && 'on', animClass(anim))} data-doc=${'live.scene.' + s.id}
          style=${`--pc:${colors[s.id] || PALETTE[i]};--vu:${vu}`}
          onClick=${() => current && recall(null, s.id)}>
          <span class="lpad-sw">#${i + 1}</span>
          <span class="lpad-sc">${s.id}</span>
          <span class="lpad-name">${esc(s.name || '')}</span>
        </button>`;
      })}
    </div>

    <div class="live2-exp" data-doc="live.exp">
      ${['exp1', 'exp2'].map((p, i) => {
        // rôle de chaque pédale physique selon la config (Système ▸ Pedalboard) — couleur liée au RÔLE
        const isVol = ((st.pedals || {}).volume || 'exp1') === p;
        // les couleurs de la BARRE (2026-10-11 : « les couleurs sont atroces ») : volume = mauve (Settings),
        // l'autre pédale = orange (Live) — plus de bleu nuit ni de jaune moutarde
        return html`<${ExpBar} key=${p} pedal=${p} label=${`EXP ${i + 1} · ` + (isVol ? 'Volume' : (st.exp2_target || 'Whammy'))}
                      value=${st[p] || 0} color=${isVol ? '#b06cf0' : '#ff5a3c'} />`;
      })}
    </div>

    ${bkgSheet ? html`<${BackingSheet} st=${st} onClose=${() => setBkgSheet(false)} />` : ''}

  </div>`;
}

// ── accordeur plein écran (refonte 2026-07-26) : jauge d'accordeur DIGITAL ──────────────
// Le JSFX analyse ~30×/s et chaque analyse traverse fichier -> bridge -> WS : brut, l'aiguille
// SACCADE. Deux lissages, comme un accordeur du commerce :
//   · cents  -> filtre exponentiel (l'aiguille glisse au lieu de sauter)
//   · note   -> HYSTÉRÉSIS : on ne change de note affichée qu'après 3 analyses concordantes
//     (sinon l'affichage clignote entre deux demi-tons quand la corde est pile entre les deux)
// L'ACCORDEUR vit dans live-tuner.js (2026-10-15) : partagé par les deux vues de /live, via live-tools.js.
export { TunerOverlay } from './live-tuner.js';

// Une pédale EXP de l'écran : on la GLISSE au doigt ou à la souris (talon à gauche, pointe à
// droite). Elle emprunte le chemin de la vraie pédale (POST /api/exp -> _on_pedal) : ce qu'elle
// pilote, c'est le RÔLE du moment (volume, wah…), jamais un potard choisi ici.
// Pendant le geste la barre suit le doigt (valeur locale) ; l'envoi est limité à ~25/s, et la
// position finale part TOUJOURS au lâcher. Après le lâcher on garde la valeur locale un instant :
// l'écho du rack arrive par le WebSocket, sans quoi la barre sauterait en arrière.
function ExpBar({ pedal, label, value, color }) {
  const [held, setHeld] = useState(null);                 // 0..127 pendant le geste, sinon null
  const box = useRef(null), dragging = useRef(false), sent = useRef({ t: 0, v: -1, timer: 0, release: 0 });
  const shown = held ?? value;
  const pct = Math.round(Math.min(127, Math.max(0, shown)) / 127 * 100);
  const at = e => {
    const r = box.current.getBoundingClientRect();
    return Math.round(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * 127);
  };
  const send = (v, final) => {
    const S = sent.current;
    clearTimeout(S.timer);
    const wait = 40 - (performance.now() - S.t);
    if (!final && wait > 0) { S.timer = setTimeout(() => send(v, true), wait); return; }
    if (v === S.v) return;
    S.t = performance.now(); S.v = v;
    post('/api/exp', { pedal, value: v }).catch(() => {});
  };
  const move = e => { const v = at(e); setHeld(v); send(v, false); };
  const down = e => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragging.current = true; clearTimeout(sent.current.release);
    move(e);
  };
  const up = e => {
    if (!dragging.current) return;
    dragging.current = false;
    const v = at(e); setHeld(v); send(v, true);
    sent.current.release = setTimeout(() => setHeld(null), 600);
  };
  return html`<div ref=${box} class=${cls('expbar', held !== null && 'held')} style=${`--ec:${color}`}
      title="drag to move the pedal — heel on the left, toe on the right"
      onPointerDown=${down} onPointerMove=${e => dragging.current && move(e)}
      onPointerUp=${up} onPointerCancel=${up}>
    <div class="expbar-fill" style=${`width:${pct}%`}></div>
    <span class="expbar-lbl">${label}</span>
    <span class="expbar-val">${pct}%</span>
  </div>`;
}

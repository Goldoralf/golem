// SPDX-License-Identifier: GPL-3.0-or-later
// LES OUTILS DU TOP MENU DE /live, partagés par la vue pédalier et la vue Timeline (2026-10-15). Deux familles :
//  · les PANNEAUX — Mixer, Tuner, ✎ (assigner le pédalier) : un seul ouvert à la fois, au gabarit du Mixer, SOUS le top
//    menu. Tout autre bouton ou lien du top menu ferme d'abord le panneau ouvert, puis fait son action.
//  · les INTERRUPTEURS — Click, Lock, Rec : un tap allume, un tap éteint. Ils ne ferment rien d'autre qu'un panneau, et
//    rien ne les éteint en passant (ouvrir le Mixer coupait le métronome).
// Ordre  : [vue] · Mixer · Tuner · ✎ · Click · Lock · Rec.
import { html, useState, useEffect, useRef, post, cls } from './lib.js';
import { Icon } from './icons.js';
import { LiveMixer } from './live-mixer.js';
import { LiveAssign } from './live-assign.js';
import { TunerOverlay } from './live-tuner.js';
import { CustomizePanel } from './live-customize.js';
import { PAGE_LABEL } from './live-widgets-model.mjs';

// ── LA VUE DE CET ÉCRAN (2026-10-15) : un menu en tête des outils — Pedalboard · Rehearsal · Concert (docs/live-
// pages.md §2), puis « Customize this page… ». Le choix vaut
// pour CET écran, le temps du MODE : il ne réécrit pas le réglage du mode (verrouillé en Gig / Show), il est mémorisé
// pour la session et rattaché au mode — au prochain changement de mode, on revient à sa vue (Settings ▸ Mode ▸ Live screen).
const VKEY = 'golem.liveView';
export const modeViewKey = st => { const m = (st && st.mode) || {}; return (m.id || '') + ':' + ((m.ui || {}).live || 'pedalboard'); };
export function viewOverride(key) {
  try { const o = JSON.parse(sessionStorage.getItem(VKEY) || 'null'); return o && o.key === key ? o.view : null; } catch { return null; }
}
function setViewOverride(key, view) {
  try { if (view) sessionStorage.setItem(VKEY, JSON.stringify({ key, view })); else sessionStorage.removeItem(VKEY); } catch { /* privé */ }
  window.dispatchEvent(new Event('golem:live-view'));
}
// relit la bascule quand elle change (la page qui choisit la vue n'est pas celle qui porte le bouton)
export function useViewOverride(key) {
  const [, bump] = useState(0);
  useEffect(() => { const on = () => bump(x => x + 1); window.addEventListener('golem:live-view', on);
    return () => window.removeEventListener('golem:live-view', on); }, []);
  return viewOverride(key);
}

// rec = { perfOn, on, toggle, title } — chaque vue garde sa façon d'enregistrer (et de dire un refus)
export function useLiveTools({ rig, st, presetId, rec, view }) {
  const [panel, setPanel] = useState(null);                 // 'mixer' | 'assign' | 'customize' — l'accordeur, lui, est l'état du rack
  const [menu, setMenu] = useState(false);                  // le menu de vue : false | {x, y} (la barre d'outils coupe ce qui dépasse : le menu est FIXE, calé sous le bouton)
  const tunerOn = !!(st.tuner && st.tuner.on);
  const clickOn = !!(st.click && st.click.on);
  const uiLocked = !!(st.live_lock || ((st.mode || {}).ui || {}).locked);   // Gig, Show : on n'assigne pas en concert
  const desk = !!(st.audio_metrics && st.audio_metrics.platform);
  // les écouteurs du document lisent l'état COURANT (une fermeture figée fermerait un panneau déjà fermé)
  const live = useRef({});
  live.current = { panel, tunerOn, menu };
  const closeAll = () => {
    if (live.current.panel) setPanel(null);
    if (live.current.tunerOn) post('/api/tuner', { on: false }).catch(() => {});
  };
  const togglePanel = which => {
    const open = which === 'tuner' ? tunerOn : panel === which;
    closeAll();
    if (open) return;
    if (which === 'tuner') post('/api/tuner', { on: true }).catch(() => {});
    else setPanel(which);
  };
  const then = fn => () => { closeAll(); fn(); };              // un interrupteur ferme le panneau ouvert, puis agit
  // LE TOP MENU FERME LE PANNEAU (« la croix, le bouton du menu, n'importe quel autre lien du top menu ») — sauf
  // les boutons d'outils eux-mêmes, qui ont leur propre règle ci-dessus. Phase de capture : avant la navigation.
  useEffect(() => {
    const onDown = e => {
      const t = e.target;
      if (live.current.menu && !(t && t.closest && t.closest('.lt-view'))) setMenu(false);   // un tap ailleurs ferme le menu
      if (!(live.current.panel || live.current.tunerOn)) return;
      if (t && t.closest && t.closest('.topbar') && !t.closest('.live-acts')) closeAll();
    };
    document.addEventListener('pointerdown', onDown, true);
    return () => document.removeEventListener('pointerdown', onDown, true);
  }, []);
  // quitter /live éteint l'accordeur : il écoute la lane, et rien ne le montrerait plus ailleurs
  useEffect(() => () => { if (live.current.tunerOn) post('/api/tuner', { on: false }).catch(() => {}); }, []);

  const vKey = modeViewKey(st);
  const mv = ((st.mode || {}).ui || {}).live;
  const modeDefault = PAGE_LABEL[mv] ? mv : 'pedalboard';
  const pickView = v => { setMenu(false); setViewOverride(vKey, v === modeDefault ? null : v); };   // la vue du mode efface la bascule
  const modeLocked = !!((st.mode || {}).ui || {}).locked;
  const VIEW_IC = { pedalboard: 'pedalboard', rehearsal: 'rehearsal', timeline: 'timeline' };
  const buttons = html`
    ${PAGE_LABEL[view] ? html`<span class="lt-view">
      <button class=${cls('live-act', (view !== modeDefault || menu) && 'on-mixer')} data-doc="live.tool.view"
        title=${PAGE_LABEL[view] + ' page — tap to change the page of this screen' + (view !== modeDefault ? ' (the mode says ' + PAGE_LABEL[modeDefault] + ')' : '')}
        onClick=${e => { const r = e.currentTarget.getBoundingClientRect(); const o = !menu; closeAll();
          setMenu(o ? { x: Math.max(8, Math.min(window.innerWidth - 268, r.left)), y: r.bottom + 6 } : false); }}><${Icon} id=${VIEW_IC[view]} /></button>
      ${menu ? html`<div class="lt-menu" role="menu" style=${'left:' + menu.x + 'px;top:' + menu.y + 'px'}>
        ${['pedalboard', 'rehearsal', 'timeline'].map(v => html`<button class=${cls('lt-mi', v === view && 'on')} role="menuitem" data-doc=${'live.view.' + v} onClick=${() => pickView(v)}>
          <${Icon} id=${VIEW_IC[v]} /><span>${PAGE_LABEL[v]}</span>${v === modeDefault ? html`<small>mode default</small>` : ''}</button>`)}
        <div class="lt-sep"></div>
        <button class="lt-mi lt-cust" role="menuitem" disabled=${view === 'pedalboard' || modeLocked}
          title=${modeLocked ? 'Locked by the mode' : view === 'pedalboard' ? 'the pedalboard page has no widgets' : 'choose the widgets of this page'}
          onClick=${() => { setMenu(false); setPanel('customize'); }}>✎ Customize this page…${modeLocked ? html`<small>Locked by the mode</small>` : ''}</button>
      </div>` : ''}
    </span>` : ''}
    <button class=${cls('live-act', panel === 'mixer' && 'on-mixer')} data-doc="live.tool.mixer"
      title=${panel === 'mixer' ? 'close the mixer' : 'mixer — balance what comes out of the rack'}
      onClick=${() => togglePanel('mixer')}><${Icon} id="mixer" /></button>
    <button class=${cls('live-act', tunerOn && 'on-tuner')} title=${tunerOn ? 'tuner ON — tap to close' : 'tuner'}
      onClick=${() => togglePanel('tuner')}><${Icon} id="tuner" /></button>
    ${!uiLocked ? html`<button class=${cls('live-act', panel === 'assign' && 'on-mixer')} data-doc="live.tool.assign"
      title=${panel === 'assign' ? 'close the pedalboard editor' : 'assign the pedalboard — what each switch controls'}
      onClick=${() => togglePanel('assign')}>✎</button>` : ''}
    <button class=${cls('live-act', clickOn && 'on-click')}
      title=${clickOn ? 'metronome ON — tap to stop' : 'metronome (follows this preset’s BPM)'}
      onClick=${then(() => post('/api/metronome', { on: !clickOn }).catch(() => {}))}><${Icon} id="metronome" /></button>
    <button class=${cls('live-act', st.live_lock && 'on-lock')}
      title=${desk ? (st.live_lock ? 'live lock ON — Designer frozen' : 'lock the Designer during the set')
        : (st.live_lock ? 'live lock ON — Designer frozen, CPU boosted (tap to unlock)' : 'lock the Designer + CPU boost during the set')}
      onClick=${then(() => {
        const on = !st.live_lock;
        post('/api/live-lock', { on }).catch(() => {});
        // le lock EST le geste « on entre en live » : il emporte le CPU boost du rack (pas sur un poste de bureau)
        if (!desk) post('/api/perf-mode', { on }).catch(() => {});
      })}><${Icon} id=${st.live_lock ? 'lock' : 'unlock'} /></button>
    ${rec && rec.perfOn ? html`<button class=${cls('live-act', rec.on && 'on-rec')} title=${rec.title}
      onClick=${then(rec.toggle)}><${Icon} id=${rec.on ? 'stop' : 'rec'} /></button>` : ''}`;

  const panelView = panel === 'customize' ? html`<div class="live2"><${CustomizePanel} st=${st} page=${view} onClose=${() => setPanel(null)} /></div>`
    : panel === 'mixer' ? html`<div class="live2" data-doc="live.mixer"><${LiveMixer} rig=${rig} onClose=${() => setPanel(null)} /></div>`
    : panel === 'assign' ? html`<div class="live2" data-doc="live.assign"><${LiveAssign} presetId=${presetId} inputmap=${st.inputmap}
        onClose=${() => setPanel(null)} /></div>`
    : tunerOn ? html`<div class="live2"><${TunerOverlay} panel=${true} t=${st.tuner}
        onClose=${() => post('/api/tuner', { on: false }).catch(() => {})} /></div>`
    : null;
  // ce que l'effet qui publie le top menu doit surveiller (le piège du slot figé sur son premier rendu)
  const deps = [view, vKey, menu && menu.x, modeDefault, modeLocked, panel, tunerOn, clickOn, st.live_lock, uiLocked, desk, rec && rec.perfOn, rec && rec.on, rec && rec.title];
  return { buttons, view: panelView, deps };
}

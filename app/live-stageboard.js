// SPDX-License-Identifier: GPL-3.0-or-later
// Les briques du PUPITRE de /live, partagées par les pages Répète et Concert (live-pages.js). Le pupitre lui-même
// (l'ancienne vue « Timeline », StageBoard) a été remplacé le 2026-10-15 par ces deux pages (docs/live-pages.md) ;
// restent ici le témoin d'enregistrement, la rangée des instruments et la couleur d'une scène.
import { html, useState, useEffect, post, cls, esc, LIVE_PALETTE } from './lib.js';

export const mmss = s => {
  if (!(s > 0)) return '0:00';
  const m = Math.floor(s / 60);
  return m + ':' + String(Math.floor(s % 60)).padStart(2, '0');
};

// ⚠ LE MAGNÉTOPHONE EST UN RÉGLAGE DE MODE, ET SHOW EST EN `auto` : entrer sur /live LANCE une
// prise. Ce bloc a été ajouté après m'être fait avoir — mes propres tests du mode Show ont
// enregistré 13 minutes et 1,7 Go sans que RIEN à l'écran ne le dise. Un écran conçu pour un mode
// qui enregistre tout seul DOIT porter le témoin, sinon on repart d'un concert avec une prise
// qu'on ne savait pas avoir lancée (ou pire, sans celle qu'on croyait avoir).
// Jumeau de la logique de PedalboardLive (page-live.js) : les deux vues doivent se comporter
// pareil sur ce point. Non factorisé pour l'instant — page-live.js est énorme et le hook devrait
// sortir dans un module partagé, ce qui est un chantier à part.
export function usePerfRec(st) {
  const perfOn = !!(((st.mode || {}).services || {}).perfrec);
  const auto = ((st.mode || {}).perfrec_mode || 'manual') === 'auto';
  const [poll, setPoll] = useState(null);
  const perf = st.perf || poll || {};
  const on = !!perf.recording;
  const [, tick] = useState(0);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => tick(x => x + 1), 1000);
    return () => clearInterval(t);
  }, [on]);
  useEffect(() => {
    if (!perfOn) return;
    let alive = true;
    const load = () => fetch('/api/perf').then(r => r.json()).then(d => alive && setPoll(d)).catch(() => {});
    load();
    if (auto) fetch('/api/perf').then(r => r.json())
      .then(d => { if (alive && !d.recording) post('/api/perf/start'); }).catch(() => {});
    const t = setInterval(load, 3000);
    return () => { alive = false; clearInterval(t); };
  }, [perfOn, auto]);
  const secs = on && perf.started_at
    ? Math.max(0, Math.floor((Date.now() - new Date(perf.started_at).getTime()) / 1000)) : 0;
  return { perfOn, on, mmss: mmss(secs),
           toggle: () => post('/api/perf/' + (on ? 'stop' : 'start')) };
}

export const sceneColor = (sid, p) => {
  if (!sid) return '#2a2f37';
  const c = ((p && p.colors) || {})[sid];
  if (c) return c;
  const i = ((p && p.scenes) || []).findIndex(x => x.id === sid);
  return LIVE_PALETTE[i >= 0 ? i % LIVE_PALETTE.length : 0];
};


// La rangée des lignes ACTIVES du groupe : icône + prénom (attribution par entrée, roster) —
// éteinte quand le MODE coupe le rôle. Un regard = qui joue.
const ROLE_IC = { guitar: '🎸', bass: '🎸', voice: '🎤', keys: '🎹', pads: '▦', 'keys-pads': '🎹', drums: '🥁', line: '〜' };
export function Instruments({ st, preset }) {
  const imap = st.inputmap || {};
  const services = (st.mode || {}).services || {};
  const hasBlocks = r => {
    if (!preset) return false;
    if (r === 'guitar') { const g = preset.guitar || {};
      return !!((g.pre || []).length || (g.post || []).length ||
        ((g.split || {}).branches || []).some(b => (b.blocks || []).length)); }
    return !!(((preset[r] || {}).chain) || []).length;
  };
  const rows = [];
  const laneBlocksOf = L => { const c = (L && L.chain) || {};
    return (c.pre || []).length + (c.post || []).length + (((c.split || {}).branches) || []).reduce((n, b) => n + (b.blocks || []).length, 0); };
  if (preset && preset.lanes_v === 2 && Array.isArray(preset.lanes)) {
    // LOT 4 : une rangée PAR LANE du preset — trois guitaristes = trois rangées, chacune jugée sur SON rôle
    for (const L of preset.lanes) {
      if (!laneBlocksOf(L) || L.in_sel === 'NONE') continue;
      const e = L.midi ? (imap.midi || {}) : ((imap.inputs || []).find(x => String(x.ch) === String(L.in_sel)) || {});
      const roles = L.role === 'keys-pads' ? ['keys', 'pads'] : [L.role];
      rows.push({ ic: ROLE_IC[L.role] || '·', nm: e.person_name || L.name || e.label || L.role,
                  on: roles.some(r => services[r] !== false) });
    }
  } else {
    for (const e of imap.inputs || []) {
      const role = e.role;
      if (!role || role === 'none') continue;
      const realm = role === 'voice' ? 'voice' : 'guitar';
      if (!hasBlocks(realm)) continue;
      rows.push({ ic: ROLE_IC[role] || '·', nm: e.person_name || e.label || role,
                  on: services[role] !== false });
    }
    const mr = (imap.midi || {}).role;
    if (mr && hasBlocks('keys'))
      rows.push({ ic: ROLE_IC[mr] || '🎹', nm: (imap.midi || {}).label || 'Keys',
                  on: services.keys !== false || services.pads !== false });
  }
  if (!rows.length) return '';
  return html`<div class="sb-insts">
    ${rows.map(r => html`<span class=${cls('sb-inst', !r.on && 'off')} title=${r.on ? 'active line' : 'muted by the active mode'}><i>${r.ic}</i>${esc(r.nm)}</span>`)}
  </div>`;
}


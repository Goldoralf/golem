// SPDX-License-Identifier: GPL-3.0-or-later
// Les widgets des pages de /live (docs/live-pages.md §5) — MIROIR de bridge/modes.py (WIDGET_SLOTS, WIDGET_SIZES,
// WIDGET_DEFAULTS) : le mode brut publié dans l'état ne porte que ses surcharges (`ui.widgets`), la page résout le reste
// ici, avec la même règle (un widget qui ne tient pas retombe sur le défaut). Pur : testé par live-widgets-model.test.mjs.

export const WIDGET_SLOTS = { rehearsal: { right: 'M', bottom: 'L' }, timeline: { top1: 'S', top2: 'S', bottom: 'L' } };
export const WIDGET_SIZES = { lyrics: ['L'], song_time: ['M'], set_clock: ['S'], chords: ['M', 'L'], notes: ['S', 'M'],
                              instruments: ['S', 'M'] };
export const WIDGET_DEFAULTS = { rehearsal: { right: 'chords', bottom: 'lyrics' },
                                 timeline: { top1: 'notes', top2: 'set_clock', bottom: 'lyrics' } };
export const WIDGET_INFO = {
  lyrics: ['Lyrics', 'the current line and the next'],
  song_time: ['Song time', 'elapsed / total'],
  set_clock: ['Set clock', 'early or late on the plan'],
  chords: ['Chords', 'the bars of the standard, the current one lit'],
  notes: ['Stage notes', 'capo, tuning, the note of the song'],
  instruments: ['Instruments', 'who plays in this scene'],
};
export const PAGE_LABEL = { pedalboard: 'Pedalboard', rehearsal: 'Rehearsal', timeline: 'Concert' };

// les widgets effectifs d'une page pour un mode BRUT ({ui: {widgets}})
export function widgetsOf(mode, page) {
  const slots = WIDGET_SLOTS[page] || {};
  const mine = ((((mode || {}).ui || {}).widgets || {})[page]) || {};
  const out = {};
  for (const [slot, size] of Object.entries(slots)) {
    const w = Object.prototype.hasOwnProperty.call(mine, slot) ? mine[slot] : WIDGET_DEFAULTS[page][slot];
    out[slot] = (w === null || (WIDGET_SIZES[w] || []).includes(size)) ? w : WIDGET_DEFAULTS[page][slot];
  }
  return out;
}

export const fits = (w, size) => (WIDGET_SIZES[w] || []).includes(size);

// le décompte d'un départ de section (docs/live-pages.md §6.1) : max(1, 2 si une mesure dure moins de 2 s)
export function countInBars(part) {
  if (!part || !part.bars) return 1;
  return (part.dur / part.bars) < 2 ? 2 : 1;
}

// la durée prévue d'une ligne de setlist : son arrangement (mesures × métrique × tempo), sinon inconnue (null)
export function lineSeconds(line, fallbackBpm) {
  const pm = ((line || {}).arrangement || {}).params || {};
  const secs = pm.sections || [];
  const bpm = +(line && line.bpm) || +fallbackBpm || 0;
  if (!secs.length || !bpm) return null;
  const base = pm.sig || { num: 4, den: 4 };
  return secs.reduce((t, s) => { const g = s.sig || base;
    return t + (+s.bars || 0) * (+g.num || 4) * (4 / (+g.den || 4)) * (60 / bpm); }, 0);
}

// l'horloge du set : secondes de RETARD (> 0) ou d'avance (< 0) sur le prévu, ou null si on ne sait pas
export function setLate({ startedAt, now, lines, curIdx, pos }) {
  if (!startedAt || curIdx < 0 || pos == null) return null;
  let before = 0;
  for (let i = 0; i < curIdx; i++) {
    const s = lineSeconds(lines[i]);
    if (s == null) return null;                 // un morceau d'avant sans durée connue : on ne prétend rien
    before += s;
  }
  return (now - startedAt) - (before + pos);
}

export const fmtClock = s => { const a = Math.abs(Math.round(s)); return Math.floor(a / 60) + ':' + String(a % 60).padStart(2, '0'); };

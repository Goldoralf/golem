// SPDX-License-Identifier: GPL-3.0-or-later
// LES GESTES AU PIED, À L'ÉCRAN (2026-09-21). Trois signes — • tap · •• double-tap · ▬ appui
// long (▬▬ maintien prolongé) — chacun suivi de l'icône de ce qu'il fait MAINTENANT : la légende
// suit l'état du bloc. UNE source : config/pedalboard/gestures.json, servie par GET /api/gestures ;
// l'onglet MIDI assign du Designer en écrit les phrases (la bande de glyphes de /live est retirée le 2026-10-09). Rien n'est
// recopié ici : si la table ne se charge pas, on n'affiche RIEN plutôt qu'une légende inventée.
import { html, useState, useEffect } from './lib.js';

let _table = null, _pending = null;
const _subs = new Set();
const load = () => _pending || (_pending = fetch('/api/gestures').then(r => r.json())
  .then(t => { _table = t; _subs.forEach(f => f(t)); return t; })
  .catch(() => { _pending = null; return null; }));

export function useGestures() {
  const [t, setT] = useState(_table);
  useEffect(() => { _subs.add(setT); if (!_table) load(); return () => { _subs.delete(setT); }; }, []);
  return t;
}

const Sign = g => g === 'tap' ? html`<span class="lpg-d"><i></i></span>`
  : g === 'double' ? html`<span class="lpg-d"><i></i><i></i></span>`
  : g === 'longhold' ? html`<span class="lpg-h long"></span>`
  : html`<span class="lpg-h"></span>`;

// LA LÉGENDE EN PHRASES (Designer ▸ MIDI assign) : tous les états du bloc, toujours visible.
export function GestureLegend({ t, block, extra }) {
  const b = t && t.blocks && t.blocks[block];
  const states = b ? Object.values(b.states) : [];
  const rows = [...states, ...(extra || [])];
  if (!rows.length) return '';
  return html`<div class="lgd">
    <span class="lgd-t">On the pedalboard</span>
    ${rows.map(s => html`<span class="lgd-st">${s.label ? html`<em>${s.label}</em>` : ''}
      ${s.gestures.map(x => html`<span class="lgd-it">${Sign(x.g)}<span>${x.text}${x.s && x.g !== 'double' ? ' (' + x.s + ' s)' : ''}</span></span>`)}</span>`)}
  </div>`;
}

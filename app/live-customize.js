// SPDX-License-Identifier: GPL-3.0-or-later
// « CUSTOMIZE THIS PAGE… » (docs/live-pages.md §5) : un panneau au gabarit du Mixer qui n'édite QUE la page ouverte.
// La page en miniature avec ses emplacements (le premier sélectionné d'office) ; un tap sur un emplacement, puis sur un
// widget — seuls ceux qui TIENNENT dans sa taille sont proposés, `Empty` libère l'emplacement. Gardé par mode.
import { html, useState, post, cls, esc } from './lib.js';
import { WIDGET_SLOTS, WIDGET_INFO, PAGE_LABEL, widgetsOf, fits } from './live-widgets-model.mjs';

const SIZE_NAME = { S: 'small', M: 'medium', L: 'large' };

export function CustomizePanel({ st, page, onClose }) {
  const slots = WIDGET_SLOTS[page] || {};
  const mode = st.mode || {};
  const cur = widgetsOf(mode, page);
  const [slot, setSlot] = useState(Object.keys(slots)[0]);
  const [said, setSaid] = useState('');
  const size = slots[slot];
  // un widget déjà posé dans un AUTRE emplacement de la page : le choisir l'y DÉPLACE (jamais deux fois le même)
  const usedIn = w => Object.keys(slots).find(k => k !== slot && cur[k] === w);
  const SLOT_LB = { right: 'right of NOW', bottom: 'under NOW', top1: 'top left · 1', top2: 'top left · 2' };
  const pick = async w => {
    const other = w ? usedIn(w) : null;
    try {
      await post('/api/mode/update', { id: mode.id, widgets: { [page]: { [slot]: w, ...(other ? { [other]: null } : {}) } } });
      setSaid('✓ saved'); setTimeout(() => setSaid(''), 1200);
    } catch (e) { setSaid('✗ ' + ((e && e.body && e.body.error) || 'not saved')); }
  };
  const S = (id, lb) => html`<button class=${cls('lc-slot', slot === id && 'sel', 'sz-' + slots[id])} onClick=${() => setSlot(id)}>
    <small>${slots[id]}</small><b>${cur[id] ? (WIDGET_INFO[cur[id]] || [cur[id]])[0] : 'Empty'}</b><em>${lb}</em></button>`;
  const F = (lb, cl) => html`<div class=${cls('lc-fixed', cl)}>${lb}</div>`;
  const mini = page === 'rehearsal'
    ? html`<div class="lc-mini lc-reh">${F('song · tempo')}${F('SECTION CARDS', 'tall')}
        <div class="lc-row">${F('NOW · section + bar', 'grow')}${S('right', 'right of NOW')}</div>
        ${S('bottom', 'under NOW')}${F('song map · ▶ FROM · ■')}</div>`
    : html`<div class="lc-mini lc-gig">${F('setlist band')}
        <div class="lc-now">${F('NOW · section + bar · next', 'grow')}<div class="lc-tops">${S('top1', 'top left · 1')}${S('top2', 'top left · 2')}</div></div>
        ${S('bottom', 'under NOW')}${F('song map · ▶ PLAY · ■ hold')}</div>`;
  const list = Object.keys(WIDGET_INFO).filter(w => fits(w, size));
  return html`<div class="lmx lc">
    <section class="card-panel lmx-head">
      <b>Customize — ${PAGE_LABEL[page] || page}</b>
      <span class="lmx-dest">saved for the ${esc(mode.name || 'current')} mode</span>
      <span class="lmx-spacer" />${said ? html`<span class="lc-said">${said}</span>` : ''}
      <button class="chip lc-done" onClick=${onClose}>Done</button>
    </section>
    <div class="lc-body">
      <section class="card-panel lc-left">${mini}</section>
      <section class="card-panel lc-right">
        <div class="lc-h">${SIZE_NAME[size] || ''} slot · ${SLOT_LB[slot] || slot}</div>
        <div class="lc-list">
          ${list.map(w => html`<button class=${cls('lc-w', cur[slot] === w && 'on')} onClick=${() => pick(w)}>
            <b>${WIDGET_INFO[w][0]}${cur[slot] === w ? ' ✓' : ''}</b>
            <small>${usedIn(w) ? 'in use · ' + SLOT_LB[usedIn(w)] + ' — tap to move it here' : WIDGET_INFO[w][1]}</small></button>`)}
          <button class=${cls('lc-w', cur[slot] === null && 'on')} onClick=${() => pick(null)}>
            <b>Empty${cur[slot] === null ? ' ✓' : ''}</b><small>give the space back to the page</small></button>
        </div>
        <p class="muted lc-hint">A widget with nothing to show hides itself — a song without lyrics gives its space back.</p>
      </section>
    </div>
  </div>`;
}

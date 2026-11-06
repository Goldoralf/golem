// SPDX-License-Identifier: GPL-3.0-or-later
// Le RAIL DE SETLISTS et la RANGÉE partagés par les deux modals du sélecteur (Presets, Patches) — une seule grammaire
// (mockups/browser-setlists.html, 2026-10-14). Classes préfixées `brw-` : rien ne se mélange aux autres pages.
import { html, cls, esc, useState, useEffect } from './lib.js';
import { railCount, posOf, othersOf } from './browser-model.mjs';
import { ICON, blkColor } from './designer-model.js';
import { ICONS } from './icons.js';

// les setlists du rack, lues une fois par ouverture du modal
export function useSetlists() {
  const [d, setD] = useState(null);
  useEffect(() => { fetch('/api/setlists').then(r => r.json()).then(setD).catch(() => setD({ setlists: [] })); }, []);
  return d;
}

// `sel` = ce que la grille montre ; `remembered` = la setlist choisie, montrée en pointillé pendant une recherche.
// `hideEmpty` : un autre filtre est posé (l'instrument des patches, 2026-10-17) — une setlist qui n'a RIEN pour lui
// disparaît au lieu d'être grisée : « Voice » puis « Factory Guitar » menait à une liste vide par construction.
export function SetlistRail({ kind, lists, active, pool, sel, remembered, onSel, hideEmpty }) {
  const item = (id, label, extra) => {
    const n = railCount(id, pool, lists);
    return html`<button class=${cls('brw-ri', sel === id && 'on', sel !== id && remembered === id && 'ghost', n === 0 && id !== 'all' && 'zero')}
      onClick=${() => onSel(id)}>${extra || ''}${label}<span class="brw-n">${n}</span></button>`;
  };
  const keep = id => !hideEmpty || id === sel || railCount(id, pool, lists) > 0;
  const shownLists = lists.filter(s => keep(s.id));
  return html`<nav class="brw-rail">
    ${item('all', html`<span class="brw-t"><b>All ${kind}</b></span>`)}
    ${shownLists.length ? html`<div class="brw-rh">${kind === 'presets' ? 'SETLISTS' : 'SOUND SETLISTS'}</div>` : ''}
    ${shownLists.map(s => s.id === active
      ? item(s.id, html`<span class="brw-t"><b>${esc(s.name || s.id)}</b><small>ON THE FOOT</small></span>`, html`<span class="brw-foot">⚑</span>`)
      : item(s.id, html`<span class="brw-t"><b>${esc(s.name || s.id)}</b></span>`))}
    ${keep('none') ? html`<div class="brw-sep"></div>
    ${item('none', html`<span class="brw-t"><b>Not in a setlist</b></span>`)}` : ''}
  </nav>`;
}

// une rangée de 48 px : [#pos] ● nom [+n] … [aside] — `aside` = ♩bpm + scènes (preset) ou source + scènes (patch)
export function BrowseRow({ x, name, styleCls, sel, lists, active, current, title, aside, onPick }) {
  const pos = posOf(x.id, sel, lists, active);
  const others = othersOf(x.id, sel, lists, active);
  return html`<button class=${cls('brw-row', styleCls, current && 'cur')} title=${title || ''} onClick=${onPick}>
    <span class=${cls('brw-pos', pos && pos.foot && 'brw-on-foot')}>${pos ? '#' + String(pos.n).padStart(2, '0') : '—'}</span>
    <span class="brw-dot"></span>
    <span class="brw-nm">${name}</span>
    ${others ? html`<span class="brw-more" title=${'also in ' + others + ' other setlist' + (others > 1 ? 's' : '')}>+${others}</span>` : ''}
    ${aside}
  </button>`;
}

export function Pager({ page, pages, onPage }) {
  if (pages < 2) return '';
  return html`<div class="brw-pager">
    <button disabled=${page === 0} onClick=${() => onPage(page - 1)} aria-label="previous page">‹</button>
    <span>${page + 1}/${pages}</span>
    <button disabled=${page >= pages - 1} onClick=${() => onPage(page + 1)} aria-label="next page">›</button>
  </div>`;
}

// CE QUE FAIT un preset ou un patch au-delà du son (2026-10-17) : le menu « With » filtre, l'icône le dit sur
// chaque rangée. La liste vient du bridge (preset_view.FEATURES) ; les blocs permanents (Rec, Click…) n'en sont pas.
// L'ICÔNE EST CELLE DU BLOC (sa tuile du Designer : ICON + blkColor, hydratés depuis le catalogue) — jamais un emoji.
export const FEATURES = [['backing', 'Backing', 'backing-track'], ['standard', 'Standard', 'standard'],
                         ['drums', 'Drum machine', 'drums'], ['looper', 'Looper', 'looper'], ['pads', 'Pads', 'pads'],
                         // Rec et Riff : seulement côté patches (un preset les a toujours) — le menu ne propose que
                         // ce que la liste contient, donc rien à filtrer ici
                         ['rec', 'Rec', 'rec'], ['compo', 'Riff', 'compo']];
export const FEAT = Object.fromEntries(FEATURES.map(([id, label, type]) => [id, { label, type }]));
// les mêmes exceptions que la tuile (page-designer.js fxIcon) : le Riff est une flamme DESSINÉE, pas le glyphe du catalogue
const glyphOf = type => type === 'compo' ? ICONS.riff : (ICON[type] || '');
const FeatGlyph = ({ f }) => html`<span class="brw-feat" style=${'color:' + blkColor(FEAT[f].type)}
  title=${FEAT[f].label}>${glyphOf(FEAT[f].type)}</span>`;
export const hasFeat = (x, f) => f === 'any' || (x.features || []).includes(f);

// le menu : « With anything » + chaque bloc présent dans `all`, avec son nombre (un bloc absent n'est pas proposé)
export function FeatureMenu({ all, feat, onPick }) {
  const [open, setOpen] = useState(false);
  const n = f => all.filter(x => hasFeat(x, f)).length;
  const pick = f => { setOpen(false); onPick(f); };
  return html`<div class="brw-inst">
    <button class="brw-instb brw-featb" onClick=${() => setOpen(v => !v)}
      title="what else it plays: a backing, a standard, a drum machine…">${feat === 'any' ? 'With anything'
        : html`<${FeatGlyph} f=${feat} /> ${FEAT[feat].label}`} ▾</button>
    ${open ? html`<div class="save-pop brw-pop" onClick=${e => e.stopPropagation()}>
      <button class=${cls('row-btn', feat === 'any' && 'on')} onClick=${() => pick('any')}>With anything<small>${all.length}</small></button>
      ${FEATURES.filter(([id]) => n(id) > 0).map(([id, label]) => html`<button class=${cls('row-btn', feat === id && 'on')}
        onClick=${() => pick(id)}><${FeatGlyph} f=${id} /> ${label}<small>${n(id)}</small></button>`)}
    </div>` : ''}
  </div>`;
}

// les icônes d'une rangée
// les CARTES de Songs ▸ Presets et Songs ▸ Patches (2026-10-18) : les mêmes blocs que le sélecteur du Designer, mais
// avec leur nom — une carte se lit, elle n'est pas un rail serré. Rien si le preset n'en a aucun.
export const FeatChips = ({ x }) => {
  const fs = (x.features || []).filter(f => FEAT[f]);
  return fs.length ? html`<div class="pcard-feats" title="the special blocks it plays">${fs.map(f => html`<span class="pfeat"
    style=${'--fc:' + blkColor(FEAT[f].type)}><${FeatGlyph} f=${f} />${FEAT[f].label}</span>`)}</div>` : '';
};
export const FeatIcons = ({ x }) => (x.features || []).filter(f => FEAT[f]).map(f => html`<${FeatGlyph} f=${f} />`);

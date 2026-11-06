// SPDX-License-Identifier: GPL-3.0-or-later
// LA LISTE AU PIED D'UN MODE, choisie dans un modal (2026-10-15 : « la liste des banks/setlists est trop longue,
// on a un scrolleur horizontal — un user peut en avoir beaucoup »). Le segmenté alignait une case par setlist : il
// débordait dès la septième. Ici : « Keep » en tête, puis les setlists par nature (chansons / sons) sur trois colonnes,
// une recherche dès qu'il y en a beaucoup, et des PAGES — jamais de défilement (format 1024×600).
import { html, useState, useAsync, cls, esc } from './lib.js';

const PER = 15;                                   // 5 rangées × 3 colonnes de 48 px
// LA BANQUE DE L'INSTRUMENT (docs/modes.md §2, 2026-10-24) : pas une setlist, un choix résolu à l'entrée du mode —
// la banque de sons d'usine du premier instrument posé sur la carte (guitare -> Factory Guitar)
export const INSTRUMENT = '@instrument';

export function FootListButton({ lists, value, onOpen }) {
  const s = ((lists || {}).setlists || []).find(x => x.id === value);
  return html`<button class=${cls('mode-svc', 'tog', 'on', 'fl-btn')} onClick=${onOpen}
    title="the list put on the pedalboard when entering this mode — tap to choose">
    ${value === INSTRUMENT ? '⛓ My instrument\'s bank' : s ? (s.kind === 'sounds' ? '⛓ ' : '▤ ') + (s.name || s.id) : value ? '⚠ ' + value + ' (missing)' : 'Keep'} ▾</button>`;
}

export function FootListPicker({ lists, value, modeName, onPick, onClose }) {
  // L'USINE MASQUÉE (Settings ▸ Content ▸ Factory) ne se propose plus — sauf la liste que ce mode désigne déjà : on voit ce qu'on a.
  // Masquer n'est pas supprimer : le mode qui la désigne continue de la mettre au pied (docs/factory.md).
  const { data: vis } = useAsync(() => fetch('/api/factory/visibility').then(r => r.json()).catch(() => null), []);
  const hideFactory = !!(vis && vis.show && vis.show.setlists === false);
  const all = ((lists || {}).setlists || []).filter(s => !(hideFactory && s.factory && s.id !== value));
  const active = (lists || {}).active;
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const ql = q.trim().toLowerCase();
  // chansons d'abord, puis sons ; dans chaque nature, celle du pied en tête puis A→Z
  const order = s => (s.kind === 'sounds' ? 1 : 0);
  const items = all.filter(s => !ql || String(s.name || s.id).toLowerCase().includes(ql))
    .sort((a, b) => order(a) - order(b) || (b.id === active) - (a.id === active) || String(a.name || a.id).localeCompare(String(b.name || b.id)));
  const pages = Math.max(1, Math.ceil(items.length / PER));
  const pg = Math.min(page, pages - 1);
  const shown = items.slice(pg * PER, pg * PER + PER);
  const pick = v => { onPick(v); onClose(); };
  const n = s => (s.presets || []).length;
  const card = s => html`<button class=${cls('fl-item', s.id === value && 'on')} onClick=${() => pick(s.id)}
      title=${'entering this mode puts « ' + (s.name || s.id) + ' » on the foot — you can still change it after'}>
    <span class="fl-ic">${s.kind === 'sounds' ? '⛓' : '▤'}</span>
    <span class="fl-nm">${esc(s.name || s.id)}${s.id === active ? html`<small>ON THE FOOT NOW</small>` : ''}</span>
    <span class="fl-n">${n(s)}</span>
  </button>`;
  // les sections de LA PAGE : un titre chaque fois que la nature change
  const sections = [];
  for (const s of shown) {
    const k = s.kind === 'sounds' ? 'sounds' : 'songs';
    if (!sections.length || sections[sections.length - 1].k !== k) sections.push({ k, items: [] });
    sections[sections.length - 1].items.push(s);
  }
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card fl-modal">
      <div class="fl-hd">
        <h2>Foot list${modeName ? html` <small>— ${esc(modeName)}</small>` : ''}</h2>
        ${all.length > PER ? html`<input class="search" placeholder="Search setlists…" value=${q} autofocus
          onInput=${e => { setQ(e.target.value); setPage(0); }} />` : html`<span class="grow"></span>`}
        <button class="brw-x" onClick=${onClose} aria-label="close">✕</button>
      </div>
      <div class="fl-top">
        <button class=${cls('fl-keep', !value && 'on')} onClick=${() => pick('')}>
          <b>Keep</b><span class="muted">entering this mode leaves the pedalboard list as it is</span></button>
        <button class=${cls('fl-keep', value === INSTRUMENT && 'on')} onClick=${() => pick(INSTRUMENT)}>
          <b>⛓ My instrument's bank</b><span class="muted">a guitar gets Factory Guitar</span></button>
      </div>
      <div class="fl-body">
        ${sections.map(sec => html`<div class="fl-sec">${sec.k === 'songs' ? 'SONG SETLISTS' : 'SOUND SETLISTS'}
            <em>${sec.k === 'songs' ? 'presets, one per bank' : 'patches, one per bank'}</em></div>
          <div class="fl-grid">${sec.items.map(card)}</div>`)}
        ${!items.length ? html`<div class="empty">${ql ? html`Nothing matches “${esc(q)}”.` : 'No setlist yet.'}</div>` : ''}
      </div>
      <div class="fl-ft">
        <span class="muted">${items.length} setlist${items.length > 1 ? 's' : ''} · the number is how many banks it fills</span>
        ${pages > 1 ? html`<div class="brw-pager">
          <button disabled=${pg === 0} onClick=${() => setPage(pg - 1)} aria-label="previous page">‹</button>
          <span>${pg + 1}/${pages}</span>
          <button disabled=${pg >= pages - 1} onClick=${() => setPage(pg + 1)} aria-label="next page">›</button>
        </div>` : ''}
      </div>
    </div>
  </div>`;
}

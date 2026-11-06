// SPDX-License-Identifier: GPL-3.0-or-later
// ── LA BARRE DES ONGLETS PRESETS ET PATCHES (2026-10-08) ─────────────────────────────────
// Deux mondes CLOISONNÉS : Presets ↔ Setlists (les morceaux), Patches ↔ Banks (les sons). Chaque
// onglet a la même barre, dans la rangée des sous-onglets (une ligne, 1024 px partagés avec les
// onglets) — d'où les astuces :
//   - la LISTE regardée est un menu compact (▤ setlist / ⛓ bank) ; elle ne change PAS ce que joue le
//     pédalier (ça se fait dans « Banks & Setlists » ou sur /live) — le menu marque juste « on the foot » ;
//   - la recherche est une loupe qui s'ouvre au tap (et reste ouverte tant qu'elle contient du texte) ;
//   - le TRI est UN bouton qui dit le tri en cours (« ↕ Setlist # ») et ouvre ses choix ;
//   - les FILTRES sont UN bouton qui RÉSUME ce qui est filtré (« ⚲ Guitar · not in list ») et ouvre un
//     panneau ; sans filtre, il dit « ⚲ Filters ».
// Les panneaux sont en position FIXE, calés sous leur bouton : la rangée des sous-onglets coupe ce qui
// déborde.
import { html, useState, useEffect, useRef, cls, esc } from './lib.js';

function Pop({ anchor, onClose, children, wide }) {
  const r = anchor ? anchor.getBoundingClientRect() : { left: 0, bottom: 0, right: 0 };
  const w = wide ? 300 : 190;
  const left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
  return html`<div class="ltb-scrim" onClick=${onClose}>
    <div class="ltb-pop" style=${`top:${Math.round(r.bottom + 6)}px;left:${Math.round(left)}px;width:${w}px`}
      onClick=${e => e.stopPropagation()}>${children}</div></div>`;
}

// lists = [{id, name, count}] (déjà filtrées sur le bon `kind`) ; footId = la liste du pédalier
// sorts = [[id, label]] ; filters = [{id, label, options:[[v,label]], value, set, multi}] — `value` vaut
// le défaut quand il est égal à `def` (le bouton ne le compte pas comme un filtre)
export function ListToolbar({ kind, lists, viewId, footId, onView, q, setQ, placeholder, sorts, sort, setSort, filters }) {
  const [open, setOpen] = useState(null);          // 'sort' | 'flt' | null
  const [searching, setSearching] = useState(!!q);
  const sortRef = useRef(null), fltRef = useRef(null), inRef = useRef(null);
  useEffect(() => { if (searching && inRef.current) inRef.current.focus(); }, [searching]);
  const ic = kind === 'sounds' ? '⛓' : '▤';
  const noun = kind === 'sounds' ? 'bank' : 'setlist';
  const active = (filters || []).filter(f => f.value !== f.def);
  const fltLabel = active.length ? active.map(f => (f.options.find(o => o[0] === f.value) || [0, f.value])[1]).join(' · ') : 'Filters';
  const sortLabel = ((sorts || []).find(s => s[0] === sort) || [0, ''])[1];
  return html`
    ${lists.length ? html`<select class="flt-sel ltb-list" value=${viewId || ''} title=${'the ' + noun + ' whose # you see and edit here — the pedalboard plays the one marked ●'}
        onChange=${e => onView(e.target.value)}>
        ${lists.map(x => html`<option value=${x.id} selected=${x.id === viewId}>${ic} ${esc(x.name)}${x.id === footId ? '  ●' : ''}</option>`)}
      </select>` : html`<span class="ltb-none">no ${noun} yet</span>`}
    ${searching || q
      ? html`<input ref=${inRef} class="search ltb-q" type="search" placeholder=${placeholder || 'Search…'} value=${q}
          onInput=${e => setQ(e.target.value)} onBlur=${e => { if (!e.target.value) setSearching(false); }} />`
      : html`<button class="ltb-btn ic" title="search" onClick=${() => setSearching(true)}>⌕</button>`}
    <button ref=${sortRef} class=${cls('ltb-btn', open === 'sort' && 'on')} title="sort" onClick=${() => setOpen(open === 'sort' ? null : 'sort')}>↕ ${esc(sortLabel)}</button>
    <button ref=${fltRef} class=${cls('ltb-btn', active.length && 'set', open === 'flt' && 'on')} title="filters"
      onClick=${() => setOpen(open === 'flt' ? null : 'flt')}>⚲ ${esc(fltLabel)}</button>
    ${open === 'sort' ? html`<${Pop} anchor=${sortRef.current} onClose=${() => setOpen(null)}>
        ${sorts.map(([id, lb, dead]) => html`<button class=${cls('ltb-opt', sort === id && 'on')} disabled=${!!dead} title=${dead || ''}
          onClick=${() => { setSort(id); setOpen(null); }}>${lb}</button>`)}
      </${Pop}>` : ''}
    ${open === 'flt' ? html`<${Pop} anchor=${fltRef.current} wide onClose=${() => setOpen(null)}>
        ${filters.map(f => html`<div class="ltb-sec"><small>${esc(f.title)}</small>
          <div class="ltb-chips">${f.options.map(([v, lb]) => html`<button class=${cls('ltb-chip', f.value === v && 'on')}
            onClick=${() => f.set(v)}>${lb}</button>`)}</div></div>`)}
        ${active.length ? html`<button class="ltb-opt reset" onClick=${() => { active.forEach(f => f.set(f.def)); setOpen(null); }}>Clear filters</button>` : ''}
      </${Pop}>` : ''}`;
}

// la liste regardée, mémorisée par onglet (confort par appareil ; repli : celle du pied, sinon la première)
export function useViewedList(key, lists, footId) {
  const read = () => { try { return localStorage.getItem('golem.view.' + key) || ''; } catch { return ''; } };
  const [id, setId] = useState(read);
  const ok = lists.some(x => x.id === id) ? id : (lists.some(x => x.id === footId) ? footId : ((lists[0] || {}).id || ''));
  const set = v => { setId(v); try { localStorage.setItem('golem.view.' + key, v); } catch { /* stockage indisponible */ } };
  return [ok, set];
}

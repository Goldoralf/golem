// SPDX-License-Identifier: GPL-3.0-or-later
// Navigateur de presets — le sélecteur du top menu. 2026-10-14 (« pour se repérer, un filtre pour les banks ») :
// un RAIL DE SETLISTS à gauche (celle du pied en tête), des rangées dans l'ordre de la setlist, des pages au lieu du
// défilement (mockups/browser-setlists.html, proposition de l'agent UX). Style, Sort et « On the foot » sont retirés :
// le rail fait leur travail. La même grammaire que le navigateur de patches (designer-browse.js).
import { html, useState, useEffect, cls, esc, genreLabel } from './lib.js';
import { SCENE_IDS } from './designer-model.js';
import { railLists, itemsFor, openSel, paginate, pageOfItem, matches } from './browser-model.mjs';
import { useSetlists, SetlistRail, BrowseRow, Pager, FeatureMenu, FeatIcons, FEAT, hasFeat } from './browser-rail.js';

export function PresetBrowser({ presets: all, current, onLoad, onClose, onSwitch }) {
  const [feat, setFeat] = useState('any');           // le menu « With » (browser-rail.js)
  const presets = all.filter(pr => hasFeat(pr, feat));
  const sl = useSetlists();
  const active = sl && sl.active;
  const lists = sl ? railLists(sl.setlists, 'presets', active) : [];
  const [sel, setSel] = useState(null);                  // null = pas encore ouvert (setlists en route)
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const SC5 = SCENE_IDS.slice(0, 5);
  // à l'ouverture : la setlist qui contient le preset joué (celle du pied d'abord), à SA page
  useEffect(() => {
    if (!sl || sel !== null) return;
    const s = openSel(lists, current);
    setSel(s); setPage(pageOfItem(itemsFor(s, presets, lists), current));
  }, [sl]);
  const searching = q.trim() !== '';
  const view = searching ? 'all' : (sel || 'all');       // la recherche porte toujours sur TOUT
  const items = itemsFor(view, presets, lists).filter(x => matches(x, q));
  const { shown, page: pg, pages, rows } = paginate(items, page);
  const stylesOf = pr => (pr.styles && pr.styles.length ? pr.styles : (pr.style ? [pr.style] : []));
  const pick = id => { setSel(id); setQ(''); setPage(0); };
  // un bloc choisi quand la setlist ouverte n'en a aucun : retour à « All » (le rail cache alors cette setlist)
  const pickFeat = f => {
    setFeat(f); setPage(0);
    const p2 = all.filter(pr => hasFeat(pr, f));
    if (sel && sel !== 'all' && !itemsFor(sel, p2, lists).length) setSel('all');
  };

  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card browse-modal brw">
      <div class="brw-hd">
        ${onSwitch ? html`<div class="tb-seg browse-kind" title="what to browse">
          <button class="on">Presets</button><button onClick=${onSwitch}>Patches</button></div>` : html`<h2>Presets</h2>`}
        <${FeatureMenu} all=${all} feat=${feat} onPick=${pickFeat} />
        <input class="search" placeholder="Search name / artist…" value=${q} autofocus
          onInput=${e => { setQ(e.target.value); setPage(0); }} />
        <button class="primary tb-new" onClick=${() => onLoad('')}>＋ New</button>
        <button class="brw-x" onClick=${onClose} aria-label="close">✕</button>
      </div>
      <div class="brw-bd">
        <${SetlistRail} kind="presets" lists=${lists} active=${active} pool=${presets} sel=${view} hideEmpty=${feat !== 'any'}
          remembered=${searching ? sel : null} onSel=${pick} />
        <div class="brw-main">
          ${shown.length ? html`<div class="brw-grid" style=${'--rows:' + rows}>
            ${shown.map(pr => {
              const tip = [pr.artist, stylesOf(pr).map(genreLabel).join(' · '), (pr.tags || []).join(' · ')].filter(Boolean).join(' — ');
              return html`<${BrowseRow} x=${pr} name=${esc(pr.name || pr.id)} sel=${view} lists=${lists} active=${active}
                styleCls=${'style-' + String(stylesOf(pr)[0] || 'rock').replace(/ /g, '-')} current=${pr.id === current}
                title=${tip} onPick=${() => onLoad(pr.id)}
                aside=${html`<${FeatIcons} x=${pr} />
                  <span class="brw-bpm">${pr.bpm ? '♩' + pr.bpm : ''}</span>
                  <span class="prow-scenes">${SC5.map(s => html`<i class=${cls((pr.scenes || []).some(x => x.id === s) && 'on')}>${s}</i>`)}</span>`} />`;
            })}
          </div>` : html`<div class="empty">${searching ? html`Nothing matches “${esc(q)}”.` : feat !== 'any'
            ? html`No preset with ${FEAT[feat].label.toLowerCase()} here.` : view === 'none'
            ? 'Every preset is in a setlist.' : html`No presets in this setlist — tap <b>＋ New</b> to start one.`}</div>`}
          <div class="brw-ft">
            <span class="brw-hint">${searching ? 'Searching every preset — clear the search to return to the setlist'
              : view === 'all' || view === 'none' ? 'A → Z' : 'In the order of the setlist' + (view === active ? ' — the order of the foot' : '')}</span>
            <${Pager} page=${pg} pages=${pages} onPage=${setPage} />
          </div>
        </div>
      </div>
    </div></div>`;
}

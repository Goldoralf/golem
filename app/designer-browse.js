// SPDX-License-Identifier: GPL-3.0-or-later
// Le navigateur de PATCHES du Designer (audit 2026-09-13, M7, troisième découpe) : filtré par instrument et par
// recherche, il rend le patch choisi au parent. 2026-10-14 : le rail des setlists de SONS à gauche et des rangées de
// 48 px — la grammaire du navigateur de presets (mockups/browser-setlists.html) ; l'instrument devient UN menu.
import { html, cls, esc, useState, useEffect } from './lib.js';
import { railLists, itemsFor, openSel, paginate, pageOfItem, matches } from './browser-model.mjs';
import { useSetlists, SetlistRail, BrowseRow, Pager, FeatureMenu, FeatIcons, hasFeat } from './browser-rail.js';

// Les QUATRE instruments d'un patch neuf — la même liste que le « + Add » de l'onglet Patches
// (2026-09-08 : le rôle décide du tiroir, des captures et de ce que l'IA propose).
// Une seule source : page-patches.js l'importe d'ici.
export const NEW_ROLES = [['guitar', 'Guitar', 'amps, pedals, cabs'], ['bass', 'Bass', 'bass amps and pedals'],
                          ['voice', 'Voice', 'vocal FX chain'], ['keys', 'Keys', 'synth · piano · organ · pads'],
                          ['drums', 'Drums', 'drum kit · dynamics · room']];   // docs/drums-kit.md : le 5e instrument (2026-09-17)

const PATCH_STYLE = { guitar: 'rock', bass: 'bass', voice: 'jazz', keys: 'blues', 'keys-pads': 'blues', pads: 'funk', drums: 'metal' };   // la couleur de carte par instrument (celle du Designer)

const ROLE_LABEL = r => r === 'all' ? 'All instruments' : r[0].toUpperCase() + r.slice(1);
// la rangée ne porte plus que « Factory » (2026-10-17) : « golem.fm » / « Local » ne disaient rien d'utile au
// choix, et le nombre de scènes non plus

export function PatchBrowser({ patches, patchMode, into, role: role0, setRole, q, setQ, laneRoleOf, onPick, onSwitchToPresets, onNew, onClose }) {
  const all = patches || [];
  const cur = (patchMode && (patchMode.role || patchMode.realm)) || 'guitar';
  const role = role0 ?? cur;                       // à l'ouverture : l'instrument courant
  // « ＋ New » SUIT l'instrument choisi (2026-09-14) : sur « All », il DEMANDE au lieu de deviner.
  const [addMenu, setAddMenu] = useState(false);
  const [roleMenu, setRoleMenu] = useState(false);
  const newPatch = () => { if (role !== 'all') { onNew(role); return; } setAddMenu(v => !v); };
  // le menu montre TOUJOURS les instruments d'un patch neuf, plus ceux que la bibliothèque contient
  const roles = [...new Set([...NEW_ROLES.map(r => r[0]), ...all.map(x => x.role || 'guitar')])].sort();
  const sl = useSetlists();
  const active = sl && sl.active;
  const lists = sl ? railLists(sl.setlists, 'patches', active) : [];
  // la lane ⚙ d'un patch porte aussi des blocs de service (docs/patches.md §3) : le menu « With » les filtre
  const [feat, setFeat] = useState('any');
  const ofRole = r => all.filter(x => r === 'all' || (x.role || 'guitar') === r);
  const pool = ofRole(role).filter(x => hasFeat(x, feat));
  const curId = patchMode && patchMode.id;
  const [sel, setSel] = useState(null);
  const [page, setPage] = useState(0);
  useEffect(() => {
    if (!sl || sel !== null) return;
    const s = openSel(lists, null);                 // les patches s'ouvrent sur « All » (l'instrument filtre déjà)
    setSel(s); setPage(pageOfItem(itemsFor(s, pool, lists), curId));
  }, [sl]);
  const searching = !!(q && q.trim());
  const view = searching ? 'all' : (sel || 'all');
  const items = itemsFor(view, pool, lists).filter(x => matches(x, q));
  const { shown, page: pg, pages, rows } = paginate(items, page);
  const nm = x => String(x.name || '').replace(/\s*·\s*[a-z-]+\s*$/i, '');
  const nBlocks = x => ((x.chain || {}).pre || (x.chain || {}).chain || []).length
    + (((x.chain || {}).split || {}).branches || []).reduce((n, br) => n + (br.blocks || []).length, 0);
  const pickSel = id => { setSel(id); setQ(''); setPage(0); };
  // changer d'instrument quand la setlist choisie n'a rien pour lui : retour à « All » (sinon une grille vide, et sa
  // setlist cachée par le rail — on ne saurait même plus d'où elle vient)
  const pickRole = r => {
    setRole(r); setRoleMenu(false); setPage(0);
    const p2 = ofRole(r).filter(x => hasFeat(x, feat));
    if (sel && sel !== 'all' && !itemsFor(sel, p2, lists).length) setSel('all');
  };
  const pickFeat = f => {
    setFeat(f); setPage(0);
    const p2 = ofRole(role).filter(x => hasFeat(x, f));
    if (sel && sel !== 'all' && !itemsFor(sel, p2, lists).length) setSel('all');
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card browse-modal brw pat-browse">
      <div class="brw-hd">
        ${into ? html`<h2 class="brw-into">Load into the ${laneRoleOf(into) || 'guitar'} lane</h2>` : html`<div class="tb-seg browse-kind" title="what to browse">
          <button onClick=${onSwitchToPresets}>Presets</button><button class="on">Patches</button></div>`}
        <div class="brw-inst">
          <button class=${cls('brw-instb', 'style-' + (PATCH_STYLE[role] || 'rock'))} onClick=${() => setRoleMenu(v => !v)}>
            ${role !== 'all' ? html`<i></i>` : ''}${ROLE_LABEL(role)} ▾</button>
          ${roleMenu ? html`<div class="save-pop brw-pop" onClick=${e => e.stopPropagation()}>
            ${['all', ...roles].map(r => html`<button class=${cls('row-btn', 'style-' + (PATCH_STYLE[r] || 'rock'), r === role && 'on')} onClick=${() => pickRole(r)}>
              ${r !== 'all' ? html`<i></i>` : ''}${ROLE_LABEL(r)}<small>${r === 'all' ? all.length : all.filter(x => (x.role || 'guitar') === r).length}</small></button>`)}
          </div>` : ''}
        </div>
        <${FeatureMenu} all=${ofRole(role)} feat=${feat} onPick=${pickFeat} />
        <input class="search" placeholder="Search…" value=${q} autofocus onInput=${e => { setQ(e.target.value); setPage(0); }} />
        ${into ? '' : html`<div class="pb-new-wrap">
          ${addMenu ? html`<div class="save-pop pb-new-pop" onClick=${e => e.stopPropagation()}>
            ${NEW_ROLES.map(([id, lb, sub]) => html`<button class="row-btn" onClick=${() => { setAddMenu(false); onNew(id); }}>${lb}<small>${sub}</small></button>`)}
          </div>` : ''}
          <button class="primary tb-new" title=${role === 'all' ? 'empty bench — pick the instrument' : 'empty ' + role + ' bench'}
            onClick=${newPatch}>＋ New${role !== 'all' ? ' ' + role : ''}</button>
        </div>`}
        <button class="brw-x" onClick=${onClose} aria-label="close">✕</button>
      </div>
      <div class="brw-bd">
        <${SetlistRail} kind="patches" lists=${lists} active=${active} pool=${pool} sel=${view} hideEmpty=${role !== 'all' || feat !== 'any'}
          remembered=${searching ? sel : null} onSel=${pickSel} />
        <div class="brw-main">
          ${shown.length ? html`<div class="brw-grid" style=${'--rows:' + rows}>
            ${shown.map(x => html`<${BrowseRow} x=${x} name=${esc(nm(x))} sel=${view} lists=${lists} active=${active}
              styleCls=${'style-' + (PATCH_STYLE[x.role] || 'rock')} current=${curId === x.id}
              title=${(into ? 'replaces the lane with this patch (chain + scenes) — ' : '') + nBlocks(x) + ' blocks'}
              onPick=${() => onPick(x)}
              aside=${html`<${FeatIcons} x=${x} />${x.origin === 'factory' ? html`<span class="brw-src">Factory</span>` : ''}`} />`)}
          </div>` : html`<div class="empty">${searching ? html`Nothing matches “${esc(q)}”.`
            : html`No ${role === 'all' ? '' : role + ' '}patch here${into ? '' : html` — tap <b>＋ New</b>`}.`}</div>`}
          <div class="brw-ft">
            <span class="brw-hint">${searching ? 'Searching every ' + (role === 'all' ? '' : role + ' ') + 'patch — clear the search to return to the setlist'
              : view === 'all' || view === 'none' ? 'A → Z' : 'In the order of the setlist'}</span>
            <${Pager} page=${pg} pages=${pages} onPage=${setPage} />
          </div>
        </div>
      </div>
    </div>
  </div>`;
}

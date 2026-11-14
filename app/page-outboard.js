// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Outboard (hub Library ▸ Tones) — les préamplis, tranches et compresseurs CAPTURÉS
// (TONE3000 gear=outboard, .nam ; docs/blocks-doctrine.md addendum quater). Un pack = un appareil,
// N modèles = ses réglages (le Capture dial les parcourt du plus propre au plus chaud,
// capture-gain.js). Visible sous tous les rôles du segment Tones : c'est le rôle de la LANE qui
// choisit ensuite la prise (mic pour une voix, DI/line pour le reste). « + Add » = TONE3000
// gear=outboard ; suppression = le flux partagé des captures (/api/amp/{id}, corbeille).
import { html, useState, useEffect, useAsync, cls, esc, safeHref, getCatalog, refreshCatalog, setTopAction, setSubToolbar, useRev } from './lib.js';
import { T3kModal } from './t3k-modal.js';
import { DeleteFlow } from './page-amps.js';
import { orderModels, describe } from './capture-gain.js';
import { useVisuals, Drawing, rackSvg, usePage, Pager, useAudition, PlayMark, AuditionNote } from './tones-ui.js';

const nameOf = t => t.amp || t.title || 'Outboard';

export function OutboardPage() {
  const [catTick, setCatTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data } = useAsync(getCatalog, [catTick, libRev]);
  const tones = (data && data.tones) || [];
  const packs = tones.filter(t => t.gear === 'outboard' && t.format !== 'ir');
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(null);
  const [t3k, setT3k] = useState(false);
  const reloadCat = () => { refreshCatalog(); setCatTick(x => x + 1); };

  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" title="download a captured preamp / compressor from TONE3000" onClick=${() => setT3k(true)}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);
  useEffect(() => {
    setSubToolbar(html`<input class="search" type="search" placeholder="Search preamp / compressor…"
      onInput=${e => setQ(e.target.value.trim().toLowerCase())} />`);
    return () => setSubToolbar(null);
  }, []);

  const match = t => !q || (nameOf(t) + ' ' + (t.brand || '') + ' ' + (t.tags || []).join(' ')).toLowerCase().includes(q);
  const list = packs.filter(match).sort((a, b) => (b.downloads || 0) - (a.downloads || 0));

  // LE RACK 19" (docs/library-tones.md §4) : un pack = une unité dessinée par golem-fx (namRack), des emplacements vides
  const fxDoc = useAsync(() => fetch('/api/effects').then(r => r.json()), []).data || null;
  const vis = useVisuals(fxDoc);
  const P = vis ? window.GolemPedals : null;
  const uOf = t => { const a = P && P.archetypeFor ? P.archetypeFor('outboard', nameOf(t)) : null; return (a && a.u) || 2; };
  const slots = list.slice(0, 6);
  const usedU = slots.reduce((s, t) => s + uOf(t), 0);

  if (sel) return html`<div class="library tn-page"><${UnitPanel} t=${sel} vis=${vis} onClose=${() => setSel(null)}
    onDeleted=${() => { setSel(null); reloadCat(); }} /></div>`;
  return html`<div class="library tn-page">
    <div class="tn-rackv">
      <div class="tn-rack">
        ${slots.map(t => html`<button class="tn-unit" style=${`height:${uOf(t) * 46}px`} onClick=${() => setSel(t)} title=${nameOf(t)}>
          ${vis ? html`<${Drawing} svg=${rackSvg(nameOf(t), null, true)} align="xMidYMid" />` : html`<div class="tn-draw"></div>`}</button>`)}
        <button class="tn-blank" onClick=${() => setT3k(true)}><span>+ Add outboard</span><small>Preamps, compressors, EQs captured on TONE3000</small></button>
        ${usedU < 8 ? html`<div class="tn-vent"></div>` : ''}${usedU < 5 ? html`<div class="tn-vent"></div>` : ''}
      </div>
      <aside class="tn-legend"><h6>In the rack</h6>
        ${list.map(t => html`<button class="tn-rb" onClick=${() => setSel(t)}>${nameOf(t)}<em>${(t.models || []).length}</em></button>`)}
        <p>${list.length ? 'Each unit is one capture pack. Tap a unit to see the settings it was captured at, and hear them.'
          : 'No captured outboard yet. A voice lane loads them as Preamp and Compressor (NAM capture) blocks.'}</p>
      </aside>
    </div>
    ${t3k ? html`<${T3kModal} initGear="outboard" onClose=${() => setT3k(false)} onInstalled=${reloadCat} />` : ''}
  </div>`;
}

// LA FICHE D'UNE UNITÉ (docs/library-tones.md §4) : ses captures lues comme UNE unité — chaque nom dit un réglage
// (golem-fx outboardSetting : « 1073MP - 60 dB Hard - B » = gain 60, hard, canal B). Les réglages qui varient
// deviennent une GRILLE (colonnes : gain, ratio ou temps ; lignes : normal / hard) et des sélecteurs (canal…) ;
// toucher une case tourne les commandes de l'unité et fait entendre cette capture. Sans réglage lisible : une liste.
const AX_LABEL = { gain: g => g + ' dB', ratio: r => r + ':1', time: x => String(x), limit: x => String(x), channel: x => String(x) };
function UnitPanel({ t, vis, onClose, onDeleted }) {
  const au = useAudition();
  const [del_, setDel] = useState(false);
  const P = vis ? window.GolemPedals : null;
  const rows = orderModels(t.models || []);
  const caps = rows.map(r => ({ m: r.m, g: r.g, s: (P && P.outboardSetting ? P.outboardSetting(r.m.name) : {}) || {} }));
  const vals = k => [...new Set(caps.map(c => c.s[k]).filter(v => v != null))];
  const colKey = ['gain', 'ratio', 'time'].find(k => vals(k).length > 1);
  const rowKey = vals('hard').length > 1 ? 'hard' : null;
  const selKeys = ['channel', 'limit'].filter(k => vals(k).length > 1 && k !== colKey);
  const [pick, setPick] = useState(() => Object.fromEntries(selKeys.map(k => [k, vals(k).sort()[0]])));
  const [cur, setCur] = useState(null);
  const sorted = k => vals(k).sort((x, y) => (typeof x === 'number' && typeof y === 'number') ? x - y : String(x).localeCompare(String(y)));
  const find = (cv, rv, pk) => caps.find(c => (!colKey || c.s[colKey] === cv) && (!rowKey || !!c.s.hard === rv)
    && selKeys.every(k => c.s[k] === pk[k]));
  const tap = c => { if (!c) return; setCur(c); au.play(t.id, c.m.id); };
  const shown = cur || caps.find(c => selKeys.every(k => c.s[k] === pick[k])) || caps[0];
  const grid = colKey || rowKey || selKeys.length;
  const pg = usePage(caps.length, 6, [t.id]);
  return html`<div class="tn-unitd">
    <button class="tn-back" onClick=${onClose}>‹ Outboard</button>
    <div class="tn-ubig">${vis ? html`<${Drawing} svg=${rackSvg(nameOf(t), shown ? shown.s : null, true)} align="xMidYMid" />` : ''}</div>
    <h2>${nameOf(t)}</h2>
    ${grid ? html`<div class="tn-matrix"><h6>Captured settings · tap one to hear it</h6>
      ${colKey ? html`<div class="tn-mrow head"><span></span>${sorted(colKey).map(v => html`<b>${AX_LABEL[colKey](v)}</b>`)}</div>` : ''}
      ${(rowKey ? [false, true] : [null]).map(rv => html`<div class="tn-mrow"><span>${rowKey ? (rv ? 'Hard' : 'Normal') : ''}</span>
        ${(colKey ? sorted(colKey) : [null]).map(cv => { const c = find(cv, rv, pick); const on = c && au.playing(t.id, c.m.id);
          return html`<button class=${cls('tn-cell', c && 'has', on && 'on')} disabled=${!c} onClick=${() => tap(c)}>${!c ? '—' : on ? '● playing' : au.loading(t.id, c.m.id) ? '…' : '▶'}</button>`; })}</div>`)}
      ${selKeys.map(k => html`<div class="tn-mrow"><span>${k[0].toUpperCase() + k.slice(1)}</span>
        ${sorted(k).map(v => html`<button class=${cls('tn-cell narrow has', pick[k] === v && 'on')} onClick=${() => {
          const pk = { ...pick, [k]: v }; setPick(pk);
          if (!colKey && !rowKey) tap(find(null, null, pk));
          else if (cur) tap(find(colKey ? cur.s[colKey] : null, rowKey ? !!cur.s.hard : null, pk)); }}>${v}</button>`)}<span class="grow"></span></div>`)}
    </div>` : html`<div class="tn-list">${caps.slice(pg.from, pg.to).map(c => html`<button class=${cls('tn-row', au.playing(t.id, c.m.id) && 'on')} onClick=${() => tap(c)}>
        <span class="nm">${c.m.name || 'setting'}<small>${describe(c.g)}</small></span><${PlayMark} on=${au.playing(t.id, c.m.id)} busy=${au.loading(t.id, c.m.id)} /></button>`)}
      <${Pager} pg=${pg} /></div>`}
    <${AuditionNote} au=${au} />
    <div class="tn-act"><span class="muted" style="font-size:12px">${caps.length} capture${caps.length > 1 ? 's' : ''} · ${t.brand || t.creator || ''}</span><span class="grow"></span>
      ${safeHref(t.url) ? html`<a class="mini" href=${safeHref(t.url)} target="_blank" rel="noopener">Source ↗</a>` : ''}
      <button class="mini danger" onClick=${() => setDel(true)}>Delete</button></div>
    ${del_ ? html`<div class="sheet-scrim"><div class="gf-sheet"><${DeleteFlow} t=${t} onDone=${() => { setDel(false); onDeleted(); }} onCancel=${() => setDel(false)} /></div></div>` : ''}
  </div>`;
}

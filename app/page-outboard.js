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

const nameOf = t => t.amp || t.title || 'Outboard';
const FAMILY = [['mic', 'Mic'], ['di', 'DI'], ['line', 'Line']];

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
  // les prises d'entrée que le pack propose (lues dans les noms de modèles) : « Mic / DI »
  const inputs = t => { const f = new Set(orderModels(t.models || []).map(r => r.g.family).filter(Boolean)); return FAMILY.filter(([k]) => f.has(k)).map(([, l]) => l); };

  const Card = t => html`
    <div class=${cls('card syn', sel && String(sel.id) === String(t.id) && 'on')} onClick=${() => setSel(t)} style="--sc:#d9a441">
      <div class="fxb-icon">⬡</div>
      <div class="syn-body">
        <h3>${esc(nameOf(t))}</h3>
        <div class="gear muted">${esc(t.brand || t.creator || '—')} · ${(t.models || []).length} setting(s)${inputs(t).length ? ' · ' + inputs(t).join(' / ') : ''}</div>
      </div>
    </div>`;

  return html`<div class="library">
    <div class="lib-grid">
      ${list.length ? html`<div class="syn-pack"><div class="grid gsyn">${list.map(Card)}</div></div>`
        : html`<div class="empty">No captured outboard yet — tap <b>+ Add</b> to download a preamp or compressor capture from TONE3000 (Neve 1073, 1176, LA-2A…). A voice lane loads them as <b>Preamp</b> and <b>Compressor (NAM capture)</b> blocks.</div>`}
    </div>
    ${sel ? html`<${Detail} t=${sel} onClose=${() => setSel(null)} onDeleted=${() => { setSel(null); reloadCat(); }} />` : ''}
    ${t3k ? html`<${T3kModal} initGear="outboard" onClose=${() => setT3k(false)} onInstalled=${reloadCat} />` : ''}
  </div>`;
}

function Detail({ t, onClose, onDeleted }) {
  const [del_, setDel] = useState(false);
  const rows = orderModels(t.models || []);            // du plus propre au plus chaud, doublons 44.1k retirés
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card" style="--sc:#d9a441">
      <button class="close" onClick=${onClose}>×</button>
      <button class="mini danger amp-del" title="delete this capture (trash)" onClick=${() => setDel(true)}>🗑</button>
      ${del_ ? html`<${DeleteFlow} t=${t} onDone=${() => { setDel(false); onDeleted(); }} onCancel=${() => setDel(false)} />` : ''}
      <span class="badge" style="background:#d9a441">outboard</span>
      <h2>⬡ ${esc(nameOf(t))}</h2>
      <div class="sub">${esc(t.brand || t.creator || 'unknown')} · ${rows.length} setting(s)${t.downloads ? ' · ⬇ ' + t.downloads : ''}</div>
      ${(t.tags || []).length ? html`<div class="kv"><strong>Tags:</strong> ${(t.tags || []).map(m => html`<span class="tag">${esc(m)}</span>`)}</div>` : ''}
      <div class="models"><strong>Settings (clean → hot):</strong>${rows.map(r => html`<div><span>${esc(r.m.name || '')}</span><span class="muted">${esc(describe(r.g))}</span></div>`)}</div>
      <p class="muted" style="margin-top:14px">Load it from the Designer: <b>Preamp</b> or <b>Compressor (NAM capture)</b> block, category Preamp / Dynamics. The default setting follows the lane: mic for a voice, DI/line for the rest.</p>
      ${t.url ? html`<p style="margin-top:10px"><a href=${safeHref(t.url)} target="_blank" rel="noopener">Source ↗</a></p>` : ''}
    </div></div>`;
}

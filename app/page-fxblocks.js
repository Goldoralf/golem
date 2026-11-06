// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet « Pedals » (hub Library) — palette des BLOCKS d'effets DSP disponibles (effects.json via
// /api/effects). Ce sont des effets branchés sur des plugins (ReaComp, guitarix LV2…), pas des
// fichiers : on les PARCOURT (nom, plugin, params), groupés par catégorie. « + Add » ne fabrique pas
// un block DSP (= intégration plugin, côté dev) mais importe une CAPTURE NAM de pédale depuis
// TONE3000 (gear=pedal) — le seul « ajout de pédale » qui a un sens depuis l'UI.
// NB : distinct de page-pedals.js (panneau MIDI Whammy DT de Settings ▸ Pedalboard).
import { html, useState, useEffect, useAsync, cls, esc, setTopAction, setSubToolbar, getCatalog, refreshCatalog, useRev } from './lib.js';
import { CAT_COLOR, ICON, capText, archOf } from './designer-model.js';
import { T3kModal } from './t3k-modal.js';
import { Detail as CaptureDetail, famOf } from './page-amps.js';

const catColor = c => CAT_COLOR[c] || '#8a94a3';
const CAT_LABEL = {
  dynamics: 'Dynamics', drive: 'Drive', filter: 'Filter', amp: 'Amp', cab: 'Cab', eq: 'EQ',
  modulation: 'Modulation', delay: 'Delay', reverb: 'Reverb', pitch: 'Pitch', utility: 'Utility',
};
// pédales NOMMÉES (archétypes effects.json pedals[]) : familles + ordre d'affichage
const PED_FAM = [['overdrive', 'Overdrive'], ['distortion', 'Distortion'], ['fuzz', 'Fuzz'], ['boost', 'Boost'], ['bass', 'Bass']];
const isBass = a => (a.roles || ['guitar']).includes('bass');

export function FxBlocksPage({ role, gears } = {}) {
  const { data } = useAsync(() => fetch('/api/effects').then(r => r.json()), []);
  const [catTick, setCatTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data: catalog } = useAsync(getCatalog, [catTick, libRev]);   // captures installées (gear=pedal)
  const cats = (data && data.categories) || [];
  // le RÔLE (segment Tones) filtre la palette comme le tiroir du Designer : catégories de
  // role_categories + `roles` par bloc ; et les captures de pédales par famille (guitar/bass)
  const roleCats = role && data && data.role_categories && Array.isArray(data.role_categories[role]) ? data.role_categories[role] : null;
  const fx = ((data && data.effects) || []).filter(e => (!roleCats || roleCats.includes(e.category)) && (!role || !e.roles || e.roles.includes(role)));
  const roleCanLoad = !gears || gears.has('pedal');
  const pedals = (data && data.pedals) || [];     // pédales NOMMÉES (archétypes) — Big Muff, TS, Fortin…
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('all');
  const [sel, setSel] = useState(null);
  const [selPed, setSelPed] = useState(null);     // détail d'une pédale nommée
  const [selCap, setSelCap] = useState(null);     // détail d'une CAPTURE installée
  const [t3k, setT3k] = useState(false);          // modal + Add (capture NAM de pédale)

  // « + Add » CONTEXTUEL dans la topbar → modal TONE3000 PRÉ-FILTRÉ Pedals (recherche de captures)
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${() => setT3k(true)}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);

  const match = e => (cat === 'all' || e.category === cat)
    && (!q || (e.name + ' ' + (e.short || '') + ' ' + e.type + ' ' + (e.plugin || '')).toLowerCase().includes(q));
  const list = fx.filter(match);
  const groups = cats.filter(c => list.some(e => e.category === c));

  // pédales NOMMÉES (archétypes) : visibles quand la catégorie est « all » ou « drive » (leur famille)
  const pedMatch = a => (cat === 'all' || cat === 'drive')
    && (!q || (a.name + ' ' + (a.short || '') + ' ' + (a.match || '') + ' ' + a.family).toLowerCase().includes(q));
  const namedPeds = pedals.filter(pedMatch);
  const pedFams = PED_FAM.filter(([f]) => namedPeds.some(a => a.family === f));

  // ── captures INSTALLÉES gear=pedal, rattachées à leur pédale nommée : règle unique
  // partagée (designer-model.archOf). Les orphelines restent visibles. ──
  const pedOf = t => archOf(pedals, t);
  // format=ir exclu : les packs d'IR « de pédale » (cab-sim capturé en .wav) vivent dans Cabs
  const pedCaps = (((catalog && catalog.tones) || []).filter(t => t.gear === 'pedal' && t.format !== 'ir'
    && roleCanLoad && (!role || role === 'voice' || famOf(t) === role)));
  const capsByPed = {}, orphans = [];
  for (const t of pedCaps) { const a = pedOf(t); if (a) (capsByPed[a.id] = capsByPed[a.id] || []).push(t); else orphans.push(t); }
  const shownOrphans = (cat === 'all' || cat === 'drive')
    ? orphans.filter(t => !q || capText(t).includes(q)).sort((x, y) => (x.amp || x.title || '').localeCompare(y.amp || y.title || ''))
    : [];

  const Card = e => html`
    <div class=${cls('card syn', sel && sel.type === e.type && 'on')} onClick=${() => setSel(e)}
      style=${'--sc:' + catColor(e.category)}>
      <div class="fxb-icon">${ICON[e.type] || e.icon || '▪'}</div>
      <div class="syn-body">
        <h3>${esc(e.name)}</h3>
        <div class="gear muted">${esc(e.short || CAT_LABEL[e.category] || e.category)} · ${esc(e.plugin || e.engine)}</div>
      </div>
    </div>`;

  const PedCard = a => { const caps = capsByPed[a.id] || [];
    return html`
    <div class=${cls('card syn', selPed && selPed.id === a.id && 'on')} onClick=${() => setSelPed(a)} style=${'--sc:' + (a.color || '#ffb03a')}>
      <div class="fxb-icon">${a.glyph || '⬢'}</div>
      <div class="syn-body">
        <h3>${esc(a.name)}${isBass(a) ? html` <span class="ped-bass" title="bass pedal">🎸</span>` : ''}</h3>
        <div class="gear muted">${esc(a.family)}${isBass(a) && a.family !== 'bass' ? ' · bass' : ''} · NAM capture</div>
        ${caps.length ? html`<div class="amp-caps">
          ${caps.slice(0, 2).map(t => html`<div class="amp-cap-line">${esc(t.amp || t.title)}</div>`)}
          ${caps.length > 2 ? html`<div class="amp-cap-line muted">+ ${caps.length - 2} more…</div>` : ''}
        </div>` : html`<div class="gear muted">no capture yet</div>`}
      </div>
    </div>`; };
  // capture installée SANS pédale nommée : reste visible ici, cliquable (modal capture partagé)
  const OrphanCard = t => html`
    <div class=${'card cpt style-' + (t.style || 'rock')} onClick=${() => setSelCap(t)}>
      <h3>${esc(t.amp || t.title)}</h3>
      <div class="gear">${esc(t.brand || t.creator || '')} · ${(t.models || []).length} mdl${(t.models || []).some(m => String(m.arch) === '2') ? html` · <span class="a2-chip">A2</span>` : ''}</div>
    </div>`;

  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search block / plugin…"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <select class="flt-sel" value=${cat} onChange=${e => setCat(e.target.value)} title="Category">
        <option value="all">Category · all</option>
        ${cats.map(c => html`<option value=${c} selected=${c === cat}>${CAT_LABEL[c] || c}</option>`)}
      </select>`);
    return () => setSubToolbar(null);
  }, [cat, cats.length]);

  return html`
    <div class="library">
      <div class="lib-grid">
        ${namedPeds.length ? html`<div class="syn-pack">
          ${pedFams.map(([f, lbl]) => html`<div class="np-fam">
            <div class="np-fam-hd muted">${lbl}</div>
            <div class="grid gsyn">${namedPeds.filter(a => a.family === f).map(PedCard)}</div>
          </div>`)}
          ${shownOrphans.length ? html`<div class="np-fam">
            <div class="np-fam-hd muted">Other captures <span>${shownOrphans.length}</span></div>
            <div class="grid gcpt">${shownOrphans.map(OrphanCard)}</div>
          </div>` : ''}
        </div>` : ''}
        ${list.length ? groups.map(c => html`
          <div class="syn-pack">
            <div class="syn-pack-hd" style=${'color:' + catColor(c)}>${CAT_LABEL[c] || c}
              <span class="muted">${list.filter(e => e.category === c).length}</span></div>
            <div class="grid gsyn">${list.filter(e => e.category === c).map(Card)}</div>
          </div>`)
        : (!namedPeds.length ? html`<div class="empty">No effect blocks for these filters.</div>` : '')}
      </div>

      ${sel ? html`<${Detail} e=${sel} onClose=${() => setSel(null)} />` : ''}
      ${selPed ? html`<${PedDetail} a=${selPed} caps=${capsByPed[selPed.id] || []}
        onCap=${t => { setSelPed(null); setSelCap(t); }}
        onClose=${() => setSelPed(null)} onT3k=${() => { setSelPed(null); setT3k(true); }} />` : ''}
      ${selCap ? html`<${CaptureDetail} t=${selCap} onClose=${() => setSelCap(null)}
        onDeleted=${() => { setSelCap(null); refreshCatalog(); setCatTick(x => x + 1); }} />` : ''}
      ${t3k ? html`<${T3kModal} initGear="pedal" onClose=${() => setT3k(false)} onInstalled=${() => { refreshCatalog(); setCatTick(x => x + 1); }} />` : ''}
    </div>`;
}

// détail d'une PÉDALE NOMMÉE (archétype) : ce que c'est + comment l'ajouter (tiroir Designer,
// picker de capture TONE3000). Pas un fichier installé -> pas de suppression ici.
function PedDetail({ a, caps, onCap, onClose, onT3k }) {
  return html`<div class="detail" onClick=${ev => ev.target.classList.contains('detail') && onClose()}>
    <div class="detail-card" style=${'--sc:' + (a.color || '#ffb03a')}>
      <button class="close" onClick=${onClose}>×</button>
      <span class="badge" style=${'background:' + (a.color || '#ffb03a')}>${esc(a.family)}${isBass(a) ? ' · bass' : ''}</span>
      <h2>${a.glyph || '⬢'} ${esc(a.name)}</h2>
      <div class="sub">Named pedal · ${isBass(a) ? 'bass' : 'guitar'} · plays through a <b>NAM capture</b> · ${(caps || []).length} capture(s) on the rack</div>
      ${(caps || []).length ? html`<div class="models" style="margin-top:12px"><strong>Your captures:</strong>
        ${caps.map(t => html`<div class="arch-cap" onClick=${() => onCap(t)} title="open this capture">
          <span>${esc(t.amp || t.title)}</span>
          <span class="muted">${esc(t.brand || t.creator || '')}${(t.models || []).some(m => String(m.arch) === '2') ? ' · A2' : ''} · ⬇ ${t.downloads || 0}</span>
        </div>`)}
      </div>` : ''}
      <p class="muted" style="margin-top:12px">A real pedal by name. Add it from the <b>Designer ▸ +</b> drawer
        (${isBass(a) ? 'a Bass' : 'the'} input's Drive section) — the picker opens pre-filtered on
        <b>${esc(a.match || a.name)}</b> captures (installed + downloadable). Empty is fine: pick a capture later.</p>
      <div class="kv"><strong>Search:</strong> <span class="tag">${esc(a.match || a.name)}</span></div>
      <p style="margin-top:16px"><button class="chip" onClick=${onT3k}>⬇ Browse TONE3000 captures</button></p>
    </div></div>`;
}

function Detail({ e, onClose }) {
  const params = e.params || [];
  return html`<div class="detail" onClick=${ev => ev.target.classList.contains('detail') && onClose()}>
    <div class="detail-card" style=${'--sc:' + catColor(e.category)}>
      <button class="close" onClick=${onClose}>×</button>
      <span class="badge" style=${'background:' + catColor(e.category)}>${esc(CAT_LABEL[e.category] || e.category)}</span>
      <h2>${ICON[e.type] || e.icon || ''} ${esc(e.name)}</h2>
      <div class="sub">${esc(e.type)} · ${esc(e.plugin || '')} <span class="muted">(${esc(e.engine || 'plugin')})</span></div>
      ${e.note ? html`<p class="muted" style="margin-top:10px">${esc(e.note)}</p>` : ''}
      ${params.length ? html`<div class="models" style="margin-top:14px"><strong>Params:</strong>
        ${params.map(p => html`<div><span>${esc(p.name)}</span><span class="muted">${esc(p.min)}…${esc(p.max)}${p.unit ? ' ' + esc(p.unit) : ''} · def ${esc(p.default)}</span></div>`)}
      </div>` : html`<p class="muted" style="margin-top:14px">No parameters.</p>`}
      <p class="muted" style="margin-top:16px">Drop this block into a chain from the <b>Designer ▸ +</b> drawer.
        ${e.loads ? html`<br/>Loads a capture — pick a model on add.` : ''}</p>
    </div></div>`;
}

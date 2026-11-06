// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet IR (hub Library) — impulse responses (cabs). Source = catalogue tones (gear=cab / format=ir,
// même index que Amps), filtrées ici. « + Add » propose DEUX voies : upload d'un .wav local (corps
// brut vers /api/ir/upload, façon Vital) OU téléchargement depuis TONE3000 (T3kModal gear=cab).
// Suppression = flux amp partagé (/api/amp/{id} : corbeille + dépendances par preset).
import { html, useState, useEffect, useRef, useAsync, cls, esc, safeHref, getCatalog, refreshCatalog, setTopAction, setSubToolbar, useRev } from './lib.js';
import { T3kModal } from './t3k-modal.js';
import { DeleteFlow, famOf } from './page-amps.js';

const irName = t => t.amp || t.title || 'IR';
// « pack à écho » (2026-09-14) : le rack a LU les fichiers — une impulsion tardive répète chaque note.
// Le compile coupe la copie avant l'écho, donc le pack reste jouable ; le badge dit ce qu'il contient.
const echoTitle = e => `${e.bad}/${e.files} IR file${e.files > 1 ? 's' : ''} carry a late impulse (worst: ${e.worst_ms} ms at ${e.worst_db} dB) — a second hit per note. Played CUT before the echo; a clean pack is better.`;
const styleColor = s => ({ metal: '#ff5a3c', rock: '#ffb03a', blues: '#5a7cff', jazz: '#b06cf0',
  funk: '#2ecc71', bass: '#e0b23a' }[s] || '#1ab7b0');

export function IRPage({ role, gears } = {}) {
  const [catTick, setCatTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data } = useAsync(getCatalog, [catTick, libRev]);
  const tones = (data && data.tones) || [];
  const roleCanLoad = !gears || gears.has('cab');
  const irs = tones.filter(t => (t.gear === 'cab' || t.format === 'ir') && (!role || role === 'voice' || famOf(t) === role));
  const [q, setQ] = useState('');
  const [style, setStyle] = useState('all');
  const [sel, setSel] = useState(null);
  const [t3k, setT3k] = useState(false);
  const [addMenu, setAddMenu] = useState(false);  // « + Add » -> menu 2 voies (TONE3000 / upload)
  const [busy, setBusy] = useState('');           // message d'état upload
  const fileRef = useRef(null);
  const reloadCat = () => { refreshCatalog(); setCatTick(x => x + 1); };

  // upload : POST chaque .wav en CORPS BRUT vers /api/ir/upload?name= puis rafraîchit le catalogue
  const uploadFiles = async files => {
    let added = 0, errs = [];
    for (const f of Array.from(files || [])) {
      setBusy(`⬆ ${f.name}…`);
      try {
        const r = await fetch('/api/ir/upload?name=' + encodeURIComponent(f.name),
          { method: 'POST', body: f }).then(x => x.json());
        if (r.ok) added += 1; else errs.push(`${f.name}: ${r.error}`);
      } catch (e) { errs.push(`${f.name}: ${e}`); }
    }
    setBusy(errs.length ? `✗ ${errs[0]}` : `✓ ${added} IR added`);
    reloadCat();
    setTimeout(() => setBusy(''), 4000);
  };

  // « + Add » CONTEXTUEL : ouvre un mini-menu 2 voies (TONE3000 gear Cabs/IR, OU upload .wav local).
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${() => setAddMenu(true)}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);

  const styles = [...new Set(irs.map(t => t.style).filter(Boolean))].sort();
  const match = t => (style === 'all' || t.style === style)
    && (!q || (irName(t) + ' ' + (t.brand || '') + ' ' + (t.creator || '') + ' ' + (t.tags || []).join(' ')).toLowerCase().includes(q));
  const list = irs.filter(match).sort((a, b) => (b.downloads || 0) - (a.downloads || 0));
  // ── classement PAR MARQUE (« comme les tiroirs ») : la marque, sinon 1er fabricant, sinon Other ;
  // marques génériques (« Cabs / IR ») rejetées. Dans chaque marque : modèles triés A→Z. ──
  const GENERIC = /^(cabs?\s*\/?\s*ir|ir|cab|other|divers|unknown|\-|)$/i;
  // un `brand` peut arriver en OBJET ({Name}) depuis golem.fm — un en-tête « {'Name': …} » vu à l'écran le 2026-09-14
  const brandOf = t => { const raw = t.brand && typeof t.brand === 'object' ? (t.brand.Name || t.brand.name || '') : (t.brand || '');
    const b = String(raw).trim();
    if (b && !GENERIC.test(b)) return b;
    const m = (t.makes || []).find(x => x && !GENERIC.test(x));
    return m || 'Other'; };
  const brands = [...new Set(list.map(brandOf))].sort((a, b) => a === 'Other' ? 1 : b === 'Other' ? -1 : a.localeCompare(b));
  const byBrand = b => list.filter(t => brandOf(t) === b).sort((x, y) => irName(x).localeCompare(irName(y)));

  const Card = t => html`
    <div class=${cls('card syn', sel && String(sel.id) === String(t.id) && 'on')} onClick=${() => setSel(t)}
      style=${'--sc:' + styleColor(t.style)}>
      <div class="fxb-icon">◨</div>
      <div class="syn-body">
        <h3>${esc(irName(t))}</h3>
        <div class="gear muted">${esc(t.creator || t.brand || '—')}${t.models ? ' · ' + t.models.length + ' IR' : ''}${t.style ? ' · ' + esc(t.style) : ''}</div>
        ${t.echo ? html`<span class="echo-chip" title=${echoTitle(t.echo)}>⚠ echo</span>` : ''}
      </div>
    </div>`;

  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search cab / creator…"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <select class="flt-sel" value=${style} onChange=${e => setStyle(e.target.value)} title="Style">
        <option value="all">Style · all</option>
        ${styles.map(s => html`<option value=${s} selected=${s === style}>${s}</option>`)}
      </select>
      ${busy ? html`<span class="syn-busy">${busy}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [style, styles.length, busy]);

  if (!roleCanLoad) return html`<div class="library"><div class="empty">A <b>${esc(role)}</b> lane has no cab — see <b>Outboard</b>.</div></div>`;

  return html`
    <div class="library">
      <input id="ir-file-input" ref=${fileRef} type="file" accept=".wav,audio/wav" multiple
        style="display:none" onChange=${e => { uploadFiles(e.target.files); e.target.value = ''; }} />
      <div class="lib-grid">
        ${list.length ? brands.map(b => html`
          <div class="syn-pack">
            <div class="syn-pack-hd">${esc(b)} <span class="muted">${byBrand(b).length}</span></div>
            <div class="grid gsyn">${byBrand(b).map(Card)}</div>
          </div>`)
        : html`<div class="empty">No IRs — tap <b>+ Add</b> to import a <code>.wav</code> impulse response,
            or download cab IRs from TONE3000.</div>`}
      </div>

      ${addMenu ? html`<div class="add-scrim" onClick=${() => setAddMenu(false)}>
        <div class="add-menu" onClick=${e => e.stopPropagation()}>
          <button class="row-btn" onClick=${() => { setAddMenu(false); setT3k(true); }}>⬇ From TONE3000 <small>cab IRs</small></button>
          <button class="row-btn" onClick=${() => { setAddMenu(false); document.getElementById('ir-file-input')?.click(); }}>⬆ Upload a <code>.wav</code></button>
        </div></div>` : ''}
      ${sel ? html`<${Detail} t=${sel} onClose=${() => setSel(null)}
        onDeleted=${() => { setSel(null); reloadCat(); }} />` : ''}
      ${t3k ? html`<${T3kModal} initGear="cab" onClose=${() => setT3k(false)} onInstalled=${reloadCat} />` : ''}
    </div>`;
}

function Detail({ t, onClose, onDeleted }) {
  const [del_, setDel] = useState(false);
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card" style=${'--sc:' + styleColor(t.style)}>
      <button class="close" onClick=${onClose}>×</button>
      <button class="mini danger amp-del" title="delete this IR (trash)" onClick=${() => setDel(true)}>🗑</button>
      ${del_ ? html`<${DeleteFlow} t=${t} onDone=${() => { setDel(false); onDeleted(); }} onCancel=${() => setDel(false)} />` : ''}
      <span class="badge" style=${'background:' + styleColor(t.style)}>${esc(t.style || 'ir')}</span>
      <h2>◨ ${esc(irName(t))}</h2>
      <div class="sub">${esc(t.creator || t.brand || 'unknown')}${t.models ? ' · ' + t.models.length + ' IR file(s)' : ''}
        ${t.downloads ? ' · ⬇ ' + t.downloads : ''}</div>
      ${t.echo ? html`<p class="echo-note"><span class="echo-chip">⚠ echo</span> ${echoTitle(t.echo)}</p>` : ''}
      ${(t.makes || []).length ? html`<div class="kv"><strong>Cab:</strong> ${(t.makes || []).map(m => html`<span class="tag">${esc(m)}</span>`)}</div>` : ''}
      ${(t.tags || []).length ? html`<div class="kv"><strong>Tags:</strong> ${(t.tags || []).map(m => html`<span class="tag">${esc(m)}</span>`)}</div>` : ''}
      <div class="models"><strong>Files:</strong>${(t.models || []).map(m => html`<div><span>${esc(m.name || 'IR')}</span><span class="muted">${esc(m.size || '')}</span></div>`)}</div>
      <p class="muted" style="margin-top:14px">Assign this IR to a <b>Cab</b> block in the Designer (pick it from the <b>+</b> drawer).</p>
      ${t.url ? html`<p style="margin-top:10px"><a href=${safeHref(t.url)} target="_blank" rel="noopener">Source ↗</a></p>` : ''}
    </div></div>`;
}

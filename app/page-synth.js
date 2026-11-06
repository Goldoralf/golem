// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Synth (hub Library) — bibliothèque des presets Vital de la lane Keys.
// Ajout : upload .vital / .vitalbank / .zip (corps brut, pas de multipart) + rescan après dépôt
// manuel. Organisation : groupés par PACK, filtrables par style (tag natif Vital) + recherche.
// Les .vital portent leur propre métadonnée (author, preset_style) -> zéro étiquetage manuel.
import { html, useState, useEffect, useAsync, cls, esc, post, del, setTopAction, setSubToolbar, useRev } from './lib.js';

// couleur de pastille par style Vital (tags natifs : Bass/Lead/Keys/Pad/Percussion/Sequence/SFX…)
const STYLE_COLOR = {
  Bass: '#e0b23a', Lead: '#ff5a3c', Keys: '#3d9be9', Pad: '#b06cf0',
  Percussion: '#8a94a3', Sequence: '#2ecc71', SFX: '#5ec8e0', Experiment: '#ff851b',
};
const styleColor = s => STYLE_COLOR[s] || '#8a94a3';

export function SynthPage() {
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data, reload } = useAsync(() => fetch('/api/vital/presets').then(r => r.json()), [libRev]);
  const presets = (data && data.presets) || [];
  const [q, setQ] = useState('');
  const [style, setStyle] = useState('all');
  const [busy, setBusy] = useState('');            // message d'état upload/rescan
  const [sel, setSel] = useState(null);            // preset ouvert (détail + suppression)
  const fileRef = useState(null)[0];               // placeholder (input via ref DOM ci-dessous)

  // upload : POST le fichier en CORPS BRUT vers /api/vital/upload?name= (chaque fichier), puis refresh
  const uploadFiles = async files => {
    let added = 0, errs = [];
    for (const f of Array.from(files || [])) {
      setBusy(`⬆ ${f.name}…`);
      try {
        const r = await fetch('/api/vital/upload?name=' + encodeURIComponent(f.name),
          { method: 'POST', body: f }).then(x => x.json());
        if (r.ok) added += (r.added || []).length; else errs.push(`${f.name}: ${r.error}`);
      } catch (e) { errs.push(`${f.name}: ${e}`); }
    }
    setBusy(errs.length ? `✗ ${errs[0]}` : `✓ ${added} preset(s) added`);
    reload();
    setTimeout(() => setBusy(''), 4000);
  };
  const rescan = async () => {
    setBusy('⟳ rescan…');
    const r = await post('/api/vital/rescan').catch(() => ({}));
    setBusy(`✓ ${r.count ?? '?'} preset(s)`); reload();
    setTimeout(() => setBusy(''), 3000);
  };

  // « + Add » contextuel dans la topbar : ouvre le sélecteur de fichier (input caché du body)
  useEffect(() => {
    const pick = () => document.getElementById('vital-file-input')?.click();
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${pick}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);

  const styles = [...new Set(presets.map(p => p.style).filter(Boolean))].sort();
  // toolbar compacte (search/filtres) publiée dans la barre de sous-onglets (remplace .lib-head)
  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search preset / author…"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <select class="flt-sel" value=${style} onChange=${e => setStyle(e.target.value)} title="Style">
        <option value="all">Style · all</option>
        ${styles.map(s => html`<option value=${s} selected=${s === style}>${s}</option>`)}
      </select>
      <button class="mini edit-only" onClick=${rescan} title="re-index after dropping .vital files manually">⟳</button>
      ${busy ? html`<span class="syn-busy">${busy}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [style, styles.length, busy]);
  const match = p => (style === 'all' || p.style === style)
    && (!q || (p.name + ' ' + (p.author || '') + ' ' + (p.pack || '')).toLowerCase().includes(q));
  const list = presets.filter(match);
  // groupé par pack (factory d'abord, puis alpha)
  const packs = [...new Set(list.map(p => p.pack || 'user'))]
    .sort((a, b) => (a === 'factory' ? -1 : b === 'factory' ? 1 : a.localeCompare(b)));

  const Card = p => html`
    <div class=${cls('card syn', sel && sel.id === p.id && 'on')} onClick=${() => setSel(p)}
      style=${'--sc:' + styleColor(p.style)}>
      <div class="syn-dot"></div>
      <div class="syn-body">
        <h3>${esc(p.name)}</h3>
        <div class="gear muted">${esc(p.author || '—')}${p.style ? ' · ' + esc(p.style) : ''}</div>
      </div>
    </div>`;

  return html`
    <div class="library">
      <input id="vital-file-input" type="file" accept=".vital,.vitalbank,.zip" multiple
        style="display:none" onChange=${e => { uploadFiles(e.target.files); e.target.value = ''; }} />
      <div class="lib-grid">
        ${list.length ? packs.map(pk => html`
          <div class="syn-pack">
            ${pk === 'factory' ? '' : html`<div class="syn-pack-hd">${esc(pk)}
              <span class="muted">${list.filter(p => (p.pack || 'user') === pk).length}</span></div>`}
            <div class="grid gsyn">${list.filter(p => (p.pack || 'user') === pk).map(Card)}</div>
          </div>`)
        : html`<div class="empty">No Vital presets — tap <b>+ Add</b> to import a .vital, .vitalbank or .zip pack
            (from the vital.audio store), or drop files in <code>library/synth/vital/</code> and Rescan.</div>`}
      </div>

      ${sel ? html`<${Detail} p=${sel} onClose=${() => setSel(null)}
        onDeleted=${() => { setSel(null); reload(); }} />` : ''}
    </div>`;
}

function Detail({ p, onClose, onDeleted }) {
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const isFactory = (p.pack || '') === 'factory';
  const doDelete = async () => {
    setBusy(true); setErr('');
    try {
      const r = await del('/api/vital/preset/' + encodeURIComponent(p.id));
      if (!r.ok) throw new Error(r.error || 'failed');
      onDeleted();
    } catch (e) { setErr(String(e.message || e)); setBusy(false); }
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card" style=${'--sc:' + styleColor(p.style)}>
      <button class="close" onClick=${onClose}>×</button>
      <span class="badge" style=${'background:' + styleColor(p.style)}>${esc(p.style || 'preset')}</span>
      <h2>${esc(p.name)}</h2>
      <div class="sub">${esc(p.author || 'unknown')} · pack « ${esc(p.pack || 'user')} »</div>
      <p class="muted" style="margin-top:14px">Assign this sound to a scene in the <b>Designer ▸ Keys</b> lane
        (the Preset knob is scene-first — one Vital sound per scene).</p>
      <div class="del-foot" style="margin-top:18px">
        <span class="flash-ko">${err}</span><span class="grow"></span>
        ${isFactory ? html`<span class="muted">factory seed — protected</span>`
          : html`<button class="primary" onClick=${doDelete} disabled=${busy}>${busy ? '…' : '🗑 Delete (to trash)'}</button>`}
      </div>
    </div></div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Synths (hub Library ▸ Keys) — la bibliothèque des presets Vital de la lane Keys.
// Ajout : upload .vital / .vitalbank / .zip (corps brut, pas de multipart) + rescan après dépôt manuel. Les .vital
// portent leur propre métadonnée (auteur, preset_style, macros, commentaire) : zéro étiquetage manuel.
// 2026-11-14 (maquette validée, docs/preset-preview.md §9.1) : un MUR paginé (l'écran ne défile jamais) où chaque
// preset est DESSINÉ par golem-fx (keysUnit compact : la couleur et l'onde de son style, ses quatre macros) et
// s'ENTEND au toucher — la démo rendue à travers le preset seul (bridge/sound_preview.py) ; ceux de l'utilisateur
// ont la leur quand le rack est au repos (§9.2). La fiche : le grand dessin, la démo, le commentaire, les macros.
import { html, useState, useEffect, useAsync, cls, esc, post, del, setTopAction, setSubToolbar, useRev } from './lib.js';
import { useVisuals, Drawing } from './tones-ui.js';
import { keysSvg, macrosOf, useClip, Mark, ClipBar, dur } from './keys-ui.js';

// l'état de la démo, en un signe à côté du nom : ▶ prête, ◌ au prochain repos du rack, rien sinon
const mark = s => s.status === 'ready' ? html`<i class="ky-dm ok" title=${(s.phrase || 'demo') + ' · ' + dur(s)}>▶</i>`
  : s.status === 'pending' ? html`<i class="ky-dm wait" title="its demo renders when the rack is idle">◌</i>` : '';

export function SynthPage() {
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data, reload } = useAsync(() => fetch('/api/keys/sounds').then(r => r.json()), [libRev]);
  const vis = useVisuals();
  const cl = useClip();
  const all = (data && data.synths) || [];
  const [q, setQ] = useState('');
  const [style, setStyle] = useState('all');
  const [busy, setBusy] = useState('');            // message d'état upload/rescan
  const [sel, setSel] = useState(null);            // preset ouvert

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
  useEffect(() => {
    const pick = () => document.getElementById('vital-file-input')?.click();
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${pick}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);

  const styles = [...new Set(all.map(p => p.style).filter(Boolean))].sort();
  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search preset / author…"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <button class="mini edit-only" onClick=${rescan} title="re-index after dropping .vital files manually">⟳</button>
      ${busy ? html`<span class="syn-busy">${busy}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [busy]);

  // l'usine d'abord, puis les tiens (par nom)
  const list = all.filter(p => (style === 'all' || p.style === style)
      && (!q || (p.name + ' ' + (p.author || '') + ' ' + (p.pack || '')).toLowerCase().includes(q)))
    .sort((a, b) => ((a.pack === 'factory') === (b.pack === 'factory') ? a.name.localeCompare(b.name) : a.pack === 'factory' ? -1 : 1));
  const ready = all.filter(p => p.status === 'ready').length;
  const fileInput = html`<input id="vital-file-input" type="file" accept=".vital,.vitalbank,.zip" multiple
    style="display:none" onChange=${e => { uploadFiles(e.target.files); e.target.value = ''; }} />`;

  const open = all.find(p => sel && p.sound === sel);
  if (open) return html`<div class="library tn-page">${fileInput}<${Detail} p=${open} vis=${vis} cl=${cl}
    onClose=${() => setSel(null)} onDeleted=${() => { setSel(null); reload(); }} /></div>`;

  const touch = p => { setSel(p.sound); if (p.status === 'ready' && !cl.playing(p)) cl.play({ ...p, title: p.name }); };
  return html`<div class="library tn-page">${fileInput}
    <div class="tn-col ky-col">
      <div class="ky-styles">${[['all', 'All', all.length], ...styles.map(s => [s, s, all.filter(p => p.style === s).length])].map(([k, lb, n]) =>
        html`<button class=${cls('ky-sty', style === k && 'on')} onClick=${() => setStyle(k)}>${lb} <em>${n}</em></button>`)}
</div>
      ${list.length ? html`<div class="ky-wall">${list.map(p => html`
        <button class=${cls('ky-syn', cl.playing(p) && 'on', p.status === 'none' && 'dim')} onClick=${() => touch(p)}
          aria-label=${p.name}>
          <div class="ky-art">${vis ? html`<${Drawing} svg=${keysSvg({ kind: 'synth', compact: true, title: p.name, style: p.style,
            macros: macrosOf(p), on: p.status !== 'none' })} align="xMidYMid" />` : ''}</div>
          <b>${cl.playing(p) ? html`<${Mark} on=${true} />` : mark(p)}${esc(p.name)}</b>
          <span>${esc(p.author || '—')}${p.style ? ' · ' + esc(p.style) : ''}${p.pack === 'factory' ? ' · factory' : ''}</span>
        </button>`)}</div>`
      : html`<div class="empty">No Vital presets — tap <b>+ Add</b> to import a .vital, .vitalbank or .zip pack
          (from the vital.audio store), or drop files in <code>library/synth/vital/</code> and Rescan.</div>`}
      <${ClipBar} cl=${cl} hint=${`${list.length < all.length ? list.length + ' shown · ' : ''}${all.filter(p => p.pack === 'factory').length} factory · ${all.filter(p => p.pack !== 'factory').length} yours · ${ready} demos ready — touch a preset to hear it.`} />
    </div></div>`;
}

function Detail({ p, vis, cl, onClose, onDeleted }) {
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const isFactory = p.pack === 'factory';
  const doDelete = async () => {
    setBusy(true); setErr('');
    try {
      const r = await del('/api/vital/preset/' + encodeURIComponent(p.id));
      if (!r.ok) throw new Error(r.error || 'failed');
      onDeleted();
    } catch (e) { setErr(String(e.message || e)); setBusy(false); }
  };
  const named = (p.macros || []).filter(m => !/^macro \d$/i.test(m));
  return html`<div class="tn-col ky-col">
    <div class="ky-detail">
      <div class="ky-left wide">
        <button class="tn-back" onClick=${onClose}>‹ Synths</button>
        <div class="ky-art big">${vis ? html`<${Drawing} svg=${keysSvg({ kind: 'synth', title: p.name, style: p.style, macros: macrosOf(p) })} align="xMidYMid" />` : ''}</div>
        <div class="ky-card">
          <h6 class="ky-h6">Demo${p.phrase ? ' · the same phrase for every ' + esc((p.style || 'synth').toLowerCase()) : ''}</h6>
          ${p.status === 'ready' ? html`<button class=${cls('ky-row', cl.playing(p) && 'on')} onClick=${() => cl.play({ ...p, title: p.name })}>
              <${Mark} on=${cl.playing(p)} s=${p} /><span class="nm">${esc(p.phrase || 'Demo')}</span><em>${dur(p)}</em></button>`
            : html`<div class="muted">${p.status === 'pending' ? 'Its demo renders when the rack is idle (10 minutes without anyone playing).' : esc(p.why || 'No demo for this sound.')}</div>`}
        </div>
      </div>
      <div class="ky-right">
        <div class="ky-title"><b>${esc(p.name)}</b><span>${esc(p.author || 'unknown')} · ${esc(p.style || 'no style')} · ${isFactory ? 'factory' : 'pack « ' + esc(p.pack || 'user') + ' »'}</span></div>
        <div class="ky-card">
          <h6 class="ky-h6">About</h6>
          <div class=${p.comments ? '' : 'muted'}>${p.comments ? esc(p.comments) : 'No comment in this preset.'}</div>
        </div>
        <div class="ky-card">
          <h6 class="ky-h6">Macros</h6>
          <div class="ky-macros">${(p.macros || []).map((m, i) => html`<div class=${cls('ky-mac', !named.includes(m) && 'dim')}>
            <span>${esc(m)}</span><i><b style=${'width:' + Math.round(100 * ((p.macro_vals || [])[i] || 0)) + '%'}></b></i></div>`)}</div>
        </div>
        <div class="muted ky-how">Use it in the <b>Designer ▸ Keys</b> lane: the Preset knob picks one Vital sound per scene.</div>
        <div class="del-foot">
          <span class="flash-ko">${err}</span><span class="grow"></span>
          ${isFactory ? html`<span class="muted">factory seed — protected</span>`
            : html`<button class="mini" onClick=${doDelete} disabled=${busy}>${busy ? '…' : 'Delete (to trash)'}</button>`}
        </div>
      </div>
    </div>
    <${ClipBar} cl=${cl} />
  </div>`;
}

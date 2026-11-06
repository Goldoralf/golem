// SPDX-License-Identifier: GPL-3.0-or-later
// Settings ▸ Content ▸ Factory (2026-10-13) — tout ce qui touche à L'USINE au même endroit : ce qu'on en VOIT (un
// interrupteur par sorte ; masquer ne supprime rien), ce qu'on a supprimé et qu'on peut REMETTRE, et les captures
// TONE3000 que les patches d'usine nomment. Le verrou (« Save as mine », docs/factory.md phase 4) viendra ici aussi.
import { html, useState, useEffect, post, cls, esc } from './lib.js';
import { useFactoryShow, setFactoryShow } from './factory-show.js';
import { FactoryCaptures } from './page-api.js';

const KINDS = [
  ['patches', 'Patches', 'Songs ▸ Patches'],
  ['presets', 'Presets', 'Songs ▸ Presets'],
  ['setlists', 'Banks & Setlists', 'Songs ▸ Banks & Setlists'],
  ['kits', 'Pad kits', 'Library ▸ Drums ▸ Kits'],
  ['grooves', 'Grooves', 'Library ▸ Drums ▸ Grooves'],
  ['standards', 'Standards', 'Library ▸ Tracks ▸ Standards'],
];
const KIND_OF = { patches: 'patch', presets: 'preset', setlists: 'bank / setlist', grooves: 'groove', standards: 'standard',
  songs: 'song', dx7: 'DX7 bank' };

// LES DÉMOS D'USINE (docs/preset-preview.md §7, 2026-11-03) : la DI ou la phrase MIDI de référence rendue à travers
// chaque patch d'usine, scène par scène — par lot, reprenable (une démo à jour est sautée), le moteur pris le temps
// du rendu. Le compte vient de /api/patches (`preview`) ; le lot se suit par GET /api/preview/batch.
const PAD_ROLES = ['pads', 'keys-pads'];
function FactoryDemos() {
  const [pt, setPt] = useState(null);
  const [b, setB] = useState(null);
  const [err, setErr] = useState('');
  const load = () => {
    fetch('/api/patches').then(r => r.json()).then(d => setPt((d.patches || []).filter(x => x.factory && !PAD_ROLES.includes(x.role)))).catch(() => {});
    fetch('/api/preview/batch').then(r => r.json()).then(setB).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  const running = !!(b && b.running);
  useEffect(() => { if (!running) return; const t = setInterval(load, 3000); return () => clearInterval(t); }, [running]);
  if (!pt) return '';
  const have = pt.filter(x => x.preview).length;
  const go = async () => { setErr(''); const r = await post('/api/preview/batch', {}).catch(e => (e.body || { error: String(e) }));
    if (r && r.error) setErr(r.error); load(); };
  const stop = async () => { await post('/api/preview/batch/stop', {}).catch(() => {}); load(); };
  const skipped = ((b && b.items) || []).filter(i => i.status === 'skipped' && i.reason !== 'up to date');
  const failed = ((b && b.items) || []).filter(i => i.status === 'failed');
  return html`<div class="fac-cap">
    <div class="fac-cap-hd"><b>Sound demos</b>
      <span class=${cls('muted', have === pt.length && 'ok')}>${have} of ${pt.length} factory patches can be heard ${have === pt.length ? '✓' : ''}</span></div>
    <div class="row">
      ${running
        ? html`<button class="edit-only" onClick=${stop} title="stops after the patch being rendered">■ Stop</button>
            <span class="muted">${b.done} of ${b.total}${b.current ? ' — ' + esc(b.current.replace(/^factory-/, '')) : ''}</span>`
        : html`<button class="primary edit-only" onClick=${go}
            title="renders a reference phrase through every factory patch, scene by scene — takes the engine, nobody should play; demos already up to date are skipped">
            🎧 ${have ? 'Render the missing demos' : 'Render the factory demos'}</button>
            ${b && b.stopped ? html`<span class="muted">${esc(b.stopped)}</span>` : ''}`}
    </div>
    ${!running && (skipped.length || failed.length) ? html`<p class="muted" title=${[...skipped, ...failed].map(i => i.id + ': ' + (i.reason || i.status)).join('\n')}>
      ${skipped.length ? `${skipped.length} skipped — no reference phrase or no input for them yet` : ''}${skipped.length && failed.length ? ' · ' : ''}${failed.length ? `${failed.length} failed` : ''}</p>` : ''}
    ${err ? html`<p class="bad">✗ ${esc(err)}</p>` : ''}
  </div>`;
}

export function FactoryPanel() {
  const show = useFactoryShow();
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState('');
  const load = () => fetch('/api/factory/status').then(r => r.json()).then(setSt).catch(() => {});
  useEffect(() => { load(); }, []);
  const counts = (st && st.counts) || {};
  const removed = (st && st.removed) || [];
  // objets d'usine RETOUCHÉS ici (2026-10-22) : les anciennes versions intactes suivent l'usine toutes seules au
  // démarrage ; une retouche reste, et seul un geste explicite la remplace — en deux temps, car elle est perdue
  const edited = (st && st.edited) || [];
  const [arm, setArm] = useState('');
  const [view, setView] = useState('');
  const reset = async files => {
    const key = files ? files[0] : '*';
    if (arm !== key) { setArm(key); return; }
    setArm(''); setBusy('reset');
    await post('/api/factory/reset', files ? { files } : {}).catch(() => null);
    setBusy(''); load();
  };
  const restore = async files => {
    setBusy('restore');
    await post('/api/factory/restore', files ? { files } : {}).catch(() => null);
    setBusy(''); load();
  };
  return html`<div class="fac-panel">
    <p class="muted fac-intro">What ships with golem — <b>◆ factory</b> patches, presets, banks, kits, grooves and
      standards. Hide what you do not want to see: nothing is deleted, and it comes back with one tap.</p>

    <div class="fac-cols"><div class="fac-col"><div class="fac-sec" data-doc="factory.show">
      <div class="fac-h">Show factory content</div>
      ${KINDS.map(([k, label, where]) => html`<label class=${cls('fac-row', show[k] === false && 'off')} data-doc=${'factory.kind:' + k}>
        <span class="fac-lb"><b>${label} <small class="muted">${counts[k] || (k === 'kits' ? 3 : '')}</small></b><small class="muted">${where}</small></span>
        <button class=${cls('fac-sw ro-inert', show[k] !== false && 'on')} role="switch" aria-checked=${show[k] !== false}
          onClick=${() => setFactoryShow(k, show[k] === false)}>${show[k] === false ? 'Hidden' : 'Shown'}</button>
      </label>`)}
    </div>
    ${edited.length ? html`<div class="fac-sec" data-doc="factory.edited"><div class="fac-h">Changed on this golem</div><div class="fac-edited-line"><span class="muted">${`${edited.length} factory item${edited.length > 1 ? 's were' : ' was'} changed here — factory updates skip ${edited.length > 1 ? 'them' : 'it'}.`}</span>
        <button class="mini" onClick=${() => setView('edited')}>Review</button></div></div>` : ''}
    </div>

    ${view === 'edited' && edited.length ? html`<div class="fac-col"><div class="fac-sec">
      <div class="fac-h fac-h-back"><button class="mini" onClick=${() => { setView(''); setArm(''); }}>‹ Back</button>
        Changed on this golem</div>
      <p class="muted fac-edited-why">Factory updates skip what was changed here — by you, or by the rack while you played.
        Reset to get the factory version back: your changes are lost.</p>
      <div class="fac-removed">${edited.map(r => html`<span class=${cls('fac-chip', arm === r.file && 'arm')}
        title=${`${KIND_OF[r.kind] || r.kind} · ${r.id}`}><small class="muted">${esc(KIND_OF[r.kind] || r.kind)}</small> ${esc(r.name || r.id)}
        <button class="mini" disabled=${!!busy} onClick=${() => reset([r.file])}>${arm === r.file ? 'Sure?' : 'Reset'}</button></span>`)}</div>
      ${edited.length > 1 ? html`<div><button class=${cls('mini', arm === '*' && 'danger')} disabled=${!!busy}
        onClick=${() => reset(null)}>${busy === 'reset' ? '⏳' : arm === '*' ? `Tap again: reset ${edited.length} items` : 'Reset all'}</button></div>` : ''}
    </div></div>` : html`<div class="fac-col"><div class="fac-sec" data-doc="factory.restore">
      <div class="fac-h">Restore factory content</div>
      ${removed.length ? html`
        <p class="muted fac-edited-why">You deleted ${removed.length} factory item${removed.length > 1 ? 's' : ''}. They do not come back by themselves — restore them here.</p>
        <div class="fac-removed">${removed.map(r => html`<span class="fac-chip" title=${r.id}><small class="muted">${esc(KIND_OF[r.kind] || r.kind)}</small> ${esc(r.name || r.id)}
          <button class="mini" disabled=${!!busy} onClick=${() => restore([r.file])}>Restore</button></span>`)}</div>
        ${removed.length > 1 ? html`<div><button class="mini" disabled=${!!busy} onClick=${() => restore(null)}>${busy ? '⏳' : 'Restore all'}</button></div>` : ''}`
        : html`<p class="muted">Nothing deleted — the whole factory content is on this golem.</p>`}
    </div>

    <div class="fac-sec" data-doc="factory.sounds">
      <div class="fac-h">Factory sounds</div>
      <${FactoryCaptures} authed=${true} />
      <${FactoryDemos} />
    </div></div>`}</div>
  </div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// « + Add » dans Library ▸ Drums ▸ Drums — LA FEUILLE D'IMPORT D'UNE BATTERIE (mockups/drums-add.html, validée
// le 2026-10-11 ; contrat docs/drums-kit.md §8). Des gigaoctets ne passent pas par un navigateur : LE RACK lit un
// dossier de ce poste, une clé USB ou une URL (il télécharge). Avant d'installer, la feuille dit ce qu'il a LU dans le
// kit (pièces → notes lues dans le midimap ou les clés du .sfz, micros, taille, place libre) et si le moteur existe
// sur ce rack — sinon le bouton reste gris. Le kit installé est « this golem only » : seule sa carte part à golem.fm.
import { html, useState, useEffect, useRef, useAsync, post, cls, esc } from './lib.js';

const api = (p, opts) => fetch('/api/kits/import/' + p, opts).then(r => r.json()).catch(e => ({ error: String(e) }));
export const gb = n => n == null ? '—' : n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' kB'
  : n < 1073741824 ? (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB' : (n / 1073741824).toFixed(1) + ' GB';
const nfmt = n => (n == null ? '—' : String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' '));

// les pièces lues, en une ligne : « kick 36 · snare 38 · hihat 42/46 · toms 45 47 50 · ride 51 · crash 49 57 »
export const piecesLine = pieces => {
  const p = pieces || {}, out = [];
  const grp = (label, keys) => { const v = keys.map(k => p[k]).filter(n => n != null); if (v.length) out.push(label + ' ' + v.join('/')); };
  grp('kick', ['kick']); grp('snare', ['snare', 'snare-rim', 'snare-xstick']);
  grp('hihat', ['hh-closed', 'hh-open', 'hh-pedal', 'hh-half']);
  const toms = ['tom1', 'tom2', 'tom3', 'tom4'].map(k => p[k]).filter(n => n != null); if (toms.length) out.push('toms ' + toms.join(' '));
  grp('ride', ['ride', 'ride-bell']); const cr = ['crash1', 'crash2'].map(k => p[k]).filter(n => n != null); if (cr.length) out.push('crash ' + cr.join(' '));
  grp('china', ['china']); grp('splash', ['splash']);
  return out.join(' · ');
};

// « Browse… » (2026-10-14) : les dossiers de ce poste, lus par le RACK — un dossier qui ressemble à un kit est
// marqué 🥁 ; « Use this folder » le lit, un .sfz se choisit d'un tap
function KitBrowser({ start, onPick, onClose }) {
  const [at, setAt] = useState(start || '');
  const [d, setD] = useState(null);
  useEffect(() => { setD(null); api('browse?path=' + encodeURIComponent(at || '')).then(setD); }, [at]);
  const join = n => d.path + (d.path.includes('\\') && !d.path.includes('/') ? '\\' : '/') + n;
  return html`<div class="dki-br">
    <div class="dki-br__bar"><code title=${(d && d.path) || ''}>${(d && d.path) || '…'}</code>
      ${d && d.parent ? html`<button onClick=${() => setAt(d.parent)}>↑ Up</button>` : ''}
      <button class="p" disabled=${!d || !d.path} onClick=${() => onPick(d.path)}>${d && d.kit ? '🥁 ' : ''}Use this folder</button>
      <button onClick=${onClose}>Close</button></div>
    <div class="dki-br__list">
      ${!d ? html`<span class="muted">reading…</span>` : d.error ? html`<span class="dki-err">✗ ${esc(d.error)}</span>` : html`
        ${d.dirs.map(x => html`<button class=${cls('dki-br__it', x.kit && 'kit')} onClick=${() => setAt(join(x.name))}
          title=${x.kit ? 'looks like a ' + (x.kit === 'sfz' ? 'SFZ' : 'DrumGizmo') + ' kit' : ''}>${x.kit ? '🥁' : '📁'} ${esc(x.name)}${x.kit ? html` <small>${x.kit === 'sfz' ? 'SFZ' : 'DrumGizmo'}</small>` : ''}</button>`)}
        ${d.sfz.map(n => html`<button class="dki-br__it kit" onClick=${() => onPick(join(n))}>🎼 ${esc(n)}</button>`)}
        ${!d.dirs.length && !d.sfz.length ? html`<span class="muted">no folder here</span>` : ''}`}
    </div>
  </div>`;
}

export function DrumImportSheet({ onClose, onInstalled }) {
  const [src, setSrc] = useState('folder');
  const [path, setPath] = useState('');
  const [url, setUrl] = useState('');
  const [hits, setHits] = useState(null);           // ce qu'un dossier / volume contient
  const [doc, setDoc] = useState(null);             // ce que le rack a LU dans le kit choisi
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [job, setJob] = useState(null);             // {id, kind} — install ou download, suivi en octets
  const [jobSt, setJobSt] = useState(null);
  const [name, setName] = useState('');
  const [browsing, setBrowsing] = useState(false);
  const { data: vols } = useAsync(() => src === 'usb' ? api('volumes') : Promise.resolve(null), [src]);
  const pathRef = useRef(null);
  useEffect(() => { if (src === 'folder' && pathRef.current) pathRef.current.focus(); }, [src]);

  // un job se suit toutes les 400 ms ; fini → on lit (download) ou on referme (install)
  useEffect(() => {
    if (!job) return;
    let alive = true;
    const tick = async () => {
      const j = await api('job/' + job.id);
      if (!alive) return;
      setJobSt(j);
      if (j.state === 'running') { setTimeout(tick, 400); return; }
      setJob(null);
      if (j.state === 'error') { setErr(j.error || 'failed'); setBusy(''); return; }
      if (job.kind === 'download') { setBusy(''); readPath(j.result && j.result.path); }
      else { setBusy(''); onInstalled && onInstalled(j.result && j.result.kit); onClose(); }
    };
    tick();
    return () => { alive = false; };
  }, [job]);

  const readPath = async p => {
    if (!p) return;
    setErr(''); setDoc(null); setBusy('reading…');
    const r = await api('read?path=' + encodeURIComponent(p));
    setBusy('');
    if (r.error) { setErr(r.error); return; }
    setDoc(r); setName(r.name || '');
  };
  const scanPath = async p => {
    if (!p) return;
    setErr(''); setDoc(null); setHits(null); setBusy('looking…');
    const r = await api('scan?path=' + encodeURIComponent(p));
    setBusy('');
    if (r.error) { setErr(r.error); return; }
    setHits(r.hits || []);
    if ((r.hits || []).length === 1) readPath(r.hits[0].path);
    else if (!(r.hits || []).length) { const rr = await api('read?path=' + encodeURIComponent(p)); if (!rr.error) { setDoc(rr); setName(rr.name || ''); } else setErr('nothing that looks like a drum kit here (a DrumGizmo folder holds a drumkit.xml and a midimap.xml; an SFZ kit is a .sfz file)'); }
  };
  const download = async () => {
    if (!url.trim()) return;
    setErr(''); setDoc(null); setHits(null); setBusy('downloading…');
    const r = await post('/api/kits/import/url', { url: url.trim() });
    if (!r || r.error) { setBusy(''); setErr((r && r.error) || 'download failed'); return; }
    setJob({ id: r.job, kind: 'download' });
  };
  const install = async () => {
    if (!doc || doc.available === false) return;
    setErr(''); setBusy('installing…');
    const r = await post('/api/kits/import/install', { path: doc.path, name: name.trim() || doc.name });
    if (!r || r.error) { setBusy(''); setErr((r && r.error) || 'install failed'); return; }
    setJob({ id: r.job, kind: 'install' });
  };
  const pct = jobSt && jobSt.total_bytes ? Math.min(100, Math.round(100 * jobSt.done_bytes / jobSt.total_bytes)) : null;
  const eng = doc && doc.engine;
  const engLabel = eng === 'drumgizmo' ? 'DrumGizmo' : eng === 'sfz' ? 'SFZ (sfizz)' : eng;
  const unknown = doc && doc.unknown && doc.unknown.length ? doc.unknown : null;

  return html`<div class="sheet-scrim scn-scrim dki-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && !job && onClose()}>
    <div class="dki-sheet" role="dialog" aria-label="Add a drum kit">
      <h2>Add a drum kit — this golem only</h2>
      <p class="dki-s">A DrumGizmo kit (drumkit.xml + midimap.xml + samples) or an SFZ kit. Big files stay on this rack; golem.fm only gets the card.</p>
      <div class="dki-src">
        <button class=${cls(src === 'folder' && 'on')} onClick=${() => { setSrc('folder'); setHits(null); }}>📁 A folder on this computer</button>
        <button class=${cls(src === 'usb' && 'on')} onClick=${() => { setSrc('usb'); setHits(null); }}>🔌 A USB key</button>
        <button class=${cls(src === 'url' && 'on')} onClick=${() => { setSrc('url'); setHits(null); }}>🔗 A URL (the rack downloads)</button>
      </div>
      ${src === 'folder' ? html`<div class="dki-row">
          <input ref=${pathRef} value=${path} placeholder=${'the kit’s folder, or its .sfz file — e.g. ' + (navigator.platform.startsWith('Win') ? 'D:\\Drums\\Salamander' : '/home/golem/Drums/Salamander')}
            onInput=${e => setPath(e.target.value)} onKeyDown=${e => e.key === 'Enter' && scanPath(path.trim())} />
          <button class="dki-go" disabled=${!!busy} onClick=${() => setBrowsing(!browsing)}>Browse…</button>
          <button class="dki-go" disabled=${!path.trim() || !!busy} onClick=${() => scanPath(path.trim())}>Read</button>
        </div>
        ${browsing ? html`<${KitBrowser} start=${path.trim() ? path.trim().replace(/[\\/][^\\/]*\.sfz$/i, '') : ''}
          onPick=${p => { setPath(p); setBrowsing(false); /\.sfz$/i.test(p) ? readPath(p) : scanPath(p); }} onClose=${() => setBrowsing(false)} />` : ''}` : ''}
      ${src === 'usb' ? html`<div class="dki-vols">
          ${!vols ? html`<span class="muted">looking for volumes…</span>`
            : !(vols.volumes || []).length ? html`<span class="muted">no volume found — plug the key, then tap 🔌 again</span>`
            : (vols.volumes || []).map(v => html`<button class=${cls('dki-vol', v.removable && 'usb')} onClick=${() => { setPath(v.path); scanPath(v.path); }} title=${v.path}>${v.removable ? '🔌' : '💽'} ${esc(v.label)}</button>`)}
        </div>` : ''}
      ${src === 'url' ? html`<div class="dki-row">
          <input value=${url} placeholder="https://… a .zip / .tar.gz of the kit, or a .sfz" onInput=${e => setUrl(e.target.value)} onKeyDown=${e => e.key === 'Enter' && download()} />
          <button class="dki-go" disabled=${!url.trim() || !!busy} onClick=${download}>Download</button>
        </div>` : ''}
      ${hits && hits.length > 1 ? html`<div class="dki-hits"><span class="muted">${hits.length} kits found — pick one:</span>
          ${hits.map(h => html`<button class=${cls('dki-hit', doc && doc.path === h.path && 'on')} onClick=${() => readPath(h.path)} title=${h.path}>${h.engine === 'sfz' ? '🎼' : '🥁'} ${esc(h.name)} <small>${h.engine}</small></button>`)}
        </div>` : ''}
      ${busy && !job ? html`<div class="dki-busy">${esc(busy)}</div>` : ''}
      ${job ? html`<div class="dki-prog"><div class="dki-bar"><i style=${'width:' + (pct == null ? 100 : pct) + '%'} class=${cls(pct == null && 'indet')}></i></div>
          <span>${job.kind === 'download' ? 'Downloading' : 'Installing'}${jobSt && jobSt.total_bytes ? ' — ' + gb(jobSt.done_bytes) + ' of ' + gb(jobSt.total_bytes) : '…'}</span></div>` : ''}
      ${err ? html`<div class="dki-err">✗ ${esc(err)}</div>` : ''}
      ${doc ? html`<div class="dki-read">
          <div class="dki-t"><input class="dki-name" value=${name} onInput=${e => setName(e.target.value)} title="the kit’s name on this golem" />
            <span>${esc(doc.folder || doc.path)} · read in ${doc.read_ms < 1000 ? doc.read_ms + ' ms' : (doc.read_ms / 1000).toFixed(1) + ' s'}</span></div>
          <div class="dki-kv">
            <span>Engine</span><div>${engLabel} ${doc.available === true ? html`<b class="ok">· available on this rack ✓</b>` : doc.available === false ? html`<b class="bad">· ${esc(doc.why || 'not available on this rack')}</b>` : html`<b class="wn">· not checked yet (${esc(doc.why || 'REAPER inventory')})</b>`}
              ${doc.os_note ? html` <span class=${cls(eng === 'drumgizmo' ? 'wn' : 'muted')}>(${esc(doc.os_note)})</span>` : ''}</div>
            <span>Pieces → notes</span><div>${Object.keys(doc.pieces || {}).length ? html`${esc(piecesLine(doc.pieces))} — <b class="ok">read in ${esc(doc.pieces_src)} ✓</b>` : html`<b class="bad">none read in ${esc(doc.pieces_src)}</b>`}
              ${unknown ? html` <span class="wn">· not recognised: ${esc(unknown.slice(0, 6).join(', '))}${unknown.length > 6 ? '…' : ''}</span>` : ''}</div>
            <span>${eng === 'sfz' ? 'Regions' : 'Mics'}</span><div>${eng === 'sfz' ? nfmt(doc.regions) + ' regions · stereo out' : nfmt(doc.mics) + ' outputs (one channel each) — mixed in the Drums block'}</div>
            <span>Size</span><div>${gb(doc.bytes)} · ${nfmt(doc.files)} files${doc.sample_rate ? ' · ' + (doc.sample_rate / 1000) + ' kHz' + (doc.bits ? ' ' + doc.bits + '-bit' : '') : ''} <span class="muted">— copied to ${esc(doc.dest)}/</span></div>
            <span>Free space</span><div class=${cls(doc.free_bytes != null && doc.free_bytes - doc.bytes < 536870912 ? 'bad' : 'ok')}>${gb(doc.free_bytes)} on the rack ${doc.free_bytes != null && doc.free_bytes - doc.bytes < 536870912 ? '— not enough' : '✓'}</div>
          </div>
          ${doc.sfz_choices && doc.sfz_choices.length > 1 ? html`<div class="dki-hits dki-sfzs"><span class="muted">${doc.sfz_choices.length} .sfz in this folder — the kit is:</span>
              ${doc.sfz_choices.map(f => html`<button class=${cls('dki-hit', doc.sfz_file === f && 'on')} onClick=${() => readPath(doc.folder + (doc.folder.includes('\\') ? '\\' : '/') + f)}>🎼 ${esc(f)}</button>`)}</div>` : ''}
          ${doc.exists ? html`<div class="dki-err">« ${esc(doc.name)} » is already installed — delete it in the list first, or give this one another name.</div>` : ''}
        </div>` : ''}
      <div class="dki-acts">
        <button onClick=${onClose} disabled=${!!job}>Cancel</button>
        <button class="p" disabled=${!doc || doc.available === false || !!job || !!busy} onClick=${install}>${doc ? `Install « ${name.trim() || doc.name} »` + (doc.bytes ? ` (${gb(doc.bytes)})` : '') : 'Install'}</button>
      </div>
      <p class="dki-note"><b>Not synced:</b> only a card (name, engine, pieces, size) goes to golem.fm, so your other racks and the band see it exists. The samples never leave this golem. An SFZ kit reads its pieces from the .sfz keys the same way.</p>
    </div>
  </div>`;
}

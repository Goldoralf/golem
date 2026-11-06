// SPDX-License-Identifier: GPL-3.0-or-later
// System ▸ System ▸ STORAGE (2026-10-09 — maquette mockups/storage.html ; ex-« Song Folders », docs/song-folders.md).
// La place que prend la MUSIQUE sur le golem — catégorie par catégorie, les mêmes que les sauvegardes (docs/backups.md),
// avec l'âge de leur dernière sauvegarde — à côté des DOSSIERS DE CHANSONS, lus sur place (sur ce disque, un disque
// externe ou le réseau : c'est LU dans le système, song_folders.location), et des CACHES qu'on vide d'un geste.
// « + Add folders » est dans la topbar (la charte) ; l'explorateur, servi par le rack, coche PLUSIEURS dossiers.
import { html, useState, useEffect, useAsync, post, del, api, cls, esc, go, setTopAction } from './lib.js';
import { IoModal } from './io-modal.js';

const mb = n => !n ? '0 MB' : n < 1048576 ? Math.round(n / 1024) + ' kB' : n < 1073741824 ? (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB'
  : (n / 1073741824).toFixed(n < 10737418240 ? 1 : 0) + ' GB';
const n_ = x => Number(x || 0).toLocaleString('en-US').replace(/,/g, ' ');
const days = t => t ? Math.max(0, Math.floor((Date.now() / 1000 - t) / 86400)) : null;
const ago = iso => { if (!iso) return ''; const s = (Date.now() - new Date(iso).getTime()) / 1000;
  return !(s >= 0) ? '' : s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + ' min ago' : s < 129600 ? Math.round(s / 3600) + ' h ago' : Math.round(s / 86400) + ' days ago'; };
const TAG = { external: ['external', 'ext'], network: ['network', 'ext'], 'this-disk': ['this disk', ''], 'other-disk': ['other disk', ''] };
const FOLDERS_PAGE = 3;
// les lignes « ta musique » de la maquette : les petites catégories partagent une ligne
const MUSIC_ROWS = [
  [['amps'], 'Amps', c => (c.amps || {}).tones + ' amps'],
  [['recordings'], 'Recordings', c => ((c.recordings || {}).audio || 0) + ' takes'],
  [['synths'], 'Synth presets', c => ((c.synths || {}).n || 0) + ' Vital'],
  [['songs'], 'Songs', c => ((c.songs || {}).n || 0) + ' .golem'],
  // Vocals vit dans le même dossier que les chansons (sa sauvegarde est celle des chansons : son âge vient de « songs »)
  [['vocals'], 'Vocals', c => ((c.vocals || {}).n || 0) + ' lines', ['songs']],
  [['standards'], 'Standards', c => ((c.standards || {}).n || 0) + ' charts'],
  [['pedals'], 'Pedals · Outboard', c => ((c.pedals || {}).tones || 0) + ' + ' + ((c.pedals || {}).outboard || 0)],
  [['cabs'], 'Cabs / IRs', c => ((c.cabs || {}).tones || 0) + ' cabs'],

  [['presets', 'patches', 'banks'], 'Presets · Patches · Setlists', c => [(c.presets || {}).n, (c.patches || {}).n, (c.banks || {}).n].join(' · ')],
  [['kits', 'grooves', 'settings'], 'Kits & samples · Grooves · Settings', () => ''],
];

export function StoragePage() {
  const [tick, setTick] = useState(0);
  const refresh = () => setTick(x => x + 1);
  const { data: st } = useAsync(() => fetch('/api/storage').then(r => r.json()).catch(() => null), [tick]);
  const { data: fo } = useAsync(() => fetch('/api/song-folders').then(r => r.json()).catch(() => null), [tick]);
  const [adding, setAdding] = useState(false);
  const [io, setIo] = useState(false);
  const busy = !!(fo && fo.scanning);
  // un passage en cours : on suit sa progression ; sinon un coup d'œil lent (un disque branché se voit)
  useEffect(() => { const t = setInterval(refresh, busy ? 2000 : 15000); return () => clearInterval(t); }, [busy]);
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" title="add song folders" onClick=${() => setAdding(true)}>+ Add folders</button></div>`);
    return () => setTopAction(null);
  }, []);
  return html`<div class="sto">
    <${Disk} st=${st} />
    <div class="sto-cols">
      <${Music} st=${st} onBackup=${() => setIo(true)} />
      <div class="sto-card" data-doc="storage.folders">
        <${Folders} fo=${fo} onChanged=${refresh} />
        <${Caches} st=${st} onChanged=${refresh} />
      </div>
    </div>
    ${adding ? html`<${AddFolders} existing=${((fo || {}).folders || []).map(f => f.path)}
      onClose=${() => setAdding(false)} onAdded=${() => { setAdding(false); refresh(); }} />` : ''}
    ${io ? html`<${IoModal} onClose=${() => { setIo(false); refresh(); }} />` : ''}
  </div>`;
}

// ── le disque ──
function Disk({ st }) {
  if (!st) return html`<div class="sto-disk"><span class="muted">measuring…</span></div>`;
  const d = st.disk, pct = x => (100 * x / d.total).toFixed(2) + '%';
  const segs = [['music', st.music_total, 'Your music'], ['inst', st.installed_total, 'Installed sounds'],
    ['cache', st.caches_total, 'Caches'], ['other', st.other, 'System & other apps']];
  return html`<div class="sto-disk" data-doc="storage.disk">
    <div class="sto-dh"><b>This golem’s disk</b><span class="muted">${mb(d.total)} · <b>${mb(d.free)} free</b></span>
      <span class="grow"></span><span class="muted">your music takes ${mb(st.music_total)}</span></div>
    <div class="sto-bar">${segs.map(([k, v]) => html`<i class=${'sto-c-' + k} style=${'width:' + pct(v)}></i>`)}</div>
    <div class="sto-leg">${segs.map(([k, v, l]) => html`<span><i class=${'sto-c-' + k}></i>${l} <b>${mb(v)}</b></span>`)}
      <span><i class="sto-c-free"></i>Free <b>${mb(d.free)}</b></span></div>
  </div>`;
}

// ── ta musique ──
function Music({ st, onBackup }) {
  const rows = st ? MUSIC_ROWS.map(([ks, l, sub, ageKs]) => {
    const bytes = ks.reduce((t, k) => t + (st.music[k] || 0), 0);
    const ts = (ageKs || ks).map(k => ((st.last || {})[k] || {}).t || 0);
    const t = ts.some(x => !x) ? null : Math.min(...ts);        // l'âge de la PLUS ancienne : jamais = jamais
    return { l, sub: sub(st.counts || {}), bytes, age: days(t) };
  }) : [];
  const max = Math.max(1, ...rows.map(r => r.bytes));
  const lf = st && st.last_full ? days(st.last_full.t) : null;
  return html`<div class="sto-card" data-doc="storage.music">
    <div class="sto-ch"><b>Your music on this golem</b><span class="grow"></span>
      <button class="mini edit-only" data-doc="storage.backup" onClick=${onBackup} title="open the backups">⇅ Back up…</button></div>
    ${!st ? html`<p class="muted">measuring…</p>` : rows.map(r => html`<div class="sto-row">
      <span class="sto-n">${r.l}${r.sub ? html`<small>${r.sub}</small>` : ''}</span>
      <span class="sto-mbar"><i style=${'width:' + Math.max(r.bytes ? 1 : 0, Math.round(100 * r.bytes / max)) + '%'}></i></span>
      <span class="sto-sz">${mb(r.bytes)}</span>
      <span class="sto-age"><i class=${'sto-dot ' + (r.age == null || r.age > 30 ? 'r' : r.age > 7 ? 'a' : '')}></i>${r.age == null ? 'never' : r.age + ' d'}</span>
    </div>`)}
    ${st ? html`<div class="sto-tot"><b>${mb(st.music_total)}</b><span class="muted">across ${MUSIC_ROWS.reduce((t, r) => t + r[0].length, 0)} categories · last full backup ${lf == null ? 'never' : lf + ' days ago'}</span></div>` : ''}
  </div>`;
}

// ── les dossiers de chansons ──
// ce qu'un dossier apporte (bridge/song_folders.KINDS) : le golem range toujours d'après le CONTENU ; un type filtre
const KINDS = ['auto', 'song', 'vocals', 'standard'];
const KIND_LABEL = { auto: 'Auto', song: 'Songs', vocals: 'Vocals', standard: 'Standards' };
function Folders({ fo, onChanged }) {
  const [page, setPage] = useState(0);
  const [menu, setMenu] = useState(null);           // le ⋯ ouvert : un chemin
  const [arm, setArm] = useState(false);
  const [dirEdit, setDirEdit] = useState(null);
  const [open, setOpen] = useState(null);           // les fichiers illisibles d'un dossier
  useEffect(() => setArm(false), [menu]);
  const rows = (fo && fo.folders) || [];
  const pages = Math.max(1, Math.ceil(rows.length / FOLDERS_PAGE));
  const shown = rows.slice(page * FOLDERS_PAGE, page * FOLDERS_PAGE + FOLDERS_PAGE);
  const rescan = async p => { await post('/api/song-folders/rescan', { path: p }).catch(() => null); setMenu(null); setTimeout(onChanged, 400); };
  const show = async (p, on) => { await api('/api/song-folders', { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: p, show_on_golemfm: on }) }).catch(() => null); onChanged(); };
  // CE QUE LE DOSSIER APPORTE (song-folders.md §2.9) : Auto = tout, rangé d'après le contenu ; typé = un filtre compté
  const setKind = async (p, kind) => { await api('/api/song-folders', { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: p, kind }) }).catch(() => null); setMenu(null); onChanged(); };
  const remove = async p => { if (!arm) { setArm(true); return; } await del('/api/song-folders?path=' + encodeURIComponent(p)).catch(() => null); setMenu(null); onChanged(); };
  const saveDir = async () => { const r = await fetch('/api/inbox', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir: dirEdit }) });
    if (r.ok) { setDirEdit(null); onChanged(); } };
  return html`
    <div class="sto-ch"><b>Song folders</b><span class="muted">songs, Vocals and standards — read where they are, golem never writes there</span>
      ${pages > 1 ? html`<span class="grow"></span><button class="mini" disabled=${page === 0} onClick=${() => setPage(page - 1)}>‹</button>
        <small class="muted">${page + 1}/${pages}</small><button class="mini" disabled=${page >= pages - 1} onClick=${() => setPage(page + 1)}>›</button>` : ''}</div>
    <div class="sto-fold drop"><span>⤓</span>
      ${dirEdit != null ? html`<span class="sto-fe"><input class="gf-dir" value=${dirEdit} onInput=${e => setDirEdit(e.target.value)} />
          <button class="mini primary" onClick=${saveDir}>Save</button><button class="mini" onClick=${() => setDirEdit(null)}>Cancel</button></span>`
        : html`<span class="sto-fm"><span class="sto-p">${esc((fo || {}).drop_folder || '…')}</span><small>Drop folder — a .golem dropped there is copied into this golem</small></span>
          <button class="mini edit-only" onClick=${() => setDirEdit((fo || {}).drop_folder || '')}>Change…</button>`}</div>
    ${fo && !rows.length ? html`<div class="sto-empty">No song folders yet<span class="edit-only"> — <b>+ Add folders</b> to read .golem files from this disk, an external drive or a network share</span>.</div>` : ''}
    ${shown.map(f => { const s = f.state || 'waiting'; const tag = TAG[f.location] || null;
      const c = f.counts || {}; const parts = [c.song && n_(c.song) + ' songs', c.vocals && n_(c.vocals) + ' Vocals', c.standard && n_(c.standard) + ' standards'].filter(Boolean);
      return html`<div class=${cls('sto-fold', 'sto-' + s)}>
        <i class=${cls('sto-st', s === 'online' && 'on')}>${s === 'online' ? '●' : s === 'offline' ? '○' : '◐'}</i>
        <span class="sto-fm"><span class="sto-p" title=${f.path}><span>${esc(f.label || f.path)}</span>${tag ? html`<span class=${cls('sto-tag', tag[1])}>${tag[0]}</span>` : ''}
            <span class=${cls('sto-kind', (f.kind || 'auto') !== 'auto' && 'on')}
              title=${(f.kind || 'auto') === 'auto' ? 'everything in it, sorted by what each file is' : 'only ' + KIND_LABEL[f.kind] + ' are taken from this folder'}>${KIND_LABEL[f.kind || 'auto']}</span></span>
          <small>${s === 'indexing' ? ((f.progress || {}).found ? `indexing… ${n_(f.progress.done)} / ${n_(f.progress.found)} .golem` : 'indexing… looking for .golem files')
            : s === 'offline' ? `offline · ${n_(f.songs)} songs known${f.last_seen ? ' · last seen ' + ago(f.last_seen) : ''}`
            : s === 'waiting' ? 'waiting for its first pass…'
            : [parts.join(' · ') || 'no songs', mb(f.bytes), ago(f.scanned_at)].filter(Boolean).join(' · ')}
            ${s === 'partial' ? ' · read in part — nothing removed' : ''}
            ${f.ignored ? html` · <span class="sto-ign" title="readable, but not what this folder brings">${n_(f.ignored)} not ${KIND_LABEL[f.kind]} — ignored</span>` : ''}
            ${f.bad ? html` · <a onClick=${() => setOpen(open === f.path ? null : f.path)}>${f.bad} unreadable</a>` : ''}</small>
          ${f.suggest ? html`<small class="sto-sug">Only ${KIND_LABEL[f.suggest]} in this folder —${' '}<a class="edit-only" onClick=${() => setKind(f.path, f.suggest)}>mark it ${KIND_LABEL[f.suggest]}</a></small>` : ''}
          ${open === f.path ? html`<small class="sto-bad">${(f.bad_files || []).slice(0, 3).map(b => b.file + ' — ' + b.why).join(' · ')}</small>` : ''}</span>
        <span class="sto-mw"><button class="mini" onClick=${() => setMenu(menu === f.path ? null : f.path)}>⋯</button>
          ${menu === f.path ? html`<div class=${cls('sto-menu', shown.indexOf(f) >= shown.length - 2 && shown.length > 1 && 'up')}>
            <div class="sto-kinds"><small>This folder brings</small>
              ${KINDS.map(k => html`<button class=${cls('sto-kb', (f.kind || 'auto') === k && 'on')}
                onClick=${() => setKind(f.path, k)}>${KIND_LABEL[k]}</button>`)}</div>
            <button disabled=${s === 'indexing'} onClick=${() => rescan(f.path)}>Rescan</button>
            <label><input type="checkbox" checked=${f.show_on_golemfm !== false} onChange=${e => show(f.path, e.target.checked)} /> Show on golem.fm</label>
            <button class=${cls('danger', arm && 'armed')} onClick=${() => remove(f.path)}
              title="golem stops reading this folder — no file is touched">${arm ? 'Stop reading — sure?' : 'Stop reading this folder'}</button>
          </div>` : ''}</span>
      </div>`; })}`;
}

// ── les caches ──
function Caches({ st, onChanged }) {
  const [arm, setArm] = useState(null);
  const [said, setSaid] = useState('');
  useEffect(() => { if (!arm) return; const t = setTimeout(() => setArm(null), 3000); return () => clearTimeout(t); }, [arm]);
  if (!st) return '';
  const DESC = { peaks: x => x.n + ' left by takes that are gone', work: () => 'unpacked .golem, rebuilt when needed', backing: x => x.n ? x.n + ' no longer needed — your library has these songs' : 'downloaded stems, all in use' };
  const clear = async id => {
    if (arm !== id) { setArm(id); return; }
    setArm(null);
    const r = await post('/api/storage/clear', { cache: id }).catch(e => (e.body || { why: String(e) }));
    setSaid(r && r.ok ? mb(r.freed) + ' freed' : (r && r.why) || 'could not clear');
    setTimeout(() => setSaid(''), 5000);
    onChanged();
  };
  return html`<div class="sto-gh">Caches — rebuilt on their own ${said ? html`<span class="sto-said">${esc(said)}</span>` : ''}</div>
    ${st.caches.map(c => html`<div class="sto-cache">
      <span>${c.label}<small>${DESC[c.id] ? DESC[c.id](c) : ''}</small></span>
      <span class="sto-sz">${mb(c.bytes)}</span>
      ${c.clear ? html`<button class=${cls('mini', c.id === 'peaks' && c.bytes > 100e6 && 'warn', arm === c.id && 'armed')} disabled=${c.id === 'backing' ? !c.n : !c.bytes}
          onClick=${() => clear(c.id)}>${arm === c.id ? 'sure?' : 'Clear'}</button>`
        : html`<button class="mini" onClick=${() => go('library/tracks/backing')}>Open ›</button>`}
    </div>`)}`;
}

// ── « + Add folders » : l'explorateur du rack, PLUSIEURS dossiers d'un coup ──
const inside = (a, b) => a === b || a.startsWith(b.replace(/[\\/]+$/, '') + '/') || a.startsWith(b.replace(/[\\/]+$/, '') + '\\');
function AddFolders({ existing, onClose, onAdded }) {
  const [path, setPath] = useState('');
  const [typed, setTyped] = useState(null);
  const [sel, setSel] = useState([]);
  const [show, setShow] = useState(true);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [pg, setPg] = useState(0);
  useEffect(() => setPg(0), [path]);
  const { data: rt } = useAsync(() => fetch('/api/song-folders/browse').then(r => r.json()).catch(() => null), []);
  const { data } = useAsync(() => !path ? Promise.resolve(null) : fetch('/api/song-folders/browse?path=' + encodeURIComponent(path))
    .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.why || 'not readable'); return d; })
    .catch(e => ({ error: e.message })), [path]);
  const d = data || {};
  const roots = (rt && rt.roots) || [];
  const curRoot = roots.filter(r => path && inside(path, r.path)).sort((a, b) => b.path.length - a.path.length)[0];
  // pourquoi on ne peut pas cocher ce dossier : refusé par le rack, ou il chevauche un dossier déjà choisi / listé
  const blocked = x => {
    if (x.can_add && !x.can_add.ok) return x.can_add.why;
    const hit = [...sel, ...existing].find(s => s !== x.path && (inside(x.path, s) || inside(s, x.path)));
    return hit ? 'overlaps ' + hit.split(/[\\/]/).pop() : null;
  };
  const toggle = x => setSel(s => s.includes(x.path) ? s.filter(p => p !== x.path) : [...s, x.path]);
  const dirs = (d.dirs || []).slice(pg * 18, pg * 18 + 18);
  const add = async () => {
    setBusy(true); setErr('');
    const r = await post('/api/song-folders', { paths: sel, show_on_golemfm: show }).catch(e => (e.body || { why: String(e) }));
    setBusy(false);
    if (r && r.ok) { (r.refused || []).length ? setErr('not added: ' + r.refused.map(x => x.path.split(/[\\/]/).pop() + ' (' + x.why + ')').join(', ')) : onAdded(); if (!(r.refused || []).length) return; }
    else setErr((r && r.why) || 'refused');
  };
  const KIND = { external: '💾', network: '🌐', 'this-disk': '🏠', 'other-disk': '🖴' };
  return html`<div class="sheet-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && onClose()}>
    <div class="gf-sheet sto-add">
      <div class="gf-hd"><b>Add song folders</b><span class="muted">pick one or several — golem reads them where they are</span>
        <span class="grow"></span><button class="mini" onClick=${onClose}>✕</button></div>
      <div class="sto-roots">${!rt ? html`<span class="muted">looking for drives…</span>` : roots.map(r => html`
        <button class=${cls('sto-root', curRoot && curRoot.path === r.path && 'on')} onClick=${() => setPath(r.path)} title=${r.path}>
          ${KIND[r.kind] || '📁'} ${esc(r.label)}${r.kind === 'external' || r.kind === 'network' ? html` <small>${r.kind}${r.total ? ' · ' + mb(r.total) : ''}</small>` : ''}</button>`)}</div>
      <div class="sf-crumb">
        <button class="mini" disabled=${!path || !d.parent} onClick=${() => setPath(d.parent || '')} title="up">↑</button>
        ${typed != null ? html`<input class="gf-dir" value=${typed} onInput=${e => setTyped(e.target.value)}
            onKeyDown=${e => { if (e.key === 'Enter') { setPath(typed); setTyped(null); } }} />
            <button class="mini primary" onClick=${() => { setPath(typed); setTyped(null); }}>Go</button>`
          : html`<code onClick=${() => setTyped(path)} title="type a path">${esc(path || 'Pick a drive above')}</code>`}
        ${path && d.can_add && d.can_add.ok && !sel.includes(path) && !blocked({ path, can_add: d.can_add }) ? html`<button class="mini" onClick=${() => setSel(s => [...s, path])}
            title="add this folder itself">＋ This folder${d.golem_here ? ' (' + n_(d.golem_here) + ' .golem)' : ''}</button>` : ''}
      </div>
      <div class="sto-dirs">
        ${!path ? '' : d.error ? html`<p class="warn">${esc(d.error)}</p>` : !data ? html`<p class="muted">reading…</p>`
          : !(d.dirs || []).length ? html`<p class="muted">no folders inside</p>`
          : dirs.map(x => { const why = blocked(x); const on = sel.includes(x.path);
            return html`<div class=${cls('sto-dir', on && 'sel', why && !on && 'no')}>
              <button class="sto-ck" disabled=${!!why && !on} onClick=${() => toggle(x)} title=${why || 'pick this folder'}></button>
              <button class="sto-dn" onClick=${() => setPath(x.path)} title="open">📁 ${esc(x.name)}
                <small>${why && !on ? ' · ' + why : x.golem == null || (!x.golem && !x.complete) ? '' : ' · ' + (x.golem ? n_(x.golem) + (x.complete ? '' : '+') + ' .golem' : 'no .golem')}</small></button>
            </div>`; })}
      </div>
      ${(d.dirs || []).length > 18 ? html`<div class="sf-ft"><button class="mini" disabled=${pg === 0} onClick=${() => setPg(pg - 1)}>‹</button>
        <small>${pg + 1} / ${Math.ceil(d.dirs.length / 18)}</small><button class="mini" disabled=${(pg + 1) * 18 >= d.dirs.length} onClick=${() => setPg(pg + 1)}>›</button></div>` : ''}
      <div class="gf-ft">
        <div class="sto-chips">${sel.map(p => html`<span class="sto-chip" title=${p}>${esc(p.split(/[\\/]/).slice(-2).join('/'))} <a onClick=${() => setSel(s => s.filter(x => x !== p))}>✕</a></span>`)}</div>
        ${err ? html`<span class="warn">${esc(err)}</span>` : html`<span class="muted">${sel.length ? sel.length + ' folder' + (sel.length > 1 ? 's' : '') : 'nothing picked yet'}</span>`}
        <span class="grow"></span>
        <label class="sto-show"><input type="checkbox" checked=${show} onChange=${e => setShow(e.target.checked)} /> Show on golem.fm</label>
        <button class="primary" disabled=${!sel.length || busy} onClick=${add}>${busy ? 'adding…' : sel.length > 1 ? `Add ${sel.length} folders` : 'Add folder'}</button>
      </div>
    </div></div>`;
}

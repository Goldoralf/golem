// SPDX-License-Identifier: GPL-3.0-or-later
// ── LE .golem À L'ÉCRAN (plan-song-sharing lot 5, maquette mockups/golem-files.html, 2026-10-08) ──────
// Deux panneaux :
//   FileSheet — « What this song carries » : chaque élément du .golem, LU dans l'archive (GET /api/songs/{id}/files),
//     présent ✓ / attendu absent ✕ / sans objet — ; d'où vient le fichier ; « Replace with a file… » (un .golem du
//     MÊME enregistrement remplace les médias, la fiche reste la tienne).
//   DropSheet — déposer un .golem, et SEULEMENT un .golem (2026-10-08 : « on ne dépose pas un mp3 sur le golem
//     pour qu'il parte en traitement — c'est sur golem.fm ») : un lien y mène. Les derniers événements (dépôts et
//     dossier surveillé, GET /api/inbox) et le réglage du dossier surveillé.
// Le fichier part en CORPS BRUT (POST /api/golem/drop?name=…) : le navigateur envoie le File en flux, le bridge
// l'écrit sur disque sans le tenir en mémoire.
import { DECLARATION } from './separation-batch.js';
import { html, useState, useEffect, useRef, useAsync, cls, esc, go } from './lib.js';

// golem.fm ne fait le .golem d'un fichier qu'à un golem APPAIRÉ : sinon, le chemin local seul (audit 31/10 — le lien
// menait à une page en construction). Le chemin local passe toujours en premier : Separate a folder, sur ce golem.
const useFmPaired = () => (useAsync(() => fetch('/api/golemfm/status').then(r => r.json()).catch(() => null), []).data || {}).paired === true;
const SEPARATE = 'system/engines/separation';

export const GOLEMFM_CREATE = 'https://golem.fm/songs?add=1';

// la ligne « File » d'une chanson (liste Songs, case de la page) : complete · partial · card
export function fileLine(f) {
  if (!f) return { cls: 'none', ic: '—', txt: 'no file', sub: '' };
  if (f.state === 'complete') return { cls: 'ok', ic: '▣', txt: 'complete', sub: `${f.present}/${f.expected} · ${mb(f.bytes)}` };
  if (f.state === 'partial') return { cls: 'part', ic: '▣', txt: 'partial', sub: 'no ' + (f.missing || []).map(x => x.toLowerCase()).join(', no ') };
  // « cardonly », jamais « card » : la classe générique .card de la page dessinait une boîte autour (2026-10-17)
  if (f.state === 'card') return { cls: 'cardonly', ic: '◌', txt: 'card only', sub: 'no recording yet' };
  return { cls: 'bad', ic: '✕', txt: 'unreadable', sub: f.why || '' };
}
const mb = b => b ? (b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : Math.round(b / 1e6) + ' MB') : '';

async function sendFile(file, replace) {
  const url = '/api/golem/drop?name=' + encodeURIComponent(file.name) + (replace ? '&replace=' + encodeURIComponent(replace) : '');
  const r = await fetch(url, { method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' } });
  let d = {};
  try { d = await r.json(); } catch { /* corps vide */ }
  return { ok: r.ok && d.ok !== false, ...d };
}

// ── « What this song carries » ──
export function FileSheet({ song, onClose, onChanged, onLink, onAdopt }) {
  const paired = useFmPaired();
  const [tick, setTick] = useState(0);
  const { data } = useAsync(() => fetch('/api/songs/' + encodeURIComponent(song.id) + '/files').then(r => r.json()), [song.id, tick]);
  const [said, setSaid] = useState(null);
  const pick = useRef(null);
  const replace = async file => {
    if (!file) return;
    setSaid({ busy: true, msg: 'installing ' + file.name + '…' });
    const r = await sendFile(file, song.id);
    setSaid({ ok: r.ok, msg: r.ok ? 'replaced — your song keeps its sheet' : (r.why || r.error || 'refused') });
    if (r.ok) { setTick(t => t + 1); onChanged && onChanged(); }
  };
  const st = (data || {}).state;
  // « Store on golem.fm » (song-sharing.md §2.7) : un GESTE, jamais automatique — les places restantes AVANT l'envoi
  const { data: quota } = useAsync(() => fetch('/api/golemfm/quotas').then(r => r.json()).catch(() => null), [song.id, tick]);
  // la déclaration d'origine licite à CHAQUE dépôt vers golem.fm (avocat, 2026-10-21, point 2) — quelle que soit la
  // chanson ; une `track` (de l'audio en attente de sa tab) n'a en plus rien à porter en « Text only »
  const [declared, setDeclared] = useState(false);
  const track = !!(data && data.category === 'track');
  const store = async mode => {
    setSaid({ busy: true, msg: mode === 'light' ? 'storing the text on golem.fm…' : 'storing the whole file on golem.fm…' });
    const r = await fetch('/api/songs/' + encodeURIComponent(song.id) + '/store', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, declared }) }).then(x => x.json()).catch(() => ({ why: 'golem.fm unreachable' }));
    setSaid({ ok: r.ok, msg: r.ok ? (r.already_here ? 'already on golem.fm — now linked to it' : 'stored on golem.fm — visible only to you') : (r.why || 'refused') });
    if (r.ok) { setTick(t => t + 1); onChanged && onChanged(); }
  };
  // « Get this recording » (song-sharing.md §2.6, lot 7) : le chemin LÉGAL vers l'audio — des liens de marchands
  // (Bandcamp, Qobuz, iTunes…) quand golem.fm a identifié l'enregistrement ; sinon on le dit, sans inventer de lien
  const { data: rec } = useAsync(() => fetch('/api/songs/' + encodeURIComponent(song.id) + '/recording').then(r => r.json()).catch(() => null), [song.id]);
  const sec = data && data.section && quota && quota.online ? quota[data.section] : null;
  // lue dans un DOSSIER DE CHANSONS (song-folders.md §2.2) : rien ne s'y écrit — pas de « Replace », pas de lien ;
  // « Use on this golem » la copie ici
  const inFolder = !!(data && data.folder);
  const full = sec && sec.limit != null && sec.used >= sec.limit;
  return html`<div class="sheet-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && onClose()}>
    <div class="gf-sheet">
      <div class="gf-hd"><b>What this song carries</b><span class="muted">${esc(song.title || song.id)} · ${esc(song.id.slice(0, 7))}…</span>
        <span class="grow"></span><button class="mini" onClick=${onClose}>✕</button></div>
      ${!data ? html`<p class="muted">reading the file…</p>`
        : st === 'broken' ? html`<p class="gf-bad">This song's file cannot be read: ${esc(data.why || '')}</p>`
        : html`<div class="gf-grid">${(data.items || []).map(i => html`<div class=${cls('gf-it', i.state)}>
            <div class="gf-ih"><i>${i.state === 'ok' ? '✓' : i.state === 'missing' ? '✕' : '—'}</i>${esc(i.label)}</div>
            <small title=${i.info || ''}>${esc(i.info || '')}</small></div>`)}</div>`}
      ${st === 'card' ? html`<div class="gf-hint">↗ No recording on this golem yet — have your own file? <b>Separate a folder</b>
          makes songs from it, on this golem. <a href=${'#/' + SEPARATE} onClick=${onClose}>Engines ▸ Separation</a>
          ${paired ? html` · or make the song's .golem on golem.fm: it comes back here on its own. <a href=${GOLEMFM_CREATE} target="_blank" rel="noopener">Open golem.fm</a>` : ''}</div>` : ''}
      ${rec && (rec.links || []).length ? html`<div class="gf-rec">
          <span><b>Get this recording</b> <small>${rec.isrc ? 'ISRC ' + rec.isrc : 'identified by golem.fm'}${rec.source === 'cache' ? ' · offline, last known' : ''}</small></span>
          <span class="grow"></span>
          ${rec.links.slice(0, 5).map(l => html`<a class="mini gf-a" href=${l.url} target="_blank" rel="noopener noreferrer" title=${l.url}>${esc(l.label)} ↗</a>`)}
        </div>`
        : rec && !rec.identified && st && st !== 'complete' && song.kind !== 'original' ? html`<div class="gf-rec muted">
          <span><b>Get this recording</b> <small>not identified yet — golem.fm recognises the recording the first time you play the song in its player</small></span>
        </div>` : ''}
      ${data && data.category && !data.from_golemfm ? html`<div class="gf-store">
          <span><b>Store on golem.fm</b> <small>${sec ? (sec.limit != null ? `${data.section} · ${sec.used} of ${sec.limit} used` : `${data.section} · ${sec.used} used`) : quota && !quota.online ? 'golem.fm unreachable' : 'only you will see it'}</small></span>
          <span class="grow"></span>
          ${track ? '' : html`<button class="mini" disabled=${!!full || (said && said.busy) || (quota && !quota.online) || !declared}
            title="lyrics, tab, chart and bar map only — a few KB, no audio" onClick=${() => store('light')}>Text only</button>`}
          <button class="mini primary" disabled=${!!full || (said && said.busy) || (quota && !quota.online) || !declared}
            title="the whole file, audio and stems included" onClick=${() => store('full')}>⇧ Whole file</button>
          ${full ? html`<small class="gf-bad">no room left</small>` : ''}
        </div>` : ''}
      ${data && data.category && !data.from_golemfm ? html`<label class="gf-decl"><input type="checkbox" checked=${declared}
          onChange=${e => setDeclared(e.target.checked)} /><span>${track ? html`<b>Waiting for a tab</b> — on golem.fm you can add your tablature or lyrics, then sync them. ` : ''}${DECLARATION}</span></label>` : ''}
      ${said ? html`<div class=${cls('gf-said', said.ok ? 'ok' : said.busy ? '' : 'bad')}>${esc(said.msg)}</div>` : ''}
      <div class="gf-ft">
        ${inFolder ? html`<span>📁 read from a song folder · ${mb(data.bytes)} · <code title=${data.path}>${esc(data.folder.folder)}</code></span>`
        : data && data.path ? html`<span>${data.from_golemfm ? 'also on golem.fm' : 'on this rack only'}${data.etag ? html` · version <code>${esc(data.etag.slice(0, 6))}</code>` : ''}${' · ' + mb(data.bytes)} · <code>${esc(data.path)}</code></span>` : html`<span></span>`}
        <span class="grow"></span>
        ${inFolder ? (onAdopt ? html`<button class="mini primary" title="copy it into this golem — the folder copy is untouched"
            onClick=${onAdopt}>Use on this golem</button>` : '') : html`
        ${onLink ? html`<button class="mini" title="the golem.fm song this one follows (its file is pulled from there)" onClick=${onLink}>☁ golem.fm link…</button>` : ''}
        <input ref=${pick} type="file" accept=".golem" style="display:none" onChange=${e => replace(e.target.files[0])} />
        <button class="mini" title="a .golem of the SAME recording replaces this song's files — your sheet stays yours"
          onClick=${() => pick.current && pick.current.click()}>⤓ Replace with a file…</button>`}
      </div>
    </div></div>`;
}

// ── déposer un .golem ──
export function DropSheet({ onClose, onChanged }) {
  const paired = useFmPaired();
  const [tick, setTick] = useState(0);
  const { data } = useAsync(() => fetch('/api/inbox').then(r => r.json()).catch(() => null), [tick]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(null);
  const [dirEdit, setDirEdit] = useState(null);
  const pick = useRef(null);
  useEffect(() => { const t = setInterval(() => setTick(x => x + 1), 4000); return () => clearInterval(t); }, []);   // le dossier surveillé travaille aussi
  const send = async files => {
    for (const f of [...(files || [])]) {
      setBusy(f.name);
      await sendFile(f);
      setTick(x => x + 1);
    }
    setBusy(null);
    onChanged && onChanged();
  };
  const saveDir = async () => {
    const r = await fetch('/api/inbox', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir: dirEdit }) });
    if (r.ok) { setDirEdit(null); setTick(x => x + 1); }
  };
  const evText = e => e.ok
    ? (e.replaced ? `replaced the files of « ${e.title || e.id} »` : e.created ? `new song « ${e.title || e.id} »` : `updated « ${e.title || e.id} »`)
      + (e.preset && e.preset.action === 'created' ? ' · its preset added' : '')
    : e.why || 'refused';
  return html`<div class="sheet-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && onClose()}>
    <div class="gf-sheet gf-drop">
      <div class="gf-hd"><b>Drop a .golem</b><span class="grow"></span><button class="mini" onClick=${onClose}>✕</button></div>
      <div class=${cls('gf-zone', over && 'over')}
        onDragOver=${e => { e.preventDefault(); setOver(true); }} onDragLeave=${() => setOver(false)}
        onDrop=${e => { e.preventDefault(); setOver(false); send(e.dataTransfer.files); }}>
        <b>${busy ? 'installing ' + busy + '…' : 'Drop a .golem file here'}</b>
        <small>a song: its recording, stems, tab, lyrics, bar map and preset</small>
        <input ref=${pick} type="file" accept=".golem" multiple style="display:none" onChange=${e => send(e.target.files)} />
        <button class="primary" disabled=${!!busy} onClick=${() => pick.current && pick.current.click()}>Choose a file…</button>
      </div>
      <div class="gf-ev gf-fm"><i>↗</i><div><b>Only have an MP3, WAV or FLAC?</b> <small>Separate a folder makes songs from your own files, on this golem — stems included</small></div>
        <button class="mini" onClick=${() => { onClose(); go(SEPARATE); }}>Separation ›</button></div>
      ${paired ? html`<div class="gf-ev gf-fm"><i>↗</i><div><b>Or on golem.fm</b> <small>it separates the stems and maps the bars, then sends the .golem here</small></div>
        <a class="mini gf-a" href=${GOLEMFM_CREATE} target="_blank" rel="noopener">Open golem.fm</a></div>` : ''}
      <div class="gf-list">
        ${((data || {}).recent || []).slice(0, 4).map(e => html`<div class="gf-ev">
          <i class=${e.ok ? 'ok' : 'bad'}>${e.ok ? '✓' : '✕'}</i>
          <div><b>${esc(e.file || '')}</b> <small>${esc(evText(e))}</small></div>
          <small>${esc(String(e.at || '').slice(11, 16))}</small></div>`)}
      </div>
      <div class="gf-ft">
        ${dirEdit != null
          ? html`<span>Watched folder</span><input class="gf-dir" value=${dirEdit} onInput=${e => setDirEdit(e.target.value)} />
              <button class="mini primary" onClick=${saveDir}>Save</button><button class="mini" onClick=${() => setDirEdit(null)}>Cancel</button>`
          : html`<span>Watched folder: <code>${esc((data || {}).dir || '…')}</code> — a .golem dropped there is installed the same way</span>
              <span class="grow"></span><button class="mini" onClick=${() => setDirEdit((data || {}).dir || '')}>Change folder…</button>`}
      </div>
    </div></div>`;
}

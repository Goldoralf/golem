// SPDX-License-Identifier: GPL-3.0-or-later
// Le RÉPERTOIRE — Songs ▸ Songs (docs/songs.md, lots 2 et 3). Deux écrans dans un module :
// la LISTE des chansons du groupe, et LA PAGE d'une chanson.
//
// ⚠ UNE CHANSON S'OUVRE, elle n'est pas une ligne dans une liste. La première maquette reprenait
// le patron de la setlist ouverte (colonne de 290 px + détail) et le mainteneur l'a lue comme une setlist,
// à juste titre : c'est la forme d'un AGRÉGAT. D'où une page pleine largeur, et l'arrangement au
// centre — « l'arrangement se fait maintenant dans songs » (2026-09-20).
//
// ⚠ PAS D'INTERRUPTEUR DE PORTÉE ICI. Tout ce qui s'édite sur cette page entre dans la CHANSON :
// on y est. L'interrupteur « saves into the song » n'avait de sens que depuis une setlist.
//
// §9 (2026-09-22) : une chanson NAÎT AUSSI SUR LE RACK (＋ New song : titre, nature, preset,
// tempo qui surcharge le preset, espace). Les stems restent une option de golem.fm : la case les
// LIE à un morceau du catalogue, elle n'importe aucun fichier. Et la setlist ne fabrique plus de
// chanson : elle en AJOUTE du répertoire (SongPicker, exporté pour elle).
import { html, useState, useEffect, useRef, useAsync, post, del, cls, esc, go, setSubToolbar, setTopAction, savePresetEverywhere } from './lib.js';
import { menuEntry as startupEntry } from './startup-model.mjs';   // l'accueil au démarrage (mockups/startup-home.html)
import { FileSheet, DropSheet, fileLine } from './song-files.js';
import { fmPaired } from './services-model.mjs';   // ☁ Pull seulement sur un golem appairé
import { PARTS, PART_SHORT, PART_LABEL } from './page-backing.js';   // la bande des instruments, celle des cartes Tracks
import { ArrangementPage } from './designer-arrangement.js';
import { arrangementLanes, arrangementEntries, hydrateBlockMeta } from './designer-model.js';

// l'erreur du bridge porte une PHRASE (« say what it is: cover or original ») : on la lit dans le
// corps de la réponse au lieu de la jeter pour « /api/songs → 400 »
const api = (u, b) => post(u, b).catch(e => ((e.body && e.body.error) ? e.body : { error: String(e) }));
const TUNINGS = ['Standard', 'E♭', 'D standard', 'Drop D', 'Drop C♯', 'Drop C', 'Open G', 'Open D', 'DADGAD'];
// l'espace d'une chanson, dit en clair : « ◇ le groupe », « ◇ le groupe · personal »
const spaceOf = (spaces, id) => (spaces || []).find(x => x.id === id) || null;
const spaceLabel = sp => sp ? sp.name + (sp.kind === 'personal' ? ' · personal' : '') : null;
// LA MONTÉE vers golem.fm (docs/songs.md §9.8) — calculée par le bridge (`sync`), dite ici en une puce :
// la raison d'un refus est affichée telle que golem.fm l'a donnée, jamais résumée en « error ».
const syncChip = (sy, rev) => {
  const st = (sy || {}).state;
  if (st === 'synced') return html`<span class="chip fm" title="golem.fm has this version">☁ golem.fm · rev ${sy.rev || rev}</span>`;
  if (st === 'rejected') return html`<span class="chip warn" title="golem.fm refused it — it stays on this rack until it changes">⚠ golem.fm: ${esc(sy.why || 'refused')}</span>`;
  if (st === 'factory') return html`<span class="chip" title="a factory song — it ships with golem and stays on this rack">◆ Factory</span>`;
  if (st === 'pending') return html`<span class="chip sg-up" title="it goes up at the next round trip with golem.fm">↑ waiting for golem.fm</span>`;
  return html`<span class="chip sg-up" title="this rack is not paired with golem.fm">rack only</span>`;
};
// après « ＋ New song… » depuis une setlist : la chanson créée y revient ajoutée (docs/songs.md §9.6)
const RETURN_KEY = 'golem.newSongFor';
const secs = a => (((a || {}).params || {}).sections) || [];
const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
// la durée d'une chanson : la MÊME formule que le moteur et que le click (docs/arrangement.md) —
// bars × num × (4/den) × 60/bpm. Recopiée nulle part ailleurs dans ce fichier.
const songSeconds = (a, bpm) => {
  const p = (a || {}).params || {}, sig = p.sig || { num: 4, den: 4 };
  const beat = 60 / (bpm || 120);
  return secs(a).reduce((t, s) => {
    const g = s.sig || sig;
    return t + (s.bars || 0) * (g.num || 4) * (4 / (g.den || 4)) * beat;
  }, 0);
};

// ── ① LA LISTE ──────────────────────────────────────────────────────────────────────────────
// Quatre états sur un écran, et c'est le point : prête, à finir, née ici, nature à dire. Aucun
// n'était visible tant qu'une chanson n'existait que dans une setlist.
// LA SOURCE (docs/song-folders.md §2.8) : les chansons du golem, celles des dossiers de chansons (lues sur place),
// ou les deux. Les dossiers peuvent porter des milliers de chansons : ils sont CHERCHÉS côté rack, par pages.
const SOURCES = [['golem', 'Golem', 'the songs on this golem'], ['folders', 'Folders', 'songs read from your song folders — Settings ▸ Content ▸ Storage'],
  ['all', 'All', 'both']];
const FOLDER_PAGE = 30;
const FACETS = [
  ['all', 'All', 'every song the band knows'],
  ['ready', 'Stage-ready', 'a preset on this rack, and an arrangement'],
  ['todo', 'To finish', 'something is still missing'],
  ['cover', 'Covers', ''],
  ['original', 'Originals', ''],
];

export function RepertoirePage({ rig, sub }) {
  const open = (sub || '').trim();
  if (open === '+import') return html`<${ImportPage} />`;
  if (open === '+new') return html`<${SongList} rig=${rig} creating=${true} />`;
  // key = l'id : le brouillon d'arrangement d'une chanson ne doit jamais suivre sur la suivante
  return open ? html`<${SongPage} key=${open} sid=${decodeURIComponent(open)} rig=${rig} />`
              : html`<${SongList} rig=${rig} />`;
}

// ── ③ L'IMPORT — et ce qui manque pour qu'il marche ─────────────────────────────────────────
// ⚠ Cet écran DIT que la source n'existe pas encore, au lieu d'afficher une liste vide qu'on
// lirait « votre groupe n'a aucune chanson » (docs/songs.md §7). Une absence expliquée se
// comprend ; une absence muette envoie chercher la panne au mauvais endroit — c'est la leçon la
// plus chère de ce dépôt.
function ImportPage() {
  const { data } = useAsync(() => fetch('/api/songs/source').then(r => r.json()).catch(() => null), []);
  useEffect(() => { setSubToolbar(html`<span class="muted sg-crumb">
    <a onClick=${() => go('songs/songs')}>‹ All songs</a> / <b>Pull from golem.fm</b></span>`);
    return () => setSubToolbar(null); }, []);
  if (!data) return html`<div class="lib-grid"><p class="muted">loading…</p></div>`;
  return html`<div class="lib-grid"><div class="sg-empty">
    <h3>☁ Pull from golem.fm</h3>
    <p class="muted">Songs of your spaces on golem.fm arrive here with their preset, their arrangement and their
      stems. To start a song on this rack instead, use ＋ New song.</p>
    ${data.available ? '' : html`
      <div class="sg-blocked">
        <span class="chip warn">not available yet</span>
        <p>${esc(data.says || '')}</p>
        ${data.why === 'not_paired'
          ? html`<button class="primary" onClick=${() => go('system/connect/golemfm')}>Pair this rack →</button>`
          : html`<p class="muted sg-mean">Meanwhile, a song reaches this rack <b>with a setlist</b>:
              every line that names one brings it along.</p>`}
      </div>`}
  </div></div>`;
}

function SongList({ creating, rig }) {
  const paired = fmPaired(rig);
  const [nonce, bump] = useState(0);
  const { data } = useAsync(() => fetch('/api/songs').then(r => r.json()).catch(() => null), [nonce]);
  const { data: presets } = useAsync(() => fetch('/api/presets').then(r => r.json()).catch(() => []), []);
  const songs = (data || {}).songs || [];
  const spaces = (data || {}).spaces || [];
  const pname = id => ((presets || []).find(p => p.id === id) || {}).name || id;
  const [q, setQ] = useState('');
  const [facet, setFacet] = useState('all');
  const [drop, setDrop] = useState(false);              // « ⤓ Drop a file » (lot 5) : un .golem, et seulement ça
  const [src, setSrc] = useState('golem');
  const [fpage, setFpage] = useState(0);
  const [fsheet, setFsheet] = useState(null);           // une chanson de dossier ouverte (« What this song carries »)
  const [fsaid, setFsaid] = useState(null);
  useEffect(() => setFpage(0), [q, src]);
  const { data: fold } = useAsync(() => src === 'golem' ? Promise.resolve(null)
    : fetch(`/api/song-folders/songs?q=${encodeURIComponent(q)}&offset=${fpage * FOLDER_PAGE}&limit=${FOLDER_PAGE}`)
      .then(r => r.json()).catch(() => null), [src, q, fpage, nonce]);
  const adopt = async e => {
    setFsaid({ busy: true, msg: 'copying « ' + (e.title || e.id) + ' » into this golem…' });
    const r = await api('/api/song-folders/adopt', { path: e.path });
    setFsaid({ ok: !r.error && r.ok !== false, msg: r.ok ? 'Added to this golem — the folder copy is untouched' : (r.why || r.error || 'refused') });
    if (r.ok) { setFsheet(null); bump(n => n + 1); }
  };

  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search songs…"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <div class="tb-seg" data-doc="songs.sources" title="where the songs are">
        ${SOURCES.map(([id, lb, ttl]) => html`<button class=${cls(src === id && 'on')} title=${ttl}
          onClick=${() => setSrc(id)}>${lb}</button>`)}
      </div>
      ${/* les facettes ne valent que pour les chansons du golem : une chanson de dossier n'a ni preset ni arrangement */''}
      ${src === 'golem' ? html`<div class="tb-seg" data-doc="songs.facets" title="what to show">
        ${FACETS.map(([id, lb, ttl]) => html`<button class=${cls(facet === id && 'on')} title=${ttl}
          onClick=${() => setFacet(id)}>${lb}</button>`)}
      </div>` : ''}`);
    return () => setSubToolbar(null);
  }, [facet, src]);

  // ＋ New song (la porte principale, §9) et ☁ Pull (golem.fm, la seconde). L'action appartient à la
  // PAGE, jamais au hub — sinon le hub écrase le `+ Add` de la page (piège setTopAction).
  // ⚠ Rendue dans la TOPBAR, pas dans l'hôte « page » : le hub Songs n'affiche pas cet hôte (seule la
  // Library le fait), et le « ＋ Add a song » du 20/09 publié là n'est JAMAIS apparu — trouvé au rendu
  // le 2026-09-22. La topbar de Songs a la place : ses onglets sont dans la rangée du hub.
  useEffect(() => {
    setTopAction(html`<span class="sgn-acts">
      <button class="chip sg-drop" title="install a song from a .golem file" onClick=${() => setDrop(true)}>⤓ Drop a file</button>
      ${paired ? html`<button class="chip" title="pull songs from your band's repertoire on golem.fm"
        onClick=${() => go('songs/songs/+import')}>☁ Pull from golem.fm</button>` : ''}
      <button class="primary" title="create a song on this rack" onClick=${() => go('songs/songs/+new')}>＋ New song</button></span>`);
    return () => setTopAction(null); }, [paired]);

  const shown = src === 'folders' ? [] : songs.filter(s => {
    if (q && !((s.title || '') + ' ' + (s.artist || '')).toLowerCase().includes(q)) return false;
    if (src === 'all') return true;
    if (facet === 'ready') return s.ready;
    if (facet === 'todo') return !s.ready;
    if (facet === 'cover' || facet === 'original') return s.kind === facet;
    return true;
  });
  const sheet = html`${creating && data ? html`<${NewSongSheet} presets=${presets || []} spaces=${spaces}
    defaultSpace=${data.default_space} onClose=${() => { try { sessionStorage.removeItem(RETURN_KEY); } catch (e) {} go('songs/songs'); }} />` : ''}
    ${drop ? html`<${DropSheet} onClose=${() => setDrop(false)} onChanged=${() => bump(n => n + 1)} />` : ''}
    ${fsheet ? html`<${FileSheet} song=${fsheet} onClose=${() => setFsheet(null)} onAdopt=${() => adopt(fsheet)} />` : ''}`;
  // les chansons des DOSSIERS (song-folders.md) : déjà sur le golem = absentes (la liste du golem les montre),
  // les standards vont au tiroir des standards
  const fitems = ((fold || {}).items || []).filter(e => e.category !== 'standard');
  const ftotal = (fold || {}).total || 0;
  const folderRows = src === 'golem' ? '' : html`
    ${src === 'all' && fitems.length ? html`<div class="sg-fhd muted">From your song folders</div>` : ''}
    ${fitems.map(e => html`<div class=${cls('prow', 'sg-row', 'sg-folder', e.state !== 'ok' && 'sg-off')}
        onClick=${() => e.state === 'ok' && setFsheet(e)}>
      <div class="prow-main">
        <div class="pm-head">
          <b class="prow-name">${esc(e.title || e.path.split(/[\\/]/).pop())}</b>
          ${e.kind ? html`<span class="chip">${e.kind}</span>` : ''}
          ${e.category === 'vocals' ? html`<span class="chip">Vocals</span>` : ''}
          <span class="chip sg-fchip" title=${e.path}>📁 ${esc(e.folder.split(/[\\/]/).pop())}</span>
          ${e.state !== 'ok' ? html`<span class="chip warn" title="the folder is offline — plug it in">offline</span>` : ''}
          ${e.copies && e.copies.length > 1 ? html`<span class="chip" title=${e.copies.map(c => c.path).join('\n')}>${e.copies.length} copies</span>` : ''}
          ${e.same_as ? html`<span class="chip warn" title="same recording as a song on this golem">same recording as « ${esc(e.same_as.title || e.same_as.id)} »</span>` : ''}
        </div>
        <div class="sg-sub">
          ${e.artist ? html`<span>${esc(e.artist)}</span>` : ''}
          ${e.duration_ms ? html`<span>${mmss(e.duration_ms / 1000)}</span>` : ''}
          ${Object.entries(e.carries || {}).filter(([k, v]) => v && (!Array.isArray(v) || v.length)).map(([k, v]) =>
            html`<span>${Array.isArray(v) ? v.length + ' ' + k : k}</span>`)}
        </div>
      </div>
      <div class="prow-side sg-side">
        <div class="next muted">read in place — play and rehearse from the folder</div>
        <button class="mini primary" disabled=${e.state !== 'ok' || (fsaid && fsaid.busy)}
          title="copy it into this golem — the folder copy is untouched"
          onClick=${ev => { ev.stopPropagation(); adopt(e); }}>Use on this golem</button>
      </div>
    </div>`)}
    ${fsaid && !fsheet ? html`<div class=${cls('gf-said', fsaid.ok ? 'ok' : fsaid.busy ? '' : 'bad')}>${esc(fsaid.msg)}</div>` : ''}
    ${ftotal > FOLDER_PAGE ? html`<div class="sg-fpg">
      <button class="mini" disabled=${fpage === 0} onClick=${() => setFpage(fpage - 1)}>‹</button>
      <small>${fpage * FOLDER_PAGE + 1}–${Math.min(ftotal, (fpage + 1) * FOLDER_PAGE)} of ${ftotal} — search to narrow</small>
      <button class="mini" disabled=${(fpage + 1) * FOLDER_PAGE >= ftotal} onClick=${() => setFpage(fpage + 1)}>›</button></div>` : ''}
    ${src === 'folders' && fold && !ftotal ? html`<div class="sg-empty"><h3>No songs from folders</h3>
      <p class="muted">${q ? 'Nothing matches.' : 'Add a folder of .golem files in Settings ▸ Content ▸ Storage.'}</p>
      ${q ? '' : html`<button class="primary" onClick=${() => go('system/content/storage')}>Song folders →</button>`}</div>` : ''}`;

  if (!data) return html`<div class="lib-grid"><p class="muted">loading…</p></div>`;
  if (!songs.length && src === 'golem') return html`<div class="lib-grid"><div class="sg-empty">
    <h3>No songs yet</h3>
    <p class="muted">Create one here — a title, cover or original, its preset, its tempo — then lay out its
      arrangement. Songs of your band on golem.fm can be pulled too.</p>
    <button class="primary" onClick=${() => go('songs/songs/+new')}>＋ New song</button>
  </div>${sheet}</div>`;

  return html`<div class="lib-grid"><div class="sgc-grid">
    ${shown.map(s => {
      const sh = s.sheet || {};
      const dur = sh.arrangement ? songSeconds(sh.arrangement, sh.bpm) : 0;
      const sp = spaceOf(spaces, s.band);
      // CE QUI MANQUE, dit une fois et précisément — « not ready » tout seul n'appelle aucun geste
      const missing = !sh.preset ? 'choose a preset' : !s.preset_here ? 'preset not on this rack'
        : !s.parts ? 'arrange it' : null;
      const fl = fileLine(s.file);
      const art = k => '/api/backing/asset/' + encodeURIComponent(s.id) + '/' + k;
      const nset = (s.setlists || []).length;
      // LA CARTE DE CHANSON (2026-10-17, harmonisée avec Library ▸ Tracks) : pochette, titre, artiste et sa photo,
      // les étiquettes ; en pied le preset, le .golem, les setlists et le geste suivant ; la bande des instruments.
      return html`<div class=${cls('sgc', s.ready && 'ready', s.born === 'rack' && 'rk', !s.kind && 'draft', missing && !sh.preset && 'todo')} data-doc=${'songs.song:' + s.id}
        onClick=${() => go('songs/songs/' + encodeURIComponent(s.id))}>
        <div class="sgc-top">
          <div class="bkg-art sgc-art">
            <span class="bkg-noart" aria-hidden="true">♪</span>
            ${s.has_cover ? html`<img src=${art('cover')} alt="" loading="lazy" onError=${e => { e.target.style.display = 'none'; }} />` : ''}
          </div>
          <div class="sgc-info">
            <b class="sgc-title" title=${s.title || s.id}>${esc(s.title || s.id)}</b>
            <div class="sgc-artist">
              ${s.has_photo ? html`<img class="bkg-face" src=${art('photo')} alt="" loading="lazy" onError=${e => { e.target.style.display = 'none'; }} />` : ''}
              <span>${esc(s.artist || 'unknown artist')}</span>
              ${sh.bpm ? html`<i>♩ ${sh.bpm}</i>` : ''}${dur ? html`<i>${mmss(dur)}</i>` : ''}
              ${sh.tuning ? html`<i>${esc(sh.tuning)}</i>` : ''}${sh.capo ? html`<i>capo ${sh.capo}</i>` : ''}
            </div>
            <div class="sgc-chips">
              ${s.kind ? html`<span class="bkg-tag">${s.kind}</span>`
                       : html`<span class="chip warn" title="cover or original? golem.fm needs it — a cover's audio, tab and lyrics are never shared with anyone">nature to say</span>`}
              ${s.ready ? html`<span class="chip go">● stage-ready</span>` : ''}
              ${s.born === 'rack' ? html`<span class="chip sg-born" title="created on this rack">◆ born here</span>` : ''}
              ${sp ? html`<span class="bkg-chip">◇ ${esc(spaceLabel(sp))}</span>` : ''}
              ${syncChip(s.sync, s.rev)}
            </div>
          </div>
        </div>
        <div class="sgc-foot">
          <span title="preset">${sh.preset ? html`<b class=${cls(!s.preset_here && 'muted')}>⚡ ${esc(pname(sh.preset))}</b>` : html`<span class="muted">no preset</span>`}</span>
          <span class=${'sg-file ' + fl.cls} title=${fl.sub}>${fl.ic} ${fl.txt}</span>
          <span class="muted" title=${(s.setlists || []).map(x => x.name).join(' · ')}>${nset} setlist${nset === 1 ? '' : 's'}</span>
          <span class="muted">${s.parts ? s.parts + ' part' + (s.parts > 1 ? 's' : '') : 'no arrangement'}</span>
          <span class="grow"></span>
          ${missing ? html`<a class="sgc-next">${missing} →</a>` : ''}
        </div>
        ${s.tab_parts && s.tab_parts.length ? html`<div class="bkg-strip-parts" role="group" aria-label="Instruments in this song">
          ${PARTS.map(p => { const on = s.tab_parts.includes(p);
            return html`<span class=${cls('bkg-part', 'bkg-part-' + p, !on && 'off')}
              title=${on ? PART_LABEL[p] + ' part' : 'No ' + PART_LABEL[p].toLowerCase() + ' part'}>${PART_SHORT[p]}</span>`; })}
        </div>` : ''}
      </div>`;
    })}
    ${!shown.length && src === 'golem' ? html`<p class="muted" style="padding:10px 2px">Nothing matches.</p>` : ''}
  </div>${folderRows ? html`<div class="plist sgc-folders">${folderRows}</div>` : ''}${sheet}</div>`;
}

// ── ② ＋ NEW SONG (docs/songs.md §9.2) ─────────────────────────────────────────────────────
// Quatre réponses, puis on arrange. La NATURE n'a pas de défaut et pas de « plus tard » : chez
// golem.fm une chanson sans nature tomberait dans leur défaut `original` — une reprise publiable.
// Le TEMPO surcharge le preset ; vide, il suit celui du preset (dit en clair, ↺ y revient).
function NewSongSheet({ presets, spaces, defaultSpace, onClose }) {
  const [f, setF] = useState({ title: '', artist: '', kind: null, preset: null, bpm: null, band: defaultSpace || null });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF(x => ({ ...x, [k]: v }));
  const pr = presets.find(x => x.id === f.preset) || null;
  const pbpm = pr ? pr.bpm : null;
  const step = d => set('bpm', Math.max(20, Math.min(400, (f.bpm || pbpm || 120) + d)));
  const ok = f.title.trim() && f.kind && !busy;
  const create = async () => {
    if (!ok) return;
    setBusy(true); setErr('');
    const r = await api('/api/songs', { title: f.title.trim(), artist: f.artist.trim() || null, kind: f.kind,
      preset: f.preset, bpm: f.bpm, band: f.band });
    setBusy(false);
    if (!r || r.error || !r.song) { setErr((r && r.error) || 'could not create the song'); return; }
    let back = null;
    try { back = sessionStorage.getItem(RETURN_KEY); sessionStorage.removeItem(RETURN_KEY); } catch (e) {}
    if (back) {                                   // venu d'une setlist : elle y revient ajoutée
      await api('/api/setlists/' + encodeURIComponent(back) + '/songs', { ids: [r.song.id] });
      go('songs/setlists/' + back);
    } else go('songs/songs/' + encodeURIComponent(r.song.id));
  };
  return html`<div class="sgn-scrim" onClick=${e => e.target.classList.contains('sgn-scrim') && onClose()}>
    <div class="sgn" onKeyDown=${e => { if (e.key === 'Escape') onClose(); }}>
      <div class="sgn-hd"><b>＋ New song</b><span class="chip sg-born">◆ born on this rack</span><span class="grow"></span>
        <label class="sgn-space" title="where the song lives: your personal space, or one of your bands">space
          <select value=${f.band || ''} onChange=${e => set('band', e.target.value)}>
            ${spaces.map(sp => html`<option value=${sp.id} selected=${sp.id === f.band}>${spaceLabel(sp)}</option>`)}
          </select></label></div>
      <div class="sgn-row">
        <label class="sgn-in sgn-wide"><span class="k">Title <em>required</em></span>
          <input autofocus maxlength="160" value=${f.title} placeholder="Killing in the Name"
            onInput=${e => set('title', e.target.value)} onKeyDown=${e => e.key === 'Enter' && create()} /></label>
        <label class="sgn-in"><span class="k">Artist</span>
          <input maxlength="160" value=${f.artist} placeholder="—" onInput=${e => set('artist', e.target.value)} /></label>
      </div>
      <div class="sgn-row">
        <div class="sgn-in"><span class="k">Cover or original?</span>
          <div class="sgn-kind"><div class="tb-seg">
            ${[['cover', 'Cover'], ['original', 'Original']].map(([k, lb]) => html`<button class=${cls(f.kind === k && 'on')}
              onClick=${() => set('kind', k)}>${lb}</button>`)}</div>
            ${!f.kind ? html`<span class="muted">no default — pick one</span>` : ''}</div></div>
        <div class="sgn-in"><span class="k">Tempo · overrides the preset</span>
          <div class="sgn-tempo">
            <button class="sgn-stp" onClick=${() => step(-1)}>−</button>
            <input type="number" min="20" max="400" value=${f.bpm == null ? '' : f.bpm} placeholder=${pbpm || '—'}
              onInput=${e => set('bpm', e.target.value === '' ? null : +e.target.value)} />
            <button class="sgn-stp" onClick=${() => step(1)}>＋</button>
            <button class="sgn-stp" title="follow the preset's tempo" onClick=${() => set('bpm', null)}>↺</button>
            <span class="sgn-ov">${!pr ? 'Choose a preset — or type a tempo.'
              : f.bpm && f.bpm !== pbpm ? html`The preset plays at ${pbpm}.<br /><b>This song plays at ${f.bpm}.</b>`
              : html`Follows the preset: ${pbpm}.`}</span>
          </div></div>
      </div>
      <div class="sgn-in"><span class="k">Preset <span class="muted">— the sound of the song. You can change it later.</span></span>
        <div class="sgn-pgrid">
          ${presets.map(p => html`<button class=${cls('sgn-pc', f.preset === p.id && 'on')} onClick=${() => set('preset', p.id)}>
            <b>${esc(p.name || p.id)}</b><small>♩ ${p.bpm || '—'} · ${(p.scenes || []).length} scenes</small></button>`)}
          <button class=${cls('sgn-pc', 'none', !f.preset && 'on')} onClick=${() => set('preset', null)}>
            <b>None yet</b><small>choose it later</small></button>
        </div></div>
      <p class="muted sgn-sub">Tuning, capo, a note and the arrangement live on the song page; stems come from golem.fm. <b>Nothing here needs golem.fm</b>: the song works on this rack right away.</p>
      <div class="sgn-ft">${err ? html`<span class="chip warn">✗ ${esc(err)}</span>` : html`<span class="muted">Esc = cancel · nothing is written until you create it</span>`}
        <span class="grow"></span>
        <button class="chip" onClick=${onClose}>Cancel</button>
        <button class="primary" disabled=${!ok} title=${!f.title.trim() ? 'a song needs a title' : !f.kind ? 'cover or original?' : ''}
          onClick=${create}>${busy ? 'creating…' : 'Create — then arrange ›'}</button></div>
    </div></div>`;
}

// ── LES STEMS : une option de golem.fm (docs/songs.md §9.5) ─────────────────────────────────
// Le rack n'importe aucun fichier : il LIE la chanson à un morceau du catalogue golem.fm, que le rack
// sait déjà lister et télécharger. Sans golem.fm, la case reste vide et le DIT. Les backings LOCAUX
// (composés de samples) ne sont pas proposés ici : ils vivent dans Library ▸ Tracks.
function StemsSheet({ song, onClose, onPick }) {
  const { data } = useAsync(() => fetch('/api/backing/catalog').then(r => r.json()).catch(() => ({ online: false, songs: [] })), []);
  const [q, setQ] = useState('');
  const cur = (song.sheet || {}).backing || null;
  const list = ((data || {}).songs || []).filter(x => x && !x.local && x.slug)
    .filter(x => !q || ((x.title || '') + ' ' + (x.artist || '')).toLowerCase().includes(q));
  const online = !!(data || {}).online;
  return html`<div class="sgn-scrim" onClick=${e => e.target.classList.contains('sgn-scrim') && onClose()}>
    <div class="sgn sgs">
      <div class="sgn-hd"><b>☁ Stems of « ${esc(song.title || song.id)} »</b><span class="grow"></span>
        ${data ? html`<span class=${cls('chip', online ? 'go' : 'warn')}>${online ? '● golem.fm connected' : 'golem.fm not connected'}</span>` : ''}</div>
      <p class="muted sgn-sub">Pick the song in your golem.fm catalogue. Its stems download to this rack and play with the
        arrangement. For a cover, this also links the song to its catalogue entry.</p>
      ${!online && data ? html`<div class="sgs-off"><b>Stems come from golem.fm — not connected.</b>
        <span class="muted">Only stems already on this rack are listed.</span></div>` : ''}
      <input class="search sgs-q" type="search" placeholder="Search the catalogue…" onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <div class="sgs-list">
        ${!data ? html`<p class="muted">loading…</p>`
          : !list.length ? html`<p class="muted">${online ? 'Nothing matches in your catalogue.' : 'Nothing on this rack yet.'}</p>`
          : list.map(x => html`<button class=${cls('sgs-row', cur === x.slug && 'on')} onClick=${() => onPick(x)}>
              <span class="nm">${esc(x.title || x.slug)}<small>${esc(x.artist || '')}${x.duration_sec ? ' · ' + mmss(x.duration_sec) : ''}</small></span>
              <span class=${cls('chip', x.cached ? 'go' : 'fm')}>${x.cached ? '● on this rack' : '☁ downloads'}</span>
            </button>`)}
      </div>
      <div class="sgn-ft"><span class="muted">The stems stay in golem.fm's catalogue; the rack keeps a copy to play offline.</span>
        <span class="grow"></span>
        ${cur ? html`<button class="chip" onClick=${() => onPick(null)}>Remove the stems</button>` : ''}
        <button class="chip" onClick=${onClose}>Close</button></div>
    </div></div>`;
}

// ── ＋ ADD A SONG DEPUIS LA SETLIST (docs/songs.md §9.6) — exporté pour page-setlist-groups ──
// La setlist ne FABRIQUE plus de chanson : elle en choisit dans le répertoire, plusieurs à la fois.
// Une chanson déjà présente est grisée, pas masquée : on voit pourquoi elle ne s'ajoute pas.
export function SongPicker({ setlist, onClose, onAdded }) {
  const { data } = useAsync(() => fetch('/api/songs').then(r => r.json()).catch(() => null), []);
  const [q, setQ] = useState('');
  const [sel, setSel] = useState([]);
  const [err, setErr] = useState('');
  const here = new Set((setlist.lines || []).map(l => l.band_song).filter(Boolean));
  const spaces = (data || {}).spaces || [];
  const songs = ((data || {}).songs || []).filter(s => !q || ((s.title || '') + ' ' + (s.artist || '')).toLowerCase().includes(q));
  const toggle = id => setSel(x => x.includes(id) ? x.filter(y => y !== id) : [...x, id]);
  const add = async () => {
    const r = await api('/api/setlists/' + encodeURIComponent(setlist.id) + '/songs', { ids: sel });
    if (!r || r.error) { setErr((r && r.error) || 'could not add'); return; }
    onAdded && onAdded(r);
  };
  const newSong = () => { try { sessionStorage.setItem(RETURN_KEY, setlist.id); } catch (e) {} go('songs/songs/+new'); };
  return html`<div class="sgn-scrim" onClick=${e => e.target.classList.contains('sgn-scrim') && onClose()}>
    <div class="sgn sgp">
      <div class="sgn-hd"><b>＋ Add songs to « ${esc(setlist.name || setlist.id)} »</b><span class="grow"></span>
        <input class="search" type="search" placeholder="Search the repertoire…" onInput=${e => setQ(e.target.value.trim().toLowerCase())} /></div>
      <div class="sgs-list">
        ${!data ? html`<p class="muted">loading…</p>`
          : !songs.length ? html`<p class="muted">${q ? 'Nothing matches.' : 'No songs yet — create the first one.'}</p>`
          : songs.map(s => { const sh = s.sheet || {}; const has = here.has(s.id); const sp = spaceOf(spaces, s.band);
              return html`<button class=${cls('sgs-row', 'sgp-row', sel.includes(s.id) && 'on', has && 'have')} disabled=${has}
                onClick=${() => toggle(s.id)}>
                <span class=${cls('sgp-ck', sel.includes(s.id) && 'on')}></span>
                <span class="nm">${esc(s.title || s.id)}<small>${has ? 'already in this setlist'
                  : [s.artist, s.kind, sp ? '◇ ' + spaceLabel(sp) : null].filter(Boolean).join(' · ')}</small></span>
                <span class="w">${sh.bpm ? '♩ ' + sh.bpm : ''}</span>
                ${has ? html`<span></span>` : s.ready ? html`<span class="chip go">● stage-ready</span>`
                  : html`<span class="chip warn">${!sh.preset ? 'no preset' : 'no arrangement'}</span>`}
              </button>`; })}
      </div>
      <p class="muted sgn-sub">A song can sit in several setlists — it is <b>the same song</b> in each: edit it once, every
        setlist follows. Songs are added at the end; reorder with ⇅ Banks.</p>
      <div class="sgn-ft"><button class="chip sgp-new" onClick=${newSong}>＋ New song…</button>
        <span class="muted">creates it, then comes back here</span>
        ${err ? html`<span class="chip warn">✗ ${esc(err)}</span>` : ''}
        <span class="grow"></span>
        <button class="chip" onClick=${onClose}>Cancel</button>
        <button class="primary" disabled=${!sel.length} onClick=${add}>Add ${sel.length || ''} song${sel.length === 1 ? '' : 's'}</button></div>
    </div></div>`;
}

// ── ③ LA PAGE D'UNE CHANSON ─────────────────────────────────────────────────────────────────
function SongPage({ sid, rig }) {
  const [nonce, bump] = useState(0);
  const { data } = useAsync(() => fetch('/api/song/' + encodeURIComponent(sid))
    .then(r => r.ok ? r.json() : null).catch(() => null), [sid, nonce]);
  const { data: rep } = useAsync(() => fetch('/api/songs').then(r => r.json()).catch(() => null), [nonce]);
  const { data: presets } = useAsync(() => fetch('/api/presets').then(r => r.json()).catch(() => []), []);
  const song = (data || {}).song;
  const sets = (data || {}).setlists || [];
  const spaces = (rep || {}).spaces || [];
  const [msg, setMsg] = useState('');
  const [stems, setStems] = useState(false);
  const [files, setFiles] = useState(false);            // « What this song carries » (lot 5)
  const [addOpen, setAddOpen] = useState(false);
  // L'ARRANGEMENT EN COURS D'ÉDITION vit ICI, et part au bridge 600 ms après la dernière retouche —
  // comme sur une ligne de setlist. Avant (2026-09-22), chaque frappe faisait POST + relecture et
  // l'éditeur restait sur l'ANCIENNE valeur tant que la relecture n'était pas revenue : une saisie
  // rapide se calculait sur un état périmé. Quitter la page envoie ce qui attend encore.
  const [arrDraft, setArrDraft] = useState(null);
  const arrTimer = useRef(null);
  const arrPending = useRef(null);
  const flushArr = () => {
    clearTimeout(arrTimer.current); arrTimer.current = null;
    const next = arrPending.current; arrPending.current = null;
    if (next) api('/api/song/' + encodeURIComponent(sid), { arrangement: next })
      .then(r => { if (r && r.error) flash('✗ ' + r.error); });
  };
  useEffect(() => () => flushArr(), [sid]);
  // LE PRESET DE LA CHANSON : la piste des parties montre la SCÈNE de chacune (A/B/C) et les
  // blocs commutables — sans lui, l'éditeur afficherait des scènes vides et des blocs absents.
  // Absent du rack = état NORMAL (chanson reçue avant ses presets) : on dégrade, on ne casse pas.
  const pid = ((song || {}).sheet || {}).preset;
  // LA CARTE DES MESURES de la backing liée (docs/bars-format.md) : la rangée dit si les parties et le click
  // suivront les VRAIS temps du morceau, ou un tempo constant
  const bkSlug = ((song || {}).sheet || {}).backing || null;
  const { data: barMap } = useAsync(() => bkSlug ? fetch('/api/backing/bars/' + encodeURIComponent(bkSlug))
    .then(r => r.json()).catch(() => null) : Promise.resolve(null), [bkSlug]);
  const { data: pre, setData: setPre } = useAsync(() => pid
    ? fetch('/api/preset/' + encodeURIComponent(pid)).then(r => r.ok ? r.json() : null).catch(() => null)
    : Promise.resolve(null), [pid]);
  // LE TABLEAU DE L'ARRANGEMENT (sections × musiciens : scène, état de lane, stomps) a besoin des ENTRÉES
  // du preset, du patch de la carte (qui tient quelle entrée) et du catalogue (les noms courts « Comp »,
  // « Big Muff » que lisent ses lignes). La page Setlists les passait ; celle-ci non — et depuis le lot D
  // (2026-09-24, « un seul point d'entrée, /songs ») c'est la SEULE porte : le tableau avait disparu
  // (2026-09-30). Mêmes sources que page-setlist-groups.js.
  const { data: fxD } = useAsync(() => fetch('/api/effects').then(r => r.json()).then(d => { hydrateBlockMeta(d.effects || d, d); return d; }).catch(() => null), []);
  const { data: imap } = useAsync(() => fetch('/api/inputmap').then(r => r.json()).catch(() => null), []);
  const fx = (fxD && (fxD.effects || fxD)) || [];
  function flash(m) { setMsg(m); setTimeout(() => setMsg(''), 2600); }

  useEffect(() => { setSubToolbar(html`<span class="muted sg-crumb">
    <a onClick=${() => go('songs/songs')}>‹ All songs</a> / <b>${esc((song || {}).title || sid)}</b></span>`);
    return () => setSubToolbar(null); }, [song]);
  // « ＋ Add to a setlist ▾ » AJOUTE vraiment (docs/songs.md §9.4) : avant, il changeait d'onglet — et
  // il n'apparaissait même pas (hôte « page » que le hub Songs n'affiche pas). Topbar, comme la liste.
  useEffect(() => {
    setTopAction(html`<button class="chip sg-addbtn" onClick=${() => setAddOpen(o => !o)}>＋ Add to a setlist ▾</button>`);
    return () => setTopAction(null); }, []);

  if (!data) return html`<div class="lib-grid"><p class="muted">loading…</p></div>`;
  if (!song) return html`<div class="lib-grid"><p class="muted">This song is not on this rack.
    <a onClick=${() => go('songs/songs')}>‹ back to the repertoire</a></p></div>`;

  const sh = song.sheet || {};
  const save = async (k, v) => {
    const r = await api('/api/song/' + encodeURIComponent(sid), { [k]: v });
    if (r && r.error) flash('✗ ' + r.error); else bump(n => n + 1);
    return r;
  };
  // l'arrangement est édité par LE composant du Designer — une seule implémentation de la piste
  // des parties, sinon deux écrans divergent dès la première correction (vécu sur les scènes).
  const arrNow = arrDraft || sh.arrangement || { type: 'arrangement', id: 'arr-song', params: { advance: 'bars', sections: [] } };
  const putArr = next => {
    setArrDraft(next);
    arrPending.current = next;
    clearTimeout(arrTimer.current);
    arrTimer.current = setTimeout(flushArr, 600);
  };
  const onParam = (key, val) => {
    putArr({ ...arrNow, params: { ...(arrNow.params || {}), [key]: val } });
    if (key === 'advance') presetArr(b => { b.params = { ...(b.params || {}), advance: val }; });
  };
  // ⏻ AUTOMATION : l'état de la CHANSON (son bloc arrangement), même chemin que les parties
  const onBypass = () => putArr({ ...arrNow, bypass: !arrNow.bypass });

  // GET /api/preset/<id> rend le preset À PLAT (pas d'enveloppe {preset}) : lu sous {preset}, il était null —
  // aucune scène dans le sélecteur, aucun bloc commutable (trouvé le 2026-09-24 en posant le sélecteur de scène)
  const preset = (pre && pre.preset) || (pre && pre.id ? pre : null);
  const presetBpm = preset ? preset.bpm : ((presets || []).find(p => p.id === pid) || {}).bpm;
  const sp = spaceOf(spaces, song.band);
  const bands = spaces.filter(x => x.kind === 'band');
  // les blocs COMMUTABLES du preset : ce que l'éditeur propose d'allumer par partie. Plats, tous
  // royaumes confondus — une partie ne sait pas dans quelle lane vit son delay.
  const footBlocks = !preset ? [] : [
    ...((preset.lanes || []).flatMap(L => {
      const c = L.chain || {};
      return [...(c.pre || []), ...(c.post || []), ...((c.split || {}).branches || []).flatMap(b => b.blocks || [])];
    })),
    ...(((preset.config || {}).gen || {}).blocks || []),
  ].filter(b => b && b.id && b.type);
  // ── CE QUI APPARTIENT AU PRESET (docs/arrangement.md §4 bis) : le SWITCH et la règle d'avance. La chanson
  // ne les porte pas — `merge_arrangement` prend ceux du preset. Les boutons « foot » et « Bars | Foot » de
  // cette page écrivaient donc dans le vide, ou rien du tout (`onFoot` manquait : 2026-10-07). On écrit le
  // PRESET, par le chemin des autres pages (fichier + brouillon du Designer).
  const arrOfPreset = d => ((((d || {}).config || {}).arr || {}).blocks || []).find(b => b && b.type === 'arrangement');
  const presetArr = async mut => {
    if (!preset) return;
    const m = d => {
      d.config = d.config || {};
      d.config.arr = d.config.arr || { blocks: [] };
      d.config.arr.blocks = d.config.arr.blocks || [];
      let b = arrOfPreset(d);
      if (!b) { b = { type: 'arrangement', id: 'arrangement', params: { advance: 'bars', sections: [] }, bypass: false };
        d.config.arr.blocks.push(b); }
      mut(b);
    };
    const doc = structuredClone(preset);
    m(doc);
    const r = await savePresetEverywhere(doc, m);
    if (r && r.error) flash('✗ preset not saved: ' + r.error);
    else setPre(doc);
  };
  const onFoot = n => presetArr(b => { if (n == null) delete b.foot; else b.foot = n; });
  // « Add » du Sample absent (arrangement-controls §10.3) : il dit sa PORTÉE avant d'agir — ajouter un bloc
  // au preset touche toutes ses chansons.
  const onAddSample = async () => {
    if (!preset) return;
    const n = ((rep || {}).songs || []).filter(x => ((x.sheet || {}).preset) === preset.id).length;
    if (!window.confirm(`Add a Sample block to the preset « ${preset.name || preset.id} »? It is used by ${n} song${n === 1 ? '' : 's'} — the sampler is added for all of them (each song still decides whether it fires).`)) return;
    const mut = d => {
      d.config = d.config || {};
      d.config.gen = d.config.gen || { blocks: [], out: '1-2' };
      d.config.gen.blocks = d.config.gen.blocks || [];
      if (!d.config.gen.blocks.some(b => b && b.type === 'sample'))
        d.config.gen.blocks.push({ type: 'sample', id: 'sample-' + Math.random().toString(36).slice(2, 6), params: {} });
    };
    const doc = structuredClone(preset);
    mut(doc);
    const r = await savePresetEverywhere(doc, mut);
    if (r && r.error) flash('✗ preset not saved: ' + r.error);
    else { setPre(doc); flash('✓ Sample added to « ' + (preset.name || preset.id) + ' »'); }
  };
  const pArr = arrOfPreset(preset) || {};
  // le bloc tel que le pied le joue : les parties et l'automation de la chanson, le switch et l'avance du preset
  const arrShown = { ...arrNow, foot: pArr.foot,
    params: { ...(arrNow.params || {}), ...((pArr.params || {}).advance ? { advance: pArr.params.advance } : {}) } };
  const takenSwitches = !preset ? [] : [
    ...footBlocks,
    ...((((preset.config || {}).rec || {}).blocks) || []),
  ].filter(b => b && b.foot && b.type !== 'arrangement').map(b => b.foot);
  const give = async band => {
    if (!window.confirm(`Give « ${song.title} » to ${band.name}? It leaves your personal space — same song, it just changes hands.`)) return;
    const r = await api('/api/song-transfer/' + encodeURIComponent(sid), { band: band.id });
    if (r && r.error) flash('✗ ' + r.error); else { flash('✓ given to ' + band.name); bump(n => n + 1); }
  };
  const addTo = async sl => {
    setAddOpen(false);
    const r = await api('/api/setlists/' + encodeURIComponent(sl.id) + '/songs', { ids: [sid] });
    const sk = ((r || {}).skipped || [])[0];
    if (r && r.error) flash('✗ ' + r.error);
    else if (sk) flash(sk.why === 'already in this setlist' ? 'already in ' + sl.name : '✗ ' + sk.why);
    else { flash('✓ added to ' + sl.name); bump(n => n + 1); }
  };
  // STEMS : lier un morceau du catalogue golem.fm (jamais un fichier importé, §9.5). Une reprise sans
  // référence de catalogue la reçoit au passage ; le téléchargement part s'il manque.
  const pickStems = async x => {
    setStems(false);
    if (!x) { await save('backing', null); flash('stems removed'); return; }
    const r = await save('backing', x.slug);
    if (r && r.error) return;
    if (!song.song_slug) await save('song_slug', x.slug);
    if (!x.cached) { await api('/api/backing/dl', { slug: x.slug }); flash('☁ stems downloading…'); }
    else flash('✓ stems linked');
  };

  return html`<div class="sg-page">
    <div class="sg-head" data-doc="song.head">
      <span class="ttl">${esc(song.title || sid)}</span>
      ${song.artist ? html`<span class="art">${esc(song.artist)}</span>` : ''}
      <span class=${cls('tb-seg sg-kindseg', !song.kind && 'warn')} data-doc="song.kind" title="cover or original — golem.fm needs it: a cover's audio, tab and lyrics are never shared with anyone">
        ${[['cover', 'Cover'], ['original', 'Original']].map(([k, lb]) => html`<button class=${cls(song.kind === k && 'on')}
          onClick=${() => song.kind !== k && save('kind', k)}>${lb}</button>`)}</span>
      ${song.born === 'rack' ? html`<span class="chip sg-born" title="created on this rack">◆ born here</span>` : ''}
      ${syncChip((data || {}).sync, song.rev)}
      <span class="grow"></span>
      ${msg ? html`<span class="chip">${msg}</span>` : ''}
      ${sets.length ? html`<span class="chip pk" data-doc="song.setlists">in ${sets.length} setlist${sets.length > 1 ? 's' : ''}</span>` : ''}
    </div>
    ${/* L'ESPACE de la chanson, et le TRANSFERT (§9.6) : une chanson perso se DONNE à un groupe — même
          id, pas de copie. Sur golem.fm, une setlist de groupe ne joue que les chansons de ce groupe. */''}
    ${sp ? html`<div class="sg-head2"><span>◇ ${esc(spaceLabel(sp))}</span>
      ${sp.kind === 'personal' ? bands.map(b => html`<button class="chip sg-give" title="a band setlist on golem.fm only plays songs of that band"
        onClick=${() => give(b)}>Give to ${esc(b.name)}</button>`) : ''}</div>` : ''}

    <div class="sg-fields" data-doc="song.sheet">
      <label class="sg-f sg-pick sg-w2"><span class="k">Preset</span>
        <select class="v" onChange=${e => save('preset', e.target.value || null)}>
          <option value="" selected=${!pid}>— none yet —</option>
          ${(presets || []).map(p => html`<option value=${p.id} selected=${p.id === pid}>${esc(p.name || p.id)}</option>`)}
          ${pid && !(presets || []).some(p => p.id === pid) ? html`<option value=${pid} selected>${esc(pid)} (not on this rack)</option>` : ''}
        </select></label>
      <label class="sg-f"><span class="k">Tempo${presetBpm && sh.bpm && sh.bpm !== presetBpm ? html` <em class="sg-ovr">preset ${presetBpm}</em>` : ''}</span>
        <input class="v" type="number" min="20" max="400" value=${sh.bpm == null ? '' : sh.bpm}
          placeholder=${presetBpm ? presetBpm + ' (preset)' : '—'}
          title="empty = the preset's tempo"
          onChange=${e => { const raw = e.target.value.trim(); save('bpm', raw === '' ? null : Number(raw)); }} /></label>
      <label class="sg-f sg-pick"><span class="k">Tuning</span>
        <select class="v" onChange=${e => save('tuning', e.target.value || null)}>
          <option value="" selected=${!sh.tuning}>—</option>
          ${TUNINGS.map(t => html`<option value=${t} selected=${sh.tuning === t}>${t}</option>`)}
          ${sh.tuning && !TUNINGS.includes(sh.tuning) ? html`<option value=${sh.tuning} selected>${esc(sh.tuning)}</option>` : ''}
        </select></label>
      <label class="sg-f"><span class="k">Capo</span>
        <input class="v" type="number" min="0" max="12" value=${sh.capo == null ? '' : sh.capo} placeholder="—"
          onChange=${e => { const raw = e.target.value.trim(); save('capo', raw === '' ? null : Number(raw)); }} /></label>
      ${/* « Stems » est devenu « File » (lot 5, maquette mockups/golem-files.html) : ce que porte le .golem. Le lien
            vers un morceau du catalogue golem.fm (StemsSheet) reste, depuis le panneau. */''}
      ${(() => { const fl = fileLine((((rep || {}).songs || []).find(x => x.id === song.id) || {}).file);
        return html`<button class=${cls('sg-f', 'sg-stems', 'sg-w2', 'sg-file-' + fl.cls)} data-doc="song.file" title="what this song's .golem carries"
          onClick=${() => setFiles(true)}>
          <span class="k">File</span>
          <span class="v">${fl.ic} ${fl.txt}${fl.sub ? html` <small>${esc(fl.sub)}</small>` : ''}</span></button>`; })()}
      <label class="sg-f"><span class="k">Note</span>
        <input class="v" maxlength="140" value=${sh.note || ''} placeholder="—"
          onChange=${e => save('note', e.target.value.trim() || null)} /></label>
    </div>

    ${/* L'ARRANGEMENT EST LE CŒUR DE LA PAGE (2026-09-20) : il prend la hauteur restante,
          pas un encart en bas d'une fiche. Et c'est le composant du Designer, pas une copie. */''}
    <div class="sg-arr" data-doc="song.arrangement">
      <div class="sg-arr-body">
        <${ArrangementPage} rig=${rig} preset=${preset} bpm=${sh.bpm || (preset || {}).bpm || 120}
          scenes=${(preset || {}).scenes || []} lanes=${preset ? arrangementLanes(preset, fx) : []}
          entries=${preset ? arrangementEntries(preset, fx) : []} inputmap=${imap}
          block=${arrShown} footBlocks=${footBlocks} onParam=${onParam} onFoot=${onFoot} onBypass=${onBypass}
          takenSwitches=${takenSwitches} onLinkStems=${() => setStems(true)} onAddSample=${onAddSample}
          barMap=${barMap}
          ${/* la backing CHARGÉE est celle de la chanson si sa clé est le slug de la fiche OU, depuis le lot 1.5, l'id de
                la chanson (ses stems dans son .golem) — comparer au seul slug disait « stems not on the rack yet » à tort */''}
          backingSec=${(() => { const bk = ((rig || {}).state || {}).backing || {};
            const mine = bk.slug && (bk.slug === sh.backing || bk.slug === song.id
              || (bk.songs || []).some(x => x.slug === bk.slug && x.from_slug && x.from_slug === sh.backing));
            return sh.backing && mine ? bk.len || 0 : 0; })()}
          backingLinked=${!!sh.backing}
          modeOk=${(((rig || {}).state || {}).mode || {}).services ? !!((((rig || {}).state || {}).mode || {}).services || {}).arrangement : undefined}
          modeName=${(((rig || {}).state || {}).mode || {}).name}
          onPlay=${async () => { await flushArr(); const r = await post('/api/arrangement', { op: 'start', song: song.id }).catch(e => ({ error: String(e) }));
            if (r && r.error) setSaid('✗ ' + r.error); }}
          onStop=${() => post('/api/arrangement', { op: 'stop' }).catch(() => {})} />
      </div>
      <div class="sg-arr-ft" data-doc="song.footer">
        <span>Everything on this page <b>is the song</b> — every setlist that plays it follows.</span>
        <span class="grow"></span>
        ${(() => { const st0 = ((rig || {}).state || {}).startup, onFoot = sets.find(x => x.active && x.line);
          // une chanson s'ouvre au démarrage sur SA ligne de la setlist au pied (2026-10-13 — option a) : ni
          // ligne là, ni ouverture — le bouton le dit au lieu de deviner une autre setlist
          if (!onFoot) return html`<button class="chip" disabled title="open at startup: this song is not in the setlist on the foot — add it there first">⌂ startup</button>`;
          const key = { kind: 'song', setlist: onFoot.id, line: onFoot.line }, e = startupEntry(st0, key);
          return html`<button class=${cls('chip edit-only', e.remove && 'pk')} title=${e.remove ? 'opens at startup — tap to remove' : 'open this song at startup, on its line of « ' + (onFoot.name || onFoot.id) + ' »' + (e.small ? ' · ' + e.small : '')}
            onClick=${() => e.remove ? del('/api/startup/home').catch(() => {}) : post('/api/startup/home', { ...key, name: song.title || song.id }).catch(() => {})}>${e.remove ? '⌂ startup ✓' : '⌂ Open at startup'}</button>`; })()}
        ${sets.map(x => html`<button class="chip pk" title="open this setlist"
          onClick=${() => go('songs/setlists/' + x.id)}>${esc(x.name || x.id)} · #${x.slot}</button>`)}
      </div>
    </div>
    ${addOpen ? html`<${AddToSetlist} have=${sets} onPick=${addTo} onClose=${() => setAddOpen(false)} />` : ''}
    ${stems ? html`<${StemsSheet} song=${song} onClose=${() => setStems(false)} onPick=${pickStems} />` : ''}
    ${files ? html`<${FileSheet} song=${song} onClose=${() => setFiles(false)} onChanged=${() => bump(n => n + 1)}
        onLink=${() => { setFiles(false); setStems(true); }} />` : ''}
  </div>`;
}

// le menu « ＋ Add to a setlist ▾ » : les setlists du rack, celles qui la jouent déjà grisées
function AddToSetlist({ have, onPick, onClose }) {
  const { data } = useAsync(() => fetch('/api/setlists').then(r => r.json()).catch(() => null), []);
  const already = new Set((have || []).map(x => x.id));
  // une bank de SONS ne prend pas de morceaux (patch-as-preset §11) : elle n'est pas proposée ici
  const list = ((data || {}).setlists || []).filter(sl => sl.kind !== 'sounds');
  return html`<div class="picker-scrim" onClick=${onClose}></div>
    <div class="save-pop sg-addpop" onClick=${e => e.stopPropagation()}>
      ${!data ? html`<span class="muted">loading…</span>`
        : !list.length ? html`<span class="muted">No setlist yet — create one in Setlists.</span>`
        : list.map(sl => html`<button class="row-btn sm" disabled=${already.has(sl.id)} onClick=${() => onPick(sl)}>
            ${esc(sl.name || sl.id)}<small class="muted">${already.has(sl.id) ? 'already in it'
              : (sl.lines || []).length + ' song' + ((sl.lines || []).length === 1 ? '' : 's')}</small></button>`)}
    </div>`;
}

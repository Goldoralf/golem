// SPDX-License-Identifier: GPL-3.0-or-later
// LA CHANSON CHARGÉE DANS LE DESIGNER (docs/designer-song.md, maquette validée le 2026-10-18).
//
// Un preset sert plusieurs chansons et ne les connaît pas : ce qui change d'une chanson à l'autre (tempo, mesure, click
// au départ, samples, stems, arrangement) appartient à la CHANSON. Le Designer travaille donc dans le contexte de la
// chanson chargée : une barre la nomme (Load / ✕), et les tiroirs éditent ses valeurs à côté de celles du preset.
// Une valeur « for this song » s'écrit dans la FICHE de la chanson (POST /api/song/<id>) — toutes ses setlists suivent.
import { html, useState, useEffect, useRef, post, cls, esc, bankNo } from './lib.js';

const art = (sid, k) => '/api/backing/asset/' + encodeURIComponent(sid) + '/' + k;

// les surcharges de blocs d'une fiche, un bloc modifié : `patch` fusionné sur l'existant ; une clé à null est RETIRÉE,
// un bloc vidé disparaît (une fiche sans surcharge n'a pas de `blocks`)
export function sheetBlocks(sheet, blockId, patch) {
  const all = { ...(((sheet || {}).blocks) || {}) };
  const cur = { ...(all[blockId] || {}) };
  const params = { ...(cur.params || {}) };
  Object.entries((patch && patch.params) || {}).forEach(([k, v]) => { if (v == null) delete params[k]; else params[k] = v; });
  if (Object.keys(params).length) cur.params = params; else delete cur.params;
  if (patch && 'bypass' in patch) { if (patch.bypass == null) delete cur.bypass; else cur.bypass = !!patch.bypass; }
  if (Object.keys(cur).length) all[blockId] = cur; else delete all[blockId];
  return all;
}

// LE CONTEXTE : la chanson chargée si elle joue CE preset, sa fiche, les chansons qui l'utilisent, et les gestes
export function useSongCtx(p, rig) {
  const st = ((rig || {}).state || {}).song || null;
  const sid = st && st.preset === (p || {}).id ? (st.band_song || null) : null;
  const lineId = st && st.preset === (p || {}).id ? (st.line || null) : null;
  const [doc, setDoc] = useState(null);
  const [used, setUsed] = useState(null);
  const [busy, setBusy] = useState(null);
  const [said, setSaid] = useState('');
  const [tick, setTick] = useState(0);
  const [utick, setUtick] = useState(0);         // « les chansons qui jouent ce preset », relues après un lien ou une création
  useEffect(() => {
    let live = true;
    if (!sid) { setDoc(null); return undefined; }
    fetch('/api/song/' + encodeURIComponent(sid)).then(r => r.json()).then(r => live && setDoc((r || {}).song || null)).catch(() => null);
    return () => { live = false; };
  }, [sid, tick]);
  useEffect(() => {
    let live = true;
    if (!(p || {}).id) return undefined;
    post('/api/backing/drawer', { preset: p }).then(r => live && setUsed((r || {}).used_by || null)).catch(() => null);
    return () => { live = false; };
  }, [(p || {}).id, utick]);
  const err = e => ({ error: (e && e.body && e.body.error) || String(e) });
  // UNE SEULE CHANSON JOUE CE PRESET → ELLE SE CHARGE (2026-10-24 : « ça fera gagner du temps à tout le
  // monde »). Seulement quand le rig joue DÉJÀ ce preset — sinon `select` le rappellerait (reconstruction du rig, et
  // l'essai en cours perdu). Une fois par preset ouvert ; et un ✕ de l'utilisateur est respecté tant qu'on y reste.
  const autoDone = useRef(null);
  const unloadedFor = useRef(null);
  const rigPid = ((rig || {}).state || {}).preset_id;
  useEffect(() => {
    const pid = (p || {}).id;
    if (unloadedFor.current && unloadedFor.current !== pid) unloadedFor.current = null;
    const one = ((used || {}).songs || []).length === 1 ? used.songs[0].song : null;
    if (!pid || sid || !one || rigPid !== pid || autoDone.current === pid || unloadedFor.current === pid) return;
    if (['sandbox-try', 'nouveau-preset'].includes(pid) || String(pid).startsWith('patch:')) return;
    autoDone.current = pid;
    post('/api/arrangement', { op: 'select', song: one }).catch(() => null);
  }, [(p || {}).id, used, rigPid, sid]);
  const act = async (body, key) => {
    setBusy(key); setSaid('');
    const r = await post('/api/arrangement', body).catch(err);
    setBusy(null);
    if (r && r.error) setSaid('✗ ' + r.error);
    return r;
  };
  // DONNER UNE CHANSON À CE PRESET (2026-10-24) : le panneau Arrangement n'offrait qu'un gros « ＋ Add … to « Factory
  // Golem » » — une LIGNE libre ajoutée à la setlist active (une bank de plus au pédalier, une setlist d'usine modifiée),
  // pas une chanson : les parties ne pouvaient toujours pas s'écrire. Une chanson du répertoire porte son preset
  // (`sheet.preset`) : on en relie une, ou on en crée une. La setlist se choisit ensuite, dans Songs.
  const draft = !(p || {}).id || ['sandbox-try', 'nouveau-preset'].includes(p.id) || String(p.id).startsWith('patch:');
  const songAct = async (key, fn) => {
    if (draft) { setSaid('✗ save the preset first — a draft cannot be a song\'s preset'); return null; }
    setBusy(key); setSaid('');
    const r = await fn().catch(err);
    setBusy(null);
    if (r && r.error) setSaid('✗ ' + r.error); else setUtick(t => t + 1);
    return r;
  };
  return {
    sid, lineId, doc, sheet: (doc || {}).sheet || {}, used, busy, said, draft,
    linkSong: songId => songAct('link', () => post('/api/song/' + encodeURIComponent(songId), { preset: p.id })),
    newSong: (title, kind) => songAct('new', () => post('/api/songs', { title, kind, preset: p.id, ...(p.bpm ? { bpm: p.bpm } : {}) })),
    title: (doc && doc.title) || (st && st.title) || '',
    load: id => act({ op: 'select', song: id }, id),
    unload: () => { unloadedFor.current = (p || {}).id; return act({ op: 'unselect' }, '-'); },
    // une valeur pour CETTE chanson : écrite dans sa fiche, puis la chanson est ré-armée (jamais relancée)
    saveSheet: async fields => {
      if (!sid) return null;
      const r = await post('/api/song/' + encodeURIComponent(sid), fields).catch(err);
      if (r && r.error) { setSaid('✗ ' + r.error); return r; }
      if (r && r.song) setDoc(r.song); else setTick(t => t + 1);
      await post('/api/arrangement', { op: 'select', song: sid }).catch(() => null);
      return r;
    },
  };
}

// où vient la chanson chargée : « Covers #02 » quand c'est une ligne de setlist
function whereOf(ctx) {
  const s = ((ctx.used || {}).songs || []).find(x => x.song === ctx.sid);
  const ln = s && ctx.lineId ? (s.lines || []).find(l => l.line === ctx.lineId) : null;
  return ln ? (ln.name || ln.setlist) + ' #' + bankNo(ln.bank) : '';
}

// LA BARRE « SONG » (§2) — sur la ligne des lanes, avant le BPM
export function SongBar({ ctx }) {
  // {top, right} : le menu est en position FIXE — la ligne des lanes défile (overflow:auto) et l'aurait coupé
  const [open, setOpen] = useState(null);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const off = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(null); };
    document.addEventListener('pointerdown', off);
    return () => document.removeEventListener('pointerdown', off);
  }, [open]);
  const songs = (ctx.used || {}).songs || [];
  if (ctx.sid) {
    const where = whereOf(ctx);
    return html`<span class="dsong" data-doc="designer.song" title=${'the song loaded: its backing, tempo and arrangement play with this preset' + (where ? ' — from ' + where : '')}>
      <img class="dsong-cv" src=${art(ctx.sid, 'cover')} alt="" onError=${e => { e.target.style.visibility = 'hidden'; }} />
      <b>♪ ${esc(ctx.title || 'song')}</b>${where ? html`<small>· ${esc(where)}</small>` : ''}
      <button class="dsong-x" disabled=${!!ctx.busy} title="unload — the preset stays, on its own (no backing, no arrangement)"
        onClick=${() => ctx.unload()}>${ctx.busy === '-' ? '…' : '✕'}</button></span>`;
  }
  return html`<span class="dsong-wrap" ref=${ref}>
    <button class="dsong empty" data-doc="designer.song" onClick=${e => { const r = e.currentTarget.getBoundingClientRect();
      setOpen(o => o ? null : { top: Math.round(r.bottom + 6), right: Math.max(8, Math.round(window.innerWidth - r.right)) }); }}>♪ <b>Load a song ▾</b></button>
    ${open ? html`<div class="dsong-menu" style=${'top:' + open.top + 'px;right:' + open.right + 'px'}>
      <span class="dsong-lbl">Songs that use this preset</span>
      ${songs.map(s => html`<div class="dsong-mi">
        <img src=${art(s.song, 'cover')} alt="" onError=${e => { e.target.style.visibility = 'hidden'; }} />
        <div><b>${esc(s.title || s.song)}</b><small>${esc([s.artist, ...(s.lines || []).map(l => (l.name || l.setlist) + ' #' + bankNo(l.bank))].filter(Boolean).join(' · '))}</small></div>
        <button class="dsong-ld" disabled=${!!ctx.busy} onClick=${async () => { const r = await ctx.load(s.song); if (!(r && r.error)) setOpen(null); }}>
          ${ctx.busy === s.song ? '…' : 'Load'}</button></div>`)}
      ${!songs.length ? html`<span class="dsong-note">No song uses this preset yet.</span>` : ''}
      <span class="dsong-note">A song picks its preset on its page (Songs). Loading does not start it.</span>
      ${ctx.said ? html`<span class="bad">${esc(ctx.said)}</span>` : ''}
    </div>` : ''}
  </span>`;
}

// la ligne de setlist chargée surcharge-t-elle ce champ ce soir ? (`line_overrides`, songs.md §9.7)
function tonight(ctx, setlists, key) {
  if (!ctx.lineId) return null;
  for (const sl of ((setlists || {}).setlists || [])) {
    const i = (sl.lines || []).findIndex(l => l.id === ctx.lineId);
    if (i >= 0) {
      const l = sl.lines[i];
      return (l.line_overrides || []).includes(key) ? { where: (sl.name || sl.id) + ' #' + bankNo(i), line: l } : null;
    }
  }
  return null;
}

// UNE LIGNE SOUS LES TIROIRS (§4) : avec une chanson, où elle joue aussi ; sans, quelles chansons ont leurs valeurs
export function PerSongNote({ ctx }) {
  const songs = (ctx.used || {}).songs || [];
  if (ctx.sid) {
    const s = songs.find(x => x.song === ctx.sid);
    const others = ((s || {}).lines || []).filter(l => l.line !== ctx.lineId).map(l => (l.name || l.setlist) + ' #' + bankNo(l.bank));
    return html`<div class="dsong-also">${others.length
      ? html`<b>${esc(ctx.title)}</b> is also in ${esc(others.join(', '))} — the same song, the same values. Edited here: saved in the song.`
      : html`Values for <b>${esc(ctx.title)}</b> are saved in the song — every setlist that plays it follows.`}</div>`;
  }
  if (!songs.length) return '';
  return html`<div class="dsong-also">Set per song in: ${songs.map((s, i) => html`${i ? ', ' : ''}<b>${esc(s.title || s.song)}</b>`)} — load it to see its values
    ${songs.slice(0, 2).map(s => html`<button class="mini" disabled=${!!ctx.busy} onClick=${() => ctx.load(s.song)}>${ctx.busy === s.song ? '…' : '▶ Load ' + esc(s.title || s.song)}</button>`)}</div>`;
}

// LE CLICK EN DEUX COLONNES (§4) : ce preset, toutes les chansons | cette chanson seulement
export function ClickSongCols({ ctx, block, presetBpm, setlists }) {
  const [glob, setGlob] = useState(null);
  const [setSig, setSetSig] = useState(false);
  useEffect(() => { fetch('/api/click').then(r => r.json()).then(setGlob).catch(() => null); }, []);
  const g = glob || {};
  const sh = ctx.sheet || {};
  const ov = ((sh.blocks || {})[block.id]) || {};
  const op = ov.params || {};
  const pBeats = g.beats || 4, pDen = g.den || 4;
  const sBeats = op.beats, sDen = op.den;
  const pOn = !block.bypass;
  const sOn = ov.bypass != null ? !ov.bypass : null;
  const saveBlk = patch => ctx.saveSheet({ blocks: sheetBlocks(sh, block.id, patch) });
  const bpmT = tonight(ctx, setlists, 'bpm');
  const blkT = tonight(ctx, setlists, 'blocks');
  const sigOwn = sBeats != null || sDen != null || setSig;
  const reset = fn => html`<button class="dsc-rst" onClick=${fn}>↺ use the preset's</button>`;
  return html`<div class="dsc">
    <div class="dsc-h"></div><div class="dsc-h">This preset · every song</div><div class="dsc-h sg">♪ ${esc(ctx.title)} · this song only</div>

    <div class="dsc-k">Tempo</div><div><b>${presetBpm || 120}</b><i>the preset's BPM</i></div>
    <div class="sg">
      <span class="dsc-st"><button onClick=${() => ctx.saveSheet({ bpm: Math.max(20, (sh.bpm || presetBpm || 120) - 1) })}>−</button>
        <b>${sh.bpm || presetBpm || 120}</b>
        <button onClick=${() => ctx.saveSheet({ bpm: Math.min(300, (sh.bpm || presetBpm || 120) + 1) })}>+</button></span>
      ${sh.bpm ? html`<em>the song's tempo</em>${reset(() => ctx.saveSheet({ bpm: null }))}` : html`<i>same as the preset</i>`}
      ${bpmT ? html`<em class="dsc-tn">${esc(bpmT.where)} plays ${bpmT.line.bpm || '?'} tonight</em>` : ''}</div>

    <div class="dsc-k">Time signature</div><div><b>${pBeats}/${pDen}</b><i>global</i></div>
    <div class="sg">${sigOwn ? html`
      <span class="dsc-chips">${[2, 3, 4, 5, 6, 7].map(n => html`<button class=${cls((sBeats || pBeats) === n && 'on')}
        onClick=${() => saveBlk({ params: { beats: n } })}>${n}</button>`)}<span>/</span>${[4, 8].map(n => html`<button class=${cls((sDen || pDen) === n && 'on')}
        onClick=${() => saveBlk({ params: { den: n } })}>${n}</button>`)}</span>
      ${sBeats != null || sDen != null ? reset(() => { setSetSig(false); saveBlk({ params: { beats: null, den: null } }); }) : ''}`
      : html`<i>same as the preset</i><button class="mini" onClick=${() => setSetSig(true)}>Set for this song</button>`}</div>

    <div class="dsc-k">On at start</div><div><b>${pOn ? 'on' : 'off'}</b></div>
    <div class="sg">${sOn == null ? html`<i>same as the preset</i>
        <button class="mini" onClick=${() => saveBlk({ bypass: pOn })}>${pOn ? 'Off' : 'On'} for this song</button>`
      : html`<b class=${cls(sOn && 'dsc-on')}>${sOn ? 'on' : 'off'}</b>${reset(() => saveBlk({ bypass: null }))}`}
      ${blkT ? html`<em class="dsc-tn">${esc(blkT.where)} has its own blocks tonight</em>` : ''}</div>
  </div>
  ${ctx.said ? html`<span class="bad">${esc(ctx.said)}</span>` : ''}`;
}

// LE SÉLECTEUR DE COUCHE (§4, Sample) : ce que la liste édite — le preset, ou la chanson chargée
export function SongLayer({ ctx, layer, onLayer, own }) {
  return html`<div class="dsong-layer">
    <button class=${cls(layer === 'preset' && 'on')} onClick=${() => onLayer('preset')}>This preset</button>
    <button class=${cls('sg', layer === 'song' && 'on')} onClick=${() => onLayer('song')}>♪ ${esc(ctx.title)} · this song</button>
    <span class="muted">${layer === 'song' ? (own ? 'the song has its own list' : 'the preset\'s list — a change makes one for the song') : 'every song without its own list'}</span>
  </div>`;
}

// L'ENCADRÉ DE LA CHANSON CHARGÉE — le même dans les tiroirs Backing Track et Arrangement (harmonisés le 2026-10-18) :
// pochette, « The song loaded now · <ce qu'elle apporte> », artiste, pastilles, d'où elle vient, Open the song ›,
// ✕ Unload ; sans chanson, ce qui manque et un ▶ Load par chanson qui utilise ce preset.
//   song  : {id, title, artist, cover, photo, from: {name, bank}} ou null ;  chips : [{t, cls}]
export function SongCard({ song, label, chips, emptyTitle, emptyText, songs, busy, said, onLoad, onUnload, onOpen, extra }) {
  if (song) {
    return html`<div class="bkd-song">
      <span class="bkd-cover">♪${song.cover ? html`<img src=${song.cover} alt="" onError=${e => { e.target.style.display = 'none'; }} />` : ''}</span>
      <div class="bkd-st"><span class="bkd-lbl">${label}</span>
        <b>${esc(song.title || '')}</b>
        <span class="bkd-artist">${song.photo ? html`<img src=${song.photo} alt="" onError=${e => { e.target.style.display = 'none'; }} />` : ''}
          ${esc(song.artist || '')}${(chips || []).filter(Boolean).map(c => html`<span class=${cls('bkd-chip', c.cls)}>${c.t}</span>`)}</span></div>
      <span class="grow"></span>
      <div class="bkd-side">${song.from ? html`from <span class="bkd-chip sg">${esc(song.from.name || '')} #${bankNo(song.from.bank ?? 0)}</span>` : ''}
        ${song.id && onOpen ? html`<a onClick=${onOpen}>Open the song ›</a>` : ''}
        ${onUnload ? html`<button class="mini bkd-unload" disabled=${!!busy} title="the preset stays, on its own — no song, no backing, no arrangement"
          onClick=${onUnload}>${busy === '-' ? '…' : '✕ Unload'}</button>` : ''}</div>
    </div>`;
  }
  const list = songs || [];
  return html`<div class="bkd-song none"><span class="bkd-cover">♪</span>
    <div class="bkd-st"><b>${emptyTitle}</b>
      <span class="muted">${emptyText || (list.length ? 'Load a song that uses this preset — on its own, a preset plays none.'
        : html`No song uses this preset yet: a song picks its preset on its page (<b>Songs</b>).`)}</span>
      ${list.length && onLoad ? html`<div class="bkd-load">${list.slice(0, 4).map(x => html`
        <button class="mini primary" disabled=${!!busy} onClick=${() => onLoad(x.song)}>
          ${busy === x.song ? '⏳ loading…' : '▶ Load « ' + (x.title || x.song) + ' »'}</button>`)}</div>` : ''}
      ${extra || ''}
      ${said ? html`<span class="bad">✗ ${esc(String(said).replace(/^✗ /, ''))}</span>` : ''}</div></div>`;
}

// la chanson chargée du contexte, à la forme de SongCard
export function songOfCtx(ctx) {
  if (!ctx || !ctx.sid) return null;
  const s = ((ctx.used || {}).songs || []).find(x => x.song === ctx.sid);
  const ln = s && ctx.lineId ? (s.lines || []).find(l => l.line === ctx.lineId) : null;
  return { id: ctx.sid, title: ctx.title, artist: (ctx.doc || {}).artist || (s || {}).artist,
           cover: art(ctx.sid, 'cover'), photo: art(ctx.sid, 'photo'), from: ln ? { name: ln.name || ln.setlist, bank: ln.bank } : null };
}

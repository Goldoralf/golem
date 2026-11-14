// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Grooves (hub Library ▸ Drums) — les patterns MIDI de batterie que le bloc Drum Machine joue (params
// patterns / fills). docs/drums-library.md, maquette validée le 2026-11-14 : des LIGNES fines (le motif est le
// contenu, il lui faut la largeur), « Yours » puis « Ships with golem », des filtres par signature, longueur et usage,
// et une FICHE : le motif en grand, une ligne par pièce ; ce que dit le fichier (signature, longueur, tempo, joué ou
// sur la grille) ; l'usage ; les notes qu'aucun kit ne joue, à associer à une pièce ; l'écoute sur un kit ; « Add to
// my drum machine » (le Designer, son bloc Drum Machine, le groove ajouté). Import de .mid General MIDI, multi.
import { useFactoryShow, keepFactory } from './factory-show.js';
import { html, useState, useEffect, useAsync, useRef, cls, esc, setTopAction, setSubToolbar, useRev, saveClick, openInDesigner, post } from './lib.js';
import { useGenreLabel } from './genres.js';
import { useClip, ClipBar } from './keys-ui.js';

// l'ordre des lignes, de haut en bas : cymbales, charleston, caisse claire, toms, grosse caisse (une note inconnue en haut)
const ORDER = [49, 57, 52, 55, 51, 59, 53, 46, 42, 44, 54, 56, 39, 37, 38, 40, 50, 48, 47, 45, 43, 41, 36, 35];
const rank = n => { const i = ORDER.indexOf(n); return i < 0 ? -1 : i; };
const USES = [['loop', 'Loop'], ['oneshot', 'One-shot'], ['fill', 'Fill'], ['intro', 'Intro'], ['end', 'End']];
const USE_NAME = Object.fromEntries(USES);

/** les frappes d'un groove, chargées quand la ligne entre à l'écran */
function useNotes(file, lazy) {
  const [d, setD] = useState(null);
  const box = useRef(null), asked = useRef(false);
  useEffect(() => {
    const go = () => { asked.current = true;
      fetch('/api/groove-notes?file=' + encodeURIComponent(file)).then(r => r.json()).then(setD).catch(() => setD({ notes: [] })); };
    if (!lazy) { go(); return; }
    const el = box.current;
    if (!el || asked.current) return;
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting) && !asked.current) { io.disconnect(); go(); } }, { rootMargin: '250px' });
    io.observe(el);
    return () => io.disconnect();
  }, [file]);
  return [d, box];
}

/** le motif : une ligne par pièce, toutes les mesures ; `unknown` en orange */
function Lanes({ d, beats, bar, unknown, names, big }) {
  const notes = (d && d.notes) || [], ppq = (d && d.ppq) || 480;
  const span = Math.max(1, beats || (d && d.beats) || 1);
  const pitches = [...new Set(notes.map(n => n.n))].sort((a, b) => rank(a) - rank(b));
  const W = 1000, rh = big ? 26 : 7, H = Math.max(rh, pitches.length * rh);
  return html`<svg class=${cls('gr-lanes', big && 'big')} viewBox=${`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
      aria-label=${pitches.map(p => names[p] || 'note ' + p).join(', ')}>
    ${Array.from({ length: Math.floor(span / (bar || 4)) + 1 }, (_, b) => html`<line class="gr-bar" x1=${b * (bar || 4) / span * W} x2=${b * (bar || 4) / span * W} y1="0" y2=${H} />`)}
    ${notes.map(n => html`<rect class=${unknown.includes(n.n) ? 'gr-hit unk' : 'gr-hit'} x=${(n.t / ppq / span * W).toFixed(1)}
      y=${(pitches.indexOf(n.n) * rh + rh * 0.15).toFixed(1)} width=${big ? 4 : 3} height=${(rh * 0.7).toFixed(1)}
      opacity=${(0.5 + 0.5 * (n.v || 100) / 127).toFixed(2)} />`)}
  </svg>`;
}

function Row({ g, names, onOpen }) {
  const [d, box] = useNotes(g.file, true);
  const bar = { '6/8': 3, '3/4': 3, '12/8': 6 }[g.meter] || 4;
  return html`<button class="gr-row" ref=${box} onClick=${() => onOpen(g)} aria-label=${g.name}>
    <span class="gr-id"><b>${esc(g.name)}</b><small>${g.meter} · ${g.bars} bar${g.bars > 1 ? 's' : ''}${g.file_bpm ? ' · ' + Math.round(g.file_bpm) + ' BPM' : ''}${g.played ? ' · played' : ''}</small></span>
    <span class=${'gr-use u-' + g.use}>${USE_NAME[g.use] || g.use}</span>
    ${g.unknown.length ? html`<span class="gr-unk">${g.unknown.length} note${g.unknown.length > 1 ? 's' : ''} unknown</span>` : ''}
    <span class="gr-strip">${d ? html`<${Lanes} d=${d} beats=${g.bars * bar} bar=${bar} unknown=${g.unknown} names=${names} />` : ''}</span>
    <span class="gr-go" aria-hidden="true">›</span>
  </button>`;
}

export function GroovesPage() {
  const facShow = useFactoryShow();
  const [tick, setTick] = useState(0);
  const libRev = useRev('library_rev');
  const { data } = useAsync(() => fetch('/api/grooves').then(r => r.json()), [tick, libRev]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(null);
  const [q, setQ] = useState('');
  const [genreF, setGenreF] = useState('all');
  const [packF, setPackF] = useState('all');
  const [meter, setMeter] = useState('all');
  const [len, setLen] = useState('all');
  const [use, setUse] = useState('all');
  const [sel, setSel] = useState(null);
  const cl = useClip();
  const fileRef = useRef(null);
  const reload = () => setTick(t => t + 1);
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${() => fileRef.current && fileRef.current.click()} title="import General-MIDI drum patterns (.mid), several at once">+ Import</button></div>`);
    return () => setTopAction(null);
  }, []);
  const importMids = async files => {
    const arr = Array.from(files || []);
    if (!arr.length) return;
    setErr(null); let ok = 0, lastErr = null;
    for (const f of arr) {
      setBusy(`importing ${ok + 1}/${arr.length}…`);
      const r = await fetch('/api/groove/import?name=' + encodeURIComponent(f.name), { method: 'POST', body: f })
        .then(x => x.json()).catch(e => ({ error: String(e) }));
      if (r && r.ok) ok++; else lastErr = (r && r.error) || 'import failed';
    }
    setBusy(null);
    if (lastErr) setErr(arr.length > 1 ? `${ok}/${arr.length} imported · ${lastErr}` : lastErr);
    reload();
  };
  const grooves = (data && data.grooves) || [];
  const names = Object.fromEntries(Object.entries((data && data.pieces) || {}).map(([k, v]) => [+k, v[0].toUpperCase() + v.slice(1)]));
  const genreLabel = useGenreLabel();
  const genres = [...new Set(grooves.map(g => g.genre).filter(Boolean))].sort();
  const packs = [...new Set(grooves.map(g => g.pack).filter(Boolean))].sort();
  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search groove…" onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      ${packs.length ? html`<select class="flt-sel" value=${packF} onChange=${e => setPackF(e.target.value)} title="Pack of origin">
        <option value="all">Pack · all</option>${packs.map(p => html`<option value=${p} selected=${p === packF}>${p}</option>`)}
        <option value="(none)" selected=${packF === '(none)'}>(no pack)</option></select>` : ''}
      ${genres.length ? html`<select class="flt-sel" value=${genreF} onChange=${e => setGenreF(e.target.value)} title="Genre">
        <option value="all">Genre · all</option>${genres.map(g => html`<option value=${g} selected=${g === genreF}>${genreLabel(g)}</option>`)}</select>` : ''}
      ${busy ? html`<span class="syn-busy">${esc(busy)}</span>` : ''}
      ${err ? html`<span class="lib-err" title=${esc(err)}>⚠ ${esc(err)}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [genreF, packF, genres.length, packs.length, busy, err]);
  const lenOf = g => g.bars >= 8 ? '8' : String(g.bars);
  const base = grooves.filter(keepFactory(facShow, 'grooves')).filter(g => (genreF === 'all' || g.genre === genreF)
    && (packF === 'all' || (packF === '(none)' ? !g.pack : g.pack === packF)) && (!q || (g.name || '').toLowerCase().includes(q)));
  const shown = base.filter(g => (meter === 'all' || g.meter === meter) && (len === 'all' || lenOf(g) === len)
    && (use === 'all' || g.use === use || (use === 'intro' && g.use === 'end')));
  const open = grooves.find(g => g.id === sel);
  const input = html`<input ref=${fileRef} type="file" accept=".mid,.midi" multiple style="display:none"
    onChange=${e => { importMids(e.target.files); e.target.value = ''; }} />`;
  if (open) return html`<div class="library tn-page">${input}<${GrooveDetail} g=${open} names=${names} targets=${(data && data.targets) || []}
    cl=${cl} onClose=${() => setSel(null)} onChanged=${reload} onDeleted=${() => { setSel(null); reload(); }} /></div>`;
  const chip = (cur, set, v, lb, n) => html`<button class=${cls('ky-sty', cur === v && 'on')} onClick=${() => set(cur === v && v !== 'all' ? 'all' : v)}>${lb}${n != null ? html` <em>${n}</em>` : ''}</button>`;
  const meters = [...new Set(base.map(g => g.meter))].sort();
  const mine = shown.filter(g => !g.factory), fac = shown.filter(g => g.factory);
  return html`<div class="library tn-page">${input}
    <div class="tn-col ky-col">
      <div class="ky-styles">
        ${chip(meter, setMeter, 'all', 'All', base.length)}
        ${meters.map(m => chip(meter, setMeter, m, m, base.filter(g => g.meter === m).length))}
        <span class="gr-sep"></span>
        ${[['1', '1 bar'], ['2', '2 bars'], ['4', '4'], ['8', '8+']].filter(([v]) => base.some(g => lenOf(g) === v)).map(([v, lb]) => chip(len, setLen, v, lb))}
        <span class="gr-sep"></span>
        ${[['loop', 'Loop'], ['oneshot', 'One-shot'], ['fill', 'Fill'], ['intro', 'Intro · End']].map(([v, lb]) => chip(use, setUse, v, lb))}
      </div>
      <div class="gr-scroll">
        ${mine.length ? html`<h6 class="dk-h">Yours · imported</h6>${mine.map(g => html`<${Row} key=${g.id} g=${g} names=${names} onOpen=${x => setSel(x.id)} />`)}` : ''}
        ${fac.length ? html`<h6 class="dk-h">Ships with golem · ${fac.length}</h6>${fac.map(g => html`<${Row} key=${g.id} g=${g} names=${names} onOpen=${x => setSel(x.id)} />`)}` : ''}
        ${!shown.length ? html`<div class="empty">${grooves.length ? 'No groove matches these filters.' : html`No grooves yet — tap <b>+ Import .mid</b> to add General-MIDI drum patterns (36 kick, 38 snare, 42 hi-hat…). Multi-select works.`}</div>` : ''}
      </div>
      <${ClipBar} cl=${cl} hint="Touch a groove to open it: hear it on a kit, set what it is for, add it to your drum machine." />
    </div></div>`;
}

function GrooveDetail({ g, names, targets, cl, onClose, onChanged, onDeleted }) {
  const [d] = useNotes(g.file, false);
  const { data: kd } = useAsync(() => fetch('/api/drums/kits').then(r => r.json()), []);
  // les batteries ET les kits de pads ; le kit du groove d'abord (son « esprit » : Lo-fi sur les pads Lo-fi), puis les autres
  const kits = ((kd && kd.kits) || []).filter(k => k.available !== false && (k.type !== 'pads' || (k.pads || []).some(p => p.sample)));
  const [kit, setKit] = useState(null);
  const suggested = kits.find(k => k.id === g.kit);
  const [tempo, setTempo] = useState(g.file_bpm && g.file_bpm > 170 ? 'half' : 'file');
  const [hear, setHear] = useState(null);
  const [msg, setMsg] = useState(null);
  const [armDel, setArmDel] = useState(false);
  const [pick, setPick] = useState(null);           // la note inconnue en cours d'association
  const kitId = kit || (suggested && suggested.id) || (kits[0] && kits[0].id);
  const bar = { '6/8': 3, '3/4': 3, '12/8': 6 }[g.meter] || 4;
  const call = async (u, b) => { const r = await post(u, b).catch(e => ({ error: (e.body && e.body.error) || String(e) })); if (r && r.error) setMsg(r.error); return r; };
  const setUse = async u => { const r = await call('/api/groove/' + encodeURIComponent(g.id) + '/use', { use: u }); if (r && r.ok) onChanged(); };
  const remap = async m => { const r = await call('/api/groove/' + encodeURIComponent(g.id) + '/remap', { mapping: m }); if (r && r.ok) { setPick(null); onChanged(); } };
  const play = async () => {
    setHear({ phase: 'render' }); setMsg(null);
    const r = await call('/api/groove/' + encodeURIComponent(g.id) + '/hear', { kit: kitId, tempo });
    if (!r || r.error) return setHear(null);
    const done = st => { setHear(st); if (st.phase === 'ready') cl.play({ sound: 'gok:' + st.key, clip: st.clip, title: g.name,
      phrase: (kits.find(k => k.id === kitId) || {}).name + ' · ' + r.bpm + ' BPM' }); else if (st.error) setMsg(st.error); };
    if (r.phase !== 'render') return done(r);
    const t = setInterval(async () => { const st = await fetch('/api/groove-hear').then(x => x.json()).catch(() => null);
      if (!st || st.key !== r.key || st.phase === 'render') return; clearInterval(t); done(st); }, 800);
  };
  const del = async () => {
    if (!armDel) { setArmDel(true); setTimeout(() => setArmDel(false), 2500); return; }
    await fetch('/api/groove/' + encodeURIComponent(g.id), { method: 'DELETE' }).catch(() => null);
    onDeleted();
  };
  const remapped = Object.entries(g.remap || {});
  const pitches = [...new Set(((d && d.notes) || []).map(n => n.n))].sort((a, b) => rank(a) - rank(b));
  const fileBpm = g.file_bpm ? Math.round(g.file_bpm) : null;
  return html`<div class="tn-col ky-col">
    <div class="gr-head">
      <button class="tn-back gr-back" onClick=${onClose}>‹ Grooves</button>
      <b>${esc(g.name)}</b><span class="muted">${g.factory ? 'ships with golem' : 'yours · imported from a .mid'}${g.pack ? ' · ' + esc(g.pack) : ''}</span>
      <span class="grow"></span>
      <a class="mini" href=${'/api/groove/' + encodeURIComponent(g.id)} onClick=${saveClick('/api/groove/' + encodeURIComponent(g.id))}>Download</a>
      ${g.factory ? '' : html`<button class=${cls('mini', armDel && 'arm')} onClick=${del}>${armDel ? 'Tap again to delete' : 'Delete'}</button>`}
    </div>
    <div class="gr-big">
      <span class="gr-names">${pitches.map(p => html`<i class=${g.unknown.includes(p) ? 'unk' : ''}>${names[p] || 'Note ' + p + ' ?'}</i>`)}</span>
      ${d ? html`<${Lanes} d=${d} beats=${g.bars * bar} bar=${bar} unknown=${g.unknown} names=${names} big=${true} />` : ''}
    </div>
    <div class="gr-cards">
      <div class="ky-card gr-facts">
        <h6 class="ky-h6">From the file</h6>
        <div><span>Meter</span><b>${g.meter}</b></div>
        <div><span>Length</span><b>${g.bars} bar${g.bars > 1 ? 's' : ''}</b></div>
        <div><span>Tempo</span><b>${fileBpm ? fileBpm + ' BPM' : 'not written'}</b></div>
        <div><span>Feel</span><b>${g.played ? 'off the grid (swing or played)' : 'on the grid'}</b></div>
        <div><span>Hits</span><b>${g.notes}</b></div>
        <h6 class="ky-h6 gr-h2">What it is for</h6>
        <div class="gr-uses">${USES.map(([v, lb]) => html`<button class=${cls('ky-sty', g.use === v && 'on')} disabled=${g.factory} onClick=${() => setUse(v)}>${lb}</button>`)}</div>
      </div>
      ${g.unknown.length || remapped.length ? html`<div class=${cls('ky-card', g.unknown.length && 'gr-warn')}>
        <h6 class="ky-h6">${g.unknown.length ? `Note${g.unknown.length > 1 ? 's' : ''} golem doesn't know` : 'Notes reassigned'}</h6>
        ${g.unknown.map(n => html`<div class="gr-unkrow">
          <span>Note ${n} plays ${(g.voices || {})[n] || 0} times. No kit plays it: which piece is it?</span>
          ${pick === n ? html`<div class="gr-targets">${targets.map(t => html`<button class="ky-sty" onClick=${() => remap({ ...Object.fromEntries(remapped), [n]: t.note })}>${t.name}</button>`)}</div>`
            : html`<button class="ky-sty" onClick=${() => setPick(n)}>Choose the piece</button>`}</div>`)}
        ${remapped.length ? html`<div class="gr-remapped">${remapped.map(([a, b]) => html`<span>Note ${a} → ${names[b] || b}</span>`)}
          <button class="mini" onClick=${() => remap({})}>Restore the original</button></div>` : ''}
      </div>` : ''}
      <div class="ky-card gr-hear">
        <h6 class="ky-h6">Hear it on a kit</h6>
        <label class="gr-kit"><span>Kit</span><select class="flt-sel" value=${kitId || ''} onChange=${e => setKit(e.target.value)}>
          ${suggested ? html`<option value=${suggested.id} selected=${kitId === suggested.id}>${suggested.name} · made for it</option>` : ''}
          <optgroup label="Drum sets">${kits.filter(k => k.type !== 'pads' && k !== suggested).map(k => html`<option value=${k.id} selected=${kitId === k.id}>${k.name}</option>`)}</optgroup>
          <optgroup label="Pads">${kits.filter(k => k.type === 'pads' && k !== suggested).map(k => html`<option value=${k.id} selected=${kitId === k.id}>${k.name}</option>`)}</optgroup></select></label>
        <div class="tn-seg">${[['file', fileBpm ? fileBpm + ' · file' : 'File'], ['half', fileBpm ? Math.round(fileBpm / 2) + ' · half' : 'Half'], ['patch', 'Patch tempo']].map(([v, lb]) =>
          html`<button class=${tempo === v ? 'on' : ''} onClick=${() => setTempo(v)}>${lb}</button>`)}</div>
        <button class="ky-row" disabled=${!kitId || (hear && hear.phase === 'render')} onClick=${play}>
          ${hear && hear.phase === 'render' ? html`<span class="ky-dm wait">◌</span><span class="nm">Rendering on the kit…</span>` : html`<span class="ky-play">▶</span><span class="nm">Play</span>`}</button>
        ${msg ? html`<div class="gr-msg">${esc(msg)}</div>` : ''}
        <button class="primary gr-add" onClick=${() => openInDesigner(null, 'cfg', { kind: 'drums-groove', file: g.file, list: g.use === 'fill' ? 'fills' : 'patterns' })}>
          Add to my drum machine</button>
      </div>
    </div>
    <${ClipBar} cl=${cl} hint="Play renders this groove on the kit you pick (a few seconds the first time), then plays it." />
  </div>`;
}

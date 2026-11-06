// SPDX-License-Identifier: GPL-3.0-or-later
// LES PAGES RÉPÈTE ET CONCERT DE /live (docs/live-pages.md, FIGÉ 2026-10-15 ; maquette mockups/live-timeline-v2.html).
//  · Répète (`rehearsal`) : les sections en cartes ; un tap met une section en attente, jamais un départ ; on repart d'une
//    section, on la boucle, on enchaîne celle qu'on a choisie à la frontière.
//  · Concert (`timeline`) : lisible à deux mètres ; c'est le pied qui joue ; STOP se tient appuyé.
// Les widgets vivent dans des EMPLACEMENTS FIXES (live-widgets-model.mjs) ; un widget sans données s'efface et rend sa
// place à la page. Le moteur (bridge/arrangement.py) publie le plan (`parts`), la section, la mise en attente, la boucle.
import { html, useState, useEffect, useRef, useAsync, post, cls, esc, setTopSlot, setTopAction } from './lib.js';
import { useLiveTools } from './live-tools.js';
import { usePerfRec, Instruments, sceneColor, mmss } from './live-stageboard.js';
import { widgetsOf, countInBars, setLate, fmtClock } from './live-widgets-model.mjs';

// une écriture au moteur qui RAPPORTE son refus (« too late — the jump is already armed ») au lieu de le jeter
const arrPost = body => fetch('/api/arrangement', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body) }).then(r => r.json().catch(() => ({})).then(d => ({ ...d, ok: r.ok && d.ok !== false })))
  .catch(() => ({ ok: false, error: 'the rack did not answer' }));
const backingOp = (op, extra) => post('/api/backing', { op, ...(extra || {}) }).catch(() => {});

// re-rendre la page à `ms` tant que `on` — la mesure, le temps, la ligne de paroles avancent
function useTick(on, ms = 100) {
  const [, bump] = useState(0);
  useEffect(() => { if (!on) return; const t = setInterval(() => bump(x => x + 1), ms); return () => clearInterval(t); }, [on, ms]);
}

// la setlist du soir, le morceau courant, son preset complet (couleurs des scènes, lanes)
function useStage(rig) {
  const st = rig.state;
  const { data: sl } = useAsync(() => fetch('/api/setlists').then(r => r.json()), []);
  const { data: presets } = useAsync(() => fetch('/api/presets').then(r => r.json()), []);
  const { data: fullP } = useAsync(() => st.preset_id
    ? fetch('/api/preset/' + encodeURIComponent(st.preset_id)).then(r => r.json()).catch(() => null) : Promise.resolve(null), [st.preset_id]);
  const active = sl && (sl.setlists || []).find(x => x.id === sl.active);
  const byId = Object.fromEntries(((presets || [])).map(p => [p.id, p]));
  const lines = (active && active.lines) || ((active && active.presets) || []).map((id, i) => ({ id: 'r:' + i, preset: id }));
  const songs = lines.map((l, i) => ({ ...l, slot: i, p: byId[l.preset] || null,
    title: l.title || ((byId[l.preset] || {}).name) || l.preset || '—' }));
  const curLine = st.song && st.song.line;
  const curIdx = curLine ? songs.findIndex(s => s.id === curLine) : songs.findIndex(s => s.preset === st.preset_id);
  const cur = curIdx >= 0 ? songs[curIdx] : null;
  const title = cur ? cur.title : ((st.song && st.song.title) || st.preset_name || st.preset_id || '');
  return { sl, active, songs, lines, curIdx, cur, title, fullP,
           prev: curIdx > 0 ? songs[curIdx - 1] : null, next: curIdx >= 0 && curIdx + 1 < songs.length ? songs[curIdx + 1] : null };
}

// ── LE TEMPS DU MORCEAU, lu dans l'état publié (horloge du serveur, comme la barre de section d'avant) ──
function clockOf(arr, parts) {
  const now = Date.now() / 1000;
  const running = !!arr.running && !arr.counting;
  const pos = running && arr.song_t0 ? Math.max(0, now - arr.song_t0) : null;
  const sec = running && arr.index >= 0 ? parts[arr.index] : null;
  let bar = null, beat = null, barsLeft = null;
  if (sec && arr.sec_to > arr.sec_from) {
    const f = Math.max(0, Math.min(0.9999, (now - arr.sec_from) / (arr.sec_to - arr.sec_from)));
    const fb = f * sec.bars;
    bar = Math.floor(fb) + 1;
    beat = Math.floor((fb % 1) * (sec.num || 4));
    barsLeft = Math.max(1, sec.bars - Math.floor(fb));
  }
  let cBeat = null, cBeats = null;
  if (arr.counting && arr.count_to > arr.count_from) {
    const k = parts[arr.from || 0] || parts[0];
    cBeats = Math.max(1, Math.round(countInBars(k) * (k ? k.num || 4 : 4)));
    cBeat = Math.min(cBeats - 1, Math.floor(((now - arr.count_from) / (arr.count_to - arr.count_from)) * cBeats));
  }
  return { now, running, pos, sec, bar, beat, barsLeft, cBeat, cBeats };
}

const Dots = ({ n, on, color }) => html`<span class="lp-dots" style=${color ? '--c:' + color : ''}>
  ${Array.from({ length: Math.min(n || 4, 12) }, (_, i) => html`<i class=${cls(i === 0 && 'one', on != null && i <= on && 'on')}></i>`)}</span>`;

// la carte du morceau : les sections à l'échelle, la tête de lecture — lecture seule, ce n'est pas une cible
function SongMap({ parts, colorOf, pos, len, from }) {
  const head = pos != null ? pos : (parts[from] ? parts[from].at : null);
  return html`<div class="lp-map" data-doc="live.map" aria-hidden="true">
    ${parts.map(p => html`<i style=${'flex:' + Math.max(0.3, p.dur) + ';--c:' + colorOf(p.scene)} title=${p.name}></i>`)}
    ${head != null && len ? html`<span class="lp-head" style=${'left:' + Math.min(100, (head / len) * 100).toFixed(2) + '%'}></span>` : ''}
  </div>`;
}

// ── LES DONNÉES DES WIDGETS QUI EN DEMANDENT (au niveau de la page : jamais un hook sous condition) ──
function useLyrics(st) {
  const key = ((st.backing || {}).slug || '') + '|' + (st.preset_id || '') + '|' + ((st.song || {}).line || '');
  const { data } = useAsync(() => fetch('/api/live/lyrics').then(r => r.json()).catch(() => null), [key]);
  return (data && data.lines) || [];
}

function useStdChart(st) {
  const p = st.standard_block || null;
  const slug = p && p.standard;
  const [chart, setChart] = useState(null);
  const [live, setLive] = useState(null);
  useEffect(() => {
    if (!slug) { setChart(null); return; }
    let alive = true;
    fetch('/api/standards/' + encodeURIComponent(slug) + '/preview', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ key: p.key && p.key !== 'Original' ? p.key : null, feel: p.feel && p.feel !== 'auto' ? p.feel : null,
        choruses: 1, bpm: st.tempo || null }) })
      .then(r => r.json()).then(r => alive && !r.error && setChart(r)).catch(() => {});
    return () => { alive = false; };
  }, [slug, p && p.key, p && p.feel]);
  const playing = !!(live && live.playing);
  useEffect(() => {
    if (!slug) return;
    const t = setInterval(() => fetch('/api/standards/state').then(r => r.json()).then(setLive).catch(() => {}), playing ? 400 : 2000);
    return () => clearInterval(t);
  }, [slug, playing]);
  return slug && chart ? { bars: chart.bars || [], bar: live && live.playing ? live.bar : -1 } : null;
}

// l'heure de départ du set : le premier morceau de la setlist lancé dans cette session (mémorisée pour la session)
function useSetStart(slId, curIdx, running, pos) {
  const key = 'golem.setStart.' + (slId || '');
  let start = null;
  try { start = +sessionStorage.getItem(key) || null; } catch { /* privé */ }
  useEffect(() => {
    if (!running || curIdx !== 0 || pos == null || pos > 5) return;
    try { sessionStorage.setItem(key, String(Date.now() / 1000 - pos)); } catch { /* privé */ }
  }, [running, curIdx, pos != null && pos <= 5]);
  return start;
}

// un widget = un élément, ou null quand il n'a rien à montrer (il s'efface, docs/live-pages.md §5)
function widget(id, size, c) {
  if (!id) return null;
  if (id === 'lyrics') {
    if (!c.lyrics.length) return null;
    const t = c.pos != null ? c.pos : (c.parts[c.focus] ? c.parts[c.focus].at : 0);
    let i = c.lyrics.findIndex(l => l[0] > t) - 1;
    if (i < -1) i = c.lyrics.length - 1;
    if (i < 0) i = 0;
    const l1 = (c.lyrics[i] || [0, ''])[1], l2 = (c.lyrics[i + 1] || [0, ''])[1];
    return html`<div class=${'lp-w lp-lyrics lp-' + size}><span class="l1">${esc(l1 || '…')}</span><span class="l2">${esc(l2 || '')}</span></div>`;
  }
  if (id === 'chords') {
    // seulement quand la grille JOUE : des accords figés sur les mesures 1-4 ne disent rien de ce qu'on joue (relecture UX)
    if (!c.chart || !c.chart.bars.length || c.chart.bar < 0) return null;
    const b = c.chart.bar;
    const w0 = Math.floor(b / 4) * 4;
    const win = c.chart.bars.slice(w0, w0 + (size === 'L' ? 8 : 4));
    return html`<div class=${'lp-w lp-chords lp-' + size}><span class="k">CHORDS</span>
      <div class="lp-chordrow">${win.map((bar, k) => html`<span class=${cls(c.chart.bar === w0 + k && 'on')}>
        ${((bar.chords || []).map(x => x.sym).join(' ')) || '—'}</span>`)}</div></div>`;
  }
  if (id === 'notes') {
    const ln = c.line || {};
    const tags = [ln.capo ? 'capo ' + ln.capo : null, ln.tuning ? ln.tuning : null, ln.note || null].filter(Boolean);
    if (!tags.length) return null;
    return size === 'S' ? html`<div class="lp-w lp-tags">${tags.map(t => html`<span class="lp-tag">${esc(t)}</span>`)}</div>`
      : html`<div class="lp-w lp-notes lp-M"><span class="k">STAGE NOTES</span>${tags.map(t => html`<b>${esc(t)}</b>`)}</div>`;
  }
  if (id === 'song_time') {
    if (!c.len) return null;
    return html`<div class="lp-w lp-songtime lp-M"><span class="k">SONG TIME</span>
      <b>${mmss(c.pos || 0)}</b><small> / ${mmss(c.len)}</small></div>`;
  }
  if (id === 'set_clock') {
    if (c.late == null) return null;
    const late = c.late > 5, early = c.late < -5;
    return html`<div class=${cls('lp-w', 'lp-tag', 'lp-setclock', late && 'late', early && 'early')}
      title="the set against its plan — the planned length of every song so far">
      SET ${c.late >= 0 ? '+' : '−'}${fmtClock(c.late)} ${late ? 'LATE' : early ? 'EARLY' : 'ON TIME'}</div>`;
  }
  if (id === 'instruments') {
    return html`<div class=${'lp-w lp-insts lp-' + size}><${Instruments} st=${c.st} preset=${c.fullP} /></div>`;
  }
  return null;
}

// le contexte commun des widgets et des deux pages
function usePageCtx(rig, page) {
  const st = rig.state;
  const arr = st.arrangement || {};
  const S = useStage(rig);
  const parts = arr.present ? (arr.parts || []) : [];
  const lyrics = useLyrics(st);
  const chart = useStdChart(st);
  const clk = clockOf(arr, parts);
  useTick(clk.running || !!arr.counting, 100);
  const len = arr.song_len || (st.backing || {}).len || 0;
  const setStart = useSetStart(S.active && S.active.id, S.curIdx, clk.running, clk.pos);
  const late = setLate({ startedAt: setStart, now: clk.now, lines: S.lines, curIdx: S.curIdx, pos: clk.pos });
  const colorOf = sid => sceneColor(sid, S.fullP);
  const W = widgetsOf(st.mode, page);
  return { st, arr, S, parts, lyrics, chart, clk, len, late, colorOf, W, line: S.cur };
}

// ════════════════════════════════════ LA PAGE RÉPÈTE ════════════════════════════════════
function RehearsalPage({ c0, tools }) {
  const { st, arr, S, parts, clk, colorOf, W } = c0;
  const n = parts.length;
  const running = clk.running, counting = !!arr.counting;
  const [sel, setSel] = useState(0);                                   // d'où l'on repart, à l'arrêt
  const songKey = (st.preset_id || '') + '|' + ((st.song || {}).line || '');
  useEffect(() => { setSel(0); }, [songKey]);
  useEffect(() => { if (arr.done && !running) setSel(0); }, [arr.done]);
  const [said, setSaid] = useState('');
  useEffect(() => { if (!said) return; const t = setTimeout(() => setSaid(''), 2500); return () => clearTimeout(t); }, [said]);
  // ── le rail : 5 cartes visibles ; au-delà, des pages de 4 (une carte reste visible) ; il suit la carte qui joue
  const many = n > 5;
  const [off, setOff] = useState(0);
  const lastGesture = useRef(0);
  const focus = running ? arr.index : counting ? (arr.from || 0) : sel;
  useEffect(() => {
    if (!many || Date.now() - lastGesture.current < 5000) return;
    if (focus < off || focus >= off + 5) setOff(Math.max(0, Math.min(n - 5, focus - 1)));
  }, [focus, many, n]);
  const page = d => { lastGesture.current = Date.now(); setOff(o => Math.max(0, Math.min(n - 5, o + d * 4))); };
  // un glissé n'est jamais un tap : au-delà de 10 px, le tap est annulé ; au-delà de 40 px (|dx| > 1,5·|dy|), on tourne
  const g = useRef(null);
  const onDown = e => { const el = e.target && e.target.closest && e.target.closest('[data-card]');
    g.current = { x: e.clientX, y: e.clientY, moved: false, swiped: false, card: el ? +el.dataset.card : null }; };
  const onMove = e => {
    const s = g.current; if (!s) return;
    const dx = e.clientX - s.x, dy = e.clientY - s.y;
    if (Math.hypot(dx, dy) > 10) s.moved = true;
    if (many && !s.swiped && Math.abs(dx) > 40 && Math.abs(dx) > 1.5 * Math.abs(dy)) { s.swiped = true; page(dx < 0 ? 1 : -1); }
  };
  const tapCard = async i => {
    if (g.current && (g.current.moved || g.current.card !== i)) return;   // appui commencé ailleurs, ou glissé : pas un tap
    if (counting) { await arrPost({ op: 'stop' }); await arrPost({ op: 'start', from: i }); return; }
    if (running) {
      const r = await arrPost({ op: 'cue', index: arr.cue === i ? null : i });
      if (!r.ok) setSaid(r.error || 'refused');
      return;
    }
    setSel(i);
  };
  const go = async () => { const r = await arrPost({ op: 'start', from: sel }); if (!r.ok) setSaid(r.error || 'refused'); };
  const pause = async () => { const i = arr.index; await arrPost({ op: 'stop' }); if (i >= 0) setSel(i); };
  const stop = async () => { const f = arr.from || 0; await arrPost({ op: 'stop' }); setSel(f); };
  const loop = async () => { if (g.current && g.current.moved) return; const r = await arrPost({ op: 'loop', on: !arr.loop }); if (!r.ok) setSaid(r.error || 'refused'); };
  const ctx = { ...c0, focus, pos: clk.pos };
  const right = widget(W.right, 'M', ctx);
  const bottom = widget(W.bottom, 'L', ctx);
  const barOfSong = SECS => parts.slice(0, SECS).reduce((a, p) => a + (p.bars || 0), 0) + 1;
  const ciBars = countInBars(parts[sel]);

  if (tools.view) return tools.view;
  if (S.sl && !S.songs.length && !st.preset_id) return html`<div class="lp lp-empty"><div><h2>No setlist for tonight</h2>
    <p class="muted">Build one in Songs ▸ Setlists, or bring one from golem.fm.</p></div></div>`;

  // ── un morceau SANS arrangement : ni cartes ni carte du morceau ──
  if (!n) {
    const bk = st.backing || {};
    return html`<div class="lp lp-reh">
      <div class="lp-song"><b>${esc(S.title || 'No song loaded')}</b>${st.tempo ? html`<em>${st.tempo} BPM</em>` : ''}</div>
      <div class="lp-noarr"><b>${bk.present ? 'No arrangement — plays from the top' : 'Nothing to run on this song'}</b>
        <span class="muted">${bk.present ? "add sections in the song's Arrangement block to rehearse it part by part"
          : 'no stems and no sections — add them in the Backing and Arrangement blocks'}</span></div>
      <div class="lp-tr" data-doc="live.transport">
        <button class=${cls('lp-go', bk.playing && 'on')} disabled=${!bk.present} onClick=${() => backingOp(bk.playing ? 'pause' : 'play')}>
          ${bk.playing ? '❚❚ PAUSE' : '▶ PLAY'}</button>
        <button class="lp-stop" disabled=${!bk.playing} onClick=${() => backingOp('stop')}>■ STOP</button>
      </div></div>`;
  }

  const cueI = arr.cue, loopOn = !!arr.loop;
  const nowSec = running ? parts[arr.index] : null;
  const pulse = running && clk.barsLeft != null && clk.barsLeft <= 2;
  const card = (p, i) => {
    const isNow = running && i === arr.index;
    const isSel = !running && !counting && i === sel;
    const isCue = running && cueI === i;
    const isFrom = counting && i === (arr.from || 0);
    const ly = c0.lyrics.find(l => l[0] >= p.at && l[0] < p.at + p.dur && l[1]);
    return html`<div key=${'c' + i + (isNow ? '-' + (arr.loops || 0) : '')} data-card=${i} data-doc=${'live.section.' + (i + 1)}
        class=${cls('lp-card', isNow && 'now', isNow && 'lp-flashin', (isSel || isCue || isFrom) && 'cued', isCue && pulse && 'pulse')}
        style=${'--c:' + colorOf(p.scene) + (isCue && pulse ? ';--beat:' + (60 / (st.tempo || 120)).toFixed(3) + 's' : '')}
        onPointerUp=${() => tapCard(i)} role="button" tabindex="0"
        ${/* un clic SANS pointeur (clavier, ou element.click() de la doc golem.fm) : detail === 0. Un vrai tap a déjà joué
              par pointerup — le doubler annulerait un cue. Le geste d'avant est oublié : ce clic n'a pas glissé. */''}
        onClick=${e => { if (e.detail === 0) { g.current = null; tapCard(i); } }}
        onKeyDown=${e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); g.current = null; tapCard(i); } }}
        title=${running ? (isCue ? 'tap to cancel' : 'tap: play this section next') : 'tap: start from here'}>
      ${isSel || isCue || isFrom ? html`<span class="lp-cueband">${isFrom ? 'COUNT-IN' : running ? 'NEXT' : 'START'}</span>` : ''}
      <span class="lp-c-n">${i + 1}${isNow ? ' · PLAYING' : ''}</span>
      ${p.scene ? html`<span class="lp-c-s">${p.scene}</span>` : ''}
      <b class="lp-c-nm">${esc(p.name)}</b>
      <span class="lp-c-m">${p.bars} bar${p.bars === 1 ? '' : 's'}${(p.num || 4) !== 4 || (p.den || 4) !== 4 ? ' · ' + p.num + '/' + p.den : ''}</span>
      ${isNow ? html`<span class="lp-c-bar"><i style=${'width:' + (((clk.bar || 1) - 1) / Math.max(1, p.bars) * 100).toFixed(1) + '%'}></i></span>` : ''}
      ${ly && !isNow ? html`<span class="lp-c-ly">“${esc(ly[1])}”</span>` : ''}
      ${isNow ? html`<button class=${cls('lp-loop', loopOn && 'on')} onPointerUp=${e => { e.stopPropagation(); loop(); }}
          title=${loopOn ? 'stop looping — the song goes on at the end of the section' : 'loop this section'}>
          ⟲ ${loopOn ? (arr.loops ? '×' + (arr.loops + 1) : 'LOOP') : 'LOOP'}</button>` : ''}
    </div>`;
  };

  // la zone NOW
  let now;
  if (counting) {
    const k = parts[arr.from || 0] || parts[0];
    now = html`<div class="lp-now lp-count" style=${'--c:' + colorOf(k.scene)}><span class="k">COUNT-IN · then ${esc(k.name)}</span>
      <span class="lp-cnum">${(clk.cBeat ?? 0) + 1}<small> / ${clk.cBeats || 4}</small></span>
      <${Dots} n=${clk.cBeats} on=${clk.cBeat} color=${colorOf(k.scene)} />
      <span class="nx muted">tap a section to start from it instead</span></div>`;
  } else if (running && nowSec) {
    const then = cueI != null ? html`<span class="nx accent">then ▸ <b>${esc(parts[cueI].name)}</b> (cued) in ${clk.barsLeft} bar${clk.barsLeft > 1 ? 's' : ''}</span>`
      : loopOn ? html`<span class="nx">loops <b>${esc(nowSec.name)}</b> in ${clk.barsLeft} bar${clk.barsLeft > 1 ? 's' : ''}</span>`
      : arr.next ? html`<span class=${cls('nx', clk.barsLeft <= 4 && 'accent')}>then ▸ <b>${esc(arr.next)}</b> in ${clk.barsLeft} bar${clk.barsLeft > 1 ? 's' : ''}</span>`
      : html`<span class="nx">last section — the song ends with it</span>`;
    now = html`<div key=${'n' + arr.index + '-' + (arr.loops || 0)} class="lp-now lp-flashin" style=${'--c:' + colorOf(nowSec.scene)}><span class="k">NOW${nowSec.scene ? ' · SCENE ' + nowSec.scene : ''}</span>
      <span class="nm">${esc(nowSec.name)}</span>
      <span class="bt">bar ${clk.bar || 1} / ${nowSec.bars} <${Dots} n=${nowSec.num} on=${clk.beat} color=${colorOf(nowSec.scene)} /></span>${then}</div>`;
  } else if (arr.done) {
    now = html`<div class="lp-now end"><span class="k">END</span><span class="nm">${esc(S.title)}</span>
      <span class="nx muted">the last section held — start again from any section</span></div>`;
  } else {
    const k = parts[sel] || parts[0];
    now = html`<div class="lp-now" style=${'--c:' + colorOf(k.scene)}><span class="k">READY</span>
      <span class="nm">from ${esc(k.name)}</span><span class="nx muted">tap a section above to start from it</span></div>`;
  }

  return html`<div class="lp lp-reh" data-doc="live.rehearsal">
    <div class="lp-song" data-doc="live.rehearsal.song"><b>${esc(S.title)}</b>
      <em>${st.tempo ? st.tempo + ' BPM · ' : ''}${n} sections · ${parts.reduce((a, p) => a + p.bars, 0)} bars</em>
      ${said ? html`<span class="lp-said">${esc(said)}</span>` : ''}</div>
    <div class=${cls('lp-rail', !many && 'fit')} data-doc="live.sections" onPointerDown=${onDown} onPointerMove=${onMove}>
      ${many ? html`<button class="lp-arw" disabled=${off === 0} onClick=${() => page(-1)} aria-label="previous sections">‹</button>` : ''}
      <div class="lp-cards" style=${'--n:' + (many ? 5 : n)}>${parts.slice(many ? off : 0, many ? off + 5 : n).map((p, k) => card(p, (many ? off : 0) + k))}</div>
      ${many ? html`<button class="lp-arw" disabled=${off >= n - 5} onClick=${() => page(1)} aria-label="next sections">›</button>` : ''}
    </div>
    <div class=${cls('lp-mid', !right && 'solo')} data-doc="live.now">${now}${right || ''}</div>
    ${bottom || ''}
    <${SongMap} parts=${parts} colorOf=${colorOf} pos=${clk.pos} len=${c0.len} from=${sel} />
    <div class="lp-tr" data-doc="live.transport">
      ${running || counting ? html`
        <button class="lp-go on" onClick=${pause} title="stop — you will start again from the section that was playing">❚❚ PAUSE</button>
        <button class="lp-stop" onClick=${stop} title="stop — back to the section you started from">■ STOP</button>`
      : html`<button class="lp-go" onClick=${go}>▶ FROM ${esc((parts[sel] || parts[0]).name).toUpperCase()}
          <small>bar ${barOfSong(sel)} · ${ciBars}-bar count-in</small></button>
        <button class="lp-stop" disabled>■ STOP</button>`}
    </div>
  </div>`;
}

// ════════════════════════════════════ LA PAGE CONCERT ════════════════════════════════════
// STOP SE TIENT APPUYÉ 0,6 s (docs/live-pages.md §4) : un tap accidentel ne coupe pas le morceau
function HoldStop({ onStop, off }) {
  const [p, setP] = useState(0);
  const t = useRef(null);
  const start = () => { const t0 = performance.now();
    const tick = () => { const k = Math.min(1, (performance.now() - t0) / 600); setP(k);
      if (k >= 1) { t.current = null; setP(0); onStop(); return; } t.current = requestAnimationFrame(tick); };
    t.current = requestAnimationFrame(tick); };
  const cancel = () => { if (t.current) cancelAnimationFrame(t.current); t.current = null; setP(0); };
  if (off) return html`<button class="lp-stop hold" disabled>■ STOP<small>nothing is playing</small></button>`;
  return html`<button class="lp-stop hold" style=${'--p:' + p} onPointerDown=${start} onPointerUp=${cancel} onPointerLeave=${cancel}
    onPointerCancel=${cancel} title="hold to stop">■ STOP<small>Hold to stop</small></button>`;
}

function ConcertPage({ c0, tools }) {
  const { st, arr, S, parts, clk, colorOf, W } = c0;
  const n = parts.length;
  const running = clk.running, counting = !!arr.counting;
  const bk = st.backing || {};
  const ctx = { ...c0, focus: 0, pos: clk.pos };
  const top1 = widget(W.top1, 'S', ctx), top2 = widget(W.top2, 'S', ctx);
  const bottom = widget(W.bottom, 'L', ctx);
  const recall = s => s && s.p && post('/api/recall', { slot: s.slot }).catch(() => {});
  const play = () => n ? arrPost({ op: 'start' }) : backingOp('play');
  const stop = () => { if (n) arrPost({ op: 'stop' }); if (bk.present) backingOp('stop'); };

  if (tools.view) return tools.view;
  if (S.sl && !S.songs.length && !st.preset_id) return html`<div class="lp lp-empty"><div><h2>No setlist for tonight</h2>
    <p class="muted">The music stand plays the active setlist. Build one in Songs ▸ Setlists, or bring one from golem.fm.</p></div></div>`;

  const nowSec = running ? parts[arr.index] : null;
  const elapsed = clk.pos != null ? clk.pos : (bk.playing ? bk.pos : null);
  let big;
  if (counting) {
    const k = parts[arr.from || 0] || parts[0];
    big = html`<span class="lp-sec">COUNT-IN</span><span class="lp-nx">then <b>${esc(k ? k.name : '')}</b></span>
      <div class="lp-rt"><${Dots} n=${clk.cBeats} on=${clk.cBeat} color=${colorOf(k && k.scene)} /></div>`;
  } else if (nowSec) {
    const soon = clk.barsLeft != null && clk.barsLeft <= 4;
    big = html`<span key=${'s' + arr.index} class="lp-sec lp-flashin">${esc(nowSec.name)}</span>
      <span class=${cls('lp-nx', soon && 'accent')}>${arr.next ? html`next ▸ <b>${esc(arr.next)}</b> in ${clk.barsLeft} bar${clk.barsLeft > 1 ? 's' : ''}` : 'last section'}</span>
      <div class="lp-rt"><span class="lp-bb">${clk.bar || 1}<small> / ${nowSec.bars}</small></span>
        <${Dots} n=${nowSec.num} on=${clk.beat} color=${colorOf(nowSec.scene)} />
        ${nowSec.scene ? html`<span class="lp-sn">SCENE ${nowSec.scene}</span>` : ''}</div>`;
  } else if (arr.done) {
    big = html`<span class="lp-sec sm">END — ${esc(S.title)}</span><span class="lp-nx">${S.next ? html`Next song ▸ <b>${esc(S.next.title)}</b>` : 'last song of the set'}</span>`;
  } else {
    big = html`<span class="lp-sec sm">${esc(S.title || 'Pick a song')}</span>
      <span class="lp-nx">${n ? n + ' sections — ▶ PLAY starts the song' : bk.present ? 'No arrangement — plays from the top' : 'Nothing to run on this song'}</span>`;
  }
  const sc = nowSec ? nowSec.scene : (parts[0] || {}).scene;
  return html`<div class="lp lp-gig" data-doc="live.concert">
    <div class="lp-band" data-doc="live.concert.setlist">
      <button class="prev" disabled=${!S.prev || running} onClick=${() => recall(S.prev)}>${S.prev ? html`${String(S.curIdx).padStart(2, '0')} ${esc(S.prev.title)}` : ''}</button>
      <div class="cur">▶ ${S.curIdx >= 0 ? String(S.curIdx + 1).padStart(2, '0') + ' ' : ''}${esc(S.title)}
        ${c0.len ? html`<em>${mmss(elapsed || 0)} / ${mmss(c0.len)}</em>` : ''}</div>
      <button class="nxt" disabled=${!S.next || running} onClick=${() => recall(S.next)}>${S.next ? html`${String(S.curIdx + 2).padStart(2, '0')} ${esc(S.next.title)} ›` : 'last song'}</button>
    </div>
    <div class="lp-big" data-doc="live.concert.section" style=${'--c:' + colorOf(sc)}>
      ${top1 || top2 ? html`<div class="lp-slots">${top1 || ''}${top2 || ''}</div>` : ''}
      ${big}
    </div>
    ${bottom || ''}
    ${n ? html`<${SongMap} parts=${parts} colorOf=${colorOf} pos=${clk.pos} len=${c0.len} from=${0} />` : ''}
    <div class="lp-tr" data-doc="live.transport">
      ${!running && !counting ? html`<button class="lp-go" disabled=${!n && !bk.present} onClick=${play}>▶ PLAY</button>`
        : arr.mode === 'foot' && running ? html`<button class="lp-go" onClick=${() => arrPost({ op: 'next' })}>▶▶ NEXT</button>`
        : html`<span class="lp-playing">● ${counting ? 'COUNT-IN' : 'PLAYING'}</span>`}
      <${HoldStop} onStop=${stop} off=${!running && !counting && !bk.playing} />
    </div>
  </div>`;
}

// ── LA PAGE (Répète ou Concert) : les données, le top menu, puis la page elle-même ──
// Le top menu est PUBLIÉ par un effet (setTopSlot / setTopAction) : tout ce qu'il montre doit être dans ses deps — le
// piège du slot figé sur son premier rendu.
export function StagePage({ rig, page }) {
  const c0 = usePageCtx(rig, page);
  const { st, arr, S } = c0;
  const rec = usePerfRec(st);
  const tools = useLiveTools({ rig, st, view: page,
    presetId: st.preset_id === 'sandbox-try' || String(st.preset_id || '').startsWith('patch:') ? null : st.preset_id,
    rec: { perfOn: rec.perfOn, on: rec.on, toggle: rec.toggle, title: rec.on ? 'stop recording — save the take (' + rec.mmss + ')' : 'record the set' } });
  useEffect(() => {
    setTopSlot(html`<div class="tb-setlist" title="active setlist">
      <span class="tb-sl-ic">▤</span><span class="tb-sl-nm">${esc((S.active && S.active.name) || 'Setlist')}</span>
      <em>${S.curIdx >= 0 ? (S.curIdx + 1) + '/' + S.songs.length : S.songs.length}</em></div>`);
    setTopAction(html`<div class="live-info">
      <span class="live-inf" title=${st.audio_metrics && st.audio_metrics.platform ? 'input + output latency reported by the audio device' : 'round-trip latency from ALSA'}>${st.latency_ms != null ? st.latency_ms + ' ms' : '— ms'}</span>
      ${st.xruns_recent ? html`<span class="live-inf warn" title="audio dropouts in the last 10 min">⚠ ${st.xruns_recent}</span>` : ''}
    </div>
    <div class="live-acts">${tools.buttons}</div>`);
    return () => { setTopSlot(null); setTopAction(null); };
  }, [(S.active && S.active.name), S.songs.length, S.curIdx, st.latency_ms, st.xruns_recent,
      st.audio_metrics && st.audio_metrics.platform, rec.mmss, ...tools.deps]);
  return page === 'rehearsal' ? html`<${RehearsalPage} c0=${c0} tools=${tools} />` : html`<${ConcertPage} c0=${c0} tools=${tools} />`;
}

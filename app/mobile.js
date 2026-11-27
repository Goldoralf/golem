// SPDX-License-Identifier: GPL-3.0-or-later
// Golem Companion — le « site » MOBILE de GoleM (docs/devices-people.md).
// Compagnon personnel : il lit beaucoup et agit peu. Il bascule les pédales de SES lignes, pose une
// marque dans la prise ; s'il est CONDUCTOR, il charge, lance et arrête les morceaux, et pilote /live
// (mode Control : scènes et stomps du pédalier — le son de tout le groupe, d'où le droit).
//
// LE TOP MENU A DEUX ICÔNES (maquettes validées le 2026-11-26, artifact « Companion · Live et System ») :
//   Live   — un MODE choisi dans une feuille, comme la page Mode du rack : Now · Control · Mine · Lyrics · Beat · Rec
//            (Song est fondu dans Control : un seul écran charge un morceau) — mobile-control.js pour Control ;
//   System — This golem · Pair a device · golem.fm · Account (mobile-system.js).
// Adresse : ?tab=live&mode=control, ?tab=system&page=golem.fm ; les anciens ?tab=now… y mènent toujours.
import { html, render, useState, useEffect, useRef, post, cls, useRigState, keepAwake } from './lib.js';
import { watchErrors } from './ui-errors.mjs';
import { startAnimStepper, setDisplay } from './anim-stepper.mjs';
import { ICON, hydrateBlockMeta, shortBlockName } from './designer-model.js';
import { PhoneCaptures } from './capture-module.js';
import { useCpuMany, StageChip, StageCpuSheet } from './cpu-budget.js';   // docs/cpu-budget.md, lot 4
import { ControlPage } from './mobile-control.js';
import { SystemPage } from './mobile-system.js';
import { canFullscreen, toggleFullscreen, useFullscreen, startAutoFullscreen, setFullscreenPref } from './fullscreen.mjs';

const api = p => fetch(p).then(r => { if (!r.ok) throw new Error(p); return r.json(); });
const LANE_TAG = { guitar: 'GTR', bass: 'BASS', voice: 'VOX', keys: 'KEYS', 'keys-pads': 'KEYS', pads: 'PADS', drums: 'DRUM', line: 'LINE' };
const fmtT = s => `${Math.floor((s || 0) / 60)}:${String(Math.floor((s || 0) % 60)).padStart(2, '0')}`;
const dbTxt = v => v == null ? '0 dB' : (v > 0 ? '+' : '') + Number(v).toFixed(v % 1 ? 1 : 0) + ' dB';
const NOTE = n => n == null ? null : ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'][((n % 12) + 12) % 12] + (Math.floor(n / 12) - 1);

let _metaP = null;
const ensureMeta = () => _metaP || (_metaP = api('/api/effects').then(d => hydrateBlockMeta(d.effects || d, d)).catch(() => { _metaP = null; }));

function useWakeLock() {
  // un seul verrou pour toute l'app, avec son repli hors HTTPS (lib.keepAwake, docs/devices-people.md lot E)
  useEffect(() => { keepAwake(); }, []);
}

// une horloge locale pour les barres et les temps (le serveur publie les bornes, l'écran interpole)
function useTick(ms = 250) {
  const [, set] = useState(0);
  useEffect(() => { const t = setInterval(() => set(x => x + 1), ms); return () => clearInterval(t); }, [ms]);
  return Date.now() / 1000;
}

// ── LES DONNÉES : qui je suis, mes lignes, la setlist, le catalogue des morceaux ─────────────────────
function useCompanion(st) {
  const qp = new URL(location.href).searchParams;
  const [who, setWho] = useState(null);
  const [mine, setMine] = useState(null);
  const [setlists, setSetlists] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [presets, setPresets] = useState(null);
  const [, setMeta] = useState(0);
  const reloadWho = () => api('/api/auth/whoami').then(setWho).catch(() => setWho({}));
  useEffect(() => { reloadWho(); ensureMeta().then(() => setMeta(x => x + 1)); }, []);
  useEffect(() => { api('/api/backing/catalog').then(d => setCatalog(d.songs || [])).catch(() => setCatalog([])); }, []);
  const dev = (who && who.device) || {};
  const person = qp.get('person') || dev.person;
  const role = qp.get('role') || dev.role || (person ? null : 'Guitar');
  const lineKey = [st.preset_id, st.scene_id, JSON.stringify(st.stomps || {}), JSON.stringify(st.lane_toggles || {})].join('|');
  useEffect(() => {
    if (!st.preset_id) { setMine(null); return; }
    api('/api/lane/mine?role=' + encodeURIComponent(role || '') + (qp.get('person') ? '&person=' + encodeURIComponent(qp.get('person')) : ''))
      .then(setMine).catch(() => {});
  }, [lineKey, role]);
  const songKey = [st.preset_id, (st.song || {}).line, (st.song || {}).setlist, st.loaded_by].join('|');
  useEffect(() => { api('/api/setlists').then(setSetlists).catch(() => {}); }, [songKey]);
  useEffect(() => { api('/api/presets').then(setPresets).catch(() => {}); }, [st.preset_id]);
  const sl = setlists && (setlists.setlists || []).find(x => x.id === ((st.song || {}).setlist || setlists.active)) || null;
  const lines = ((sl && sl.lines) || []).filter(Boolean);
  let idx = lines.findIndex(l => l.id === (st.song || {}).line);
  if (idx < 0) idx = lines.findIndex(l => l.preset === st.preset_id);
  const songOf = ln => { const c = (catalog || []).find(x => ln && x.slug === ln.backing) || {}; return { artist: c.artist, key: c.key, duration: c.duration_sec }; };
  const lanes = (mine && mine.lanes) || [];
  // le titre d'une ligne comme la setlist du rack l'écrit : titre, sinon nom du preset, sinon « New song »
  // (l'id du preset n'est pas un titre ; une ligne vide affichait un numéro seul)
  const titleOf = ln => !ln ? '' : (ln.title || ((presets || []).find(p => p.id === ln.preset) || {}).name || ln.preset
    || ((catalog || []).find(x => x.slug === ln.backing) || {}).title || 'New song');
  return {
    who, dev, person, role, mine, lanes, sl, lines, idx, songOf, presets, titleOf, reloadWho,
    personName: dev.person_name || (mine && mine.person_name) || qp.get('person') || role || 'Guest',
    conductor: !!(dev.conductor || dev.admin || qp.get('conductor') === '1' || (who && who.local && qp.get('conductor') !== '0' && !qp.get('person') && !qp.get('role'))),
    hasVoice: lanes.some(L => L.role === 'voice'),
    current: st.preset_id && (presets || []).find(p => p.id === st.preset_id),
  };
}

// l'état qu'une de MES lignes joue dans une scène donnée (fiche preset : scenes[].lanes[])
const myRowsIn = (presetSummary, sceneId, laneIds) => {
  const sc = ((presetSummary && presetSummary.scenes) || []).find(s => s.id === sceneId);
  return ((sc && sc.lanes) || []).filter(r => laneIds.includes(r.id));
};
const cap = t => t ? String(t).charAt(0).toUpperCase() + String(t).slice(1) : '';
const rowName = r => r.mute ? 'muted' : (r.state && !r.implicit ? r.state : (r.block ? shortBlockName(r.block) : cap(r.name)));
const Acc = ({ rows }) => html`<div class="c-acc">${rows.map(r => html`<div class=${cls('c-l', r.mute && 'off')}>
  <span class="g">${ICON[r.glyph_type] || '•'}</span>${rowName(r)}<em class=${'c-tag ' + (r.role || '')}>${LANE_TAG[r.role] || r.role}</em></div>`)}</div>`;

// la scène effective d'une partie : la sienne, sinon celle de la partie d'avant
const partScene = (parts, i) => { for (let k = i; k >= 0; k--) if (parts[k] && parts[k].scene) return parts[k].scene; return null; };
const PART_COLOR = n => /chorus|refrain/i.test(n) ? '#cc1f1f' : /solo|bridge|pont/i.test(n) ? '#7a2a52' : /outro|end/i.test(n) ? '#2a7d3f' : '#3f7fd6';

// ── les éléments partagés ──────────────────────────────────────────────────────────────────────
function PartNow({ arr, now }) {
  const f = arr.sec_to > arr.sec_from ? Math.max(0, Math.min(1, (now - arr.sec_from) / (arr.sec_to - arr.sec_from))) : 0;
  const bars = arr.bars || 0, bar = bars ? Math.min(bars, Math.floor(f * bars) + 1) : 0;
  return html`<div class="c-part" style=${'--pc:' + PART_COLOR(arr.name || '')}>
    <span class="c-lbl">Part now${arr.scene ? ' · scene ' + arr.scene : ''}</span>
    <div class="c-part-name">${arr.name || '—'}</div>
    <div class="c-sub">${bars ? 'bar ' + bar + ' of ' + bars : ''}${arr.sig ? ' · ' + arr.sig : ''}${arr.mode === 'foot' ? ' · parts on the foot' : ' · parts follow the bars'}</div>
    ${bars ? html`<div class="c-bars">${Array.from({ length: Math.min(bars, 32) }, (_, i) => html`<i class=${i < bar ? 'done' : ''}></i>`)}</div>` : ''}
  </div>`;
}
function NextPart({ arr, now }) {
  if (!arr.next) return html`<div class="c-next last"><span class="c-lbl">Next</span><b>End of the song</b></div>`;
  const f = arr.sec_to > arr.sec_from ? Math.max(0, Math.min(1, (now - arr.sec_from) / (arr.sec_to - arr.sec_from))) : 0;
  const left = arr.bars ? arr.bars - Math.min(arr.bars, Math.floor(f * arr.bars) + 1) : null;
  return html`<div class="c-next" style=${'--pc:' + PART_COLOR(arr.next)}><span class="c-lbl">Next</span><b>${arr.next}</b>
    <small>${arr.mode === 'foot' ? 'on the foot' : left != null ? (left ? 'in ' + left + ' bar' + (left > 1 ? 's' : '') : 'next bar') : ''}</small></div>`;
}
function Rail({ arr }) {
  const parts = arr.parts || [];
  if (!parts.length) return '';
  return html`<div class="c-rail">${parts.map((p, i) => html`<span class=${cls(i === arr.index && 'on')}
    style=${`flex:${Math.max(1, p.bars || 1)};background:${PART_COLOR(p.name)}`}>${p.name}</span>`)}</div>`;
}
function CountIn({ arr }) {
  if (!arr.counting) return '';
  return html`<div class="c-countin"><span class="c-lbl">Count-in</span><b>${arr.parts && arr.parts[0] ? arr.parts[0].name : ''}</b></div>`;
}
// ── 1. NOW (et ses deux variantes qui s'ouvrent seules) ─────────────────────────────────────────
function NowPage({ st, c }) {
  const arr = st.arrangement || {};
  const ln = c.lines[c.idx] || null;
  // LE BUDGET CPU (docs/cpu-budget.md §3, lot 4) : la même puce que /live sous le morceau, et sur les suivants — seulement
  // tendu ou rouge, jamais un chiffre ; un tap = la feuille, en lecture seule. AVANT les retours anticipés (règle des hooks).
  const nextLines = c.idx >= 0 ? c.lines.slice(c.idx + 1, c.idx + 4) : [];
  const cpu = useCpuMany([st.preset_id, ...nextLines.map(l => l && l.preset)]);
  const [cpuOpen, setCpuOpen] = useState(null);
  const now = useTick(500);                          // la barre de la partie en cours (ex-mode Song)
  const isShow = (st.mode || {}).id === 'show';
  // READY FOR THE SHOW : mode Show, rien n'a encore joué (on est sur la 1re chanson, ou sur rien)
  if (isShow && c.conductor && !arr.running && !arr.done && c.idx <= 0) return html`<${ReadyForShow} st=${st} c=${c} />`;
  // BETWEEN SONGS : le morceau vient de finir, ou le suivant est chargé et attend le départ
  const upcoming = arr.done ? c.lines[c.idx + 1] : (arr.present && !arr.running && c.idx >= 0 ? ln : null);
  if (upcoming) return html`<${BetweenSongs} st=${st} c=${c} next=${upcoming} loaded=${!arr.done} />`;
  const info = c.songOf(ln);
  const next = nextLines;
  // LA PARTIE EN COURS (ce que le mode Song montrait au musicien, 2026-11-26 : Song est fondu dans Control)
  const playing = arr.present && (arr.running || arr.counting);
  return html`<div class="c-page">
    ${playing ? html`<${CountIn} arr=${arr} />${arr.running && !arr.counting ? html`<${PartNow} arr=${arr} now=${now} /><${NextPart} arr=${arr} now=${now} />` : ''}` : ''}
    ${cpuOpen ? html`<${StageCpuSheet} preset=${cpuOpen.preset} title=${'CPU · ' + (cpuOpen.title || '')} onClose=${() => setCpuOpen(null)} />` : ''}
    <div class="c-card"><span class="c-lbl">Now${c.idx >= 0 ? ' · ' + (c.idx + 1) + ' / ' + c.lines.length : ''}${c.sl ? ' · ' + c.sl.name : ''}</span>
      <div class="c-big">${(ln && ln.title) || st.preset_name || 'No song'}</div>${info.artist ? html`<div class="c-sub">${info.artist}</div>` : ''}
      ${cpu[st.preset_id] ? html`<div class="c-cpu"><${StageChip} entry=${cpu[st.preset_id]}
        onOpen=${() => setCpuOpen({ preset: st.preset_id, title: (ln && ln.title) || st.preset_name })} /></div>` : ''}
      <div class="c-chips">
        <div class="c-chip"><small>BPM</small><b>${Math.round(st.tempo || 0)}</b></div>
        ${info.key ? html`<div class="c-chip"><small>KEY</small><b>${info.key}</b></div>` : ''}
        <div class="c-chip"><small>SCENE</small><b>${st.scene_id || '—'}</b></div>
        ${st.perf && st.perf.recording ? html`<div class="c-chip rec"><small>REC</small><b>●</b></div>` : ''}
      </div></div>
    ${c.lanes.length ? html`<div class="c-card"><span class="c-lbl">Your lines in this song</span>
      <${Acc} rows=${c.lanes.map(L => ({ id: L.id, role: L.role, state: L.state, implicit: L.implicit, mute: L.mute, name: L.name,
        glyph_type: (myRowsIn(c.current, st.scene_id, [L.id])[0] || {}).glyph_type, block: (myRowsIn(c.current, st.scene_id, [L.id])[0] || {}).block }))} /></div>`
      : c.person ? html`<div class="c-card"><span class="c-sub">None of your lines is in this song.</span></div>` : ''}
    <div class="c-card grow"><span class="c-lbl">Next up</span>
      ${next.length ? html`<div class="c-list">${next.map((l, i) => { const inf = c.songOf(l);
        return html`<div class=${cls('c-row', !l.preset && 'dim')}><span class="n">${String(c.idx + i + 2).padStart(2, '0')}</span>${c.titleOf(l)}
          <small>${l.preset && cpu[l.preset] ? html`<${StageChip} next entry=${cpu[l.preset]} onOpen=${() => setCpuOpen({ preset: l.preset, title: c.titleOf(l) })} />` : ''}${l.preset ? [l.bpm, inf.key].filter(Boolean).join(' · ') : 'no rig yet'}</small></div>`; })}</div>`
        : html`<p class="c-sub">${c.idx >= 0 ? 'End of the setlist.' : 'This preset is not in the setlist.'}</p>`}</div>
  </div>`;
}

function BetweenSongs({ st, c, next, loaded }) {
  const [nextMine, setNextMine] = useState(null);
  useEffect(() => {
    if (!next.preset) { setNextMine(null); return; }
    api('/api/lane/mine?preset=' + encodeURIComponent(next.preset) + (c.person ? '&person=' + encodeURIComponent(c.person) : '&role=' + encodeURIComponent(c.role || '')))
      .then(setNextMine).catch(() => {});
  }, [next.preset, c.person]);
  const info = c.songOf(next);
  const prev = c.lines[c.idx - (loaded ? 1 : 0)] || {};
  const nowRoles = new Set(c.lanes.map(L => L.role)), nextLanes = (nextMine && nextMine.lanes) || [];
  const nextRoles = new Set(nextLanes.map(L => L.role));
  const items = [];
  if ((next.tuning || 'standard') !== (prev.tuning || 'standard')) items.push({ ic: '♪', t: 'Tune to ' + (next.tuning || 'standard'), s: 'from ' + (prev.tuning || 'standard'), warn: true });
  else if (next.tuning) items.push({ ic: '♪', t: 'Tuning: ' + next.tuning, s: 'same' });
  if ((next.capo || 0) !== (prev.capo || 0)) items.push({ ic: '⊘', t: next.capo ? 'Capo on fret ' + next.capo : 'No capo', s: prev.capo ? 'was ' + prev.capo : '—', warn: true });
  [...nowRoles].filter(r => !nextRoles.has(r)).forEach(r => items.push({ ic: '⇄', t: (LANE_TAG[r] || r) + ': not in this song', s: 'put it down', warn: true }));
  [...nextRoles].filter(r => !nowRoles.has(r)).forEach(r => items.push({ ic: '⇄', t: (LANE_TAG[r] || r) + ': you play it in this song', s: 'pick it up', warn: true }));
  if (nextRoles.has('voice')) items.push({ ic: '◎', t: 'You sing', s: 'VOX' });
  if (next.note) items.push({ ic: '✎', t: next.note, s: '' });
  const parts = ((next.arrangement || {}).params || {}).sections || [];
  const ci = +(((next.arrangement || {}).params || {}).count_in) || 0;
  if (parts.length) items.push({ ic: '▶', t: 'Starts with the ' + parts[0].name, s: ci ? ci + ' bar' + (ci > 1 ? 's' : '') + ' count-in' : 'no count-in' });
  return html`<div class="c-page">
    ${loaded && st.loaded_by ? html`<div class="c-who">🎼 <span><b>${st.loaded_by}</b> loaded ${c.titleOf(next)} · ${st.rig_loading ? 'the rig is loading…' : 'the rig is ready'}</span></div>` : ''}
    <div class="c-card"><span class="c-lbl">${loaded ? 'Loaded · ready to start' : 'Song over · next'}</span>
      <div class="c-big">${c.titleOf(next) || '—'}</div>
      <div class="c-sub">${[info.artist, next.bpm ? next.bpm + ' BPM' : '', info.key].filter(Boolean).join(' · ')}</div></div>
    ${items.length ? html`<span class="c-lbl pad">Get ready</span><div class="c-list">${items.map(x => html`<div class=${cls('c-row', x.warn && 'warn')}><i>${x.ic}</i>${x.t}<small>${x.s}</small></div>`)}</div>` : ''}
    ${nextLanes.length ? html`<div class="c-card"><span class="c-lbl">Your lines in ${c.titleOf(next) || 'it'}</span>
      <${Acc} rows=${nextLanes.map(L => ({ id: L.id, role: L.role, state: L.state, implicit: L.implicit, name: L.name }))} /></div>` : ''}
  </div>`;
}

function ReadyForShow({ st, c }) {
  const now = useTick(1000);
  const rec = !!(st.perf && st.perf.recording);
  const first = c.lines.find(l => l.preset) || null;
  const loaded = first && (st.song || {}).line === first.id;
  const recSec = rec && st.perf.started_at ? Math.max(0, Math.floor(now - new Date(st.perf.started_at).getTime() / 1000)) : 0;
  const online = st.devices_online || [];
  const [err, setErr] = useState('');
  const act = async fn => { setErr(''); try { await fn(); } catch (e) { setErr((e.body && e.body.error) || String(e.message || e)); } };
  const load = () => act(() => post('/api/recall', { slot: c.lines.indexOf(first), confirm: true }));
  const start = () => act(async () => { if (!loaded) await post('/api/recall', { slot: c.lines.indexOf(first), confirm: true }); await post('/api/arrangement', { op: 'start' }); });
  return html`<div class="c-page">
    <div class="c-card"><span class="c-lbl">Show · ${c.sl ? c.sl.name : 'no setlist'} · ${c.lines.length} song${c.lines.length === 1 ? '' : 's'}</span><div class="c-big">Ready for the show</div></div>
    ${rec ? html`<div class="c-recbig"><span class="d"></span><b>Recording</b><small>${fmtT(recSec)}</small></div>
        <p class="c-sub pad">The take covers the whole show.</p>`
      : html`<div class="c-row warn"><i>●</i>Recording starts with song 1<small><button class="c-mini" onClick=${() => act(() => post('/api/perf/start', {}))}>Start now</button></small></div>`}
    <div class="c-list">
      <div class=${cls('c-row', loaded ? 'ok' : 'warn')}><i>${loaded ? '✓' : '!'}</i>${first ? c.titleOf(first) : 'No song'} ${loaded ? 'loaded' : 'not loaded'}
        <small>${loaded ? 'song 1' : html`<button class="c-mini" disabled=${!first || st.rig_loading} onClick=${load}>${st.rig_loading ? 'Loading…' : 'Load'}</button>`}</small></div>
      ${st.backing && st.backing.present ? html`<div class="c-row ok"><i>✓</i>Backing ready<small>${(st.backing.songs || []).length || ''}</small></div>` : ''}
      <div class=${cls('c-row', online.length ? 'ok' : 'warn')}><i>${online.length ? '✓' : '!'}</i>${online.length} device${online.length === 1 ? '' : 's'} connected
        <small>${online.map(d => d.person_name || d.name).slice(0, 3).join(', ')}</small></div>
    </div>
    ${err ? html`<p class="c-err">${err}</p>` : ''}
    <button class="c-start" disabled=${!first || st.rig_loading} onClick=${start}><b>▶ Start the show</b>
      <small>SONG 1 · ${first ? c.titleOf(first).toUpperCase() : '—'}</small></button>
  </div>`;
}

// ── 3. MINE ───────────────────────────────────────────────────────────────────────────────────
function MinePage({ st, c, onTuner }) {
  const [sel, setSel] = useState(null);
  const [err, setErr] = useState('');
  const lanes = c.lanes;
  if (!st.preset_id) return html`<div class="c-page"><p class="c-empty">No song loaded.</p></div>`;
  if (!lanes.length) return html`<div class="c-page"><p class="c-empty">${c.person ? 'None of your lines is in this song — your inputs are not on it, or no one set you on them.' : 'This song has no lane for this phone.'}</p></div>`;
  const L = lanes.find(x => x.id === sel) || lanes[0];
  const myTarget = c.person && (((st.compo || {}).targets) || {})[c.person];
  const tap = async b => { setErr(''); const r = await post('/api/lane/stomp', { block: b.id, on: !b.on }).catch(e => e.body || null);
    if (!r || r.ok === false) setErr((r && r.error) || 'the rack did not answer'); };
  const cur = L.midi ? (L.instruments || []).find(x => x.scene === st.scene_id) : null;
  return html`<div class="c-page">
    ${myTarget ? html`<div class="c-card c-compo" title="armed from golem.fm (Follow Golem): your next Riff tap writes into this song">
      <span class="c-lbl">🔥 Riff → ${myTarget.title || myTarget.id}</span><small>${myTarget.mode} · next tap goes there</small></div>` : ''}
    ${lanes.length > 1 ? html`<div class="c-seg">${lanes.map(x => html`<button class=${cls(x.id === L.id && 'on')} onClick=${() => setSel(x.id)}>
      <em class=${'c-tag ' + x.role}>${LANE_TAG[x.role] || x.role}</em>${x.name}</button>`)}</div>` : ''}
    ${L.midi ? html`
      <div class="c-card"><span class="c-lbl">Playing now · scene ${st.scene_id || '—'}</span>
        <div class="c-big">${cur && !cur.muted ? cur.name : 'muted'}</div>
        <div class="c-sub">${cur && !cur.muted ? cur.instrument + ' · ' + L.input : L.input}</div>
        ${cur && !cur.muted ? html`<div class="c-chips">
          ${cur.zone_lo != null || cur.zone_hi != null ? html`<div class="c-chip"><small>ZONE</small><b>${NOTE(cur.zone_lo) || '…'}–${NOTE(cur.zone_hi) || '…'}</b></div>` : ''}
          ${cur.transpose ? html`<div class="c-chip"><small>TRANSPOSE</small><b>${cur.transpose > 0 ? '+' : ''}${cur.transpose}</b></div>` : ''}</div>` : ''}</div>
      <div class="c-card"><span class="c-lbl">By scene</span><div class="c-list">${(L.instruments || []).map(x => html`<div class=${cls('c-row', x.muted && 'dim', x.scene === st.scene_id && 'cur')}>
        <span class="n">${x.scene}</span>${x.muted ? 'muted' : x.name}<small>${x.scene_name || ''}${x.scene === st.scene_id ? ' · now' : ''}</small></div>`)}</div></div>`
    : html`<div class="c-card slim"><span class="c-lbl">Scene ${st.scene_id || '—'}</span><div class="c-mid">${L.mute ? 'muted in this scene' : (L.state && !L.implicit ? L.state : 'this scene’s own settings')} <span class="c-sub">· ${L.input}</span></div></div>`}
    ${L.blocks.length ? html`<div class="c-pedals">${L.blocks.map(b => html`<button class=${cls('c-pd', b.on && 'on', b.live && 'live')} onClick=${() => tap(b)}>
      <span class="g">${ICON[b.type] || '•'}</span><b>${shortBlockName(b)}</b><small>${b.foot ? '#' + b.foot : 'TAP'} · ${b.on ? 'ON' : 'OFF'}</small></button>`)}</div>`
      : !L.capture_modules ? html`<p class="c-sub pad">No pedal to switch on this line.</p>` : ''}
    ${err ? html`<p class="c-err">${err}</p>` : ''}
    <${PhoneCaptures} preset=${st.preset_id} scene=${st.scene_id} lane=${L.id} />
    <div class="c-card slim row"><span class="c-lbl">Scene level</span><b class="right">${L.mute ? 'muted' : dbTxt(L.level)}</b></div>
    ${!L.midi && L.role !== 'voice' && L.role !== 'drums' ? html`<button class="c-btn wide" onClick=${onTuner}><b>♪ Tuner</b><small>listens to the rack's tuner input</small></button>` : ''}
  </div>`;
}

// ── 4. LYRICS ─────────────────────────────────────────────────────────────────────────────────
// Les paroles du morceau (backing/meta) ; si le texte porte des repères de partie (« [Chorus] »,
// « Verse 2: »), la partie EN COURS est mise en avant, et la suivante annoncée. Sinon, le texte entier.
const splitLyrics = txt => {
  const out = [];
  if (!String(txt || '').trim()) return out;       // pas de paroles = aucun bloc (un bloc vide cachait « No lyrics »)
  let cur = { name: null, lines: [] };
  String(txt || '').split('\n').forEach(raw => {
    const l = raw.trim();
    const m = l.match(/^\[([^\]]+)\]$/) || l.match(/^(intro|verse|pre-?chorus|chorus|bridge|solo|outro|refrain|couplet|pont)\s*\d*\s*:?$/i);
    if (m) { if (cur.lines.length || cur.name) out.push(cur); cur = { name: m[1], lines: [] }; }
    else cur.lines.push(l);
  });
  if (cur.lines.length || cur.name) out.push(cur);
  return out;
};
function LyricsPage({ st, c }) {
  const ln = c.lines[c.idx] || {};
  // le morceau : celui de la ligne, sinon la backing chargée, sinon la première du preset (une backing
  // pas encore chargée — mode sans service backing, rack qui démarre — reste la backing du morceau)
  const slug = ln.backing || (st.backing && st.backing.slug) || (((c.current || {}).backing) || [])[0];
  const [meta, setMeta] = useState(null);
  // la taille du texte vient du PROFIL golem.fm quand la personne en a un (docs/devices-people.md §8.1,
  // lecture seule au premier tour) ; A−/A+ la change pour cette session, sans rien réécrire là-bas
  const PREF_SIZE = { s: -1, m: 0, l: 1, xl: 2 };
  const fromPrefs = PREF_SIZE[((c.mine || {}).prefs || {}).lyrics_size];
  const [big, setBig] = useState(fromPrefs === undefined ? 0 : fromPrefs);
  const [touched, setTouched] = useState(false);
  useEffect(() => { if (!touched && fromPrefs !== undefined) setBig(fromPrefs); }, [fromPrefs]);
  useEffect(() => { setMeta(null); if (slug) api('/api/backing/meta/' + slug).then(setMeta).catch(() => setMeta({})); }, [slug]);
  const arr = st.arrangement || {};
  const blocks = splitLyrics(meta && meta.lyrics);
  // la partie en cours : le n-ième bloc du même nom que la n-ième occurrence de la partie dans l'arrangement
  const parts = arr.parts || [];
  const occ = arr.index >= 0 ? parts.slice(0, arr.index + 1).filter(p => p.name === arr.name).length : 0;
  let hit = -1, seen = 0;
  if (arr.running && arr.name) blocks.forEach((b, i) => { if (hit < 0 && b.name && b.name.toLowerCase().replace(/\s*\d+$/, '') === arr.name.toLowerCase()) { seen++; if (seen === occ) hit = i; } });
  const vox = c.lanes.find(L => L.role === 'voice');
  return html`<div class="c-page">
    <div class="c-chips">
      ${arr.running ? html`<div class="c-chip"><small>PART</small><b>${arr.name}</b></div>` : ''}
      ${vox ? html`<div class="c-chip"><small>VOX</small><b>${vox.mute ? 'muted' : (vox.state && !vox.implicit ? vox.state : '—')}</b></div>` : ''}
    </div>
    <div class=${cls('c-card grow c-lyrics', 'size' + big)}>
      ${!slug ? html`<p class="c-sub">No lyrics: this song has no backing track.</p>`
        : !meta ? html`<p class="c-sub">Loading…</p>`
        : !blocks.length ? html`<p class="c-sub">No lyrics for this song.</p>`
        : blocks.map((b, i) => html`<div class=${cls('c-lyr', hit === i && 'now', hit >= 0 && i === hit + 1 && 'next', hit >= 0 && i !== hit && i !== hit + 1 && 'far')}>
            ${b.name ? html`<span class="sec">${b.name}${hit === i ? ' · now' : hit >= 0 && i === hit + 1 && arr.next ? ' · next' : ''}</span>` : ''}
            ${b.lines.map(l => l ? html`<p>${l}</p>` : html`<p class="gap"> </p>`)}</div>`)}
    </div>
    <div class="c-ctl"><button class="c-btn" onClick=${() => { setTouched(true); setBig(Math.max(-1, big - 1)); }}><b>A− text</b></button><button class="c-btn" onClick=${() => { setTouched(true); setBig(Math.min(2, big + 1)); }}><b>A+ text</b></button></div>
  </div>`;
}

// ── 6. BEAT (un batteur sans entrée) ─────────────────────────────────────────────────────────
function BeatPage({ st, c }) {
  const now = useTick(80);
  const arr = st.arrangement || {};
  const [num, den] = String(arr.sig || '4/4').split('/').map(Number);
  const bpm = st.tempo || 120, beatSec = (60 / bpm) * (4 / (den || 4));
  const beat = arr.running && !arr.counting && arr.sec_from ? Math.floor(Math.max(0, now - arr.sec_from) / beatSec) % (num || 4) : -1;
  const bk = st.backing || {};
  const pos = bk.playing && bk.t ? (bk.pos || 0) + Math.max(0, now - bk.t) : (bk.pos || 0);
  return html`<div class="c-page">
    <div class="c-card row"><b class="c-huge">${Math.round(bpm)}</b><span class="c-lbl">BPM · ${arr.sig || '4/4'}</span></div>
    <div class="c-beats">${Array.from({ length: Math.min(num || 4, 7) }, (_, i) => html`<span class=${cls(i === beat && 'on', i === 0 && 'one')}>${i + 1}</span>`)}</div>
    <${CountIn} arr=${arr} />
    ${arr.running && !arr.counting ? html`<${PartNow} arr=${arr} now=${now} /><${NextPart} arr=${arr} now=${now} />` : html`<div class="c-card"><span class="c-lbl">${arr.done ? 'Song over' : 'Waiting for the start'}</span></div>`}
    ${bk.present ? html`<div class="c-card row"><span class="c-lbl">Backing</span><b>${bk.playing ? '▶ playing' : bk.paused ? '❚❚ paused' : '■ stopped'}</b><span class="c-sub right">${fmtT(pos)} / ${fmtT(bk.len)}</span></div>` : ''}
  </div>`;
}

// ── 7. TUNER ─────────────────────────────────────────────────────────────────────────────────
function TunerSheet({ st, c, onClose }) {
  const t = st.tuner || {};
  // L'ACCORDEUR DU RACK EST GLOBAL : il ne coupe pas le son (le JSFX laisse passer le signal), mais son
  // overlay couvre /live sur l'écran du rack. Depuis un téléphone on ne l'arme donc pas d'office pendant
  // un morceau, et on ne l'éteint en partant que si c'est CE téléphone qui l'a allumé.
  const playing = !!((st.arrangement || {}).running || (st.backing || {}).playing);
  const mineOn = useRef(false);
  const turnOn = () => { mineOn.current = true; post('/api/tuner', { on: true }).catch(() => {}); };
  useEffect(() => { if (!t.on && !playing) turnOn(); return () => { if (mineOn.current) post('/api/tuner', { on: false }).catch(() => {}); }; }, []);
  const active = t.active && t.note;
  const cents = Math.max(-50, Math.min(50, t.cents || 0));
  const ln = c.lines[c.idx] || {};
  return html`<div class="c-page">
    <div class=${cls('c-tuner', active && Math.abs(cents) < 5 && 'ok')}>
      <span class="c-lbl">${ln.tuning ? ln.tuning + ' tuning for this song' : 'Standard tuning'}</span>
      <b>${active ? t.note : '—'}${active ? html`<sub>${t.octave}</sub>` : ''}</b>
      <div class="c-needle"><i style=${'left:' + (50 + cents) + '%'}></i></div>
      <span class="c-sub">${active ? (cents > 0 ? '+' : '') + Math.round(cents) + ' cents' + (t.freq ? ' · ' + Number(t.freq).toFixed(1) + ' Hz' : '') : 'play a note'}</span>
    </div>
    ${!t.on ? html`<div class="c-row warn"><i>!</i>${playing ? 'A song is playing — the tuner covers the rack screen' : 'The tuner is off'}
      <small><button class="c-mini" onClick=${turnOn}>Turn on</button></small></div>` : ''}
    <p class="c-sub pad">The tuner listens to the lane that carries the tuner block on the rack, and shows on its screen too.</p>
    <button class="c-start" onClick=${onClose}><b>Done</b></button>
  </div>`;
}

// ── 9. REC ───────────────────────────────────────────────────────────────────────────────────
function RecPage({ st, c }) {
  const now = useTick(1000);
  const rec = !!(st.perf && st.perf.recording);
  const [mine, setMine] = useState([]);
  const [count, setCount] = useState(0);
  const [takes, setTakes] = useState([]);
  const [pop, setPop] = useState(false);
  const [err, setErr] = useState('');
  const loadFlags = () => api('/api/take/flags').then(d => { setMine(d.mine || []); setCount((d.flags || []).length); }).catch(() => {});
  useEffect(() => { loadFlags(); api('/api/loops').then(d => setTakes((d.takes || []).slice(0, 3))).catch(() => {}); }, [rec]);
  const flag = async () => {
    const r = await post('/api/take/flag', {}).catch(() => null);
    if (r && r.ok) { setPop(true); setTimeout(() => setPop(false), 350); loadFlags(); }
  };
  const secs = rec && st.perf.started_at ? Math.max(0, Math.floor(now - new Date(st.perf.started_at).getTime() / 1000)) : 0;
  const toggle = async () => { setErr(''); try { await post('/api/perf/' + (rec ? 'stop' : 'start'), {}); } catch (e) { setErr((e.body && e.body.error) || 'the rack refused'); } };
  return html`<div class="c-page">
    <div class="c-card row">${rec ? html`<span class="c-dotrec"></span><b>Recording</b><b class="right mono">${fmtT(secs)}</b>` : html`<b>Not recording</b>${st.rec_with_song ? html`<span class="c-sub right">starts with the song</span>` : ''}`}</div>
    <button class=${cls('c-flag', pop && 'pop')} disabled=${!rec} onClick=${flag}><b>⚑</b><span>Mark that</span><em>${count} mark${count === 1 ? '' : 's'} in this take</em></button>
    ${c.conductor ? html`<button class="c-btn wide" onClick=${toggle}><b>${rec ? '■ Stop recording' : '● Start recording'}</b><small>${rec ? 'ends the take' : 'the whole rehearsal or show'}</small></button>` : ''}
    ${err ? html`<p class="c-err">${err}</p>` : ''}
    ${mine.length ? html`<div class="c-card"><span class="c-lbl">Your marks</span><div class="c-list">${mine.slice(-4).map(f => html`<div class="c-row"><span class="n">⚑</span>${[f.song, f.part].filter(Boolean).join(' · ') || 'mark'}<small>${f.sec != null ? fmtT(f.sec) : ''}</small></div>`)}</div></div>` : ''}
    <div class="c-card"><span class="c-lbl">Last takes</span><div class="c-list">
      ${takes.length ? takes.map(t => { const m = t.manifest || {}; const fl = (m.flags || []).length;
        return html`<div class="c-row">${m.kind ? m.kind.charAt(0).toUpperCase() + m.kind.slice(1) : 'Take'} · ${(t.dir || '').replace(/^take-?/, '').slice(0, 13)}<small>${fl ? fl + ' ⚑' : ''}</small></div>`; })
        : html`<p class="c-sub">No take yet.</p>`}</div></div>
  </div>`;
}

// ── le shell : en-tête à deux icônes, le mode de Live, la page ──────────────────────────────────
const MODES = [
  ['now', 'Now', '≡', 'The song, your lines, what comes next.'],
  ['control', 'Control', '◫', 'Pick a setlist or a bank, then scenes and stomps. Drives the whole band.'],
  ['mine', 'Mine', '◉', 'Your pedals and your scene level, tuner.'],
  ['lyrics', 'Lyrics', '¶', "Follows the song's parts."],
  ['beat', 'Beat', '♩', 'The tempo and the parts, for a drummer without an input.'],
  ['rec', 'Rec', '⏺', 'Mark a moment in the take.'],
];
// les anciennes adresses (?tab=now, ?tab=song…) : la coquille `golem phone` et les écrans d'accueil les gardent
const LEGACY_TAB = { now: 'now', song: 'control', control: 'control', mine: 'mine', lyrics: 'lyrics', beat: 'beat', rec: 'rec', stage: 'mine' };
const MODE_KEY = 'golem.phone.mode';
const IcoLive = () => html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4v16M5 6h11l-2 4 2 4H5"/></svg>`;
const IcoSys = () => html`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>`;

// LA VUE HORIZONTALE DU MODE CONTROL (2026-11-26) : le téléphone couché montre la VRAIE page /live du rack (?embed=live :
// sans top menu, sans liens Designer/Songs/Library ni outils), cadrée et mise à l'échelle — mêmes cases, mêmes animations,
// mêmes flèches de bank. Hauteur logique 552 px (l'écran 1024×600 moins sa barre) ; la largeur suit le téléphone.
// Sans le droit conductor, un voile prend les touches : on regarde, on ne pilote pas (le rack refuse de toute façon).
const LIVE_H = 552;
function useLandscape() {
  const q = '(orientation: landscape) and (max-height: 600px)';
  const [on, setOn] = useState(() => { try { return matchMedia(q).matches; } catch (_) { return false; } });
  useEffect(() => { let m; try { m = matchMedia(q); } catch (_) { return; }
    const f = () => setOn(m.matches); m.addEventListener('change', f); return () => m.removeEventListener('change', f); }, []);
  return on;
}
function LiveLandscape({ canDrive }) {
  const [box, setBox] = useState({ w: innerWidth, h: innerHeight });
  useEffect(() => { const f = () => setBox({ w: innerWidth, h: innerHeight }); addEventListener('resize', f); return () => removeEventListener('resize', f); }, []);
  const k = box.h / LIVE_H, w = Math.round(box.w / k);
  return html`<div class="m-land">
    <iframe class="m-land-f" src="/app/?desktop=1&embed=live#/live" title="Live" style=${`width:${w}px;height:${LIVE_H}px;transform:scale(${k})`}></iframe>
    ${canDrive ? '' : html`<div class="m-land-veil"><span>🔒 View only: the conductor drives</span></div>`}
  </div>`;
}

function Companion() {
  useWakeLock();
  const { state: st, wsUp } = useRigState();
  setDisplay(st && st.display);                     // les animations de l'écran (Settings ▸ System ▸ Display)
  setFullscreenPref(st && st.display && st.display.fullscreen);   // le premier tap = plein écran (fullscreen.mjs)
  const c = useCompanion(st);
  const qp = new URL(location.href).searchParams;
  const t0 = qp.get('tab');
  const [tab, setTabState] = useState(t0 === 'system' ? 'system' : 'live');
  const [mode, setModeState] = useState(() => {
    const m = qp.get('mode') || LEGACY_TAB[t0];
    if (m) return m;
    try { return localStorage.getItem(MODE_KEY) || 'now'; } catch (_) { return 'now'; }
  });
  const [page, setPageState] = useState(t0 === 'system' ? qp.get('page') : null);
  const [sheet, setSheet] = useState(false);
  const [tuner, setTuner] = useState(false);
  // l'adresse suit l'écran : un rechargement (la coquille `golem phone`, un téléphone qui a dormi) revient au même
  // endroit ; la coquille en est prévenue pour son propre ↻
  const syncUrl = (t, m, pg) => {
    try {
      const u = new URL(location.href);
      u.searchParams.set('tab', t);
      if (t === 'live') { u.searchParams.set('mode', m); u.searchParams.delete('page'); }
      else { u.searchParams.delete('mode'); if (pg) u.searchParams.set('page', pg); else u.searchParams.delete('page'); }
      history.replaceState(null, '', u);
      if (parent !== window) parent.postMessage({ type: 'golem-tab', tab: t === 'live' ? m : 'system' }, location.origin);
    } catch (_) { /* aperçu hors origine : l'écran reste en mémoire */ }
  };
  const setTab = t => { setTabState(t); setTuner(false); syncUrl(t, mode, page); };
  const setMode = m => { setModeState(m); setSheet(false); setTuner(false); syncUrl('live', m, null);
    try { localStorage.setItem(MODE_KEY, m); } catch (_) { /* navigation privée */ } };
  const setPage = pg => { setPageState(pg); syncUrl('system', mode, pg); };
  // un appareil Drums a désormais SA lane (docs/drums-kit.md lot 0) : « pas de ligne » se lit dans les lanes, plus dans le rôle
  const noLines = !c.lanes.length && (c.mine && !c.person && !c.mine.lanes.length);
  const local = !!(c.who && c.who.local);
  const rights = local ? { control: true } : ((c.who && c.who.rights) || {});
  const avail = MODES.filter(([id]) => id === 'mine' ? c.lanes.length : id === 'lyrics' ? c.hasVoice : id === 'beat' ? noLines : true);
  const cur = avail.some(m => m[0] === mode) ? mode : (mode === 'mine' && !c.lanes.length ? 'control' : 'now');
  const curM = MODES.find(m => m[0] === cur);
  const signIn = () => { setTab('system'); setPage('account'); };
  const land = useLandscape();
  if (land && tab === 'live' && cur === 'control' && !tuner) return html`<${LiveLandscape} canDrive=${!!rights.control} />`;
  return html`
    <header class="m-head">
      <span class="m-mark" aria-label="golem"><span class="s">/</span><span class="g">golem</span><span class="cur">_</span></span>
      <span class="m-role">${c.personName}</span>
      <nav class="m-nav2">
        <button class=${cls('m-ni', tab === 'live' && 'on')} aria-label="Live" onClick=${() => setTab('live')}><${IcoLive} /></button>
        <button class=${cls('m-ni', tab === 'system' && 'on')} aria-label="System" onClick=${() => { setTab('system'); if (tab === 'system') setPage(null); }}><${IcoSys} /></button>
      </nav>
      <span class=${cls('m-ws', wsUp && 'up')} title=${wsUp ? 'live' : 'reconnecting…'}></span>
    </header>
    ${tab === 'live' ? html`<div class="m-sub">
      <button class="m-mode" onClick=${() => setSheet(true)}><i>${curM[2]}</i>${curM[1]}<small>▾</small></button>
      ${c.conductor && !(local && !qp.get('conductor')) ? html`<span class="c-condtag">CONDUCTOR</span>` : ''}
    </div>` : ''}
    <main class="m-main">
      ${tab === 'system' ? html`<${SystemPage} st=${st} who=${c.who} local=${local} page=${page} setPage=${setPage} reloadWho=${c.reloadWho} />`
      : tuner ? html`<${TunerSheet} st=${st} c=${c} onClose=${() => setTuner(false)} />`
      : cur === 'now' ? html`<${NowPage} st=${st} c=${c} />`
      : cur === 'control' ? html`<${ControlPage} st=${st} c=${c} rights=${rights} onTuner=${() => setTuner(true)} onSignIn=${local ? null : signIn} />`
      : cur === 'mine' ? html`<${MinePage} st=${st} c=${c} onTuner=${() => setTuner(true)} />`
      : cur === 'lyrics' ? html`<${LyricsPage} st=${st} c=${c} />`
      : cur === 'beat' ? html`<${BeatPage} st=${st} c=${c} />`
      : html`<${RecPage} st=${st} c=${c} />`}
    </main>
    ${sheet ? html`<div class="m-scrim" onClick=${() => setSheet(false)}></div>
      <div class="m-sheet" role="dialog" aria-label="Live mode">
        <span class="m-grab"></span><span class="c-lbl pad">Live mode on this phone</span>
        ${avail.map(([id, label, ico, sub]) => { const lk = id === 'control' && !rights.control;
          return html`<button class=${cls('m-mo', id === cur && 'on', lk && 'lk')} onClick=${() => setMode(id)}>
            <span class="ic">${ico}</span><div><b>${label}${lk ? ' 🔒' : ''}</b><small>${lk ? 'View only on this phone: the conductor drives.' : sub}</small></div>
            ${id === cur ? html`<span class="dot"></span>` : ''}</button>`; })}
      </div>` : ''}`;
}

// L'AFFICHAGE TABLETTE D'UN TÉLÉPHONE (docs/devices-people.md §4 ter, 2026-11-26) : des musiciens n'ont qu'un téléphone et
// veulent l'app complète. Couché, elle s'ouvre dans un cadre de 1024×600 mis à l'échelle (petit, mais permis) ; debout,
// on demande de le tourner. Les droits restent ceux d'un téléphone (le rack les décide par le type d'appareil). LA SORTIE
// est toujours à l'écran : la pastille 📱 ramène au Companion (règle du projet : jamais de mode sans sortie testée).
const APP_W = 1024, APP_H = 600;
function TabletDisplay() {
  const [box, setBox] = useState({ w: innerWidth, h: innerHeight });
  useEffect(() => { const f = () => setBox({ w: innerWidth, h: innerHeight }); addEventListener('resize', f); return () => removeEventListener('resize', f); }, []);
  const [busy, setBusy] = useState(false);
  const full = useFullscreen();
  const back = async () => { setBusy(true); try { await post('/api/auth/display', { display: 'phone' }); } catch (_) { /* la pastille reste */ }
    location.replace('/app/m.html'); };
  const land = box.w > box.h;
  const k = Math.min(box.w / APP_W, box.h / APP_H);
  return html`<div class="m-tab-host">
    ${land ? html`<iframe class="m-land-f" src="/app/?desktop=1#/live" title="golem"
        style=${`width:${APP_W}px;height:${APP_H}px;left:${Math.round((box.w - APP_W * k) / 2)}px;top:${Math.round((box.h - APP_H * k) / 2)}px;transform:scale(${k})`}></iframe>
      <button class="m-tab-back" disabled=${busy} onClick=${back} title="Back to the phone display" aria-label="Back to the phone display">📱</button>
      ${canFullscreen() ? html`<button class=${cls('m-tab-back m-tab-full', full && 'on')} onClick=${toggleFullscreen}
        title=${full ? 'Leave full screen' : 'Full screen'} aria-label=${full ? 'Leave full screen' : 'Full screen'}>⛶</button>` : ''}`
    : html`<div class="m-turn"><div class="m-turn-ico">⟳</div><b>Turn your phone sideways</b>
        <span>This phone shows the tablet display: the full golem app, made smaller.</span>
        <button class="c-btn wide" disabled=${busy} onClick=${back}><b>Back to the phone display</b><small>the Companion</small></button></div>`}
  </div>`;
}

function Root() {
  const [who, setWho] = useState(null);
  useEffect(() => { api('/api/auth/whoami').then(setWho).catch(() => setWho({})); }, []);
  if (!who) return '';
  if (!who.local && who.device && who.device.display === 'tablet') return html`<${TabletDisplay} />`;
  return html`<${Companion} />`;
}

export function mountCompanion(el) {
  watchErrors('companion');                  // docs/diagnostics.md §7.2
  startAnimStepper();                        // les animations infinies au pas (le téléphone aussi : sa batterie)
  startAutoFullscreen();                     // le premier tap = plein écran, si le rack le veut (Settings ▸ System ▸ Display)
  render(html`<${Root} />`, el);
}

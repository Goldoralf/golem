// SPDX-License-Identifier: GPL-3.0-or-later
// Companion ▸ Live ▸ CONTROL — le téléphone pilote /live (docs/devices-people.md §4, maquettes validées le 2026-11-26,
// artifact « Companion · Live et System », C1-C4). Trois niveaux, dans l'ordre du rack : la LISTE AU PIED (setlist ou
// bank), ses LIGNES (un preset ou un patch), puis l'écran de jeu — le miroir du FCB retourné pour le pouce : les scènes
// en bas, sous le pouce, les cinq stomps au-dessus. Charger, une scène, un stomp : le son de TOUT le groupe, donc un
// geste de conductor (auth._conductor_path). Sans ce droit, le même écran grisé, et pourquoi.
import { html, useState, useEffect, useRef, post, cls } from './lib.js';
import { ICON, shortBlockName, animClass, animPackOf, ensurePackCss } from './designer-model.js';
import { tilesStill } from './anim-stepper.mjs';
import { loadTileAnims } from './anim-tiles.mjs';

const api = p => fetch(p).then(r => { if (!r.ok) throw new Error(p); return r.json(); });
const errOf = e => (e && e.body && e.body.error) || String((e && e.message) || e);

// l'état VRAI d'un bloc de service posé sur un stomp — même règle que /live (page-live.js, SVC_STATE) :
// `state.stomps` dit « activé dans la scène », toujours vrai pour un service ; ce qui compte, c'est qu'il joue
const SVC_STATE = {
  standard: st => !!(st.standard && st.standard.playing),
  click: st => !!(st.click && st.click.on),
  tuner: st => !!(st.tuner && st.tuner.on),
  rec: st => !!(st.perf && st.perf.recording),
  drums: (st, b) => !!(((st.drums || {})[b.id]) || {}).playing,
  sample: (st, b) => !!(((st.samples || {})[b.id]) || {}).playing,
};
const stompOn = (st, sw) => {
  const svc = (sw.blocks || []).find(b => SVC_STATE[b.type]);
  return svc ? SVC_STATE[svc.type](st, svc) : !!(st.stomps || {})[String(sw.sw)];
};
const stompName = sw => {
  const bs = sw.blocks || [];
  if (!bs.length) return null;
  const n = shortBlockName(bs[0]) || bs[0].type;
  return bs.length > 1 ? n + ' +' + (bs.length - 1) : n;
};

// STOP par appui long (0,6 s), comme le switch et le mode Song d'avant
function Hold({ label, sub, onHold }) {
  const [p, setP] = useState(false);
  const t = useRef(null);
  const down = () => { setP(true); t.current = setTimeout(() => { setP(false); onHold(); }, 600); };
  const up = () => { setP(false); clearTimeout(t.current); };
  return html`<button class=${cls('c-hold', 'stop', p && 'pressing')} onPointerDown=${down} onPointerUp=${up} onPointerLeave=${up} onPointerCancel=${up}>
    <b>${label}</b><small>${sub}</small></button>`;
}

// ── LE TRANSPORT DU MORCEAU (l'ancien mode Song, fusionné ici : un seul écran charge un morceau) ─────────────────
function Transport({ st, title, act }) {
  const arr = st.arrangement || {};
  const running = arr.running || arr.counting;
  const isShow = (st.mode || {}).id === 'show';
  const [recWith, setRecWith] = useState(false);
  if (running) return html`<div class="c-ctl">
    ${arr.mode === 'foot' ? html`<button class="c-btn" onClick=${() => act(() => post('/api/arrangement', { op: 'next' }))}><b>⏭ Next part</b><small>${arr.next || 'last part'}</small></button>`
      : html`<button class="c-btn" disabled><b>↻ ${arr.name || 'Playing'}</b><small>parts follow the bars</small></button>`}
    <${Hold} label="■ Hold to stop" sub="0.6 s" onHold=${() => act(() => post('/api/arrangement', { op: 'stop' }))} /></div>`;
  if (!arr.present) return '';
  return html`<button class="c-start" disabled=${st.rig_loading || arr.allowed === false}
      onClick=${() => act(() => post('/api/arrangement', { op: 'start', rec: recWith && !isShow }))}>
      <b>▶ Start ${title || ''}</b>
      <small>${st.rig_loading ? 'THE RIG IS LOADING…' : arr.allowed === false ? 'THE ARRANGEMENT IS OFF IN THIS MODE'
        : [(arr.parts || []).length + ' PARTS', Math.round(st.tempo || 0) + ' BPM'].join(' · ')}</small></button>
    ${isShow ? '' : html`<button class="c-opt" onClick=${() => setRecWith(!recWith)}><i class=${recWith ? 'on' : ''}></i>Record with the song<small>rehearsal</small></button>`}`;
}

export function ControlPage({ st, c, rights, onTuner, onSignIn }) {
  const canDrive = !!(rights && rights.control);
  const [lists, setLists] = useState(null);
  const [foot, setFoot] = useState(null);                // /api/foot-list : la liste que le pied joue, ses lignes
  const [trial, setTrial] = useState(null);              // un patch joué (`patch:<id>`) n'est pas dans /api/presets
  // la vue par défaut se décide quand l'état arrive (le WebSocket suit le 1er rendu) : un morceau chargé = l'écran de jeu
  const [picked, setView] = useState(null);
  const view = picked || (st.preset_id ? 'play' : 'lists');
  const [kind, setKind] = useState('songs');
  const [openId, setOpenId] = useState(null);            // la liste ouverte dans « lines »
  const [arm, setArm] = useState(null);                  // 1er tap armé : changer la liste du pied, ou arrêter le morceau
  const [err, setErr] = useState('');
  const act = async fn => { setErr(''); try { await fn(); return true; } catch (e) { setErr(errOf(e)); return false; } };

  const listKey = [(st.song || {}).setlist, st.library_rev].join('|');
  useEffect(() => { api('/api/setlists').then(setLists).catch(() => setLists({ setlists: [] }));
    api('/api/foot-list').then(setFoot).catch(() => {}); }, [listKey]);
  const isTrial = st.preset_id === 'sandbox-try' || String(st.preset_id || '').startsWith('patch:');
  useEffect(() => { if (!isTrial) { setTrial(null); return; }
    fetch('/api/live/trial').then(r => r.ok ? r.json() : null).then(setTrial).catch(() => setTrial(null)); }, [st.preset_id, st.sandbox_rev]);
  useEffect(() => { if (err) { const t = setTimeout(() => setErr(''), 6000); return () => clearTimeout(t); } }, [err]);
  useEffect(() => { loadTileAnims(); }, []);
  const animKey = JSON.stringify(((c.presets || []).find(p => p.id === st.preset_id) || trial || {}).anims || {});
  useEffect(() => { Object.values(JSON.parse(animKey)).forEach(v => ensurePackCss(animPackOf(v))); }, [animKey]);

  const sets = (lists && lists.setlists) || [];
  const activeId = (foot && foot.id) || (lists && lists.active);
  const kindOf = s => (s.kind === 'sounds' ? 'sounds' : 'songs');
  const current = (c.presets || []).find(p => p.id === st.preset_id) || (trial && trial.scenes ? trial : null);
  const flines = (foot && foot.lines) || [];
  const playable = l => !!(l && (l.patch || (l.preset && (c.presets || []).some(p => p.id === l.preset))));
  const lineSlot = st.song && st.song.line ? flines.findIndex(l => l.id === st.song.line) : -1;
  const titleOf = l => !l ? '' : (l.title || ((c.presets || []).find(p => p.id === l.preset) || {}).name || l.patch || l.preset || 'New song');

  // CHARGER UNE LIGNE : dans la liste du pied, c'est le geste de ◀ ▶ ; dans une autre liste, la liste du pied change
  // d'abord (2 taps, comme /live : « ce soir je joue le set du Bar du Port » se confirme). Pendant un morceau, le rack
  // répond 409 « loading stops it » : le 2e tap confirme.
  const loadLine = async (list, i) => {
    if (!canDrive) return;
    const key = list.id + '#' + i;
    const other = list.id !== activeId;
    const confirm = arm === 'stop:' + key;
    if (other && arm !== key && !confirm) {           // 1er tap dans une autre liste : armer
      setArm(key); setTimeout(() => setArm(a => a === key ? null : a), 3000); return;
    }
    setArm(null);
    const ok = await act(async () => {
      let slot = i;
      if (other) {
        await post('/api/setlists/' + list.id + '/activate');
        const fl = await api('/api/foot-list');
        setFoot(fl);
        const id = ((list.lines || [])[i] || {}).id;
        const k = (fl.lines || []).findIndex(l => l.id === id);
        slot = k >= 0 ? k : i;
      }
      try { await post('/api/recall', { slot, ...(confirm ? { confirm: true } : {}) }); }
      catch (e) { if (e.body && e.body.confirm) { setArm('stop:' + key); throw new Error('A song is playing. Tap again to stop it and load.'); } throw e; }
    });
    if (ok) setView('play');
  };
  // ◀ ▶ : les lignes JOUABLES de la liste du pied, dans l'ordre des banks (live-bankbar.js)
  const step = d => {
    if (!canDrive) return;
    const slots = flines.map((l, i) => playable(l) ? i : -1).filter(i => i >= 0);
    if (!slots.length) return;
    const k = slots.indexOf(lineSlot);
    const nxt = k < 0 ? slots[d > 0 ? 0 : slots.length - 1] : slots[(k + d + slots.length) % slots.length];
    act(() => post('/api/recall', { slot: nxt }).catch(e => { if (e.body && e.body.confirm) throw new Error('A song is playing — stop it first, or load from the list.'); throw e; }));
  };
  const scene = id => canDrive && id !== st.scene_id && act(() => post('/api/recall', { scene: id }));
  const stomp = sw => canDrive && act(() => post('/api/stomp', { switch: sw }));

  const lock = !canDrive ? html`<div class="cc-lock"><i>🔒</i><div><b>This phone can watch, not drive.</b>
      <span>Scenes, stomps and loading a song change the sound for the whole band. Ask for the conductor right on the rack
      (Settings ▸ Connect ▸ Devices), or sign in with golem.fm as the band's owner.</span></div></div>` : '';
  const errLine = err ? html`<p class="c-err">${err}</p>` : '';

  // ── C1 · LES LISTES ──
  if (view === 'lists') {
    const grp = sets.filter(s => kindOf(s) === kind);
    return html`<div class="c-page">
      ${lock}
      <div class="c-seg">${[['songs', '▤ Setlists'], ['sounds', '⛓ Banks']].map(([k, lb]) => html`<button class=${cls(kind === k && 'on')} onClick=${() => setKind(k)}>${lb}</button>`)}</div>
      <div class="c-list">${grp.map(s => html`<button class=${cls('c-row', 'cc-tap', s.id === activeId && 'cur')} onClick=${() => { setOpenId(s.id); setView('lines'); }}>
          <span class="cc-t">${s.id === activeId ? html`<b>${s.name}</b>` : s.name}</span>
          <small>${s.count ?? (s.lines || []).length} ${kind === 'sounds' ? 'sound' : 'song'}${(s.count ?? (s.lines || []).length) === 1 ? '' : 's'}${s.id === activeId ? ' · on the foot' : ''}</small><em class="cc-go">›</em></button>`)}
        ${!grp.length ? html`<p class="c-sub pad">${lists ? (kind === 'sounds' ? 'No bank yet.' : 'No setlist yet.') : 'Loading…'}</p>` : ''}</div>
      <p class="c-sub pad">“On the foot” is the list the pedalboard plays. Opening another one changes nothing until you load a line from it.</p>
      ${st.preset_id ? html`<button class="c-btn wide" onClick=${() => setView('play')}><b>Play ${current ? current.name : ''} →</b><small>scenes and stomps</small></button>` : ''}
    </div>`;
  }

  // ── C2 · LES LIGNES ──
  if (view === 'lines') {
    const list = sets.find(s => s.id === (openId || activeId)) || null;
    const lines = (list && list.lines) || [];
    const isFoot = list && list.id === activeId;
    const curIdx = isFoot ? lines.findIndex(l => st.song && l.id === st.song.line) : -1;
    const curLine = curIdx >= 0 ? lines[curIdx] : null;
    return html`<div class="c-page">
      <div class="cc-crumb"><button class="c-mini" onClick=${() => setView('lists')}>‹ ${list && list.kind === 'sounds' ? 'Banks' : 'Setlists'}</button>
        <b>${list ? list.name : '—'}</b>${isFoot ? html`<small>on the foot</small>` : ''}</div>
      ${lock}
      <div class="c-list cc-lines">${lines.map((l, i) => { const key = list.id + '#' + i, cur = i === curIdx;
        const ok = l.patch || l.preset;
        return html`<button class=${cls('c-row', 'cc-tap', cur && 'cur', !ok && 'dim')} disabled=${!ok || !canDrive}
            onClick=${() => loadLine(list, i)}>
          <span class="n">${String(i + 1).padStart(2, '0')}</span><span class="cc-t">${cur ? html`<b>${titleOf(l)}</b>` : titleOf(l)}</span>
          <small class=${cls(arm === key && 'cc-arm', arm === 'stop:' + key && 'cc-stop', cur && 'cc-ok')}>${arm === key ? 'tap again: play this list'
            : arm === 'stop:' + key ? 'tap again: stop & load' : cur ? (st.rig_loading ? 'loading…' : 'loaded') : !ok ? 'no rig yet' : (l.bpm || '')}</small></button>`; })}
        ${!lines.length ? html`<p class="c-sub pad">${list ? 'This list is empty.' : 'Loading…'}</p>` : ''}</div>
      ${errLine}
      ${canDrive && curLine ? html`<${Transport} st=${st} title=${titleOf(curLine)} act=${act} />` : ''}
      ${st.preset_id ? html`<button class="c-btn wide" onClick=${() => setView('play')}><b>Play it →</b><small>scenes and stomps</small></button>` : ''}
    </div>`;
  }

  // ── C3 · L'ÉCRAN DE JEU ──
  const scenes = (current && current.scenes) || [];
  const colors = (current && current.colors) || {};
  // LES ANIMATIONS DES CASES (2026-11-26) : celles du preset (preset.anims[scène|switch]), comme sur /live — sauf cases
  // figées (Settings ▸ System ▸ Display : Off). Le téléphone n'est pas la machine qui joue le son : « Auto » anime.
  const anims = (current && current.anims) || {};
  const disp = st.display || {};
  const still = tilesStill({ local: false, display: { animations: disp.animations || 'auto', blinks: disp.blinks !== false } });
  const vu = (st.levels && (st.levels.in1 ?? st.levels.guitar)) || 0;
  const tile = (anim, color) => ({ cls: still ? '' : animClass(anim),
    style: '--c:' + color + ';--pc:' + color + (!still && (anim === 'vu' || String(anim || '').includes('/')) ? ';--vu:' + vu : '') });
  const switches = ((current && current.switches) || []).filter(sw => sw.sw >= 6 && sw.sw <= 10);
  const footName = foot ? foot.name : '';
  const bankLbl = (foot && foot.kind === 'sounds' ? 'Bank ' : 'Song ') + (lineSlot >= 0 ? String(lineSlot + 1).padStart(2, '0') : '—');
  const arr = st.arrangement || {};
  const title = (st.song && st.song.title) || (current && current.name) || st.preset_name || 'Nothing loaded';
  return html`<div class="c-page cc-play">
    ${lock}
    <div class=${cls('cc-now', !canDrive && 'cc-ghost')}>
      <button class="cc-arrow" aria-label="previous" onClick=${() => step(-1)}>◀</button>
      <button class="cc-title" onClick=${() => { setOpenId(activeId); setView('lines'); }}>
        <span class="c-lbl">${bankLbl}${footName ? ' · ' + footName : ''}</span><b>${title} ▾</b></button>
      <button class="cc-arrow" aria-label="next" onClick=${() => step(1)}>▶</button>
    </div>
    ${!current ? html`<p class="c-empty">${st.preset_id ? 'Loading the song…' : 'No song loaded. Pick one from a setlist or a bank.'}</p>
        <button class="c-btn wide" onClick=${() => setView('lists')}><b>Setlists and banks</b></button>` : html`
    <span class="c-lbl pad">Stomps</span>
    <div class=${cls('cc-stomps', !canDrive && 'cc-ghost')}>
      ${switches.map(sw => { const nm = stompName(sw), on = nm && stompOn(st, sw), b0 = (sw.blocks || [])[0];
        const t = tile(nm ? anims[sw.sw] || anims[String(sw.sw)] : '', colors[String(sw.sw)] || '#3fb96a');
        return html`<button class=${cls('cc-st', on && 'on', nm && !on && 'dim', !nm && 'empty', t.cls)} style=${t.style}
            disabled=${!nm} onClick=${() => nm && stomp(sw.sw)}>
          <span class="sw">SW ${sw.sw}</span><span class="g">${b0 ? (ICON[b0.type] || '') : ''}</span><b>${nm || 'empty'}</b><small>${nm ? (on ? 'ON' : 'OFF') : ''}</small></button>`; })}
      <button class="cc-st cc-tool" onClick=${onTuner}><span class="sw">—</span><span class="g">♪</span><b>Tuner</b><small>open</small></button>
    </div>
    <span class="c-lbl pad cc-push">Scenes</span>
    <div class=${cls('cc-scenes', !canDrive && 'cc-ghost')} style=${'grid-template-columns:repeat(' + Math.max(1, Math.min(scenes.length, 5)) + ',1fr)'}>
      ${scenes.slice(0, 8).map(s => { const t = tile(anims[s.id], colors[s.id] || '#c9722e');
        return html`<button class=${cls('cc-sc', s.id === st.scene_id ? 'on' : 'dim', t.cls)} style=${t.style}
          onClick=${() => scene(s.id)}><b>${s.id}</b><small>${s.name || ''}</small></button>`; })}
    </div>`}
    ${errLine}
    <div class="cc-foot">
      <div class="c-chip"><small>BPM</small><b>${Math.round(st.tempo || 0) || '—'}</b></div>
      <div class="c-chip"><small>PART</small><b>${arr.running ? (arr.name || '—') : arr.counting ? 'count-in' : '—'}</b></div>
      ${st.perf && st.perf.recording ? html`<div class="c-chip rec"><small>REC</small><b>●</b></div>` : ''}
    </div>
    ${!canDrive && onSignIn ? html`<button class="c-btn wide" onClick=${onSignIn}><b>Sign in with golem.fm</b></button>` : ''}
  </div>`;
}

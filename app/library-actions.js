// SPDX-License-Identifier: GPL-3.0-or-later
// LIBRARY : LISTEN · PLAY IT · ADD TO… (docs/library-play.md, maquette validée le 2026-11-15). Sur chaque fiche — une
// capture, un son clavier, un kit — les trois mêmes gestes :
//   Listen   la démo rendue (une phrase de référence), sans rien brancher : la fiche la fournit ;
//   Play it  TON instrument sur le son BRUT : un rig d'essai d'une lane, l'instrument branché (POST /api/library/try) ;
//            le patch est mis de côté, Stop le rend ; sans appareil, le bouton le dit ;
//   Add to…  où le mettre : le patch édité, un nouveau patch, un patch ou un morceau existant (et sa lane) — on arrive
//            dans le Designer avec le changement en brouillon, rien n'est écrit avant d'enregistrer.
import { html, useState, useEffect, useRef, cls, esc, post, openInDesigner, getCatalog } from './lib.js';
import { patchDraft } from './designer-model.js';
import { lanesAfter, addLaneState, namVariant } from './cpu-budget.js';   // docs/cpu-budget.md, lot 3

const j = u => fetch(u).then(r => r.json());

/** l'essai d'un son : ce qu'il faut pour le jouer (check), l'état (on), jouer/arrêter */
export function usePlayIt(item) {
  const key = JSON.stringify(item || null);
  const [check, setCheck] = useState(null);
  const [st, setSt] = useState({ on: false, busy: false, err: null, name: null, device: null });
  const mine = useRef(false);
  useEffect(() => {
    if (!item) return;
    let gone = false;
    const look = () => post('/api/library/try/check', { item }).then(r => { if (!gone) setCheck(r); }).catch(() => {});
    look();
    const t = setInterval(look, 4000);               // un appareil branché pendant qu'on regarde : le bouton s'allume
    return () => { gone = true; clearInterval(t); };
  }, [key]);
  useEffect(() => {                                   // un rappel ailleurs (pied, écran) remplace l'essai : on le voit
    const t = setInterval(() => j('/api/library/try').then(r => { if (mine.current && !r.on) { mine.current = false; setSt(s => ({ ...s, on: false })); } }).catch(() => {}), 3000);
    return () => { clearInterval(t); if (mine.current) post('/api/library/try/stop', {}).catch(() => {}); };
  }, []);
  const play = async it => {
    setSt(s => ({ ...s, busy: true, err: null }));
    try {
      const r = await post('/api/library/try', { item: it || item });
      mine.current = true;
      setSt({ on: true, busy: false, err: null, name: r.name, device: r.device });
    } catch (e) { setSt(s => ({ ...s, busy: false, err: (e.body && e.body.error) || 'Could not reach golem.' })); }
  };
  const stop = async () => {
    mine.current = false;
    setSt(s => ({ ...s, on: false, busy: true }));
    await post('/api/library/try/stop', {}).catch(() => {});
    setSt(s => ({ ...s, busy: false }));
  };
  return { check, st, play, stop };
}

/** le bandeau de l'essai en cours */
export const PlayBanner = ({ pi }) => pi.st.on ? html`<div class="la-banner" role="status">
    <b class="tn-eq" aria-hidden="true"><i></i><i></i><i></i></b>
    <span><b>Playing it:</b> ${esc(pi.st.device || 'your instrument')} → ${esc(pi.st.name || '')}, raw. Your patch is paused.</span>
    <button class="la-stop" onClick=${pi.stop}>Stop</button></div>`
  : pi.st.err ? html`<div class="la-banner ko" role="alert"><span>${esc(pi.st.err)}</span></div>` : '';

/** la barre du bas : Listen · Play it · Add to… */
export function ActionBar({ pi, item, onListen, listening, listenOff, extra }) {
  const [sheet, setSheet] = useState(false);
  const ok = pi.check && pi.check.ok;
  return html`<div class="la-bar">
    ${onListen ? html`<button class=${cls('la-btn', listening && 'on')} disabled=${listenOff} onClick=${onListen}>${listening ? html`<b class="tn-eq" aria-hidden="true"><i></i><i></i><i></i></b>` : html`<span class="ky-play">▶</span>`} Listen</button>` : ''}
    <button class=${cls('la-btn', pi.st.on && 'on', !ok && 'off')} disabled=${!ok || pi.st.busy}
      title=${ok ? 'play it with ' + (pi.check.name || 'your instrument') : (pi.check && pi.check.why) || ''}
      onClick=${() => pi.st.on ? pi.stop() : pi.play()}>◉ ${pi.st.busy ? '…' : pi.st.on ? 'Stop' : ok ? 'Play it' : 'Play it · ' + (pi.check && pi.check.role === 'drums' ? 'plug a kit' : pi.check && pi.check.role === 'keys' ? 'plug a keyboard' : 'no input')}</button>
    <span class="la-hint">${ok ? (pi.st.on ? '' : 'Play it = ' + (pi.check.name || 'your instrument') + ', on the raw sound') : (pi.check && pi.check.why) || ''}</span>
    ${extra || ''}
    <button class="primary la-add" onClick=${() => setSheet(true)}>Add to…</button>
    ${sheet ? html`<${AddToSheet} item=${item} onClose=${() => setSheet(false)} />` : ''}
  </div>`;
}

const roleFits = (role, laneRole) => laneRole === role || (role === 'bass' && laneRole === 'guitar');
const ROLE_NAME = { guitar: 'guitar', bass: 'bass', keys: 'keys', drums: 'drums' };

/** « Add to… » : le patch édité, un nouveau patch, un patch ou un morceau existant */
export function AddToSheet({ item, onClose }) {
  const [info, setInfo] = useState(null);             // {doc, block, role, name}
  const [sb, setSb] = useState(null);                 // le brouillon du Designer
  const [step, setStep] = useState('main');
  const [tab, setTab] = useState('songs');
  const [q, setQ] = useState('');
  const [lists, setLists] = useState({ patches: [], presets: [] });
  const [pick, setPick] = useState(null);             // {kind: 'patch'|'song', x, lanes?}
  const [lane, setLane] = useState(null);
  const [err, setErr] = useState(null);
  // LE BUDGET CPU (docs/cpu-budget.md §3, maquette Amps) : une lane que la capture pousserait dans le rouge est grisée, et
  // la raison est écrite. {laneId: pct} pour le morceau choisi, et pour le patch édité (la sandbox). Sans les routes
  // /api/cpu/* ou sans profil, rien n'est grisé.
  const [after, setAfter] = useState({});
  const [draftAfter, setDraftAfter] = useState({});
  const cpuItem = async () => {
    const b = (info && info.block) || {};
    let variant = null;
    if (/-nam$/.test(b.type || '') && item && item.capture != null) {
      const cat = await getCatalog().catch(() => null);
      const tone = ((cat && cat.tones) || []).find(t => String(t.id) === String(item.capture));
      const m = tone && (tone.models || []).find(x => String(x.id) === String(item.model));
      if (m) variant = namVariant(m);
    }
    return { type: b.type, ref: b.ref != null ? b.ref : item && item.capture, model: b.model != null ? b.model : item && item.model, variant };
  };
  useEffect(() => {
    post('/api/library/patch-doc', { item }).then(setInfo).catch(e => setErr((e.body && e.body.error) || 'Could not reach golem.'));
    j('/api/sandbox').then(setSb).catch(() => {});
  }, []);
  useEffect(() => {
    if (!info || !sb || !sb.preset) return;
    let live = true;
    cpuItem().then(it => lanesAfter('sandbox', sb.preset, it)).then(m => { if (live) setDraftAfter(m); }).catch(() => {});
    return () => { live = false; };
  }, [info, sb]);
  useEffect(() => {
    if (step !== 'pick' || lists.loaded) return;
    Promise.all([j('/api/patches').catch(() => ({})), j('/api/presets').catch(() => [])])
      .then(([pa, pr]) => setLists({ loaded: true, patches: (pa && pa.patches) || [], presets: Array.isArray(pr) ? pr : [] }));
  }, [step]);
  if (!info) return html`<div class="la-sheet-bg" onClick=${onClose}><div class="la-sheet"><div class="muted">${err || '…'}</div></div></div>`;
  const role = info.role;
  const act = { kind: 'block', role, block: info.block };
  const draft = sb && sb.preset;
  const draftLane = draft && (draft.lanes || []).find(L => roleFits(role, L.role || L.in_role));
  const draftCpu = draftLane ? addLaneState(draftAfter[draftLane.id]) : { disabled: false, why: '' };
  const go = (fn) => { onClose(); fn(); };
  const close = html`<button class="la-x" aria-label="Close" onClick=${onClose}>×</button>`;
  if (step === 'main') return html`<div class="la-sheet-bg" onClick=${e => e.target === e.currentTarget && onClose()}><div class="la-sheet">
    <div class="la-sheet-hd"><b>Add ${esc(info.name)} to…</b><span class="muted">${esc(info.block.type)} · ${ROLE_NAME[role] || role}</span>${close}</div>
    <div class="la-dests">
      <button class="la-dest on" disabled=${!draftLane || draftCpu.disabled} onClick=${() => go(() => openInDesigner(null, null, act))}>
        <small>The patch you're editing</small><b>${esc((draft && (draft.name || '').replace(/^⛓\s*/, '')) || 'Nothing open')}</b>
        <span class=${draftCpu.why ? 'cpu-why lv-' + draftCpu.level : ''}>${draftLane ? (draftCpu.why ? 'CPU: its ' + (draftLane.name || role) + ' lane ' + draftCpu.why + '.' : 'Its ' + (draftLane.name || role) + ' lane takes it. Opens the Designer on it.') : 'It has no ' + (ROLE_NAME[role] || role) + ' lane.'}</span></button>
      <button class="la-dest" onClick=${() => go(() => openInDesigner(patchDraft(info.doc)))}>
        <small>A new patch</small><b>New ${ROLE_NAME[role] || role} patch</b>
        <span>A blank ${ROLE_NAME[role] || role} patch with this sound in it. You name it when you save.</span></button>
      <button class="la-dest" onClick=${() => setStep('pick')}>
        <small>A patch or a song</small><b>Pick one…</b><span>Any patch, or a song and the lane it goes to.</span></button>
    </div>
    <div class="muted la-foot">Wherever it goes, you land in the Designer with the change as a draft: nothing is written until you save.</div>
  </div></div>`;
  const ql = q.toLowerCase();
  const patches = lists.patches.filter(x => roleFits(role, x.role) && (!q || (x.name || '').toLowerCase().includes(ql)));
  const presets = lists.presets.filter(x => !q || (x.name || '').toLowerCase().includes(ql));
  const choose = async (kind, x) => {
    setLane(null);
    if (kind === 'patch') return setPick({ kind, x });
    const d = await j('/api/preset/' + encodeURIComponent(x.id)).catch(() => null);
    const lanes = ((d && d.lanes) || []).filter(L => roleFits(role, L.role || L.in_role));
    setPick({ kind, x, lanes });
    setAfter({});
    if (lanes[0]) setLane(lanes[0].id);
    // où irait chaque lane : une lane rouge ne reste pas choisie d'office
    const m = await cpuItem().then(it => lanesAfter(x.id, d, it)).catch(() => ({}));
    setAfter(m);
    const ok = lanes.find(L => !addLaneState(m[L.id]).disabled);
    setLane(ok ? ok.id : null);
  };
  return html`<div class="la-sheet-bg" onClick=${e => e.target === e.currentTarget && onClose()}><div class="la-sheet tall">
    <div class="la-sheet-hd"><button class="tn-back la-back" onClick=${() => setStep('main')}>‹ Back</button><b>Add ${esc(info.name)} to a patch or a song</b>
      <input class="search" type="search" placeholder="Search…" onInput=${e => setQ(e.target.value.trim())} />${close}</div>
    <div class="ky-styles">
      <button class=${cls('ky-sty', tab === 'songs' && 'on')} onClick=${() => { setTab('songs'); setPick(null); }}>Songs <em>${lists.presets.length}</em></button>
      <button class=${cls('ky-sty', tab === 'patches' && 'on')} onClick=${() => { setTab('patches'); setPick(null); }}>${ROLE_NAME[role] || role} patches <em>${patches.length}</em></button>
    </div>
    <div class="la-pick">
      <div class="la-list">${(tab === 'songs' ? presets : patches).map(x => html`<button class=${cls('la-item', pick && pick.x.id === x.id && 'on')}
          onClick=${() => choose(tab === 'songs' ? 'song' : 'patch', x)}><b>${esc(x.name || x.id)}</b><small>${tab === 'songs' ? (x.bpm ? x.bpm + ' BPM' : '') : esc((x.tags || []).slice(0, 3).join(' · '))}</small></button>`)}</div>
      <div class="la-where">${!pick ? html`<div class="muted">Pick a ${tab === 'songs' ? 'song' : 'patch'}.</div>`
        : pick.kind === 'patch' ? html`<h6 class="ky-h6">${esc(pick.x.name)}</h6><div class="muted">Its ${ROLE_NAME[role] || role} lane takes it, in its place (an amp replaces the amp, a pedal goes before it).</div>
            <button class="primary la-open" onClick=${() => go(() => openInDesigner(patchDraft(pick.x), null, act))}>Open ${esc(pick.x.name)} in the Designer</button>`
        : html`<h6 class="ky-h6">${esc(pick.x.name)} · where does it go?</h6>
          ${pick.lanes.length ? pick.lanes.map(L => { const c = addLaneState(after[L.id]);
            return html`<button class=${cls('la-lane', lane === L.id && 'on')} disabled=${c.disabled} onClick=${() => setLane(L.id)}
              title=${c.why ? 'CPU on this golem: this lane ' + c.why : ''}>
            <b>${esc(L.name || L.id)}</b>${c.why ? html`<span class=${'cpu-why lv-' + c.level}>${c.why}</span>` : html`<span>${esc(L.role || L.in_role)}</span>`}</button>`; })
            : html`<div class="muted">This song has no ${ROLE_NAME[role] || role} lane. Add one in the Designer first, or pick another song.</div>`}
          <button class="primary la-open" disabled=${!lane} onClick=${() => go(() => openInDesigner(pick.x.id, null, { ...act, lane }))}>Open ${esc(pick.x.name)} in the Designer</button>`}</div>
    </div>
  </div></div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// LA VÉRIFICATION DE PREMIÈRE INSTALLATION (docs/health.md §2, maquette mockups/first-check.html validée le
// 2026-10-20). Elle CONTINUE l'écran de chargement (mêmes lignes, même marque) une fois le premier démarrage fini :
// les faits automatiques d'abord (bridge/first_check.py : moteur, carte, contenu d'usine, premier preset), puis trois
// gestes demandés au musicien, chacun avec sa mesure EN DIRECT et son verdict d'une phrase — brancher et jouer (les
// vumètres OSC de TOUTES les entrées de la carte : celle qui joue est trouvée, le musicien confirme ce qui y est branché
// — enregistré dans l'input map, comme Soundcard — et le gain est jugé en direct pendant qu'il tourne le bouton), écouter (le clic joue, l'entend-il ?), appuyer sur un switch (le pédalier a répondu APRÈS le
// départ du geste, vérifié par le bridge). L'écran a toujours une sortie (« Skip for now ») ; rejouable depuis
// Settings ▸ Health. Le résultat est gardé (config/.first-check.json) et part dans le paquet de démarrage.
import { html, useState, useEffect, useRef, api, post, go, cls } from './lib.js';
import { INPUT_MIN, autoRows, gestureRows, summary, fmtTook, db, gainOf, gainText, cardInputs, loudest, inst, METERED, AUDIO_ROLES } from './first-check-model.mjs';

const DOT = { ok: '✓', on: '', wait: '', late: '!', skip: '–' };
const FC = '/api/health/first-check';
const HOLD_MS = 3000;                                     // la crête « récente » : celle qu'on juge pendant qu'on règle le gain

export function FirstCheckPage({ rig, onDone, demo }) {
  const st = (rig && rig.state) || {};
  const [status, setStatus] = useState(demo || null);
  const [current, setCurrent] = useState(demo ? (demo.current || {}).step || null : null);   // le geste en cours
  const [sel, setSel] = useState(null);                   // l'entrée où l'on a vu jouer
  const [role, setRole] = useState(null);                 // ce que le musicien dit y être branché
  const hist = useRef({});                                // {ch: [[t, v], …]} sur HOLD_MS
  const lastPeak = useRef(0);                             // la dernière crête mesurée : le verdict reste quand on s'arrête de jouer
  const [click, setClick] = useState({ ticks: 0, off: false });
  const [left, setLeft] = useState(null);                 // secondes restantes au pédalier
  const [busy, setBusy] = useState(false);
  const footAt = useRef(null);
  const live = !demo;
  const reload = () => api(FC).then(setStatus).catch(() => {});
  const act = body => post(FC, body);

  // 1. ouvrir la vérification, puis le premier geste
  useEffect(() => {
    if (!live) return;
    (async () => {
      const s = await api(FC).catch(() => null);
      if (!s) return;
      setStatus(s);
      if (s.done_at) return;
      const next = ['input', 'output', 'foot'].find(id => !(s.steps || {})[id]);
      if (next) await startStep(next);
    })();
  }, []);

  const startStep = async id => {
    const r = await act({ action: 'begin', step: id }).catch(() => null);
    if (id === 'foot') footAt.current = (r && r.at) || null;
    if (id === 'output') {
      setClick({ ticks: 0, off: false });
      const c = await post('/api/metronome', { on: true }).catch(e => ({ off: !!(e.body && /off in this mode/.test(e.body.error || '')) }));
      if (c && c.off) setClick({ ticks: 0, off: true });
    }
    if (id === 'input') { hist.current = {}; setSel(null); setRole(null); }
    lastPeak.current = 0; setLeft(null); setCurrent(id);
  };
  const finishStep = async (id, ok, measured) => {
    if (busy) return;
    setBusy(true);
    if (id === 'output') await post('/api/metronome', { on: false }).catch(() => {});
    await act({ action: 'step', step: id, ok, measured: measured || {} }).catch(() => {});
    const s = await api(FC).catch(() => null);
    setCurrent(null); setBusy(false);
    if (!s) return;
    setStatus(s);
    const next = ['input', 'output', 'foot'].find(x => !(s.steps || {})[x]);
    if (next) await startStep(next);
    else { const f = await act({ action: 'finish' }).catch(() => null); if (f) await reload(); }
  };

  // 2. brancher et jouer : les vumètres OSC de chaque entrée (state.levels.in<N>, ~20 Hz). L'entrée retenue est la plus
  // forte des crêtes récentes ; on ne passe pas tout seul : le musicien confirme l'instrument et règle son gain d'abord.
  const ins = cardInputs(st.inputmap);
  const levels = (demo && demo.demo && demo.demo.levels) || st.levels || {};
  const vuOf = ch => levels['in' + ch] || 0;
  const peaks = {};
  if (current === 'input') {
    const now = Date.now();
    for (const i of ins) {
      if (i.ch > METERED) continue;
      const h = (hist.current[i.ch] || []).filter(([t]) => now - t < HOLD_MS);
      h.push([now, vuOf(i.ch)]); hist.current[i.ch] = h;
      peaks[i.ch] = Math.max(...h.map(([, v]) => v));
    }
  }
  const hot = loudest(peaks);
  // la crête récente de l'entrée retenue (le verdict de gain), ou la dernière mesurée quand on s'arrête de jouer
  if (sel && peaks[sel] >= INPUT_MIN) lastPeak.current = peaks[sel];
  const inPeak = sel ? (peaks[sel] >= INPUT_MIN ? peaks[sel] : lastPeak.current) : 0;
  useEffect(() => {
    if (current === 'input' && hot && hot.ch !== sel) { setSel(hot.ch); setRole((ins.find(i => i.ch === hot.ch) || {}).role || null); }
  }, [current, hot && hot.ch]);
  // l'input map peut arriver APRÈS l'entrée retenue (WebSocket) : l'instrument déclaré est proposé dès qu'il est connu
  const declared = sel ? (ins.find(i => i.ch === sel) || {}).role || null : null;
  useEffect(() => { if (current === 'input' && sel && !role && declared) setRole(declared); }, [sel, declared]);
  const clipped = ch => { const c = (st.clip || {})['in' + ch]; return !!(c && c.at && Date.now() / 1000 - c.at < HOLD_MS / 1000 + 2); };
  const confirmInput = async () => {
    // l'instrument confirmé va dans l'input map, comme depuis Soundcard ; à la fin du geste seulement : le
    // ré-émission du rig qui suit couperait les vumètres pendant qu'on règle le gain
    if (live && role && role !== declared) await post('/api/inputmap', { kind: 'input', ch: String(sel), role }).catch(() => {});
    finishStep('input', true, { peak: inPeak, input: sel, role, clipped: clipped(sel) });
  };
  // 3. écouter : le clic tourne-t-il vraiment ? (.click.json, ticks) — la réponse, elle, vient du musicien
  useEffect(() => {
    if (current !== 'output' || !live || click.off) return;
    const t = setInterval(() => api('/api/click').then(c => setClick(k => ({ ...k, ticks: c.ticks || 0 }))).catch(() => {}), 700);
    return () => clearInterval(t);
  }, [current, click.off]);
  // 4. appuyer sur un switch : foot_heard (horloge du bridge) après le départ du geste ; trente secondes, puis c'est dit
  const waitS = (status && status.foot_wait_s) || 30;
  useEffect(() => {
    if (current !== 'foot' || !live) return;
    const t0 = Date.now();
    const t = setInterval(() => {
      const l = waitS - (Date.now() - t0) / 1000;
      setLeft(l);
      if (l <= 0) finishStep('foot', false, {});
    }, 500);
    return () => clearInterval(t);
  }, [current]);
  useEffect(() => {
    if (current !== 'foot' || !live || !footAt.current) return;
    if (st.foot_heard && st.foot_heard >= footAt.current) finishStep('foot', true, {});
  }, [st.foot_heard, current]);

  const steps = (status && status.steps) || {};
  const done = !!(status && status.done_at);
  const rows = autoRows(status);
  const demoLive = demo && demo.demo ? demo.demo : null;
  const gest = gestureRows(steps, current, { peak: inPeak, ch: sel, ticks: demoLive ? demoLive.ticks : click.ticks, clickOff: click.off, left_s: left, foot_wait_s: waitS });
  const sum = done ? summary(steps) : null;
  const os = (st.boot && st.boot.os) || '';
  const skip = async () => { if (live) await act({ action: 'skip' }).catch(() => {}); onDone && onDone(); };
  const again = async () => { if (!live) return; await act({ action: 'reset' }).catch(() => {}); await act({ action: 'begin' }).catch(() => {});
    setStatus(s => ({ ...(s || {}), done_at: null, steps: {} })); await startStep('foot'); };
  const Row = r => html`<div class=${'ld-m ' + r.state} key=${r.id}>
    <span class="d">${DOT[r.state] || ''}</span><span class="n">${r.name}</span>
    <span class="t" title=${r.text}>${r.text}</span>
    ${r.state === 'late' && r.fix ? html`<span class="fc-fix">${r.fix}</span>` : ''}
  </div>`;
  return html`<div class="ld fc">
    <div class="ld-body">
      <div class="ld-mark" aria-label="first check"><span class="s">/</span><span class="g">first check</span></div>
      <div class="ld-sub">${done ? 'done in ' + fmtTook(status.took_s) : 'three minutes, once — so you know this golem works before you play'}</div>
      ${sum ? html`<div class=${'fc-sum fc-' + sum.level}><span class="fc-big"></span><div><b>${sum.title}</b><br /><span class="fc-m">${sum.text}</span></div></div>` : ''}
      <div class="fc-gh">What the machine saw by itself</div>
      <div class="ld-mods">${rows.map(Row)}</div>
      <div class="fc-gh">${done ? 'What only you could tell' : 'What only you can tell'}</div>
      <div class="ld-mods">
        ${gest.map(r => r.state === 'on' && r.id === 'output' ? html`<div class="fc-ask" key="ask">
            <div class="fc-q"><i></i>2 · Listen — the click is playing on the main output. Do you hear it?</div>
            <div class="fc-how">${r.text}. If not: check the monitors are on and plugged into the main output of the card. You can change the output in Settings ▸ Gear ▸ Soundcard afterwards.</div>
            <div class="fc-acts"><button disabled=${busy} onClick=${() => finishStep('output', false, { heard: false })}>No, nothing</button>
              <button class="g" disabled=${busy} onClick=${() => finishStep('output', true, { heard: true })}>Yes, I hear it</button></div>
          </div>`
          : r.state === 'on' && r.id === 'input' ? html`<div class="fc-ask" key="ask">
            <div class="fc-q"><i></i>${sel ? '1 · We hear IN ' + sel + '. What is plugged in?' : '1 · Plug and play — plug your instrument into any input of the card and play.'}</div>
            ${ins.filter(i => i.ch <= METERED).map(i => html`<div class=${cls('fc-in', sel === i.ch && 'fc-in-sel')} key=${'in' + i.ch}>
              <span class="fc-in-ch">IN ${i.ch}</span>
              <span class="fc-in-r">${sel === i.ch && role ? (inst(role).icon + ' ' + inst(role).name) : i.role ? (i.icon || '') + ' ' + (i.label || i.role) : 'nothing declared'}</span>
              <div class="fc-meter"><i style=${'width:' + Math.min(100, Math.round(vuOf(i.ch) * 100)) + '%'}></i>
                ${peaks[i.ch] > 0 ? html`<b style=${'left:' + Math.min(99, Math.round(peaks[i.ch] * 100)) + '%'}></b>` : ''}</div>
            </div>`)}
            ${sel ? html`<div class="fc-roles">${AUDIO_ROLES.map(r => html`<button key=${r.id} class=${cls(role === r.id && 'on')} onClick=${() => setRole(r.id)}>${r.icon} ${r.name}</button>`)}</div>
              <div class=${'fc-gain fc-g-' + (gainOf(inPeak, clipped(sel)) || 'none')}>Level: ${db(inPeak) != null ? 'peak ' + db(inPeak) + ' dBFS — ' : ''}${gainText(gainOf(inPeak, clipped(sel)), sel) || 'keep playing…'}</div>`
            : html`<div class="fc-how">${r.text}</div>`}
            <div class="fc-acts"><button disabled=${busy} onClick=${() => finishStep('input', false, { peak: 0, input: sel })}>Nothing to plug in — skip</button>
              ${sel ? html`<button class="g" disabled=${busy || !role} onClick=${confirmInput}>${role ? 'This is my ' + inst(role).name.toLowerCase() + ' — next' : 'Choose what is plugged in'}</button>` : ''}</div>
          </div>`
          : r.state === 'on' && r.id === 'foot' ? html`<div class="fc-ask" key="ask">
            <div class="fc-q"><i></i>3 · Press any switch of the pedalboard.</div>
            <div class="fc-how">${r.text}. The pedalboard has ${waitS} s to answer; nothing is an error before that.</div>
            <div class="fc-acts"><button disabled=${busy} onClick=${() => finishStep('foot', false, {})}>No pedalboard — skip</button></div>
          </div>`
          : Row(r))}
      </div>
      ${done ? html`<div class="fc-acts fc-end">
          ${steps.foot && !steps.foot.ok ? html`<button onClick=${again}>Try the pedalboard again</button>` : ''}
          <button class="p" onClick=${() => { onDone && onDone(); go('live'); }}>Open golem →</button>
        </div>` : ''}
    </div>
    <div class="ld-foot">
      <span>golem${os ? ' · ' + os : ''} · first start · ${done ? 'kept in Settings ▸ Health · sent with the boot report' : 'results kept and sent with the boot report'}</span>
      ${done ? html`<button class="ld-skip" onClick=${() => { onDone && onDone(); go('system/gear/board'); }}>Help: pedalboard →</button>`
             : html`<button class="ld-skip" onClick=${skip}>Skip for now →</button>`}
    </div>
  </div>`;
}

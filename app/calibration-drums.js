// SPDX-License-Identifier: GPL-3.0-or-later
// Calibration ▸ Drums (docs/calibration.md, addendum 2026-09-23) — le module de batterie est un FAIT
// DU RACK, et il se MESURE : « hit the kick », le module répond, le rack note. Rien ici ne choisit un
// descripteur à la main : soit le nom USB en identifie un (et on le vérifie), soit la mesure en crée un.
//   DrumsPanel   : les modules liés en drums (Soundcard) + ceux qu'on peut déclarer ; par module, le
//                  descripteur identifié, sa provenance, et « Measure ».
//   DrumStepper  : une question par élément, le tampon LIVE de drum-tap.jsfx (via la piste d'écoute
//                  golem_drumlearn), skip/redo, puis la revue (POST /api/drumkits/measure dry) et
//                  « Save as measured ».
// L'écoute passe par Reaper (tant qu'il détient le port rawmidi, personne d'autre ne peut lire le
// module) : start/stop posent et retirent la piste d'écoute. Interface en ANGLAIS ; commentaires FR.
import { html, useState, useEffect, useRef, useAsync, post, cls, esc, go } from './lib.js';
import { elLabel } from './designer-drumset.js';
import { DeviceState } from './calibration.js';

// Les étapes = bridge/drumlearn.STEPS, dans le même ordre, avec la phrase à l'écran. `gesture` = un
// comportement mesuré (le choke), pas une ligne de la table.
const STEPS = [
  ['kick', 'Hit the kick'], ['snare', 'Hit the snare — centre of the head'], ['snare-rim', 'Hit the snare rim'],
  ['tom1', 'Hit tom 1 (the highest)'], ['tom1-rim', 'Hit the rim of tom 1'],
  ['tom2', 'Hit tom 2'], ['tom2-rim', 'Hit the rim of tom 2'],
  ['tom3', 'Hit tom 3 (the lowest / floor tom)'], ['tom3-rim', 'Hit the rim of tom 3'],
  ['tom4', 'Hit tom 4 — if you have one'], ['tom4-rim', 'Hit the rim of tom 4'],
  ['hh-closed', 'Hi-hat — pedal DOWN and held, then hit'], ['hh-open', 'Hi-hat — pedal UP, hit'],
  ['hh-half', 'Hi-hat — pedal HALF way, held, hit'], ['hh-pedal', 'Pedal only — the chick, sticks down'],
  ['hh-splash', 'Splash — hit open, then close the pedal'],
  ['crash1', 'Hit crash 1'], ['crash1-choke', 'Hit crash 1, then GRAB it to choke', 'gesture'],
  ['crash2', 'Hit crash 2 — if you have one'], ['ride', 'Hit the ride'], ['ride-bell', 'Ride bell — if the pad has one'],
];
const KIND = { 1: 'note', 2: 'CC', 3: 'AT' };

const PROV = {
  verified: ['✓ verified', 'measured on this very module'],
  reported: ['~ reported', 'from a manual or a forum — not measured here'],
  unconfirmed: ['? unconfirmed', 'assumed — treat as a lead, not a fact'],
};
export function KitProvenance({ confidence }) {
  const [label, why] = PROV[confidence] || ['? unknown', 'no provenance'];
  return html`<span class=${cls('pb-prov', confidence || 'unknown')} title=${why}>${label}</span>`;
}

// ── le flux LIVE : le tampon des 32 derniers événements, lu par SEQ ─────────────────────────
// Le 1er poll AMORCE le seq sans rien émettre (un coup d'il y a une minute n'apprend rien).
function useDrumLive(active, onEvents) {
  const [st, setSt] = useState(null);
  const seq = useRef(null);
  useEffect(() => {
    if (!active) { seq.current = null; return; }
    let alive = true;
    const t = setInterval(() => fetch('/api/calibrate/drums/live').then(r => r.json()).then(d => {
      if (!alive) return;
      setSt(d);
      const cur = d.seq || 0;
      if (seq.current === null) { seq.current = cur; return; }
      if (cur > seq.current) {
        const fresh = (d.events || []).slice(-Math.min(cur - seq.current, (d.events || []).length));
        seq.current = cur;
        if (fresh.length) onEvents(fresh);
      }
    }).catch(() => {}), 150);
    return () => { alive = false; clearInterval(t); };
  }, [active]);
  return st;
}

// ── le stepper ─────────────────────────────────────────────────────────────────────────────
export function DrumStepper({ port, device, kit, onClose, onSaved }) {
  const [phase, setPhase] = useState('start');               // start | steps | review
  const [i, setI] = useState(0);
  const [steps, setSteps] = useState({});                    // id -> {events:[...]} (absent = pas posé)
  const [err, setErr] = useState(null);
  const [review, setReview] = useState(null);
  const [saving, setSaving] = useState(false);
  const t0 = useRef(0);
  const cur = STEPS[i];
  // ⚠ CLOSURE FIGÉE (vécu 2026-09-23, « le kick ok, le snare reste sur listening… ») : le rappel du
  // poll est créé UNE fois (effet sur `active`) et capturait le `i` du premier rendu — toutes les frappes
  // allaient au kick. L'étape courante se lit dans une ref, mise à jour à chaque rendu.
  const curRef = useRef(cur[0]);
  curRef.current = cur[0];
  const live = useDrumLive(phase === 'steps', evts => {
    // ce qui arrive appartient à l'étape AFFICHÉE — la séquence est gardée telle quelle (règle 1)
    setSteps(s => { const id = curRef.current; const prev = (s[id] || { events: [] }).events;
      return { ...s, [id]: { events: [...prev, ...evts.map(e => ({ ...e, ms: Math.round((e.t - t0.current) * 1000) }))] } }; });
  });
  useEffect(() => { if (phase === 'steps') t0.current = (live && live.t) || t0.current; }, [i, phase]);
  useEffect(() => () => { post('/api/calibrate/drums/stop').catch(() => {}); }, []);   // jamais une piste orpheline

  const start = async () => {
    setErr(null);
    const r = await post('/api/calibrate/drums/start', { port }).catch(e => ({ error: String(e) }));
    if (!r || r.error) { setErr((r && r.error) || 'cannot start'); return; }
    setPhase('steps');
  };
  const events = (steps[(cur || [])[0]] || { events: [] }).events;
  const notes = events.filter(e => e.k === 1);
  const skip = () => { setSteps(s => ({ ...s, [cur[0]]: { events: [] } })); next(); };
  const redo = () => setSteps(s => ({ ...s, [cur[0]]: { events: [] } }));
  const next = () => { if (i + 1 >= STEPS.length) finish(); else setI(i + 1); };
  const back = () => { if (i > 0) setI(i - 1); };
  const measure = () => ({ port: device, kit: kit && kit.id, measured_at: new Date().toISOString().slice(0, 10),
    steps, clock: !!(live && live.clock) });
  const finish = async () => {
    await post('/api/calibrate/drums/stop').catch(() => {});
    // un 409 PORTE la raison et le rapport (le conflit de notes) : on garde le corps de la réponse — avant,
    // seul « Error: /api/drumkits/measure → 409 » s'affichait et l'écran ne pouvait rien expliquer (2026-10-03)
    const r = await post('/api/drumkits/measure', { measure: measure(), kit: kit && !kit.fallback ? kit.id : null, dry: true })
      .catch(e => ({ ...(e.body || {}), error: (e.body && e.body.error) || String(e) }));
    setReview(r || { error: 'no answer' });
    setPhase('review');
  };
  const save = async () => {
    setSaving(true);
    const r = await post('/api/drumkits/measure', { measure: measure(), kit: kit && !kit.fallback ? kit.id : null })
      .catch(e => ({ ...(e.body || {}), error: (e.body && e.body.error) || String(e) }));
    setSaving(false);
    if (r && r.ok) { onSaved && onSaved(r); onClose(); } else setErr((r && r.error) || 'save failed');
  };
  // la note de la frappe, comme le bridge la lira : la plus forte (le splash : la première)
  const strike = () => { if (!notes.length) return null;
    if (cur[0] === 'hh-splash') return notes[0];
    return notes.reduce((a, b) => (b.v > a.v ? b : a)); };
  const s = strike();
  const done = Object.keys(steps).length;

  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card cal-card cal-drums">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Measure — ${esc(device)}</h2>

      ${phase === 'start' ? html`<div class="cal-body">
        <p>golem listens to the module through Reaper and asks for <b>one element at a time</b>. Hit it,
        the note lights up, move on. Skip what your kit does not have; redo a hit you are not sure of.</p>
        <p class="muted">Descriptor: ${kit ? html`<b>${esc(kit.name)}</b> <${KitProvenance} confidence=${kit.confidence} />`
          : 'none matches this USB name — the measurement will create one.'}
          ${kit && kit.fallback ? html` <span class="muted">(GM fallback — the measurement will create a descriptor for this module)</span>` : ''}</p>
        <p class="muted">The module stays playable. Nothing is written before you confirm on the review screen.</p>
        ${err ? html`<p class="cal-err">⚠ ${esc(err)}</p>` : ''}
        <div class="cal-nav"><span class="grow"></span><button class="primary" onClick=${start}>Start listening</button></div>
      </div>`

      : phase === 'steps' ? html`<div class="cal-body">
        <div class="cal-drum-head">
          <span class="muted">${i + 1} / ${STEPS.length}</span>
          ${live && live.on === false ? html`<span class="cal-err">⚠ listen track is gone${live.err ? ' — ' + esc(live.err) : ''}</span>` : ''}
        </div>
        <p class="cal-ask"><span class="cal-el">${esc(elLabel(cur[0]) || cur[0])}</span> — ${cur[1]}</p>
        <div class=${cls('cal-heard', !events.length && 'wait', s && 'got')}>
          ${!events.length ? html`<span class="muted">listening…</span>`
            : html`${s ? html`<b>note ${s.n}</b> <small>velocity ${s.v}</small>` : html`<span class="muted">no note yet</span>`}
              ${notes.length > 1 && new Set(notes.map(e => e.n)).size > 1 ? html`<span class="cal-flag">⚠ several notes in one gesture — kept as a sequence</span>` : ''}
              ${s && s.v <= 20 ? html`<span class="cal-flag">⚠ very soft — a real zone, or crosstalk from the next pad?</span>` : ''}
              <div class="cal-seq">${events.slice(-8).map(e => html`<span class=${'cal-ev k' + e.k}>${e.ms} ms · ${KIND[e.k]} ${e.n} = ${e.v}</span>`)}</div>`}
        </div>
        <div class="cal-nav">
          <button class="chip" disabled=${i === 0} onClick=${back}>← Back</button>
          <button class="chip" onClick=${skip} title="this element does not exist on this kit">Skip</button>
          <button class="chip" disabled=${!events.length} onClick=${redo}>Redo</button>
          <span class="grow"></span>
          <button class="chip on" disabled=${!events.length && cur[2] !== 'gesture'} onClick=${next}>${i + 1 >= STEPS.length ? 'Review →' : 'Next →'}</button>
        </div>
        <div class="cal-done">${STEPS.slice(0, i).map(([id]) => { const st = steps[id]; const n = st && st.events.filter(e => e.k === 1);
          const b = n && n.length ? (id === 'hh-splash' ? n[0] : n.reduce((a, c) => (c.v > a.v ? c : a))) : null;
          return html`<span class=${cls('cal-slot', b && 'got')} title=${elLabel(id)}>${esc(elLabel(id))}${b ? ' ' + b.n : ' —'}</span>`; })}</div>
      </div>`

      : html`<div class="cal-body">
        ${!review || review.error ? html`<p class="cal-err">⚠ ${esc((review && review.error) || 'no answer')}</p>
            ${review && review.report && review.report.clash && Object.keys(review.report.clash).length
              ? html`<p class="muted">Two base elements answered the same note: ${Object.entries(review.report.clash).map(([n, els]) => `${n} (${els.map(elLabel).join(' / ')})`).join(', ')}.
                  Usually one hit also triggered the other pad (or the wrong pad was hit) — redo one of them:</p>
                <div class="cal-caps">${[...new Set(Object.values(review.report.clash).flat())].map(el => html`<button class="chip"
                  onClick=${() => { const j = STEPS.findIndex(([id]) => id === el); if (j < 0) return;
                    setSteps(s => ({ ...s, [el]: { events: [] } })); setI(j); setPhase('steps');
                    post('/api/calibrate/drums/start', { port }).catch(() => {}); }}>↺ Redo ${esc(elLabel(el))}</button>`)}</div>` : ''}`
          : html`<p class="muted">${done} step${done === 1 ? '' : 's'} · ${Object.keys(review.report.elements).length} elements heard
              · channel ${(review.report.channel || []).join(', ') || '?'}
              ${review.report.clock ? ' · the module streams MIDI clock (harmless)' : ''}</p>
            <div class="cal-rev-grid">
              ${(review.compare ? review.compare.rows : Object.entries(review.report.elements).map(([el, m]) => ({ el, note: m.note, status: 'new', vel: m.vel })))
                .map(r => html`<span class=${'cal-rev ' + r.status} title=${r.status === 'twin' ? `same note as ${elLabel(r.of)} — one zone on this pad` : r.status === 'differs' ? `descriptor said ${r.declared}` : r.status}>
                  ${r.status === 'ok' ? '✓' : r.status === 'twin' ? '≡' : r.status === 'differs' ? '✗' : r.status === 'absent' ? '+' : '•'} ${esc(elLabel(r.el))} <b>${r.note}</b>${r.status === 'twin' ? html` <small>= ${esc(elLabel(r.of))}</small>` : r.status === 'differs' ? html` <small>was ${r.declared}</small>` : ''}</span>`)}
            </div>
            ${review.compare && review.compare.ghosts.length ? html`<p class="muted">Declared, never heard: ${review.compare.ghosts.map(g => `${elLabel(g.el)} (${g.note})`).join(', ')} — moved to the descriptor's memory, not its table.</p>` : ''}
            <ul class="cal-review">
              <li>Hi-hat: <b>${review.report.hihat.cc == null ? 'switch pedal — no CC' : 'position on CC ' + review.report.hihat.cc}</b>, ${review.report.hihat.positions} positions${review.compare && !review.compare.verdict.hihat_cc.ok ? html` <small class="cal-err">(descriptor said CC ${review.compare.verdict.hihat_cc.declared ?? 'none'})</small>` : ''}</li>
              <li>Choke: <b>${review.report.choke}</b>${review.compare && !review.compare.verdict.choke.ok ? html` <small class="cal-err">(descriptor said ${review.compare.verdict.choke.declared})</small>` : ''}${review.report.aftertouch_elsewhere.length ? html` <small class="muted">· aftertouch also came during ${review.report.aftertouch_elsewhere.join(', ')} — that is the pedal, not a choke</small>` : ''}</li>
              ${review.problems && review.problems.length ? html`<li class="cal-err">Cannot save: ${review.problems.join(' · ')}</li>` : ''}
            </ul>`}
        ${err ? html`<p class="cal-err">⚠ ${esc(err)}</p>` : ''}
        <div class="cal-nav">
          <button class="chip" onClick=${() => { setPhase('steps'); post('/api/calibrate/drums/start', { port }).catch(() => {}); }}>← Back to the steps</button>
          <span class="grow"></span>
          <button class="primary" disabled=${saving || !review || review.error || (review.problems && review.problems.length)} onClick=${save}>
            ${saving ? '⏳' : (kit && !kit.fallback ? '💾 Save as measured' : '💾 Create descriptor')}</button>
        </div>
      </div>`}
    </div></div>`;
}

// ── le panneau ─────────────────────────────────────────────────────────────────────────────
export function DrumsPanel() {
  // connus ∪ détectés (docs/gear-registry.md addendum 2026-09-23) : un module débranché reste listé,
  // « not connected » ; Measure exige la présence et le dit ; un MIDI inconnu se déclare module.
  const { data, reload } = useAsync(() => fetch('/api/devices').then(r => r.json()), []);
  const [meas, setMeas] = useState(null);
  const [flash, setFlash] = useState('');
  const all = (data && data.devices) || [];
  const drums = all.filter(d => (d.roles || []).includes('drums'));
  const others = all.filter(d => !d.known && d.connected && d.kind === 'midi');
  const declare = async d => { await post('/api/soundcard/usb', { port: d.port, enabled: true, roles: ['drums'] }).catch(() => {}); reload(); };
  const forget = async d => { await fetch('/api/devices/' + encodeURIComponent(d.key), { method: 'DELETE' }).catch(() => {}); reload(); };
  return html`<div class="cal-panel">
    <p class="muted cal-intro">Electronic drum modules over USB-MIDI. A module's note map is <b>measured</b> here, pad by pad —
    a manual or a forum is a lead, the pads are the fact. Patches then read the calibrated module, they never pick one.</p>
    ${drums.map(d => { const k = d.kit || {}; const conf = k.confidence;
      return html`<div class=${cls('cal-ctl', !d.connected && 'dim')}>
        <span class="cal-ctl-ic">🥁</span>
        <div class="cal-ctl-tx"><b>${esc(d.name)}</b>
          <small class="muted"><${DeviceState} d=${d} /> · ${k.id ? (k.fallback ? 'no descriptor matches this name — GM fallback' : html`${esc(k.name)} <${KitProvenance} confidence=${conf} />`) : 'no descriptor'}
            ${k.id && conf !== 'verified' && !k.fallback ? html` <span class="muted">· ${k.auto ? 'identified from the USB name' : 'chosen'}, never measured here</span>` : ''}</small></div>
        <button class="chip" title="forget this module — the only way it leaves the rack" onClick=${() => forget(d)}>Forget</button>
        <button class="primary" disabled=${!d.connected} title=${d.connected ? '' : 'plug it in to measure — golem listens to the real pads'}
          onClick=${() => setMeas({ port: d.port, device: d.name, kit: k.id ? { ...k } : null })}>
          ${conf === 'verified' ? 'Re-measure' : 'Measure'}</button>
      </div>`; })}
    ${others.map(d => html`<div class="cal-ctl dim">
      <span class="cal-ctl-ic">🎛</span>
      <div class="cal-ctl-tx"><b>${esc(d.name)}</b><small class="muted">USB ${d.port} · a MIDI device, not known as a drum module</small></div>
      <button class="chip" onClick=${() => declare(d)}>This is a drum module</button>
    </div>`)}
    ${!drums.length && !others.length ? html`<div class="empty">No drum module known or connected. Plug the module's USB, then come back.</div>` : ''}
    ${flash ? html`<p class="muted">${esc(flash)}</p>` : ''}
    ${meas ? html`<${DrumStepper} ...${meas} onClose=${() => setMeas(null)}
      onSaved=${r => { setFlash(`Saved: ${r.path} — ${Object.keys((r.descriptor || {}).map || {}).length} elements, verified.`); reload(); }} />` : ''}
  </div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Calibration (docs/calibration.md) — connaître le gear à fond, en prod, sans code.
//   ControllersPanel : contrôleurs USB clavier/pads -> stepper MIDI-learn -> profil
//     (config/controllers/*.json + propagation knobs.json). « Touche/tourne, GoleM regarde. »
//   PedalCalib : vérification du mapping Whammy PC par PC + wizard de création d'un mapping
//     pour une pédale JAMAIS VUE (on émet, l'humain observe la pédale).
import { html, useState, useEffect, useRef, useAsync, post, cls, esc } from './lib.js';

const NPADS = 8, NKNOBS = 8;
const noteName = n => ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][n % 12] + (Math.floor(n / 12) - 1);

// ── flux learn : poll /api/calibrate/live, émet le DERNIER événement note/cc/pb ──
// Le 1er poll AMORCE les seq sans émettre (un CC d'il y a une heure ne doit pas « apprendre »).
function useLearn(active) {
  const [ev, setEv] = useState(null);
  const seqs = useRef(null);
  useEffect(() => {
    if (!active) { seqs.current = null; return; }
    let alive = true;
    const t = setInterval(() => fetch('/api/calibrate/live').then(r => r.json()).then(d => {
      if (!alive) return;
      const first = seqs.current === null;
      const s = seqs.current = seqs.current || {};
      for (const [k, type] of [['note', 'note'], ['cc', 'cc'], ['pb', 'pb']]) {
        const cur = (d[k] || {}).seq || 0;
        if (s[k] !== cur) {
          // seulement un compteur qui MONTE (2026-10-03) : à chaque ouverture de la piste d'écoute, knob-tap
          // repart de zéro — ce retour à 0 « changeait » le compteur et s'apprenait comme un geste de numéro 0
          // (le « CC 0 » sur K7/K8, un pad compté deux fois). On se recale sans rien émettre.
          const emit = !first && s[k] !== undefined && cur > s[k];
          s[k] = cur;
          if (emit) setEv({ type, num: (d[k] || {}).num, val: (d[k] || {}).val ?? (d[k] || {}).vel,
                            ch: (d[k] || {}).ch || 0, seq: cur, t: Date.now() });   // ch : canal 1-16 (0 = inconnu)
        }
      }
    }).catch(() => {}), 150);
    return () => { alive = false; clearInterval(t); };
  }, [active]);
  return ev;
}

// ── stepper de calibration d'un contrôleur ──────────────────────────────────────
const STEPS = ['intro', 'keys', 'pads', 'knobs', 'extras', 'review'];
// Extras GUIDÉS (2026-10-03 : « je ne peux pas sélectionner quelle fonction on calibre ») : une
// fonction à la fois, comme low/high/middle — la case en cours est désignée, on passe à la suivante dès
// qu'elle est vue, et chacune se saute. L'arp dit le geste COMPLET : l'allumer seul n'émet rien.
const EXTRAS = [
  ['sustain', 'sustain pedal (CC64)', 'Press the sustain pedal.'],
  ['pitch', 'pitch wheel', 'Move the pitch wheel (joystick left / right).'],
  ['mod', 'mod wheel (CC1)', 'Move the mod wheel (joystick up).'],
  ['arp', 'arpeggiator', 'Turn ARP on, then HOLD a key or a chord for a few seconds — the arpeggiator only plays while a key is held.'],
];
function CalibStepper({ ctl, onClose, onSaved }) {
  const [step, setStep] = useState('intro');
  const [keys, setKeys] = useState({ lo: null, hi: null, middle: null });
  const [keyPhase, setKeyPhase] = useState('lo');            // lo -> hi -> middle
  const [pads, setPads] = useState(Array(NPADS).fill(null));
  const [padIdx, setPadIdx] = useState(0);
  const [knobs, setKnobs] = useState(Array(NKNOBS).fill(null));
  const [knobIdx, setKnobIdx] = useState(0);
  const [caps, setCaps] = useState({});
  const [extraIdx, setExtraIdx] = useState(0);
  const [skipped, setSkipped] = useState({});
  // la case en cours avance d'elle-même vers la première fonction ni vue ni sautée
  useEffect(() => {
    const next = EXTRAS.findIndex(([k]) => !caps[k] && !skipped[k]);
    setExtraIdx(next < 0 ? EXTRAS.length : next);
  }, [caps, skipped]);
  // LES CANAUX (2026-10-13) : mesurés sur les notes des étapes Keys et Pads. Identiques = un pad joue aussi
  // l'instrument de la lane Keys ; on le dit, et on propose de le régler (descripteur du modèle) ou comment le faire.
  const [keysCh, setKeysCh] = useState(0);
  const [padsCh, setPadsCh] = useState(0);
  const [prog, setProg] = useState(null);                    // null | 'busy' | {ok, msg}
  const [listenRev, setListenRev] = useState(0);             // rouvre la piste d'écoute (la programmation la ferme)
  const [saving, setSaving] = useState(false);
  const lock = useRef(0);                                    // anti-débordement d'un geste sur le slot suivant
  const listening = step !== 'intro' && step !== 'review';
  const ev = useLearn(listening);
  // PISTE D'ÉCOUTE (2026-10-03) : sans elle, seul le knob-tap de la lane Keys du preset chargé entendait le
  // clavier — un patch guitare n'en a pas, et aucune touche n'était détectée. Ouverte en entrant dans les
  // étapes, fermée en sortant (ou en fermant la fenêtre).
  const [listenErr, setListenErr] = useState('');
  useEffect(() => {
    if (!listening) return;
    setListenErr('');
    post('/api/calibrate/keys/start', { device: ctl.name })
      .catch(e => setListenErr((e.body && e.body.error) || e.message));
    return () => { post('/api/calibrate/keys/stop', {}).catch(() => {}); };
  }, [listening, listenRev]);

  // consommation des événements learn selon l'étape courante
  useEffect(() => {
    if (!ev || Date.now() < lock.current) return;
    if (step === 'keys' && ev.type === 'note') {
      lock.current = Date.now() + 700;
      if (ev.ch) setKeysCh(ev.ch);
      if (keyPhase === 'lo') { setKeys(k => ({ ...k, lo: ev.num })); setKeyPhase('hi'); }
      else if (keyPhase === 'hi') { setKeys(k => ({ ...k, hi: ev.num })); setKeyPhase('middle'); }
      else { setKeys(k => ({ ...k, middle: ev.num })); }
    } else if (step === 'pads' && ev.type === 'note' && padIdx < NPADS) {
      lock.current = Date.now() + 600;
      if (ev.ch) setPadsCh(ev.ch);
      setPads(p => { const n = [...p]; n[padIdx] = ev.num; return n; });
      setPadIdx(i => i + 1);
    } else if (step === 'knobs' && ev.type === 'cc' && knobIdx < NKNOBS) {
      lock.current = Date.now() + 1200;                      // un potard crache des dizaines de CC
      setKnobs(p => { const n = [...p]; n[knobIdx] = ev.num; return n; });
      setKnobIdx(i => i + 1);
    } else if (step === 'extras') {
      if (ev.type === 'cc' && ev.num === 64) setCaps(c => ({ ...c, sustain: true }));
      if (ev.type === 'cc' && ev.num === 1) setCaps(c => ({ ...c, mod: true }));
      if (ev.type === 'pb') setCaps(c => ({ ...c, pitch: true }));
    }
  }, [ev]);

  // ARPÉGIATEUR — VU EN CONTINU (2026-10-03). Le test à bouton comptait les notes pendant les 5 s qui
  // SUIVENT le clic : il fallait tenir l'accord d'une main et cliquer de l'autre au bon moment, et il
  // ratait un arp pourtant reçu (mesuré le même soir : 6 à 8 notes/s arrivaient à GoleM, calées sur son
  // horloge). Pendant l'étape Extras, on suit le compteur de note-on : ≥ 8 notes dans une fenêtre de 5 s
  // = rafale = arp. Toujours VÉRIFIÉ (des notes réellement reçues), plus jamais une question de timing.
  const [arpRate, setArpRate] = useState(0);
  useEffect(() => {
    if (step !== 'extras') return;
    let alive = true;
    const hist = [];                                          // [t, seq] des 5 dernières secondes
    const t = setInterval(() => fetch('/api/calibrate/live').then(r => r.json()).then(d => {
      if (!alive) return;
      const now = Date.now(), seq = (d.note || {}).seq || 0;
      hist.push([now, seq]);
      while (hist.length && now - hist[0][0] > 5000) hist.shift();
      const n = Math.max(0, seq - hist[0][1]);
      setArpRate(n);
      if (n >= 8) setCaps(c => (c.arp ? c : { ...c, arp: true }));
    }).catch(() => {}), 250);
    return () => { alive = false; clearInterval(t); };
  }, [step]);
  const save = async () => {
    setSaving(true);
    const profile = { usb: ctl.usb, name: ctl.name, keys,
      pads: pads.filter(p => p != null).length ? pads : null,
      knobs: knobs.filter(k => k != null).length ? knobs.map(k => k ?? -1) : null,
      caps };
    if (keysCh && padsCh) profile.channels = { keys: keysCh, pads: padsCh };
    const r = await post('/api/controllers/profile', profile).catch(() => null);
    setSaving(false);
    if (r && r.ok) { onSaved && onSaved(); onClose(); }
  };

  const shared = keysCh && padsCh && keysCh === padsCh;
  const canProgram = !!(ctl.model && ctl.model.can_program);
  const programPads = async () => {
    setProg('busy');
    const r = await post('/api/controllers/pads-channel', { usb: ctl.usb, name: ctl.name })
      .catch(e => ({ ok: false, error: (e.body && e.body.error) || e.message }));
    if (r && r.ok) {
      // on RE-MESURE : les pads ont changé de notes et de canal — refrapper confirme ce que le contrôleur envoie vraiment
      setPads(Array(NPADS).fill(null)); setPadIdx(0); setPadsCh(0); setStep('pads');
      setProg({ ok: true, msg: `Done — pads on channel ${r.pad_ch}, keys on channel ${r.key_ch}. Hit pad 1 again to check.` });
    } else setProg({ ok: false, msg: (r && r.error) || 'failed' });
    setListenRev(n => n + 1);                                 // la programmation a fermé la piste d'écoute
  };
  const ChannelNote = () => {
    if (!keysCh || !padsCh) return '';
    if (!shared) return html`<p class="cal-ch ok">✓ Pads on channel ${padsCh}, keys on channel ${keysCh} — golem plays each on its own sound.</p>`;
    return html`<div class="cal-ch warn">
      <p><b>Pads and keys both send on channel ${keysCh}.</b> A pad also plays a note on the keyboard's sound
        (Vital…), and golem cannot tell a pad from a key.</p>
      ${canProgram ? html`<button class="primary" disabled=${prog === 'busy'} onClick=${programPads}>
          ${prog === 'busy' ? '⏳ Programming…' : 'Give the pads their own channel'}</button>
        <small class="muted">golem writes it into the ${esc(ctl.model.name || 'controller')} (pads on channel 10, notes 36-51) and keeps a copy of the original.</small>`
        : html`<small class="muted">Set the pads to another MIDI channel (10 is the usual one) in the maker's editor, then calibrate again.</small>`}
    </div>`;
  };

  const idx = STEPS.indexOf(step);
  const next = () => setStep(STEPS[Math.min(idx + 1, STEPS.length - 1)]);
  const Nav = extra => html`<div class="cal-nav">
    ${idx > 0 ? html`<button class="chip" onClick=${() => setStep(STEPS[idx - 1])}>← Back</button>` : ''}
    <span class="grow"></span>${extra || ''}
    ${step !== 'review' ? html`<button class="chip on" onClick=${next}>${step === 'intro' ? 'Start' : 'Next →'}</button>`
      : html`<button class="primary" disabled=${saving} onClick=${save}>${saving ? '⏳' : '💾 Save profile'}</button>`}
  </div>`;

  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card cal-card">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Calibrate — ${esc(ctl.name)}</h2>
      <div class="cal-steps">${STEPS.map((s, i) => html`<span class=${cls('cal-dot', i === idx && 'on', i < idx && 'done')}>${i < idx ? '✓' : i + 1}</span>`)}</div>

      ${step === 'intro' ? html`<div class="cal-body">
        <p>golem will learn this controller by <b>listening</b> : play what each step asks, the values
        are captured live. Every step can be skipped — a partial profile is fine.</p>
        <p class="muted">Detected : USB ${esc(ctl.usb || '?')} · golem listens through a temporary track of the
        audio engine, whatever patch is loaded (the controller stays fully playable during calibration).</p>
      </div>` : ''}

      ${listenErr ? html`<p class="muted warn">✗ golem cannot listen to this controller: ${esc(listenErr)}</p>` : ''}
      ${step === 'keys' ? html`<div class="cal-body">
        <p><b>Keyboard range.</b> ${keyPhase === 'lo' ? 'Play the LOWEST key.' : keyPhase === 'hi' ? 'Now the HIGHEST key.' : 'Now MIDDLE C (or your reference key).'}</p>
        <div class="cal-caps">
          <span class=${cls('cal-slot', keys.lo != null && 'got')}>low ${keys.lo != null ? noteName(keys.lo) : '—'}</span>
          <span class=${cls('cal-slot', keys.hi != null && 'got')}>high ${keys.hi != null ? noteName(keys.hi) : '—'}</span>
          <span class=${cls('cal-slot', keys.middle != null && 'got')}>middle ${keys.middle != null ? noteName(keys.middle) : '—'}</span>
        </div>
      </div>` : ''}

      ${step === 'pads' ? html`<div class="cal-body">
        <p><b>Pads.</b> Hit <b>pad ${Math.min(padIdx + 1, NPADS)}</b> — each one lights up when learned.</p>
        <div class="cal-grid">
          ${pads.map((p, i) => html`<div class=${cls('cal-pad', p != null && 'got', i === padIdx && 'wait')}>
            <b>${i + 1}</b><span>${p != null ? noteName(p) : i === padIdx ? '…' : ''}</span></div>`)}
        </div>
        ${padIdx < NPADS ? html`<button class="mini" onClick=${() => setPadIdx(i => i + 1)}>skip pad ${padIdx + 1}</button>` : ''}
        ${prog && prog !== 'busy' ? html`<p class=${cls('cal-ch', prog.ok ? 'ok' : 'warn')}>${prog.ok ? '' : '✗ '}${esc(prog.msg)}</p>` : ''}
        <${ChannelNote} />
      </div>` : ''}

      ${step === 'knobs' ? html`<div class="cal-body">
        <p><b>Knobs.</b> Turn <b>knob K${Math.min(knobIdx + 1, NKNOBS)}</b> (any direction).</p>
        <div class="cal-grid">
          ${knobs.map((k, i) => html`<div class=${cls('cal-pad', k != null && 'got', i === knobIdx && 'wait')}>
            <b>K${i + 1}</b><span>${k != null ? 'CC' + k : i === knobIdx ? '…' : ''}</span></div>`)}
        </div>
        ${knobIdx < NKNOBS ? html`<button class="mini" onClick=${() => setKnobIdx(i => i + 1)}>skip K${knobIdx + 1}</button>` : ''}
      </div>` : ''}

      ${step === 'extras' ? html`<div class="cal-body">
        ${extraIdx < EXTRAS.length
          ? html`<p><b>Extras.</b> ${EXTRAS[extraIdx][2]}</p>`
          : html`<p><b>Extras</b> — done. Next → to review.</p>`}
        <div class="cal-caps">
          ${EXTRAS.map(([k, label], i) => html`<span class=${cls('cal-slot', caps[k] && 'got', i === extraIdx && 'wait')}
            onClick=${() => { setSkipped(s => ({ ...s, [k]: false })); setCaps(c => ({ ...c, [k]: false })); setExtraIdx(i); }}
            title="redo this one">${caps[k] ? '✓ ' : skipped[k] ? '– ' : ''}${label}</span>`)}
        </div>
        ${extraIdx < EXTRAS.length && EXTRAS[extraIdx][0] === 'arp' ? html`
          <p class="muted">Heard : <b>${arpRate}</b> note${arpRate === 1 ? '' : 's'} in the last 5 s
            — the badge lights up at 8+ (a run, synced to golem's clock).</p>` : ''}
        ${extraIdx < EXTRAS.length ? html`<button class="mini"
          onClick=${() => setSkipped(s => ({ ...s, [EXTRAS[extraIdx][0]]: true }))}>skip — ${EXTRAS[extraIdx][1]}</button>` : ''}
      </div>` : ''}

      ${step === 'review' ? html`<div class="cal-body">
        <p><b>Review</b> — saved to the controller's profile, shared by every preset :</p>
        <ul class="cal-review">
          <li>Keys : ${keys.lo != null ? `${noteName(keys.lo)} → ${noteName(keys.hi ?? keys.lo)}` : 'skipped'}${keys.middle != null ? ` · middle ${noteName(keys.middle)}` : ''}</li>
          <li>Pads : ${pads.filter(p => p != null).length ? pads.map((p, i) => p != null ? `${i + 1}=${noteName(p)}` : null).filter(Boolean).join(' · ') : 'skipped'}</li>
          <li>Knobs : ${knobs.filter(k => k != null).length ? knobs.map((k, i) => k != null ? `K${i + 1}=CC${k}` : null).filter(Boolean).join(' · ') : 'skipped'}</li>
          <li>Caps : ${Object.keys(caps).filter(k => caps[k]).join(' · ') || 'none verified'}</li>
          <li>Channels : ${keysCh && padsCh ? `keys ${keysCh} · pads ${padsCh}` : 'not measured'}</li>
        </ul>
        <${ChannelNote} />
        <p class="muted">Knobs & keyboard range apply immediately (knobs.json + hot reload). Pads and
        capabilities are stored in the profile for their future consumers.</p>
      </div>` : ''}

      ${Nav()}
    </div>
  </div>`;
}

// « CONNU ≠ BRANCHÉ » (docs/gear-registry.md, addendum 2026-09-23) : la liste = les contrôleurs CONNUS
// du rack (registre bridge/devices.py) ∪ les branchés. Un contrôleur calibré puis débranché reste là,
// « not connected » — avant, il disparaissait avec son profil intact sur le disque (« je repars
// de zéro »). Calibrer exige la présence : le bouton le dit, il ne se cache pas. « Forget » est la
// seule sortie, et elle est explicite.
export function DeviceState({ d }) {
  return d.connected
    ? html`<span class="dev-state on" title=${d.hw ? 'ALSA ' + d.hw : 'connected'}>● connected${d.port ? ' · USB ' + d.port : ''}</span>`
    : html`<span class="dev-state off" title="known to this rack — plug it in and it activates by itself, on any port">○ not connected${d.last_seen ? ' · last seen ' + esc(d.last_seen) : ''}</span>`;
}

export function ControllersPanel() {
  const { data, reload } = useAsync(() => fetch('/api/controllers').then(r => r.json()), []);
  const [calib, setCalib] = useState(null);
  const list = (data && data.controllers) || [];
  const forget = async c => { if (!c.key) return; await fetch('/api/devices/' + encodeURIComponent(c.key), { method: 'DELETE' }).catch(() => {}); reload(); };
  return html`<div class="cal-panel">
    <p class="muted cal-intro">USB keyboard/pad controllers. golem <b>probes</b> what it can and${' '}
    <b>learns</b> the rest from you — the profile makes every knob, pad and key exploitable. A controller
    stays known once it has been connected; unplugged, it is just not active.</p>
    ${list.length ? list.map(c => html`<div class=${cls('cal-ctl', !c.connected && 'dim')}>
      <span class="cal-ctl-ic">🎹</span>
      <div class="cal-ctl-tx"><span class="cal-ctl-nm"><b>${esc(c.name)}</b>${c.channels ? html`<span class=${cls('cal-chip', c.split ? 'ok' : 'warn')}
          title=${c.split ? 'golem sends each channel to its own sound' : 'a pad also plays the keyboard sound — calibrate to fix it'}>
          ${c.split ? `pads ch ${c.channels.pads} · keys ch ${c.channels.keys}` : `pads = keys, ch ${c.channels.keys}`}</span>` : ''}</span>
        <small class="muted"><${DeviceState} d=${c} /> · ${c.usb ? esc(c.usb) + ' · ' : ''}${c.calibrated ? `calibrated ${c.calibrated}` : (c.known ? 'never calibrated — using defaults' : 'not yet known — calibrate or bind it (Soundcard) to keep it')}</small></div>
      ${c.known ? html`<button class="chip edit-only" title="forget this device — the only way it leaves the rack" onClick=${() => forget(c)}>Forget</button>` : ''}
      <button class="primary edit-only" disabled=${!c.connected} title=${c.connected ? '' : 'plug it in to calibrate — golem listens to the real device'}
        onClick=${() => setCalib(c)}>${c.calibrated ? 'Re-calibrate' : 'Calibrate'}</button>
    </div>`) : html`<div class="empty">No USB MIDI controller known or connected.</div>`}
    ${calib ? html`<${CalibStepper} ctl=${calib} onClose=${() => setCalib(null)} onSaved=${reload} />` : ''}
  </div>`;
}

// ── pédales MIDI : vérification du mapping + wizard nouvelle pédale ─────────────
// Vérification COMPLÈTE : chaque mode, un par un. C'est un AUDIT du descripteur — long (39
// modes sur la Whammy), à faire quand on doute d'une table, pas à chaque branchement. Les
// contrôles canoniques (`verify.checks`, 3 questions) suffisent pour dire « ça marche chez moi ».
// Le verdict part par le MÊME endpoint que les contrôles rapides : un seul champ dans le fichier.
export function VerifyMapping({ pedal, onClose, onDone }) {
  const [i, setI] = useState(0);
  const [results, setResults] = useState({});
  const modes = (pedal && pedal.modes) || [];
  const cur = modes[i];
  const isWhammy = pedal && pedal.id === 'whammy-dt';
  useEffect(() => {                                           // envoie le PC du mode courant
    if (!cur) return;
    // la Whammy garde son chemin dédié (il tient l'état du rig) ; les autres partent en MIDI brut
    if (isWhammy) post('/api/whammy', { mode: cur.name, active: true }).catch(() => {});
    else post('/api/calibrate/midi', { pc: cur.active_pc, channel: pedal.channel || 1 }).catch(() => {});
  }, [i, modes.length]);
  const mark = ok => { setResults(r => ({ ...r, [cur.name]: ok })); setI(x => x + 1); };
  const done = i >= modes.length && modes.length > 0;
  const saveVerdict = async () => {
    const ko = Object.keys(results).filter(k => !results[k]);
    await post('/api/pedals/' + pedal.id + '/verify',
               { failed: ko, scope: 'full', checked: modes.length }).catch(() => {});
    onDone ? onDone() : onClose();
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card cal-card">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Check every mode — ${esc((pedal || {}).name || '')}</h2>
      ${!modes.length ? html`<p class="muted">This mapping has no mode.</p>`
      : done ? html`<div class="cal-body">
          <p><b>${modes.length - Object.values(results).filter(v => !v).length}/${modes.length} confirmed.</b>
          ${Object.values(results).some(v => !v) ? ' Failed: ' + Object.keys(results).filter(k => !results[k]).join(', ') : ' The mapping is no longer an act of faith.'}</p>
          <div class="cal-nav"><span class="grow"></span><button class="primary" onClick=${saveVerdict}>💾 Save verdict</button></div>
        </div>`
      : html`<div class="cal-body">
          <p>Mode <b>${i + 1}/${modes.length}</b> sent : the pedal display should show
          <b class="cal-mode">${esc((cur || {}).name || '')}</b></p>
          <div class="cal-nav">
            <button class="chip" onClick=${() => mark(false)}>✗ not that</button>
            <span class="grow"></span>
            <button class="chip on" onClick=${() => mark(true)}>✓ confirmed</button>
          </div>
        </div>`}
    </div>
  </div>`;
}

export function NewPedalWizard({ onClose }) {
  const [name, setName] = useState('');
  const [channel, setChannel] = useState(1);
  const [treadleCc, setTreadleCc] = useState(11);
  const [pc, setPc] = useState(0);
  const [label, setLabel] = useState('');
  const [modes, setModes] = useState([]);
  const sendPc = async n => { setPc(n); setLabel(''); await post('/api/calibrate/midi', { pc: n, channel }).catch(() => {}); };
  const addMode = () => { if (!label.trim()) return; setModes(m => [...m, { name: label.trim(), family: 'custom', active_pc: pc }]); setLabel(''); };
  const save = async () => {
    const id = name.trim().toLowerCase().replace(/[^\w-]+/g, '-');
    await post('/api/mapping', { id, name: name.trim(), device: name.trim(), channel,
      treadle_cc: treadleCc, treadle: { cc: treadleCc, toe_up: 0, toe_down: 127 }, modes,
      _source: `wizard calibration ${new Date().toISOString().slice(0, 10)} (docs/calibration.md)` }).catch(() => {});
    onClose();
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card cal-card">
      <button class="close" onClick=${onClose}>×</button>
      <h2>New MIDI pedal mapping</h2>
      <div class="cal-body">
        <div class="cal-row"><label>Pedal name</label><input value=${name} placeholder="e.g. H9, Big Sky…" onInput=${e => setName(e.target.value)} /></div>
        <div class="cal-row"><label>MIDI channel</label><input type="number" min="1" max="16" value=${channel} onInput=${e => setChannel(+e.target.value || 1)} />
          <label>Treadle CC</label><input type="number" min="0" max="127" value=${treadleCc} onInput=${e => setTreadleCc(+e.target.value || 11)} />
          <button class="mini" title="sweep 0→127 on the treadle CC — the pedal should react"
            onClick=${() => post('/api/calibrate/midi', { sweep_cc: treadleCc, channel }).catch(() => {})}>▶ sweep test</button></div>
        <p><b>Map the programs</b> — golem sends a PC, you read the pedal :</p>
        <div class="cal-row">
          <button class="mini" onClick=${() => sendPc(Math.max(0, pc - 1))}>◀</button>
          <b class="cal-mode">PC ${pc}</b>
          <button class="mini" onClick=${() => sendPc(pc + 1)}>▶</button>
          <input value=${label} placeholder="what does the pedal show ?" onInput=${e => setLabel(e.target.value)}
            onKeyDown=${e => e.key === 'Enter' && addMode()} />
          <button class="chip" onClick=${addMode}>+ add</button>
        </div>
        ${modes.length ? html`<ul class="cal-review">${modes.map(m => html`<li>PC ${m.active_pc} → ${esc(m.name)}</li>`)}</ul>` : ''}
        <div class="cal-nav"><span class="grow"></span>
          <button class="primary" disabled=${!name.trim() || !modes.length} onClick=${save}>💾 Save mapping</button></div>
      </div>
    </div>
  </div>`;
}

export function PedalCalib() {
  const [verify, setVerify] = useState(false);
  const [wizard, setWizard] = useState(false);
  return html`<div class="cal-pedtools">
    <button class="chip" onClick=${() => setVerify(true)} title="golem sends each program change, you confirm what the pedal displays">✓ Verify Whammy mapping</button>
    <button class="chip" onClick=${() => setWizard(true)} title="build a mapping for a pedal golem has never seen — it sends, you observe">+ New pedal mapping</button>
    ${verify ? html`<${VerifyMapping} onClose=${() => setVerify(false)} />` : ''}
    ${wizard ? html`<${NewPedalWizard} onClose=${() => setWizard(false)} />` : ''}
  </div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// LA VÉRIFICATION DE PREMIÈRE INSTALLATION (docs/health.md §2, mockups/first-check.html) : la part pure, testée
// (first-check-model.test.mjs). Entrées : le statut du bridge (GET /api/health/first-check : auto[], steps{}, now,
// foot_wait_s), le geste en cours et ce que l'écran voit en direct (crête du vumètre, clic qui tourne, secondes
// restantes). Sorties : les lignes {id, name, state: ok|on|wait|late|skip, text} dans le vocabulaire de l'écran de
// chargement, et le bilan {level, title, text}. RÈGLE : rien n'est une erreur avant son délai ; une ligne dit ce qui
// a été mesuré, en chiffres quand il y en a.

// Le vumètre OSC de REAPER est LINÉAIRE EN dB : 0 → −72 dB, 1 → +6 dB (mesuré au rig, voir bridge/first_check.py) —
// pas une amplitude. Les seuils se disent en dBFS et se convertissent.
export const VU_MIN_DB = -72, VU_MAX_DB = 6;
export const vuDb = v => (v > 0 ? VU_MIN_DB + v * (VU_MAX_DB - VU_MIN_DB) : null);
export const dbVu = d => (d - VU_MIN_DB) / (VU_MAX_DB - VU_MIN_DB);
export const INPUT_MIN = dbVu(-45);                  // au-dessus, quelqu'un joue (une entrée vide est sous −72 dB)
export const GAIN_LOW_DB = -24, GAIN_HOT_DB = -3;      // les mêmes seuils que bridge/first_check.py (gain_of)
export const METERED = 3;                            // le bridge ne reçoit le vumètre que des pistes d'entrée 1 à 3 (app.py on_osc)
// les instruments qu'on propose pour une entrée AUDIO de la carte (les autres rôles de l'input map sont MIDI/USB)
// (ids, noms et icônes de bridge/inputmap.py INSTRUMENTS)
export const AUDIO_ROLES = [{ id: 'guitar', name: 'Guitar', icon: '🎸' }, { id: 'bass', name: 'Bass', icon: '🎸' },
  { id: 'voice', name: 'Voice', icon: '🎤' }, { id: 'keys', name: 'Keys', icon: '🎹' }, { id: 'line', name: 'Line', icon: '〜' }];
export const inst = id => AUDIO_ROLES.find(x => x.id === id) || { id, name: id ? id[0].toUpperCase() + id.slice(1) : '', icon: '' };
export const STEPS = ['input', 'output', 'foot'];
const NAMES = { input: '1 · Plug and play', output: '2 · Listen', foot: '3 · Press a switch' };

const LEVEL_STATE = { ok: 'ok', wait: 'wait', warn: 'late', bad: 'late' };
export const autoRows = status => ((status && status.auto) || []).map(f => ({ id: f.id, name: f.name, state: LEVEL_STATE[f.level] || 'wait', text: f.text }));

export const db = peak => (peak > 0 ? vuDb(peak).toFixed(0) : null);

// le verdict de gain d'une crête (0..1) : low · good · hot ; l'écrêtage vu par le bridge l'emporte
export const gainOf = (peak, clipped) => {
  if (clipped) return 'hot';
  if (!(peak > 0)) return null;
  const d = vuDb(peak);
  return d < GAIN_LOW_DB ? 'low' : d > GAIN_HOT_DB ? 'hot' : 'good';
};
export const gainText = (gain, ch) => gain === 'good' ? 'good level'
  : gain === 'low' ? 'low — turn up the gain of IN ' + ch + ' on the card'
  : gain === 'hot' ? 'too hot — turn down the gain of IN ' + ch + ' on the card' : '';

// les entrées audio de la carte, avec ce que l'input map dit d'elles (state.inputmap.inputs) ; sans input map, IN 1 et 2
export const cardInputs = inputmap => {
  const ins = (inputmap && inputmap.inputs) || [];
  const list = ins.length ? ins : [{ ch: '1' }, { ch: '2' }];
  return list.map(i => ({ ch: Number(i.ch), role: i.role && i.role !== 'none' ? i.role : null, label: i.label || null, icon: i.icon || null }))
    .filter(i => i.ch > 0);
};

// l'entrée qu'on écoute : la plus forte des crêtes récentes au-dessus du seuil (deux instruments branchés : celui qui joue)
export const loudest = peaks => {
  let best = null;
  for (const [ch, p] of Object.entries(peaks || {})) if (p >= INPUT_MIN && (!best || p > best.peak)) best = { ch: Number(ch), peak: p };
  return best;
};
const roleName = r => (r ? inst(r).name : null);

// `live` : {peak, ticks, left_s, clickOff} — ce que l'écran voit pendant le geste en cours
export const gestureRows = (steps, current, live) => {
  steps = steps || {}; live = live || {};
  return STEPS.map(id => {
    const r = steps[id];
    if (r) {
      if (id === 'input') {
        const where = (r.role ? roleName(r.role) + ' on ' : 'signal seen on ') + 'IN ' + (r.input || 1);
        const lvl = r.peak_db != null ? ' — peak ' + Math.round(r.peak_db) + ' dBFS' + (r.gain ? ', ' + gainText(r.gain, r.input || 1) : '') : '';
        return { id, name: NAMES.input, state: !r.ok ? 'late' : r.gain && r.gain !== 'good' ? 'late' : 'ok',
          text: r.ok ? where + lvl : 'no signal seen on any input',
          fix: r.ok ? (r.gain === 'low' ? 'Turn up the input gain' : r.gain === 'hot' ? 'Turn down the input gain' : null) : 'Check the cable and the input gain' };
      }
      if (id === 'output') return { id, name: NAMES.output, state: r.ok ? 'ok' : 'late',
        text: r.ok ? 'you heard the click on the main output' : (r.click_ticks ? 'the click ran but you did not hear it' : 'the click did not start'),
        fix: r.ok ? null : 'Check the monitors and the output in Settings ▸ Gear ▸ Soundcard' };
      return { id, name: NAMES.foot, state: r.ok ? 'ok' : 'late',
        text: r.ok ? 'the pedalboard answered' : 'nothing received in ' + (live.foot_wait_s || 30) + ' s — no switch heard',
        fix: r.ok ? null : 'Check the USB or MIDI cable' };
    }
    if (current === id) {
      if (id === 'input') return { id, name: NAMES.input, state: 'on', text: live.peak > 0 && live.ch ? 'we hear IN ' + live.ch + ' at ' + db(live.peak) + ' dBFS' : 'play something — we watch every input of the card' };
      if (id === 'output') return { id, name: NAMES.output, state: 'on', text: live.clickOff ? 'the click is off in this mode' : live.ticks ? 'the click is playing — beat ' + live.ticks : 'starting the click…' };
      return { id, name: NAMES.foot, state: 'on', text: 'press any switch of the pedalboard' + (live.left_s != null ? ' · ' + Math.max(0, Math.ceil(live.left_s)) + ' s' : '') };
    }
    return { id, name: NAMES[id], state: 'wait', text: id === 'input' ? 'next — plug in and play' : id === 'output' ? 'next — the click will play on the main output' : 'next — any switch of the pedalboard' };
  });
};

// le bilan, une phrase : tout vert, ou le premier geste qui manque avec ce qu'il faut faire
export const summary = steps => {
  steps = steps || {};
  const ok = id => !!(steps[id] && steps[id].ok);
  const g = steps.input && steps.input.ok && steps.input.gain;
  if (ok('input') && ok('output') && ok('foot') && g && g !== 'good') return { level: 'warn', title: 'Ready, one adjustment: the input gain.',
    text: 'IN ' + (steps.input.input || 1) + ' is ' + gainText(g, steps.input.input || 1) + '. Everything else works.' };
  if (ok('input') && ok('output') && ok('foot')) return { level: 'ok', title: 'Ready: sound in, sound out, the pedalboard answers.', text: 'This golem works. Play.' };
  if (!ok('input')) return { level: 'bad', title: 'No signal came in.', text: 'Nothing was seen on any input of the card. Check the cable and the input gain, then try again — the rest cannot be judged without sound in.' };
  if (!ok('output')) return { level: 'bad', title: 'Sound comes in but the click was not heard.', text: 'Check the monitors are on and plugged into the main output, or choose another output in Settings ▸ Gear ▸ Soundcard.' };
  return { level: 'warn', title: 'Almost ready: sound in and out, one thing left.', text: 'The pedalboard did not answer. You can play from the screen now; the foot can wait.' };
};

export const fmtTook = s => (s == null ? '' : s < 60 ? Math.round(s) + ' s' : Math.floor(s / 60) + ' min ' + Math.round(s % 60) + ' s');

// DEV : un statut fabriqué pour voir l'écran sans rack neuf (main.js : ?boot=firstcheck[&at=input|done]) — l'écran 1 pendant
// le geste 2, l'écran 2 au bilan de la maquette
export const demoStatus = at => {
  const auto = [
    { id: 'engine', name: 'Engine', level: 'ok', text: 'REAPER 7.79 · started and answers the bridge' },
    { id: 'audio', name: 'Sound card', level: 'ok', text: 'Volt 276 · 48 kHz · 128 samples · 2.7 ms' },
    // les chiffres de l'USINE (la doc des musiciens montre cette démo) : 9 presets, 38 patches, 1 chanson — pas un rack de dev
    { id: 'content', name: 'Factory content', level: 'ok', text: '9 presets · 38 patches · 1 song · 7 kits' },
    { id: 'preset', name: 'First preset', level: 'ok', text: '“Rooftop Prowl” posed: 12 blocks, every file loaded (3 checked)' }];
  const input = { ok: true, input: 2, role: 'guitar', peak_db: -11, gain: 'good', took_s: 12 };
  if (at === 'input') return { pending: true, auto, steps: {}, current: { step: 'input', at: 990 }, now: 1000, foot_wait_s: 30,
    demo: { levels: { in1: 0, in2: dbVu(-11) } } };
  if (at === 'done') return { pending: false, auto, done_at: 1000, took_s: 160, verdict: 'partial', now: 1000, foot_wait_s: 30,
    steps: { input, output: { ok: true, heard: true, click_ticks: 42 }, foot: { ok: false, answered: false, took_s: 30 } } };
  return { pending: true, auto, steps: { input }, current: { step: 'output', at: 990 }, now: 1000, foot_wait_s: 30, demo: { ticks: 7 } };
};

// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { autoRows, gestureRows, summary, db, demoStatus, fmtTook, gainOf, gainText, cardInputs, loudest, inst, vuDb, dbVu, INPUT_MIN } from './first-check-model.mjs';

test('les faits automatiques parlent le vocabulaire de l’écran de chargement', () => {
  const rows = autoRows({ auto: [{ id: 'engine', name: 'Engine', level: 'ok', text: 'x' }, { id: 'audio', name: 'Sound card', level: 'bad', text: 'y' },
    { id: 'preset', name: 'First preset', level: 'wait', text: 'z' }] });
  assert.deepEqual(rows.map(r => r.state), ['ok', 'late', 'wait']);
  assert.deepEqual(autoRows(null), []);
});

test('un geste fait dit sa mesure, le geste en cours dit ce que l’écran voit, les autres attendent', () => {
  const rows = gestureRows({ input: { ok: true, input: 1, peak_db: -9 } }, 'output', { ticks: 7 });
  assert.equal(rows[0].state, 'ok'); assert.equal(rows[0].text, 'signal seen on IN 1 — peak -9 dBFS');
  assert.equal(rows[1].state, 'on'); assert.equal(rows[1].text, 'the click is playing — beat 7');
  assert.equal(rows[2].state, 'wait');
  const r2 = gestureRows({}, 'input', { peak: dbVu(-20), ch: 2 });
  assert.match(r2[0].text, /IN 2 at -20 dBFS/);
  assert.equal(gestureRows({}, 'input', {})[0].text, 'play something — we watch every input of the card');
  const r3 = gestureRows({}, 'foot', { left_s: 12.4 });
  assert.equal(r3[2].text, 'press any switch of the pedalboard · 13 s');
  const r4 = gestureRows({ input: { ok: false, input: 1 }, output: { ok: false, click_ticks: 0 }, foot: { ok: false } }, null, { foot_wait_s: 30 });
  assert.deepEqual(r4.map(r => r.state), ['late', 'late', 'late']);
  assert.equal(r4[0].text, 'no signal seen on any input'); assert.equal(r4[1].text, 'the click did not start');
  assert.equal(r4[2].text, 'nothing received in 30 s — no switch heard'); assert.ok(r4[2].fix);
  assert.equal(gestureRows({}, 'output', { clickOff: true })[1].text, 'the click is off in this mode');
});

test('une entrée jouée dit ce qui y est branché, sa crête et le verdict de gain', () => {
  const ok = gestureRows({ input: { ok: true, input: 2, role: 'guitar', peak_db: -11.4, gain: 'good' } }, null, {})[0];
  assert.equal(ok.state, 'ok'); assert.equal(ok.text, 'Guitar on IN 2 — peak -11 dBFS, good level'); assert.equal(ok.fix, null);
  const low = gestureRows({ input: { ok: true, input: 1, peak_db: -30, gain: 'low' } }, null, {})[0];
  assert.equal(low.state, 'late'); assert.match(low.text, /^signal seen on IN 1 — peak -30 dBFS, low — turn up the gain of IN 1/);
  assert.equal(low.fix, 'Turn up the input gain');
  assert.equal(gainOf(dbVu(-18)), 'good'); assert.equal(gainOf(dbVu(-30)), 'low'); assert.equal(gainOf(dbVu(-1)), 'hot');
  assert.equal(gainOf(dbVu(-18), true), 'hot', 'l’écrêtage vu par le bridge l’emporte'); assert.equal(gainOf(0), null);
  // la mesure du rig (2026-10-20) : une crête à −18 dBFS rendait 0,685 au vumètre OSC — un bon niveau, pas « trop chaud »
  assert.equal(Math.round(vuDb(0.685)), -19); assert.equal(gainOf(0.685), 'good');
  assert.ok(INPUT_MIN > 0.3 && INPUT_MIN < 0.4, 'le seuil « quelqu’un joue » est à −45 dBFS');
  assert.equal(gainText('hot', 2), 'too hot — turn down the gain of IN 2 on the card');
});

test('les entrées de la carte viennent de l’input map ; on écoute la plus forte au-dessus du seuil', () => {
  const ins = cardInputs({ inputs: [{ ch: '1', role: 'voice', label: 'Voice', icon: '🎤' }, { ch: '2', role: 'none' }] });
  assert.deepEqual(ins.map(i => [i.ch, i.role]), [[1, 'voice'], [2, null]]);
  assert.deepEqual(cardInputs(null).map(i => i.ch), [1, 2], 'sans input map : IN 1 et 2');
  assert.deepEqual(loudest({ 1: 0.2, 2: 0.7, 3: 0.5 }), { ch: 2, peak: 0.7 });
  assert.equal(loudest({ 1: 0.2 }), null, 'sous le seuil (−56 dBFS), personne ne joue');
  assert.equal(inst('voice').icon, '🎤'); assert.equal(inst('drums').name, 'Drums');
});

test('le bilan : tout vert, ou le premier geste qui manque avec son geste', () => {
  assert.equal(summary({ input: { ok: true }, output: { ok: true }, foot: { ok: true } }).level, 'ok');
  assert.equal(summary({ input: { ok: false }, output: { ok: true }, foot: { ok: true } }).level, 'bad');
  assert.match(summary({ input: { ok: true }, output: { ok: false }, foot: { ok: true } }).title, /click was not heard/);
  const s = summary({ input: { ok: true }, output: { ok: true }, foot: { ok: false } });
  assert.equal(s.level, 'warn'); assert.match(s.title, /Almost ready/); assert.match(s.text, /pedalboard did not answer/);
  assert.equal(summary({}).level, 'bad'); assert.match(summary({}).text, /any input/);
  const g = summary({ input: { ok: true, input: 2, gain: 'low' }, output: { ok: true }, foot: { ok: true } });
  assert.equal(g.level, 'warn'); assert.match(g.text, /IN 2 is low/);
});

test('dB, durées, et la démo des deux écrans', () => {
  assert.equal(db(1), '6'); assert.equal(db(dbVu(-20)), '-20'); assert.equal(db(0), null);
  assert.equal(fmtTook(45), '45 s'); assert.equal(fmtTook(160), '2 min 40 s'); assert.equal(fmtTook(null), '');
  assert.equal(demoStatus().current.step, 'output'); assert.equal(demoStatus('done').verdict, 'partial');
  assert.equal(demoStatus('input').current.step, 'input'); assert.ok(demoStatus('input').demo.levels.in2 > 0);
});

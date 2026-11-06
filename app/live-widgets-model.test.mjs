// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { widgetsOf, countInBars, lineSeconds, setLate, fmtClock } from './live-widgets-model.mjs';

test('les widgets : le défaut, une surcharge, un emplacement vidé, un widget qui ne tient pas retombe', () => {
  assert.deepEqual(widgetsOf({}, 'rehearsal'), { right: 'chords', bottom: 'lyrics' });
  const m = { ui: { widgets: { timeline: { top1: null, bottom: 'chords' }, rehearsal: { right: 'lyrics' } } } };
  assert.deepEqual(widgetsOf(m, 'timeline'), { top1: null, top2: 'set_clock', bottom: 'chords' });
  assert.equal(widgetsOf(m, 'rehearsal').right, 'chords');            // les paroles ne tiennent pas en M
});

test('le décompte : 2 mesures sous 2 s la mesure, 1 au-dessus', () => {
  assert.equal(countInBars({ bars: 12, dur: 30 }), 1);                 // 96 BPM : 2,5 s la mesure
  assert.equal(countInBars({ bars: 8, dur: 10.67 }), 2);               // 180 BPM : 1,33 s
});

test('l\'horloge du set : en retard, en avance, et rien quand une durée manque', () => {
  const ln = bars => ({ bpm: 120, arrangement: { params: { sections: [{ bars }] } } });   // 2 s la mesure
  assert.equal(lineSeconds(ln(10)), 20);
  const lines = [ln(10), ln(10), ln(10)];
  assert.equal(setLate({ startedAt: 1000, now: 1050, lines, curIdx: 2, pos: 5 }), 5);    // 50 − (40 + 5)
  assert.equal(setLate({ startedAt: 1000, now: 1040, lines, curIdx: 2, pos: 5 }), -5);
  assert.equal(setLate({ startedAt: 1000, now: 1050, lines: [{}, ln(10)], curIdx: 1, pos: 5 }), null);
  assert.equal(fmtClock(-130), '2:10');
});

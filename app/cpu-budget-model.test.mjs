// SPDX-License-Identifier: GPL-3.0-or-later
// node --test app/cpu-budget-model.test.mjs — le budget CPU côté app (docs/cpu-budget.md §3, §4, §9)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  levelOf, verdictOf, fmtPct, fmtCores, barWidth, verdictChip, sceneLine, blockChips, heaviestLine, lanePctIn, laneAlerts,
  gainText, gainLevel, fixButton, fixesFor, machineLine, whenText, budgetLine, stageChip, nextChip, namArch, namVariant,
  blockQuery, blockKey, costPct, blockCostLine, captureCostLabel, rangeLine, afterAdd, swapView, swapHint, addLaneState, blockLevel,
} from './cpu-budget-model.mjs';

// une estimation au format du contrat (§9)
const EST = {
  verdict: 'tight', budget_us: 4000, cores: 1.4, total_cores: 8,
  worst: { lane: 'guitar-1', scene: 'C', pct: 78 },
  lanes: [
    { id: 'guitar-1', name: 'Guitar', pct: 78, worst_scene: 'C', by_scene: { A: 78, B: 41, C: 74 },
      blocks: [
        { id: 'g', type: 'gate', label: 'Gate', pct: 2, stereo: false, measured: true, on: { A: true, B: true, C: true } },
        { id: 'f', type: 'gfx-fuzz', label: 'Fuzz', pct: 22, stereo: true, measured: true, on: { A: true, B: false, C: true } },
        { id: 'a', type: 'amp-nam', label: 'EVH 5150', pct: 18, stereo: false, measured: true, on: {} },
        { id: 'x', type: 'vst-host', label: 'Mystery', pct: null, stereo: false, measured: false, on: {} },
      ] },
    { id: 'voice-1', name: 'Voice', pct: 34, by_scene: { A: 34, B: 34, C: 34 }, blocks: [] },
    { id: 'bass-1', name: 'Bass', pct: 92, by_scene: { A: 92 }, blocks: [] },
  ],
  fixes: [
    { id: 'perf', title: 'CPU in performance mode', sub: 'powersave', gain_pct: 25, action: { kind: 'perf-mode' } },
    { id: 'mono', title: 'Fuzz: stereo → mono', sub: '', gain_pct: 15, action: { kind: 'mono', block: 'f' } },
    { id: 'buf', title: 'Buffer 192 → 256', sub: '+1.3 ms', gain_pct: 20, action: { kind: 'buffer', bsize: 256 } },
    { id: 'light', title: 'Lighter capture', sub: '', gain_pct: 9, action: { kind: 'lighter-capture', block: 'a' } },
    { id: 'bass', title: 'Bass only', sub: '', gain_pct: 30, action: { kind: 'turn-off', block: 'z', scene: 'A', lane: 'bass-1' } },
    { id: 'none', title: 'Too heavy for this golem', sub: '', gain_pct: null, action: null },
  ],
  machine: { cpu: 'Ryzen 7 8700G', governor: 'performance', bsize: 192, srate: 48000 }, measured_at: '2026-11-16T22:40:00',
};

test('levels follow the 60 / 80 thresholds; null is unknown, never zero', () => {
  assert.equal(levelOf(0), 'ok');
  assert.equal(levelOf(60), 'ok');
  assert.equal(levelOf(60.5), 'tight');
  assert.equal(levelOf(80), 'tight');
  assert.equal(levelOf(81), 'red');
  assert.equal(levelOf(null), 'unknown');
  assert.equal(levelOf(undefined), 'unknown');
  assert.equal(levelOf(NaN), 'unknown');
  assert.equal(verdictOf('red', 10), 'red');            // le verdict du bridge l'emporte
  assert.equal(verdictOf('bogus', 70), 'tight');
});

test('formatting: whole percents, cores as information, bars clamped', () => {
  assert.equal(fmtPct(77.6), '78 %');
  assert.equal(fmtPct(null), '—');
  assert.equal(fmtCores(1.43, 8), '1.4 of 8 cores');
  assert.equal(fmtCores(null, 8), '');
  assert.equal(barWidth(130), 100);
  assert.equal(barWidth(-3), 0);
  assert.equal(barWidth(null), 0);
});

test('the verdict chip names the busiest lane', () => {
  assert.deepEqual(verdictChip(EST), { level: 'tight', text: 'Tight · lane Guitar 78 %' });
  assert.deepEqual(verdictChip({ verdict: 'ok', worst: { lane: 'voice-1', pct: 34 }, lanes: EST.lanes }), { level: 'ok', text: 'Plays · lane Voice 34 %' });
  assert.deepEqual(verdictChip({ verdict: 'unknown', worst: {}, lanes: [] }), { level: 'unknown', text: 'CPU not measured' });
  assert.equal(verdictChip(null), null);
});

test('scene line, block chips (off = dashed), heaviest blocks', () => {
  const g = EST.lanes[0];
  assert.equal(sceneLine(g, ['A', 'B', 'C', 'D']), 'A 78 · B 41 · C 74');
  assert.equal(sceneLine(g), 'A 78 · B 41 · C 74');
  const chips = blockChips(g, 'B');
  assert.equal(chips.find(c => c.id === 'f').off, true);
  assert.equal(chips.find(c => c.id === 'g').off, false);
  assert.equal(chips.find(c => c.id === 'x').cost, 'not measured');
  assert.equal(heaviestLine(g, 'A'), 'Fuzz 22 % (stereo) · EVH 5150 18 % · Gate 2 %');
  assert.equal(heaviestLine(g, 'B'), 'EVH 5150 18 % · Gate 2 %');   // la fuzz est coupée en B
  assert.equal(lanePctIn(g, 'B'), 41);
  assert.equal(lanePctIn(g, 'Z'), 78);
});

test('lane alerts: only tight and red lanes get a dot', () => {
  assert.deepEqual(laneAlerts(EST), { 'guitar-1': 'tight', 'bass-1': 'red' });
  assert.deepEqual(laneAlerts(null), {});
});

test('fixes: gain text and colour, a button only where golem can act, none on stage', () => {
  const [perf, mono, buf, light] = EST.fixes;
  assert.equal(gainText(perf), '−25 %');
  assert.equal(gainLevel(perf), 'ok');
  assert.equal(gainLevel(buf), 'tight');                // la latence a un prix
  assert.equal(gainLevel(light), 'tight');              // moins de 10 %
  assert.deepEqual(fixButton(perf), { kind: 'perf-mode', label: 'Turn on', primary: true });
  assert.equal(fixButton(buf).label, 'Settings');
  assert.equal(fixButton(mono), null);                  // une phrase, pas de bouton
  assert.equal(fixButton({ action: { kind: 'split' } }), null);
  assert.equal(fixButton(light), null);                 // l'écran ne sait pas faire
  assert.equal(fixButton(light, { can: ['lighter-capture'] }).label, 'Find');
  assert.equal(fixButton({ action: { kind: 'lighter-capture', block: 'a', ref: '12' } }, { can: ['lighter-capture'] }).label, 'Use it');
  assert.equal(fixButton({ action: { kind: 'turn-off', block: 'a', scene: 'A' } }, { can: ['turn-off'] }).label, 'Turn off');
  assert.equal(fixButton(perf, { stage: true }), null); // sur scène : lecture seule
  assert.equal(fixButton(EST.fixes[5]), null);
});

test('fixes follow their lane; untargeted fixes belong to the busiest lane', () => {
  assert.deepEqual(fixesFor(EST, 'guitar-1').map(f => f.id), ['perf', 'mono', 'buf', 'light', 'none']);
  assert.deepEqual(fixesFor(EST, 'bass-1').map(f => f.id), ['bass']);
  assert.deepEqual(fixesFor(EST, 'voice-1'), []);
  assert.deepEqual(fixesFor(null, 'x'), []);
});

test('every figure says which machine and when', () => {
  const now = new Date('2026-11-16T23:00:00');
  assert.equal(machineLine(EST, now), 'Measured on this golem · Ryzen 7 8700G · performance mode · 192 samples · 48 kHz · today 22:40');
  assert.equal(machineLine({ machine: {} }, now), 'Not measured on this golem yet.');
  assert.equal(machineLine(null, now), 'Not measured on this golem yet.');
  assert.equal(whenText('2026-11-15T09:05:00', now), 'yesterday 09:05');
  assert.equal(whenText('2026-11-02T09:05:00', now), '2 Nov');
  assert.equal(whenText('nope', now), '');
  assert.equal(budgetLine(EST), "Each lane runs on one core: its bar is that core's time for one buffer (4.0 ms · 192 samples · 48 kHz).");
});

test('on stage: a chip only when tight or red, never a number', () => {
  assert.deepEqual(stageChip({ verdict: 'tight', worst: { lane: 'g', scene: 'C', pct: 78 } }), { level: 'tight', text: 'CPU tight in scene C' });
  assert.deepEqual(stageChip({ verdict: 'red', worst: { scene: 'A', pct: 94 } }), { level: 'red', text: 'CPU will crackle in scene A' });
  assert.equal(stageChip({ verdict: 'ok', worst: { pct: 30 } }), null);
  assert.equal(stageChip({ verdict: 'unknown', worst: {} }), null);
  assert.equal(stageChip(undefined), null);
  assert.deepEqual(nextChip({ verdict: 'red' }), { level: 'red', text: 'CPU: will crackle' });
  assert.deepEqual(nextChip({ verdict: 'tight' }), { level: 'tight', text: 'CPU tight' });
  assert.equal(nextChip({ verdict: 'ok' }), null);
  for (const c of [stageChip({ verdict: 'red', worst: { scene: 'A', pct: 94 } }), nextChip({ verdict: 'tight' })])
    assert.ok(!/\d+ ?%/.test(c.text), 'no percentage on stage: ' + c.text);
});

test('NAM architecture as the profile variant', () => {
  assert.equal(namArch({ size: 'Lite' }), 'lite');
  assert.equal(namArch({ size: 'feather' }), 'feather');
  assert.equal(namArch({ arch: '2' }), 'a2');
  assert.equal(namArch({ arch: 2, size: 'lite' }), 'a2');
  assert.equal(namArch({}), 'standard');
  assert.equal(namArch({ size: 'custom' }), 'standard');
  assert.equal(namVariant({ size: 'nano' }), 'nam:nano');
  assert.equal(blockQuery('amp-nam', 'nam:lite', false), '/api/cpu/block?type=amp-nam&variant=nam%3Alite&stereo=0');
  assert.equal(blockQuery('delay', null, true), '/api/cpu/block?type=delay&stereo=1');
  assert.equal(blockKey('delay', null, true), 'delay|stereo');
});

test('a block cost, a capture cost, an amp range', () => {
  assert.equal(costPct({ pct: 9, measured: true }), 9);
  assert.equal(costPct({ pct: 9, measured: false }), null);
  assert.equal(blockCostLine({ pct: 9.2, measured: true }), '≈ 9 % of a core');
  assert.equal(blockCostLine({ pct: null, measured: false }), 'not measured on this golem');
  assert.equal(blockCostLine(null), '');                // route absente : rien
  assert.equal(captureCostLabel({ pct: 6, measured: true }, 'lite'), '6 % · lite');
  assert.equal(captureCostLabel({ measured: false }, 'standard'), 'not measured · standard');
  assert.equal(captureCostLabel(null, 'lite'), '');
  assert.equal(rangeLine([6, 18, 17.6, null]), '≈ 6–18 % of a core');
  assert.equal(rangeLine([12]), '≈ 12 % of a core');
  assert.equal(rangeLine([null]), '');
});

test('the add drawer: where the lane would go', () => {
  assert.deepEqual(afterAdd(78, { pct: 7, measured: true }), { pct: 85, level: 'red', text: '→ 85 %' });
  assert.deepEqual(afterAdd(40, { pct: 7, measured: true }), { pct: 47, level: 'ok', text: '→ 47 %' });
  assert.equal(afterAdd(null, { pct: 7 }), null);
  assert.equal(afterAdd(40, { pct: 7, measured: false }), null);
});

test('listening in a patch: before → after, and a lighter capture', () => {
  const v = swapView({ lane: 'guitar-1', before_pct: 78, after_pct: 82, verdict_after: 'tight', lighter: { ref: '1', model: 'm1', pct: 72 } });
  assert.equal(v.text, '78 % → 82 % · tight');
  assert.equal(v.base.w, 78);
  assert.equal(v.delta.from, 78);
  assert.equal(v.delta.w, 4);
  assert.equal(v.delta.freed, false);
  assert.equal(swapHint({ before_pct: 78, after_pct: 82, verdict_after: 'tight', lighter: { pct: 72 } }, { current: 'EVH 5150', arch: 'standard', lighterName: 'Capture 1 (lite)' }),
    'This capture (standard) costs 4 % more than the EVH 5150 it replaces. Capture 1 (lite) would bring the lane to 72 %.');
  assert.equal(swapHint({ before_pct: 50, after_pct: 40, verdict_after: 'ok', lighter: null }, {}),
    'This capture costs 10 % less than the capture it replaces.');
  assert.equal(swapView({ before_pct: null, after_pct: 3 }), null);
  assert.equal(swapHint(null), '');
});

test('a block is coloured on a block scale, not a lane scale', () => {
  assert.equal(blockLevel(6), 'ok');
  assert.equal(blockLevel(18), 'tight');
  assert.equal(blockLevel(30), 'red');
  assert.equal(blockLevel(null), 'unknown');
});

test('Add to… greys a lane pushed into red, and says why', () => {
  assert.deepEqual(addLaneState(92), { disabled: true, level: 'red', why: 'would go to 92 % of a core — it would crackle' });
  assert.equal(addLaneState(70).disabled, false);
  assert.equal(addLaneState(70).level, 'tight');
  assert.deepEqual(addLaneState(null), { disabled: false, why: '' });
});

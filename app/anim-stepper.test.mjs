// SPDX-License-Identifier: GPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import { stepPlan, stepped, phaseAt, startAnimStepper } from './anim-stepper.mjs';

test('une animation finie reste libre ; une infinie a deux états', () => {
  assert.equal(stepPlan({ duration: 300, iterations: 1 }), null);
  assert.deepEqual(stepPlan({ duration: 1700, iterations: Infinity, direction: 'normal' }), { half: 850, on: 0, off: 851 });
  // alternate : l'aller entier est un état, le retour l'autre
  assert.deepEqual(stepPlan({ duration: 500, iterations: Infinity, direction: 'alternate' }), { half: 500, on: 0, off: 499 });
});

test('les spinners et les cases du Live ne sont pas mis au pas', () => {
  assert.equal(stepped('swspin', []), false);
  assert.equal(stepped('lp-fire', ['lpad', 'stomp', 'anim-fire']), false);
  assert.equal(stepped('golem-caret', ['cur']), true);
});

test('la phase bascule à chaque demi-période', () => {
  const p = stepPlan({ duration: 1600, iterations: Infinity });
  assert.deepEqual([0, 799, 800, 1599, 1600].map(t => phaseAt(p, t)), [0, 0, 1, 1, 0]);
});

test('le minuteur met en pause et ne touche l\'animation qu\'à la bascule', () => {
  const writes = [];
  const anim = {
    animationName: 'led-pulse', paused: false,
    effect: { target: { nodeType: 1, classList: ['tile-led'] }, getTiming: () => ({ duration: 1600, iterations: Infinity }) },
    pause() { this.paused = true; },
    set currentTime(v) { writes.push(v); },
  };
  const spin = { animationName: 'swspin', effect: { target: { nodeType: 1, classList: [] }, getTiming: () => ({ duration: 900, iterations: Infinity }) },
    pause() { throw new Error('a spinner is never paused'); } };
  let now = 0;
  const doc = { getAnimations: () => [anim, spin] };
  const realSet = globalThis.setInterval;
  let tick;
  globalThis.setInterval = f => { tick = f; return 1; };
  try {
    startAnimStepper(doc, () => now);
    for (now of [100, 300, 799, 800, 900, 1600]) tick();
  } finally { globalThis.setInterval = realSet; }
  assert.equal(anim.paused, true);
  assert.deepEqual(writes, [0, 801, 0]);          // allumé, éteint à 800, rallumé à 1600 — rien entre deux
});

// SPDX-License-Identifier: GPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import { stepPlan, sortOf, isLocalHost, phaseAt, startAnimStepper, tilesStill, STILL_CLASS } from './anim-stepper.mjs';

test('une animation finie reste libre ; une infinie a deux états', () => {
  assert.equal(stepPlan({ duration: 300, iterations: 1 }), null);
  assert.deepEqual(stepPlan({ duration: 1700, iterations: Infinity, direction: 'normal' }), { half: 850, on: 0, off: 851 });
  // alternate : l'aller entier est un état, le retour l'autre
  assert.deepEqual(stepPlan({ duration: 500, iterations: Infinity, direction: 'alternate' }), { half: 500, on: 0, off: 499 });
});

test('au pas, figée ou libre', () => {
  assert.equal(sortOf('golem-caret', {}), 'step');
  assert.equal(sortOf('swspin', {}), 'free');                                          // un spinner tourne
  assert.equal(sortOf('lp-fire', { picker: true, tile: true }, { local: true }), 'free'); // l'aperçu du sélecteur
  // une case du Live, réglage auto : figée sur l'écran local, animée sur un écran déporté
  assert.equal(sortOf('lp-fire', { tile: true }, { local: true }), 'freeze');
  assert.equal(sortOf('lp-fire', { tile: true }, { local: false }), 'free');
  // on : animée partout ; off : figée partout (Settings ▸ System ▸ Display)
  assert.equal(sortOf('lp-fire', { tile: true }, { local: true, display: { animations: 'on' } }), 'free');
  assert.equal(sortOf('lp-fire', { tile: true }, { local: false, display: { animations: 'off' } }), 'freeze');
  // les voyants : au pas, ou tenus allumés
  assert.equal(sortOf('led-pulse', {}, { display: { animations: 'auto', blinks: false } }), 'hold');
});

test("l'écran local est celui de la machine qui joue le son", () => {
  assert.equal(isLocalHost('127.0.0.1'), true);
  assert.equal(isLocalHost('localhost'), true);
  assert.equal(isLocalHost('192.168.0.22'), false);
  assert.equal(isLocalHost('golem.local'), false);
});

test('la phase bascule à chaque demi-période', () => {
  const p = stepPlan({ duration: 1600, iterations: Infinity });
  assert.deepEqual([0, 799, 800, 1599, 1600].map(t => phaseAt(p, t)), [0, 0, 1, 1, 0]);
});

const fake = (name, duration, where) => ({
  animationName: name, paused: false, writes: [], where,
  effect: { target: { nodeType: 1 }, getTiming: () => ({ duration, iterations: Infinity }) },
  pause() { this.paused = true; }, play() { this.paused = false; },
  set currentTime(v) { this.writes.push(v); },
});

function run(anims, times, opts) {
  let now = 0, tick;
  const realSet = globalThis.setInterval;
  globalThis.setInterval = f => { tick = f; return 1; };
  try {
    startAnimStepper({ getAnimations: () => anims }, () => now, { where: el => anims.find(a => a.effect.target === el).where, ...opts });
    for (now of times) tick();
  } finally { globalThis.setInterval = realSet; }
}

test("le minuteur met en pause et ne touche l'animation qu'à la bascule", () => {
  const led = fake('led-pulse', 1600, {});
  const spin = fake('swspin', 900, {});
  spin.pause = () => { throw new Error('a spinner is never paused'); };
  run([led, spin], [100, 300, 799, 800, 900, 1600], { local: false });
  assert.equal(led.paused, true);
  assert.deepEqual(led.writes, [0, 801, 0]);          // allumé, éteint à 800, rallumé à 1600 — rien entre deux
});

test('cases figées : le curseur et les voyants sont tenus allumés, sans pas (0 image au repos)', () => {
  assert.equal(sortOf('golem-caret', {}, { local: true }), 'hold');                            // auto, écran local
  assert.equal(sortOf('golem-caret', {}, { local: false, display: { animations: 'off' } }), 'hold');
  assert.equal(sortOf('golem-caret', {}, { local: true, display: { animations: 'on', blinks: true } }), 'step');
  const led = fake('led-pulse', 1600, {});
  run([led], [100, 800, 1600, 2400], { local: true });
  assert.deepEqual(led.writes, [0]);                  // posé allumé une fois, plus jamais touché
});

test('une case figée en local repart quand le réglage la permet', () => {
  const fire = fake('lp-fire', 1000, { tile: true });
  let allow = false;
  const anims = [fire];
  let now = 0, tick;
  const realSet = globalThis.setInterval;
  globalThis.setInterval = f => { tick = f; return 1; };
  try {
    startAnimStepper({ getAnimations: () => anims }, () => now, { local: true, display: () => ({ animations: allow ? 'on' : 'auto', blinks: true }), where: () => fire.where });
    assert.equal(fire.paused, true);
    assert.deepEqual(fire.writes, [350]);             // figée au tiers de son cycle, une seule écriture
    for (now of [200, 400]) tick();
    assert.deepEqual(fire.writes, [350]);
    allow = true;
    tick();
    assert.equal(fire.paused, false);                 // rendue à l'écran local
  } finally { globalThis.setInterval = realSet; }
});

// une animation en pause garde sa couche composée : les cases figées perdent leurs animations (html.tiles-still)
test('les cases figées se rendent sans animation : classe racine selon le réglage et l’écran', () => {
  assert.equal(tilesStill({ local: true }), true);                                     // auto, écran local
  assert.equal(tilesStill({ local: false }), false);                                   // auto, tablette
  assert.equal(tilesStill({ local: false, display: { animations: 'off' } }), true);
  assert.equal(tilesStill({ local: true, display: { animations: 'on' } }), false);
  const cls = new Set();
  const root = { classList: { toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)) } };
  let allow = false, tick;
  const realSet = globalThis.setInterval;
  globalThis.setInterval = f => { tick = f; return 1; };
  try {
    startAnimStepper({ getAnimations: () => [], documentElement: root }, () => 0,
      { local: true, display: () => ({ animations: allow ? 'on' : 'auto', blinks: true }) });
    assert.equal(cls.has(STILL_CLASS), true);
    allow = true; tick();
    assert.equal(cls.has(STILL_CLASS), false);        // « Animated everywhere » : les cases retrouvent leurs animations
  } finally { globalThis.setInterval = realSet; }
});

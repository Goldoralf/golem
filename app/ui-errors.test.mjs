// SPDX-License-Identifier: GPL-3.0-or-later
// Les erreurs de l'app (ui-errors.mjs, docs/diagnostics.md §7.2) : ce qui part, et combien de fois.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { payload, frames, pageOf, watch, MAX_PER_LOAD } from './ui-errors.mjs';

const loc = { hash: '#/songs/rs-0123456789abcdef?tab=2', pathname: '/app/' };

test('la page sans ses paramètres ni ses ids', () => {
  assert.equal(pageOf(loc), '/songs');
  assert.equal(pageOf({ hash: '', pathname: '/app/m.html' }), 'm.html');
});

test('les frames : fichier:ligne, jamais l\'adresse', () => {
  const st = 'TypeError: x is undefined\n    at f (http://192.168.1.4:8770/app/page-live.js?v=2:120:7)\n    at http://192.168.1.4:8770/app/lib.js:33:1\ng@http://rack.local:8770/app/main.js:9:3';
  assert.deepEqual(frames(st), ['page-live.js:120', 'lib.js:33', 'main.js:9']);
});

test('un ErrorEvent et un rejet deviennent le même corps, sans adresse', () => {
  const err = new Error('boom'); err.stack = 'Error: boom\n    at f (http://10.0.0.2:8770/app/page-x.js:5:2)';
  const a = payload({ message: 'Uncaught Error: boom', filename: 'http://10.0.0.2:8770/app/page-x.js', lineno: 5, colno: 2, error: err }, loc, 'rack');
  assert.deepEqual(a, { page: '/songs', msg: 'Uncaught Error: boom', src: 'page-x.js', line: 5, col: 2, frames: ['page-x.js:5'], client: 'rack' });
  const b = payload({ reason: err }, loc, 'companion');
  assert.equal(b.msg, 'boom'); assert.equal(b.src, 'page-x.js'); assert.equal(b.line, 5);
  assert.ok(!JSON.stringify(a).includes('10.0.0.2'));
  assert.equal(payload({ reason: undefined }, loc, 'rack').msg, 'undefined');
  assert.equal(payload({ message: '' }, loc, 'rack'), null);
});

test('la même erreur une fois par chargement, et un plafond', () => {
  const ls = {};
  const win = { location: loc, addEventListener: (t, f) => { ls[t] = f; }, removeEventListener: () => {} };
  const sent = [];
  watch(win, 'rack', (b) => sent.push(b));
  for (let i = 0; i < 3; i++) ls.error({ message: 'same', filename: 'a.js', lineno: 1 });
  assert.equal(sent.length, 1);
  for (let i = 0; i < 50; i++) ls.unhandledrejection({ reason: new Error('e' + i) });
  assert.equal(sent.length, MAX_PER_LOAD);
});

test('un envoi qui échoue ne casse rien', () => {
  const ls = {};
  const win = { location: loc, addEventListener: (t, f) => { ls[t] = f; }, removeEventListener: () => {} };
  watch(win, 'rack', () => { throw new Error('offline'); });
  assert.doesNotThrow(() => ls.error({ message: 'x', filename: 'a.js', lineno: 1 }));
});

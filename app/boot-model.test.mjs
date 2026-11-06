// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { bootRows, showBoot, DEADLINES } from './boot-model.mjs';

const T0 = 1000;
const OK = { fm: { configured: true, ok: true }, t3k: { configured: true, ok: true } };
const st = (now, steps, more, services) => ({ boot: { t0: T0, now: T0 + now, steps: Object.fromEntries(Object.entries(steps || {}).map(([k, v]) => [k, T0 + v])), done: null, failed: null, last_took: 11, services: services || OK },
  caps: { os: 'windows' }, audio: { ok: !!(steps || {}).audio }, audio_metrics: { driver: 'ASIO Universal Audio Volt', buffer_size: 128 },
  midi: (steps || {}).midi != null ? { ok: true } : {}, pedalboard: { id: 'fcb1010-uno2', name: 'FCB1010' }, preset_name: 'Velvetine — Swerve Lane', ...(more || {}) });

test('à 9 s : moteur ok, carte en cours, rien en retard, pas de sortie', () => {
  const r = bootRows(st(9, { reaper: 2.1, osc: 6.4, fm: 1.9 }));
  assert.deepEqual(r.rows.map(x => [x.id, x.state]), [['bridge', 'ok'], ['reaper', 'ok'], ['audio', 'on'], ['midi', 'wait'], ['preset', 'wait'], ['fm', 'ok'], ['t3k', 'ok']]);
  assert.equal(r.rows[1].ms, '6.4 s');
  assert.match(r.rows[2].text, /opening ASIO Universal Audio Volt · 128 smp/);
  assert.equal(r.late, false);
});

test('REAPER muet 30 s après son démarrage : en retard, avec ses gestes ; « Keep waiting » repousse', () => {
  const r = bootRows(st(40, { reaper: 2 }));
  assert.equal(r.rows[1].state, 'late');
  assert.deepEqual(r.rows[1].actions, ['restart', 'wait']);
  assert.equal(r.late, true);
  assert.equal(bootRows(st(40, { reaper: 2 }), { osc: 30 }).late, false);      // 30 s de plus accordées
});

test('le délai de REAPER suit le dernier démarrage (double, 30 s minimum)', () => {
  assert.equal(DEADLINES(11).reaper, 30);
  assert.equal(DEADLINES(25).reaper, 50);
  assert.equal(bootRows(st(31, {})).rows[1].state, 'late');                   // last_took 11 → 30 s
});

test('MIDI absent ou en défaut est dit, jamais en retard', () => {
  const r = bootRows(st(20, { reaper: 2, osc: 6, audio: 8, midi: 9 }, { midi: { ok: false, issues: [{ text: 'pedalboard port held by REAPER' }], fix: 'restart for MIDI' } }));
  assert.equal(r.rows[3].state, 'skip');
  assert.match(r.rows[3].text, /pedalboard port held/);
  assert.equal(r.late, false);
});

test('TONE3000 en erreur : la page reste après « fini », la sortie apparaît ; golem.fm jamais appairé ne retient rien', () => {
  const bad = { fm: { configured: false, ok: false, why: 'not paired' }, t3k: { configured: true, ok: false, why: 'token expired' } };
  const s = st(14, { reaper: 2, osc: 6, audio: 8, midi: 9, preset: 12 }, null, bad); s.boot.done = T0 + 12;
  const r = bootRows(s);
  assert.equal(r.rows[5].state, 'skip'); assert.equal(r.rows[5].err, undefined); assert.match(r.rows[5].text, /^optional/);
  assert.equal(r.rows[6].state, 'late'); assert.match(r.rows[6].text, /token expired/); assert.deepEqual(r.rows[6].actions, ['setup']);
  assert.equal(r.late, true); assert.equal(r.servicesError, true);
  assert.equal(showBoot(s, null), true);                                      // fini, mais la page reste
  assert.equal(showBoot(s, T0), false);                                       // « Open the app anyway »
  const checking = st(3, {}, null, { fm: { configured: null, ok: null }, t3k: { configured: null, ok: null } });
  assert.deepEqual(bootRows(checking).rows.slice(5).map(x => x.state), ['on', 'on']);   // pas encore vérifié : pas une erreur
});

test('fini : le preset joue, l’écran se retire ; un restart (nouveau t0) le ramène malgré « anyway »', () => {
  const s = st(12, { reaper: 2, osc: 6, audio: 8, midi: 9, preset: 11.5 }); s.boot.done = T0 + 11.5;
  const r = bootRows(s);
  assert.equal(r.done, true); assert.equal(r.rows[4].state, 'ok'); assert.equal(r.rows[4].ms, '12 s');
  assert.equal(showBoot(s, null), false);
  const s2 = st(3, {});
  assert.equal(showBoot(s2, null), true);
  assert.equal(showBoot(s2, T0), false);                                      // sorti pour CE démarrage
  assert.equal(showBoot({ ...s2, boot: { ...s2.boot, t0: T0 + 500 } }, T0), true);   // un autre démarrage
});


test('un bridge plus vieux que la page (sans `services`) : les deux lignes sont dites, jamais en erreur', () => {
  const s = st(30, { reaper: 2, osc: 6, audio: 8 }); delete s.boot.services;
  const r = bootRows(s);
  assert.deepEqual(r.rows.slice(5).map(x => [x.id, x.state]), [['fm', 'skip'], ['t3k', 'skip']]);
  assert.equal(r.servicesError, false);
});

test('licence REAPER absente : une ligne orange avec « Set up », qui ne retient ni l’écran ni la sortie', () => {
  const sv = { ...OK, reaper: { present: false, state: null, ok: false } };
  const r = bootRows(st(9, { reaper: 2.1, osc: 6.4, fm: 1.9 }, null, sv));
  const lic = r.rows.find(x => x.id === 'lic');
  assert.equal(lic.state, 'late');
  assert.deepEqual(lic.actions, ['setup']);
  assert.match(lic.text, /^evaluation — add your license to remove the reminder$/);
  assert.equal(r.late, false);                         // pas de « Open the app anyway » pour un rappel d'achat
  assert.equal(r.servicesError, false);
  const done = st(14, { reaper: 2, osc: 6, audio: 8, midi: 9, preset: 12 }, null, sv); done.boot.done = T0 + 12;
  assert.equal(showBoot(done, null), false);           // fini : l'écran se retire quand même
});

test('licence REAPER posée, pas encore lue, ou bridge ancien : pas de ligne ; refusée par ce REAPER : dit', () => {
  for (const reaper of [{ present: true, ok: true }, { present: null, ok: null }, undefined]) {
    const r = bootRows(st(9, {}, null, { ...OK, ...(reaper ? { reaper } : {}) }));
    assert.equal(r.rows.some(x => x.id === 'lic'), false);
  }
  const r = bootRows(st(9, {}, null, { ...OK, reaper: { present: true, state: 'evaluation', ok: false } }));
  assert.match(r.rows.find(x => x.id === 'lic').text, /does not accept the license/);
});

test('un golem neuf (ni golem.fm ni TONE3000 réglés) : l’écran se retire dès que le preset joue (audit 2026-10-31)', () => {
  const fresh = { fm: { configured: false, ok: false, why: 'not paired' }, t3k: { configured: false, ok: false } };
  const s = st(14, { reaper: 2, osc: 6, audio: 8, midi: 9, preset: 12 }, null, fresh); s.boot.done = T0 + 12;
  const r = bootRows(s);
  assert.deepEqual(r.rows.slice(5, 7).map(x => [x.id, x.state, !!x.soft]), [['fm', 'skip', true], ['t3k', 'late', true]]);
  assert.equal(r.servicesError, false); assert.equal(r.late, false);
  assert.equal(showBoot(s, null), false);
});

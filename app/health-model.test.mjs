// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { healthDot, ago, countsLine, incidentChip, incidentLine, hintCandidate, undoCandidate, lastFixUndo } from './health-model.mjs';

test('pas de point tant que le bridge n’a pas mesuré', () => {
  assert.equal(healthDot(null), null);
  assert.equal(healthDot({}), null);
  assert.equal(healthDot({ health: null }), null);
});

test('le point suit le verdict ; seul le rouge met une pastille dans les menus et un mot à côté du point', () => {
  assert.deepEqual(healthDot({ health: { level: 'ok', bad: 0, warn: 0, title: 'Everything checks out.' } }),
    { level: 'ok', badge: null, text: '', title: 'Everything checks out.' });
  const warn = healthDot({ health: { level: 'warn', bad: 0, warn: 3, title: 'Playing is safe. 3 things to look at.' } });
  assert.equal(warn.level, 'warn'); assert.equal(warn.badge, null); assert.equal(warn.text, '');
  assert.match(warn.title, /3 things to look at in Settings/);
  const bad = healthDot({ health: { level: 'bad', bad: 1, warn: 2 } });
  assert.equal(bad.badge, 'bad'); assert.equal(bad.text, 'something is wrong'); assert.equal(bad.level, 'bad');
  assert.equal(healthDot({ health: { level: 'wait' } }).badge, null);
});

test('les âges viennent de l’horloge du bridge, en mots courts', () => {
  assert.equal(ago(12), '12 s ago'); assert.equal(ago(89.6), '90 s ago'); assert.equal(ago(600), '10 min ago');
  assert.equal(ago(7200), '2 h ago'); assert.equal(ago(null), ''); assert.equal(ago(-3), '');
});

test('la rangée des compteurs tait les zéros', () => {
  assert.deepEqual(countsLine({ ok: 12, warn: 1, bad: 0, wait: 1 }),
    [{ level: 'ok', n: 12 }, { level: 'warn', n: 1 }, { level: 'wait', n: 1, word: 'waiting' }]);
  assert.deepEqual(countsLine(null), []);
});

test('la pastille d’un incident dit comment il a fini', () => {
  assert.deepEqual(incidentChip({ state: 'open' }), { cls: 'open', text: 'open' });
  assert.equal(incidentChip({ state: 'verifying' }).text, 'verifying');
  assert.equal(incidentChip({ state: 'closed', resolved_by: 'action', by: 'button' }).text, 'fixed');
  assert.equal(incidentChip({ state: 'closed', resolved_by: 'action', by: 'assistant' }).text, 'fixed · assistant');
  assert.equal(incidentChip({ state: 'closed', resolved_by: 'outside', hint: 'gain' }).text, 'outside · gain');
  assert.equal(incidentChip({ state: 'closed', resolved_by: 'restart' }).cls, 'rs');
});

test('la ligne d’un incident, la question facultative et le retour arrière', () => {
  const now = Date.UTC(2026, 9, 20, 15, 0) / 1000;
  assert.match(incidentLine({ state: 'closed', closed_at: now - 600, after_s: 120 }, now), /^today \d\d:\d\d · back after 2 min$/);
  assert.match(incidentLine({ state: 'open', opened_at: now - 60, detail: '14 in the last 10 min' }, now), /^since \d\d:\d\d · 14 in the last 10 min$/);
  const items = [{ id: 'i3', state: 'open' }, { id: 'i4', state: 'closed', resolved_by: 'outside', closed_at: now - 60, hintable: false },
    { id: 'i2', state: 'closed', resolved_by: 'outside', closed_at: now - 120, hintable: true },
    { id: 'i1', state: 'closed', resolved_by: 'outside', closed_at: now - 7200, hintable: true }];
  assert.equal(hintCandidate(items, now, null).id, 'i2', 'golem.fm revenu tout seul ne demande pas « câble ou gain ? »');
  assert.equal(hintCandidate(items, now, 'a take is recording'), null, 'jamais pendant qu’on joue');
  assert.equal(hintCandidate([{ ...items[1], hint: 'cable' }], now, null), null);
  const undo = { action: 'set_buffer', params: { size: 128 } };
  assert.equal(undoCandidate([{ state: 'closed', resolved_by: 'action', undo }]).undo, undo);
  assert.equal(undoCandidate([{ state: 'closed', resolved_by: 'outside' }, { state: 'closed', resolved_by: 'action', undo }]), null);
});

test('une réparation sans incident garde son retour arrière une heure', () => {
  const undo = { action: 'set_buffer', params: { size: 192 } };
  const last = { phase: 'done', undo, ended_at: 1000, label: 'Lower the buffer' };
  assert.equal(lastFixUndo(last, 1600), last);
  assert.equal(lastFixUndo(last, 5000), null);
  assert.equal(lastFixUndo({ ...last, incident: 'i3' }, 1600), null, 'avec un incident, l’undo vit sur l’incident');
  assert.equal(lastFixUndo({ ...last, phase: 'verifying' }, 1600), null);
});

test('Health v2 : le verdict en mots, ce qui demande quelque chose, ce qui est une information', async () => {
  const M = await import('./health-model.mjs');
  const facts = [{ id: 'engine', level: 'ok' }, { id: 'golemfm', level: 'warn' }, { id: 'dropouts', level: 'warn' },
    { id: 'environment', level: 'warn' }, { id: 'playing', level: 'bad' }];
  assert.deepEqual(M.needs(facts).map(f => f.id), ['playing', 'dropouts', 'golemfm'], 'le rouge d’abord, golem.fm après, la mise à jour n’est pas un problème');
  assert.equal(M.verdictWords('warn', 2).title, 'Playable — 2 things need you');
  assert.equal(M.verdictWords('warn', 1).title, 'Playable — 1 thing needs you');
  assert.equal(M.verdictWords('ok', 0).title, 'Ready to play');
  assert.match(M.verdictWords('bad', 1).title, /^Not ready/);
  assert.equal(M.problemTitle({ id: 'dropouts' }), 'Clicks in the sound');
  assert.equal(M.plainName({ id: 'nouveau', name: 'New probe' }), 'New probe');
  assert.equal(M.chipText({ text: 'Golem Engine 9.9-g8 · running · talking to the bridge' }), 'Golem Engine 9.9-g8 · running');
  assert.equal(M.chipText({ text: '4 in the last 10 min — something interrupts' }), '4 in the last 10 min');
  assert.equal(M.sinceWords(1000, 1000 + 35 * 86400), '5 weeks ago');
  assert.equal(M.sinceWords(null, 5), 'never');
});

test('Health v2 : l’historique groupé par sujet, en mots', async () => {
  const M = await import('./health-model.mjs');
  const now = Date.UTC(2026, 10, 25, 16) / 1000;
  const rows = M.historyRows([
    { id: 'a', title: 'Audio dropouts', state: 'open', opened_at: now - 600 },
    { id: 'b', title: 'Sound card stopped', state: 'closed', closed_at: now - 1800, resolved_by: 'outside', after_s: 38 },
    { id: 'c', title: 'Audio dropouts', state: 'closed', closed_at: now - 3600, resolved_by: 'action' }], now);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].open, true); assert.match(rows[0].text, /^happening now · since .* · 2 times$/);
  assert.match(rows[1].text, /came back by itself after 38 s$/);
});

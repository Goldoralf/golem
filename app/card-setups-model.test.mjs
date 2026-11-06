// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { setupRows, chipLabel, labelOf } from './card-setups-model.mjs';

const INSTR = [{ id: 'guitar', icon: '🎸' }, { id: 'voice', icon: '🎤' }, { id: 'none', icon: '·' }];
const PEOPLE = { alex: 'Alex' };
// la vraie divergence du 2026-10-10 : Windows (ici) voix en 1, guitare en 2 ; le rack Linux l'inverse
const HERE = { inputs: [{ slot: 'IN 1', role: 'voice', nth: 1, name: 'Voice 1', person: null }, { slot: 'IN 2', role: 'guitar', nth: 1, name: 'Guitar 1', person: 'alex' }],
  outputs: [{ slot: 'OUT 1-2', role: 'monitors', type: null, person: null }], midi_in: 'fcb', midi_out: 'whammy-dt' };
const THERE = { inputs: [{ slot: 'IN 1', role: 'guitar', nth: 1, name: 'Guitar 1', person: 'alex' }, { slot: 'IN 2', role: 'voice', nth: 1, name: 'Voice 1', person: 'alex' },
  { slot: 'USB 1', kind: 'midi', role: 'keys', name: 'Keys' }],
  outputs: [{ slot: 'OUT 1-2', role: 'monitors', type: null, person: null }], midi_in: 'fcb', midi_out: 'whammy-dt' };

test('la comparaison dit ce qui diffère, entrée par entrée, et ignore les ports USB du rack', () => {
  const rows = setupRows(HERE, THERE, INSTR, PEOPLE);
  assert.deepEqual(rows.map(r => [r.k, r.same]), [['IN 1', false], ['IN 2', false], ['OUT 1-2', true], ['MIDI', true]]);
  assert.equal(rows[0].here, '🎤 Voice 1');
  assert.equal(rows[0].there, '🎸 Guitar 1 · Alex');          // la personne, par son nom du roster
  assert.equal(rows[1].here, '🎸 Guitar 1 · Alex');
});

test('une entrée absente d’un côté s’affiche « — », un id de personne inconnu reste tel quel', () => {
  const rows = setupRows({ inputs: [{ slot: 'IN 1', role: 'guitar', name: 'Guitar 1', person: 'sam' }] }, { inputs: [] }, INSTR, PEOPLE);
  assert.equal(rows[0].here, '🎸 Guitar 1 · sam');
  assert.equal(rows[0].there, '—');
  assert.equal(labelOf({ role: 'none' }, INSTR, PEOPLE), '· unassigned');
});

test('le chip : une proposition passe avant une divergence, « separate » et « same » se taisent', () => {
  assert.equal(chipLabel({ siblings: [{ rack_name: 'Rack', same: false, separate: false }] }), '⇄ Rack setup differs');
  assert.equal(chipLabel({ siblings: [{ rack_name: 'Rack', same: false, separate: true }] }), null);
  assert.equal(chipLabel({ siblings: [{ rack_name: 'Rack', same: true }] }), null);
  assert.equal(chipLabel({ siblings: [{ rack_name: 'Rack', same: false }], offers: [{ from_name: 'Rack' }] }), '⇄ setup offered by Rack');
  assert.equal(chipLabel(null), null);
});

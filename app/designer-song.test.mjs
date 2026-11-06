// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { sheetBlocks } from './designer-song.js';

test('une valeur pour la chanson : fusionnée sur les surcharges existantes de la fiche', () => {
  const sheet = { blocks: { clk: { params: { beats: 3 } }, smp: { params: { samples: ['a.wav'] } } } };
  assert.deepEqual(sheetBlocks(sheet, 'clk', { params: { den: 8 } }).clk, { params: { beats: 3, den: 8 } });
  assert.deepEqual(sheetBlocks(sheet, 'clk', { bypass: true }).clk, { params: { beats: 3 }, bypass: true });
  assert.deepEqual(sheetBlocks(sheet, 'clk', {}).smp, { params: { samples: ['a.wav'] } });      // les autres blocs intacts
  assert.deepEqual(sheet.blocks.clk, { params: { beats: 3 } });                                 // la fiche n'est pas mutée
});

test('« use the preset’s » retire la valeur, et un bloc vidé disparaît', () => {
  const sheet = { blocks: { clk: { params: { beats: 3 }, bypass: false } } };
  assert.deepEqual(sheetBlocks(sheet, 'clk', { params: { beats: null } }).clk, { bypass: false });
  assert.deepEqual(sheetBlocks(sheet, 'clk', { params: { beats: null }, bypass: null }), {});
  assert.deepEqual(sheetBlocks({}, 'smp', { params: { samples: ['x.wav'] } }), { smp: { params: { samples: ['x.wav'] } } });
});

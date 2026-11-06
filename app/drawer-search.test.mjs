// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { searchDrawer } from './drawer-search.mjs';

const MODEL_GEARS = { amp: ['amp-cab'], 'amp-nam': ['amp'], cab: ['cab'], 'pedal-nam': ['pedal'],
  'preamp-nam': ['outboard'], 'comp-nam': ['outboard'] };
const FX = [
  { type: 'amp', name: 'Head+Cab (NAM)', category: 'amp' },
  { type: 'amp-nam', name: 'Head (NAM)', category: 'amp' },
  { type: 'preamp-nam', name: 'Preamp (NAM capture)', category: 'preamp' },
  { type: 'comp-nam', name: 'Compressor (NAM capture)', category: 'dynamics' },
  { type: 'compressor', name: 'Compressor', category: 'dynamics' },
  { type: 'drumkit', name: 'Drum Kit', category: 'drums' },
];
const TONES = [
  { id: 'cap-module-1', title: 'Titan — Dynamic Waters', amp: 'Titan — Dynamic Waters', gear: 'amp-cab' },
  { id: 19, title: 'Fender Super Reverb 1977', amp: 'Super Reverb', brand: 'Fender', gear: 'amp' },
  { id: 26483, title: 'BAE 1073MP Preamp', amp: 'BAE 1073', brand: 'BAE', gear: 'outboard' },
];
const ALL = ['amp', 'preamp', 'dynamics'];

test('une capture installée se trouve par son nom, dans le bloc qui la joue', () => {
  const r = searchDrawer('titan', { cats: ALL, fx: FX, tones: TONES, modelGears: MODEL_GEARS });
  assert.deepEqual(r.captures.map(c => [c.tone.id, c.type, c.block]), [['cap-module-1', 'amp', 'Head+Cab (NAM)']]);
});

test('moins de deux lettres : pas de recherche', () => {
  assert.equal(searchDrawer('g', { cats: ALL, fx: FX, tones: TONES, modelGears: MODEL_GEARS }), null);
});

test('un préampli capturé vaut pour les deux blocs outboard que la lane propose', () => {
  const r = searchDrawer('bae', { cats: ALL, fx: FX, tones: TONES, modelGears: MODEL_GEARS });
  assert.deepEqual(r.captures.map(c => c.type).sort(), ['comp-nam', 'preamp-nam']);
  const voice = searchDrawer('bae', { cats: ['preamp'], fx: FX, tones: TONES, modelGears: MODEL_GEARS });
  assert.deepEqual(voice.captures.map(c => c.type), ['preamp-nam']);
});

test('une catégorie que la lane n\'a pas ne sort jamais de la recherche', () => {
  const r = searchDrawer('drum', { cats: ALL, fx: FX, tones: TONES, modelGears: MODEL_GEARS });
  assert.deepEqual(r.blocks, []);
  const amps = searchDrawer('fender', { cats: ['dynamics'], fx: FX, tones: TONES, modelGears: MODEL_GEARS });
  assert.deepEqual(amps.captures, []);
});

test('blocs et modèles nommés par leur nom', () => {
  const arch = [{ id: 'fender-twin', name: 'Fender Twin', short: 'Twin', brand: 'Fender', category: 'amp' },
    { id: 'tube-screamer', name: 'Tube Screamer', category: 'drive' }];
  const r = searchDrawer('COMP', { cats: ALL, fx: FX, archetypes: arch, tones: TONES, modelGears: MODEL_GEARS });
  assert.deepEqual(r.blocks.map(e => e.type), ['comp-nam', 'compressor']);
  const t = searchDrawer('twin', { cats: ALL, fx: FX, archetypes: arch, tones: TONES, modelGears: MODEL_GEARS });
  assert.deepEqual(t.archetypes.map(a => a.id), ['fender-twin']);
});

test('le titre TONE3000 ne compte pas quand l\'appareil est connu', () => {
  const ts9 = { id: 7, title: '[500 Epochs] Ibanez TS9 Tube Screamer - Complete Pack', amp: 'Ibanez TS9 Tube Screamer',
    brand: 'Ibanez', gear: 'pedal' };
  const fx = [...FX, { type: 'pedal-nam', name: 'Pedal (NAM capture)', category: 'drive' }];
  assert.deepEqual(searchDrawer('comp', { cats: ['drive'], fx, tones: [ts9], modelGears: MODEL_GEARS }).captures, []);
  assert.equal(searchDrawer('ts9', { cats: ['drive'], fx, tones: [ts9], modelGears: MODEL_GEARS }).captures.length, 1);
});

test('« Mine » : les captures importées ou faites ici, que la lane peut jouer', async () => {
  const { myCaptures, isMine } = await import('./drawer-search.mjs');
  const mine = [{ id: 'cap-module-1', title: 'Titan — Dynamic Waters', gear: 'amp-cab', source: 'capture', private: true },
    { id: 'imp-1', title: 'My pedal', gear: 'pedal', source: 'import', private: true }];
  const tones = [...mine, ...TONES];
  assert.deepEqual(TONES.filter(isMine), []);
  const fx = [...FX, { type: 'pedal-nam', name: 'Pedal (NAM capture)', category: 'drive' }];
  const guitar = myCaptures({ cats: [...ALL, 'drive'], fx, tones, modelGears: MODEL_GEARS });
  assert.deepEqual(guitar.map(c => [c.tone.id, c.type]), [['cap-module-1', 'amp'], ['imp-1', 'pedal-nam']]);
  assert.deepEqual(myCaptures({ cats: ['dynamics', 'preamp'], fx, tones, modelGears: MODEL_GEARS }), []);
});

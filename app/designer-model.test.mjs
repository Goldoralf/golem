// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { blank, seatPatchLane, PATCH_REALM, swapVitalPreset, sameSound, archOf } from './designer-model.js';
import { readFileSync } from 'node:fs';

// la carte d'entrées de le 2026-10-10 (Volt 276) : le micro 48 V sur IN 1, la guitare sur IN 2
const IMAP = {
  inputs: [{ ch: '1', role: 'voice', nth: 1 }, { ch: '2', role: 'guitar', nth: 1 }, { ch: '3', role: 'guitar', nth: 2 }],
  usb: [{ ch: 'usb1', port: 1, role: 'none' }, { ch: 'usb2', port: 2, role: 'keys-pads', nth: 1 }],
};
const fresh = role => { const b = blank(); b.__patch = { realm: PATCH_REALM[role] || 'guitar', id: null, name: 'x', role }; return b; };
const realm = p => p.lanes.find(l => l.id === p.__patch.realm);

test('un patch guitare neuf prend la PREMIÈRE entrée guitare de la carte', () => {
  const L = realm(seatPatchLane(fresh('guitar'), IMAP));
  assert.equal(L.in_sel, '2');
  assert.equal(L.in_role, 'guitar');
  assert.equal(L.in_nth, 1);
});

test('la voix prend IN 1, un clavier le port USB qui porte son rôle', () => {
  assert.equal(realm(seatPatchLane(fresh('voice'), IMAP)).in_sel, '1');
  const K = realm(seatPatchLane(fresh('keys'), IMAP));
  assert.equal(K.in_sel, 'usb2');
  assert.equal(K.midi, true);
});

test('un instrument absent de la carte garde son entrée, lié par son rôle', () => {
  const before = realm(fresh('bass')).in_sel;
  const L = realm(seatPatchLane(fresh('bass'), IMAP));
  assert.equal(L.in_sel, before);
  assert.equal(L.in_role, 'bass');
});

test('une batterie et un kit ne sont pas touchés (ils posent leur propre question)', () => {
  const d = fresh('drums');
  const before = JSON.stringify(d.lanes);
  assert.equal(JSON.stringify(seatPatchLane(d, IMAP).lanes), before);
});

import { alignBoundInputs } from './designer-model.js';

test('une lane liée par nom montre l’entrée que le moteur joue (brouillon « full vst », 2026-10-10)', () => {
  const p = { lanes: [{ id: 'guitar', role: 'guitar', in_sel: '2', in_role: 'voice', in_nth: 1 },   // liée « Voice 1 »
                      { id: 'g2', role: 'guitar', in_sel: '1', in_role: 'guitar', in_nth: 1 },     // patch ouvert, in_sel par défaut
                      { id: 'k', role: 'keys', midi: true, in_sel: 'usb2', in_role: 'keys-pads', in_nth: 1 },
                      { id: 'b', role: 'guitar', in_sel: '3', in_role: 'guitar', in_nth: 2 }] };   // déjà juste : intact
  assert.equal(alignBoundInputs(p, IMAP), 2);
  assert.deepEqual(p.lanes.map(L => L.in_sel), ['1', '2', 'usb2', '3']);
  assert.equal(alignBoundInputs(p, IMAP), 0);                       // stable : aucune boucle d'effet
});

test('un patch neuf ne garde que SA lane : la voix vide du preset vierge ne partage plus IN 2 (2026-10-10)', () => {
  const p = seatPatchLane(fresh('guitar'), IMAP);
  assert.deepEqual(p.lanes.map(L => [L.id, L.in_sel]), [[p.__patch.realm, '2']]);
});

import { patchDraft } from './designer-model.js';
test('un patch à deux lanes guitare se lie à Guitar 1 ET Guitar 2 (audit 2026-10-10)', () => {
  const x = { name: 'duo', lanes_v: 2, lanes: [{ id: 'g1', role: 'guitar', chain: {} }, { id: 'g2', role: 'guitar', chain: {} }, { id: 'v', role: 'voice', chain: {} }], scenes: [] };
  assert.deepEqual(patchDraft(x).lanes.map(L => [L.in_role, L.in_nth]), [['guitar', 1], ['guitar', 2], ['voice', 1]]);
});

// 2026-10-13 : Paper Kite (patch v1 de golem.fm) ouvert dans le Designer — la lane du patch écoutait IN 1 (le
// micro), la guitare d'IN 2 tombait dans la lane voix VIDE du brouillon et sortait sèche. Un v1 se lie par son rôle.
test('un patch v1 NOMMÉ se lie par son rôle, sans les lanes vides du brouillon', () => {
  const v1 = { id: 'paper-kite', name: 'Paper Kite', role: 'guitar',
    chain: { pre: [{ id: 'g', type: 'gate' }], post: [{ id: 'r', type: 'reverb' }] }, scenes: [{ id: 'A', name: 'Verse', blocks: {} }] };
  const p = patchDraft(v1);
  assert.equal(p.lanes.length, 1, 'plus de lane voix ni clavier vide : une entrée = une piste');
  const L = p.lanes[0];
  assert.equal(L.in_role, 'guitar');
  assert.equal(L.in_nth, 1);
  alignBoundInputs(p, IMAP);                       // l'écran montre l'entrée que le moteur jouera
  assert.equal(L.in_sel, '2');
});

test('un patch v1 de clavier prend le port USB, une basse se lie comme basse', () => {
  const keys = patchDraft({ id: 'k', name: 'K', role: 'keys', chain: { chain: [{ id: 'v', type: 'vital' }] } });
  assert.equal(keys.lanes.length, 1);
  assert.equal(keys.lanes[0].midi, true);
  const bass = patchDraft({ id: 'b', name: 'B', role: 'bass', chain: { pre: [{ id: 'c', type: 'comp' }] } });
  assert.equal(bass.lanes[0].in_role, 'bass');
});

test('un patch batterie v2 s’ouvre en MIDI USB (auto par rôle), pas sur une entrée audio absente', () => {
  const p = patchDraft({ id: 'd', name: 'D', role: 'drums', lanes_v: 2,
    lanes: [{ id: 'drums-1', role: 'drums', chain: { chain: [{ id: 'k', type: 'drumkit' }] } }] });
  assert.equal(p.lanes[0].midi, true);
  assert.equal(p.lanes[0].in_sel, 'usb');
});

test('fenêtre de Vital : le son retouché remplace celui d\'origine, en base et dans les scènes qui le jouaient', () => {
  const p = { lanes: [{ id: 'keys-1', chain: { pre: [{ id: 'v1', type: 'vital', params: { preset: 'Pad' } }], post: [] } }],
    scenes: [{ id: 'A', params: {} }, { id: 'B', params: { v1: { preset: 'Pad' } } }, { id: 'C', params: { v1: { preset: 'Lead' } } }] };
  assert.equal(swapVitalPreset(p, 'v1', 'Pad', 'Pad~v1'), true);
  assert.equal(p.lanes[0].chain.pre[0].params.preset, 'Pad~v1');
  assert.equal(p.scenes[1].params.v1.preset, 'Pad~v1');
  assert.equal(p.scenes[2].params.v1.preset, 'Lead');            // une scène qui jouait un autre son le garde
  assert.equal(swapVitalPreset(p, 'nope', 'Pad', 'x'), false);
});

test('patchDraft garde le switch de Rec et de Riff (2026-10-17 : Jazz Clean montait avec SW9 « free »)', () => {
  const x = { id: 'p', name: 'Jazz Clean', role: 'guitar', lanes_v: 2,
    lanes: [{ id: 'guitar-1', role: 'guitar', chain: {} }],
    config: { gen: { blocks: [{ type: 'standard', id: 'standard', foot: 10 }] }, rec: { blocks: [{ id: 'rec-global', type: 'rec', foot: 9 }] } } };
  const p = patchDraft(x);
  const rec = p.config.rec.blocks.find(b => b.type === 'rec');
  assert.equal(rec.foot, 9);
  assert.equal(p.config.gen.blocks[0].foot, 10);
});

test('un patch ouvert par les flèches porte les blocs permanents de Config (Rec, Click, Riff)', () => {
  // 2026-10-18 : ◀ ▶ ouvraient le patch sans migrateConfig — le Click manquait jusqu'au rechargement de la page
  const x = { id: 'jazz-clean', name: 'Jazz Clean', role: 'guitar', lanes_v: 2,
    lanes: [{ id: 'gtr', key: 'gtr', role: 'guitar', chain: [] }],
    config: { rec: { blocks: [{ type: 'rec', foot: 9 }] } } };
  const types = patchDraft(x).config.rec.blocks.map(b => b.type);
  assert.ok(types.includes('rec') && types.includes('click') && types.includes('compo'));
  assert.equal(patchDraft(x).config.rec.blocks.find(b => b.type === 'rec').foot, 9);
});

// la puce « ⛓ patch » d'une lane : le dépôt renomme les blocs et réattribue les switchs, ce n'est pas une retouche
test('sameSound ignores the ids and switches a deposit changes, not the sound', () => {
  const patch = { chain: [{ type: 'eq', id: 'eq', foot: 7 }, { type: 'delay', id: 'dly', params: { mix: 0.3 } }] };
  const lane = { pre: [{ type: 'eq', id: 'eq-2' }, { type: 'delay', id: 'dly-2', foot: 8, params: { mix: 0.3 } }], post: [] };
  assert.ok(sameSound(patch, lane));
  lane.pre[1].params.mix = 0.5;
  assert.ok(!sameSound(patch, lane));                       // un potard tourné : retouché
  lane.pre[1].params.mix = 0.3;
  lane.post.push({ type: 'volume', id: 'vol' });
  assert.ok(!sameSound(patch, lane));                       // un bloc ajouté : retouché
});

// les deux 5150 (2026-11-13) : « Peavey 5150 II » tombait sur l'EVH 5150 (match « 5150 ») — le mot-clé le plus long
// l'emporte, donc « peavey 5150 » / « 5150 ii » rangent le Peavey, et « 5150 iii » garde l'EVH devant « 5150 ii »
test('les deux 5150 : la capture Peavey et la capture EVH ne se confondent pas', () => {
  const amps = JSON.parse(readFileSync(new URL('../library/catalog/effects.json', import.meta.url))).amps;
  const id = title => (archOf(amps, { amp: title }) || {}).id;
  assert.equal(id('Peavey 5150 II'), 'peavey-6505');
  assert.equal(id('EVH 5150 III Stealth'), '5150');
  assert.equal(id('5150 III 50W'), '5150');
  assert.equal(id('Peavey 6505+'), 'peavey-6505');
});

test('un patch neuf naît avec Rec, Click et Riff dans sa lane config', () => {
  // 2026-11-13 : blank() sautait migrateConfig — l'onglet ⚙ d'un patch voix tout neuf était vide
  for (const role of ['guitar', 'voice', 'bass', 'keys', 'drums']) {
    const types = fresh(role).config.rec.blocks.map(b => b.type);
    assert.deepEqual(['rec', 'click', 'compo'].filter(t => types.includes(t)), ['rec', 'click', 'compo'], role);
  }
  assert.equal(blank().config.rec.blocks.find(b => b.type === 'click').bypass, true);   // le Click naît éteint
});

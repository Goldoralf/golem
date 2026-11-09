// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { captureHostState, selectVsts, variantOf, vstInfo, vstFormatCounts, vstGroups,
         rememberVst, recentVsts, pickRecent, RECENT_MAX } from './vst-host-model.mjs';

test('REAPER distingue instruments et effets sans perdre les formats', () => {
  const rows = [
    { name: 'VST3: AIDA-X (AIDA DSP) (mono)' },
    { name: 'VST3i: Ample Metal R (Ample Sound)' },
    { name: 'CLAP: Compressor (Acme)' },
    { name: 'VSTi: Piano (Acme)' },
  ];
  assert.equal(vstInfo(rows[0]).vendor, 'AIDA DSP');
  assert.equal(vstInfo(rows[0]).title, 'AIDA-X');
  assert.deepEqual(selectVsts(rows, { kind: 'instrument' }).map(x => x.name),
    ['VSTi: Piano (Acme)', 'VST3i: Ample Metal R (Ample Sound)']);
  assert.equal(selectVsts(rows, { formats: ['CLAP'] }).length, 1);
  assert.equal(selectVsts(rows, { formats: { VST3: true, VST: false, CLAP: false } }).length, 2);
  assert.equal(selectVsts(rows, { query: 'aida' }).length, 1);
  assert.equal(selectVsts(rows).length, rows.length);
  assert.deepEqual(vstFormatCounts(rows), { VST3: 2, VST: 1, CLAP: 1 });
  assert.deepEqual(vstFormatCounts(rows, 'instrument'), { VST3: 1, VST: 1, CLAP: 0 });
});

test('les sorties ne sont pas un éditeur, et un éditeur n\'a qu\'un groupe', () => {
  // mesuré 2026-10-10 : 21 instruments rangés sous « 32 out », iZotope en deux groupes
  assert.equal(vstInfo({ name: 'VST3i: BM-VOID (UJAM) (32 out)' }).vendor, 'UJAM');
  assert.equal(vstInfo({ name: 'VST3i: BM-VOID (UJAM) (32 out)' }).title, 'BM-VOID');
  assert.equal(vstInfo({ name: 'VSTi: ReaSynDr (Cockos) (4 out)' }).vendor, 'REAPER (Cockos)');
  assert.equal(vstInfo({ name: 'VST3: Stutter Edit 2 (iZotope, Inc.)' }).vendor, 'iZotope');
  assert.equal(vstInfo({ name: 'VST3: ValhallaSupermassive (Valhalla DSP, LLC)' }).vendor, 'Valhalla DSP');
});

test('un plugin en VST et VST3 est UNE ligne, et le tap pose le VST3', () => {
  const rows = selectVsts([
    { name: 'VST: Example Amp Suite (Example Vendor)' },
    { name: 'VST3: Example Amp Suite (Example Vendor)' },
    { name: 'VSTi: Superior Drummer 3 (Toontrack) (32 out)' },
    { name: 'VST3i: Superior Drummer 3 (Toontrack) (32 out)' },
  ]);
  assert.equal(rows.length, 2);
  const g = rows.find(x => x.title === 'Example Amp Suite');
  assert.deepEqual(g.formats, ['VST3', 'VST']);
  assert.equal(g.name, 'VST3: Example Amp Suite (Example Vendor)');
  assert.equal(g.names.VST, 'VST: Example Amp Suite (Example Vendor)');
  // décocher VST3 : la ligne reste, mais ne propose plus que le VST
  const onlyVst = selectVsts([{ name: 'VST: A (X)' }, { name: 'VST3: A (X)' }], { formats: ['VST'] });
  assert.deepEqual(onlyVst.map(x => [x.formats, x.name]), [[['VST'], 'VST: A (X)']]);
});

test('l\'accordéon range les éditeurs du plus fourni au moins fourni', () => {
  const rows = selectVsts([{ name: 'VST3: B (Zed)' }, { name: 'VST3: A (Acme)' }, { name: 'VST3: C (Zed)' }]);
  assert.deepEqual(vstGroups(rows).map(g => [g.vendor, g.items.length]), [['Zed', 2], ['Acme', 1]]);
});

test('Recent : le dernier posé en tête, sans doublon, plafonné, et retrouvé quel que soit le format', () => {
  const mem = new Map(), storage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  const rows = selectVsts([...'ABCDEFGH'].map(c => ({ name: `VST3: ${c} (Acme)` })));
  for (const r of rows) rememberVst(r, storage);
  rememberVst(rows[2], storage);
  const ids = recentVsts(storage);
  assert.equal(ids.length, RECENT_MAX);
  assert.equal(ids[0], 'Acme|C');
  assert.equal(new Set(ids).size, ids.length);
  const asVst = selectVsts([{ name: 'VST: C (Acme)' }]);
  assert.deepEqual(pickRecent(asVst, ids).map(x => x.name), ['VST: C (Acme)']);
  assert.deepEqual(recentVsts({ getItem: () => { throw new Error('blocked'); } }), []);
});

test('le retour du VST dans la scène B conserve le son hérité de la scène A', () => {
  const base = { p7: 0.25, _vst_chunk: 'base' }, sceneB = { p7: 0.75 };
  const captured = captureHostState(base, sceneB, {
    kind: 'vst_chunk', chunk: 'scene-b', params: [{ i: 7, value: 0.75 }],
  });
  assert.equal(captured.params.p7, 0.25);
  assert.equal(captured.overrides.p7, 0.75);
  assert.equal(captured.params._vst_chunk, 'scene-b');
  assert.deepEqual(base, { p7: 0.25, _vst_chunk: 'base' });
  assert.deepEqual(sceneB, { p7: 0.75 });
  assert.equal(captureHostState(captured.params, captured.overrides, {
    kind: 'vst_chunk', chunk: 'scene-b', params: [{ i: 7, value: 0.75 }],
  }).changed, false);
});

test('une retouche native du potard de scène reste dans cette scène', () => {
  const captured = captureHostState({ p7: 0.25 }, { p7: 0.75 }, {
    kind: 'clap_chunk', chunk: 'edited', params: [{ i: 7, value: 0.9 }],
  });
  assert.equal(captured.params.p7, 0.25);
  assert.equal(captured.overrides.p7, 0.9);
});

test('un plugin déjà joué par un bloc golem garde sa marque à la fusion des formats (2026-11-09)', () => {
  const rows = selectVsts([
    { name: 'VST3: Surge XT Effects (Surge Synth Team)', block: 'surge-spring', block_name: 'Spring Reverb' },
    { name: 'CLAP: Surge XT Effects (Surge Synth Team)' },
    { name: 'CLAP: Surge XT (Surge Synth Team)' }]);
  const fx = rows.find(x => x.title === 'Surge XT Effects');
  assert.equal(fx.block, 'surge-spring');
  assert.equal(fx.blockName, 'Spring Reverb');
  assert.equal(rows.find(x => x.title === 'Surge XT').block, undefined);
});

test('les déclinaisons LSP (canaux, bandes) sont UNE ligne, la version posée suit la lane (2026-11-09)', () => {
  assert.deepEqual(variantOf('Parametric Equalizer x16 Stereo'), { base: 'Parametric Equalizer', chan: 'Stereo', size: 16, label: 'Stereo x16' });
  assert.equal(variantOf('Stereo Tool').base, 'Stereo Tool');                    // un nom qui COMMENCE par Stereo reste
  const lsp = ['Compressor Mono', 'Compressor Stereo', 'Compressor LeftRight', 'Compressor MidSide',
               'Sidechain Compressor Mono', 'Parametric Equalizer x16 Stereo', 'Parametric Equalizer x32 Stereo',
               'Parametric Equalizer x16 Mono', 'Phase Detector'].map(t => ({ name: `CLAP: ${t} (LSP CLAP)` }));
  const mono = selectVsts(lsp);
  assert.deepEqual(mono.map(x => x.title), ['Compressor', 'Parametric Equalizer', 'Phase Detector', 'Sidechain Compressor Mono']);
  const comp = mono.find(x => x.title === 'Compressor');
  assert.equal(comp.name, 'CLAP: Compressor Mono (LSP CLAP)');
  assert.equal(comp.variants.length, 4);
  assert.deepEqual(comp.variants.map(v => v.label), ['Mono', 'Stereo', 'L/R', 'M/S']);
  const st = selectVsts(lsp, { stereo: true });
  assert.equal(st.find(x => x.title === 'Compressor').name, 'CLAP: Compressor Stereo (LSP CLAP)');
  assert.equal(st.find(x => x.title === 'Parametric Equalizer').name, 'CLAP: Parametric Equalizer x16 Stereo (LSP CLAP)');  // la plus petite
  assert.equal(st.find(x => x.title === 'Phase Detector').variants, undefined);   // un seul : pas de déclinaisons
  assert.equal(selectVsts(lsp, { query: 'midside' })[0].title, 'Compressor');     // une déclinaison se retrouve par son nom
});

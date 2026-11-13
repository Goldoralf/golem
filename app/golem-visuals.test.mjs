// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { createRequire } from 'node:module';

// le DESSIN d'une pédale reste le même texte d'un rendu à l'autre (2026-11-13) : golem-fx numérote les ids de chaque
// dessin, et le tiroir redessiné à chaque état du rack remplaçait le SVG sous le doigt — le clic était perdu en vue Pedals
test('un même bloc donne le même SVG, rendu après rendu', async () => {
  globalThis.window = globalThis;
  const req = createRequire(import.meta.url);
  req('./vendor/golem-visuals/visuals-data.js');
  req('./vendor/golem-visuals/golem-pedals.js');
  req('./vendor/golem-visuals/golem-stage.js');
  const P = globalThis.GolemPedals;
  assert.notEqual(P.pedalFor({ type: 'chorus' }), P.pedalFor({ type: 'chorus' }));   // la cause : deux textes
  const { pedalSvg, stageSvg } = await import('./golem-visuals.js');
  assert.equal(pedalSvg({ type: 'chorus', title: 'Chorus' }), pedalSvg({ type: 'chorus', title: 'Chorus' }));
  const chain = { pre: [{ id: 'g', type: 'gate' }], post: [{ id: 'd', type: 'delay' }] };
  assert.equal(stageSvg(chain, { blocks: { g: true } }), stageSvg(chain, { blocks: { g: true } }));
  assert.notEqual(stageSvg(chain, { blocks: { g: true } }), stageSvg(chain, { blocks: { g: false } }));   // l'état compte
});

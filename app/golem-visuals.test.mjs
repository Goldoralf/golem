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

// LE RIG PAR SECTIONS (GolemRig, 2026-11-17) : la vue pédalier du Designer montre une section à la fois
test('une lane est découpée en sections, et le même état redonne le même dessin', async () => {
  globalThis.window = globalThis;
  const req = createRequire(import.meta.url);
  req('./vendor/golem-visuals/visuals-data.js');
  req('./vendor/golem-visuals/golem-pedals.js');
  req('./vendor/golem-visuals/golem-stage.js');
  req('./vendor/golem-visuals/golem-rig.js');
  const { rigSections, rigFloor } = await import('./golem-visuals.js');
  const chain = { pre: [{ id: 'od', type: 'drive' }, { id: 'amp', type: 'amp-nam', label: 'Twin' }, { id: 'cab', type: 'cab' }],
    post: [{ id: 'd', type: 'delay' }] };
  const on = { blocks: { od: true, amp: true, cab: true, d: true } };
  const secs = rigSections(chain, on);
  assert.deepEqual(secs.map(s => s.key), ['pre', 'amp', 'post']);        // seules les sections que la chaîne a
  assert.ok(secs.every(s => s.label && s.count >= 1 && s.svg.startsWith('<svg')));
  assert.match(secs[1].svg, /data-idx="1"/);                            // la tête garde son chemin : le geste la retrouve
  assert.doesNotMatch(secs[0].svg, /data-idx="1"/);                     // et n'est pas dessinée parmi les pédales
  assert.equal(rigSections(chain, on)[0].svg, secs[0].svg);             // même état : même texte (le clic n'est pas perdu)
  assert.notEqual(rigSections(chain, { blocks: { ...on.blocks, od: false } })[0].svg, secs[0].svg);
  assert.deepEqual(rigSections({ pre: [], post: [] }, {}), []);         // rien à dessiner : aucune section
  assert.equal(rigFloor(''), 'stage');
  assert.equal(rigFloor('djent'), 'plate');
});

test("la bande de la chaîne garde l'ordre du signal, avec les chemins du dessin", async () => {
  const { signalOrder } = await import('./designer-pedalview.js').catch(() => ({}));
  if (!signalOrder) return;                                             // le module tire lib.js (navigateur) : testé au rendu
  const chain = { pre: [{ id: 'a', type: 'gate' }], split: { branches: [{ id: 'x', blocks: [{ id: 'h', type: 'amp-nam' }, { id: 'c', type: 'cab' }] },
    { id: 'y', blocks: [{ id: 'h2', type: 'amp-nam' }] }] }, post: [{ id: 'd', type: 'delay' }] };
  assert.deepEqual(signalOrder(chain).map(b => b.path + ':' + b.id + (b.branch || '')), ['0:a', '1.0.0:hA', '1.0.1:cA', '1.1.0:h2B', '2:d']);
  assert.deepEqual(signalOrder({ chain: [{ id: 'k', type: 'comp' }] }).map(b => b.path), ['0']);
});

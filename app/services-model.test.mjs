// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { serviceBadges, fmPaired } from './services-model.mjs';

const st = (services, age = 100) => ({ boot: { t0: 0, now: age, services } });

test('rien quand ça marche, ou quand ce n’est pas encore vérifié', () => {
  assert.deepEqual(serviceBadges(st({ fm: { configured: true, ok: true }, t3k: { configured: true, ok: true } })), { fm: null, t3k: null, api: null, settings: null });
  assert.deepEqual(serviceBadges(st({ fm: { configured: null, ok: null }, t3k: { configured: null, ok: null } })), { fm: null, t3k: null, api: null, settings: null });
  assert.deepEqual(serviceBadges({ boot: {} }), { fm: null, t3k: null, api: null, settings: null });   // un bridge qui ne vérifie pas
});

test('anneau = manquant, plein = en erreur, et le pire monte sur API puis ⚙', () => {
  const b = serviceBadges(st({ fm: { configured: false, ok: false }, t3k: { configured: false, ok: false } }));
  assert.equal(b.fm, null);                            // golem.fm jamais appairé : optionnel, pas d'anneau (2026-10-31)
  assert.equal(b.t3k.kind, 'missing'); assert.equal(b.api, 'missing'); assert.equal(b.settings, 'missing');
  const c = serviceBadges(st({ fm: { configured: false, ok: false }, t3k: { configured: true, ok: false, why: 'token expired' } }));
  assert.equal(c.t3k.kind, 'error'); assert.match(c.t3k.text, /token expired/); assert.equal(c.api, 'error');
});

test('golem.fm appairé mais pas encore lié : pas de pastille pendant les premières secondes', () => {
  assert.equal(serviceBadges(st({ fm: { configured: true, ok: false }, t3k: { configured: true, ok: true } }, 5)).fm, null);
  assert.equal(serviceBadges(st({ fm: { configured: true, ok: false }, t3k: { configured: true, ok: true } }, 60)).fm.kind, 'error');
});

test('fmPaired : seulement un golem.fm vu réglé au démarrage', () => {
  assert.equal(fmPaired(null), false);
  assert.equal(fmPaired({ boot: { services: { fm: { configured: null } } } }), false);
  assert.equal(fmPaired({ boot: { services: { fm: { configured: false } } } }), false);
  assert.equal(fmPaired({ boot: { services: { fm: { configured: true, ok: false } } } }), true);
});

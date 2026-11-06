// SPDX-License-Identifier: GPL-3.0-or-later
import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { chipLabel, isHome, menuEntry } from './startup-model.mjs';

const HOME = { policy: 'home', home: { kind: 'preset', id: 'velvetine-swerve-lane', name: 'Velvetine — Swerve Lane', missing: null } };

test('le chip de /live dit l’accueil, la politique, ou l’objet disparu', () => {
  assert.equal(chipLabel(null), '⌂ first bank');
  assert.equal(chipLabel({ policy: 'last', home: null }), '⌂ last played');
  assert.equal(chipLabel(HOME), '⌂ Velvetine — Swerve Lane');
  assert.equal(chipLabel({ policy: 'home', home: { ...HOME.home, missing: 'not found' } }), '⌂ missing');
  assert.equal(chipLabel({ policy: 'bank0', home: HOME.home }), '⌂ first bank');     // posé mais politique bank 00
});

test('l’entrée du menu ⋯ : poser (et dire ce qu’elle remplace), ou retirer', () => {
  assert.deepEqual(menuEntry(HOME, { kind: 'preset', id: 'velvetine-swerve-lane' }), { label: '⌂ Opens at startup ✓', small: 'tap to remove', remove: true });
  assert.deepEqual(menuEntry(HOME, { kind: 'song', setlist: 's1', line: 'r:s1:ab' }), { label: '⌂ Open at startup', small: 'song · replaces Velvetine — Swerve Lane', remove: false });
  assert.deepEqual(menuEntry({ policy: 'bank0', home: null }, { kind: 'patch', id: 'patch:full-vst' }), { label: '⌂ Open at startup', small: 'patch', remove: false });
  assert.equal(isHome(HOME, { kind: 'song', setlist: 's1', line: 'x' }), false);
  assert.equal(isHome({ policy: 'home', home: { kind: 'song', setlist: 's1', line: 'x' } }, { kind: 'song', setlist: 's1', line: 'x' }), true);
});

// SPDX-License-Identifier: GPL-3.0-or-later
// Joue app/capture-gain.js contre la table de cas de la spec (tests/capture-gain-cases.json,
// copie de golem.fm/conception/capture-gain-cases.json v0.1 — même table des deux côtés).
// Sortie : JSON {names:{ok,total,fails[]}, order:{...}, defaults:{...}} — lu par test_capture_gain.py.
import { readFileSync } from 'node:fs';
import { parseName, orderModels, defaultModel } from '../app/capture-gain.js';

const table = JSON.parse(readFileSync(new URL('./capture-gain-cases.json', import.meta.url), 'utf8'));
const fails = { names: [], order: [], defaults: [] };
const NUL = v => (v == null ? null : v);
for (const c of table.names) {
  const g = parseName(c.name);
  const diffs = [];
  for (const k of ['gain', 'level', 'channel', 'family', 'rate']) if (k in c && NUL(c[k]) !== NUL(g[k])) diffs.push(`${k}: want ${c[k]} got ${g[k]}`);
  for (const k of ['hot', 'off', 'max']) if (!!c[k] !== !!g[k]) diffs.push(`${k}: want ${!!c[k]} got ${!!g[k]}`);
  if (diffs.length) fails.names.push({ name: c.name, diffs, why: c.why || '' });
}
for (const p of table.packs) {
  const got = orderModels(p.models).map(r => r.m);
  if (JSON.stringify(got) !== JSON.stringify(p.order)) fails.order.push({ tone_id: p.tone_id, title: p.title, want: p.order, got });
  for (const role of ['voice', 'other']) {
    const d = defaultModel(p.models, role);
    if (d !== p.defaults[role]) fails.defaults.push({ tone_id: p.tone_id, title: p.title, role, want: p.defaults[role], got: d });
  }
}
const out = { spec: table.spec,
  names: { ok: table.names.length - fails.names.length, total: table.names.length, fails: fails.names },
  order: { ok: table.packs.length - fails.order.length, total: table.packs.length, fails: fails.order },
  defaults: { ok: table.packs.length * 2 - fails.defaults.length, total: table.packs.length * 2, fails: fails.defaults } };
console.log(JSON.stringify(out, null, 1));
process.exit(fails.names.length + fails.order.length + fails.defaults.length ? 1 : 0);

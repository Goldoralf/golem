// SPDX-License-Identifier: GPL-3.0-or-later
// Inventaire REAPER : le préfixe du nom indique format et instrument, pas le genre sonore.
// `(32 out)` est le nombre de SORTIES d'un instrument, pas son éditeur : sans `\d+ out` ici, les 14 UJAM,
// Superior Drummer et Kontakt d'un poste se rangeaient sous un éditeur « 32 out » (mesuré 2026-10-10).
const CHANNEL_SUFFIX = /^(?:mono|stereo|\d+(?:->\d+)?ch|\d+->\d+ch|\d+\s*outs?)$/i;
// un même éditeur s'écrit « iZotope » et « iZotope, Inc. » selon le plugin : un seul groupe
const LEGAL_SUFFIX = /,?\s*(?:Inc\.?|LLC|Ltd\.?|GmbH|S\.?A\.?S\.?)$/i;
const VENDOR_ALIAS = { Cockos: 'REAPER (Cockos)' };   // les plugins livrés avec REAPER se reconnaissent ainsi
export const FORMATS = ['VST3', 'VST', 'CLAP'];
const RANK = { VST3: 0, CLAP: 1, VST: 2, Other: 3 };  // le format posé par un tap : VST3 d'abord (2026-10-10)

export function vstInfo(entry) {
  const name = String(entry.name || '');
  const prefix = /^([^:]+):\s*/.exec(name)?.[1] || '';
  const format = prefix.startsWith('VST3') ? 'VST3' : prefix.startsWith('VST') ? 'VST' :
    prefix.startsWith('CLAP') ? 'CLAP' : 'Other';
  const kind = prefix.endsWith('i') ? 'instrument' : 'effect';
  const label = name.slice(prefix.length ? prefix.length + 1 : 0).trim();
  const parentheses = [...label.matchAll(/\(([^()]*)\)/g)].map(m => m[1]);
  const raw = [...parentheses].reverse().find(x => !CHANNEL_SUFFIX.test(x)) || 'Other';
  const clean = raw.replace(LEGAL_SUFFIX, '').trim() || raw;
  const vendor = VENDOR_ALIAS[clean] || clean;
  // le nom affiché : sans l'éditeur ni les sorties (« Superior Drummer 3 (Toontrack) (32 out) » → « Superior Drummer 3 »)
  const title = label.replace(/\s*\([^()]*\)/g, '').trim() || label;
  return { ...entry, format, kind, vendor, label, title };
}

/** Une LIGNE par plugin (éditeur + nom) : ses formats installés, du préféré au moins préféré, et le nom
 *  REAPER de chacun (`names[format]`) — `name` est celui que pose un tap. */
export function mergeVsts(entries) {
  const m = new Map();
  for (const x of entries.map(vstInfo)) {
    const k = x.vendor + '|' + x.title + '|' + x.kind;
    const e = m.get(k) || { title: x.title, vendor: x.vendor, kind: x.kind, formats: [], names: {} };
    if (!e.names[x.format]) { e.formats.push(x.format); e.names[x.format] = x.name; }
    m.set(k, e);
  }
  for (const e of m.values()) {
    e.formats.sort((a, b) => RANK[a] - RANK[b]);
    e.name = e.names[e.formats[0]];
  }
  return [...m.values()];
}

/** `formats` = les formats cochés ({VST3: true, …} ou tableau) ; absent = tous. Rend des LIGNES (mergeVsts),
 *  triées par éditeur puis nom ; une ligne garde les formats cochés seulement. */
export function selectVsts(entries, { kind = 'all', formats = null, query = '' } = {}) {
  const on = !formats ? null : new Set(Array.isArray(formats) ? formats : Object.keys(formats).filter(f => formats[f]));
  const q = query.trim().toLocaleLowerCase();
  const kept = entries.map(vstInfo).filter(x => (kind === 'all' || x.kind === kind) && (!on || on.has(x.format)));
  return mergeVsts(kept).filter(x => !q || `${x.title} ${x.vendor}`.toLocaleLowerCase().includes(q))
    .sort((a, b) => a.vendor.localeCompare(b.vendor) || a.title.localeCompare(b.title));
}

/** Combien de plugins par format, pour les cases à cocher (avant le filtre de format, après celui du genre). */
export function vstFormatCounts(entries, kind = 'all') {
  const n = Object.fromEntries(FORMATS.map(f => [f, 0]));
  for (const x of entries.map(vstInfo)) if ((kind === 'all' || x.kind === kind) && x.format in n) n[x.format]++;
  return n;
}

/** Les groupes de l'accordéon : [{vendor, items}] du plus fourni au moins fourni. */
export function vstGroups(rows) {
  const m = new Map();
  for (const x of rows) (m.get(x.vendor) || m.set(x.vendor, []).get(x.vendor)).push(x);
  return [...m].map(([vendor, items]) => ({ vendor, items }))
    .sort((a, b) => b.items.length - a.items.length || a.vendor.localeCompare(b.vendor));
}

// ── « Recent » : les derniers plugins posés, sur CET appareil (une commodité d'affichage, pas un état du rack) ──
const RECENT_KEY = 'golem.vstRecent';
export const RECENT_MAX = 6;
export function recentVsts(storage = globalThis.localStorage) {
  try { const a = JSON.parse(storage.getItem(RECENT_KEY) || '[]'); return Array.isArray(a) ? a.filter(s => typeof s === 'string') : []; }
  catch (e) { return []; }
}
/** Retient la ligne posée par son identité (éditeur + nom), pas par son format : un VST3 réinstallé en VST la retrouve. */
export function rememberVst(row, storage = globalThis.localStorage) {
  const id = row.vendor + '|' + row.title;
  const next = [id, ...recentVsts(storage).filter(x => x !== id)].slice(0, RECENT_MAX);
  try { storage.setItem(RECENT_KEY, JSON.stringify(next)); } catch (e) {}
  return next;
}
export function pickRecent(rows, ids) {
  return ids.map(id => rows.find(x => x.vendor + '|' + x.title === id)).filter(Boolean);
}

export function captureHostState(base = {}, scene = {}, state) {
  const params = { ...base }, overrides = { ...scene };
  let changed = base['_' + state.kind] !== state.chunk;
  delete params._vst_chunk; delete params._clap_chunk;
  params['_' + state.kind] = state.chunk;
  for (const pm of state.params || []) {
    const key = 'p' + pm.i;
    // L'instance contient le son EFFECTIF : une valeur de scène ne devient pas la base.
    const target = Object.hasOwn(scene, key) ? overrides : Object.hasOwn(base, key) ? params : null;
    if (target && target[key] !== pm.value) {
      target[key] = pm.value;
      changed = true;
    }
  }
  return { params, overrides, changed };
}

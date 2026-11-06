// SPDX-License-Identifier: GPL-3.0-or-later
// Lire le GAIN dans le nom d'un modèle de capture — spec « capture-gain » v0.1 (golem.fm,
// 2026-09-14, canonique dans docs/blocks-doctrine.md « Addendum outboard »). Deux lecteurs :
// le Capture dial du rack (ordre du plus propre au plus chaud) et le modèle par DÉFAUT à la pose
// (le plus propre, famille d'entrée selon le rôle). UNE spec, UNE table de cas
// (tests/capture-gain-cases.json, 34 noms + 15 packs réels), deux implémentations (ici et golem.fm).
//
// ⚠ Module SANS dépendance : importé par l'app (Preact) ET par node (tests/capture_gain_check.mjs).
// Rien de DOM, rien de lib.js ici.

// ── 1. ce qu'on lit dans un nom ────────────────────────────────────────────────────────────
// Clés de gain : `mic gain`, `pre`, `gain`, `inp`/`input`, `drive`, `line`. Entre la clé et la
// valeur : rien, une espace, `_` ou `-`. Le SIGNE ne compte que précédé d'une espace (`Gain -10`)
// ou s'il est un `+` ; un tiret collé à la clé est un séparateur (`Gain-8` → 8).
// Deux alternatives, dans cet ordre : (a) espace puis nombre signé ; (b) séparateur optionnel puis
// nombre non signé (ou `+`), `off` ou `max`.
const KEY_RE = /(?<![a-z])(mic[ _-]?gain|gain|input|inp|pre|drive|line)(?:[ ]([+-]?\d+(?:\.\d+)?)(?![a-z0-9.%])|[ _-]?(\+?\d+(?:\.\d+)?|off|max)(?![a-z0-9.%]))/i;
// `G` collé au nombre, majuscule, précédé d'un non-alphanumérique (`1073_Mic_G70`)
const G_RE = /(?<![A-Za-z0-9])G(\d+(?:\.\d+)?)(?![A-Za-z0-9.])/;
// un nombre suivi de dB, collé ou non, casse indifférente (`70 dB`, `55db`)
const DB_RE = /(?<![A-Za-z0-9.])([+-]?\d+(?:\.\d+)?)\s?db(?![a-z])/i;
// un pourcentage (`SILK RED at 75%`)
const PCT_RE = /(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s?%/;
// mots de niveau — seulement quand aucun gain n'est lisible ; un mot collé à `-<nombre>` est un
// réglage (`High-7`), pas un niveau
const LEVEL_WORDS = { low: 1, mild: 1, light: 1, medium: 2, mid: 2, high: 3, hot: 3, heavy: 3, cranked: 3, crank: 3, smashed: 3 };
const LEVEL_RE = /(?<![a-z])(low|mild|light|medium|mid|high|hot|heavy|cranked|crank|smashed)(?![a-z])(?!-\d)/gi;
// variante chaude : `hard` ou `pushed` en mot isolé
const HOT_RE = /(?<![a-z])(hard|pushed)(?![a-z])/i;
// canal : jeton ISOLÉ — précédé du début, d'une espace, `-`, `(`, `[`, `_` ; suivi de la fin,
// d'une espace, `)`, `]`. Suivi d'un tiret (`R-100`), ce n'est PAS un canal. Lettres seules en
// MAJUSCULE (`L`, `R`, `A`, `B`), mots en casse libre.
const CH_RE = /(?:^|[ \-(\[_])(?:(L|A|[Ll]eft|LEFT|[Cc]h(?:an|annel)?[ _]?1)|(R|B|[Rr]ight|RIGHT|[Cc]h(?:an|annel)?[ _]?2))(?=$|[ )\]])/g;
// famille d'entrée : `mic`, `di`, `line` — précédé et suivi d'un NON-lettre (`1073DI_…` → di ;
// « Studio », « Dirtier » ne contiennent pas la famille di)
const FAM_RE = /(?<![a-z])(mic|di|line)(?![a-z])/i;
// fréquence d'échantillonnage : `(48k)` / `(44.1k)`
const RATE_RE = /\((48|44\.1)k\)/i;

const num = s => parseFloat(String(s).replace(',', '.'));

/** Ce qu'un nom dit : {gain, level, off, max, hot, channel, family, rate}. Un nom qui ne dit
 *  rien est illisible — ce n'est pas une erreur. */
export function parseName(name) {
  const s = String(name || '');
  const out = { gain: null, level: null, off: false, max: false, hot: false, channel: null, family: null, rate: null };
  const rate = RATE_RE.exec(s);
  if (rate) out.rate = rate[1] === '48' ? 48000 : 44100;
  // le gain, par ordre de priorité : clé+nombre (ou off/max), puis `G<n>`, puis `<n> dB`, puis `<n>%`
  const k = KEY_RE.exec(s);
  if (k) {
    const v = k[2] != null ? k[2] : k[3];
    const lv = String(v).toLowerCase();
    if (lv === 'off') out.off = true;
    else if (lv === 'max') out.max = true;
    else out.gain = num(v);
  } else {
    const g = G_RE.exec(s);
    const db = !g && DB_RE.exec(s);
    const pct = !g && !db && PCT_RE.exec(s);
    if (g) out.gain = num(g[1]);
    else if (db) out.gain = num(db[1]);
    else if (pct) out.gain = num(pct[1]);
  }
  if (out.gain == null && !out.off && !out.max) {
    let m; LEVEL_RE.lastIndex = 0;
    while ((m = LEVEL_RE.exec(s))) { const l = LEVEL_WORDS[m[1].toLowerCase()]; if (l && out.level == null) out.level = l; }
  }
  out.hot = HOT_RE.test(s);
  let c; CH_RE.lastIndex = 0;
  while ((c = CH_RE.exec(s))) { out.channel = c[1] ? 1 : 2; break; }
  const f = FAM_RE.exec(s);
  if (f) out.family = f[1].toLowerCase();
  return out;
}

// ── 2. l'ordre d'un pack (Capture dial) ─────────────────────────────────────────────────────
const readable = p => p.gain != null || p.off || p.max;
const nameOf = m => (m && typeof m === 'object') ? String(m.name || '') : String(m || '');

/** Retire les doublons `(44.1k)` qui ont un jumeau `(48k)` : le rack tourne à 48 kHz. Rend les
 *  modèles conservés, dans l'ordre du pack. */
export function dedupeRate(models) {
  const at48 = new Set(models.map(nameOf).filter(n => /\(48k\)/i.test(n)).map(n => n.replace(/\(48k\)/i, '(#k)')));
  return models.filter(m => { const n = nameOf(m);
    return !(/\(44\.1k\)/i.test(n) && at48.has(n.replace(/\(44\.1k\)/i, '(#k)'))); });
}

/** Les modèles d'un pack annotés et TRIÉS du plus propre au plus chaud, doublons 44.1k retirés.
 *  Rend [{m, g, i}] : le modèle, sa lecture, son rang dans le pack. */
export function orderModels(models) {
  const kept = dedupeRate(models || []);
  const rows = kept.map((m, i) => ({ m, g: parseName(nameOf(m)), i }));
  const anyGain = rows.some(r => readable(r.g));
  const anyLevel = !anyGain && rows.some(r => r.g.level != null);
  if (anyLevel) {
    // dans un pack où des voisins portent un mot de niveau, le nom nu prend le niveau 2
    for (const r of rows) if (r.g.level == null) r.g = { ...r.g, level: 2 };
  }
  if (!anyGain && !anyLevel) return rows;   // l'ordre du pack, tel quel
  const key = r => anyGain ? (r.g.off ? -Infinity : r.g.max ? Infinity : r.g.gain) : r.g.level;
  const chRank = ch => ch === 1 ? 0 : ch == null ? 1 : 2;
  const isRead = r => anyGain ? readable(r.g) : r.g.level != null;
  return rows.slice().sort((a, b) => {
    const ra = isRead(a), rb = isRead(b);
    if (ra !== rb) return ra ? -1 : 1;            // les illisibles viennent APRÈS, dans l'ordre du pack
    if (!ra) return a.i - b.i;
    const ka = key(a), kb = key(b);
    if (ka !== kb) return ka < kb ? -1 : 1;
    if (a.g.hot !== b.g.hot) return a.g.hot ? 1 : -1;   // non chaud avant chaud
    const ca = chRank(a.g.channel), cb = chRank(b.g.channel);
    if (ca !== cb) return ca - cb;                 // canal 1, sans canal, canal 2
    return a.i - b.i;                              // puis l'ordre du pack
  });
}

// ── 3. le modèle par défaut ─────────────────────────────────────────────────────────────────
/** Le modèle à poser quand on choisit le pack, selon le rôle de la lane ('voice' | autre).
 *  1. la famille d'entrée D'ABORD : une voix garde les `mic`, les autres rôles `di`/`line` ; si
 *     le pack n'en a aucun, la famille ne filtre rien. 2. le premier nom LISIBLE (dans l'ordre du
 *     dial) de canal 1 ou sans canal, ni chaud ni off ; sinon le premier de canal 1 ou sans canal.
 *  Rend le modèle (l'objet passé), ou null si le pack est vide. */
export function defaultModel(models, role) {
  const rows = orderModels(models);
  if (!rows.length) return null;
  const want = role === 'voice' ? ['mic'] : ['di', 'line'];
  const fam = rows.filter(r => r.g.family && want.includes(r.g.family));
  const pool = fam.length ? fam : rows;
  const anyGain = pool.some(r => readable(r.g));
  const isRead = r => anyGain ? readable(r.g) : r.g.level != null;
  const ok1 = r => r.g.channel == null || r.g.channel === 1;
  const hit = pool.find(r => isRead(r) && ok1(r) && !r.g.hot && !r.g.off)
    || pool.find(ok1) || pool[0];
  return hit.m;
}

/** Libellé court d'une lecture, pour la sous-ligne du Capture dial ('' si rien de lisible). */
export function describe(g) {
  if (!g) return '';
  const parts = [];
  if (g.off) parts.push('input off');
  else if (g.max) parts.push('gain max');
  else if (g.gain != null) parts.push('gain ' + g.gain);
  else if (g.level != null) parts.push(['', 'low', 'medium', 'high'][g.level]);
  if (g.hot) parts.push('hot');
  if (g.channel) parts.push('ch ' + g.channel);
  if (g.family) parts.push(g.family);
  return parts.join(' · ');
}

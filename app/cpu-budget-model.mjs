// SPDX-License-Identifier: GPL-3.0-or-later
// LE BUDGET CPU, CÔTÉ APP — la logique PURE (docs/cpu-budget.md §3, §4, §9). Aucun DOM, aucun fetch : ce qu'on
// affiche se décide ici, et se teste avec `node --test app/cpu-budget-model.test.mjs`.
//
// Les pourcentages sont ceux d'UN cœur pour UN buffer (§1 : une lane est une chaîne en série, elle tient sur un cœur).
// `null` = « not measured » — jamais un zéro : un bloc qu'on n'a pas mesuré ne coûte pas rien, on ne le sait pas.

// les seuils du bridge (cpu_budget.THRESHOLDS, §9) : ok ≤ 60 %, tight ≤ 80 %, red au-delà
export const THRESHOLDS = { ok: 60, tight: 80 };
export const COLORS = { ok: '#2ecc71', tight: '#ff9f43', red: '#ff5a4d', unknown: '#8a94a3' };
const LEVELS = new Set(['ok', 'tight', 'red', 'unknown']);

const num = x => (typeof x === 'number' && Number.isFinite(x) ? x : null);

/** le niveau d'un pourcentage : ok | tight | red | unknown (null = pas mesuré) */
export function levelOf(pct) {
  const p = num(pct);
  if (p == null) return 'unknown';
  return p > THRESHOLDS.tight ? 'red' : p > THRESHOLDS.ok ? 'tight' : 'ok';
}
/** un verdict du bridge, ou le niveau déduit du pourcentage quand il n'en donne pas */
export const verdictOf = (v, pct) => (LEVELS.has(v) ? v : levelOf(pct));
export const colorOf = level => COLORS[level] || COLORS.unknown;

/** « 78 % » ; « — » si pas mesuré. Arrondi à l'entier : une estimation n'a pas de décimale à montrer. */
export function fmtPct(pct) {
  const p = num(pct);
  return p == null ? '—' : Math.round(p) + ' %';
}
/** « 1.4 of 8 cores » (une information, jamais le verdict — §1) */
export function fmtCores(cores, total) {
  const c = num(cores), t = num(total);
  if (c == null || t == null || t <= 0) return '';
  return (Math.round(c * 10) / 10).toFixed(1) + ' of ' + Math.round(t) + ' cores';
}
/** la largeur d'une barre (0..100), bornée : un 130 % remplit la barre, le chiffre dit le reste */
export const barWidth = pct => { const p = num(pct); return p == null ? 0 : Math.max(0, Math.min(100, p)); };

export const VERDICT_WORD = { ok: 'Plays', tight: 'Tight', red: 'Will crackle', unknown: 'Not measured' };
export const VERDICT_LONG = { ok: 'plays', tight: 'tight', red: 'will crackle', unknown: 'not measured' };

/** le nom d'une lane de l'estimation (son nom, sinon son id) */
export function laneLabel(est, laneId) {
  const L = ((est && est.lanes) || []).find(x => x && x.id === laneId);
  return (L && (L.name || L.id)) || laneId || '';
}

/** la puce de verdict d'un preset (en-tête du Designer, feuille) : {level, text} — null quand il n'y a rien à dire */
export function verdictChip(est) {
  if (!est || typeof est !== 'object') return null;
  const w = est.worst || {};
  const level = verdictOf(est.verdict, w.pct);
  if (level === 'unknown' && num(w.pct) == null) return { level, text: 'CPU not measured' };
  const lane = laneLabel(est, w.lane);
  const where = lane ? ' · lane ' + lane : '';
  return { level, text: VERDICT_WORD[level] + where + (num(w.pct) != null ? ' ' + fmtPct(w.pct) : '') };
}

/** « A 78 · B 41 · C 74 » — les scènes dans l'ordre donné (celui du preset), sinon celui de by_scene */
export function sceneLine(lane, sceneIds) {
  const by = (lane && lane.by_scene) || {};
  const ids = (sceneIds && sceneIds.length ? sceneIds : Object.keys(by)).filter(id => id in by);
  return ids.map(id => id + ' ' + (num(by[id]) == null ? '—' : Math.round(by[id]))).join(' · ');
}

/** l'état d'un bloc dans une scène : `on[scene]` s'il est donné, sinon allumé */
export const blockOnIn = (b, sceneId) => !(b && b.on && sceneId in b.on && b.on[sceneId] === false);

/** les puces de blocs d'une lane (la part de chacun) pour la scène affichée */
export function blockChips(lane, sceneId) {
  return ((lane && lane.blocks) || []).map(b => ({
    id: b.id, label: b.label || b.type || b.id,
    cost: b.measured === false || num(b.pct) == null ? 'not measured' : fmtPct(b.pct),
    off: !blockOnIn(b, sceneId),
  }));
}

/** « Fuzz 30 % (stereo) · EVH 5150 18 % · … » — les plus lourds d'abord, allumés dans la scène, `n` au plus */
export function heaviestLine(lane, sceneId, n = 4) {
  const bs = ((lane && lane.blocks) || []).filter(b => num(b.pct) != null && (sceneId == null || blockOnIn(b, sceneId)))
    .slice().sort((a, b) => b.pct - a.pct).slice(0, n);
  return bs.map(b => (b.label || b.type) + ' ' + fmtPct(b.pct) + (b.stereo ? ' (stereo)' : '')).join(' · ');
}

/** le pourcentage d'une lane dans une scène (by_scene), sinon celui de sa scène la plus lourde */
export function lanePctIn(lane, sceneId) {
  const by = (lane && lane.by_scene) || {};
  if (sceneId != null && num(by[sceneId]) != null) return by[sceneId];
  return num(lane && lane.pct);
}

/** la carte de niveau des lanes (pour les pastilles des onglets) : seulement tight / red — le vert ne se signale pas */
export function laneAlerts(est) {
  const out = {};
  for (const L of (est && est.lanes) || []) {
    const lv = levelOf(L.pct);
    if (lv === 'tight' || lv === 'red') out[L.id] = lv;
  }
  return out;
}

// ── LES CORRECTIFS (§4) ─────────────────────────────────────────────────────────────────────────────
/** « −25 % » (le gain est un pourcentage de cœur rendu à la lane) */
export function gainText(fix) {
  const g = num(fix && fix.gain_pct);
  return g == null ? '' : '−' + Math.round(Math.abs(g)) + ' %';
}
/** vert si le correctif rend vraiment de la place, orange s'il gagne peu ou coûte autre chose (le buffer : la latence) */
export function gainLevel(fix) {
  const g = num(fix && fix.gain_pct);
  if (g == null) return 'unknown';
  return ((fix.action || {}).kind === 'buffer' || Math.abs(g) < 10) ? 'tight' : 'ok';
}

/** le bouton d'un correctif, ou null quand golem ne sait pas le faire ici (la phrase reste) — §4 : « un bouton là où
 *  golem peut le faire, une phrase là où il ne peut pas ». `ctx.stage` = /live ou Companion : lecture seule.
 *  `ctx.can` = les gestes que l'écran sait faire (le Designer : turn-off, lighter-capture). */
export function fixButton(fix, ctx = {}) {
  const a = (fix && fix.action) || null;
  if (!a || ctx.stage) return null;
  const can = new Set(ctx.can || []);
  switch (a.kind) {
    case 'perf-mode': return { kind: 'perf-mode', label: 'Turn on', primary: true };
    case 'buffer': return { kind: 'buffer', label: 'Settings' };
    case 'turn-off': return can.has('turn-off') && a.block ? { kind: 'turn-off', label: 'Turn off' } : null;
    case 'lighter-capture':
      if (!can.has('lighter-capture') || !a.block) return null;
      return a.ref ? { kind: 'lighter-capture', label: 'Use it' } : { kind: 'lighter-capture', label: 'Find' };
    default: return null;               // mono, split : une phrase, pas de bouton (aucun geste propre du Designer)
  }
}

/** les correctifs à montrer pour une lane : ceux qui la visent (`action.lane`), sinon tous s'il s'agit de la lane la
 *  plus chargée — le bridge les range du moins cher au plus cher, on garde son ordre */
export function fixesFor(est, laneId) {
  const fixes = ((est && est.fixes) || []).filter(f => f && f.title);
  const worstLane = ((est && est.worst) || {}).lane;
  return fixes.filter(f => {
    const l = (f.action || {}).lane;
    return l ? l === laneId : laneId == null || laneId === worstLane;
  });
}

/** la ligne « où et quand » (§3 : chaque chiffre dit sur quelle machine et quand il a été mesuré) */
export function machineLine(src, now = new Date()) {
  const m = (src && src.machine) || {};
  if (!src || (!m.cpu && !src.measured_at)) return 'Not measured on this golem yet.';
  const bits = ['Measured on this golem'];
  if (m.cpu) bits.push(String(m.cpu));
  if (m.governor) bits.push(m.governor === 'performance' ? 'performance mode' : String(m.governor));
  if (num(m.bsize) != null) bits.push(m.bsize + ' samples');
  if (num(m.srate) != null) bits.push(Math.round(m.srate / 100) / 10 + ' kHz');
  const when = whenText(src.measured_at, now);
  if (when) bits.push(when);
  return bits.join(' · ');
}
/** « today 22:40 », « yesterday 09:05 », « 12 Nov » — l'heure locale de l'écran */
export function whenText(at, now = new Date()) {
  if (at == null || at === '') return '';
  const d = typeof at === 'number' ? new Date(at < 1e12 ? at * 1000 : at) : new Date(at);
  if (Number.isNaN(d.getTime())) return '';
  const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dd = Math.round((day(now) - day(d)) / 86400000);
  if (dd === 0) return 'today ' + hm;
  if (dd === 1) return 'yesterday ' + hm;
  return d.getDate() + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()];
}
/** « Each lane runs on one core: its bar is that core's time for one buffer (4.0 ms · 192 samples · 48 kHz). » */
export function budgetLine(est) {
  const m = (est && est.machine) || {};
  const us = num(est && est.budget_us);
  const parts = [];
  if (us != null) parts.push((us / 1000).toFixed(1) + ' ms');
  if (num(m.bsize) != null) parts.push(m.bsize + ' samples');
  if (num(m.srate) != null) parts.push(Math.round(m.srate / 100) / 10 + ' kHz');
  return 'Each lane runs on one core: its bar is that core\'s time for one buffer' + (parts.length ? ' (' + parts.join(' · ') + ')' : '') + '.';
}

// ── SUR SCÈNE (/live, Companion) : une puce SEULEMENT si c'est tendu ou rouge, jamais un chiffre (§3) ─────────────
/** la puce du morceau chargé : « CPU tight in scene C » / « CPU will crackle in scene C » — null sinon */
export function stageChip(entry) {
  if (!entry) return null;
  const w = entry.worst || {};
  const level = verdictOf(entry.verdict, w.pct);
  if (level !== 'tight' && level !== 'red') return null;
  const where = w.scene ? ' in scene ' + w.scene : '';
  return { level, text: level === 'red' ? 'CPU will crackle' + where : 'CPU tight' + where };
}
/** la puce d'une ligne à venir de la setlist : « CPU tight » / « CPU: will crackle » — null sinon */
export function nextChip(entry) {
  if (!entry) return null;
  const level = verdictOf(entry.verdict, (entry.worst || {}).pct);
  if (level === 'red') return { level, text: 'CPU: will crackle' };
  if (level === 'tight') return { level, text: 'CPU tight' };
  return null;
}

// ── UN BLOC, UNE CAPTURE (Library, tiroir) ───────────────────────────────────────────────────────────────────
/** l'architecture NAM d'un modèle du catalogue, comme variante du profil (§2, §9 : `nam:standard`, `nam:lite`…) */
export function namArch(model) {
  if (!model) return 'standard';
  if (String(model.arch) === '2') return 'a2';
  const s = String(model.size || '').toLowerCase().trim();
  return ['standard', 'lite', 'feather', 'nano'].includes(s) ? s : 'standard';
}
export const namVariant = model => 'nam:' + namArch(model);

/** la requête GET /api/cpu/block (§9) */
export function blockQuery(type, variant, stereo) {
  const q = new URLSearchParams();
  q.set('type', type || '');
  if (variant) q.set('variant', variant);
  q.set('stereo', stereo ? '1' : '0');
  return '/api/cpu/block?' + q.toString();
}
/** la clé de cache d'un coût de bloc */
export const blockKey = (type, variant, stereo) => (type || '') + (variant ? ':' + variant : '') + '|' + (stereo ? 'stereo' : 'mono');

/** le pourcentage d'une réponse /api/cpu/block, null si pas mesuré */
export const costPct = cost => (cost && cost.measured !== false ? num(cost.pct) : null);

/** « ≈ 9 % of a core » ; « not measured on this golem » ; '' quand on ne sait rien (route absente) */
export function blockCostLine(cost) {
  if (!cost) return '';
  const p = costPct(cost);
  return p == null ? 'not measured on this golem' : '≈ ' + fmtPct(p) + ' of a core';
}
/** la puce d'une capture : « 6 % · lite », « not measured · lite » ; '' sans réponse */
export function captureCostLabel(cost, arch) {
  if (!cost) return '';
  const p = costPct(cost);
  return (p == null ? 'not measured' : fmtPct(p)) + (arch ? ' · ' + arch : '');
}
/** la fourchette d'un ampli : « ≈ 6–18 % of a core » / « ≈ 6 % of a core » ; '' si aucune capture mesurée */
export function rangeLine(pcts) {
  const ps = (pcts || []).map(num).filter(p => p != null);
  if (!ps.length) return '';
  const lo = Math.round(Math.min(...ps)), hi = Math.round(Math.max(...ps));
  return '≈ ' + (lo === hi ? lo : lo + '–' + hi) + ' % of a core';
}

/** « this lane would go to 85 % » (le tiroir d'ajout) : la lane dans sa scène la plus lourde + le bloc (un bloc ajouté
 *  est allumé partout) — null quand l'un des deux n'est pas mesuré */
export function afterAdd(lanePct, cost) {
  const a = num(lanePct), b = costPct(cost);
  if (a == null || b == null) return null;
  const pct = a + b;
  return { pct, level: levelOf(pct), text: '→ ' + fmtPct(pct) };
}

// ── L'ÉCOUTE DANS LA LIBRARY (swap, §9) ────────────────────────────────────────────────────────────────────────
/** la barre « avant → après » : {before, after, level, text, segs:[{from, w, level}]} — null sans réponse */
export function swapView(swap) {
  if (!swap) return null;
  const b = num(swap.before_pct), a = num(swap.after_pct);
  if (b == null || a == null) return null;
  const level = verdictOf(swap.verdict_after, a);
  const lo = barWidth(Math.min(a, b)), hi = barWidth(Math.max(a, b));
  return {
    before: b, after: a, level,
    text: fmtPct(b) + ' → ' + fmtPct(a) + ' · ' + VERDICT_LONG[level],
    // le socle commun, puis ce qui s'ajoute (couleur de l'après) ou ce qui se libère (hachuré)
    base: { w: lo, level: levelOf(Math.min(a, b)) },
    delta: { from: lo, w: hi - lo, level, freed: a < b },
  };
}
/** la phrase sous la barre : « This capture (standard) costs 4 % more than the EVH 5150 it replaces. Capture 1 (lite)
 *  would bring the lane to 72 %. » — `names` : {current: nom du bloc remplacé, arch, lighterName} */
export function swapHint(swap, names = {}) {
  const v = swapView(swap);
  if (!v) return '';
  const d = Math.round(v.after - v.before);
  const what = 'This capture' + (names.arch ? ' (' + names.arch + ')' : '');
  const than = names.current ? ' than the ' + names.current + ' it replaces' : ' than the capture it replaces';
  let s = d > 0 ? what + ' costs ' + d + ' % more' + than + '.'
    : d < 0 ? what + ' costs ' + (-d) + ' % less' + than + '.'
    : what + ' costs about the same' + than + '.';
  const L = swap.lighter;
  if (L && num(L.pct) != null && v.level !== 'ok') s += ' ' + (names.lighterName || 'A lighter capture') + ' would bring the lane to ' + fmtPct(L.pct) + '.';
  return s;
}

/** la couleur d'UN bloc (Library, puces de capture) : sa part d'un cœur, à l'échelle d'un bloc — une lane en porte
 *  plusieurs, les seuils de lane (60 / 80) n'y veulent rien dire. ≤ 10 % léger, ≤ 25 % moyen, au-delà lourd. */
export function blockLevel(pct) {
  const p = num(pct);
  if (p == null) return 'unknown';
  return p > 25 ? 'red' : p > 10 ? 'tight' : 'ok';
}

/** une lane proposée par « Add to… » : grisée si la capture la pousse dans le rouge, avec la raison */
export function addLaneState(afterPct) {
  const p = num(afterPct);
  if (p == null) return { disabled: false, why: '' };
  if (levelOf(p) === 'red') return { disabled: true, level: 'red', why: 'would go to ' + fmtPct(p) + ' of a core — it would crackle' };
  if (levelOf(p) === 'tight') return { disabled: false, level: 'tight', why: 'would go to ' + fmtPct(p) + ' of a core — tight' };
  return { disabled: false, level: 'ok', why: '' };
}

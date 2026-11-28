// SPDX-License-Identifier: GPL-3.0-or-later
// SETTINGS ▸ HEALTH (docs/health.md, maquette mockups/health.html, validée le 2026-10-20) : la part pure, testée
// (health-model.test.mjs). Le bridge mesure et juge (bridge/health.py) ; ici on ne fait que traduire son verdict en
// point de santé pour la barre du haut, et dater ses faits pour l'écran — jamais une mesure côté écran.

// Le point de la barre : `level` colore le point (vert, orange, rouge) ; `badge` = la pastille posée sur ⚙, System et
// l'onglet Health, et `text` = le mot à côté du point — SEULEMENT en rouge. L'orange n'est pas une panne : il se lit
// sur le point et sur la page Health, pas dans tous les menus (2026-10-20 : « c'est orange mais pas bloquant,
// pas la peine que ce soit comme si l'app était en erreur »). `null` tant que le bridge n'a pas mesuré.
export const healthDot = st => {
  const h = st && st.health;
  if (!h || !h.level) return null;
  const n = (h.bad || 0) + (h.warn || 0);
  const title = (h.title || '') + (n ? ' — ' + n + (n === 1 ? ' thing' : ' things') + ' to look at in Settings ▸ System ▸ Health' : '');
  if (h.level === 'bad') return { level: 'bad', badge: 'bad', text: 'something is wrong', title };
  if (h.level === 'warn') return { level: 'warn', badge: null, text: '', title };
  if (h.level === 'wait') return { level: 'wait', badge: null, text: '', title: h.title || '' };
  return { level: 'ok', badge: null, text: '', title: h.title || '' };
};

// « checked 12 s ago » — à partir de l'horloge du BRIDGE (fact.at vs doc.at), jamais de celle de l'écran
export const ago = (s) => {
  if (s == null || !(s >= 0)) return '';
  if (s < 90) return Math.round(s) + ' s ago';
  if (s < 5400) return Math.round(s / 60) + ' min ago';
  return (s / 3600).toFixed(0) + ' h ago';
};

// la rangée des compteurs du verdict : « 12 · 1 · 1 waiting » — les zéros se taisent
export const countsLine = counts => {
  if (!counts) return [];
  const out = [];
  if (counts.ok) out.push({ level: 'ok', n: counts.ok });
  if (counts.warn) out.push({ level: 'warn', n: counts.warn });
  if (counts.bad) out.push({ level: 'bad', n: counts.bad });
  if (counts.wait) out.push({ level: 'wait', n: counts.wait, word: 'waiting' });
  return out;
};

// ── HEALTH ▸ FIX ET LES INCIDENTS (docs/assistant.md §3, maquette mockups/health-fix.html validée le 2026-10-20) ──
// La pastille d'un incident : comment il a fini (ou qu'il ne l'est pas). Le bridge décide (bridge/incidents.py),
// l'écran ne fait que le dire.
export const incidentChip = inc => {
  if (!inc) return null;
  if (inc.state === 'open') return { cls: 'open', text: 'open' };
  if (inc.state === 'verifying') return { cls: 'rs', text: 'verifying' };
  if (inc.resolved_by === 'action') return { cls: 'act', text: 'fixed' + (inc.by === 'assistant' ? ' · assistant' : inc.by === 'doctor' ? ' · doctor' : '') };
  if (inc.resolved_by === 'restart') return { cls: 'rs', text: 'restart' };
  if (inc.resolved_by === 'outside') return { cls: 'out', text: 'outside' + (inc.hint ? ' · ' + inc.hint : '') };
  return { cls: '', text: inc.resolved_by || inc.state || '' };
};

const dur = s => (s < 90 ? Math.round(s) + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : Math.round(s / 3600) + ' h');
const when = (t, now) => {
  const d = new Date(t * 1000), n = new Date(now * 1000);
  const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  if (d.toDateString() === n.toDateString()) return 'today ' + hm;
  if (now - t < 2 * 86400 && new Date((now - 86400) * 1000).toDateString() === d.toDateString()) return 'yesterday ' + hm;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
};

// la ligne sous le titre : quand, et combien de temps ça a duré (ou depuis quand ça dure)
export const incidentLine = (inc, now) => {
  if (!inc) return '';
  if (inc.state !== 'closed') return 'since ' + when(inc.opened_at, now).replace('today ', '') + (inc.detail ? ' · ' + inc.detail : '');
  return when(inc.closed_at, now) + ' · back after ' + dur(inc.after_s || 0);
};

// « What fixed it? » : le dernier incident revenu tout seul dans l'heure, sans réponse, que la main peut régler (le bridge
// dit `hintable` : la carte, le pédalier, REAPER — pas golem.fm ni le disque) — jamais pendant qu'on joue
export const hintCandidate = (items, now, busy) => {
  if (busy) return null;
  return (items || []).find(i => i.state === 'closed' && i.resolved_by === 'outside' && i.hintable && !i.hint && now - (i.closed_at || 0) < 3600) || null;
};

// le retour arrière d'une réparation : seulement la dernière fermée par une action qui en porte un
export const undoCandidate = items => {
  const last = (items || []).find(i => i.state === 'closed');
  return last && last.resolved_by === 'action' && last.undo ? last : null;
};

// la dernière réparation SANS incident (demandée à l'assistant, ou depuis doctor) qui a changé un réglage : son retour
// arrière doit rester à portée — sinon la feuille promet un « Undo » introuvable. Une heure, pas plus.
export const lastFixUndo = (last, now) => (last && last.undo && !last.incident && ['done', 'failed'].includes(last.phase)
  && now - (last.ended_at || 0) < 3600 ? last : null);

// ── HEALTH V2 (maquette mockups/health-v2.html, validée le 2026-11-25 : « elle est très chargée, et on ne comprend pas
// tout ») : un verdict en mots de musicien, ce qui DEMANDE quelque chose en cartes (une fois chacun), ce qui va bien en
// pastilles, l'historique groupé par sujet. Les sources techniques ne sont plus au premier niveau : elles vivent dans le
// détail, sous « For developers ». Toujours le verdict et les faits du BRIDGE : l'écran ne fait que les dire.

// le nom d'un fait pour un musicien (le bridge nomme pour le diagnostic) ; un fait inconnu garde son nom
const PLAIN = { engine: 'Audio engine', audio: 'Sound card', dropouts: 'Clicks', pedalboard: 'Pedalboard', playing: 'Sound loaded',
  setlist: 'Setlist', plugins: 'Plugins', disk: 'Disk', golemfm: 'golem.fm', scripts: 'Scripts', perf: 'Processor speed',
  cpu: 'CPU budget', environment: 'Since last start', display: 'Display', safemode: 'Card safe mode', midi: 'MIDI devices' };
export const plainName = f => PLAIN[f && f.id] || (f && f.name) || '';

// le titre d'une carte « Needs you » : ce qui se passe, pas le nom de la sonde
const PROBLEM = { dropouts: 'Clicks in the sound', golemfm: 'golem.fm is out of reach', engine: 'The audio engine is not playing',
  audio: 'The sound card is not playing', pedalboard: 'The pedalboard does not answer', playing: 'The sound is not fully loaded',
  setlist: 'The setlist is not ready', plugins: 'Plugins are missing', disk: 'The disk is almost full', scripts: 'A script failed',
  perf: 'The processor is saving power', cpu: 'The CPU budget is not measured', display: 'Moving tiles may cause the clicks',
  midi: 'A MIDI device is not reachable' };
export const problemTitle = f => PROBLEM[f && f.id] || plainName(f);

// une INFORMATION, pas un problème : ce qui a changé depuis le dernier démarrage (une mise à jour se dit, elle n'alarme
// pas), et un CONSEIL du bridge (`advice` : le safe mode de la carte, qui ajoute ~3 ms) — en bleu, hors du compte ;
// et ce dont le jeu ne dépend pas (golem.fm) — une carte bleue, qui compte quand même parmi ce qui demande
export const isInfo = f => !!f && (f.id === 'environment' || !!f.advice);
// la couleur d'une pastille : bleue pour une information qui dit quelque chose (un conseil, un changement), sinon son niveau
export const chipLevel = f => (isInfo(f) && (f.advice || f.level !== 'ok') ? 'info' : f.level);
export const offStage = f => !!f && f.id === 'golemfm';
export const OFF_STAGE_NOTE = 'Playing does not need it.';

// ce qui demande quelque chose : orange ou rouge, sauf une information ; le rouge d'abord
export const needs = facts => (facts || []).filter(f => (f.level === 'warn' || f.level === 'bad') && !isInfo(f))
  .sort((a, b) => (b.level === 'bad') - (a.level === 'bad') || offStage(a) - offStage(b));

// le verdict en mots : peut-on jouer ? `level` est celui du bridge ; `n` = le nombre de choses qui demandent
export const verdictWords = (level, n) => {
  const things = n + (n === 1 ? ' thing needs you' : ' things need you');
  if (level === 'bad') return { title: 'Not ready — ' + things, sub: 'Look at the red one first.' };
  if (level === 'warn' && n) return { title: 'Playable — ' + things, sub: 'Everything else works.' };
  if (level === 'wait') return { title: 'Measuring…', sub: 'golem is reading the rack.' };
  return { title: 'Ready to play', sub: 'Every check is green.' };
};

// la ligne courte d'une pastille : les deux premiers morceaux du texte du bridge (la suite est dans le détail)
export const chipText = f => String((f && f.text) || '').split(' · ').slice(0, 2).join(' · ').split(' — ')[0];

// « 5 weeks ago », « today » : la date du dernier passage du first check, en mots
export const sinceWords = (t, now) => {
  if (!t || !now) return 'never';
  const d = Math.max(0, now - t) / 86400;
  if (d < 1) return 'today';
  if (d < 2) return 'yesterday';
  if (d < 14) return Math.round(d) + ' days ago';
  if (d < 60) return Math.round(d / 7) + ' weeks ago';
  return Math.round(d / 30) + ' months ago';
};

// l'historique groupé par SUJET : le plus récent de chaque titre, combien de fois, et comment il a fini — en mots
const ENDED = { action: 'fixed by golem', restart: 'fixed by a restart', outside: 'came back by itself' };
export const historyRows = (items, now) => {
  const by = new Map();
  for (const i of items || []) {
    const k = i.title || '';
    const g = by.get(k);
    if (!g) by.set(k, { ...i, times: 1 });
    else g.times += 1;
  }
  return [...by.values()].map(i => {
    const open = i.state !== 'closed';
    const how = open ? 'happening now · since ' + when(i.opened_at, now).replace('today ', '')
      : when(i.closed_at, now) + ' · ' + (ENDED[i.resolved_by] || i.resolved_by || 'ended') + (i.resolved_by === 'outside' ? ' after ' + dur(i.after_s || 0) : '')
        + (i.hint ? ' (' + i.hint + ')' : '');
    return { id: i.id, title: i.title, open, times: i.times, text: how + (i.times > 1 ? ' · ' + i.times + ' times' : '') };
  }).sort((a, b) => b.open - a.open);
};

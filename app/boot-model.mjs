// SPDX-License-Identifier: GPL-3.0-or-later
// L'écran de chargement (mockups/loading.html, 2026-10-11) : pur, testé (boot-model.test.mjs).
// Entrée : `st` = l'état du bridge (st.boot = {t0, now, steps, done, failed, why, last_took}, plus reaper_running,
// audio, midi, pedalboard, preset_id, preset_name, bank_base…) ; `extra` = les secondes accordées par « Keep waiting »,
// par module. Sortie : les lignes {id, name, text, state: ok|on|wait|late|skip, ms, actions} et le verdict
// {done, late, failed}. RÈGLE : rien n'est une erreur avant son délai — par module, au double du dernier démarrage
// (30 s minimum pour REAPER) ; le MIDI et golem.fm ne sont JAMAIS en retard (absents, ils sont dits, pas déplorés).

export const DEADLINES = (lastTook) => {
  const ref = Math.max(30, Math.ceil((lastTook || 0) * 2));
  return { reaper: ref, osc: 15, audio: 20, preset: Math.max(15, Math.ceil((lastTook || 0))) };
};

const fmt = s => s == null ? '' : (s < 10 ? s.toFixed(1) : Math.round(s)) + ' s';
const since = (boot, step) => boot.steps && boot.steps[step] != null ? boot.steps[step] - boot.t0 : null;

export const bootRows = (st, extra) => {
  st = st || {}; extra = extra || {};
  const boot = st.boot || { t0: 0, now: 0, steps: {} };
  const dl = DEADLINES(boot.last_took);
  const now = (boot.now || 0) - (boot.t0 || 0);
  const steps = boot.steps || {};
  const osName = boot.os || ({ win32: 'Windows', windows: 'Windows', linux: 'Linux', darwin: 'macOS' })[(st.caps || {}).os] || '';
  const rows = [];
  const elapsedFrom = step => now - (steps[step] != null ? steps[step] - boot.t0 : 0);
  // 1. le bridge : la page a sa réponse
  rows.push({ id: 'bridge', name: 'Bridge', state: 'ok', text: 'up' + (st.devices_online && st.devices_online.length ? ' · ' + st.devices_online.length + ' device' + (st.devices_online.length > 1 ? 's' : '') + ' connected' : ''), ms: fmt(0.3) });
  // 2. le moteur : process, puis lien OSC
  const rp = since(boot, 'reaper'), osc = since(boot, 'osc');
  let s2 = 'on', t2 = 'starting REAPER…', ms2 = fmt(now);
  if (osc != null) { s2 = 'ok'; t2 = 'REAPER started · talking (OSC)'; ms2 = fmt(osc); }
  else if (rp != null) { t2 = 'REAPER started · waiting for it to answer…'; if (now - rp > dl.osc + (extra.osc || 0)) { s2 = 'late'; t2 = 'REAPER started but is not answering (OSC silent for ' + Math.round(now - rp) + ' s)'; } }
  else if (now > dl.reaper + (extra.reaper || 0)) { s2 = 'late'; t2 = 'REAPER has not started after ' + Math.round(now) + ' s'; }
  if (boot.failed && s2 !== 'ok') { s2 = 'late'; t2 = boot.failed; }
  rows.push({ id: 'reaper', name: 'Audio engine', state: s2, text: t2, ms: ms2, actions: s2 === 'late' ? ['restart', 'wait'] : [] });
  // 3. la carte son
  const au = since(boot, 'audio'), a = st.audio || {};
  const card = (st.audio_metrics || {}).driver || a.card || 'sound card';
  const buf = (st.audio_metrics || {}).buffer_size ? ' · ' + st.audio_metrics.buffer_size + ' smp' : '';
  let s3 = 'wait', t3 = card + ' — waits for the engine', ms3 = '';
  if (au != null) { s3 = 'ok'; t3 = card + buf; ms3 = fmt(au); }
  else if (osc != null) { s3 = 'on'; t3 = 'opening ' + card + buf + '…'; ms3 = fmt(now);
    if (now - osc > dl.audio + (extra.audio || 0)) { s3 = 'late'; t3 = card + (a.why ? ' — ' + a.why : ' is not answering (' + Math.round(now - osc) + ' s)'); } }
  rows.push({ id: 'audio', name: 'Sound card', state: s3, text: t3, ms: ms3, actions: s3 === 'late' ? ['restart', 'wait'] : [] });
  // 4. MIDI : dit, jamais déploré
  const mi = since(boot, 'midi'), m = st.midi || {}, pb = st.pedalboard || {};
  let s4 = 'wait', t4 = 'pedalboard, keyboards — after the sound card', ms4 = '';
  if (mi != null) { ms4 = fmt(mi);
    if (m.ok === false) { s4 = 'skip'; t4 = (m.issues && m.issues[0] && (m.issues[0].text || m.issues[0].msg || m.issues[0])) || 'MIDI issue' + (m.fix ? ' — ' + m.fix : ''); }
    else { s4 = 'ok'; t4 = pb && pb.id ? 'pedalboard ' + (pb.name || pb.id) + (pb.stale ? ' (not confirmed)' : '') : 'no pedalboard'; } }
  rows.push({ id: 'midi', name: 'MIDI', state: s4, text: String(t4), ms: ms4 });
  // 5. le premier preset
  const pr = since(boot, 'preset');
  const want = st.preset_name || (st.preset_id ? String(st.preset_id) : 'bank 00');
  let s5 = 'wait', t5 = 'bank 00' + (st.preset_name ? ' · ' + st.preset_name : ''), ms5 = '';
  if (boot.done) { s5 = 'ok'; t5 = want + ' plays'; ms5 = fmt(pr != null ? pr : (boot.done - boot.t0)); }
  else if (au != null) { s5 = 'on'; t5 = 'loading ' + want + '…'; ms5 = fmt(now);
    if (now - au > dl.preset + (extra.preset || 0)) { s5 = 'late'; t5 = want + ' is still loading after ' + Math.round(now - au) + ' s'; } }
  if (boot.failed && /preset/i.test(boot.failed)) { s5 = 'late'; t5 = boot.failed; }
  rows.push({ id: 'preset', name: 'First preset', state: s5, text: t5, ms: ms5, actions: s5 === 'late' ? ['wait'] : [] });
  // 6-7. LES DEUX SERVICES (2026-10-11) : golem.fm et TONE3000 — injoignables ou refusés = en ERREUR, dits sur une page
  // qui RESTE (showBoot) jusqu'à « Open the app anyway » ou au réglage. JAMAIS RÉGLÉS (audit 2026-10-31 : un golem neuf
  // restait sur cet écran à CHAQUE démarrage) = une ligne `soft` qui ne retient rien : golem.fm est optionnel (les chansons
  // partagées, les stems, le groupe), TONE3000 donne les captures — dit en orange, sans bloquer.
  const sv = boot.services || {};
  const fmS = sv.fm || {}, fm = since(boot, 'fm');
  if (!boot.services) {                                 // un bridge qui ne vérifie pas encore (plus vieux que la page) : dit, jamais une erreur
    rows.push(fm != null ? { id: 'fm', name: 'golem.fm', state: 'ok', text: 'linked', ms: fmt(fm) } : { id: 'fm', name: 'golem.fm', state: 'skip', text: 'not checked by this bridge — restart golem to check', ms: '' });
    rows.push({ id: 't3k', name: 'TONE3000', state: 'skip', text: 'not checked by this bridge — restart golem to check', ms: '' });
  } else if (fm != null || fmS.ok) rows.push({ id: 'fm', name: 'golem.fm', state: 'ok', text: 'linked', ms: fmt(fm != null ? fm : now) });
  else if (fmS.configured === false) rows.push({ id: 'fm', name: 'golem.fm', state: 'skip', soft: true, text: 'optional — not paired · shared songs, your band', ms: '' });
  else if (fmS.configured && now > 12) rows.push({ id: 'fm', name: 'golem.fm', state: 'late', text: 'paired but not reachable — check the network or golem.fm', ms: '', actions: ['setup', 'wait'], err: true });
  else rows.push({ id: 'fm', name: 'golem.fm', state: 'on', text: fmS.configured ? 'connecting…' : 'checking…', ms: '' });
  const tk = sv.t3k || {};
  if (!boot.services) { /* déjà dit */ }
  else if (tk.ok) rows.push({ id: 't3k', name: 'TONE3000', state: 'ok', text: 'connected', ms: '' });
  else if (tk.ok === null || tk.ok === undefined) rows.push({ id: 't3k', name: 'TONE3000', state: now > 20 ? 'late' : 'on', text: now > 20 ? 'no answer — check the network' : 'checking…', ms: '', actions: now > 20 ? ['setup', 'wait'] : [], err: now > 20 });
  else if (tk.configured === false) rows.push({ id: 't3k', name: 'TONE3000', state: 'late', soft: true, text: 'not connected · amp captures come from TONE3000', ms: '', actions: ['setup'] });
  else rows.push({ id: 't3k', name: 'TONE3000', state: 'late', text: 'not connected — ' + (tk.why || 'sign in again') + ' · amp captures come from TONE3000', ms: '', actions: ['setup'], err: true });
  // 8. LA LICENCE REAPER (2026-10-16) : sans elle REAPER tourne en évaluation — un rappel d'achat, pas une panne.
  // Dite en orange avec « Set up » (Settings ▸ About ▸ REAPER) ; `soft` : elle ne fait ni « traîner » le démarrage
  // (pas de « Open the app anyway ») ni rester l'écran (pas `err`). Licence là, ou pas encore lue : pas de ligne.
  const rl = (boot.services && boot.services.reaper) || {};
  if (rl.ok === false) rows.push({ id: 'lic', name: 'REAPER', state: 'late', soft: true, ms: '', actions: ['setup'],
    text: rl.present && rl.state === 'evaluation' ? 'evaluation — this REAPER does not accept the license on this computer'
      : 'evaluation — add your license to remove the reminder' });
  const late = rows.some(r => r.state === 'late' && !r.soft);
  const servicesError = rows.some(r => r.err);
  return { rows, done: !!boot.done, late, servicesError, failed: boot.failed || null, os: osName, lastTook: boot.last_took || null, elapsed: now };
};

// l'écran s'affiche à la place de /live tant que le démarrage n'est pas fini — sauf si l'utilisateur est sorti
// par « Open the app anyway » POUR CE démarrage (t0) : un autre démarrage (restart) le ramène
// DEV : un état fabriqué pour voir l'écran sans redémarrer (main.js : ?boot=demo[&at=40]) — l'écran 1 à 9 s,
// l'écran 2 (REAPER muet) à 40 s de la maquette
export const demoState = (at) => {
  const t0 = 1000, s = Number(at) || 9;
  const steps = s < 30 ? { reaper: t0 + 2.1, osc: t0 + 6.4, fm: t0 + 1.9 } : { reaper: t0 + 2.0, midi: t0 + 1.2 };
  return { boot: { t0, now: t0 + s, steps, done: null, failed: null, last_took: 11, os: s < 30 ? 'Windows' : 'Linux',
      services: s < 30 ? { fm: { configured: true, ok: true }, t3k: { configured: true, ok: true } }
                       : { fm: { configured: false, ok: false, why: 'not paired' }, t3k: { configured: true, ok: false, why: 'token expired' },
                         reaper: { present: false, state: null, ok: false } } },
    audio: { ok: false }, audio_metrics: { driver: 'ASIO Universal Audio Volt', buffer_size: 128 },
    midi: s < 30 ? {} : { ok: true }, pedalboard: { id: 'fcb1010-uno2', name: 'FCB1010' },
    preset_name: s < 30 ? 'Velvetine — Swerve Lane' : 'Paper Kite', devices_online: [{ id: 'a' }, { id: 'b' }] };
};

export const showBoot = (st, skippedT0, extra) => {
  const boot = st && st.boot;
  if (!boot || !boot.t0) return false;
  if (skippedT0 === boot.t0) return false;
  if (!boot.done) return true;
  return bootRows(st, extra).servicesError;          // fini, mais un service en erreur : la page reste, et le dit
};

// SPDX-License-Identifier: GPL-3.0-or-later
// Le MIXER de /live (contrat docs/mixer.md, maquette « maison » validée) — doser ce qui
// sort du rack : les lanes d'instruments, les blocs de service, le clic. Plein écran sous la
// topbar, une tranche par source.
//
// CE QUE CET ÉCRAN RÈGLE : le D_VOL du SEND MATÉRIEL de chaque piste-source (le trim du rig),
// jamais le fader de piste (niveau de scène, autorité du preset) ni le bloc Volume (pédale EXP).
// Les niveaux sont du RIG : ils survivent aux recalls et aux redémarrages (config/mixer.json).
//
// LE TRIM ATTÉNUE : 0 dB = unité, en haut du fader — pas de gain. Tout se somme dans une seule
// paire sur une petite carte, et c'est là que ça clippe (bug volume 2026-07-23).
//
// LINK — PAS UN MODE (refonte 2026-08-07, verdict : « j'aurais mis juste une case à
// cocher »). Chaque tranche porte une case PERMANENTE ; dès que deux sont cochées, bouger l'un
// de leurs faders les déplace toutes du même ÉCART en dB. Aucun état à comprendre, aucun clic
// d'entrée/sortie de mode — et la case ne coûte rien en hauteur puisqu'elle absorbe l'afficheur
// de dB, qui gaspillait 19 px pour un glyphe.
//
// ⚠ LE DELTA EST BORNÉ, PAS LES MEMBRES. Clamper chaque membre séparément détruit précisément
// ce que le groupe doit préserver : dès qu'un membre touche 0 dB il sature pendant que les
// autres continuent, et les écarts s'écrasent EN SILENCE. Le groupe touche le mur d'un bloc.
// Corollaire assumé : tout étant à 0 par défaut, un groupe ne peut que descendre.
//
// Le mix d'ENREGISTREMENT suit ces niveaux (recopié sur le send vers la piste Recording) : la
// prise porte le mix complet tel qu'entendu ; les DI, eux, restent bruts.
import { html, useState, useRef, useAsync, post, cls, esc, LoadGuard } from './lib.js';

const DB_MIN = -60, DB_MAX = 0;
const clampDb = v => Math.max(DB_MIN, Math.min(DB_MAX, Math.round(v * 2) / 2));
const fmt = db => (db == null || db <= DB_MIN) ? '−∞' : (db === 0 ? '0' : (db > 0 ? '+' : '−') + Math.abs(db).toFixed(Math.abs(db) < 10 ? 1 : 0));

// fader vertical tactile : géométrie linéaire en dB (-60..0), bas de course = −∞ (send coupé).
// mode 'solo' : le tap saute à la position (attendu au doigt, et vrai aussi pour une tranche
// cochée SEULE — un groupe d'un est un fader normal). mode 'group' : le tap ne saute pas, le
// parent n'exploite que le DELTA depuis le début du geste.
// Throttle ~8/s (chaque envoi = une écriture de .command.json + un tick Reaper), envoi FINAL
// garanti au relâchement.
function Fader({ db, mode = 'solo', onStart, onChange, disabled }) {
  const ref = useRef(null);
  const throttle = useRef({ t: 0, timer: null, last: null });
  const pct = Math.max(0, Math.min(100, ((db ?? 0) - DB_MIN) / (DB_MAX - DB_MIN) * 100));

  const dbAt = (clientY) => {
    const r = ref.current.getBoundingClientRect();
    const frac = 1 - Math.max(0, Math.min(1, (clientY - r.top) / r.height));
    return clampDb(DB_MIN + frac * (DB_MAX - DB_MIN));
  };
  const send = (v, final) => {
    const th = throttle.current;
    th.last = v;
    const now = Date.now();
    if (final || now - th.t > 120) {
      th.t = now;
      if (th.timer) { clearTimeout(th.timer); th.timer = null; }
      onChange(v);
    } else if (!th.timer) {
      th.timer = setTimeout(() => { th.timer = null; th.t = Date.now(); onChange(th.last); }, 130);
    }
  };
  const down = (e) => {
    if (disabled) return;
    // ⚠ capturer l'ÉLÉMENT : e.currentTarget n'est valide que pendant la dispatch — dans un
    // handler différé (up) il est null, et le removeEventListener plantait au relâchement
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    onStart && onStart(dbAt(e.clientY));
    if (mode === 'solo') send(dbAt(e.clientY), false);      // group : delta pur, personne ne saute
    const move = ev => send(dbAt(ev.clientY), false);
    const up = ev => {
      send(dbAt(ev.clientY), true);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
  };

  return html`<div class=${cls('lmx-fader', disabled && 'off')} ref=${ref} onPointerDown=${down}>
    <div class="lmx-rail">
      <div class="lmx-fill" style=${`height:${pct}%`} />
      <div class="lmx-knob" style=${`bottom:calc(${pct}% - 9px)`} />
    </div>
  </div>`;
}

export function LiveMixer({ rig, onClose }) {
  const { data, err, reload } = useAsync(() => fetch('/api/mixer').then(r => r.json()), []);
  // état optimiste : le fader suit le doigt, le POST confirme — sans ça chaque throttle
  // ferait sauter le curseur en arrière le temps de l'aller-retour
  const [local, setLocal] = useState({});
  // la sélection meurt à la fermeture du mixer, elle n'est JAMAIS persistée : un groupe qui
  // survivrait invisiblement, c'est le doigt qui traîne différé de trois jours
  const [sel, setSel] = useState([]);
  const gesture = useRef(null);

  if (!data || !data.sources) return html`<${LoadGuard} err=${err} reload=${reload} label="Reading the mixer…" />`;
  const st = (rig && rig.state) || {};
  const lv = { ...data.levels };
  for (const [k, v] of Object.entries(local)) lv[k] = { ...lv[k], ...v };
  const dbOf = id => (lv[id] || {}).db ?? 0;

  // une source qui a disparu du preset ne doit plus peser dans un geste de groupe : on écrirait
  // des niveaux pour une piste absente, invisiblement
  const alive = data.sources.filter(s => s.present).map(s => s.id);
  const group = sel.filter(id => alive.includes(id));
  const linked = id => group.includes(id);

  // une tranche de BOUCLE (« loop:N ») : son volume vit dans le looper (et la table du preset), pas dans un send
  const loopSlot = id => String(id).startsWith('loop:') ? +String(id).slice(5) : null;
  const postLoop = (id, ch) => post('/api/looper', { op: 'level', slot: loopSlot(id), ...ch }).catch(() => {});
  const postOne = (id, db) => {
    setLocal(l => ({ ...l, [id]: { ...l[id], db } }));
    if (loopSlot(id) != null) postLoop(id, { db });
    else post('/api/mixer', { source: id, db }).catch(() => {});
  };
  const postGroup = (changes) => {                  // {id: db} — UNE requête pour tout le geste
    setLocal(l => {
      const n = { ...l };
      for (const [id, db] of Object.entries(changes)) n[id] = { ...n[id], db };
      return n;
    });
    const ch = Object.entries(changes);
    ch.filter(([id]) => loopSlot(id) != null).forEach(([id, db]) => postLoop(id, { db }));
    const mx = ch.filter(([id]) => loopSlot(id) == null);
    if (mx.length) post('/api/mixer', { levels: Object.fromEntries(mx.map(([id, db]) => [id, { db }])) }).catch(() => {});
  };
  const toggleMute = (id) => {
    const mute = !(lv[id] || {}).mute;
    setLocal(l => ({ ...l, [id]: { ...l[id], mute } }));
    if (loopSlot(id) != null) postLoop(id, { mute });
    else post('/api/mixer', { source: id, mute }).catch(() => {});
  };
  const toggleLink = (id) => setSel(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]);

  // ≥ 2 pour coupler : une case cochée seule est « armée », son fader reste un fader normal
  const modeFor = (id) => (group.length >= 2 && linked(id)) ? 'group' : 'solo';
  const startFor = (id) => (tapDb) => {
    if (modeFor(id) !== 'group') { gesture.current = null; return; }
    gesture.current = { ids: [...group], base: Object.fromEntries(group.map(s => [s, dbOf(s)])), first: tapDb };
  };
  const changeFor = (id) => (db) => {
    const g = gesture.current;
    if (!g) { postOne(id, db); return; }
    const bases = g.ids.map(s => g.base[s]);
    // ⚠ borner le DELTA (pas les membres) : le groupe touche le mur d'un seul bloc, les écarts
    // survivent. Clamper membre par membre les écraserait dès qu'un seul sature.
    const delta = Math.max(DB_MIN - Math.min(...bases),
                  Math.min(DB_MAX - Math.max(...bases), db - g.first));
    postGroup(Object.fromEntries(g.ids.map(s => [s, clampDb(g.base[s] + delta)])));
  };

  const main = (data.destinations || []).find(d => !d.virtual);
  const recording = !!(st.perf && (st.perf.recording || st.perf.state === 'rec'));

  return html`<div class="lmx">
    <section class="card-panel lmx-head">
      <b>Mixer</b>
      <span class="lmx-dest">→ ${main ? esc(main.label + (main.role ? ' · ' + main.role : '')) : 'the outputs'}</span>
      <span class="lmx-spacer" />
      <span class=${cls('lmx-rec', recording && 'on')}
        title="The recording mix follows these levels — DIs stay raw.">● rec mix follows</span>
      <button class="chip" onClick=${onClose}>Done</button>
    </section>
    <section class="card-panel lmx-strips">
      ${data.sources.map((s, i) => {
        const v = lv[s.id] || {};
        const on = linked(s.id);
        // la barre de liaison ne s'allume qu'à partir de DEUX : cochée seule = armée, pas couplée
        const prev = i > 0 && linked(data.sources[i - 1].id) && group.length >= 2;
        const next = i < data.sources.length - 1 && linked(data.sources[i + 1].id) && group.length >= 2;
        const meter = st.levels ? (st.levels[s.id] ?? (s.role ? st.levels[s.role] : null) ?? null) : null;   // par entrée (in1, in2…), repli par rôle
        return html`<div class=${cls('lmx-strip', !s.present && 'off', s.kind === 'loop' && 'lmx-loop')}
          title=${s.present ? '' : 'not in this preset — the level is kept and will apply when it is'}>
          <i>${esc(s.label)}</i><small>${esc(s.sub || '')}</small>
          <div class="lmx-body">
            <${Fader} db=${v.db ?? 0} disabled=${!s.present} mode=${modeFor(s.id)}
              onStart=${startFor(s.id)} onChange=${changeFor(s.id)} />
            ${/* la gouttière est RÉSERVÉE sur les 8 même sans mesure : sinon les knobs des
                  tranches qui en ont une ne sont pas sur la même verticale que les autres, et
                  8 knobs désalignés, ça se voit avant tout le reste */''}
            <div class=${cls('lmx-meter', meter == null && 'ghost')}>
              <div style=${`height:${Math.round((meter || 0) * 100)}%`} /></div>
          </div>
          <button class=${cls('lmx-link', on && 'on', prev && 'l', next && 'r')}
            disabled=${!s.present}
            title=${on ? 'linked — drag any linked fader, they all move together'
                       : 'link this strip: check two or more, then drag one fader'}
            aria-pressed=${on ? 'true' : 'false'}
            onClick=${() => s.present && toggleLink(s.id)}>
            <em /><b>${fmt(v.db ?? 0)}</b>
          </button>
          <button class=${cls('lmx-mute', v.mute && 'on')} disabled=${!s.present}
            onClick=${() => toggleMute(s.id)}>${v.mute ? 'MUTED' : 'MUTE'}</button>
        </div>`;
      })}
    </section>
    <section class="card-panel lmx-foot">
      <span class="muted">⚠ Trim <b>attenuates</b> — 0 dB is unity, there is no boost. It composes with
        the scene level and the volume pedal, it replaces neither.</span>
    </section>
  </div>`;
}

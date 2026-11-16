// SPDX-License-Identifier: GPL-3.0-or-later
// LE BUDGET CPU À L'ÉCRAN (docs/cpu-budget.md, lots 2-4) : les lectures de /api/cpu/* et les morceaux d'interface
// partagés — la barre contre UN cœur, la puce de verdict, la feuille des correctifs, la puce de scène. Ce qu'on affiche
// se décide dans cpu-budget-model.mjs (testé) ; ici on va chercher et on dessine.
//
// ⚠ SE TAIRE PLUTÔT QUE CASSER : le lot 1 (les routes du bridge) peut manquer — un bridge plus ancien, un profil vide.
// Une route absente (404 « Not Found » de FastAPI) éteint TOUTES les lectures de cette page jusqu'au rechargement, sans
// bandeau ni erreur ; une réponse vide dit « not measured ». Rien ici ne lève : un écran de scène ne tombe pas pour ça.
import { html, useState, useEffect, cls, esc, go, post } from './lib.js';
import {
  levelOf, verdictOf, colorOf, fmtPct, fmtCores, barWidth, verdictChip, sceneLine, blockChips, heaviestLine, laneLabel,
  gainText, gainLevel, fixButton, fixesFor, machineLine, budgetLine, stageChip, nextChip, blockQuery, blockKey, VERDICT_LONG, afterAdd,
} from './cpu-budget-model.mjs';

export { levelOf, colorOf, fmtPct, stageChip, nextChip };
export { laneAlerts } from './cpu-budget-model.mjs';

// ── LES LECTURES ────────────────────────────────────────────────────────────────────────────────────────────────
let _missing = false;                    // une route /api/cpu/* n'existe pas sur ce bridge : on ne redemande plus
export const cpuMissing = () => _missing;

/** GET d'une route /api/cpu/… → le JSON, ou null (absente, refusée, bridge muet) — ne lève jamais */
export async function cpuGet(path) {
  if (_missing) return null;
  try {
    const r = await fetch(path);
    if (r.ok) return await r.json();
    if (r.status === 404) {
      // la route elle-même manque (FastAPI : {"detail": "Not Found"}) ≠ un preset inconnu de la route
      const b = await r.json().catch(() => null);
      if (!b || b.detail === 'Not Found') _missing = true;
    }
    return null;
  } catch (e) { return null; }
}

/** une lecture qui suit ses dépendances ; `path` null = ne rien demander. undefined = en cours, null = rien */
export function useCpu(path, deps = []) {
  const [data, setData] = useState(undefined);
  useEffect(() => {
    if (!path) { setData(null); return; }
    let live = true;
    cpuGet(path).then(d => { if (live) setData(d); });
    return () => { live = false; };
  }, [path, ...deps]);
  return data;
}

/** l'estimation d'un preset (`sandbox` = le brouillon du Designer) */
export const useCpuEstimate = (preset, deps = []) =>
  useCpu(preset ? '/api/cpu/estimate?preset=' + encodeURIComponent(preset) : null, deps);

/** les verdicts de plusieurs presets d'un coup (setlist, /live, Companion) : {id: {verdict, worst}} */
export function useCpuMany(ids, deps = []) {
  const list = [...new Set((ids || []).filter(Boolean))];
  const key = list.join(',');
  const d = useCpu(list.length ? '/api/cpu/estimate-many?ids=' + list.map(encodeURIComponent).join(',') : null, [key, ...deps]);
  return d && typeof d === 'object' ? d : {};
}

// le coût d'un bloc (GET /api/cpu/block) : mis en cache le temps de la page, une minute — une calibration qui finit
// se voit au prochain passage
const _blocks = new Map();
export function cpuBlock(type, variant, stereo) {
  const k = blockKey(type, variant, stereo);
  const hit = _blocks.get(k);
  if (hit && Date.now() - hit.t < 60000) return hit.p;
  const p = cpuGet(blockQuery(type, variant, stereo));
  _blocks.set(k, { t: Date.now(), p });
  return p;
}
/** les coûts de plusieurs blocs : specs = [{type, variant?, stereo?}] → {clé: réponse|null} */
export function useCpuBlocks(specs) {
  const list = (specs || []).filter(s => s && s.type);
  const key = list.map(s => blockKey(s.type, s.variant, s.stereo)).join(',');
  const [map, setMap] = useState({});
  useEffect(() => {
    if (!list.length || _missing) { setMap({}); return; }
    let live = true;
    Promise.all(list.map(s => cpuBlock(s.type, s.variant, s.stereo).then(c => [blockKey(s.type, s.variant, s.stereo), c])))
      .then(rows => { if (live) setMap(Object.fromEntries(rows)); });
    return () => { live = false; };
  }, [key]);
  return map;
}

// ── LES MORCEAUX D'INTERFACE ─────────────────────────────────────────────────────────────────────────────────────
/** la barre d'une lane contre UN cœur : remplie à sa couleur, repères à 60 et 80 % */
export function CpuBar({ pct, big, thin }) {
  const lv = levelOf(pct);
  return html`<span class=${cls('cpu-bar', big && 'big', thin && 'thin')}>
    <i class="cpu-fill" style=${'width:' + barWidth(pct) + '%;background:' + colorOf(lv)}></i>
    <i class="cpu-tick" style="left:60%"></i><i class="cpu-tick" style="left:80%"></i></span>`;
}

const ChipIcon = () => html`<svg class="cpu-ic" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
  <rect x="2" y="2" width="10" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"></rect>
  <rect x="5" y="5" width="4" height="4" fill="currentColor"></rect></svg>`;

/** la puce de verdict d'un preset (en-tête du Designer) ; rien sans estimation */
export function VerdictChip({ est, onClick, compact }) {
  const v = verdictChip(est);
  if (!v) return '';
  const c = fmtCores(est.cores, est.total_cores);
  // compacte (la rangée de titre de la chaîne, partagée avec la bande de stomps) : « Tight · Guitar 78 % », les cœurs
  // passent dans la feuille
  const text = compact ? v.text.replace(' · lane ', ' · ') : v.text;
  return html`<button class=${'cpu-chip lv-' + v.level} data-doc="designer.cpu" onClick=${onClick}
    title=${'CPU budget on this golem: the busiest lane in its heaviest scene' + (c ? ' (' + c + ' in all)' : '') + ' — tap for every lane and what to do'}>
    <${ChipIcon} /><span class="cpu-chip-tx"><b>${text}</b>${c && !compact ? html`<small>${c}</small>` : ''}</span></button>`;
}

/** la puce de scène (/live, Companion) : seulement quand c'est tendu ou rouge, jamais un chiffre */
export function StageChip({ entry, onOpen, next, still, short }) {
  const c = next ? nextChip(entry) : stageChip(entry);
  if (!c) return '';
  // `short` : une liste étroite (setlist, presets) — « CPU » à la couleur du verdict, le texte entier en titre
  const text = short ? 'CPU' : c.text;
  const k = cls('cpu-stage', 'lv-' + c.level, next && 'next', short && 'short');
  // `still` : dans une ligne qui est déjà un bouton (setlist) — un bouton dans un bouton n'est pas du HTML ; une étiquette
  if (still) return html`<span class=${k} title=${c.text + ' on this golem — open the preset for what to do'}>${text}</span>`;
  return html`<button class=${k} onClick=${e => { e.stopPropagation(); onOpen && onOpen(); }}
    title=${(short ? c.text + ' — ' : '') + 'tap: what weighs, and what golem proposes'}>${next ? '' : html`<${ChipIcon} />`}${text}</button>`;
}

// ── LA FEUILLE (maquettes Main + Fix) ─────────────────────────────────────────────────────────────────────────────
/** toutes les lanes contre un cœur, puis une lane et ses correctifs. `stage` = lecture seule (/live, Companion).
 *  `can` = les gestes de l'écran appelant ; `onAction(fix)` les fait ; perf-mode et buffer sont faits ici. */
export function CpuSheet({ est, title, sceneIds, sceneId, lane: lane0, stage, can, onAction, onChanged, onClose }) {
  const [laneId, setLaneId] = useState(lane0 || null);
  const [busy, setBusy] = useState({});
  const [done, setDone] = useState({});
  const close = html`<button class="cpu-x" aria-label="Close" onClick=${onClose}>▾</button>`;
  const scrim = body => html`<div class="cpu-scrim" onClick=${e => e.target === e.currentTarget && onClose()}>
    <div class=${cls('cpu-sheet', stage && 'stage')} data-doc="cpu.sheet">${body}</div></div>`;
  if (!est) return scrim(html`<div class="cpu-hd"><b>${esc(title || 'CPU budget')}</b><span class="grow"></span>${close}</div>
    <p class="cpu-empty">Not measured on this golem yet. golem measures each block when the rack is idle, after an install or an update.</p>`);
  const lanes = (est.lanes || []).filter(Boolean);
  const L = laneId ? lanes.find(x => x.id === laneId) : null;
  const act = async (fix, b) => {
    if (b.kind === 'buffer') { onClose(); go('system/sys'); return; }
    setBusy(s => ({ ...s, [fix.id]: true }));
    try {
      if (b.kind === 'perf-mode') {
        const r = await post('/api/perf-mode', { on: true }).catch(() => null);
        setDone(s => ({ ...s, [fix.id]: r && r.ok === false ? 'failed' : 'done' }));
      } else if (onAction) {
        const r = await onAction(fix, b);
        if (r !== false) setDone(s => ({ ...s, [fix.id]: 'done' }));
        if (r === 'close') { onClose(); return; }
      }
      onChanged && onChanged();
    } finally { setBusy(s => ({ ...s, [fix.id]: false })); }
  };
  const foot = html`<div class="cpu-ft">${esc(machineLine(est))}${L ? '. An estimate with a margin: other programs and heat can still make a lane crackle.' : ''}</div>`;

  if (L) {                                         // UNE LANE (maquette Fix)
    const lv = levelOf(L.pct);
    const scene = L.worst_scene || (est.worst && est.worst.lane === L.id ? est.worst.scene : null);
    const fixes = fixesFor(est, L.id);
    const heavy = heaviestLine(L, scene);
    const unmeasured = (L.blocks || []).filter(b => b && b.measured === false).map(b => b.label || b.type || b.id);
    return scrim(html`
      <div class="cpu-hd">${lanes.length > 1 ? html`<button class="cpu-back" onClick=${() => setLaneId(null)}>‹ All lanes</button>` : ''}
        <b>Lane ${esc(L.name || L.id)}${scene ? ' · scene ' + esc(scene) : ''}</b>
        <span class=${'cpu-verdict lv-' + lv}>${lv === 'unknown' ? 'not measured' : fmtPct(L.pct) + ' of a core — ' + VERDICT_LONG[lv]}</span>
        <span class="grow"></span>${close}</div>
      <${CpuBar} pct=${L.pct} big />
      ${heavy ? html`<div class="cpu-sub">Heaviest blocks: ${esc(heavy)}</div>` : ''}
      ${unmeasured.length ? html`<div class="cpu-sub">Not measured yet: ${esc(unmeasured.join(', '))}. The figure leaves ${unmeasured.length > 1 ? 'them' : 'it'} out until golem measures ${unmeasured.length > 1 ? 'them' : 'it'}, when the rack is idle.</div>` : ''}
      ${fixes.length ? html`<div class="cpu-cap">${stage ? 'What golem proposes, cheapest first' : 'What golem can do, cheapest first'}</div>
        <div class="cpu-fixes">${fixes.map((f, i) => { const b = fixButton(f, { stage, can });
          return html`<div class="cpu-fix">
            <span class="cpu-n">${i + 1}</span>
            <span class="cpu-fix-tx"><b>${esc(f.title)}</b>${f.sub ? html`<small>${esc(f.sub)}</small>` : ''}</span>
            ${gainText(f) ? html`<b class=${'cpu-gain lv-' + gainLevel(f)}>${gainText(f)}</b>` : ''}
            ${b ? html`<button class=${cls('cpu-act', b.primary && 'primary', done[f.id] && 'done')} disabled=${busy[f.id] || done[f.id] === 'done'}
              onClick=${() => act(f, b)}>${busy[f.id] ? '…' : done[f.id] === 'done' ? '✓ done' : done[f.id] === 'failed' ? 'Retry' : b.label}</button>` : ''}
          </div>`; })}</div>`
        : html`<p class="cpu-empty">${lv === 'ok' ? 'This lane has room on its core.' : lv === 'unknown' ? 'A block of this lane is not measured yet: golem measures it when the rack is idle.' : 'golem has nothing to propose for this lane yet.'}</p>`}
      <span class="grow"></span>${foot}`);
  }

  const v = verdictChip(est);                      // TOUTES LES LANES (maquette Main)
  const ids = sceneIds && sceneIds.length ? sceneIds : null;
  return scrim(html`
    <div class="cpu-hd"><b>${esc(title || 'CPU budget')}</b>
      ${v ? html`<span class=${'cpu-chip ro lv-' + v.level}><${ChipIcon} /><span class="cpu-chip-tx"><b>${v.text}</b></span></span>` : ''}
      <small class="cpu-cores">${fmtCores(est.cores, est.total_cores)}</small>
      <span class="grow"></span>${close}</div>
    <div class=${cls('cpu-lanes', lanes.length > 4 && 'dense')}>${lanes.map(x => { const lv = levelOf(x.pct);
      const chips = blockChips(x, sceneId);
      return html`<button class=${cls('cpu-lane', 'lv-' + lv)} onClick=${() => setLaneId(x.id)}
        title=${lv === 'tight' || lv === 'red' ? 'tap: what golem proposes for this lane' : 'tap: this lane in detail'}>
        <span class="cpu-lane-row"><b class="cpu-lane-nm">${esc(x.name || x.id)}</b><${CpuBar} pct=${x.pct} />
          <b class=${'cpu-pct lv-' + lv}>${fmtPct(x.pct)}</b><small class="cpu-scn">${esc(sceneLine(x, ids))}</small>
          <span class="cpu-more">${lv === 'tight' || lv === 'red' ? 'Fixes ›' : '›'}</span></span>
        ${chips.length ? html`<span class="cpu-blocks">${chips.map(c => html`<span class=${cls('cpu-blk', c.off && 'off')}
          title=${c.off ? 'off in this scene: it costs (almost) nothing here' : ''}>${esc(c.label)} <em>${c.cost}</em></span>`)}</span>` : ''}
      </button>`; })}
      ${!lanes.length ? html`<p class="cpu-empty">${est.verdict === 'unknown' || !est.machine || !est.machine.cpu
        ? 'Not measured on this golem yet. golem measures each block when the rack is idle, after an install or an update.'
        : 'No lane to measure in this preset.'}</p>` : ''}</div>
    <div class="cpu-ft"><span>${esc(budgetLine(est))} Ticks: 60 % and 80 %.</span><span class="grow"></span><span>${esc(machineLine(est))}</span></div>`);
}

/** la feuille d'un preset joué (sur scène) : l'estimation se lit à l'ouverture — lecture seule */
export function StageCpuSheet({ preset, title, onClose, stage = true }) {
  const est = useCpuEstimate(preset);
  const worst = est && est.worst && est.worst.lane;
  if (est === undefined) return html`<div class="cpu-scrim" onClick=${onClose}><div class="cpu-sheet stage"><p class="cpu-empty">…</p></div></div>`;
  return html`<${CpuSheet} est=${est} title=${title} lane=${worst} stage=${stage} onClose=${onClose} />`;
}
/** la même hors scène (Songs ▸ Presets) : perf-mode et buffer ont leur bouton ; les gestes du Designer restent une phrase
 *  (le preset n'y est pas ouvert) */
export const PresetCpuSheet = props => html`<${StageCpuSheet} ...${props} stage=${false} />`;

// ── LA LIBRARY (lot 3) ───────────────────────────────────────────────────────────────────────────────────────────
/** la lane avant → après le remplacement de la capture d'un bloc (GET /api/cpu/swap) */
export function swapPath(preset, block, ref, model) {
  if (!preset || !block || ref == null) return null;
  const q = new URLSearchParams({ preset, block, ref: String(ref) });
  if (model != null && model !== '') q.set('model', String(model));
  return '/api/cpu/swap?' + q.toString();
}

/** « Add to… » : où irait chaque lane d'un preset si la capture y entrait — {laneId: pct|null}. Un bloc du même type
 *  dans la lane = la capture le REMPLACE (swap) ; sinon elle s'ajoute (la lane dans sa scène la plus lourde + le coût du
 *  bloc). `doc` = le document du preset (ses lanes et leurs chaînes) ; `item` = {type, ref, model, variant}. */
export async function lanesAfter(preset, doc, item) {
  const out = {};
  if (!preset || !doc || !item || !item.type || _missing) return out;
  const lanes = (doc.lanes || []).filter(Boolean);
  const blocksOf = L => { const c = L.chain || {};
    return [...(c.pre || []), ...((c.split && c.split.branches) || []).flatMap(b => b.blocks || []), ...(c.post || [])].filter(Boolean); };
  let est;
  for (const L of lanes) {
    const same = blocksOf(L).find(b => b.type === item.type && b.id);
    if (same) {
      const sw = await cpuGet(swapPath(preset, same.id, item.ref, item.model));
      out[L.id] = sw && typeof sw.after_pct === 'number' ? sw.after_pct : null;
      continue;
    }
    if (est === undefined) est = await cpuGet('/api/cpu/estimate?preset=' + encodeURIComponent(preset));
    const el = est && (est.lanes || []).find(x => x.id === L.id);
    const cost = await cpuBlock(item.type, item.variant, !!L.stereo);
    const a = el ? afterAdd(el.pct, cost) : null;
    out[L.id] = a ? a.pct : null;
  }
  return out;
}

/** le coût d'un bloc, en clair (« ≈ 9 % of a core ») — utilisé par la feuille de bloc */
export { blockCostLine, captureCostLabel, rangeLine, afterAdd, swapView, swapHint, addLaneState, namArch, namVariant, costPct, laneLabel, verdictOf, blockLevel } from './cpu-budget-model.mjs';

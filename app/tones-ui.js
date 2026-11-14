// SPDX-License-Identifier: GPL-3.0-or-later
// LIBRARY ▸ TONES, LES BRIQUES COMMUNES (docs/library-tones.md) : les quatre onglets (Amps, Pedals, Cabs, Outboard)
// montrent chaque capture DESSINÉE par les visuels de golem-fx (têtes, stacks, pédales NAM, baffles, unités rack),
// paginée (l'écran ne défile jamais), et une fiche où toucher une capture la fait ENTENDRE dans le patch qui joue
// (POST /api/library/audition, bridge/audition.py). Ici : le chargement des visuels, le dessin dans un cadre, la
// pagination, la lecture des NOMS de captures (micro, gain, potards, position du micro, taille du baffle) et l'écoute.
import { html, useState, useEffect, useRef, cls, api, post } from './lib.js';
import { loadVisuals, visualsReady } from './golem-visuals.js';
import { hydrateBlockMeta } from './designer-model.js';

/** true quand les moteurs de dessin de golem-fx sont chargés (une fois par page). */
export function useVisuals(effects) {
  const [ok, setOk] = useState(visualsReady());
  useEffect(() => { if (!ok) loadVisuals(effects || undefined).then(() => setOk(true)).catch(() => {}); }, []);
  // les types que golem-fx JOUE ici (/api/effects `golem_fx`) : sans eux, une pédale golem-fx se dessine en émail
  // générique (golem-visuals.js pedalFor) — le Designer les hydrate, la Library doit le faire aussi
  useEffect(() => { if (effects && effects.effects) hydrateBlockMeta(effects.effects, effects); }, [effects]);
  useEffect(() => { if (ok && effects) loadVisuals(effects); }, [ok, effects]);
  return ok;
}
export const GP = () => (typeof window !== 'undefined' && window.GolemPedals) || null;

// un SVG de golem-fx (chaîne) remplit son cadre, posé sur le bas (un ampli repose sur le sol)
const fitted = (svg, align) => String(svg || '').replace(/^<svg([^>]*?) width="[\d.]+"/, `<svg$1 width="100%" height="100%" preserveAspectRatio="${align || 'xMidYMax'} meet"`);
export const Drawing = ({ svg, cls: c, align }) => html`<div class=${cls('tn-draw', c)} aria-hidden="true"
  dangerouslySetInnerHTML=${{ __html: fitted(svg, align) }}></div>`;

// ── les dessins, par nature de capture ──────────────────────────────────────────────────────────────────────────
export const AMP_FAMILIES = [['clean', 'Clean', '#d9c9a0'], ['crunch', 'Crunch', '#c9873a'], ['high-gain', 'High gain', '#ff4136'], ['bass', 'Bass', '#1ab7b0']];
const shortTitle = (s, n = 10) => String(s || '').replace(/[^\w ]+/g, ' ').trim().split(/\s+/).slice(0, 2).join(' ').slice(0, n);
export const ampSvg = (t, arch, family) => {
  const P = GP(); if (!P) return '';
  const o = { family, title: (arch && arch.short) || shortTitle(String(t.amp || t.title || '').replace(new RegExp('^' + String(t.brand || '').split('/')[0] + '\\s*', 'i'), '')) };
  return t.gear === 'amp' ? P.namHead(o) : P.namStack(o);
};
export const namPedalSvg = (arch, title, family, on) => {
  const P = GP(); if (!P) return '';
  return P.namPedal('pedal-nam', { archetype: arch || { family: family || 'overdrive' }, title, on });
};
export const cabSvg = (c, ring) => {
  const P = GP(); if (!P) return '';
  let s = P.namCab({ family: c.look, size: c.size, title: c.title });
  if (ring) {                                     // le haut-parleur où était le micro, entouré
    const L = P.cabLayout(c.size), iw = L.w - 18, ih = L.h - 18, r = Math.min(iw / L.cols, ih / L.rows) * .42;
    const [i, j] = ring;
    s = s.replace(/<\/svg>\s*$/, `<circle cx="${9 + iw * (i + .5) / L.cols}" cy="${9 + ih * (j + .5) / L.rows}" r="${r + 3}" fill="none" stroke="#2ecc71" stroke-width="3" stroke-dasharray="6 4"/></svg>`);
  }
  return s;
};
export const rackSvg = (label, setting, on, extra) => {
  const P = GP(); if (!P || !P.namRack) return '';
  // `extra` : { format: 'ir', program } pour une unité d'IR (golem-fx dessine sa variante IR quand il la connaît)
  return P.namRack(Object.assign({ label, title: label, setting: setting || undefined, on: on !== false }, extra || {}));
};
/** les PROGRAMMES d'un pack d'IR (docs/library-tones.md §8) : ses fichiers regroupés par nom sans leur numéro
 *  (« delay 1…10 », « reverb 1…3 ») : [[nom du groupe, [{n, m}]]] dans l'ordre du pack */
export function irPrograms(models) {
  const groups = [];
  for (const m of models || []) {
    const name = String(m.name || '').trim();
    const k = /^(.*?)[\s_-]*(\d+)$/.exec(name);
    const g = k ? k[1].trim() || 'Program' : name, n = k ? k[2] : '·';
    let row = groups.find(x => x[0].toLowerCase() === g.toLowerCase());
    if (!row) { row = [g, []]; groups.push(row); }
    row[1].push({ n, m });
  }
  for (const row of groups) row[1].sort((a, b) => (+a.n || 0) - (+b.n || 0));
  return groups;
}

// ── ce qu'un NOM de capture dit (seulement quand le créateur l'a écrit) ─────────────────────────────────────────
const MIC = /(sm ?-?57|sm ?58|sm7b|akg ?414|c414|r-?121|u67|md ?421|e ?906|origin|ra-1142)/ig;
/** étiquettes d'une capture d'ampli : micro, gain, canal (3 au plus). [[classe, texte]] */
export function captureTags(name) {
  const n = String(name || ''), t = [];
  [...new Set((n.match(MIC) || []).map(m => m.replace(/[\s-]/g, '').toUpperCase()))].forEach(m => t.push(['mic', m]));
  const g = /(?:\bG|\bgain\s?)(\d+(?:\.\d)?)\b/i.exec(n); if (g) t.push(['gain', 'Gain ' + g[1]]);
  const ch = /\b(clean(?:est)?|crunch|lead|rhythm|red|blue|boost(?:ed)?|cranked|crancked)\b/i.exec(n);
  if (ch) t.push(['ch', ch[1][0].toUpperCase() + ch[1].slice(1).toLowerCase()]);
  return t.slice(0, 3);
}
const KNOB = { drive: 'Drive', gain: 'Gain', tone: 'Tone', level: 'Level', sustain: 'Sustain', attack: 'Attack', volume: 'Volume',
  bass: 'Bass', treble: 'Treble', mid: 'Mid', g: 'Gain', t: 'Tone', b: 'Bass', l: 'Level' };
/** les potards d'une capture de pédale, lus dans son nom (« Drive 7 Tone 6 Level 9 », « L8 B7 T5 G10 ») :
 *  [[nom, valeur 0..10]] — vide si moins de deux potards sont écrits (un nombre seul ne dit rien). */
export function knobsOf(name) {
  const out = [], re = /\b(drive|gain|tone|level|sustain|attack|volume|bass|treble|mid|g|t|b|l)\s?(\d{1,2}(?:\.\d)?)\b/ig;
  let m;
  while ((m = re.exec(String(name || '')))) {
    const k = KNOB[m[1].toLowerCase()], v = +m[2];
    if (v <= 10 && !out.some(o => o[0] === k)) out.push([k, v]);
  }
  return out.length >= 2 ? out.slice(0, 4) : [];
}
/** la position du micro d'une IR, lue dans son nom : {r (0 = centre, 1 = bord), label, dist, off, spk} ou null */
export function micPos(name) {
  const n = String(name || ''), s = n.toLowerCase();
  let r = null, label = null;
  const inch = /(\d+(?:\.\d+)?)\s?in\b/.exec(s), cm = /(\d+(?:\.\d+)?)\s?cm\b/.exec(s);
  if (/cap[\s-]?edge/.test(s)) { r = .3; label = 'Cap edge'; }
  else if (/\bcap\b|\bcnt\b|center|centre/.test(s)) { r = .05; label = 'Center'; }
  else if (/\bmid\b/.test(s)) { r = .55; label = 'Mid cone'; }
  else if (/\bedge\b/.test(s)) { r = .85; label = 'Edge'; }
  else if (inch) { r = Math.min(.95, +inch[1] / 6); label = inch[1] + ' in from center'; }
  if (r == null) return null;
  const spk = /\b(UL|UR|LL|LR)\b/.exec(n);
  return { r, label, dist: cm ? cm[1] + ' cm' : null, off: /45\s?°|off.?axis/i.test(n), spk: spk ? spk[1] : null };
}
export const micOf = name => ((String(name || '').match(MIC) || [''])[0]).replace(/[\s-]/g, '').toUpperCase();
/** la taille d'un baffle (« 4x12 »), lue dans son nom puis dans ses IR (« 412 Mesa » compte) ; null si rien */
export function cabSize(t) {
  const norm = s => String(s || '').replace(/\b412\b/, '4x12').replace(/\b212\b/, '2x12').replace(/\b112\b/, '1x12');
  for (const s of [t.amp || t.title, ...(t.makes || []), ...((t.models || []).map(m => m.name))]) {
    const m = /(\d)\s*x\s*(\d{2})/i.exec(norm(s));
    if (m) return `${m[1]}x${m[2]}`;
  }
  return null;
}

// ── la pagination (l'écran ne défile jamais) ────────────────────────────────────────────────────────────────────
export function usePage(n, per, deps) {
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), deps || []);
  const pages = Math.max(1, Math.ceil(n / per));
  const p = Math.min(page, pages - 1);
  return { page: p, pages, from: p * per, to: p * per + per, set: setPage };
}
export const Pager = ({ pg }) => pg.pages <= 1 ? html`<div class="tn-pager"></div>` : html`<div class="tn-pager">
  <button class="mini" disabled=${!pg.page} onClick=${() => pg.set(pg.page - 1)} aria-label="previous page">‹</button>
  ${Array.from({ length: Math.min(pg.pages, 12) }, (_, i) => html`<i class=${i === pg.page ? 'on' : ''}></i>`)}
  <span>${pg.page + 1} / ${pg.pages}</span>
  <button class="mini" disabled=${pg.page >= pg.pages - 1} onClick=${() => pg.set(pg.page + 1)} aria-label="next page">›</button></div>`;

// ── ÉCOUTER (docs/library-tones.md §4) ───────────────────────────────────────────────────────────────────────────
// Une écoute à la fois ; quitter la fiche (ou la page) rend le patch tel qu'il était.
const NOTE = { no_cab: 'No cab after this amp in the patch: you hear the head alone.',
  amp_has_cab: 'The amp in the patch already has its cab: you hear two cabs.' };
export function useAudition() {
  const [st, setSt] = useState({ on: false, ref: null, model: null, busy: false, err: '', notes: [] });
  const live = useRef(false);
  useEffect(() => () => { if (live.current) post('/api/library/audition/stop', {}).catch(() => {}); }, []);
  const play = async (ref, model) => {
    if (st.busy) return;
    if (st.on && String(st.ref) === String(ref) && String(st.model) === String(model)) return stop();
    setSt(s => ({ ...s, busy: true, err: '', ref: String(ref), model: String(model) }));
    try {
      const r = await post('/api/library/audition', { ref, model });
      live.current = true;
      setSt({ on: true, ref: String(ref), model: String(model), busy: false, err: '', notes: ((r.info || {}).notes || []).map(k => NOTE[k] || k) });
    } catch (e) {
      setSt({ on: false, ref: null, model: null, busy: false, err: (e.body && e.body.error) || 'Could not reach golem: the capture was not played.', notes: [] });
    }
  };
  const stop = async () => {
    live.current = false;
    setSt({ on: false, ref: null, model: null, busy: true, err: '', notes: [] });
    await post('/api/library/audition/stop', {}).catch(() => {});
    setSt(s => ({ ...s, busy: false }));
  };
  const playing = (ref, model) => st.on && String(st.ref) === String(ref) && String(st.model) === String(model);
  const loading = (ref, model) => st.busy && String(st.ref) === String(ref) && String(st.model) === String(model);
  return { st, play, stop, playing, loading };
}
/** l'indicateur d'une ligne : ▶ à l'arrêt, « … » pendant l'émission, l'égaliseur animé quand elle joue */
export const PlayMark = ({ on, busy }) => html`<span class="tn-play">${busy ? '…' : on ? html`<b class="tn-eq"><i></i><i></i><i></i></b>` : '▶'}</span>`;
export const AuditionNote = ({ au }) => au.st.err ? html`<div class="tn-note ko">${au.st.err}</div>`
  : au.st.notes.length ? html`<div class="tn-note">${au.st.notes.join(' ')}</div>`
  : au.st.on ? html`<div class="tn-note on">Playing in the patch that is loaded. Nothing is saved.<button class="mini" onClick=${au.stop}>Stop</button></div>`
  : html`<div class="tn-note muted">Tap a capture to hear it in the patch that is loaded. Nothing is saved.</div>`;

// ── ouvrir une fiche d'un autre onglet (« Pairs with » d'un ampli ouvre le baffle) ─────────────────────────────
let _open = null;
export const openLater = (kind, id) => { _open = { kind, id: String(id) }; };
export const takeOpen = kind => { if (_open && _open.kind === kind) { const id = _open.id; _open = null; return id; } return null; };

/** un potard dessiné (pédale : la position écrite dans le nom de la capture) */
export function knobsSvg(knobs, color) {
  const w = 110;
  const one = ([label, v], i) => {
    const cx = 55 + i * w, cy = 52, r = 28, a = -135 + 270 * Math.max(0, Math.min(1, v / 10)), rad = (a - 90) * Math.PI / 180;
    const ticks = Array.from({ length: 11 }, (_, k) => { const b = (-135 + 27 * k - 90) * Math.PI / 180;
      return `<line x1="${cx + Math.cos(b) * (r + 4)}" y1="${cy + Math.sin(b) * (r + 4)}" x2="${cx + Math.cos(b) * (r + 8)}" y2="${cy + Math.sin(b) * (r + 8)}" stroke="#8a94a3" stroke-width="${k % 5 ? 1 : 2}"/>`; }).join('');
    return `<g>${ticks}<circle cx="${cx}" cy="${cy + 2}" r="${r}" fill="#000" opacity=".4"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob)" stroke="#000" stroke-opacity=".5"/>
      <line x1="${cx}" y1="${cy}" x2="${cx + Math.cos(rad) * r * .85}" y2="${cy + Math.sin(rad) * r * .85}" stroke="${color || '#ffb03a'}" stroke-width="3" stroke-linecap="round"/>
      <text x="${cx}" y="${cy + r + 22}" text-anchor="middle" class="tn-kl">${String(label).toUpperCase()}</text><text x="${cx}" y="${cy + r + 38}" text-anchor="middle" class="tn-kv">${v}</text></g>`;
  };
  return `<svg viewBox="0 0 ${knobs.length * w} 136" width="100%" role="img" aria-label="${knobs.map(k => k.join(' ')).join(', ')}">${knobs.map(one).join('')}</svg>`;
}
export { api };

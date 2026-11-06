// SPDX-License-Identifier: GPL-3.0-or-later
// Blocs graphiques des tiroirs v2 (docs/archive/block-sheets.md, réf. docs/QC UI/) — le design system
// des feuilles de réglages : PCell (la cellule QC : label / valeur+unité / contrôle à droite),
// PDial (potard SVG à arc coloré), PToggle. Purement PRÉSENTATION : la mécanique scene-first
// (val/onParam/override) reste dans ParamSheet — ces widgets reçoivent tout en props.
import { html, useState, useEffect, useRef, cls, esc } from './lib.js';

// ── PDial : le potard seul (drag vertical + molette, double-tap = reset base/défaut) ──
// Arc SVG -135°..+135°, couleur = var(--tc) (catégorie du bloc, posée par la feuille).
export function PDial({ value, min, max, onChange, size = 52, decimals = 2 }) {
  const [drag, setDrag] = useState(false);
  const st = useRef({ y: 0, v: 0 });
  const v = value == null ? min : value;
  const span = (max - min) || 1;
  const factor = 10 ** decimals;
  const norm = Math.max(0, Math.min(1, (v - min) / span));
  useEffect(() => {
    if (!drag) return;
    const mv = e => { const dy = st.current.y - (e.clientY ?? 0);
      const nv = st.current.v + dy / 140 * span;
      onChange(Math.max(min, Math.min(max, Math.round(nv * factor) / factor))); };
    const up = () => setDrag(false);
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    return () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); };
  }, [drag]);
  const wheel = e => { e.preventDefault();
    const step = span / (e.shiftKey ? 400 : 100) * (e.deltaY < 0 ? 1 : -1);
    onChange(Math.max(min, Math.min(max, Math.round((v + step) * factor) / factor))); };
  // arc : cercle r=17, circonférence ~106.8 ; 270° utiles = 80.1 ; rotation pour démarrer à -135°
  const C = 2 * Math.PI * 17, arc = C * 0.75;
  const ang = -135 + norm * 270;
  return html`<svg class=${cls('pdial', drag && 'act')} viewBox="0 0 44 44" width=${size} height=${size}
      onPointerDown=${e => { st.current = { y: e.clientY, v }; setDrag(true); }}
      onDblClick=${() => onChange(null)} onWheel=${wheel}>
    <circle class="pdial-bg" cx="22" cy="22" r="17"
      stroke-dasharray=${arc + ' ' + C} transform="rotate(135 22 22)" />
    <circle class="pdial-arc" cx="22" cy="22" r="17"
      stroke-dasharray=${(arc * norm) + ' ' + C} transform="rotate(135 22 22)" />
    <line class="pdial-pin" x1="22" y1="22" x2="22" y2="8" transform=${`rotate(${ang} 22 22)`} />
    <circle class="pdial-cap" cx="22" cy="22" r="11" />
    <line class="pdial-pin2" x1="22" y1="14" x2="22" y2="11" transform=${`rotate(${ang} 22 22)`} />
  </svg>`;
}

// ── PCell : LA cellule standard (patron tiroirs.jpg) — label en haut, valeur+unité en bas
// à gauche, contrôle à droite. `wide` = cellule double. `off` = param conditionnel inactif
// (depends, patron neural-split-mix2 : visible mais grisé). `extra` = chips EXP / base 🎬. ──
export function PCell({ label, value, unit, sub, wide, off, ovr, base, extra, children, title }) {
  return html`<div class=${cls('pcell', wide && 'x2', off && 'off', ovr && 'ovr')} title=${title || ''}>
    <div class="pcell-top"><span class="pcell-lb">${label}</span>${extra || ''}</div>
    <div class="pcell-body">
      <div class="pcell-vw">
        <div class="pcell-val">${value}${unit ? html`<i>${esc(unit)}</i>` : ''}</div>
        ${sub ? html`<div class="pcell-sub" title=${typeof sub === 'string' ? sub : ''}>${sub}</div>` : ''}
        ${ovr && base != null ? html`<div class="pcell-base" title="base value (inherited by other scenes)">base ${base}</div>` : ''}
      </div>
      <div class="pcell-ctl">${children}</div>
    </div>
  </div>`;
}

// ── PToggle : interrupteur vertical façon QC (Split/Normal, On/Off) ──
export function PToggle({ on, labels = ['On', 'Off'], onChange }) {
  return html`<div class="ptoggle" onClick=${() => onChange(!on)}>
    <span class=${cls('pt-opt', on && 'on')}>${labels[0]}</span>
    <span class=${cls('pt-opt', !on && 'on')}>${labels[1]}</span>
  </div>`;
}

// formatage de la valeur affichée : pm.fmt = décimales imposées ; sinon heuristique (entier
// au-delà de 100, 1 décimale sinon) — les GRANDS chiffres de la référence QC.
export function fmtVal(v, pm) {
  if (v == null || typeof v !== 'number') return v == null ? '—' : String(v);
  if (pm && pm.fmt != null) return v.toFixed(pm.fmt);
  return String(Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 10) / 10);
}

// ── PFader / PFaderBank : jauges verticales façon pédale Boss GE-7 (EQ graphique). Une bande =
// une jauge à zéro CENTRAL (gain ±dB) : remplissage du centre vers la valeur, drag vertical,
// double-tap = reset. La banque = rangée pleine largeur de bandes contiguës (widget:"fader"). ──
export function PFader({ label, value, min, max, ovr, onChange, h }) {
  const [drag, setDrag] = useState(false);
  const st = useRef({ y: 0, v: 0 });
  const v = value == null ? 0 : value;
  const span = (max - min) || 1;
  const norm = Math.max(0, Math.min(1, (v - min) / span));
  useEffect(() => {
    if (!drag) return;
    const H = h || 86;                               // hauteur utile de la piste (px) — DOIT suivre le CSS,
                                                     // sinon le pouce dérive (mixeur batterie : 118)
    const mv = e => { const dy = st.current.y - (e.clientY ?? 0);
      const nv = st.current.v + dy / H * span;
      onChange(Math.max(min, Math.min(max, Math.round(nv * 10) / 10))); };
    const up = () => setDrag(false);
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    return () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); };
  }, [drag]);
  const zero = Math.max(0, Math.min(1, (0 - min) / span));  // position du zéro (fill central)
  const lo = Math.min(norm, zero), hi = Math.max(norm, zero);
  return html`<div class=${cls('pfader', ovr && 'ovr', drag && 'act')}
      onPointerDown=${e => { st.current = { y: e.clientY, v }; setDrag(true); }}
      onDblClick=${() => onChange(null)} title=${label}>
    <span class="pfader-val">${Math.round(v * 10) / 10}</span>
    <div class="pfader-track">
      <span class="pfader-zero" style=${`bottom:${zero * 100}%`}></span>
      <span class="pfader-fill" style=${`bottom:${lo * 100}%; height:${(hi - lo) * 100}%`}></span>
      <span class="pfader-thumb" style=${`bottom:calc(${norm * 100}% - 3px)`}></span>
    </div>
    <span class="pfader-lb">${label}</span>
  </div>`;
}

export function PFaderBank({ items }) {
  return html`<div class="pfbank">
    ${items.map(it => html`<${PFader} label=${it.pm.label || it.pm.name} value=${it.value}
      min=${it.pm.min} max=${it.pm.max} ovr=${it.ovr} onChange=${it.onChange} />`)}
  </div>`;
}

// ── EqCurve : courbe d'EQ paramétrique INTERACTIVE (P3, réf. parametric_eq.png du QC) ──
// Nœuds draggables : HP (x = fréquence, double-tap = on/off), lowshelf/highshelf (y = gain),
// 3 cloches (x = fréquence dans sa plage, y = gain). La réponse tracée est une APPROXIMATION
// visuelle (cloches gaussiennes en log-f, pentes 12 dB/oct) — le son réel vient du x42.
const EQC = { W: 560, H: 150, FMIN: 20, FMAX: 20000, GMAX: 15 };
const efx = f => Math.log10(f / EQC.FMIN) / Math.log10(EQC.FMAX / EQC.FMIN) * EQC.W;
const exf = x => EQC.FMIN * Math.pow(EQC.FMAX / EQC.FMIN, x / EQC.W);
const egy = g => EQC.H / 2 - (g / EQC.GMAX) * (EQC.H / 2 - 8);
const eyg = y => (EQC.H / 2 - y) / (EQC.H / 2 - 8) * EQC.GMAX;

export function EqCurve({ vals, onParam }) {
  const [dragN, setDragN] = useState(null);
  const svgRef = useRef(null);
  const v = id => Number(vals[id] ?? 0);
  const nodes = [
    { id: 'hp', x: efx(Math.max(20, v('lowcut'))), y: egy(0), mode: 'x', fid: 'lowcut',
      fmin: 20, fmax: 250, label: 'HP', off: !vals.lowcut_on },
    { id: 'ls', x: efx(140), y: egy(v('bass')), mode: 'y', gid: 'bass', label: 'LS' },
    { id: 'b1', x: efx(v('f1')), y: egy(v('g1')), mode: 'xy', fid: 'f1', gid: 'g1', fmin: 60, fmax: 600, label: '1' },
    { id: 'b2', x: efx(v('f2')), y: egy(v('g2')), mode: 'xy', fid: 'f2', gid: 'g2', fmin: 200, fmax: 2000, label: '2' },
    { id: 'b3', x: efx(v('f3')), y: egy(v('g3')), mode: 'xy', fid: 'f3', gid: 'g3', fmin: 500, fmax: 8000, label: '3' },
    { id: 'ts', x: efx(6500), y: egy(v('treble')), mode: 'y', gid: 'treble', label: 'HS' },
  ];
  const mag = f => {
    let db = 0;
    if (vals.lowcut_on) { const fc = Math.max(20, v('lowcut')); if (f < fc) db += 12 * Math.log2(f / fc); }
    db += v('bass') / (1 + Math.pow(f / 160, 2));
    for (const [fc, g] of [[v('f1'), v('g1')], [v('f2'), v('g2')], [v('f3'), v('g3')]]) {
      const x = Math.log2(f / Math.max(20, fc));
      db += g * Math.exp(-x * x / 0.72);                       // cloche ~0.6 octave
    }
    db += v('treble') / (1 + Math.pow(5000 / f, 2));
    return Math.max(-EQC.GMAX, Math.min(EQC.GMAX, db));
  };
  let path = '';
  for (let i = 0; i <= 120; i++) {
    const x = i / 120 * EQC.W;
    path += (i ? 'L' : 'M') + x.toFixed(1) + ',' + egy(mag(exf(x))).toFixed(1);
  }
  useEffect(() => {
    if (!dragN) return;
    const n = nodes.find(x => x.id === dragN);
    const mv = e => {
      const r = svgRef.current.getBoundingClientRect();
      const sx = (e.clientX - r.left) / r.width * EQC.W;
      const sy = (e.clientY - r.top) / r.height * EQC.H;
      if (n.mode !== 'y' && n.fid) {
        const f = Math.round(Math.max(n.fmin, Math.min(n.fmax, exf(Math.max(0, Math.min(EQC.W, sx))))));
        onParam(n.fid, f);
      }
      if (n.mode !== 'x' && n.gid) {
        const g = Math.round(Math.max(-12, Math.min(12, eyg(sy))) * 10) / 10;
        onParam(n.gid, g);
      }
    };
    const up = () => setDragN(null);
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    return () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); };
  }, [dragN, vals]);
  // nœuds en HTML absolu PAR-DESSUS le SVG : le viewBox étiré (preserveAspectRatio none)
  // déformait les cercles SVG en ovales — un div rond en px reste rond (remarque 2026-07-23).
  return html`<div ref=${svgRef} class="eqcurve">
    <svg class="eqc-svg" viewBox=${'0 0 ' + EQC.W + ' ' + EQC.H} preserveAspectRatio="none">
      ${[-12, -6, 0, 6, 12].map(g => html`<line class=${cls('eqc-grid', g === 0 && 'zero')}
        x1="0" x2=${EQC.W} y1=${egy(g)} y2=${egy(g)} />`)}
      ${[100, 1000, 10000].map(f => html`<line class="eqc-grid" x1=${efx(f)} x2=${efx(f)} y1="0" y2=${EQC.H} />`)}
      <path class="eqc-path" d=${path} />
      <path class="eqc-fill" d=${path + `L${EQC.W},${egy(0)} L0,${egy(0)} Z`} />
    </svg>
    ${[100, 1000, 10000].map(f => html`<span class="eqc-flb" style=${`left:${efx(f) / EQC.W * 100}%`}>${f >= 1000 ? (f / 1000) + 'k' : f}</span>`)}
    ${nodes.map(n => html`<button type="button"
      class=${cls('eqc-node', dragN === n.id && 'drag', n.off && 'off')}
      style=${`left:${n.x / EQC.W * 100}%;top:${n.y / EQC.H * 100}%`}
      onPointerDown=${e => { e.preventDefault(); setDragN(n.id); }}
      onDblClick=${() => n.id === 'hp' && onParam('lowcut_on', !vals.lowcut_on)}>${n.label}</button>`)}
  </div>`;
}

// ── DynMeter : niveaux temps réel d'un bloc dynamique (P3) — IN (peak piste) + GR (réduction
// de gain rapportée par ReaGate/ReaComp/ReaLimit via GainReduction_dB). Le composant ARME la
// boucle de mesure côté Reaper (POST, ré-armée périodiquement tant que la feuille est ouverte)
// et lit /api/meters/read à ~7 Hz. LED : verte = porte ouverte / pas de réduction.
export function DynMeter({ blockId, kind }) {
  const [m, setM] = useState(null);
  useEffect(() => {
    let live = true;
    const arm = () => fetch('/api/meters', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ block: blockId }) }).catch(() => null);
    arm();
    const ta = setInterval(arm, 4000);
    const tr = setInterval(() => fetch('/api/meters/read').then(r => r.json())
      .then(d => { if (live && d && d.t) setM(d); }).catch(() => {}), 150);
    return () => { live = false; clearInterval(ta); clearInterval(tr); };
  }, [blockId]);
  const peak = m ? Math.max(-60, Math.min(0, m.peak_db)) : -60;
  const gr = m ? Math.max(-30, Math.min(0, m.gr_db || 0)) : 0;
  // ReaGate ne publie PAS GainReduction_dB (vérifié 2026-07-23 — ReaComp/ReaLimit oui) :
  // pour la gate, la LED suit le niveau de SORTIE de piste (porte fermée = silence en aval).
  const hasGR = !!(m && m.gr_ok);
  const open = hasGR ? gr > -1 : peak > -60;
  return html`<div class="dynmeter">
    <span class="dm-lb">OUT</span>
    <div class="dm-bar"><span class="dm-fill in" style=${`width:${(peak + 60) / 60 * 100}%`}></span></div>
    <span class="dm-val">${m ? peak.toFixed(1) : '—'}<i>dB</i></span>
    ${hasGR ? html`
      <span class="dm-lb">GR</span>
      <div class="dm-bar gr"><span class="dm-fill gr" style=${`width:${-gr / 30 * 100}%`}></span></div>
      <span class="dm-val">${gr.toFixed(1)}<i>dB</i></span>` : ''}
    ${kind === 'gate' ? html`<span class=${cls('dm-led', open && 'open')}
      title=${open ? 'gate OPEN' : 'gate closed'}></span>` : ''}
  </div>`;
}

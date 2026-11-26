// SPDX-License-Identifier: GPL-3.0-or-later
// golem pedals: SVG renderers for every block golem can put on a lane, in three families.
//
//   gfx      "metal"    golem-fx's own effects, in one of two finishes: "anodized" (machined aluminium
//                       in the family's colour, the motif engraved) or "thrash" (gloss lacquer, diamond
//                       plate, the motif in yellow lined in black). By default ("auto") the finish
//                       follows the family (finishFor); GolemPedals.setStyle or opts.style force one.
//                       gfx-met, gfx-emet, gfx-shem and gfx-golem have their own "blackwork" finish: black
//                       lacquer, white engraving, a skull whose eyes light when the pedal is on. Each effect has a motif saying what it does (MOTIF) and its glyph lit
//                       as a rune when on. "clay", the first prototype, stays available.
//   nam-*    "specimen" NAM captures: a steel pedal with a glass window (the captured circuit), and the
//                       amp line: head, cab, head + cab (stack or combo), voiced by the amp's family.
//   generic  "enamel"   every other golem block: a hammertone die-cast box, a jewel lamp, the glyph on
//                       an enamel badge.
//
// Plain script (no module), so the gallery opens from disk and golem can load it as is. Everything is
// returned as SVG strings. Call GolemPedals.defs() once per page: the shared gradients, textures and
// filters live there (ids prefixed `gp-`).
(function (root) {
  'use strict';

  const FONT = {
    gfx: "'Saira Semi Condensed','Saira','Arial Narrow',sans-serif",
    enamel: "'Shrikhand','Cooper Black','Georgia',serif",
    enamelSmall: "'Saira Semi Condensed','Arial Narrow',sans-serif",
    nam: "'Big Shoulders Display','Oswald','Arial Narrow',sans-serif",
    blackletter: "'Pirata One','UnifrakturCook','Georgia',serif",
    lcd: "'Share Tech Mono','DejaVu Sans Mono','Courier New',monospace",
  };

  // ---------- colour ----------
  const hex = h => {
    h = String(h || '#8a94a3').replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const toHex = rgb => '#' + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
  const mix = (a, b, t) => { const A = hex(a), B = hex(b); return toHex(A.map((v, i) => v + (B[i] - v) * t)); };
  const luma = c => { const [r, g, b] = hex(c); return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255; };

  // golem's newer blocks share a neutral grey; the clay and enamel bodies take their category's hue
  // instead, so two greys never sit side by side on a board. The block tile keeps the catalogue colour.
  const CATEGORY_HUE = {
    dynamics: '#5f86b8', preamp: '#d9a441', drive: '#ffb03a', lofi: '#e07a3a', filter: '#5ec8e0',
    amp: '#ff5a3c', cab: '#1ab7b0', eq: '#3d9be9', modulation: '#2ecc71', delay: '#5a7cff',
    reverb: '#7a6cf0', pitch: '#b06cf0', utility: '#a39a86', hardware: '#e06ac0', keys: '#e0b23a',
  };
  const hueOf = (color, category) => {
    const [r, g, b] = hex(color);
    const grey = Math.max(r, g, b) - Math.min(r, g, b) < 34;
    return grey ? (CATEGORY_HUE[category] || color) : color;
  };

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------- glyphs ----------
  function data() { return root.GOLEM_VISUALS || { glyphs: {}, gfx: {}, blocks: [], archetypes: {} }; }
  function glyphInner(id) {
    const g = data().glyphs[id];
    return g ? g.svg : "<circle cx='12' cy='12' r='8'/>";
  }
  // A glyph placed at (x, y) (its centre), `size` px wide, stroked in `color`.
  function glyphAt(id, x, y, size, color, sw, extra) {
    const s = size / 24;
    return `<g transform="translate(${x - size / 2} ${y - size / 2}) scale(${s})" fill="none" stroke="${color}" ` +
      `stroke-width="${sw || 1.8}" stroke-linecap="round" stroke-linejoin="round" color="${color}" ${extra || ''}>${glyphInner(id)}</g>`;
  }
  // A standalone glyph icon (block mode), sized by CSS (1em by default).
  function glyph(id, opts) {
    opts = opts || {};
    return `<svg class="${opts.cls || 'gp-glyph'}" viewBox="0 0 24 24" width="${opts.size || '1em'}" height="${opts.size || '1em'}" ` +
      `fill="none" stroke="currentColor" stroke-width="${opts.sw || 1.8}" stroke-linecap="round" stroke-linejoin="round" ` +
      `role="img" aria-label="${esc((data().glyphs[id] || {}).label || id)}">${glyphInner(id)}</svg>`;
  }

  // ---------- shared defs ----------
  function defs() {
    return `<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>
  <linearGradient id="gp-sheen" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset=".18" stop-color="#fff" stop-opacity=".04"/>
    <stop offset=".75" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></linearGradient>
  <linearGradient id="gp-side" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#000" stop-opacity=".25"/><stop offset=".08" stop-color="#000" stop-opacity="0"/>
    <stop offset=".92" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".3"/></linearGradient>
  <radialGradient id="gp-knob" cx=".38" cy=".32" r=".75">
    <stop offset="0" stop-color="#5a524b"/><stop offset=".55" stop-color="#26211d"/><stop offset="1" stop-color="#0e0c0a"/></radialGradient>
  <radialGradient id="gp-knob-alu" cx=".4" cy=".35" r=".8">
    <stop offset="0" stop-color="#f4f6f8"/><stop offset=".5" stop-color="#b9bfc6"/><stop offset="1" stop-color="#6d747c"/></radialGradient>
  <radialGradient id="gp-knob-cream" cx=".4" cy=".35" r=".75">
    <stop offset="0" stop-color="#fffaf0"/><stop offset=".6" stop-color="#e6dcc6"/><stop offset="1" stop-color="#a99d86"/></radialGradient>
  <radialGradient id="gp-chrome" cx=".35" cy=".3" r=".8">
    <stop offset="0" stop-color="#ffffff"/><stop offset=".35" stop-color="#d4d9de"/><stop offset=".7" stop-color="#7c848c"/><stop offset="1" stop-color="#c9ced3"/></radialGradient>
  <radialGradient id="gp-jewel" cx=".35" cy=".3" r=".8">
    <stop offset="0" stop-color="#fff" stop-opacity=".9"/><stop offset=".25" stop-color="#fff" stop-opacity=".15"/><stop offset="1" stop-color="#000" stop-opacity=".45"/></radialGradient>
  <linearGradient id="gp-brushed" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#d9dde1"/><stop offset=".45" stop-color="#9ea5ad"/><stop offset=".55" stop-color="#b8bec5"/><stop offset="1" stop-color="#7d848c"/></linearGradient>
  <linearGradient id="gp-glass" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#1b2228"/><stop offset="1" stop-color="#05080a"/></linearGradient>
  <linearGradient id="gp-glass-glare" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset=".4" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="gp-cable" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#3a3a3a"/><stop offset="1" stop-color="#0a0a0a"/></linearGradient>
  <pattern id="gp-brush-lines" width="6" height="2" patternUnits="userSpaceOnUse">
    <path d="M0 .5h6" stroke="#fff" stroke-opacity=".10" stroke-width=".5"/><path d="M0 1.5h4" stroke="#000" stroke-opacity=".08" stroke-width=".5"/></pattern>
  <pattern id="gp-grip" width="6" height="6" patternUnits="userSpaceOnUse">
    <path d="M0 3h6" stroke="#000" stroke-opacity=".55" stroke-width="2.2"/><path d="M0 1.6h6" stroke="#fff" stroke-opacity=".08" stroke-width=".6"/></pattern>
  <pattern id="gp-weave" width="4" height="4" patternUnits="userSpaceOnUse">
    <path d="M0 1h2M2 3h2" stroke="#fff" stroke-opacity=".10" stroke-width="1"/><path d="M1 0v2M3 2v2" stroke="#000" stroke-opacity=".25" stroke-width="1"/></pattern>
  <pattern id="gp-mesh" width="3" height="3" patternUnits="userSpaceOnUse">
    <circle cx="1.5" cy="1.5" r=".7" fill="#000" fill-opacity=".55"/></pattern>
  <pattern id="gp-basket" width="8" height="8" patternUnits="userSpaceOnUse">
    <path d="M0 2h4M4 6h4" stroke="#000" stroke-opacity=".28" stroke-width="2"/><path d="M6 0v4M2 4v4" stroke="#fff" stroke-opacity=".12" stroke-width="2"/></pattern>
  <linearGradient id="gp-flame" x1="0" y1="1" x2="0" y2="0">
    <stop offset="0" stop-color="#ff3b00"/><stop offset=".55" stop-color="#ffa000"/><stop offset="1" stop-color="#ffe14a"/></linearGradient>
  <linearGradient id="gp-anod-sheen" x1="0" y1="0" x2="1" y2=".25">
    <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".36" stop-color="#fff" stop-opacity=".2"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <linearGradient id="gp-gloss" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity=".3"/><stop offset=".18" stop-color="#fff" stop-opacity=".04"/><stop offset="1" stop-color="#000" stop-opacity=".18"/></linearGradient>
  <linearGradient id="gp-bw-body" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#1c1c1c"/><stop offset=".5" stop-color="#0d0d0d"/><stop offset="1" stop-color="#040404"/></linearGradient>
  <linearGradient id="gp-bw-gloss" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity=".12"/><stop offset=".2" stop-color="#fff" stop-opacity=".02"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <radialGradient id="gp-bw-knob" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#3a3a3a"/><stop offset="1" stop-color="#030303"/></radialGradient>
  <filter id="gp-bw-glow" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="3"/></filter>
  <pattern id="gp-hazard" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="10" height="10" fill="#111"/><rect width="5" height="10" fill="#ffd400"/></pattern>
  <pattern id="gp-plate" width="9" height="9" patternUnits="userSpaceOnUse">
    <rect width="9" height="9" fill="#1a1a1c"/><path d="M1.3 3.9 3.9 1.3 5.2 2.3 2.6 4.9Z" fill="#4a4b50"/><path d="M1.3 3.9 3.9 1.3" stroke="#8a8c92" stroke-width=".35"/>
    <path d="M5.8 8.4 8.4 5.8 9.7 6.8 7.1 9.4Z" fill="#4a4b50"/><path d="M5.8 8.4 8.4 5.8" stroke="#8a8c92" stroke-width=".35"/></pattern>
  <pattern id="gp-knurl" width="2.4" height="10" patternUnits="userSpaceOnUse">
    <rect width="1.2" height="10" fill="#000" opacity=".3"/><rect x="1.2" width=".5" height="10" fill="#fff" opacity=".22"/></pattern>
  <filter id="gp-clay" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7" result="n"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 .5  0 0 0 0 .45  0 0 0 0 .4  0 0 0 .5 0"/>
    <feComposite in2="SourceGraphic" operator="in"/></filter>
  <filter id="gp-hammer" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency=".09" numOctaves="2" seed="3" result="n"/>
    <feDiffuseLighting in="n" surfaceScale="2.2" lighting-color="#fff" result="l"><feDistantLight azimuth="235" elevation="48"/></feDiffuseLighting>
    <feColorMatrix in="l" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  .9 0 0 0 -.45" result="hl"/>
    <feComposite in="hl" in2="SourceGraphic" operator="in"/></filter>
  <filter id="gp-tolex" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="1" seed="11" result="n"/>
    <feDiffuseLighting in="n" surfaceScale=".8" lighting-color="#fff" result="l"><feDistantLight azimuth="225" elevation="55"/></feDiffuseLighting>
    <feColorMatrix in="l" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  .7 0 0 0 -.38"/>
    <feComposite in2="SourceGraphic" operator="in"/></filter>
  <filter id="gp-speckle" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="2.4" numOctaves="1" seed="5" result="n"/>
    <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 2.2 -1.25"/>
    <feComposite in2="SourceGraphic" operator="in"/></filter>
  <filter id="gp-glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="2.6"/></filter>
  <filter id="gp-glow-soft" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="1.1"/></filter>
  <filter id="gp-shadow" x="-30%" y="-30%" width="160%" height="170%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="4"/><feOffset dy="5" dx="2"/>
    <feComponentTransfer><feFuncA type="linear" slope=".6"/></feComponentTransfer>
    <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="gp-shadow-small" x="-30%" y="-30%" width="160%" height="170%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="1.2"/><feOffset dy="1.5" dx=".6"/>
    <feComponentTransfer><feFuncA type="linear" slope=".55"/></feComponentTransfer>
    <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs></svg>`;
  }

  // ---------- parts ----------
  // knob value -> angle (degrees, 0 = up), over a 270° sweep
  const angleOf = (p) => {
    if (!p || p.max === p.min) return 0;
    let v = p.value != null ? p.value : p.default;
    if (typeof v !== 'number' || !isFinite(v)) v = (p.min + p.max) / 2;
    return -135 + 270 * Math.max(0, Math.min(1, (v - p.min) / (p.max - p.min)));
  };
  // The value a control shows: `values` is {param id: value} in the parameter's own unit, as a golem patch
  // stores a block's params. An enum also takes its option's name, a toggle a boolean; a missing or unreadable
  // key leaves the default.
  const valueOf = (p, values) => {
    let v = values && values[p.id] != null ? values[p.id] : p.value != null ? p.value : p.default;
    if (typeof v === 'boolean') v = v ? 1 : 0;
    if (typeof v === 'string') {
      const i = (p.options || []).findIndex(o => String(o).toLowerCase() === v.trim().toLowerCase());
      v = i >= 0 ? i : v.trim() !== '' && isFinite(+v) ? +v : p.default;
    }
    return typeof v === 'number' && isFinite(v) ? v : (p.min + p.max) / 2;
  };
  // a face (or a catalogue block) with every control set to its value in `values`
  const CONTROL_LISTS = ['knobs', 'selectors', 'toggles', 'params'];
  function withValues(spec, values) {
    if (!values || typeof values !== 'object') return spec;
    const out = Object.assign({}, spec);
    CONTROL_LISTS.forEach(k => {
      if (Array.isArray(spec[k])) out[k] = spec[k].map(p => p && values[p.id] != null ? Object.assign({}, p, { value: valueOf(p, values) }) : p);
    });
    return out;
  }
  const polar = (cx, cy, r, deg) => {
    const a = (deg - 90) * Math.PI / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const shortLabel = s => {
    s = String(s || '');
    const map = { 'Threshold': 'thresh', 'Feedback': 'fdbk', 'High Cut': 'hi cut', 'Low Cut': 'lo cut' };
    return (map[s] || s).toLowerCase();
  };

  // the gfx knob: low-profile, knurled, a pointer in the rune's colour
  function knobClay(cx, cy, r, p, accent, label) {
    const a = angleOf(p);
    const [px, py] = polar(cx, cy, r * .78, a);
    const [qx, qy] = polar(cx, cy, r * .25, a);
    let ticks = '';
    for (let i = 0; i <= 10; i++) {
      const d = -135 + 27 * i;
      const [x1, y1] = polar(cx, cy, r + 2.2, d), [x2, y2] = polar(cx, cy, r + (i % 5 ? 3.6 : 4.6), d);
      ticks += `<path d="M${x1.toFixed(2)} ${y1.toFixed(2)}L${x2.toFixed(2)} ${y2.toFixed(2)}"/>`;
    }
    return `<g class="gp-knob" data-param="${esc(p && p.id)}">
  <g stroke="#000" stroke-opacity=".35" stroke-width=".7">${ticks}</g>
  <circle cx="${cx}" cy="${cy + 1.2}" r="${r}" fill="#000" opacity=".35"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob)"/>
  <circle cx="${cx}" cy="${cy}" r="${r - .8}" fill="none" stroke="#000" stroke-opacity=".6" stroke-width="1.4" stroke-dasharray="1 1.1"/>
  <circle cx="${cx}" cy="${cy}" r="${r * .62}" fill="#1a1613" stroke="#fff" stroke-opacity=".07"/>
  <path d="M${qx.toFixed(2)} ${qy.toFixed(2)}L${px.toFixed(2)} ${py.toFixed(2)}" stroke="${accent}" stroke-width="${Math.max(1.4, r / 6)}" stroke-linecap="round"/>
  ${label ? `<text x="${cx}" y="${cy + r + 8.5}" text-anchor="middle" font-family="${FONT.gfx}" font-size="6.4" font-weight="600" letter-spacing=".2" fill="#000" fill-opacity=".62">${esc(label)}</text>` : ''}
</g>`;
  }

  // a small pointer selector, one tick per option
  function selectorClay(cx, cy, r, p, accent, inkOpacity, ink) {
    const n = (p.options || []).length || 2;
    const idx = Math.max(0, Math.min(n - 1, Math.round(p.value != null ? p.value : p.default) || 0));
    const sweep = Math.min(270, 30 * (n - 1));
    const at = i => n === 1 ? 0 : -sweep / 2 + sweep * i / (n - 1);
    let ticks = '';
    for (let i = 0; i < n; i++) {
      const [x, y] = polar(cx, cy, r + 3, at(i));
      ticks += `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${i === idx ? 1.1 : .65}" fill="${i === idx ? accent : '#000'}" fill-opacity="${i === idx ? 1 : .45}"/>`;
    }
    const [px, py] = polar(cx, cy, r + .5, at(idx));
    const label = (p.options || [])[idx] || '';
    return `<g class="gp-selector" data-param="${esc(p.id)}">${ticks}
  <circle cx="${cx}" cy="${cy + .8}" r="${r}" fill="#000" opacity=".35"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob)"/>
  <path d="M${cx} ${cy}L${px.toFixed(2)} ${py.toFixed(2)}" stroke="#d8d0c4" stroke-width="1.6" stroke-linecap="round"/>
  <text x="${cx}" y="${cy + r + 8}" text-anchor="middle" font-family="${FONT.gfx}" font-size="5.6" font-weight="600" fill="${ink || '#000'}" fill-opacity="${ink ? .9 : (inkOpacity || .62)}">${esc(label.toLowerCase())}</text>
</g>`;
  }

  function toggleClay(cx, cy, p, ink) {
    const on = (p.value != null ? p.value : p.default) >= .5;
    return `<g class="gp-toggle" data-param="${esc(p.id)}"><rect x="${cx - 3.2}" y="${cy - 5}" width="6.4" height="10" rx="1.6" fill="#16120f"/>
  <circle cx="${cx}" cy="${on ? cy - 2.4 : cy + 2.4}" r="2.1" fill="url(#gp-chrome)"/>
  <text x="${cx}" y="${cy + 12}" text-anchor="middle" font-family="${FONT.gfx}" font-size="5.4" font-weight="600" fill="${ink || '#000'}" fill-opacity="${ink ? .9 : .6}">${esc(shortLabel(p.name))}</text></g>`;
  }

  // side jacks (input left, output right: golem lanes read left to right)
  function jacks(w, y, metal) {
    const m = metal || '#2a2a2a';
    return `<g class="gp-jacks"><rect x="-3.5" y="${y - 5}" width="5" height="10" rx="1" fill="${m}"/><rect x="-4.5" y="${y - 3.4}" width="2" height="6.8" fill="#000" opacity=".5"/>
  <rect x="${w - 1.5}" y="${y - 5}" width="5" height="10" rx="1" fill="${m}"/><rect x="${w + 2.5}" y="${y - 3.4}" width="2" height="6.8" fill="#000" opacity=".5"/></g>`;
  }

  function stompSwitch(cx, cy, r) {
    return `<g class="gp-switch"><circle cx="${cx}" cy="${cy + 1.5}" r="${r + 2.5}" fill="#000" opacity=".3"/>
  <polygon points="${hexPoints(cx, cy, r + 2.6)}" fill="url(#gp-chrome)" stroke="#000" stroke-opacity=".3" stroke-width=".5"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-chrome)" stroke="#000" stroke-opacity=".35" stroke-width=".6"/>
  <circle cx="${cx - r * .25}" cy="${cy - r * .3}" r="${r * .35}" fill="#fff" opacity=".55" filter="url(#gp-glow-soft)"/></g>`;
  }
  function hexPoints(cx, cy, r) {
    const pts = [];
    for (let i = 0; i < 6; i++) { const a = Math.PI / 6 + i * Math.PI / 3; pts.push((cx + r * Math.cos(a)).toFixed(2) + ',' + (cy + r * Math.sin(a)).toFixed(2)); }
    return pts.join(' ');
  }

  // knob grid inside [x0, x1] starting at y0; returns {svg, bottom}
  function knobGrid(knobs, x0, x1, y0, accent, kind, knobFn) {
    const n = knobs.length;
    if (!n) return { svg: '', bottom: y0 };
    const w = x1 - x0;
    const rows = n <= 3 ? [knobs] : [knobs.slice(0, 2), knobs.slice(2)];
    const r = n === 1 ? 16 : n === 2 ? 12.5 : n === 3 ? 10.5 : 9.5;
    let svg = '', y = y0 + r + 2, last = y;
    rows.forEach((row, ri) => {
      let deepest = y;
      row.forEach((p, i) => {
        // 3 in a row: the middle one drops a little, like a cast face
        const cx = x0 + w * (i + .5) / row.length;
        const dy = row.length === 3 && i === 1 ? 6 : 0;
        deepest = Math.max(deepest, y + dy);
        svg += knobFn ? knobFn(cx, y + dy, r, p) : kind === 'enamel' ? knobEnamel(cx, y + dy, r, p) : knobClay(cx, y + dy, r, p, accent, shortLabel(p.name));
      });
      last = deepest;
      if (ri < rows.length - 1) y += r * 2 + 12;
    });
    return { svg, bottom: last + r + 10 };
  }

  // ---------- gfx: clay ----------
  function gfxPedal(crateOrSpec, opts) {
    opts = opts || {};
    let spec = typeof crateOrSpec === 'string' ? data().gfx[crateOrSpec] : crateOrSpec;
    if (!spec) return '';
    // the controls at the block's settings: `values`, or `params` as a chain item carries them
    const values = opts.values || opts.params;
    if (values) { spec = withValues(spec, values); opts = Object.assign({}, opts, { values }); }
    let style = opts.style || api.style;
    if (style === 'auto') style = finishFor(spec);
    // the wide stomp (sliders) has no clay or blackwork drawing: those finishes fall back to anodized
    if (spec.shape === 'wide') return gfxWide(spec, opts, style === 'thrash' ? 'thrash' : 'anodized');
    if (style === 'blackwork') return gfxPedalBlackwork(spec, opts);
    if (METAL_STYLES.includes(style)) return spec.shape === 'treadle' ? gfxTreadleMetal(spec, opts, style) : gfxPedalMetal(spec, opts, style);
    if (spec.shape === 'treadle') return gfxTreadle(spec, opts);
    const on = opts.on !== false;
    const hue = hueOf(spec.color, spec.category);
    const body = mix(hue, '#3b342e', .42);
    const bodyDark = mix(body, '#000', .45);
    const rune = mix(hue, '#ffffff', .25);
    const knobs = spec.knobs || [], sels = spec.selectors || [], togs = spec.toggles || [];
    const W = knobs.length <= 2 && !sels.length ? 92 : 112, H = 200;

    const grid = knobGrid(knobs, 6, W - 6, 10, rune, 'clay');
    let y = knobs.length ? grid.bottom : 22;
    let svg = grid.svg;
    // selectors and toggles share one row
    const row = [...sels.map(p => ({ p, k: 's' })), ...togs.map(p => ({ p, k: 't' }))];
    if (row.length) {
      y += 10;
      row.forEach((it, i) => {
        const cx = W * (i + .5) / row.length;
        svg += it.k === 's' ? selectorClay(cx, y, 6.5, it.p, rune) : toggleClay(cx, y, it.p);
      });
      y += 15;
    }
    // the rune: centred in what is left above the switch
    const top = y, bottom = 148;
    const gy = (top + bottom - 6) / 2, gsize = Math.max(18, Math.min(40, bottom - top - 22));
    const cw = Math.min(W - 26, gsize + 30), ch = gsize + 12;
    const cart = `<rect x="${W / 2 - cw / 2}" y="${gy - ch / 2}" width="${cw}" height="${ch}" rx="${ch / 2}" fill="${mix(body, '#000', .3)}"/>
  <rect x="${W / 2 - cw / 2}" y="${gy - ch / 2}" width="${cw}" height="${ch}" rx="${ch / 2}" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="2.4" transform="translate(0 -.6)"/>
  <rect x="${W / 2 - cw / 2}" y="${gy - ch / 2 + 1}" width="${cw}" height="${ch}" rx="${ch / 2}" fill="none" stroke="#fff" stroke-opacity=".14" stroke-width=".8"/>`;
    const runeSvg = cart +
      glyphAt(spec.glyph, W / 2 + .7, gy + .9, gsize, '#fff', 2.1, 'stroke-opacity=".22"') +
      glyphAt(spec.glyph, W / 2, gy, gsize, mix(bodyDark, '#000', .3), 2.1) +
      (on ? glyphAt(spec.glyph, W / 2, gy, gsize, rune, 2.4, 'filter="url(#gp-glow)" opacity=".95"') +
            glyphAt(spec.glyph, W / 2, gy, gsize, mix(rune, '#fff', .55), 1.1) : '');

    const ledOn = on ? mix(hue, '#fff', .35) : '#2a211c';
    return `<svg class="gp-pedal gp-gfx${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" ` +
      `role="img" aria-label="${esc(spec.name)} — golem-fx ${esc(spec.crate)}" data-crate="${esc(spec.crate)}">
<g filter="url(#gp-shadow)">
  ${jacks(W, 40)}
  <rect x="0" y="6" width="${W}" height="${H}" rx="12" fill="${bodyDark}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="12" fill="${body}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="12" fill="#000" filter="url(#gp-clay)" opacity=".55"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="12" fill="url(#gp-sheen)"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="12" fill="url(#gp-side)"/>
  <rect x="2.5" y="2.5" width="${W - 5}" height="${H - 5}" rx="10" fill="none" stroke="#fff" stroke-opacity=".10"/>
</g>
${svg}
${runeSvg}
<text x="${W / 2}" y="${bottom + 6}" text-anchor="middle" font-family="${FONT.gfx}" font-size="12" font-weight="700" letter-spacing=".4" fill="#000" fill-opacity=".72">${esc(spec.name.toLowerCase())}</text>
<circle cx="${W / 2}" cy="${bottom + 14}" r="2.4" fill="${ledOn}"${on ? ` filter="url(#gp-glow-soft)"` : ''}/>
<circle cx="${W / 2}" cy="${bottom + 14}" r="2.4" fill="url(#gp-jewel)"/>
${stompSwitch(W / 2, H - 21, 8.5)}
<text x="${W - 9}" y="${H - 6}" text-anchor="end" font-family="${FONT.gfx}" font-size="5.6" font-weight="700" fill="#000" fill-opacity=".45">golem fx</text>
</svg>`;
  }

  // ---------- gfx: metal (anodized | thrash) ----------
  // Two finishes for golem-fx's own pedals, both saturated (no grey mixed into the hue):
  //   anodized  machined aluminium in the family's colour, the motif engraved in the metal;
  //   thrash    gloss lacquer, a diamond-plate panel round the switch, the motif in yellow lined in black.
  // Each effect carries a motif that says what it does (flames for the drive, echoes for the delay…).
  const METAL_HUE = {
    dynamics: '#4a5a6e', drive: '#e04a00', utility: '#f0a500', filter: '#00a8c0', eq: '#0058e0',
    modulation: '#00a84f', delay: '#3a28f0', reverb: '#6a1fd1', pitch: '#c4148c',
    // raspberry: golem's lofi orange sits too close to drive's; free between pitch's magenta and the thrash red
    lofi: '#e8336f',
    // orchid violet: the free gap between reverb / shimmer (265°) and pitch's magenta (319°)
    preamp: '#b316c0',
    // teal: between filter's cyan and modulation's green, near golem's own cab tile (gfx-cab's review)
    cab: '#00a898',
  };
  const METAL_CRATE_HUE = { 'gfx-shimmer': '#8a3ff0', 'gfx-gapmeter': '#6b7480', 'gfx-glitch': '#72c000', 'gfx-ringmod': '#c9b000',
    // deck champagne: the pale gold-anodized faceplate of a reel deck (gfx-tape's review: brown is
    // gfx-fuzz's copper at tile size)
    'gfx-tape': '#d8c8a0',
    // ice glass: pale sky, air and open space (gfx-widener's review: utility's amber would read as a boost)
    'gfx-widener': '#c0e0f8',
    // germanium copper (gfx-fuzz's review: a third thrash-red drive pedal would be told apart by its
    // motif alone; no other pedal is copper)
    'gfx-fuzz': '#b0602a',
    // gfx-octafuzz: the same germanium copper (gfx-fuzz's engine, its family and finish); the motif tells
    // them apart
    'gfx-octafuzz': '#b0602a',
    // deep scope green: separated from gfx-glitch's lime and modulation's green by lightness (L* 40)
    'gfx-tuner': '#126e1c',
    // deep plum: a darker sister of the pitch family's magenta (gfx-correct's review: ΔE00 16 from it,
    // 20.6 from preamp violet); it sits beside gfx-formant on a voice lane
    'gfx-correct': '#7a1450',
    // rosewood: a dark, saturated wood (gfx-acoustic's review: ΔE 36 to the copper)
    'gfx-acoustic': '#552210',
    'gfx-radio': '#4b5320',
    'gfx-stretch': '#a0a8ff',
    // neon rose: the pink of an 80s synth's lettering, a light tint of the pitch family's magenta
    // (gfx-polysynth's review: the draft's mint was ΔE*ab 27 from gfx-cab's teal; this rose is 42 – 44 from
    // raspberry, periwinkle and the pitch magenta)
    'gfx-polysynth': '#ff9ecf',
    // deep crimson: a raw throat, the darker sister of the lofi family's raspberry (gfx-morph's design:
    // ΔE*ab 29 from raspberry, 34 from gfx-acoustic's rosewood, 35 from gfx-correct's plum)
    'gfx-morph': '#9a0d2a',
    // midnight blue: a lacquered console at night, the darkest blue of the family (gfx-organ's design:
    // ΔE*ab 41 from the eq blue, 41 from gfx-correct's plum, 43 from the dynamics slate)
    'gfx-organ': '#20226a' };
  const THRASH_HUE = { drive: '#c8160e' };
  // the rune's light where the body's own hue would glow too dull
  const RUNE_LIGHT = { dynamics: '#5fb0ff', preamp: '#ecb8ff', 'gfx-gapmeter': '#d8dde3', 'gfx-swell': '#ffd0dc', 'gfx-tape': '#94461a', 'gfx-widener': '#3a7fc0', 'gfx-tuner': '#3ddc2e', 'gfx-correct': '#ff5fb4', 'gfx-acoustic': '#ffc46b', 'gfx-radio': '#c8d86a', 'gfx-stretch': '#3040c8', 'gfx-polysynth': '#8a1060', 'gfx-morph': '#ff6a4d', 'gfx-organ': '#f0e6c8' };
  const MOTIF = {
    'gfx-drive': 'flames', 'gfx-boost': 'chevrons', 'gfx-gate': 'barbed', 'gfx-comp': 'clamp', 'gfx-limiter': 'clamp',
    'gfx-deesser': 'clamp', 'gfx-wah': 'crescent', 'gfx-autowah': 'crescent', 'gfx-eq': 'curve', 'gfx-tremolo': 'pulse',
    'gfx-vibrato': 'waves', 'gfx-chorus': 'waves', 'gfx-flanger': 'jet', 'gfx-phaser': 'spiral', 'gfx-rotary': 'swirl',
    'gfx-killswitch': 'bolt', 'gfx-delay': 'echo', 'gfx-reverb': 'rays', 'gfx-shimmer': 'stars', 'gfx-octaver': 'diamonds',
    'gfx-pitch': 'stairs', 'gfx-pitch-classic': 'stairs', 'gfx-detune': 'stairs', 'gfx-gapmeter': 'ticks',
    'gfx-met': 'barbed', 'gfx-emet': 'flames', 'gfx-shem': 'chevrons', 'gfx-golem': 'waves', 'gfx-glitch': 'bins',
    'gfx-geq': 'scale',
    'gfx-freqshift': 'barber',
    'gfx-swell': 'swells',
    'gfx-crusher': 'pixels',
    'gfx-ringmod': 'sidebands',
    'gfx-bassdi': 'parallel',
    'gfx-tape': 'ribbon',
    'gfx-grit': 'prism',
    'gfx-dist': 'traces',
    'gfx-transient': 'spikes',
    'gfx-mbcomp': 'tiers',
    'gfx-widener': 'fan',
    'gfx-ducker': 'dips',
    'gfx-fuzz': 'sputter',
    'gfx-octafuzz': 'octring',
    'gfx-tuner': 'strobe',
    'gfx-cab': 'cone',
    'gfx-irfx': 'impulse',
    'gfx-correct': 'staff',
    'gfx-vocoder': 'bank',
    'gfx-acoustic': 'rosette',
    'gfx-radio': 'grille',
    'gfx-stretch': 'chirp',
    'gfx-grains': 'grains',
    'gfx-sustainer': 'modes',
    'gfx-polysynth': 'saws',
    'gfx-spectralcomp': 'skyline',
    'gfx-morph': 'canned',
    'gfx-formant': 'formants',
    'gfx-organ': 'drawbars' };
  const METAL_STYLES = ['anodized', 'thrash'];
  // style 'auto' (the default): the finish follows the family. Aggressive families (drive, dynamics,
  // utility) are thrash, the rest anodized; the killswitch's lightning is thrash, the gap meter anodized.
  const FAMILY_FINISH = { drive: 'thrash', dynamics: 'thrash', utility: 'thrash', lofi: 'thrash' };
  // the high-gain companions (Fortin's role) and the vocal doubler have their own black finish
  // the swell removes attacks (violins, pads): anodized, against the dynamics family's thrash
  const CRATE_FINISH = { 'gfx-killswitch': 'thrash', 'gfx-gapmeter': 'anodized', 'gfx-swell': 'anodized', 'gfx-tape': 'anodized', 'gfx-widener': 'anodized', 'gfx-fuzz': 'anodized', 'gfx-octafuzz': 'anodized', 'gfx-tuner': 'anodized', 'gfx-correct': 'anodized', 'gfx-met': 'blackwork', 'gfx-emet': 'blackwork', 'gfx-shem': 'blackwork', 'gfx-golem': 'blackwork', 'gfx-acoustic': 'anodized', 'gfx-radio': 'thrash', 'gfx-polysynth': 'anodized', 'gfx-organ': 'anodized' };
  const finishFor = spec => CRATE_FINISH[spec.crate] || FAMILY_FINISH[spec.category] || 'anodized';
  let metalCount = 0;
  const f1 = v => (+v).toFixed(1);

  function metalHue(spec, style) {
    return (style === 'thrash' && THRASH_HUE[spec.category]) || METAL_CRATE_HUE[spec.crate] || METAL_HUE[spec.category] || hueOf(spec.color, spec.category);
  }
  const pill = (x, y, w, h) => { const r = h / 2; return `M${f1(x + r)} ${f1(y)}h${f1(w - h)}a${f1(r)} ${f1(r)} 0 0 1 0 ${f1(h)}h${f1(h - w)}a${f1(r)} ${f1(r)} 0 0 1 0 ${f1(-h)}Z`; };
  const sine = (x0, x1, y, a, period, phase) => {
    let d = '';
    for (let x = x0; x <= x1 + .01; x += 2) d += (d ? 'L' : 'M') + f1(x) + ' ' + f1(y + a * Math.sin((x / period) * 2 * Math.PI + (phase || 0)));
    return d;
  };
  const arcPath = (cx, cy, r, a0, a1) => {
    const p = a => [cx + r * Math.cos(a * Math.PI / 180), cy + r * Math.sin(a * Math.PI / 180)];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    return `M${f1(x0)} ${f1(y0)}A${f1(r)} ${f1(r)} 0 ${Math.abs(a1 - a0) > 180 ? 1 : 0} 1 ${f1(x1)} ${f1(y1)}`;
  };

  // a motif as parts: {d, fill} paths in the pedal's own coordinates (g: the rune's centre and cartouche)
  function motifParts(kind, W, H, g) {
    const { x: cx, y: cy, cw, ch } = g, P = [];
    const line = (d, op) => P.push({ d, op: op == null ? 1 : op });
    const shape = (d, op, fill) => P.push({ d, op: op == null ? 1 : op, fill: fill || true });
    switch (kind) {
      case 'flames': {
        const base = H - 36, top = cy + 2, n = 5, w = W / n;
        let d = `M-2 ${H}L-2 ${f1(base)}`;
        for (let i = 0; i < n; i++) {
          const x0 = i * w, xm = x0 + w / 2, x1 = x0 + w, pk = top + (i % 2 ? 16 : 0) + (i === 2 ? -6 : 0);
          d += `C${f1(x0 + w * .1)} ${f1(base - (base - pk) * .55)} ${f1(xm - w * .3)} ${f1(pk + 12)} ${f1(xm)} ${f1(pk)}` +
               `C${f1(xm + w * .05)} ${f1(pk + 14)} ${f1(x1 - w * .2)} ${f1(base - (base - pk) * .35)} ${f1(x1)} ${f1(base - (base - pk) * .2)}`;
        }
        shape(d + `L${W + 2} ${H}Z`, 1, 'flame');
        break;
      }
      case 'chevrons':
        [W * .13, W * .87].forEach(x => { for (let k = 0; k < 3; k++) { const y = cy + 12 - k * 12; shape(`M${f1(x - 6)} ${f1(y + 4)}L${f1(x)} ${f1(y - 3)}L${f1(x + 6)} ${f1(y + 4)}L${f1(x + 6)} ${f1(y + 8)}L${f1(x)} ${f1(y + 1)}L${f1(x - 6)} ${f1(y + 8)}Z`, 1 - k * .25); } });
        break;
      case 'barbed':
        [cy - ch / 2 - 5, cy + ch / 2 + 5].forEach(y => {
          line(sine(0, W, y, 1.6, 9, 0)); line(sine(0, W, y, 1.6, 9, Math.PI));
          for (let x = 9; x < W; x += 18) line(`M${f1(x - 3.5)} ${f1(y - 4)}L${f1(x + 3.5)} ${f1(y + 4)}M${f1(x + 3.5)} ${f1(y - 4)}L${f1(x - 3.5)} ${f1(y + 4)}`);
        });
        break;
      case 'clamp':
        P.push({ band: [cy - ch / 2 - 4, ch + 8] });
        shape(`M2 ${f1(cy - 7)}L11 ${f1(cy)}L2 ${f1(cy + 7)}Z`); shape(`M${W - 2} ${f1(cy - 7)}L${W - 11} ${f1(cy)}L${W - 2} ${f1(cy + 7)}Z`);
        break;
      case 'tiers': {
        // gfx-comp's clamp split into bands: four short meter bars each side of the rune, inside the
        // cartouche's height, each pressed at its inner end by its own small clamp (gfx-comp's
        // triangle at 0.45, 2 px clear); the two sides run to different depths, fainter downwards
        const s = (W - cw) / 2 - 4, room = s - 8, ops = [1, .85, .7, .55];
        const lens = [[.7, .4, .55, .3], [.35, .65, .3, .5]];
        [-.375, -.125, .125, .375].forEach((k, i) => {
          const y = cy + k * ch;
          [0, 1].forEach(side => {
            const len = Math.max(3, lens[side][i] * room), x0 = side ? W - 4 - len : 4;
            shape(pill(x0, y - 1.5, len, 3), ops[i]);
            if (s >= 16) {
              const tip = side ? x0 - 2 : x0 + len + 2, dir = side ? -1 : 1;
              shape(`M${f1(tip)} ${f1(y)}L${f1(tip + dir * 4.05)} ${f1(y - 3.15)}L${f1(tip + dir * 4.05)} ${f1(y + 3.15)}Z`, ops[i]);
            }
          });
        });
        break;
      }
      case 'crescent':
        line(arcPath(cx, cy, W * .44, 200, 340)); line(arcPath(cx, cy, W * .53, 205, 335), .6);
        line(arcPath(cx, cy, W * .44, 20, 160), .45);
        break;
      case 'strobe':
        // the bands of a strobe disc round the rune: 12, 24 and 48 segments per turn (the octave bands),
        // equal gaps, on crescent's two spans (clear of the knobs); the middle band offset by half a
        // segment so the eye reads motion
        [[.40, 12, 1, 0], [.47, 24, .7, .5], [.54, 48, .45, 0]].forEach(([k, n, op, off]) => {
          const per = 360 / n, r = W * k;
          for (const [a0, a1] of [[200, 340], [20, 160]]) {
            for (let s = Math.ceil(a0 / per - off); (s + off) * per + per / 2 <= a1 + 1e-9; s++) {
              const b = (s + off) * per;
              if (b >= a0 - 1e-9) line(arcPath(cx, cy, r, b, b + per / 2), op);
            }
          }
        });
        break;
      case 'staff': {
        // five engraved staff lines across the face; on the left a free-hand pitch trace wanders between
        // them with a small vibrato (60 %), on the right it rests on lines and spaces, joined by risers
        const gap = ch * .3, ys = [-2, -1, 0, 1, 2].map(k => cy + k * gap);
        ys.forEach(y => line(`M0 ${f1(y)}H${W}`, .45));
        let d = '';
        for (let x = 0; x <= W / 2 + .01; x += 2) {
          const y = cy + gap * (1.1 * Math.sin(x / W * 5.2) - .5 * Math.sin(x / W * 11 + 1)) + .9 * Math.sin(x / 2.6);
          d += (d ? 'L' : 'M') + f1(x) + ' ' + f1(y);
        }
        line(d, .6);
        const steps = [.5, -1, 0, 1.5, .5], sw = (W / 2) / steps.length;
        let q = `M${f1(W / 2)} ${f1(cy + steps[0] * gap)}`;
        steps.forEach((k, i) => {
          if (i) q += `V${f1(cy + k * gap)}`;
          q += `H${f1(W / 2 + (i + 1) * sw)}`;
        });
        line(q);
        break;
      }
      case 'curve':
        for (let i = 1; i < 8; i++) line(`M${f1(W * i / 8)} ${f1(cy - ch)}V${f1(cy + ch)}`, .35);
        line(`M0 ${f1(cy + ch * .7)}C${f1(W * .18)} ${f1(cy + ch * .7)} ${f1(W * .18)} ${f1(cy - ch * .95)} ${f1(W * .35)} ${f1(cy - ch * .95)}` +
             `S${f1(W * .55)} ${f1(cy + ch * .95)} ${f1(W * .72)} ${f1(cy + ch * .95)}S${f1(W * .9)} ${f1(cy - ch * .5)} ${W} ${f1(cy - ch * .5)}`);
        break;
      case 'pulse': {
        const a = ch * .75, per = 16;
        let d = `M0 ${f1(cy + a)}`;
        for (let x = 0; x < W; x += per) d += `H${f1(x + per / 2)}V${f1(cy - a)}H${f1(x + per)}V${f1(cy + a)}`;
        line(d);
        break;
      }
      case 'waves':
        line(sine(0, W, cy - 4, ch * .7, 30, 0)); line(sine(0, W, cy + 4, ch * .7, 30, 1.4), .6);
        break;
      case 'sidebands': {
        // the product of two sines, above and below the rune: a fast sine (period ≈ 9 px) whose amplitude
        // follows a slow one (period W / 1.5), pinching to zero and swelling twice; its two envelope
        // curves (± |slow sine|) at opacity 0.4. Polylines sampled every 1 px
        const a = 6, fast = 9, slow = W / 1.5;
        [cy - ch / 2 - 11, cy + ch / 2 + 11].forEach(y0 => {
          let d = '', up = '', dn = '';
          for (let x = 0; x <= W + .01; x += 1) {
            const env = Math.sin(x / slow * 2 * Math.PI);
            const m = (d ? 'L' : 'M');
            d += m + f1(x) + ' ' + f1(y0 + a * env * Math.sin(x / fast * 2 * Math.PI));
            up += m + f1(x) + ' ' + f1(y0 - a * Math.abs(env));
            dn += m + f1(x) + ' ' + f1(y0 + a * Math.abs(env));
          }
          line(d); line(up, .4); line(dn, .4);
        });
        break;
      }
      case 'jet':
        [[-10, 30, 70], [0, 18, 90], [20, 4, 60], [-6, -10, 110], [30, -22, 80], [10, -36, 70], [40, 44, 60]].forEach(([x, dy, len], i) =>
          line(`M${f1(x)} ${f1(cy + dy + len * .35)}L${f1(x + len)} ${f1(cy + dy - len * .25)}`, .45 + .08 * (i % 4)));
        break;
      case 'spiral':
        [0, 1, 2].forEach(k => line(arcPath(cx, cy, ch / 2 + 7 + k * 9, -60 + k * 70, 190 + k * 70), 1 - k * .25));
        break;
      case 'swirl':
        [0, 90, 180, 270].forEach(a0 => {
          const p = (r, a) => [cx + r * Math.cos(a * Math.PI / 180), cy + r * Math.sin(a * Math.PI / 180)];
          const [x0, y0] = p(ch / 2 + 2, a0), [x1, y1] = p(ch / 2 + 20, a0 + 35), [x2, y2] = p(ch / 2 + 36, a0 + 85);
          line(`M${f1(x0)} ${f1(y0)}Q${f1(x1)} ${f1(y1)} ${f1(x2)} ${f1(y2)}`);
        });
        break;
      case 'bolt':
        shape('M' + [[.88, .06], [.6, .38], [.72, .4], [.42, .66], [.54, .68], [.14, .95], [.36, .62], [.24, .6], [.48, .34], [.36, .32]]
          .map(([x, y]) => f1(x * W) + ' ' + f1(y * H)).join('L') + 'Z');
        break;
      case 'echo':
        [[.16, .65], [.32, .4], [.48, .2]].forEach(([dx, op]) => line(pill(cx - cw / 2 + W * dx, cy - ch / 2, cw, ch), op));
        break;
      case 'rays':
        P.push({ rays: true });
        break;
      case 'stars':
        [[.08, .55, 7], [.92, .47, 6], [.9, .7, 4.5], [.12, .72, 5], [.8, .32, 3.5], [.22, .36, 3.5]].forEach(([x, y, s]) => {
          const X = x * W, Y = y * H;
          shape(`M${f1(X)} ${f1(Y - s)}Q${f1(X)} ${f1(Y)} ${f1(X + s)} ${f1(Y)}Q${f1(X)} ${f1(Y)} ${f1(X)} ${f1(Y + s)}Q${f1(X)} ${f1(Y)} ${f1(X - s)} ${f1(Y)}Q${f1(X)} ${f1(Y)} ${f1(X)} ${f1(Y - s)}Z`);
        });
        break;
      case 'diamonds':
        [10, 20, 30].forEach((k, i) => { const v = ch / 2 + k, h = cw / 2 + k * 1.1; line(`M${f1(cx)} ${f1(cy - v)}L${f1(cx + h)} ${f1(cy)}L${f1(cx)} ${f1(cy + v)}L${f1(cx - h)} ${f1(cy)}Z`, 1 - i * .28); });
        break;
      case 'stairs': {
        const n = 6, sw = W / n, y0 = cy + ch * .95, rise = ch * 1.9 / n;
        let d = `M0 ${f1(y0)}`;
        for (let i = 0; i < n; i++) d += `H${f1((i + 1) * sw)}V${f1(y0 - (i + 1) * rise)}`;
        line(d);
        break;
      }
      case 'barber': {
        // two barber-pole columns at the face's edges, over the rune zone: diagonal stripes at 30°,
        // rising to the right on the left column and to the left on the right one (two channels
        // shifted opposite ways), brighter towards the top (the endless climb)
        const top = cy - ch, bot = cy + ch, cwid = 12, rise = cwid * Math.tan(Math.PI / 6);
        [[4, 1], [W - 16, -1]].forEach(([x0, dir]) => {
          const x1 = x0 + cwid;
          line(`M${f1(x0)} ${f1(top)}V${f1(bot)}`, .5); line(`M${f1(x1)} ${f1(top)}V${f1(bot)}`, .5);
          for (let y = top + 9; y < bot + rise; y += 9) {
            // the stripe from (start x, y) up to (end x, y − rise), clipped to the column
            let t0 = 0, t1 = 1;
            if (y > bot) t0 = (y - bot) / rise;
            if (y - rise < top) t1 = (y - top) / rise;
            if (t1 <= t0) continue;
            const xa = dir > 0 ? x0 : x1, xs = dir * cwid;
            const ym = y - rise * (t0 + t1) / 2, op = .35 + .65 * (bot - ym) / (bot - top);
            line(`M${f1(xa + xs * t0)} ${f1(y - rise * t0)}L${f1(xa + xs * t1)} ${f1(y - rise * t1)}`, op);
          }
        });
        break;
      }
      case 'formants': {
        // the envelope moves, the harmonics stay: two columns over the rune zone (x 4 – 16 and W − 16 –
        // W − 4, as barber). In both, harmonic ticks 6 long every 5 units from the outer edge (opacity
        // .35), identical left and right: the pitch does not change. Over them the envelope, frequency
        // upwards, sampled every unit: three raised-cosine bumps 6 deep pointing towards the rune, at
        // 22 / 42 / 62 % of the column's height on the left (the giant) and the same curve stretched
        // ×1.3 on the right (29 / 55 / 81 %: the child)
        const top = cy - ch, bot = cy + ch, hgt = bot - top;
        [[4, 1, 1], [W - 4, -1, 1.3]].forEach(([xo, dir, k]) => {
          for (let y = bot; y >= top - 1e-9; y -= 5) line(`M${f1(xo)} ${f1(y)}H${f1(xo + dir * 6)}`, .35);
          let d = '';
          for (let y = bot; y >= top - 1e-9; y -= 1) {
            const u = (bot - y) / hgt;
            let b = 0;
            [.22, .42, .62].forEach(c => { const z = (u - c * k) / .09; if (Math.abs(z) < 1) b += .5 + .5 * Math.cos(Math.PI * z); });
            d += `${d ? 'L' : 'M'}${f1(xo + dir * (3 + 6 * Math.min(b, 1)))} ${f1(y)}`;
          }
          line(d, 1);
        });
        break;
      }
      case 'ribbon': {
        // a tape ribbon: two lines 2.5 units apart crossing the face through the rune zone, waving with
        // an irregular wow (sines of 1 and 2.7 cycles across the face, amplitude 3 units), broken by two
        // short gaps (dropouts: 3 and 5 units), passing behind the rune's disc; three oxide specks
        // (r 0.6) by the wider gap
        const yAt = x => cy + 3 * (.62 * Math.sin(2 * Math.PI * x / W) + .38 * Math.sin(2 * Math.PI * 2.7 * x / W + 1.1));
        const behind = x => Math.abs(x - cx) < cw / 2 + 1.5;
        const gaps = [[W * .16, 3], [W * .84, 5]];
        const gapped = x => gaps.some(([g0, w]) => x >= g0 && x <= g0 + w);
        [-1.25, 1.25].forEach(off => {
          let d = '', on = false;
          for (let x = 2; x <= W - 2 + .01; x += 1) {
            if (behind(x) || gapped(x)) { on = false; continue; }
            d += (on ? 'L' : 'M') + f1(x) + ' ' + f1(yAt(x) + off);
            on = true;
          }
          if (d) line(d);
        });
        const [g1, w1] = gaps[1], r = .6;
        [[g1 - 2.2, 3.4], [g1 + w1 + 1.8, -3.3], [g1 + w1 / 2, 4.2]].forEach(([x, dy]) =>
          shape(`M${f1(x - r)} ${f1(yAt(x) + dy)}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`, .8));
        break;
      }
      case 'chirp': {
        // one wave whose period grows ×8 from left to right, time being stretched: instantaneous
        // period p0 · 8^(x / W), p0 = 5 px, so φ(x) = 2π W / (p0 ln 8) · (1 − 8^(−x / W)) (≈ 6.7 cycles
        // over an 80 px face). A second copy at .45, 4 px lower and a quarter of the local period
        // later: the stereo wash. In the rune band like `waves`, told apart by its glide
        const a = ch * .7, p0 = 5, k = 2 * Math.PI * W / (p0 * Math.log(8));
        const phi = x => k * (1 - Math.pow(8, -x / W));
        [[0, 0, 1], [4, -Math.PI / 2, .45]].forEach(([dy, ph, op]) => {
          let d = '';
          for (let x = 0; x <= W + .01; x += 1) d += (d ? 'L' : 'M') + f1(x) + ' ' + f1(cy + dy + a * Math.sin(phi(x) + ph));
          line(d, op);
        });
        break;
      }
      case 'grains': {
        // a cloud of grains converging on the rune: seven small Hann arches each side (3 – 7 units wide,
        // 2 – 6 high), each with a dot at its peak, placed by a fixed seed (from the crate's name, so the
        // drawing is stable), larger, denser and brighter toward the rune (35 → 90 %); inside the
        // rune's band, clear of the knobs
        let seed = 0;
        for (const c of 'gfx-grains') seed = (seed * 31 + c.charCodeAt(0)) >>> 0;
        const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
        const inner = cx - cw / 2 - 3, outer = 4, n = 7;
        [[1, outer, inner], [-1, W - outer, W - inner]].forEach(([s, a, b]) => {
          for (let k = 0; k < n; k++) {
            // denser toward the rune: positions on a square-root law
            const t = Math.sqrt((k + .5 + .4 * (rnd() - .5)) / n), x = a + s * t * Math.abs(b - a);
            const w = 3 + 4 * t * (.7 + .3 * rnd()), h = 2 + 4 * t * (.7 + .3 * rnd());
            const y0 = cy + (ch / 2 - h - 1) * (rnd() - .5) * 1.6 + h / 2, op = .35 + .55 * t;
            line(`M${f1(x - w / 2)} ${f1(y0)}C${f1(x - w / 6)} ${f1(y0)} ${f1(x - w / 6)} ${f1(y0 - h)} ${f1(x)} ${f1(y0 - h)}` +
              `S${f1(x + w / 2 - w / 3)} ${f1(y0)} ${f1(x + w / 2)} ${f1(y0)}`, op);
            const r = .55 + .25 * t;
            shape(`M${f1(x - r)} ${f1(y0 - h - 1.6)}a${r} ${r} 0 1 0 ${f1(2 * r)} 0a${r} ${r} 0 1 0 ${f1(-2 * r)} 0Z`, op);
          }
        });
        break;
      }
      case 'bank': {
        // a filterbank raised by a vowel: nine overlapping bells on one baseline just under the
        // cartouche, each reaching its neighbours' centres; low under the rune (2 px under it), tall
        // beside it (up to the cartouche's top). Closed arches only, no envelope line (gfx-formant's)
        const y0 = cy + ch / 2 + 8, w = W / 9;
        const e = [1, .55, .85, .45, .3, .5, .9, .6, .7];
        for (let i = 0; i < 9; i++) {
          const x = W * (i + .5) / 9, room = Math.abs(x - cx) < cw / 2 ? 6 : ch + 6, h = e[i] * room;
          line(`M${f1(x - w)} ${f1(y0)}C${f1(x - w / 3)} ${f1(y0)} ${f1(x - w / 3)} ${f1(y0 - h)} ${f1(x)} ${f1(y0 - h)}` +
            `S${f1(x + w / 3)} ${f1(y0)} ${f1(x + w)} ${f1(y0)}`, .45 + .5 * e[i]);
        }
        break;
      }
      case 'modes': {
        // a string's standing waves, the note blooming into its harmonic (gfx-sustainer). Left of the
        // cartouche the fundamental: one loop between two nodes, three nested lenses (a = .35, .65, 1 ×
        // .55 ch; opacity .35, .65, 1: the bloom). Right of it the octave: two loops (one lens each,
        // a = .55 ch) over a faint one-loop lens (.3: the harmonic taking over). The string through both
        // regions at the rune's centre line (.4)
        const lens = (xa, xb, a, op) => {
          const xm = (xa + xb) / 2;
          line(`M${f1(xa)} ${f1(cy)}Q${f1(xm)} ${f1(cy - 2 * a)} ${f1(xb)} ${f1(cy)}Q${f1(xm)} ${f1(cy + 2 * a)} ${f1(xa)} ${f1(cy)}`, op);
        };
        const l0 = 6, l1 = cx - cw / 2 - 6, r0 = cx + cw / 2 + 6, r1 = W - 6, a = .55 * ch, rm = (r0 + r1) / 2;
        line(`M${f1(l0)} ${f1(cy)}H${f1(l1)}`, .4);
        line(`M${f1(r0)} ${f1(cy)}H${f1(r1)}`, .4);
        [.35, .65, 1].forEach(k => lens(l0, l1, k * a, k));
        lens(r0, r1, a, .3);
        lens(r0, rm, a, 1);
        lens(rm, r1, a, 1);
        break;
      }
      case 'drawbars': {
        // a registration pulled out (gfx-organ). Two fields in the rune band, left and right of the
        // cartouche, clear of the knobs: nine bars hang from a rail at the field's top edge, each a line
        // ending in a short wide tip (2.5 × the stroke); lengths follow a registration, the left field
        // 88 8000 000 (Trio), the right 88 8888 888 (full organ); a drawbar at 0 is its tip alone on the
        // rail. The Hammond colours as opacity: brown (16', 5⅓') .55, white (8', 4', 2', 1') 1, black
        // (2⅔', 1⅗', 1⅓') .75
        const op = [.55, .55, 1, 1, .75, 1, .75, .75, 1];
        const top = cy - ch / 2, len = ch;
        const field = (x0, x1, reg) => {
          line(`M${f1(x0)} ${f1(top)}H${f1(x1)}`, .45);
          const step = (x1 - x0) / 9;
          reg.forEach((n, i) => {
            const x = x0 + step * (i + .5), y = top + len * n / 8;
            if (n > 0) line(`M${f1(x)} ${f1(top)}V${f1(y)}`, op[i]);
            line(`M${f1(x - 1.25)} ${f1(y)}H${f1(x + 1.25)}`, op[i]);
          });
        };
        field(6, cx - cw / 2 - 6, [8, 8, 8, 0, 0, 0, 0, 0, 0]);
        field(cx + cw / 2 + 6, W - 6, [8, 8, 8, 8, 8, 8, 8, 8, 8]);
        break;
      }
      case 'saws': {
        // a chord turned into oscillators (gfx-polysynth). Either side of the cartouche, within the
        // rune band, three sawtooth rows at cy − ch / 2, cy, cy + ch / 2 (amplitude ch / 6), periods
        // 6 : 5 : 4 from bottom to top (a major triad: the higher note, the shorter period), each tooth a
        // ramp then a vertical drop; opacity .45, .7, 1 from bottom to top. The left rows start with one
        // sine cycle (the string) before the teeth; the right rows are teeth only
        const l0 = 6, l1 = cx - cw / 2 - 6, r0 = cx + cw / 2 + 6, r1 = W - 6, a = ch / 6;
        const rows = [[cy + ch / 2, 6, .45], [cy, 5, .7], [cy - ch / 2, 4, 1]];
        const unit = Math.max(2, (l1 - l0) / 22);
        rows.forEach(([y, k, op]) => {
          const per = k * unit;
          const teeth = (x0, x1, start) => {
            let d = start;
            for (let x = x0; x + per <= x1 + .01; x += per) d += `L${f1(x + per)} ${f1(y - a)}V${f1(y + a)}`;
            return d;
          };
          // left: one sine cycle, then teeth from its end
          let d = `M${f1(l0)} ${f1(y)}`;
          for (let x = 0; x <= per + .01; x += 1) d += `L${f1(l0 + x)} ${f1(y - a * Math.sin(x / per * 2 * Math.PI))}`;
          d += `L${f1(l0 + per)} ${f1(y + a)}`;
          line(teeth(l0 + per, l1, d), op);
          line(teeth(r0, r1, `M${f1(r0)} ${f1(y + a)}`), op);
        });
        break;
      }
      case 'bins': {
        // a spectrum's bins either side of the rune, sliced along one line and the tops slipped
        // sideways, as the glyph: the spectrum fractured
        const y0 = cy + ch / 2 + 6, cut = cy + 2, slip = 2.4, gap = 2.6;
        const tops = [.35, .62, .48, .9, .28, .74, 1, .52, .4, .66, .22, .58];
        let k = 0;
        for (let x = 7; x <= W - 7; x += 5) {
          if (Math.abs(x - cx) < cw / 2 - 2) continue;
          const t = tops[k++ % tops.length], top = y0 - (y0 - (cy - ch * .7)) * t, op = .45 + .5 * t;
          if (top < cut - gap - 1.5) {
            line(`M${f1(x)} ${f1(y0)}V${f1(cut)}`, op);
            line(`M${f1(x + slip)} ${f1(cut - gap)}V${f1(top)}`, op);
          } else line(`M${f1(x)} ${f1(y0)}V${f1(top)}`, op);
        }
        break;
      }
      case 'skyline': {
        // a spectrum evened by a tilted line (gfx-spectralcomp): bins' grid and baseline either side of
        // the rune; a threshold line falling to the right (the `slope`), broken at the cartouche; a bar
        // over it is cut at the line with a faint stub of what was taken, a bar under it is lifted by a
        // third of its gap to the line. Uneven below, flattened along the line
        const y0 = cy + ch / 2 + 6, ya = cy - .15 * ch, yb = cy - .05 * ch, clear = cw / 2 + 2, gap = 1.6;
        const yl = x => ya + (yb - ya) * x / W;
        const tops = [.35, .9, .5, 1, .25, .7, .95, .4, .6, .3, .85, .55];
        line(`M0 ${f1(ya)}L${f1(cx - clear)} ${f1(yl(cx - clear))}`, .45);
        line(`M${f1(cx + clear)} ${f1(yl(cx + clear))}L${W} ${f1(yb)}`, .45);
        let k = 0;
        for (let x = 7; x <= W - 7; x += 5) {
          if (Math.abs(x - cx) < clear) continue;
          const t = tops[k++ % tops.length], top = y0 - (y0 - (cy - ch * .7)) * t, l = yl(x);
          if (top < l) {
            line(`M${f1(x)} ${f1(y0)}V${f1(l + gap)}`);
            if (top < l - gap) line(`M${f1(x)} ${f1(l - gap)}V${f1(top)}`, .3);
          } else {
            line(`M${f1(x)} ${f1(y0)}V${f1(top)}`);
            line(`M${f1(x)} ${f1(top)}V${f1(top - (top - l) / 3)}`, .55);
          }
        }
        break;
      }
      case 'scale':
        // a screen-printed fader scale: rules at 0 (stronger), ±5, ±10, ±15 dB across the slider field
        // (the wide face's slots run y 16 – 100, 0 dB at 58)
        for (let db = -15; db <= 15; db += 5) line(`M4 ${f1(WIDE_SLOT.mid - db / 15 * WIDE_SLOT.half)}H${W - 4}`, db === 0 ? 1 : .5);
        break;
      case 'spikes': {
        // either side of the rune, two envelopes each: the original (ghost) and the shaped one over it,
        // a taller, sharper spike and a lifted tail (t 4 then 2: two shaped notes, not one stamp)
        const y0 = cy + ch / 2 + 3, yTop = cy - ch / 2 - 6, free = (W - cw) / 2 - 3, w = free / 2 - 2;
        for (const left of [true, false]) {
          for (let k = 0; k < 2; k++) {
            const x0 = (left ? 2 : cx + cw / 2 + 3) + k * (w + 2), t = k === 0 ? 4 : 2;
            line(`M${f1(x0)} ${f1(y0)}L${f1(x0 + 1.5)} ${f1(y0 - 12)}Q${f1(x0 + .3 * w)} ${f1(y0 - 6)} ${f1(x0 + w)} ${f1(y0)}`, .35);
            line(`M${f1(x0)} ${f1(y0)}L${f1(x0 + 1.2)} ${f1(yTop)}Q${f1(x0 + .25 * w)} ${f1(y0 - 9)} ${f1(x0 + w)} ${f1(y0 - t)}`);
          }
        }
        break;
      }
      case 'dips': {
        // the swells' band and slots, the figure hung from a level line: in each of four beats the
        // level runs flat, drops at once to near the baseline and climbs back along a curve (a pump);
        // under each drop, three faint ticks are the key's burst that caused it. The dips get
        // shallower by 2 px from left to right, so the row is not a repeated stamp
        const y0 = H - 40, sw = W / 4, w = sw - 4, yTop = cy + ch / 2 + 8;
        line(`M0 ${f1(y0)}H${W}`, .4);
        for (let k = 0; k < 4; k++) {
          const x0 = k * sw + 2, xd = x0 + .12 * w, yb = y0 - 10 - 2 * k;
          line(`M${f1(x0)} ${f1(yTop)}H${f1(xd)}L${f1(xd + 1.5)} ${f1(yb)}Q${f1(x0 + .45 * w)} ${f1(yb)} ${f1(x0 + .9 * w)} ${f1(yTop)}H${f1(x0 + w)}`);
          line(`M${f1(xd - 1)} ${f1(y0)}v-3M${f1(xd + .75)} ${f1(y0)}v-6M${f1(xd + 2.5)} ${f1(y0)}v-4`, .35);
        }
        break;
      }
      case 'swells': {
        // four notes along a baseline: each pick's tick (the attack removed, faint), then a concave-up
        // rise (the Square curve) to a plateau, then the next note's dip; plateaus climb, a crescendo
        const y0 = H - 40, sw = W / 4, w = sw - 4;
        line(`M0 ${f1(y0)}H${W}`);
        for (let k = 0; k < 4; k++) {
          const x0 = k * sw + 2, yTop = cy + ch / 2 + 8 - 3 * k, op = .45 + .55 * k / 3;
          line(`M${f1(x0)} ${f1(y0)}V${f1(y0 - 8)}`, .35);
          line(`M${f1(x0)} ${f1(y0)}Q${f1(x0 + .75 * w)} ${f1(y0)} ${f1(x0 + .92 * w)} ${f1(yTop)}H${f1(x0 + w)}V${f1(y0)}`, op);
        }
        break;
      }
      case 'parallel': {
        // the blend, drawn: one line splits into two tracks, a clipped wave above and the same wave
        // round below (its crests under the flats), and the tracks rejoin into one line
        const x0 = W * .12, x1 = W * .88, ya = cy - ch * .9, yb = cy + ch * .9, a = ch * .35, s = 6;
        line(`M0 ${f1(cy)}H${f1(x0)}L${f1(x0 + s)} ${f1(ya)}M${f1(x0)} ${f1(cy)}L${f1(x0 + s)} ${f1(yb)}`);
        line(`M${f1(x1 - s)} ${f1(ya)}L${f1(x1)} ${f1(cy)}H${W}M${f1(x1 - s)} ${f1(yb)}L${f1(x1)} ${f1(cy)}`);
        // trapezoids from the middle level, rising: rise 4, flat 7, fall 4, flat 7 (period 22)
        const xs = x0 + s, xe = x1 - s;
        let d = `M${f1(xs)} ${f1(ya)}`, x = xs;
        const steps = [[2, -1], [7, -1], [4, 1], [7, 1], [2, 0]];
        while (x < xe - .01) {
          for (const [dx, lv] of steps) {
            const nx = Math.min(x + dx, xe);
            d += `L${f1(nx)} ${f1(ya + a * lv)}`;
            x = nx;
            if (x >= xe - .01) break;
          }
        }
        line(d);
        line(sine(xs, xe, yb, -a, 22, -2 * Math.PI * xs / 22), .6);
        break;
      }
      case 'pixels': {
        // a sine sampled into square pixels either side of the rune (one column every 6 units, 1.5
        // periods across the face, 5 levels), joined by its hold staircase; the two columns nearest
        // the rune smaller and fainter, so the wave dissolves into it
        // (the phase puts a rising swing on each side: trough at the edge, crest by the rune)
        const amp = ch * .6, cols = [];
        for (let x = 5; x <= W - 5; x += 6) {
          if (Math.abs(x - cx) < cw / 2 + 2) continue;
          const lv = Math.round((Math.sin(3 * Math.PI * x / W - Math.PI / 2) + 1) * 2) / 2 - 1;
          cols.push({ x, y: cy - amp * lv, side: x < cx ? 0 : 1 });
        }
        [0, 1].forEach(side => {
          const c = cols.filter(p => p.side === side);
          if (!c.length) return;
          let d = `M${f1(c[0].x)} ${f1(c[0].y)}`;
          for (let i = 1; i < c.length; i++) d += `H${f1(c[i].x)}V${f1(c[i].y)}`;
          line(d, .35);
          const near = side ? c.slice(0, 2) : c.slice(-2);
          c.forEach(p => {
            const small = near.includes(p), s = small ? 3 : 4;
            shape(`M${f1(p.x - s / 2)} ${f1(p.y - s / 2)}h${s}v${s}h${-s}Z`, small ? .55 : 1);
          });
        });
        break;
      }
      case 'cone': {
        // a loudspeaker from the front, the rune as its dust cap: either side, arcs of radius 34, 40,
        // 46 (opacity 1, .8, .6) and 52 dashed (the surround, 2 on 2 off) over ±28° about the
        // horizontal, and three ribs at 0° and ±18° from 34 to 52 at 40 %
        [[34, 1], [40, .8], [46, .6]].forEach(([r, op]) => {
          line(arcPath(cx, cy, r, -28, 28), op);
          line(arcPath(cx, cy, r, 152, 208), op);
        });
        const step = 4 / 52 * 180 / Math.PI, on = 2 / 52 * 180 / Math.PI;
        for (const a0 of [-28, 152]) {
          for (let a = a0; a < a0 + 56 - .01; a += step) line(arcPath(cx, cy, 52, a, Math.min(a + on, a0 + 56)));
        }
        const pt = (r, deg) => [cx + r * Math.cos(deg * Math.PI / 180), cy + r * Math.sin(deg * Math.PI / 180)];
        [-18, 0, 18, 162, 180, 198].forEach(deg => {
          const [x0, y0] = pt(34, deg), [x1, y1] = pt(52, deg);
          line(`M${f1(x0)} ${f1(y0)}L${f1(x1)} ${f1(y1)}`, .4);
        });
        break;
      }
      case 'impulse': {
        // an impulse response either side of the rune, bars on the baseline of 'bins': a tall spike at
        // the inner end, then bars every 4 units decaying ×0.72, a gap, and a fainter echo cluster
        const y0 = cy + ch / 2 + 6, top = cy - ch * .7, full = y0 - top;
        for (const sgn of [-1, 1]) {
          const x0 = cx + sgn * (cw / 2 + 3), end = sgn < 0 ? 7 : W - 7;
          let x = x0, h = full, k = 0;
          while (sgn * (end - x) >= 0) {
            const echo = k >= 7, hh = echo ? full * .38 * Math.pow(.72, k - 7) : h;
            if (k !== 6 && hh > 1) line(`M${f1(x)} ${f1(y0)}V${f1(y0 - hh)}`, k === 0 ? 1 : echo ? .45 : .75);
            h *= .72;
            x += sgn * 4;
            k++;
          }
        }
        break;
      }
      case 'fan': {
        // the mono axis and the spread image: a vertical centre line from just under the rune to above
        // the switch zone (the mid, untouched), and either side five straight rays opening upward from
        // a point 6 units below the rune's centre, at ±18° … ±66° from the vertical, 0.9 · ch down to
        // 0.5 · ch long, fainter outward (the side, L = M + S, R = M − S)
        line(`M${f1(cx)} ${f1(cy + ch / 2 + 3)}V${f1(H - 34)}`);
        const oy = cy + 6;
        [18, 30, 42, 54, 66].forEach((deg, i) => {
          const a = deg * Math.PI / 180, len = ch * (.9 - .1 * i), op = 1 - .1625 * i;
          const y1 = Math.max(cy - ch, oy - len * Math.cos(a)), dx = (oy - y1) * Math.tan(a);
          [-1, 1].forEach(sgn => line(`M${f1(cx)} ${f1(oy)}L${f1(cx + sgn * dx)} ${f1(y1)}`, op));
        });
        break;
      }
      case 'prism': {
        // one beam in on the left of the rune, four rays out on the right, fanning: each carries its
        // band's dirt along its length, top to bottom clean, clipped (a sine with flat crests),
        // folded (a zigzag), crushed (a staircase), fainter downwards like light dispersed
        const xl = cx - cw / 2 - 2, x0 = cx + cw / 2 + 2, x1 = W - 6;
        line(`M6 ${f1(cy)}H${f1(xl)}`);
        const ends = [-.7, -.23, .23, .7].map(k => cy + k * ch), ops = [1, .85, .7, .55];
        ends.forEach((y1, i) => {
          const dx = x1 - x0, dy = y1 - cy, L = Math.hypot(dx, dy), ux = dx / L, uy = dy / L;
          const at = (s, o) => `${f1(x0 + ux * s - uy * o)} ${f1(cy + uy * s + ux * o)}`;
          let d = `M${f1(x0)} ${f1(cy)}`;
          if (i === 0) {
            d += `L${f1(x1)} ${f1(y1)}`;
          } else if (i === 1) {
            for (let s = .5; s <= L; s += .5) d += `L${at(s, Math.max(-1.4, Math.min(1.4, 2.1 * Math.sin(2 * Math.PI * s / 6))))}`;
          } else if (i === 2) {
            for (let s = 1; s <= L; s += 1) d += `L${at(s, [1.6, 0, -1.6, 0][(s - 1) % 4])}`;
          } else {
            for (let x = x0 + 3; x <= x1 + .01; x += 3) d += `H${f1(x)}V${f1(cy + dy * (x - x0) / dx)}`;
          }
          line(d, ops[i]);
        });
        break;
      }
      case 'traces': {
        // printed-circuit traces: three each side from the body's edge to the rune's cartouche (inside
        // the rune band, clear of the knob grid), the outer ones jogging 45° away from the centre,
        // each ending on a round pad; the middle one carries a diode pointing to the rune
        const L = cx - cw / 2 - 4, sides = [[1, 0], [-1, W]];
        sides.forEach(([s, x0]) => [-.6, 0, .6].forEach(k => {
          const y = cy + k * ch, jog = k === 0 ? 0 : 6 * Math.sign(k), xa = x0 + s * 4, xb = x0 + s * W * .18,
                xe = s > 0 ? L : W - L;
          line(`M${f1(xa)} ${f1(y)}H${f1(xb)}L${f1(xb + s * 6)} ${f1(y + jog)}H${f1(xe)}`);
          shape(`M${f1(xe - 2.2)} ${f1(y + jog)}a2.2 2.2 0 1 0 4.4 0a2.2 2.2 0 1 0 -4.4 0Z`);
          if (k === 0) {
            const xd = x0 + s * W * .27;
            shape(`M${f1(xd - s * 3)} ${f1(y - 3.5)}L${f1(xd + s * 3)} ${f1(y)}L${f1(xd - s * 3)} ${f1(y + 3.5)}Z`);
            line(`M${f1(xd + s * 3)} ${f1(y - 3.5)}V${f1(y + 3.5)}`);
          }
        }));
        break;
      }
      case 'rosette': {
        // the sound-hole rosette drawn around the rune (gfx-acoustic): circles at r0 and r0 + 2.5, a
        // herringbone ring of 36 strokes every 10° alternately slanted ±25° from the radius between
        // r0 + 3.3 and r0 + 7.2, circles at r0 + 8 and r0 + 10.5; the face's clip cuts what leaves it
        const r0 = Math.hypot(cw, ch) / 2 + 3;
        const ring = (r, op) => line(arcPath(cx, cy, r, 0, 359.9), op);
        ring(r0, 1);
        ring(r0 + 2.5, .6);
        const ri = r0 + 3.3, ro = r0 + 7.2, tilt = Math.tan(25 * Math.PI / 180) * (ro - ri);
        let d = '';
        for (let k = 0; k < 36; k++) {
          const a = k * 10 * Math.PI / 180, s = k % 2 ? -1 : 1;
          const t = [-Math.sin(a), Math.cos(a)];
          const x0 = cx + ri * Math.cos(a), y0 = cy + ri * Math.sin(a);
          const x1 = cx + ro * Math.cos(a) + s * tilt * t[0], y1 = cy + ro * Math.sin(a) + s * tilt * t[1];
          d += `${k ? 'L' : 'M'}${f1(x0)} ${f1(y0)}L${f1(x1)} ${f1(y1)}`;
        }
        line(d + 'Z', .8);
        ring(r0 + 8, .6);
        ring(r0 + 10.5, 1);
        break;
      }
      case 'octring': {
        // the octave: left of the rune a sine (2 periods), right of it the same sine full-wave
        // rectified (4 arches at twice the frequency, the octave), at the same amplitude ±0.3 · ch (≤ 7);
        // a thin pill round the cartouche at 60 %, the octave's ring. Polylines sampled every 1 px
        const a = Math.min(7, .3 * ch), xl = cx - cw / 2 - 4, xr = cx + cw / 2 + 4, x0 = 6, x1 = W - 6;
        line(sine(x0, xl, cy, a, (xl - x0) / 2, 0));
        let d = '';
        const pr = (x1 - xr) / 2;
        for (let x = xr; x <= x1 + .01; x += 1) {
          const v = Math.abs(Math.sin(((x - xr) / pr) * 2 * Math.PI));
          d += (d ? 'L' : 'M') + f1(x) + ' ' + f1(cy + a - 2 * a * v);
        }
        line(d);
        // the ring: a pill round the cartouche, as tall as the waves plus 3 units each side
        const h = 2 * a + 6;
        line(pill(cx - cw / 2 - 1, cy - h / 2, cw + 2, h), .6);
        break;
      }
      case 'sputter': {
        // a square wave each side of the rune, gating out towards it: each pulse narrower and lower
        // (widths 6 : 4.5 : 3 : 2, heights 100 / 75 / 50 / 30 %), the last two fading (60 / 35 %);
        // flat tops at ±7 (≤ 0.3 of the cartouche: inside the rune band), 1.5-unit fillets
        const a0 = Math.min(7, .3 * ch), r = 1.5, wid = [6, 4.5, 3, 2], amp = [1, .75, .5, .3], ops = [1, 1, .6, .35];
        const inner = cx - cw / 2 - 4, span = inner - 6, unit = span / wid.reduce((s, w) => s + w, 0);
        [[1, 6], [-1, W - 6]].forEach(([s, x0]) => {
          let x = x0;
          wid.forEach((w, k) => {
            const pw = w * unit, h = a0 * amp[k], rr = Math.min(r, pw / 6, h / 2), half = pw / 2;
            const up = cy - h, dn = cy + h;
            // up, across, down through the axis to the bottom, across, back up to the axis
            let d = `M${f1(x)} ${f1(cy)}V${f1(up + rr)}Q${f1(x)} ${f1(up)} ${f1(x + s * rr)} ${f1(up)}` +
                    `H${f1(x + s * (half - rr))}Q${f1(x + s * half)} ${f1(up)} ${f1(x + s * half)} ${f1(up + rr)}` +
                    `V${f1(dn - rr)}Q${f1(x + s * half)} ${f1(dn)} ${f1(x + s * (half + rr))} ${f1(dn)}` +
                    `H${f1(x + s * (pw - rr))}Q${f1(x + s * pw)} ${f1(dn)} ${f1(x + s * pw)} ${f1(dn - rr)}V${f1(cy)}`;
            line(d, ops[k]);
            x += s * pw;
          });
        });
        break;
      }
      case 'canned': {
        // the voice shouted into a can: left of the rune a smooth sine (3 periods, amplitude 0.25 · ch)
        // from x = 6 to the cartouche's left edge − 2, the voice going in; right of the rune the outline
        // of a can on its side (a 0.9 · ch × 1.3 · ch rounded rectangle at the cartouche's right edge +
        // 3, its open left side an ellipse rim), and out of it to W − 6 the same wave squared off and
        // broken: three flat-topped pulses, a gap, a stair step, at the same amplitude
        const a = .25 * ch, xl = cx - cw / 2 - 2;
        line(sine(6, xl, cy, a, (xl - 6) / 3, 0));
        const w = .9 * ch, h = 1.3 * ch, x0 = cx + cw / 2 + 3, x1 = x0 + w, r = .15 * ch, top = cy - h / 2, bot = cy + h / 2;
        line(`M${f1(x0)} ${f1(top)}H${f1(x1 - r)}Q${f1(x1)} ${f1(top)} ${f1(x1)} ${f1(top + r)}V${f1(bot - r)}` +
             `Q${f1(x1)} ${f1(bot)} ${f1(x1 - r)} ${f1(bot)}H${f1(x0)}`);
        const rx = .18 * w;
        line(`M${f1(x0)} ${f1(top)}a${f1(rx)} ${f1(h / 2)} 0 1 0 0 ${f1(h)}a${f1(rx)} ${f1(h / 2)} 0 1 0 0 ${f1(-h)}Z`, .8);
        const xs = x1 + 2, xe = W - 6, span = xe - xs, pw = span * .55 / 3, gapw = span * .12;
        let x = xs, d = `M${f1(xs)} ${f1(cy)}`;
        for (let k = 0; k < 3; k++) {
          d += `V${f1(cy - a)}H${f1(x + pw / 2)}V${f1(cy + a)}H${f1(x + pw)}V${f1(cy)}`;
          x += pw;
        }
        d += `H${f1(x + gapw)}`;
        x += gapw;
        const sw = (xe - x) / 4;
        [-.5, -1, -.5, 0].forEach(k => { d += `V${f1(cy + k * a)}H${f1(x + sw)}`; x += sw; });
        line(d);
        break;
      }
      case 'grille': {
        // a speaker grille each side of the rune: 4 pill slots (height 2.4, gap 2.0) stacked and centred
        // on it, 14 / 11.5 / 9 / 6.5 long from the top, anchored at the outer margin; above the rune a
        // tuning dial: a baseline from 8 to W − 8, 9 ticks alternating 2.5 / 1.4 tall, a 1.4-wide needle
        // 6 tall at 62 % of the strip, between two ticks ("between stations")
        const hh = 2.4, gap = 2.0, lens = [14, 11.5, 9, 6.5], top = cy - (4 * hh + 3 * gap) / 2;
        lens.forEach((len, k) => {
          const y = top + k * (hh + gap);
          shape(pill(6, y, len, hh));
          shape(pill(W - 6 - len, y, len, hh));
        });
        const yb = cy - ch / 2 - 6, x0 = 8, x1 = W - 8, step = (x1 - x0) / 8;
        line(`M${f1(x0)} ${f1(yb)}H${f1(x1)}`);
        for (let k = 0; k <= 8; k++) line(`M${f1(x0 + k * step)} ${f1(yb)}v${f1(k % 2 ? -1.4 : -2.5)}`, k % 2 ? .7 : 1);
        const xn = x0 + .62 * (x1 - x0);
        shape(`M${f1(xn - .7)} ${f1(yb + 1.5)}h1.4v-6h-1.4Z`);
        break;
      }
      case 'ticks':
        for (let y = 14; y < H - 40; y += 7) { const long = Math.round((y - 14) / 7) % 4 === 0; line(`M5 ${y}h${long ? 7 : 4}M${W - 5} ${y}h${long ? -7 : -4}`, long ? 1 : .6); }
        break;
    }
    return P;
  }

  function motifSvg(kind, style, W, H, g, colors) {
    if (!kind) return '';
    const parts = motifParts(kind, W, H, g);
    let out = '';
    parts.forEach(p => {
      if (p.rays) {
        if (style === 'thrash') {
          for (let i = 0; i < 12; i++) {
            const a = (i * 30 + 15) * Math.PI / 180, h = 6 * Math.PI / 180, r0 = g.ch / 2 + 2, r1 = 260;
            const pt = (ang, r) => f1(g.x + r * Math.sin(ang)) + ',' + f1(g.y - r * Math.cos(ang));
            out += `<polygon points="${pt(a - h, r0)} ${pt(a - h, r1)} ${pt(a + h, r1)} ${pt(a + h, r0)}" fill="#000" opacity=".32"/>`;
          }
        } else {
          let d = '';
          for (let i = 0; i < 36; i++) { const a = (i * 10 + 5) * Math.PI / 180; d += `M${f1(g.x + (g.ch / 2 + 4) * Math.sin(a))} ${f1(g.y - (g.ch / 2 + 4) * Math.cos(a))}L${f1(g.x + 260 * Math.sin(a))} ${f1(g.y - 260 * Math.cos(a))}`; }
          out += `<path d="${d}" stroke="${colors.engraveDark}" stroke-width="1.2" opacity=".5"/><path d="${d}" stroke="${colors.engraveLight}" stroke-width=".45" opacity=".35" transform="translate(.5 .5)"/>`;
        }
        return;
      }
      if (p.band) {
        const [y, h] = p.band;
        out += style === 'thrash'
          ? `<rect x="-2" y="${f1(y)}" width="${W + 4}" height="${f1(h)}" fill="url(#gp-hazard)"/><path d="M-2 ${f1(y)}H${W + 2}M-2 ${f1(y + h)}H${W + 2}" stroke="#000" stroke-width="2"/>`
          : `<rect x="-2" y="${f1(y)}" width="${W + 4}" height="${f1(h)}" fill="url(#gp-knurl)"/><path d="M-2 ${f1(y)}H${W + 2}M-2 ${f1(y + h)}H${W + 2}" stroke="${colors.engraveDark}" stroke-width="1.2" opacity=".7"/><path d="M-2 ${f1(y + .7)}H${W + 2}M-2 ${f1(y + h + .7)}H${W + 2}" stroke="${colors.engraveLight}" stroke-width=".45" opacity=".5"/>`;
        return;
      }
      const op = p.op;
      if (style === 'thrash') {
        out += p.fill
          ? `<path d="${p.d}" fill="${p.fill === 'flame' ? 'url(#gp-flame)' : '#ffd400'}" stroke="#000" stroke-width="1.6" stroke-linejoin="round" opacity="${op}"/>`
          : `<path d="${p.d}" stroke="#000" stroke-width="3.4" opacity="${op}"/><path d="${p.d}" stroke="#ffd400" stroke-width="1.6" opacity="${op}"/>`;
      } else {
        out += `<path d="${p.d}" stroke="${colors.engraveDark}" stroke-width="${p.fill ? 1.6 : 1.8}" opacity="${f1(.6 * op)}"/>` +
               `<path d="${p.d}" stroke="${colors.engraveLight}" stroke-width=".7" opacity="${f1(.75 * op)}" transform="translate(.6 .6)"/>`;
      }
    });
    return `<g class="gp-motif gp-motif-${kind}" fill="none" stroke-linecap="round" stroke-linejoin="round">${out}</g>`;
  }

  function knobMetal(style, ink) {
    return (cx, cy, r, p) => {
      const a = angleOf(p);
      const label = shortLabel(p.name).toUpperCase();
      const lbl = `<text x="${cx}" y="${f1(cy + r + 8.5)}" text-anchor="middle" font-family="${FONT.nam}" font-size="6.6" font-weight="800" letter-spacing=".5" fill="${ink}">${esc(label)}</text>`;
      if (style === 'thrash') {
        const [qx, qy] = polar(cx, cy, r * .45, a), [px, py] = polar(cx, cy, r * .94, a);
        return `<g class="gp-knob" data-param="${esc(p.id)}"><circle cx="${cx}" cy="${cy + 1.4}" r="${r + .6}" fill="#000" opacity=".5"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob)" stroke="#000" stroke-width="1.4"/>
  <circle cx="${cx}" cy="${cy}" r="${f1(r * .42)}" fill="url(#gp-chrome)"/>
  <path d="M${f1(qx)} ${f1(qy)}L${f1(px)} ${f1(py)}" stroke="#ffd400" stroke-width="${f1(Math.max(1.5, r / 6))}" stroke-linecap="round"/>${lbl}</g>`;
      }
      const [px, py] = polar(cx, cy, r * .85, a);
      return `<g class="gp-knob" data-param="${esc(p.id)}"><circle cx="${cx}" cy="${cy + 1.3}" r="${r + .4}" fill="#000" opacity=".45"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob-alu)"/>
  <circle cx="${cx}" cy="${cy}" r="${f1(r - .6)}" fill="none" stroke="#000" stroke-opacity=".28" stroke-width="1.4" stroke-dasharray=".5 .9"/>
  <circle cx="${cx}" cy="${cy}" r="${f1(r * .56)}" fill="url(#gp-knob-alu)" stroke="#000" stroke-opacity=".2" stroke-width=".4"/>
  <path d="M${cx} ${cy}L${f1(px)} ${f1(py)}" stroke="#111" stroke-width="${f1(Math.max(1.3, r / 7))}" stroke-linecap="round"/>${lbl}</g>`;
    };
  }

  function metalColors(spec, style) {
    const hue = metalHue(spec, style);
    const light = RUNE_LIGHT[spec.crate] || RUNE_LIGHT[spec.category] || mix(hue, '#fff', .3);
    const darkInk = style === 'thrash' ? luma(hue) > .5 : luma(hue) > .38;
    return {
      hue, light,
      top: mix(hue, '#fff', .22), bottom: mix(hue, '#000', .5), base: mix(hue, '#000', .78),
      faceTop: mix(hue, '#000', .12), faceBottom: mix(hue, '#000', .38),
      ink: darkInk ? mix(hue, '#000', .85) : (style === 'thrash' ? '#fff4ee' : mix(hue, '#fff', .9)),
      rim: mix(hue, '#fff', .6),
      engraveDark: mix(hue, '#000', .7), engraveLight: mix(hue, '#fff', .65),
    };
  }

  function gfxPedalMetal(spec, opts, style) {
    const on = opts.on !== false;
    const c = metalColors(spec, style), id = 'gpm' + (++metalCount);
    const knobs = spec.knobs || [], sels = spec.selectors || [], togs = spec.toggles || [];
    const W = knobs.length <= 2 && !sels.length ? 92 : 112, H = 200;
    const rx = style === 'thrash' ? 7 : 10;
    const grid = knobGrid(knobs, 6, W - 6, 10, c.light, 'metal', knobMetal(style, c.ink));
    let y = knobs.length ? grid.bottom : 22;
    let svg = grid.svg;
    const row = [...sels.map(p => ({ p, k: 's' })), ...togs.map(p => ({ p, k: 't' }))];
    const accent = style === 'thrash' ? '#ffd400' : c.light;
    const control = (it, cx, cy) => it.k === 's' ? selectorClay(cx, cy, 6.5, it.p, accent, null, c.ink) : toggleClay(cx, cy, it.p, c.ink);
    // layout 'fixed': the rune always sits at the same height and the selectors flank it, so every pedal
    // of the family lines up; 'flow' (the first layout): the rune centred in what the knob rows leave
    const fixed = (opts.layout || api.layout) === 'fixed';
    let gy, gsize;
    const bottom = 148;
    if (fixed) {
      // the selectors right under the knobs (one row), the rune always at 112: the knobs end by y 72 at most
      // (two rows of two), so the row never reaches the rune
      row.forEach((it, i) => { svg += control(it, W * (i + .5) / row.length, Math.min(y + 10, 82)); });
      gy = 112;
      gsize = 26;
    } else {
      if (row.length) {
        y += 10;
        row.forEach((it, i) => { svg += control(it, W * (i + .5) / row.length, y); });
        y += 15;
      }
      gy = (y + bottom - 6) / 2;
      gsize = Math.max(18, Math.min(38, bottom - y - 22));
    }
    const cw = Math.min(W - 26, gsize + 30), ch = gsize + 12;
    const g = { x: W / 2, y: gy, cw, ch };
    // rune 'cartouche' (dark pill / hexagon), 'engraved' (cut into the metal like the motif, lit when on)
    // or 'clearing' (the motif stops round an engraved ring; the rune lights on bare metal)
    const runeMode = opts.rune || api.rune;

    const body = style === 'thrash'
      ? `<rect x="0" y="5" width="${W}" height="${H}" rx="${rx}" fill="${c.base}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#${id}-b)"/>`
      : `<rect x="0" y="5" width="${W}" height="${H}" rx="${rx}" fill="${c.base}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#${id}-b)"/>
  <rect x="4" y="4" width="${W - 8}" height="${H - 8}" rx="${rx - 3}" fill="url(#${id}-f)"/>
  <rect x="4" y="4" width="${W - 8}" height="${H - 8}" rx="${rx - 3}" fill="url(#gp-brush-lines)"/>`;
    const finish = style === 'thrash'
      ? `<rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#gp-gloss)"/>
<g stroke="#fff" stroke-opacity=".28" stroke-width=".45"><path d="M${f1(W * .1)} ${f1(H * .5)}l${f1(W * .28)} -6"/><path d="M${f1(W * .74)} ${f1(H * .14)}l${f1(W * .2)} 9"/><path d="M${f1(W * .2)} ${f1(H * .3)}l7 -6"/></g>
<rect x="5" y="${H - 40}" width="${W - 10}" height="34" rx="3" fill="url(#gp-plate)" stroke="#000" stroke-width=".8"/>
${[[9, H - 36], [W - 9, H - 36], [9, H - 10], [W - 9, H - 10]].map(([x, yy]) => `<circle cx="${x}" cy="${yy}" r="1.4" fill="url(#gp-chrome)"/>`).join('')}`
      : `<rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#gp-anod-sheen)"/>
<rect x=".6" y=".6" width="${W - 1.2}" height="${H - 1.2}" rx="${rx - .6}" fill="none" stroke="${c.rim}" stroke-opacity=".7" stroke-width="1"/>
<rect x="4" y="4" width="${W - 8}" height="${H - 8}" rx="${rx - 3}" fill="none" stroke="${c.base}" stroke-opacity=".5" stroke-width=".8"/>`;

    // the cartouche: a hexagon in black lacquer, or a dark pill with a light rim
    const cart = style === 'thrash'
      ? `<path d="M${f1(g.x - cw / 2)} ${f1(gy)}L${f1(g.x - cw / 2 + ch * .45)} ${f1(gy - ch / 2)}H${f1(g.x + cw / 2 - ch * .45)}L${f1(g.x + cw / 2)} ${f1(gy)}L${f1(g.x + cw / 2 - ch * .45)} ${f1(gy + ch / 2)}H${f1(g.x - cw / 2 + ch * .45)}Z" fill="#0b0707" stroke="#000" stroke-width="2"/>`
      : `<path d="${pill(g.x - cw / 2, gy - ch / 2, cw, ch)}" fill="${mix(c.hue, '#000', .88)}" stroke="${c.rim}" stroke-opacity=".6" stroke-width="1"/>`;
    const lit = glyphAt(spec.glyph, g.x, gy, gsize, c.light, 2.8, 'filter="url(#gp-glow)" opacity=".95"') + glyphAt(spec.glyph, g.x, gy, gsize, mix(c.light, '#fff', .75), 1.3);
    // the glyph cut into the metal: a dark groove and its light edge, as the motif's lines
    const cut = style === 'thrash'
      ? glyphAt(spec.glyph, g.x, gy, gsize, '#000', 3.4, 'opacity=".85"') + glyphAt(spec.glyph, g.x, gy, gsize, on ? mix(c.light, '#fff', .3) : '#ffd400', 1.5, on ? '' : 'opacity=".55"')
      : glyphAt(spec.glyph, g.x + .5, gy + .5, gsize, c.engraveLight, 1.0, 'opacity=".75"') + glyphAt(spec.glyph, g.x, gy, gsize, c.engraveDark, 1.9, 'opacity=".75"');
    const ringR = ch / 2 + 5;
    const ring = style === 'thrash'
      ? `<circle cx="${g.x}" cy="${f1(gy)}" r="${f1(ringR)}" fill="none" stroke="#000" stroke-width="3.4"/><circle cx="${g.x}" cy="${f1(gy)}" r="${f1(ringR)}" fill="none" stroke="#ffd400" stroke-width="1.5"/>`
      : `<circle cx="${g.x}" cy="${f1(gy)}" r="${f1(ringR)}" fill="none" stroke="${c.engraveDark}" stroke-width="1.6" opacity=".6"/><circle cx="${g.x + .5}" cy="${f1(gy + .5)}" r="${f1(ringR)}" fill="none" stroke="${c.engraveLight}" stroke-width=".6" opacity=".7"/>`;
    const rune = runeMode === 'engraved' ? cut + (on ? lit : '')
      : runeMode === 'clearing' ? ring + cut + (on ? lit : '')
      : cart + (on ? lit : glyphAt(spec.glyph, g.x, gy, gsize, mix(c.hue, '#000', .45), 1.8));
    const clearMask = runeMode === 'clearing'
      ? `<mask id="${id}-m"><rect x="-10" y="-10" width="${W + 20}" height="${H + 20}" fill="#fff"/><circle cx="${g.x}" cy="${f1(gy)}" r="${f1(ringR + 4)}" fill="#000"/></mask>` : '';

    const name = spec.name.toUpperCase(), fs = name.length > 10 ? 10 : name.length > 7 ? 12 : 14;
    const nameSvg = style === 'thrash'
      ? `<text x="${W / 2}" y="${bottom + 8}" text-anchor="middle" font-family="${FONT.nam}" font-size="${fs + 1}" font-weight="900" letter-spacing="1" fill="#fff" stroke="#000" stroke-width="1.8" paint-order="stroke" transform="rotate(-5 ${W / 2} ${bottom + 4})">${esc(name)}</text>`
      : `<text x="${W / 2}" y="${bottom + 7}" text-anchor="middle" font-family="${FONT.nam}" font-size="${fs}" font-weight="900" letter-spacing="2.5" fill="${c.ink}">${esc(name)}</text>`;
    const ledX = style === 'thrash' ? W - 22 : W / 2, ledY = style === 'thrash' ? H - 23 : bottom + 16;
    const led = `<circle cx="${ledX}" cy="${ledY}" r="3" fill="#000" opacity=".7"/><circle cx="${ledX}" cy="${ledY}" r="2.3" fill="${on ? c.light : mix(c.hue, '#000', .7)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>${on ? `<circle cx="${ledX}" cy="${ledY}" r="1.3" fill="#fff"/>` : ''}`;

    return `<svg class="gp-pedal gp-gfx gp-${style}${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" ` +
      `role="img" aria-label="${esc(spec.name)} — golem-fx ${esc(spec.crate)}" data-crate="${esc(spec.crate)}" data-style="${style}">
<defs>
  <linearGradient id="${id}-b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c.top}"/><stop offset=".48" stop-color="${c.hue}"/><stop offset="1" stop-color="${c.bottom}"/></linearGradient>
  <linearGradient id="${id}-f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c.faceTop}"/><stop offset="1" stop-color="${c.faceBottom}"/></linearGradient>
  <clipPath id="${id}-c"><rect x="${style === 'thrash' ? 0 : 4}" y="${style === 'thrash' ? 0 : 4}" width="${style === 'thrash' ? W : W - 8}" height="${style === 'thrash' ? H : H - 8}" rx="${style === 'thrash' ? rx : rx - 3}"/></clipPath>
  ${clearMask}
</defs>
<g filter="url(#gp-shadow)">
  ${jacks(W, 40)}
  ${body}
</g>
<g clip-path="url(#${id}-c)"><g${clearMask ? ` mask="url(#${id}-m)"` : ''}>${motifSvg(MOTIF[spec.crate], style, W, H, g, c)}</g></g>
${finish}
${svg}
${rune}
${nameSvg}
${led}
${stompSwitch(W / 2, H - 21, 8.5)}
<text x="${W - 8}" y="${H - 4}" text-anchor="end" font-family="${FONT.gfx}" font-size="5" font-weight="700" fill="${style === 'thrash' ? '#fff' : c.ink}" fill-opacity=".6">golem fx</text>
</svg>`;
  }

  // ---------- gfx: the wide stomp (sliders) ----------
  // The graphic EQ's face (faces.json `shape: "wide"`, `faders`, `fader_sets`, `level_fader`): a box of
  // fixed width (168, never driven by a parameter: the pedalboard must not reflow), one slider per fader
  // of the set the enum picks, the level slider set apart, a line through the caps when on.
  const WIDE_SLOT = { top: 16, bottom: 100, mid: 58, half: 42 };
  // a monotone cubic through points equally spaced in x (Fritsch – Carlson), as Bézier segments
  function monotonePath(pts) {
    const n = pts.length;
    if (n < 2) return '';
    const m = [], d = [];
    for (let i = 0; i < n - 1; i++) m.push((pts[i + 1][1] - pts[i][1]) / (pts[i + 1][0] - pts[i][0]));
    d[0] = m[0];
    d[n - 1] = m[n - 2];
    for (let i = 1; i < n - 1; i++) d[i] = m[i - 1] * m[i] <= 0 ? 0 : 2 / (1 / m[i - 1] + 1 / m[i]);
    let s = `M${f1(pts[0][0])} ${f1(pts[0][1])}`;
    for (let i = 0; i < n - 1; i++) {
      const h = (pts[i + 1][0] - pts[i][0]) / 3;
      s += `C${f1(pts[i][0] + h)} ${f1(pts[i][1] + d[i] * h)} ${f1(pts[i + 1][0] - h)} ${f1(pts[i + 1][1] - d[i + 1] * h)} ${f1(pts[i + 1][0])} ${f1(pts[i + 1][1])}`;
    }
    return s;
  }
  function gfxWide(spec, opts, style) {
    const on = opts.on !== false, values = opts.values;
    const c = metalColors(spec, style), id = 'gpm' + (++metalCount);
    const W = 168, H = 200, rx = style === 'thrash' ? 7 : 10;
    const accent = style === 'thrash' ? '#ffd400' : c.light;
    // the set drawn: the one the enum's value picks (by rank), else `faders`
    const fs = spec.fader_sets;
    const rank = fs && fs.param ? Math.round(valueOf(fs.param, values)) : 0;
    const faders = (fs && fs.sets[rank]) || spec.faders || [];
    const lvl = spec.level_fader;
    // 11 bands + level at a 12.5 px pitch with 6 px margins; fewer bands centred at an 18 px pitch
    const pitch = faders.length > 7 ? 12.5 : 18, gap = lvl ? 6 : 0;
    const span = pitch * (faders.length + (lvl ? 1 : 0)) + gap, x0 = (W - span) / 2;
    const S = WIDE_SLOT;
    const capY = p => S.bottom - (S.bottom - S.top) * Math.max(0, Math.min(1, (valueOf(p, values) - p.min) / ((p.max - p.min) || 1)));
    const slider = (p, x, label, capFill, lineCol) => {
      const y = capY(p);
      return `<g class="gp-fader" data-param="${esc(p.id)}">
  <path d="M${f1(x)} ${S.top}V${S.bottom}" stroke="#000" stroke-opacity=".75" stroke-width="1.6" stroke-linecap="round"/>
  <path d="M${f1(x + .8)} ${S.top}V${S.bottom}" stroke="${c.engraveLight}" stroke-opacity=".35" stroke-width=".4"/>
  <rect x="${f1(x - 4.5)}" y="${f1(y - 2.4)}" width="9" height="6" rx="1" fill="#000" opacity=".45"/>
  <rect x="${f1(x - 4.5)}" y="${f1(y - 3)}" width="9" height="6" rx="1" fill="${capFill}" stroke="#000" stroke-opacity=".55" stroke-width=".5"/>
  <path d="M${f1(x - 3.6)} ${f1(y)}H${f1(x + 3.6)}" stroke="${lineCol}" stroke-width=".9"/>
  <text x="${f1(x)}" y="${S.bottom + 8}" text-anchor="middle" font-family="${FONT.gfx}" font-size="4.5" font-weight="700" fill="${c.ink}">${esc(label)}</text></g>`;
    };
    const capFill = style === 'thrash' ? '#141414' : 'url(#gp-knob-alu)';
    const capLine = style === 'thrash' ? '#ffd400' : mix(c.light, '#000', .15);
    let sliders = '';
    const pts = [];
    faders.forEach((p, i) => {
      const x = x0 + pitch * (i + .5);
      sliders += slider(p, x, p.label || shortLabel(p.name), capFill, capLine);
      pts.push([x, capY(p)]);
    });
    if (lvl) sliders += slider(lvl, x0 + pitch * (faders.length + .5) + gap, 'LVL', accent, style === 'thrash' ? '#000' : mix(c.hue, '#000', .6));
    // in a group of its own, with the faders it passes through and their exact places: gfx-ui's build-ui.js
    // cuts it out and the editor draws it from the caps
    const curve = on && pts.length > 1
      ? `<g class="gp-curve" data-params="${faders.map(p => esc(p.id)).join(' ')}" data-x="${pts.map(q => q[0]).join(' ')}" data-slot="${S.top} ${S.bottom}"><path d="${monotonePath(pts)}" fill="none" stroke="${c.light}" stroke-width="1.6" opacity=".55" filter="url(#gp-glow-soft)"/><path d="${monotonePath(pts)}" fill="none" stroke="${mix(c.light, '#fff', .5)}" stroke-width=".7"/></g>` : '';

    const body = style === 'thrash'
      ? `<rect x="0" y="5" width="${W}" height="${H}" rx="${rx}" fill="${c.base}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#${id}-b)"/>`
      : `<rect x="0" y="5" width="${W}" height="${H}" rx="${rx}" fill="${c.base}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#${id}-b)"/>
  <rect x="4" y="4" width="${W - 8}" height="${H - 8}" rx="${rx - 3}" fill="url(#${id}-f)"/>
  <rect x="4" y="4" width="${W - 8}" height="${H - 8}" rx="${rx - 3}" fill="url(#gp-brush-lines)"/>`;
    const finish = style === 'thrash'
      ? `<rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#gp-gloss)"/>
<rect x="5" y="${H - 40}" width="${W - 10}" height="34" rx="3" fill="url(#gp-plate)" stroke="#000" stroke-width=".8"/>
${[[9, H - 36], [W - 9, H - 36], [9, H - 10], [W - 9, H - 10]].map(([x, yy]) => `<circle cx="${x}" cy="${yy}" r="1.4" fill="url(#gp-chrome)"/>`).join('')}`
      : `<rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#gp-anod-sheen)"/>
<rect x=".6" y=".6" width="${W - 1.2}" height="${H - 1.2}" rx="${rx - .6}" fill="none" stroke="${c.rim}" stroke-opacity=".7" stroke-width="1"/>
<rect x="4" y="4" width="${W - 8}" height="${H - 8}" rx="${rx - 3}" fill="none" stroke="${c.base}" stroke-opacity=".5" stroke-width=".8"/>`;

    // below the sliders: the name, then the rune (left of the switch), the switch and the LED (right)
    const sy = H - 21, gx = W / 2 - 46, gsize = 18, ch = gsize + 10, cw = gsize + 22;
    const g = { x: gx, y: sy, cw, ch };
    const rune = (style === 'thrash'
      ? `<path d="${pill(gx - cw / 2, sy - ch / 2, cw, ch)}" fill="#0b0707" stroke="#000" stroke-width="2"/>`
      : `<path d="${pill(gx - cw / 2, sy - ch / 2, cw, ch)}" fill="${mix(c.hue, '#000', .88)}" stroke="${c.rim}" stroke-opacity=".6" stroke-width="1"/>`) +
      (on ? glyphAt(spec.glyph, gx, sy, gsize, c.light, 2.6, 'filter="url(#gp-glow)" opacity=".95"') + glyphAt(spec.glyph, gx, sy, gsize, mix(c.light, '#fff', .75), 1.2)
        : glyphAt(spec.glyph, gx, sy, gsize, mix(c.hue, '#000', .45), 1.8));
    const name = spec.name.toUpperCase();
    const nameY = S.bottom + 34;
    const nameSvg = style === 'thrash'
      ? `<text x="${W / 2}" y="${nameY}" text-anchor="middle" font-family="${FONT.nam}" font-size="15" font-weight="900" letter-spacing="1" fill="#fff" stroke="#000" stroke-width="1.8" paint-order="stroke" transform="rotate(-3 ${W / 2} ${nameY - 4})">${esc(name)}</text>`
      : `<text x="${W / 2}" y="${nameY}" text-anchor="middle" font-family="${FONT.nam}" font-size="14" font-weight="900" letter-spacing="2.5" fill="${c.ink}">${esc(name)}</text>`;
    const ledX = W / 2 + 46;
    const led = `<circle cx="${ledX}" cy="${sy}" r="3" fill="#000" opacity=".7"/><circle cx="${ledX}" cy="${sy}" r="2.3" fill="${on ? c.light : mix(c.hue, '#000', .7)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>${on ? `<circle cx="${ledX}" cy="${sy}" r="1.3" fill="#fff"/>` : ''}`;

    return `<svg class="gp-pedal gp-gfx gp-wide gp-${style}${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" ` +
      `role="img" aria-label="${esc(spec.name)} — golem-fx ${esc(spec.crate)}" data-crate="${esc(spec.crate)}" data-style="${style}" data-layout="${rank}">
<defs>
  <linearGradient id="${id}-b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c.top}"/><stop offset=".48" stop-color="${c.hue}"/><stop offset="1" stop-color="${c.bottom}"/></linearGradient>
  <linearGradient id="${id}-f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c.faceTop}"/><stop offset="1" stop-color="${c.faceBottom}"/></linearGradient>
  <clipPath id="${id}-c"><rect x="${style === 'thrash' ? 0 : 4}" y="${style === 'thrash' ? 0 : 4}" width="${style === 'thrash' ? W : W - 8}" height="${style === 'thrash' ? H : H - 8}" rx="${style === 'thrash' ? rx : rx - 3}"/></clipPath>
</defs>
<g filter="url(#gp-shadow)">
  ${jacks(W, 40)}
  ${body}
</g>
<g clip-path="url(#${id}-c)">${motifSvg(MOTIF[spec.crate], style, W, H, g, c)}</g>
${finish}
${sliders}
${curve}
${nameSvg}
${rune}
${led}
${stompSwitch(W / 2, sy, 8.5)}
<text x="${W - 8}" y="${H - 4}" text-anchor="end" font-family="${FONT.gfx}" font-size="5" font-weight="700" fill="${style === 'thrash' ? '#fff' : c.ink}" fill-opacity=".6">golem fx</text>
</svg>`;
  }

  // the wah in metal: the same treadle, the body in the finish, the rune lit in the family's light
  function gfxTreadleMetal(spec, opts, style) {
    const on = opts.on !== false;
    const c = metalColors(spec, style), id = 'gpm' + (++metalCount);
    const W = 124, H = 228, rx = style === 'thrash' ? 8 : 12;
    const knobs = spec.knobs || [], sels = spec.selectors || [];
    let parts = '';
    knobs.forEach((p, i) => { parts += knobMetal(style, c.ink)(26 + i * 22, H - 26, 7, Object.assign({}, p, { name: '' })); });
    sels.forEach(p => { parts += selectorClay(W - 26, H - 26, 6, p, style === 'thrash' ? '#ffd400' : c.light, null, c.ink); });
    return `<svg class="gp-pedal gp-gfx gp-treadle gp-${style}${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" role="img" aria-label="${esc(spec.name)} — golem-fx ${esc(spec.crate)}" data-crate="${esc(spec.crate)}" data-style="${style}">
<defs><linearGradient id="${id}-b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c.top}"/><stop offset=".48" stop-color="${c.hue}"/><stop offset="1" stop-color="${c.bottom}"/></linearGradient></defs>
<g filter="url(#gp-shadow)">
  ${jacks(W, 150)}
  <rect x="0" y="8" width="${W}" height="${H}" rx="${rx}" fill="${c.base}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#${id}-b)"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="${rx}" fill="url(#${style === 'thrash' ? 'gp-gloss' : 'gp-anod-sheen'})"/>
</g>
${style === 'thrash' ? `<rect x="6" y="${H - 44}" width="${W - 12}" height="38" rx="3" fill="url(#gp-plate)" stroke="#000" stroke-width=".8"/>` : `<rect x=".6" y=".6" width="${W - 1.2}" height="${H - 1.2}" rx="${rx - .6}" fill="none" stroke="${c.rim}" stroke-opacity=".7"/>`}
<g filter="url(#gp-shadow-small)">
  <path d="M12 14 Q${W / 2} 4 ${W - 12} 14 L${W - 9} ${H - 50} Q${W / 2} ${H - 44} 9 ${H - 50}Z" fill="${mix(c.hue, '#000', .55)}"/>
  <rect x="22" y="22" width="${W - 44}" height="${H - 94}" rx="6" fill="#121212"/>
  <rect x="22" y="22" width="${W - 44}" height="${H - 94}" rx="6" fill="url(#gp-grip)"/>
</g>
${on ? glyphAt(spec.glyph, W / 2, 86, 40, c.light, 2.8, 'filter="url(#gp-glow)"') + glyphAt(spec.glyph, W / 2, 86, 40, mix(c.light, '#fff', .75), 1.3) : glyphAt(spec.glyph, W / 2, 86, 40, mix(c.hue, '#000', .3), 2)}
<text x="${W / 2}" y="${H - 56}" text-anchor="middle" font-family="${FONT.nam}" font-size="13" font-weight="900" letter-spacing="2.5" fill="${style === 'thrash' ? '#fff' : c.ink}"${style === 'thrash' ? ' stroke="#000" stroke-width="1.6" paint-order="stroke"' : ''}>${esc(spec.name.toUpperCase())}</text>
<circle cx="${W / 2}" cy="${H - 44}" r="2.4" fill="${on ? c.light : mix(c.hue, '#000', .7)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
${parts}
</svg>`;
  }

  // ---------- gfx: blackwork (gfx-met, gfx-emet, gfx-shem) ----------
  // Black lacquer, white engraving, one engraved skull whose eyes light in the pedal's colour when it
  // is on: the only colour. One discreet motif per pedal. Drawn on a 200 × 330 grid, scaled to the
  // stomp's 112-wide body so it stands with the other golem-fx pedals.
  const BW_INK = '#ecebe6';
  const BW_EYES = { 'gfx-met': ['#22ff66', '#b9ffd0'], 'gfx-emet': ['#ff2a1a', '#ffd0c8'], 'gfx-shem': ['#ffaa00', '#fff0cc'], 'gfx-golem': ['#a259ff', '#e9dcff'] };
  const BW_MOTIF = {
    'gfx-met': `<g fill="none" stroke="${BW_INK}" stroke-linecap="round" stroke-width="1">
  <path d="M22 172 C40 168 52 176 70 172 M130 172 C148 168 160 176 178 172"/><path d="M22 175 C40 179 52 171 70 175 M130 175 C148 179 160 171 178 175"/>
  <path d="M33 168 l6 10 M39 168 l-6 10 M53 168 l6 10 M59 168 l-6 10 M141 168 l6 10 M147 168 l-6 10 M161 168 l6 10 M167 168 l-6 10"/></g>`,
    'gfx-emet': `<g fill="none" stroke="${BW_INK}" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.2">
  <path d="M62 168 C54 152 62 140 58 124 C68 134 72 142 72 150 C74 136 80 128 78 112 C88 124 90 134 88 144"/>
  <path d="M138 168 C146 152 138 140 142 124 C132 134 128 142 128 150 C126 136 120 128 122 112 C112 124 110 134 112 144"/>
  <path d="M100 126 C96 116 102 108 100 98 C106 106 106 114 104 122"/></g>`,
    'gfx-golem': `<g fill="none" stroke="${BW_INK}" stroke-linecap="round" stroke-width="1.1">
  <path d="M58 150 A44 44 0 0 0 58 196 M48 142 A56 56 0 0 0 48 204 M38 134 A68 68 0 0 0 38 212"/>
  <path d="M142 150 A44 44 0 0 1 142 196 M152 142 A56 56 0 0 1 152 204 M162 134 A68 68 0 0 1 162 212"/></g>`,
    'gfx-shem': `<g fill="none" stroke="${BW_INK}" stroke-linecap="round" stroke-width=".9">
  <path d="M100 168 L30 128 M100 168 L36 112 M100 168 L48 100 M100 168 L170 128 M100 168 L164 112 M100 168 L152 100"/></g>`,
  };
  // knob places on the 200 × 330 grid: [x, y, radius] per front knob, in face order
  const BW_LAYOUT = {
    'gfx-met': [[100, 70, 23], [40, 40, 10], [160, 40, 10]],
    'gfx-emet': [[50, 46, 16], [100, 66, 13], [150, 46, 16]],
    'gfx-shem': [[100, 62, 23]],
    'gfx-golem': [[52, 50, 16], [148, 50, 16], [72, 96, 10], [128, 96, 10]],
  };
  const BW_SKULL = `<g class="gp-skull">
  <path d="M100 126 C78 126 66 142 66 162 C66 176 72 184 76 188 L76 198 C76 202 80 204 84 204 L86 212 L114 212 L116 204 C120 204 124 202 124 198 L124 188 C128 184 134 176 134 162 C134 142 122 126 100 126Z" fill="${BW_INK}" stroke="#000" stroke-width="1.2"/>
  <path d="M78 161 C78 152 86 150 92 154 C96 157 96 166 92 170 C88 174 80 172 78 166Z M122 161 C122 152 114 150 108 154 C104 157 104 166 108 170 C112 174 120 172 122 166Z" fill="#000"/>
  <path d="M100 173 L95 185 Q100 187 105 185Z" fill="#000"/>
  <path d="M80 198 Q100 203 120 198 M86 205 H114 M90 199 V211 M95 200 V212 M100 200 V212 M105 200 V212 M110 199 V211" fill="none" stroke="#000" stroke-width="1.1" stroke-linecap="round"/>
  <path d="M70 170 l5 -2 M71 176 l5 -2 M130 170 l-5 -2 M129 176 l-5 -2" fill="none" stroke="#000" stroke-width=".8" stroke-linecap="round"/></g>`;

  function knobBlackwork(x, y, r, p) {
    const a = angleOf(p);
    const big = r >= 15;
    const label = String(p.name || p.id).toUpperCase();
    const ly = big ? y + r + 15 : y + r + 10;
    return `<g class="gp-knob" data-param="${esc(p.id)}" transform="translate(${x} ${y})">
  <circle cy="2" r="${r + 2}" fill="#000" opacity=".7"/><circle r="${r}" fill="url(#gp-bw-knob)" stroke="#000" stroke-width="${big ? 2 : 1.4}"/>
  ${big ? `<circle r="${r - 1.5}" fill="none" stroke="#5a5a5a" stroke-width="1.5" stroke-dasharray=".8 1.4"/>` : ''}
  <line y1="${-r * .26}" y2="${-r * .87}" stroke="${BW_INK}" stroke-width="${big ? 3 : 1.8}" stroke-linecap="round" transform="rotate(${a.toFixed(1)})"/></g>
<text x="${x}" y="${ly}" text-anchor="middle" font-family="${FONT.nam}" font-weight="900" font-size="${big ? 8 : 7}" letter-spacing="1" fill="${BW_INK}">${esc(label)}</text>`;
  }

  function gfxPedalBlackwork(spec, opts) {
    const on = opts.on !== false;
    const W = 112, H = 188, s = W / 192;
    const [eye, core] = BW_EYES[spec.crate] || ['#ffffff', '#ffffff'];
    const layout = BW_LAYOUT[spec.crate] || [];
    const knobs = (spec.knobs || []).map((p, i) => {
      const [x, y, r] = layout[i] || [40 + 120 * (i % 2), 40, 10];
      return knobBlackwork(x, y, r, p);
    }).join('');
    const eyes = on
      ? `<circle cx="87" cy="162" r="4.5" fill="${eye}" filter="url(#gp-bw-glow)"/><circle cx="113" cy="162" r="4.5" fill="${eye}" filter="url(#gp-bw-glow)"/>
  <circle cx="87" cy="162" r="2.4" fill="${core}"/><circle cx="113" cy="162" r="2.4" fill="${core}"/>`
      : `<circle cx="87" cy="162" r="2.4" fill="${mix(eye, '#000', .8)}"/><circle cx="113" cy="162" r="2.4" fill="${mix(eye, '#000', .8)}"/>`;
    return `<svg class="gp-pedal gp-gfx gp-blackwork${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" ` +
      `role="img" aria-label="${esc(spec.name)} — golem-fx ${esc(spec.crate)}" data-crate="${esc(spec.crate)}" data-style="blackwork">
<g filter="url(#gp-shadow)">
  ${jacks(W, 40)}
  <rect x="0" y="4" width="${W}" height="${H}" rx="8" fill="#000"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="8" fill="url(#gp-bw-body)"/>
</g>
<g transform="translate(${(-4 * s).toFixed(2)} ${(-4 * s).toFixed(2)}) scale(${s.toFixed(4)})">
  <rect x="4" y="4" width="192" height="322" rx="14" fill="url(#gp-bw-gloss)"/>
  <rect x="11" y="11" width="178" height="308" rx="10" fill="none" stroke="${BW_INK}" stroke-width="1.2"/>
  ${BW_MOTIF[spec.crate] || ''}
  ${BW_SKULL}
  <g class="gp-eyes">${eyes}</g>
  ${knobs}
  <text x="100" y="258" text-anchor="middle" font-family="${FONT.blackletter}" font-size="40" fill="${BW_INK}" letter-spacing="2">${esc(spec.name)}</text>
  ${stompSwitch(100, 286, 12)}
  <text x="100" y="314" text-anchor="middle" font-family="${FONT.nam}" font-weight="900" font-size="7" letter-spacing="2.5" fill="${BW_INK}">GOLEM · FX</text>
</g>
</svg>`;
  }

  // the wah: a treadle on a cast base
  function gfxTreadle(spec, opts) {
    const on = opts.on !== false;
    const hue = hueOf(spec.color, spec.category);
    const body = mix(hue, '#3b342e', .5), bodyDark = mix(body, '#000', .5), rune = mix(hue, '#fff', .25);
    const W = 124, H = 228;
    const knobs = spec.knobs || [], sels = spec.selectors || [];
    let parts = '';
    knobs.forEach((p, i) => { parts += knobClay(26 + i * 22, H - 22, 7, p, rune, ''); });
    sels.forEach(p => { parts += selectorClay(W - 26, H - 24, 6, p, rune, .7); });
    const ledOn = on ? mix(hue, '#fff', .35) : '#2a211c';
    return `<svg class="gp-pedal gp-gfx gp-treadle${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" role="img" aria-label="${esc(spec.name)} — golem-fx ${esc(spec.crate)}" data-crate="${esc(spec.crate)}">
<g filter="url(#gp-shadow)">
  ${jacks(W, 150)}
  <rect x="0" y="8" width="${W}" height="${H}" rx="14" fill="${bodyDark}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="${body}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="#000" filter="url(#gp-clay)" opacity=".55"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="url(#gp-side)"/>
</g>
<g filter="url(#gp-shadow-small)">
  <path d="M12 14 Q${W / 2} 4 ${W - 12} 14 L${W - 9} ${H - 46} Q${W / 2} ${H - 40} 9 ${H - 46}Z" fill="${mix(body, '#fff', .08)}"/>
  <path d="M12 14 Q${W / 2} 4 ${W - 12} 14 L${W - 9} ${H - 46} Q${W / 2} ${H - 40} 9 ${H - 46}Z" fill="url(#gp-sheen)"/>
  <rect x="22" y="22" width="${W - 44}" height="${H - 90}" rx="6" fill="#141110"/>
  <rect x="22" y="22" width="${W - 44}" height="${H - 90}" rx="6" fill="url(#gp-grip)"/>
</g>
${glyphAt(spec.glyph, W / 2, 86, 40, bodyDark, 2.2)}
${on ? glyphAt(spec.glyph, W / 2, 86, 40, rune, 2.4, 'filter="url(#gp-glow)"') + glyphAt(spec.glyph, W / 2, 86, 40, mix(rune, '#fff', .55), 1.1) : ''}
<text x="${W / 2}" y="${H - 52}" text-anchor="middle" font-family="${FONT.gfx}" font-size="12" font-weight="700" fill="#000" fill-opacity=".7">${esc(spec.name.toLowerCase())}</text>
<circle cx="${W / 2}" cy="${H - 26}" r="2.6" fill="${ledOn}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/><circle cx="${W / 2}" cy="${H - 26}" r="2.6" fill="url(#gp-jewel)"/>
${parts}
<text x="${W - 10}" y="${H - 5}" text-anchor="end" font-family="${FONT.gfx}" font-size="5.6" font-weight="700" fill="#000" fill-opacity=".45">golem fx</text>
</svg>`;
  }

  // ---------- generic: enamel ----------
  function knobEnamel(cx, cy, r, p) {
    const a = angleOf(p);
    const [px, py] = polar(cx, cy, r * .95, a), [qx, qy] = polar(cx, cy, r * .45, a);
    return `<g class="gp-knob" data-param="${esc(p.id)}"><circle cx="${cx}" cy="${cy + 1.6}" r="${r + 2.4}" fill="#000" opacity=".35"/>
  <circle cx="${cx}" cy="${cy}" r="${r + 2.4}" fill="#16130f"/>
  <circle cx="${cx}" cy="${cy}" r="${r + 2.4}" fill="none" stroke="#000" stroke-width="1.6" stroke-dasharray=".8 1.2"/>
  <circle cx="${cx}" cy="${cy}" r="${r * .62}" fill="url(#gp-chrome)"/>
  <path d="M${qx.toFixed(2)} ${qy.toFixed(2)}L${px.toFixed(2)} ${py.toFixed(2)}" stroke="#f3ead2" stroke-width="1.5" stroke-linecap="round"/>
  <text x="${cx}" y="${cy - r - 5.5}" text-anchor="middle" font-family="${FONT.enamelSmall}" font-size="6.2" font-weight="700" fill="#f3ead2" fill-opacity=".92">${esc(enamelLabel(p))}</text></g>`;
  }

  function enamelLabel(p) {
    const n = shortLabel(p.name);
    return n.length <= 9 ? n : String(p.id || n).replace(/_/g, ' ').slice(0, 9);
  }
  // the name printed on an enamel box: the block's name without its parenthesis, else its short name
  function enamelName(block) {
    const n = String(block.name || '').replace(/\s*\(.*\)\s*/g, '').trim();
    return n && n.length <= 13 ? n : (block.short || n);
  }

  // block: a catalogue entry ({type, name, short, color, category, params})
  // a 5-pin DIN socket on the top edge: the mark of a block golem drives over MIDI (hardware in the rig)
  function dinSocket(cx, y) {
    const pins = [-150, -120, -90, -60, -30].map(d => polar(cx, y + 9, 4.6, d))
      .map(([x, yy]) => `<circle cx="${x.toFixed(2)}" cy="${yy.toFixed(2)}" r=".75" fill="#9a9a9a"/>`).join('');
    return `<g class="gp-din"><rect x="${cx - 10}" y="${y - 6}" width="20" height="8" rx="1.5" fill="#1d1d1d"/>
  <circle cx="${cx}" cy="${y + 9}" r="8.2" fill="url(#gp-chrome)"/><circle cx="${cx}" cy="${y + 9}" r="6.6" fill="#141414"/>${pins}
  <rect x="${cx - 1}" y="${y + 13.5}" width="2" height="1.8" fill="#9a9a9a"/></g>`;
  }
  const isMidi = block => block && block.engine === 'midi';

  // a MIDI-driven pitch pedal (whammy-dt): an enamel treadle, the glyph on the badge, the DIN on top
  function enamelTreadle(block, opts) {
    const on = opts.on !== false;
    const hue = hueOf(block.color, block.category);
    const body = mix(mix(hue, '#77704f', .52), '#000', .08), bodyDark = mix(body, '#000', .5), cream = '#f3ead2';
    const W = 124, H = 228;
    const label = enamelName(block);
    const fs = label.length > 11 ? 10.5 : label.length > 8 ? 12 : 14;
    const lamp = on ? '#ff3b2a' : '#4a1410';
    return `<svg class="gp-pedal gp-enamel gp-treadle gp-midi${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" role="img" aria-label="${esc(block.name)}" data-type="${esc(block.type)}">
<g filter="url(#gp-shadow)">
  ${jacks(W, 150, '#1d1d1d')}
  <rect x="0" y="8" width="${W}" height="${H}" rx="8" fill="${bodyDark}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="8" fill="${body}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="8" fill="#fff" filter="url(#gp-hammer)" opacity=".42"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="8" fill="url(#gp-sheen)"/>
</g>
${dinSocket(W / 2, -2)}
<g filter="url(#gp-shadow-small)">
  <path d="M12 22 Q${W / 2} 13 ${W - 12} 22 L${W - 10} ${H - 50} Q${W / 2} ${H - 44} 10 ${H - 50}Z" fill="${mix(body, '#000', .25)}"/>
  <rect x="20" y="30" width="${W - 40}" height="${H - 96}" rx="5" fill="#141110"/>
  <rect x="20" y="30" width="${W - 40}" height="${H - 96}" rx="5" fill="url(#gp-grip)"/>
</g>
<g filter="url(#gp-shadow-small)"><circle cx="${W / 2}" cy="92" r="21" fill="${cream}"/></g>
<circle cx="${W / 2}" cy="92" r="18.5" fill="none" stroke="${bodyDark}" stroke-width=".8"/>
${glyphAt(block.type, W / 2, 92, 25, mix(hue, '#000', .35), 2)}
<text x="${W / 2}" y="${H - 30 + fs / 3}" text-anchor="middle" font-family="${FONT.enamel}" font-size="${fs}" fill="${cream}" transform="rotate(-4 ${W / 2} ${H - 30})">${esc(label)}</text>
<circle cx="${W - 16}" cy="${H - 14}" r="3.6" fill="#2a2a2a"/><circle cx="${W - 16}" cy="${H - 14}" r="2.8" fill="${lamp}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/><circle cx="${W - 16}" cy="${H - 14}" r="2.8" fill="url(#gp-jewel)"/>
<text x="14" y="${H - 10}" font-family="${FONT.enamelSmall}" font-size="6" font-weight="700" letter-spacing="1" fill="${cream}" fill-opacity=".7">MIDI</text>
</svg>`;
  }

  function genericPedal(block, opts) {
    opts = opts || {};
    block = withValues(block, opts.values || opts.params);
    if (isMidi(block) && block.category === 'pitch') return enamelTreadle(block, opts);
    const on = opts.on !== false;
    const hue = hueOf(block.color, block.category);
    // aged enamel: the hue pulled toward olive and cream, never neon
    const body = mix(mix(hue, '#77704f', .52), '#000', .08);
    const bodyDark = mix(body, '#000', .5);
    const cream = '#f3ead2';
    const knobs = (block.params || []).filter(p => typeof p.min === 'number' && typeof p.max === 'number' && p.max > p.min).slice(0, 3);
    const W = 112, H = 200;
    const kr = knobs.length === 1 ? 12 : knobs.length === 2 ? 10 : 8.5;
    let ks = '';
    knobs.forEach((p, i) => { ks += knobEnamel(W * (i + .5) / knobs.length, 40, kr, p); });
    const label = enamelName(block);
    const fs = label.length > 11 ? 10.5 : label.length > 8 ? 12 : label.length > 6 ? 13.5 : 15;
    const lamp = on ? '#ff3b2a' : '#4a1410';
    return `<svg class="gp-pedal gp-enamel${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" role="img" aria-label="${esc(block.name)}" data-type="${esc(block.type)}">
<g filter="url(#gp-shadow)">
  ${jacks(W, 40, '#1d1d1d')}
  <rect x="0" y="6" width="${W}" height="${H}" rx="6" fill="${bodyDark}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="${body}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="#fff" filter="url(#gp-hammer)" opacity=".42"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="url(#gp-sheen)"/>
</g>
<rect x="6" y="6" width="${W - 12}" height="${H - 12}" rx="3" fill="none" stroke="${cream}" stroke-opacity=".7" stroke-width="1.1"/>
<rect x="8.5" y="8.5" width="${W - 17}" height="${H - 17}" rx="2" fill="none" stroke="${cream}" stroke-opacity=".35" stroke-width=".5"/>
${[[4, 4], [W - 4, 4], [4, H - 4], [W - 4, H - 4]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.1" fill="url(#gp-chrome)"/><path d="M${x - 1.3} ${y}h2.6" stroke="#333" stroke-width=".6"/>`).join('')}
${ks}
<g filter="url(#gp-shadow-small)"><circle cx="${W / 2}" cy="92" r="19" fill="${cream}"/></g>
<circle cx="${W / 2}" cy="92" r="16.5" fill="none" stroke="${bodyDark}" stroke-width=".8"/>
${glyphAt(block.type, W / 2, 92, 22, mix(hue, '#000', .35), 2)}
<text x="${W / 2}" y="${128 + fs / 3}" text-anchor="middle" font-family="${FONT.enamel}" font-size="${fs}" fill="${cream}" transform="rotate(-4 ${W / 2} 128)">${esc(label)}</text>
${isMidi(block) ? dinSocket(W / 2, -2) + `<text x="${W - 12}" y="${H - 8}" text-anchor="end" font-family="${FONT.enamelSmall}" font-size="5.6" font-weight="700" letter-spacing="1" fill="${cream}" fill-opacity=".7">MIDI</text>` : ''}
<circle cx="${W / 2}" cy="152" r="4.4" fill="#2a2a2a"/>
<circle cx="${W / 2}" cy="152" r="3.4" fill="${lamp}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
<circle cx="${W / 2}" cy="152" r="3.4" fill="url(#gp-jewel)"/>
${stompSwitch(W / 2, H - 24, 10)}
</svg>`;
  }

  // ---------- NAM: specimen ----------
  const NAM_VOICE = {
    overdrive: { glow: '#ffb03a', label: 'overdrive' }, distortion: { glow: '#ff6a3c', label: 'distortion' },
    fuzz: { glow: '#ff4fa3', label: 'fuzz' }, boost: { glow: '#ffe06a', label: 'boost' }, bass: { glow: '#6aa8ff', label: 'bass' },
    preamp: { glow: '#ffa64d', label: 'preamp' }, comp: { glow: '#5fe0d0', label: 'compressor' }, plugin: { glow: '#e8ecf2', label: 'captured plugin' },
  };

  // what the glass shows: the capture's lattice, a valve, or a needle
  function specimenWindow(x, y, w, h, kind, glow, on, seed) {
    let inner = '';
    if (kind === 'preamp') {
      const cx = x + w / 2, cy = y + h / 2 + 2;
      inner = `<rect x="${cx - 11}" y="${cy - 18}" width="22" height="34" rx="11" fill="none" stroke="#9fb2bf" stroke-opacity=".5"/>
        <path d="M${cx - 6} ${cy + 12}V${cy - 6}M${cx + 6} ${cy + 12}V${cy - 6}M${cx - 6} ${cy - 6}h12" stroke="#7d8a94" stroke-width="1"/>
        ${on ? `<ellipse cx="${cx}" cy="${cy + 2}" rx="6" ry="9" fill="${glow}" filter="url(#gp-glow)" opacity=".9"/><path d="M${cx - 3} ${cy + 8}c1-6 5-6 6-12" stroke="#fff4dc" stroke-width=".8" fill="none"/>` : ''}`;
    } else if (kind === 'comp') {
      const cx = x + w / 2, cy = y + h - 6, r = h - 14;
      const a = on ? -20 : -50, [nx, ny] = polar(cx, cy, r, a);
      let marks = '';
      for (let i = 0; i <= 8; i++) { const d = -55 + i * 13.75, [x1, y1] = polar(cx, cy, r - 3, d), [x2, y2] = polar(cx, cy, r, d); marks += `<path d="M${x1} ${y1}L${x2} ${y2}"/>`; }
      inner = `${on ? `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${glow}" opacity=".18"/>` : ''}
        <g stroke="${glow}" stroke-opacity="${on ? .9 : .35}" stroke-width=".8">${marks}</g>
        <path d="M${cx} ${cy}L${nx} ${ny}" stroke="#ff5a3c" stroke-width="1"/><circle cx="${cx}" cy="${cy}" r="2" fill="#222"/>`;
    } else {
      // the lattice: 4 layers of nodes, deterministic from the seed
      let rnd = seed || 1;
      const R = () => (rnd = (rnd * 16807) % 2147483647) / 2147483647;
      const cols = [3, 5, 5, 2], pts = cols.map((n, ci) => Array.from({ length: n }, (_, i) =>
        [x + w * (ci + .5) / cols.length, y + h * (i + .5) / n + (R() - .5) * 3]));
      let lines = '';
      for (let c = 0; c < pts.length - 1; c++) pts[c].forEach(a => pts[c + 1].forEach(b => {
        if (R() < .7) lines += `<path d="M${a[0].toFixed(1)} ${a[1].toFixed(1)}L${b[0].toFixed(1)} ${b[1].toFixed(1)}" stroke-opacity="${(.15 + R() * .5).toFixed(2)}"/>`;
      }));
      const nodes = pts.flat().map(([px, py]) => `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="1.6"/>`).join('');
      inner = `<g stroke="${glow}" stroke-width=".55" opacity="${on ? 1 : .35}">${lines}</g>
        ${on ? `<g fill="${glow}" filter="url(#gp-glow)" opacity=".8">${nodes}</g>` : ''}
        <g fill="${on ? mix(glow, '#fff', .5) : '#56606a'}">${nodes}</g>`;
    }
    return `<rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${h + 6}" rx="5" fill="#1a1d20" stroke="#000" stroke-opacity=".6"/>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="url(#gp-glass)"/>
  <clipPath id="gp-win-${seed}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3"/></clipPath>
  <g clip-path="url(#gp-win-${seed})">${inner}</g>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="url(#gp-glass-glare)"/>`;
  }

  function knobAlu(cx, cy, r, p, label, ink) {
    const a = angleOf(p || { min: 0, max: 1, default: .5 });
    const [px, py] = polar(cx, cy, r * .85, a);
    return `<g class="gp-knob"><circle cx="${cx}" cy="${cy + 1.2}" r="${r}" fill="#000" opacity=".4"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob-alu)"/>
  <circle cx="${cx}" cy="${cy}" r="${r - .6}" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="1.2" stroke-dasharray=".6 .9"/>
  <path d="M${cx} ${cy}L${px.toFixed(2)} ${py.toFixed(2)}" stroke="#111" stroke-width="1.3" stroke-linecap="round"/>
  ${label ? `<text x="${cx}" y="${cy + r + 8}" text-anchor="middle" font-family="${FONT.nam}" font-size="6.6" font-weight="600" letter-spacing=".5" fill="${ink || '#1d2226'}">${esc(label)}</text>` : ''}</g>`;
  }

  let seedCounter = 1;
  // a NAM capture pedal. block: pedal-nam / preamp-nam / comp-nam / capture-module; opts.archetype: a
  // catalogue pedal archetype ({name, short, family}) when the capture was picked from one
  function namPedal(type, opts) {
    opts = opts || {};
    const on = opts.on !== false;
    const arch = opts.archetype;
    const kind = type === 'preamp-nam' ? 'preamp' : type === 'comp-nam' ? 'comp' : type === 'capture-module' ? 'plugin' : (arch && arch.family) || 'overdrive';
    const voice = NAM_VOICE[kind] || NAM_VOICE.overdrive;
    const W = 112, H = 200, seed = seedCounter++;
    const title = opts.title || (arch ? arch.short || arch.name : { preamp: 'preamp', comp: 'comp', plugin: 'capture' }[kind] || 'capture');
    return `<svg class="gp-pedal gp-nam${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" role="img" aria-label="NAM capture — ${esc(title)}" data-type="${esc(type)}">
<g filter="url(#gp-shadow)">
  ${jacks(W, 40, '#3a3f44')}
  <rect x="0" y="6" width="${W}" height="${H}" rx="4" fill="#4a5056"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="4" fill="url(#gp-brushed)"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="4" fill="url(#gp-brush-lines)"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="4" fill="url(#gp-sheen)" opacity=".6"/>
</g>
${[[6, 6], [W - 6, 6], [6, H - 6], [W - 6, H - 6]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="#6d747c"/><circle cx="${x - .4}" cy="${y - .4}" r=".8" fill="#eef1f4"/>`).join('')}
${specimenWindow(14, 16, W - 28, 62, kind, voice.glow, on, seed)}
<rect x="14" y="88" width="${W - 28}" height="22" rx="2" fill="#15181b"/>
<text x="20" y="103.5" font-family="${FONT.nam}" font-size="13" font-weight="800" letter-spacing=".6" fill="#e9edf1">${esc(String(title).toUpperCase().slice(0, 11))}</text>
${glyphAt(type, W - 25, 99, 13, voice.glow, 2)}
<text x="${W / 2}" y="120" text-anchor="middle" font-family="${FONT.nam}" font-size="6.5" font-weight="600" letter-spacing="1.4" fill="#2b3136">NAM · ${esc(voice.label)}</text>
${knobAlu(32, 140, 9, { min: 0, max: 1, default: .5 }, 'input')}${knobAlu(W - 32, 140, 9, { min: 0, max: 1, default: .55 }, 'output')}
<rect x="${W / 2 - 3}" y="132" width="6" height="16" rx="1.5" fill="#15181b"/>
<rect x="${W / 2 - 1.8}" y="133.5" width="3.6" height="13" rx="1" fill="${on ? voice.glow : '#2b3136'}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
<g class="gp-switch"><rect x="${W / 2 - 17}" y="${H - 38}" width="34" height="24" rx="4" fill="#000" opacity=".3" transform="translate(1 2)"/>
  <rect x="${W / 2 - 17}" y="${H - 38}" width="34" height="24" rx="4" fill="#202428"/>
  <rect x="${W / 2 - 14}" y="${H - 35.5}" width="28" height="19" rx="3" fill="#2d3237" stroke="#fff" stroke-opacity=".08"/>
  <path d="M${W / 2 - 9} ${H - 26}h18" stroke="#000" stroke-opacity=".5" stroke-width="2"/></g>
</svg>`;
  }

  // amp families -> look. No maker's livery: each is a period and a material, not a brand.
  const AMP_LOOK = {
    clean: { tolex: '#d9c9a0', tolexDark: '#a8946a', panel: 'url(#gp-brushed)', ink: '#26211a', cloth: '#6f5a3a', clothPat: 'gp-weave', knob: 'cream', piping: '#f2ead8', label: 'clean' },
    crunch: { tolex: '#5a1f1c', tolexDark: '#2e0f0d', panel: '#c9a45a', ink: '#2a1a08', cloth: '#2c2a26', clothPat: 'gp-basket', knob: 'black', piping: '#d8c18a', label: 'crunch' },
    'high-gain': { tolex: '#1b1c1e', tolexDark: '#08090a', panel: '#2a2d31', ink: '#d9dde2', cloth: '#141516', clothPat: 'gp-mesh', knob: 'alu', piping: '#5a5f66', label: 'high gain' },
    bass: { tolex: '#24324a', tolexDark: '#111a29', panel: 'url(#gp-brushed)', ink: '#141a24', cloth: '#1d2230', clothPat: 'gp-mesh', knob: 'black', piping: '#9fb2d0', label: 'bass' },
  };
  const ampLook = fam => AMP_LOOK[fam] || AMP_LOOK.crunch;

  function ampKnob(cx, cy, r, look, label, v) {
    const p = { min: 0, max: 1, default: v == null ? .55 : v };
    if (look.knob === 'alu') return knobAlu(cx, cy, r, p, label, look.ink);
    if (look.knob === 'cream') {
      const a = angleOf(p), [px, py] = polar(cx, cy, r * .9, a);
      return `<g class="gp-knob"><circle cx="${cx}" cy="${cy + 1}" r="${r}" fill="#000" opacity=".3"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob-cream)"/>
        <path d="M${cx} ${cy}L${px} ${py}" stroke="#3b2f22" stroke-width="1.4" stroke-linecap="round"/>
        <text x="${cx}" y="${cy + r + 8}" text-anchor="middle" font-family="${FONT.nam}" font-size="6.8" font-weight="700" letter-spacing=".6" fill="${look.ink}">${esc(label)}</text></g>`;
    }
    // chicken head
    const a = angleOf(p);
    return `<g class="gp-knob" transform="rotate(${a} ${cx} ${cy})"><circle cx="${cx}" cy="${cy + 1}" r="${r}" fill="#000" opacity=".35"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob)"/>
      <path d="M${cx - r * .32} ${cy + r * .4}L${cx} ${cy - r * 1.25}L${cx + r * .32} ${cy + r * .4}Z" fill="#1a1613" stroke="#3a332d" stroke-width=".6"/>
      <path d="M${cx} ${cy - r * .2}V${cy - r * 1.1}" stroke="#f3ead2" stroke-width="1.1"/></g>
      <text x="${cx}" y="${cy + r + 8}" text-anchor="middle" font-family="${FONT.nam}" font-size="6.8" font-weight="700" letter-spacing=".6" fill="${look.ink}">${esc(label)}</text>`;
  }

  // the head's body at (x, y), w x h. Shared by the head, the stack and the combo
  function headBody(x, y, w, h, look, title, on, opts) {
    opts = opts || {};
    const gh = Math.round(h * .42);
    const py = y + gh + 6;
    const qualities = ['std', 'lite', 'feather'];
    return `<g class="gp-head">
  <path d="M${x + w / 2 - 34} ${y + 2}c0-10 6-12 34-12s34 2 34 12" fill="none" stroke="#111" stroke-width="5" stroke-linecap="round"/>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="${look.tolex}"/>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="#fff" filter="url(#gp-tolex)"/>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="url(#gp-sheen)" opacity=".7"/>
  <rect x="${x + 7}" y="${y + 6}" width="${w - 14}" height="${gh}" rx="2" fill="${look.cloth}"/>
  <rect x="${x + 7}" y="${y + 6}" width="${w - 14}" height="${gh}" rx="2" fill="url(#${look.clothPat})"/>
  <rect x="${x + 7}" y="${y + 6}" width="${w - 14}" height="${gh}" rx="2" fill="none" stroke="${look.piping}" stroke-width="1.6"/>
  <g filter="url(#gp-shadow-small)"><rect x="${x + w / 2 - 46}" y="${y + 6 + gh / 2 - 9}" width="92" height="18" rx="3" fill="#0f1012" stroke="${look.piping}" stroke-opacity=".6"/></g>
  ${glyphAt(opts.glyph || 'amp-nam', x + w / 2 - 35, y + 6 + gh / 2, 11, look.piping, 2)}
  <text x="${x + w / 2 - 26}" y="${y + 6 + gh / 2 + 4.6}" font-family="${FONT.nam}" font-size="13" font-weight="800" letter-spacing=".8" fill="#eef0f2">${esc(String(title).toUpperCase().slice(0, 10))}</text>
  <rect x="${x + 7}" y="${py}" width="${w - 14}" height="${h - gh - 13}" rx="2" fill="${look.panel}"/>
  <rect x="${x + 7}" y="${py}" width="${w - 14}" height="${h - gh - 13}" rx="2" fill="url(#gp-brush-lines)" opacity=".7"/>
  <circle cx="${x + 22}" cy="${py + 14}" r="4" fill="#111"/><circle cx="${x + 22}" cy="${py + 14}" r="1.8" fill="#333"/>
  ${ampKnob(x + 50 * Math.min(1, w / 300) + (w < 230 ? 4 : 0), py + 13, 7.5, look, 'input', .5)}
  ${ampKnob(x + (w < 230 ? w * .45 : 82), py + 13, 7.5, look, 'output', .6)}
  ${ampKnob(x + (w < 230 ? w * .68 : 114), py + 13, 7.5, look, opts.quality || qualities[0], .15)}
  ${w < 230 ? '' : `<text x="${x + w - 60}" y="${py + 10}" font-family="${FONT.nam}" font-size="6.5" font-weight="700" letter-spacing="1.2" fill="${look.ink}" opacity=".85">NAM</text>`}
  ${w < 230 ? '' : `<text x="${x + w - 60}" y="${py + 18}" font-family="${FONT.nam}" font-size="6" font-weight="600" letter-spacing=".8" fill="${look.ink}" opacity=".7">${esc(look.label)}</text>`}
  <circle cx="${x + w - 22}" cy="${py + 13}" r="5.2" fill="#2a2a2a"/>
  <circle cx="${x + w - 22}" cy="${py + 13}" r="4" fill="${on ? '#ff3b2a' : '#4a1410'}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  <circle cx="${x + w - 22}" cy="${py + 13}" r="4" fill="url(#gp-jewel)"/>
  ${corners(x, y, w, h)}
</g>`;
  }
  function corners(x, y, w, h) {
    const c = (cx, cy, sx, sy) => `<path d="M${cx} ${cy + sy * 11}V${cy}H${cx + sx * 11}" fill="none" stroke="url(#gp-chrome)" stroke-width="4" stroke-linejoin="round"/>`;
    return `<g opacity=".9">${c(x + 1.5, y + 1.5, 1, 1)}${c(x + w - 1.5, y + 1.5, -1, 1)}${c(x + 1.5, y + h - 1.5, 1, -1)}${c(x + w - 1.5, y + h - 1.5, -1, -1)}</g>`;
  }

  function cabBody(x, y, w, h, look, layout, title) {
    const [cols, rows, size] = layout;
    const inner = { x: x + 9, y: y + 9, w: w - 18, h: h - 18 };
    let cones = '';
    const r = Math.min(inner.w / cols, inner.h / rows) * .42;
    for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
      const cx = inner.x + inner.w * (i + .5) / cols, cy = inner.y + inner.h * (j + .5) / rows;
      cones += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="#000" opacity=".28"/><circle cx="${cx}" cy="${cy}" r="${r * .33}" fill="#000" opacity=".25"/>`;
    }
    return `<g class="gp-cab">
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="${look.tolex}"/>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="#fff" filter="url(#gp-tolex)"/>
  <rect x="${inner.x}" y="${inner.y}" width="${inner.w}" height="${inner.h}" rx="3" fill="${look.cloth}"/>
  ${cones}
  <rect x="${inner.x}" y="${inner.y}" width="${inner.w}" height="${inner.h}" rx="3" fill="url(#${look.clothPat})"/>
  <rect x="${inner.x}" y="${inner.y}" width="${inner.w}" height="${inner.h}" rx="3" fill="#fff" filter="url(#gp-speckle)" opacity=".18"/>
  <rect x="${inner.x}" y="${inner.y}" width="${inner.w}" height="${inner.h}" rx="3" fill="none" stroke="${look.piping}" stroke-width="1.8"/>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="url(#gp-sheen)" opacity=".6"/>
  ${title ? `<g filter="url(#gp-shadow-small)"><rect x="${inner.x + 8}" y="${inner.y + 8}" width="${Math.min(110, 18 + title.length * 6.5)}" height="14" rx="2" fill="#0f1012"/></g>
  ${glyphAt('cab', inner.x + 16, inner.y + 15, 9, look.piping, 2.2)}
  <text x="${inner.x + 24}" y="${inner.y + 19}" font-family="${FONT.nam}" font-size="9.5" font-weight="800" letter-spacing=".6" fill="#eef0f2">${esc(title.toUpperCase())}</text>` : ''}
  ${corners(x, y, w, h)}
</g>`;
  }

  // cab sizes from a name: "4x12", "2x12", "8x10"…
  function cabLayout(name) {
    const m = /(\d)\s*x\s*(\d{2})/i.exec(name || '');
    const n = m ? +m[1] : 4, inch = m ? +m[2] : 12;
    const layout = { 1: [1, 1], 2: [2, 1], 4: [2, 2], 8: [2, 4] }[n] || [2, 2];
    const unit = inch >= 12 ? 92 : inch >= 10 ? 76 : 70;
    return { cols: layout[0], rows: layout[1], w: layout[0] * unit + 22, h: layout[1] * unit + 22, label: m ? `${n}x${inch}` : '' };
  }

  function namHead(opts) {
    opts = opts || {};
    const look = ampLook(opts.family);
    const W = 300, H = 120;
    return `<svg class="gp-amp gp-nam-head${opts.on !== false ? ' is-on' : ''}" viewBox="-6 -18 ${W + 12} ${H + 30}" width="${opts.width || W + 12}" role="img" aria-label="NAM head — ${esc(opts.title || look.label)}">
<g filter="url(#gp-shadow)">${headBody(0, 0, W, H, look, opts.title || 'head', opts.on !== false, { glyph: 'amp-nam' })}</g></svg>`;
  }

  function namCab(opts) {
    opts = opts || {};
    const look = ampLook(opts.family);
    const L = cabLayout(opts.size || opts.title);
    return `<svg class="gp-amp gp-nam-cab" viewBox="-6 -6 ${L.w + 12} ${L.h + 20}" width="${opts.width || L.w + 12}" role="img" aria-label="Cab — ${esc(opts.title || L.label)}">
<g filter="url(#gp-shadow)">${cabBody(0, 0, L.w, L.h, look, [L.cols, L.rows], opts.title || L.label || 'cab')}
<rect x="10" y="${L.h}" width="16" height="6" rx="2" fill="#111"/><rect x="${L.w - 26}" y="${L.h}" width="16" height="6" rx="2" fill="#111"/></g></svg>`;
  }

  // head + cab: a stack (head on a cab) or a combo (one box)
  function namStack(opts) {
    opts = opts || {};
    const look = ampLook(opts.family);
    const on = opts.on !== false;
    if (opts.form === 'combo') {
      const W = 300, H = 250, hh = 104;
      return `<svg class="gp-amp gp-nam-combo${on ? ' is-on' : ''}" viewBox="-6 -18 ${W + 12} ${H + 34}" width="${opts.width || W + 12}" role="img" aria-label="NAM combo — ${esc(opts.title || look.label)}">
<g filter="url(#gp-shadow)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="9" fill="${look.tolex}"/>
  ${cabBody(0, hh - 14, W, H - hh + 14, look, [2, 1], '')}
  ${headBody(0, 0, W, hh, look, opts.title || 'combo', on, { glyph: 'amp' })}
  <rect x="12" y="${H}" width="18" height="7" rx="2" fill="#111"/><rect x="${W - 30}" y="${H}" width="18" height="7" rx="2" fill="#111"/>
</g></svg>`;
    }
    const L = cabLayout(opts.size || '4x12');
    const hw = Math.min(300, L.w - 8), hh = 112, hx = (L.w - hw) / 2;
    return `<svg class="gp-amp gp-nam-stack${on ? ' is-on' : ''}" viewBox="-6 -18 ${L.w + 12} ${hh + L.h + 34}" width="${opts.width || L.w + 12}" role="img" aria-label="NAM head + cab — ${esc(opts.title || look.label)}">
<g filter="url(#gp-shadow)">
  ${cabBody(0, hh + 2, L.w, L.h, look, [L.cols, L.rows], opts.cabTitle || L.label)}
  <rect x="10" y="${hh + 2 + L.h}" width="16" height="6" rx="2" fill="#111"/><rect x="${L.w - 26}" y="${hh + 2 + L.h}" width="16" height="6" rx="2" fill="#111"/>
  ${headBody(hx, 0, hw, hh, look, opts.title || 'stack', on, { glyph: 'amp' })}
</g></svg>`;
  }

  // ---------- NAM: rack (outboard captures: preamps, compressors, EQs) ----------
  // looks: a period and a material, never a maker's livery
  const RACK_LOOK = {
    'console-60s': { panel: '#5b6d80', tex: 'gp-brush-lines', ink: '#eef1f4', sub: '#d6dde4', scale: '#c9d3dc', lamp: '#ff3b2a' },
    'black-60s': { panel: '#17181a', tex: 'gp-brush-lines', ink: '#e9edf1', sub: '#8a94a3', scale: '#aab3bd', lamp: '#ff3b2a' },
    'hammertone-60s': { panel: '#7d858c', tex: 'gp-hammer', ink: '#101316', sub: '#262b30', scale: '#1c2024', lamp: '#ffb03a' },
    'enamel-50s': { panel: '#3e6675', tex: 'gp-speckle', ink: '#f1ece0', sub: '#cfd8d6', scale: '#e6e1d4', lamp: '#ff5a3c' },
    'console-80s': { panel: '#2c3035', tex: 'gp-brush-lines', ink: '#e8ebee', sub: '#9aa3ad', scale: '#b9c1c9', lamp: '#2ecc71' },
    'module-70s': { panel: '#1d1f22', tex: 'gp-brush-lines', ink: '#e2e6ea', sub: '#7fa6d6', scale: '#b9c1c9', lamp: '#ff3b2a' },
    'modern-90s': { panel: '#141518', tex: 'gp-brush-lines', ink: '#dfe3e7', sub: '#8a94a3', scale: '#aab3bd', lamp: '#ff3b2a' },
    'tube-50s': { panel: '#6f767c', tex: 'gp-hammer', ink: '#0f1214', sub: '#23282c', scale: '#1b1f22', lamp: '#ffb03a' },
    // the IR units (ir-fx): an amp-tank spring unit in tolex, a cream 70s tape echo, a brushed-steel
    // analog echo, a charcoal 80s digital rack with its program LCD
    'tolex-60s': { panel: '#211e1b', tex: 'gp-tolex', ink: '#efe6cf', sub: '#c9b98f', scale: '#d9cca8', lamp: '#ff5a3c' },
    'cream-70s': { panel: '#d6ccb0', tex: 'gp-speckle', ink: '#1d1b17', sub: '#5a4e3a', scale: '#3a342a', lamp: '#ff5a3c' },
    'steel-70s': { panel: '#9ba2a9', tex: 'gp-brush-lines', ink: '#121417', sub: '#2b3036', scale: '#1d2125', lamp: '#ff3b2a' },
    'digital-80s': { panel: '#25282d', tex: 'gp-brush-lines', ink: '#e6e9ec', sub: '#7fb0d8', scale: '#b9c1c9', lamp: '#2ecc71', lcd: '#9fd0e8' },
  };
  // a unit golem has no archetype for: voiced by kind
  const RACK_GENERIC = {
    preamp: { id: 'preamp', short: 'PREAMP', kind: 'preamp', sub: 'mic pre', look: 'console-60s', u: 1, controls: [
      { type: 'stepped', bind: 'gain', label: 'gain', values: [20, 30, 40, 50, 60, 70], default: 50, unit: 'dB', cap: 'red' },
      { type: 'toggle', bind: 'hard', label: 'drive' }, { type: 'knob', label: 'output', cap: 'grey' }, { type: 'badge', bind: 'channel', label: 'ch' }] },
    comp: { id: 'comp', short: 'COMP', kind: 'comp', sub: 'compressor', look: 'black-60s', u: 1, controls: [
      { type: 'knob', label: 'threshold', cap: 'alu' }, { type: 'buttons', bind: 'ratio', label: 'ratio', values: [2, 4, 8], default: 4, row: true },
      { type: 'knob', label: 'attack', cap: 'alu' }, { type: 'knob', label: 'release', cap: 'alu' }, { type: 'leds', label: 'gr' },
      { type: 'knob', label: 'output', cap: 'alu' }, { type: 'badge', bind: 'channel', label: 'ch' }] },
    eq: { id: 'eq', short: 'EQ', kind: 'eq', sub: 'equalizer', look: 'module-70s', u: 1, controls: [
      { type: 'knob', label: 'low', cap: 'black' }, { type: 'knob', label: 'low mid', cap: 'black' }, { type: 'knob', label: 'high mid', cap: 'black' },
      { type: 'knob', label: 'high', cap: 'black' }, { type: 'toggle', label: 'in', on: true }, { type: 'badge', bind: 'channel', label: 'ch' }] },
    // IR units (ir-fx): a digital reverb rack with its program LCD, a generic echo with a program LED
    reverb: { id: 'reverb', short: 'REVERB', kind: 'reverb', sub: 'digital reverb', look: 'digital-80s', u: 1, controls: [
      { type: 'program', style: 'lcd', label: 'program', default: 'Hall 1' }, { type: 'knob', label: 'decay', cap: 'grey' },
      { type: 'knob', label: 'pre-delay', cap: 'grey' }, { type: 'knob', label: 'mix', cap: 'grey' }, { type: 'leds', label: 'in' }] },
    echo: { id: 'echo', short: 'ECHO', kind: 'echo', sub: 'studio echo', look: 'console-80s', u: 1, controls: [
      { type: 'program', style: 'led', label: 'program', default: 'Echo 1' }, { type: 'knob', label: 'time', cap: 'black' },
      { type: 'knob', label: 'repeats', cap: 'black' }, { type: 'knob', label: 'mix', cap: 'black' }, { type: 'knob', label: 'tone', cap: 'black' }] },
  };
  // the kind of a unit golem has no archetype for, from its label
  const rackKindOf = label => {
    const l = String(label || '').toLowerCase();
    return /reverb|spring|\bhall\b|\broom\b|\bplate\b|chamber|ambien/.test(l) ? 'reverb' : /echo|delay/.test(l) ? 'echo'
      : /comp|limit|level(?:l)?er/.test(l) ? 'comp' : /\beq\b|equali/.test(l) ? 'eq' : 'preamp';
  };
  const rackArch = opts => opts.archetype || archetypeFor('outboard', opts.label || opts.title)
    || RACK_GENERIC[opts.kind] || RACK_GENERIC[rackKindOf(opts.label || opts.title)] || RACK_GENERIC.preamp;
  const rackGlyph = (kind, ir) => ir ? 'ir-fx' : { comp: 'comp-nam', eq: 'eq', reverb: 'reverb', echo: 'delay-tape' }[kind] || 'preamp-nam';
  // an IR's program, from its label: "… Spring Reverb 3" -> "Spring 3", "… delay 7" -> "Delay 7", "… Hall 3"
  const PROGRAM_WORD = 'spring(?:\\s*reverb)?|reverb|hall|room|plate|chamber|ambience|ambiance|echo|delay|tape|repeat|mode|program|prog|preset|patch|bank|setting|head|tank';
  function programOf(label) {
    const l = String(label || '').replace(/\.(wav|aiff?|flac)$/i, '').trim();
    const title = w => w.toLowerCase().replace(/^spring\s*reverb$/, 'spring').replace(/^program$/, 'prog').replace(/^./, x => x.toUpperCase());
    let m = new RegExp(`(?:^|[\\s\\-–_/(])(${PROGRAM_WORD})\\s*[#.]?\\s*(\\d{1,3}[a-z]?)\\s*\\)?$`, 'i').exec(l);
    if (m) return `${title(m[1])} ${m[2].toUpperCase()}`;
    m = /(?:^|[\s\-–_/(])(hall|room|plate|chamber|spring|ambience)\s*\)?$/i.exec(l);
    if (m) return title(m[1]);
    m = /\s[-–_]\s*(\d{1,2})\s*$/.exec(l);
    return m ? `Prog ${m[1]}` : null;
  }
  const programNum = p => { const m = /(\d+)[a-z]?\s*$/i.exec(String(p || '')); return m ? +m[1] : null; };
  const RACK_U = 56;

  // the setting a capture was taken at, from its label: "1073MP - 60 dB Hard - B", "1176 L", "Bus comp 4:1"
  function outboardSetting(label) {
    const l = String(label || '');
    const s = {};
    const g = /(-?\d+(?:\.\d+)?)\s*dB\b/i.exec(l); if (g) s.gain = +g[1];
    if (/\bhard\b/i.test(l)) s.hard = true; else if (g) s.hard = false;
    const r = /\b(\d+(?:\.\d+)?)\s*:\s*1\b/.exec(l); if (r) s.ratio = +r[1];
    const c = /(?:^|[\s\-–_/(])(?:ch(?:annel)?\s*)?([A-D]|L|R)\s*\)?\s*$/i.exec(l.trim()); if (c) s.channel = c[1].toUpperCase();
    if (/\blimit\b/i.test(l)) s.limit = true;
    const t = /\btime\s*(\d)\b/i.exec(l); if (t) s.time = +t[1];
    const p = programOf(l); if (p) s.program = p;
    return s;
  }

  function rackKnob(cx, cy, r, frac, cap, label, L, sweep, ldy) {
    sweep = sweep || 135;
    const a = -sweep + 2 * sweep * Math.max(0, Math.min(1, frac)), [px, py] = polar(cx, cy, r * .86, a);
    const lbl = label ? `<text x="${cx}" y="${cy + r + (ldy || 10)}" text-anchor="middle" font-family="${FONT.nam}" font-size="${r > 16 ? 9 : 7.4}" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(String(label).toUpperCase())}</text>` : '';
    if (cap === 'chicken') {
      return `<g class="gp-knob"><circle cx="${cx}" cy="${cy}" r="${r + 3}" fill="none" stroke="${L.scale}" stroke-opacity=".5" stroke-dasharray="1 3.2"/>
  <g transform="rotate(${a} ${cx} ${cy})"><circle cx="${cx}" cy="${cy + 1}" r="${r * .7}" fill="#000" opacity=".35"/><circle cx="${cx}" cy="${cy}" r="${r * .7}" fill="url(#gp-knob)"/>
  <path d="M${cx - r * .28} ${cy + r * .45}L${cx} ${cy - r * 1.05}L${cx + r * .28} ${cy + r * .45}Z" fill="#141210"/><path d="M${cx} ${cy - r * .15}V${cy - r * .95}" stroke="#f3ead2" stroke-width="1.1"/></g>${lbl}</g>`;
    }
    if (cap === 'alu') return knobAlu(cx, cy, r, { min: 0, max: 1, default: frac }, '', L.ink).replace('</g>', '') + lbl + '</g>';
    const fill = { red: '#a3201a', blue: '#2f5f9e', grey: '#9aa3ad', black: '#17191b', cream: '#e6dcc0' }[cap] || '#17191b';
    return `<g class="gp-knob"><circle cx="${cx}" cy="${cy + 1.4}" r="${r}" fill="#000" opacity=".45"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob)"/><circle cx="${cx}" cy="${cy}" r="${r * .72}" fill="${fill}"/>
  <circle cx="${cx}" cy="${cy}" r="${r * .72}" fill="url(#gp-sheen)" opacity=".5"/>
  <path d="M${cx} ${cy}L${px.toFixed(2)} ${py.toFixed(2)}" stroke="${cap === 'grey' || cap === 'cream' ? '#15181b' : '#f2f4f6'}" stroke-width="${r > 16 ? 2.2 : 1.5}" stroke-linecap="round"/>${lbl}</g>`;
  }

  function rackControl(c, cx, cy, h, set, L, on, cw) {
    const big = c.size === 'big', r = Math.min(big ? 26 : 17, h * (big ? .3 : .22));
    const v = c.bind ? set[c.bind] : undefined;
    switch (c.type) {
      case 'stepped': {
        const vals = c.values || [0, 1], cur = v != null ? v : c.default;
        let k = 0; vals.forEach((x, i) => { if (Math.abs(x - cur) < Math.abs(vals[k] - cur)) k = i; });
        const step = vals.length > 1 ? 1 / (vals.length - 1) : .5;
        const marks = vals.map((x, i) => { const [tx, ty] = polar(cx, cy, r + 9, -110 + 220 * i * step);
          return `<text x="${tx.toFixed(1)}" y="${(ty + 2.6).toFixed(1)}" text-anchor="middle" font-family="${FONT.gfx}" font-size="${r > 14 ? 7.6 : 6.4}" font-weight="700" fill="${i === k ? L.ink : L.scale}" opacity="${i === k ? 1 : .7}">${x}</text>`; }).join('');
        return `<g class="gp-rack-ctl" data-bind="${esc(c.bind || '')}">${marks}${rackKnob(cx, cy, r, k * step, c.cap, c.label + (c.unit ? ` · ${c.unit}` : ''), L, 110, 15)}</g>`;
      }
      case 'knob': return rackKnob(cx, cy, r, c.value != null ? c.value : .5, c.cap, c.label, L);
      case 'toggle': {
        const up = v != null ? !!v : !!c.on;
        return `<g class="gp-rack-ctl" data-bind="${esc(c.bind || '')}"><circle cx="${cx}" cy="${cy}" r="6.5" fill="url(#gp-chrome)"/><circle cx="${cx}" cy="${cy}" r="4" fill="#202326"/>
  <path d="M${cx} ${cy}L${cx} ${cy + (up ? -12 : 12)}" stroke="url(#gp-chrome)" stroke-width="3.4" stroke-linecap="round"/>
  <text x="${cx}" y="${cy + (up ? 18 : -14)}" text-anchor="middle" font-family="${FONT.nam}" font-size="7.4" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(c.label.toUpperCase())}</text></g>`;
      }
      case 'buttons': {
        const vals = c.values || [], cur = v != null ? v : c.default;
        const n = vals.length, row = buttonsRow(c, h);
        const bw = row ? 18 : 26, bh = row ? 13 : Math.min(15, (h - 22) / n - 3);
        const x0 = row ? cx - (n * (bw + 3) - 3) / 2 : cx - bw / 2, y0 = row ? cy - bh / 2 - 4 : cy - (n * (bh + 3) - 3) / 2 - 3;
        const b = vals.map((x, i) => { const sel = x === cur, bx = row ? x0 + i * (bw + 3) : x0, by = row ? y0 : y0 + i * (bh + 3);
          return `<rect x="${bx}" y="${by}" width="${bw}" height="${bh}" rx="2" fill="${sel ? '#eef1f4' : '#34383d'}" stroke="#000" stroke-opacity=".5"/>
  <text x="${bx + bw / 2}" y="${by + bh / 2 + 3}" text-anchor="middle" font-family="${FONT.gfx}" font-size="7.4" font-weight="700" fill="${sel ? '#111' : '#aab3bd'}">${x}</text>`; }).join('');
        const ly = row ? y0 + bh + 10 : y0 + n * (bh + 3) + 8;
        return `<g class="gp-rack-ctl" data-bind="${esc(c.bind || '')}">${b}<text x="${cx}" y="${ly}" text-anchor="middle" font-family="${FONT.nam}" font-size="7.4" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(c.label.toUpperCase())}</text></g>`;
      }
      case 'vu': {
        const w = Math.min(150, h * 1.5, (cw || 150) - 6), vh = Math.min(84, h - 16), x = cx - w / 2, y = cy - vh / 2 - 2;
        const pcx = cx, pcy = y + vh - 6, pr = Math.min(w * .42, vh - 14);
        let ticks = '';
        for (let i = 0; i <= 8; i++) { const d = -50 + i * 12.5, [a1, b1] = polar(pcx, pcy, pr - 5, d), [a2, b2] = polar(pcx, pcy, pr, d);
          ticks += `<path d="M${a1.toFixed(1)} ${b1.toFixed(1)}L${a2.toFixed(1)} ${b2.toFixed(1)}" stroke="${i > 6 ? '#c0392b' : '#222'}" stroke-width="1.4"/>`; }
        const [nx, ny] = polar(pcx, pcy, pr - 2, on ? -12 : -50);
        return `<g class="gp-rack-vu"><rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${vh + 6}" rx="4" fill="#0d0e10"/>
  <rect x="${x}" y="${y}" width="${w}" height="${vh}" rx="3" fill="#f2e6c4"/>${on ? `<rect x="${x}" y="${y}" width="${w}" height="${vh}" rx="3" fill="#ffd27a" opacity=".22"/>` : ''}
  ${ticks}<text x="${pcx}" y="${pcy - pr * .42}" text-anchor="middle" font-family="${FONT.nam}" font-size="${vh > 40 ? 10 : 7}" font-weight="800" fill="#333">VU</text>
  <path d="M${pcx} ${pcy}L${nx.toFixed(1)} ${ny.toFixed(1)}" stroke="#111" stroke-width="1.6"/><circle cx="${pcx}" cy="${pcy}" r="2.4" fill="#222"/>
  <rect x="${x}" y="${y}" width="${w}" height="${vh}" rx="3" fill="url(#gp-glass-glare)"/></g>`;
      }
      case 'leds': {
        const n = 8, lit = on ? 5 : 0, lh = Math.min(5, (h - 24) / n - 1.5), y0 = cy - (n * (lh + 1.8)) / 2 - 4;
        const cells = Array.from({ length: n }, (_, i) => { const col = i < 5 ? '#2ecc71' : i < 7 ? '#ffd400' : '#ff3b2a', j = n - 1 - i;
          return `<rect x="${cx - 6}" y="${(y0 + j * (lh + 1.8)).toFixed(1)}" width="12" height="${lh.toFixed(1)}" rx="1" fill="${i < lit ? col : mix(col, '#111', .78)}"${i < lit ? ' filter="url(#gp-glow-soft)"' : ''}/>`; }).join('');
        return `<g class="gp-rack-leds">${cells}<text x="${cx}" y="${y0 + n * (lh + 1.8) + 8}" text-anchor="middle" font-family="${FONT.nam}" font-size="7.4" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(c.label.toUpperCase())}</text></g>`;
      }
      case 'badge': {
        if (v == null) return '';
        return `<g class="gp-rack-ctl" data-bind="channel"><rect x="${cx - 13}" y="${cy - 13}" width="26" height="22" rx="3" fill="#0f1012" stroke="${L.scale}" stroke-opacity=".5"/>
  <text x="${cx}" y="${cy + 3.6}" text-anchor="middle" font-family="${FONT.nam}" font-size="13" font-weight="800" fill="#eef0f2">${esc(v)}</text>
  <text x="${cx}" y="${cy + 19}" text-anchor="middle" font-family="${FONT.nam}" font-size="7" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(c.label.toUpperCase())}</text></g>`;
      }
      case 'program': {
        // an IR's program: a lit LCD, an LED readout, or a stepped selector (opts.program, or the label's)
        const prog = String((v != null ? v : set.program != null ? set.program : c.default) || '--');
        const lbl = (t, y) => `<text x="${cx}" y="${y.toFixed(1)}" text-anchor="middle" font-family="${FONT.nam}" font-size="7.4" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(t)}</text>`;
        if (c.style === 'selector') {
          const n = Math.max(2, Math.min(12, c.count || 6)), num = programNum(prog), k = Math.max(0, Math.min(n - 1, (num || 1) - 1));
          const r = Math.min(15, h * .22), step = 1 / (n - 1), sweep = 120;
          const marks = Array.from({ length: n }, (_, i) => {
            const a = -sweep + 2 * sweep * i * step, [tx, ty] = polar(cx, cy, r + (n <= 6 ? 9 : 6), a), sel = i === k;
            if (n <= 6 || sel) return `<text x="${tx.toFixed(1)}" y="${(ty + 2.6).toFixed(1)}" text-anchor="middle" font-family="${FONT.gfx}" font-size="${r > 12 ? 7.6 : 6.4}" font-weight="700" fill="${sel ? L.ink : L.scale}" opacity="${sel ? 1 : .7}">${i + 1}</text>`;
            const [a1, b1] = polar(cx, cy, r + 3, a), [a2, b2] = polar(cx, cy, r + 7, a);
            return `<path d="M${a1.toFixed(1)} ${b1.toFixed(1)}L${a2.toFixed(1)} ${b2.toFixed(1)}" stroke="${L.scale}" stroke-opacity=".7" stroke-width="1.1"/>`;
          }).join('');
          const [lx, ly] = polar(cx, cy, r + (n <= 6 ? 16 : 13), -sweep + 2 * sweep * k * step);
          const led = `<circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="1.9" fill="${on ? L.lamp : mix(L.lamp, '#000', .7)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>`;
          return `<g class="gp-rack-program" data-program="${esc(prog)}">${marks}${led}${rackKnob(cx, cy, r, k * step, c.cap || 'black', '', L, sweep)}${lbl(prog.toUpperCase().slice(0, 12), cy + r + 15)}</g>`;
        }
        const led = c.style === 'led', w = Math.min(led ? 92 : 100, (cw || 110) - 8), dh = Math.min(22, h * .4), x = cx - w / 2, y = cy - dh / 2 - 3;
        const txt = prog.toUpperCase().slice(0, 12), fs = Math.min(dh * .68, (w - 10) / (Math.max(4, txt.length) * .62));
        const tint = c.tint || L.lcd || '#b4d86a';
        const screen = led ? '#1c0705' : on ? tint : mix(tint, '#111', .82);
        const ink = led ? (on ? '#ff4b33' : '#4a1a14') : on ? '#11180d' : mix(tint, '#111', .62);
        const ty = (y + dh / 2 + fs * .36).toFixed(1);
        return `<g class="gp-rack-program" data-program="${esc(prog)}"><rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${dh + 6}" rx="3" fill="#0b0c0e"/>
  <rect x="${x}" y="${y}" width="${w}" height="${dh}" rx="1.6" fill="${screen}"/>${!led && on ? `<rect x="${x}" y="${y}" width="${w}" height="${dh}" rx="1.6" fill="#fff" opacity=".12"/>` : ''}
  <text x="${cx}" y="${ty}" text-anchor="middle" font-family="${FONT.lcd}" font-size="${fs.toFixed(1)}" font-weight="700" letter-spacing=".5" fill="${ink}"${led && on ? ' filter="url(#gp-glow-soft)"' : ''}>${esc(txt)}</text>${led && on ? `<text x="${cx}" y="${ty}" text-anchor="middle" font-family="${FONT.lcd}" font-size="${fs.toFixed(1)}" font-weight="700" letter-spacing=".5" fill="#ffb3a6">${esc(txt)}</text>` : ''}
  <rect x="${x}" y="${y}" width="${w}" height="${dh}" rx="1.6" fill="url(#gp-glass-glare)"/>${lbl(String(c.label || 'program').toUpperCase(), y + dh + 12)}</g>`;
      }
      case 'spring': {
        // the tank seen through a window: transducers at both ends, the coiled springs between
        const w = Math.min(150, (cw || 150) - 8), wh = Math.min(46, h - 26), x = cx - w / 2, y = cy - wh / 2 - 3;
        const n = wh > 30 ? 3 : 2, col = on ? '#d4dbe1' : '#70767d';
        const springs = Array.from({ length: n }, (_, i) => { const yy = (y + wh * (i + 1) / (n + 1)).toFixed(1);
          return `<path d="M${x + 13} ${yy}H${x + w - 13}" stroke="#000" stroke-opacity=".5" stroke-width="5.4"/>
  <path d="M${x + 13} ${yy}H${x + w - 13}" stroke="${col}" stroke-width="4.6" stroke-dasharray="1 1.3"/>
  <path d="M${x + 13} ${yy}H${x + w - 13}" stroke="${on ? '#ffffff' : '#9aa3ad'}" stroke-opacity=".35" stroke-width=".6"/>`; }).join('');
        const tr = xx => `<rect x="${xx}" y="${y + 3}" width="9" height="${wh - 6}" rx="1.5" fill="#2e3236" stroke="#000" stroke-opacity=".5"/><rect x="${xx + 2}" y="${y + wh / 2 - 3}" width="5" height="6" rx="1" fill="${on ? '#b87333' : '#5a3b22'}"/>`;
        return `<g class="gp-rack-spring"><rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${wh + 6}" rx="4" fill="#0b0c0e"/>
  <rect x="${x}" y="${y}" width="${w}" height="${wh}" rx="2.5" fill="#181a1d"/>${on ? `<rect x="${x}" y="${y}" width="${w}" height="${wh}" rx="2.5" fill="${L.lamp}" opacity=".07"/>` : ''}
  ${springs}${tr(x + 2)}${tr(x + w - 11)}
  <rect x="${x}" y="${y}" width="${w}" height="${wh}" rx="2.5" fill="url(#gp-glass-glare)"/>
  <text x="${cx}" y="${y + wh + 12}" text-anchor="middle" font-family="${FONT.nam}" font-size="7.4" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(String(c.label || 'tank').toUpperCase())}</text></g>`;
      }
      case 'tape': {
        // the tape window: two reels, the loop running past the heads
        const w = Math.min(150, (cw || 150) - 8), wh = Math.min(70, h - 26), x = cx - w / 2, y = cy - wh / 2 - 3;
        const r = Math.min(wh * .36, w * .17), ry = y + r + 4, hy = y + wh - 7;
        const reel = (rx, rot) => `<g transform="rotate(${rot} ${rx.toFixed(1)} ${ry.toFixed(1)})"><circle cx="${rx.toFixed(1)}" cy="${ry.toFixed(1)}" r="${(r * .82).toFixed(1)}" fill="#3a281a"/>
  <circle cx="${rx.toFixed(1)}" cy="${ry.toFixed(1)}" r="${r.toFixed(1)}" fill="none" stroke="#9aa3ad" stroke-width="1.2"/>
  ${[0, 120, 240].map(a => { const [px, py] = polar(rx, ry, r * .52, a); return `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="${(r * .2).toFixed(1)}" fill="#0f0d0b"/>`; }).join('')}
  <circle cx="${rx.toFixed(1)}" cy="${ry.toFixed(1)}" r="${(r * .22).toFixed(1)}" fill="#c9d3dc"/></g>`;
        const lx = x + r + 6, rx2 = x + w - r - 6, hx0 = cx - w * .2, hx1 = cx + w * .2;
        const heads = [0, 1, 2, 3].map(i => `<rect x="${(hx0 + (hx1 - hx0) * i / 3 - 3).toFixed(1)}" y="${hy - 1}" width="6" height="6" rx="1" fill="${i ? '#aab3bd' : '#6f767c'}"/>`).join('');
        return `<g class="gp-rack-tape"><rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${wh + 6}" rx="4" fill="#0b0c0e"/>
  <rect x="${x}" y="${y}" width="${w}" height="${wh}" rx="2.5" fill="#1a1714"/>
  <path d="M${lx.toFixed(1)} ${(ry + r * .82).toFixed(1)}L${hx0 - 6} ${hy - 1}H${hx1 + 6}L${rx2.toFixed(1)} ${(ry + r * .82).toFixed(1)}" fill="none" stroke="#5a3b22" stroke-width="1.6"/>
  ${reel(lx, on ? 25 : 0)}${reel(rx2, on ? 70 : 0)}${heads}<circle cx="${hx1 + 9}" cy="${hy + 2}" r="2.4" fill="#26282b" stroke="#6f767c" stroke-width=".6"/>
  <rect x="${x}" y="${y}" width="${w}" height="${wh}" rx="2.5" fill="url(#gp-glass-glare)"/>
  <text x="${cx}" y="${y + wh + 12}" text-anchor="middle" font-family="${FONT.nam}" font-size="7.4" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(String(c.label || 'tape').toUpperCase())}</text></g>`;
      }
      case 'bbd': {
        // the bucket brigade: a chain of cells, each passing a fainter copy on, under the clock
        const w = Math.min(112, (cw || 120) - 8), wh = Math.min(28, h - 28), x = cx - w / 2, y = cy - wh / 2 - 3, n = 10;
        const cw2 = (w - 12) / n, col = on ? '#ffb03a' : '#5a4a3a';
        const cells = Array.from({ length: n }, (_, i) => `<rect x="${(x + 6 + i * cw2 + 1).toFixed(1)}" y="${(y + wh * .45).toFixed(1)}" width="${(cw2 - 2).toFixed(1)}" height="${(wh * .4).toFixed(1)}" rx="1" fill="${col}" opacity="${(1 - i * .075).toFixed(2)}"${on && i < 3 ? ' filter="url(#gp-glow-soft)"' : ''}/>`).join('');
        let clk = `M${x + 6} ${(y + wh * .32).toFixed(1)}`;
        for (let i = 0; i < n; i++) clk += `h${(cw2 / 2).toFixed(1)}v${(-wh * .18).toFixed(1)}h${(cw2 / 2).toFixed(1)}v${(wh * .18).toFixed(1)}`;
        return `<g class="gp-rack-bbd"><rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${wh + 6}" rx="4" fill="#0b0c0e"/>
  <rect x="${x}" y="${y}" width="${w}" height="${wh}" rx="2.5" fill="#15171a"/>
  <path d="${clk}" fill="none" stroke="#7fa6d6" stroke-opacity="${on ? .8 : .35}" stroke-width=".9"/>${cells}
  <rect x="${x}" y="${y}" width="${w}" height="${wh}" rx="2.5" fill="url(#gp-glass-glare)"/>
  <text x="${cx}" y="${y + wh + 12}" text-anchor="middle" font-family="${FONT.nam}" font-size="7.4" font-weight="700" letter-spacing=".9" fill="${L.ink}">${esc(String(c.label || 'bbd').toUpperCase())}</text></g>`;
      }
      default: return '';
    }
  }
  // IR format: the controls an IR cannot turn are drawn fixed (greyed); the capture's own setting stays
  const FIXABLE = new Set(['knob', 'stepped', 'toggle', 'buttons']);
  const rackFixed = (c, svg, ir) => ir && !c.bind && FIXABLE.has(c.type) ? `<g class="gp-rack-fixed" opacity=".42">${svg}</g>` : svg;
  // an IR's program display, when the unit has none of its own: an LED readout
  const irControls = (arch, ir) => {
    const list = (arch.controls || []).slice();
    if (ir && !list.some(c => c.type === 'program')) list.unshift({ type: 'program', style: 'led', label: 'program' });
    return list;
  };
  // the engraved IR mark: a recessed plate, the letters cut through to the panel's own light
  const irBadge = (x, y, L) => { const light = luma(L.panel) > .45;
    return `<g class="gp-ir-badge"><rect x="${x - 11}" y="${y - 6}" width="22" height="12" rx="2.5" fill="${mix(L.panel, '#000', light ? .74 : .45)}" stroke="#fff" stroke-opacity=".16"/>
  <rect x="${x - 11.5}" y="${y - 6.5}" width="22" height="12" rx="2.5" fill="none" stroke="#000" stroke-opacity=".55"/>
  <text x="${x}" y="${y + 3.4}" text-anchor="middle" font-family="${FONT.nam}" font-size="9.4" font-weight="800" letter-spacing="1.4" fill="${light ? mix(L.panel, '#fff', .3) : mix(L.ink, L.panel, .1)}">IR</text></g>`; };
  const RACK_W = { stepped: 78, knob: 52, toggle: 40, buttons: 44, vu: 150, leds: 34, badge: 38, program: 108, spring: 156, tape: 156, bbd: 120 };
  // ratio buttons: a column when it fits the unit's height, else a row
  const buttonsRow = (c, h) => !!c.row || (c.values || []).length * 14 > h - 26;
  const rackWidth = (c, small, h) => c.type === 'buttons' && buttonsRow(c, h) ? (c.values || []).length * 21 + 6
    : c.type === 'program' && c.style === 'selector' ? 76
    : (c.size === 'big' ? 1.35 : 1) * (RACK_W[c.type] || 50) * (small && c.type === 'vu' ? .55 : 1);

  // a NAM capture of outboard gear, as a 19" rack unit. opts: archetype (an outboard archetype, or found
  // from opts.label / opts.title), kind ('preamp' | 'comp' | 'eq' | 'reverb' | 'echo', for the generic
  // unit; else guessed from the label), title, u, on, setting (or read from opts.label: gain, hard,
  // channel, ratio, program), width. format: 'ir' draws the unit as an IR (golem's ir-fx: a captured
  // impulse response, played whole): an engraved IR mark, the controls it cannot turn greyed, and its
  // program (opts.program, or the label's "Spring 3" / "Delay 7") on the unit's program display, an
  // LED readout added when the unit has none
  function namRack(opts) {
    opts = opts || {};
    const on = opts.on !== false;
    const arch = rackArch(opts), ir = opts.format === 'ir';
    const L = RACK_LOOK[arch.look] || RACK_LOOK['console-60s'];
    const voice = NAM_VOICE[arch.kind] || (arch.kind ? { label: arch.kind } : NAM_VOICE.preamp);
    const set = Object.assign({}, outboardSetting(opts.label), opts.setting || {}, opts.program != null ? { program: opts.program } : {});
    const u = Math.max(1, Math.min(4, opts.u || arch.u || 1));
    const W = 600, H = u * RACK_U - 2, EAR = 26, title = opts.title || arch.short || arch.name || 'outboard';
    const holes = (u === 1 ? [H / 2] : [RACK_U * .27, H - RACK_U * .27]).flatMap(y => [[EAR / 2, y], [W - EAR / 2, y]])
      .map(([x, y]) => `<rect x="${x - 6.5}" y="${y - 3.6}" width="13" height="7.2" rx="3.6" fill="#0b0c0e"/><circle cx="${x}" cy="${y}" r="2.7" fill="#9aa3ad"/><circle cx="${x - .5}" cy="${y - .5}" r="1" fill="#eef1f4"/>`).join('');
    // the name block, left
    const tx = EAR + 14, small = u === 1;
    const tsize = small ? 17 : Math.min(26, 13 + u * 4);
    const name = `<text x="${tx}" y="${small ? H / 2 + 2 : H * .4}" font-family="${FONT.nam}" font-size="${tsize}" font-weight="800" letter-spacing="1.6" fill="${L.ink}">${esc(String(title).toUpperCase().slice(0, 12))}</text>
  <text x="${tx}" y="${small ? H / 2 + 14 : H * .4 + 15}" font-family="${FONT.gfx}" font-size="8" font-weight="600" letter-spacing="1.6" fill="${L.sub}">${esc(String(arch.sub || voice.label).toUpperCase())}</text>
  ${small ? '' : `<text x="${tx}" y="${H * .4 + 28}" font-family="${FONT.nam}" font-size="7" font-weight="700" letter-spacing="1.4" fill="${L.sub}" opacity=".8">${ir ? 'IMPULSE RESPONSE' : `NAM · ${esc(voice.label)}`}</text>`}`;
    // the controls, spread between the name block and the lamp
    const x0 = EAR + (small ? 128 : 150), x1 = W - EAR - 40;
    const ctls = irControls(arch, ir).filter(c => c.type !== 'badge' || (c.bind && set[c.bind] != null));
    // an IR makes room for its program by dropping the fixed knobs from the right
    for (let i = ctls.length - 1; ir && i >= 0 && ctls.reduce((a, c) => a + rackWidth(c, small, H), 0) > x1 - x0; i--)
      if (!ctls[i].bind && FIXABLE.has(ctls[i].type)) ctls.splice(i, 1);
    const widths = ctls.map(c => rackWidth(c, small, H));
    const total = widths.reduce((a, b) => a + b, 0), gap = Math.max(0, (x1 - x0 - total) / Math.max(1, ctls.length));
    const scale = total > x1 - x0 ? (x1 - x0) / total : 1;
    let cx = x0 + gap / 2;
    const cy = small ? H / 2 - 3 : H / 2 - 4;
    const body = ctls.map((c, i) => { const w = widths[i] * scale, x = cx + w / 2; cx += w + gap; return rackFixed(c, rackControl(c, x, cy, H, set, L, on, w + gap), ir); }).join('');
    const lamp = `<circle cx="${W - EAR - 18}" cy="${H / 2}" r="6.4" fill="#26282b"/>
  <circle cx="${W - EAR - 18}" cy="${H / 2}" r="4.6" fill="${on ? L.lamp : mix(L.lamp, '#000', .7)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  <circle cx="${W - EAR - 18}" cy="${H / 2}" r="4.6" fill="url(#gp-jewel)"/>`;
    return `<svg class="gp-rack gp-nam-rack${on ? ' is-on' : ''}" viewBox="-4 -4 ${W + 8} ${H + 10}" width="${opts.width || W + 8}" role="img" aria-label="${ir ? 'IR' : 'NAM'} outboard — ${esc(title)}" data-archetype="${esc(arch.id || '')}" data-u="${u}"${ir ? ' data-format="ir"' : ''}>
<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="${L.panel}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="url(#${L.tex})" opacity="${L.tex === 'gp-brush-lines' ? .55 : .35}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="url(#gp-sheen)" opacity=".45"/>
  <path d="M${EAR} 2V${H - 2}M${W - EAR} 2V${H - 2}" stroke="#000" stroke-opacity=".35"/>
</g>
${holes}${name}${body}${lamp}
${glyphAt(rackGlyph(arch.kind, ir), W - EAR - 18, small ? H / 2 - 16 : H / 2 - 20, 11, L.sub, 2)}${ir ? irBadge(W - EAR - 18, small ? H / 2 + 16 : H / 2 + 20, L) : ''}
</svg>`;
  }

  // the same outboard unit at the pedal footprint (Designer, pedal mode): a 500-series-style vertical
  // module, its controls in a narrow column. Same opts as namRack (format 'ir' too: the program display
  // comes first); the rack stays in the Library.
  function namModule(opts) {
    opts = opts || {};
    const on = opts.on !== false;
    const arch = rackArch(opts), ir = opts.format === 'ir';
    const L = RACK_LOOK[arch.look] || RACK_LOOK['console-60s'];
    const voice = NAM_VOICE[arch.kind] || (arch.kind ? { label: arch.kind } : NAM_VOICE.preamp);
    const set = Object.assign({}, outboardSetting(opts.label), opts.setting || {}, opts.program != null ? { program: opts.program } : {});
    const W = 112, H = 200, title = opts.title || arch.short || arch.name || 'outboard';
    const top = 42, bottom = H - 34;
    // rows: a wide control alone, small ones in pairs; bound controls first in priority
    const ctls = irControls(arch, ir).filter(c => c.type !== 'leds' && (c.type !== 'badge' || (c.bind && set[c.bind] != null)))
      .map(c => c.type === 'buttons' && (c.values || []).length * 21 > W - 16 ? Object.assign({}, c, { type: 'stepped' }) : c);
    const MOTIF = new Set(['spring', 'tape', 'bbd']);
    const wide = c => c.type === 'stepped' || c.type === 'vu' || c.type === 'buttons' || c.type === 'program' || MOTIF.has(c.type) || c.size === 'big';
    const rowH = r => { const t = r.items[0].type, sel = r.items[0].style === 'selector';
      return !r.wide ? 44 : t === 'buttons' ? 34 : t === 'vu' || t === 'bbd' ? 40 : t === 'program' && !sel ? 36 : t === 'spring' ? 46 : t === 'tape' ? 58 : 54; };
    const layout = list => {
      const rows = [];
      list.forEach(c => {
        const last = rows[rows.length - 1];
        if (!wide(c) && last && !last.wide && last.items.length < 2) last.items.push(c);
        else rows.push({ wide: wide(c), items: [c] });
      });
      return rows;
    };
    const height = rows => rows.reduce((a, r) => a + rowH(r), 0);
    // the program first, then the capture's own setting, then the meter or the unit's window, then the
    // rest, while the column has room; drawn in the unit's own order
    const flat = ctls.map((c, i) => Object.assign({}, c, { size: undefined, _i: i }));
    const show = c => c.type === 'vu' || MOTIF.has(c.type);
    const prio = flat.filter(c => c.type === 'program').concat(flat.filter(c => c.bind && c.type !== 'program'),
      flat.filter(c => !c.bind && show(c)), flat.filter(c => !c.bind && !show(c) && c.type !== 'program'));
    let chosen = [];
    prio.forEach(c => {
      const next = chosen.concat(c).sort((a, b) => a._i - b._i);
      if (height(layout(next)) <= bottom - top) chosen = next;
    });
    const rows = layout(chosen);
    const used = () => height(rows);
    const spare = Math.max(0, (bottom - top - used()) / (rows.length + 1));
    let y = top + spare;
    const body = rows.map(r => {
      const h = rowH(r), cy = y + h / 2 - 5;
      y += h + spare;
      if (r.wide) return rackFixed(r.items[0], rackControl(r.items[0], W / 2, cy, h + 6, set, L, on, W - 12), ir);
      if (r.items.length === 1) return rackFixed(r.items[0], rackControl(r.items[0], W / 2, cy, h, set, L, on, W - 12), ir);
      return r.items.map((c, i) => rackFixed(c, rackControl(c, W * (i ? .73 : .27), cy, h, set, L, on, W / 2), ir)).join('');
    }).join('');
    const screws = [[W / 2, 7], [W / 2, H - 7]].map(([x, yy]) => `<rect x="${x - 7}" y="${yy - 3.4}" width="14" height="6.8" rx="3.4" fill="#0b0c0e"/><circle cx="${x}" cy="${yy}" r="2.5" fill="#9aa3ad"/><circle cx="${x - .5}" cy="${yy - .5}" r=".9" fill="#eef1f4"/>`).join('');
    const tsize = String(title).length > 7 ? 11 : 15;
    return `<svg class="gp-pedal gp-nam-module${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" role="img" aria-label="${ir ? 'IR' : 'NAM'} outboard — ${esc(title)}" data-archetype="${esc(arch.id || '')}"${ir ? ' data-format="ir"' : ''}>
<g filter="url(#gp-shadow)">
  <rect x="0" y="5" width="${W}" height="${H}" rx="3" fill="#0b0c0e"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="${L.panel}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="url(#${L.tex})" opacity="${L.tex === 'gp-brush-lines' ? .55 : .35}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="url(#gp-sheen)" opacity=".45"/>
</g>
${screws}
<text x="${W / 2}" y="28" text-anchor="middle" font-family="${FONT.nam}" font-size="${tsize}" font-weight="800" letter-spacing="1.2" fill="${L.ink}">${esc(String(title).toUpperCase().slice(0, 11))}</text>
<text x="${W / 2}" y="38" text-anchor="middle" font-family="${FONT.gfx}" font-size="5.6" font-weight="600" letter-spacing="1.1" fill="${L.sub}">${esc(String(arch.sub || voice.label).toUpperCase().slice(0, 22))}</text>
${body}
<circle cx="${W / 2 - 18}" cy="${H - 18}" r="5" fill="#26282b"/>
<circle cx="${W / 2 - 18}" cy="${H - 18}" r="3.6" fill="${on ? L.lamp : mix(L.lamp, '#000', .7)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
<circle cx="${W / 2 - 18}" cy="${H - 18}" r="3.6" fill="url(#gp-jewel)"/>
${ir ? irBadge(W / 2 + 3, H - 18, L) : `<text x="${W / 2 - 8}" y="${H - 15.5}" font-family="${FONT.nam}" font-size="6.4" font-weight="700" letter-spacing="1.2" fill="${L.sub}">NAM</text>`}
${glyphAt(rackGlyph(arch.kind, ir), W / 2 + 26, H - 18, 10, L.sub, 2)}
</svg>`;
  }

  // ---------- keys: golem's instruments and synth presets ----------
  // A period and a material per family, never a maker's livery: a black-lacquer upright piano, an
  // 80s FM keyboard in graphite, a walnut tonewheel organ with drawbars, a synth whose panel takes the
  // preset's style colour and shows its four macros.
  const KEYS_STYLE_HUE = {
    pad: '#7a6cf0', lead: '#ff5a3c', keys: '#e0b23a', bass: '#3d9be9', pluck: '#2ecc71',
    arp: '#00a8c0', sfx: '#e06ac0', drone: '#5a7cff', experiment: '#72c000',
    sequence: '#18c4a8', percussion: '#f08a24',
  };

  // a keybed at (x, y), w x h; `held` lists the white-key indices pressed (a chord when on)
  function keybed(x, y, w, h, opts) {
    opts = opts || {};
    const n = Math.max(8, Math.round(w / (opts.keyW || 17)));
    const kw = w / n, held = new Set(opts.held || []), tint = opts.tint || '#ffd27a';
    const black = new Set([0, 1, 3, 4, 5]); // after C, D, F, G, A
    let whites = '', blacks = '';
    for (let i = 0; i < n; i++) {
      const kx = x + i * kw, down = held.has(i);
      const nat = opts.reverse ? '#2a1d14' : opts.ivory || '#f6f1e4';
      whites += `<rect x="${kx.toFixed(2)}" y="${y}" width="${(kw - .8).toFixed(2)}" height="${h - (down ? 0 : 1.5)}" rx="1.6" fill="${down ? mix(nat, tint, .35) : nat}" stroke="#000" stroke-opacity=".25" stroke-width=".6"/>`;
      if (!down) whites += `<rect x="${kx.toFixed(2)}" y="${y + h - 4}" width="${(kw - .8).toFixed(2)}" height="2.5" fill="#000" opacity=".12"/>`;
      if (black.has(i % 7) && i < n - 1) {
        const bw = kw * .6, bx = kx + kw - bw / 2 - .4;
        blacks += `<rect x="${bx.toFixed(2)}" y="${y}" width="${bw.toFixed(2)}" height="${(h * .6).toFixed(1)}" rx="1.2" fill="${opts.reverse ? '#efe6d2' : '#141416'}"/>
  <rect x="${(bx + bw * .18).toFixed(2)}" y="${y + 1}" width="${(bw * .64).toFixed(2)}" height="${(h * .6 - 5).toFixed(1)}" rx="1" fill="${opts.reverse ? '#fffaf0' : '#3a3b40'}" opacity=".55"/>`;
      }
    }
    return `<g class="gp-keybed"><rect x="${x - 1}" y="${y - 2}" width="${w + 2}" height="${h + 3}" fill="#0b0b0c"/>${whites}${blacks}
  <rect x="${x - 1}" y="${y - 2}" width="${w + 2}" height="4" fill="${opts.rail || '#5a1d1d'}"/></g>`;
  }
  // a C major triad (C, E, G) in the keybed's middle octave
  const triad = n => { const c = Math.max(0, Math.floor(n / 14) * 7); return [c, c + 2, c + 4]; };

  function keysLamp(cx, cy, col, on) {
    return `<circle cx="${cx}" cy="${cy}" r="4.6" fill="#1a1b1d"/><circle cx="${cx}" cy="${cy}" r="3.2" fill="${on ? col : mix(col, '#000', .72)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/><circle cx="${cx}" cy="${cy}" r="3.2" fill="url(#gp-jewel)"/>`;
  }
  function keysText(x, y, s, size, fill, opts) {
    opts = opts || {};
    return `<text x="${x}" y="${y}" text-anchor="${opts.anchor || 'middle'}" font-family="${opts.font || FONT.nam}" font-size="${size}" font-weight="${opts.weight || 800}" letter-spacing="${opts.ls != null ? opts.ls : 1.4}" fill="${fill}"${opts.opacity ? ` opacity="${opts.opacity}"` : ''}>${esc(s)}</text>`;
  }

  function keysPiano(W, title, on) {
    const H = 236, K = 70, ky = H - K - 10, cheek = 26;
    const kn = Math.round((W - 2 * cheek) / 17), held = on ? triad(kn) : [];
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="#111214"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="url(#gp-gloss)" opacity=".55"/>
  <rect x="0" y="0" width="${W}" height="14" rx="5" fill="#1d1e21"/>
  <rect x="18" y="26" width="${W - 36}" height="${ky - 74}" rx="4" fill="#0c0d0e" stroke="#2a2b2f"/>
  <rect x="34" y="38" width="${(W - 84) / 2}" height="${ky - 98}" rx="3" fill="none" stroke="#2c2d31" stroke-width="1.4"/>
  <rect x="${W / 2 + 8}" y="38" width="${(W - 84) / 2}" height="${ky - 98}" rx="3" fill="none" stroke="#2c2d31" stroke-width="1.4"/>
  <rect x="18" y="26" width="${W - 36}" height="${ky - 74}" rx="4" fill="url(#gp-sheen)" opacity=".35"/>
</g>
  <rect x="${cheek - 6}" y="${ky - 42}" width="${W - 2 * cheek + 12}" height="34" rx="3" fill="#0e0f10" stroke="#2c2d31"/>
  <rect x="${cheek - 6}" y="${ky - 42}" width="${W - 2 * cheek + 12}" height="34" rx="3" fill="url(#gp-gloss)" opacity=".4"/>
  ${keysText(W / 2, ky - 20, String(title).toUpperCase().slice(0, 22), 14, '#d9c08a', { ls: 4 })}
  ${on ? `<rect x="${W / 2 - 60}" y="${ky - 15}" width="120" height="1.2" fill="#d9c08a" opacity=".6"/>` : ''}
  <rect x="${cheek - 6}" y="${ky - 6}" width="${W - 2 * cheek + 12}" height="6" fill="#1b1c1f"/>
  ${keybed(cheek, ky, W - 2 * cheek, K, { held, rail: '#7a1414', tint: '#d9c08a' })}
  <path d="M0 ${ky - 44}h${cheek - 6}v${K + 54}H6a6 6 0 0 1-6-6Z" fill="#17181b"/><path d="M${W} ${ky - 44}h-${cheek - 6}v${K + 54}h${cheek - 12}a6 6 0 0 0 6-6Z" fill="#17181b"/>
  <path d="M2 ${ky - 44}h${cheek - 8}" stroke="#2f3035"/><path d="M${W - 2} ${ky - 44}h-${cheek - 8}" stroke="#2f3035"/>
  ${glyphAt('piano', cheek + 14, ky - 25, 10, '#d9c08a', 2)}` };
  }

  function keysEpiano(W, title, on) {
    const H = 196, K = 74, ky = H - K - 10, cheek = 14, panel = '#2b2c2f', ink = '#cfd3d8';
    const kn = Math.round((W - 2 * cheek) / 15), held = on ? triad(kn) : [];
    // membrane buttons: two banks, one coral accent row
    let btn = '';
    const bx0 = 238, cols = 16, bw = (W - bx0 - 34) / cols;
    for (let r = 0; r < 2; r++) for (let i = 0; i < cols; i++) {
      const fill = r === 0 ? (i < 6 ? '#c96a52' : i < 12 ? '#5f7f86' : '#8b8f95') : '#4a4d52';
      btn += `<rect x="${(bx0 + i * bw).toFixed(1)}" y="${26 + r * 28}" width="${(bw - 4).toFixed(1)}" height="14" rx="1.2" fill="${fill}" opacity="${r === 1 ? .9 : .95}"/>
  <text x="${(bx0 + i * bw + (bw - 4) / 2).toFixed(1)}" y="${48 + r * 28}" text-anchor="middle" font-family="${FONT.gfx}" font-size="5.6" font-weight="700" fill="${ink}" opacity=".55">${r * cols + i + 1}</text>`;
    }
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="${panel}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-brush-lines)" opacity=".25"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-sheen)" opacity=".4"/>
</g>
  <rect x="0" y="${ky - 22}" width="${W}" height="3" fill="#c96a52" opacity=".85"/>
  <rect x="22" y="22" width="118" height="34" rx="2" fill="#0d1314" stroke="#000"/>
  <rect x="26" y="26" width="110" height="26" rx="1" fill="${on ? '#5fd4c4' : '#1f3b38'}" opacity="${on ? .9 : 1}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  ${keysText(31, 37, String(title).toUpperCase().slice(0, 16), 8.4, on ? '#0b2522' : '#2f5a55', { anchor: 'start', font: FONT.gfx, weight: 700, ls: .8 })}
  ${keysText(31, 48, 'FM  E.PIANO', 7, on ? '#0b2522' : '#2f5a55', { anchor: 'start', font: FONT.gfx, weight: 600, ls: 1 })}
  <rect x="160" y="22" width="12" height="52" rx="2" fill="#151618"/><rect x="157" y="${on ? 36 : 54}" width="18" height="9" rx="1.5" fill="#9aa0a7"/>
  ${keysText(166, 86, 'DATA', 6, ink, { font: FONT.gfx, weight: 700, ls: 1 })}
  <rect x="190" y="26" width="30" height="14" rx="1.2" fill="#5f7f86"/><rect x="190" y="54" width="30" height="14" rx="1.2" fill="#5f7f86"/>
  ${btn}
  ${keysText(22, 86, 'FREQUENCY MODULATION', 6.4, ink, { anchor: 'start', font: FONT.gfx, weight: 700, ls: 1.8, opacity: .75 })}
  ${keysLamp(W - 22, 18, '#ff3b2a', on)}
  ${keybed(cheek, ky, W - 2 * cheek, K, { keyW: 15, held, rail: '#1a1b1d', tint: '#5fd4c4' })}
  ${glyphAt('ep', W - 44, 18, 9, ink, 2)}` };
  }

  // drawbars: 9 pulls, opts.drawbars = '888000000' (0 = in, 8 = fully out)
  function keysOrgan(W, title, on, opts) {
    const H = 260, K = 52, cheek = 30, ky2 = H - K - 14, ky1 = ky2 - K - 8;
    const wood = '#5b3a22', woodDark = '#3a2414';
    const reg = String(opts.drawbars || '888000000').replace(/\D/g, '').padEnd(9, '0').slice(0, 9).split('').map(Number);
    const tips = ['#5a3418', '#5a3418', '#f1ece0', '#f1ece0', '#141414', '#f1ece0', '#141414', '#141414', '#f1ece0'];
    const feet = ["16'", "5⅓'", "8'", "4'", "2⅔'", "2'", "1⅗'", "1⅓'", "1'"];
    const dx0 = W / 2 - 4.5 * 26, dy = 22;
    const bars = reg.map((v, i) => {
      const x = dx0 + i * 26 + 13, len = 8 + v * 6.2;
      return `<rect x="${x - 3.2}" y="${dy}" width="6.4" height="${len}" fill="url(#gp-chrome)"/>
  <rect x="${x - 8}" y="${dy + len}" width="16" height="16" rx="3" fill="${tips[i]}" stroke="#000" stroke-opacity=".45"/>
  <rect x="${x - 6}" y="${dy + len + 2}" width="12" height="4" rx="2" fill="#fff" opacity=".18"/>
  <text x="${x}" y="${dy + len + 12}" text-anchor="middle" font-family="Arial,'DejaVu Sans',sans-serif" font-size="5.4" font-weight="700" fill="${tips[i] === '#f1ece0' ? '#222' : '#ddd'}">${feet[i]}</text>`;
    }).join('');
    const tabs = ['perc', 'soft', 'fast', '3rd'].map((l, i) => `<rect x="${44 + i * 22}" y="40" width="16" height="26" rx="2" fill="${i === 0 && on ? '#f1ece0' : '#d8d0bf'}"/><rect x="${44 + i * 22}" y="${i === 0 && on ? 40 : 53}" width="16" height="13" rx="2" fill="#000" opacity=".12"/>
  ${keysText(52 + i * 22, 78, l.toUpperCase(), 5.6, '#e9dcc4', { font: FONT.gfx, weight: 700, ls: .6 })}`).join('');
    const kn = Math.round((W - 2 * cheek) / 16);
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="${wood}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-brush-lines)" opacity=".5"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-sheen)" opacity=".45"/>
  <rect x="0" y="0" width="${W}" height="10" rx="4" fill="${woodDark}"/>
</g>
  <rect x="${cheek}" y="16" width="${W - 2 * cheek}" height="${ky1 - 30}" rx="3" fill="#1a120b" opacity=".55"/>
  ${tabs}${bars}
  ${keysText(W - 104, 52, String(title).toUpperCase().slice(0, 16), 10, '#e9dcc4', { ls: 1.2 })}
  ${keysText(W - 104, 64, 'TONEWHEEL', 6.4, '#e9dcc4', { font: FONT.gfx, weight: 600, ls: 2, opacity: .75 })}
  <path d="M${W - 120} 78a10 10 0 0 1 20 0Z" fill="#d8d0bf"/><path d="M${W - 110} 78L${W - 110 + (on ? 7 : -7)} 70" stroke="#3a2414" stroke-width="2.2" stroke-linecap="round"/>
  ${keysText(W - 110, 88, 'SLOW · FAST', 5.4, '#e9dcc4', { font: FONT.gfx, weight: 700, ls: .6 })}
  ${keysLamp(W - 60, 76, '#ff3b2a', on)}
  ${keybed(cheek, ky1, W - 2 * cheek, K, { keyW: 16, rail: '#1a120b', held: [] })}
  <rect x="${cheek}" y="${ky1 + K + 1}" width="${W - 2 * cheek}" height="7" fill="${woodDark}"/>
  ${keybed(cheek, ky2, W - 2 * cheek, K, { keyW: 16, rail: '#1a120b', held: on ? triad(kn) : [], tint: '#ffb03a' })}
  <rect x="0" y="${ky1 - 6}" width="${cheek}" height="${H - ky1 + 6}" fill="${woodDark}"/><rect x="${W - cheek}" y="${ky1 - 6}" width="${cheek}" height="${H - ky1 + 6}" fill="${woodDark}"/>
  ${glyphAt('organ', 34, 20, 10, '#e9dcc4', 2)}` };
  }

  // the style's wave on the screen
  function styleWave(style, x, y, w, h) {
    const N = 48, pts = [];
    for (let i = 0; i <= N; i++) {
      const t = i / N, ph = t * Math.PI * 2 * 2.5;
      let v;
      switch (style) {
        case 'lead': v = ((t * 5) % 1) * 2 - 1; break;
        case 'bass': v = Math.sin(ph) > 0 ? .85 : -.85; break;
        case 'pluck': v = Math.sin(ph * 2) * Math.exp(-t * 4); break;
        case 'arp': v = [-.6, .1, .7, .1][Math.floor(t * 8) % 4]; break;
        case 'sequence': v = [-.7, -.2, .5, -.2, .8, .2, -.4, .3][Math.floor(t * 16) % 8] * (((t * 16) % 1) < .6 ? 1 : .15); break;
        case 'percussion': { const k = (t * 4) % 1; v = Math.sin(k * 45) * Math.exp(-k * 7) * .95; break; }
        case 'sfx': v = Math.sin(ph * 3.3 + Math.sin(ph * 7.1) * 2) * .9; break;
        case 'drone': v = Math.sin(ph * .4) * .7; break;
        case 'experiment': v = Math.sin(ph * 1.7) * Math.cos(ph * 4.3) ; break;
        case 'keys': v = (Math.sin(ph) + .35 * Math.sin(ph * 3)) * .75; break;
        default: v = (Math.sin(ph) * .6 + Math.sin(ph * 1.5) * .3);
      }
      pts.push(`${(x + t * w).toFixed(1)} ${(y + h / 2 - v * h * .42).toFixed(1)}`);
    }
    return `M${pts.join('L')}`;
  }

  function keysSynth(W, title, on, opts) {
    const style = synthStyle(opts.style);
    const hue = KEYS_STYLE_HUE[style] || '#8a94a3';
    const H = 214, K = 66, ky = H - K - 10, cheek = 22, wheels = 46;
    const panel = mix(hue, '#16181b', .72), ink = mix(hue, '#ffffff', .65);
    const macros = (opts.macros && opts.macros.length ? opts.macros : [1, 2, 3, 4].map(i => ({ name: `macro ${i}`, value: .5 }))).slice(0, 4);
    const sx = cheek + 18, sy = 20, sw = 176, sh = 58;
    const kx0 = sx + sw + 34, kx1 = W - cheek - 46, step = (kx1 - kx0) / 4;
    const knobs = macros.map((m, i) => {
      const v = Math.max(0, Math.min(1, +m.value || 0)), cx = kx0 + step * (i + .5), cy = 48, r = 15;
      const a = -135 + 270 * v, arc = (from, to) => { const [ax, ay] = polar(cx, cy, r + 5, from), [bx, by] = polar(cx, cy, r + 5, to);
        return `M${ax.toFixed(1)} ${ay.toFixed(1)}A${r + 5} ${r + 5} 0 ${to - from > 180 ? 1 : 0} 1 ${bx.toFixed(1)} ${by.toFixed(1)}`; };
      return `<path d="${arc(-135, 135)}" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="3" stroke-linecap="round"/>
  ${v > .005 ? `<path d="${arc(-135, a)}" fill="none" stroke="${on ? hue : mix(hue, '#000', .5)}" stroke-width="3" stroke-linecap="round"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>` : ''}
  ${knobAlu(cx, cy, r, { min: 0, max: 1, default: v }, '', ink).replace('</g>', '')}</g>
  ${keysText(cx, cy + r + 17, String(m.name || `macro ${i + 1}`).toUpperCase().slice(0, 12), 6.8, ink, { font: FONT.gfx, weight: 700, ls: .8 })}`;
    }).join('');
    const kn = Math.round((W - 2 * cheek - wheels) / 16);
    const wheel = (x, pos) => `<rect x="${x}" y="${ky + 6}" width="13" height="${K - 14}" rx="3" fill="#0b0c0d"/><rect x="${x + 2}" y="${ky + 8 + pos}" width="9" height="16" rx="2" fill="#3a3d42"/><path d="M${x + 3} ${ky + 16 + pos}h7" stroke="#6a6f75"/>`;
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="${panel}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="url(#gp-brush-lines)" opacity=".35"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="url(#gp-sheen)" opacity=".45"/>
</g>
  <rect x="${sx - 4}" y="${sy - 4}" width="${sw + 8}" height="${sh + 8}" rx="4" fill="#07080a"/>
  <rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" rx="2" fill="${on ? mix(hue, '#05070a', .82) : '#0a0c0e'}"/>
  <path d="${styleWave(style, sx + 8, sy + 22, sw - 16, sh - 26)}" fill="none" stroke="${on ? mix(hue, '#fff', .25) : mix(hue, '#000', .55)}" stroke-width="1.6"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  ${keysText(sx + 8, sy + 14, String(title).toUpperCase().slice(0, 22), 9, on ? '#eef0f2' : '#5a5f66', { anchor: 'start', font: FONT.gfx, weight: 700, ls: .8 })}
  ${keysText(sx + sw - 8, sy + 14, style.toUpperCase(), 6.6, on ? hue : mix(hue, '#000', .5), { anchor: 'end', font: FONT.gfx, weight: 700, ls: 1.4 })}
  <rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" rx="2" fill="url(#gp-glass-glare)"/>
  ${knobs}
  ${keysLamp(W - cheek - 20, 26, hue, on)}
  ${keysText(W - cheek - 20, 46, 'SYNTH', 6, ink, { font: FONT.gfx, weight: 700, ls: 1.2, opacity: .7 })}
  <rect x="${cheek}" y="${ky - 8}" width="${W - 2 * cheek}" height="3" fill="${hue}" opacity="${on ? .9 : .4}"/>
  <rect x="${cheek}" y="${ky - 2}" width="${wheels}" height="${K + 3}" fill="#141518"/>
  ${wheel(cheek + 6, 18)}${wheel(cheek + 25, 30)}
  ${keybed(cheek + wheels, ky, W - 2 * cheek - wheels, K, { keyW: 16, held: on ? triad(kn) : [], rail: '#0b0c0d', tint: hue })}
  <rect x="0" y="0" width="${cheek}" height="${H}" rx="6" fill="#4a3020"/><rect x="${W - cheek}" y="0" width="${cheek}" height="${H}" rx="6" fill="#4a3020"/>
  <rect x="0" y="0" width="${cheek}" height="${H}" rx="6" fill="url(#gp-brush-lines)" opacity=".5"/><rect x="${W - cheek}" y="0" width="${cheek}" height="${H}" rx="6" fill="url(#gp-brush-lines)" opacity=".5"/>
  ${glyphAt('piano', sx + sw + 16, 20, 8, ink, 2)}` };
  }

  // the electric-piano families a program falls into, from its title (golem's curated FM programs:
  // "TINE E.PNO", "WURLI/TREM", "CLAVINET 1", "HARPSICH 2", "VIBE 1"…); 'fm' when none fits
  const EP_FAMILIES = ['fm', 'tine', 'reed', 'clav', 'harpsichord', 'mallet'];
  function keysFamily(title) {
    const t = String(title || '').toLowerCase();
    if (/harpsi|cemb/.test(t)) return 'harpsichord';
    if (/clav/.test(t)) return 'clav';
    if (/wurl|reed/.test(t)) return 'reed';
    if (/vibe|vibra|marimba|xylo|mallet|glock|celest/.test(t)) return 'mallet';
    if (/rhodes|tine|suitcase|stage/.test(t)) return 'tine';
    return 'fm';
  }
  // golem's Vital `preset_style` names that differ from ours
  const STYLE_ALIAS = { sequence: 'sequence', seq: 'sequence', percussion: 'percussion', perc: 'percussion', arpeggio: 'arp' };
  const synthStyle = s => { s = String(s || '').toLowerCase().trim(); s = STYLE_ALIAS[s] || s; return KEYS_STYLE_HUE[s] ? s : 'synth'; };

  // a tolex-covered body (the tine piano's case)
  const tolexRect = (x, y, w, h, rx, fill) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}"/><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="#fff" filter="url(#gp-tolex)" opacity=".5"/>`;
  const smallKnob = (cx, cy, r, v, label, ink, cap) => {
    const a = -135 + 270 * v, [px, py] = polar(cx, cy, r * .82, a);
    return `<circle cx="${cx}" cy="${cy + 1}" r="${r}" fill="#000" opacity=".35"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="${cap || '#17191b'}"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-sheen)" opacity=".45"/>
  <path d="M${cx} ${cy}L${px.toFixed(1)} ${py.toFixed(1)}" stroke="${luma(cap || '#17191b') > .5 ? '#222' : '#eee'}" stroke-width="1.4" stroke-linecap="round"/>
  ${label ? keysText(cx, cy + r + 9, label.toUpperCase(), 5.8, ink, { font: FONT.gfx, weight: 700, ls: .8 }) : ''}`;
  };

  function keysTine(W, title, on) {
    const H = 206, K = 72, ky = H - K - 12, cheek = 18;
    const kn = Math.round((W - 2 * cheek) / 16);
    return { H, svg: `<g filter="url(#gp-shadow-small)">${tolexRect(0, 0, W, H, 9, '#1c1c1e')}
  <rect x="0" y="0" width="${W}" height="${H}" rx="9" fill="url(#gp-sheen)" opacity=".35"/></g>
  <rect x="${cheek}" y="16" width="${W - 2 * cheek}" height="${ky - 40}" rx="3" fill="url(#gp-brushed)"/>
  <rect x="${cheek}" y="16" width="${W - 2 * cheek}" height="${ky - 40}" rx="3" fill="url(#gp-brush-lines)" opacity=".6"/>
  ${keysText(cheek + 18, 16 + (ky - 40) / 2 + 6, String(title).toUpperCase().slice(0, 18), 16, '#202226', { anchor: 'start', ls: 3 })}
  ${smallKnob(W - 190, 16 + (ky - 40) / 2 - 3, 10, .7, 'volume', '#202226')}${smallKnob(W - 150, 16 + (ky - 40) / 2 - 3, 10, .45, 'bass', '#202226')}
  ${smallKnob(W - 110, 16 + (ky - 40) / 2 - 3, 10, on ? .35 : 0, 'vibrato', '#202226')}
  ${keysLamp(W - 60, 16 + (ky - 40) / 2 - 3, '#ff3b2a', on)}
  <rect x="${cheek}" y="${ky - 14}" width="${W - 2 * cheek}" height="10" fill="#0e0e0f"/>
  ${keybed(cheek, ky, W - 2 * cheek, K, { keyW: 16, held: on ? triad(kn) : [], rail: '#7a1414', tint: '#ffb03a' })}
  ${glyphAt('ep', W - 38, 32, 9, '#202226', 2)}` };
  }

  function keysReed(W, title, on) {
    const H = 214, K = 70, ky = H - K - 12, cheek = 24, body = '#d6c6a3', ink = '#4a3622';
    const kn = Math.round((W - 2 * cheek) / 16);
    const grille = Array.from({ length: 6 }, (_, r) => Array.from({ length: 9 }, (_, c) =>
      `<circle cx="${cheek + 22 + c * 7 + (r % 2) * 3.5}" cy="${34 + r * 7}" r="1.8" fill="#2a2016" opacity=".7"/>`).join('')).join('');
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <path d="M0 ${ky - 6}V40Q0 6 40 6H${W - 40}Q${W} 6 ${W} 40V${H - 6}a6 6 0 0 1-6 6H6a6 6 0 0 1-6-6Z" fill="${body}"/>
  <path d="M0 ${ky - 6}V40Q0 6 40 6H${W - 40}Q${W} 6 ${W} 40V${H - 6}a6 6 0 0 1-6 6H6a6 6 0 0 1-6-6Z" fill="url(#gp-sheen)" opacity=".55"/></g>
  <path d="M10 ${ky - 30}H${W - 10}" stroke="#b9a681" stroke-width="2"/>
  ${grille}
  <rect x="${W / 2 - 110}" y="34" width="220" height="30" rx="4" fill="url(#gp-chrome)"/>
  ${keysText(W / 2, 54, String(title).toUpperCase().slice(0, 18), 14, ink, { ls: 3 })}
  ${smallKnob(W - 120, 50, 9, .6, 'volume', ink, '#f1ece0')}${smallKnob(W - 84, 50, 9, on ? .5 : 0, 'vibrato', ink, '#f1ece0')}
  ${keysLamp(W - 48, 50, '#ff5a3c', on)}
  <rect x="${cheek - 4}" y="${ky - 8}" width="${W - 2 * cheek + 8}" height="8" fill="#2a2016"/>
  ${keybed(cheek, ky, W - 2 * cheek, K, { keyW: 16, held: on ? triad(kn) : [], rail: '#2a2016', tint: '#ff5a3c' })}
  ${glyphAt('ep', cheek + 100, 52, 9, ink, 2)}` };
  }

  function keysClav(W, title, on) {
    const H = 196, K = 66, ky = H - K - 12, cheek = 22, wood = '#a8743f';
    const kn = Math.round((W - 2 * cheek) / 16);
    const tabs = ['brill', 'treble', 'medium', 'soft', 'a·b', 'c·d'].map((l, i) => {
      const x = W - 300 + i * 34, down = on ? i === 0 || i === 4 : false;
      return `<rect x="${x}" y="30" width="24" height="30" rx="2" fill="${i < 4 ? '#e9dcc4' : '#c9452e'}"/><rect x="${x}" y="${down ? 30 : 45}" width="24" height="15" rx="2" fill="#000" opacity=".16"/>
  ${keysText(x + 12, 72, l.toUpperCase(), 5.6, '#e9dcc4', { font: FONT.gfx, weight: 700, ls: .5 })}`;
    }).join('');
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="${wood}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-brush-lines)" opacity=".55"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-sheen)" opacity=".4"/></g>
  <rect x="${cheek}" y="16" width="${W - 2 * cheek}" height="${ky - 30}" rx="3" fill="#18181a"/>
  ${keysText(cheek + 18, 52, String(title).toUpperCase().slice(0, 16), 14, '#e9dcc4', { anchor: 'start', ls: 2.6 })}
  ${tabs}
  <rect x="${W - 82}" y="36" width="6" height="34" rx="3" fill="#0b0b0c"/><rect x="${W - 86}" y="${on ? 40 : 58}" width="14" height="9" rx="2" fill="#9aa0a7"/>
  ${keysText(W - 79, 82, 'MUTE', 5.6, '#e9dcc4', { font: FONT.gfx, weight: 700, ls: .6 })}
  ${keysLamp(W - 48, 44, '#ff3b2a', on)}
  ${keybed(cheek, ky, W - 2 * cheek, K, { keyW: 16, held: on ? triad(kn) : [], rail: '#18181a', tint: '#c9452e' })}
  ${glyphAt('ep', cheek + 12, 28, 8, '#e9dcc4', 2)}` };
  }

  function keysHarpsichord(W, title, on) {
    const H = 236, K = 62, ky = H - K - 14, cheek = 30, wood = '#6b4226', gold = '#d9b25a';
    const kn = Math.round((W - 2 * cheek) / 15);
    const strings = Array.from({ length: 28 }, (_, i) => { const x = cheek + 16 + i * ((W - 2 * cheek - 32) / 27);
      return `<path d="M${x.toFixed(1)} ${ky - 22}L${(x + 30 - i * 1.6).toFixed(1)} 30" stroke="${gold}" stroke-width=".6" opacity="${on ? .7 : .4}"/>`; }).join('');
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="4" fill="${wood}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="4" fill="url(#gp-brush-lines)" opacity=".5"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="4" fill="url(#gp-sheen)" opacity=".4"/></g>
  <rect x="6" y="6" width="${W - 12}" height="${H - 12}" rx="3" fill="none" stroke="${gold}" stroke-width="1.2" opacity=".8"/>
  <path d="M${cheek} ${ky - 18}L${cheek + 40} 22H${W - cheek - 40}L${W - cheek} ${ky - 18}Z" fill="#c9a77a"/>
  <path d="M${cheek} ${ky - 18}L${cheek + 40} 22H${W - cheek - 40}L${W - cheek} ${ky - 18}Z" fill="url(#gp-brush-lines)" opacity=".4"/>
  ${strings}
  <rect x="${W / 2 - 100}" y="${ky - 50}" width="200" height="22" rx="2" fill="#2a1a10" stroke="${gold}" stroke-width=".8"/>
  ${keysText(W / 2, ky - 34, String(title).toUpperCase().slice(0, 20), 11, gold, { ls: 3 })}
  <rect x="${cheek - 4}" y="${ky - 14}" width="${W - 2 * cheek + 8}" height="12" fill="#3a2414"/>
  ${keybed(cheek, ky, W - 2 * cheek, K, { keyW: 15, held: on ? triad(kn) : [], rail: '#3a2414', tint: gold, reverse: true })}
  ${glyphAt('ep', W - cheek - 20, ky - 39, 8, gold, 2)}` };
  }

  // a vibraphone: graduated bars over resonators, in keyboard order
  function malletBars(x, y, w, h, n, on, accent) {
    const bw = w / n, held = on ? new Set(triad(n)) : new Set();
    const black = new Set([0, 1, 3, 4, 5]);
    let s = '';
    for (let i = 0; i < n; i++) {
      const len = h * (1 - .38 * i / n), bx = x + i * bw, by = y + h * .42 + (h - len) / 2;
      s += `<rect x="${(bx + bw * .3).toFixed(1)}" y="${(by + len).toFixed(1)}" width="${(bw * .4).toFixed(1)}" height="${(h * .32).toFixed(1)}" fill="#55595f" opacity=".6"/>
  <rect x="${(bx + 1).toFixed(1)}" y="${(by).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${(len * .55).toFixed(1)}" rx="1.5" fill="${held.has(i) ? mix('#cfd3d8', accent, .45) : '#c9ced4'}"${held.has(i) ? ' filter="url(#gp-glow-soft)"' : ''}/>
  <rect x="${(bx + 1).toFixed(1)}" y="${(by).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${(len * .55).toFixed(1)}" rx="1.5" fill="url(#gp-brush-lines)" opacity=".5"/>`;
      if (black.has(i % 7) && i < n - 1) {
        const ax = bx + bw * .55, alen = len * .45;
        s += `<rect x="${ax.toFixed(1)}" y="${(y + (h * .42 - alen) / 2).toFixed(1)}" width="${(bw * .9).toFixed(1)}" height="${alen.toFixed(1)}" rx="1.5" fill="#b8bec5"/>
  <rect x="${ax.toFixed(1)}" y="${(y + (h * .42 - alen) / 2).toFixed(1)}" width="${(bw * .9).toFixed(1)}" height="${alen.toFixed(1)}" rx="1.5" fill="url(#gp-brush-lines)" opacity=".5"/>`;
      }
    }
    return `<g class="gp-bars"><path d="M${x} ${y + h * .2}H${x + w}M${x} ${y + h * .62}H${x + w}" stroke="#8a2a1a" stroke-width="1.2" opacity=".7"/>${s}</g>`;
  }
  function keysMallet(W, title, on) {
    const H = 200, cheek = 18, top = 46;
    return { H, svg: `<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="#26282c"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="6" fill="url(#gp-sheen)" opacity=".4"/></g>
  ${keysText(cheek + 8, 30, String(title).toUpperCase().slice(0, 18), 13, '#e2e6ea', { anchor: 'start', ls: 2.6 })}
  <circle cx="${W - 92}" cy="25" r="11" fill="#17181a" stroke="#55595f"/>
  <path d="M${W - 92} 25l${on ? 7 : 0} ${on ? -6 : -9}M${W - 92} 25l${on ? -8 : 0} ${on ? 3 : 9}" stroke="#9aa0a7" stroke-width="2" stroke-linecap="round"/>
  ${keysText(W - 92, 44, 'MOTOR', 5.6, '#9aa0a7', { font: FONT.gfx, weight: 700, ls: .8 })}
  ${keysLamp(W - 48, 25, '#ffb03a', on)}
  ${malletBars(cheek, top, W - 2 * cheek, H - top - 10, 30, on, '#ffb03a')}
  ${glyphAt('ep', cheek + 4, 14, 7, '#e2e6ea', 2)}` };
  }

  // ---------- compact: a tile for a wall of sounds (~230 px wide) ----------
  const KEYS_COMPACT = {
    piano: { body: '#111214', panel: '#0c0d0e', ink: '#d9c08a', rail: '#7a1414' },
    fm: { body: '#2b2c2f', panel: '#1d1e20', ink: '#cfd3d8', rail: '#c96a52', lcd: '#5fd4c4' },
    tine: { body: '#1c1c1e', panel: 'url(#gp-brushed)', ink: '#202226', rail: '#7a1414', tolex: true },
    reed: { body: '#d6c6a3', panel: '#e6d9bd', ink: '#4a3622', rail: '#2a2016' },
    clav: { body: '#a8743f', panel: '#18181a', ink: '#e9dcc4', rail: '#18181a', wood: true },
    harpsichord: { body: '#6b4226', panel: '#2a1a10', ink: '#d9b25a', rail: '#3a2414', wood: true, reverse: true },
    mallet: { body: '#26282c', panel: '#26282c', ink: '#e2e6ea', rail: '#26282c' },
    organ: { body: '#5b3a22', panel: '#1a120b', ink: '#e9dcc4', rail: '#1a120b', wood: true },
  };
  function keysCompact(kind, family, title, on, opts) {
    const W = 300, H = 176, K = 58, ky = H - K - 8, side = 10;
    let M = KEYS_COMPACT[kind === 'epiano' ? family : kind] || KEYS_COMPACT.fm, hue = null, style = null;
    if (kind === 'synth') {
      style = synthStyle(opts.style); hue = KEYS_STYLE_HUE[style] || '#8a94a3';
      M = { body: mix(hue, '#16181b', .72), panel: '#07080a', ink: mix(hue, '#fff', .65), rail: '#0b0c0d', wood: false };
    }
    const T = String(title).toUpperCase().slice(0, 16);
    const py = 10, ph = ky - 18;
    let emblem = '';
    if (kind === 'synth') {
      emblem = `<rect x="${side + 6}" y="${py + 4}" width="${W - 2 * side - 12}" height="${ph - 8}" rx="3" fill="${on ? mix(hue, '#05070a', .82) : '#0a0c0e'}"/>
  <path d="${styleWave(style, side + 150, py + 12, W - 2 * side - 166, ph - 24)}" fill="none" stroke="${on ? mix(hue, '#fff', .25) : mix(hue, '#000', .55)}" stroke-width="1.8"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  ${keysText(side + 16, py + 26, T, 15, on ? '#eef0f2' : '#5a5f66', { anchor: 'start', ls: 1.2 })}
  ${keysText(side + 16, py + 42, style.toUpperCase(), 9, on ? hue : mix(hue, '#000', .5), { anchor: 'start', font: FONT.gfx, weight: 700, ls: 1.6 })}
  ${(opts.macros || []).slice(0, 4).map((m, i) => { const v = Math.max(0, Math.min(1, +m.value || 0));
    return `<rect x="${side + 16 + i * 30}" y="${py + ph - 22}" width="24" height="4" rx="2" fill="#000" opacity=".5"/><rect x="${side + 16 + i * 30}" y="${py + ph - 22}" width="${(24 * v).toFixed(1)}" height="4" rx="2" fill="${on ? hue : mix(hue, '#000', .5)}"/>`; }).join('')}`;
    } else if (kind === 'organ') {
      const reg = String(opts.drawbars || '888000000').replace(/\D/g, '').padEnd(9, '0').slice(0, 9).split('').map(Number);
      const tips = ['#5a3418', '#5a3418', '#f1ece0', '#f1ece0', '#141414', '#f1ece0', '#141414', '#141414', '#f1ece0'];
      emblem = keysText(side + 14, py + 28, T, 15, M.ink, { anchor: 'start', ls: 1.4 }) + reg.map((v, i) => { const x = W - side - 128 + i * 13, len = 4 + v * 4.2;
        return `<rect x="${x - 1.6}" y="${py + 6}" width="3.2" height="${len}" fill="url(#gp-chrome)"/><rect x="${x - 4.5}" y="${py + 6 + len}" width="9" height="9" rx="2" fill="${tips[i]}"/>`; }).join('');
    } else if (kind === 'epiano' && family === 'fm') {
      emblem = `<rect x="${side + 8}" y="${py + 8}" width="${W - 2 * side - 70}" height="${ph - 18}" rx="2" fill="#0d1314"/>
  <rect x="${side + 12}" y="${py + 12}" width="${W - 2 * side - 78}" height="${ph - 26}" rx="1" fill="${on ? M.lcd : '#1f3b38'}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  ${keysText(side + 20, py + 12 + (ph - 26) / 2 + 5, T, 14, on ? '#0b2522' : '#2f5a55', { anchor: 'start', font: FONT.gfx, weight: 700, ls: .8 })}
  ${[0, 1, 2].map(i => `<rect x="${W - side - 52 + i * 15}" y="${py + 12}" width="11" height="8" rx="1" fill="${['#c96a52', '#5f7f86', '#8b8f95'][i]}"/>`).join('')}`;
    } else if (kind === 'epiano' && family === 'clav') {
      emblem = keysText(side + 14, py + 30, T, 14, M.ink, { anchor: 'start', ls: 1.2 }) + [0, 1, 2, 3, 4, 5].map(i => `<rect x="${W - side - 98 + i * 15}" y="${py + 12}" width="11" height="18" rx="1.5" fill="${i < 4 ? '#e9dcc4' : '#c9452e'}"/>`).join('');
    } else {
      emblem = keysText(W / 2, py + ph / 2 + 6, T, 16, M.ink, { ls: 2.4 });
    }
    const lamp = keysLamp(W - side - 12, py + ph - 10, hue || '#ff3b2a', on);
    const lower = kind === 'epiano' && family === 'mallet'
      ? malletBars(side, ky - 4, W - 2 * side, K + 4, 18, on, '#ffb03a')
      : keybed(side, ky, W - 2 * side, K, { keyW: 14, held: on ? triad(Math.round((W - 2 * side) / 14)) : [], rail: M.rail, tint: hue || '#ffd27a', reverse: M.reverse });
    const panelFill = M.panel;
    return { W, H, svg: `<g filter="url(#gp-shadow-small)">${M.tolex ? tolexRect(0, 0, W, H, 7, M.body) : `<rect x="0" y="0" width="${W}" height="${H}" rx="7" fill="${M.body}"/>`}
  ${M.wood ? `<rect x="0" y="0" width="${W}" height="${H}" rx="7" fill="url(#gp-brush-lines)" opacity=".5"/>` : ''}
  <rect x="0" y="0" width="${W}" height="${H}" rx="7" fill="url(#gp-sheen)" opacity=".4"/></g>
  <rect x="${side}" y="${py}" width="${W - 2 * side}" height="${ph}" rx="3" fill="${panelFill}"/>
  ${kind === 'piano' ? `<rect x="${side}" y="${py}" width="${W - 2 * side}" height="${ph}" rx="3" fill="url(#gp-gloss)" opacity=".4"/>` : ''}
  ${emblem}${lamp}${lower}` };
  }

  // a keys sound: golem's built-in instruments and synth presets. opts: kind ('piano' | 'epiano' |
  // 'organ' | 'synth'), title (the name on the panel), family (epiano: 'fm' · 'tine' · 'reed' · 'clav' ·
  // 'harpsichord' · 'mallet'; found from the title by keysFamily when absent), style (synth: pad, lead,
  // keys, bass, pluck, arp, sequence, percussion, sfx, drone, experiment, golem's Vital preset_style
  // names included; empty or unknown = a neutral synth), macros ([{name, value 0..1}], up to 4, synth),
  // drawbars ('888000000', organ), compact (a 300-wide tile for a wall of sounds), on, width
  function keysUnit(opts) {
    opts = opts || {};
    const kind = ['piano', 'epiano', 'organ', 'synth'].includes(opts.kind) ? opts.kind : 'synth';
    const on = opts.on !== false;
    const family = kind === 'epiano' ? (EP_FAMILIES.includes(opts.family) ? opts.family : keysFamily(opts.title)) : '';
    const title = opts.title || { piano: 'Grand', epiano: 'E-Piano', organ: 'Tonewheel', synth: 'Synth' }[kind];
    let r, W = 600;
    if (opts.compact) { r = keysCompact(kind, family, title, on, opts); W = r.W; }
    else if (kind === 'epiano') r = { fm: keysEpiano, tine: keysTine, reed: keysReed, clav: keysClav, harpsichord: keysHarpsichord, mallet: keysMallet }[family](W, title, on);
    else r = kind === 'piano' ? keysPiano(W, title, on) : kind === 'organ' ? keysOrgan(W, title, on, opts) : keysSynth(W, title, on, opts);
    const data = kind === 'synth' ? ` data-style="${esc(synthStyle(opts.style))}"` : kind === 'epiano' ? ` data-family="${family}"` : '';
    return `<svg class="gp-keys gp-keys-${kind}${opts.compact ? ' gp-keys-compact' : ''}${on ? ' is-on' : ''}" viewBox="-4 -4 ${W + 8} ${r.H + 10}" width="${opts.width || W + 8}" role="img" aria-label="${esc(kind)} — ${esc(title)}" data-kind="${kind}"${data}>
${r.svg}
</svg>`;
  }

  // ---------- kits: drum sets and pad kits ----------
  // A drum set is a photograph, one per kind of kit, generated for golem (Nano Banana, 2026-11-15) from the
  // drummer's throne, raised, looking across the kit: no maker's livery, no lettering. The files live in
  // `assets/kits/` (`<type>.webp` 1600 px, `<type>-sm.webp` 600 px for the compact tile); KIT_ASSETS is the
  // path prefix the page serves them from. `lit` draws a soft warm glow (no outline) over the pieces that play, from the
  // hotspots below (fractions of the image: centre x, centre y, half-width, half-height).
  const KIT_TYPES = ['rock', 'jazz', 'metal', 'vintage', 'electronic', 'hybrid'];
  const KIT_HUES = ['#b3121f', '#1f4fa3', '#2b2b2e', '#e8e2d0', '#2f7a3a', '#6e3aa0', '#c47a1c', '#7a4a26', '#0f6f7a', '#8a1e4a'];
  const KIT_PIECES = ['kick', 'snare', 'hats', 'ride', 'crash', 'toms'];
  const KIT_ASPECT = 1536 / 2752;
  let kitCount = 0;
  const LIT = '#ffd27a';
  const hashOf = s => { let h = 2166136261; for (const c of String(s || '')) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };
  // in pixels of a 700 × 390.7 view of each photograph
  const KIT_SPOTS = {
    rock: { hats: [[155, 150, 62, 15]], crash: [[225, 62, 58, 14]], ride: [[522, 85, 80, 25]], snare: [[265, 205, 57, 30]],
      toms: [[312, 118, 37, 20], [410, 118, 42, 22], [485, 210, 63, 30]], kick: [[357, 258, 62, 45]] },
    jazz: { hats: [[158, 152, 63, 15]], crash: [[226, 62, 58, 14]], ride: [[528, 75, 85, 30]], snare: [[263, 205, 58, 30]],
      toms: [[315, 115, 40, 20], [486, 210, 63, 30]], kick: [[357, 245, 62, 55]] },
    metal: { hats: [[182, 155, 48, 13]], crash: [[110, 98, 62, 16], [215, 57, 50, 13], [440, 52, 50, 13], [598, 57, 70, 25]], ride: [[506, 127, 65, 22]],
      snare: [[150, 293, 60, 30]], toms: [[255, 118, 33, 16], [320, 113, 33, 16], [392, 115, 35, 17], [493, 207, 47, 22], [583, 257, 62, 32]],
      kick: [[282, 225, 58, 45], [415, 213, 58, 45]] },
    vintage: { hats: [[158, 153, 63, 15]], crash: [[226, 63, 58, 14]], ride: [[530, 80, 85, 30]], snare: [[263, 205, 58, 30]],
      toms: [[315, 120, 40, 20], [486, 210, 63, 32]], kick: [[357, 240, 60, 50]] },
    electronic: { hats: [[143, 158, 48, 13]], crash: [[235, 65, 55, 15], [585, 135, 75, 22]], ride: [[478, 80, 62, 18]], snare: [[280, 245, 58, 28]],
      toms: [[313, 155, 42, 20], [405, 155, 42, 20], [497, 245, 58, 28]], kick: [[362, 255, 45, 45]] },
    hybrid: { hats: [[158, 155, 63, 15]], crash: [[226, 62, 58, 14]], ride: [[528, 83, 82, 28]], snare: [[263, 205, 57, 30], [140, 240, 40, 18]],
      toms: [[313, 125, 37, 20], [410, 125, 42, 22], [486, 210, 63, 30], [593, 190, 40, 16]], kick: [[357, 245, 60, 45]] },
  };
  const api_assets = { base: 'assets/kits/' };

  // a drum set. opts: type ('rock' · 'jazz' · 'metal' · 'vintage' · 'electronic' · 'hybrid'), title (in the
  // strip), lit (a piece or a list: kick, snare, hats, ride, crash, toms — glowing when on), on (off dims
  // the photograph), compact (a 300 × 186 tile for a wall, on the small image), src (an image URL that
  // replaces the type's photograph), width. `finish` is accepted for compatibility and ignored: each type
  // has its own photographed finish.
  function drumKit(opts) {
    opts = opts || {};
    const type = KIT_TYPES.includes(opts.type) ? opts.type : 'rock';
    const title = opts.title || { rock: 'Rock', jazz: 'Jazz', metal: 'Metal', vintage: 'Vintage', electronic: 'E-Kit', hybrid: 'Hybrid' }[type];
    const on = opts.on !== false, compact = !!opts.compact, id = 'gpk' + (++kitCount);
    const W = compact ? 300 : 640, IH = Math.round(W * KIT_ASPECT), strip = compact ? 19 : 30, H = IH + strip;
    const href = opts.src || `${api_assets.base}${type}${compact ? '-sm' : ''}.webp`;
    const lit = new Set([].concat(opts.lit || []).filter(p => KIT_PIECES.includes(p)));
    const k = W / 700, spots = KIT_SPOTS[type];
    const glow = on ? [...lit].flatMap(p => spots[p] || []).map(([x, y, rx, ry]) =>
      `<ellipse cx="${(x * k).toFixed(1)}" cy="${(y * k).toFixed(1)}" rx="${(rx * k).toFixed(1)}" ry="${(ry * k).toFixed(1)}" fill="#ffc66b" opacity=".38" filter="url(#${id}-glow)"/>`).join('') : '';
    const accent = mix(KIT_HUES[hashOf(type) % KIT_HUES.length], '#fff', .45);
    return `<svg class="gp-kit gp-kit-${type}${compact ? ' gp-kit-compact' : ''}${on ? ' is-on' : ''}" viewBox="0 0 ${W} ${H}" width="${opts.width || W}" role="img" aria-label="drum kit — ${esc(title)}" data-type="${type}">
<defs><clipPath id="${id}-frame"><rect x="0" y="0" width="${W}" height="${H}" rx="${compact ? 7 : 9}"/></clipPath>
<filter id="${id}-glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="${compact ? 4 : 9}"/></filter></defs>
<g clip-path="url(#${id}-frame)">
<rect x="0" y="0" width="${W}" height="${H}" fill="#121214"/>
<image href="${esc(href)}" x="0" y="0" width="${W}" height="${IH}" preserveAspectRatio="xMidYMid slice"${on ? '' : ' opacity=".45"'}/>
<g style="mix-blend-mode:screen">${glow}</g>
<rect x="0" y="${IH}" width="${W}" height="${strip}" fill="#0b0c0e"/>
<text x="${compact ? 9 : 16}" y="${IH + strip / 2 + (compact ? 4 : 5.5)}" font-family="${type === 'vintage' ? FONT.enamel : FONT.nam}" font-size="${compact ? 11 : 16}" font-weight="800" letter-spacing="${type === 'vintage' ? .4 : 1.4}" fill="#e2e6ea">${esc(type === 'vintage' ? String(title).slice(0, 26) : String(title).toUpperCase().slice(0, 26))}</text>
<text x="${W - (compact ? 9 : 16)}" y="${IH + strip / 2 + (compact ? 3 : 4.5)}" text-anchor="end" font-family="${FONT.gfx}" font-size="${compact ? 7.5 : 10}" font-weight="700" letter-spacing="1.6" fill="${accent}">${type.toUpperCase()}</text>
</g>
</svg>`;
  }

  // a 4 × 4 pad kit. opts: title, pads ([{label, hue}], up to 16, bottom-left = pad 1 as on hardware), lit
  // (a pad index 0–15, or a list), on, compact, width
  function padKit(opts) {
    opts = opts || {};
    const on = opts.on !== false, compact = !!opts.compact, title = opts.title || 'Pads';
    const W = compact ? 300 : 600, H = compact ? 186 : 340, id = 'gpp' + (++kitCount);
    const pads = (opts.pads || []).slice(0, 16), lit = new Set([].concat(opts.lit == null ? [] : opts.lit));
    const accent = KIT_HUES[hashOf(title) % KIT_HUES.length];
    const gx = compact ? 128 : 236, gy = compact ? 12 : 22, cell = compact ? 40 : 74, gap = compact ? 3.5 : 6;
    const grid = Array.from({ length: 16 }, (_, i) => {
      const row = 3 - Math.floor(i / 4), col = i % 4, p = pads[i] || {}, x = gx + col * (cell + gap), y = gy + row * (cell + gap);
      const hue = p.hue || accent, isLit = on && lit.has(i), glow = on ? (isLit ? .95 : .28) : .08;
      return `<g class="gp-pad"><rect x="${x}" y="${y}" width="${cell}" height="${cell}" rx="${cell * .1}" fill="#2a2c30"/>
  <rect x="${x}" y="${y}" width="${cell}" height="${cell}" rx="${cell * .1}" fill="${hue}" opacity="${glow}"${isLit ? ' filter="url(#gp-glow-soft)"' : ''}/>
  <rect x="${x + 2}" y="${y + 2}" width="${cell - 4}" height="${cell * .35}" rx="${cell * .08}" fill="#fff" opacity=".07"/>
  ${p.label && (!compact || cell > 30) ? `<text x="${x + cell / 2}" y="${y + cell - (compact ? 5 : 9)}" text-anchor="middle" font-family="${FONT.gfx}" font-size="${compact ? 6.4 : 10}" font-weight="700" fill="${isLit ? '#111' : '#d9dde2'}" opacity="${on ? .9 : .5}">${esc(String(p.label).toUpperCase().slice(0, compact ? 6 : 9))}</text>` : ''}</g>`;
    }).join('');
    const sw = compact ? 104 : 190, sx = compact ? 12 : 26;
    const knobs = [0, 1, 2, 3].map(i => { const cx = sx + sw * (i + .5) / 4, cy = compact ? 108 : 196, r = compact ? 8 : 14;
      return knobAlu(cx, cy, r, { min: 0, max: 1, default: [.6, .3, .75, .5][i] }, '', '#d9dde2'); }).join('');
    return `<svg class="gp-padkit${compact ? ' gp-kit-compact' : ''}${on ? ' is-on' : ''}" viewBox="-4 -4 ${W + 8} ${H + 8}" width="${opts.width || W + 8}" role="img" aria-label="pad kit — ${esc(title)}">
<g filter="url(#gp-shadow-small)"><rect x="0" y="0" width="${W}" height="${H}" rx="${compact ? 8 : 12}" fill="#1c1d20"/>
<rect x="0" y="0" width="${W}" height="${H}" rx="${compact ? 8 : 12}" fill="url(#gp-brush-lines)" opacity=".25"/></g>
<rect x="${sx}" y="${gy}" width="${sw}" height="${compact ? 52 : 96}" rx="3" fill="#07080a"/>
<rect x="${sx + 3}" y="${gy + 3}" width="${sw - 6}" height="${(compact ? 52 : 96) - 6}" rx="2" fill="${on ? mix(accent, '#05070a', .7) : '#0a0c0e'}"/>
<text x="${sx + 9}" y="${gy + (compact ? 22 : 36)}" font-family="${FONT.nam}" font-size="${compact ? 13 : 22}" font-weight="800" letter-spacing="1.2" fill="${on ? '#eef0f2' : '#4a4f56'}">${esc(String(title).toUpperCase().slice(0, compact ? 9 : 10))}</text>
<text x="${sx + 9}" y="${gy + (compact ? 38 : 64)}" font-family="${FONT.gfx}" font-size="${compact ? 7.5 : 11}" font-weight="700" letter-spacing="1.4" fill="${on ? mix(accent, '#fff', .4) : '#3a3f46'}">${pads.length || 16} PADS</text>
${knobs}
${grid}
</svg>`;
  }

  const { featureUnit, isFeature, FEATURE_TYPES } = (() => {
  // ---------- golem feature units (Console) ----------
  // golem's service blocks (rec, tuner, click, backing-track, looper, compo, drums, standard, arrangement,
  // sample) are golem's own devices, not effects: a graphite unit with a light bar, a screen that shows
  // what the feature is doing, and a ribbed rubber pad. The block's catalogue colour is its only colour.
  // Same 112 × 200 footprint as a pedal. The maintainer chose this look (A · Console) on 2026-11-15.
  const FEATURE_TYPES = ['rec', 'tuner', 'click', 'backing-track', 'looper', 'compo', 'drums', 'standard', 'arrangement', 'sample'];
  const FEATURE_NAME = { rec: 'Rec', tuner: 'Tuner', click: 'Click', 'backing-track': 'Backing', looper: 'Looper', compo: 'Riff',
    drums: 'Drums', standard: 'Standard', arrangement: 'Arrange', sample: 'Sample' };
  const FEATURE_COLOR = { rec: '#ff4136', tuner: '#3ddc2e', click: '#e0b23a', 'backing-track': '#1ab7b0', looper: '#2ecc71',
    compo: '#ff7a45', drums: '#7fd4a8', standard: '#9ad9be', arrangement: '#c98a2e', sample: '#5fce8f' };
  let featureCount = 0;
  // the catalogue colour, except a grey one (the tuner's would read as "off"): then this table's
  const featureColor = (type, block) => {
    const col = block && block.color;
    if (col) { const [r, g, b] = hex(col); if (Math.max(r, g, b) - Math.min(r, g, b) >= 34) return col; }
    return FEATURE_COLOR[type] || '#8a94a3';
  };
  const W = 112, H = 200;
  const f1 = v => (Math.round(v * 10) / 10).toString();
  const txt = (x, y, s, size, fill, o) => `<text x="${f1(x)}" y="${f1(y)}" font-family="${(o && o.font) || FONT.lcd}" font-size="${size}"` +
    ` fill="${fill}"${o && o.anchor ? ` text-anchor="${o.anchor}"` : ''}${o && o.weight ? ` font-weight="${o.weight}"` : ''}` +
    `${o && o.ls ? ` letter-spacing="${o.ls}"` : ''}${o && o.op ? ` fill-opacity="${o.op}"` : ''}>${esc(s)}</text>`;
  const isFeature = t => FEATURE_TYPES.includes(t);

  // ---------- the screen: what the feature is doing, in a few strokes ----------
  // (x, y, w, h): the screen's inner box; ink: lit colour; dim: unlit segments; on: the feature runs
  function featureScreen(type, x, y, w, h, ink, dim, on) {
    const cx = x + w / 2, s = [];
    const r = (rx, ry, rw, rh, fill, op) => `<rect x="${f1(rx)}" y="${f1(ry)}" width="${f1(rw)}" height="${f1(rh)}" rx=".6" fill="${fill}"${op ? ` fill-opacity="${op}"` : ''}/>`;
    const line = (d, col, sw, op) => `<path d="${d}" fill="none" stroke="${col}" stroke-width="${sw || 1}" stroke-linecap="round" stroke-linejoin="round"${op ? ` stroke-opacity="${op}"` : ''}/>`;
    const head = (label, right) => txt(x + 4, y + 9, label, 7, ink, { ls: .8 }) + (right ? txt(x + w - 4, y + 9, right, 7, ink, { anchor: 'end', op: .75 }) : '');
    switch (type) {
      case 'rec': {
        s.push(`<circle cx="${f1(x + 7)}" cy="${f1(y + 6.6)}" r="2.6" fill="${on ? '#ff3b2a' : dim}"/>`);
        s.push(txt(x + 12, y + 9, on ? 'REC' : 'STBY', 7, ink, { ls: .8 }), txt(x + w - 4, y + 9, 'ALL', 7, ink, { anchor: 'end', op: .75 }));
        s.push(txt(cx, y + h * .6, on ? '02:41' : '00:00', 15, ink, { anchor: 'middle' }));
        // input meters: the lanes being taken
        for (let i = 0; i < 4; i++) {
          const lv = on ? [.82, .55, .7, .3][i] : 0;
          s.push(r(x + 4, y + h - 13 + i * 2.6, w - 8, 1.6, dim), lv ? r(x + 4, y + h - 13 + i * 2.6, (w - 8) * lv, 1.6, ink) : '');
        }
        break;
      }
      case 'tuner': {
        const R = h * .62, oy = y + h - 3;
        for (let k = -5; k <= 5; k++) {
          const a = (k / 5) * .9, x1 = cx + Math.sin(a) * R, y1 = oy - Math.cos(a) * R, l = k % 5 === 0 ? 5 : 3;
          s.push(line(`M${f1(x1)} ${f1(y1)}L${f1(cx + Math.sin(a) * (R - l))} ${f1(oy - Math.cos(a) * (R - l))}`, k === 0 ? ink : dim, 1));
        }
        const a = on ? .12 : 0;
        s.push(line(`M${f1(cx)} ${f1(oy)}L${f1(cx + Math.sin(a) * (R - 2))} ${f1(oy - Math.cos(a) * (R - 2))}`, ink, 1.2));
        s.push(txt(x + 4, y + 9, on ? 'A' : '—', 9, ink, { weight: 700 }), txt(x + w - 4, y + 9, on ? '+3¢' : '440', 7, ink, { anchor: 'end', op: .75 }));
        break;
      }
      case 'click': {
        s.push(head('CLICK', '4/4'));
        s.push(txt(cx, y + h * .62, '120', 17, ink, { anchor: 'middle' }), txt(cx, y + h * .62 + 7, 'BPM', 5.5, ink, { anchor: 'middle', op: .7, ls: 1 }));
        for (let i = 0; i < 4; i++) {
          const lit = on && i === 0;
          s.push(`<circle cx="${f1(x + w * (i + .5) / 4)}" cy="${f1(y + h - 5)}" r="${i === 0 ? 2.4 : 1.9}" fill="${lit ? ink : dim}"/>`);
        }
        break;
      }
      case 'backing-track': {
        s.push(head(on ? '▶ PLAY' : '■ STOP', '3:12'));
        const n = 30, bw = (w - 8) / n, mid = y + h * .55;
        for (let i = 0; i < n; i++) {
          const a = (.25 + .75 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * .43))) * h * .26;
          s.push(r(x + 4 + i * bw, mid - a / 2, bw * .62, a, i < n * .38 && on ? ink : dim));
        }
        s.push(r(x + 4, y + h - 6, w - 8, 1.6, dim), r(x + 4, y + h - 6, (w - 8) * (on ? .38 : 0), 1.6, ink));
        break;
      }
      case 'looper': {
        s.push(head(on ? 'OVERDUB' : 'LOOP', '8 BARS'));
        const R = h * .3, cy = y + h * .6, frac = on ? .62 : 0;
        s.push(`<circle cx="${f1(cx)}" cy="${f1(cy)}" r="${f1(R)}" fill="none" stroke="${dim}" stroke-width="2.4"/>`);
        if (frac) {
          const a = frac * 2 * Math.PI, ex = cx + Math.sin(a) * R, ey = cy - Math.cos(a) * R;
          s.push(`<path d="M${f1(cx)} ${f1(cy - R)}A${f1(R)} ${f1(R)} 0 ${frac > .5 ? 1 : 0} 1 ${f1(ex)} ${f1(ey)}" fill="none" stroke="${ink}" stroke-width="2.4" stroke-linecap="round"/>`);
        }
        s.push(txt(cx, cy + 3, on ? '5.2' : '0', 9, ink, { anchor: 'middle' }));
        break;
      }
      case 'compo': {
        s.push(head(on ? 'TAKE ●' : 'RIFF', on ? '0:07' : 'ARMED'));
        const t0 = y + 14, gap = (h - 19) / 5;
        for (let i = 0; i < 6; i++) s.push(line(`M${f1(x + 4)} ${f1(t0 + i * gap)}H${f1(x + w - 4)}`, dim, .6));
        const notes = [[0, 5, '0'], [1, 5, '3'], [2, 4, '2'], [3, 4, '5'], [4, 3, '2'], [5, 5, '3'], [6, 4, '5']];
        notes.forEach(([k, str, fr]) => {
          const nx = x + 9 + k * (w - 18) / 6, ny = t0 + str * gap;
          s.push(r(nx - 2.4, ny - 3, 4.8, 6, mix(dim, '#000', .55)), txt(nx, ny + 2.3, fr, 6, on || k < 3 ? ink : dim, { anchor: 'middle' }));
        });
        break;
      }
      case 'drums': {
        s.push(head('PATTERN A', 'FILL'));
        const rows = [[1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1], [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1]];
        const gx = x + 4, gw = (w - 8) / 16, gy = y + 14, gh = (h - 18) / 3, step = on ? 5 : -1;
        rows.forEach((row, ri) => row.forEach((v, i) => {
          const fill = i === step ? ink : v ? mix(ink, dim, .35) : dim;
          s.push(r(gx + i * gw + .4, gy + ri * gh + .6, gw - .8, gh - 1.4, fill, v || i === step ? null : .55));
        }));
        break;
      }
      case 'standard': {
        s.push(head('Am · SWING', '♩=132'));
        const ch = ['Am7', 'D7', 'G△', 'C△', 'F♯ø', 'B7', 'Em', 'Em'], cw = (w - 8) / 4, rh = (h - 16) / 2;
        ch.forEach((c, i) => {
          const bx = x + 4 + (i % 4) * cw, by = y + 13 + Math.floor(i / 4) * rh, cur = on && i === 1;
          s.push(`<rect x="${f1(bx + .5)}" y="${f1(by + .5)}" width="${f1(cw - 1)}" height="${f1(rh - 1)}" rx=".8" fill="${cur ? mix(ink, '#000', .55) : 'none'}" stroke="${dim}" stroke-width=".6"/>`);
          s.push(txt(bx + cw / 2, by + rh / 2 + 2.6, c, 7, cur ? ink : mix(ink, dim, .3), { anchor: 'middle' }));
        });
        break;
      }
      case 'arrangement': {
        s.push(head(on ? 'CHORUS 2' : 'INTRO', 'BAR 3/8'));
        const parts = [['I', 1], ['V', 2], ['C', 2], ['V', 2], ['C', 2], ['B', 1], ['C', 2], ['O', 1]], tot = 13, sw = w - 8;
        let px = x + 4; const by = y + h * .42, bh = h * .32;
        parts.forEach(([p, len], i) => {
          const pw = sw * len / tot, cur = on ? i === 4 : i === 0;
          s.push(`<rect x="${f1(px + .5)}" y="${f1(by)}" width="${f1(pw - 1)}" height="${f1(bh)}" rx=".8" fill="${cur ? ink : p === 'C' ? mix(dim, ink, .25) : dim}"/>`);
          s.push(txt(px + pw / 2, by + bh / 2 + 2.4, p, 6.5, cur ? '#000' : mix(ink, dim, .25), { anchor: 'middle' }));
          px += pw;
        });
        s.push(r(x + 4, y + h - 6, sw, 1.6, dim), r(x + 4, y + h - 6, sw * (on ? .55 : .03), 1.6, ink));
        break;
      }
      case 'sample': {
        s.push(head('SAMPLE', 'PAD 2'));
        const pw = (w - 8 - 9) / 4, py = y + 13, ph = h - 17;
        for (let i = 0; i < 4; i++) {
          const px = x + 4 + i * (pw + 3), hit = on && i === 1;
          s.push(`<rect x="${f1(px)}" y="${f1(py)}" width="${f1(pw)}" height="${f1(ph)}" rx="1.4" fill="${hit ? ink : 'none'}" stroke="${hit ? ink : dim}" stroke-width=".8"/>`);
          s.push(txt(px + pw / 2, py + ph / 2 + 2.5, String(i + 1), 7, hit ? '#000' : mix(ink, dim, .3), { anchor: 'middle' }));
        }
        break;
      }
      default: s.push(head(String(type).toUpperCase()));
    }
    return s.join('');
  }

  // Realistic pass: grained polymer with a bevelled edge, four torx screws, a USB-C port on the top edge,
  // a diffused light bar that spills onto the body, a recessed screen behind glass (inner shadow, glow
  // on the lit segments, scan lines, a diagonal reflection), and a ribbed rubber pad standing in a well
  // ringed by a light pipe.
  function featureUnit(item, opts) {
    const it = typeof item === 'string' ? { type: item } : (item || {});
    opts = Object.assign({}, opts || {}, it);
    const type = it.type, block = blockByType(type) || {};
    const on = opts.on !== false, c = featureColor(type, block), id = 'gpf' + (++featureCount);
    const name = String(opts.title || FEATURE_NAME[type] || block.short || block.name || type);
    const body = '#25282d', ink = mix(c, '#fff', .35), dim = mix(c, '#0b0d10', .82);
    const sx = 11, sy = 23, sw = W - 22, sh = 62;
    const well = { x: 13, y: 118, w: W - 26, h: 66 }, pad = { x: 18, y: 122, w: W - 36, h: 56 };
    const ribs = Array.from({ length: 6 }, (_, i) => pad.y + 13 + i * 6.4);
    const screw = (x, y) => `<g><circle cx="${x}" cy="${y}" r="2.6" fill="#101214"/><circle cx="${x}" cy="${y}" r="2.1" fill="url(#${id}-scr)"/>` +
      `<path d="M${x} ${y - 1.1}V${y + 1.1}M${x - .95} ${y - .55}L${x + .95} ${y + .55}M${x - .95} ${y + .55}L${x + .95} ${y - .55}" stroke="#1d2024" stroke-width=".55" stroke-linecap="round"/></g>`;
    return `<svg class="gp-pedal gp-feature gp-feature-console${on ? ' is-on' : ''}" viewBox="-6 -8 ${W + 12} ${H + 20}" width="${opts.width || W + 12}" role="img" aria-label="${esc(block.name || name)}" data-type="${esc(type)}">
<defs>
<linearGradient id="${id}-b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mix(body, '#fff', .09)}"/><stop offset=".5" stop-color="${body}"/><stop offset="1" stop-color="${mix(body, '#000', .3)}"/></linearGradient>
<linearGradient id="${id}-bev" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".28"/><stop offset=".06" stop-color="#fff" stop-opacity=".06"/><stop offset=".94" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></linearGradient>
<filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="1.15" numOctaves="2" seed="7" result="n"/>
  <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .09 0"/><feComposite in2="SourceGraphic" operator="in"/></filter>
<radialGradient id="${id}-scr" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#9aa1a8"/><stop offset=".6" stop-color="#555b62"/><stop offset="1" stop-color="#2b2f34"/></radialGradient>
<linearGradient id="${id}-bar" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${c}" stop-opacity=".35"/><stop offset=".15" stop-color="${mix(c, '#fff', .25)}"/><stop offset=".85" stop-color="${mix(c, '#fff', .25)}"/><stop offset="1" stop-color="${c}" stop-opacity=".35"/></linearGradient>
<radialGradient id="${id}-spill" cx=".5" cy="0" r=".9"><stop offset="0" stop-color="${c}" stop-opacity=".22"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></radialGradient>
<linearGradient id="${id}-in" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".85"/><stop offset=".22" stop-color="#000" stop-opacity="0"/></linearGradient>
<radialGradient id="${id}-lcd" cx=".5" cy=".45" r=".75"><stop offset="0" stop-color="${on ? mix(c, '#0b0f12', .93) : '#0b0d0f'}"/><stop offset="1" stop-color="#050607"/></radialGradient>
<pattern id="${id}-scan" width="2" height="1.4" patternUnits="userSpaceOnUse"><rect width="2" height=".55" fill="#000" opacity=".28"/></pattern>
<linearGradient id="${id}-refl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".11"/><stop offset=".45" stop-color="#fff" stop-opacity=".025"/><stop offset=".46" stop-color="#fff" stop-opacity="0"/></linearGradient>
<filter id="${id}-glow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="${on ? .9 : 0}" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<filter id="${id}-bloom" x="-40%" y="-200%" width="180%" height="500%"><feGaussianBlur stdDeviation="3"/></filter>
<linearGradient id="${id}-pad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#43474e"/><stop offset=".35" stop-color="#2c2f34"/><stop offset="1" stop-color="#17191c"/></linearGradient>
<radialGradient id="${id}-sheen" cx=".35" cy=".1" r=".7"><stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
<linearGradient id="${id}-well" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#050607"/><stop offset="1" stop-color="#15171a"/></linearGradient>
<clipPath id="${id}-sc"><rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" rx="3"/></clipPath>
</defs>
<rect x="${W / 2 - 9}" y="-5.5" width="18" height="7" rx="2" fill="#0d0e10"/>
<rect x="${W / 2 - 6.5}" y="-4" width="13" height="4" rx="2" fill="#2a2d31"/><rect x="${W / 2 - 4}" y="-2.6" width="8" height="1.3" rx=".6" fill="#8b9097"/>
<g filter="url(#gp-shadow)">
  <rect x="0" y="5" width="${W}" height="${H}" rx="14" fill="#0e0f11"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="url(#${id}-b)"/>
</g>
<rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="#fff" filter="url(#${id}-grain)"/>
<rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="url(#gp-side)"/>
<rect x=".6" y=".6" width="${W - 1.2}" height="${H - 1.2}" rx="13.4" fill="none" stroke="url(#${id}-bev)" stroke-width="1.2"/>
${on ? `<rect x="6" y="9" width="${W - 12}" height="34" fill="url(#${id}-spill)"/>` : ''}
<rect x="9" y="6" width="${W - 18}" height="6" rx="3" fill="#0a0b0d"/>
${on ? `<rect x="12" y="7.2" width="${W - 24}" height="3.6" rx="1.8" fill="${c}" opacity=".9" filter="url(#${id}-bloom)"/>` : ''}
<rect x="10.5" y="7.2" width="${W - 21}" height="3.6" rx="1.8" fill="${on ? `url(#${id}-bar)` : mix(c, '#101214', .78)}"/>
<rect x="10.5" y="7.2" width="${W - 21}" height="1.3" rx=".65" fill="#fff" opacity="${on ? .35 : .06}"/>
<rect x="${sx - 3.5}" y="${sy - 3.5}" width="${sw + 7}" height="${sh + 7}" rx="6" fill="#0b0c0e"/>
<rect x="${sx - 3.5}" y="${sy - 3.5}" width="${sw + 7}" height="${sh + 7}" rx="6" fill="none" stroke="#000" stroke-opacity=".6" stroke-width=".8"/>
<path d="M${sx - 3} ${sy + sh + 3.2}H${sx + sw + 3}" stroke="#fff" stroke-opacity=".09" stroke-width=".8"/>
<rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" rx="3" fill="url(#${id}-lcd)"/>
<g clip-path="url(#${id}-sc)">
  <g opacity="${on ? 1 : .5}" filter="url(#${id}-glow)">${featureScreen(type, sx, sy, sw, sh, ink, dim, on)}</g>
  <rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" fill="url(#${id}-scan)"/>
  <rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" fill="url(#${id}-in)"/>
  <rect x="${sx}" y="${sy}" width="${sw}" height="${sh}" fill="url(#${id}-refl)"/>
</g>
${glyphAt(type, 20, 101, 13, on ? ink : mix(c, '#000', .35), 1.9)}
${txt(31, 105.5, name.toUpperCase().slice(0, 10), 11, '#dfe2e5', { font: FONT.gfx, weight: 700, ls: 1.4 })}
<rect x="${well.x}" y="${well.y}" width="${well.w}" height="${well.h}" rx="15" fill="url(#${id}-well)"/>
<rect x="${well.x}" y="${well.y}" width="${well.w}" height="${well.h}" rx="15" fill="none" stroke="#fff" stroke-opacity=".07" stroke-width=".8"/>
${on ? `<rect x="${well.x + 1.5}" y="${well.y + 1.5}" width="${well.w - 3}" height="${well.h - 3}" rx="13.5" fill="none" stroke="${c}" stroke-width="3.2" opacity=".55" filter="url(#${id}-bloom)"/>` : ''}
<rect x="${well.x + 1.5}" y="${well.y + 1.5}" width="${well.w - 3}" height="${well.h - 3}" rx="13.5" fill="none" stroke="${on ? mix(c, '#fff', .3) : '#24272b'}" stroke-width="1.3"/>
<rect x="${pad.x}" y="${pad.y + 3.5}" width="${pad.w}" height="${pad.h}" rx="11" fill="#08090a"/>
<rect x="${pad.x}" y="${pad.y}" width="${pad.w}" height="${pad.h}" rx="11" fill="url(#${id}-pad)"/>
<rect x="${pad.x}" y="${pad.y}" width="${pad.w}" height="${pad.h}" rx="11" fill="#fff" filter="url(#${id}-grain)" opacity=".7"/>
${ribs.map(y => `<path d="M${pad.x + 10} ${f1(y)}H${pad.x + pad.w - 10}" stroke="#0c0d0f" stroke-opacity=".8" stroke-width="1.7" stroke-linecap="round"/>` +
      `<path d="M${pad.x + 10} ${f1(y + 1.5)}H${pad.x + pad.w - 10}" stroke="#fff" stroke-opacity=".09" stroke-width=".8" stroke-linecap="round"/>`).join('')}
<rect x="${pad.x}" y="${pad.y}" width="${pad.w}" height="${pad.h}" rx="11" fill="url(#${id}-sheen)"/>
<rect x="${pad.x + .5}" y="${pad.y + .5}" width="${pad.w - 1}" height="${pad.h - 1}" rx="10.5" fill="none" stroke="#fff" stroke-opacity=".12" stroke-width=".7"/>
${screw(6.5, 6.5)}${screw(W - 6.5, 6.5)}${screw(6.5, H - 6.5)}${screw(W - 6.5, H - 6.5)}
${txt(W / 2, H - 4.4, 'golem', 7, '#fff', { font: FONT.gfx, anchor: 'middle', weight: 700, ls: 2.2, op: .07 })}
${txt(W / 2, H - 5, 'golem', 7, '#0b0c0e', { font: FONT.gfx, anchor: 'middle', weight: 700, ls: 2.2, op: .75 })}
</svg>`;
  }

  return { featureUnit, isFeature, FEATURE_TYPES };
  })();

  const { hardwareUnit, HARDWARE_KINDS } = (() => {
  // ---------- golem hardware units ----------
  // The MIDI hardware golem drives (its pedal registry: whammy-dt, midi-pedal), drawn as realistic vector
  // renders, one per kind of unit, at the real units' proportions. Generic forms only: no maker's livery,
  // colours, logo or lettering. `on` lights the LEDs and the screens. The maintainer validated them on 2026-11-15.
  const f1 = v => (Math.round(v * 10) / 10).toString();
  let count = 0;

  // ---------- parts ----------
  function hwDefs(id, body) {
    return `<defs>
<linearGradient id="${id}-b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mix(body, '#fff', .14)}"/><stop offset=".45" stop-color="${body}"/><stop offset="1" stop-color="${mix(body, '#000', .32)}"/></linearGradient>
<linearGradient id="${id}-bev" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset=".05" stop-color="#fff" stop-opacity=".05"/><stop offset=".95" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".5"/></linearGradient>
<filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="3" result="n"/>
  <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .1 0"/><feComposite in2="SourceGraphic" operator="in"/></filter>
<filter id="${id}-brush" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9 .012" numOctaves="2" seed="5" result="n"/>
  <feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .16 0"/><feComposite in2="SourceGraphic" operator="in"/></filter>
<radialGradient id="${id}-knob" cx=".4" cy=".3" r=".8"><stop offset="0" stop-color="#4a4d52"/><stop offset=".55" stop-color="#1c1e21"/><stop offset="1" stop-color="#0a0b0c"/></radialGradient>
<linearGradient id="${id}-skirt" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2c2f33"/><stop offset="1" stop-color="#08090a"/></linearGradient>
<radialGradient id="${id}-cap" cx=".38" cy=".32" r=".75"><stop offset="0" stop-color="#ffffff"/><stop offset=".3" stop-color="#d8dde2"/><stop offset=".7" stop-color="#7b838b"/><stop offset="1" stop-color="#b9bfc5"/></radialGradient>
<linearGradient id="${id}-nut" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e6e9ec"/><stop offset=".5" stop-color="#8e959c"/><stop offset="1" stop-color="#4a4f55"/></linearGradient>
<linearGradient id="${id}-rub" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3c3f44"/><stop offset=".4" stop-color="#25272b"/><stop offset="1" stop-color="#121315"/></linearGradient>
<linearGradient id="${id}-steel" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#6d737a"/><stop offset=".25" stop-color="#d5d9dd"/><stop offset=".5" stop-color="#9aa0a7"/><stop offset=".8" stop-color="#e2e5e8"/><stop offset="1" stop-color="#7a8087"/></linearGradient>
<linearGradient id="${id}-in" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".8"/><stop offset=".25" stop-color="#000" stop-opacity="0"/></linearGradient>
<linearGradient id="${id}-refl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".14"/><stop offset=".45" stop-color="#fff" stop-opacity=".03"/><stop offset=".46" stop-color="#fff" stop-opacity="0"/></linearGradient>
<filter id="${id}-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.6"/></filter>
<filter id="${id}-soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation=".7" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>`;
  }
  // a box seen from above: drop shadow, painted body, grain (or brushed), side shading, bevelled edge
  function enclosure(id, x, y, w, h, r, finish) {
    return `<rect x="${x}" y="${y + 4}" width="${w}" height="${h}" rx="${r}" fill="#000" opacity=".55" filter="url(#${id}-glow)"/>
<rect x="${x}" y="${y + 2.5}" width="${w}" height="${h}" rx="${r}" fill="#000" opacity=".6"/>
<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="url(#${id}-b)"/>
<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="#fff" filter="url(#${id}-${finish === 'brushed' ? 'brush' : 'grain'})"/>
<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="url(#gp-side)"/>
<rect x="${x + .6}" y="${y + .6}" width="${w - 1.2}" height="${h - 1.2}" rx="${Math.max(0, r - .6)}" fill="none" stroke="url(#${id}-bev)" stroke-width="1.2"/>`;
  }
  function knob(id, cx, cy, r, pos, pointer) {
    const a = (-135 + 270 * (pos == null ? .5 : pos)) * Math.PI / 180;
    const px = cx + Math.sin(a) * r * .78, py = cy - Math.cos(a) * r * .78;
    return `<g><circle cx="${cx}" cy="${f1(cy + r * .18)}" r="${f1(r * 1.08)}" fill="#000" opacity=".5" filter="url(#${id}-glow)"/>
<circle cx="${cx}" cy="${cy}" r="${f1(r * 1.06)}" fill="url(#${id}-skirt)"/>
<circle cx="${cx}" cy="${cy}" r="${f1(r * .86)}" fill="url(#${id}-knob)"/>
<circle cx="${cx}" cy="${cy}" r="${f1(r * .86)}" fill="none" stroke="#fff" stroke-opacity=".08" stroke-width=".5"/>
<path d="M${f1(cx + Math.sin(a) * r * .25)} ${f1(cy - Math.cos(a) * r * .25)}L${f1(px)} ${f1(py)}" stroke="${pointer || '#e9ecef'}" stroke-width="${f1(Math.max(.7, r * .14))}" stroke-linecap="round"/></g>`;
  }
  // chicken-head selector: a tapered pointer over a round base
  function chicken(id, cx, cy, r, deg) {
    return `<g transform="rotate(${deg || 0} ${cx} ${cy})"><circle cx="${cx}" cy="${f1(cy + r * .2)}" r="${f1(r)}" fill="#000" opacity=".45" filter="url(#${id}-glow)"/>
<circle cx="${cx}" cy="${cy}" r="${f1(r * .78)}" fill="url(#${id}-knob)"/>
<path d="M${f1(cx - r * .42)} ${f1(cy + r * .3)}L${f1(cx - r * .14)} ${f1(cy - r * 1.2)}Q${cx} ${f1(cy - r * 1.35)} ${f1(cx + r * .14)} ${f1(cy - r * 1.2)}L${f1(cx + r * .42)} ${f1(cy + r * .3)}Z" fill="url(#${id}-knob)" stroke="#000" stroke-opacity=".4" stroke-width=".4"/>
<path d="M${cx} ${f1(cy - r * .2)}L${cx} ${f1(cy - r * 1.1)}" stroke="#e9ecef" stroke-width="${f1(r * .12)}" stroke-linecap="round"/></g>`;
  }
  function hexPts(cx, cy, r) { return [0, 1, 2, 3, 4, 5].map(i => { const a = Math.PI / 6 + i * Math.PI / 3; return `${f1(cx + r * Math.cos(a))},${f1(cy + r * Math.sin(a))}`; }).join(' '); }
  // a chrome stomp switch: shadow, hex nut, threaded collar, domed cap with a specular highlight
  function foot(id, cx, cy, r) {
    return `<g><circle cx="${cx}" cy="${f1(cy + 2)}" r="${f1(r * 1.5)}" fill="#000" opacity=".5" filter="url(#${id}-glow)"/>
<polygon points="${hexPts(cx, cy, r * 1.45)}" fill="url(#${id}-nut)" stroke="#000" stroke-opacity=".45" stroke-width=".5"/>
<circle cx="${cx}" cy="${cy}" r="${f1(r * 1.12)}" fill="#3a3f45"/>
${[0, 1, 2].map(i => `<circle cx="${cx}" cy="${cy}" r="${f1(r * (1.08 - i * .06))}" fill="none" stroke="#fff" stroke-opacity=".12" stroke-width=".35"/>`).join('')}
<circle cx="${cx}" cy="${f1(cy + .6)}" r="${f1(r * .92)}" fill="#000" opacity=".5"/>
<circle cx="${cx}" cy="${cy}" r="${f1(r * .9)}" fill="url(#${id}-cap)"/>
<ellipse cx="${f1(cx - r * .28)}" cy="${f1(cy - r * .32)}" rx="${f1(r * .32)}" ry="${f1(r * .22)}" fill="#fff" opacity=".85" filter="url(#${id}-soft)"/></g>`;
  }
  function led(id, cx, cy, col, on, r) {
    r = r || 1.8;
    return `<g>${on ? `<circle cx="${cx}" cy="${cy}" r="${f1(r * 3)}" fill="${col}" opacity=".55" filter="url(#${id}-glow)"/>` : ''}
<circle cx="${cx}" cy="${cy}" r="${f1(r + .7)}" fill="#0b0c0d"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="${on ? mix(col, '#fff', .35) : mix(col, '#000', .72)}"/>
<circle cx="${f1(cx - r * .35)}" cy="${f1(cy - r * .35)}" r="${f1(r * .35)}" fill="#fff" opacity="${on ? .8 : .35}"/></g>`;
  }
  function toggle(id, cx, cy, up) {
    return `<g><circle cx="${cx}" cy="${cy}" r="3.1" fill="url(#${id}-nut)"/><circle cx="${cx}" cy="${cy}" r="1.9" fill="#2a2d31"/>
<path d="M${cx} ${cy}L${cx} ${cy + (up ? -7 : 7)}" stroke="url(#${id}-steel)" stroke-width="2.2" stroke-linecap="round"/><circle cx="${cx}" cy="${cy + (up ? -7 : 7)}" r="1.5" fill="#e5e8eb"/></g>`;
  }
  // top-edge connectors: a 1/4" jack nut, a 5-pin DIN, a 3.5 mm TRS, a USB-C
  function jackTop(cx, y) { return `<rect x="${f1(cx - 5)}" y="${f1(y - 5)}" width="10" height="6" rx="1" fill="#15171a"/><rect x="${f1(cx - 3.5)}" y="${f1(y - 7)}" width="7" height="3" rx="1" fill="#9aa1a8"/>`; }
  function dinTop(cx, y) { return `<rect x="${f1(cx - 8)}" y="${f1(y - 6)}" width="16" height="7" rx="1.5" fill="#15171a"/><rect x="${f1(cx - 6)}" y="${f1(y - 8)}" width="12" height="3.2" rx="1.4" fill="#7d848b"/>`; }
  function trsTop(cx, y) { return `<rect x="${f1(cx - 3.5)}" y="${f1(y - 5)}" width="7" height="6" rx="1" fill="#15171a"/><rect x="${f1(cx - 2.2)}" y="${f1(y - 6.5)}" width="4.4" height="2.4" rx=".8" fill="#9aa1a8"/>`; }
  function usbTop(cx, y) { return `<rect x="${f1(cx - 5)}" y="${f1(y - 4.5)}" width="10" height="5" rx="1.5" fill="#15171a"/><rect x="${f1(cx - 3)}" y="${f1(y - 3.2)}" width="6" height="1.6" rx=".8" fill="#6f767d"/>`; }
  function screw(cx, cy, r) {
    r = r || 2.2;
    return `<g><circle cx="${cx}" cy="${cy}" r="${f1(r + .5)}" fill="#0d0e10"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-chrome)"/><path d="M${f1(cx - r * .6)} ${cy}H${f1(cx + r * .6)}M${cx} ${f1(cy - r * .6)}V${f1(cy + r * .6)}" stroke="#2a2d31" stroke-width=".55"/></g>`;
  }
  // a screen under glass with abstract content ('bars', 'wave', 'blocks', 'segments', 'vfd')
  function screen(id, x, y, w, h, kind, col, on) {
    const ink = on ? col : mix(col, '#000', .78), s = [];
    const n = Math.max(6, Math.round(w / 6));
    if (kind === 'bars') for (let i = 0; i < n; i++) { const bh = (h - 8) * (.25 + .7 * Math.abs(Math.sin(i * 1.3 + .4))); s.push(`<rect x="${f1(x + 4 + i * (w - 8) / n)}" y="${f1(y + h - 4 - bh)}" width="${f1((w - 8) / n * .6)}" height="${f1(bh)}" fill="${ink}" opacity=".9"/>`); }
    if (kind === 'wave') { let d = ''; for (let i = 0; i <= 60; i++) { const t = i / 60; d += `${i ? 'L' : 'M'}${f1(x + 4 + t * (w - 8))} ${f1(y + h / 2 + Math.sin(t * Math.PI * 4) * Math.sin(t * Math.PI) * (h * .32))}`; } s.push(`<path d="${d}" fill="none" stroke="${ink}" stroke-width="1.2"/>`, `<path d="M${x + 4} ${y + h / 2}H${x + w - 4}" stroke="${ink}" stroke-opacity=".25" stroke-width=".5"/>`); }
    if (kind === 'blocks') { const cols = ['#3dd6ff', '#ff7a45', '#7bd36b', '#c77dff', '#ffd23f']; const bw = (w - 16) / 5; cols.forEach((c, i) => s.push(`<rect x="${f1(x + 4 + i * (bw + 2))}" y="${f1(y + h * .38)}" width="${f1(bw)}" height="${f1(h * .3)}" rx="1.5" fill="${on ? c : mix(c, '#000', .75)}"/>`)); s.push(`<path d="M${x + 4} ${f1(y + h * .53)}H${x + w - 4}" stroke="${ink}" stroke-opacity=".4" stroke-width=".7"/>`); }
    if (kind === 'segments') { const sw = (w - 10) / 2; [0, 1].forEach(i => { const sx = x + 5 + i * sw, a = sw * .62, b = h - 10; s.push(`<path d="M${f1(sx + 2)} ${y + 5}h${f1(a)}M${f1(sx + 2)} ${f1(y + 5 + b / 2)}h${f1(a)}M${f1(sx + 2)} ${f1(y + 5 + b)}h${f1(a)}M${f1(sx + 1)} ${y + 6}v${f1(b / 2 - 2)}M${f1(sx + 3 + a)} ${f1(y + 6 + b / 2)}v${f1(b / 2 - 2)}" stroke="${ink}" stroke-width="2" stroke-linecap="round"/>`); }); }
    if (kind === 'vfd') for (let i = 0; i < 3; i++) s.push(`<rect x="${f1(x + 4)}" y="${f1(y + 4 + i * (h - 8) / 3)}" width="${f1((w - 8) * [.85, .55, .7][i])}" height="${f1((h - 8) / 3 - 2.5)}" rx=".6" fill="${ink}" opacity="${[.9, .6, .75][i]}"/>`);
    return `<rect x="${f1(x - 2.5)}" y="${f1(y - 2.5)}" width="${f1(w + 5)}" height="${f1(h + 5)}" rx="3" fill="#060708"/>
<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="1.6" fill="${on ? mix(col, '#050607', .9) : '#07080a'}"/>
<g filter="url(#${id}-soft)">${s.join('')}</g>
<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="1.6" fill="url(#${id}-in)"/><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="1.6" fill="url(#${id}-refl)"/>`;
  }
  // an expression treadle seen from above: steel side rails, ribbed rubber top, hinge shadow
  function treadle(id, x, y, w, h, plate) {
    const ribs = []; for (let yy = y + 10; yy < y + h - 8; yy += 6) ribs.push(`<path d="M${x + 7} ${yy}H${x + w - 7}" stroke="#08090a" stroke-opacity=".85" stroke-width="2" stroke-linecap="round"/><path d="M${x + 7} ${yy + 1.8}H${x + w - 7}" stroke="#fff" stroke-opacity=".08" stroke-width=".8" stroke-linecap="round"/>`);
    return `<rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${h + 6}" rx="5" fill="#000" opacity=".55" filter="url(#${id}-glow)"/>
<rect x="${x - 2}" y="${y - 2}" width="${w + 4}" height="${h + 4}" rx="4" fill="url(#${id}-steel)"/>
<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="url(#${id}-rub)"/>
<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="#fff" filter="url(#${id}-grain)" opacity=".6"/>
${ribs.join('')}${plate ? `<rect x="${f1(x + w * .26 - 1)}" y="${f1(y + h * .22 - 1)}" width="${f1(w * .48 + 2)}" height="${f1(h * .5 + 2)}" rx="4" fill="#000" opacity=".55"/><rect x="${f1(x + w * .26)}" y="${f1(y + h * .22)}" width="${f1(w * .48)}" height="${f1(h * .5)}" rx="3.5" fill="url(#${id}-steel)" opacity=".85"/><rect x="${f1(x + w * .26)}" y="${f1(y + h * .22)}" width="${f1(w * .48)}" height="${f1(h * .5)}" rx="3.5" fill="#fff" filter="url(#${id}-brush)"/><rect x="${f1(x + w * .26)}" y="${f1(y + h * .22)}" width="${f1(w * .48)}" height="${f1(h * .5)}" rx="3.5" fill="url(#${id}-in)" opacity=".6"/>` : ''}
<rect x="${x}" y="${y + h - 6}" width="${w}" height="6" rx="2" fill="#000" opacity=".35"/>`;
  }
  const svg = (cls, vb, w, body, label) => `<svg class="gp-hw gp-hw-${cls}" viewBox="${vb}" width="${w}" role="img" aria-label="${esc(label)}" data-kind="${cls}">${body}</svg>`;

  // ---------- the kinds ----------
  const KINDS = {
    'pitch-treadle'(o) {
      const id = 'ghw' + (++count), W = 230, H = 214, body = '#3c4a5c', on = o.on !== false;
      const leds = []; for (let i = 0; i < 9; i++) leds.push(led(id, 22, 30 + i * 11, '#ff3b2a', on && i === 3, 1.5), led(id, 50, 30 + i * 11, '#ff3b2a', false, 1.5));
      const diag = []; for (let i = 0; i < 8; i++) diag.push(led(id, 168 + i * 6, 74 - i * 5.5, '#ff3b2a', on && i === 2, 1.4), led(id, 168 + i * 6, 96 + i * 5.5, '#ff3b2a', false, 1.4));
      return svg('pitch-treadle', `-8 -12 ${W + 16} ${H + 26}`, o.width || W + 16, hwDefs(id, body) +
        jackTop(30, 0) + jackTop(200, 0) + dinTop(140, 0) + `<rect x="${W / 2 - 50}" y="-4" width="12" height="5" rx="1" fill="#15171a"/>` +
        enclosure(id, 0, 0, W, H, 7) +
        `<rect x="6" y="18" width="62" height="112" rx="3" fill="#000" opacity=".22"/><rect x="${W - 68}" y="18" width="62" height="112" rx="3" fill="#000" opacity=".22"/>` +
        leds.join('') + chicken(id, 36, 84, 8, 30) + diag.join('') + chicken(id, 198, 84, 8, -60) +
        treadle(id, 76, 12, 78, 186, true) +
        foot(id, 26, 186, 8) + foot(id, W - 26, 186, 8) + foot(id, W - 26, 150, 6.5) + led(id, 26, 160, '#ff3b2a', on) +
        screw(6, 6) + screw(W - 6, 6) + screw(6, H - 6) + screw(W - 6, H - 6), o.label || 'pitch treadle');
    },
    'big-box'(o) {
      const id = 'ghw' + (++count), W = 260, H = 150, body = '#34373c', on = o.on !== false;
      const ks = [0, 1, 2, 3, 4, 5].map(i => knob(id, 40 + i * 30, 70, 9, [.3, .55, .7, .45, .2, .8][i])).join('') + [0, 1, 2].map(i => knob(id, 70 + i * 30, 98, 7, [.6, .35, .5][i])).join('');
      return svg('big-box', `-8 -12 ${W + 16} ${H + 26}`, o.width || W + 16, hwDefs(id, body) +
        jackTop(30, 0) + jackTop(50, 0) + dinTop(130, 0) + jackTop(210, 0) + jackTop(230, 0) +
        `<rect x="-2" y="2" width="${W + 4}" height="${H - 4}" rx="9" fill="url(#${id}-steel)"/>` + enclosure(id, 0, 0, W, H, 8, 'brushed') +
        `<rect x="5" y="5" width="${W - 10}" height="${H - 10}" rx="5" fill="#1d1f22" opacity=".75"/>` +
        screen(id, 92, 18, 76, 28, 'bars', '#9ad7ff', on) + ks +
        `<circle cx="214" cy="98" r="12" fill="#000" opacity=".45" filter="url(#${id}-glow)"/><circle cx="214" cy="98" r="11" fill="url(#${id}-steel)"/>${[...Array(24)].map((_, i) => { const a = i * Math.PI / 12; return `<path d="M${f1(214 + Math.cos(a) * 9.2)} ${f1(98 + Math.sin(a) * 9.2)}L${f1(214 + Math.cos(a) * 11)} ${f1(98 + Math.sin(a) * 11)}" stroke="#555b62" stroke-width=".7"/>`; }).join('')}<circle cx="214" cy="98" r="7.5" fill="url(#${id}-knob)"/>` +
        `<rect x="186" y="62" width="9" height="5" rx="1.2" fill="#121315"/><rect x="200" y="62" width="9" height="5" rx="1.2" fill="#121315"/>` +
        [0, 1, 2].map(i => led(id, 50 + i * 80, 112, i === 0 ? '#ffb02e' : '#4cff7a', on && i < 2) + foot(id, 50 + i * 80, 132, 8)).join(''),
      o.label || 'big box');
    },
    'mid-box'(o) {
      const id = 'ghw' + (++count), W = 180, H = 132, body = '#4a4d52', on = o.on !== false;
      return svg('mid-box', `-8 -12 ${W + 16} ${H + 26}`, o.width || W + 16, hwDefs(id, body) +
        jackTop(24, 0) + usbTop(70, 0) + trsTop(100, 0) + jackTop(156, 0) +
        enclosure(id, 0, 0, W, H, 6) + `<rect x="0" y="${H * .62}" width="${W}" height="${H * .38}" rx="6" fill="#000" opacity=".18"/>` +
        screen(id, 14, 16, 64, 30, 'wave', '#7fe0ff', on) + knob(id, 120, 31, 14, .62) +
        [0, 1, 2, 3].map(i => knob(id, 26 + i * 42, 66, 7.5, [.4, .65, .3, .55][i])).join('') +
        led(id, 50, 92, '#ff4d3d', on) + led(id, 130, 92, '#ff4d3d', false) + foot(id, 50, 112, 8) + foot(id, 130, 112, 8),
      o.label || 'mid box');
    },
    compact(o) {
      const id = 'ghw' + (++count), W = 100, H = 140, body = '#e4dfd2', on = o.on !== false;
      return svg('compact', `-8 -12 ${W + 16} ${H + 26}`, o.width || W + 16, hwDefs(id, body) +
        jackTop(18, 0) + trsTop(50, 0) + jackTop(82, 0) + enclosure(id, 0, 0, W, H, 5) +
        [0, 1, 2].map(i => knob(id, 22 + i * 28, 24, 7.5, [.35, .6, .5][i], '#f4f1ea')).join('') +
        [0, 1, 2].map(i => knob(id, 22 + i * 28, 52, 7.5, [.7, .25, .45][i], '#f4f1ea')).join('') +
        [0, 1, 2].map(i => toggle(id, 30 + i * 20, 78, i !== 1)).join('') +
        led(id, 28, 100, '#ffb347', on) + led(id, 72, 100, '#ffb347', false) + foot(id, 28, 120, 7.5) + foot(id, 72, 120, 7.5),
      o.label || 'compact');
    },
    'floor-multi'(o) {
      const id = 'ghw' + (++count), W = 300, H = 164, body = '#1d1f22', on = o.on !== false;
      const rings = ['#3dd6ff', '#ff7a45', '#7bd36b', '#c77dff', '#ffd23f', '#ff4d6d'];
      return svg('floor-multi', `-8 -12 ${W + 16} ${H + 26}`, o.width || W + 16, hwDefs(id, body) +
        jackTop(24, 0) + jackTop(44, 0) + usbTop(110, 0) + dinTop(140, 0) + dinTop(166, 0) + jackTop(196, 0) +
        enclosure(id, 0, 0, W, H, 8) + screen(id, 52, 14, 140, 46, 'blocks', '#9fd8ff', on) +
        [0, 1, 2, 3, 4, 5].map(i => knob(id, 54 + i * 27, 76, 6.5, [.4, .6, .3, .7, .5, .45][i])).join('') +
        rings.map((c, i) => { const cx = 24 + i * 38, cy = 132; return `${on ? `<circle cx="${cx}" cy="${cy}" r="13" fill="none" stroke="${c}" stroke-width="2.4" opacity=".5" filter="url(#${id}-glow)"/>` : ''}<circle cx="${cx}" cy="${cy}" r="12" fill="none" stroke="${on ? c : mix(c, '#000', .7)}" stroke-width="1.6"/>` + foot(id, cx, cy, 7); }).join('') +
        treadle(id, 240, 18, 50, 136) + screw(7, 7) + screw(W - 7, 7) + screw(7, H - 7) + screw(W - 7, H - 7),
      o.label || 'floor multi-effects');
    },
    'loop-switcher'(o) {
      const id = 'ghw' + (++count), W = 300, H = 120, body = '#26282b', on = o.on !== false;
      const loops = []; for (let i = 0; i < 8; i++) loops.push(jackTop(70 + i * 26, 0), jackTop(80 + i * 26, 0));
      return svg('loop-switcher', `-8 -12 ${W + 16} ${H + 26}`, o.width || W + 16, hwDefs(id, body) +
        jackTop(14, 0) + jackTop(28, 0) + loops.join('') + dinTop(286, 0) + `<rect x="${W - 6}" y="20" width="6" height="8" rx="1" fill="#15171a"/>` +
        enclosure(id, 0, 0, W, H, 6) + screen(id, 14, 22, 36, 26, 'segments', '#ff3b2a', on) +
        [0, 1, 2, 3, 4, 5, 6, 7].map(i => { const cx = 84 + (i % 4) * 54, cy = i < 4 ? 40 : 92; return led(id, cx, cy - 15, '#4cff7a', on && [0, 2, 5].includes(i), 1.6) + foot(id, cx, cy, 7); }).join('') +
        screw(6, 6) + screw(W - 6, 6) + screw(6, H - 6) + screw(W - 6, H - 6),
      o.label || 'loop switcher');
    },
    'foot-controller'(o) {
      const id = 'ghw' + (++count), W = 360, H = 134, body = '#3e4146', on = o.on !== false;
      return svg('foot-controller', `-8 -12 ${W + 16} ${H + 26}`, o.width || W + 16, hwDefs(id, body) +
        dinTop(40, 0) + dinTop(64, 0) + `<rect x="100" y="-4" width="10" height="5" rx="1" fill="#15171a"/>` +
        enclosure(id, 0, 0, W, H, 5) + `<rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="#fff" filter="url(#${id}-grain)" opacity=".7"/>` +
        screen(id, 12, 12, 40, 22, 'segments', '#ff3b2a', on) +
        [...Array(10)].map((_, i) => { const cx = 74 + (i % 5) * 34, cy = i < 5 ? 48 : 104; return led(id, cx, cy - 16, '#ff3b2a', on && i === 6, 1.5) + foot(id, cx, cy, 7.5); }).join('') +
        treadle(id, 252, 10, 44, 114) + treadle(id, 306, 10, 44, 114) + screw(5, 5) + screw(W - 5, 5) + screw(5, H - 5) + screw(W - 5, H - 5),
      o.label || 'MIDI foot controller');
    },
    'rack-1u'(o) {
      const id = 'ghw' + (++count), W = 400, H = 56, body = '#1f2124', on = o.on !== false;
      const btn = [...Array(8)].map((_, i) => `<rect x="${196 + i * 16}" y="34" width="12" height="7" rx="1.2" fill="#000" opacity=".5"/><rect x="${196 + i * 16}" y="33" width="12" height="7" rx="1.2" fill="#8d939a"/><rect x="${196 + i * 16}" y="33" width="12" height="2.2" rx="1" fill="#fff" opacity=".3"/>`).join('');
      const meter = (y) => [...Array(8)].map((_, i) => `<rect x="${118 + i * 6}" y="${y}" width="4.6" height="3" rx=".6" fill="${on && i < (y < 30 ? 6 : 5) ? (i > 5 ? '#ffb02e' : '#4cff7a') : '#1a2a1c'}"/>`).join('');
      return svg('rack-1u', `-6 -6 ${W + 12} ${H + 14}`, o.width || W + 12, hwDefs(id, body) +
        enclosure(id, 0, 0, W, H, 2, 'brushed') +
        [10, W - 10].map(x => `<rect x="${x - 6}" y="2" width="1" height="${H - 4}" fill="#000" opacity=".45"/>`).join('') +
        `<ellipse cx="9" cy="14" rx="3.2" ry="2.2" fill="#0a0b0c"/><ellipse cx="9" cy="42" rx="3.2" ry="2.2" fill="#0a0b0c"/><ellipse cx="${W - 9}" cy="14" rx="3.2" ry="2.2" fill="#0a0b0c"/><ellipse cx="${W - 9}" cy="42" rx="3.2" ry="2.2" fill="#0a0b0c"/>` +
        screw(9, 14, 1.8) + screw(9, 42, 1.8) + screw(W - 9, 14, 1.8) + screw(W - 9, 42, 1.8) +
        `<circle cx="34" cy="28" r="7" fill="url(#${id}-nut)"/><circle cx="34" cy="28" r="5" fill="#16181a"/>` + led(id, 52, 28, '#4cff7a', on, 1.4) +
        screen(id, 64, 14, 46, 26, 'vfd', '#5cffb0', on) + meter(18) + meter(30) + btn +
        `<circle cx="${W - 46}" cy="28" r="14" fill="#000" opacity=".5" filter="url(#${id}-glow)"/><circle cx="${W - 46}" cy="28" r="13" fill="url(#${id}-steel)"/><circle cx="${W - 46}" cy="28" r="9" fill="url(#${id}-steel)" stroke="#000" stroke-opacity=".25"/><circle cx="${W - 50}" cy="23" r="1.8" fill="#3c4146"/>`,
      o.label || 'rack effects unit');
    },
  };
  const HARDWARE_KINDS = Object.keys(KINDS);
  // kind: one of HARDWARE_KINDS (an unknown kind draws as `compact`); opts: {on, label, width}
  function hardwareUnit(kind, opts) { opts = opts || {}; return (KINDS[kind] || KINDS.compact)(opts); }
  return { hardwareUnit, HARDWARE_KINDS };
  })();

  // ---------- block mode ----------
  function blockTile(block, opts) {
    opts = opts || {};
    const c = block.color || '#8a94a3';
    return `<div class="gp-tile${opts.on === false ? ' is-off' : ''}" style="--tile:${esc(c)}" title="${esc(block.name)}" data-type="${esc(block.type)}">
  <span class="gp-tile-glyph">${glyph(block.glyph || block.type)}</span><span class="gp-tile-name">${esc(block.short || block.name)}</span></div>`;
  }

  // ---------- dispatch: any golem block, the right pedal ----------
  function blockByType(type) { return data().blocks.find(b => b.type === type); }
  // a capture's label ("EVH 5150 III Stealth", "Mesa 4x12 Celestion V30") -> its catalogue archetype
  // (kind: 'amps' | 'cabs' | 'pedals'), by the catalogue's own `match` and `aliases`, longest keyword
  // first; null when none fits
  function archetypeFor(kind, label) {
    const l = String(label || '').toLowerCase();
    if (!l) return null;
    // the longest matching keyword wins (golem's rule: "peavey 5150" beats "5150")
    let best = null, len = 0;
    (data().archetypes[kind] || []).forEach(a => [a.match].concat(a.aliases || []).forEach(m => {
      const k = String(m || '').toLowerCase();
      if (k && k.length > len && l.includes(k)) { best = a; len = k.length; }
    }));
    return best;
  }
  // item: a catalogue type, or {type, on, archetype, family, title, size, form}
  function pedalFor(item, opts) {
    const it = typeof item === 'string' ? { type: item } : item;
    // a type golem's catalogue does not list yet, but a golem-fx pedal stands for, is that pedal
    const gfxOf = t => Object.values(data().gfx).find(g => (g.blocks || []).includes(t));
    const b = blockByType(it.type) || (gfxOf(it.type) ? { type: it.type, family: 'gfx', gfx: gfxOf(it.type).crate }
      : { type: it.type, name: it.type, color: '#8a94a3', family: 'generic', params: [] });
    const o = Object.assign({}, opts || {}, it);
    if (isFeature(it.type)) return featureUnit(it.type, o);
    // MIDI hardware: the Whammy DT is a pitch treadle; a generic midi-pedal takes its registry kind (`kind`)
    if (it.type === 'whammy-dt') return hardwareUnit(o.kind || 'pitch-treadle', o);
    if (it.type === 'midi-pedal') return hardwareUnit(o.kind || 'compact', o);
    switch (b.family) {
      case 'gfx': return gfxPedal(b.gfx, o);
      case 'nam-pedal': return namPedal(b.type, o);
      case 'nam-head': return namHead(o);
      case 'nam-cab': return namCab(o);
      case 'nam-stack': return namStack(o);
      default: return genericPedal(b, o);
    }
  }

  // Real footprints. A drawing's native units are life-size for a compact stomp (112 units = 73 mm), but the
  // large floor units are drawn smaller than life so they read alone in a gallery: on a board next to stomps
  // they take this factor. footprint(svg) -> {w, h} in native units at life size, {mm} the real width;
  // a scene draws every unit at the same px per unit: width = footprint.w × scale.
  const FOOTPRINT = { 'gp-treadle': 1.26, 'gp-hw-pitch-treadle': 1.36, 'gp-hw-floor-multi': 2, 'gp-hw-loop-switcher': 1.9, 'gp-hw-foot-controller': 2.2 };
  function footprint(svg) {
    const vb = /viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"/.exec(svg) || [0, 124, 216];
    const cls = (/class="([^"]*)"/.exec(svg) || [0, ''])[1].split(/\s+/);
    const k = cls.reduce((m, c) => FOOTPRINT[c] || m, 1);
    return { w: vb[1] * k, h: vb[2] * k, k, mm: Math.round((vb[1] - 12) * k * 73 / 112) };
  }

  // the golem-fx finish: 'auto' (by family, default), 'anodized', 'thrash'; 'clay' is the first prototype's
  const api = {
    footprint, FOOTPRINT, defs, glyph, glyphAt, gfxPedal, genericPedal, namPedal, namHead, namCab, namStack, namRack, namModule, keysUnit, keysFamily, drumKit, padKit, featureUnit, isFeature, FEATURE_TYPES, hardwareUnit, HARDWARE_KINDS, outboardSetting, blockTile, pedalFor,
    blockByType, archetypeFor, enamelTreadle, ampLook, cabLayout, hueOf, mix, luma, esc, FONT, AMP_LOOK, NAM_VOICE, RACK_LOOK, RACK_GENERIC, KEYS_STYLE_HUE, EP_FAMILIES, KIT_TYPES, KIT_PIECES, KIT_SPOTS, kitAssets: api_assets,
    _parts: { dinSocket, stompSwitch, knobAlu, headBody, cabBody, corners, rackKnob, rackControl },
    layout: 'fixed', rune: 'engraved',
    style: 'auto', STYLES: ['auto'].concat(METAL_STYLES, 'blackwork', 'clay'), MOTIF, METAL_HUE, FAMILY_FINISH, CRATE_FINISH, finishFor,
    setStyle(s) { if (this.STYLES.includes(s)) this.style = s; return this.style; },
  };
  root.GolemPedals = api;
})(typeof window !== 'undefined' ? window : globalThis);

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
    const idx = Math.round(p.value != null ? p.value : p.default);
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
    return `<g class="gp-toggle"><rect x="${cx - 3.2}" y="${cy - 5}" width="6.4" height="10" rx="1.6" fill="#16120f"/>
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
    const spec = typeof crateOrSpec === 'string' ? data().gfx[crateOrSpec] : crateOrSpec;
    if (!spec) return '';
    let style = opts.style || api.style;
    if (style === 'auto') style = finishFor(spec);
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
  };
  const METAL_CRATE_HUE = { 'gfx-shimmer': '#8a3ff0', 'gfx-gapmeter': '#6b7480' };
  const THRASH_HUE = { drive: '#c8160e' };
  // the rune's light where the body's own hue would glow too dull
  const RUNE_LIGHT = { dynamics: '#5fb0ff', 'gfx-gapmeter': '#d8dde3' };
  const MOTIF = {
    'gfx-drive': 'flames', 'gfx-boost': 'chevrons', 'gfx-gate': 'barbed', 'gfx-comp': 'clamp', 'gfx-limiter': 'clamp',
    'gfx-deesser': 'clamp', 'gfx-wah': 'crescent', 'gfx-autowah': 'crescent', 'gfx-eq': 'curve', 'gfx-tremolo': 'pulse',
    'gfx-vibrato': 'waves', 'gfx-chorus': 'waves', 'gfx-flanger': 'jet', 'gfx-phaser': 'spiral', 'gfx-rotary': 'swirl',
    'gfx-killswitch': 'bolt', 'gfx-delay': 'echo', 'gfx-reverb': 'rays', 'gfx-shimmer': 'stars', 'gfx-octaver': 'diamonds',
    'gfx-pitch': 'stairs', 'gfx-pitch-classic': 'stairs', 'gfx-detune': 'stairs', 'gfx-gapmeter': 'ticks',
    'gfx-met': 'barbed', 'gfx-emet': 'flames', 'gfx-shem': 'chevrons', 'gfx-golem': 'waves',
  };
  const METAL_STYLES = ['anodized', 'thrash'];
  // style 'auto' (the default): the finish follows the family. Aggressive families (drive, dynamics,
  // utility) are thrash, the rest anodized; the killswitch's lightning is thrash, the gap meter anodized.
  const FAMILY_FINISH = { drive: 'thrash', dynamics: 'thrash', utility: 'thrash' };
  // the high-gain companions (Fortin's role) and the vocal doubler have their own black finish
  const CRATE_FINISH = { 'gfx-killswitch': 'thrash', 'gfx-gapmeter': 'anodized', 'gfx-met': 'blackwork', 'gfx-emet': 'blackwork', 'gfx-shem': 'blackwork', 'gfx-golem': 'blackwork' };
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
      case 'crescent':
        line(arcPath(cx, cy, W * .44, 200, 340)); line(arcPath(cx, cy, W * .53, 205, 335), .6);
        line(arcPath(cx, cy, W * .44, 20, 160), .45);
        break;
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
    if (row.length) {
      y += 10;
      row.forEach((it, i) => {
        const cx = W * (i + .5) / row.length;
        svg += it.k === 's' ? selectorClay(cx, y, 6.5, it.p, style === 'thrash' ? '#ffd400' : c.light, null, c.ink) : toggleClay(cx, y, it.p, c.ink);
      });
      y += 15;
    }
    const top = y, bottom = 148;
    const gy = (top + bottom - 6) / 2, gsize = Math.max(18, Math.min(38, bottom - top - 22));
    const cw = Math.min(W - 26, gsize + 30), ch = gsize + 12;
    const g = { x: W / 2, y: gy, cw, ch };

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
    const rune = cart + (on
      ? glyphAt(spec.glyph, g.x, gy, gsize, c.light, 2.8, 'filter="url(#gp-glow)" opacity=".95"') + glyphAt(spec.glyph, g.x, gy, gsize, mix(c.light, '#fff', .75), 1.3)
      : glyphAt(spec.glyph, g.x, gy, gsize, mix(c.hue, '#000', .45), 1.8));

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
</defs>
<g filter="url(#gp-shadow)">
  ${jacks(W, 40)}
  ${body}
</g>
<g clip-path="url(#${id}-c)">${motifSvg(MOTIF[spec.crate], style, W, H, g, c)}</g>
${finish}
${svg}
${rune}
${nameSvg}
${led}
${stompSwitch(W / 2, H - 21, 8.5)}
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
    return `<g class="gp-knob"><circle cx="${cx}" cy="${cy + 1.6}" r="${r + 2.4}" fill="#000" opacity=".35"/>
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
    switch (b.family) {
      case 'gfx': return gfxPedal(b.gfx, o);
      case 'nam-pedal': return namPedal(b.type, o);
      case 'nam-head': return namHead(o);
      case 'nam-cab': return namCab(o);
      case 'nam-stack': return namStack(o);
      default: return genericPedal(b, o);
    }
  }

  // the golem-fx finish: 'auto' (by family, default), 'anodized', 'thrash'; 'clay' is the first prototype's
  const api = {
    defs, glyph, glyphAt, gfxPedal, genericPedal, namPedal, namHead, namCab, namStack, blockTile, pedalFor,
    blockByType, archetypeFor, enamelTreadle, ampLook, cabLayout, hueOf, mix, luma, esc, FONT, AMP_LOOK, NAM_VOICE,
    _parts: { dinSocket, stompSwitch, knobAlu, headBody, cabBody, corners },
    style: 'auto', STYLES: ['auto'].concat(METAL_STYLES, 'blackwork', 'clay'), MOTIF, METAL_HUE, FAMILY_FINISH, CRATE_FINISH, finishFor,
    setStyle(s) { if (this.STYLES.includes(s)) this.style = s; return this.style; },
  };
  root.GolemPedals = api;
})(typeof window !== 'undefined' ? window : globalThis);

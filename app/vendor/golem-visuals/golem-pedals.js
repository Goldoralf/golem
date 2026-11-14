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
  const METAL_CRATE_HUE = { 'gfx-shimmer': '#8a3ff0', 'gfx-gapmeter': '#6b7480', 'gfx-glitch': '#72c000' };
  const THRASH_HUE = { drive: '#c8160e' };
  // the rune's light where the body's own hue would glow too dull
  const RUNE_LIGHT = { dynamics: '#5fb0ff', 'gfx-gapmeter': '#d8dde3' };
  const MOTIF = {
    'gfx-drive': 'flames', 'gfx-boost': 'chevrons', 'gfx-gate': 'barbed', 'gfx-comp': 'clamp', 'gfx-limiter': 'clamp',
    'gfx-deesser': 'clamp', 'gfx-wah': 'crescent', 'gfx-autowah': 'crescent', 'gfx-eq': 'curve', 'gfx-tremolo': 'pulse',
    'gfx-vibrato': 'waves', 'gfx-chorus': 'waves', 'gfx-flanger': 'jet', 'gfx-phaser': 'spiral', 'gfx-rotary': 'swirl',
    'gfx-killswitch': 'bolt', 'gfx-delay': 'echo', 'gfx-reverb': 'rays', 'gfx-shimmer': 'stars', 'gfx-octaver': 'diamonds',
    'gfx-pitch': 'stairs', 'gfx-pitch-classic': 'stairs', 'gfx-detune': 'stairs', 'gfx-gapmeter': 'ticks',
    'gfx-met': 'barbed', 'gfx-emet': 'flames', 'gfx-shem': 'chevrons', 'gfx-golem': 'waves', 'gfx-glitch': 'bins',
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
  };
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
    const fill = { red: '#a3201a', blue: '#2f5f9e', grey: '#9aa3ad', black: '#17191b' }[cap] || '#17191b';
    return `<g class="gp-knob"><circle cx="${cx}" cy="${cy + 1.4}" r="${r}" fill="#000" opacity=".45"/>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-knob)"/><circle cx="${cx}" cy="${cy}" r="${r * .72}" fill="${fill}"/>
  <circle cx="${cx}" cy="${cy}" r="${r * .72}" fill="url(#gp-sheen)" opacity=".5"/>
  <path d="M${cx} ${cy}L${px.toFixed(2)} ${py.toFixed(2)}" stroke="${cap === 'grey' ? '#15181b' : '#f2f4f6'}" stroke-width="${r > 16 ? 2.2 : 1.5}" stroke-linecap="round"/>${lbl}</g>`;
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
      default: return '';
    }
  }
  const RACK_W = { stepped: 78, knob: 52, toggle: 40, buttons: 44, vu: 150, leds: 34, badge: 38 };
  // ratio buttons: a column when it fits the unit's height, else a row
  const buttonsRow = (c, h) => !!c.row || (c.values || []).length * 14 > h - 26;
  const rackWidth = (c, small, h) => c.type === 'buttons' && buttonsRow(c, h) ? (c.values || []).length * 21 + 6
    : (c.size === 'big' ? 1.35 : 1) * (RACK_W[c.type] || 50) * (small && c.type === 'vu' ? .55 : 1);

  // a NAM capture of outboard gear, as a 19" rack unit. opts: archetype (an outboard archetype, or found
  // from opts.label / opts.title), kind ('preamp' | 'comp' | 'eq', for the generic unit), title, u,
  // on, setting (or read from opts.label: gain, hard, channel, ratio), width
  function namRack(opts) {
    opts = opts || {};
    const on = opts.on !== false;
    const arch = opts.archetype || archetypeFor('outboard', opts.label || opts.title) || RACK_GENERIC[opts.kind] || RACK_GENERIC.preamp;
    const L = RACK_LOOK[arch.look] || RACK_LOOK['console-60s'];
    const voice = NAM_VOICE[arch.kind] || NAM_VOICE.preamp;
    const set = Object.assign({}, outboardSetting(opts.label), opts.setting || {});
    const u = Math.max(1, Math.min(4, opts.u || arch.u || 1));
    const W = 600, H = u * RACK_U - 2, EAR = 26, title = opts.title || arch.short || arch.name || 'outboard';
    const holes = (u === 1 ? [H / 2] : [RACK_U * .27, H - RACK_U * .27]).flatMap(y => [[EAR / 2, y], [W - EAR / 2, y]])
      .map(([x, y]) => `<rect x="${x - 6.5}" y="${y - 3.6}" width="13" height="7.2" rx="3.6" fill="#0b0c0e"/><circle cx="${x}" cy="${y}" r="2.7" fill="#9aa3ad"/><circle cx="${x - .5}" cy="${y - .5}" r="1" fill="#eef1f4"/>`).join('');
    // the name block, left
    const tx = EAR + 14, small = u === 1;
    const tsize = small ? 17 : Math.min(26, 13 + u * 4);
    const name = `<text x="${tx}" y="${small ? H / 2 + 2 : H * .4}" font-family="${FONT.nam}" font-size="${tsize}" font-weight="800" letter-spacing="1.6" fill="${L.ink}">${esc(String(title).toUpperCase().slice(0, 12))}</text>
  <text x="${tx}" y="${small ? H / 2 + 14 : H * .4 + 15}" font-family="${FONT.gfx}" font-size="8" font-weight="600" letter-spacing="1.6" fill="${L.sub}">${esc(String(arch.sub || voice.label).toUpperCase())}</text>
  ${small ? '' : `<text x="${tx}" y="${H * .4 + 28}" font-family="${FONT.nam}" font-size="7" font-weight="700" letter-spacing="1.4" fill="${L.sub}" opacity=".8">NAM · ${esc(voice.label)}</text>`}`;
    // the controls, spread between the name block and the lamp
    const x0 = EAR + (small ? 128 : 150), x1 = W - EAR - 40;
    const ctls = (arch.controls || []).filter(c => c.type !== 'badge' || (c.bind && set[c.bind] != null));
    const widths = ctls.map(c => rackWidth(c, small, H));
    const total = widths.reduce((a, b) => a + b, 0), gap = Math.max(0, (x1 - x0 - total) / Math.max(1, ctls.length));
    const scale = total > x1 - x0 ? (x1 - x0) / total : 1;
    let cx = x0 + gap / 2;
    const cy = small ? H / 2 - 3 : H / 2 - 4;
    const body = ctls.map((c, i) => { const w = widths[i] * scale, x = cx + w / 2; cx += w + gap; return rackControl(c, x, cy, H, set, L, on, w + gap); }).join('');
    const lamp = `<circle cx="${W - EAR - 18}" cy="${H / 2}" r="6.4" fill="#26282b"/>
  <circle cx="${W - EAR - 18}" cy="${H / 2}" r="4.6" fill="${on ? L.lamp : mix(L.lamp, '#000', .7)}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  <circle cx="${W - EAR - 18}" cy="${H / 2}" r="4.6" fill="url(#gp-jewel)"/>`;
    return `<svg class="gp-rack gp-nam-rack${on ? ' is-on' : ''}" viewBox="-4 -4 ${W + 8} ${H + 10}" width="${opts.width || W + 8}" role="img" aria-label="NAM outboard — ${esc(title)}" data-archetype="${esc(arch.id || '')}" data-u="${u}">
<g filter="url(#gp-shadow-small)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="${L.panel}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="url(#${L.tex})" opacity="${L.tex === 'gp-brush-lines' ? .55 : .35}"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="3" fill="url(#gp-sheen)" opacity=".45"/>
  <path d="M${EAR} 2V${H - 2}M${W - EAR} 2V${H - 2}" stroke="#000" stroke-opacity=".35"/>
</g>
${holes}${name}${body}${lamp}
${glyphAt(arch.kind === 'comp' ? 'comp-nam' : arch.kind === 'eq' ? 'eq' : 'preamp-nam', W - EAR - 18, small ? H / 2 - 16 : H / 2 - 20, 11, L.sub, 2)}
</svg>`;
  }

  // the same outboard unit at the pedal footprint (Designer, pedal mode): a 500-series-style vertical
  // module, its controls in a narrow column. Same opts as namRack; the rack stays in the Library.
  function namModule(opts) {
    opts = opts || {};
    const on = opts.on !== false;
    const arch = opts.archetype || archetypeFor('outboard', opts.label || opts.title) || RACK_GENERIC[opts.kind] || RACK_GENERIC.preamp;
    const L = RACK_LOOK[arch.look] || RACK_LOOK['console-60s'];
    const voice = NAM_VOICE[arch.kind] || NAM_VOICE.preamp;
    const set = Object.assign({}, outboardSetting(opts.label), opts.setting || {});
    const W = 112, H = 200, title = opts.title || arch.short || arch.name || 'outboard';
    const top = 42, bottom = H - 34;
    // rows: a wide control alone, small ones in pairs; bound controls first in priority
    const ctls = (arch.controls || []).filter(c => c.type !== 'leds' && (c.type !== 'badge' || (c.bind && set[c.bind] != null)))
      .map(c => c.type === 'buttons' && (c.values || []).length * 21 > W - 16 ? Object.assign({}, c, { type: 'stepped' }) : c);
    const wide = c => c.type === 'stepped' || c.type === 'vu' || c.type === 'buttons' || c.size === 'big';
    const rowH = r => r.wide ? (r.items[0].type === 'buttons' ? 34 : r.items[0].type === 'vu' ? 40 : 54) : 44;
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
    // the capture's own setting first, then the meter, then the rest, while the column has room;
    // drawn in the unit's own order
    const flat = ctls.map((c, i) => Object.assign({}, c, { size: undefined, _i: i }));
    const prio = flat.filter(c => c.bind).concat(flat.filter(c => !c.bind && c.type === 'vu'), flat.filter(c => !c.bind && c.type !== 'vu'));
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
      if (r.wide) return rackControl(r.items[0], W / 2, cy, h + 6, set, L, on, W - 12);
      if (r.items.length === 1) return rackControl(r.items[0], W / 2, cy, h, set, L, on, W - 12);
      return r.items.map((c, i) => rackControl(c, W * (i ? .73 : .27), cy, h, set, L, on, W / 2)).join('');
    }).join('');
    const screws = [[W / 2, 7], [W / 2, H - 7]].map(([x, yy]) => `<rect x="${x - 7}" y="${yy - 3.4}" width="14" height="6.8" rx="3.4" fill="#0b0c0e"/><circle cx="${x}" cy="${yy}" r="2.5" fill="#9aa3ad"/><circle cx="${x - .5}" cy="${yy - .5}" r=".9" fill="#eef1f4"/>`).join('');
    const tsize = String(title).length > 7 ? 11 : 15;
    return `<svg class="gp-pedal gp-nam-module${on ? ' is-on' : ''}" viewBox="-6 -4 ${W + 12} ${H + 16}" width="${opts.width || W + 12}" role="img" aria-label="NAM outboard — ${esc(title)}" data-archetype="${esc(arch.id || '')}">
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
<text x="${W / 2 - 8}" y="${H - 15.5}" font-family="${FONT.nam}" font-size="6.4" font-weight="700" letter-spacing="1.2" fill="${L.sub}">NAM</text>
${glyphAt(arch.kind === 'comp' ? 'comp-nam' : arch.kind === 'eq' ? 'eq' : 'preamp-nam', W / 2 + 26, H - 18, 10, L.sub, 2)}
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
  // A drum set seen from the front, one layout per kind of kit, never a maker's livery; the finish (a hue and
  // a wrap) is picked from the title when not given, so two kits never look the same.
  const KIT_TYPES = ['rock', 'jazz', 'metal', 'vintage', 'electronic', 'hybrid'];
  const KIT_HUES = ['#b3121f', '#1f4fa3', '#2b2b2e', '#e8e2d0', '#2f7a3a', '#6e3aa0', '#c47a1c', '#7a4a26', '#0f6f7a', '#8a1e4a'];
  const KIT_WRAPS = ['gloss', 'sparkle', 'pearl', 'wood', 'satin'];
  const KIT_PIECES = ['kick', 'snare', 'hats', 'ride', 'crash', 'toms'];
  let kitCount = 0;
  const hashOf = s => { let h = 2166136261; for (const c of String(s || '')) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };
  // opts.finish: a hex hue, a wrap name, or {hue, wrap}; else from the title (and the type's taste)
  function kitFinish(type, title, finish) {
    const h = hashOf(title);
    const f = typeof finish === 'string' ? (finish[0] === '#' ? { hue: finish } : { wrap: finish }) : (finish || {});
    const wrapPref = { vintage: ['pearl', 'sparkle', 'wood'], jazz: ['wood', 'satin', 'gloss'], metal: ['gloss', 'satin', 'sparkle'] }[type] || KIT_WRAPS;
    const huePref = type === 'metal' ? ['#2b2b2e', '#8a1e4a', '#b3121f', '#1f4fa3'] : KIT_HUES;
    return { hue: f.hue || huePref[h % huePref.length], wrap: KIT_WRAPS.includes(f.wrap) ? f.wrap : wrapPref[(h >>> 8) % wrapPref.length] };
  }

  function kitDefs(id, F) {
    const sparkle = Array.from({ length: 14 }, (_, i) => `<circle cx="${(i * 37) % 23 + .5}" cy="${(i * 53) % 19 + .5}" r="${.5 + (i % 3) * .35}" fill="#fff" opacity="${.35 + (i % 4) * .15}"/>`).join('');
    return `<defs>
  <linearGradient id="${id}-shade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity=".45"/><stop offset=".32" stop-color="#fff" stop-opacity=".16"/><stop offset=".55" stop-color="#fff" stop-opacity=".04"/><stop offset="1" stop-color="#000" stop-opacity=".5"/></linearGradient>
  <radialGradient id="${id}-cym" cx=".42" cy=".35" r=".75"><stop offset="0" stop-color="#f6dc8c"/><stop offset=".55" stop-color="#d0a447"/><stop offset="1" stop-color="#8a6420"/></radialGradient>
  <radialGradient id="${id}-pearl" cx=".3" cy=".3" r=".9"><stop offset="0" stop-color="#fff" stop-opacity=".85"/><stop offset=".5" stop-color="${mix(F.hue, '#fff', .6)}" stop-opacity=".55"/><stop offset="1" stop-color="${F.hue}" stop-opacity="0"/></radialGradient>
  <pattern id="${id}-sparkle" width="23" height="19" patternUnits="userSpaceOnUse">${sparkle}</pattern>
  <pattern id="${id}-mesh" width="4" height="4" patternUnits="userSpaceOnUse"><path d="M0 0L4 4M4 0L0 4" stroke="#000" stroke-opacity=".5" stroke-width=".6"/></pattern>
</defs>`;
  }
  // the wrap on a shell's body
  function wrapFill(id, F, x, y, w, h, rx) {
    const r = `x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${rx || 0}"`;
    const over = { sparkle: `<rect ${r} fill="url(#${id}-sparkle)"/>`, pearl: `<rect ${r} fill="url(#${id}-pearl)"/>`,
      wood: `<rect ${r} fill="url(#gp-brush-lines)" opacity=".55"/>`, satin: '', gloss: `<rect ${r} fill="url(#gp-gloss)" opacity=".35"/>` }[F.wrap] || '';
    return `<rect ${r} fill="${F.wrap === 'wood' ? mix(F.hue, '#6b3e1e', .55) : F.hue}"/>${over}<rect ${r} fill="url(#${id}-shade)"/>`;
  }
  const LIT = '#ffd27a';
  // the stroke of a hoop or a pad: its own, or the lit gold one (never both: an attribute twice is invalid XML)
  const litStroke = (on, lit, stroke, width) => on && lit ? ` stroke="${LIT}" stroke-width="2.4" filter="url(#gp-glow-soft)"`
    : stroke ? ` stroke="${stroke}" stroke-width="${width}"` : '';

  // a shell seen slightly from above: body w × h under its top head
  function shell(id, F, cx, top, w, h, o) {
    o = o || {};
    const ry = w * .17, x = cx - w / 2, head = o.mesh ? '#3a3d42' : (o.head || '#ece6d6');
    const nl = Math.max(3, Math.round(w / 22));
    const lugs = o.detail && !o.mesh ? Array.from({ length: nl }, (_, i) => {
      const lx = x + w * (i + .5) / nl; return `<rect x="${(lx - 1.6).toFixed(1)}" y="${(top + h * .3).toFixed(1)}" width="3.2" height="${(h * .4).toFixed(1)}" rx="1.2" fill="url(#gp-chrome)"/>`; }).join('') : '';
    return `<g class="gp-drum">${o.mesh ? `<rect x="${x}" y="${top}" width="${w}" height="${h}" fill="#1b1c1f"/><rect x="${x}" y="${top}" width="${w}" height="${h}" fill="url(#${id}-shade)"/>` : wrapFill(id, F, x, top, w, h)}
  <ellipse cx="${cx}" cy="${top + h}" rx="${w / 2}" ry="${ry}" fill="#000" opacity=".25"/>${lugs}
  <ellipse cx="${cx}" cy="${top}" rx="${w / 2}" ry="${ry}" fill="${head}"/>${o.mesh ? `<ellipse cx="${cx}" cy="${top}" rx="${w / 2}" ry="${ry}" fill="url(#${id}-mesh)"/>` : ''}
  <ellipse cx="${cx}" cy="${top}" rx="${w / 2}" ry="${ry}" fill="none"${litStroke(o.on, o.lit, 'url(#gp-chrome)', o.detail ? 2.6 : 1.8)}/></g>`;
  }
  function cymbal(id, cx, cy, rx, o) {
    o = o || {};
    const ry = Math.max(3, rx * (o.china ? .2 : .14)), floor = o.floor;
    const stand = floor ? `<path d="M${cx} ${cy}V${floor - 10}M${cx} ${floor - 10}l-${rx * .35} 10M${cx} ${floor - 10}l${rx * .35} 10" stroke="#7d838a" stroke-width="1.6" fill="none"/>` : '';
    const body = o.rubber ? `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="#1c1d20"/><ellipse cx="${cx}" cy="${cy}" rx="${rx * .82}" ry="${ry * .78}" fill="none" stroke="${o.ring || '#5ec8e0'}" stroke-width="1.4" opacity=".8"/>`
      : o.china ? `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="url(#${id}-cym)"/><ellipse cx="${cx}" cy="${cy}" rx="${rx * .78}" ry="${ry * .7}" fill="#8a6420" opacity=".55"/><path d="M${cx - rx} ${cy}q${rx * .08} ${-ry * 1.1} ${rx * .2} ${-ry * .5}M${cx + rx} ${cy}q${-rx * .08} ${-ry * 1.1} ${-rx * .2} ${-ry * .5}" stroke="#d0a447" stroke-width="1.6" fill="none"/>`
        : `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="url(#${id}-cym)"/><ellipse cx="${cx}" cy="${cy - ry * .2}" rx="${rx * .18}" ry="${ry * .45}" fill="#f6dc8c"/>`;
    const lit = o.on && o.lit ? `<ellipse cx="${cx}" cy="${cy}" rx="${rx + 3}" ry="${ry + 2}" fill="none" stroke="${LIT}" stroke-width="2" filter="url(#gp-glow-soft)"/>` : '';
    return `<g class="gp-cymbal">${stand}${body}${lit}</g>`;
  }
  function hats(id, cx, cy, rx, o) {
    o = o || {};
    return `<g class="gp-hats">${cymbal(id, cx, cy + 4, rx, { floor: o.floor, rubber: o.rubber, ring: o.ring })}${cymbal(id, cx, cy, rx, { rubber: o.rubber, ring: o.ring, on: o.on, lit: o.lit })}</g>`;
  }
  // the kick from the front: the resonant head carries the title
  function kickFront(id, F, cx, cy, r, title, o) {
    o = o || {};
    const metal = o.type === 'metal', vint = o.type === 'vintage';
    const head = metal ? '#141416' : vint ? '#efe6cf' : '#ece6d6', ink = metal ? '#e9edf1' : vint ? mix(F.hue, '#2a1a10', .55) : '#202226';
    const t = String(title || '').slice(0, 14), fs = Math.min(r * .34, (1.62 * r) / Math.max(4, t.length) * 1.25);
    const lugs = o.detail ? Array.from({ length: 10 }, (_, i) => { const [lx, ly] = polar(cx, cy, r + 2, i * 36);
      return `<circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="2.2" fill="url(#gp-chrome)"/>`; }).join('') : '';
    const spurs = `<path d="M${cx - r * .8} ${cy + r * .5}l-${r * .25} ${r * .5}M${cx + r * .8} ${cy + r * .5}l${r * .25} ${r * .5}" stroke="url(#gp-chrome)" stroke-width="2.4"/>`;
    const port = metal && o.detail ? `<circle cx="${cx + r * .42}" cy="${cy + r * .42}" r="${r * .16}" fill="#000"/><circle cx="${cx + r * .42}" cy="${cy + r * .42}" r="${r * .16}" fill="none" stroke="#555"/>` : '';
    return `<g class="gp-kick">${spurs}<circle cx="${cx}" cy="${cy}" r="${r + 5}" fill="${F.wrap === 'wood' ? mix(F.hue, '#6b3e1e', .55) : F.hue}"/>
  ${F.wrap === 'sparkle' ? `<circle cx="${cx}" cy="${cy}" r="${r + 5}" fill="url(#${id}-sparkle)"/>` : F.wrap === 'pearl' ? `<circle cx="${cx}" cy="${cy}" r="${r + 5}" fill="url(#${id}-pearl)"/>` : ''}
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="${head}"/>${lugs}
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#gp-sheen)" opacity=".35"/>
  ${vint ? `<circle cx="${cx}" cy="${cy}" r="${r * .62}" fill="none" stroke="${ink}" stroke-width="1.2" opacity=".6"/>` : ''}${port}
  <text x="${cx}" y="${cy + fs * .36}" text-anchor="middle" font-family="${vint ? FONT.enamel : FONT.nam}" font-size="${fs.toFixed(1)}" font-weight="800" letter-spacing="${vint ? .5 : 1.4}" fill="${ink}">${esc(vint ? t : t.toUpperCase())}</text>
  <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"${litStroke(o.on, o.lit, 'url(#gp-chrome)', o.detail ? 3 : 2)}/></g>`;
  }
  // an electronic kit's kick tower
  function kickTower(id, cx, base, w, h, title, o) {
    o = o || {};
    return `<g class="gp-kick"><rect x="${cx - w / 2}" y="${base - h}" width="${w}" height="${h}" rx="4" fill="#1b1c1f"/>
  <rect x="${cx - w * .38}" y="${base - h + 6}" width="${w * .76}" height="${w * .76}" rx="3" fill="#3a3d42"/><rect x="${cx - w * .38}" y="${base - h + 6}" width="${w * .76}" height="${w * .76}" rx="3" fill="url(#${id}-mesh)"${litStroke(o.on, o.lit)}/>
  <text x="${cx}" y="${base - 8}" text-anchor="middle" font-family="${FONT.gfx}" font-size="${Math.min(9, w / 6)}" font-weight="700" letter-spacing="1" fill="#cfd3d8">${esc(String(title || '').toUpperCase().slice(0, 10))}</text></g>`;
  }
  function kitModule(cx, cy, w, title, on, hue) {
    const h = w * .62;
    return `<g class="gp-module"><path d="M${cx} ${cy + h / 2}V${cy + h / 2 + 60}" stroke="#7d838a" stroke-width="1.6"/>
  <rect x="${cx - w / 2}" y="${cy - h / 2}" width="${w}" height="${h}" rx="3" fill="#202226"/>
  <rect x="${cx - w * .4}" y="${cy - h * .34}" width="${w * .8}" height="${h * .34}" rx="1.5" fill="${on ? mix(hue, '#05070a', .55) : '#0a0c0e'}"${on ? ' filter="url(#gp-glow-soft)"' : ''}/>
  <text x="${cx}" y="${cy - h * .1}" text-anchor="middle" font-family="${FONT.gfx}" font-size="${(h * .2).toFixed(1)}" font-weight="700" fill="${on ? '#eef0f2' : '#4a4f56'}">${esc(String(title || '').toUpperCase().slice(0, 9))}</text>
  ${[0, 1, 2].map(i => `<circle cx="${cx - w * .25 + i * w * .25}" cy="${cy + h * .25}" r="${w * .07}" fill="#3a3d42"/>`).join('')}</g>`;
  }

  // layouts on a 600 × 340 floor plan (floor at y 322); `s` scales them for the compact tile
  function kitBody(id, type, F, title, o) {
    const on = o.on, d = !o.compact, L = new Set([].concat(o.lit || []).filter(p => KIT_PIECES.includes(p)));
    const lit = p => on && L.has(p), floor = 322, ring = mix(F.hue, '#fff', .3);
    const parts = [];
    const stand = (x, y) => `<path d="M${x} ${y}V${floor - 12}M${x} ${floor - 12}l-12 12M${x} ${floor - 12}l12 12" stroke="#7d838a" stroke-width="1.6" fill="none"/>`;
    const floorTom = (cx, top, w, h) => `<path d="M${cx - w * .42} ${top + h}l-6 ${floor - top - h}M${cx + w * .42} ${top + h}l6 ${floor - top - h}" stroke="url(#gp-chrome)" stroke-width="2.2"/>` + shell(id, F, cx, top, w, h, { detail: d, on, lit: lit('toms') });
    if (type === 'electronic') {
      parts.push(`<path d="M120 196H520M140 196V${floor}M500 196V${floor}" stroke="#3a3d42" stroke-width="6" stroke-linecap="round"/>`);
      parts.push(hats(id, 66, 150, 40, { floor, rubber: true, ring, on, lit: lit('hats') }));
      parts.push(cymbal(id, 178, 74, 46, { floor, rubber: true, ring, on, lit: lit('crash') }));
      parts.push(cymbal(id, 462, 88, 52, { floor, rubber: true, ring, on, lit: lit('ride') }));
      parts.push(shell(id, F, 240, 150, 62, 12, { mesh: true, on, lit: lit('toms') }), shell(id, F, 340, 150, 62, 12, { mesh: true, on, lit: lit('toms') }));
      parts.push(shell(id, F, 462, 196, 72, 14, { mesh: true, on, lit: lit('toms') }));
      parts.push(shell(id, F, 160, 210, 76, 14, { mesh: true, on, lit: lit('snare') }));
      parts.push(kickTower(id, 300, floor, 70, 96, title, { on, lit: lit('kick') }));
      parts.push(kitModule(552, 214, 62, title, on, F.hue));
      return parts.join('');
    }
    const T = {
      rock: { kick: [300, 246, 72], toms: [[250, 118, 64, 46], [348, 118, 64, 46]], floor: [[484, 176, 88, 92]], snare: [154, 186, 84, 32], hats: [66, 150, 40], crash: [[168, 70, 52]], ride: [474, 96, 60], china: [] },
      jazz: { kick: [300, 262, 56], toms: [[300, 152, 56, 40]], floor: [[452, 196, 80, 82]], snare: [176, 204, 80, 28], hats: [74, 164, 38], crash: [[178, 92, 44]], ride: [438, 84, 72], china: [] },
      vintage: { kick: [300, 248, 70], toms: [[300, 126, 62, 46]], floor: [[478, 180, 86, 90]], snare: [158, 190, 82, 32], hats: [66, 154, 40], crash: [[172, 76, 50]], ride: [470, 92, 62], china: [] },
      metal: { kick: [[238, 258, 60], [362, 258, 60]], toms: [[218, 116, 54, 42], [300, 104, 56, 44], [382, 116, 54, 42]], floor: [[490, 172, 82, 92], [560, 196, 56, 72]], snare: [130, 194, 80, 30], hats: [52, 152, 36], crash: [[146, 62, 50], [454, 50, 52]], ride: [536, 112, 50], china: [[64, 92, 40]] },
    };
    const k = T[type === 'hybrid' ? 'rock' : type] || T.rock;
    // stands first, cymbals last (on top), drums between, back to front
    k.crash.forEach(([x, y]) => parts.push(stand(x, y)));
    parts.push(stand(k.ride[0], k.ride[1]));
    (k.china || []).forEach(([x, y]) => parts.push(stand(x, y)));
    k.floor.forEach(([x, t, w, h]) => parts.push(floorTom(x, t, w, h)));
    const kicks = Array.isArray(k.kick[0]) ? k.kick : [k.kick];
    k.toms.forEach(([x, t, w, h]) => parts.push(shell(id, F, x, t, w, h, { detail: d, on, lit: lit('toms') })));
    kicks.forEach(([x, y, r]) => parts.push(kickFront(id, F, x, y, r, title, { detail: d, type, on, lit: lit('kick') })));
    const [sx, st, sw, sh] = k.snare;
    parts.push(`<path d="M${sx} ${st + sh}V${floor - 12}M${sx} ${floor - 12}l-12 12M${sx} ${floor - 12}l12 12" stroke="#7d838a" stroke-width="1.6" fill="none"/>`);
    parts.push(shell(id, { hue: '#b9bfc6', wrap: 'gloss' }, sx, st, sw, sh, { detail: d, on, lit: lit('snare') }));
    parts.push(hats(id, k.hats[0], k.hats[1], k.hats[2], { floor, on, lit: lit('hats') }));
    k.crash.forEach(([x, y, r]) => parts.push(cymbal(id, x, y, r, { on, lit: lit('crash') })));
    (k.china || []).forEach(([x, y, r]) => parts.push(cymbal(id, x, y, r, { china: true, on, lit: lit('crash') })));
    parts.push(cymbal(id, k.ride[0], k.ride[1], k.ride[2], { on, lit: lit('ride') }));
    if (type === 'hybrid') {
      parts.push(shell(id, F, 96, 230, 48, 10, { mesh: true, on, lit: lit('snare') }), shell(id, F, 556, 248, 48, 10, { mesh: true, on, lit: lit('toms') }));
      parts.push(kitModule(556, 202, 54, title, on, F.hue));
    }
    return parts.join('');
  }

  // a drum set. opts: type ('rock' · 'jazz' · 'metal' · 'vintage' · 'electronic' · 'hybrid'), title (on
  // the kick head), finish (a hex hue, a wrap 'gloss' · 'sparkle' · 'pearl' · 'wood' · 'satin', or {hue,
  // wrap}; from the title when absent), lit (a piece or a list: kick, snare, hats, ride, crash, toms — lit
  // when on), on, compact (a 300-wide tile for a wall), width
  function drumKit(opts) {
    opts = opts || {};
    const type = KIT_TYPES.includes(opts.type) ? opts.type : 'rock';
    const title = opts.title || { rock: 'Rock', jazz: 'Jazz', metal: 'Metal', vintage: 'Vintage', electronic: 'E-Kit', hybrid: 'Hybrid' }[type];
    const on = opts.on !== false, F = kitFinish(type, title, opts.finish), id = 'gpk' + (++kitCount);
    const compact = !!opts.compact, W = compact ? 300 : 600, H = compact ? 186 : 340;
    const body = kitBody(id, type, F, title, { on, lit: opts.lit, compact });
    const s = compact ? .5 : 1, dy = compact ? 2 : 0;
    const bg = compact ? `<rect x="0" y="0" width="${W}" height="${H}" rx="7" fill="#17181b"/><rect x="0" y="${H - 22}" width="${W}" height="22" fill="#0e0f11"/>
  <text x="10" y="${H - 7}" font-family="${FONT.nam}" font-size="12" font-weight="800" letter-spacing="1.2" fill="#e2e6ea">${esc(String(title).toUpperCase().slice(0, 22))}</text>
  <text x="${W - 10}" y="${H - 7}" text-anchor="end" font-family="${FONT.gfx}" font-size="8" font-weight="700" letter-spacing="1.4" fill="${mix(F.hue, '#fff', .45)}">${type.toUpperCase()}</text>`
      : `<rect x="0" y="0" width="${W}" height="${H}" rx="8" fill="#17181b"/><rect x="0" y="${H - 18}" width="${W}" height="18" rx="0" fill="#0e0f11"/>
  <ellipse cx="${W / 2}" cy="${H - 18}" rx="${W * .46}" ry="12" fill="${mix(F.hue, '#000', .7)}" opacity=".6"/>`;
    return `<svg class="gp-kit gp-kit-${type}${compact ? ' gp-kit-compact' : ''}${on ? ' is-on' : ''}" viewBox="-4 -4 ${W + 8} ${H + 8}" width="${opts.width || W + 8}" role="img" aria-label="drum kit — ${esc(title)}" data-type="${type}" data-wrap="${F.wrap}">
${kitDefs(id, F)}${bg}
<g transform="translate(0 ${dy}) scale(${s})">${body}</g>
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
    defs, glyph, glyphAt, gfxPedal, genericPedal, namPedal, namHead, namCab, namStack, namRack, namModule, keysUnit, keysFamily, drumKit, padKit, outboardSetting, blockTile, pedalFor,
    blockByType, archetypeFor, enamelTreadle, ampLook, cabLayout, hueOf, mix, luma, esc, FONT, AMP_LOOK, NAM_VOICE, RACK_LOOK, RACK_GENERIC, KEYS_STYLE_HUE, EP_FAMILIES, KIT_TYPES, KIT_PIECES,
    _parts: { dinSocket, stompSwitch, knobAlu, headBody, cabBody, corners, rackKnob, rackControl },
    layout: 'fixed', rune: 'engraved',
    style: 'auto', STYLES: ['auto'].concat(METAL_STYLES, 'blackwork', 'clay'), MOTIF, METAL_HUE, FAMILY_FINISH, CRATE_FINISH, finishFor,
    setStyle(s) { if (this.STYLES.includes(s)) this.style = s; return this.style; },
  };
  root.GolemPedals = api;
})(typeof window !== 'undefined' ? window : globalThis);

// SPDX-License-Identifier: GPL-3.0-or-later
// golem pedals: SVG renderers for every block golem can put on a lane, in three families.
//
//   gfx      "clay"     golem-fx's own effects: a matte cast body tinted by the block's colour, the
//                       glyph cast into it as a rune that lights up when the pedal is on.
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
  function selectorClay(cx, cy, r, p, accent, inkOpacity) {
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
  <text x="${cx}" y="${cy + r + 8}" text-anchor="middle" font-family="${FONT.gfx}" font-size="5.6" font-weight="600" fill="#000" fill-opacity="${inkOpacity || .62}">${esc(label.toLowerCase())}</text>
</g>`;
  }

  function toggleClay(cx, cy, p) {
    const on = (p.value != null ? p.value : p.default) >= .5;
    return `<g class="gp-toggle"><rect x="${cx - 3.2}" y="${cy - 5}" width="6.4" height="10" rx="1.6" fill="#16120f"/>
  <circle cx="${cx}" cy="${on ? cy - 2.4 : cy + 2.4}" r="2.1" fill="url(#gp-chrome)"/>
  <text x="${cx}" y="${cy + 12}" text-anchor="middle" font-family="${FONT.gfx}" font-size="5.4" font-weight="600" fill="#000" fill-opacity=".6">${esc(shortLabel(p.name))}</text></g>`;
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
  function knobGrid(knobs, x0, x1, y0, accent, kind) {
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
        svg += kind === 'enamel' ? knobEnamel(cx, y + dy, r, p) : knobClay(cx, y + dy, r, p, accent, shortLabel(p.name));
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
    const b = blockByType(it.type) || { type: it.type, name: it.type, color: '#8a94a3', family: 'generic', params: [] };
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

  root.GolemPedals = {
    defs, glyph, glyphAt, gfxPedal, genericPedal, namPedal, namHead, namCab, namStack, blockTile, pedalFor,
    blockByType, archetypeFor, enamelTreadle, ampLook, cabLayout, hueOf, mix, luma, esc, FONT, AMP_LOOK, NAM_VOICE,
    _parts: { dinSocket, stompSwitch, knobAlu, headBody, cabBody, corners },
  };
})(typeof window !== 'undefined' ? window : globalThis);

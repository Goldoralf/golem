// SPDX-License-Identifier: GPL-3.0-or-later
// golem rig: a lane cut into sections, each drawn in its natural view (the way amp-sim plugins do):
// the pedals from above on a board, the heads / cabs and the outboard rack from the front.
//
//   const secs = GolemRig.sections(chain, {outboard: 'rack' | 'board', features: 'tab' | 'hide' | 'inline'})
//   GolemRig.render(secs[i], {floor, seed, W, H, width})   one section, 16:9 by default
//   GolemRig.card(secs, {floor, seed, width})              the fixed 16:9 picture of a rig (cards, shares)
//   GolemRig.floorFor(genre)                               a floor for a song's genre
//   GolemRig.standalone(svg, {fontsCss})                   the same drawing as a file of its own
// detail: 'badge' (the card's default) puts each block's glyph, large, over its pedal; 'full' leaves it bare.
//
// chain: GolemStage.render()'s items (block types, {type, on, …} objects, {split: {…}}), so
// GolemRig.sections(GolemStage.fromGolem(lane.chain, laneState)) draws a golem lane.
//   GolemRig.fromLane(lane, state, opts)                   a golem lane -> its sections (needs golem-stage.js)
//   GolemRig.presetCard(lanes, {floor, seed})              the picture of a preset: one cell per lane
// A section: {key: 'instrument' | 'pre' | 'outboard' | 'amp' | 'post' | 'tools', label, items}. Each item keeps its path in
// the chain as `idx` ("3", or "3.1.0" inside a branch) and is drawn with data-idx; a block of a split's branch
// carries `branch` (its letter) and a tape with data-split / data-branch / data-b, as GolemStage does.
// Needs golem-pedals.js and its defs().
(function (root) {
  'use strict';
  const P = () => root.GolemPedals;
  let count = 0;
  const f = n => n.toFixed(1);
  const letter = b => String.fromCharCode(65 + b);
  const PRE = '#c9a24b', POST = '#3d8f96', TOOLS = '#8d949b';   // cable colour: which side of the amp
  const shade = (hex, k) => '#' + [1, 3, 5].map(i => Math.max(0, Math.min(255, Math.round(parseInt(hex.slice(i, i + 2), 16) * k))).toString(16).padStart(2, '0')).join('');
  const rng = seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  // a seed from a number or any string (a patch id), so a rig always draws the same floor
  const seedOf = s => { if (typeof s === 'number' && s > 0) return Math.floor(s) % 2147483646 + 1; let h = 20261117; for (const c of String(s || '')) h = (h * 31 + c.charCodeAt(0)) % 2147483646; return h + 1; };

  const familyOf = t => (P().blockByType(t) || {}).family || 'generic';
  const isHead = it => familyOf(it.type) === 'nam-head';
  const isCab = it => it.type === 'cab' || familyOf(it.type) === 'nam-cab';
  const isAmp = it => ['nam-head', 'nam-cab', 'nam-stack'].includes(familyOf(it.type));
  const OUTBOARD = ['preamp-nam', 'comp-nam', 'ir-fx'];
  const isOutboard = it => OUTBOARD.includes(it.type);

  function place(svg, x, y, w, idx) {
    const vb = /viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"/.exec(svg).slice(1).map(Number);
    const h = w * vb[3] / vb[2];
    return { svg: svg.replace(/^<svg /, `<svg x="${f(x)}" y="${f(y)}" height="${f(h)}" ${idx != null ? `data-idx="${idx}" ` : ''}`).replace(/ width="[\d.]+"/, ` width="${f(w)}"`), h, vb, x, y, w };
  }

  // ---------- the chain -> sections ----------
  function sections(chain, opts) {
    opts = opts || {};
    const rackMode = opts.outboard !== 'board', feat = opts.features || 'tab';
    const pre = [], post = [], amps = [], ob = [], tools = [], inst = [];
    let obAfter = false;
    const norm = c => (typeof c === 'string' ? { type: c } : c);
    // one series of blocks; `seen`: an amp already came before. Returns whether one has come by its end.
    function walk(list, prefix, seen, br) {
      for (let i = 0; i < list.length; i++) {
        const it = norm(list[i]), idx = prefix + i;
        if (it && it.split) {
          const sp = it.split;
          let any = false;
          (sp.branches || []).forEach((b, bi) => {
            const arr = Array.isArray(b) ? b : (b.items || b.blocks || []);
            const tag = { letter: letter(bi), b: bi, id: (b && b.id) || letter(bi), mute: !!(b && b.mute) || !!(br && br.mute), split: idx };
            if (walk(arr, `${idx}.${bi}.`, seen, tag)) any = true;
          });
          seen = seen || any;
          continue;
        }
        const x = Object.assign({}, it, { idx }, br ? { branch: br.letter, branchInfo: br } : {}, br && br.mute ? { on: false, muted: true } : {});
        if (P().isFeature(x.type) && feat !== 'inline') { if (feat === 'tab') tools.push(x); continue; }
        if (familyOf(x.type) === 'instrument' && feat !== 'inline-instruments') { inst.push(x); continue; }
        if (isAmp(x)) {
          const nx = list[i + 1] && norm(list[i + 1]);
          if (!isCab(x) && nx && isCab(nx)) {            // an amp and the cab after it stand as one stack
            amps.push(Object.assign({}, x, { type: 'amp', family: x.family || nx.family, size: nx.size || nx.title, cabTitle: nx.title }));
            i++;
          } else amps.push(x);
          seen = true;
          continue;
        }
        if (isOutboard(x) && rackMode) { ob.push(x); if (seen) obAfter = true; continue; }
        (seen ? post : pre).push(x);
      }
      return seen;
    }
    walk(chain || [], '', false, null);
    const sec = [];
    if (inst.length) sec.push({ key: 'instrument', label: inst.every(x => x.type === 'drumkit') ? 'Drums' : inst.every(x => x.type === 'pads') ? 'Pads' : inst.some(x => x.type === 'drumkit' || x.type === 'pads') ? 'Instruments' : 'Keys', items: inst });
    if (pre.length) sec.push({ key: 'pre', label: amps.length ? 'Pedals · pre' : 'Pedals', items: pre });
    if (ob.length && !obAfter) sec.push({ key: 'outboard', label: 'Outboard', items: ob });
    if (amps.length) sec.push({ key: 'amp', label: amps.length > 1 ? 'Heads / Cabs' : amps[0].type === 'amp' ? 'Head / Cab' : 'Amp', items: amps });
    if (ob.length && obAfter) sec.push({ key: 'outboard', label: 'Outboard', items: ob });
    if (post.length) sec.push({ key: 'post', label: 'Pedals · post', items: post });
    if (tools.length) sec.push({ key: 'tools', label: 'golem', items: tools });
    return sec;
  }

  // ---------- floors (from above) and their back walls (from the front) ----------
  const grain = (id, fq, a, b) => `<filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="${fq}" numOctaves="2" seed="9"/>
    <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 ${a} ${b}"/></filter>`;
  function boards(id, W, H, R, ph, tones, fq) {
    let s = '';
    for (let y = -ph / 2, row = 0; y < H; y += ph, row++) {
      let x = -((row * 137) % 260);
      while (x < W) {
        const len = 260 + R() * 320;
        s += `<rect x="${x.toFixed(0)}" y="${y.toFixed(0)}" width="${len.toFixed(0)}" height="${ph - 1.5}" fill="${tones[Math.floor(R() * tones.length)]}"/>`;
        x += len + 1.5;
      }
    }
    return `<defs>${grain(id, fq, .9, -.25)}</defs><rect width="${W}" height="${H}" fill="${shade(tones[0], .45)}"/>${s}<rect width="${W}" height="${H}" filter="url(#${id}-grain)"/>`;
  }
  // a velvet curtain in four tones (shadow, light, mid, deep shadow)
  const curtain = (id, W, wy, c) => `<defs><linearGradient id="${id}-fold" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="${c[0]}"/><stop offset=".35" stop-color="${c[1]}"/><stop offset=".6" stop-color="${c[2]}"/><stop offset="1" stop-color="${c[3]}"/></linearGradient>
    <pattern id="${id}-curtain" width="74" height="10" patternUnits="userSpaceOnUse"><rect width="74" height="10" fill="url(#${id}-fold)"/></pattern></defs><rect width="${W}" height="${wy}" fill="url(#${id}-curtain)"/>`;
  const bricks = (W, wy, mortar, tones, R) => { let b = ''; for (let y = 0, r = 0; y < wy; y += 30, r++) for (let x = -(r % 2) * 43; x < W; x += 86) b += `<rect x="${x + 1.5}" y="${y + 1.5}" width="83" height="27" fill="${tones[Math.floor(R() * tones.length)]}"/>`; return `<rect width="${W}" height="${wy}" fill="${mortar}"/>${b}`; };
  const FLOORS = {
    // a stage: dark boards, a red curtain behind
    stage: {
      floor: (id, W, H, R) => boards(id, W, H, R, 46, ['#2b221b', '#251d17', '#30261e'], '.003 .22'),
      wall: (id, W, wy) => curtain(id, W, wy, ['#1c0d0f', '#4a1a1e', '#2a1114', '#14090a']),
      edge: '#140f0c',
    },
    // a persian rug on a dark floor, wood panelling behind
    rug: {
      floor: (id, W, H) => {
        const m = Math.min(W, H) * .05, rw = W - m * 2, rh = H - m * 2;
        return `<defs><pattern id="${id}-field" width="56" height="56" patternUnits="userSpaceOnUse"><rect width="56" height="56" fill="#6e1e1a"/>
          <path d="M28 6 50 28 28 50 6 28z" fill="#8b2a22"/><path d="M28 14 42 28 28 42 14 28z" fill="#1f2a44"/><path d="M28 21 35 28 28 35 21 28z" fill="#d9b779"/>
          <circle cx="0" cy="0" r="5" fill="#d9b779" opacity=".8"/><circle cx="56" cy="0" r="5" fill="#d9b779" opacity=".8"/><circle cx="0" cy="56" r="5" fill="#d9b779" opacity=".8"/><circle cx="56" cy="56" r="5" fill="#d9b779" opacity=".8"/></pattern>
          <pattern id="${id}-border" width="22" height="22" patternUnits="userSpaceOnUse"><rect width="22" height="22" fill="#1f2a44"/><path d="M0 11 11 0 22 11 11 22z" fill="none" stroke="#d9b779" stroke-width="2"/><circle cx="11" cy="11" r="2.5" fill="#b8402f"/></pattern>
          <filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="1.3" numOctaves="2" seed="4"/><feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1.1 -.42"/></filter></defs>
          <rect width="${W}" height="${H}" fill="#2a2420"/><rect x="${f(m)}" y="${f(m)}" width="${f(rw)}" height="${f(rh)}" fill="url(#${id}-border)"/>
          <rect x="${f(m + 22)}" y="${f(m + 22)}" width="${f(rw - 44)}" height="${f(rh - 44)}" fill="#d9b779"/><rect x="${f(m + 26)}" y="${f(m + 26)}" width="${f(rw - 52)}" height="${f(rh - 52)}" fill="url(#${id}-field)"/>
          <rect x="${f(m)}" y="${f(m)}" width="${f(rw)}" height="${f(rh)}" filter="url(#${id}-grain)"/><rect width="${W}" height="${H}" fill="#000" opacity=".28"/>`;
      },
      wall: (id, W, wy) => `<defs><pattern id="${id}-panel" width="150" height="20" patternUnits="userSpaceOnUse"><rect width="150" height="20" fill="#3a2a1c"/><rect width="3" height="20" fill="#1c130c"/><rect x="3" width="2" height="20" fill="#57412c"/></pattern></defs>
        <rect width="${W}" height="${wy}" fill="url(#${id}-panel)"/>`,
      edge: '#3c1512',
    },
    // a rehearsal room: raw concrete, painted blocks
    concrete: {
      floor: (id, W, H, R) => {
        let s = '';
        for (let i = 0; i < 7; i++) {
          let x = R() * W, y = R() * H, d = `M${f(x)} ${f(y)}`;
          for (let k = 0; k < 6; k++) { x += (R() - .5) * 150; y += (R() - .3) * 70; d += `L${f(x)} ${f(y)}`; }
          s += `<path d="${d}" fill="none" stroke="#000" stroke-opacity=".28" stroke-width="1.2"/>`;
        }
        for (let i = 0; i < 5; i++) s += `<ellipse cx="${f(R() * W)}" cy="${f(R() * H)}" rx="${f(60 + R() * 120)}" ry="${f(30 + R() * 70)}" fill="#000" opacity=".10"/>`;
        return `<defs><filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".55" numOctaves="3" seed="3"/><feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .7 -.22"/></filter></defs>
          <rect width="${W}" height="${H}" fill="#3b3d3f"/>${s}<rect width="${W}" height="${H}" filter="url(#${id}-grain)"/><path d="M0 ${f(H * .63)}H${W}M${f(W * .37)} 0V${H}" stroke="#000" stroke-opacity=".35" stroke-width="3"/>`;
      },
      wall: (id, W, wy) => { let b = ''; for (let y = 0, r = 0; y < wy; y += 44, r++) for (let x = -(r % 2) * 60; x < W; x += 120) b += `<rect x="${x + 1}" y="${y + 1}" width="118" height="42" fill="#34373b"/>`; return `<rect width="${W}" height="${wy}" fill="#1b1c1e"/>${b}`; },
      edge: '#1b1c1e',
    },
    // a flight-case floor: aluminium tread plate, road cases stacked behind
    plate: {
      floor: (id, W, H) => `<defs><pattern id="${id}-tread" width="44" height="44" patternUnits="userSpaceOnUse"><rect width="44" height="44" fill="#4a4e53"/>
          <g fill="#6f757c"><rect x="4" y="9" width="15" height="4" rx="2" transform="rotate(45 11 11)"/><rect x="26" y="31" width="15" height="4" rx="2" transform="rotate(45 33 33)"/>
          <rect x="26" y="9" width="15" height="4" rx="2" transform="rotate(-45 33 11)"/><rect x="4" y="31" width="15" height="4" rx="2" transform="rotate(-45 11 33)"/></g></pattern>${grain(id, '.9', .5, -.2)}</defs>
        <rect width="${W}" height="${H}" fill="url(#${id}-tread)"/><rect width="${W}" height="${H}" filter="url(#${id}-grain)"/><rect width="${W}" height="${H}" fill="#000" opacity=".3"/>`,
      wall: (id, W, wy) => { let b = ''; for (let x = -40; x < W; x += 330) b += `<rect x="${x}" y="0" width="318" height="${wy}" fill="#1f2226"/><rect x="${x + 6}" y="6" width="306" height="${wy - 12}" fill="none" stroke="#7b838b" stroke-width="5"/><rect x="${x + 136}" y="${f(wy * .42)}" width="46" height="30" rx="4" fill="#0c0d0e" stroke="#7b838b" stroke-width="3"/>`; return `<rect width="${W}" height="${wy}" fill="#0e0f11"/>${b}`; },
      edge: '#2a2d31',
    },
    // a studio: pale parquet, acoustic panels
    parquet: {
      floor: (id, W, H, R) => boards(id, W, H, R, 40, ['#8a6a48', '#7d5f40', '#927250', '#84643f'], '.004 .3') + `<rect width="${W}" height="${H}" fill="#000" opacity=".22"/>`,
      wall: (id, W, wy) => { let b = ''; for (let x = 30, i = 0; x < W; x += 210, i++) b += `<rect x="${x}" y="${f(wy * .12)}" width="170" height="${f(wy * .62)}" rx="4" fill="${i % 2 ? '#5b6770' : '#6b5a4a'}"/><rect x="${x}" y="${f(wy * .12)}" width="170" height="${f(wy * .62)}" rx="4" fill="url(#gp-weave)" opacity=".5"/>`; return `<rect width="${W}" height="${wy}" fill="#3d3a36"/>${b}`; },
      edge: '#5a4530',
    },
    // a diner floor: black and white tiles, a red curtain
    checker: {
      floor: (id, W, H) => `<defs><pattern id="${id}-tiles" width="120" height="120" patternUnits="userSpaceOnUse"><rect width="120" height="120" fill="#d8d2c4"/><rect width="60" height="60" fill="#161514"/><rect x="60" y="60" width="60" height="60" fill="#161514"/></pattern>${grain(id, '.7', .5, -.2)}</defs>
        <rect width="${W}" height="${H}" fill="url(#${id}-tiles)"/><rect width="${W}" height="${H}" filter="url(#${id}-grain)"/><rect width="${W}" height="${H}" fill="#000" opacity=".34"/>`,
      wall: (id, W, wy) => FLOORS.stage.wall(id, W, wy),
      edge: '#161514',
    },
    // a modern studio: dark carpet, acoustic foam
    carpet: {
      floor: (id, W, H) => `<defs><filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="6"/><feColorMatrix type="matrix" values="0 0 0 0 .5  0 0 0 0 .55  0 0 0 0 .7  0 0 0 .9 -.3"/></filter>
        <pattern id="${id}-tile" width="400" height="400" patternUnits="userSpaceOnUse"><rect width="400" height="400" fill="#23262d"/><rect width="200" height="200" fill="#1f2228"/><rect x="200" y="200" width="200" height="200" fill="#1f2228"/></pattern></defs>
        <rect width="${W}" height="${H}" fill="url(#${id}-tile)"/><rect width="${W}" height="${H}" filter="url(#${id}-grain)" opacity=".55"/>`,
      wall: (id, W, wy) => `<defs><pattern id="${id}-foam" width="64" height="64" patternUnits="userSpaceOnUse"><rect width="64" height="64" fill="#1b1d21"/>
        <path d="M0 0L32 32L64 0z" fill="#2c2f35"/><path d="M0 0L32 32L0 64z" fill="#23262b"/><path d="M64 0L32 32L64 64z" fill="#15171a"/><path d="M0 64L32 32L64 64z" fill="#0f1012"/></pattern></defs><rect width="${W}" height="${wy}" fill="url(#${id}-foam)"/>`,
      edge: '#1f2228',
    },
    // a bar: worn wide boards, a brick wall
    bar: {
      floor: (id, W, H, R) => boards(id, W, H, R, 62, ['#4a3020', '#55381f', '#3f2a1c', '#5c3f26', '#463021'], '.004 .16') + `<rect width="${W}" height="${H}" fill="#000" opacity=".18"/>`,
      wall: (id, W, wy, R) => bricks(W, wy, '#2a1d17', ['#6b3526', '#5c2e22', '#74402c', '#4f2a20'], R),
      edge: '#3f2a1c',
    },
    // a jazz club: herringbone parquet, a midnight curtain
    chevron: {
      floor: (id, W, H) => `<defs><pattern id="${id}-herr" width="120" height="60" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="120" height="60" fill="#6f4a2a"/>
        <rect x="1" y="1" width="118" height="28" fill="#8a5f38"/><rect x="1" y="31" width="58" height="28" fill="#7a5230"/><rect x="61" y="31" width="58" height="28" fill="#946a40"/></pattern>${grain(id, '.004 .5', .6, -.2)}</defs>
        <rect width="${W}" height="${H}" fill="url(#${id}-herr)"/><rect width="${W}" height="${H}" filter="url(#${id}-grain)"/><rect width="${W}" height="${H}" fill="#000" opacity=".3"/>`,
      wall: (id, W, wy) => curtain(id, W, wy, ['#0b1220', '#1f3a5c', '#13243c', '#070b14']),
      edge: '#5a3b20',
    },
    // the seventies: an orange shag carpet, wood panelling with stripes
    shag: {
      floor: (id, W, H) => `<defs><filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="turbulence" baseFrequency=".09 .16" numOctaves="3" seed="12"/><feColorMatrix type="matrix" values="0 0 0 0 .25  0 0 0 0 .08  0 0 0 0 0  0 0 0 1.4 -.35"/></filter></defs>
        <rect width="${W}" height="${H}" fill="#c4691f"/><rect width="${W}" height="${H}" filter="url(#${id}-grain)"/><rect width="${W}" height="${H}" fill="#000" opacity=".26"/>`,
      wall: (id, W, wy) => `${FLOORS.rug.wall(id, W, wy)}<rect y="${f(wy * .3)}" width="${W}" height="${f(wy * .07)}" fill="#d98a2b"/><rect y="${f(wy * .37)}" width="${W}" height="${f(wy * .07)}" fill="#a8421c"/><rect y="${f(wy * .44)}" width="${W}" height="${f(wy * .07)}" fill="#e7d3a1"/>`,
      edge: '#8a4514',
    },
    // a synth stage: a dark floor with a lit grid, a night wall with a low sun
    neon: {
      floor: (id, W, H) => `<defs><pattern id="${id}-grid" width="100" height="100" patternUnits="userSpaceOnUse"><rect width="100" height="100" fill="#0d0a1c"/><path d="M0 0H100M0 0V100" stroke="#ff3fd0" stroke-width="5" opacity=".35"/><path d="M0 0H100M0 0V100" stroke="#ff9bef" stroke-width="1.6"/></pattern>
        <radialGradient id="${id}-glow" cx=".5" cy=".5" r=".7"><stop offset="0" stop-color="#35e0ff" stop-opacity=".2"/><stop offset="1" stop-color="#35e0ff" stop-opacity="0"/></radialGradient></defs>
        <rect width="${W}" height="${H}" fill="url(#${id}-grid)"/><rect width="${W}" height="${H}" fill="url(#${id}-glow)"/>`,
      wall: (id, W, wy) => `<defs><linearGradient id="${id}-night" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#07061a"/><stop offset=".7" stop-color="#2a1150"/><stop offset="1" stop-color="#b0308f"/></linearGradient>
        <linearGradient id="${id}-sun" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ffd23c"/><stop offset="1" stop-color="#ff3f8f"/></linearGradient></defs>
        <rect width="${W}" height="${wy}" fill="url(#${id}-night)"/><circle cx="${f(W / 2)}" cy="${f(wy * .78)}" r="${f(Math.min(W * .3, wy * .5))}" fill="url(#${id}-sun)" opacity=".8"/>
        ${[.56, .66, .75, .83, .9].map((t, i) => `<rect y="${f(wy * t)}" width="${W}" height="${f(wy * (.012 + i * .006))}" fill="#160a30"/>`).join('')}`,
      edge: '#0d0a1c',
    },
  };
  // a floor for a genre (free text: "Thrash Metal", "indie-pop"); the first family that matches wins
  const GENRES = [
    ['plate', /metal|djent|thrash|death|indus|core\b/],
    ['concrete', /punk|grunge|garage|stoner|doom|sludge|noise|emo|shoegaze/],
    ['neon', /synth|electro|edm|techno|house|wave\b|cyber|hyperpop|trance|drum ?(and|&|n) ?bass|dubstep/],
    ['checker', /rockabilly|rock ?'?n'? ?roll|ska|surf|doo[- ]?wop/],
    ['shag', /funk|soul|disco|psych|motown|afrobeat|reggae|r ?(&|n) ?b|70s/],
    ['chevron', /jazz|bossa|swing|fusion|lounge|bebop|latin|manouche/],
    ['bar', /blues|country|americana|southern|honky|bluegrass|roots|outlaw|rhythm/],
    ['rug', /classic|folk|acoustic|singer|60s|celtic|unplugged/],
    ['carpet', /prog|modern|ambient|post[- ]?rock|math|worship|hip[- ]?hop|rap|trap|studio|session|cinematic/],
    ['parquet', /pop|indie|alternative|gospel/],
  ];
  function floorFor(genre) {
    const g = String(genre || '').toLowerCase();
    const hit = GENRES.find(([, re]) => re.test(g));
    return hit ? hit[0] : 'stage';
  }
  const floorOf = name => FLOORS[name] || FLOORS.stage;

  // ---------- the board from above, tape, cables ----------
  function board(id, x, y, w, h) {
    const n = Math.max(3, Math.round(h / 78)), gap = 13, rh = (h - gap * (n - 1)) / n;
    let rails = '';
    for (let i = 0; i < n; i++) {
      const ry = y + i * (rh + gap);
      rails += `<rect x="${f(x)}" y="${f(ry)}" width="${f(w)}" height="${f(rh)}" rx="5" fill="url(#${id}-rail)"/><rect x="${f(x)}" y="${f(ry)}" width="${f(w)}" height="${f(rh)}" rx="5" fill="url(#gp-brush-lines)" opacity=".5"/>
        <rect x="${f(x + 4)}" y="${f(ry + 1)}" width="${f(w - 8)}" height="1.4" fill="#fff" opacity=".13"/>`;
    }
    const cap = cx => `<rect x="${f(cx)}" y="${f(y - 5)}" width="26" height="${f(h + 10)}" rx="7" fill="#1b1d20"/><rect x="${f(cx + 3)}" y="${f(y - 2)}" width="2" height="${f(h + 4)}" fill="#fff" opacity=".08"/>`;
    return `<defs><linearGradient id="${id}-rail" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#3d4146"/><stop offset="1" stop-color="#25282c"/></linearGradient></defs>
      <rect x="${f(x - 6)}" y="${f(y + 10)}" width="${f(w + 12)}" height="${f(h + 14)}" rx="14" fill="#000" opacity=".62" filter="url(#${id}-ash)"/>
      <rect x="${f(x)}" y="${f(y)}" width="${f(w)}" height="${f(h)}" rx="8" fill="#060606" opacity=".8"/>${rails}${cap(x - 8)}${cap(x + w - 18)}`;
  }
  // a strip of gaffer tape with a marker's lettering, centred on (0, 0); k scales it
  const tape = (x, y, txt, rot, k, muted) => `<g transform="translate(${f(x)} ${f(y)}) rotate(${rot}) scale(${f(k || 1)})"><rect x="${-txt.length * 4.6 - 9}" y="-10" width="${txt.length * 9.2 + 18}" height="20" rx="1.5" fill="#e8e2c8" opacity="${muted ? .6 : .92}"/>
    <text y="5" text-anchor="middle" font-family="${P().FONT.nam}" font-size="14" font-weight="800" letter-spacing="1.4" fill="${muted ? '#7a6f62' : '#2a2018'}">${P().esc(txt)}</text></g>`;
  const branchAttrs = bi => `class="gr-branch${bi.mute ? ' is-muted' : ''}" data-split="${bi.split}" data-branch="${P().esc(bi.id)}" data-b="${bi.b}" style="cursor:pointer"`;
  function plug(x, y, dir, k) {
    const s = k || 1;
    return `<g transform="translate(${f(x)} ${f(y)}) scale(${f(s)})"><rect x="${dir > 0 ? -11 : 1}" y="-3.4" width="10" height="6.8" rx="1.2" fill="url(#gp-chrome)"/><rect x="${dir > 0 ? -19 : 9}" y="-5" width="10" height="10" rx="2.5" fill="#1b1b1b"/></g>`;
  }
  // a braided cable through way points (Catmull-Rom as cubic Béziers)
  function wire(id, pts, color, wdt) {
    let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2, t = .2;
      d += `C${f(p1[0] + (p2[0] - p0[0]) * t)} ${f(p1[1] + (p2[1] - p0[1]) * t)},${f(p2[0] - (p3[0] - p1[0]) * t)} ${f(p2[1] - (p3[1] - p1[1]) * t)},${f(p2[0])} ${f(p2[1])}`;
    }
    return `<g class="gr-cable" fill="none" stroke-linecap="round"><path d="${d}" stroke="#000" stroke-opacity=".5" stroke-width="${f(wdt + 2)}" transform="translate(3 6)" filter="url(#${id}-blur)"/>
      <path d="${d}" stroke="${shade(color, .55)}" stroke-width="${f(wdt)}"/><path d="${d}" stroke="${color}" stroke-width="${f(wdt * .6)}" stroke-dasharray="5 3"/>
      <path d="${d}" stroke="#fff" stroke-opacity=".16" stroke-width="1.2" transform="translate(-.8 -1.4)"/></g>`;
  }

  // ---------- pedals, from above: every unit at the same scale, as large as the frame allows ----------
  function drawingOf(it, o) {
    if (isOutboard(it) && o.outboard === 'board') return P().namModule({ label: it.label, title: it.title, on: it.on !== false, kind: it.kind, format: it.type === 'ir-fx' ? 'ir' : it.format, program: it.program });
    return P().pedalFor(it);
  }
  function pedals(id, sec, W, H, o) {
    const col = sec.key === 'post' ? POST : sec.key === 'tools' ? TOOLS : PRE;
    const MX = Math.min(150, W * .13), MY = Math.min(110, H * .12), PADX = Math.min(70, W * .07), PADY = 22, RG = 30;
    const all = sec.items.map(it => { const svg = drawingOf(it, o), fp = P().footprint(svg); return { it, svg, uw: fp.w / 124, uh: fp.h / 124 }; });
    const lim = W - MX * 2 - PADX * 2, N = all.length, total = all.reduce((t, n) => t + n.uw, 0);
    let rows = [all], PW = 0;
    for (let rn = 1; rn <= Math.min(4, N); rn++) {    // rows of even width; keep the count that gives the largest pedals
      const chunks = [[]];
      let acc = 0;
      all.forEach(n => { if (chunks[chunks.length - 1].length && chunks.length < rn && acc + n.uw / 2 > total * chunks.length / rn) chunks.push([]); chunks[chunks.length - 1].push(n); acc += n.uw; });
      const wide = Math.max(...chunks.map(c => c.reduce((t, n) => t + n.uw, 0) + .36 * (c.length - 1)));
      const tall = chunks.reduce((t, c) => t + Math.max(...c.map(n => n.uh)), 0);
      const pw = Math.min(300, lim / wide, (H - MY * 2 - PADY * 2 - (chunks.length - 1) * RG) / tall);
      if (pw > PW * 1.04) { PW = pw; rows = chunks; }
    }
    const GAP = PW * .36, k = Math.max(.8, PW / 124);
    rows.forEach(r => r.forEach(n => { n.w = PW * n.uw; n.h = PW * n.uh; }));
    const rowHs = rows.map(r => Math.max(...r.map(n => n.h))), rowW = r => r.reduce((s, n) => s + n.w, 0) + GAP * (r.length - 1);
    const bw = Math.max(...rows.map(rowW)) + PADX * 2, bh = rowHs.reduce((t, h) => t + h, 0) + (rows.length - 1) * RG + PADY * 2;
    const bx = (W - bw) / 2, by = (H - bh) / 2, sw = Math.max(4, PW * .05);
    let draw = '', under = '', plugs = '', tapes = '', prev = null;
    rows.forEach((r, ri) => {
      let x = bx + (bw - rowW(r)) / 2;
      const rowH = rowHs[ri], y0 = by + PADY + rowHs.slice(0, ri).reduce((t, h) => t + h + RG, 0);
      r.forEach(n => {
        const pl = place(n.svg, x, y0 + rowH - n.h, n.w, n.it.idx), sc = pl.h / pl.vb[3];
        const jy = pl.y + (/gp-hw/.test(n.svg) ? pl.h * .62 : (40 - pl.vb[1]) * sc);
        n.in = [x + 2, jy]; n.out = [x + n.w - 2, jy];
        let d = pl.svg;
        if (o.detail === 'badge' && /class="gp-pedal/.test(n.svg)) {   // the card: the block's glyph, large, over its pedal
          const b = P().blockByType(n.it.type) || {}, cx = x + n.w / 2, cy = pl.y + pl.h * .36, r = n.w * .36;
          d += `<g class="gr-badge" pointer-events="none"><circle cx="${f(cx)}" cy="${f(cy)}" r="${f(r)}" fill="#0b0b0d" opacity="${n.it.on === false ? .5 : .78}"/><circle cx="${f(cx)}" cy="${f(cy)}" r="${f(r)}" fill="none" stroke="#fff" stroke-opacity=".3" stroke-width="${f(r * .06)}"/>
            ${P().glyphAt(b.glyph || n.it.type, cx, cy, r * 1.35, n.it.on === false ? '#8d949b' : '#fff', 2.1)}</g>`;
        }
        draw += n.it.muted ? `<g class="gr-muted" opacity=".5">${d}</g>` : d;
        if (n.it.branchInfo) tapes += `<g ${branchAttrs(n.it.branchInfo)}>${tape(x + n.w / 2, pl.y + pl.h + 6 * k, n.it.branch + (n.it.muted ? ' · MUTED' : ''), -2, k * .8, n.it.muted)}</g>`;
        if (prev) {
          const a = prev.out, b = n.in;
          under += b[0] > a[0] ? wire(id, [[a[0] + 16 * k, a[1]], [(a[0] + b[0]) / 2, Math.abs(a[1] - b[1]) > PW * .4 ? (a[1] + b[1]) / 2 : Math.max(a[1], b[1]) + PW * .26], [b[0] - 16 * k, b[1]]], col, sw)
            : wire(id, [[a[0] + 16 * k, a[1]], [a[0] + 60, y0 - RG * .6], [(a[0] + b[0]) / 2, y0 - RG / 2], [b[0] - 60, y0 - RG * .4], [b[0] - 16 * k, b[1]]], col, sw);
          plugs += plug(a[0], a[1], -1, k) + plug(b[0], b[1], 1, k);
        }
        prev = n; x += n.w + GAP;
      });
    });
    const p = rows[0][0].in, q = prev.out;
    under += wire(id, [[-20, p[1] + H * .2], [bx - MX * .7, p[1] + H * .16], [bx - 30, p[1] + 50], [p[0] - 16 * k, p[1]]], col, sw + 1)
      + wire(id, [[q[0] + 16 * k, q[1]], [bx + bw + 30, q[1] + 40], [bx + bw + MX * .7, q[1] + H * .14], [W + 20, q[1] + H * .18]], col, sw + 1);
    plugs += plug(p[0], p[1], 1, k) + plug(q[0], q[1], -1, k);
    return `${floorOf(o.floor).floor(id, W, H, o.R)}${board(id, bx, by, bw, bh)}${under}${draw}${plugs}${tapes}`;
  }

  // ---------- what stands: the back wall with a pool of light, the floor's front edge ----------
  function room(id, W, H, o, FL) {
    const F = floorOf(o.floor);
    return `${F.wall(id, W, FL, o.R)}<defs><linearGradient id="${id}-wsh" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".7"/><stop offset=".7" stop-color="#000" stop-opacity=".2"/><stop offset="1" stop-color="#000" stop-opacity=".45"/></linearGradient>
      <radialGradient id="${id}-pool" cx=".5" cy=".62" r=".55"><stop offset="0" stop-color="#ffe2b0" stop-opacity=".26"/><stop offset="1" stop-color="#ffe2b0" stop-opacity="0"/></radialGradient></defs>
      <rect width="${W}" height="${f(FL)}" fill="url(#${id}-wsh)"/><rect width="${W}" height="${f(FL)}" fill="url(#${id}-pool)"/>
      <rect y="${f(FL - 9)}" width="${W}" height="9" fill="#0c0b0a"/>
      <rect y="${f(FL)}" width="${W}" height="${f(H - FL)}" fill="${F.edge}"/><rect y="${f(FL)}" width="${W}" height="${f(H - FL)}" fill="#000" opacity=".45"/><rect y="${f(FL)}" width="${W}" height="3" fill="#fff" opacity=".1"/>`;
  }
  function amps(id, sec, W, H, o) {
    const n = sec.items.length, FL = H * .86, AG = Math.min(70, W * .06);
    const svgs = sec.items.map(a => P().pedalFor(a)), ratio = Math.max(...svgs.map(s => place(s, 0, 0, 100).h / 100));
    const AW = Math.min((W - W * .16 - AG * (n - 1)) / n, (FL - H * .07) / ratio, W * .5), tot = n * AW + (n - 1) * AG;
    let s = room(id, W, H, o, FL);
    sec.items.forEach((a, i) => {
      const x = (W - tot) / 2 + i * (AW + AG), pl = place(svgs[i], x, 0, AW), y = FL + AW * .06 - pl.h, d = place(svgs[i], x, y, AW, a.idx).svg;
      s += `<ellipse cx="${f(x + AW / 2)}" cy="${f(FL + AW * .05)}" rx="${f(AW * .58)}" ry="${f(AW * .07)}" fill="#000" opacity=".75" filter="url(#${id}-ash)"/>${a.muted ? `<g class="gr-muted" opacity=".45">${d}</g>` : d}`;
      if (a.branchInfo) s += `<g ${branchAttrs(a.branchInfo)}>${tape(x + AW / 2, FL + (H - FL) * .6, a.branch + (a.muted ? ' · MUTED' : ''), -2, Math.max(1.2, H / 420), a.muted)}</g>`;
    });
    return s;
  }
  function outboard(id, sec, W, H, o) {
    const FL = H * .86;
    const mk = it => P().namRack({ label: it.label, title: it.title, on: it.on !== false, kind: it.kind, format: it.type === 'ir-fx' ? 'ir' : it.format, program: it.program, setting: it.setting });
    let UW = Math.min(W - W * .2, 860);
    const hs = w => sec.items.reduce((t, it) => t + place(mk(it), 0, 0, w).h - 2, 0);
    if (hs(UW) > FL - H * .2) UW *= (FL - H * .2) / hs(UW);
    const pad = UW * .045, ch = hs(UW) + pad * 2.4, cw = UW + pad * 2, x = (W - cw) / 2, y = FL + 10 - ch;
    let yy = y + pad * 1.2, units = '';
    sec.items.forEach(it => { const pl = place(mk(it), x + pad, yy, UW, it.idx); units += it.muted ? `<g class="gr-muted" opacity=".5">${pl.svg}</g>` : pl.svg; yy += pl.h - 2; });
    return `${room(id, W, H, o, FL)}<ellipse cx="${f(W / 2)}" cy="${f(FL + 10)}" rx="${f(cw * .56)}" ry="${f(cw * .035)}" fill="#000" opacity=".75" filter="url(#${id}-ash)"/>
      <rect x="${f(x)}" y="${f(y)}" width="${f(cw)}" height="${f(ch)}" rx="8" fill="#17181a"/><rect x="${f(x)}" y="${f(y)}" width="${f(cw)}" height="${f(ch)}" rx="8" fill="url(#gp-tolex)" opacity=".7"/>
      <rect x="${f(x + 3)}" y="${f(y + 3)}" width="${f(cw - 6)}" height="${f(ch - 6)}" rx="6" fill="none" stroke="url(#gp-chrome)" stroke-width="${f(pad * .22)}"/>
      <rect x="${f(x + pad * .8)}" y="${f(y + pad)}" width="${f(cw - pad * 1.6)}" height="${f(ch - pad * 2)}" fill="#050505"/>${units}
      ${[[0, 0], [1, 0], [0, 1], [1, 1]].map(([cx, cy]) => `<circle cx="${f(x + pad * .5 + cx * (cw - pad))}" cy="${f(y + pad * .5 + cy * (ch - pad))}" r="${f(pad * .42)}" fill="url(#gp-chrome)"/>`).join('')}`;
  }

  // ---------- the instrument of a keys, pads or drums lane, from above: the keyboard, the pads, the kit ----------
  const pretty = s => String(s || '').replace(/^.*\//, '').replace(/\.[a-z0-9]+$/i, '').replace(/^(drums|pads|kit)-/, '').replace(/[_-]+/g, ' ').trim().replace(/\b\w/g, c => c.toUpperCase());
  // An item is drawn from its sound: `params` as golem writes them (kit, preset, the organ's drawbars), and what
  // the host knows better: title, kitType (KIT_TYPES), style (a synth preset's), family (an e-piano's), macros, pads.
  function instrumentSvg(it) {
    const p = it.params || {}, on = it.on !== false, title = it.title || it.label;
    if (it.type === 'drumkit') {
      const name = title || pretty(p.kit) || 'Drum kit';
      const type = it.kitType || P().KIT_TYPES.find(k => new RegExp(k.slice(0, 5), 'i').test(`${p.kit} ${name}`)) || 'rock';
      return P().drumKit({ type, title: name, on });
    }
    if (it.type === 'pads') return P().padKit({ title: title || pretty(p.kit) || 'Pads', pads: it.pads, on });
    if (it.type === 'organ') return P().keysUnit({ kind: 'organ', title, on, drawbars: it.drawbars || ['db16', 'db513', 'db8', 'db4', 'db223', 'db2', 'db135', 'db113', 'db1'].map(k => Math.max(0, Math.min(8, Math.round(+p[k] || 0)))).join('') });
    if (it.type === 'piano') return P().keysUnit({ kind: 'piano', title: title || 'Piano', on });
    if (it.type === 'ep') return P().keysUnit({ kind: 'epiano', title: title || 'E. Piano', family: it.family || P().keysFamily(title || ''), on });
    const name = title || pretty(p.preset) || (P().blockByType(it.type) || {}).name || it.type;
    const style = it.style || Object.keys(P().KEYS_STYLE_HUE).find(k => new RegExp(`\\b${k}`, 'i').test(name)) || '';
    return P().keysUnit({ kind: 'synth', title: name, style, macros: it.macros, on });
  }
  function instruments(id, sec, W, H, o) {
    const svgs = sec.items.map(instrumentSvg), n = svgs.length;
    if (n === 1 && /<image /.test(svgs[0])) {          // a drum kit is a photograph: it fills the frame
      const d = place(svgs[0], 0, 0, W, sec.items[0].idx).svg.replace(/ height="[\d.]+"/, ` height="${H}"`).replace(/^<svg /, '<svg preserveAspectRatio="xMidYMid slice" ');
      return `<rect width="${W}" height="${H}" fill="#0d0b09"/>${sec.items[0].muted ? `<g class="gr-muted" opacity=".5">${d}</g>` : d}`;
    }
    const G = Math.min(60, W * .05), ratio = Math.max(...svgs.map(v => place(v, 0, 0, 100).h / 100));
    const rows = n > 1 && W / H < 1.2 ? n : 1, cols = Math.ceil(n / rows);      // a narrow band stacks them
    const UW = Math.min((W * .86 - G * (cols - 1)) / cols, (H * .8 - G * (rows - 1)) / rows / ratio);
    let s = floorOf(o.floor).floor(id, W, H, o.R);
    svgs.forEach((v, i) => {
      const c = i % cols, r = Math.floor(i / cols), h = place(v, 0, 0, UW).h;
      const x = (W - (cols * UW + (cols - 1) * G)) / 2 + c * (UW + G), y = (H - (rows * UW * ratio + (rows - 1) * G)) / 2 + r * (UW * ratio + G) + (UW * ratio - h) / 2;
      const d = place(v, x, y, UW, sec.items[i].idx).svg;
      s += `<rect x="${f(x + UW * .01)}" y="${f(y + h * .1)}" width="${f(UW * .98)}" height="${f(h)}" rx="10" fill="#000" opacity=".65" filter="url(#${id}-ash)"/>${sec.items[i].muted ? `<g class="gr-muted" opacity=".5">${d}</g>` : d}`;
    });
    return s;
  }

  const inner = (id, sec, W, H, o) => (sec.key === 'amp' ? amps : sec.key === 'outboard' ? outboard : sec.key === 'instrument' ? instruments : pedals)(id, sec, W, H, o);
  const defs = id => `<defs><filter id="${id}-blur" x="-10%" y="-30%" width="120%" height="160%"><feGaussianBlur stdDeviation="2.4"/></filter>
    <filter id="${id}-ash" x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="9"/></filter>
    <radialGradient id="${id}-spot" cx=".5" cy=".55" r=".75"><stop offset="0" stop-color="#ffe9c2" stop-opacity=".14"/><stop offset=".6" stop-color="#ffe9c2" stop-opacity=".03"/><stop offset="1" stop-color="#000" stop-opacity=".6"/></radialGradient></defs>`;
  const sizeAttr = (opts, W, H) => (opts.width ? ` width="${opts.width}" height="${f(opts.width * H / W)}"` : '');

  // one section. opts: floor (FLOORS), seed (number or string), W, H (viewBox, 1600 × 900), width (px),
  // outboard: 'board' when the sections were cut with it (outboard units drawn as modules on the board)
  function render(sec, opts) {
    opts = opts || {};
    if (!sec || !(sec.items || []).length) return '';
    const id = 'gr' + (++count), W = opts.W || 1600, H = opts.H || 900, o = { floor: opts.floor, outboard: opts.outboard, detail: opts.detail, R: rng(seedOf(opts.seed)) };
    return `<svg class="gr-scene gr-${sec.key}" viewBox="0 0 ${W} ${H}"${sizeAttr(opts, W, H)} role="img" aria-label="${P().esc(sec.label)}: ${sec.items.length} block${sec.items.length > 1 ? 's' : ''}">${defs(id)}${inner(id, sec, W, H, o)}
<rect width="${W}" height="${H}" fill="url(#${id}-spot)" pointer-events="none"/></svg>`;
  }

  // the fixed picture of a rig: its sections as slanted bands of one 16:9 image, the amp band the widest.
  // golem's own devices (the 'tools' section) are not part of a sound: they stay out of it.
  function card(secs, opts) {
    opts = opts || {};
    const list = (secs || []).filter(s => s.key !== 'tools' && (s.items || []).length);
    const W = 1600, H = 900, cid = 'grc' + (++count);
    if (!list.length) return '';
    const SL = list.length > 1 ? 46 : 0, seed = seedOf(opts.seed);
    const wt = s => (s.key === 'instrument' ? 1.6 : s.key === 'amp' ? 1.15 + .2 * Math.min(2, s.items.length) : s.key === 'outboard' ? .95 : Math.min(1.25, .7 + s.items.length * .11));
    const tw = list.reduce((t, s) => t + wt(s), 0);
    let x = 0, out = '', lines = '';
    list.forEach((s, i) => {
      const w = W * wt(s) / tw, id = 'gr' + (++count), bwd = w + SL * 2, o = { floor: opts.floor, outboard: opts.outboard, detail: opts.detail || 'badge', R: rng(seed + i) };
      const last = i === list.length - 1, x0 = i ? x + SL : 0, x1 = last ? W : x + w + SL, x2 = last ? W : x + w - SL, x3 = i ? x - SL : 0;
      out += `<clipPath id="${cid}-c${i}"><polygon points="${f(x0)},0 ${f(x1)},0 ${f(x2)},${H} ${f(x3)},${H}"/></clipPath>
<g clip-path="url(#${cid}-c${i})"><svg x="${f(x - SL)}" y="0" width="${f(bwd)}" height="${H}" viewBox="0 0 ${f(bwd)} ${H}">${defs(id)}${inner(id, s, bwd, H, o)}<rect width="${f(bwd)}" height="${H}" fill="url(#${id}-spot)"/></svg></g>`;
      if (i) lines += `<path d="M${f(x + SL)} 0L${f(x - SL)} ${H}" stroke="#000" stroke-opacity=".7" stroke-width="16"/><path d="M${f(x + SL)} 0L${f(x - SL)} ${H}" stroke="#ffd23c" stroke-width="5"/>`;
      x += w;
    });
    return `<svg class="gr-scene gr-card" viewBox="0 0 ${W} ${H}"${sizeAttr(opts, W, H)} role="img" aria-label="rig: ${list.map(s => P().esc(s.label)).join(', ')}">${out}${lines}</svg>`;
  }

  // ---------- a preset: several lanes (a band) ----------
  const needStage = fn => { if (!root.GolemStage || !root.GolemStage.fromLane) throw new Error(`GolemRig.${fn} needs golem-stage.js (GolemStage.fromLane)`); return root.GolemStage; };
  // one golem lane -> its sections. state: a lane state, the id or name of one of lane.states, or nothing (the first)
  const fromLane = (lane, state, opts) => sections(needStage('fromLane').fromLane(lane, state), opts);
  // golem's lanes -> [{id, name, role, sections}]. opts.states: {lane id: state} to draw other states than the first
  function preset(lanes, opts) {
    opts = opts || {};
    return (lanes || []).map(l => (l && l.sections ? l : { id: l.id, name: l.name, role: l.role, sections: fromLane(l, (opts.states || {})[l.id], opts) }));
  }
  // what stands for a lane in a group picture: its instrument, else its amp, else its pedals
  const heroOf = secs => secs.find(s => s.key === 'instrument') || secs.find(s => s.key === 'amp') || secs.find(s => s.key !== 'tools');
  // the fixed picture of a preset: one cell per lane (its instrument, its amp or its board), the lane's name
  // on a strip of tape. lanes: golem's lanes or preset()'s result. One lane: that lane's own card.
  function presetCard(lanes, opts) {
    opts = opts || {};
    const list = preset(lanes, opts).map(l => ({ lane: l, hero: heroOf(l.sections || []) })).filter(x => x.hero && x.hero.items.length);
    if (!list.length) return '';
    if (list.length === 1) return card(list[0].lane.sections, opts);
    const W = 1600, H = 900, n = list.length, cols = n <= 3 ? n : n === 4 ? 2 : 3, rows = Math.ceil(n / cols), seed = seedOf(opts.seed);
    let out = '', lines = '';
    for (let r = 0, i = 0; r < rows; r++) {
      const inRow = Math.min(cols, n - r * cols), cw = W / inRow, ch = H / rows;
      for (let c = 0; c < inRow; c++, i++) {
        const { lane, hero } = list[i], id = 'gr' + (++count), o = { floor: opts.floor, outboard: opts.outboard, detail: opts.detail || 'badge', R: rng(seed + i) };
        out += `<svg x="${f(c * cw)}" y="${f(r * ch)}" width="${f(cw)}" height="${f(ch)}" viewBox="0 0 ${f(cw)} ${f(ch)}" data-lane="${P().esc(lane.id || '')}">${defs(id)}${inner(id, hero, cw, ch, o)}<rect width="${f(cw)}" height="${f(ch)}" fill="url(#${id}-spot)"/>
          ${lane.name ? (k => tape(18 + (String(lane.name).length * 4.6 + 9) * k, 14 + 10 * k, String(lane.name).toUpperCase(), 0, k))(Math.max(1.5, ch / 300)) : ''}</svg>`;
        if (c) lines += `<path d="M${f(c * cw)} ${f(r * ch)}V${f((r + 1) * ch)}" stroke="#000" stroke-opacity=".7" stroke-width="14"/><path d="M${f(c * cw)} ${f(r * ch)}V${f((r + 1) * ch)}" stroke="#ffd23c" stroke-width="5"/>`;
      }
      if (r) lines += `<path d="M0 ${f(r * ch)}H${W}" stroke="#000" stroke-opacity=".7" stroke-width="14"/><path d="M0 ${f(r * ch)}H${W}" stroke="#ffd23c" stroke-width="5"/>`;
    }
    return `<svg class="gr-scene gr-card gr-preset" viewBox="0 0 ${W} ${H}"${sizeAttr(opts, W, H)} role="img" aria-label="preset: ${list.map(x => P().esc(x.lane.name || x.hero.label)).join(', ')}">${out}${lines}</svg>`;
  }

  // a drawing as a file: the namespace, golem-pedals' shared defs and (fontsCss: a stylesheet URL) the fonts.
  // What render() and card() return is meant for a page that already called GolemPedals.defs().
  function standalone(svg, opts) {
    opts = opts || {};
    const d = /<defs>([\s\S]*)<\/defs>/.exec(P().defs());
    const style = opts.fontsCss ? `<style>@import url("${P().esc(opts.fontsCss)}");</style>` : '';
    return String(svg).replace(/^<svg /, '<svg xmlns="http://www.w3.org/2000/svg" ').replace(/>/, `>${style}<defs>${d ? d[1] : ''}</defs>`);
  }

  root.GolemRig = { sections, render, card, fromLane, preset, presetCard, floorFor, standalone, FLOORS: Object.keys(FLOORS), GENRES, OUTBOARD };
})(typeof window !== 'undefined' ? window : globalThis);

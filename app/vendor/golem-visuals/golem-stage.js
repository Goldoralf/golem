// SPDX-License-Identifier: GPL-3.0-or-later
// golem stage: one audio lane drawn "for real": the pedals on a stage floor or a rug, patch cables
// between them, the guitar cable coming in, and the amp (or a stage box) at the end.
//
//   GolemStage.render(chain, {floor: 'stage' | 'rug', guitar: true})
//   GolemStage.render(GolemStage.fromGolem(lane.chain, laneState), …)
//
// chain: golem block types in lane order, or {type, on, archetype, family, title, size, form} objects,
// or {split: {mode, gain, branches: [[…], […]] | [{id, mute, items}]}}: a split draws a split box, each
// branch in series on its own lettered strip of tape (two amps stand side by side), and a merge box.
// An `amp-nam` directly followed by a `cab` stands as one stack. Needs golem-pedals.js and its defs().
(function (root) {
  'use strict';
  const P = () => root.GolemPedals;
  let sceneCount = 0;

  // seeded random, so a lane always draws the same floor
  const rng = seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647;

  // nest a pedal's <svg> at (x, y) with width w; returns {svg, h}
  function place(svg, x, y, w, idx) {
    const vb = /viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"/.exec(svg);
    const h = vb ? w * (+vb[4]) / (+vb[3]) : w;
    const out = svg.replace(/^<svg /, `<svg x="${x.toFixed(1)}" y="${y.toFixed(1)}" height="${h.toFixed(1)}" ${idx != null ? `data-idx="${idx}" ` : ''}`)
      .replace(/ width="[\d.]+"/, ` width="${w.toFixed(1)}"`);
    return { svg: out, h, vb: vb ? vb.slice(1).map(Number) : [0, 0, w, w] };
  }
  // a point given in the pedal's own viewBox -> scene coordinates
  const toScene = (pl, x, y, px, py) => [x + (px - pl.vb[0]) * (pl.h / pl.vb[3]), y + (py - pl.vb[1]) * (pl.h / pl.vb[3])];

  function familyOf(type) {
    const b = P().blockByType(type);
    return b ? b.family : 'generic';
  }

  // ---------- floors ----------
  function floorStage(id, W, H, R) {
    let planks = '';
    const ph = 34;
    for (let y = -ph / 2, row = 0; y < H; y += ph, row++) {
      let x = -((row * 137) % 260);
      while (x < W) {
        const len = 220 + R() * 260, t = R();
        const c = t < .33 ? '#2b221b' : t < .66 ? '#251d17' : '#30261e';
        planks += `<rect x="${x.toFixed(0)}" y="${y.toFixed(0)}" width="${len.toFixed(0)}" height="${ph - 1.5}" fill="${c}"/>`;
        x += len + 1.5;
      }
    }
    // tape marks where the player stands, and a set list taped to the floor
    const tapes = [[W * .18, H * .2, -8], [W * .71, H * .12, 6]].map(([x, y, r]) =>
      `<g transform="translate(${x} ${y}) rotate(${r})" opacity=".85"><rect x="-26" y="-4" width="52" height="8" fill="#e8e2c8" opacity=".75"/><rect x="-4" y="-26" width="8" height="52" fill="#e8e2c8" opacity=".75"/></g>`).join('');
    return `<defs>
  <filter id="${id}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".003 .28" numOctaves="2" seed="9"/>
    <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .9 -.25"/></filter>
  <radialGradient id="${id}-spot" cx=".5" cy=".42" r=".62"><stop offset="0" stop-color="#ffe9c2" stop-opacity=".20"/><stop offset=".55" stop-color="#ffe9c2" stop-opacity=".05"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>
</defs>
<rect width="${W}" height="${H}" fill="#120e0b"/>${planks}
<rect width="${W}" height="${H}" filter="url(#${id}-grain)"/>
${tapes}
<rect width="${W}" height="${H}" fill="url(#${id}-spot)"/>`;
  }

  function floorRug(id, W, H, R) {
    const rx = 26, ry = 22, rw = W - 52, rh = H - 44;
    let fringe = '';
    for (let y = ry + 4; y < ry + rh - 2; y += 5) {
      fringe += `<path d="M${rx} ${y}h-${8 + R() * 6}M${rx + rw} ${y}h${8 + R() * 6}"/>`;
    }
    return `<defs>
  <pattern id="${id}-field" width="56" height="56" patternUnits="userSpaceOnUse">
    <rect width="56" height="56" fill="#6e1e1a"/>
    <path d="M28 6 50 28 28 50 6 28z" fill="#8b2a22"/><path d="M28 14 42 28 28 42 14 28z" fill="#1f2a44"/>
    <path d="M28 21 35 28 28 35 21 28z" fill="#d9b779"/><circle cx="0" cy="0" r="5" fill="#d9b779" opacity=".8"/><circle cx="56" cy="0" r="5" fill="#d9b779" opacity=".8"/>
    <circle cx="0" cy="56" r="5" fill="#d9b779" opacity=".8"/><circle cx="56" cy="56" r="5" fill="#d9b779" opacity=".8"/></pattern>
  <pattern id="${id}-border" width="22" height="22" patternUnits="userSpaceOnUse">
    <rect width="22" height="22" fill="#1f2a44"/><path d="M0 11 11 0 22 11 11 22z" fill="none" stroke="#d9b779" stroke-width="2"/><circle cx="11" cy="11" r="2.5" fill="#b8402f"/></pattern>
  <filter id="${id}-weave" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="1.3" numOctaves="2" seed="4"/>
    <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1.1 -.42"/></filter>
  <radialGradient id="${id}-lamp" cx=".5" cy=".45" r=".7"><stop offset="0" stop-color="#ffd9a0" stop-opacity=".16"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>
</defs>
<rect width="${W}" height="${H}" fill="#2a2420"/>
<g stroke="#d8cbb0" stroke-width="1.6" opacity=".8">${fringe}</g>
<rect x="${rx}" y="${ry}" width="${rw}" height="${rh}" fill="url(#${id}-border)"/>
<rect x="${rx + 22}" y="${ry + 22}" width="${rw - 44}" height="${rh - 44}" fill="#d9b779"/>
<rect x="${rx + 26}" y="${ry + 26}" width="${rw - 52}" height="${rh - 52}" fill="url(#${id}-field)"/>
<rect x="${rx}" y="${ry}" width="${rw}" height="${rh}" filter="url(#${id}-weave)"/>
<rect width="${W}" height="${H}" fill="url(#${id}-lamp)"/>`;
  }

  // ---------- cables ----------
  function plug(x, y, dir) {
    // a right-angle jack: barrel into the socket, boot toward the cable
    const s = dir; // +1: plug enters to the right (into a left-side input)
    return `<g><rect x="${s > 0 ? x - 11 : x + 1}" y="${y - 3.4}" width="10" height="6.8" rx="1.2" fill="url(#gp-chrome)"/>
      <rect x="${s > 0 ? x - 19 : x + 9}" y="${y - 5}" width="10" height="10" rx="2.5" fill="#1b1b1b"/>
      <rect x="${s > 0 ? x - 19 : x + 9}" y="${y - 5}" width="10" height="3" rx="1.5" fill="#fff" opacity=".1"/></g>`;
  }
  // returns [cable, plugs]: the plugs are drawn over the pedals' sides, the cable under the pedals
  function cable(id, x1, y1, x2, y2, sag, color) {
    // leaves the output to the right, drops to the floor, comes back up into the input
    const a = x1 + 18, b = x2 - 18, span = Math.abs(b - a);
    const k = Math.min(34, span * .25);
    const d = `M${a} ${y1} C${a + k} ${y1 + sag}, ${b - k} ${y2 + sag}, ${b} ${y2}`;
    return [`<g class="gs-cable">
  <path d="${d}" fill="none" stroke="#000" stroke-opacity=".55" stroke-width="7" transform="translate(3 6)" filter="url(#${id}-blur)"/>
  <path d="${d}" fill="none" stroke="${color || '#141414'}" stroke-width="5.5" stroke-linecap="round"/>
  <path d="${d}" fill="none" stroke="#fff" stroke-opacity=".16" stroke-width="1.3" transform="translate(-.8 -1.4)"/></g>`, plug(x1, y1, -1) + plug(x2, y2, 1)];
  }

  // ---------- the stage box (a lane with no amp ends in the snake) ----------
  function stageBox() {
    return `<svg viewBox="-4 -4 96 76" width="96" role="img" aria-label="stage box"><g filter="url(#gp-shadow)">
  <rect x="0" y="0" width="88" height="64" rx="5" fill="#2b2f33"/><rect x="0" y="0" width="88" height="64" rx="5" fill="url(#gp-brush-lines)"/>
  <rect x="0" y="0" width="88" height="64" rx="5" fill="url(#gp-sheen)"/></g>
  ${[0, 1, 2, 3].map(i => `<circle cx="${16 + i * 19}" cy="26" r="7" fill="#111"/><circle cx="${16 + i * 19}" cy="26" r="4.4" fill="#2a2a2a"/>
    <circle cx="${14.5 + i * 19}" cy="24.5" r=".8" fill="#888"/><circle cx="${17.5 + i * 19}" cy="24.5" r=".8" fill="#888"/><circle cx="${16 + i * 19}" cy="28" r=".8" fill="#888"/>`).join('')}
  <text x="44" y="52" text-anchor="middle" font-family="${P().FONT.nam}" font-size="9" font-weight="700" letter-spacing="1.5" fill="#c9ced3">FOH</text></svg>`;
  }

  // ---------- split and merge boxes (a lane that splits into branches) ----------
  const BRANCH_TAPE = ['#d9c58a', '#d98a7a', '#8ab4d9', '#a6cf8f'];
  const BRANCH_CABLE = ['#1c2530', '#33201c', '#1c2b33', '#222e1d'];
  const letter = b => String.fromCharCode(65 + b);
  // kind 'split': one input, n outputs; 'merge': n inputs, one output. Jacks in the box's own viewBox.
  function splitBox(kind, n, opts) {
    opts = opts || {};
    const W = 76, H = 58, ys = Array.from({ length: n }, (_, b) => n === 1 ? H / 2 : 14 + b * (H - 28) / (n - 1));
    const many = kind === 'split' ? 'right' : 'left';
    const leds = (opts.muted || []).map((m, b) => {
      const cx = 18 + b * 14;
      return `<circle cx="${cx}" cy="40" r="3.2" fill="#222"/><circle cx="${cx}" cy="40" r="2.4" fill="${m ? '#3a2a12' : '#ffb340'}"${m ? '' : ' filter="url(#gp-glow-soft)"'}/>
        <text x="${cx}" y="51" text-anchor="middle" font-family="${P().FONT.nam}" font-size="6.5" font-weight="700" fill="#c9ced3">${letter(b)}</text>`;
    }).join('');
    const jack = (x, y) => `<rect x="${x - 2.5}" y="${y - 4.5}" width="5" height="9" rx="1" fill="#1d1d1d"/>`;
    const svg = `<svg viewBox="-4 -4 ${W + 8} ${H + 12}" width="${W + 8}" role="img" aria-label="${kind} box" class="gs-${kind}box"><g filter="url(#gp-shadow)">
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="#2b2f33"/><rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-brush-lines)"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="5" fill="url(#gp-sheen)"/></g>
  ${ys.map(y => jack(many === 'right' ? W : 0, y)).join('')}${jack(many === 'right' ? 0 : W, H / 2)}
  <text x="${W / 2}" y="20" text-anchor="middle" font-family="${P().FONT.nam}" font-size="10" font-weight="700" letter-spacing="1.6" fill="#c9ced3">${kind === 'split' ? 'SPLIT' : 'MERGE'}</text>
  ${kind === 'merge' && opts.gain != null ? `<text x="${W / 2}" y="${H - 12}" text-anchor="middle" font-family="${P().FONT.nam}" font-size="9" font-weight="600" fill="#9aa3ab">${opts.gain > 0 ? '+' : opts.gain < 0 ? '−' : ''}${Math.abs(opts.gain)} dB</text>` : leds}
</svg>`;
    return { svg, ins: many === 'left' ? ys.map(y => [-2, y]) : [[-2, H / 2]], outs: many === 'right' ? ys.map(y => [W + 2, y]) : [[W + 2, H / 2]] };
  }

  // ---------- render ----------
  // chain items: a block type, a {type, on, …} object, or {split: {mode, gain, branches}} where each
  // branch is an array of items or {id, mute, items}. data-idx on a drawn block is its path in the
  // chain: "3" at the top level, "3.1.0" for the first block of the second branch of item 3.
  function normalize(c) {
    if (typeof c === 'string') return { type: c };
    if (c && c.split) {
      const sp = c.split;
      return Object.assign({}, c, { split: Object.assign({}, sp, { branches: (sp.branches || []).map((br, b) => {
        const arr = Array.isArray(br) ? br : (br.items || br.blocks || []);
        return { id: (br && br.id) || letter(b), mute: !!(br && br.mute), items: arr.map(normalize) };
      }) }) });
    }
    return Object.assign({}, c);
  }
  // an amp-nam directly followed by a cab stands as one stack
  function groupItems(items, prefix) {
    const groups = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i], idx = prefix + i;
      if (it.split) { groups.push({ idx, kind: 'split', split: it.split, branches: it.split.branches.map((br, b) => Object.assign({}, br, { groups: groupItems(br.items, `${idx}.${b}.`) })) }); continue; }
      const fam = familyOf(it.type);
      if (fam === 'nam-head' && items[i + 1] && familyOf(items[i + 1].type) === 'nam-cab') {
        const cab = items[i + 1];
        groups.push({ idx, kind: 'amp', item: Object.assign({}, it, { type: 'amp', family: it.family || cab.family, size: cab.size || cab.title, cabTitle: cab.title }) });
        i++;
      } else {
        groups.push({ idx, kind: ['nam-head', 'nam-cab', 'nam-stack'].includes(fam) ? 'amp' : 'pedal', item: it });
      }
    }
    return groups;
  }
  const anyAmp = groups => groups.some(g => g.kind === 'amp' || (g.kind === 'split' && g.branches.some(br => anyAmp(br.groups))));
  const allGroups = groups => groups.flatMap(g => g.kind === 'split' ? g.branches.flatMap(br => allGroups(br.groups)) : [g]);

  function render(chain, opts) {
    opts = opts || {};
    const id = 'gs' + (++sceneCount);
    const R = rng(opts.seed || 20261113);
    const items = (chain || []).map(normalize);
    const groups = groupItems(items, '');
    const hasAmp = anyAmp(groups);

    // the scene is as tall as its tallest amp needs (amps stand 70 px behind the pedal line)
    let ampH = 0;
    allGroups(groups).filter(g => g.kind === 'amp').forEach(g => {
      const fam = familyOf(g.item.type);
      ampH = Math.max(ampH, place(P().pedalFor(g.item), 0, 0, fam === 'nam-cab' ? 200 : 250).h);
    });
    const H = opts.height || Math.max(330, ampH + 70 + 46 + 24), floorY = H - 46; // pedals stand on floorY
    const pedalW = 104, gap = 46, ampW = 250, margin = 84;
    let x = margin;
    const nodes = [], edges = [], tapes = [];

    // one block (pedal or amp) at x; muted: drawn off and dimmed
    function placeGroup(g, muted) {
      const item = muted ? Object.assign({}, g.item, { on: false }) : g.item;
      const fam = familyOf(item.type);
      const svg = P().pedalFor(item);
      let node;
      if (g.kind === 'amp') {
        const w = fam === 'nam-cab' ? ampW * .8 : ampW;
        const pl = place(svg, x, 0, w);
        const y = floorY - 70 - pl.h; // stands behind the pedal line
        const p2 = place(svg, x, y, w, g.idx);
        const inPt = [x + w * .09, y + p2.h * (fam === 'nam-cab' ? .5 : (fam === 'nam-head' ? .72 : .36))];
        node = { svg: p2.svg, inPt, outPt: [x + w * .96, inPt[1]], amp: true };
        x += w + gap;
      } else {
        const isTreadle = /gp-treadle/.test(svg);
        const w = isTreadle ? pedalW * 1.08 : /viewBox="-6 -4 104/.test(svg) ? pedalW * .84 : pedalW;
        const pl = place(svg, x, 0, w);
        const y = floorY - pl.h;
        const p2 = place(svg, x, y, w, g.idx);
        const jy = isTreadle ? 150 : 40;
        node = { svg: p2.svg, inPt: toScene(p2, x, y, -4, jy), outPt: toScene(p2, x, y, p2.vb[0] + p2.vb[2] - 2, jy) };
        x += w + gap;
      }
      if (muted) node.svg = `<g class="gs-muted" opacity=".5">${node.svg}</g>`;
      nodes.push(node);
      return node;
    }
    // a box at x on the floor, jacks given in its viewBox
    function placeBox(box) {
      const vb = /viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"/.exec(box.svg).slice(1).map(Number);
      const w = vb[2], h = vb[3], y = floorY - h, bx = x;
      const pt = ([px, py]) => [bx + px - vb[0], y + py - vb[1]];
      const node = { svg: place(box.svg, bx, y, w).svg, ins: box.ins.map(pt), outs: box.outs.map(pt) };
      node.inPt = node.ins[0]; node.outPt = node.outs[0];
      nodes.push(node);
      x += w + gap;
      return node;
    }
    const link = (from, to, color, sagMin) => {
      if (from && to) edges.push({ a: from, b: to, color, toAmp: !!(to.amp || from.amp), sagMin });
    };

    // lay out a list of groups in series; returns the last node (prev in, last out)
    function layout(gs, prev, muted, color) {
      gs.forEach(g => {
        if (g.kind === 'split') {
          const n = g.branches.length;
          const mutes = g.branches.map(br => muted || br.mute);
          const sp = placeBox(splitBox('split', n, { muted: mutes }));
          sp.idx = g.idx;
          link(prev, { outPt: null, inPt: sp.ins[0] }, color);
          const ends = [];
          g.branches.forEach((br, b) => {
            const x0 = x;
            const head = { outPt: sp.outs[b] };
            const last = layout(br.groups, head, mutes[b], BRANCH_CABLE[b % 4]);
            ends.push(last);
            if (last === head) x += 40; // an empty (dry) branch still takes a little floor
            tapes.push({ x0: x0 - 14, x1: x - gap + 14, b, id: br.id, idx: g.idx, mute: mutes[b] });
            x += 26; // air between branches
          });
          const mg = placeBox(splitBox('merge', n, { gain: g.split.gain }));
          ends.forEach((last, b) => link({ outPt: last.outPt, amp: last.amp }, { inPt: mg.ins[b] }, BRANCH_CABLE[b % 4], last.outPt === sp.outs[b] ? 30 : 0));
          prev = mg;
        } else {
          const node = placeGroup(g, muted);
          link(prev, node, color);
          prev = node;
        }
      });
      return prev;
    }
    const last = layout(groups, null, false, null);

    // the end: a stage box when the lane has no amp
    if (!hasAmp) {
      const pl = place(stageBox(), x + 10, floorY - 80, 96);
      const end = { svg: pl.svg, inPt: [x + 12, floorY - 80 + pl.h * .4], outPt: null };
      nodes.push(end);
      link(last, end, null);
      x += 120;
    }
    const W = Math.max(opts.minWidth || 0, x + margin - gap);

    let cables = '', plugs = '';
    // the guitar cable, from off stage
    const first = nodes[0];
    if (first && opts.guitar !== false) {
      const [ix, iy] = first.inPt;
      const d = `M-10 ${floorY + 30} C${ix * .3} ${floorY + 40}, ${ix - 60} ${iy + 70}, ${ix - 18} ${iy}`;
      cables += `<g class="gs-cable"><path d="${d}" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="8" transform="translate(3 6)" filter="url(#${id}-blur)"/>
        <path d="${d}" fill="none" stroke="#1d1d1d" stroke-width="6.5"/><path d="${d}" fill="none" stroke="#fff" stroke-opacity=".14" stroke-width="1.4" transform="translate(-.8 -1.4)"/></g>`;
      plugs += plug(ix, iy, 1);
    }
    edges.forEach(e => {
      const sag = Math.max(e.sagMin || 0, e.toAmp ? 120 : 26 + R() * 14);
      const [c, pl] = cable(id, e.a.outPt[0], e.a.outPt[1], e.b.inPt[0], e.b.inPt[1], sag, e.color || (e.toAmp ? '#191919' : null));
      cables += c; plugs += pl;
    });
    // the last block after an amp goes off to front of house
    if (hasAmp && last && last.outPt) {
      const [ox, oy] = last.outPt;
      cables += `<g class="gs-cable"><path d="M${ox + 18} ${oy} C${ox + 70} ${oy + 40}, ${W - 40} ${floorY + 20}, ${W + 10} ${floorY + 34}" fill="none" stroke="#1d1d1d" stroke-width="6"/></g>`;
      plugs += plug(ox, oy, -1);
    }
    // gaffer tape on the floor under each branch, lettered; data-branch lets the host mute it
    const tapeSvg = tapes.map(t => {
      const c = BRANCH_TAPE[t.b % 4], ty = floorY + 16, lx = t.x0 + 6;
      const txt = letter(t.b) + (t.mute ? ' · MUTED' : '');
      return `<g class="gs-branch${t.mute ? ' is-muted' : ''}" data-split="${t.idx}" data-branch="${P().esc(t.id)}" data-b="${t.b}" style="cursor:pointer">
  <rect x="${t.x0}" y="${ty}" width="${t.x1 - t.x0}" height="5" fill="${c}" opacity="${t.mute ? .25 : .55}"/>
  <rect x="${lx}" y="${ty - 12}" width="${txt.length * 10.5 + 18}" height="28" rx="1.5" fill="#e8e2c8" opacity=".92" transform="rotate(-2 ${lx} ${ty})"/>
  <text x="${lx + 9}" y="${ty + 9}" font-family="${P().FONT.nam}" font-size="20" font-weight="800" letter-spacing="1.5" fill="${t.mute ? '#7a6f62' : '#2a2018'}" transform="rotate(-2 ${lx} ${ty})">${txt}</text></g>`;
    }).join('');

    const floor = opts.floor === 'rug' ? floorRug(id, W, H, R) : floorStage(id, W, H, R);
    return `<svg class="gs-scene gs-${opts.floor === 'rug' ? 'rug' : 'stage'}" viewBox="0 0 ${W.toFixed(0)} ${H}" width="${opts.width || W.toFixed(0)}" role="img" aria-label="${allGroups(groups).length} blocks on a ${opts.floor === 'rug' ? 'rug' : 'stage floor'}">
<defs><filter id="${id}-blur" x="-10%" y="-30%" width="120%" height="160%"><feGaussianBlur stdDeviation="2.4"/></filter></defs>
${floor}
${tapeSvg}
${nodes.filter(p => p.amp).map(p => p.svg).join('\n')}
${cables}
${nodes.filter(p => !p.amp).map(p => p.svg).join('\n')}
${plugs}
</svg>`;
  }

  // golem's lane chain -> render() items. chain: golem's {pre, split, post} (lanes v2) or a flat block
  // list; state: a lane state ({blocks: {id: on}, branches: {id: {mute}}}) to draw the scene as it plays.
  // Capture labels resolve to the catalogue's archetypes, never to a maker's name.
  function fromGolem(chain, state) {
    state = state || {};
    const onMap = state.blocks || {}, brMap = state.branches || {};
    const conv = list => {
      let lastFamily;
      return (list || []).map(b => {
        const it = { type: b.type, id: b.id, on: b.id in onMap ? !!onMap[b.id] : b.on !== false };
        if (b.type === 'amp-nam' || b.type === 'amp') {
          const a = P().archetypeFor('amps', b.label);
          if (a) { it.family = a.family; it.title = a.short; }
          lastFamily = it.family;
        } else if (b.type === 'cab') {
          const a = P().archetypeFor('cabs', b.label), m = /(\d+)\s*x\s*(\d+)/i.exec(b.label || '');
          it.size = m ? `${m[1]}x${m[2]}` : undefined;
          it.title = a ? a.short : it.size;
          it.family = lastFamily;
        } else if (/-nam$|^capture-module$/.test(b.type)) {
          const a = P().archetypeFor('pedals', b.label);
          if (a) it.archetype = a;
        }
        return it;
      });
    };
    if (Array.isArray(chain)) return conv(chain);
    chain = chain || {};
    const out = conv(chain.pre);
    if (chain.split && (chain.split.branches || []).length) {
      out.push({ split: { mode: chain.split.mode, gain: chain.split.gain, branches: chain.split.branches.map(br => ({
        id: br.id, mute: br.id in brMap ? !!(brMap[br.id] && brMap[br.id].mute) : !!br.mute, items: conv(br.blocks) })) } });
    }
    return out.concat(conv(chain.post));
  }

  root.GolemStage = { render, fromGolem, stageBox, splitBox };
})(typeof window !== 'undefined' ? window : globalThis);

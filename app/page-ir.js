// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet IR (hub Library) — impulse responses (cabs). Source = catalogue tones (gear=cab / format=ir,
// même index que Amps), filtrées ici. « + Add » propose DEUX voies : upload d'un .wav local (corps
// brut vers /api/ir/upload, façon Vital) OU téléchargement depuis TONE3000 (T3kModal gear=cab).
// Suppression = flux amp partagé (/api/amp/{id} : corbeille + dépendances par preset).
import { html, useState, useEffect, useRef, useAsync, cls, esc, safeHref, getCatalog, refreshCatalog, setTopAction, setSubToolbar, useRev } from './lib.js';
import { T3kModal } from './t3k-modal.js';
import { DeleteFlow, famOf } from './page-amps.js';
import { archOf } from './designer-model.js';
import { useVisuals, Drawing, cabSvg, cabSize, micPos, micOf, usePage, Pager, useAudition, PlayMark, AuditionNote, takeOpen } from './tones-ui.js';

const irName = t => t.amp || t.title || 'IR';
// « pack à écho » (2026-09-14) : le rack a LU les fichiers — une impulsion tardive répète chaque note.
// Le compile coupe la copie avant l'écho, donc le pack reste jouable ; le badge dit ce qu'il contient.
const echoTitle = e => `${e.bad}/${e.files} IR file${e.files > 1 ? 's' : ''} carry a late impulse (worst: ${e.worst_ms} ms at ${e.worst_db} dB) — a second hit per note. Played CUT before the echo; a clean pack is better.`;
const styleColor = s => ({ metal: '#ff5a3c', rock: '#ffb03a', blues: '#5a7cff', jazz: '#b06cf0',
  funk: '#2ecc71', bass: '#e0b23a' }[s] || '#1ab7b0');

export function IRPage({ role, gears } = {}) {
  const [catTick, setCatTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data } = useAsync(getCatalog, [catTick, libRev]);
  const tones = (data && data.tones) || [];
  const roleCanLoad = !gears || gears.has('cab');
  const irs = tones.filter(t => (t.gear === 'cab' || t.format === 'ir') && (!role || role === 'voice' || famOf(t) === role));
  const [q, setQ] = useState('');
  const [style, setStyle] = useState('all');
  const [sel, setSel] = useState(null);
  const [t3k, setT3k] = useState(false);
  const [addMenu, setAddMenu] = useState(false);  // « + Add » -> menu 2 voies (TONE3000 / upload)
  const [busy, setBusy] = useState('');           // message d'état upload
  const fileRef = useRef(null);
  const reloadCat = () => { refreshCatalog(); setCatTick(x => x + 1); };

  // upload : POST chaque .wav en CORPS BRUT vers /api/ir/upload?name= puis rafraîchit le catalogue
  const uploadFiles = async files => {
    let added = 0, errs = [];
    for (const f of Array.from(files || [])) {
      setBusy(`⬆ ${f.name}…`);
      try {
        const r = await fetch('/api/ir/upload?name=' + encodeURIComponent(f.name),
          { method: 'POST', body: f }).then(x => x.json());
        if (r.ok) added += 1; else errs.push(`${f.name}: ${r.error}`);
      } catch (e) { errs.push(`${f.name}: ${e}`); }
    }
    setBusy(errs.length ? `✗ ${errs[0]}` : `✓ ${added} IR added`);
    reloadCat();
    setTimeout(() => setBusy(''), 4000);
  };

  // « + Add » CONTEXTUEL : ouvre un mini-menu 2 voies (TONE3000 gear Cabs/IR, OU upload .wav local).
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${() => setAddMenu(true)}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);

  const styles = [...new Set(irs.map(t => t.style).filter(Boolean))].sort();
  const match = t => (style === 'all' || t.style === style)
    && (!q || (irName(t) + ' ' + (t.brand || '') + ' ' + (t.creator || '') + ' ' + (t.tags || []).join(' ')).toLowerCase().includes(q));
  const list = irs.filter(match).sort((a, b) => (b.downloads || 0) - (a.downloads || 0));
  // ── classement PAR MARQUE (« comme les tiroirs ») : la marque, sinon 1er fabricant, sinon Other ;
  // marques génériques (« Cabs / IR ») rejetées. Dans chaque marque : modèles triés A→Z. ──
  const GENERIC = /^(cabs?\s*\/?\s*ir|ir|cab|other|divers|unknown|\-|)$/i;
  // un `brand` peut arriver en OBJET ({Name}) depuis golem.fm — un en-tête « {'Name': …} » vu à l'écran le 2026-09-14
  const brandOf = t => { const raw = t.brand && typeof t.brand === 'object' ? (t.brand.Name || t.brand.name || '') : (t.brand || '');
    const b = String(raw).trim();
    if (b && !GENERIC.test(b)) return b;
    const m = (t.makes || []).find(x => x && !GENERIC.test(x));
    return m || 'Other'; };
  const brands = [...new Set(list.map(brandOf))].sort((a, b) => a === 'Other' ? 1 : b === 'Other' ? -1 : a.localeCompare(b));
  const byBrand = b => list.filter(t => brandOf(t) === b).sort((x, y) => irName(x).localeCompare(irName(y)));

  // LE MUR DE BAFFLES (docs/library-tones.md §3) : la taille lue dans le nom (puis dans les IR), dessinée avec le
  // bon nombre de haut-parleurs ; filtre par taille ; 10 baffles par page
  const fxDoc = useAsync(() => fetch('/api/effects').then(r => r.json()), []).data || null;
  const vis = useVisuals(fxDoc);
  const [size, setSize] = useState('all');
  const cabOf = t => { const sz = cabSize(t) || '4x12';
    const a = archOf((fxDoc && fxDoc.cabs) || [], t);
    const all = irName(t) + ' ' + (t.models || []).map(m => m.name).join(' ');
    const mics = [...new Set((all.match(/sm ?-?57|sm ?58|sm7b|r-?121|origin|u67|md ?421/ig) || []).map(m => m.replace(/[\s-]/g, '').toUpperCase().replace('ORIGIN', 'Origin')))];
    return { t, size: sz, mics, look: t.style === 'metal' ? 'high-gain' : t.style === 'bass' ? 'bass' : 'crunch',
      title: (a ? String(a.short || a.name).replace(/\s*\(.*\)/, '') : brandOf(t) !== 'Other' ? brandOf(t) : irName(t).split(/[\s-]/)[0]).slice(0, 12) }; };
  const cabs = list.map(cabOf);
  const sizes = [...new Set(cabs.map(c => c.size))].sort();
  const shown = cabs.filter(c => size === 'all' || c.size === size);
  const pg = usePage(shown.length, 10, [size, style, q, role]);
  const [opened] = useState(() => takeOpen('cab'));
  useEffect(() => { if (opened) { const t = tones.find(x => String(x.id) === opened); if (t) setSel(t); } }, [opened, tones.length]);

  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search cabs"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <select class="flt-sel" value=${style} onChange=${e => setStyle(e.target.value)} title="Style">
        <option value="all">Style · all</option>
        ${styles.map(s => html`<option value=${s} selected=${s === style}>${s}</option>`)}
      </select>
      ${busy ? html`<span class="syn-busy">${busy}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [style, styles.length, busy]);

  if (!roleCanLoad) return html`<div class="library"><div class="empty">A <b>${esc(role)}</b> lane has no cab — see <b>Outboard</b>.</div></div>`;

  const addMenuEl = addMenu ? html`<div class="add-scrim" onClick=${() => setAddMenu(false)}>
    <div class="add-menu" onClick=${e => e.stopPropagation()}>
      <button class="row-btn" onClick=${() => { setAddMenu(false); setT3k(true); }}>⬇ From TONE3000 <small>cab IRs</small></button>
      <button class="row-btn" onClick=${() => { setAddMenu(false); document.getElementById('ir-file-input')?.click(); }}>⬆ Upload a <code>.wav</code></button>
    </div></div>` : '';
  return html`
    <div class="library tn-page">
      <input id="ir-file-input" ref=${fileRef} type="file" accept=".wav,audio/wav" multiple
        style="display:none" onChange=${e => { uploadFiles(e.target.files); e.target.value = ''; }} />
      ${sel ? html`<${CabPanel} c=${cabOf(sel)} vis=${vis} onClose=${() => setSel(null)} onDeleted=${() => { setSel(null); reloadCat(); }} />`
      : html`<div class="tn-col">
        <div class="tn-bar"><div class="chips">
          <button class=${cls('chip', size === 'all' && 'on')} onClick=${() => setSize('all')}>All sizes <em>${cabs.length}</em></button>
          ${sizes.map(s => html`<button class=${cls('chip', size === s && 'on')} onClick=${() => setSize(s)}>${s} <em>${cabs.filter(c => c.size === s).length}</em></button>`)}</div>
          <span class="grow"></span><span class="muted" style="font-size:12px">Size read from the name · mics from the IR files</span></div>
        ${shown.length ? html`<div class="tn-wall">${shown.slice(pg.from, pg.to).map(c => html`
          <button class="tn-tile tn-cab" onClick=${() => setSel(c.t)}>
            ${vis ? html`<${Drawing} svg=${cabSvg(c)} />` : html`<div class="tn-draw"></div>`}
            <b>${irName(c.t)}</b>
            <span>${(c.t.models || []).length} IR${(c.t.models || []).length > 1 ? 's' : ''}${c.mics.length ? ' · ' + c.mics.slice(0, 2).join(' + ') : ''}${c.t.echo ? html` · <i class="tn-echo" title=${echoTitle(c.t.echo)}>echo</i>` : ''}</span>
          </button>`)}</div>`
        : html`<div class="empty">No IRs — tap <b>+ Add</b> to import a <code>.wav</code> impulse response, or download cab IRs from TONE3000.</div>`}
        <${Pager} pg=${pg} />
      </div>`}
      ${addMenuEl}
      ${t3k ? html`<${T3kModal} initGear="cab" onClose=${() => setT3k(false)} onInstalled=${reloadCat} />` : ''}
    </div>`;
}

// LA FICHE D'UN BAFFLE (docs/library-tones.md §3) : OÙ ÉTAIT LE MICRO — chaque IR placée est un point sur le cône
// (lu dans son nom : centre, cap edge, mi-cône, bord ; « 0.50in » ; 45° hors axe) ; les IR prises au même endroit se
// regroupent ; sur le baffle, le haut-parleur capté (UL/UR/LL/LR) est entouré. Toucher une IR la fait entendre.
function CabPanel({ c, vis, onClose, onDeleted }) {
  const t = c.t;
  const au = useAudition();
  const [del_, setDel] = useState(false);
  const irs = (t.models || []).map((m, i) => ({ i, m, p: micPos(m.name), mic: micOf(m.name) }));
  const [selI, setSelI] = useState(0);
  const pg = usePage(irs.length, 7, [t.id]);
  const cur = irs[selI];
  const P = window.GolemPedals;
  const L = P ? P.cabLayout(c.size) : { cols: 2, rows: 2 };
  const spk = cur && cur.p && cur.p.spk;
  const ring = cur && cur.p ? (spk ? [spk[1] === 'R' ? Math.min(1, L.cols - 1) : 0, spk[0] === 'L' ? L.rows - 1 : 0] : [0, 0]) : null;
  const groups = [];
  for (const x of irs.filter(x => x.p && (!spk || x.p.spk === spk))) {
    const g = groups.find(g => Math.abs(g.r - x.p.r) < .02 && g.off === x.p.off);
    if (g) g.items.push(x); else groups.push({ r: x.p.r, off: x.p.off, items: [x] });
  }
  const R = 108, cx = 130, cy = 130;
  const dots = groups.map((g, k) => { const a = (-60 + k * (300 / Math.max(groups.length, 1))) * Math.PI / 180, rr = Math.max(g.r, .12);
    return { i: g.items[0].i, n: g.items.length, on: cur && g.items.some(x => x.i === cur.i), off: g.off, x: cx + Math.cos(a) * rr * R, y: cy + Math.sin(a) * rr * R }; });
  const tap = i => { setSelI(i); au.play(t.id, irs[i].m.id); };
  const placed = irs.filter(x => x.p).length;
  return html`<div class="tn-detail">
    <section class="tn-stage narrow"><button class="tn-back" onClick=${onClose}>‹ Cabs</button>
      <div class="tn-spot">${vis ? html`<${Drawing} svg=${cabSvg(c, ring)} />` : ''}</div>
      <h2>${irName(t)}</h2>
      <div class="tn-meta"><span class="fam" style="--c:#1ab7b0">${c.size}</span>${c.mics.map(m => html`<span>${m}</span>`)}<span>${irs.length} IR${irs.length > 1 ? 's' : ''}</span></div>
    </section>
    <section class="tn-caps">
      <header><b>Where the mic was</b><span class="grow"></span><span class="muted" style="font-size:12px">${placed} placed · ${irs.length - placed} blends</span></header>
      ${t.echo ? html`<div class="tn-note ko" title=${echoTitle(t.echo)}>Late echo in ${t.echo.bad} of ${t.echo.files} files: played cut before the echo.</div>` : ''}
      <div class="tn-split">
        ${placed ? html`<svg class="tn-cone" viewBox="0 0 260 270" role="img" aria-label="mic positions on the speaker">
          <defs><radialGradient id="tn-cg" cx="50%" cy="45%"><stop offset="0" stop-color="#4a4f57"/><stop offset=".25" stop-color="#1d2026"/><stop offset=".26" stop-color="#2a2e35"/><stop offset="1" stop-color="#0e1013"/></radialGradient></defs>
          <circle cx=${cx} cy=${cy} r=${R + 14} fill="#08090b" stroke="#2a2f37"/><circle cx=${cx} cy=${cy} r=${R} fill="url(#tn-cg)"/>
          ${[.33, .55, .8].map(f => html`<circle cx=${cx} cy=${cy} r=${R * f} fill="none" stroke="#fff" stroke-opacity=".06"/>`)}
          <circle cx=${cx} cy=${cy} r=${R * .26} fill="#3b4048"/>
          ${spk ? html`<text x=${cx} y="12" text-anchor="middle" class="tn-kl">SPEAKER ${spk}</text>` : ''}
          <text x=${cx} y=${cy + R + 34} text-anchor="middle" class="tn-kl">CENTER ← → EDGE</text>
          ${dots.map(d => html`<g class=${cls('tn-dot', d.on && 'on')} onClick=${() => tap(d.i)}><circle cx=${d.x} cy=${d.y} r=${d.on ? 11 : 8}/>
            ${d.off ? html`<path d=${`M${d.x - 5} ${d.y + 5}L${d.x + 5} ${d.y - 5}`} stroke="#0d0f12" stroke-width="2"/>` : ''}
            ${d.n > 1 ? html`<text x=${d.x + 13} y=${d.y - 9} class="tn-kv" style="font-size:12px">×${d.n}</text>` : ''}</g>`)}
        </svg>` : ''}
        <div class="tn-rows irs">${irs.slice(pg.from, pg.to).map(x => html`
          <button class=${cls('tn-row', au.playing(t.id, x.m.id) && 'on', x.i === selI && 'cur')} onClick=${() => tap(x.i)}>
            <span class="nm">${x.m.name || 'IR'}<small>${x.p ? [x.p.label, x.p.dist, x.p.off ? '45° off-axis' : '', x.p.spk ? 'speaker ' + x.p.spk : ''].filter(Boolean).join(' · ') : 'Blend or unnamed position'}</small></span>
            ${x.mic ? html`<i class="t-mic">${x.mic}</i>` : ''}<${PlayMark} on=${au.playing(t.id, x.m.id)} busy=${au.loading(t.id, x.m.id)} /></button>`)}</div>
      </div>
      <${Pager} pg=${pg} />
      <${AuditionNote} au=${au} />
      <div class="tn-act"><span class="grow"></span>
        ${safeHref(t.url) ? html`<a class="mini" href=${safeHref(t.url)} target="_blank" rel="noopener">Source ↗</a>` : ''}
        <button class="mini danger" onClick=${() => setDel(true)}>Delete</button></div>
      ${del_ ? html`<div class="sheet-scrim"><div class="gf-sheet"><${DeleteFlow} t=${t} onDone=${() => { setDel(false); onDeleted(); }} onCancel=${() => setDel(false)} /></div></div>` : ''}
    </section></div>`;
}

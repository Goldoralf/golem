// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet « Pedals » (hub Library) — palette des BLOCKS d'effets DSP disponibles (effects.json via
// /api/effects). Ce sont des effets branchés sur des plugins (ReaComp, guitarix LV2…), pas des
// fichiers : on les PARCOURT (nom, plugin, params), groupés par catégorie. « + Add » ne fabrique pas
// un block DSP (= intégration plugin, côté dev) mais importe une CAPTURE NAM de pédale depuis
// TONE3000 (gear=pedal) — le seul « ajout de pédale » qui a un sens depuis l'UI.
// NB : distinct de page-pedals.js (panneau MIDI Whammy DT de Settings ▸ Pedalboard).
import { html, useState, useEffect, useAsync, cls, esc, setTopAction, setSubToolbar, getCatalog, refreshCatalog, useRev } from './lib.js';
import { CAT_COLOR, capText, archOf, GOLEM_FX } from './designer-model.js';
import { useVisuals, Drawing, namPedalSvg, usePage, Pager, useAudition, PlayMark, AuditionNote, knobsOf, knobsSvg, takeOpen } from './tones-ui.js';
import { pedalSvg } from './golem-visuals.js';
import { T3kModal } from './t3k-modal.js';
import { Detail as CaptureDetail, famOf } from './page-amps.js';

const catColor = c => CAT_COLOR[c] || '#8a94a3';
const CAT_LABEL = {
  dynamics: 'Dynamics', drive: 'Drive', filter: 'Filter', amp: 'Amp', cab: 'Cab', eq: 'EQ',
  modulation: 'Modulation', delay: 'Delay', reverb: 'Reverb', pitch: 'Pitch', utility: 'Utility',
};
// pédales NOMMÉES (archétypes effects.json pedals[]) : familles + ordre d'affichage
const PED_FAM = [['overdrive', 'Overdrive'], ['distortion', 'Distortion'], ['fuzz', 'Fuzz'], ['boost', 'Boost'], ['bass', 'Bass']];
const isBass = a => (a.roles || ['guitar']).includes('bass');

export function FxBlocksPage({ role, gears } = {}) {
  const { data } = useAsync(() => fetch('/api/effects').then(r => r.json()), []);
  const [catTick, setCatTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data: catalog } = useAsync(getCatalog, [catTick, libRev]);   // captures installées (gear=pedal)
  const cats = (data && data.categories) || [];
  // le RÔLE (segment Tones) filtre la palette comme le tiroir du Designer : catégories de
  // role_categories + `roles` par bloc ; et les captures de pédales par famille (guitar/bass)
  const roleCats = role && data && data.role_categories && Array.isArray(data.role_categories[role]) ? data.role_categories[role] : null;
  const fx = ((data && data.effects) || []).filter(e => (!roleCats || roleCats.includes(e.category)) && (!role || !e.roles || e.roles.includes(role)));
  const roleCanLoad = !gears || gears.has('pedal');
  const pedals = (data && data.pedals) || [];     // pédales NOMMÉES (archétypes) — Big Muff, TS, Fortin…
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('all');
  const [sel, setSel] = useState(null);
  const [selPed, setSelPed] = useState(null);     // détail d'une pédale nommée
  const [selCap, setSelCap] = useState(null);     // détail d'une CAPTURE installée
  const [t3k, setT3k] = useState(false);          // modal + Add (capture NAM de pédale)

  // « + Add » CONTEXTUEL dans la topbar → modal TONE3000 PRÉ-FILTRÉ Pedals (recherche de captures)
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${() => setT3k(true)}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);

  // LE PÉDALIER (docs/library-tones.md §2) : deux mondes — les pédales CAPTÉES (NAM : une pédale nommée et ses
  // captures, ou une capture que rien ne nomme) et les effets INTÉGRÉS (golem-fx en métal, les autres en émail)
  const [mode, setMode] = useState('captured');
  const [pfam, setPfam] = useState('all');
  const vis = useVisuals(data);
  const pedOf = t => archOf(pedals, t);
  // format=ir exclu : les packs d'IR « de pédale » (cab-sim capturé en .wav) vivent dans Cabs
  const pedCaps = (((catalog && catalog.tones) || []).filter(t => t.gear === 'pedal' && t.format !== 'ir'
    && roleCanLoad && (!role || role === 'voice' || famOf(t) === role)));
  const capsByPed = {}, orphans = [];
  for (const t of pedCaps) { const a = pedOf(t); if (a) (capsByPed[a.id] = capsByPed[a.id] || []).push(t); else orphans.push(t); }
  const famGuess = n => /fuzz/i.test(n) ? 'fuzz' : /boost|precision/i.test(n) ? 'boost' : /dist|ds-?1|full moon/i.test(n) ? 'distortion' : /comp|kokko/i.test(n) ? 'other' : 'overdrive';
  const byName = {};
  for (const t of orphans) (byName[t.amp || t.title] = byName[t.amp || t.title] || []).push(t);
  const famKey = f => ['overdrive', 'distortion', 'fuzz', 'boost', 'bass'].includes(f) ? f : 'other';
  const board = [
    ...pedals.filter(a => !role || role === 'voice' || (role === 'bass') === isBass(a) || a.family === 'bass')
      .map(a => ({ key: 'a-' + a.id, name: a.name, short: a.short || a.name, family: famKey(a.family), arch: a, caps: capsByPed[a.id] || [] })),
    ...Object.entries(byName).map(([n, caps]) => ({ key: 'c-' + caps[0].id, name: n, short: n.replace(/^(boss|ibanez|fender|jhs|maxon|horizon devices|electro-harmonix)\s+/i, ''),
      family: famGuess(n), arch: null, caps })),
  ].filter(p => !q || (p.name + ' ' + p.short + ' ' + p.caps.map(capText).join(' ')).toLowerCase().includes(q))
   .sort((x, y) => (y.caps.length > 0) - (x.caps.length > 0) || y.caps.length - x.caps.length || x.name.localeCompare(y.name));
  const boardShown = board.filter(p => pfam === 'all' || p.family === pfam);
  const CAPTURE_TYPES = new Set(['pedal-nam', 'preamp-nam', 'comp-nam', 'capture-module']);
  const isBuilt = e => !e.loads && !CAPTURE_TYPES.has(e.type) && e.category !== 'amp' && e.category !== 'cab';
  const builtCats = cats.filter(c => fx.some(e => e.category === c && isBuilt(e)));
  const [bcat, setBcat] = useState(null);
  const curCat = bcat && builtCats.includes(bcat) ? bcat : (builtCats.includes('drive') ? 'drive' : builtCats[0]);
  const built = fx.filter(e => e.category === curCat && isBuilt(e) && (!q || (e.name + ' ' + (e.short || '') + ' ' + e.type + ' ' + (e.plugin || '')).toLowerCase().includes(q)));
  const per = 14;
  const pg = usePage(mode === 'captured' ? boardShown.length : built.length, per, [mode, pfam, curCat, q, role]);
  const [opened] = useState(() => takeOpen('pedal'));
  useEffect(() => { if (opened && !selPed) { const p = board.find(b => b.key === opened); if (p) setSelPed(p); } }, [opened, board.length]);

  useEffect(() => {
    setSubToolbar(html`<input class="search" type="search" placeholder="Search pedals and effects"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />`);
    return () => setSubToolbar(null);
  }, []);

  if (selPed) return html`<div class="library tn-page"><${PedalPanel} p=${selPed} vis=${vis}
    onClose=${() => setSelPed(null)} onT3k=${() => setT3k(true)} onOpen=${t => setSelCap(t)} />
    ${selCap ? html`<${CaptureDetail} t=${selCap} onClose=${() => setSelCap(null)}
      onDeleted=${() => { setSelCap(null); setSelPed(null); refreshCatalog(); setCatTick(x => x + 1); }} />` : ''}
    ${t3k ? html`<${T3kModal} initGear="pedal" onClose=${() => setT3k(false)} onInstalled=${() => { refreshCatalog(); setCatTick(x => x + 1); }} />` : ''}</div>`;
  if (sel) return html`<div class="library tn-page"><${BuiltinPanel} e=${sel} vis=${vis} onClose=${() => setSel(null)} /></div>`;

  const famCount = f => board.filter(p => p.family === f).length;
  return html`
    <div class="library tn-page"><div class="tn-col">
      <div class="tn-bar">
        <div class="tn-seg"><button class=${cls(mode === 'captured' && 'on')} onClick=${() => setMode('captured')}>Captured pedals <em>${board.length}</em></button>
          <button class=${cls(mode === 'builtin' && 'on')} onClick=${() => setMode('builtin')}>Built-in effects <em>${fx.filter(isBuilt).length}</em></button></div>
        <div class="chips">${mode === 'captured'
          ? [['all', 'All'], ...PED_FAM, ['other', 'Other']].filter(([f]) => f === 'all' || famCount(f)).map(([f, l]) => html`<button class=${cls('chip', pfam === f && 'on')} onClick=${() => setPfam(f)}>${l}${f !== 'all' ? html` <em>${famCount(f)}</em>` : ''}</button>`)
          : builtCats.map(c => html`<button class=${cls('chip', curCat === c && 'on')} onClick=${() => setBcat(c)}>${CAT_LABEL[c] || c}</button>`)}</div>
      </div>
      <div class="tn-board"><div class="tn-pedals">${mode === 'captured'
        ? boardShown.slice(pg.from, pg.to).map(p => html`<button class=${cls('tn-tile tn-ped', !p.caps.length && 'ghost')} onClick=${() => setSelPed(p)}>
            ${vis ? html`<${Drawing} svg=${namPedalSvg(p.arch, p.short, p.family === 'other' ? 'boost' : p.family, p.caps.length > 0)} />` : html`<div class="tn-draw"></div>`}
            <b>${p.name}</b><span>${p.caps.length ? `${p.caps.reduce((s, t) => s + (t.models || []).length, 0)} captures` : 'Find on TONE3000'}</span></button>`)
        : built.slice(pg.from, pg.to).map(e => html`<button class="tn-tile tn-ped" onClick=${() => setSel(e)}>
            ${vis ? html`<${Drawing} svg=${pedalSvg({ type: e.type, title: e.short || e.name })} />` : html`<div class="tn-draw"></div>`}
            <b>${e.name}</b><span>${GOLEM_FX.has(e.type) ? 'golem-fx' : String(e.plugin || 'built-in').replace(/^\w+:\s*/, '').split(/[ (]/)[0]}</span></button>`)}</div></div>
      <${Pager} pg=${pg} />
    </div>
    ${t3k ? html`<${T3kModal} initGear="pedal" onClose=${() => setT3k(false)} onInstalled=${() => { refreshCatalog(); setCatTick(x => x + 1); }} />` : ''}
    </div>`;
}

// LA FICHE D'UNE PÉDALE CAPTÉE (docs/library-tones.md §2) : ses captures, regroupées sous la pédale ; quand le nom
// d'une capture écrit ses potards (« Drive 7 Tone 6 Level 9 »), ils sont dessinés à cette position.
function PedalPanel({ p, vis, onClose, onT3k, onOpen }) {
  const au = useAudition();
  const models = [];
  for (const t of p.caps) for (const m of (t.models || [])) models.push({ t, m });
  const firstKnobs = Math.max(0, models.findIndex(x => knobsOf(x.m.name).length));
  const [selI, setSelI] = useState(firstKnobs);
  const pg = usePage(models.length, 6, [p.key]);
  useEffect(() => { pg.set(Math.floor(firstKnobs / 6)); }, [p.key]);
  const cur = models[selI];
  const kn = cur ? knobsOf(cur.m.name) : [];
  const P = window.GolemPedals;
  const col = ((P && P.NAM_VOICE && P.NAM_VOICE[p.family]) || { glow: '#ffb03a' }).glow;
  const tap = i => { setSelI(i); au.play(models[i].t.id, models[i].m.id); };
  return html`<div class="tn-detail">
    <section class="tn-stage board"><button class="tn-back" onClick=${onClose}>‹ Pedals</button>
      <div class="tn-spot pedal">${vis ? html`<${Drawing} svg=${namPedalSvg(p.arch, p.short, p.family === 'other' ? 'boost' : p.family, true)} align="xMidYMid" />` : ''}</div>
      <h2>${p.name}</h2>
      <div class="tn-meta"><span class="fam" style=${'--c:' + col}>${p.family}</span><span>${p.caps.length} pack${p.caps.length > 1 ? 's' : ''} · ${models.length} captures</span></div>
    </section>
    <section class="tn-caps">
      <header><b>Captured settings</b><em>${models.length}</em></header>
      ${models.length ? html`<div class="tn-split">
        <div class="tn-rows">${models.slice(pg.from, pg.to).map((x, i) => { const k = pg.from + i; return html`
          <button class=${cls('tn-row', au.playing(x.t.id, x.m.id) && 'on', k === selI && 'cur')} onClick=${() => tap(k)}>
            <span class="nm">${x.m.name || 'model'}<small>${x.t.amp || x.t.title}</small></span>
            ${knobsOf(x.m.name).length ? html`<i class="t-gain">knobs</i>` : ''}
            <${PlayMark} on=${au.playing(x.t.id, x.m.id)} busy=${au.loading(x.t.id, x.m.id)} /></button>`; })}</div>
        <div class="tn-kbox"><h6>On the pedal</h6>${kn.length
          ? html`<div dangerouslySetInnerHTML=${{ __html: knobsSvg(kn, col) }}></div>`
          : html`<p class="muted">The settings are not written in this capture's name.</p>`}</div>
      </div>` : html`<div class="tn-rows"><p class="muted">No capture of this pedal on the rack yet.</p></div>`}
      <${Pager} pg=${pg} />
      ${models.length ? html`<${AuditionNote} au=${au} />` : ''}
      <div class="tn-act"><button class="mini" onClick=${onT3k}>Find more on TONE3000</button><span class="grow"></span>
        ${cur ? html`<button class="mini" onClick=${() => onOpen(cur.t)}>Pack details</button>` : ''}</div>
    </section></div>`;
}

// UN EFFET INTÉGRÉ : pas de capture, son son est ses réglages — la fiche montre ses presets d'usine
function BuiltinPanel({ e, vis, onClose }) {
  const { data } = useAsync(() => fetch('/api/block-presets/' + encodeURIComponent(e.type)).then(r => r.json()), [e.type]);
  const presets = (data && data.presets) || [];
  const pg = usePage(presets.length, 7, [e.type]);
  return html`<div class="tn-detail">
    <section class="tn-stage board"><button class="tn-back" onClick=${onClose}>‹ Pedals</button>
      <div class="tn-spot pedal">${vis ? html`<${Drawing} svg=${pedalSvg({ type: e.type, title: e.short || e.name })} align="xMidYMid" />` : ''}</div>
      <h2>${e.name}</h2>
      <div class="tn-meta"><span class="fam" style=${'--c:' + catColor(e.category)}>${CAT_LABEL[e.category] || e.category}</span>
        <span>${GOLEM_FX.has(e.type) ? 'golem-fx' : String(e.plugin || 'built-in').replace(/^\w+:\s*/, '')}</span></div>
    </section>
    <section class="tn-caps">
      <header><b>Factory presets</b><em>${presets.length}</em></header>
      <div class="tn-rows">${presets.length ? presets.slice(pg.from, pg.to).map(bp => html`<div class="tn-row">
          <span class="nm">${bp.name}${bp.desc ? html`<small>${bp.desc}</small>` : ''}</span>${bp.default ? html`<i>default</i>` : ''}</div>`)
        : html`<p class="muted">${e.note || 'No factory preset for this effect yet.'}</p>`}</div>
      <${Pager} pg=${pg} />
      <div class="tn-act"><span class="muted">A built-in effect has no capture: its sound is its settings. Add it from the Designer ▸ + drawer.</span></div>
    </section></div>`;
}

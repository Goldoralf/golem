// SPDX-License-Identifier: GPL-3.0-or-later
// Tiroir d'ajout de blocs (catégories→blocs→sims) + SimList + AmpPicker (extraits, P3).
import { html, useState, useEffect, useAsync, post, cls, esc, getCatalog, refreshCatalog } from './lib.js';
import { CAT_COLOR, ICON, MODEL_GEARS, needsModel, archOf, archKws, catLabel, GOLEM_FX } from './designer-model.js';
import { makerOf, splitGolem } from './drawer-rows.mjs';
import { loadVisuals, pedalSvg, visualsReady } from './golem-visuals.js';
import { searchDrawer, myCaptures, isMine } from './drawer-search.mjs';
import { FORMATS, selectVsts, vstFormatCounts, vstGroups, recentVsts, rememberVst, pickRecent } from './vst-host-model.mjs';

// familles d'archétypes nommés (pédales + amplis) — libellé + ordre d'affichage des sous-groupes
const FAMILY_LABELS = { overdrive: 'Overdrive', distortion: 'Distortion', fuzz: 'Fuzz', boost: 'Boost',
  clean: 'Clean', crunch: 'Crunch', 'high-gain': 'High-gain', bass: 'Bass' };
const FAMILY_ORDER = ['overdrive', 'distortion', 'fuzz', 'boost', 'clean', 'crunch', 'high-gain', 'bass'];

// ── tiroir « ajouter un bloc » : catégories → blocs → (ampli/cab) volet des sims ──
// hw = pédales MIDI INSTALLÉES (registre, /api/mappings, sans la Whammy qui a son bloc dédié) :
// elles paraissent dans une catégorie `hardware` qui n'existe que si le rack en a (bloc midi-pedal).
export function CategoryDrawer({ cats, fx, pedals, fam, post, voice, stereo, laneStereo, present, hw, onAdd, onAddPedal, onAddHw, onAddStereo, onAddVst, onClose, flat, vstHost, vstOnly }) {
  // blocs `unique` (looper, pads — docs/blocks-doctrine.md) : grisés si déjà dans le preset
  const taken = t => (present || new Set()).has(t);
  // ── CONFLITS entre blocs ────────────────────────────────────────────────────────────
  // Déclarés UNE fois dans le catalogue (`conflicts` sur le bloc standard) et appliqués
  // DANS LES DEUX SENS : sinon un catalogue à moitié rempli laisserait passer l'inverse.
  // On grise et on DIT pourquoi — un bouton mort sans explication est pire que pas de bouton.
  const nameOf = t => (fx.find(x => x.type === t) || {}).name || t;
  const conflict = e => {
    const mine = (e.conflicts || []).find(t => taken(t));
    if (mine) return mine;
    const other = fx.find(x => (x.conflicts || []).includes(e.type) && taken(x.type));
    return other ? other.type : null;
  };
  const whyBlocked = (e, t) => {
    if (t === 'backing-track' || e.type === 'backing-track')
      return `${nameOf(t)} is already here — a song is either a backing track or a standard, not both.`;
    if (t === 'drums' || e.type === 'drums')
      return `${nameOf(t)} is already here — the Standard block brings its own drums (Parts ▸ Drums).`;
    return `${nameOf(t)} is already here and conflicts with this block.`;
  };
  // Input 2 (ex-« voix ») = chaîne générique : MÊMES catégories que l'Input 1 (plus de filtre VCATS).
  const POST_CATS = ['eq', 'modulation', 'delay', 'reverb', 'pitch', 'utility'];
  const allow = c => !post || POST_CATS.includes(c);
  // `hardware` s'ajoute EN QUEUE, hors filtre de rôle : une pédale MIDI physique se patche où
  // l'utilisateur l'a câblée — le bloc n'est qu'une balise MIDI, la position dans la chaîne est
  // documentaire. La catégorie n'existe que si le rack a des pédales installées.
  const hwList = flat ? [] : (hw || []);
  // vstOnly : ouvert depuis la feuille d'un bloc indisponible — on REMPLACE ce bloc, pas d'ajout ailleurs
  const base = vstOnly ? ['vst-host'] : [...(cats.length ? cats : [...new Set(fx.map(e => e.category))]).filter(allow).filter(c => c !== 'hardware'),
                ...(vstHost && !flat ? ['vst-host'] : []),
                ...(hwList.length ? ['hardware'] : [])];
  // « Mine » EN TÊTE (2026-10-25) : tes captures importées ou faites ici, que cette lane peut jouer. Triées par
  // popularité TONE3000, elles finissaient au bas d'Amp ▸ Other ▸ Head+Cab (NAM) — la dernière ligne d'une longue liste
  const { data: catg } = useAsync(getCatalog, []);
  const mine = flat || vstOnly ? [] : myCaptures({ cats: base, fx, tones: (catg && catg.tones) || [], modelGears: MODEL_GEARS });
  const list = mine.length ? ['mine', ...base] : base;
  const [cat, setCat] = useState(vstOnly ? 'vst-host' : '');
  const [vstQuery, setVstQuery] = useState('');
  const [vstKind, setVstKind] = useState(vstOnly ? 'effect' : 'all');   // remplacer un effet : des effets d'abord
  // VST Host (maquette mockups/vst-host-list.html, 2026-10-10) : trois cases de format, un accordéon par
  // éditeur, une ligne par plugin (le tap pose le VST3), « Recent » en tête
  const [vstFormats, setVstFormats] = useState(() => Object.fromEntries(FORMATS.map(f => [f, true])));
  const [vstOpen, setVstOpen] = useState(() => new Set());
  const [vstRecent, setVstRecent] = useState(() => recentVsts());
  const [vstReload, setVstReload] = useState(0);        // relire l'inventaire (après « Rescan plugins »)
  const { data: vstData, err: vstErr } = useAsync(() => cat === 'vst-host'
    ? fetch('/api/vst-host/plugins').then(r => r.json()) : Promise.resolve(null), [cat, vstReload]);
  // OÙ INSTALLER UN PLUGIN (2026-11-09) : les dossiers que REAPER scanne ici, et « Rescan » qui le redémarre
  const [vstWhere, setVstWhere] = useState(false);
  const [vstFolders, setVstFolders] = useState(null);
  const [vstRescan, setVstRescan] = useState('');       // '' | 'confirm' | 'running' | message d'erreur
  const openWhere = () => {
    setVstWhere(!vstWhere); setVstRescan('');
    if (!vstFolders || vstFolders.error) fetch('/api/vst-host/folders').then(async r => r.ok ? r.json() : { error: true })
      .then(setVstFolders).catch(() => setVstFolders({ error: true }));
  };
  const rescan = async () => {
    if (vstRescan !== 'confirm') { setVstRescan('confirm'); return; }
    setVstRescan('running');
    const r = await fetch('/api/vst-host/rescan', { method: 'POST' }).then(async x => ({ ok: x.ok, d: await x.json().catch(() => ({})) }))
      .catch(() => ({ ok: false, d: {} }));
    if (!r.ok) { setVstRescan(r.d.error || 'REAPER could not be restarted'); return; }
    for (let i = 0; i < 60; i++) {                       // REAPER revient : l'inventaire répond de nouveau
      await new Promise(res => setTimeout(res, 3000));
      const ok = await fetch('/api/vst-host/plugins').then(x => x.ok).catch(() => false);
      if (ok && i > 1) { setVstRescan(''); setVstWhere(false); setVstReload(x => x + 1); return; }
    }
    setVstRescan('REAPER did not come back — see Settings ▸ System');
  };
  // CE QUE GOLEM PROPOSE DÉJÀ (2026-11-09) : la liste montre les plugins NOUVEAUX ; ceux qu'un bloc golem joue déjà
  // sont rangés en bas, repliés, avec leur bloc (« Use the golem block ») — pas en remplacement d'un bloc indisponible
  const vstRaw = (vstData && vstData.plugins) || [];
  const vstAll = vstRaw.filter(x => !x.block);
  const [vstKnownOpen, setVstKnownOpen] = useState(false);
  const vstKnown = vstOnly ? [] : selectVsts(vstRaw.filter(x => x.block), { kind: vstKind, query: vstQuery, stereo: !!laneStereo });
  const [vstVarOpen, setVstVarOpen] = useState(() => new Set());   // lignes dont les déclinaisons sont dépliées
  const vstCounts = vstFormatCounts(vstAll, vstKind);
  // une case sans plugin ne filtre rien : décochée ou non, elle ne peut pas vider la liste
  const vstShown = selectVsts(vstAll, { kind: vstKind, formats: FORMATS.filter(f => vstFormats[f] && vstCounts[f]), query: vstQuery, stereo: !!laneStereo });
  const vstTotal = selectVsts(vstAll).length;
  const vstByVendor = vstGroups(vstShown);
  const vstSearching = !!vstQuery.trim();
  const vstAllOpen = vstByVendor.length > 0 && vstByVendor.every(g => vstOpen.has(g.vendor));
  const vstToggleFormat = f => {
    const others = FORMATS.filter(g => g !== f && vstFormats[g] && vstCounts[g]);
    if (vstFormats[f] && !others.length) return;              // au moins un format reste coché
    setVstFormats({ ...vstFormats, [f]: !vstFormats[f] });
  };
  const vstToggleVendor = v => { const n = new Set(vstOpen); n.has(v) ? n.delete(v) : n.add(v); setVstOpen(n); };
  const vstAdd = (row, format) => { setVstRecent(rememberVst(row)); onAddVst(row.names[format] || row.name); };
  // VUE Blocks | Pedals (docs/designer-glyphs-pedals.md, maquette D) : les mêmes blocs, en lignes ou en étagère de
  // pédales ; le choix est retenu sur cet écran (préférence d'affichage, jamais un réglage du rack)
  const [view, setView0] = useState(() => { try { return localStorage.getItem('golem.drawer.view') || 'blocks'; } catch (e) { return 'blocks'; } });
  const setView = v => { setView0(v); try { localStorage.setItem('golem.drawer.view', v); } catch (e) { /* navigation privée */ } };
  const [vis, setVis] = useState(visualsReady());
  useEffect(() => { if (view === 'pedals' && !vis) loadVisuals({ effects: fx }).then(() => setVis(true)).catch(() => setView('blocks')); }, [view]);
  const [pick, setPick] = useState(null);         // 3e volet : {type,name,macro?} (sim) | {ped:archétype} (pédale nommée)
  const [gainF, setGainF] = useState('');         // filtre caractère : '' (tout) | clean | crunch | high-gain
  const [rigF, setRigF] = useState('all');        // filtre nature : all | amp (têtes) | amp-cab (full-rig)
  const activeCat = list.includes(cat) ? cat : (base[0] || '');   // « Mine » ne s'ouvre pas tout seul : le tiroir garde son départ   // fallback réactif (effects peut charger après le montage)
  // flat (lane config) : pas de colonne catégories — la liste des services directement (peu nombreux).
  // midi-pedal jamais en tuile brute : il s'ajoute UNIQUEMENT via une pédale installée (catégorie hardware).
  const items0 = (flat ? fx : fx.filter(e => e.category === activeCat)).filter(e => e.type !== 'midi-pedal' && !e.hidden);
  // archétypes nommés (pédales en « drive », amplis en « amp ») sous-groupés par famille.
  const arch0 = flat ? [] : (pedals || []).filter(a => (a.category || 'drive') === activeCat);

  // ── inventaire : captures installées par archétype ET par nature (règle unique archOf) ?
  // -> badge « n » sur chaque modèle (suit le filtre Heads|+Cab), vides grisés + en fin de famille.
  const POOL = { amp: t => (t.gear === 'amp' || t.gear === 'amp-cab') && t.format !== 'ir',
                 drive: t => t.gear === 'pedal' && t.format !== 'ir',
                 cab: t => t.gear === 'cab' || t.format === 'ir' };
  const counts = {};                              // id -> {total, amp, 'amp-cab'}
  if (arch0.length && POOL[activeCat]) {
    for (const t of (((catg && catg.tones) || []).filter(POOL[activeCat]))) {
      const a = archOf(arch0, t);
      // cabs : le badge compte les IRs (fichiers du pack), pas les packs
      const w = activeCat === 'cab' ? ((t.models || []).length || 1) : 1;
      if (a) { const c = counts[a.id] = counts[a.id] || { total: 0 }; c.total += w; c[t.gear] = (c[t.gear] || 0) + w; }
    }
  }
  const nOf = a => { const c = counts[a.id]; return !c ? 0 : rigF === 'all' ? c.total : (c[rigF] || 0); };
  // filtres : caractère (family du modèle) + nature (le modèle doit avoir ≥1 capture du type
  // demandé — un vide n'apporte rien quand on cherche une tête ou un full-rig) ; tri = pourvus
  // d'abord puis alpha (les marques se regroupent).
  const isAmpCat = activeCat === 'amp';
  const brandCat = isAmpCat || activeCat === 'cab';   // sections par MARQUE (amplis + cabs)
  const items = items0.filter(e => !isAmpCat || rigF === 'all'
    || (rigF === 'amp' ? e.type !== 'amp' : e.type !== 'amp-nam'));
  const arch = arch0
    .filter(a => !isAmpCat || !gainF || (a.family || 'crunch') === gainF)
    .filter(a => !isAmpCat || rigF === 'all' || nOf(a) > 0)
    .sort((a, b) => (nOf(b) && 1) - (nOf(a) && 1) || a.name.localeCompare(b.name));
  // clic sur un bloc : à modèle (ampli/cab) → ouvre le 3e volet ; sinon → ajout direct
  const chooseItem = e => needsModel(e.type) ? setPick({ type: e.type, name: e.name }) : onAdd(e.type);
  // ── recherche : toutes les catégories de la lane d'un coup (2026-10-25 : deux captures importées n'étaient
  // trouvables qu'en passant par Amp ▸ Other ▸ Head+Cab (NAM) ▸ recherche — quatre gestes pour un nom connu) ──
  const [q, setQ] = useState('');
  const capRow = c => html`<button class="sim-row ds-cap" onClick=${() => onAdd(c.type, c.tone)}>
    <span class="ds-nm">${esc(c.tone.amp || c.tone.title)}</span>
    <small class="ds-meta">${esc([isMine(c.tone) ? (c.tone.source === 'capture' ? 'captured here' : 'imported') : c.tone.brand,
      c.block].filter(Boolean).join(' · '))}</small></button>`;
  const found = flat || vstOnly ? null : searchDrawer(q, { cats: base, fx, archetypes: pedals || [],
    tones: (catg && catg.tones) || [], modelGears: MODEL_GEARS });
  // les archétypes nommés (pédales par famille, amplis/cabs par marque) — dans les deux présentations du tiroir
  const archSections = (() => {                      // amplis : sections par MARQUE (comme Library ▸ Amps) ; pédales : par famille
            if (!arch.length) return '';
            const unit = activeCat === 'cab' ? 'IR(s)' : 'capture(s)';
            const tile = a => { const n = nOf(a);
              return html`<button class=${cls('di', 'ped', !n && 'nocap', pick && pick.ped && pick.ped.id === a.id && 'on')}
                style=${'--tc:' + (a.color || '#ffb03a')} onClick=${() => setPick({ ped: a })}
                title=${n ? a.name + ' — ' + n + ' ' + unit + ' on the rack' : a.name + ' — no capture yet (download one from the picker)'}>
                <span class="di-ic">${a.glyph || '⬢'}</span><span class="di-nm">${brandCat ? (a.short || a.name) : a.name}</span>
                ${n ? html`<span class="di-count">${n}</span>` : ''}<span class="di-caret">›</span>
              </button>`; };
            if (brandCat) {
              const brandOfArch = a => a.brand || a.name.split(' ')[0];
              return [...new Set(arch.map(brandOfArch))].sort((a, b) => a.localeCompare(b)).map(b => html`
                <div class="di-group">${esc(b)}</div>
                ${arch.filter(a => brandOfArch(a) === b).map(tile)}`);
            }
            return FAMILY_ORDER.filter(f => arch.some(a => a.family === f)).map(fam => html`
              <div class="di-group">${FAMILY_LABELS[fam] || fam}</div>
              ${arch.filter(a => a.family === fam).map(tile)}`);
          })();
  // un bloc du catalogue, en tuile (présentation d'avant, et toute catégorie que les lignes ne couvrent pas)
  const itemTile = e => { const cf = conflict(e);
            // `blocked` (+ `why`) : posé par l'appelant quand le bloc existe mais ne peut pas jouer ICI
            // (Drum Kit sur une lane audio) — même traitement qu'un conflit : grisé, étiqueté, expliqué.
            const off = (e.unique && taken(e.type)) || !!cf || !!e.blocked;
            return html`<button class=${cls('di', pick && !pick.macro && !pick.ped && pick.type === e.type && 'on', off && 'off')}
            disabled=${off} title=${cf ? whyBlocked(e, cf) : e.blocked ? e.why : (e.unique && taken(e.type) ? 'already in this preset (unique block)' : '')}
            ${/* la couleur du BLOC d'abord, sa catégorie ensuite (2026-09-18) : les services de la
                  lane ⚙ sont tous en catégorie `utility`, donc tous gris ici alors que leurs tuiles
                  portent chacune leur teinte — le tiroir et la chaîne doivent dire la même chose. */''}
            style=${'--tc:' + (e.color || CAT_COLOR[e.category] || '#8a94a3')} onClick=${() => chooseItem(e)}>
            <span class="di-ic">${ICON[e.type] || e.icon || '▫'}</span><span class="di-nm">${e.name}</span>
            ${needsModel(e.type) ? html`<span class="di-caret">›</span>` : ''}
            ${e.blocked ? html`<span class="di-tag">${e.blocked}</span>` : ''}
            ${/* ⚠ VISIBLE, pas en infobulle : l'écran du rack est TACTILE — il n'y a pas de
                  survol, donc un `title` n'existe pas au doigt (leçon déjà payée sur le
                  bouton play des cartes). Une tuile morte sans raison est pire qu'absente. */ ''}
            ${cf ? html`<span class="di-why">${whyBlocked(e, cf)}</span>` : e.blocked ? html`<span class="di-why">${e.why}</span>` : ''}
          </button>`; };
  // ── LIGNES (maquette B) : les effets golem FX dans leur colonne, les autres blocs à côté avec leur fabricant ; en vue
  // Pedals, les mêmes en étagère de pédales (maquette D). Pas pour la recherche, le 3e volet, Mine, VST Host, Hardware.
  const useB = !flat && !vstOnly && !found && !pick && !['vst-host', 'hardware', 'mine'].includes(activeCat)
    && (items.length > 0 || arch.length > 0);
  const { gfx: gxItems, other: oxItems } = splitGolem(items, GOLEM_FX);
  const offOf = e => { const cf = conflict(e); return { cf, off: (e.unique && taken(e.type)) || !!cf || !!e.blocked }; };
  const rowOf = (e, golem) => { const { cf, off } = offOf(e); const mk = golem ? '' : makerOf(e.plugin);
    return html`<button class=${cls('dr', golem && 'g', off && 'off')} disabled=${off}
      style=${'--tc:' + (e.color || CAT_COLOR[e.category] || '#8a94a3')}
      title=${cf ? whyBlocked(e, cf) : e.blocked ? e.why : (e.unique && taken(e.type) ? 'already in this preset (unique block)' : '')}
      onClick=${() => chooseItem(e)}>
      <span class="dr-ic">${ICON[e.type] || e.icon || '▫'}</span>
      <span class="dr-tx"><span class="dr-nm">${e.name}</span>${mk ? html`<small>${esc(mk)}</small>` : ''}
        ${cf ? html`<span class="di-why">${whyBlocked(e, cf)}</span>` : e.blocked ? html`<span class="di-why">${e.why}</span>` : ''}</span>
      <span class="dr-add">${needsModel(e.type) ? '›' : '+'}</span></button>`; };
  const shelf = view === 'pedals' && vis;
  const pedalOf = e => { const { cf, off } = offOf(e);
    return html`<button class=${cls('dp', off && 'off')} disabled=${off} onClick=${() => chooseItem(e)} aria-label=${e.name}
      title=${e.name + (cf ? ' — ' + whyBlocked(e, cf) : e.blocked ? ' — ' + e.why : '')}>
      <span class="dp-svg" dangerouslySetInnerHTML=${{ __html: pedalSvg({ type: e.type, title: e.short || e.name }) }}></span>
      <span class="dp-nm">${e.short || e.name}</span></button>`; };
  // une catégorie sans golem FX (Amp, Cab, Preamp…) prend toute la largeur : une colonne vide ne dirait rien d'utile
  const bView = () => html`<div class=${cls('dbx', shelf && 'shelf', !gxItems.length && 'solo')}>
    ${!gxItems.length ? '' : html`<div class="dbx-g">
      <div class="dbx-h"><b class="dbx-mark">/g_</b><b>golem FX</b>
        ${gxItems.length ? html`<span>${gxItems.length} effect${gxItems.length > 1 ? 's' : ''}</span><em>testing</em>` : ''}</div>
      ${shelf ? html`<div class="dp-row">${gxItems.map(pedalOf)}</div>` : gxItems.map(e => rowOf(e, true))}
    </div>`}
    <div class="dbx-o">
      ${oxItems.length ? html`<div class="dbx-h"><b>Other blocks</b><span>${oxItems.length}</span></div>
        ${shelf ? html`<div class="dp-row">${oxItems.map(pedalOf)}</div>` : oxItems.map(e => rowOf(e, false))}` : ''}
      ${arch.length ? html`<div class="dbx-arch">${archSections}</div>` : ''}
    </div></div>`;
  const headTitle = pick ? (pick.ped ? pick.ped.name : pick.name) : flat ? 'Add service' : vstOnly ? 'Replace with your own plugin' : 'Add block';
  return html`<div class="drawer-scrim" onClick=${e => e.target.classList.contains('drawer-scrim') && onClose()}>
    <div class=${cls('drawer', pick && 'wide', flat && 'flat', activeCat === 'vst-host' && !flat && 'vst-wide', useB && 'rows')}>
      <div class="drawer-head"><b>${esc(headTitle)}</b>
        ${flat || vstOnly ? '' : html`<input class="drawer-search" type="search" placeholder="Search blocks and captures"
          value=${q} onInput=${e => setQ(e.target.value)} />`}
        ${flat || vstOnly ? '' : html`<div class="tb-seg dv-seg" title="The same blocks as rows or as pedals">
          <button class=${cls(view !== 'pedals' && 'on')} onClick=${() => setView('blocks')}>Blocks</button>
          <button class=${cls(view === 'pedals' && 'on')} onClick=${() => setView('pedals')}>Pedals</button></div>`}
        <button class="close" onClick=${onClose}>×</button></div>
      <div class="drawer-body">
        ${flat ? '' : html`<div class="drawer-cats">
          ${list.map(c => html`<button class=${'dc' + (c === activeCat && !found ? ' on' : '')} style=${'--tc:' + (CAT_COLOR[c] || '#8a94a3')}
            onClick=${() => { setCat(c); setPick(null); setGainF(''); setRigF('all'); setQ(''); }}>${catLabel(c)}</button>`)}
        </div>`}
        <div class="drawer-items">
          ${found ? html`
            ${!found.captures.length && !found.archetypes.length && !found.blocks.length
              ? html`<div class="di-group">Nothing on this lane matches “${esc(q.trim())}”.</div>` : ''}
            ${found.captures.length ? html`<div class="di-group">Captures on the rack</div>
              ${found.captures.map(capRow)}` : ''}
            ${found.archetypes.length ? html`<div class="di-group">Models</div>
              ${found.archetypes.map(a => html`<button class=${cls('di', 'ped', pick && pick.ped && pick.ped.id === a.id && 'on')}
                style=${'--tc:' + (a.color || '#ffb03a')} onClick=${() => { setCat(a.category || 'drive'); setPick({ ped: a }); }}>
                <span class="di-ic">${a.glyph || '⬢'}</span><span class="di-nm">${esc(a.name)}</span><span class="di-caret">›</span>
              </button>`)}` : ''}
            ${found.blocks.length ? html`<div class="di-group">Blocks</div>
              ${found.blocks.map(e => { const cf = conflict(e); const off = (e.unique && taken(e.type)) || !!cf || !!e.blocked;
                return html`<button class=${cls('di', off && 'off')} disabled=${off}
                  style=${'--tc:' + (e.color || CAT_COLOR[e.category] || '#8a94a3')} onClick=${() => chooseItem(e)}>
                  <span class="di-ic">${ICON[e.type] || e.icon || '▫'}</span><span class="di-nm">${e.name}</span>
                  ${needsModel(e.type) ? html`<span class="di-caret">›</span>` : ''}
                  ${cf ? html`<span class="di-why">${whyBlocked(e, cf)}</span>` : e.blocked ? html`<span class="di-why">${e.why}</span>` : ''}
                </button>`; })}` : ''}
          ` : html`
          ${activeCat === 'mine' ? html`<div class="di-group">Your captures — imported or made on this rack</div>${mine.map(capRow)}` : ''}
          ${!flat && isAmpCat ? html`<div class="drawer-filters">
            <div class="tb-seg" title="Gain character">
              ${[['clean', 'Clean'], ['crunch', 'Crunch'], ['high-gain', 'High']].map(([v, l]) => html`
                <button class=${cls(gainF === v && 'on')} onClick=${() => setGainF(gainF === v ? '' : v)}>${l}</button>`)}
            </div>
            <div class="tb-seg" title="Capture type — head only vs full rig (cab included)">
              <button class=${cls(rigF !== 'amp-cab' && 'on')} onClick=${() => setRigF(rigF === 'all' ? 'amp-cab' : 'all')}>Heads</button>
              <button class=${cls(rigF !== 'amp' && 'on')} onClick=${() => setRigF(rigF === 'all' ? 'amp' : 'all')}>+Cab</button>
            </div>
          </div>` : ''}
          ${activeCat === 'vst-host' ? html`<div class="vh-list">
            <div class="vh-top">
              <div class="vh-srow">
                <input class="vst-host-search" placeholder="Search plugins or vendors" value=${vstQuery}
                  onInput=${e => setVstQuery(e.target.value)} />
                <span class="vh-count"><b>${vstShown.length}</b> of ${vstTotal}</span>
                ${vstOnly ? '' : html`<button class=${cls('vh-link', 'vh-where-b', vstWhere && 'on')} onClick=${openWhere}>Where to install plugins</button>`}
              </div>
              ${vstWhere ? html`<div class="vh-where">
                <p>Copy a plugin into one of the folders REAPER scans on this machine, then tap <b>Rescan plugins</b>.</p>
                ${!vstFolders ? html`<p class="muted">Reading REAPER's folders…</p>`
                  : vstFolders.error || !(vstFolders.folders || []).length ? html`<p class="vh-where-err">REAPER's plugin folders could not be read here.</p>`
                  : html`<div class="vh-where-grid">
                  ${['VST3', 'CLAP', 'VST'].map(f => {
                    const rows = (vstFolders.folders || []).filter(x => x.format === f);
                    const best = rows.find(x => x.exists && x.writable) || rows.find(x => x.writable);
                    return rows.length ? html`<div class="vh-where-f"><b>${f}</b>
                      ${rows.map(x => html`<code class=${cls(x === best && 'best', !x.exists && 'gone')}
                        title=${x === best ? 'you can copy here without a password' : !x.exists ? 'this folder does not exist yet' : !x.writable ? 'needs an administrator password' : ''}>${esc(x.path)}</code>`)}</div>` : '';
                  })}</div>`}
                <div class="vh-where-act">
                  <span class="muted">${vstRescan === 'confirm' ? 'REAPER restarts: the sound stops for a few seconds.'
                    : vstRescan === 'running' ? 'Restarting REAPER and reading its plugins…'
                    : vstRescan ? vstRescan : 'REAPER only finds new plugins when it starts.'}</span>
                  <button class=${cls('mini', vstRescan === 'confirm' && 'danger')} disabled=${vstRescan === 'running'} onClick=${rescan}>
                    ${vstRescan === 'confirm' ? 'Tap again to restart REAPER' : 'Rescan plugins'}</button>
                </div>
              </div>` : ''}
              <div class="vst-host-filters">
                <div class="tb-seg">
                  ${[['all', 'All'], ['instrument', 'Instruments'], ['effect', 'Effects']].map(([value, label]) => html`
                    <button class=${cls(vstKind === value && 'on')} onClick=${() => setVstKind(value)}>${label}</button>`)}
                </div>
                ${FORMATS.map(f => html`<button class=${cls('vh-fmt', vstFormats[f] && vstCounts[f] && 'on')}
                    disabled=${!vstCounts[f]} onClick=${() => vstToggleFormat(f)} aria-pressed=${!!(vstFormats[f] && vstCounts[f])}>
                  <span class="vh-box"></span>${f} <small>${vstCounts[f]}</small></button>`)}
              </div>
            </div>
            ${!vstData && !vstErr ? html`<div class="di-group">Scanning REAPER plugins…</div>` : ''}
            ${vstErr ? html`<div class="di-why">${esc(String(vstErr.message || vstErr))}</div>` : ''}
            ${(vstData && vstData.error) ? html`<div class="di-why">${esc(vstData.error)}</div>` : ''}
            ${vstData && !vstShown.length && !vstKnown.length ? html`<div class="vh-empty">No plugins match. Clear the search or tick another format.</div>` : ''}
            ${(() => {
              // une déclinaison (Stereo x32, M/S…) posée telle quelle, dans son format préféré
              const addVariant = (x, v) => { setVstRecent(rememberVst(x)); onAddVst(v.name); };
              const vkey = x => x.vendor + '|' + x.title;
              const row = x => html`<div class=${cls('vh-plw', x.variants && vstVarOpen.has(vkey(x)) && 'open')}>
                <button class="vh-pl" onClick=${() => vstAdd(x, x.formats[0])} title=${x.title + (x.variant ? ' (' + x.variant + ')' : '') + ' — ' + x.vendor}>
                  <span class=${cls('vh-ic', x.kind === 'instrument' && 'ins')}>${x.kind === 'instrument' ? '♫' : '◈'}</span>
                  <span class="vh-nm">${esc(x.title)}${x.variant ? html`<span class="vh-gblock">${esc(x.variant)}</span>` : ''}</span>
                  <span class="vh-pf">${x.variants ? html`<span onClick=${e => { e.stopPropagation();
                      const n = new Set(vstVarOpen); n.has(vkey(x)) ? n.delete(vkey(x)) : n.add(vkey(x)); setVstVarOpen(n); }}
                      title="other versions of this plugin (channels, bands)">+${x.variants.length - 1}</span>` : ''}
                    ${x.formats.map((f, i) => html`<span class=${cls(i === 0 && 'best')}
                    onClick=${e => { e.stopPropagation(); vstAdd(x, f); }} title=${'Add the ' + f + ' version'}>${f}</span>`)}</span>
                </button>
                ${x.variants && vstVarOpen.has(vkey(x)) ? html`<div class="vh-vars">${x.variants.map(v => html`<button class="vh-var"
                    onClick=${() => addVariant(x, v)} title=${v.title}>${esc(v.label || 'default')}</button>`)}</div>` : ''}
              </div>`;
              const recent = vstSearching ? [] : pickRecent(vstShown, vstRecent);
              return html`
                ${recent.length ? html`<div class="vh-sect">Recent</div><div class="vh-grid vh-recent">${recent.map(row)}</div>` : ''}
                ${!vstSearching && vstByVendor.length ? html`<div class="vh-sect">By vendor · ${vstByVendor.length}
                  <button class="vh-link" onClick=${() => setVstOpen(vstAllOpen ? new Set() : new Set(vstByVendor.map(g => g.vendor)))}>
                    ${vstAllOpen ? 'Collapse all' : 'Expand all'}</button></div>` : ''}
                ${vstByVendor.map(g => {
                  const open = vstSearching || vstOpen.has(g.vendor);
                  const ins = g.items.filter(x => x.kind === 'instrument').length, fx = g.items.length - ins;
                  const kinds = [fx && `${fx} effect${fx > 1 ? 's' : ''}`, ins && `${ins} instrument${ins > 1 ? 's' : ''}`].filter(Boolean).join(' · ');
                  return html`<div class=${cls('vh-vd', open && 'open')}>
                    <button class="vh-vd-h" onClick=${() => !vstSearching && vstToggleVendor(g.vendor)} aria-expanded=${open}>
                      <span class="vh-car">▸</span><b>${esc(g.vendor)}</b><span class="vh-kinds">${kinds}</span><span class="vh-n">${g.items.length}</span>
                    </button>
                    ${open ? html`<div class="vh-grid">${g.items.map(row)}</div>` : ''}
                  </div>`;
                })}
                ${vstKnown.length ? html`<div class="vh-sect vh-known-h">${vstKnown.length} plugin${vstKnown.length > 1 ? 's' : ''} golem already uses
                  <button class="vh-link" onClick=${() => setVstKnownOpen(!vstKnownOpen)}>${vstKnownOpen || vstSearching ? 'Hide' : 'Show'}</button></div>
                  ${vstKnownOpen || vstSearching ? html`<div class="vh-grid vh-known">${vstKnown.map(x => html`<button class="vh-pl"
                      onClick=${() => onAdd(x.block)} title=${'Add the golem block ' + x.blockName + ' — its settings and presets'}>
                      <span class="vh-ic">▣</span>
                      <span class="vh-nm">${esc(x.title)}<span class="vh-gblock">golem block: ${esc(x.blockName)}</span></span>
                      <span class="vh-pf"><span onClick=${e => { e.stopPropagation(); vstAdd(x, x.formats[0]); }}
                        title=${'Add the plugin itself (' + x.formats[0] + ') instead of the golem block'}>VST</span></span>
                    </button>`)}</div>` : ''}` : ''}`;
            })()}
          </div>` : ''}
          ${activeCat === 'hardware' ? html`<div class="di-group">Installed MIDI pedals</div>
            ${hwList.map(pd => html`<button class="di" style=${'--tc:' + (CAT_COLOR.hardware || '#e06ac0')}
              title=${pd.name + ' — ' + pd.modes + ' settings from the pedal registry'}
              onClick=${() => onAddHw && onAddHw(pd)}>
              <span class="di-ic">⇄</span><span class="di-nm">${esc(pd.name)}</span>
              ${/* confiance de la TABLE (docs/pedal-registry.md) — VISIBLE, pas en infobulle :
                    une table importée non vérifiée peut jouer un demi-ton à côté sur scène. */ ''}
              ${pd.confidence && pd.confidence !== 'verified' ? html`<span class="di-why">table ${pd.confidence} — verify it on the pedal before a gig</span>` : ''}
            </button>`)}` : ''}
          ${useB ? bView() : html`${archSections}
          ${arch.length ? html`<div class="di-group">Other</div>` : ''}
          ${items.map(itemTile)}`}
          ${activeCat === 'amp' && stereo ? html`<button class=${cls('di', 'macro', pick && pick.macro && 'on')} style=${'--tc:' + CAT_COLOR.amp}
            title="NAM head + 2 separate cabs routed OUT 1 / OUT 2 (stereo)" onClick=${() => setPick({ type: 'amp-nam', name: 'Amp + 2 cabs (stereo)', macro: true })}>
            <span class="di-ic">⑃</span><span class="di-nm">Amp + 2 cabs<br/>stereo</span><span class="di-caret">›</span>
          </button>` : ''}
          `}
        </div>
        ${pick ? html`<div class="drawer-sims">
          ${pick.ped ? html`<${PedalPicker} archetype=${pick.ped} allowEmpty=${true} fam=${fam} initialRig=${rigF}
              onPick=${t => onAddPedal(pick.ped.id, t)} onEmpty=${() => onAddPedal(pick.ped.id, null)} />`
          : html`${pick.macro ? html`<div class="sim-hint">Choose the amp head — 2 empty cabs (L/R) are added on OUT 1 & OUT 2. Pick each IR after.</div>` : ''}
            <${SimList} gears=${MODEL_GEARS[pick.type]} type=${pick.macro ? 'amp-nam' : pick.type} onPick=${t => pick.macro ? onAddStereo(t) : onAdd(pick.type, t)} />`}
        </div>` : ''}
      </div>
    </div></div>`;
}

// ── picker de capture pour une PÉDALE NOMMÉE (docs/archive/named-pedals.md) : deux tiers —
// captures INSTALLÉES qui matchent l'archétype (sélection directe) + résultats TONE3000
// TÉLÉCHARGEABLES (install à la demande, réutilise /api/t3k/search + /api/t3k/install). ──
function PedalPicker({ archetype, onPick, onEmpty, allowEmpty, fam, initialRig }) {
  const { data: cat } = useAsync(getCatalog, []);
  // gears acceptés : pédales = ['pedal'] ; AMPLIS = ['amp','amp-cab'] (toutes les captures du
  // modèle, têtes seules comprises — le type de bloc posé suivra la capture choisie).
  const gearsArr = archetype.gears || [archetype.gear || 'pedal'];
  const [rigF, setRigF] = useState(initialRig || 'all');   // segmenté Heads|+Cab (amplis), pré-réglé par le tiroir
  // mots-clés de rattachement : match + aliases (mêmes règles que Library ▸ Amps)
  const kws = [archetype.match || archetype.name, ...(archetype.aliases || [])]
    .filter(Boolean).map(s => String(s).toLowerCase());
  // famille (guitar/bass) : le rôle de l'entrée filtre les captures TONE3000 (famOf = champ ou heuristique)
  const famOf = t => t.family || (((t.tags || []).includes('bass') || t.style === 'bass') ? 'bass' : 'guitar');
  const inFam = t => !fam || famOf(t) === fam;
  // pool par nature : cabs = tout ce qui est IR (gear cab OU format ir, même mal étiqueté) ;
  // amplis/pédales = leur gear, JAMAIS les packs d'IR (cab-sim .wav -> bloc Cab uniquement)
  const isCabPick = gearsArr.includes('cab');
  const installed = (((cat && cat.tones) || [])
    .filter(t => isCabPick ? (t.gear === 'cab' || t.format === 'ir')
                           : gearsArr.includes(t.gear) && t.format !== 'ir').filter(inFam)
    .filter(t => rigF === 'all' || t.gear === rigF)
    .filter(t => { const txt = ((t.amp || t.title || '') + ' ' + (t.brand || '')).toLowerCase();
      return kws.some(k => txt.includes(k)); })
    .sort((a, b) => (b.downloads || 0) - (a.downloads || 0))).slice(0, 24);
  const [t3k, setT3k] = useState(null);         // null=recherche | {err} | [tones]
  const [dl, setDl] = useState(null);           // id en cours d'install
  const [err, setErr] = useState('');
  useEffect(() => { let live = true; setT3k(null); setErr(''); setDl(null);
    fetch('/api/t3k/search?q=' + encodeURIComponent(archetype.match || archetype.name) + '&gears=' + gearsArr.join('_'))
      .then(r => r.json())
      .then(d => { if (live) setT3k(d && d.error ? { err: d.error } : ((d && d.tones) || []).filter(x => !x.installed).slice(0, 12)); })
      .catch(() => { if (live) setT3k({ err: 'offline' }); });
    return () => { live = false; };
  }, [archetype.id]);
  const install = t => installFromT3k(t, { setDl, setErr, onPick });
  const list = (Array.isArray(t3k) ? t3k : []).filter(inFam)
    .filter(t => rigF === 'all' || t3kGears(t).includes(rigF));
  const cabTag = g => g === 'amp-cab' ? html` <span class="pp-cab">+CAB</span>` : '';
  return html`<div class="ped-pick">
    ${gearsArr.length > 1 ? html`<div class="tb-seg pp-seg" title="Capture type — head only vs full rig (cab included)">
      <button class=${cls(rigF !== 'amp-cab' && 'on')} onClick=${() => setRigF(rigF === 'all' ? 'amp-cab' : 'all')}>Heads</button>
      <button class=${cls(rigF !== 'amp' && 'on')} onClick=${() => setRigF(rigF === 'all' ? 'amp' : 'all')}>+Cab</button>
    </div>` : ''}
    ${allowEmpty ? html`<button class="pp-empty" onClick=${onEmpty}>＋ Add empty — pick a capture later</button>` : ''}
    <div class="pp-sec">Installed captures</div>
    ${installed.length ? html`<div class="pp-rows">
      ${installed.map(t => html`<button class="pp-row" onClick=${() => onPick(t)}>
        <span class="pp-nm">${esc(t.amp || t.title)}${cabTag(t.gear)}</span><small>${esc(t.brand || '')}${(t.models || []).length > 1 ? ' · ' + t.models.length + (isCabPick ? ' IRs' : ' mics') : ''}</small></button>`)}
    </div>` : html`<div class="pp-none muted">none installed — download one below</div>`}
    <div class="pp-sec">On TONE3000${t3k === null ? ' · searching…' : ''}</div>
    ${t3k === null ? html`<div class="muted pp-load">…</div>`
      : t3k.err ? html`<div class="muted">TONE3000 unavailable — connect it in Settings ▸ Connect ▸ TONE3000.</div>`
      : list.length ? html`<div class="pp-rows">
          ${list.map(t => html`<button class=${cls('pp-row t3k', dl === t.id && 'dl')} disabled=${dl != null} onClick=${() => install(t)}>
            <span class="pp-nm">${esc(t.title)}${cabTag(t3kGears(t).includes('amp-cab') ? 'amp-cab' : '')}</span><small>${dl === t.id ? 'installing…' : '⬇ ' + (t.downloads || 0) + (t.a2 ? ' · A2' : '')}</small></button>`)}
        </div>`
      : html`<div class="muted">no match on TONE3000.</div>`}
    ${err ? html`<div class="pp-err">✗ ${esc(err)}</div>` : ''}
  </div>`;
}

// gear d'un résultat T3K (string, parfois multi « amp,amp-cab ») -> liste propre
const t3kGears = t => String(t.gear || '').split(',').map(s => s.trim()).filter(Boolean);
// Installe une capture TONE3000 puis la REND au sélecteur (pick) : partagé par le picker des
// pédales nommées et par SimList — un seul chemin d'installation, un seul suivi de progression.
async function installFromT3k(t, { setDl, setErr, onPick }) {
  setDl(t.id); setErr('');
  const r = await post('/api/t3k/install', { id: t.id }).catch(() => ({ error: 'network' }));
  if (r && r.error) { setErr(r.error); setDl(null); return; }
  for (let i = 0; i < 200; i++) {                              // ~5 min max, poll 1,5 s
    await new Promise(res => setTimeout(res, 1500));
    const s = await fetch('/api/t3k/status').then(x => x.json()).catch(() => ({}));
    if (s.phase === 'done') { refreshCatalog();
      // gear transmis : le type de bloc posé (Head vs Head+Cab) suit la capture fraîchement installée.
      // models transmis (outboard, 2026-09-14) : le modèle par défaut se choisit dans le pack (capture-gain.js)
      const full = await getCatalog().then(c => ((c && c.tones) || []).find(x => String(x.id) === String(t.id))).catch(() => null);
      onPick({ id: t.id, amp: t.title, gear: full && full.gear ? full.gear : t3kGears(t).includes('amp') && !t3kGears(t).includes('amp-cab') ? 'amp' : t3kGears(t)[0],
               models: (full && full.models) || [] }); return; }
    if (s.phase === 'error') { setErr(s.error || 'install failed'); setDl(null); return; }
  }
  setErr('timeout'); setDl(null);
}

// buckets « caractère / gain » (regroupent des tags TONE3000) — filtre OR entre buckets cochés
const CHAR_BUCKETS = [
  ['clean', 'Clean', ['clean']],
  ['crunch', 'Crunch', ['crunch', 'breakup', 'overdrive']],
  ['high', 'High-gain', ['high-gain', 'high gain', 'distortion', 'djent', 'metal', 'saturated']],
];
// tris disponibles : [clé, label, comparateur]
const SIM_SORTS = [
  ['pop', '🔥', 'Popular (downloads)', (a, b) => (b.downloads || 0) - (a.downloads || 0)],
  ['fav', '★', 'Favorites', (a, b) => (b.favorites || 0) - (a.favorites || 0)],
  ['az', 'A→Z', 'Name A→Z', (a, b) => String(a.amp || a.title).localeCompare(String(b.amp || b.title))],
];
const toggleIn = (arr, v) => arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v];

// liste de sims (captures TONE3000) filtrée par gear + facettes (marque, caractère, style, multi-micros),
// recherche + tri. Partagée par le tiroir d'ajout et le « changer de modèle » du panneau de réglages.
export function SimList({ gears, type, current, onPick }) {
  const { data } = useAsync(getCatalog, []);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('pop');
  const [brand, setBrand] = useState('');       // '' = toutes marques
  const [chars, setChars] = useState([]);        // buckets gain actifs (OR)
  const [styles, setStyles] = useState([]);      // styles actifs (OR)
  const [multi, setMulti] = useState(false);     // ne garder que ≥2 prises de micro
  const [fam, setFam] = useState('');            // section basse : '' = tout, 'guitar' | 'bass'

  // famille : champ explicite (tones-index, éditable dans Library ▸ Amps) sinon heuristique tag/style
  const famOf = t => t.family || (((t.tags || []).includes('bass') || t.style === 'bass') ? 'bass' : 'guitar');
  const set = new Set(gears || []);
  const outboard = set.has('outboard');                                       // préampli/compresseur capturé : un modèle = un RÉGLAGE, pas un micro
  // captures du bon type de bloc : la nature, ET le bloc qui la joue (catalogue `plays`, bridge/playable.py) — sinon un
  // préampli NAM s'offrait à l'ir-fx, ou l'IR d'un écho au préampli (docs/library-tones.md §7)
  const pool = ((data && data.tones) || []).filter(t => set.has(t.gear) && (!type || !t.plays || t.plays.includes(type)));
  const brandOpts = [...new Set(pool.map(t => t.brand).filter(Boolean))].sort();
  const styleOpts = [...new Set(pool.map(t => t.style).filter(Boolean))].sort();

  const matchChar = t => {
    if (!chars.length) return true;
    const ts = new Set((t.tags || []).map(x => String(x).toLowerCase()));
    return chars.some(c => (CHAR_BUCKETS.find(b => b[0] === c) || [])[2].some(tag => ts.has(tag)));
  };
  const cmp = (SIM_SORTS.find(s => s[0] === sort) || SIM_SORTS[0])[3];
  const sims = pool
    .filter(t => !q || ((t.amp || t.title) + ' ' + (t.brand || '')).toLowerCase().includes(q))
    .filter(t => !fam || famOf(t) === fam)
    .filter(t => !brand || t.brand === brand)
    .filter(t => !styles.length || styles.includes(t.style))
    .filter(matchChar)
    .filter(t => !multi || (t.models || []).length >= 2)
    // tes captures D'ABORD, puis le tri choisi — et avant la coupe à 120 : à 0 téléchargement, une capture importée
    // finissait dernière, ou hors de la liste dès 120 sims (2026-10-25)
    .slice().sort((a, b) => (isMine(b) - isMine(a)) || cmp(a, b)).slice(0, 120);
  const nMine = sims.filter(isMine).length;

  const active = brand || chars.length || styles.length || multi || fam;
  const reset = () => { setBrand(''); setChars([]); setStyles([]); setMulti(false); setFam(''); };

  // ── TONE3000 depuis le même champ de recherche (2026-09-13) : « changer la capture »
  // d'un bloc pedal-nam ne proposait que l'installé — les pédales capturées sur TONE3000 (Big
  // Muff, Klon…) n'étaient joignables que par Library ▸ FX blocks. Même règle que le picker des
  // pédales nommées : les gears du BLOC filtrent la recherche, l'installation rend la capture
  // au sélecteur. Dès 2 caractères, hors de l'installé.
  const [t3k, setT3k] = useState(null);         // null = rien demandé | {err} | [tones]
  const [dl, setDl] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (q.length < 2) { setT3k(null); return; }
    let live = true; const timer = setTimeout(() => {
      fetch('/api/t3k/search?q=' + encodeURIComponent(q) + '&gears=' + (gears || []).join('_'))
        .then(r => r.json())
        .then(d => { if (live) setT3k(d && d.error ? { err: d.error } : ((d && d.tones) || []).filter(x => !x.installed).slice(0, 12)); })
        .catch(() => { if (live) setT3k({ err: 'offline' }); });
    }, 400);
    return () => { live = false; clearTimeout(timer); };
  }, [q, (gears || []).join('_')]);
  const t3kList = (Array.isArray(t3k) ? t3k : []).filter(t => !fam || famOf(t) === fam);

  return html`<div class="sim-list">
    <input class="sim-search" placeholder="Search installed — or type to search TONE3000…" value=${q} onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
    <div class="sim-bar">
      ${/* outboard (préampli/compresseur capturé) : pas de famille guitare/basse — l'entrée (mic/DI/line)
            se lit dans le nom du MODÈLE, et le défaut suit le rôle de la lane (capture-gain.js) */ ''}
      ${set.has('outboard') ? '' : html`<select class="sim-brand" value=${fam} onChange=${e => setFam(e.target.value)} title="instrument family">
        <option value="" selected=${!fam}>Guitar + Bass</option>
        <option value="guitar" selected=${fam === 'guitar'}>Guitar</option>
        <option value="bass" selected=${fam === 'bass'}>Bass</option>
      </select>`}
      <select class="sim-brand" value=${brand} onChange=${e => setBrand(e.target.value)}>
        <option value="" selected=${!brand}>All brands</option>
        ${brandOpts.map(b => html`<option value=${b} selected=${brand === b}>${b}</option>`)}
      </select>
      <div class="sim-sort">
        ${SIM_SORTS.map(([k, lbl, ttl]) => html`<button class=${cls('ss', sort === k && 'on')} title=${ttl} onClick=${() => setSort(k)}>${lbl}</button>`)}
      </div>
    </div>
    <div class="sim-chips">
      ${CHAR_BUCKETS.map(([k, lbl]) => html`<button class=${cls('schip', chars.includes(k) && 'on')} onClick=${() => setChars(toggleIn(chars, k))}>${lbl}</button>`)}
      <button class=${cls('schip', multi && 'on')} title=${outboard ? 'only packs with ≥2 gain settings' : 'only captures with ≥2 mic takes'} onClick=${() => setMulti(!multi)}>${outboard ? '⇅ settings' : '⇅ mics'}</button>
      ${active ? html`<button class="schip clear" title="clear filters" onClick=${reset}>× reset</button>` : ''}
    </div>
    ${styleOpts.length > 1 ? html`<div class="sim-chips">
      ${styleOpts.map(s => html`<button class=${cls('schip sm', styles.includes(s) && 'on')} onClick=${() => setStyles(toggleIn(styles, s))}>${s}</button>`)}
    </div>` : ''}
    <div class="sim-count muted">${data ? sims.length + ' sim' + (sims.length > 1 ? 's' : '') : 'loading…'}${active ? ' · filtered' : ''}</div>
    <div class="sim-rows">
      ${data && !sims.length ? html`<div class="muted sim-empty-msg">no sim matches.</div>` : ''}
      ${sims.map((t, i) => html`${nMine && i === 0 ? html`<div class="pp-sec">Yours · imported or made on this rack</div>` : ''}
      ${nMine && i === nMine ? html`<div class="pp-sec">All captures</div>` : ''}
      <button class=${cls('sim-row', current && String(current) === String(t.id) && 'on')} onClick=${() => onPick(t)}>
        <span class=${'badge style-' + (t.style || 'rock')}>${esc(t.brand || (isMine(t) ? 'Mine' : '—'))}</span>
        <span class="sim-nm">${esc(t.amp || t.title)}</span>
        ${/* POIDS DE LA CAPTURE — mesuré : du simple au quintuple de CPU entre la plus légère
              et la plus lourde de la bibliothèque (tools/bench-lanes.py). Ça décide quand six
              lanes tournent ensemble. Le badge ne paraît QUE s'il dit quelque chose : 95 % des
              captures pèsent 288 Ko, l'afficher partout masquerait les 34 lourdes. */''}
        ${capLoad(t)}
        <small class="sim-meta">${t.echo ? html`<span class="echo-chip" title=${`${t.echo.bad}/${t.echo.files} IR carry a late impulse (${t.echo.worst_ms} ms) — played cut before the echo`}>⚠ echo</span> ` : ''}${(t.models || []).some(m => String(m.arch) === '2') ? html`<span class="a2-chip">A2</span> ` : ''}${sort === 'fav' ? '★' + (t.favorites || 0) : (t.models || []).length > 1 ? (t.models.length + (outboard ? ' settings · ⬇' : ' mics · ⬇') + (t.downloads || 0)) : '⬇' + (t.downloads || 0)}</small>
      </button>`)}
    </div>
    ${q.length >= 2 ? html`<div class="pp-sec">On TONE3000${t3k === null ? ' · searching…' : ''}</div>
      ${t3k === null ? html`<div class="muted pp-load">…</div>`
        : t3k.err ? html`<div class="muted">TONE3000 unavailable — connect it in Settings ▸ Connect ▸ TONE3000.</div>`
        : t3kList.length ? html`<div class="pp-rows">
            ${t3kList.map(t => html`<button class=${cls('pp-row t3k', dl === t.id && 'dl')} disabled=${dl != null}
                onClick=${() => installFromT3k(t, { setDl, setErr, onPick })}>
              <span class="pp-nm">${esc(t.title)}${t3kGears(t).includes('amp-cab') ? html` <span class="pp-cab">+CAB</span>` : ''}</span>
              <small>${dl === t.id ? 'installing…' : '⬇ ' + (t.downloads || 0) + (t.a2 ? ' · A2' : '')}</small></button>`)}
          </div>`
        : html`<div class="muted">no match on TONE3000.</div>`}
      ${err ? html`<div class="pp-err">✗ ${esc(err)}</div>` : ''}` : ''}
  </div>`;
}

// « changer de modèle » d'un bloc ampli/cab existant (depuis le panneau de réglages). Réutilise SimList,
// filtré par le TYPE du bloc (mêmes gears que le tiroir d'ajout). current = ref actuel (surligné).
// Poids d'un TONE = le plus lourd de ses modèles (c'est celui qu'on risque de charger).
// Rend '' pour 95 % de la bibliothèque — un badge partout ne serait plus un badge.
export const capLoad = t => {
  const ms = t.models || [];
  if (ms.some(m => m.load === 'heavy')) {
    const ko = Math.max(...ms.filter(m => m.bytes).map(m => m.bytes)) / 1024;
    return html`<span class="cap-load heavy" title=${'Heavy capture (' + Math.round(ko) + ' KB) — costs several times more CPU than an average one. Matters when several lanes run at once.'}>heavy</span>`;
  }
  if (ms.length && ms.every(m => m.load === 'light')) {
    return html`<span class="cap-load light" title="Light capture — cheap on CPU. Good when several lanes run at once.">light</span>`;
  }
  return '';
};

export function AmpPicker({ type, current, onPick, onClose, archetype }) {
  const gears = MODEL_GEARS[type] || ['amp', 'amp-cab'];
  const title = archetype ? archetype.name : type === 'cab' ? 'Choose a cab (IR)' : type === 'amp-nam' ? 'Choose a head (NAM)'
    : type === 'pedal-nam' ? 'Choose a pedal (NAM capture)' : type === 'preamp-nam' ? 'Choose a preamp (NAM capture)'
    : type === 'comp-nam' ? 'Choose a compressor (NAM capture)' : type === 'ir-fx' ? 'Choose an impulse response (spring, echo, reverb)'
    : 'Choose a head+cab (NAM)';
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card">
      <button class="close" onClick=${onClose}>×</button>
      <h2>${esc(title)}</h2>
      ${archetype ? html`<${PedalPicker} archetype=${archetype} allowEmpty=${false} onPick=${onPick} onEmpty=${onClose} />`
        : html`<${SimList} gears=${gears} type=${type} current=${current} onPick=${onPick} />`}
    </div></div>`;
}

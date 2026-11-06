// SPDX-License-Identifier: GPL-3.0-or-later
// Songs ▸ Patches — le SON D'UN MUSICIEN (docs/patches.md), au MÊME langage graphique que
// l'onglet Presets (demande 2026-07-31) : mêmes cartes plist/prow, même mini-flow — mais
// UNE seule lane (la chaîne du patch), et un panneau droit d'identité (nom, personne, usages)
// à la place des scènes. Le filtre de rôle est le segmenté habituel (tb-seg), plus de <select>.
// ✎ ouvre le patch DANS LE DESIGNER comme draft lié : on le joue, on le modifie, et le chip ⛓
// « Update the patch » repousse la correction vers les N morceaux.
import { useFactoryShow, keepFactory } from './factory-show.js';
import { html, useState, useAsync, post, del, cls, esc, setSubToolbar, setTopAction, useEffect, openInDesigner, useRev, bankNo } from './lib.js';
import { menuEntry as startupEntry, isHome } from './startup-model.mjs';   // l'accueil au démarrage (mockups/startup-home.html)
import { ListToolbar, useViewedList } from './list-toolbar.js';
import { BankPicker } from './page-setlists.js';
import { blkColor, ICON, blank, blockContent, patchDraft, hydrateBlockMeta } from './designer-model.js';
import { NEW_ROLES } from './designer-browse.js';       // les quatre instruments d'un patch neuf — une seule liste
import { FeatChips } from './browser-rail.js';             // les blocs spéciaux, comme le menu « With » du Designer

// « ▤ MAKE A SONG » (docs/patches.md §4 bis) : un morceau naît du patch entier — son, scènes, stomps,
// backing — et s'ouvre dans le Designer sur son ⚙, là où se posent la backing et l'arrangement. Le patch
// reste intact ; un nom déjà pris est suffixé par le bridge, jamais écrasé. Partagé avec la sound list.
export async function makeSongFromPatch(patchId, name) {
  const r = await post('/api/patches/' + encodeURIComponent(patchId) + '/song', name ? { name } : {})
    .catch(e => ({ error: (e.body && e.body.error) || String(e) }));
  if (r && r.id) openInDesigner(r.id, 'cfg');
  return r;
}

// rôle → classe de style des cartes (la palette de genres, comme les presets)
const ROLE_STYLE = { guitar: 'rock', bass: 'bass', voice: 'jazz', keys: 'blues', drums: 'metal', pads: 'funk' };
const ROLE_REALM = { voice: 'voice', keys: 'keys' };          // le reste vit dans le realm guitar
// Le nom auto d'un patch se termine par « · guitar » (create_from_lane) alors que la carte
// affiche DÉJÀ le rôle à droite et son tag en bas : l'instrument apparaissait TROIS fois.
// Retiré à l'AFFICHAGE seulement — le nom est de la donnée utilisateur (même règle que le
// Designer, docs/patches.md §15.6 bis).
const shortName = n => String(n || '').replace(/\s*·\s*(guitar|bass|voice|keys|keys-pads|pads|line)\s*$/i, '');

// ── le mini-flow d'un patch : UNE lane, mêmes classes que MiniChain (mflow/mc-blk/mf-*) ──
// un bloc est-il ÉTEINT dans cette scène ? Un stomp cliqué (ov = {switch: bool}) prime sur la scène ;
// sinon la table `blocks` de la scène (id → on/off) ; sinon le bypass de base. Miroir de la page Presets.
export const patchBlockOff = (sc, b, ov) => {
  if (ov && b.foot != null && b.foot in ov) return !ov[b.foot];
  const t = (sc && sc.blocks) || {};
  if (b.id in t) return t[b.id] === false;
  return !!b.bypass;
};
const patchLaneMuted = (sc, br) => !!(sc && br && br.id && (((sc.branches || sc.lanes) || {})[br.id] || {}).mute === true);

function PatchFlow({ chain, role, fxShort, scene, ov }) {
  const blk = (b, muted) => { const ct = blockContent(b, null);
    return html`<span class=${cls('mc-blk', (muted || patchBlockOff(scene, b, ov)) && 'off')} style=${'--tc:' + blkColor(b.type)}
      title=${(ct ? fxShort(b.type) + ' · ' + ct : b.type) + (b.foot ? ' — switch ' + b.foot : '')}>
      <i>${ICON[b.type] || '▫'}</i><em>${esc(ct || fxShort(b.type))}</em></span>`; };
  const inBox = html`<span class="mf-io in"><span class="mf-in-row">IN</span><em>${esc(role)}</em></span>`;
  const outBox = html`<span class="mf-io out"><span class="mf-in-row">OUT</span><em>1·2</em></span>`;
  const sp = chain && chain.split;
  const blocks = (chain && (chain.pre || chain.chain)) || [];
  return html`<div class="mflow">
    ${inBox}
    ${blocks.map(b => blk(b))}
    ${sp && (sp.branches || []).length ? html`
      <span class="mf-brk">{</span>
      <div class="mf-lanes">${sp.branches.map(br => { const m = patchLaneMuted(scene, br);
        return html`<div class=${cls('mf-lane', m && 'muted-lane')}>${(br.blocks || []).map(b => blk(b, m))}</div>`; })}</div>
      ${sp.mode !== 'fanout' ? html`<span class="mf-brk">}</span>` : ''}` : ''}
    ${(chain && chain.post || []).map(b => blk(b))}
    ${outBox}
  </div>`;
}

export function PatchesPage({ rig } = {}) {
  const facShow = useFactoryShow();          // l'usine masquée par sorte (Settings ▸ Content ▸ Factory)
  const contentRev = useRev('content_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data, reload } = useAsync(() => Promise.all([
    fetch('/api/patches').then(r => r.json()),
    fetch('/api/band').then(r => r.json()),
    fetch('/api/presets').then(r => r.json()),
    // le catalogue APPLIQUÉ (glyphes et couleurs des blocs) : sans lui, les blocs spéciaux de la carte n'ont ni
    // pictogramme ni couleur — c'est le Designer qui le chargeait, pas cette page (2026-10-18)
    fetch('/api/effects').then(r => r.json()).then(d => { hydrateBlockMeta(d.effects || d, d); return d; }),
    fetch('/api/setlists').then(r => r.json()),
  ]), [contentRev]);
  const [qRaw, setQ] = useState('');
  const q = qRaw.trim().toLowerCase();
  const [role, setRole] = useState('all');
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);

  const patches = (data && data[0] && data[0].patches) || [];
  const band = (data && data[1]) || { people: [] };
  const nPresets = ((data && data[2]) || []).length;
  const fxDefs = ((data && data[3]) && (data[3].effects || data[3])) || [];
  const fxShort = t => { const d = fxDefs.find(e => e.type === t) || {}; return d.short || d.name || t; };
  const people = band.people || [];
  const personName = pid => ((people.find(x => x.id === pid) || {}).name) || pid;
  // LES CINQ INSTRUMENTS, TOUJOURS (2026-09-23 : « pas de filtre Drums ou Keys ») — les chips étaient
  // déduites des patches existants : un rôle n'avait de filtre qu'une fois un patch sauvé, et Drums/Keys
  // n'existaient pas à l'écran. Même liste et même ordre que « + Add » et que le PatchBrowser du Designer ;
  // un rôle sans patch reste VISIBLE, éteint (`dead`) : une commande qui n'apparaît qu'après coup se cherche.
  const counts = patches.reduce((m, x) => { const r = x.role || 'guitar'; m[r] = (m[r] || 0) + 1; return m; }, {});
  const roles = [...NEW_ROLES.map(r => r[0]), ...[...new Set(patches.map(x => x.role || 'guitar'))].filter(r => !NEW_ROLES.some(n => n[0] === r)).sort()];

  // ── CLOISONNÉ (2026-10-08) : Patches ↔ BANKS (les listes de sons), comme Presets ↔ Setlists. La bank
  // REGARDÉE se choisit dans la barre — elle ne change pas ce que joue le pédalier ; ses #NN sont ceux des cartes.
  const slD = (data && data[4]) || {};
  const soundLists = (slD.setlists || []).filter(x => x.kind === 'sounds');
  const [viewId, setViewId] = useViewedList('patches', soundLists, slD.active || '');
  const viewBk = soundLists.find(x => x.id === viewId) || null;
  const bankSlots = (viewBk && viewBk.presets) || [];
  const slotOf = id => bankSlots.indexOf('patch:' + id);
  const [inBank, setInBank] = useState('both');      // 'both' | 'in' | 'out'
  const [sort, setSort] = useState('bank');
  const [tag, setTag] = useState('all');
  const [person, setPerson] = useState('all');
  const allTags = [...new Set(patches.flatMap(x => x.tags || []))].sort();
  const persons = [...new Set(patches.map(x => x.person).filter(Boolean))];
  const [bankPick, setBankPick] = useState(null);    // patch dont on choisit la bank (# de la carte)
  const putInBank = async (id, slot) => {
    const n = [...bankSlots]; while (n.length <= slot) n.push('');
    const old = n.indexOf('patch:' + id); if (old >= 0) n[old] = '';
    n[slot] = 'patch:' + id;
    await post('/api/setlists/' + encodeURIComponent(viewId) + '/presets', { presets: n }).catch(() => null);
    setBankPick(null); reload();
  };

  // ＋ New patch (§13) : le mode patch EST une lane — un banc VIDE s'ouvre dans le Designer,
  // on joue en construisant, « Save as patch » naît du banc. Le rôle suit le filtre courant.
  // « + Add » demande l'INSTRUMENT (2026-09-08) : le rôle décide du tiroir, des captures et
  // de ce que l'IA propose — un banc « guitar » par défaut condamnait la basse, la voix et le
  // clavier à un détour par le filtre. Synthé, piano, orgue = des BLOCS de la lane clavier.
  const [addMenu, setAddMenu] = useState(false);
  const newPatch = (r0) => {
    const r = r0 || (role !== 'all' ? role : 'guitar');
    setAddMenu(false);
    const realm = ROLE_REALM[r] || 'guitar';
    const p = blank();
    p.id = 'nouveau-preset';
    p.name = 'New ' + r + ' patch';
    p.__patch = { realm, id: null, name: 'New ' + r + ' patch', role: r };
    { const L = p.lanes.find(l => l.id === realm); if (L) { L.role = r; if (r === 'drums') { L.midi = true; L.in_sel = 'usb'; } } }   // docs/drums-kit.md : lane batterie MIDI
    // UNE BATTERIE POSE SA QUESTION DÈS LA CRÉATION, d'où qu'on vienne (docs/drums-kit.md §6.5).
    // Le brouillon MIDI reste le repli si on ferme le tiroir : une lane jouable, jamais un écran vide.
    openInDesigner(p, null, r === 'drums' ? 'drumset' : null);
  };

  // la barre : LA MÊME que Presets (list-toolbar.js) — bank regardée, loupe, tri, filtres résumés. Les cinq
  // instruments (2026-09-23) restent tous proposés, dans le panneau des filtres.
  const cap = r => r[0].toUpperCase() + r.slice(1);
  useEffect(() => {
    if (!patches.length) { setSubToolbar(null); return () => setSubToolbar(null); }
    setSubToolbar(html`<${ListToolbar} kind="sounds" lists=${soundLists} viewId=${viewId} footId=${slD.active || ''} onView=${setViewId}
      q=${qRaw} setQ=${setQ} placeholder="Search patches…"
      sorts=${[['bank', 'Bank #', inBank === 'out' ? 'these patches are in no bank' : ''], ['az', 'A → Z'], ['za', 'Z → A'], ['person', 'Musician']]}
      sort=${sort} setSort=${setSort}
      filters=${[
        { id: 'role', title: 'Instrument', def: 'all', value: role, set: setRole,
          options: [['all', 'All'], ...roles.filter(r => counts[r]).map(r => [r, cap(r)])] },
        { id: 'in', title: 'In « ' + ((viewBk && viewBk.name) || 'the bank') + ' »', def: 'both', value: inBank,
          options: [['both', 'All'], ['in', 'In the bank'], ['out', 'Not in it']],
          set: v => { setInBank(v); setSort(v === 'out' ? 'az' : 'bank'); } },
        ...(persons.length ? [{ id: 'person', title: 'Musician', def: 'all', value: person, set: setPerson,
          options: [['all', 'All'], ...persons.map(x => [x, personName(x)])] }] : []),
        ...(allTags.length ? [{ id: 'tag', title: 'Tag', def: 'all', value: tag, set: setTag,
          options: [['all', 'All'], ...allTags.map(t => [t, t])] }] : []),
      ]} />`);
    return () => setSubToolbar(null);
  }, [patches.length, role, qRaw, roles.join(), busy, viewId, soundLists.map(x => x.id + ':' + x.name).join('|'), slD.active,
      bankSlots.join('|'), inBank, sort, tag, person, allTags.join('|'), persons.join('|')]);

  // « ＋ Add » dans la TOPBAR, comme l'onglet Presets (retour 2026-08-02) : même gabarit,
  // même classe — donc la couleur de la SECTION active, pas une teinte à part.
  // ⚠ CONTEXTUEL : chaque onglet publie le sien et le retire en partant, sinon celui de Patches
  // survivrait au passage sur Presets (piège setTopAction, CLAUDE.md).
  useEffect(() => {
    setTopAction(html`<div class="tb-action tb-add-wrap">${addMenu ? html`<div class="save-pop tb-add-pop" onClick=${e => e.stopPropagation()}>
        ${NEW_ROLES.map(([id, lb, sub]) => html`<button class="row-btn" onClick=${() => newPatch(id)}>
          ${lb}<small>${sub}</small></button>`)}
      </div>` : ''}<button class="primary tb-new"
      title=${'empty bench in the Designer — role follows the filter (' + (role !== 'all' ? role : 'guitar') + ')'}
      onClick=${() => setAddMenu(v => !v)}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, [role, addMenu]);

  const byPerson = (a, b) => (personName(a.person || '~') + a.name).localeCompare(personName(b.person || '~') + b.name);
  const bySlot = x => { const k = slotOf(x.id); return k < 0 ? 999 : k; };
  const SORTS = { person: byPerson, az: (a, b) => a.name.localeCompare(b.name), za: (a, b) => b.name.localeCompare(a.name),
    bank: (a, b) => bySlot(a) - bySlot(b) || byPerson(a, b) };
  const shown = patches
    .filter(keepFactory(facShow, 'patches'))
    .filter(x => role === 'all' || x.role === role)
    .filter(x => inBank === 'both' || (inBank === 'in') === (slotOf(x.id) >= 0))
    .filter(x => person === 'all' || x.person === person)
    .filter(x => tag === 'all' || (x.tags || []).includes(tag))
    .filter(x => !q || (x.name + ' ' + personName(x.person || '') + ' ' + (x.tags || []).join(' ')).toLowerCase().includes(q))
    .slice().sort(SORTS[sort] || byPerson);

  // ── panneau droit façon Presets (demande 2026-07-31) : scènes, stomps, PREVIEW ──
  // La démo d'un patch passe par son PREMIER morceau lié : même chaîne (snap courant), même
  // moteur de preview, zéro plomberie nouvelle. Un patch sans morceau n'a pas de démo (encore).
  const [selScene, setSelScene] = useState({});          // pid -> index de scène sélectionnée
  const [stompOv, setStompOv] = useState({});            // pid -> {switch: bool} : aperçu d'un stomp cliqué (jamais persisté)
  const [tagging, setTagging] = useState(null);           // pid dont on édite les tags
  const [tagInput, setTagInput] = useState('');
  const addTag = async (x, t) => { t = t.trim(); setTagging(null); setTagInput('');
    if (t && !(x.tags || []).includes(t)) await meta(x.id, { tags: [...(x.tags || []), t] }); };
  const [menu, setMenu] = useState(null);
  const [menuUp, setMenuUp] = useState(false);   // ouvre du côté le plus dégagé
  const [armDel, setArmDel] = useState(null);
  const [ident, setIdent] = useState(null);
  const [drop, setDrop] = useState(null);        // patch dont le modal de dépôt est ouvert
  const [dropSel, setDropSel] = useState({});    // preset id -> coché
  const [dropRes, setDropRes] = useState(null);  // compte rendu du dépôt
  const playDemo = rel => { if (!window.__patDemo) window.__patDemo = new Audio();
    const a = window.__patDemo; a.pause(); a.src = '/' + String(rel).replace(/^\/*/, ''); a.currentTime = 0; a.play().catch(() => {}); };
  // L'ÉCOUTE D'UN PATCH (2026-11-03) : la DI de référence re-ampée à travers le patch, scène par scène — le
  // moteur de la page Presets, sur « patch:<id> » (bridge/preview.py). Le rack rend sur l'entrée où le patch
  // se joue ; la démo vit à côté de ses clips et revient dans GET /api/patches (`preview`).
  const [genId, setGenId] = useState(null);
  const [genSt, setGenSt] = useState(null);
  const [genErr, setGenErr] = useState(null);     // {id, msg}
  const genDemo = async pid => {
    if (genId) return;                             // une génération à la fois
    setGenErr(null); setGenId(pid); setGenSt(null);
    const r = await post('/api/preview/' + encodeURIComponent('patch:' + pid), {})
      .catch(e => ({ error: (e.body && e.body.error) || 'unreachable' }));
    const fail = msg => { setGenId(null); setGenErr({ id: pid, msg });
      setTimeout(() => setGenErr(e => (e && e.id === pid ? null : e)), 7000); };
    if (r && r.error) return fail(r.error);
    const t = setInterval(async () => {
      const st = await fetch('/api/preview/status').then(x => x.json()).catch(() => null);
      if (!st) return;
      setGenSt(st);
      // preview.status() n'a pas de `running` : la fin se lit dans `phase` (comme page-setlists)
      if (st.phase === 'done' || st.phase === 'error') {
        clearInterval(t); setGenId(null); reload();
        if (st.phase === 'error') fail(st.error || 'generation failed');
      } else reload();                             // incrémental : la scène A s'écoute pendant que B rend
    }, 1500);
  };
  const footOf = chain => {
    const sw = {};
    const walk = bl => (bl || []).forEach(b => { if (b && b.foot >= 6 && b.foot <= 10) (sw[b.foot] = sw[b.foot] || []).push(b); });
    for (const v of Object.values(chain || {})) {
      if (Array.isArray(v)) walk(v);
      else if (v && v.branches) v.branches.forEach(br => walk(br.blocks));
    }
    return sw;
  };
  const meta = async (pid, body) => { await post('/api/patches/' + encodeURIComponent(pid) + '/meta', body); reload(); };
  const delP = async pid => {
    setBusy(true);
    await fetch('/api/patches/' + encodeURIComponent(pid), { method: 'DELETE' }).catch(() => {});
    setBusy(false); reload();
  };
  // ✎ « jouer et modifier » : un DRAFT lié au patch, poussé dans l'edit-buffer du Designer
  // (le canal openInDesigner accepte désormais un doc — même chemin que le créateur IA).
  const openPatch = x => openInDesigner(patchDraft(x));
  // JOUER UN PATCH comme un preset (docs/patches.md §6) : le rack le rappelle sous `patch:<id>`,
  // /live et le pied suivent ses scènes et ses stomps. Le retour (ou le refus : pas d'entrée de ce rôle
  // sur la carte) s'affiche sur la ligne, pas dans une modale.
  const [played, setPlayed] = useState(null);      // {id, msg, bad}
  const makeSong = async x => {
    const r = await makeSongFromPatch(x.id);
    if (r && r.error) setPlayed({ id: x.id, msg: '✗ ' + r.error, bad: true });
  };
  const [bankFor, setBankFor] = useState(null);    // patch qu'on met dans une bank de sons (patch-as-preset §7)
  const playPatch = async x => {
    setPlayed({ id: x.id, msg: '…' });
    const r = await post('/api/patches/' + encodeURIComponent(x.id) + '/play', {}).catch(e => ({ error: (e.body && e.body.error) || String(e) }));
    setPlayed({ id: x.id, msg: r && r.error ? '✗ ' + r.error : '▶ playing', bad: !!(r && r.error) });
    setTimeout(() => setPlayed(pl => pl && pl.id === x.id ? null : pl), 4000);
  };

  if (data && !patches.length) {
    return html`<div class="library"><div class="lib-grid"><div class="pat-empty">
      <h3>No patches yet.</h3>
      <p class="muted">A patch is one musician's sound — an input chain you reuse across songs.
        Build it once, then drop it into every song that needs it.</p>
      ${/* « Extract from your presets » a disparu : la route appelait patches.extract_all, retiré
            avec la copie (673cff9) — un bouton qui répondait 500 (audit 2026-09-08). Un patch se
            crée depuis une lane du Designer (chip ⛓) ou par « ＋ New ». */''}
      <small class="muted">Save any lane as a patch from the Designer (the ⛓ chip), or tap ＋ New.</small>
    </div></div></div>`;
  }

  // ⚠ la coquille .library > .lib-grid PORTE les marges (14/22) ET le défilement : rendre
  // .plist nu collait aux bords de l'écran (constaté 2026-07-31). Reprendre les classes d'une
  // page ne suffit pas — il faut reprendre son ENVELOPPE.
  return html`<div class="library">
    <div class="lib-grid" onClick=${() => { if (menu) setMenu(null); if (ident) setIdent(null); }}>
      <div class="plist">
    ${shown.map(x => html`<div class=${cls('prow', 'style-' + (ROLE_STYLE[x.role] || 'rock'))} data-doc=${'songs.patch:' + x.id}>
      <div class="prow-main">
        <div class="pm-head">
          <button class="pplay edit-only" aria-label=${'Play « ' + shortName(x.name) + ' »'} title="play this patch now — the foot follows its scenes and stomps"
            onClick=${() => playPatch(x)}>▶</button>
          <button class="pplay" aria-label=${'Edit « ' + shortName(x.name) + ' » in the Designer'} title="open in the Designer — it saves itself, and no song is affected"
            onClick=${() => openPatch(x)}>✎</button>
          ${viewBk ? html`<button class=${cls('pbank', slotOf(x.id) >= 0 && 'on')}
            title=${slotOf(x.id) >= 0 ? 'bank in « ' + viewBk.name + ' » — tap to move' : 'tap to put it in a bank of « ' + viewBk.name + ' »'}
            onClick=${() => setBankPick(x.id)}>${slotOf(x.id) >= 0 ? '#' + bankNo(slotOf(x.id)) : '—'}</button>` : ''}
          ${played && played.id === x.id ? html`<span class=${cls('muted pplayed', played.bad && 'warn')}>${esc(played.msg)}</span>` : ''}
          <b class="prow-name">${x.person ? esc(personName(x.person)) + ' · ' : ''}${esc(shortName(x.name))}</b>
          ${/* plus de « rev » ni de « utilisé dans N morceaux » : le patch est autonome et
                    rien ne sait plus où sa chaîne a été copiée (docs/patches.md §15.3). */''}
          ${/* le RÔLE en haut à droite (2026-09-08) : un fait, pas un tag — l'entrée sur
                laquelle ce son est né. Même couleur que l'ancienne étiquette du bas. */''}
          <span class="tag tag-style pat-role" style=${'--st:var(--' + (ROLE_STYLE[x.role] || 'rock') + ', var(--muted))'}>${esc(x.role || '')}</span>
        </div>
        <${PatchFlow} chain=${x.chain} role=${x.role} fxShort=${fxShort}
          scene=${(x.scenes || [])[Math.min(selScene[x.id] || 0, Math.max(0, (x.scenes || []).length - 1))] || null}
          ov=${stompOv[x.id] || {}} />
        ${/* TAGS LIBRES, comme les presets (2026-09-08) : tap = retirer, « + tag » = ajouter.
              Le style du brief IA arrive déjà semé ; la recherche les lit. */''}
        <${FeatChips} x=${x} />
        <div class="pcard-tags" onClick=${e => e.stopPropagation()}>
          ${(x.tags || []).map(t => html`<span class="tag" onClick=${() => meta(x.id, { tags: (x.tags || []).filter(z => z !== t) })} title="tap = remove tag">${esc(t)} ×</span>`)}
          ${tagging === x.id
            ? html`<input class="tag-in" autofocus value=${tagInput} placeholder="tag…"
                onInput=${e => setTagInput(e.target.value)}
                onKeyDown=${e => { if (e.key === 'Enter') { addTag(x, tagInput); } if (e.key === 'Escape') setTagging(null); }}
                onBlur=${() => setTagging(null)} />`
            : html`<button class="tag add" onClick=${() => { setTagging(x.id); setTagInput(''); }}>+ tag</button>`}

        </div>
      </div>
      ${(() => {
        const scenes = (x.scenes || []);
        const sIdx = Math.min(selScene[x.id] || 0, Math.max(0, scenes.length - 1));
        const curSc = scenes[sIdx] || null;
        const sw = footOf(x.chain);
        return html`<div class="prow-side">
          <div class="ps-head">
            <button class="mini ps-settings" title="name & person" onClick=${e => { e.stopPropagation(); setIdent(ident === x.id ? null : x.id); }}>⚙</button>
            ${isHome(((rig || {}).state || {}).startup, { kind: 'patch', id: 'patch:' + x.id }) && ((((rig || {}).state || {}).startup) || {}).policy === 'home'
              ? html`<span class="pbank home" title="opens at startup">⌂ startup</span>` : ''}
            <span class="ps-scene-name" title=${curSc ? 'scene ' + curSc.id : ''}>${curSc ? esc(curSc.name || 'Scene ' + curSc.id) : x.role}</span>
            <div class="prow-menu" onClick=${e => e.stopPropagation()}>
              <button class="mini" onClick=${e => {
                // même règle que la page Presets : le côté le plus dégagé DANS le conteneur
                // qui défile — sinon le menu d'une ligne basse sort de .lib-grid et se coupe.
                const r = e.currentTarget.getBoundingClientRect();
                const box = (e.currentTarget.closest('.lib-grid') || document.documentElement).getBoundingClientRect();
                setMenuUp((r.top - box.top) > (box.bottom - r.bottom));
                setMenu(menu === x.id ? null : x.id); setArmDel(null); }}>⋯</button>
              ${menu === x.id ? html`<div class=${cls('save-pop', menuUp && 'up')}>
                <button class="row-btn" onClick=${() => { setMenu(null); openPatch(x); }}>✎ Edit in Designer</button>
                <button class="row-btn" title="put this patch in a sound list — each sound takes a bank (#) on the pedalboard"
                  onClick=${() => { setMenu(null); setBankFor(x); }}>⛓ Add to a list<small>your sounds on the pedalboard</small></button>
                <button class="row-btn" title="a new song made of this patch — sound, scenes, stomps and backing — to lay out an arrangement. The patch stays as it is."
                  onClick=${() => { setMenu(null); makeSong(x); }}>▤ Make a song<small>then add an arrangement</small></button>
                ${(() => { const st0 = ((rig || {}).state || {}).startup, key = { kind: 'patch', id: 'patch:' + x.id }, e = startupEntry(st0, key);
                  return html`<button class=${cls('row-btn edit-only', e.remove && 'accent')} title="what golem opens on /live at startup — read on /live (⌂)"
                    onClick=${() => { setMenu(null); if (e.remove) del('/api/startup/home').catch(() => {});
                      else post('/api/startup/home', { ...key, name: x.name || x.id }).catch(() => {}); }}>
                    ${e.label}${e.small ? html`<small> ${esc(e.small)}</small>` : ''}</button>`; })()}
                <button class=${cls('row-btn danger', armDel === x.id && 'armed')}
                  title="deletes the patch file — every song keeps its own copy of the chain"
                  onClick=${() => { if (armDel === x.id) { setMenu(null); delP(x.id); } else setArmDel(x.id); }}>
                  ${armDel === x.id ? html`🗑 Sure ? tap again<small>the catalogue entry only</small>`
                    : html`🗑 Delete patch…<small>songs keep their copy</small>`}</button>
              </div>` : ''}
            </div>
            ${/* ⚙ : nom, personne, et le DÉPÔT dans des morceaux (2026-09-08 : la place du
                  bouton d'écoute). ⚠ ancré sur .ps-head (position:relative) — sans ça le popover
                  se calculait sur un ancêtre lointain et s'ouvrait SOUS l'écran : « le menu est vide ». */''}
            ${ident === x.id ? html`<div class="save-pop pat-ident" onClick=${e => e.stopPropagation()}>
              <label class="muted">Name</label>
              <input class="pat-name" value=${x.name} title="rename — every song shows the new name"
                onChange=${e => e.target.value.trim() && meta(x.id, { name: e.target.value.trim() })} />
              <label class="muted">Person</label>
              <select value=${x.person || ''} title="whose sound is this?"
                onChange=${e => meta(x.id, { person: e.target.value || '' })}>
                <option value="" selected=${!x.person}>no person</option>
                ${people.map(pe => html`<option value=${pe.id} selected=${x.person === pe.id}>${esc(pe.name)}</option>`)}
              </select>
              <button class="row-btn" title="copy this patch's chain into songs — replaces their lane"
                onClick=${() => { setIdent(null); setDrop(x); }}>⬇ Deposit in songs…<small>replaces the lane of the songs you pick</small></button>
            </div>` : ''}
          </div>
          ${(() => {
            // claviers et batterie : une référence MIDI jouée par l'instrument du patch (2026-11-03) ; les pads
            // déclenchent des échantillons, une phrase de clavier n'y voudrait rien dire — rien plutôt qu'un « soon »
            if (['pads', 'keys-pads'].includes(x.role)) return '';
            const isMidi = x.role === 'keys' || x.role === 'drums';
            const clips = (x.preview && x.preview.scenes) || {};
            const clip = curSc ? clips[curSc.id] : null;
            const err = genErr && genErr.id === x.id ? genErr.msg : null;
            const roleLb = { voice: 'Voice', bass: 'Bass', keys: 'Keys', drums: 'Drums' }[x.role] || 'Guitar';
            if (genId === x.id) return html`<div class="ps-demo"><span class="ps-demo-busy muted"
              title="generating the sound guide…">🎧 ${genSt && genSt.total ? genSt.done + '/' + genSt.total : '⏳'}</span></div>`;
            if (err && !Object.keys(clips).length) return html`<div class="ps-demo"><button class="demo-listen err edit-only"
              title=${err} onClick=${() => genDemo(x.id)}>✗ ${esc(err.length > 40 ? err.slice(0, 40) + '…' : err)}</button></div>`;
            if (Object.keys(clips).length) return html`<div class="ps-demo">
              <button class="mini demo-play" disabled=${!clip}
                title=${clip ? 'listen to scene ' + (curSc.name || curSc.id) + ' — reference: ' + (x.preview.ref || '') : 'no clip for this scene yet'}
                onClick=${() => clip && playDemo(clip)}>🎧</button>
              <button class="mini demo-regen edit-only" disabled=${!!genId} title="regenerate the sound guide"
                onClick=${() => genDemo(x.id)}>↻</button></div>`;
            return html`<div class="ps-demo"><button class="demo-listen edit-only" disabled=${!!genId}
              title=${(isMidi ? 'plays a reference MIDI phrase on this ' : 're-amps a reference DI through this ') + roleLb.toLowerCase() + ' patch, scene by scene — takes the engine a few s, restores it after'}
              onClick=${() => genDemo(x.id)}>🎧 Listen — ${roleLb}</button></div>`;
          })()}
          ${/* stomps : tap = APERÇU sur la lane (les blocs du switch s'allument/s'éteignent), jamais
                persisté — même geste que sur la page Presets hors live */''}
          <div class="ps-stomps" title="switches 6-10 carried by this patch — tap to preview a stomp on the chain">
            ${[6, 7, 8, 9, 10].map(n => { const bl = sw[n] || []; if (!bl.length) return html`<span class="scmini off" title="switch ${n} — unassigned">${n}</span>`;
              const ov = stompOv[x.id] || {};
              const on = n in ov ? ov[n] : bl.some(b => !patchBlockOff(curSc, b, null));
              return html`<button class=${cls('scmini', 'stomp', on && 'on')} title=${bl.map(b => fxShort(b.type)).join(' + ') + ' — switch ' + n}
                  onClick=${() => setStompOv({ ...stompOv, [x.id]: { ...ov, [n]: !on } })}>
                  ${bl.slice(0, 2).map(b => html`<span class="scmini-ic">${ICON[b.type] || '•'}</span>`)}</button>`; })}
          </div>
          <div class="ps-scenes">
            ${['A', 'B', 'C', 'D', 'E'].map((L, i) => {
              const sc = scenes.find(z => z.id === L);
              return sc ? html`<button class=${cls('scmini', curSc && curSc.id === L && 'on')}
                  title=${esc(sc.name || 'scene ' + L)}
                  onClick=${() => { setSelScene({ ...selScene, [x.id]: scenes.indexOf(sc) }); setStompOv({ ...stompOv, [x.id]: {} }); }}>${L}</button>`
                : html`<span class="scmini off" title="no scene ${L} in this patch">${L}</span>`;
            })}
          </div>
        </div>`;
      })()}
    </div>`)}
      ${!shown.length ? html`<div class="empty">No patch matches.</div>` : ''}
      </div>
    </div>
    ${/* LE DÉPÔT — le seul geste destructif du modèle (docs/patches.md §15.4). Il REMPLACE la
          lane du rôle dans chaque morceau coché. La phrase qui l'annonce n'est pas une alerte :
          c'est le comptage exact de ce qui va être écrasé, avant de le faire. */''}
    ${drop ? html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && (setDrop(null), setDropRes(null))}>
      <div class="detail-card pat-drop">
        <button class="close" onClick=${() => { setDrop(null); setDropRes(null); }}>×</button>
        <h2>⬇ Deposit <small>${esc(shortName(drop.name))} — ${esc(drop.role || 'guitar')}</small></h2>
        ${dropRes ? html`
          <p class="pat-drop-done">✓ ${dropRes.presets.length} song${dropRes.presets.length > 1 ? 's' : ''} updated.</p>
          ${(dropRes.presets || []).filter(r => r.added_scenes).map(r => html`
            <p class="pat-drop-warn muted">＋ ${esc(r.preset)} : scene${r.added_scenes.length > 1 ? 's' : ''}
              ${r.added_scenes.join(', ')} added, from the patch.</p>`)}
          ${(dropRes.presets || []).filter(r => r.lost_scenes).map(r => html`
            <p class="pat-drop-warn">⚠ ${esc(r.preset)} : scene${r.lost_scenes.length > 1 ? 's' : ''}
              ${r.lost_scenes.join(', ')} dropped — that song already has 8 scenes.</p>`)}
          <button class="primary" onClick=${() => { setDrop(null); setDropRes(null); }}>Done</button>`
        : html`
          <p class="muted pat-drop-lead">Its chain is <b>copied</b> into each song you pick. Nothing links
            afterwards — you can reshape it song by song.</p>
          <div class="pat-drop-list">
            ${((data && data[2]) || []).map(pr => html`<label class=${cls('pat-drop-row', dropSel[pr.id] && 'on')}>
              <input type="checkbox" checked=${!!dropSel[pr.id]}
                onChange=${e => setDropSel({ ...dropSel, [pr.id]: e.target.checked })} />
              <b>${esc(pr.name || pr.id)}</b></label>`)}
          </div>
          ${(() => { const n = Object.values(dropSel).filter(Boolean).length;
            const lane = (ROLE_REALM[drop.role] || 'guitar');
            return html`<p class=${cls('pat-drop-warn', !n && 'muted')}>
              ${n ? `⚠ the ${lane} lane of ${n} song${n > 1 ? 's' : ''} will be replaced.`
                  : 'Pick the songs that should get this sound.'}</p>
            <button class="primary" disabled=${!n || busy}
              onClick=${async () => { setBusy(true);
                const r = await post('/api/patches/' + encodeURIComponent(drop.id) + '/deposit',
                  { presets: Object.keys(dropSel).filter(k => dropSel[k]) }).catch(() => null);
                setBusy(false); setDropSel({}); setDropRes(r || { presets: [] }); reload(); }}>
              ⬇ Replace in ${n} song${n > 1 ? 's' : ''}</button>`; })()}`}
      </div>
    </div>` : ''}
    ${bankFor ? html`<${AddToBank} patch=${bankFor} onClose=${() => setBankFor(null)} />` : ''}
    ${bankPick && viewBk ? html`<${BankPicker} pid=${'patch:' + bankPick} banks=${bankSlots} sounds
        presets=${patches.map(x => ({ id: 'patch:' + x.id, name: x.name }))}
        footName=${viewBk.name} footId=${viewBk.id} footLines=${viewBk.lines} onFoot=${viewBk.id === slD.active}
        onPick=${slot => putInBank(bankPick, slot)} onClose=${() => setBankPick(null)} />` : ''}
  </div>`;
}

// ── « ⛓ Add to a bank » (docs/patches.md §7) : les BANKS DE SONS seulement — une setlist de morceaux
// ne prend pas de patch. Aucune bank encore : on en crée une ici, dans le même geste.
function AddToBank({ patch, onClose }) {
  const [nonce, setNonce] = useState(0);
  const { data } = useAsync(() => fetch('/api/setlists').then(r => r.json()).catch(() => null), [nonce]);
  const [said, setSaid] = useState('');
  const [name, setName] = useState('');
  const banks = ((data || {}).setlists || []).filter(s => s.kind === 'sounds');
  const addTo = async sl => {
    const r = await post('/api/setlists/' + encodeURIComponent(sl.id) + '/patches', { ids: [patch.id] }).catch(e => ({ error: (e.body && e.body.error) || String(e) }));
    setSaid(r && r.error ? '✗ ' + r.error : '✓ added to « ' + sl.name + ' »');
  };
  const create = async () => {
    if (!name.trim()) return;
    const r = await post('/api/setlists', { name: name.trim(), kind: 'sounds' }).catch(e => ({ error: (e.body && e.body.error) || String(e) }));
    if (r && r.error) { setSaid('✗ ' + r.error); return; }
    await addTo(r); setName(''); setNonce(n => n + 1);
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card pbp">
      <button class="close" onClick=${onClose}>×</button>
      <h2>⛓ Add to a sound list <small>« ${esc(patch.name || patch.id)} »</small></h2>
      <p class="muted">A sound list puts your patches on the pedalboard — each sound takes a bank (#), its scenes and stomps under your feet.</p>
      ${said ? html`<p class=${said.startsWith('✗') ? 'mode-err' : 'muted'}>${esc(said)}</p>` : ''}
      <div class="pbp-list">
        ${!data ? html`<p class="muted">…</p>` : banks.map(sl => { const inIt = (sl.lines || []).some(l => l.patch === patch.id);
          return html`<button class="row-btn pbp-row" disabled=${inIt} onClick=${() => addTo(sl)}>
            <b>⛓ ${esc(sl.name)}</b><small>${inIt ? 'already in it' : (sl.lines || []).length + ' sound' + ((sl.lines || []).length === 1 ? '' : 's')}${sl.active ? ' · on the foot' : ''}</small></button>`; })}
      </div>
      <div class="pld-acts">
        <input class="mode-add-in" placeholder="New sound list — « My sounds »" value=${name} onInput=${e => setName(e.target.value)}
          onKeyDown=${e => e.key === 'Enter' && create()} />
        <button class="primary" disabled=${!name.trim()} onClick=${create}>＋ Create & add</button>
      </div>
    </div></div>`;
}

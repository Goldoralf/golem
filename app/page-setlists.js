// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Presets (ex-Sets) — LA bibliothèque de presets : tout le stock, avec l'état d'assignation
// aux banks du pied (badge #NN / unassigned), des TAGS libres (artiste/album/chanson/style/année…)
// filtrables, et les actions de rangement (assign/retirer, dupliquer, supprimer).
// Les setlists de concert viendront plus tard comme une VUE ordonnée de cette bibliothèque.
import { useFactoryShow, keepFactory } from './factory-show.js';
import { html, useState, useEffect, useRef, useAsync, post, del, cls, esc, LoadGuard, pad2, bankNo, setTopAction, setSubToolbar, openInDesigner, useRev, genreLabel, go } from './lib.js';
import { ListToolbar, useViewedList } from './list-toolbar.js';
import { PresetSettings } from './designer-sheets.js';
import { blkColor, ICON, SCENE_IDS, blockContent, SPECIAL_CAT, hydrateBlockMeta } from './designer-model.js';
import { menuEntry as startupEntry, isHome } from './startup-model.mjs';   // l'accueil au démarrage (mockups/startup-home.html)
import { FeatChips } from './browser-rail.js';             // les blocs spéciaux, comme le menu « With » du Designer

// état de scène (résumé backend, READ-ONLY : scn.branches_off = branches mutées, scn.off/on = blocs
// coupés/forcés). Tout se déduit de la scène sélectionnée — aucune modif locale.
const sceneLaneMuted = (scn, laneId) => !!(scn && laneId && (scn.branches_off || scn.lanes_off || []).includes(laneId));
const sceneSwitchOn = (scn, sw) => ((scn && scn.on) || []).includes(sw);   // scn.on = numéros de switch allumés
// override d'APERÇU d'un stomp pour un bloc : ov = {switch:bool} ; on relie le bloc à son switch via b.foot
const blockOverride = (ov, b) => (ov && b && b.foot != null && b.foot in ov) ? ov[b.foot] : undefined;
const sceneBlockOff = (scn, b, ov) => {
  const o = blockOverride(ov, b);            // aperçu de stomp (clic) prime sur la scène
  if (o !== undefined) return !o;            // switch on -> bloc on
  const off = (scn && scn.off) || [], on = (scn && scn.on_blk) || [];
  if (off.includes(b.id) || off.includes(b.type)) return true;
  if (on.includes(b.id) || on.includes(b.type)) return false;
  return !!b.bypass;
};

export function SetlistsPage({ rig }) {
  const facShow = useFactoryShow();          // l'usine masquée par sorte (Settings ▸ Content ▸ Factory)
  const contentRev = useRev('content_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data: presets, err, reload } = useAsync(() => fetch('/api/presets').then(r => r.json()), [contentRev]);
  const { data: bk, reload: reloadBk } = useAsync(() => fetch('/api/foot-list').then(r => r.json()), []);
  // setlists : le sélecteur d'ACTIVE vit dans cette barre d'outils (le reste — créer, dupliquer,
  // figer, supprimer — vit dans le sous-onglet Setlists).
  const { data: slD, reload: reloadSls } = useAsync(() => fetch('/api/setlists').then(r => r.json()), [contentRev]);
  const sls = (slD || {}).setlists || [];
  const activeSl = (slD || {}).active || '';
  // APPLIQUÉ (glyphes et couleurs des blocs spéciaux de la carte), comme les autres pages — pas seulement lu
  const { data: effects } = useAsync(() => fetch('/api/effects').then(r => r.json()).then(d => { hydrateBlockMeta(d.effects || d, d); return d; }), []);
  // les CHANSONS qui jouent chaque preset (2026-10-17) : une carte de preset dit pour quoi on l'a fait
  const { data: songD } = useAsync(() => fetch('/api/songs').then(r => r.json()).catch(() => null), [contentRev]);
  const songsOf = pid => ((songD && songD.songs) || []).filter(x => ((x.sheet || {}).preset) === pid);
  const [qRaw, setQ] = useState('');
  const q = qRaw.trim().toLowerCase();
  const [tag, setTag] = useState('all');
  // 'both' | 'assigned' | 'free' — défaut : LES DEUX cochés (2026-10-08), toute la bibliothèque, pied d'abord
  const [assign, setAssign] = useState('both');
  const [sort, setSort] = useState('bank');           // défaut : ordre des banks du pied
  const [tagging, setTagging] = useState(null);  // pid en cours d'édition de tags
  const [tagInput, setTagInput] = useState('');
  // « + Add » CONTEXTUEL dans la topbar : un BANC VIDE dans le Designer.
  // ⚠ Il ouvrait le créateur IA. L'IA a quitté les presets (docs/patches.md §14), puis le rack
  // entier (2026-09-09) : un morceau est un assemblage de choix humains, et un son se décrit sur golem.fm.
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new"
      title="empty bench in the Designer — name it when it sounds right"
      onClick=${() => openInDesigner({ __new: true })}>+ Add</button></div>`);   // le Designer le fait naître de la carte
    return () => setTopAction(null);
  }, []);
  if (!presets) return html`<${LoadGuard} err=${err} reload=${reload} label="Loading presets…" />`;

  // ── CLOISONNÉ (2026-10-08) : Presets ↔ SETLISTS (les morceaux) ; les banks de sons vivent dans Patches.
  // La setlist REGARDÉE se choisit dans la barre (useViewedList) — elle ne change PAS ce que joue le pédalier.
  // Ses #NN sont ceux des cartes, et le sélecteur de bank écrit dans ELLE.
  const songLists = sls.filter(x => x.kind !== 'sounds');
  const [viewId, setViewId] = useViewedList('presets', songLists, activeSl);
  const viewSl = songLists.find(x => x.id === viewId) || null;
  const banks = (viewSl && viewSl.presets) || [];
  const slotOf = pid => banks.indexOf(pid);
  // Nom de la setlist ACTIVE : les actions du menu ⋯ agissent sur ELLE, et doivent le DIRE.
  // « Eject from the foot » ne disait pas de quoi on sortait le preset, et « Delete… » ne disait
  // pas qu'il partait de PARTOUT — un preset retiré d'un set a disparu des deux (vécu 2026-07-28).
  const setName = (viewSl && viewSl.name) || 'the setlist';
  const allTags = [...new Set(presets.flatMap(p => p.tags || []))].sort();

  const [picker, setPicker] = useState(null);    // pid dont on choisit la bank | null
  const refresh = () => { reload(); reloadBk(); reloadSls(); };
  const writeList = n => viewId ? post('/api/setlists/' + encodeURIComponent(viewId) + '/presets', { presets: n }) : Promise.resolve();
  const withFull = async (pid, mut) => {          // charge le preset complet, applique, sauve
    const full = await fetch('/api/preset/' + pid).then(r => r.json()).catch(() => null);
    if (!full) return;
    mut(full);
    await post('/api/preset', full);
    refresh();
  };
  const addTag = async (pid, t) => { t = t.trim(); if (t) await withFull(pid, f => { f.tags = [...new Set([...(f.tags || []), t])]; }); setTagInput(''); };
  const rmTag = (pid, t) => withFull(pid, f => { f.tags = (f.tags || []).filter(x => x !== t); });
  const assignTo = async (pid, slot) => {         // assigne/déplace pid sur LA bank choisie
    const n = [...banks];
    while (n.length <= slot) n.push('');
    const old = n.indexOf(pid);
    if (old >= 0) n[old] = '';                    // déplacement : libère l'ancienne bank
    n[slot] = pid;
    await writeList(n); setPicker(null); refresh();
  };
  const unassign = async pid => {
    const n = banks.map(x => x === pid ? '' : x);
    await writeList(n); refresh();
  };
  const duplicate = pid => withFull(pid, f => { f.id = null; f.name = (f.name || 'Preset') + ' copy'; });
  // suppression en DEUX taps : 🗑 arme la carte (« sure ? », 3 s), re-tap = supprime vraiment
  const [armDel, setArmDel] = useState(null);
  const armTimer = useRef(null);
  const askRemove = pid => {
    if (armDel !== pid) {
      setArmDel(pid);
      clearTimeout(armTimer.current);
      armTimer.current = setTimeout(() => setArmDel(null), 3000);
      return;
    }
    clearTimeout(armTimer.current); setArmDel(null); remove(pid);
  };
  const remove = async pid => {
    if (slotOf(pid) >= 0) await unassign(pid);
    await del('/api/preset/' + pid); refresh();
  };

  const match = p => (tag === 'all' || (p.tags || []).includes(tag))
    && (assign === 'both' || (assign === 'assigned') === (slotOf(p.id) >= 0))
    && (!q || (p.name + ' ' + (p.artist || '') + ' ' + (p.tags || []).join(' ')).toLowerCase().includes(q));
  // tri : « bank » (Setlist #) = ordre de la setlist regardée (absents à la fin)
  const bySlot = p => { const s = slotOf(p.id); return s < 0 ? 999 : s; };
  const SORTS = {
    az: (a, b) => a.name.localeCompare(b.name),
    za: (a, b) => b.name.localeCompare(a.name),
    style: (a, b) => (a.style || '').localeCompare(b.style || '') || a.name.localeCompare(b.name),
    bank: (a, b) => bySlot(a) - bySlot(b) || a.name.localeCompare(b.name),
  };
  const list = presets.filter(keepFactory(facShow, 'presets')).filter(match).sort(SORTS[sort] || SORTS.az);

  // sélection locale par rangée : entrée affichée + scène active + APERÇU de stomps (non sauvegardé).
  // Changer de scène réinitialise l'aperçu -> tout revient à l'état de la scène.
  const [rowSel, setRowSel] = useState({});          // {pid: {inputIdx, scene, stomps:{type:bool}}}
  const selOf = pid => rowSel[pid] || { inputIdx: 0, scene: 0, stomps: {} };
  const setSel = (pid, patch) => setRowSel(s => ({ ...s, [pid]: { ...selOf(pid), ...patch } }));
  // aperçu au pied : état EFFECTIF d'un stomp (scène ± bascule locale) ; tap = bascule on/off
  const switchEffOn = (pid, sw, scn) => { const ov = selOf(pid).stomps || {}; return sw in ov ? ov[sw] : sceneSwitchOn(scn, sw); };
  const toggleSwitch = (pid, sw, scn) => setSel(pid, { stomps: { ...(selOf(pid).stomps || {}), [sw]: !switchEffOn(pid, sw, scn) } });
  const [menu, setMenu] = useState(null);            // pid dont le menu ⋯ est ouvert
  const [menuUp, setMenuUp] = useState(false);       // ouvre vers le HAUT si pas la place dessous
  // GARDE-FOU crash : une seule action LIVE (recall/stomp) à la fois + cooldown. Sans ça, un clic
  // rapide spamme les rebuilds de rig (ajout/retrait de NAM/Vitalium pendant l'audio) -> GPF plugin
  // dans le thread audio de Reaper (crash observé 2026-07-09). ~320 ms couvre le temps d'un rebuild.
  const liveBusy = useRef(false);
  const liveAct = fn => { if (liveBusy.current) return; liveBusy.current = true;
    Promise.resolve(fn()).catch(() => {}).finally(() => setTimeout(() => { liveBusy.current = false; }, 320)); };
  // lecteur de démo (guide sonore) : un seul <audio> réutilisé, sert le clip .opus depuis /library
  const demoAudio = useRef(null);
  const playDemo = rel => { if (!demoAudio.current) demoAudio.current = new Audio();
    const a = demoAudio.current; a.pause(); a.src = '/' + String(rel).replace(/^\/*/, ''); a.currentTime = 0; a.play().catch(() => {}); };
  // génération de démo À LA DEMANDE (option 1) : on prend le moteur, on rend scène par scène, on le
  // remet comme avant. Poll du statut ; refresh incrémental -> scène A jouable pendant que B/C rendent.
  const [genPreview, setGenPreview] = useState(null);   // id du preset en génération | null
  const [genSt, setGenSt] = useState(null);             // statut {phase,done,total,error}
  const [genErr, setGenErr] = useState(null);           // {id, msg} — erreur affichée qq s après échec
  // réf voix (Male/Female) pour le preview de la lane chant — mémorisée pour la session
  const [voxRef, setVoxRef] = useState('voice/male');
  const genDemo = async (pid, inKey, ref) => {
    if (genPreview) return;                             // une génération à la fois
    setGenErr(null); setGenPreview(pid); setGenSt({ phase: 'render' });
    const r = await post('/api/preview/' + pid, { input: inKey || '1', ref: ref || null }).catch(() => ({ error: 'unreachable' }));
    if (r && r.error) {                                 // refus immédiat (déjà en cours, preset absent…)
      setGenPreview(null); setGenErr({ id: pid, msg: r.error });
      setTimeout(() => setGenErr(e => (e && e.id === pid ? null : e)), 7000); return;
    }
    const t = setInterval(async () => {
      const s = await fetch('/api/preview/status').then(r => r.json()).catch(() => null);
      if (!s) return;
      setGenSt(s);
      if (s.phase === 'done' || s.phase === 'error') {
        clearInterval(t); setGenPreview(null); refresh();
        if (s.phase === 'error') {                      // montre POURQUOI (ex. DI absent)
          setGenErr({ id: pid, msg: s.error || 'generation failed' });
          setTimeout(() => setGenErr(e => (e && e.id === pid ? null : e)), 7000);
        }
      } else refresh();                                 // refresh incrémental (scène A apparaît)
    }, 1200);
  };
  const [settingsP, setSettingsP] = useState(null);  // preset complet chargé pour l'éditeur Settings
  const openSettings = async pid => { const full = await fetch('/api/preset/' + pid).then(r => r.json()).catch(() => null); if (full) setSettingsP(full); };
  const settingsUpd = mut => setSettingsP(prev => { const n = JSON.parse(JSON.stringify(prev)); mut(n); post('/api/preset', n).then(refresh).catch(() => {}); return n; });
  const fxDefs = (effects && effects.effects) || [];
  const fxShort = t => { const d = fxDefs.find(e => e.type === t) || {}; return d.short || d.name || t; };

  // mini-chaîne read-only = la vraie LIGNE AUDIO reconstituée (façon Designer, simplifiée) :
  // IN → pre → { split (2 lanes décalées ±½ bloc) → } merge → post → OUT. Bloc/lane grisés si
  // coupés par la scène. La box OUT indique stéréo (1·2) ou mono.
  const outBox = o => html`<span class=${cls('mf-io out', o === 'NONE' && 'off')} title=${o === '1-2' ? 'stereo out 1+2' : o === 'NONE' ? 'chain off' : 'mono out ' + o}>
    OUT<b>${o === '1-2' ? '1·2' : o === 'NONE' ? '—' : o}</b><em>${o === '1-2' ? 'stereo' : o === 'NONE' ? 'off' : 'mono'}</em></span>`;
  const inLabel = inp => (inp.in === 'k' ? 'USB 1' : inp.in && inp.in !== '—' && inp.in !== 'NONE' ? 'IN ' + inp.in : 'IN KO');
  const MiniChain = (input, scn, inputs, sel, pid, ov, scObj) => {
    // le nom AFFICHÉ dit ce que le bloc a chargé quand il n'a pas de capture (vital→preset,
    // drums→kit…) : trois Vital sur une lane cessent d'être trois tuiles identiques.
    // ⚠ scObj est PASSÉ : `p` (le preset de la carte) n'est pas dans la portée d'ici.
    const clean = v => String(v || '').split('/').pop().replace(/\.(vital|sfz|golemkit|xml)$/i, '').replace(/_/g, ' ');
    const blk = (b, muted) => { const raw = ((b.content_scenes || {})[scn && scn.id ? scn.id : scn]) || b.content;
      const ct = raw ? clean(raw) : null;
      return html`<span class=${cls('mc-blk', (muted || sceneBlockOff(scn, b, ov)) && 'off')}
      style=${'--tc:' + blkColor(b.type)} title=${ct ? fxShort(b.type) + ' · ' + ct : b.type}>
      <i>${ICON[b.type] || '▫'}</i><em>${esc(ct || fxShort(b.type))}</em></span>`; };
    const sp = input.split;
    const laneRow = br => {
      const muted = sceneLaneMuted(scn, br.id);
      return html`<div class=${cls('mf-lane', muted && 'muted-lane')}>
        ${(br.blocks || []).map(b => blk(b, muted))}
        ${sp.mode === 'fanout' ? outBox(br.out) : ''}
      </div>`;
    };
    // bloc IN de départ = SÉLECTEUR d'entrée : <select> transparent superposé. Affiche la
    // FONCTION de l'entrée (rôle du patch Soundcard : Guitar/Voice/Keys…) sous « IN n » —
    // plus de flèches, le vert suffit (remarque 2026-07-24).
    const multi = inputs.length > 1;
    const rp = ((rig && rig.state) || {}).inputmap || {};
    // le RÔLE de la lane (bass, voice, drums…), pas l'étiquette de l'entrée : une lane sans entrée disait « Guitar »
    const roleOf = inp => inp.role ? inp.role.charAt(0).toUpperCase() + inp.role.slice(1)
      : inp.in === 'k' ? ((rp.midi || {}).label || 'Keys')
      : ((rp.inputs || []).find(x => String(x.ch) === String(inp.in)) || {}).label || '?';
    // une lane SANS entrée branchée (normal : la basse d'un preset joué seul) : « IN KO », son rôle en rouge
    const ko = input.in !== 'k' && !(input.in && input.in !== '—' && input.in !== 'NONE');
    const inBox = html`<span class=${cls('mf-io in', multi && 'sel', ko && 'in-ko')}
      title=${(ko ? 'no input connected to this lane' : '') + (multi ? (ko ? ' — ' : '') + 'tap to switch input' : '')}>
      <span class="mf-in-row">▶ ${input.in === 'k' ? html`USB <b>1</b>` : ko ? html`IN <b>KO</b>` : html`IN <b>${input.in}</b>`}</span>
      <em>${esc(roleOf(input))}</em>
      ${multi ? html`<select class="mf-in-select" value=${sel.inputIdx}
        onChange=${e => setSel(pid, { inputIdx: +e.target.value })}>
        ${inputs.map((inp, i) => html`<option value=${i} selected=${i === sel.inputIdx}>${esc(inLabel(inp))} · ${esc(roleOf(inp))}</option>`)}
      </select>` : ''}
    </span>`;
    // chaîne LINÉAIRE longue -> enroulée sur PLUSIEURS rangées (2026-07-24 : plus de
    // scrollbar horizontale) : la coupure est cousue par une paire de MAILLONS de même couleur
    // (fin de rangée ⤵n / début de la suivante n⤷) — le regard suit le fil sans ambiguïté.
    // UNE lane = UNE ligne, TOUJOURS (décision 2026-07-31 — « le renvoi à la ligne est
    // interdit ») : l'ancien repli en rangées ⤵⤷ est retiré, une chaîne longue DÉFILE dans sa
    // rangée (.mflow est overflow-x:auto — le conteneur scrolle, jamais la page).
    return html`<div class="mflow">
      ${inBox}
      ${(input.pre || []).map(b => blk(b))}
      ${sp ? html`
        <span class="mf-brk">{</span>
        <div class="mf-lanes">${sp.branches.map(laneRow)}</div>
        ${sp.mode !== 'fanout' ? html`<span class="mf-brk">}</span>${(input.post || []).map(b => blk(b))}${outBox(input.out)}` : ''}
      ` : outBox(input.out)}
    </div>`;
  };

  const Card = p => {
    const slot = slotOf(p.id);
    const sel = selOf(p.id);
    const inputs = p.inputs || [];
    const curInput = inputs[Math.min(sel.inputIdx, inputs.length - 1)] || inputs[0];
    const scenes = p.scenes || [];
    const switches = p.switches || [];      // [{sw, blocks:[{id,type}], whammy}] pour 6-10
    // état LIVE : ce preset est-il celui chargé sur le rig ? -> scène/stomps pilotent le rig (pied sync)
    const rs = (rig && rig.state) || {};
    const live = !!(rig && rig.wsUp && rs.preset_id === p.id);
    const locked = !!rs.live_lock;
    const sceneIdx = live ? Math.max(0, scenes.findIndex(s => s.id === rs.scene_id)) : sel.scene;
    const curScene = scenes[sceneIdx];
    const ov = live ? (rs.stomps || {}) : (sel.stomps || {});   // override effectif (rig live | aperçu local), clé = switch
    const switchOn = sw => (sw in ov ? ov[sw] : sceneSwitchOn(curScene, sw));
    const playIt = () => { if (!live && !locked) liveAct(() => post('/api/recall', { preset: p.id })); };
    // L'ACCUEIL : une ligne qui porte une CHANSON (band_song / titre) dans la setlist affichée se pose comme chanson
    // (son preset ET son arrangement), sinon comme preset. Un seul accueil ; le badge ⌂ dit lequel.
    const homeLine = (viewSl && (viewSl.lines || []).find(ln => ln && (ln.band_song || ln.title) && (ln.preset === p.id || ln.band_song_preset === p.id))) || null;
    const homeKey = homeLine ? { kind: 'song', setlist: viewSl.id, line: homeLine.id } : { kind: 'preset', id: p.id };
    const homeNow = isHome(rs.startup, homeKey) && (rs.startup || {}).policy === 'home';
    return html`<div class=${cls('prow', 'style-' + (p.style || 'rock'), live && 'playing')}>
      <div class="prow-main">
        <div class="pm-head">
          <button class=${cls('pplay edit-only', live && 'on')} disabled=${locked && !live}
            title=${live ? 'playing live on the rig' : locked ? 'set locked — unlock on the Live page' : 'play this preset in the sandbox'}
            onClick=${playIt}>${live ? '● LIVE' : '▶'}</button>
          ${homeNow ? html`<span class="pbank home" title="opens at startup">⌂ startup</span>` : ''}
          <button class=${cls('pbank', slot >= 0 && 'on')} title=${slot >= 0 ? 'bank — tap to move' : 'tap to assign a bank'}
            onClick=${() => setPicker(p.id)}>${slot >= 0 ? '#' + bankNo(slot) : '—'}</button>
          <b class="prow-name">${esc(p.name)}</b>
          ${/* les INSTRUMENTS du preset, en chips (demande 2026-07-31) — à la place du duo
                de styles, descendu devant les tags persos. Un tap = la lane s'affiche dans le
                mini-flow (même état que le sélecteur IN, qui reste). */''}
          <span class="pcard-insts">
            ${inputs.map((inp, i) => {
              // LE NOM DE LA LANE, puis son rôle (2026-10-17) : on lisait l'étiquette de l'ENTRÉE de la carte son —
              // une lane sans entrée (« — », la basse) retombait sur « Guitar », toute lane MIDI (la batterie) sur « Keys »
              const rp2 = ((rig && rig.state) || {}).inputmap || {};
              const lbl = inp.name ? inp.name.charAt(0).toUpperCase() + inp.name.slice(1) : (inp.role ? inp.role.charAt(0).toUpperCase() + inp.role.slice(1)
                : inp.in === 'k' ? ((rp2.midi || {}).label || 'Keys')
                : (((rp2.inputs || []).find(x => String(x.ch) === String(inp.in)) || {}).label || 'Input ' + inp.in));
              const src = inp.in === 'k' ? 'MIDI' : inp.in && inp.in !== '—' && inp.in !== 'NONE' ? 'IN ' + inp.in : 'no input';
              return html`<button class=${cls('pinst', i === Math.min(sel.inputIdx, inputs.length - 1) && 'on')}
                title=${'show the ' + lbl + ' lane below — ' + (inp.role || '?') + ' · ' + src}
                onClick=${() => setSel(p.id, { inputIdx: i })}>${esc(lbl)}</button>`;
            })}
          </span>
          <span class="pcard-sub muted">${p.artist ? esc(p.artist) : ''}${p.bpm ? `${p.artist ? ' · ' : ''}♩ ${p.bpm}` : ''}</span>
        </div>
        ${curInput ? MiniChain(curInput, curScene, inputs, sel, p.id, ov, curScene) : ''}
        ${songsOf(p.id).length ? html`<div class="pcard-songs">${songsOf(p.id).map(sg => {
          const art = k => '/api/backing/asset/' + encodeURIComponent(sg.id) + '/' + k;
          const hide = e => { e.target.style.display = 'none'; };
          return html`<button class="pcs" title=${'the song « ' + (sg.title || sg.id) + ' » plays this preset — open it'}
            onClick=${e => { e.stopPropagation(); go('songs/songs/' + encodeURIComponent(sg.id)); }}>
            <span class="pcs-cover">♪${sg.has_cover ? html`<img src=${art('cover')} alt="" loading="lazy" onError=${hide} />` : ''}</span>
            <b>${esc(sg.title || sg.id)}</b>
            ${sg.artist ? html`<span class="pcs-artist">${sg.has_photo ? html`<img src=${art('photo')} alt="" loading="lazy" onError=${hide} />` : ''}${esc(sg.artist)}</span>` : ''}
            ${sg.parts ? html`<span class="pcs-arr" style=${'color:' + SPECIAL_CAT.arrangement[1]}
              title=${sg.parts + '-part arrangement'}>▤</span>` : ''}
          </button>`; })}</div>` : ''}
        <${FeatChips} x=${p} />
        <div class="pcard-tags">
          ${((p.styles && p.styles.length ? p.styles : [p.style]).filter(Boolean)).map(st =>
            html`<span class="tag tag-style" style=${'--st:var(--' + st + ', var(--muted))'}
              title="style — set in the Designer">${esc(genreLabel(st))}</span>`)}
          ${(p.tags || []).map(t => html`<span class="tag" onClick=${() => rmTag(p.id, t)} title="tap = remove tag">${esc(t)} ×</span>`)}
          ${tagging === p.id
            ? html`<input class="tag-in" autofocus value=${tagInput} placeholder="tag…"
                onInput=${e => setTagInput(e.target.value)}
                onKeyDown=${e => { if (e.key === 'Enter') { addTag(p.id, tagInput); setTagging(null); } if (e.key === 'Escape') setTagging(null); }}
                onBlur=${() => setTagging(null)} />`
            : html`<button class="tag add" onClick=${() => { setTagging(p.id); setTagInput(''); }}>+ tag</button>`}
        </div>
      </div>

      <div class="prow-side">
        <div class="ps-head">
          <button class="mini ps-settings edit-only" title="preset settings" onClick=${() => openSettings(p.id)}>⚙</button>
          <span class="ps-scene-name">${curScene ? esc(curScene.name || curScene.id) : ''}</span>
          <div class="prow-menu edit-only" onClick=${e => e.stopPropagation()}>
            <button class="mini" onClick=${e => {
              // ⚠ ON MESURE DANS LE CONTENEUR QUI DÉFILE, pas dans la fenêtre. L'ancien test
              // (« 300 px sous le bouton dans le viewport ? ») retournait le menu vers le haut
              // là où il y avait encore MOINS de place : sur la 2e ligne, il partait 64 px
              // au-dessus de .lib-grid et se faisait couper par la barre d'onglets.
              setMenuUp((() => { const r = e.currentTarget.getBoundingClientRect();
                const box = (e.currentTarget.closest('.lib-grid') || document.documentElement).getBoundingClientRect();
                return (r.top - box.top) > (box.bottom - r.bottom); })());
              setMenu(menu === p.id ? null : p.id); setArmDel(null); }}>⋯</button>
            ${menu === p.id ? html`<div class=${cls('save-pop', menuUp && 'up')}>
              <button class="row-btn" onClick=${() => { setMenu(null); openInDesigner(p.id); }}>✎ Edit in Designer</button>
              <button class="row-btn" onClick=${() => { setMenu(null); setPicker(p.id); }}>🎹 ${slot >= 0 ? 'Move bank' : 'Assign bank'}</button>
              ${slot >= 0 ? html`<button class="row-btn"
                title=${'takes it off bank #' + bankNo(slot) + ' — the preset itself stays in the library'}
                onClick=${() => { setMenu(null); unassign(p.id); }}>
                ⏏ Remove from set<small>${esc(setName)}</small></button>` : ''}
              <button class="row-btn" onClick=${() => { setMenu(null); duplicate(p.id); }}>⧉ Duplicate</button>
              ${(() => { const e = startupEntry(rs.startup, homeKey);
                return html`<button class=${cls('row-btn', e.remove && 'accent')} title="what golem opens on /live at startup — read on /live (⌂)"
                  onClick=${() => { setMenu(null); if (e.remove) del('/api/startup/home').catch(() => {});
                    else post('/api/startup/home', { ...homeKey, name: homeLine ? (homeLine.title || p.name) : (p.name || p.id) }).catch(() => {}); }}>
                  ${e.label}${e.small ? html`<small> ${esc(e.small)}</small>` : ''}</button>`; })()}
              <button class=${cls('row-btn danger', armDel === p.id && 'armed')}
                title="deletes the preset file — it leaves every setlist at once"
                onClick=${() => { if (armDel === p.id) setMenu(null); askRemove(p.id); }}>
                ${armDel === p.id
                  ? html`🗑 Sure ? tap again<small>gone from every setlist</small>`
                  : html`🗑 Delete preset…<small>from every setlist</small>`}</button>
            </div>` : ''}
          </div>
        </div>
        ${(() => {
          // guide sonore CONTEXTUEL À L'ENTRÉE sélectionnée dans la carte (2026-07-24) :
          // IN 1 = DI guitare/basse (auto par style), IN 2 voix = réf CHANTÉE Male/Female,
          // USB = pas encore (rendu MIDI). Démos stockées PAR entrée (preview.alt[in]).
          const inKey = curInput ? curInput.in : '1';
          const role = inKey === 'k' ? 'keys'
            : ((((rs.inputmap || {}).inputs) || []).find(x => String(x.ch) === String(inKey)) || {}).role || 'guitar';
          const pv = p.preview || {};
          const scenesMap = (inKey === '1' ? pv.scenes : ((pv.alt || {})[inKey] || {}).scenes) || {};
          const hasDemo = Object.keys(scenesMap).length > 0;
          const gen = genPreview === p.id;
          const err = genErr && genErr.id === p.id ? genErr.msg : null;
          const curClip = curScene ? scenesMap[curScene.id] : null;
          const isVoice = role === 'voice';
          const ref = isVoice ? voxRef : null;
          const roleLb = role === 'voice' ? 'Voice' : role === 'bass' ? 'Bass' : role === 'keys' ? 'Keys' : 'Guitar';
          // LA DÉMO DE LA LANE (2026-11-03) : rangée avec le morceau, une par lane, lecture seule — sans notion de carte
          // son : toute lane s'écoute, même sans entrée sur cette carte. Un preset d'usine l'a reçue de son patch
          // (copiée quand la lane sonne pareil, rendue sinon) ; un clip absent = la lane se tait dans cette scène.
          const lpv = curInput && (p.lane_previews || {})[curInput.key];
          if (lpv) {
            const clip = curScene ? (lpv.scenes || {})[curScene.id] : null;
            const how = lpv.made === 'copied' ? ' — from its patch' : '';
            return html`<div class="ps-demo"><button class="mini demo-play" disabled=${!clip}
              title=${clip ? 'listen to ' + (curInput.name || roleLb) + ' in scene ' + (curScene.name || curScene.id) + ' — reference: ' + ((lpv.refs || {})[curScene.id] || lpv.ref || '') + how
                : 'this lane is silent in this scene'}
              onClick=${() => clip && playDemo(clip)}>🎧</button></div>`;
          }
          const voxChips = isVoice ? html`<span class="vox-pick">
            ${[['voice/male', 'M'], ['voice/female', 'F']].map(([r2, lb]) => html`<button
              class=${cls('p-chip', voxRef === r2 && 'on')} title=${r2 === 'voice/male' ? 'male vocal reference' : 'female vocal reference'}
              onClick=${() => setVoxRef(r2)}>${lb}</button>`)}</span>` : '';
          if (gen) return html`<div class="ps-demo"><span class="ps-demo-busy muted"
            title="generating the sound guide…">🎧 ${genSt && genSt.total ? genSt.done + '/' + genSt.total : '⏳'}</span></div>`;
          if (err && !hasDemo) return html`<div class="ps-demo">${voxChips}<button class="demo-listen err edit-only"
            title=${err} onClick=${() => genDemo(p.id, inKey, ref)}>✗ ${esc(err.length > 40 ? err.slice(0, 40) + '…' : err)}</button></div>`;
          if (hasDemo) return html`<div class="ps-demo">${voxChips}
            <button class="mini demo-play" disabled=${!curClip}
              title=${curClip ? 'listen to scene ' + (curScene ? (curScene.name || curScene.id) : '') + ' — ' + roleLb + ' (IN ' + inKey + ')' : 'no clip for this scene yet'}
              onClick=${() => curClip && playDemo(curClip)}>🎧</button>
            <button class="mini demo-regen edit-only" title=${'regenerate — ' + roleLb + ' chain (IN ' + inKey + ')'}
              onClick=${() => genDemo(p.id, inKey, ref)}>↻</button>
          </div>`;
          return html`<div class="ps-demo">${voxChips}<button class="demo-listen edit-only"
            title=${(inKey === 'k' ? 'plays a reference MIDI phrase on the ' : 're-amps a ' + (isVoice ? 'sung vocal reference' : 'reference DI') + ' through the ') + roleLb + ' chain (' + (inKey === 'k' ? 'USB' : 'IN ' + inKey) + '), scene by scene — takes the engine a few s, restores it after'}
            onClick=${() => genDemo(p.id, inKey, ref)}>🎧 Listen — ${roleLb}</button></div>`;
        })()}
        <div class=${cls('ps-stomps', live && 'playing')} title=${live ? 'switches 6-10 — live foot control' : 'switches 6-10 — tap to preview a stomp on the chain'}>
          ${switches.map(sw => { const used = (sw.blocks || []).length > 0;
            return used ? html`<button class=${cls('scmini', 'stomp', switchOn(sw.sw) && 'on')}
                aria-label=${'Switch ' + sw.sw + ' — ' + sw.blocks.map(b => fxShort(b.type)).join(' + ')}
                title=${sw.blocks.map(b => esc(fxShort(b.type)) + (b.in && b.in !== '1' ? ' (' + (b.in === 'k' ? 'USB' : 'IN' + b.in) + ')' : '')).join(' + ') + ' — switch ' + sw.sw + (switchOn(sw.sw) ? ' · on' : ' · off')}
                onClick=${() => live ? liveAct(() => post('/api/stomp', { switch: sw.sw })) : toggleSwitch(p.id, sw.sw, curScene)}>
                ${sw.blocks.slice(0, 2).map(b => html`<span class="scmini-ic">${ICON[b.type] || '•'}</span>`)}</button>`
              : html`<span class="scmini off" title="switch ${sw.sw} — unassigned">${sw.sw}</span>`; })}
        </div>
        <div class=${cls('ps-scenes', live && 'playing')}>
          ${[0, 1, 2, 3, 4].map(i => { const s = scenes[i];
            const on = live ? (s && s.id === rs.scene_id) : (i === sceneIdx);
            return s ? html`<button class=${cls('scmini', on && 'on')}
                aria-label=${'Scene ' + SCENE_IDS[i] + ' — ' + (s.name || s.id)}
                title=${esc(s.name || s.id) + (live ? ' — recall live' : '')}
                onClick=${() => live ? liveAct(() => post('/api/recall', { scene: s.id })) : setSel(p.id, { scene: i, stomps: {} })}>${SCENE_IDS[i]}</button>`
              : html`<span class="scmini off" title="empty">${SCENE_IDS[i]}</span>`; })}
        </div>
      </div>
    </div>`;
  };

  // La barre des Presets vit DANS la rangée des sous-onglets (Library | Setlists), pas sur une
  // ligne à part : c'est l'emplacement que la Library réserve déjà aux pages (Kits, Grooves,
  // Samples s'en servent). Une ligne de moins, et le contenu remonte d'autant.
  useEffect(() => {
    setSubToolbar(html`
      <!-- Ni titre ni compteur (retrait 2026-07-28) : le mot « Presets » est déjà dans la
           nav du haut, et le décompte « n/N · n on the foot » ne servait aucune décision — les
           badges #NN des cartes disent déjà ce qui est au pied, preset par preset. -->
        <!-- Setlist ACTIVE : les badges #NN et le sélecteur de bank agissent sur ELLE (contrat
             docs/setlists.md). Changer ici change ce que fait le PIED — d'où le libellé explicite
             et le renvoi vers l'onglet Setlists pour tout le reste (créer, figer, supprimer). -->
        ${/* UNE barre pour Presets ET Patches (list-toolbar.js) : liste regardée, loupe, tri, filtres résumés */''}
        <${ListToolbar} kind="songs" lists=${songLists} viewId=${viewId} footId=${activeSl} onView=${setViewId}
          q=${qRaw} setQ=${setQ} placeholder="Search presets…"
          sorts=${[['bank', 'Setlist #', assign === 'free' ? 'these presets are in no setlist' : ''], ['az', 'A → Z'], ['za', 'Z → A'], ['style', 'Style']]}
          sort=${sort} setSort=${setSort}
          filters=${[
            { id: 'in', title: 'In « ' + setName + ' »', def: 'both', value: assign,
              options: [['both', 'All'], ['assigned', 'In the setlist'], ['free', 'Not in it']],
              set: v => { setAssign(v); setSort(v === 'free' ? 'az' : 'bank'); } },
            ...(allTags.length ? [{ id: 'tag', title: 'Tag', def: 'all', value: tag,
              options: [['all', 'All'], ...allTags.map(t => [t, t])], set: setTag }] : []),
          ]} />`);
    return () => setSubToolbar(null);
  // ⚠ DÉPENDANCES PRIMITIVES UNIQUEMENT. `banks` et `sls` sont des TABLEAUX reconstruits à
  // chaque rendu (`(x || {}).y || []`) : comparés par RÉFÉRENCE ils changent toujours, l'effet
  // repart, republie la barre, provoque un rendu… et l'onglet se fige. C'est ce qui a fait
  // « l'app met beaucoup de temps à charger » le 2026-07-27 — en réalité une boucle infinie.
  // On dérive donc des clés STABLES.
  }, [list.length, presets.length, banks.join('|'), sls.map(x => x.id + ':' + x.name).join('|'),
      activeSl, viewId, qRaw, sort, assign, tag, allTags.length]);

  return html`<div class="library">
    <div class="lib-grid" onClick=${() => menu && setMenu(null)}>
      ${list.length ? html`<div class="plist">${list.map(Card)}</div>` : (() => {
        // « Installed on the rack » puis rien à l'écran (2026-09-15) : un preset poussé depuis
        // golem.fm arrive SANS bank, et la vue par défaut est « On the foot ». L'état vide dit où
        // sont les presets au lieu de « No presets match ».
        const other = assign === 'both' ? [] : presets.filter(p => (tag === 'all' || (p.tags || []).includes(tag)) && (assign === 'assigned') !== (slotOf(p.id) >= 0)
          && (!q || (p.name + ' ' + (p.artist || '') + ' ' + (p.tags || []).join(' ')).toLowerCase().includes(q)));
        if (!other.length) return html`<div class="empty">No presets${q || tag !== 'all' ? ' match' : ' yet — push one from golem.fm or save one from the Designer'}.</div>`;
        return html`<div class="empty">${assign === 'assigned'
          ? html`Nothing in « ${esc(setName)} » yet — <b>${other.length}</b> preset${other.length > 1 ? 's' : ''} not in it (${other.slice(0, 3).map(p => esc(p.name)).join(', ')}${other.length > 3 ? '…' : ''}). <button class="mini" onClick=${() => setAssign('both')}>Show all</button> — then tap the # on a card.`
          : html`Every preset is in « ${esc(setName)} » — <button class="mini" onClick=${() => setAssign('both')}>Show all</button>.`}</div>`;
      })()}
    </div>
    ${picker ? html`<${BankPicker} pid=${picker} banks=${banks} presets=${presets} footName=${viewSl && viewSl.name} footId=${viewId} footLines=${viewSl && viewSl.lines} onFoot=${viewId === activeSl}
        onPick=${slot => assignTo(picker, slot)} onClose=${() => setPicker(null)} />` : ''}
    ${settingsP ? html`<${PresetSettings} p=${settingsP} upd=${settingsUpd} onClose=${() => { setSettingsP(null); refresh(); }} />` : ''}
  </div>`;
}


// ── choix de bank : grille 00-18 (+ overflow) — libre = 1 tap, occupée = 2 taps (armer/confirmer) ──
// Exporté : réutilisé par le Designer (pill de bank à côté du BPM).
// La feuille « quelle bank ? » — NOMME sa liste (docs/setlists.md §0 : une bank est une ligne d'UNE liste).
// `footName` : la liste au pied (celle de `banks`). `browse` : on peut choisir une AUTRE setlist de
// morceaux (préparer samedi pendant que la répète est au pied) — la grille se redessine avec ses lignes,
// et `onPick(slot, sl)` reçoit la setlist choisie (null = la liste au pied). Les sound lists ne sont pas
// proposées : un preset n'y entre pas (patch-as-preset §11).
export function BankPicker({ pid, banks, presets, onPick, onClose, footName, footId, browse, footLines, onFoot = true, sounds = false, onRemove, onSetCurrent, onSwap }) {
  const [arm, setArm] = useState(null);           // slot occupé « armé » pour remplacement
  const [other, setOther] = useState(null);       // setlist choisie ≠ liste au pied (objet de /api/setlists)
  const [listOpen, setListOpen] = useState(false);
  const { data: all } = useAsync(() => browse ? fetch('/api/setlists').then(r => r.json()).catch(() => null) : Promise.resolve(null), [browse]);
  const songLists = ((all || {}).setlists || []).filter(sl => sl.kind !== 'sounds' && sl.id !== footId);
  const CAP = 19;
  // ── GLISSER-DÉPOSER UNE BANK (2026-10-08) : appui long sur une bank occupée, glisser, relâcher sur une autre
  // -> les deux ÉCHANGENT leur place (POST …/swap) ; rien d'autre ne bouge. Écouteurs sur `window`, posés à l'appui
  // (même idiome que le glisser des parties de l'arrangement : le doigt quitte la case dès qu'il bouge).
  const [dragFrom, setDragFrom] = useState(-1);
  const [dragOver, setDragOver] = useState(-1);
  // VISIBLE (2026-10-08 : « on ne comprend pas qu'on attrape un bloc ») : la case GROSSIT pendant l'appui
  // (`pressI`), puis une COPIE de la carte suit le doigt (`ghost`) ; la case d'origine devient un emplacement en
  // pointillés et la cible dit ce qui va se passer (« ⇄ swap » / « → move here »).
  const [pressI, setPressI] = useState(-1);
  const [ghost, setGhost] = useState(null);
  const latest = useRef({}); latest.current = { other, onSwap };
  const dg = useRef(null);
  if (!dg.current) {
    const cellAt = (x, y) => { const el = document.elementFromPoint(x, y); const c = el && el.closest && el.closest('.bp-cell');
      return c && c.dataset.i != null ? Number(c.dataset.i) : -1; };
    const st = { timer: null, from: -1, on: false, moved: false, x: 0, y: 0, label: '' };
    const move = e => {
      st.x = e.clientX; st.y = e.clientY;
      if (!st.on) return;
      e.preventDefault();
      setDragOver(cellAt(e.clientX, e.clientY));
      setGhost(g => g && { ...g, x: e.clientX, y: e.clientY });
    };
    const up = async e => {
      clearTimeout(st.timer);
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up);
      if (st.on) {
        st.moved = true;
        const to = cellAt(e.clientX, e.clientY), from = st.from, L = latest.current;
        if (to >= 0 && to !== from && L.onSwap) {
          const r = await L.onSwap(from, to, L.other);
          if (L.other && r && r.lines) setOther(r);           // l'autre setlist : sa grille suit tout de suite
        }
      }
      st.on = false; setDragFrom(-1); setDragOver(-1); setPressI(-1); setGhost(null);
    };
    const down = (i, e, label) => {
      st.from = i; st.on = false; st.moved = false; st.x = e.clientX; st.y = e.clientY; st.label = label;
      setPressI(i);
      window.addEventListener('pointermove', move, { passive: false });
      window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
      st.timer = setTimeout(() => {
        st.on = true; setPressI(-1); setDragFrom(i); setDragOver(i);
        setGhost({ i, label: st.label, x: st.x, y: st.y });
        try { navigator.vibrate && navigator.vibrate(15); } catch (er) { /* pas de vibreur : rien */ }
      }, 350);
    };
    dg.current = { st, down };
  }
  const grid = other ? (other.presets || []) : banks;
  const total = Math.max(grid.length, CAP);
  const known = id => !!(presets || []).find(x => x.id === id);
  const nameOf = id => { const p = (presets || []).find(x => x.id === id); return p ? p.name : id; };
  const mine = grid.indexOf(pid);
  const lines = (other ? other.lines : footLines) || [];
  const cell = i => {
    const cur = grid[i] || '';
    const isMine = cur === pid;
    // une ligne de MORCEAU sans preset (titre seul, chanson du répertoire) n'est PAS libre : la choisir
    // d'un tap la remplaçait, et set_presets la perdait en silence (trouvé le 2026-09-30, « Short Summer »)
    const ln = lines[i] || null;
    const song = !cur && ln && (ln.title || ln.band_song) ? (ln.title || 'a song') : null;
    // un preset EFFACÉ (id sans fichier) est un emplacement LIBRE, pas un nom fantôme : le
    // sélecteur proposait « frusciante » des semaines après sa suppression (2026-09-08)
    const ghost = !!cur && !known(cur) && !(ln && ln.title);
    const free = (!cur && !song) || ghost;
    const armed = arm === i;
    // ✕ VIDER LA BANK (2026-10-08 : « on ne peut pas supprimer un preset assigné ») : la ligne quitte la
    // setlist mais garde son RANG, vide — les banks suivantes ne bougent pas. Le preset et la chanson restent.
    const removable = onRemove && !free && ln && ln.id;
    const label = isMine ? nameOf(pid) : (song ? '♪ ' + song : (ln && ln.title) || nameOf(cur));   // texte brut : htm l'échappe
    const isDrop = dragFrom >= 0 && dragOver === i && dragFrom !== i;
    return html`<button class=${cls('bp-cell', free && 'free', isMine && 'mine', armed && 'armed', pressI === i && 'press', dragFrom === i && 'lift', isDrop && 'drop', onSwap && !free && 'grab')}
      data-i=${i} title=${ghost ? 'free — « ' + cur + ' » no longer exists' : (onSwap && !free ? 'hold and drag to another bank to swap them' : '')}
      onPointerDown=${e => onSwap && !free && dg.current.down(i, e, label)}
      onClick=${() => { if (dg.current.st.moved) { dg.current.st.moved = false; return; }
        if (isMine) return onClose(); if (free || armed) onPick(i, other); else setArm(i); }}>
      <b>${bankNo(i)}</b>
      ${/* UNE BANK QUI PORTE UNE CHANSON SE DIT (2026-10-08) : ♪ — la chanson apporte son preset, son arrangement,
            ses stems ; la vider l'enlève de la setlist. Une bank « preset seul » n'a pas de ♪. */''}
      <span>${dragFrom === i ? 'moving…' : isDrop ? (free ? '→ move here' : '⇄ swap')
        : isMine ? (ln && ln.band_song ? '♪ here ✓' : 'here ✓') : free ? 'free' : (armed ? 'replace ?'
        : esc(song ? '♪ ' + song : ln && ln.band_song ? '♪ ' + (ln.title || nameOf(cur)) : (ln && ln.title) || nameOf(cur)))}</span>
      ${removable ? html`<i class="bp-x" title=${ln.band_song ? 'remove the song « ' + (ln.title || nameOf(cur)) + ' » from this setlist — the song itself is kept in Songs; the banks after it do not move'
        : 'empty this bank — the banks after it do not move (the preset is kept)'}
        onClick=${e => { e.stopPropagation(); setArm(null); onRemove(i, other, ln); }}>✕</i>` : ''}
    </button>`;
  };
  const listName = other ? (other.name || other.id) : (footName || 'the foot list');
  const ghostCard = ghost ? html`<div class="bp-ghost" style=${`left:${ghost.x}px; top:${ghost.y}px`}>
    <b>${bankNo(ghost.i)}</b><span>${ghost.label}</span></div>` : '';
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card bp">
      <button class="close" onClick=${onClose}>×</button>
      <h2>« ${esc(nameOf(pid))} » in
        ${browse ? html`<button class=${cls('bp-list', listOpen && 'open')} onClick=${() => setListOpen(!listOpen)}
            title="choose the setlist">▤ ${esc(listName)} ▾</button>` : html`<span class="bp-list static">${sounds ? '⛓' : '▤'} ${esc(listName)}</span>`}
        ${other || !onFoot ? html`<span class="bp-foot off">not current</span>` : html`<span class="bp-foot">current</span>`}</h2>
      ${/* « SET AS CURRENT » (2026-10-08) : la setlist regardée ici devient celle que suivent le pédalier ET /live —
            le choisir n'était possible que par un appui long sur la pastille de /live ou dans Songs ▸ Setlists. */''}
      ${other && onSetCurrent ? html`<button class="bp-current" onClick=${async () => { await onSetCurrent(other); setOther(null); }}
          title="the pedalboard and Live follow this setlist from now on">Set as current<small>pedalboard · Live</small></button>` : ''}
      ${listOpen ? html`<div class="bp-lists">
        <button class=${cls('chip', !other && 'on')} onClick=${() => { setOther(null); setArm(null); setListOpen(false); }}>
          ▤ ${esc(footName || 'the foot list')} <small>current</small></button>
        ${all === null ? html`<span class="muted">…</span>` : songLists.map(sl => html`<button class=${cls('chip', other && other.id === sl.id && 'on')}
          onClick=${() => { setOther(sl); setArm(null); setListOpen(false); }}>▤ ${esc(sl.name || sl.id)}
          <small>${(sl.presets || []).includes(pid) ? '✓ in it' : (sl.lines || []).length + '/' + CAP}</small></button>`)}
        ${all && !songLists.length ? html`<span class="muted">no other setlist of songs — create one in Songs ▸ Setlists</span>` : ''}
      </div>` : ''}
      <p class="muted">Tap a free bank — or tap an occupied one twice to replace${onRemove ? ', ✕ to empty it' : ''}${onSwap ? ', hold and drag to swap two banks' : ''}. ${mine >= 0 ? `Currently on #${bankNo(mine)}.` : ''}
        ${other ? ' Writing here does not change what the pedalboard plays.' : ''}</p>
      <div class=${cls('bp-grid', dragFrom >= 0 && 'dragging')}>${Array.from({ length: total }, (_, i) => cell(i))}</div>
      ${ghostCard}
      <p class="muted">${bankNo(0)}–${bankNo(CAP - 1)} = the ${CAP} banks of the pedalboard (UP/DOWN)</p>
    </div></div>`;
}

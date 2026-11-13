// SPDX-License-Identifier: GPL-3.0-or-later
// Page ATELIER v2 — éditeur « grille » façon Quad Cortex : lanes = rangées de tuiles-icônes,
// tiroir de blocs par catégorie (au +), panneau de potards au tap d'une tuile (bottom sheet),
// scènes A-H (le tap d'une scène filtre l'actif/bypass par scène). Onglet SIGNAL conservé.
import { html, useState, useEffect, useRef, useAsync, api, post, del, cls, esc, go, pad2, bankNo, setTopSlot, longPress, lpFired, getCatalog, refreshCatalog, takePendingPreset, takePendingTab, takePendingAction, takeDraftMutations, LIVE_PALETTE, GENRE_FAMILIES } from './lib.js';
import { ArrangementPage } from './designer-arrangement.js';
// blocs qu'une section ne force JAMAIS : le volume système n'est pas une pédale, et le
// tuner/les services ne sont pas du son. (docs/arrangement.md §3 bis)
const ARR_NEVER = ['volume', 'tuner'];
import { defaultModel } from './capture-gain.js';
import { sortLanes, drumsetsOf, drumsetLanes, laneIdFor, ROLE_ICON, patchDraft, PATCH_REALM, SCENE_IDS, LANE_LETTER, MAX_BLOCKS, blkColor, ICON, bid, isV2, toChain, toVoice, toKeys, blank, needsModel, hydrateBlockMeta, migrateConfig, resolveStarts, STARTS_TYPES, SPECIAL_CAT, blockContent, CONTENT_PARAM, toLanesV2, normLanes, laneBlocks, sameSound, newLaneId, inOptsOf, MIDI_ROLES, CONFIG_SERVICE_TYPES, CONFIG_GEN_TYPES, CONFIG_REC_TYPES, CONFIG_ARR_TYPES, renumberScenes, ensureHeadCabs, pinWhammyFirst, lanesByPerson, patchLaneFix, seatPatchLane, alignBoundInputs, refKey, swapVitalPreset } from './designer-model.js';
import { Icon, FOOTSW } from './icons.js';
import { menuEntry as startupEntry } from './startup-model.mjs';   // l'accueil au démarrage (menu ⋯)
import { CategoryDrawer, AmpPicker } from './designer-drawer.js';
import { SceneDictionary } from './designer-scenes.js';
import { LaneApplySheet } from './designer-lane-apply.js';
import { GOLEM_FX, assignLaneState, newLaneState, renameLaneState, propagateLaneStates, laneIdentity, laneLineName, laneMutedIn, isLegacyBranchMute, ensureLaneStates } from './designer-model.js';
import { IoSheet, LaneTabs, addChoicesFor, sheetRowsFor as _sheetRowsFor, laneObj as _laneObj, laneSpecOf as _laneSpecOf, laneDisabled as _laneDisabled, laneOffCard as _laneOffCard, laneWaitsCard as _laneWaitsCard } from './designer-lanes.js';
import { DrumsetSheet, DrumsetHead, drumsetPlan, formsFor, elLabel, KIT_MIX } from './designer-drumset.js';
import { PatchBrowser } from './designer-browse.js';
import { PresetBrowser } from './designer-browser.js';
import { BankPicker } from './page-setlists.js';
import { ParamSheet, PresetSettings, NameSheet, SceneSheet, ScenePlus, Picker, OUT_OPTS, loopRows } from './designer-sheets.js';
const VCAP_ICON = '◈', VCAP_COLOR = '#8b9fd7';   // capture d'un VST : la marque du bloc VST d'origine
import { VstHostSheet } from './designer-vst-host.js';
import { PluginView } from './plugin-view.js';   // la fenêtre de Vital filmée, sous Linux (docs/plugin-window.md)
import { captureHostState } from './vst-host-model.mjs';
import { ArrangementSheet, linesOfPreset } from './designer-arrsheet.js';   // le bloc ▤ ouvre la chanson (arrangement.md §4 bis)
import { ArrangementLane } from './designer-arrlane.js';
import { useSongCtx, SongBar } from './designer-song.js';     // la chanson chargée (docs/designer-song.md)    // la ligne ⚙ = un panneau, pas une chaîne (version B validée)
import { layoutChain } from './chain-layout.js';
import { BlockStatusSheet, MissingBanner, blockSig } from './designer-blockstatus.js';   // docs/block-status.md
import { PedalView } from './designer-pedalview.js';     // la vue pédalier (docs/designer-glyphs-pedals.md §2)
import { pedalValues } from './golem-visuals.js';

// long-press = assigner (convention QC) : longPress/lpFired partagés (lib.js).


// Buffer d'édition persistant HORS du composant : on retrouve son travail en cours (chaîne + scène active,
// même non sauvegardé) en revenant sur le Designer après avoir changé de page. Vit tant que l'app est ouverte.
let _dstate = { p: null, scene: 0, rev: null, takeover: false };
// ── LOT D (docs/devices-people.md) : l'identifiant d'ÉDITEUR de cette page. Le bridge refuse l'écriture d'un
// autre écran partie d'une révision dépassée du brouillon ; une page rechargée est un nouvel éditeur.
const EDITOR = Math.random().toString(36).slice(2, 12);

// icône FOOTSWITCH : icons.js (partagée avec la tuile Arrangement)

// service de MODE d'un type de bloc de service (miroir de modes.SERVICES côté bridge) — le veto
// « preset ∧ mode » se voit ICI : absent du tiroir « Add service », et une tuile déjà posée le dit.
const SVC_OF_TYPE = { looper: 'looper', 'backing-track': 'backing', sample: 'sample', drums: 'drummachine',
                      standard: 'standard', rec: 'perfrec', arrangement: 'arrangement', compo: 'compo' };
const svcVetoed = (rig, type) => {
  const k = SVC_OF_TYPE[type]; if (!k) return false;
  const sv = ((rig && rig.mode) || {}).services || {};
  return k in sv && sv[k] === false;
};

export function DesignerPage({ rig, sub }) {
  const { data: presets, reload: reloadPresets } = useAsync(() => fetch('/api/presets').then(r => r.json()), []);
  const { data: effects } = useAsync(() => fetch('/api/effects').then(r => r.json())
    .then(d => { hydrateBlockMeta(d.effects || d, d); return d; }), []);
  const { data: catalog, reload: reloadCatalog } = useAsync(getCatalog, []);
  // pédales MIDI INSTALLÉES (registre, docs/pedal-registry.md) -> catégorie `hardware` du tiroir.
  // La Whammy DT est exclue : elle a son bloc dédié (chemin nominatif prouvé matériel).
  const { data: hwMaps } = useAsync(() => fetch('/api/mappings').then(r => r.json()).catch(() => null), []);
  const hwPedals = ((hwMaps && hwMaps.pedals) || []).filter(pd => pd.id !== 'whammy-dt');
  // presets de bloc marqués `default` : appliqués à l'AJOUT (le bloc naît avec un réglage musical)
  const { data: bpDef } = useAsync(() => fetch('/api/block-defaults').then(r => r.json()).catch(() => null), []);
  const blockDefaults = (bpDef && bpDef.defaults) || {};
  const { data: banksData, reload: reloadBanks } = useAsync(() => fetch('/api/foot-list').then(r => r.json()), []);
  const { data: listsData, reload: reloadLists } = useAsync(() => fetch('/api/setlists').then(r => r.json()), []);   // le « +2 » de la pastille
  const [p, setP0] = useState(() => _dstate.p || blank());
  // ⚠ UN SEUL point d'entrée du document : les ids de scènes redeviennent POSITIONNELS à chaque
  // édition ET à chaque chargement (renumberScenes, designer-model.js) — sans quoi une scène
  // supprimée laissait « A C C » dans la barre (patch 1983, 2026-09-14).
  const quiet = useRef(null);                      // le document réaligné par alignBoundInputs (ni audition ni sauvegarde)
  const setP = v => setP0(prev => { const raw = typeof v === 'function' ? v(prev) : v;
    const out = pinWhammyFirst(ensureHeadCabs(renumberScenes(raw)));
    if (quiet.current && quiet.current === raw) quiet.current = out;    // un réalignement garde sa marque (voir alignBoundInputs)
    return out; });
  const restoring = useRef(!_dstate.p);           // page FRAÎCHE (reload/reboot) : restaurer le buffer serveur
  const baseRev = useRef(_dstate.rev);             // LOT D : révision du brouillon sur laquelle cet écran travaille
  const takeover = useRef(!!_dstate.takeover);     // LOT D : prochain envoi = geste explicite (force)
  const initialP = useRef(null);
  if (initialP.current === null) initialP.current = _dstate.p ? false : null;
  const [scene, setScene] = useState(() => _dstate.scene || 0);   // index de scène active (filtre on/off + toggle scène)
  if (initialP.current === null) initialP.current = p;             // référence du blank de montage
  // La sandbox est « sauvegardée à sa manière » : le bridge persiste chaque audition dans
  // presets/.sandbox.json -> ici on restaure le travail non sauvegardé après un reload OU un reboot.
  useEffect(() => {
    // les écritures d'autres pages sur CE preset (scène créée depuis le tableau des parties) rejoignent le brouillon
    { const muts = takeDraftMutations(_dstate.p && _dstate.p.id); if (muts.length) upd(n => muts.forEach(fn => fn(n))); }
    // « ✎ edit » depuis la Library : le preset demandé prime sur la restauration sandbox
    const pending = takePendingPreset();
    const tab = takePendingTab();
    const act = takePendingAction();
    // « ＋ Add ▸ Drums » depuis Songs ▸ Patches arrive ici : le tiroir de kit s'ouvre comme si on
    // avait créé le patch depuis le Designer. Le geste est le même, la porte ne doit pas décider.
    if (act === 'drumset') { setDsPick(null); setDsPlan([]); setDsOpen(true); }
    if (pending) { restoring.current = false;
      if (tab) setInTab(tab);                  // « + Sampler » depuis une ligne de setlist -> l'onglet ⚙
      // un DOC = draft à auditionner (patch ouvert depuis Songs ▸ Patches) ; un id = fichier
      if (typeof pending === 'object') loadDraft(pending); else loadPreset(pending);
      return; }
    if (!restoring.current) return;
    fetch('/api/sandbox').then(r => r.json()).then(d => {
      restoring.current = false;
      // ⚠ 2026-09-15 : la garde exigeait `preset.guitar` — la clé LEGACY. Un document en lanes v2
      // (Paper Kite, tout patch venu de golem.fm) ne la porte plus : le rechargement de la page
      // ouvrait un banc vide au lieu du brouillon. La liste de lanes suffit, comme dans loadDraft.
      if (d && d.preset && (d.preset.guitar || isV2(d.preset))) {
        skipSave.current = true;
        baseRev.current = _dstate.rev = Number(d.edit_rev) || 0;   // la révision sur laquelle cet écran commence
        d.preset.guitar = toChain(d.preset.guitar);
        d.preset.voice = toVoice(d.preset.voice);
        d.preset.keys = toKeys(d.preset.keys);
        migrateConfig(d.preset);                                   // services -> lane config
        toLanesV2(d.preset, laneRoleOfKey);                        // lot 3 : la liste de lanes
        patchLaneFix(d.preset);                                    // mode patch : la lane porte le rôle du patch (drums)
        // ⚠ ROUVRIR N'EST PAS JOUER (2026-10-07) : ce rendu-là n'auditionne PAS. Il le faisait, et le bridge
        // « adoptait » le brouillon -> un simple rechargement de page RAPPELAIT un preset sur le rig (Paper Kite
        // rappelé au pied, F5 dans le Designer : le rig repartait sur le patch Night Bloom). On affiche ; la
        // première ÉDITION auditionnera, comme partout ailleurs.
        setP(cur => { if (cur !== initialP.current) return cur;     // ne pas écraser une édition déjà commencée
          noAudition.current = true; return d.preset; });
        const idx = (d.preset.scenes || []).findIndex(sc => sc.id === d.scene);
        if (idx >= 0) setScene(idx);
      } else {
        // aucun brouillon : le banc de montage (blank(), guitare sur '1') devient celui de la CARTE — sans
        // audition, comme une restauration (audit 2026-10-10 : première édition d'un rack neuf = IN 1)
        setP(cur => { if (cur !== initialP.current) return cur; noAudition.current = true; return newBlank(); });
      }
    }).catch(() => { restoring.current = false; });
  }, []);
  const [sel, setSel] = useState(null);           // bloc sélectionné (panneau params) : {li,i} | {post:i}
  // Les espaces connus du rack (roster golem.fm). Vide tant qu'aucun appairage n'a eu lieu —
  // la feuille du bloc REC n'affiche alors aucune rangée « Takes go to ».
  const [bandData, setBandData] = useState({});
  const loadBand = () => fetch('/api/band').then(r => r.json()).then(setBandData).catch(() => {});
  useEffect(() => { loadBand(); }, []);
  const [drawer, setDrawer] = useState(null);     // tiroir d'ajout : {li} | {post:true}
  const [selTab, setSelTab] = useState('params'); // onglet du tiroir de bloc : params | assign | presets
  // DEV (captures de vérification) : ?dopen=<preset>&dsel=pre0&dtab=presets ouvre un preset, sélectionne le bloc n de la
  // zone `pre` de la lane courante et l'onglet demandé — le tiroir ne s'ouvre pas autrement sans un doigt
  const devSel = useRef(null);
  if (devSel.current === null) { const m = location.search.match(/[?&]dsel=pre(\d+)/); devSel.current = m ? Number(m[1]) : false; }
  const [pickAmp, setPickAmp] = useState(null);   // {li,i} | {post:i}
  const [saved, setSaved] = useState('');
  const [saving, setSaving] = useState(false);         // auto-save en cours (indicateur persistant)
  const [settings, setSettings] = useState(false);   // sheet réglages du preset (nom/style/FCB)
  const [outPick, setOutPick] = useState(null);       // popover choix de sortie : '1' (In1) | '2' (In2) | null
  const [naming, setNaming] = useState(null);         // feuille « nommer » : { dup:bool, name? } | null
  const [sceneSheet, setSceneSheet] = useState(false); // feuille Scène (renommer/niveau/supprimer) au re-tap onglet actif
  const [scenePlus, setScenePlus] = useState(false);   // popover du + de scène (nouvelle/dupliquer/importer)
  const [saveMenu, setSaveMenu] = useState(false);     // popover ⋯ : Assign in a preset
  // VUE Blocks | Pedals de la chaîne (menu ⋯, docs/designer-glyphs-pedals.md) : une préférence d'affichage de cet écran
  const [dview, setDview0] = useState(() => { try { return localStorage.getItem('golem.designer.view') || 'blocks'; } catch (e) { return 'blocks'; } });
  const setDview = v => { setDview0(v); try { localStorage.setItem('golem.designer.view', v); } catch (e) { /* navigation privée */ } };
  // l'entrée de menu, dans les DEUX menus « ⋯ » : celui d'un preset et celui d'un patch (un bouton posé dans un seul
  // des deux est invisible dans l'autre, sans erreur — la panne déjà vécue le 2026-09-20, et revécue ici le 2026-11-13)
  const ViewBtn = () => html`<button class="row-btn sm view-btn" data-doc="designer.menu.view"
      onClick=${() => { setSaveMenu(false); setDview(dview === 'pedals' ? 'blocks' : 'pedals'); }}
      title="the same chain, drawn as a pedalboard — tap a pedal: on / off in this scene · long press: its settings">
      ▦ View: <b class=${cls(dview !== 'pedals' && 'on')}>Blocks</b> · <b class=${cls(dview === 'pedals' && 'on')}>Pedals</b></button>`;
  const [browse, setBrowse] = useState(false);         // modal presets (navigateur)
  // ── SÉLECTEUR DE PATCHES (retour 2026-08-02) ────────────────────────────────────────
  // Il était écarté tant qu'un patch n'avait pas de sauvegarde automatique : une flèche aurait
  // jeté le travail en cours sans un mot. Le modèle COPIE l'a débloqué — tout est enregistré en
  // continu, donc changer de patch ne peut plus rien perdre.
  const [patchBrowse, setPatchBrowse] = useState(false);   // true = parcourir ; {into:'1'|'2'|'k'} = déposer dans cette lane
  // DÉPÔT D'UN PATCH DANS UNE LANE DU PRESET (2026-09-08) : le chip ⛓ que les commentaires
  // attendaient depuis le modèle « copie » (docs/patches.md §15). Même geste que le dépôt de la
  // page Patches, mais dans le brouillon : le bridge injecte (pur), le Designer enregistre.
  const openPatchInto = lane => { setPatchRole(laneRole(lane)); setPatchQ(''); setPatchBrowse({ into: lane }); };
  // le chip d'une lane DIT d'où elle vient — tant que c'est vrai. `patch_from` est une mémoire posée
  // à l'injection ; on compare la chaîne de la lane à celle du patch (même forme que scenes_of/
  // chain_of côté bridge) : même son -> « ⛓ Velvetine », retouchée -> « Velvetine · edited » (sameSound, designer-model.js).
  const laneOrigin = id => {
    const L = lanes.find(x => x.id === id) || {}; const from = L.patch_from; if (!from || !from.id) return null;
    const doc = allPatches.find(x => x.id === from.id);
    const same = !!doc && sameSound(doc.chain || {}, L.chain || {});
    return { id: from.id, name: (doc && doc.name) || from.name || from.id, same, gone: !doc };
  };
  const LanePatchChip = lane => { if (patchMode) return '';
    const o = laneOrigin(lane);
    return html`<button class=${cls('mini lane-patch', o && 'from', o && !o.same && 'edited')} data-doc="designer.patch"
      title=${o ? (o.gone ? 'came from « ' + o.name + ' » (patch deleted) — tap to load another' : (o.same ? 'this lane is the patch « ' + o.name + ' » — tap to replace it' : 'came from « ' + o.name + ' », edited since — tap to replace the lane'))
                : 'load a patch into this lane — copies its chain and scenes, replaces what is here'}
      onClick=${() => openPatchInto(lane)}>⛓ ${o ? esc(o.name) + (o.same ? '' : ' · edited') : 'Load a patch'}</button>`; };
  const applyPatchInto = async x => {
    const r = await post('/api/patches/' + encodeURIComponent(x.id) + '/apply', { preset: bodyOf(), lane: patchBrowse && patchBrowse.into }).catch(e => ({ error: String(e) }));
    setPatchBrowse(false);
    if (!r || !r.preset) { flash('✗ ' + ((r && r.error) || 'apply failed')); return; }
    setSel(null); setDrawer(null); setP(toLanesV2(r.preset, laneRoleOfKey)); setScene(0);
    const skip = r.skipped_elements || [];
    const kit = (x.elements || []).length;
    flash('⛓ « ' + (x.name || x.id) + ' » loaded into ' + (kit ? 'the drum kit' : 'the ' + chainName(r.lane) + ' lane')
      + ((r.added_scenes || []).length ? ' — scene' + (r.added_scenes.length > 1 ? 's ' : ' ') + r.added_scenes.join(', ') + ' added to the song' : '')
      + ((r.lost_scenes || []).length ? ' — scene' + (r.lost_scenes.length > 1 ? 's ' : ' ') + r.lost_scenes.join(', ') + ' dropped (song full)' : '')
      + (skip.length ? ' — ' + skip.map(elLabel).join(', ') + (skip.length > 1 ? ' have' : ' has') + ' no input here, skipped' : ''));
  };
  const [patchQ, setPatchQ] = useState('');
  const [patchRole, setPatchRole] = useState(null);    // null = le rôle du patch ouvert
  // ⚠ `reloadPatches` doit suivre CHAQUE mutation du catalogue faite ici (créer, enregistrer, nommer,
  // mettre à jour) : déclaré sans jamais être appelé, le modal « browse patches » ne montrait un
  // patch fraîchement enregistré qu'après un détour par /songs/patches (remontage du composant).
  const { data: patchList, reload: reloadPatches } = useAsync(() => fetch('/api/patches').then(r => r.json()), []);
  // les LIGNES de setlist qui jouent ce preset (docs/setlists.md §9.9) : l'encart « per song » d'un bloc ⚙
  const { data: setlistsD, reload: reloadSetlists } = useAsync(() => fetch('/api/setlists').then(r => r.json()), [p.id]);
  const [arrPick, setArrPick] = useState(null);     // {sid, lid} : la chanson que la ligne ⚙ et le tiroir montrent
  // LE PRESET D'UN COUP D'ŒIL (maquette designer-preset-glance, propositions 1 + 3, 2026-10-08) : la fiche ⓘ
  // et le mini-pédalier de la barre du haut ouvrent chacun leur panneau — {kind: 'info'|'map', x, y}
  const [glance, setGlance] = useState(null);
  const [songPick, setSongPick] = useState(null);       // {slot, sl, songs} : la chanson à ranger dans une bank (assignBank)
  const openGlance = (kind, e) => { const r = e.currentTarget.getBoundingClientRect();
    setGlance(g => g && g.kind === kind ? null : { kind, x: Math.round(r.left), y: Math.round(r.bottom) }); };
  // ── CE QUE L'ARRANGEMENT PILOTE (docs/arrangement.md §4, variante 2) ── la chanson que montre la
  // ligne ⚙ (même choix que ArrangementLane : la ligne choisie, sinon la première qui joue ce preset), son
  // automation (Automation on = bloc de la CHANSON non bypassé, avec des parties), et les types de blocs que
  // ses cases lancent. Ces tuiles prennent le liseré de l'Arrangement ; rien n'est masqué ni grisé.
  const arrRows = linesOfPreset(setlistsD, p.id);
  // LA CHANSON CHARGÉE (docs/designer-song.md §5) : sans choix explicite, la bande Arrangement montre la sienne — sa ligne,
  // sinon la première ligne qui joue cette chanson
  const songCtx = useSongCtx(p, rig);
  const loadedRow = (songCtx.lineId && arrRows.find(r => r.line.id === songCtx.lineId))
    || (songCtx.sid && arrRows.find(r => r.line.band_song === songCtx.sid)) || null;
  const arrPickEff = arrPick || (loadedRow ? { sid: loadedRow.sid, lid: loadedRow.line.id } : null);
  const arrRow = arrRows.find(r => arrPickEff && r.sid === arrPickEff.sid && r.line.id === arrPickEff.lid) || arrRows[0] || null;
  const arrSong = arrRow ? (arrRow.line.arrangement || null) : null;
  const arrAuto = !!arrSong && !arrSong.bypass && ((arrSong.params || {}).sections || []).length > 0;
  const arrCtl = (() => {
    if (!arrAuto) return new Set();
    const r = resolveStarts((arrSong.params || {}).starts, p);
    return new Set(Object.keys(STARTS_TYPES).filter(k => r[k]).map(k => STARTS_TYPES[k]));
  })();
  const arrSongTitle = arrRow ? (arrRow.line.title || p.name || p.id) : '';
  // ⏻ AUTOMATION depuis la pastille de la tuile : l'état de la CHANSON, relu puis réécrit sur sa fiche (jamais la
  // copie résolue de la ligne, qui peut porter les exceptions de la ligne)
  const toggleAutomation = async () => {
    const sidSong = arrRow && arrRow.line.band_song;
    // une bank qui ne porte que le preset n'a pas d'automation à rallumer : la chanson n'est pas sur la ligne (vécu le
    // 2026-10-08 après un « vider la bank ») — on dit quoi faire, au lieu d'un message de plomberie
    if (!sidSong) { flash('no song on this bank — add the song to « ' + ((arrRow && arrRow.sname) || 'the setlist') + ' » from Songs to get its arrangement back'); return; }
    const d = await fetch('/api/song/' + encodeURIComponent(sidSong)).then(r => r.json()).catch(() => null);
    const cur = ((((d || {}).song || {}).sheet) || {}).arrangement;
    if (!cur) { flash('✗ the song has no arrangement yet'); return; }
    const r = await post('/api/song/' + encodeURIComponent(sidSong), { arrangement: { ...cur, bypass: !cur.bypass } }).catch(e => ({ error: String(e) }));
    if (r && r.error) { flash('✗ ' + r.error); return; }
    flash(cur.bypass ? '⏻ automation on for « ' + arrSongTitle + ' »' : '⏻ automation off for « ' + arrSongTitle + ' » — each block plays on its own');
    reloadSetlists();
  };
  const allPatches = (patchList || {}).patches || [];
  const [bankPick, setBankPick] = useState(false);     // picker de bank FCB (pill à côté du BPM)
  const commitTimer = useRef(null);
  const pendingSave = useRef(null);                // une audition programmée et pas encore partie : son saveToo, sinon null
  const noAudition = useRef(false);       // le prochain rendu du document est une RESTAURATION : ni audition ni sauvegarde
  const skipSave = useRef(true);          // true au montage + juste après un load : on écoute mais on ne sauve pas

  const fx = (effects && effects.effects) || [];
  const cats = (effects && effects.categories) || [];
  // archétypes NOMMÉS (docs/archive/named-pedals.md) : pédales (Big Muff…) ET amplis (5150…) = blocs
  // pedal-nam / amp pré-liés à une recherche de capture. Identité (nom/glyphe/couleur) portée par
  // la VARIANTE ; le bloc stocké reste type:"pedal-nam"|"amp" (moteur inchangé). block/gear/category
  // rendent le système uniforme : le tiroir filtre par category, le picker cherche par gear.
  const archetypes = [
    ...((effects && effects.pedals) || []).map(a => ({ ...a, block: 'pedal-nam', gear: 'pedal', category: 'drive', roles: a.roles || ['guitar'] })),
    // amplis : gears = TOUTES les captures du modèle (têtes seules + full-rig) ; le type de bloc
    // posé suivra la capture choisie (amp-nam si head-only, amp sinon) — voir addPedal.
    ...((effects && effects.amps) || []).map(a => ({ ...a, block: 'amp', gear: 'amp-cab', gears: ['amp', 'amp-cab'], category: 'amp', roles: a.roles || ['guitar'] })),
    // cabs nommés (SEULEMENT ceux qui ont des IRs en library — liste élaguée côté effects.json)
    ...((effects && effects.cabs) || []).map(a => ({ ...a, block: 'cab', gear: 'cab', gears: ['cab'], category: 'cab', roles: a.roles || ['guitar'] })),
  ];
  const pedalArch = id => archetypes.find(a => a.id === id);
  const fxDef = type => fx.find(e => e.type === type) || {};
  const fxName = type => fxDef(type).name || type;
  const fxShort = type => fxDef(type).short || fxDef(type).name || type;   // tuiles étroites : nom court
  // Le bloc Click porte LE MÊME métronome que la page Live (icons.js) : un bloc doit se
  // reconnaître d'un écran à l'autre — le glyphe « ◔ » du catalogue ne ressemblait à rien de ce
  // qu'on voit en jouant. Même exception que le clavier de Vital, au même endroit.
  const ICON_SVG_TYPES = ['vital', 'organ', 'piano', 'ep', 'pads', 'drums'];
  const fxIcon = type => type === 'click' ? html`<span class="tile-svg"><${Icon} id="metronome" /></span>`
    : type === 'drumkit' ? html`<span class="tile-svg"><${Icon} id="drumkit" /></span>`   // le kit : un dessin, pas l'emoji 🥁
    : ICON_SVG_TYPES.includes(type) ? html`<span class="tile-svg">${ICON[type]}</span>`   // les instruments : au trait (2026-10-14)
    : type === 'compo' ? html`<span class="tile-svg"><${Icon} id="riff" /></span>`         // Riff : une flamme dessinée
    : (ICON[type] || fxDef(type).icon || '▫');

  // preset NEUF = le matériel physiquement câblé est déjà là : la Whammy DT (avant l'entrée,
  // pilotée EXP1) naît en tête de chaîne si le patch la déclare (config-pas-code). Le volume
  // (EXP2) n'a PAS besoin de bloc : ensure_volume l'injecte côté bridge à chaque émission.
  const newBlank = () => {
    const b = blank();
    // ── UN PRESET NEUF NAÎT DES ENTRÉES DE LA CARTE DU MODE (2026-09-13) : blank() posait
    // toujours les trois lanes d'origine (Input 1 / Input 2 / Keys, rôles par défaut) — les
    // réglages de Settings ▸ Mode ▸ Inputs (IN 1 Guitar, IN 2 Voice, USB 1 Keys + Pads) n'y
    // étaient pas. Même fabrique que la feuille « Lanes & inputs » : une lane par entrée qui a un
    // instrument, nom / rôle / numéro pris au patch, ordre du contrat. Carte muette → l'ancien banc.
    const rows = sheetRowsFor([]).filter(r => !r.none && (r.kind === 'in' || r.kind === 'midi'));
    if (rows.length) {
      const ids = [];
      b.lanes = sortLanes(rows.map(r => { const spec = laneSpecOf(r, ids); ids.push(spec.id); return laneObj(spec); }));
      const g = b.lanes.find(l => l.role === 'guitar' || l.role === 'bass');
      b.scenes[0].levels = g ? { [g.id]: -6 } : {};
    }
    if (patch.midi_out && patch.midi_out.role === 'whammy-dt') {
      const L = (b.lanes || []).find(l => l.id === 'guitar' || l.role === 'guitar');
      if (L) L.chain.pre.unshift({ type: 'whammy-dt', id: bid('whammy-dt'), params: { won: false, don: false } });
    }
    return b;
  };
  const loadPreset = async id => {
    setSel(null); setDrawer(null); skipSave.current = true;   // charger = écouter, pas sauver
    takeover.current = _dstate.takeover = true;                                    // ouvrir un preset est un geste : il prend le brouillon
    if (!id) { setP(newBlank()); setScene(0); return; }
    const full = await fetch('/api/preset/' + id).then(r => r.json());
    full.guitar = toChain(full.guitar);
    full.voice = toVoice(full.voice);                          // anciens types nus -> blocs riches
    full.keys = toKeys(full.keys);                             // lane Keys (absente des vieux presets)
    migrateConfig(full);                                       // services -> lane config
    toLanesV2(full, laneRoleOfKey);                            // LOT 3 : la liste de lanes est le document
    setP(full); setScene(0);
  };
  // charge un DOCUMENT dans l'edit-buffer (sandbox) : draft NON nommé, éditable + auditionné — un patch
  // ouvert depuis Songs ▸ Patches, un banc vide depuis « + Add ». (Le créateur IA, qui passait ici
  // aussi, a quitté le rack le 2026-09-09 : il vit sur golem.fm, docs/patches.md §14.)
  // LOT D : reprendre le brouillon TEL QUE LE BRIDGE LE TIENT (écrit par un autre écran) — même normalisation
  // que la restauration au montage, id conservé (c'est peut-être un preset nommé), révision de base à jour
  const loadDraftKeepId = d => {
    skipSave.current = true;
    const q = d.preset;
    q.guitar = toChain(q.guitar); q.voice = toVoice(q.voice); q.keys = toKeys(q.keys);
    migrateConfig(q); toLanesV2(q, laneRoleOfKey);
    baseRev.current = _dstate.rev = Number(d.edit_rev) || 0; takeover.current = _dstate.takeover = false;
    setSel(null); setDrawer(null); setP(q);
    const idx = (q.scenes || []).findIndex(sc => sc.id === d.scene); setScene(idx >= 0 ? idx : 0);
    flash('newer draft loaded');
  };
  const loadDraft = ap => {
    skipSave.current = true;                                    // audition, pas sauve (draft anonyme)
    takeover.current = _dstate.takeover = true;                                    // déposer / ouvrir un patch : un geste qui prend le brouillon
    // ── UN DOCUMENT NEUF NAÎT DE LA CARTE, D'OÙ QU'IL VIENNE (audit 2026-10-10) ──────────────────────────
    // « + Add » (Presets) envoyait blank() tel quel — guitare sur '1' (le micro sur le rack de dev), voix vide sur '2'
    // (la prise guitare) — et la fabrique qui lit la carte (newBlank) n'était appelée par personne. « + New
    // patch » (Patches) posait un patch sans l'asseoir. C'est ICI, la seule porte, que ça se décide.
    if (ap && ap.__new) { setSel(null); setDrawer(null); setP(newBlank()); setScene(0); return; }
    const p = { ...structuredClone(ap), id: 'nouveau-preset' };
    // ⚠ 2026-09-11 : le `delete p.lanes` inconditionnel JETAIT le patch. Un document venu de
    // golem.fm (job patch-try) est en lanes_v:2 — la LISTE est le document (lot 3) — et ne porte
    // plus les royaumes guitar/voice/keys : on reconstruisait donc des lanes VIDES depuis la carte
    // du mode, en ne gardant que le nom. Vu : « Paper Kite III », 3 lanes, 0 bloc. La liste fait
    // foi quand elle existe ; le delete ne sert qu'aux documents LEGACY, qui n'ont qu'elle.
    const v2 = isV2(p) && p.lanes.length;
    p.guitar = toChain(p.guitar); p.voice = toVoice(p.voice); p.keys = toKeys(p.keys); migrateConfig(p);
    if (!v2) { delete p.lanes; delete p.lanes_v; }              // un document legacy parle encore les trois royaumes
    toLanesV2(p, laneRoleOfKey);
    if (p.__patch && !p.__patch.id) seatPatchLane(p, editPatch());   // un patch SANS NOM = neuf : sa lane, sur son entrée
    setSel(null); setDrawer(null); setP(p); setScene(0);
  };
  // « Save this lane as a patch » : le geste inverse du dépôt. Il CRÉE une entrée neuve —
  // jamais une mise à jour d'un patch existant, sinon on réintroduirait la dépendance qu'on
  // vient de supprimer (docs/patches.md §15.5).
  const laneToPatch = async () => {
    const r = await post('/api/patches', { preset: bodyOf(), lane: inTab }).catch(e => ({ error: String(e) }));
    if (r && r.patch) { reloadPatches(); flash('⛓ patch created — « ' + r.patch.name + ' »'); }
    else flash('✗ ' + ((r && r.error) || 'lane is empty'));
  };
  // LE KIT ENTIER EN UN PATCH (docs/drums-kit.md §6.7) : sept chaînes, sept jeux de scènes, un
  // fichier — le pendant de « Save this lane as patch » pour un instrument qui occupe N entrées.
  const kitToPatch = async () => {
    if (!curDs) return;
    const r = await post('/api/patches', { preset: bodyOf(), drumset: curDs,
      name: 'Drums — ' + (p.name || 'kit') }).catch(e => ({ error: String(e) }));
    if (r && r.patch) { reloadPatches(); flash('⛓ kit patch created — « ' + r.patch.name + ' » (' + (r.patch.elements || []).length + ' elements)'); }
    else flash('✗ ' + ((r && r.error) || 'the kit is empty'));
  };
  // les flèches restent DANS LE RÔLE : un guitariste qui compare ses sons ne veut pas atterrir
  // sur une ligne de voix. Même filtre que l'onglet Patches.
  const patchPeers = () => allPatches.filter(x => (x.role || 'guitar') === (patchMode ? (patchMode.role || patchMode.realm) : 'guitar'));
  const cyclePatch = d => { const l = patchPeers(); if (!l.length) return;
    const i = l.findIndex(x => x.id === (patchMode || {}).id);
    openPatchDoc(l[((i < 0 ? 0 : i) + d + l.length) % l.length]); };
  const openPatchDoc = x => { skipSave.current = true; setSel(null); setDrawer(null);
    setP(patchDraft(x)); setScene(0); setPatchBrowse(false); };
  // parcourt la liste des presets (flèches) sans ouvrir le panneau
  const cyclePreset = d => { const l = presets || []; if (!l.length) return;
    const i = l.findIndex(pr => pr.id === p.id); const j = ((i < 0 ? 0 : i) + d + l.length) % l.length; loadPreset(l[j].id); };
  // ÉDITER UNE SCÈNE, C'EST ÉDITER SON ÉTAT (docs/band-scenes.md) : une tranche de lane modifiée dans une
  // scène se recopie dans les autres scènes qui pointent le même état — « Pick » reste le même son partout
  const upd = mut => setP(prev => { const n = structuredClone(prev); mut(n); propagateLaneStates(prev, n); return n; });
  // ── LES LANES (lot 3, audit N lanes 2026-09-08) : le document est une LISTE ; l'écran montre
  // UNE lane à la fois (inTab = son id) ; les trois d'origine ont les ids guitar / voice / keys.
  const lanes = p.lanes || [];
  const laneOf = (n, id) => (n.lanes || []).find(L => L.id === id);
  // les aides de lanes vivent dans designer-lanes.js (audit 2026-09-13, M7) : ici, des enveloppes
  // qui leur passent le patch de la carte — le reste du composant ne change pas de vocabulaire
  const laneDisabled = _laneDisabled;
  const laneOffCard = L => _laneOffCard(L, patch);
  const laneWaitsCard = L => _laneWaitsCard(L, patch, modePatch);
  const sheetRowsFor = ls => _sheetRowsFor(ls, editPatch());
  const sheetRows = () => sheetRowsFor(lanes);
  const toggleRow = r => {
    const L = r.lane;
    if (L) {
      if (lanes.length === 1) return;
      const nb = laneBlocks(L).length;
      if (nb && rmLaneArm !== L.id) { setRmLaneArm(L.id); setTimeout(() => setRmLaneArm(a => a === L.id ? null : a), 4000); return; }
      removeLane(L.id); return;
    }
    if (r.none) return;
    createLane(laneSpecOf(r, lanes.map(x => x.id)));
  };
  const OUT_DEFAULT = '1-2';
  const outLabel = s => (s === 'NONE' ? '—' : s === '1-2' ? '1·2' : s);
  const setOut = (id, sel) => { upd(n => { const L = laneOf(n, id); if (L) L.out_sel = sel; }); setOutPick(null); };
  // choisir une entrée lie la lane PAR NOM quand l'entrée en a un (« Voice 1 ») : le numéro suivra le
  // patch de la carte du moment (bridge store._norm_lane) — lien fort entrée-nom, 2026-09-09
  // BASCULER L'ENTRÉE D'UNE LANE, sans perdre sa chaîne (2026-09-17). Un port USB rend la lane
  // MIDI (le rack joue ses instruments), une entrée de carte la rend AUDIO (la source sonne elle-même).
  const setIn = (id, sel) => {
    const usb = /^usb\d*$/.test(String(sel));
    const L0 = lanes.find(x => x.id === id) || {};
    const kit = laneBlocks(L0).some(b => b && b.type === 'drumkit');
    upd(n => { const L = laneOf(n, id); if (!L) return; const oldName = L.in_name; L.in_sel = sel; L.midi = usb;
      const src = usb ? (editPatch().usb || []).find(x => String(x.ch) === String(sel))
                      : (editPatch().inputs || []).find(x => String(x.ch) === String(sel));
      if (src && src.nth != null && src.role && src.role !== 'none') { L.in_role = src.role; L.in_nth = src.nth; L.in_name = src.name; }
      else { delete L.in_role; delete L.in_nth; delete L.in_name; }
      // LANE ET INSTRUMENT SE RÉSOLVENT PAR L'ENTRÉE (2026-09-09) : le rôle suit l'entrée choisie, et le titre
      // aussi s'il était celui de l'ancienne entrée — une lane guitare restait titrée « Voice 1 » après le
      // passage en IN 2, et le tiroir proposait encore les blocs de l'ancien rôle (audit 2026-10-10)
      if (!usb && src && src.role && src.role !== 'none' && !MIDI_ROLES.includes(src.role)) L.role = src.role;
      if (src && src.name && (!L.name || L.name === oldName || GENERIC_NAME.test(String(L.name).trim()))) L.name = src.name; });
    // le bloc Drum Kit ne joue qu'en MIDI : en audio le module fait le son et le bloc est retiré à la
    // compile — on le DIT au geste, au lieu de le laisser découvrir dans un journal (docs/drums-kit.md)
    if (kit && !usb) flash('⚠ audio input — the Drum Kit no longer plays here: the module makes the sound');
    setOutPick(null); };
  const chainIn = id => ((lanes.find(L => L.id === id) || {}).in_sel) || '1';
  const inOptsLive = cur => inOptsOf(editPatch(), cur);       // entrées de la carte ÉDITÉE + ports USB liés, + NONE
  // ── lane CONFIG : blocs service transversaux (docs/blocks-doctrine.md) — p.config toujours présent
  // après migrateConfig (chargement). gen = Players (générateurs+looper, IN capture + OUT façade) ;
  // rec = Recorder (le rec, IN seule = point de tap post/di/both). ──
  const cfg = p.config || { gen: { blocks: [], out: '1-2' }, rec: { blocks: [], tap: 'post' } };
  const genBlocks = (cfg.gen && cfg.gen.blocks) || [];
  const recBlocks = (cfg.rec && cfg.rec.blocks) || [];
  // lane `arr` — le chef d'orchestre (docs/arrangement.md §7). Séparée de Players (il n'est pas
  // mixé) ET de Click (lane GLOBALE, or l'arrangement est ce qu'un preset a de plus personnel).
  const arrBlocks = (cfg.arr && cfg.arr.blocks) || [];
  const cfgOutSel = (cfg.gen && cfg.gen.out) || OUT_DEFAULT;
  // sortie du CLICK : réglage GLOBAL (comme le reste du bloc, cf. config/click.json) — il est
  // stocké dans le preset comme miroir, le bridge l'extrait au save et le rend à tous les presets.
  const clickOutSel = (cfg.rec && cfg.rec.click_out) || OUT_DEFAULT;
  const setCfgOut = sel => { upd(n => { n.config = n.config || {}; n.config.gen = n.config.gen || { blocks: [] }; n.config.gen.out = sel; }); setOutPick(null); };
  const setClickOut = sel => { upd(n => { n.config = n.config || {}; n.config.rec = n.config.rec || { blocks: [] }; n.config.rec.click_out = sel; }); setOutPick(null); };
  // nom de chaque chaîne d'entrée — cascade (docs/input-map.md étape 1) :
  //   1. override PAR PRESET (p.names, édité ici) — un preset garde le droit d'appeler
  //      sa chaîne « Fuzz Wall » sans toucher au patch ;
  //   2. label du PATCH de la carte (Settings ▸ Gear ▸ Soundcard : instrument par icône) ;
  //   3. défaut générique Input 1 / Input 2 / Keys.
  const patch = (((rig && rig.state) || {}).inputmap) || {};
  // La carte que le Designer ÉDITE : celle du MODE actif quand il en préfère une autre que la carte
  // branchée (Rehearsal → XR18 déclaré, pas encore là). On prépare les lanes « Guitar 2 », « Voice 2 »
  // sur son patch ; elles se montent quand la carte arrive (bridge _norm_lane lie par rôle + numéro).
  // Sinon = le patch vivant, comme avant.
  const liveCard = String(patch.card || '').replace(/^hw:/, '');
  const modeCard = String((((rig && rig.state) || {}).mode || {}).card || '').replace(/^hw:/, '');
  const [modePatch, setModePatch] = useState(null);
  useEffect(() => {
    if (!modeCard || modeCard === liveCard) { setModePatch(null); return; }
    let alive = true;
    fetch('/api/inputmap?card=' + encodeURIComponent(modeCard)).then(r => r.json())
      // `same_as_live` : la carte du mode EST la carte branchée sous un autre nom (hw:V276 = la Volt en ASIO) —
      // on édite alors la carte branchée, celle sur laquelle le moteur résout les lanes
      .then(m => { if (alive) setModePatch(m && m.inputs && !m.same_as_live ? { ...m, card: 'hw:' + modeCard, __mode: true } : null); })
      .catch(() => { if (alive) setModePatch(null); });
    return () => { alive = false; };
  }, [modeCard, liveCard]);
  const editPatch = () => modePatch || patch;
  const editCardName = () => modePatch ? modeCard : (liveCard || 'this card');
  // une lane liée par nom montre (et enregistre) l'entrée que le moteur joue — designer-model.alignBoundInputs
  // ⚠ SANS AUDITION NI SAUVEGARDE : réaligner n'est pas éditer. Rouvrir n'est pas jouer (2026-10-07) — et un
  // brouillon venu d'une autre carte (Linux -> Windows) se réalignait au premier rendu, ce qui le RAPPELAIT sur le
  // rig et réécrivait le fichier. Le document réaligné est marqué ; l'effet d'audition le laisse passer.
  useEffect(() => {
    const pt = editPatch();
    if (!(pt.inputs || []).length || !alignBoundInputs(structuredClone({ lanes: p.lanes || [] }), pt)) return;
    setP(prev => { const n = structuredClone(prev); if (!alignBoundInputs(n, pt)) return prev; propagateLaneStates(prev, n); quiet.current = n; return n; });
  }, [p, patch, modePatch]);
  // le TITRE d'une lane suit la cascade (docs/input-map.md étape 1) : son nom s'il est le sien, sinon
  // le nom de l'ENTRÉE sur la carte (« Guitar 1 »), jamais un générique « Input 1 » / « Keys » — les
  // lanes d'un banc d'avant le 13/09 portaient ce générique, et l'onglet lisait « Input 1 · IN 1 »
  // (« il n'y a plus les titres, tu n'as mis que les entrées »).
  const GENERIC_NAME = /^(input \d+|keys|voice|guitar|bass)$/i;
  const inputNameOf = L => { const pt = editPatch(); if (!L) return null;
    if (L.midi) {
      // « usb » AUTO (par rôle) : le port qui porte le RÔLE de la lane — pas le port 1 par défaut, qui peut être un
      // module de batterie : l'onglet Keys de Chill Jazz s'appelait « Drums USB 1 » dès que la Nitro était liée, alors
      // que le moteur ne lui donne jamais un module de batterie (compile_rig midi_avoid) — bonne forme, mauvaise nature
      // (2026-10-13). Sans port de ce rôle : pas de nom d'entrée, le titre retombe sur le nom de la lane.
      const sel = String(L.in_sel || 'usb');
      const m = sel.match(/usb(\d)/);
      if (!m) {
        const roles = L.role === 'keys-pads' ? ['keys-pads', 'keys', 'pads'] : [L.role, 'keys-pads'];
        const u = (pt.usb || []).find(x => x.bound && roles.includes(x.role));
        return u ? (u.name || u.label) : null;
      }
      const u = (pt.usb || []).find(x => Number(x.port) === parseInt(m[1], 10)); return u ? (u.name || u.label) : ((pt.midi || {}).label || null); }
    const e = (pt.inputs || []).find(x => (L.in_role && x.role === L.in_role && Number(x.nth) === Number(L.in_nth))
      || String(x.ch) === String(L.in_sel) || String(x.ch).split('-').includes(String(L.in_sel).split('-')[0]));
    return e ? (e.name || e.label || null) : null; };
  const laneTitle = L => (L && L.name && !GENERIC_NAME.test(L.name.trim())) ? L.name : (inputNameOf(L) || (L && L.name) || (L && L.id) || '');
  const chainName = id => { const L = lanes.find(x => x.id === id); return L ? laneTitle(L) : id; };   // le nom de la lane (lot 3)
  const setChainName = (i, v) => upd(n => { n.names = n.names || {}; n.names[i] = v; });
  // RÔLE instrument d'une entrée (patch Soundcard) -> pilote le tiroir contextuel (guitar/bass/voice/keys/pads)
  // le rôle d'une ENTRÉE de la carte (clé legacy 1/2/k) — sert à dériver les lanes d'un preset legacy
  const laneRoleOfKey = k => {
    if (k === 'k') return (patch.midi && patch.midi.role) || 'keys';
    const e = (patch.inputs || []).find(x => String(x.ch) === String(k) || String(x.ch).split('-').includes(String(k)));
    const r = e && e.role;
    return (r && r !== 'none') ? r : (k === '2' ? 'voice' : 'guitar');   // défauts sensés si patch muet
  };
  // le rôle d'une LANE (par id) : celui qu'elle porte (lot 3), sinon celui de son entrée
  // le modèle par défaut d'un pack OUTBOARD (id du modèle, ou null si models[0] convient / pas outboard)
  const outboardDefault = (tone, role) => { if (!tone || tone.gear !== 'outboard' || (tone.models || []).length < 2) return null;
    const m = defaultModel(tone.models, role); return m && m !== tone.models[0] && m.id != null ? m.id : null; };
  const laneRole = id => { const L = (p.lanes || []).find(x => x.id === id);
    // mode patch : le rôle du PATCH fait foi pour sa lane (un brouillon d'avant le 2026-09-17 portait `guitar`)
    if (p.__patch && p.__patch.role && L && L.id === p.__patch.realm) return p.__patch.role;
    return L ? (L.role || laneRoleOfKey(L.key)) : laneRoleOfKey(id); };
  // onglet affiché = l'ID de la lane (le Designer montre UNE lane à la fois) ou 'cfg' (les services)
  // deep-link : #/designer/in2 | #/designer/keys | #/designer/config (cohérent avec #/system/<tab>)
  // ⚠ L'ONGLET N'AVAIT PAS D'ADRESSE (2026-09-16 : « le dictionnaire des scènes est difficile à
  // trouver »). Le deep-link se LISAIT au montage mais le clic n'écrivait rien, et changer de hash sans
  // recharger ne bougeait rien : ▦ Scenes était donc injoignable depuis ailleurs, et on ne pouvait pas y
  // revenir. Comme les sous-onglets de System : le clic ÉCRIT l'URL, l'URL est la source de vérité.
  const TAB_SUB = { voice: 'in2', keys: 'keys', cfg: 'config', guitar: '' };
  // `pedalboard` et `scenes` ne sont plus des onglets (2026-09-16) : on retombe sur ⚙ plutôt que sur une
  // page blanche, pour qu'un vieux lien ou un favori ne casse pas
  const tabOfSub = x => ({ in2: 'voice', keys: 'keys', config: 'cfg', pedalboard: 'cfg', scenes: 'cfg' })[x]
    || (x && x !== 'in1' ? x : 'guitar');        // une lane neuve porte son propre id : #/designer/bass-1
  const [inTab, setInTab] = useState(tabOfSub(sub));
  const pickInTab = (k, quiet) => {
    setInTab(k); setSel(null); setDrawer(null); setOutPick(null);
    if (!quiet && !p.__patch) go('designer' + ((TAB_SUB[k] !== undefined ? TAB_SUB[k] : k) ? '/' + (TAB_SUB[k] !== undefined ? TAB_SUB[k] : k) : ''));
  };
  // l'URL change (retour arrière, lien depuis une autre page) : l'onglet suit, sans réécrire l'URL
  useEffect(() => { const t = tabOfSub(sub); if (t !== inTab) pickInTab(t, true); }, [sub]);
  // ── MODE PATCH (docs/patches.md §13) : le draft ouvert depuis Songs ▸ Patches porte
  // p.__patch = {realm, id, name}. Le Designer se REPLIE : un seul onglet (la lane du patch),
  // pas de ⚙/▤/bank, sauver = ⬆ Update the patch. Tout le reste (chaîne, tiroir, feuilles,
  // scènes A-E — qui éditent les scènes DU PATCH —, audition) est l'établi normal.
  const patchMode = p.__patch || null;
  // ⚠ L'INSTRUMENT ÉTAIT ÉCRIT DEUX FOIS (retour 2026-08-02) : le nom auto d'un patch se
  // termine par « · guitar » (create_from_lane), et la ligne du dessous dit déjà « guitar patch ».
  // On retire le suffixe À L'AFFICHAGE seulement — le nom est de la donnée utilisateur, on ne le
  // réécrit pas pour un problème de mise en page.
  const pmTitle = patchMode
    ? String(patchMode.name || '').replace(/\s*·\s*(guitar|bass|voice|keys|keys-pads|pads|line)\s*$/i, '')
    : '';
  // LA LANE QUI PORTE LE PATCH : sa lane de référence (`realm`) — sauf si elle est VIDE alors qu'une lane de SON
  // rôle porte des blocs (un brouillon de batterie d'avant le 2026-10-08 : le kit MIDI était posé dans une lane
  // drums à côté, le patch restait sur `guitar`). L'effet ci-dessous rattache alors le patch à la bonne lane.
  const pmLane = (() => {
    if (!patchMode) return null;
    const r = patchMode.realm || 'guitar';
    const L = lanes.find(x => x.id === r);
    if (patchMode.drumset || (L && laneBlocks(L).length)) return r;
    const alt = lanes.find(x => x.role === patchMode.role && laneBlocks(x).length);
    return alt ? alt.id : r;
  })();
  useEffect(() => {
    if (patchMode && pmLane && pmLane !== patchMode.realm)
      setP(prev => prev && prev.__patch ? { ...prev, __patch: { ...prev.__patch, realm: pmLane } } : prev);
  }, [pmLane, patchMode && patchMode.realm]);
  const pmTab = patchMode ? pmLane : null;
  // ── LE TITRE DU SÉLECTEUR ────────────────────────────────────────────────────────────────
  // Un DRAFT porte toujours l'id 'nouveau-preset' (il n'est pas sauvé), mais il peut très bien
  // porter un NOM : un patch arrivé de golem.fm s'appelle « Paper Kite III ». Afficher
  // « Sandbox » par-dessus faisait perdre la seule indication de CE QU'ON ÉCOUTE. On ne garde
  // « Sandbox » que quand il n'y a rien à dire — le banc neuf, dont le nom générique est à nous.
  const docTitle = () => (p.name && !(isBlank() && p.name === 'New preset')) ? p.name : 'Sandbox';
  // ── L'ONGLET DOIT DÉSIGNER UNE LANE QUI EXISTE ───────────────────────────────────────────
  // Un document peut arriver avec des ids de lanes qu'on n'a pas : un patch de golem.fm ouvre
  // « guitar-try », un preset bâti sur une 8×8 atterrit sur une Volt. L'onglet restait sur
  // 'guitar', ne désignait RIEN, et l'écran s'ouvrait sur ⚙ au lieu du son qui vient d'arriver.
  // ⚠ PAS AVANT LA RESTAURATION (2026-10-21) : une page fraîche part du banc vide (une lane guitare) le temps que
  // GET /api/sandbox réponde. Corriger à ce moment-là envoyait #/designer/bass-1 (un rechargement, un lien) sur la
  // première lane, avant que le brouillon qui porte bass-1 n'arrive.
  useEffect(() => {
    if (restoring.current || patchMode || inTab === 'cfg' || !lanes.length) return;
    if (!lanes.some(L => L.id === inTab)) pickInTab(lanes[0].id);
  }, [p]);
  // la lane AFFICHÉE et sa chaîne (tout ce qui suit — split, plus, grille — travaille dessus)
  const curLane = lanes.find(L => L.id === inTab) || null;
  const g = curLane ? curLane.chain : { pre: [], split: null, post: [] };
  const split = g.split;                       // null | {mode:'fanout'|'merge', branches:[{id,blocks,out}], gain}
  const isMerge = !!(split && split.mode === 'merge');
  const gDisabled = laneDisabled(curLane);
  // ajouter / retirer une lane (lot 3) : { name, role, in_sel } -> une lane neuve, onglet dessus
  const [scnSheet, setScnSheet] = useState(false);   // le dictionnaire des scènes, en feuille
  const [ioOpen, setIoOpen] = useState(false);
  const [addRole, setAddRole] = useState(null);         // l'instrument choisi dans « Add an instrument »
  const [addArm, setAddArm] = useState(null);           // l'entrée d'un AUTRE instrument dont la reprise est armée (2 taps)
  const [laneApply, setLaneApply] = useState(null);     // id de la lane dont on ouvre la balance (écran 6)
  const [rmLaneArm, setRmLaneArm] = useState(null);      // id de la lane dont le retrait est armé (2 taps)
  const laneObj = _laneObj, laneSpecOf = _laneSpecOf;   // designer-lanes.js
  // le bloc Arrangement : un par preset (contrat), sans parties — elles sont la chanson
  const addArrangement = () => upd(n => {
    const cfg = n.config = n.config || {};
    const lane = cfg.arr = cfg.arr || {};
    const blocks = lane.blocks = lane.blocks || [];
    if (!blocks.some(b => b && b.type === 'arrangement')) blocks.push({ type: 'arrangement', id: 'arr-1', params: { advance: 'bars' } });
  });
  // Une scène neuve pour une partie, depuis le tiroir : elle COPIE la scène qui joue là et prend le nom
  // de la partie. Ici on écrit dans le brouillon (le Designer édite la sandbox) ; la ligne, elle, reçoit
  // seulement le POINTEUR vers la scène neuve.
  const newSceneForPart = (i, arr, saveArr) => {
    const secs = ((arr || {}).params || {}).sections || [];
    if (!secs[i]) return;
    let at = null; for (let k = i; k >= 0; k--) if (secs[k].scene) { at = secs[k].scene; break; }
    const id = SCENE_IDS[(p.scenes || []).length];
    if (!id) return;
    const raw = String(secs[i].name || 'part').trim();
    const name = raw.charAt(0).toUpperCase() + raw.slice(1);
    upd(n => {
      const src = (n.scenes || []).find(x => x.id === at) || (n.scenes || [])[0] || {};
      n.scenes = [...(n.scenes || []), { ...JSON.parse(JSON.stringify(src)), id, name }];
    });
    saveArr({ ...arr, params: { ...(arr.params || {}), sections: secs.map((x, j) => j === i ? { ...x, scene: id } : x) } });
  };
  // le tiroir du bloc Arrangement, créé au premier geste s'il n'existe pas encore
  const openArrangement = tab => {
    addArrangement();
    setSel({ ca: 0 }); setSelTab(tab || 'params');
  };
  const createLane = spec => {
    const L = laneObj(spec);
    upd(n => { n.lanes = n.lanes || []; n.lanes.push(L);
      n.lanes = sortLanes(n.lanes); });                    // l'ordre des onglets = le contrat, jamais l'ordre du clic
    pickInTab(L.id);
  };
  // ── AJOUTER UN INSTRUMENT (2026-09-28) : l'instrument d'abord, l'entrée ensuite ────────
  // La batterie garde SA feuille (un kit = N entrées d'un geste, docs/drums-kit.md §6.5). Pour les
  // autres, une entrée sans instrument — ou d'un autre instrument, après confirmation — est
  // baptisée dans le patch de la CARTE éditée (docs/input-map.md §3.2 : le rôle n'est jamais au
  // preset), puis la lane est créée depuis l'entrée que la carte renvoie, numéro compris.
  const openAdd = () => { setAddRole(null); setAddArm(null); setIoOpen(true); };
  const pickAddRole = r => {
    setAddArm(null);
    if (r === 'drums') { setIoOpen(false); setDsOpen(true); setDsPick(null); setDsPlan([]); return; }
    setAddRole(r);
  };
  const addOnInput = async r => {
    if (r.state === 'has') { pickInTab(r.lane.id); setIoOpen(false); return; }
    let e = r.e;
    if (r.state === 'free' || r.state === 'other') {
      if (r.state === 'other' && addArm !== r.ch) { setAddArm(r.ch); setTimeout(() => setAddArm(a => a === r.ch ? null : a), 5000); return; }
      setAddArm(null);
      let res;
      try { res = await post('/api/inputmap', { kind: 'input', ch: r.ch, role: addRole, ...(modePatch ? { card: modeCard } : {}) }); }
      catch (err) { flash('✗ input not renamed: ' + ((err.body && err.body.error) || err.message)); return; }
      const m = (res && res.inputmap) || {};
      e = (m.inputs || []).find(x => String(x.ch) === r.ch) || { ...e, role: addRole };
      // la carte du mode n'est pas poussée par le battement du rig : on garde sa réponse
      if (modePatch && m.inputs) setModePatch({ ...m, card: 'hw:' + modeCard, __mode: true });
    }
    createLane(laneSpecOf({ kind: r.kind, e, name: e.name || r.name }, lanes.map(x => x.id)));
    setIoOpen(false);
    flash('✓ ' + (e.name || r.name) + ' added');
  };
  // ── GROUPE DE BATTERIE (docs/drums-kit.md §6) ────────────────────────────────────────────
  // Le tiroir d'ajout, et le repli. `dsFold` porte les groupes DÉPLIÉS : replié est le défaut
  // (2026-09-20), donc l'ensemble vide est le bon état de départ — pas l'inverse.
  const [dsOpen, setDsOpen] = useState(false);
  const [dsPick, setDsPick] = useState(null);
  const [dsForm, setDsForm] = useState('stereo');
  const [dsPlan, setDsPlan] = useState([]);
  const [dsFold, setDsFold] = useState([]);          // ids de drumset DÉPLIÉS
  const { data: dsKits } = useAsync(() => fetch('/api/drumkits').then(r => r.json()).catch(() => null), [dsOpen]);
  // les entrées LIBRES de la carte (aucune lane dessus), dans l'ordre — une paire ⛓ compte pour ses deux canaux
  const dsFreeIn = (() => {
    // EN MODE PATCH, les entrées sont NOMINALES (2026-09-20). Un patch est un objet
    // PORTABLE : il ne connaît pas de carte, et se rebranche à la pose. Compter les entrées
    // libres de la Volt (deux) y plafonnait un kit à deux éléments, sur un banc qui n'a
    // justement aucune entrée réelle.
    if (patchMode) return Array.from({ length: 16 }, (_, i) => String(i + 1));
    const used = new Set();
    lanes.forEach(L => { if (!L.midi) String(L.in_sel || '').split('-').forEach(c => c && used.add(c)); });
    // ⚠ LA CARTE ÉDITÉE, PAS LA CARTE BRANCHÉE (2026-09-20 : « je suis en rehearsals pour
    // tester avec plein d'entrée de la XR18 », alors que la XR18 n'était pas branchée). Le
    // Designer sait déjà préparer un preset sur la carte qu'un MODE déclare (`modePatch`, la
    // feuille « Lanes & inputs » le fait depuis le 09/09) : sans ça, on ne peut monter un kit à
    // huit entrées QUE le jour où la console est là — c'est-à-dire trop tard.
    return ((editPatch() || {}).inputs || []).map(e => String(e.ch)).flatMap(ch => ch.split('-')).filter(c => !used.has(c));
  })();
  // LE MODULE CALIBRÉ (docs/calibration.md addendum 2026-09-23) : le port USB lié en drums -> son descripteur.
  // Sans port lié : un module GÉNÉRIQUE (master stéréo supposé, pas de directes), dit comme tel dans le tiroir.
  const dsModule = () => {
    const d = dsKits || {}; const port = ((d.ports || []).find(p => p.kit) || null);
    const k = port && (d.kits || []).find(x => x.id === port.kit.id);
    if (k && !port.kit.fallback) return { ...k, confidence: port.kit.confidence, usb: true };   // branché en USB : MIDI d'abord
    return { id: null, name: 'unknown module', generic: true,
             audio_outs: { master: 'stereo', direct: 0, assignable: false, declared: false, generic: true } };
  };
  useEffect(() => { if (dsOpen && dsKits) dsSetKit(dsModule()); }, [dsOpen, dsKits]);
  const dsReplan = (kit, form) => {
    const outs = (kit || {}).audio_outs || {};
    setDsPlan(drumsetPlan({ outs, form, freeIn: dsFreeIn, defaults: outs.default,
      module: (kit || {}).id || 'drums', taken: lanes.map(x => x.id) }));
  };
  const dsSetKit = k => { setDsPick(k);
    // on présélectionne la forme la PLUS RICHE que le module et la carte permettent — c'est ce
    // qu'on vient chercher quand on ouvre ce tiroir ; elle reste changeable d'un tap.
    // Un module LIÉ EN USB se joue d'abord en MIDI (2026-09-23 : la forme « Stereo pair » présélectionnée
    // ouvrait « Where each element lands » sur un kit qu'il n'avait pas câblé en audio — « c'est pas dans
    // la calibration ça ? »). Sans USB, la forme la plus riche que le module et la carte permettent.
    const f = k.usb ? null : formsFor(k.audio_outs || {}, dsFreeIn.length).filter(x => x.ok && x.id !== 'midi').pop();
    const form = (f && f.id) || 'midi'; setDsForm(form); dsReplan(k, form); };
  const dsSetForm = f => { setDsForm(f); dsReplan(dsPick, f); };
  const dsSetElement = (i, el) => setDsPlan(pl => pl.map((r, j) => j === i ? { ...r, element: el, label: elLabel(el) } : r));
  // POSE LES N LANES EN UNE FOIS — c'est la seule chose qui manquait vraiment : le modèle acceptait
  // déjà N lanes, personne n'avait de bouton. Un seul `upd`, donc un seul point d'annulation.
  const dsAdd = () => {
    const mod = (dsPick || {}).id || 'drums';           // sans module calibré, le groupe s'appelle « drums »
    if (dsForm === 'midi') {
      // une lane MIDI drums existe déjà : on s'y rend, on n'en pose pas une deuxième. Vécu le 2026-09-23 :
      // deux lanes drums sur la même Nitro, deux kits qui jouaient ensemble — « le sélecteur ne change
      // rien », parce que l'autre lane gardait Black Pearl.
      const have = lanes.find(L => L.role === 'drums' && L.midi);
      if (have) { pickInTab(have.id); setDsOpen(false); flash('this patch already has a MIDI drum lane'); return; }
      const newId = laneIdFor('drums', null, lanes.map(x => x.id));
      createLane({ id: newId, name: 'Drums', role: 'drums', in_sel: 'usb' });
      // EN MODE PATCH, le patch SE RATTACHE à cette lane — comme la branche audio ci-dessous. Oublié jusqu'au
      // 2026-10-08 : le patch restait sur sa lane `guitar`, vide, et « Save as patch » répondait « lane 'guitar'
      // has no blocks » (le kit était dans la lane drums)
      if (patchMode) setP(prev => ({ ...prev, __patch: { ...(prev.__patch || {}), role: 'drums', realm: newId } }));
      setDsOpen(false); return;
    }
    const rows = dsPlan;
    if (!rows.length) return;
    upd(n => { n.lanes = n.lanes || [];
      // EN MODE PATCH, le banc part d'UNE lane vide (le brouillon de « + New patch ») : elle n'a
      // rien à faire à côté du kit qu'on vient de poser, et la garder laisserait une lane fantôme
      // dans le patch enregistré. On la retire ici, jamais dans un preset.
      if (patchMode) n.lanes = n.lanes.filter(L => laneBlocks(L).length || L.drumset);
      rows.forEach(r => n.lanes.push(_laneObj({ id: r.id, name: elLabel(r.element), role: 'drums', in_sel: r.in_sel })));
      // les trois champs du groupe se posent APRÈS `laneObj`, qui ne connaît que les lanes ordinaires
      rows.forEach(r => { const L = n.lanes.find(x => x.id === r.id);
        if (L) { L.drumset = r.drumset; L.drumset_module = r.drumset_module; L.element = r.element; } });
      n.lanes = sortLanes(n.lanes); });
    if (patchMode) {
      // le patch DEVIENT un patch de kit : `__patch.drumset` est ce que lisent les onglets,
      // l'auto-save et `patchLaneFix`. Sans lui, le banc se replierait à une lane au prochain rendu.
      const mod2 = (dsPick || {}).id || 'drums';
      setP(prev => ({ ...prev, __patch: { ...(prev.__patch || {}), role: 'drums', realm: rows[0].id, drumset: mod2 } }));
    }
    pickInTab(rows[0].id);
    setDsOpen(false);
    flash(rows.length + ' drum lane' + (rows.length === 1 ? '' : 's') + ' added');
  };
  // le groupe de la lane ouverte, s'il y en a un — c'est lui qui coiffe la chaîne
  const curDs = (lanes.find(L => L.id === inTab) || {}).drumset || null;
  const curDsLanes = curDs ? drumsetLanes(lanes, curDs).map(L => ({ ...L, __off: !patchMode && _laneOffCard(L, patch) })) : [];

  const removeLane = id => { upd(n => { n.lanes = (n.lanes || []).filter(L => L.id !== id);
      const gone = new Set(laneBlocks(lanes.find(L => L.id === id) || {}).map(b => b.id));
      n.scenes.forEach(s => { if (s.lanes) delete s.lanes[id]; ['blocks', 'params'].forEach(k => { if (s[k]) gone.forEach(b => delete s[k][b]); }); }); });
    setRmLaneArm(null); if (inTab === id) pickInTab((lanes.find(L => L.id !== id) || { id: 'cfg' }).id); };
  useEffect(() => { if (pmTab && inTab !== pmTab) pickInTab(pmTab); }, [pmTab]);

  // accès bloc par référence (lane|post|voix|keys)
  // refs de bloc : {pre:i} (pré-chaîne partagée) | {br:bi, i} (branche bi) | {post:i} (après Σ) | {vc:i} (voix) | {kc:i} (keys).
  // LOT 3 : une ref de lane porte SON ID — {lane, z:'pre'|'post'|'br', bi, i} ; les refs config restent {cg|cr|ca}.
  const zoneArr = (n, ref) => ref.cg != null ? n.config.gen.blocks : ref.cr != null ? n.config.rec.blocks : ref.ca != null ? n.config.arr.blocks
    : (() => { const c = (laneOf(n, ref.lane) || { chain: { pre: [], post: [] } }).chain;
        return ref.z === 'post' ? c.post : ref.z === 'br' ? c.split.branches[ref.bi].blocks : c.pre; })();
  // ⚠ TOUTE nouvelle sorte de référence doit être ajoutée ICI ET dans zoneArr. Oubliée dans
  // zoneIdx, elle retombe sur `ref.i` (undefined) : la tuile se sélectionne, se surligne… et
  // la feuille ne s'ouvre jamais, SANS erreur console. Vécu avec `ca` le 2026-07-30.
  const zoneIdx = ref => ref.cg != null ? ref.cg : ref.cr != null ? ref.cr : ref.ca != null ? ref.ca : ref.i;
  const blockAt = (n, ref) => zoneArr(n, ref)[zoneIdx(ref)];
  const selBlock = sel ? blockAt(p, sel) : null;
  useEffect(() => {
    if (devSel.current === false || devSel.current === true) return;
    const dopen = (location.search.match(/[?&]dopen=([^&#]+)/) || [])[1];
    if (dopen && p.id !== decodeURIComponent(dopen)) { loadPreset(decodeURIComponent(dopen)); return; }
    const L = lanes.find(x => x.id === inTab) || lanes[0];
    if (!L || !(L.chain && L.chain.pre && L.chain.pre.length > devSel.current)) return;
    const dtab = (location.search.match(/[?&]dtab=([a-z]+)/) || [])[1];
    setSel({ lane: L.id, z: 'pre', i: devSel.current }); if (dtab) setSelTab(dtab);
    devSel.current = true;
  }, [p, lanes, inTab]);

  // instrument d'une ref de bloc (lane 1 | 2 | keys) -> clé des presets par instrument
  const instOf = ref => {
    const r = ref && ref.lane ? laneRole(ref.lane) : 'guitar';
    return r === 'keys-pads' || r === 'pads' ? 'keys' : (r || 'guitar');
  };
  // preset par défaut PAR INSTRUMENT : (type, instrument de la lane) -> repli (type, any)
  const defaultParams = (type, ref) => {
    const d = blockDefaults[type];
    return d ? (d[instOf(ref)] || d.any || null) : null;
  };

  // ref = {lane, add:'pre'|'post'|'br', bi} ; tone = sim choisi ; extra = champs fusionnés (ex. pédale nommée : {variant,label}).
  // UN SEUL chemin pour toutes les lanes (lot 3) — la voix et les claviers avaient le leur, plus pauvre.
  const addBlock = (type, ref, tone, extra) => {
    const b = { type, id: bid(type) };
    { const dp = defaultParams(type, ref); if (dp) b.params = { ...dp }; }     // défaut PAR INSTRUMENT
    if (tone) { b.ref = String(tone.id); b.label = tone.amp || tone.title;    // sim baké direct à l'ajout
      const dm = outboardDefault(tone, laneRole(ref.lane)); if (dm) b.model = dm; }
    if (extra) Object.assign(b, extra);
    const z = ref.add === 'post' ? 'post' : ref.add === 'br' ? 'br' : 'pre';
    let nsel;
    upd(n => {
      const L = laneOf(n, ref.lane); if (!L) return;
      // lane MIDI : un seul instrument par claim (Vital, piano…) — les FX s'empilent
      if (L.midi && KEYS_TYPES.includes(type) && laneBlocks(L).some(x => x && x.type === type)) return;
      const arr = zoneArr(n, { lane: ref.lane, z, bi: ref.bi });
      if (arr.length >= MAX_BLOCKS) return;
      // une WAH s'ajoute -> la pédale EXP « bloc » du FCB1010 pilote son potard Wah d'office
      // (si elle est libre) : une wah sans pédale n'a pas de sens
      if ((type === 'wah' || type === 'wah-color') && !n.exp2) n.exp2 = { block: b.id, param: 'wah', min: 0, max: 1 };
      if (type === 'whammy-dt' && z === 'pre') {
        arr.unshift(b);                                  // la Whammy est AVANT l'entrée -> ancrée en tête
        nsel = { lane: ref.lane, z, bi: ref.bi, i: 0 };
      } else {
        arr.push(b);
        nsel = { lane: ref.lane, z, bi: ref.bi, i: arr.length - 1 };
      }
    });
    setDrawer(null);
    if (nsel) setSel(nsel);   // ouvre direct les réglages du nouveau bloc
  };

  // ajout d'un ARCHÉTYPE NOMMÉ (pédale ou ampli) : bloc block(arch) + variante d'identité. tone =
  // capture choisie (installée ou fraîchement téléchargée) | null = pose vide (à remplir plus tard).
  // AMPLIS : le TYPE de bloc suit la capture — head-only (gear=amp) -> bloc Head (NAM) + un Cab (IR)
  // vide ajouté derrière (IR à choisir en tapant dessus) ; full-rig -> bloc Head+Cab (NAM), pas de cab.
  const addPedal = (archId, ref, tone) => {
    const arch = pedalArch(archId) || {};
    let type = arch.block || 'pedal-nam';
    if (type === 'amp' && tone && tone.gear === 'amp') type = 'amp-nam';
    addBlock(type, ref, tone, { variant: archId, label: arch.name || 'Pedal' });
    if (type === 'amp-nam') upd(n => {
      const arr = zoneArr(n, { lane: ref.lane, z: ref.add === 'post' ? 'post' : ref.add === 'br' ? 'br' : 'pre', bi: ref.bi });
      if (arr.length < MAX_BLOCKS && !arr.some(b => b.type === 'cab' || b.type === 'amp')) arr.push({ type: 'cab', id: bid('cab') });
    });
  };

  // macro « Ampli + 2 cabs (stéréo) » : pose la tête NAM (capture head-only) dans la pré-chaîne PUIS crée un
  // split fan-out à 2 branches (1 cab chacune) routées OUT 1 / OUT 2 = deux baffles séparés. Les cabs sont
  // vides (IR à choisir en tapant dessus). N'a de sens que sur la chaîne principale sans split existant.
  const addAmp2Cabs = tone => {
    upd(n => {
      const L = laneOf(n, inTab); if (!L) return; const c = L.chain;
      c.pre = c.pre || [];
      c.pre.push({ type: 'amp-nam', id: bid('amp-nam'), ref: String(tone.id), label: tone.amp || tone.title });
      c.split = { mode: 'fanout', gain: -3, branches: [
        { id: bid('br'), blocks: [{ type: 'cab', id: bid('cab') }], out: '1' },
        { id: bid('br'), blocks: [{ type: 'cab', id: bid('cab') }], out: '2' }] };
      c.post = c.post || [];
    });
    setDrawer(null);
  };
  const rmBlock = ref => { const bid = (blockAt(p, ref) || {}).id;
    upd(n => { zoneArr(n, ref).splice(zoneIdx(ref), 1);
      if (bid) {
        // purge TOUT ce qui pointe vers le bloc supprimé (bug 2026-07-23 : l'assignation EXP
        // survivait au bloc — « EXP1 Wah » fantôme dans le bandeau après suppression de la wah)
        n.scenes.forEach(s => { if (s.params) delete s.params[bid]; if (s.blocks) delete s.blocks[bid]; });
        if (n.exp2 && n.exp2.block === bid) n.exp2 = null;
        if (n.exp1 && n.exp1.block === bid) delete n.exp1;   // plage EXP volume -> défaut
      } });
    setSel(null); };
  // REMPLACE un bloc par une chaîne, au même endroit (2026-10-05) : un bloc VST devient sa capture NAM
  // entourée de ses sections traduites (bridge/plugin_capture.replacement). Même purge que rmBlock :
  // rien ne doit plus pointer vers l'ancien bloc (scènes, pédales EXP). Rend l'index du bloc capture.
  const spliceBlocks = (n, ref, blocks) => {
    const old = (blockAt(n, ref) || {}).id;
    const fresh = blocks.map(b => ({ ...b, id: bid(b.type) }));
    const arr = zoneArr(n, ref);
    if (arr.length - 1 + fresh.length > MAX_BLOCKS) return -1;
    arr.splice(zoneIdx(ref), 1, ...fresh);
    if (old) {
      n.scenes.forEach(s => { if (s.params) delete s.params[old]; if (s.blocks) delete s.blocks[old]; });
      if (n.exp2 && n.exp2.block === old) n.exp2 = null;
      if (n.exp1 && n.exp1.block === old) delete n.exp1;
    }
    return Math.max(0, fresh.findIndex(b => (b.origin && b.origin.kind === 'vst-capture') || b.ref));   // le bloc capture, pas le gate traduit
  };
  const selAfter = (ref, k) => (k < 0 || ref.cg != null || ref.cr != null || ref.ca != null) ? null : { ...ref, i: zoneIdx(ref) + k };
  const replaceBlock = (ref, blocks) => {
    let k = -1;
    upd(n => { k = spliceBlocks(n, ref, blocks); });
    setSel(selAfter(ref, k));
  };
  // … ou dans un NOUVEAU patch (défaut, 2026-10-05 : « un patch que j'aime, je ne vais pas avoir envie
  // de l'écraser ») : la copie est créée DÉJÀ modifiée, sous son nom, comme un objet neuf (pas de
  // patch_id/origin hérités : sinon elle se sauverait sous l'id de l'original), et le Designer bascule
  // dessus. Le document ouvert n'est jamais modifié, donc jamais ré-enregistré.
  const forkWithBlocks = async (ref, blocks, name) => {
    name = (name || '').trim() || ((p.name || 'Patch') + ' — capture');
    const n = structuredClone(p);
    const k = spliceBlocks(n, ref, blocks);
    if (k < 0) { flash('✗ too many blocks in this lane'); return; }
    propagateLaneStates(p, n);
    if (patchMode) {
      const r = await post('/api/patches', { preset: n, lane: patchMode.realm, name }).catch(() => null);
      if (!(r && r.patch)) { flash('✗ patch not created'); return; }
      skipSave.current = true;
      const pm = { ...patchMode, id: r.patch.id, name: r.patch.name };
      delete pm.source_id; delete pm.origin;
      setP({ ...r.preset, __patch: pm });
      reloadPatches();
    } else {
      const body = structuredClone(n); body.name = name; body.id = null; delete body.__patch;
      const r = await post('/api/preset', body).catch(() => null);
      if (!(r && r.id)) { flash('✗ preset not created'); return; }
      skipSave.current = true;
      setP(prev => ({ ...n, id: r.id, name }));
      reloadPresets();
      await audition({ ...body, id: r.id });
    }
    setSel(selAfter(ref, k));
    flash('✓ ' + name);
  };
  const move = (ref, d) => {
    const i = zoneIdx(ref); const j = i + d;
    if (j < 0 || j >= zoneArr(p, ref).length) return;
    upd(n => { const c = zoneArr(n, ref); [c[i], c[j]] = [c[j], c[i]]; });
    setSel(s => !s ? s : s.cg != null ? { cg: j } : s.cr != null ? { cr: j } : s.ca != null ? { ca: j } : { ...s, i: j });
  };

  // ajout d'un bloc SERVICE dans la lane config (lane = 'gen' | 'rec'). Unicité par claim
  // (looper/backing/rec sont `unique`) — le tiroir grise déjà, ici on garde-fou côté data.
  const addConfigBlock = (type, lane) => {
    let ns;
    upd(n => {
      n.config = n.config || {};
      n.config[lane] = n.config[lane] || (lane === 'gen' ? { blocks: [], out: '1-2' }
                                        : lane === 'arr' ? { blocks: [] } : { blocks: [], tap: 'post' });
      const arr = n.config[lane].blocks || (n.config[lane].blocks = []);
      if (fxDef(type).unique && arr.some(b => b && b.type === type)) return;
      // un arrangement neuf n'est pas vide : une section `intro` de 8 mesures donne quelque chose
      // à regarder et à déplacer. Un écran qui s'ouvre sur du néant n'apprend rien.
      const params = type === 'arrangement'
        ? { advance: 'bars', sig: { num: 4, den: 4 },
            sections: [{ name: 'intro', bars: 8 }] }
        : {};
      arr.push({ type, id: bid(type), params });
      ns = lane === 'gen' ? { cg: arr.length - 1 } : lane === 'arr' ? { ca: arr.length - 1 } : { cr: arr.length - 1 };
    });
    setDrawer(null);
    if (ns) setSel(ns);
  };

  // ── split : diviser la chaîne, gérer les branches, mode fan-out ⇉ / merge Σ ──
  // (sur la lane AFFICHÉE — toute lane a le split depuis le lot 3)
  const curChain = n => (laneOf(n, inTab) || { chain: { pre: [], split: null, post: [] } }).chain;
  const diviser = () => upd(n => { curChain(n).split = { mode: 'fanout', gain: -3, branches: [
      { id: bid('br'), blocks: [{ type: 'cab', id: bid('cab') }], out: '1' },
      { id: bid('br'), blocks: [{ type: 'cab', id: bid('cab') }], out: '2' }] }; });
  // retire le split -> chaîne linéaire unique : garde les blocs de la lane A ET du post (non destructif),
  // jette la lane B. Sur un split VIDE (le cas du mainteneur) = suppression propre, rien à conserver.
  const unsplit = () => { upd(n => { const c = curChain(n); const s = c.split; if (!s) return;
    c.pre = (c.pre || []).concat(s.branches[0] ? (s.branches[0].blocks || []) : [], c.post || []);
    c.split = null; c.post = []; }); setSel(null); };
  const setSplitMode = mode => upd(n => { curChain(n).split.mode = mode; });
  const setMergeGain = v => upd(n => { curChain(n).split.gain = v; });
  const addBranch = () => upd(n => { const s = curChain(n).split; if (s.branches.length < 2) s.branches.push({ id: bid('br'), blocks: [{ type: 'cab', id: bid('cab') }], out: '1-2' }); });   // 2 branches MAX (grille)
  const rmBranch = bi => { upd(n => { const c = curChain(n); const s = c.split; s.branches.splice(bi, 1);
    if (s.branches.length < 2) { c.pre = c.pre.concat(s.branches[0] ? s.branches[0].blocks : []); c.split = null; c.post = []; } }); setSel(null); };
  const setBranchOut = (bi, selv) => { upd(n => { curChain(n).split.branches[bi].out = selv; }); setOutPick(null); };


  // params SCÈNE-FIRST : un potard écrit dans la scène active (override) ; value===null retire l'override
  // (le potard revient à la base = block.params, hérité par les scènes non modifiées). Auto-commit -> sandbox.
  const setParam = (ref, pid, value) =>
    upd(n => {
      const b = blockAt(n, ref); const sc = n.scenes[scene]; if (!sc || !b.id) return;
      // bloc SCENE-INVARIANT (drums, looper… docs/blocks-doctrine.md) : ses params vivent en BASE
      // (block.params) — un override de scène n'aurait pas de sens ET le bridge (switches()) lit la
      // base : écrire l'override rendait kit/grooves/sequence invisibles au pied.
      if ((fxDef(b.type) || {}).scene_invariant) {
        b.params = b.params || {};
        if (value === null) delete b.params[pid]; else b.params[pid] = value;
        return;
      }
      const dropOvr = () => { if (sc.params && sc.params[b.id]) { delete sc.params[b.id][pid]; if (!Object.keys(sc.params[b.id]).length) delete sc.params[b.id]; } };
      if (value === null) { dropOvr(); return; }               // reset override -> base héritée
      // UN PATCH À UNE SCÈNE ÉCRIT LA BASE (2026-10-14) : sinon chaque retouche partait dans A, et une scène B
      // créée ensuite reprenait la base — sans les retouches. Avec une seule scène, « la scène » et « le bloc » sont
      // la même chose pour le musicien : on écrit là où toute scène future héritera.
      if ((n.scenes || []).length <= 1) { b.params = b.params || {}; b.params[pid] = value; dropOvr(); return; }
      sc.params = sc.params || {}; sc.params[b.id] = sc.params[b.id] || {}; sc.params[b.id][pid] = value;
    });
  const setHostParam = (ref, index, initial, value) =>
    upd(n => {
      const b = blockAt(n, ref); const sc = n.scenes[scene]; if (!b?.id || !sc) return;
      const pid = 'p' + index;
      b.params = b.params || {};
      if (!Object.hasOwn(b.params, pid)) b.params[pid] = initial;
      if (value !== null && (n.scenes || []).length <= 1) {     // une seule scène : la base (cf. setParam)
        b.params[pid] = value;
        if (sc.params?.[b.id]) { delete sc.params[b.id][pid]; if (!Object.keys(sc.params[b.id]).length) delete sc.params[b.id]; }
        return;
      }
      if (value === null) {
        if (sc.params?.[b.id]) {
          delete sc.params[b.id][pid];
          if (!Object.keys(sc.params[b.id]).length) delete sc.params[b.id];
        }
      } else {
        sc.params = sc.params || {}; sc.params[b.id] = sc.params[b.id] || {};
        sc.params[b.id][pid] = value;
      }
    });
  // « → toutes les scènes » : fige les potards EFFECTIFS du bloc comme base + purge ses overrides partout.
  const applyParamsAllScenes = ref =>
    upd(n => {
      const b = blockAt(n, ref); if (!b.id) return;
      const sc = n.scenes[scene]; const ovr = (sc && sc.params && sc.params[b.id]) || {};
      b.params = { ...(b.params || {}), ...ovr };
      n.scenes.forEach(s => { if (s.params) delete s.params[b.id]; });
    });
  const toggleBypass = ref => upd(n => { const b = blockAt(n, ref); b.bypass = !b.bypass; });
  // changer de capture (tone) : pose ref+label et REMET le modèle à zéro (les IRs/variantes changent avec le tone).
  const setRef = (ref, t) => upd(n => { const b = blockAt(n, ref); b.ref = String(t.id);
    if (!b.variant) b.label = t.amp || t.title;   // pédale nommée : garde son identité (le nom d'archétype), la capture devient le badge
    delete b.model;
    // OUTBOARD (spec capture-gain, 2026-09-14) : le modèle par défaut d'un pack est le plus PROPRE,
    // famille d'entrée selon le rôle (voix → mic, autres → di/line) — pas models[0]
    const dm = outboardDefault(t, laneRole(ref.lane)); if (dm) b.model = dm; });
  // choisir le modèle précis dans le pack (IR d'un cab, variante mic d'un ampli) ; '' -> défaut (models[0]).
  const setModel = (ref, mid) => upd(n => { const b = blockAt(n, ref); if (mid) b.model = mid; else delete b.model; });

  // on/off par scène : scene.blocks[blockId] = false => coupé dans cette scène
  const sc = p.scenes[scene] || {};
  const sceneOff = b => (sc.blocks || {})[b.id] === false;
  // ── L'ÉTAT EFFECTIF d'un bloc — MIROIR EXACT de store._block_on_in_scene ──────────────────
  // clé par id > clé par TYPE (presets legacy) > bypass de base. L'écran doit dire ce que le
  // MOTEUR joue : un bloc bypassé en base mais rallumé dans la scène sonne, et se voyait éteint.
  const blockOn = b => { const sb = sc.blocks || {};
    if (b.id != null && b.id in sb) return sb[b.id] !== false;
    if (b.type in sb) return sb[b.type] !== false;
    return !b.bypass; };
  // ── UN SEUL BOUTON ⏻ (2026-10-14) : « Active » et la case « active in A » faisaient presque la même chose.
  // Le bouton dit ce que le MOTEUR joue dans la scène affichée (blockOn). Plusieurs scènes : il allume/coupe le bloc
  // DANS CETTE SCÈNE. Une seule scène (ou un bloc qui ignore les scènes) : il écrit la base, et efface ce que la
  // scène disait d'autre — sinon le bouton changerait d'état sans changer le son.
  const multiScene = (p.scenes || []).length > 1;
  const setPower = (ref, on) => {
    const b0 = blockAt(p, ref);
    if (multiScene && !(fxDef(b0.type) || {}).scene_invariant) return setSceneBlock(ref, on);
    upd(n => { const b = blockAt(n, ref); b.bypass = !on;
      for (const s of (n.scenes || [])) {
        if (!s.blocks) continue;
        delete s.blocks[b.id];
        if (b.type in s.blocks) s.blocks[b.id] = on;            // clé legacy par TYPE : l'id la domine
      } });
  };
  // l'état d'une lane dans la scène courante, pour la vue pédalier : chaque bloc tel que le moteur le joue, chaque
  // branche coupée ou non (les mêmes lectures que les tuiles : blockOn, laneMuted)
  const pedalState = L => { const blocks = {}, branches = {}, c = (L && L.chain) || {};
    for (const b of [...(c.pre || []), ...(c.post || []), ...((c.split && c.split.branches) || []).flatMap(br => br.blocks || [])])
      if (b && b.id) blocks[b.id] = blockOn(b);
    for (const br of ((c.split && c.split.branches) || [])) if (br && br.id) branches[br.id] = { mute: laneMuted(br.id) };
    return { blocks, branches }; };
  // les valeurs EFFECTIVES (scène courante, puis base) de chaque bloc, pour que ses pédales golem-fx les montrent
  const pedalVals = L => { const out = {}, c = (L && L.chain) || {};
    for (const b of [...(c.pre || []), ...(c.post || []), ...((c.split && c.split.branches) || []).flatMap(br => br.blocks || [])])
      if (b && b.id && GOLEM_FX.has(b.type)) out[b.id] = pedalValues(fxDef(b.type), { ...(b.params || {}), ...((sc.params || {})[b.id] || {}) });
    return out; };
  const setSceneBlock = (ref, on) => { const b = blockAt(p, ref);
    upd(n => { const s = n.scenes[scene]; s.blocks = s.blocks || {};
      // Hériter quand la scène redit la base ; sinon POSER la valeur — y compris `true`, qui
      // rallume un bloc bypassé en base (le moteur lit « is not False »). Sans ce `true`, la
      // case ne pouvait pas rallumer, et le clic restait sans effet (2026-09-11).
      const base = !blockAt(n, ref).bypass, hasType = b.type in s.blocks;   // clé legacy = masque
      if (on === base && !hasType) delete s.blocks[b.id]; else s.blocks[b.id] = on; }); };
  // mute de BRANCHE par scène : scene.branches[branchId].mute (ex-`lanes`, renommé 2026-09-08 : le mot
  // « lane » est réservé aux lanes d'instrument) — le bake EXCLUT la branche du rig —
  // clean/sat = 2 lanes à sims différentes, chaque scène joue la sienne)
  const laneMuted = brId => { const b = (sc.branches || {})[brId]; if (b) return !!b.mute;
    const l = (sc.lanes || {})[brId]; return isLegacyBranchMute(l) && !!l.mute; };
  // ⚠ 2026-09-11 — `scene.lanes` a DEUX vies, et cette migration les confondait :
  //   · l'ANCIEN mute de branche, renommé `branches` le 2026-09-08 (lecture legacy conservée) ;
  //   · le NIVEAU par lane d'instrument, `lanes[<lane id>].level` — la forme NEUVE, lue EN
  //     PRIORITÉ par scene_bake, écrite par sceneLevelOf… et envoyée par golem.fm depuis le 09-09.
  // Verser tout `lanes` dans `branches` puis le supprimer EFFAÇAIT donc les niveaux de la scène
  // au premier mute de branche, en silence. On ne déplace QUE ce qui porte un `mute`.
  const setSceneLane = (brId, on) => upd(n => { const s = n.scenes[scene];
    // ⚠ 2026-09-15 : `lanes[<lane>].mute` veut aussi dire « lane coupée dans la scène » (docs/band-scenes.md) —
    // seuls les ANCIENS mutes de branche (ni state ni level) déménagent, sinon la coupure et l'état d'une lane partaient
    const old = s.lanes || {}, isMute = isLegacyBranchMute;
    const mutes = {}, keep = {};
    Object.entries(old).forEach(([k, v]) => { (isMute(v) ? mutes : keep)[k] = v; });
    s.branches = { ...mutes, ...(s.branches || {}) };
    if (Object.keys(keep).length) s.lanes = keep; else delete s.lanes;
    if (on) delete s.branches[brId]; else s.branches[brId] = { mute: true }; });   // `branches` vide reste : sans lui, `lanes` se relit comme la clé legacy

  // ── scènes : nouvelle / dupliquer / importer / renommer / niveau / supprimer ──
  const nextSceneId = n => SCENE_IDS[n.scenes.length] || 'X';
  const addScene = (sceneObj) => { const idx = p.scenes.length; upd(n => n.scenes.push({ ...sceneObj, id: nextSceneId(n) })); setScene(idx); setScenePlus(false); };
  const newScene = () => addScene({ name: 'scene', blocks: {}, levels: { guitar: -6 } });
  const dupScene = () => addScene({ ...structuredClone(sc), name: (sc.name || 'scene') + ' copy' });
  // tous nos blocs guitare (pré + branches + post), pour remapper une scène importée par TYPE
  const ourBlocks = () => lanes.flatMap(L => laneBlocks(L));   // tous les blocs de toutes les lanes (lot 3)
  // import : ajoute une scène (non destructif) en remappant ses on/off SUR NOS blocs, par TYPE
  const importScene = async (presetId, sceneId) => {
    setScenePlus(false);
    const src = await fetch('/api/preset/' + presetId).then(r => r.json()).catch(() => null);
    const ssc = src && (src.scenes || []).find(s => s.id === sceneId);
    if (!ssc) return;
    const srcType = {};
    normLanes(src).flatMap(L => laneBlocks(L)).forEach(b => { if (b.id) srcType[b.id] = b.type; });
    const offTypes = new Set(Object.entries(ssc.blocks || {}).filter(([, v]) => v === false).map(([id]) => srcType[id]).filter(Boolean));
    addScene({ name: (ssc.name || 'scene') + ' (import)', voice: ssc.voice !== false,
      levels: { guitar: (ssc.levels || {}).guitar ?? -6 },
      blocks: Object.fromEntries(ourBlocks().filter(b => offTypes.has(b.type)).map(b => [b.id, false])) });
  };
  const renameScene = v => upd(n => n.scenes[scene].name = v);
  // NIVEAU DE SCÈNE PAR LANE (lot 3) : scene.lanes[id].level — la guitare garde aussi le legacy levels.guitar
  const sceneLevelOf = (s, id) => { const v = (((s || {}).lanes || {})[id] || {}).level;
    return v != null ? v : (id === 'guitar' ? ((s || {}).levels || {}).guitar : undefined); };
  const setSceneLevel = (id, v) => upd(n => { const s = n.scenes[scene]; s.lanes = s.lanes || {}; s.lanes[id] = { ...(s.lanes[id] || {}), level: v };
    if (id === 'guitar') { s.levels = s.levels || {}; s.levels.guitar = v; } });
  const delScene = () => { if (p.scenes.length <= 1) return; upd(n => n.scenes.splice(scene, 1)); setScene(0); setSceneSheet(false); };

  // Modèle unifié + AUTO : toute édition ré-auditionne dans le sandbox ET s'enregistre EN PLACE (si le
  // preset est nommé), en débouncé. bodyOf = edit-buffer courant (guitare en forme de stockage).
  const bodyOf = () => structuredClone(p);   // guitar est déjà {pre,split,post}
  const scId = () => (p.scenes[scene] || p.scenes[0] || {}).id;
  const flash = m => { setSaved(m); setTimeout(() => setSaved(''), 2000); };

  // ── ÉTAT DES BLOCS (docs/block-status.md §4) : ce qui manque ICI se voit dès le chargement — tuile
  // barrée ⬇ (téléchargeable) ou ✕ (pas disponible sur ce rack), bandeau « N blocks missing », et la
  // tuile tapée propose Download / Replace / Keep it off. Redemandé quand un bloc, un type ou une
  // capture change (pas à chaque potard) et après un téléchargement.
  const [bstat, setBstat] = useState({});             // id de bloc -> {state, why, source, bytes…}
  const [bsSum, setBsSum] = useState(null);
  const [bsSheet, setBsSheet] = useState(null);       // {ref, st}
  const [bsFetch, setBsFetch] = useState(null);       // {done, total} pendant un téléchargement
  const [bsTick, setBsTick] = useState(0);
  const [bsHide, setBsHide] = useState(null);         // signature pour laquelle le bandeau a été fermé
  const bsig = p ? blockSig(p) : '';
  useEffect(() => {
    if (!p) return;
    let dead = false;
    const t = setTimeout(() => post('/api/blocks/status', { preset: p }).then(r => {
      if (dead) return;
      const m = {}; (r.blocks || []).forEach(x => { if (x.id) m[x.id] = x; });
      setBstat(m); setBsSum(r.summary || null);
      // un plugin VST en cours d'essai sur le banc (Linux, docs/platforms.md §6.1) : relire jusqu'au verdict
      if ((r.blocks || []).some(x => x.reason === 'trial')) setTimeout(() => !dead && setBsTick(x => x + 1), 2000);
    }).catch(() => {}), 350);
    return () => { dead = true; clearTimeout(t); };
  }, [bsig, bsTick]);
  const bsWatch = () => {                              // suit le téléchargement jusqu'au bout, puis relit l'état
    const poll = () => api('/api/blocks/fetch').then(r => {
      setBsFetch(r.running ? { done: (r.done || []).length + (r.failed || []).length, total: r.total } : null);
      if (r.running) { setTimeout(poll, 1500); return; }
      refreshCatalog(); reloadCatalog(); setBsTick(x => x + 1);
      if ((r.failed || []).length) flash('✗ ' + r.failed.map(f => f.why).join(' · ').slice(0, 90));
      else flash('✓ downloaded — the block plays');
    }).catch(() => setTimeout(poll, 3000));
    poll();
  };
  const bsDownload = async ids => {
    try {
      const r = await post('/api/blocks/fetch', { preset: p, blocks: ids || null });
      if (!(r.started || []).length) { flash('nothing to download'); return; }
      setBsFetch({ done: 0, total: r.started.length }); setBsSheet(null); bsWatch();
    } catch (e) { flash('✗ ' + ((e.body && e.body.error) || e.message)); }
  };
  const bsReplaceType = (ref, type) => { upd(n => { const b = blockAt(n, ref); if (!b) return;
    b.type = type; delete b.params; delete b.variant; delete b.ref; delete b.model; delete b.label;
    const dp = defaultParams(type, ref); if (dp) b.params = { ...dp }; }); setBsSheet(null); };
  // capture A2 sur un poste : sa jumelle classique depuis TONE3000 — le document ne change pas
  const [bsPlayBusy, setBsPlayBusy] = useState(false);
  const bsPlayable = async blk => {
    setBsPlayBusy(true);
    try {
      const r = await post('/api/blocks/playable', { block: blk, preset: p });
      refreshCatalog(); reloadCatalog(); setBsTick(x => x + 1);
      if (r.status && r.status.state === 'ready') { setBsSheet(null); flash('✓ playable version installed — the block plays'); }
      else flash('✗ ' + ((r.status && r.status.why) || 'still not playable'));
    } catch (e) { flash('✗ ' + ((e.body && e.body.error) || e.message)); }
    setBsPlayBusy(false);
  };
  const bsUseSuggestion = (ref, sg) => { upd(n => { const b = blockAt(n, ref); if (!b) return;
    b.ref = String(sg.ref); delete b.model; if (sg.retyped) b.type = sg.retyped; }); setBsSheet(null); };
  // ── UN PATCH EST ARRIVÉ DE GOLEM.FM (job patch-try, patches.md §17) : le rack a remplacé l'edit-buffer
  // et prévient par state.sandbox_rev. Ouvert = on le charge ; le brouillon d'avant reste à un tap. ──
  // ⚠ PAS de « || 0 » : useRigState démarre sur un état SANS cette clé, et un 0 inventé servait
  // de référence — le premier /api/state le faisait « changer », donc bannière à chaque F5.
  const sbRev = ((rig && rig.state) || {}).sandbox_rev;
  const sbSeen = useRef(null);
  const [arrived, setArrived] = useState(false);
  // ⚠ 2026-09-11 — la bannière revenait À CHAQUE CHARGEMENT DE PAGE, même après avoir sauvé le
  // patch. Deux causes : (1) au premier rendu l'état du rig n'est pas encore là, `sbRev` valait
  // donc 0 et servait de référence — le premier /api/state le faisait « changer » ; (2) rien ne
  // survivait au rechargement, donc une arrivée déjà traitée se re-signalait indéfiniment.
  // La révision déjà VUE est maintenant gardée PAR ÉCRAN (localStorage : chaque écran voit
  // l'arrivée une fois), et elle n'est marquée que lorsqu'on a AGI — ouvrir, restaurer, ou
  // enregistrer. Un rechargement sans geste re-signale : le patch joue toujours, ça reste vrai.
  const SEEN_KEY = 'golem.sandboxRevSeen';
  const readSeen = () => { try { return Number(localStorage.getItem(SEEN_KEY)) || 0; } catch (e) { return 0; } };
  const markSeen = r => { try { localStorage.setItem(SEEN_KEY, String(r)); } catch (e) { /* mode privé */ } };
  useEffect(() => {
    if (sbRev == null) return;                            // le rig n'a pas encore parlé : on ne conclut rien
    if (sbSeen.current === null) sbSeen.current = readSeen();
    if (sbRev !== sbSeen.current) { sbSeen.current = sbRev; setArrived(sbRev > 0); }
  }, [sbRev]);
  // l'affaire est CLOSE : on ne reverra plus cette arrivée, même après un rechargement.
  const closeArrived = () => { const r = sbRev || 0; sbSeen.current = r; markSeen(r); setArrived(false); };
  const openArrived = async prev => { const d = await fetch('/api/sandbox' + (prev ? '?prev=1' : '')).then(r => r.json()).catch(() => null);
    if (d && d.preset) loadDraft(d.preset); closeArrived(); flash(prev ? 'previous draft restored' : '✨ patch from golem.fm opened — 💾 Save keeps it'); };
  const isBlank = () => !p.id || p.id === 'nouveau-preset' || p.id === 'sandbox-try';   // l'essai n'est pas un preset (docs/patches.md §19) : jamais sauvé en place
  // audition : si la COMPILE échoue (ids dupliqués, routage invalide…), le rig n'est PAS mis à jour —
  // on l'AFFICHE (l'échec silencieux a déjà fait croire à des « effets non chargés », 2026-07-10).
  // LOT D : l'audition porte l'éditeur et la révision de base ; un 409 = un autre écran a écrit depuis.
  // Rend true si le brouillon est passé (la sauvegarde du preset attend ce oui).
  const audOk = useRef(true);                      // la DERNIÈRE audition est-elle passée ? (« ▶ Play on /live » le lit)
  const audition = body => post('/api/sandbox_apply', { preset: body, scene: scId(), editor: EDITOR,
      base: baseRev.current, ...(takeover.current ? { force: true } : {}) })
    .then(r => {
      if (r && r.rev != null) { baseRev.current = _dstate.rev = r.rev; takeover.current = _dstate.takeover = false; }
      // ⚠ UN REFUS RESTE AFFICHÉ tant qu'il dure (2026-10-07) : un flash de 2 s ne suffisait pas — le rig
      // gardait le document d'AVANT, l'écran montrait le nouveau, et rien ne le disait plus ensuite.
      audOk.current = !(r && r.ok === false);
      if (r && r.ok === false) setAudErr(r.error || 'compile failed');
      else if (r && !r.conflict) setAudErr(null);
      return true; })
    .catch(e => { if (e && e.status === 409 && e.body && e.body.conflict) { setConflict(e.body); return false; } return true; });

  const [audErr, setAudErr] = useState(null);
  // « ▶ Play on /live » (2026-10-17), dans les DEUX menus ⋯ (preset et patch) : un bouton posé dans un seul menu
  // est invisible dans l'autre (déjà payé le 2026-09-20)
  // OÙ LE JOUER (2026-10-17 : « ça me charge une setlist, alors que c'est un patch ») : un PATCH rangé dans une
  // bank de sons y est joué À SA PLACE — cette bank passe sur le pédalier (la chip de /live la change de nouveau), la
  // barre dit « BANK #01 » et ◀ ▶ parcourent ses voisins ; un PRESET de la setlist du pédalier y est joué à sa place.
  // Sinon il joue seul, et /live le dit (« PATCH · nom ») sans flèches qui mèneraient ailleurs.
  const playOnLive = async () => {
    setSaveMenu(false);
    if (!(await audition(bodyOf()))) return;           // conflit : un autre écran a écrit (sa feuille s'ouvre)
    if (!audOk.current) { flash('✗ the rig refused this — it is not playing'); return; }
    const want = patchMode ? (patchMode.id ? { patch: patchMode.id } : null) : (!isBlank() && p.id ? { preset: p.id } : null);
    if (want) {
      const d = await fetch('/api/setlists').then(r => r.json()).catch(() => null);
      const at = sl => (sl.lines || []).findIndex(l => want.patch ? l.patch === want.patch : l.preset === want.preset);
      const pool = ((d && d.setlists) || []).filter(sl => (sl.kind || 'songs') === (want.patch ? 'sounds' : 'songs') && at(sl) >= 0);
      const sl = pool.find(x => x.id === d.active) || (want.patch ? pool[0] : null);   // un preset : la setlist du pied seulement
      if (sl) {
        if (sl.id !== d.active) await post('/api/setlists/' + encodeURIComponent(sl.id) + '/activate', {}).catch(() => null);
        await post('/api/recall', { slot: at(sl) }).catch(() => null);
      }
    }
    go('live');
  };
  const PlayOnLiveBtn = () => html`<button class="row-btn sm" title="play what is open here, then go to /live"
    onClick=${playOnLive}>▶ Play on /live<small>with what is open here</small></button>`;
  // ── OUVRIR UN VST, C'EST L'ENTENDRE (2026-10-10 : « je ne peux plus ouvrir l'UX VST depuis le tiroir ») ──
  // Le Designer peut montrer un brouillon qui NE JOUE PAS : rouvrir n'est pas jouer (2026-10-07), et au démarrage le
  // pied rappelle la bank 0. Le bouton cherchait alors une instance absente de REAPER et échouait en silence (404).
  // Demander la fenêtre d'un plugin est un geste d'édition : le brouillon est joué, puis la fenêtre est cherchée
  // pendant que REAPER charge (une suite d'ampli commerciale prend plusieurs secondes).
  const openVst = async id => {
    // Linux (2026-11-09, docs/platforms.md §6.1) : la fenêtre du plugin vit sur l'écran virtuel de REAPER — elle est
    // filmée et montrée ici, comme celle de Vital ; à sa fermeture l'état natif est capturé dans le patch.
    if (winAvail && winAvail.mode === 'view') return openPluginWindow(id, '', 'vst');
    const tryOpen = () => post('/api/vst-host/open', { block: id }).then(() => true, () => false);
    if (await tryOpen()) return;
    flash('▶ playing this draft — loading the plugin…');
    if (!(await audition(bodyOf()))) return;
    for (let i = 0; i < 12; i++) {
      await new Promise(r => setTimeout(r, 1500));
      if (await tryOpen()) return;
    }
    flash('✗ plugin window not found in REAPER');
  };         // le rig a REFUSÉ ce brouillon : il ne joue pas
  // ── LA FENÊTRE DE VITAL (2026-10-14 : « ouvrir la fenêtre, avec sauvegarde quand on la ferme ») ──
  // golem_rig guette la fermeture (TrackFX_GetOpen) et compare l'état à celui de l'ouverture ; le bridge range le son
  // retouché en preset Vital (pack « edited ») et on le pose sur le bloc à la place de l'ancien. La surveillance vit
  // ICI, pas dans le tiroir : fermer le tiroir avant la fenêtre ne doit pas perdre la retouche.
  // Ni sur une tablette (la fenêtre s'ouvrirait sur l'écran de la machine), ni sous Linux : le bridge le dit.
  const [winAvail, setWinAvail] = useState(false);
  useEffect(() => { fetch('/api/plugin-window').then(r => r.json()).then(d => setWinAvail(d || false)).catch(() => {}); }, []);
  // LE MAGNÉTOPHONE est global (config/recorder.json) : la feuille du bloc Rec lit et écrit CETTE config, comme
  // Settings ▸ Mode. Elle lisait block.params, vide sur un patch d'usine : toutes les cases s'affichaient allumées
  // (USB compris) alors que l'enregistreur ne prenait pas USB, et le tap les éteignait — un Riff clavier refusé.
  const { data: recCfg, reload: reloadRecCfg } = useAsync(() => fetch('/api/recorder').then(r => r.json()).catch(() => null), []);
  const setRecCfg = async (k, v) => { await post('/api/recorder', { [k === 'rec_mode' ? 'mode' : k]: v }).catch(() => null); reloadRecCfg(); };
  const [winWatch, setWinWatch] = useState(null);     // { blockId, seq, from, kind: 'vital' | 'vst', title, sceneId }
  // kind 'vst' : le bloc VST Host sous Linux — même fenêtre filmée, mais à la fermeture c'est l'état natif du plugin
  // qui est capturé dans le patch (applyHostState), pas un preset Vital
  const openPluginWindow = async (blockId, from, kind = 'vital') => {
    const vst = kind === 'vst';
    const blk = vst ? allBlocksOf(p).find(b => b.id === blockId) : null;
    const title = vst ? String((blk && (blk.label || blk.plugin)) || 'Plugin').replace(/^(VST3?i?|CLAPi?):\s*/, '') : 'Vital';
    const tryOpen = () => post('/api/plugin-window/open', { block: blockId }).then(r => r, () => null);
    let r = await tryOpen();
    if (!r) {                                          // le brouillon ne joue pas encore : le jouer d'abord (comme openVst)
      // un plugin jamais essayé passe d'abord le banc (Linux, docs/platforms.md §6.1) : le dire, et attendre le verdict
      const testing = vst && bstat && bstat[blockId] && bstat[blockId].reason === 'trial';
      flash(testing ? '⏳ golem is testing this plugin before it plays — a few seconds…'
                    : `▶ playing this draft — loading ${vst ? 'the plugin' : 'Vital'}…`);
      if (!(await audition(bodyOf()))) return;
      for (let i = 0; i < (testing ? 30 : vst ? 12 : 10) && !r; i++) { await new Promise(res => setTimeout(res, 1500)); r = await tryOpen(); }
    }
    if (!r) { flash(vst ? '✗ plugin window not found in REAPER' : '✗ Vital window not found'); return; }
    if (!r.readable) flash(`⚠ ${title} opened, but its changes cannot be kept here${r.error ? ' — ' + r.error : ''}`);
    // Linux : la fenêtre est filmée et montrée ici (PluginView) ; « Done » la ferme, la surveillance ci-dessous range
    setWinWatch({ blockId, seq: r.seq, from: from || '', mode: r.mode || 'native', w: r.w, h: r.h, closing: false,
                  kind, title, sceneId: sc && sc.id });
  };
  const closeVitalView = () => {
    if (!winWatch) return;
    setWinWatch(w => w && { ...w, closing: true });
    post('/api/plugin-window/' + encodeURIComponent(winWatch.blockId) + '/close', {}).catch(() => {});
  };
  useEffect(() => {
    if (!winWatch) return;
    let alive = true;
    const t = setInterval(async () => {
      const st = await fetch('/api/plugin-window/' + encodeURIComponent(winWatch.blockId)).then(r => r.json()).catch(() => null);
      if (!alive || !st || String(st.seq) !== String(winWatch.seq) || st.state === 'open') return;
      clearInterval(t); setWinWatch(null);
      if (st.state === 'lost') { flash(`✗ ${winWatch.title || 'Vital'} was reloaded while its window was open — changes not kept`); return; }
      if (st.state !== 'closed' || !st.changed) return;          // fermée sans retouche : rien à dire
      if (winWatch.kind === 'vst') {                              // le bloc VST Host : l'état natif va dans le patch
        const r = await fetch('/api/vst-host/state/' + encodeURIComponent(winWatch.blockId)).catch(() => null);
        const state = r && await r.json().catch(() => null);
        if (!r || !r.ok || !state) { flash('✗ plugin settings not captured' + (state && state.error ? ' — ' + state.error : '')); return; }
        applyHostState(winWatch.blockId, winWatch.sceneId, state);
        window.dispatchEvent(new CustomEvent('golem:vst-captured', { detail: { blockId: winWatch.blockId } }));
        flash('✓ plugin settings captured into the patch');
        return;
      }
      const r = await post('/api/plugin-window/' + encodeURIComponent(winWatch.blockId) + '/save-vital',
        { seq: winWatch.seq, from: winWatch.from }).catch(() => null);
      if (!r || !r.id) { flash('✗ could not keep the Vital changes'); return; }
      window.dispatchEvent(new Event('golem:vital-presets'));    // la liste du tiroir relit la bibliothèque
      upd(n => { swapVitalPreset(n, winWatch.blockId, winWatch.from, r.id); });
      flash('✓ Vital sound kept');
    }, 800);
    return () => { alive = false; clearInterval(t); };
  }, [winWatch && winWatch.seq]);
  const lastSaved = useRef('');                       // sérialisation du dernier POST /api/preset
  // ── LOT D : le conflit d'édition ── {rev, by} quand un autre écran a écrit le brouillon ; tant qu'il
  // est là, cet écran n'auditionne ni ne sauve. « Load the newer draft » reprend le sien ; « Keep mine » force.
  const [conflict, setConflict0] = useState(null);
  const conflictRef = useRef(null);
  const setConflict = c => { conflictRef.current = c; setConflict0(c); };
  const loadNewer = async () => {
    const d = await fetch('/api/sandbox').then(r => r.json()).catch(() => null);
    setConflict(null);
    if (d && d.preset) { loadDraftKeepId(d); }
  };
  const keepMine = () => { setConflict(null); takeover.current = true; commit(true); };
  const commit = async saveToo => {
    const body = bodyOf();
    if (conflictRef.current) { setSaving(false); return; }   // un autre écran a écrit : on n'écrase rien tant qu'on n'a pas choisi
    if (!(await audition(body))) { setSaving(false); return; }
    const js = JSON.stringify(body);                  // changement de scène seul = corps identique -> pas de save
    if (!saveToo || js === lastSaved.current) { setSaving(false); return; }
    // ── UN PATCH S'ENREGISTRE COMME UN PRESET (docs/patches.md §15) ─────────────────────────
    // C'est la conséquence directe du modèle COPIE : le patch est autonome, l'enregistrer
    // n'affecte AUCUN morceau. L'argument qui interdisait l'auto-save (« Update propage dans N
    // chansons ») est mort avec la propagation.
    if (patchMode && patchMode.id) {
      lastSaved.current = js;
      post('/api/patches/' + encodeURIComponent(patchMode.id),
           // un patch de KIT s'enregistre par son GROUPE : `lane` ne désignerait qu'un élément,
           // et les six autres seraient perdus à la première sauvegarde automatique (§6.7)
           patchMode.drumset ? { preset: body, drumset: patchMode.drumset }
                             : { preset: body, lane: patchMode.realm })
        // ⚠ un refus DOIT se voir : pendant des jours l'auto-save d'un patch venu de golem.fm
        // rendait 400 (lane `guitar-try` refusée par la route) et l'écran disait « saved » —
        // la scène supprimée n'atteignait jamais le fichier (1983, 2026-09-14)
        .then(r => { if (r && r.error) { flash('✗ patch not saved: ' + r.error); lastSaved.current = null; } else { closeArrived(); reloadPatches(); } setSaving(false); })
        .catch(e => { flash('✗ patch not saved: ' + e); lastSaved.current = null; setSaving(false); });
      return;
    }
    if (!isBlank()) {
      lastSaved.current = js;
      post('/api/preset', body).then(r => { if (r && r.error) flash('✗ not saved: ' + r.error); else closeArrived();
        reloadPresets(); setSaving(false); }).catch(() => setSaving(false));   // sauvé = l'arrivée est traitée
    } else { setSaving(false); }
  };
  // auto-commit débouncé : l'effet voit toujours le p le plus frais (pas de closure obsolète).
  useEffect(() => {
    if (restoring.current) return;                   // restauration en cours : ne rien auditionner/écraser
    _dstate.p = p; _dstate.scene = scene;            // persiste le buffer d'édition (retour Designer = travail intact)
    if (noAudition.current) { noAudition.current = false; skipSave.current = false; return; }
    // RÉALIGNÉ, PAS ÉDITÉ — mais une audition DÉJÀ DEMANDÉE n'est pas annulée pour autant (2026-10-13 : « quand
    // je change de patch par le sélecteur, le son ne se met pas à jour, je dois cliquer sur la scène B »). Choisir un
    // patch programme son audition ; le réalignement de son entrée arrive au rendu suivant, et sa marque « silencieux »
    // tuait ce minuteur en vol. Elle ne vaut que pour un brouillon ROUVERT, où rien n'attendait.
    if (quiet.current && quiet.current === p) {
      quiet.current = null; skipSave.current = false;
      if (pendingSave.current === null) return;
      const again = pendingSave.current;
      clearTimeout(commitTimer.current);
      commitTimer.current = setTimeout(() => { pendingSave.current = null; commit(again); }, 450);
      return () => clearTimeout(commitTimer.current);
    }
    clearTimeout(commitTimer.current);
    const saveToo = !skipSave.current; skipSave.current = false;
    if (saveToo && (!isBlank() || (patchMode && patchMode.id))) setSaving(true);   // preset OU patch nommé
    pendingSave.current = saveToo;
    commitTimer.current = setTimeout(() => { pendingSave.current = null; commit(saveToo); }, 450);
    return () => clearTimeout(commitTimer.current);
  }, [p, scene]);

  // Enregistrer = surtout pour NOMMER un preset neuf (ensuite l'auto-save prend le relais). Sur un preset
  // déjà nommé : sauvegarde immédiate (l'auto-save le ferait de toute façon).
  const store = async () => {
    if (isBlank()) { setNaming({ dup: false }); return; }
    const body = bodyOf(); lastSaved.current = JSON.stringify(body); const r = await post('/api/preset', body);
    if (!(r && r.error)) closeArrived();          // le patch arrivé est devenu un preset : plus rien à signaler
    reloadPresets(); flash(r && r.error ? '✗ not saved: ' + r.error : '✓ saved');
  };

  // Dupliquer = sauver sous un NOUVEAU nom (le designer bascule sur la copie).
  const duplicate = () => setNaming({ dup: true, name: (p.name || 'Preset') + ' copy' });
  // ⬆ le geste de sauvegarde du mode patch : la lane du draft DEVIENT le patch (rev++),
  // les morceaux en rev:null suivront. Le doc muté revient avec le lien snap à jour.
  const [pmNaming, setPmNaming] = useState(false);   // NameSheet du banc NEUF (id:null)
  const doCreatePatch = async name => {
    setPmNaming(false); name = (name || '').trim(); if (!name) return;
    const r = await post('/api/patches',
      { preset: bodyOf(), lane: patchMode.realm, name,
        // l'IDENTITÉ suit : un patch essayé depuis golem.fm est sauvé sous SON id, pas sous un id
        // dérivé du nom — sinon chaque reprise fabrique un objet de plus (paper-kite-ii, -iii…)
        patch_id: patchMode.source_id || undefined, origin: patchMode.origin || undefined }).catch(() => null);
    if (r && r.patch) { skipSave.current = true;
      setP({ ...r.preset, __patch: { ...patchMode, id: r.patch.id, name: r.patch.name } });
      reloadPatches(); flash('✓ patch created'); }
    else flash('✗ create failed');
  };
  const updatePatch = async () => {
    if (!patchMode) return;
    if (!patchMode.id) { setPmNaming(true); return; }   // banc neuf : nommer d'abord
    const r = await post('/api/patches/' + encodeURIComponent(patchMode.id) + '/pull',
      { preset: bodyOf(), lane: patchMode.realm }).catch(() => null);
    if (r && r.preset) { skipSave.current = true; setP({ ...r.preset, __patch: patchMode });
      reloadPatches(); flash('✓ patch updated — rev ' + ((r.patch || {}).rev != null ? r.patch.rev : '?')); }
    else flash('✗ update failed');
  };
  // ➕ promouvoir le banc en MORCEAU : le marqueur tombe, le flux « nommer & sauver » normal
  // prend la main — la lane reste LIÉE au patch (c'est le début de l'assemblage).
  // ASSIGNER LE BANC À UN MORCEAU (2026-09-08) : « Assign in a preset » ne savait que CRÉER
  // un morceau. La feuille propose aussi les presets existants : le patch (sauvé d'abord) se DÉPOSE
  // dans la lane de son rôle — même geste que ⚙ ▸ Deposit de la page Patches, en copie.
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignDone, setAssignDone] = useState(null);   // {pid, name, lane} après un dépôt
  const depositInto = async pr => {
    if (!patchMode) return;
    if (!patchMode.id) { setAssignOpen(false); setPmNaming(true); flash('name the patch first — then assign it'); return; }
    const realm = patchMode.realm || 'guitar';
    await post('/api/patches/' + encodeURIComponent(patchMode.id), { preset: bodyOf(), lane: realm }).catch(() => null);   // le banc tel qu'il est
    const r = await post('/api/patches/' + encodeURIComponent(patchMode.id) + '/deposit', { presets: [pr.id] }).catch(e => ({ error: String(e) }));
    const row = r && r.presets && r.presets[0];
    if (!row || row.error) { flash('✗ ' + ((row && row.error) || (r && r.error) || 'deposit failed')); return; }
    reloadPresets();
    setAssignDone({ pid: pr.id, name: pr.name, lane: r.lane, lost: row.lost_scenes || [], added: row.added_scenes || [] });
  };
  // « ▤ Make a song » (patch-as-preset.md §4 bis) : le morceau né du banc s'ouvre sur son ⚙ — là où se posent
  // la backing et l'arrangement. Une ref, pas un état : le nommage passe par une feuille entre les deux.
  const toSongCfg = useRef(false);
  const createFromPatch = () => {
    // ⚠ ne PAS jeter le marqueur ici : annuler la feuille laissait échoué sur un draft anonyme
    // (« hop, la sandbox d'un preset ! » — 2026-07-31). Le marqueur tombe à la CONFIRMATION.
    setNaming({ dup: false, name: patchMode ? patchMode.name : '' });
  };

  const saveAs = async name => {
    setNaming(null); name = (name || '').trim(); if (!name) return;
    setSaved('… saving');
    const body = bodyOf(); body.name = name; body.id = null;      // le bridge dérive un id du nom
    delete body.__patch;                                          // un patch promu devient un PRESET — le marqueur ne se sauve jamais
    const r = await post('/api/preset', body); reloadPresets();
    skipSave.current = true;                                      // le setP qui suit ne doit pas re-sauver aussitôt
    setP(prev => { const n = { ...prev, id: r.id, name }; delete n.__patch; return n; });   // le designer pointe le preset sauvé, sorti du mode patch
    await audition({ ...body, id: r.id }); flash('✓ ' + name);
    if (toSongCfg.current) { toSongCfg.current = false; setInTab('cfg'); }
  };

  // ⚠ JAMAIS un JSON.stringify nu sur une ref de bloc : le tiroir recevait `ref=${sel}` et Preact, qui
  // traite `ref` comme une référence, écrivait l'instance du composant dans sel.current — la première
  // comparaison après un réglage (preset de bloc, potard) levait « Converting circular structure to
  // JSON », le rendu s'arrêtait et le tiroir restait figé jusqu'au rechargement (le mainteneur, « noté
  // plusieurs fois », reproduit le 2026-09-09 sur Spring Reverb ▸ Kicked spring). Clé = les champs
  // de la ref seulement.
  const refKey = r => JSON.stringify(r, (k, v) => (k === 'current' ? undefined : v));
  const refEq = (a, b) => !!a && !!b && refKey(a) === refKey(b);

  // verrou live : gèle la page ET la topbar (un tap de scène/preset ré-auditionnerait le brouillon)
  const locked = !!(rig && rig.state && rig.state.live_lock);

  // publie les contrôles du Designer (preset + scènes + actions) dans la TOPBAR (slot contextuel)
  useEffect(() => {
    if (locked) {
      setTopSlot(html`<span class="muted">🔒 ${esc(docTitle())} — live lock</span>`);
      return () => setTopSlot(null);
    }
    setTopSlot(html`
      ${patchMode ? html`<div class="preset-nav">
        <button class="preset-btn" onClick=${() => { setPatchRole(null); setPatchQ(''); setPatchBrowse(true); }} title=${(pmTitle || 'New patch') + ' — browse patches'}>
          <b>${esc(pmTitle || 'New patch')}</b>${patchMode.id ? '' : html`<small class="muted pm-draft" title="playing from the sandbox — not in your library until you save it"> · not saved</small>`}<span class="picker-caret">▾</span></button>
        <button class="pnav" onClick=${() => cyclePatch(-1)} title="previous patch (same instrument)">◀</button>
        <button class="pnav" onClick=${() => cyclePatch(1)} title="next patch (same instrument)">▶</button>
      </div>` : html`<div class="preset-nav" data-doc="designer.preset">
        <button class="preset-btn" onClick=${() => setBrowse(true)} title=${docTitle() + ' — browse presets'}>
          <b>${esc(docTitle())}</b><span class="picker-caret">▾</span></button>
        <button class="pnav" onClick=${() => cyclePreset(-1)} title="previous preset">◀</button>
        <button class="pnav" onClick=${() => cyclePreset(1)} title="next preset">▶</button>
      </div>`}
      <div class="scene-tabs2" data-doc="designer.scenes">
        ${Array.from({ length: Math.max(5, p.scenes.length) }, (_, i) => {
          // slot revendiqué par un bloc spécial (foot_scene_claim) : le switch i+1 n'est plus
          // une scène au pied -> onglet NON cliquable, logo du bloc à la place de la lettre
          // RETIRÉ de la barre (2026-10-08 : « les icônes qui désignent des blocs spéciaux ne sont pas utiles ») —
          // un slot de scène pris par un bloc spécial n'a simplement pas d'onglet ; /live et le tiroir MIDI assign le disent
          const claim = i < 5 ? footBlocks().map(([b]) => b).find(b => b.foot === i + 1) : null;
          if (claim) return null;
          const s = p.scenes[i];
          if (s) return html`<button class=${'sc-tab' + (i === scene ? ' on' : '')} data-doc=${'designer.scene.' + s.id}
            title=${i === scene ? 'tap again to edit the scene' : (s.name || ('scene ' + s.id))}
            onClick=${() => i === scene ? setSceneSheet(true) : setScene(i)}>${s.id}</button>`;
          const isNext = i === p.scenes.length && p.scenes.length < 8;   // 1er slot vide = « ajouter »
          return html`<button class=${cls('sc-tab empty', isNext && 'add')} disabled=${!isNext}
            title=${isNext ? 'add scene ' + SCENE_IDS[i] : 'empty slot'}
            onClick=${() => isNext && setScenePlus(true)}>${SCENE_IDS[i]}</button>`;
        })}
        ${/* LE DICTIONNAIRE N'EST PLUS UN ONGLET (2026-09-16) : il s'ouvre ICI, au bout des puces,
              là où on pense déjà « scènes ». Même composant que l'onglet Sound de l'écran du morceau. */''}
        ${/* ▦ (le dictionnaire des scènes) a quitté la barre : c'est une entrée du menu « ⋯ » (2026-10-08) */''}
        ${/* LA FICHE ⓘ (proposition 1) — après ▦ : ◀ ▶ restent collés au sélecteur de presets (2026-10-08) */''}
        ${patchMode ? '' : html`<button class=${cls('pg-info', glance && glance.kind === 'info' && 'on')} data-doc="designer.info" title="this preset at a glance — song, bank, scenes, instruments, special switches"
          onClick=${e => openGlance('info', e)}>ⓘ</button>`}
      </div>

      ${/* MÊME GRAMMAIRE QUE LES PRESETS (retour 2026-08-02) : un « ⋯ » discret plutôt que
            deux gros boutons. La topbar est un endroit de NAVIGATION ; les actions destructrices
            ou structurantes vivent derrière un tap, pas sous le pouce. */''}
      ${patchMode ? html`<div class="dsn-actions">
        ${saved ? html`<span class="autosave">${saved}</span>` : ''}
        ${/* MÊME TÉMOIN QU'UN PRESET (§15) : le patch est autonome, il s'enregistre tout seul.
              Le bouton « Update » a disparu avec la propagation qu'il servait à déclencher. */''}
        ${/* ② PAS DE DOUBLON : sur un banc neuf on affichait « ● not saved » ET « 💾 Save »,
              qui disent la même chose — 85 px pris à des boutons qui, eux, sortaient de
              l'écran. Le témoin ne parle que lorsqu'il est SEUL à pouvoir le dire. */''}
        ${patchMode.id ? html`<span class="autosave"
          title="changes save automatically — no song is affected">
          ${saving ? '…saving' : '✓ saved'}</span>`
        : html`<button class="save-btn primary txt" onClick=${updatePatch}
            title="name this bench and keep it in your catalogue">💾 Save</button>`}
        <div class="save-wrap">
          <button class=${cls('save-btn', saveMenu && 'sel')}
            onClick=${() => setSaveMenu(!saveMenu)} title="actions">⋯</button>
          ${saveMenu ? html`
            <div class="picker-scrim" onClick=${() => setSaveMenu(false)}></div>
            <div class="save-pop" onClick=${e => e.stopPropagation()}>
              ${PlayOnLiveBtn()}
              ${ViewBtn()}
              <button class="row-btn sm" onClick=${() => { setSaveMenu(false); toSongCfg.current = true; createFromPatch(); }}
                title="a new song made of this patch — its sound, scenes, stomps and backing — to lay out an arrangement. The patch stays as it is.">▤ Make a song</button>
              <button class="row-btn sm" onClick=${() => { setSaveMenu(false); setAssignDone(null); setAssignOpen(true); }}
                title="put this sound in a song — an existing one (its lane is replaced) or a new one">➕ Assign in a preset</button>
              ${/* LE MENU DU MODE PATCH EST UN AUTRE MENU (2026-09-20 : « je veux créer un
                    drum patch et je n'ai pas les nouvelles interfaces »). J'avais posé le bouton
                    dans celui des PRESETS, et il n'y en a pas qu'un — le mode patch a le sien,
                    à une seule entrée. Un bouton ajouté au mauvais menu est invisible, sans
                    erreur, sans trace : exactement la panne qu'il a vue. */''}
              ${patchMode.role === 'drums' ? html`<button class="row-btn sm"
                title="a drum module has 1, 2 or up to 8 outputs — this patch can carry the whole kit"
                onClick=${() => { setSaveMenu(false); setDsOpen(true); setDsPick(null); setDsPlan([]); }}>
                <${Icon} id="drumkit" /> ${patchMode.drumset ? 'Change the drum kit' : 'Add a drum kit'}</button>` : ''}
            </div>` : ''}
        </div>
      </div>` : html`<div class="dsn-actions">
        <span class=${cls('autosave', isBlank() && 'unsaved')} data-doc="designer.saved"
          title=${isBlank() ? 'new preset — name it to keep it' : 'changes save automatically'}>
          ${/* LE FLASH N'ÉTAIT PLUS RENDU NULLE PART depuis le menu ⋯ (1a50eb3) : « name & save the
                preset first », les « ✗ not saved » de la route… tombaient dans un état que rien
                n'affichait (2026-09-28). Il parle ici, à la place du témoin, le temps de son délai. */''}
          ${saved || (isBlank() ? '● not saved' : saving ? '…saving' : '✓ saved')}</span>
        <div class="save-wrap">
          <button class=${cls('save-btn', isBlank() && 'primary', saveMenu && 'sel')} data-doc="designer.menu" onClick=${() => setSaveMenu(!saveMenu)} title="actions">⋯</button>
          ${saveMenu ? html`
            <div class="picker-scrim" onClick=${() => setSaveMenu(false)}></div>
            <div class="save-pop" onClick=${e => e.stopPropagation()}>
              ${isBlank() ? html`<button class="row-btn sm accent" onClick=${() => { setSaveMenu(false); store(); }}>💾 Name & save</button>` : ''}
              <button class="row-btn sm" onClick=${() => { setSaveMenu(false); setSettings(true); }}>⚙ Preset settings</button>
              ${ViewBtn()}
              <button class="row-btn sm" data-doc="designer.menu.scenes" onClick=${() => { setSaveMenu(false); setScnSheet(true); }}
                title="what each lane plays in each scene — name its sounds">▦ Scenes & sounds</button>
              ${/* LANES & INPUTS (retour 2026-09-09) : ajouter, nommer, brancher, retirer une lane — dans une
                    feuille, pas dans la rangée de la lane où le champ de nom était mal placé */''}
              ${/* UNE SEULE PORTE POUR LES INSTRUMENTS (2026-09-28) : « Lanes & inputs » et « Add a
                    drum kit » fusionnés. Guitar / Bass / Voice / Keys / Drums, puis l'entrée ; Drums
                    ouvre la feuille du kit (un kit = N entrées d'un geste, docs/drums-kit.md §6.5).
                    Le retrait d'une lane vit dans la même feuille. En mode patch de batterie, le
                    menu du patch garde son « Add / Change the drum kit ». */''}
              <button class="row-btn sm" onClick=${() => { setSaveMenu(false); openAdd(); }}
                title="guitar, bass, voice, keys or a drum kit — pick the instrument, then its input">＋ Add an instrument<small>or remove one</small></button>
              <button class="row-btn sm" onClick=${() => { setSaveMenu(false); duplicate(); }}>⧉ Duplicate</button>
              ${/* PASSER SUR /live AVEC CE QU'ON ÉDITE (2026-10-17) : le Designer peut montrer un brouillon qui ne
                    joue pas (rouvrir n'est pas jouer) — le geste le fait jouer, PUIS ouvre /live. Un refus de compile reste
                    affiché ici (audErr) : on ne part pas sur un /live qui jouerait autre chose. */''}
              ${PlayOnLiveBtn()}
              ${/* L'ACCUEIL AU DÉMARRAGE (mockups/startup-home.html, écran 1) : ce preset, ou ce patch nommé — un seul,
                    poser remplace. Un banc sans nom n'a rien à poser. */''}
              ${(() => { const key = patchMode && patchMode.id ? { kind: 'patch', id: 'patch:' + patchMode.id } : (!isBlank() && p.id ? { kind: 'preset', id: p.id } : null);
                if (!key) return '';
                const e = startupEntry(((rig && rig.state) || {}).startup, key);
                return html`<button class=${cls('row-btn sm', e.remove && 'accent')} title="what golem opens on /live at startup — set from here, read on /live (⌂)"
                  onClick=${() => { setSaveMenu(false); if (e.remove) del('/api/startup/home').then(() => flash('⌂ removed — bank 00 at startup')).catch(() => {});
                    else post('/api/startup/home', { ...key, name: patchMode && patchMode.id ? (patchMode.name || patchMode.id) : (p.name || p.id) }).then(r => flash(r && r.error ? '✗ ' + r.error : '⌂ opens at startup')).catch(() => {}); }}>
                  ${e.label}${e.small ? html`<small>${esc(e.small)}</small>` : ''}</button>`; })()}
              ${/* L'« Export Rig to Pool » du Kemper (docs/patches.md §15.5) : le son qu'on vient
                    de trouver EN JOUANT part au catalogue. C'est une CRÉATION, jamais une mise à
                    jour — aucun morceau existant ne bouge, et aucune dépendance n'est créée. */''}
              ${inTab !== 'cfg' && !curDs ? html`<button class="row-btn sm"
                title="copies this lane into your patch catalogue — a NEW entry, nothing gets linked"
                onClick=${() => { setSaveMenu(false); laneToPatch(); }}>
                ⛓ Save « ${esc(chainName(inTab))} » lane as patch</button>` : ''}
              ${/* sur une lane de GROUPE, on propose le KIT ENTIER : sauver la caisse claire seule
                    produirait un patch qu'on ne saurait pas reposer (§6.7) */''}
              ${curDs ? html`<button class="row-btn sm"
                title=${'copies the whole kit — ' + curDsLanes.length + ' chains, one file. A NEW entry, nothing gets linked'}
                onClick=${() => { setSaveMenu(false); kitToPatch(); }}>
                ⛓ Save the drum kit as patch <small class="muted">${curDsLanes.length} elements</small></button>` : ''}
              ${/* LA BALANCE (docs/band-scenes.md, écran 6) : cette lane, dans tous les morceaux de la setlist */''}
              ${!patchMode && curLane ? html`<button class="row-btn sm"
                title="put this lane — blocks, knobs, captures, states — in the other songs of the setlist; each song keeps its scenes, switches and levels"
                onClick=${() => { setSaveMenu(false); if (isBlank()) { flash('name & save the preset first'); return; } setLaneApply(curLane.id); }}>
                ⇉ Apply « ${esc(laneTitle(curLane))} » to the setlist…</button>` : ''}
              ${/* PLUS D'IA SUR UN PRESET (décision 2026-08-02). Un morceau est un
                    assemblage de choix humains — quels sons, dans quel ordre, pour quelles
                    sections ; un SON, lui, se décrit et se génère. L'IA vit donc dans le
                    PATCH, et un preset se compose à partir de patches. */''}
            </div>` : ''}
        </div>
      </div>`}`);
    return () => setTopSlot(null);
  }, [presets, p, scene, saving, saved, saveMenu, locked, patchMode && patchMode.id, glance]);

  // nom RÉEL du matériel capturé (ampli/pédale) : label du bloc, sinon résolu depuis le catalogue par ref
  // -> les blocs IA (ref sans label) affichent enfin le vrai nom (ex. « Boss DS-1 », « JHS Bonsai »).
  // « ce que la tuile a chargé » — capture (ref/label) OU contenu paramétré (vital→preset,
  // drums→kit…). Même badge, une seule règle : trois Vital sur une lane ne sont plus trois
  // tuiles identiques (retour 2026-07-31). Le contenu suit la SCÈNE courante.
  // L'ORIGINE d'une capture de VST : celle du bloc, sinon celle LUE dans la bibliothèque (le tone porte
  // `capture{plugin, patch, at, part, test}`) — un bloc posé avant le 2026-10-05, ou arrivé de golem.fm
  // sans le champ, se reconnaît quand même. Jamais devinée d'un nom.
  const vcapOrigin = b => {
    if (b.origin && b.origin.kind === 'vst-capture') return b.origin;
    if (!b.ref || !catalog) return null;
    const t = (catalog.tones || []).find(x => String(x.id) === refKey(b.ref));
    const c = t && t.source_group === 'plugin-capture' && t.capture;
    return c ? { kind: 'vst-capture', plugin: c.plugin, patch: c.patch, mode: c.mode, part: c.part,
                 at: String(c.at || '').slice(0, 10), null_db: c.test && c.test.synth ? Math.round(c.test.synth.null_db * 10) / 10 : null } : null;
  };
  const capName = b => {
    if (b.label && b.label[0] !== '(') return b.label;
    if (b.ref && catalog) { const t = (catalog.tones || []).find(x => String(x.id) === refKey(b.ref)); if (t) return t.amp || t.title; }
    return blockContent(b, p.scenes && p.scenes[scene]);
  };

  // ── une tuile ──
  // ── drag'n'drop des blocs (docs/designer-dnd.md, validé) : tap / appui long / drag par mouvement.
  // Cibles = tuiles (insérer AVANT) et ＋ (append en fin de zone) ; dépose ratée = retour animé.
  // L'id du bloc suit -> potards, overrides de scène, foot et pending sont conservés. ──
  // une zone = "<lane id>|pre" | "<lane id>|post" | "<lane id>|br<bi>" (lot 3 : la lane est dans le nom)
  const zoneOfRef = ref => ref && ref.lane ? [ref.lane + '|' + (ref.z === 'br' ? 'br' + ref.bi : (ref.z || 'pre')), ref.i] : null;
  const zoneArrOf = (n, z) => { const [lid, part] = z.split('|'); const c = (laneOf(n, lid) || { chain: { pre: [], post: [] } }).chain;
    return part === 'pre' ? c.pre : part === 'post' ? c.post : c.split.branches[+part.slice(2)].blocks; };
  const zoneCap = z => { const part = z.split('|')[1]; return part === 'pre' ? PRE_MAX : part === 'post' ? POST_MAX : BR_MAX; };
  const dropOk = (fromZ, toZ) => fromZ === toZ                        // même zone = réordonner, toujours ok
    || (fromZ.split('|')[0] === toZ.split('|')[0] && zoneArrOf(p, toZ).length < zoneCap(toZ));
  const moveBlock = (fromZ, fromI, toZ, toI) => upd(n => {
    const src = zoneArrOf(n, fromZ); const b = src.splice(fromI, 1)[0]; if (!b) return;
    const dst = zoneArrOf(n, toZ);
    let i = toI == null ? dst.length : toI;
    if (fromZ === toZ && fromI < i) i--;                              // le retrait décale l'index cible
    if (toZ.endsWith('|pre') && dst[0] && dst[0].type === 'whammy-dt' && i === 0) i = 1;   // whammy épinglé en tête
    dst.splice(Math.max(0, Math.min(i, dst.length)), 0, b);
  });

  const gestFired = useRef(false);           // appui long OU drag -> avale le clic qui suit
  const tileGesture = (b, ref) => ({
    onContextMenu: e => { e.preventDefault(); setSelTab('assign'); setSel(ref); },
    onPointerDown: e => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      gestFired.current = false;
      const z = zoneOfRef(ref);
      const canDrag = !!z && b.type !== 'whammy-dt' && !locked;
      const srcEl = e.currentTarget, sx = e.clientX, sy = e.clientY;
      const r0 = srcEl.getBoundingClientRect();
      let clone = null, curEl = null, curTarget = null;
      const clearHover = () => { if (curEl) curEl.classList.remove('drop-hover'); curEl = null; curTarget = null; };
      const stopDrag = back => {
        if (!clone) return;
        srcEl.classList.remove('drag-src');
        document.documentElement.classList.remove('gc-drag');
        document.querySelectorAll('.drop-ok').forEach(el => el.classList.remove('drop-ok'));
        clearHover();
        if (back) {                                                    // dépose ratée : retour animé
          const c = clone; c.style.transition = 'transform .18s ease, opacity .18s ease';
          c.style.transform = `translate(${r0.left}px, ${r0.top}px)`; c.style.opacity = '0.4';
          setTimeout(() => c.remove(), 200);
        } else clone.remove();
        clone = null;
      };
      const lp = setTimeout(() => { gestFired.current = true; cleanup(); setSelTab('assign'); setSel(ref); }, 450);
      const move = ev => {
        const dx = ev.clientX - sx, dy = ev.clientY - sy;
        if (!clone) {
          if (Math.hypot(dx, dy) < 10) return;
          clearTimeout(lp);                                            // ça bouge : plus un appui long
          if (!canDrag) { cleanup(); return; }
          gestFired.current = true;
          clone = srcEl.cloneNode(true);                               // la tuile se soulève et suit le doigt
          Object.assign(clone.style, { position: 'fixed', left: 0, top: 0, width: r0.width + 'px',
            height: r0.height + 'px', margin: 0, zIndex: 1000, pointerEvents: 'none' });
          clone.classList.add('drag-clone');
          document.body.appendChild(clone);
          srcEl.classList.add('drag-src');
          document.documentElement.classList.add('gc-drag');
          // n'allume QUE les cibles valides (caps + zones autorisées)
          document.querySelectorAll('[data-drop],[data-dropend]').forEach(el => {
            const key = el.dataset.drop || el.dataset.dropend;
            if (el !== srcEl && dropOk(z[0], key.split(':')[0])) el.classList.add('drop-ok');
          });
        }
        clone.style.transform = `translate(${ev.clientX - r0.width / 2}px, ${ev.clientY - r0.height / 2}px)`;
        const under = document.elementFromPoint(ev.clientX, ev.clientY);
        const t = under && under.closest('.drop-ok');
        if (t !== curEl) {
          clearHover();
          if (t) { curEl = t; t.classList.add('drop-hover');
            curTarget = t.dataset.drop ? { toZ: t.dataset.drop.split(':')[0], toI: +t.dataset.drop.split(':')[1] }
                                       : { toZ: t.dataset.dropend, toI: null }; }
        }
      };
      const up = () => {
        clearTimeout(lp);
        if (clone) { const tgt = curTarget; stopDrag(!tgt); if (tgt) moveBlock(z[0], z[1], tgt.toZ, tgt.toI); }
        cleanup();
      };
      const cancel = () => { clearTimeout(lp); stopDrag(true); cleanup(); };
      const cleanup = () => { clearTimeout(lp);
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', cancel); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', cancel);
    },
  });

  const Tile = (b, ref) => {
    const off = sceneOff(b);                       // coupé PAR LA SCÈNE (style dédié)
    const on = blockOn(b);                         // ce que le moteur joue, vraiment
    const inv = !!fxDef(b.type).scene_invariant;   // looper & co : jamais piloté par la scène
    const cap = capName(b);
    // identité VARIANTE (pédale/ampli nommé) : nom/glyphe/couleur de l'archétype, pas du type de base
    const arch = b.variant ? pedalArch(b.variant) : null;
    // CAPTURE D'UN VST (2026-10-05) : un bloc ampli/pédale/baffle ORDINAIRE pour le moteur (il joue partout,
    // Linux compris), qui se RECONNAÎT ici — icône et couleur du VST d'origine, et le nom choisi à la capture
    const vcap = !!vcapOrigin(b);
    const tc = vcap ? VCAP_COLOR : arch ? arch.color : blkColor(b.type);
    const ic = vcap ? VCAP_ICON : arch ? arch.glyph : fxIcon(b.type);
    const nm = b.type === 'vst-host' ? (b.label || 'VST Host').replace(/^.*?:\s*/, '').slice(0, 18)
      : vcap ? (b.label || 'VST capture').slice(0, 18)
      : arch ? (arch.short || arch.name) : fxShort(b.type);
    // ⚠ 2026-09-11 — le badge « ∅ » ne sortait que pour un ARCHÉTYPE nommé (pédale/ampli de
    // marque). Un `amp-nam` ou un `cab` générique sans capture n'affichait RIEN, alors que le rig
    // le RETIRE désormais (un NAM vide coupe le son de sa branche, cf. rig._drop_empty_capture) :
    // la tuile montrait un ampli que le rack ne joue pas. Tout bloc à capture vide le dit.
    const emptyPed = needsModel(b.type) && !b.ref && !b.pending;
    const z = zoneOfRef(ref);
    const dropKey = z && b.type !== 'whammy-dt' ? `${z[0]}:${z[1]}` : null;   // pas d'insertion AVANT le whammy épinglé
    // quarantaine (effects.json) : le bloc est encore dans le patch mais la compile le RETIRE du rig ;
    // la tuile le dit, sinon un bloc muet se cherche à l'oreille (GxDetune, 2026-09-07)
    const quar = fxDef(b.type).quarantine;
    // service coupé par le MODE courant : la tuile reste (le preset garde son bloc) mais elle le dit
    const svcOff = svcVetoed(rig, b.type);
    // Drum Kit sur une lane AUDIO : la compile le retire (le module fait le son) — la tuile le dit AVANT
    const kitAudio = b.type === 'drumkit' && ref && ref.lane && !(lanes.find(L => L.id === ref.lane) || {}).midi;
    // ÉTAT DU BLOC SUR CE RACK (docs/block-status.md) : ⬇ téléchargeable, ✕ pas disponible ici. La
    // quarantaine a déjà son badge ; `empty` a son ∅. Taper une tuile en erreur ouvre SA feuille.
    const bst = b.id ? bstat[b.id] : null;
    const bsDl = !!bst && bst.state === 'download';
    const bsNa = !!bst && bst.state === 'unavailable' && bst.reason !== 'quarantine';
    const ctl = !patchMode && arrCtl.has(b.type);   // lancé par l'Arrangement (variante 2 : liseré + ▤)
    return html`<button class=${cls('tile', GOLEM_FX.has(b.type) && 'gfx', ctl && 'arr-ctl', (!on && !off) && 'byp', off && 'scene-off', b.pending && 'pending', emptyPed && 'empty-cap', quar && 'quar', svcOff && 'svc-off', bsDl && 'bs-dl', bsNa && 'bs-na', refEq(sel, ref) && 'sel')}
        style=${'--tc:' + tc} data-drop=${dropKey} aria-label=${nm + ' · ' + b.type} data-doc=${'designer.block:' + (b.id || b.type)}
        onClick=${() => { if (lpFired() || gestFired.current) return; setSelTab('params');
          if (bsDl || bsNa || (quar && bst)) { setBsSheet({ ref, st: bst }); return; }
          needsModel(b.type) && !b.ref ? setPickAmp(ref) : setSel(ref); }}
        ...${tileGesture(b, ref)} title=${(bsDl ? '⬇ not on this rack — ' + (bst.why || '') + ' · tap to download or replace · '
            : bsNa ? '✕ not available here — ' + (bst.why || '') + ' · tap to replace · ' : '')
          + (ctl ? '▤ started by the Arrangement with « ' + arrSongTitle + ' » — set in Songs · ' : '')
          + (b.pending ? '⬇ to download: ' : (cap ? cap + ' · ' : '')) + (cap && b.pending ? cap + ' · ' : '') + (emptyPed ? 'no capture — left out of the rig · tap to pick/download · ' : '') + 'tap = settings · long press = assign · drag = move'}>
      ${quar ? html`<span class="tile-badge quar" title=${/^golem-fx only/.test(quar)
          ? 'golem-fx only: this engine does not play it — the block is skipped (Golem Engine, or REAPER on Linux with the plugin installed)'
          : 'quarantined: this plugin crashes the engine — the block is skipped; remove it'}>⚠ off</span>`
        : svcOff ? html`<span class="tile-badge svc-off" title=${'off in ' + (((rig || {}).mode || {}).name || 'this mode') + ' — Settings ▸ Mode ▸ Tools'}>off in ${esc(((rig || {}).mode || {}).name || 'mode')}</span>` : ''}
      ${kitAudio ? html`<span class="tile-badge empty" title="audio input: the drum module makes the sound — this block is LEFT OUT of the rig. Switch the lane to its USB port to play the rack's kits.">audio</span>` : ''}
      ${b.pending ? html`<span class="tile-dl" title=${'to download: ' + esc(cap || '')}>⬇</span>` : ''}
      ${bsDl ? html`<span class="tile-dl bs" title=${esc(bst.why || '')}>⬇</span>` : bsNa ? html`<span class="tile-dl bs na" title=${esc(bst.why || '')}>✕</span>` : ''}
      ${emptyPed ? html`<span class="tile-badge empty" title="no capture — this block is LEFT OUT of the rig (empty, it would mute its branch) · tap to pick or download one">∅</span>`
        : cap ? html`<span class=${cls('tile-badge', CONTENT_PARAM[b.type] && 'wide')} title=${esc(cap)}>${esc(cap).slice(0, CONTENT_PARAM[b.type] ? 11 : 6)}</span>` : ''}
      <span class="tile-ic">${ic}</span>
      <span class="tile-nm">${nm}</span>
      ${b.foot ? html`<span class="tile-foot" title=${'pedalboard footswitch ' + b.foot}><${FOOTSW} />${b.foot}</span>` : ''}
      ${b.type === 'volume' ? html`<span class="tile-foot exp" title="driven by the volume expression pedal (Settings ▸ Pedalboard ▸ Expression roles)">EXP${((rig && rig.state && rig.state.pedals) || {}).volume === 'exp2' ? 2 : 1}</span>` : ''}
      ${/* ⚠ 2026-09-11 — cette pastille basculait le bypass de BASE. Sur un bloc que la scène
             coupe (le cas de tous les patches de golem.fm, qui posent des scene.blocks partout),
             le clic ne changeait RIEN de visible : « je n'arrive pas à activer/désactiver un bloc
             autrement que par les scènes ». Peaufiner un son, c'est allumer et éteindre DANS LA
             SCÈNE qu'on écoute — comme les potards, déjà scene-first. Le bypass global reste, lui,
             dans le tiroir (⏻ Active/Bypassed). Les blocs scene_invariant (looper) gardent le
             bypass : par doctrine, une scène ne les touche jamais. */''}
      <span class=${cls('tile-dot', !on && 'ko')} onClick=${e => { e.stopPropagation();
          inv ? toggleBypass(ref) : setSceneBlock(ref, !on); }}
        title=${inv ? (b.bypass ? 'bypassed everywhere — tap to engage' : 'scene-invariant — tap to bypass everywhere')
                    : (on ? 'on in ' + (sc.id || 'this scene') + ' — tap to mute it here'
                          : 'muted in ' + (sc.id || 'this scene') + ' — tap to bring it back')}></span>
    </button>`;
  };
  // « ＋ » unique par lane : ouvre le tiroir de blocs. Sur la chaîne PRINCIPALE non splittée, il
  // porte un petit MENU (Add block / Split the chain) — le Split a retrouvé sa place dans le +
  // (retour 2026-07-21). Ailleurs (post, branches, voix, keys) = ouverture directe du tiroir.
  const [plusMenu, setPlusMenu] = useState(null);
  const PlusBtn = (ref) => {
    const dz = ref.lane ? ref.lane + '|' + (ref.add === 'br' ? 'br' + ref.bi : (ref.add === 'post' ? 'post' : 'pre')) : null;
    const canSplit = ref.add === 'pre' && !split && !gDisabled && !(curLane && curLane.midi);
    if (!canSplit) return html`<button class="gc-addbtn" data-dropend=${dz} onClick=${() => setDrawer(ref)} title="add block">＋</button>`;
    return html`<div class="plus-wrap">
      <button class=${cls('gc-addbtn', plusMenu && 'sel')} data-dropend=${dz}
        onClick=${e => setPlusMenu(plusMenu ? null : {
          // lane vide -> ＋ au bord GAUCHE -> le menu s'ouvre vers la droite ; sinon vers la gauche
          flip: e.currentTarget.getBoundingClientRect().left < 300 })}
        title="add block / split the chain">＋</button>
      ${plusMenu ? html`
        <div class="picker-scrim" onClick=${() => setPlusMenu(null)}></div>
        <div class=${cls('save-pop', 'plus-pop', plusMenu.flip && 'flip-r')} onClick=${e => e.stopPropagation()}>
          <button class="row-btn sm" onClick=${() => { setPlusMenu(null); setDrawer(ref); }}>＋ Add block</button>
          <button class="row-btn sm" onClick=${() => { setPlusMenu(null); diviser(); }}>⑃ Split the chain</button>
        </div>` : ''}
    </div>`;
  };

  // pastille de sortie (chaîne ou branche) : ouvre le popover OUT 1 / OUT 2 / OUT 1·2
  const OutPill = (key, cur, onPick) => html`<div class="io-out-wrap">
    <button class=${cls('io-pill out', outPick === key && 'sel', cur === 'NONE' && 'off')} data-doc="designer.out" onClick=${() => setOutPick(outPick === key ? null : key)} title="output">OUT ▶<br/><b>${outLabel(cur)}</b></button>
    ${outPick === key ? Picker(cur, onPick, OUT_OPTS) : ''}
  </div>`;
  // pastille d'ENTRÉE cliquable : IN 1 / IN 2 / NONE (NONE = chaîne désactivée)
  // une lane MIDI affiche SON port (« USB 2 »), plus un « USB 1 » écrit en dur qui mentait dès le 2e port
  const InPill = (key, cur, onPick) => { const u = /^usb(\d*)$/.exec(String(cur || ''));
    return html`<div class="io-out-wrap">
    <button class=${cls('io-pill in', u && 'usb', outPick === key && 'sel', cur === 'NONE' && 'off')} data-doc="designer.in"
      onClick=${() => setOutPick(outPick === key ? null : key)}
      title="input — a card input (the source makes the sound) or a bound USB port (MIDI: the rack plays its own instruments)"
      >▶ ${u ? 'USB' : 'IN'}<br/><b>${cur === 'NONE' ? '—' : (u ? (u[1] || 'auto') : cur)}</b></button>
    ${outPick === key ? Picker(cur, onPick, inOptsLive(cur), 'right') : ''}
  </div>`; };
  // entrée du Recorder : ce qu'il capte est décrit par le MODE du bloc Rec (réglé dans son tiroir
  // avec les sources IN1/IN2/USB). L'ancien « tap point » post/di/both a été retiré : rien ne le
  // lisait côté moteur, et le mode « Multitrack + DI » couvre déjà le besoin (2026-07-25).
  const recModeLabel = m => m === 'tracks' ? 'Multi' : m === 'tracks_di' ? 'Multi+DI' : 'Mix';
  // destination du REC : le disque (pas un port audio) — pastille de fin de ligne, non cliquable
  const DiskPill = () => html`<div class="io-out-wrap">
    <div class="io-pill out fixed" title="takes are written to the rack's drive — Library ▸ Tracks ▸ Recordings">⭳ REC<br/><b>Hard drive</b></div>
  </div>`;

  // ── payloads de la GRILLE (docs/designer-grid.md) — caps : pre 12, branche 6, post 6 ──
  // le bloc VOLUME est VISIBLE et déplaçable (option B, 2026-07-20) : sa position dans la
  // chaîne compte (avant les delays = volume guitare, après = master). ensure_volume ne le
  // re-seed que s'il est ABSENT — un déplacement est donc conservé.
  const visTiles = (arr, mk) => arr.map((b, i) => b ? Tile(b, mk(i, b)) : null).filter(Boolean);
  // caps par ZONE (cachent le « ＋ ») — cohérents avec MAX_BLOCKS=18 (garde d'ajout) ; c'était
  // LA limite qui bloquait le mainteneur Test à 12 (bug 2026-07-23 : deux plafonds distincts, celui-ci en dur)
  const PRE_MAX = 16, BR_MAX = 8, POST_MAX = 8;
  const LID = curLane ? curLane.id : 'guitar';
  const gHead = [
    InPill('in:' + LID, chainIn(LID), s => setIn(LID, s)),
    ...visTiles(g.pre, i => ({ lane: LID, z: 'pre', i })),
    ...(g.pre.length < PRE_MAX ? [{ plus: PlusBtn({ lane: LID, add: 'pre' }) }] : []),
  ];
  const laneCells = bi => { const br = split.branches[bi]; return [
    ...br.blocks.map((b, i) => b ? Tile(b, { lane: LID, z: 'br', bi, i }) : null).filter(Boolean),
    ...(br.blocks.length < BR_MAX ? [{ plus: PlusBtn({ lane: LID, add: 'br', bi }) }] : []),
  ]; };
  const gZone = split && split.branches.length >= 2 ? {
    fanout: !isMerge,
    laneA: laneCells(0), laneB: laneCells(1),
    outA: !isMerge ? OutPill('br0', split.branches[0].out || '1-2', s => setBranchOut(0, s)) : null,
    outB: !isMerge ? OutPill('br1', split.branches[1].out || '1-2', s => setBranchOut(1, s)) : null,
    close: isMerge ? html`<div class="gc-sum" data-doc="designer.merge" title="somme des branches"><b>Σ</b>
      <input type="number" value=${split.gain ?? -3} onInput=${e => setMergeGain(+e.target.value)} /><small>dB</small></div>` : null,
  } : null;
  const gTail = gZone && isMerge ? [
    ...visTiles(g.post, i => ({ lane: LID, z: 'post', i })),
    ...(g.post.length < POST_MAX ? [{ plus: PlusBtn({ lane: LID, add: 'post' }) }] : []),
  ] : [];
  // retirer un split : le « × » en début de lane (rmBranch) le replie déjà — pas de bouton dédié
  // (retour 2026-07-21 : le 3e bouton dans « { » était une régression inutile).
  const gMeta = gZone ? {
    hdr: html`<div class="gc-zonehdr" data-doc="designer.split">
      <button class=${cls('mode-btn', !isMerge && 'on')} onClick=${() => setSplitMode('fanout')} title="fan-out — each branch goes out on its own output">⇉</button>
      <button class=${cls('mode-btn', isMerge && 'on')} onClick=${() => setSplitMode('merge')} title="merge — branches summed to a single output">Σ</button></div>`,
    lanes: split ? split.branches.slice(0, 2).map((br, bi) => ({
      tag: LANE_LETTER(bi), muted: laneMuted(br.id),
      onPw: () => setSceneLane(br.id, laneMuted(br.id)), onDel: () => rmBranch(bi) })) : [],
  } : null;
  // lane MIDI : blocs-instruments à input_claim (docs/blocks-doctrine.md) — Vital (touches) et
  // Pads, un seul de chaque (garde-fou dans addBlock) ; les FX s'empilent.
  // (zones + transpose : PAR INSTRUMENT, dans sa fiche « Keyboard zone » —
  //  les raccourcis globaux pill/titre sont retirés, retour UX 2026-07-19)
  // UNE pastille ＋ -> tiroir standard filtré catégorie keys (retour UX 2026-07-19 :
  // fini les 5 tuiles-slots nommées à la chaîne ; l'unicité par claim est grisée dans le tiroir)
  const KEYS_TYPES = ['vital', 'piano', 'organ', 'ep', 'pads', 'drumkit'];   // instruments d'une lane MIDI (claviers ET batterie) : un seul par type
  // sections du tiroir Keys : instruments, pads, puis les familles d'effets COHÉRENTES pour
  // un clavier (chorus/phaser sur EP, drive+rotary sur organ, delay/reverb synthé, comp/EQ,
  // captures de pédales). Exclus : wah (pédale EXP guitare), pitch/Whammy, amp/cab.
  // ⚠ 2026-09-14 : la table vit EN DONNÉE (effects.json `role_categories`) — golem.fm lit la même clé pour
  // son tiroir et le vocabulaire de l'IA (demande : « le tiroir de golem.fm filtre comme le mien »).
  // Une copie de logique des deux côtés divergerait comme une copie de table (docs/gear-classifier.md).
  const ROLE_CATS_DATA = (effects && effects.role_categories) || {};
  // le TAMIS FIN par rôle (catalogue v15, docs/drums-kit.md) : la liste exacte des blocs d'un rôle, dans ses
  // catégories ; un rôle absent voit tous les blocs de ses catégories (guitar/bass/voice/keys aujourd'hui)
  const ROLE_BLOCKS = (effects && effects.role_blocks) || {};
  const KEYS_CATS = ROLE_CATS_DATA.keys || ['keys', 'pads', 'dynamics', 'preamp', 'drive', 'lofi', 'eq', 'modulation', 'delay', 'reverb'];
  // tiroir CONTEXTUEL au rôle (patch Soundcard) : catégories autorisées + famille de captures.
  // guitar/line = toutes les catégories (absent de la table). bass = rig complet + captures basse.
  // voice = FX vocaux (pas d'ampli/cab/dirt/filtre). keys/pads = KEYS_CATS.
  // repli = la table d'avant (catalogue absent ou antérieur à v11) ; sinon la donnée, clé `_comment` exclue
  const ROLE_CATS = Object.keys(ROLE_CATS_DATA).some(k => k[0] !== '_')
    ? Object.fromEntries(Object.entries(ROLE_CATS_DATA).filter(([k]) => k[0] !== '_'))
    : { bass:  ['dynamics', 'preamp', 'drive', 'lofi', 'filter', 'amp', 'cab', 'eq', 'modulation', 'delay', 'reverb', 'pitch', 'utility'],
        voice: ['dynamics', 'preamp', 'lofi', 'eq', 'modulation', 'delay', 'reverb', 'pitch'],
        drums: ['dynamics', 'preamp', 'lofi', 'eq', 'modulation', 'delay', 'reverb', 'utility'],
        keys: KEYS_CATS, 'keys-pads': KEYS_CATS, pads: KEYS_CATS };
  const ROLE_FAM = { guitar: 'guitar', bass: 'bass' };   // filtre captures TONE3000 dans le picker

  // ── vue PÉDALIER : le FCB1010 tel qu'il pilote CE preset. Assignation LIBRE — un switch (6-10) tient
  // les blocs dont block.foot == n (plusieurs par switch, ex. 7 = delay+reverb). On/off par scène =
  // scene.blocks (même convention que la chaîne) -> synchro éditeur + auto-save. ──
  const blkOnInScene = b => { const sb = sc.blocks || {};      // effectif : id > type > bypass (comme le bake)
    if (b.id != null && b.id in sb) return sb[b.id] !== false;
    if (b.type in sb) return sb[b.type] !== false;
    return !b.bypass; };
  // blocs assignables au pied, TOUTES CHAÎNES confondues : [bloc, entrée '1'|'2'|'k'] — un switch
  // physique pilote les blocs de n'importe quelle entrée (ex. reverb du chant au pied).
  // clé « pied » d'une lane : 1/2/k pour les trois d'origine, l'ENTRÉE physique pour les autres (badge « IN 4 »)
  const footKey = L => L.midi ? 'k' : (['1', '2'].includes(L.key) ? L.key : (L.in_sel !== 'NONE' ? L.in_sel : L.id));
  const footBlocks = () => [
    ...lanes.flatMap(L => laneBlocks(L).filter(b => b && b.id).map(b => [b, footKey(L)])),
    ...genBlocks.filter(b => b && b.id).map(b => [b, 'cfg']),
    ...recBlocks.filter(b => b && b.id).map(b => [b, 'cfg']),
    ...arrBlocks.filter(b => b && b.id).map(b => [b, 'cfg']),
  ];
  const inTag = k => k === 'k' ? 'USB' : k === 'cfg' ? 'CFG' : 'IN ' + k;
  // la carte des 10 switches (mini-pédalier, fiche ⓘ) : ce que chacun porte, et sa couleur
  const swMap = () => { const fb = footBlocks().map(([b]) => b);
    // les assignations AUTOMATIQUES (2026-10-14) : un preset looper prend ses boucles (1-4), « tout » (5) et
    // « effacer » (10) — la carte les montre, au lieu de scènes que le pied ne joue plus
    const lm = looperMode();
    const lrows = lm ? looperRows() : [];
    const auto = n => { const r = lrows.find(x => x.sw === n);
      if (r) { const ln = loopLanes().find(l => l.key === r.src);   // sans nom : la LANE en clair, pas son id (« voice-1 »)
        const nm = r.label || (ln ? ln.label : r.src);
        return { kind: 'loop', color: '#e02020', label: 'loop · ' + nm, name: nm, cat: 'Loop' }; }
      if (lm && n === 5) return { kind: 'all', color: '#3d9be9', label: 'play / stop all loops', name: 'play / stop all', cat: 'All' };
      if (lm && n === 10) return { kind: 'clear', color: '#e02020', label: 'clear all loops (hold)', name: 'hold: clear all', cat: 'Clear' };
      return null; };
    return Array.from({ length: 10 }, (_, k) => { const n = k + 1; const au = auto(n);
      if (au) return { n, bs: [], sp: null, sc: null, au, color: au.color, label: au.label, short: au.kind === 'loop' ? '◉' : String(n) };
      const bs = fb.filter(b => b.foot === n);
      const sp = bs.length && bs.every(b => SPECIAL_CAT[b.type]) ? SPECIAL_CAT[bs[0].type] : null;
      const sc = n <= 5 && !bs.length ? (p.scenes || [])[n - 1] : null;
      return { n, bs, sp, sc,
        color: sp ? sp[1] : bs.length ? '#5a6270' : sc ? '#3d9be9' : null,
        label: bs.length ? bs.map(b => b.type === 'arrangement' ? 'Song' : fxShort(b.type)).join(' + ') : sc ? 'scene ' + sc.id + (sc.name && sc.name !== sc.id ? ' · ' + sc.name : '') : 'free',
        short: sc ? sc.id : String(n) }; }); };
  const ROLE_TAG = { guitar: 'GTR', bass: 'BASS', voice: 'VOX', keys: 'KEYS', 'keys-pads': 'KEYS', pads: 'PADS', drums: 'DRUM', line: 'LINE' };
  const glancePop = () => {
    if (!glance) return '';
    const map = swMap();
    const close = () => setGlance(null);
    // LA CARTE DES SWITCHES = LE PÉDALIER DU TIROIR MIDI ASSIGN (2026-10-08 : « un panel plus proche de
    // l'agencement du pédalier ») — mêmes cases (.asg-*), en LECTURE : 6-10 en haut, 1-5 en bas, EXP à droite. Une case
    // spéciale porte en plus la couleur de sa catégorie (SONG, PLAYERS…), comme sur /live.
    const fxItems = bs => html`<span class="asg-fx">${bs.slice(0, 3).map(b => html`<i><u>${fxIcon(b.type)}</u><em>${esc(b.type === 'arrangement' ? 'Song' : fxShort(b.type))}</em></i>`)}</span>`;
    const roCell = c => {
      if (c.au) return html`<div class="asg-sw used pg-sp" style=${'--sc:' + c.au.color} title=${'switch ' + c.n + ' — ' + c.au.label}>
        <span class="asg-n">${c.n}</span><span class="pg-cat">${c.au.cat}</span><em class="asg-name">${esc(c.au.name)}</em></div>`;
      if (c.bs.length) return html`<div class=${cls('asg-sw', 'used', c.sp && 'pg-sp')} style=${c.sp ? '--sc:' + c.sp[1] : ''}
        title=${'switch ' + c.n + ' — ' + c.label + (c.bs[0].type === 'arrangement' ? ' (start / stop)' : '')}>
        <span class="asg-n">${c.n}</span>${c.sp ? html`<span class="pg-cat">${c.sp[0]}</span>` : ''}${fxItems(c.bs)}</div>`;
      if (c.sc) return html`<div class=${cls('asg-sw', 'scene', (p.scenes || []).indexOf(c.sc) === scene && 'here')} title=${c.label}>
        <span class="asg-n">${c.n}</span><b class="asg-letter">${c.sc.id}</b><em class="asg-name">${esc(c.sc.name || '')}</em></div>`;
      return html`<div class="asg-sw void" title=${'switch ' + c.n + ' is free'}><span class="asg-n">${c.n}</span><span class="asg-empty">—</span></div>`;
    };
    const volN = (((rig || {}).state || {}).pedals || {}).volume === 'exp2' ? 2 : 1;
    const expB = p.exp2 ? (ourBlocks().find(b => b && b.id === p.exp2.block) || null) : null;
    const expRo = n => html`<div class="asg-sw exp void"><b class="asg-letter sm">EXP ${n}</b>
      <em class="asg-name">${n === volN ? 'volume' : expB ? esc(fxShort(expB.type)) : '—'}</em></div>`;
    const body = glance.kind === 'map' ? html`
      <b class="pg-h">Footswitches <small class="muted">— set them in a block's MIDI assign</small></b>
      <div class="asg-board pg-board">
        <div class="asg-col">
          <div class="asg-row5">${[6, 7, 8, 9, 10].map(n => roCell(map[n - 1]))}</div>
          <div class="asg-row5">${[1, 2, 3, 4, 5].map(n => roCell(map[n - 1]))}</div>
        </div>
        <div class="asg-expcol">${expRo(1)}${expRo(2)}</div>
      </div>`
    : (() => {
      const unm = ((rig || {}).state || {}).rig_unmounted || [];
      const lns = lanes.filter(L => L && !L.disabled);
      const starts = arrSong ? resolveStarts((arrSong.params || {}).starts, p) : null;
      const startsTxt = starts ? Object.keys(STARTS_TYPES).filter(k => starts[k]).map(k => ({ backing: 'backing', click: 'click', rec: 'rec', sample: 'samples' }[k])).join(' · ') : '';
      const sp = map.filter(c => c.sp);
      return html`
      <b class="pg-h">${esc(docTitle())}</b>
      <div class="pg-g">
        <b>Song</b><span>${!arrRow ? 'no song uses this preset'
          : arrRow.line.band_song ? esc(arrRow.line.title || docTitle()) + ' · ' + (((arrSong || {}).params || {}).sections || []).length + ' parts'
          : 'the bank plays the preset alone — no song on its line (add the song to the setlist from Songs)'}</span>
        <b>Bank</b><span>${myBank >= 0 ? '#' + bankNo(myBank) + ' in « ' + bankSetlist + ' » (current)' : 'not in « ' + bankSetlist + ' »'}${alsoIn.length ? ' · also in ' + alsoIn.map(x => x.name || x.id).join(', ') : ''}</span>
        <b>Scenes</b><span>${(p.scenes || []).map(sc => sc.id + (sc.name && sc.name !== sc.id ? ' ' + sc.name : '')).join(' · ') || '—'}</span>
        <b>Plays</b><span>${lns.map(L => { const off = unm.some(u => u.name === L.name);
          return html`<em class=${cls('pg-tag', 'r-' + (L.midi ? 'keys' : L.role), off && 'off')} title=${off ? L.name + ' — not on this card' : L.name}>${ROLE_TAG[L.role] || (L.midi ? 'KEYS' : String(L.role || '').toUpperCase())}</em>`; })}
          ${unm.length ? html`<small class="muted"> ${unm.map(u => u.name).join(', ')} not on this card</small>` : ''}</span>
        <b>Specials</b><span>${sp.length ? sp.map(c => 'SW' + c.n + ' ' + c.label).join(' · ') : 'none'}</span>
        ${arrSong ? html`<b>Starts with</b><span>${startsTxt || 'nothing'} · ${p.bpm || 120} BPM</span>` : ''}
      </div>`; })();
    return html`<div class="pg-scrim" onClick=${close}>
      <div class=${cls('pg-pop', 'pgp-' + glance.kind)} style=${`left:${Math.max(8, Math.min(glance.x, window.innerWidth - (glance.kind === 'map' ? 656 : 456)))}px; top:${glance.y + 6}px`}
        onClick=${e => e.stopPropagation()}>${body}</div></div>`;
  };
  const switchBlocks = n => footBlocks().filter(([b]) => b.foot === n);
  const switchOn = n => { const bs = switchBlocks(n); return bs.length > 0 && bs.every(([b]) => blkOnInScene(b)); };
  const toggleSwitch = n => { const bs = switchBlocks(n); if (!bs.length) return; const target = !switchOn(n);
    upd(x => { const s = x.scenes[scene]; s.blocks = s.blocks || {};
      bs.forEach(([b]) => { delete s.blocks[b.type];           // migre l'ancienne clé par TYPE -> clés par id
        if (target && !b.bypass) delete s.blocks[b.id]; else s.blocks[b.id] = target; });
      if (!Object.keys(s.blocks).length) delete s.blocks; }); };
  const hasWah = () => ourBlocks().some(b => b && (String(b.type).startsWith('wah') || b.type === 'autowah'));
  const FCB_SW = [6, 7, 8, 9, 10];
  // Les lanes que le preset offre VRAIMENT au looper (docs/looper.md §7) : une source absente
  // donnerait une boucle qui enregistre du silence — l'écran doit le dire, pas le laisser
  // découvrir au pied. `ok` = entrée et sortie branchées, et la lane a une chaîne (sauf la
  // guitare, qui existe même vide : passthrough).
  const loopLanes = () => lanes.map(L => ({ key: L.key, label: L.name,
    ok: !laneDisabled(L) && (L.id === 'guitar' || laneBlocks(L).length > 0) }));
  // bande récap des stomps (6-10) à la suite du titre de chaîne : icône + n° + effet(s) / « free ».
  // Preset LOOPER : elle SUIT LA TABLE DE BOUCLES du bloc (docs/looper.md §1) — plus « les trois
  // entrées » en dur. Un switch sans ligne reste un stomp ordinaire, y compris 6/7/8 : c'est tout
  // l'objet du contrat (un guitariste seul n'a plus deux switches qui enregistrent du silence).
  // le bloc looper, où qu'il vive (lane config depuis la doctrine — pas dans une chaîne)
  const looperBlock = () => { let found = null;
    const walk = o => { if (found) return;
      if (Array.isArray(o)) { o.forEach(walk); return; }
      if (o && typeof o === 'object') {
        if (o.type === 'looper') { found = o; return; }
        Object.values(o).forEach(walk);
      } };
    ['lanes', 'guitar', 'voice', 'keys', 'paths', 'config'].forEach(k => walk(p[k]));
    return found; };
  const looperRows = () => loopRows(((looperBlock() || {}).params || {}).loops);
  // mode looper = bloc marqueur présent (doctrine) OU flag legacy des anciens presets
  // ⚠ MÊME RÈGLE QUE LE RACK, sinon l'écran et le pied ne parlent pas du même preset.
  // Ce test ne regardait que les chaînes guitare / voix / claviers. Or un bloc looper vit dans
  // la LANE DE CONFIG (onglet ⚙, avec les autres générateurs) — que `rig.looper_enabled` parcourt
  // et que celui-ci ignorait. Résultat vécu sur « ZZ Conflict » : le Designer montrait une
  // rangée de stomps normale, on y assignait une wah en SW6 et une whammy en SW7… pendant que
  // le rack donnait déjà toute la rangée au looper. Les deux pédales restaient muettes au pied,
  // et l'écran d'édition affirmait le contraire. On balaie donc les mêmes racines que le bridge.
  const hasLooperBlock = (o) => {
    if (Array.isArray(o)) return o.some(hasLooperBlock);
    if (o && typeof o === 'object') {
      return o.type === 'looper' || Object.values(o).some(hasLooperBlock);
    }
    return false;
  };
  const looperMode = () => (p.looper && p.looper.enabled)
    || ['lanes', 'guitar', 'voice', 'keys', 'paths', 'config'].some(k => hasLooperBlock(p[k]));
  // ref Designer d'un bloc par prédicat (ordre pre / branches / post / voix / keys)
  const findRefBy = pred => {
    for (const L of lanes) {
      const c = L.chain || {};
      let i = (c.pre || []).findIndex(b => b && pred(b)); if (i >= 0) return { lane: L.id, z: 'pre', i };
      const brs = ((c.split || {}).branches) || [];
      for (let bi = 0; bi < brs.length; bi++) {
        const j = (brs[bi].blocks || []).findIndex(b => b && pred(b));
        if (j >= 0) return { lane: L.id, z: 'br', bi, i: j };
      }
      i = (c.post || []).findIndex(b => b && pred(b)); if (i >= 0) return { lane: L.id, z: 'post', i };
    }
    let i = genBlocks.findIndex(b => b && pred(b)); if (i >= 0) return { cg: i };
    i = recBlocks.findIndex(b => b && pred(b)); if (i >= 0) return { cr: i };
    i = arrBlocks.findIndex(b => b && pred(b)); if (i >= 0) return { ca: i };
    return null;
  };
  // L'ÉTAT NATIF D'UN BLOC VST HOST CAPTURÉ DANS LE PATCH — par son id (le tiroir, ou la fenêtre filmée de Linux qui
  // se ferme quand le tiroir n'est peut-être plus ouvert) : la base du bloc, et les valeurs de la scène `sceneId`
  const applyHostState = (blockId, sceneId, state) => {
    const ref = findRefBy(b => b.id === blockId);
    if (!ref) return false;
    setP(prev => {
      const old = blockAt(prev, ref);
      if (old?.id !== blockId || !['vst_chunk', 'clap_chunk'].includes(state.kind)) return prev;
      const oldOvr = (prev.scenes || []).find(s => s.id === sceneId)?.params?.[old.id];
      const captured = captureHostState(old.params, oldOvr, state);
      if (!captured.changed) return prev;
      const n = structuredClone(prev);
      const b = blockAt(n, ref);
      b.params = captured.params;
      const scn = (n.scenes || []).find(s => s.id === sceneId);
      if (scn?.params?.[b.id]) scn.params[b.id] = captured.overrides;
      propagateLaneStates(prev, n);
      return n;
    });
    return true;
  };
  const findVolumeRef = () => findRefBy(b => b.type === 'volume');
  const refOfBlockId = id => findRefBy(b => b.id === id);

  // pédales d'EXPRESSION : EXP1 puis EXP2, icône = le BLOC piloté (retour UX 2026-07-20).
  // TOUJOURS visibles — y compris en mode looper (retour 2026-07-20).
  const expChips = () => {
    const roles = ((rig && rig.state) || {}).pedals || { volume: 'exp1', block: 'exp2' };
    const tgtBlock = ourBlocks().find(b => b && b.id === (p.exp2 || {}).block);
    const chip = pedal => {
      const n = pedal === 'exp1' ? 1 : 2;
      if (roles.volume === pedal) {
        const ref = findVolumeRef();
        return html`<span class="ss exp" style="--tc:#8a7d1e" title="volume expression pedal — drives the Volume block (tap = open it) · role in Settings ▸ Pedalboard ▸ Expression roles"
          onClick=${() => ref && setSel(ref)}><i class="ss-ic">${fxIcon('volume')}</i><b>EXP${n}</b><em>Volume</em></span>`;
      }
      const type = tgtBlock ? tgtBlock.type : 'whammy-dt';
      const lbl = tgtBlock ? fxShort(tgtBlock.type) : ((rig && rig.state && rig.state.exp2_target) || 'Whammy');
      return html`<span class="ss exp" style="--tc:#123f63" title=${'block expression pedal — ' + lbl + ' (assign from a knob’s EXP chip in any block sheet)'}
        onClick=${() => tgtBlock && setSel(refOfBlockId(tgtBlock.id))}><i class="ss-ic">${fxIcon(type)}</i><b>EXP${n}</b><em>${esc(lbl)}</em></span>`;
    };
    return html`${chip('exp1')}${chip('exp2')}`;
  };
  // ⚠ LE LOOPER PREND TOUTE LA RANGÉE HAUTE, et les assignations faites là RESTENT dans le
  // preset sans plus jamais répondre. La bande montrait le looper à la place des stomps — donc
  // l'assignation devenait INVISIBLE, et rien ne disait qu'elle était devenue inerte. Vécu sur
  // « ZZ Conflict » : wah en SW6, whammy en SW7, un bloc looper dans le preset, et les deux
  // pédales muettes au pied sans un mot nulle part. On compte ce qui est éclipsé, et on le dit.
  // Amendement du 2026-10-14 : le looper possède SES boucles (1-4, la table du bloc), SW 5 et SW 10 — plus 6-8,
  // redevenus des stomps (le « 3 eclipsed » de Loop Station était faux le jour même).
  const loopOwned = () => [...looperRows().map(r => r.sw), 5, 10];
  const eclipsed = () => [1, 2, 3, 4, 5, ...FCB_SW].filter(n => loopOwned().includes(n) && switchBlocks(n).length);
  // Le pédalier s'assigne sur /live depuis le 2026-09-16 (app/live-assign.js + app/pedalboard-model.js) :
  // la grille de Live EST le pédalier. Le Designer garde `allBlocksOf`, dont la feuille des scènes a
  // besoin pour libérer un switch.
  const allBlocksOf = x => [...(x.lanes || []).flatMap(L => laneBlocks(L)),
    ...['gen', 'rec', 'arr'].flatMap(k => (((x.config || {})[k] || {}).blocks) || [])].filter(b => b && typeof b === 'object');
  // Preset LOOPER (2026-10-14) : les boucles (1-4), « tout » (5) et « effacer » (10) sont TOUJOURS les mêmes, un
  // switch libre ne dit rien — la bande ne garde que ce qui CHANGE d'un preset à l'autre : les effets posés sur 6-9.
  // Le reste se lit sur le mini-pédalier de la ligne de scène (tap = la carte complète).
  const stompStrip = () => looperMode()
    ? html`<div class="stomp-strip" title="looper preset — loops on 1-4, play all on 5, clear all on 10 (see the footswitch map) · the effects you put on 6-9">
        ${[6, 7, 8, 9].map(n => { const bs = switchBlocks(n); const b0 = bs[0] && bs[0][0];
          if (!bs.length) return '';
          return html`<span class="ss" style=${'--tc:' + blkColor(b0.type)}>
            <i class="ss-ic">${fxIcon(b0.type)}</i><b>${n}</b><em>${esc(bs.length === 1 ? fxShort(b0.type) : bs.length + ' fx')}</em></span>`; })}
        ${eclipsed().length ? html`<span class="ss ss-warn"
          title=${`Still assigned to ${eclipsed().map(n => '#' + n).join(', ')}, but the looper owns `
            + `these switches: they will NOT respond at the foot. Move the block, or remove that loop.`}
          ><i class="ss-ic">⚠</i><b>${eclipsed().length}</b><em>eclipsed</em></span>` : ''}
        ${expChips()}
      </div>`
    : html`<div class="stomp-strip" title="footswitch stomps (6–10) — assign them from a block's drawer, or on the Live page">
    ${FCB_SW.map(n => { const bs = switchBlocks(n); const b0 = bs[0] && bs[0][0];
      const lbl = bs.length === 0 ? 'free' : bs.length === 1 ? fxShort(b0.type) : bs.length + ' fx';
      return html`<span class=${cls('ss', !bs.length && 'free')} style=${b0 ? '--tc:' + blkColor(b0.type) : ''}>
        <i class="ss-ic">${b0 ? fxIcon(b0.type) : '·'}</i><b>${n}</b><em>${esc(lbl)}</em></span>`; })}
    ${expChips()}
  </div>`;
  // bank FCB du preset courant (pill à côté du BPM)
  const bankSlots = (banksData && banksData.presets) || [];
  const myBank = isBlank() ? -1 : bankSlots.indexOf(p.id);
  const bankSetlist = (banksData && banksData.name) || 'the foot list';   // la setlist où la pill écrit
  // `sl` = une AUTRE setlist de morceaux choisie dans la feuille (null = la liste au pied) : on écrit par la
  // route des setlists, jamais par /api/foot-list — qui écrit toujours la liste au pied (setlists.md §0)
  // ── RANGER LA CHANSON, PAS LE PRESET SEUL (2026-10-08) : une bank est une LIGNE, qui porte un preset seul ou
  // une CHANSON (qui apporte son preset, son arrangement, ses stems). Un preset qui appartient à une chanson est rangé
  // AVEC elle (POST …/place-song) — sinon la bank perdait l'arrangement (vécu sur Paper Kite). Plusieurs chansons :
  // on demande laquelle ; aucune : le preset seul, comme avant.
  const assignBank = async (slot, sl, forcePreset) => {
    if (!forcePreset) {
      const all = await fetch('/api/songs').then(r => r.json()).catch(() => null);
      const mine = (((all || {}).songs) || []).filter(x => ((x.sheet || {}).preset) === p.id);
      if (mine.length > 1) { setSongPick({ slot, sl, songs: mine }); return; }
      if (mine.length === 1) return placeSong(slot, sl, mine[0]);
    }
    const n = [...(sl ? (sl.presets || []) : bankSlots)]; while (n.length <= slot) n.push('');
    const old = n.indexOf(p.id); if (old >= 0) n[old] = '';
    n[slot] = p.id;
    try {
      if (sl) await post('/api/setlists/' + encodeURIComponent(sl.id) + '/presets', { presets: n });
      else await post('/api/foot-list', { presets: n });
    } catch (e) { flash('✗ ' + ((e.body && e.body.error) || e.message)); return; }
    setBankPick(false); reloadBanks(); reloadLists();
    flash(sl ? `✓ #${bankNo(slot)} in « ${sl.name || sl.id} »` : '✓ bank ' + bankNo(slot));
  };
  // glisser-déposer : deux banks ÉCHANGENT leur place (POST /api/setlists/<id>/swap) ; rend la setlist pour la grille
  const swapBanks = async (from, to, sl) => {
    const sid = sl ? sl.id : (banksData && banksData.id);
    if (!sid) return null;
    let r;
    try { r = await post('/api/setlists/' + encodeURIComponent(sid) + '/swap', { from, to }); }
    catch (e) { flash('✗ ' + ((e.body && e.body.error) || e.message)); return null; }
    reloadBanks(); reloadLists();
    flash('✓ banks ' + bankNo(from) + ' ⇄ ' + bankNo(to));
    return r;
  };
  // « Set as current » : cette setlist devient celle du pédalier et de /live (POST /api/setlists/<id>/activate)
  const setCurrentList = async sl => {
    try { await post('/api/setlists/' + encodeURIComponent(sl.id) + '/activate', {}); }
    catch (e) { flash('✗ ' + ((e.body && e.body.error) || e.message)); return; }
    reloadBanks(); reloadLists();
    flash('✓ « ' + (sl.name || sl.id) + ' » is the current setlist — pedalboard & Live');
  };
  const placeSong = async (slot, sl, song) => {
    const sid = sl ? sl.id : (banksData && banksData.id);
    if (!sid) return;
    try { await post('/api/setlists/' + encodeURIComponent(sid) + '/place-song', { song: song.id, slot }); }
    catch (e) { flash('✗ ' + ((e.body && e.body.error) || e.message)); return; }
    setSongPick(null); setBankPick(false); reloadBanks(); reloadLists();
    flash('✓ ♪ « ' + (song.title || song.id) + ' » on bank ' + bankNo(slot) + (sl ? ' of « ' + (sl.name || sl.id) + ' »' : ''));
  };
  // ✕ VIDER UNE BANK : la ligne part, son rang reste (DELETE …/line/<id>?keep_slot=1) — les suivantes ne bougent pas
  const removeBank = async (slot, sl, ln) => {
    const sid = sl ? sl.id : (banksData && banksData.id);
    if (!sid || !ln || !ln.id) return;
    // ⚠ UNE BANK QUI PORTE UNE CHANSON (vécu le 2026-10-08) : la vider retire la CHANSON de la setlist — arrangement,
    // stems, cases « When the song starts » — et remettre le preset ensuite ne la ramène pas (la ligne neuve ne porte
    // que le preset). On le dit AVANT.
    if (ln.band_song && !window.confirm(`Bank ${bankNo(slot)} plays the song « ${ln.title || 'this song'} » (arrangement, stems). Emptying it takes the song out of this setlist — putting the preset back will NOT bring the song back (add it again from Songs). The song itself is kept. Empty it?`)) return;
    try { await api('/api/setlists/' + encodeURIComponent(sid) + '/line/' + encodeURIComponent(ln.id) + '?keep_slot=1', { method: 'DELETE' }); }
    catch (e) { flash('✗ ' + ((e.body && e.body.error) || e.message)); return; }
    reloadBanks(); reloadLists();
    flash('✓ bank ' + bankNo(slot) + ' emptied');
  };
  // les AUTRES setlists de morceaux qui portent ce preset : le « +2 » de la pastille
  const alsoIn = isBlank() ? [] : (((listsData || {}).setlists) || [])
    .filter(sl => sl.kind !== 'sounds' && sl.id !== (banksData && banksData.id) && (sl.presets || []).includes(p.id));

  return html`
    <div class="designer">
      ${glancePop()}
      ${winWatch && winWatch.mode === 'view' ? html`<${PluginView} blockId=${winWatch.blockId} title=${winWatch.title || 'Vital'}
        w=${winWatch.w} h=${winWatch.h} saving=${winWatch.closing} onDone=${closeVitalView} />` : ''}
      ${songPick ? html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && setSongPick(null)}>
        <div class="detail-card bp-songs">
          <button class="close" onClick=${() => setSongPick(null)}>×</button>
          <h2>Which song goes on bank ${bankNo(songPick.slot)}?</h2>
          <p class="muted">« ${esc(docTitle())} » is the sound of several songs. A bank plays a song: its arrangement and stems come with it.</p>
          <div class="bp-songlist">
            ${songPick.songs.map(x => html`<button class="row-btn" onClick=${() => placeSong(songPick.slot, songPick.sl, x)}>
              ♪ ${esc(x.title || x.id)}${x.artist ? html` <small class="muted">${esc(x.artist)}</small>` : ''}</button>`)}
            <button class="row-btn" onClick=${() => { const sp = songPick; setSongPick(null); assignBank(sp.slot, sp.sl, true); }}>
              the preset alone <small class="muted">— no arrangement, no stems</small></button>
          </div>
        </div></div>` : ''}
      ${conflict ? html`<div class="dsn-arrived dsn-conflict"><span>⚠ This draft was changed on ${esc(conflict.by || 'another screen')} — this screen stopped playing and saving it.</span>
        <button class="mini primary" onClick=${loadNewer}>Load the newer draft</button>
        <button class="mini" onClick=${keepMine} title="replace the other screen's draft with this one">Keep mine</button></div>` : ''}
      ${audErr ? html`<div class="dsn-arrived dsn-conflict dsn-auderr"><span>⚠ The rig refused this draft — it is not playing: <b>${esc(audErr)}</b></span>
        <button class="mini dsn-arr-x" title="hide — it comes back with the next refused change" onClick=${() => setAudErr(null)}>×</button></div>` : ''}
      ${arrived ? html`<div class="dsn-arrived"><span>✨ A patch arrived from golem.fm and is playing — your previous draft is kept.</span>
        <button class="mini primary" onClick=${() => openArrived(false)}>Open it</button>
        <button class="mini" onClick=${() => openArrived(true)}>Restore my draft</button>
        ${/* la sortie : ni ouvrir ni restaurer, juste « j'ai vu ». Sans elle la bannière ne se
             taisait qu'en sauvant — et revenait au rechargement (retour 2026-09-11). */''}
        <button class="mini dsn-arr-x" title="dismiss — the patch keeps playing" onClick=${closeArrived}>×</button></div>` : ''}
      ${bsHide !== bsig ? html`<${MissingBanner} sum=${bsSum} fetching=${bsFetch}
        onDownloadAll=${() => bsDownload(null)} onClose=${() => setBsHide(bsig)} />` : ''}
      ${locked ? html`<div class="lock-scrim">
        <div class="lock-card">
          <span class="lock-ic">🔒</span>
          <b>Live lock is on</b>
          <p class="muted">Editing here would re-audition the draft and replace the stage sound.
            Unlock from the Live page — or here if you know what you're doing.</p>
          <button class="chip" onClick=${() => post('/api/live-lock', { on: false })}>🔓 Unlock editing</button>
        </div>
      </div>` : ''}
      <div class="grid-wrap">
        <div class="rig" data-doc="designer.rig">
          <div class=${cls('sys-tabs sub-tabs in-tabs', !patchMode && lanes.length >= 4 && 'dense')} data-doc="designer.lanes">
            ${/* ≥ 4 lanes (2026-09-09, 7 onglets en Rehearsal) : le nom SUR l'entrée, en deux lignes
                  nettes — sur une ligne les libellés se coupaient au retour à la ligne */''}
            ${/* LOT 3 : un onglet PAR LANE, généré depuis la liste — nom de la lane, entrée en petit */''}
            <${LaneTabs} lanes=${lanes} patch=${patch} patchMode=${patchMode} pmTab=${pmTab} pmTitle=${pmTitle} inTab=${inTab} laneTitle=${laneTitle} onPick=${pickInTab}
              unmounted=${((rig && rig.state) || {}).rig_unmounted || []}
              folded=${drumsetsOf(lanes).filter(d => !dsFold.includes(d))} />
            ${/* UN PATCH A SON ⚙ (docs/patches.md §4) : looper, sample, grooves, pour jouer SEUL — le
                  backing et l'arrangement restent au morceau. Le Click et le Rec y sont, globaux comme partout. */''}
            ${html`<button class=${cls('sys-tab', 'cfg-tab', inTab === 'cfg' && 'on')} data-doc="designer.lane:config" onClick=${() => pickInTab('cfg')}
              title="Config — services shared across the preset (backing, looper, rec, sample, drums)">⚙</button>`}
            ${/* DEUX ONGLETS DE MOINS (2026-09-16, maquette « Designer allégé ») : le pédalier vit
                  sur /live (sa grille EST le pédalier) et le dictionnaire des scènes s'ouvre en feuille
                  par le ▦ des puces de scènes. Le Designer redevient l'établi du son : des lanes et ⚙. */''}
            ${/* Plus d'onglet ▤ : l'arrangement vit sur la LIGNE de setlist (2026-09-08,
                  arrangement.md §4) — un preset peut servir trois chansons de structures
                  différentes. Il s'édite dans Songs ▸ Setlists, détail de ligne. */''}
            ${/* La pill NOMME sa cible (2026-07-28) : assigner une bank écrit dans la setlist
                  ACTIVE — donc dans le set qu'on jouera ce soir. « #03 » tout seul ne disait pas
                  dans quoi. Et quand le preset n'y est pas, on propose de l'AJOUTER plutôt que
                  d'afficher « no bank », qui n'appelait aucune action. */''}
            ${/* une BANK DE SONS au pied (patch-as-preset §7) ne prend pas de morceau : pas de pastille */''}
            ${patchMode || (banksData && banksData.kind === 'sounds') ? '' : html`<button class=${cls('bank-pill', myBank >= 0 && 'on')} data-doc="designer.bank"
              title=${(myBank >= 0 ? 'bank ' + bankNo(myBank) + ' of « ' + bankSetlist + ' » — tap to move'
                                   : 'add this preset to « ' + bankSetlist + ' », the setlist on the foot')
                     + (alsoIn.length ? ' · also in ' + alsoIn.map(x => '« ' + (x.name || x.id) + ' »').join(', ') : '')}
              onClick=${() => { if (isBlank()) { flash('name & save the preset first'); return; } setBankPick(true); }}>
              🎹 ${myBank >= 0 ? '#' + bankNo(myBank) : '+ add'}<small>${esc(bankSetlist)}</small>
              ${alsoIn.length ? html`<em class="bank-also">+${alsoIn.length}</em>` : ''}</button>`}
            ${/* En mode PATCH le tempo n'est PAS enregistré (un patch n'a pas de bpm — c'est le
                  morceau qui l'apporte). Il ne sert qu'à ÉPROUVER les blocs synchronisés : delay,
                  delay-tape. Le libellé le dit, plutôt que de laisser croire à une propriété du
                  patch. Aligné à droite : ce n'est pas une propriété, c'est un réglage de banc. */''}
            ${/* LE NOM DE LA SCÈNE COURANTE, en clair — comme l'en-tête du panneau droit de la page
                  Presets (2026-09-08 : « prends exemple sur /songs/presets »). L'onglet de la
                  topbar reste une lettre ; tap = la feuille de scène (renommer, niveau). */''}
            ${sc ? html`<button class="scene-cap" data-doc="designer.scene-name" title="scene ${sc.id} — tap to rename or set its level"
              onClick=${() => setSceneSheet(true)}><b>${sc.id}</b><span>${esc(sc.name || 'scene ' + sc.id)}</span></button>` : ''}
            ${/* LE MINI-PÉDALIER (proposition 3) — sur cette ligne, à droite du nom de la scène, hors de la barre du haut
                  (2026-10-08) : la forme du FCB, 6-10 en haut, 1-5 en bas ; bleu = scène, couleur de catégorie =
                  bloc spécial, gris = effet, pointillé = libre. Un tap = la carte des switches en clair. */''}
            ${patchMode ? '' : html`<button class=${cls('pg-map', glance && glance.kind === 'map' && 'on')} data-doc="designer.foot" title="what each footswitch does — tap for the detail"
              onClick=${e => openGlance('map', e)}>
              ${[6, 7, 8, 9, 10, 1, 2, 3, 4, 5].map(n => { const c = swMap()[n - 1];
                return html`<i style=${c.color ? '--c:' + c.color : ''} class=${cls(!c.color && 'free')}>${c.short}</i>`; })}
            </button>`}
            ${patchMode ? '' : html`<${SongBar} ctx=${songCtx} />`}
            <label class=${cls('bpm-set', patchMode && 'pm-bpm')} data-doc="designer.bpm"
              title=${patchMode ? 'the tempo when this patch plays on its own (BPM-synced delays, looper, grooves). Dropped into a song, the song\'s tempo wins.'
                                : 'preset tempo (BPM)'}>${patchMode ? html`BPM<small>when alone</small>` : 'BPM'}
              <div class="bpm-field">
                <input type="number" min="20" max="300" value=${p.bpm || 120}
                  onInput=${e => upd(n => { n.bpm = Math.max(20, Math.min(300, +e.target.value || 120)); })} />
                ${/* ▼ À GAUCHE, ▲ À DROITE, chacun la hauteur du champ (2026-10-27, tools/check-use.py) : empilés, ils
                     faisaient 15×14 px — une cible qu'un doigt manque sur un écran de rack */''}
                <button class="bpm-step dn" tabindex="-1" title="−1" onClick=${() => upd(n => { n.bpm = Math.max(20, (n.bpm || 120) - 1); })}>▼</button>
                <button class="bpm-step up" tabindex="-1" title="+1" onClick=${() => upd(n => { n.bpm = Math.min(300, (n.bpm || 120) + 1); })}>▲</button>
              </div>
            </label>
          </div>
          ${scnSheet && !patchMode ? html`<div class="sheet-scrim scn-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && setScnSheet(false)}>
            <div class="rig-sec scn sheet-scn" data-doc="designer.scenes-sheet">
            <div class="scn-sheet-hd"><span class="arrsh-ic">▦</span><b>Scenes & sounds · ${esc(p.name || 'this preset')}</b>
              <span class="muted scn-sub">name the sound each instrument plays in each scene — it shows on Live, on the musicians' phones and in the arrangement</span>
              <span class="grow"></span>
              <button class="mini" onClick=${() => setScnSheet(false)}>✕</button></div>
            <${SceneDictionary} p=${p} lanes=${lanes} sceneIdx=${scene} laneTitle=${laneTitle}
              inTagOf=${L => L.midi ? 'USB ' + (((String(L.in_sel || 'usb1').match(/usb(\d)/)) || [])[1] || 1) : L.in_sel === 'NONE' ? 'IN —' : 'IN ' + L.in_sel}
              claimOf=${n => { const bs = switchBlocks(n); return bs.length ? bs.map(([b]) => fxShort(b.type)).join(' + ') : null; }}
              levelOf=${(sc2, id) => sceneLevelOf(sc2, id)}
              onPickScene=${i => setScene(i)}
              onAssign=${(lid, si, stid) => upd(n => { assignLaneState(n, lid, si, stid); })}
              onNewState=${(lid, si, name) => upd(n => { newLaneState(n, lid, si, name); })}
              onRename=${(lid, stid, name) => upd(n => { renameLaneState(n, lid, stid, name); })}
              onLevel=${(lid, si, v) => upd(n => { ensureLaneStates(n); const s2 = n.scenes[si]; s2.lanes = s2.lanes || {}; s2.lanes[lid] = { ...(s2.lanes[lid] || {}), level: v };
                if (lid === 'guitar') { s2.levels = s2.levels || {}; s2.levels.guitar = v; } })}
              onMute=${(lid, si, on) => upd(n => { ensureLaneStates(n);   // une coupure SANS `state` se lirait comme un ancien mute de branche
                const s2 = n.scenes[si]; s2.lanes = s2.lanes || {}; const e = { ...(s2.lanes[lid] || {}) };
                if (on) e.mute = true; else delete e.mute; s2.lanes[lid] = e; })}
              onOpenLane=${(lid, si) => { setScene(si); pickInTab(lid); }}
              onAddScene=${() => newScene()} onPedalboard=${null} />
            </div>
          </div>`
          : ''}
          ${/* LE PÉDALIER A DÉMÉNAGÉ SUR /live (2026-09-16) : sa grille EST le pédalier, pavé par
                pavé, et on assigne là où on voit la pédale. L'assignation d'un bloc reste dans son
                tiroir (onglet MIDI assign) ; l'onglet ▤ du Designer, lui, n'existe plus. */''}
          ${/* L'EN-TÊTE DU GROUPE DE BATTERIE (docs/drums-kit.md §6.6) : replié, un kit est UN
                instrument — nom du module, nombre d'entrées, et ses éléments en pastilles pour
                passer de la caisse claire au charleston sans quitter l'écran. « ▾ Show elements »
                rend à chaque élément son onglet : une lane d'élément est une lane comme les autres. */''}
          ${curDs ? html`<${DrumsetHead} ds=${curDs} lanes=${curDsLanes}
            moduleName=${((((dsKits || {}).kits) || []).find(k => k.id === (curLane || {}).drumset_module) || {}).name}
            who=${(curLane || {}).person_name} open=${dsFold.includes(curDs)} curId=${inTab}
            onToggle=${() => setDsFold(f => f.includes(curDs) ? f.filter(x => x !== curDs) : [...f, curDs])}
            onPick=${pickInTab} />` : ''}
          ${curLane ? html`<div class=${cls('rig-sec', curLane.role === 'voice' && 'voice', curLane.midi && 'keys', gDisabled && 'off', curDs && 'in-ds')} data-doc="designer.chain">
            <div class="rig-lbl-row">
              ${/* le label répétait l'onglet (retour 2026-07-31) : le chip ⛓ prend sa
                    place à gauche ; la lane se renomme, change d'instrument et se retire ici (lot 3) */''}
              ${LanePatchChip(curLane.id)}
              ${gDisabled ? html`<small class="muted lane-off">· off (IN/OUT NONE)</small>` : ''}
              ${curLane && laneWaitsCard(curLane) ? html`<small class="lane-off waits" title="the lane is prepared on the mode's card — it mounts when that card is connected">⏳ ${esc(modeCard)} not connected</small>`
                : curLane && laneOffCard(curLane) ? html`<small class="lane-off warn">⚠ not mounted — IN ${curLane.in_sel} is not on this card, pick another input</small>` : ''}
              ${stompStrip()}
            </div>
            ${dview === 'pedals' && !curLane.midi ? html`<${PedalView} lane=${curLane.id} chain=${curLane.chain} catalog=${effects}
                sceneState=${pedalState(curLane)} values=${pedalVals(curLane)}
                onToggle=${ref => { const b = blockAt(p, ref); if (!b) return;
                  fxDef(b.type).scene_invariant ? toggleBypass(ref) : setSceneBlock(ref, !blockOn(b)); }}
                onOpen=${ref => { const b = blockAt(p, ref); if (!b) return; setSelTab('params');
                  needsModel(b.type) && !b.ref ? setPickAmp(ref) : setSel(ref); }}
                onBranch=${brId => setSceneLane(brId, laneMuted(brId))} />`
            : html`<${GridChain} head=${gHead} zone=${gZone} tail=${gTail} meta=${gMeta}
              out=${(!gZone || isMerge) ? OutPill('out:' + curLane.id, curLane.out_sel, s => setOut(curLane.id, s)) : null} />`}
          </div>` : html`<div class="rig-sec config">
            <div class="cfg-lane">
              <div class="cfg-lane-hd"><b>Players</b><small>${patchMode ? 'looper · sample · drums — to play this patch on its own' : 'backing · looper · sample · drums — mixed into the output'}</small></div>
              <${GridChain} head=${[
                html`<div class="io-pill in cfg fixed" title="capture source for the looper — the post-chain mix">▶ IN<br/><b>Mix</b></div>`,
                ...visTiles(genBlocks, i => ({ cg: i })),
                { edge: !genBlocks.length,   // lane vide : le ＋ colle à la pastille IN, pas à une tuile
                  plus: html`<button class="gc-addbtn" onClick=${() => setDrawer({ config: 'gen' })}
                    title="add a player — backing / looper / sample / drums">＋</button>` },
              ]} out=${OutPill('cfg', cfgOutSel, setCfgOut)} cols=${CFG_COLS} />
            </div>
            <!-- UNE SEULE LANE « GLOBAL » POUR LE CLICK ET LE REC (2026-09-16) : ce sont les deux
                 blocs dont les réglages sont partagés par TOUS les presets — seule l'assignation au pied
                 est locale. Ils gardent deux rangées, pas un split : le click est un GÉNÉRATEUR (son
                 entrée est le tempo) et le rec un CAPTEUR (un puits, sans sortie) — les fondre en une
                 seule chaîne laisserait croire qu'un même signal alimente les deux (retour 2026-07-25,
                 toujours vrai). Ce qu'on gagne, c'est un en-tête : quatre lanes tenaient dans l'écran à
                 14 px près, et le prochain bloc de service n'aurait plus eu de place. -->
            <div class="cfg-lane">
              <div class="cfg-lane-hd"><b>Global</b><small
                title="Click, recorder and Riff: their settings are shared by every preset (level, beats/bar, tap point, recording mode, what Riff keeps). What stays per preset: the BPM the click follows, whether it plays (Settings ▸ Mode), and the footswitch of each block.">🌐
                every preset · click, recorder and riff — only the foot is per preset</small></div>
              <${GridChain} head=${[
                html`<div class="io-pill in cfg fixed bpm" title="tempo of this preset — change it with the BPM field in the header">♩ BPM<br/><b>${p.bpm || 120}</b></div>`,
                ...visTiles(recBlocks.filter(b => b && b.type === 'click'),
                            () => ({ cr: recBlocks.findIndex(b => b && b.type === 'click') })),
              ]} out=${OutPill('clickout', clickOutSel, setClickOut)} cols=${CFG_COLS} />
              <${GridChain} head=${[
                html`<div class="io-pill in cfg fixed" title="what the recorder captures — pick the inputs and the recording mode in the Rec block's drawer">▶ IN<br/><b>${recModeLabel(recCfg && recCfg.mode)}</b></div>`,
                // COMPO à côté du REC (2026-09-17, docs/compo.md §2) : deux CAPTEURS sur la même
                // rangée — l'écran (1024×600, sans scroll) n'a pas la place d'une quatrième rangée.
                ...visTiles(recBlocks.filter(b => b && (b.type === 'rec' || b.type === 'compo')),
                            (_i, b) => ({ cr: recBlocks.indexOf(b) })),
              ]} out=${DiskPill()} cols=${CFG_COLS} />
            </div>
            <!-- ARRANGEMENT (docs/arrangement.md §7, version B du 2026-09-16) : sa propre lane, juste après
                 Global — un PANNEAU (setlist, chanson, pédale, avance, frise), pas une chaîne : le bloc n'a ni
                 entrée ni sortie audio. Le panneau EST le bloc ; le bloc se crée au premier geste. -->
            ${patchMode ? '' : html`<${ArrangementLane} preset=${p} block=${arrBlocks.find(b => b && b.type === 'arrangement') || null}
              automation=${arrAuto} drives=${arrCtl.size} onAutomation=${toggleAutomation}
              loneLoad=${!!arrRow && ((rig || {}).state || {}).preset_id === p.id && !(((rig || {}).state || {}).song || {}).line && !(((rig || {}).state || {}).song || {}).band_song}
              setlists=${setlistsD} pick=${arrPickEff} onPick=${setArrPick}
              onOpen=${() => openArrangement('params')} onSwitch=${() => openArrangement('assign')}
              onAdvance=${v => { addArrangement(); upd(x => { const b = (x.config.arr.blocks || []).find(k => k && k.type === 'arrangement'); if (b) b.params = { ...(b.params || {}), advance: v }; }); }}
              songs=${(songCtx.used || {}).songs || []} />`}

          </div>`}
        </div>

      </div>

      ${sel && selBlock ? (() => {
        const allB = footBlocks().map(([b, k]) => ({ id: b.id, type: b.type, foot: b.foot, in: k }));
        const exp = p.exp2 || null, expOn = !!(exp && exp.block === selBlock.id);
        const expLabel = exp ? fxShort((ourBlocks().find(b => b && b.id === exp.block) || {}).type || exp.param) : null;
        // le potard que le bloc DÉCLARE pour la pédale (pm.exp) d'abord, sinon le premier continu
        const knobs = (fxDef(selBlock.type).params || []).filter(x => x.type !== 'enum' && x.type !== 'bool');
        const pmA = knobs.find(x => x.exp) || knobs[0];
        const assignProps = { blocks: allB, scenes: p.scenes, sceneIdx: scene,
          sceneClaim: !!fxDef(selBlock.type).foot_scene_claim,
          transport: fxDef(selBlock.type).foot_mode === 'transport',
          transportLoops: ((looperBlock() || {}).params || {}).loops,
          transportLanes: loopLanes(),
          expOn, expLabel, canExp: !!pmA, fxName, fxShort,
          pedals: (rig && rig.state && rig.state.pedals) || undefined,
          onSwitch: nn => upd(x => { const b = blockAt(x, sel); if (nn) b.foot = nn; else delete b.foot; }),
          // « voir tout le pédalier » : c'est /live désormais (2026-09-16) — la grille y est déjà,
          // et on n'assigne pas sur un plan quand on peut assigner sur l'objet
          onBoard: null,
          onExp: () => pmA && upd(x => { const b = blockAt(x, sel); const cur = x.exp2;
            x.exp2 = (cur && cur.block === b.id) ? null : { block: b.id, param: pmA.id, min: pmA.min, max: pmA.max }; }) };
        // ── LE BLOC ARRANGEMENT A SON PROPRE TIROIR (2026-09-16) : il n'a pas de potards, il a une
        //    CHANSON. Les parties partent dans la ligne de setlist, la pédale dans le preset.
        if (selBlock.type === 'arrangement') {
          // ⚠ `transport=${true}` + `sceneClaim=${false}` (codés en dur depuis db089c1, 2026-09-17) : l'onglet MIDI
          // assign montrait la grille du LOOPER et interdisait la rangée 1-5 — l'arrangement ne pouvait JAMAIS être
          // posé au pied depuis le Designer (2026-10-01 : « je ne peux pas l'assigner »). Il se pose sur UN
          // switch, rangée des scènes comprise (catalogue : foot_scene_claim).
          return html`<${ArrangementSheet} block=${selBlock} preset=${p} presetId=${p.id} presetName=${p.name}
            fx=${fx} fxIcon=${fxIcon} fxName=${fxName} fxShort=${fxShort} imap=${patch}
            scenes=${p.scenes} sceneIdx=${scene} pedals=${assignProps.pedals} blocks=${allB}
            sceneClaim=${!!fxDef('arrangement').foot_scene_claim} transport=${false} transportLoops=${assignProps.transportLoops}
            transportLanes=${assignProps.transportLanes}
            tab=${selTab} onTab=${setSelTab}
            onFoot=${assignProps.onSwitch}
            onAdvance=${v => upd(x => { const b = blockAt(x, sel); b.params = { ...(b.params || {}), advance: v }; })}
            onRemove=${() => { upd(x => { x.config.arr.blocks = (x.config.arr.blocks || []).filter(b => b !== blockAt(x, sel)); }); setSel(null); }}
            pick=${arrPickEff} onPick=${setArrPick} songCtx=${songCtx}
            onNewScene=${(i, arr, saveArr) => newSceneForPart(i, arr, saveArr)}
            onScenes=${() => { setSel(null); setScnSheet(true); }}
            onClose=${() => setSel(null)} />`;
        }
        if (selBlock.type === 'vst-host') return html`<${VstHostSheet} block=${selBlock}
          patchName=${String(p.name || p.id || 'Patch').replace(/^\W+\s*/, '')}
          onReplace=${(blocks, dest, name) => {
            refreshCatalog(); reloadCatalog();
            return dest === 'new' ? forkWithBlocks(sel, blocks, name) : replaceBlock(sel, blocks);
          }}
          sceneId=${sc.id} sceneOff=${sceneOff(selBlock)} ovr=${(sc.params && sc.params[selBlock.id]) || {}}
          powerOn=${blockOn(selBlock)} onPower=${on => setPower(sel, on)} multiScene=${multiScene}
          onParam=${(index, initial, value) => setHostParam(sel, index, initial, value)}
          onCapture=${params => upd(n => { const b = blockAt(n, sel); if (!b?.id) return;
            b.params = { ...(b.params || {}) };
            params.forEach(pm => { b.params['p' + pm.i] = pm.value; });
          })}
          onNativeState=${state => applyHostState(selBlock.id, sc.id, state)}
          captureOk=${!!(effects && effects.vst_capture)}
          inApp=${!!(winAvail && winAvail.mode === 'view')}
          onKnobs=${(list, remember) => {
            upd(n => { const b = blockAt(n, sel); if (!b?.id) return;
              if (list.length) b.knobs = list; else delete b.knobs;
              // la pédale qui pilotait un potard retiré ne pilote plus rien
              if (n.exp2 && n.exp2.block === b.id && !list.some(k => 'p' + k.i === n.exp2.param)) n.exp2 = null; });
            if (remember && selBlock.plugin) post('/api/vst-host/knobs', { plugin: selBlock.plugin, knobs: list }).catch(() => {});
          }}
          exp2=${p.exp2} expN=${(((rig && rig.state && rig.state.pedals) || {}).volume) === 'exp2' ? 1 : 2}
          onExp=${k => upd(n => { const cur = n.exp2, key = 'p' + k.i;
            n.exp2 = (cur && cur.block === selBlock.id && cur.param === key) ? null
                   : { block: selBlock.id, param: key, min: 0, max: 1 }; })}
          onApplyAll=${() => applyParamsAllScenes(sel)}
          onBypass=${() => toggleBypass(sel)} onScene=${on => setSceneBlock(sel, on)}
          onMove=${d => move(sel, d)} onRemove=${() => rmBlock(sel)}
          onOpen=${() => openVst(selBlock.id)}
          onClose=${() => setSel(null)} />`;
        return html`<${ParamSheet} block=${vcapOrigin(selBlock) ? { ...selBlock, origin: vcapOrigin(selBlock) } : selBlock} def=${fxDef(selBlock.type)}
        onRename=${name => upd(n => { const b = blockAt(n, sel); if (b && name) b.label = name.slice(0, 60); })}
        onCaptureFoot=${(id, sw) => upd(n => {
          const b = blockAt(n, sel); if (!b) return;
          b.capture_foot = { ...(b.capture_foot || {}) };
          if (sw) b.capture_foot[id] = sw; else delete b.capture_foot[id];
        })}
        tones=${(catalog && catalog.tones) || []}
        tab=${selTab} onTab=${setSelTab} assign=${assignProps}
        svc=${{ songCtx, setlists: setlistsD,             // la chanson chargée : ses valeurs à côté de celles du preset
                preset: p,                                // le tiroir Backing calcule ce que CE preset joue (brouillon compris)
                songs: ((p.backing || {}).songs) || [],
                onSongs: songs => upd(n => { if (songs.length) n.backing = { songs }; else delete n.backing; }),
                recSrc: recCfg ? { ...recCfg, rec_mode: recCfg.mode } : null,
                // la fenêtre de Vital (2026-10-14) : seulement sur l'écran de la machine, sous Windows / macOS
                vitalWindow: selBlock.type === 'vital' ? (cur => openPluginWindow(selBlock.id, cur)) : null,
                // grisé ailleurs que sur l'écran d'un golem Windows / macOS : le tiroir dit pourquoi au tap
                vitalWindowWhy: winAvail && winAvail.available ? '' : ((winAvail && winAvail.why) || 'Vital’s window is not available here'),
                vitalWindowOpen: !!(winWatch && winWatch.blockId === selBlock.id),
                recInputs: (patch.inputs || []).filter(e => e.role && e.role !== 'none'),   // une case REC par entrée de la carte
                onRecSrc: setRecCfg,
                // COMPO (docs/compo.md §4) : les personnes de la carte du mode et LEURS lanes dans ce
                // preset, avec les prénoms du roster ; la config vit dans block.params (singleton,
                // extraite au save comme le Rec) ; la destination est l'espace courant (miroir /api/band).
                compoPersons: lanesByPerson(p, patch),
                // LE REC DONT RIFF DÉPEND (2026-09-30, solution A) : ses réglages, lus dans le bloc Rec du
                // preset, et le chemin pour aller les régler — le tiroir Riff les montre, il ne les écrit pas
                recCfg: (((p.config || {}).rec || {}).blocks || []).find(b => b && b.type === 'rec')?.params || {},
                recAllowed: !svcVetoed(rig, 'rec'),
                modeName: ((rig || {}).mode || {}).name || ((((rig || {}).state || {}).mode) || {}).name || null,
                onOpenRec: () => { const i = (((p.config || {}).rec || {}).blocks || []).findIndex(b => b && b.type === 'rec');
                                   if (i >= 0) { setSelTab('params'); setSel({ cr: i }); } },
                personNames: Object.fromEntries([...(patch.inputs || []), ...(patch.usb || [])]
                  .filter(e => e.person).map(e => [e.person, e.person_name || e.person])),
                compoTargets: ((rig && rig.state && rig.state.compo) || {}).targets || {},
                // ── L'ESPACE DE DESTINATION DES PRISES ────────────────────────────────────
                // ⚠ CE N'EST PAS UN PARAMÈTRE DU BLOC. C'est le MIROIR de l'état du rack
                // (config/.band.json), lu et écrit par /api/band. Le graver dans le preset
                // ferait deux sources de vérité et collerait une destination à un SON — or
                // le même son sert dans deux groupes.
                // La rangée n'apparaît QUE si le rack connaît des espaces, c'est-à-dire
                // seulement après un appairage à golem.fm : un rack jamais connecté n'a pas
                // à prononcer le mot « groupe ».
                spaces: bandData.bands || [], space: bandData.band || null,
                onSpace: id => fetch('/api/band/current', { method: 'POST',
                    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) })
                  .then(loadBand).catch(() => {}),
                loopLanes: loopLanes(),
                footBlocks: footBlocks().map(([b]) => b),   // la carte du looper montre les effets posés sur 6-9
                fxShort,
                // le bloc Standard AMORCE le tempo du preset avec celui du morceau — il n'en
                // porte pas (contrat docs/standards.md §2 : preset.bpm est la seule vérité).
                onBpm: v => upd(n => { n.bpm = v; }),
                // bloc Arrangement : ses sections POINTENT vers des scènes du preset — il lui faut
                // donc la liste, et un chemin pour aller ÉDITER la scène (on ne redéfinit pas un
                // son dans une section, cf. docs/arrangement.md §3).
                scenes: p.scenes,
                onEditScene: id => { const i = (p.scenes || []).findIndex(x => (x.id || '') === id);
                                     if (i >= 0) { setScene(i); setSel(null); } } }}
        expVol=${p.exp1} onExpVol=${(min, max) => upd(n => { n.exp1 = { block: selBlock.id, param: 'gain', min, max }; })}
        ovr=${(sc.params && sc.params[selBlock.id]) || {}}
        sceneId=${sc.id} sceneOff=${sceneOff(selBlock)} fxIcon=${fxIcon} bpm=${p.bpm || 120} laneInst=${instOf(sel)}
        powerOn=${blockOn(selBlock)} onPower=${on => setPower(sel, on)} multiScene=${multiScene}
        onParam=${(pid, v) => setParam(sel, pid, v)} onBypass=${() => toggleBypass(sel)}
        onScene=${on => setSceneBlock(sel, on)} onModel=${mid => setModel(sel, mid)} onApplyAll=${() => applyParamsAllScenes(sel)}
        onLoadPreset=${ps => upd(n => { const b = blockAt(n, sel); if (!b.id) return;
          // UN PRESET EST TOUT LE SON (2026-11-13, docs/golem-fx-sheet.md §5) : sur un bloc que golem-fx joue, chaque
          // réglage repart de son défaut, puis le preset par-dessus — rien de l'état d'avant ne survit (les presets de
          // golem-fx sont complets ; un ancien preset partiel du rack sonne ainsi pareil quoi qu'il y avait avant).
          // L'IDENTITÉ du type (Plate, Room, GCB-95) est cachée : jamais écrite.
          const base = GOLEM_FX.has(b.type) ? Object.fromEntries(((fxDef(b.type) || {}).params || [])
            .filter(pm => !pm.hidden && pm.default !== undefined && pm.default !== null).map(pm => [pm.id, pm.default])) : (b.params || {});
          b.params = { ...base, ...ps };                                    // preset de bloc -> BASE
          n.scenes.forEach(s => { if (s.params) delete s.params[b.id]; }); // + purge overrides (global)
        })}
        onMove=${d => move(sel, d)} onRemove=${['rec', 'click', 'compo'].includes(selBlock.type) ? null : () => rmBlock(sel)}
        pedals=${(rig && rig.state && rig.state.pedals) || undefined}
        exp2=${p.exp2} onExp=${pm => upd(n => { const cur = n.exp2;
          n.exp2 = (cur && cur.block === selBlock.id && cur.param === pm.id) ? null
                 : { block: selBlock.id, param: pm.id, min: pm.min, max: pm.max }; })}
        onPickRef=${() => { setPickAmp(sel); setSel(null); }} onClose=${() => setSel(null)} />`; })() : ''}

      ${drawer ? (() => {
        // royaume : lane config -> services à plat. Sinon, tiroir CONTEXTUEL au rôle de l'entrée
        // (patch Soundcard) : catégories + archétypes + famille de captures par instrument.
        const isCfg = !!drawer.config;
        const cfgTypes = drawer.config === 'rec' ? CONFIG_REC_TYPES
                       : drawer.config === 'arr' ? CONFIG_ARR_TYPES
                       // le ⚙ d'un PATCH (docs/patches.md §4, amendé le 2026-09-30) : tout l'accompagnement,
                       // backing comprise — seul l'arrangement (la forme du morceau) reste au preset, et il vit ailleurs
                       : CONFIG_GEN_TYPES;
        const role = isCfg ? null : laneRole(drawer.lane || inTab);
        const dLane = lanes.find(L => L.id === (drawer.lane || inTab)) || {};
        // blocs à rôles restreints (def.roles, ex. pitch-correct/deesser = voice only) :
        // absents des tiroirs des autres rôles (rôle absent/ligne = 'guitar')
        // veto de MODE (2026-09-08) : un service coupé par le mode courant n'est pas proposé —
        // l'éditeur de mode (Settings ▸ Mode ▸ Tools / Arrangement) est la seule porte
        const dfx = (isCfg ? fx.filter(e => cfgTypes.includes(e.type) && !svcVetoed(rig, e.type))
                           : fx.filter(e => !CONFIG_SERVICE_TYPES.includes(e.type)))
          .filter(e => !e.roles || e.roles.includes(role || 'guitar'))
          // tamis fin par rôle (role_blocks, v15) : une lane batterie ne voit que les blocs d'un kit
          .filter(e => e.type === 'vst-host' || isCfg || !role || !Array.isArray(ROLE_BLOCKS[role]) || ROLE_BLOCKS[role].includes(e.type))
          // le Drum Kit est un INSTRUMENT MIDI. Sur une lane AUDIO il ne se retire pas du tiroir (une tuile
          // absente ne s'explique pas) : il y reste GRISÉ, avec son tag USB et sa raison (2026-09-18)
          .map(e => e.type === 'drumkit' && !(dLane && dLane.midi)
            ? { ...e, blocked: 'USB', why: "the rack's kits play from MIDI — switch this lane to its USB port (the ▶ IN pill). On an audio input the drum module makes the sound." }
            : e)
          // quarantaine (effects.json) : un plugin qui fait tomber Reaper n'est pas proposé (GxDetune, 2026-09-07)
          .filter(e => !e.quarantine && e.type !== 'vst-host');
        const roleCats = role ? ROLE_CATS[role] : null;                 // absent (guitar) -> toutes
        const roleArch = role ? archetypes.filter(a => (a.roles || ['guitar']).includes(role)) : [];
        return html`<${CategoryDrawer} cats=${isCfg ? cats : (roleCats || cats)} fx=${dfx} flat=${isCfg}
          pedals=${isCfg ? [] : roleArch} fam=${role ? ROLE_FAM[role] : null}
          post=${!!drawer.post} voice=${dLane.role === 'voice'} stereo=${drawer.add === 'pre' && !split && !dLane.midi} laneStereo=${!!dLane.stereo}
          present=${new Set([...laneBlocks(dLane), ...genBlocks, ...recBlocks].filter(Boolean).map(b => b.type))}
          hw=${isCfg ? [] : hwPedals}
          onAdd=${(type, tone) => { if (isCfg) addConfigBlock(type, drawer.config);
            else addBlock(type, { lane: drawer.lane || inTab, add: drawer.add || 'pre', bi: drawer.bi }, tone); }}
          onAddPedal=${(archId, tone) => { addPedal(archId, { lane: drawer.lane || inTab, add: drawer.add || 'pre', bi: drawer.bi }, tone); if (tone) reloadCatalog(); }}
          onAddHw=${pd => { const tone = { id: pd.id, title: pd.name };   // bloc midi-pedal, ref = descripteur
            addBlock('midi-pedal', { lane: drawer.lane || inTab, add: drawer.add || 'pre', bi: drawer.bi }, tone); }}
          onAddStereo=${addAmp2Cabs} vstHost=${!!(effects && effects.vst_host)}
          vstOnly=${!!drawer.replace}
          onAddVst=${name => drawer.replace
            // depuis la feuille d'un bloc qui ne joue pas ici : le plugin prend SA place (même purge que Replace)
            ? (replaceBlock(drawer.replace, [{ type: 'vst-host', plugin: name, label: name }]), setDrawer(null))
            : addBlock('vst-host', { lane: drawer.lane || inTab, add: drawer.add || 'pre', bi: drawer.bi }, null,
              { plugin: name, label: name })}
          onClose=${() => setDrawer(null)} />`;
      })() : ''}



      ${/* EN MODE PATCH, l'IA ne fabrique pas un morceau : elle remplit LA LANE de ce patch.
            « C'est là qu'il doit être »  — générer un son, c'est un geste de création de
            patch, pas de création de preset. */''}
      ${/* NAVIGATEUR DE PATCHES : volontairement plus simple que celui des presets (pas de
            banks, pas de styles, pas de scènes en aperçu) — un patch se choisit par son
            instrument et son nom. Le « ＋ New » ouvre un banc vide du MÊME rôle. */''}
      ${patchBrowse ? html`<${PatchBrowser} patches=${allPatches} patchMode=${patchMode} into=${patchBrowse && patchBrowse.into}
          role=${patchRole} setRole=${setPatchRole} q=${patchQ} setQ=${setPatchQ} laneRoleOf=${laneRole}
          onPick=${x => patchBrowse && patchBrowse.into ? applyPatchInto(x) : openPatchDoc(x)}
          onSwitchToPresets=${() => { setPatchBrowse(false); setBrowse(true); }}
          onNew=${cur => { setPatchBrowse(false); skipSave.current = true; setSel(null); setDrawer(null);
            const b = blank(); b.name = 'New ' + cur + ' patch';
            b.__patch = { realm: PATCH_REALM[cur] || 'guitar', id: null, name: b.name, role: cur };
            seatPatchLane(b, editPatch());            // l'entrée de cet instrument sur la carte (Soundcard)
            setP(b); setScene(0);
            // UNE BATTERIE POSE SA QUESTION TOUT DE SUITE (2026-09-20, deux fois : « je veux
            // créer un drum patch et je n'ai pas les nouvelles interfaces »). Pour les autres
            // instruments, « quelle entrée » n'a qu'une réponse ; pour une batterie il y en a
            // trois — MIDI, une paire stéréo, N sorties directes — et c'est LE moment où elle se
            // pose. La laisser derrière un menu ⋯, c'est la laisser introuvable : un brouillon
            // MIDI s'ouvrait d'office, sans que rien ne dise qu'un autre choix existait.
            if (cur === 'drums') { setDsPick(null); setDsPlan([]); setDsOpen(true); } }}
          onClose=${() => setPatchBrowse(false)} />` : ''}

      ${pickAmp ? (() => { const blk = blockAt(p, pickAmp);
        const arch = blk.type === 'pedal-nam' && blk.variant ? pedalArch(blk.variant) : null;
        return html`<${AmpPicker} type=${blk.type} current=${blk.ref} archetype=${arch}
          onPick=${t => { setRef(pickAmp, t); reloadCatalog(); setPickAmp(null); }} onClose=${() => setPickAmp(null)} />`; })() : ''}



      ${bsSheet ? (() => { const blk = blockAt(p, bsSheet.ref); if (!blk) return '';
        const arch = blk.variant ? pedalArch(blk.variant) : null;
        return html`<${BlockStatusSheet} block=${blk} st=${bstat[blk.id] || bsSheet.st} role=${laneRole(bsSheet.ref.lane)}
          name=${capName(blk) || (arch ? arch.name : fxDef(blk.type).name || blk.type)} fetching=${bsFetch}
          onDownload=${() => bsDownload([blk.id])} onReplaceType=${t => bsReplaceType(bsSheet.ref, t)}
          onPlayable=${() => bsPlayable(blk)} playBusy=${bsPlayBusy}
          onPickCapture=${() => { const r = bsSheet.ref; setBsSheet(null); setPickAmp(r); }}
          onUseSuggestion=${sg => bsUseSuggestion(bsSheet.ref, sg)}
          onVstHost=${effects && effects.vst_host && bsSheet.ref.cg == null && bsSheet.ref.cr == null && bsSheet.ref.ca == null
            ? () => { const r = bsSheet.ref; setBsSheet(null); setDrawer({ lane: r.lane, replace: r }); } : null}
          onRemove=${() => { const ref = bsSheet.ref; setBsSheet(null); rmBlock(ref); }} onClose=${() => setBsSheet(null)} />`; })() : ''}
      ${settings ? html`<${PresetSettings} p=${p} upd=${upd} onClose=${() => setSettings(false)} />` : ''}
      ${naming ? html`<${NameSheet} initial=${naming.name || ''} dup=${naming.dup} onOk=${saveAs} onClose=${() => setNaming(null)} />` : ''}
      ${assignOpen ? html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && setAssignOpen(false)}>
        <div class="detail-card sm assign-sheet">
          <button class="close" onClick=${() => setAssignOpen(false)}>×</button>
          <h2>Assign « ${esc(patchMode ? patchMode.name : '')} »</h2>
          ${assignDone ? html`
            <p class="pat-drop-done">✓ deposited into « ${esc(assignDone.name)} » — ${assignDone.lane} lane replaced.</p>
            ${assignDone.added.length ? html`<p class="pat-drop-warn muted">＋ scene${assignDone.added.length > 1 ? 's' : ''} ${assignDone.added.join(', ')} added to the song, from the patch.</p>` : ''}
            ${assignDone.lost.length ? html`<p class="pat-drop-warn">⚠ scene${assignDone.lost.length > 1 ? 's' : ''} ${assignDone.lost.join(', ')} dropped — the song already has 8 scenes.</p>` : ''}
            <div class="assign-actions">
              ${/* ⚠ pas openInDesigner ici : il pose un preset « en attente » et navigue vers le Designer —
                    or on y EST déjà, rien ne le consomme (2026-09-08 : « ouvrir Velvetine n'a pas
                    marché »). On charge le preset directement dans le banc, ce qui quitte le mode patch. */''}
              <button class="primary" onClick=${() => { setAssignOpen(false); loadPreset(assignDone.pid); }}>Open « ${esc(assignDone.name)} »</button>
              <button class="mini" onClick=${() => setAssignOpen(false)}>Stay on the bench</button>
            </div>`
          : html`
            <p class="muted">Into an existing song — its ${(patchMode && patchMode.realm) || 'guitar'} lane is <b>replaced</b> by this patch — or into a new one.</p>
            <button class="row-btn" onClick=${() => { setAssignOpen(false); createFromPatch(); }}>➕ New song from this bench<small>the bench becomes a preset</small></button>
            <div class="assign-list">
              ${(presets || []).slice().sort((a, b) => (a.name || '').localeCompare(b.name || '')).map(pr => html`
                <button class="row-btn" onClick=${() => depositInto(pr)}>${esc(pr.name)}<small>replaces its ${(patchMode && patchMode.realm) || 'guitar'} lane</small></button>`)}
              ${!(presets || []).length ? html`<p class="muted">No song yet.</p>` : ''}
            </div>`}
        </div></div>` : ''}
      ${pmNaming ? html`<${NameSheet} kind="patch" fixed=${!!(patchMode && patchMode.source_id)}
        initial=${patchMode ? patchMode.name : ''} onOk=${doCreatePatch} onClose=${() => setPmNaming(false)} />` : ''}
      ${laneApply ? html`<${LaneApplySheet} doc=${bodyOf()} lane=${laneApply}
        laneName=${laneTitle(lanes.find(L => L.id === laneApply) || {})} onClose=${() => setLaneApply(null)} />` : ''}
      ${sceneSheet ? html`<${SceneSheet} sc=${sc} canDelete=${p.scenes.length > 1}
        lanes=${lanes.map(L => ({ id: L.id, name: L.name, icon: ROLE_ICON[L.role || laneRoleOfKey(L.key)], level: sceneLevelOf(sc, L.id),
          // l'ÉTAT que la scène choisit pour cette lane (band-scenes.md) — un état implicite n'a rien à dire de plus que la scène
          state: (() => { const st = (L.states || []).find(x => x.id === (((sc.lanes || {})[L.id] || {}).state)); return st && !st.implicit ? st.name : null; })() }))}
        onName=${renameScene} onLevel=${setSceneLevel} onDelete=${delScene} onClose=${() => setSceneSheet(false)} />` : ''}
      ${ioOpen ? html`<${IoSheet} rows=${sheetRows()} lanes=${lanes} inTab=${inTab} patch=${patch} modePatch=${modePatch} modeCard=${modeCard}
          modeName=${(((rig && rig.state) || {}).mode || {}).name} cardName=${editCardName()} inputsCount=${inOptsLive().length - 1}
          rmLaneArm=${rmLaneArm} laneBlocks=${laneBlocks} onToggle=${toggleRow} onRemove=${removeLane} onClose=${() => setIoOpen(false)}
          addRole=${addRole} addRows=${addRole ? addChoicesFor(addRole, lanes, editPatch()) : []} addArm=${addArm}
          onAddRole=${pickAddRole} onAddRow=${addOnInput} />` : ''}
      ${dsOpen ? html`<${DrumsetSheet} pick=${dsPick} form=${dsForm} plan=${dsPlan}
          freeIn=${dsFreeIn} elements=${(dsKits || {}).elements || []} cardName=${editCardName()} portable=${!!patchMode}
          onPick=${dsSetKit} onForm=${dsSetForm} onElement=${dsSetElement} onAdd=${dsAdd} onClose=${() => setDsOpen(false)} />` : ''}
      ${scenePlus ? html`<${ScenePlus} presets=${presets || []} activeName=${sc.name || sc.id}
        onNew=${newScene} onDup=${dupScene} onImport=${importScene} onClose=${() => setScenePlus(false)} />` : ''}
      ${browse ? html`<${PresetBrowser} presets=${presets || []} current=${p.id}
        onSwitch=${() => { setBrowse(false); setPatchRole(null); setPatchQ(''); setPatchBrowse(true); }}
        onLoad=${id => { loadPreset(id); setBrowse(false); }}
        onSettings=${() => { setBrowse(false); setSettings(true); }} onClose=${() => setBrowse(false)} />` : ''}
      ${bankPick ? html`<${BankPicker} pid=${p.id} banks=${bankSlots} presets=${presets || []} browse=${true}
        footName=${banksData && banksData.name} footId=${banksData && banksData.id} footLines=${banksData && banksData.lines}
        onPick=${assignBank} onRemove=${removeBank} onSetCurrent=${setCurrentList} onSwap=${swapBanks} onClose=${() => setBankPick(false)} />` : ''}
    </div>`;
}

// ── connecteur split/merge (courbes SVG, s'étire à la hauteur des lanes) ──
function Connector({ n, side, ys }) {
  const W = 46, H = 100;
  const paths = [];
  for (let i = 0; i < n; i++) {
    const y = ys ? ys[i] * H : (i + 0.5) * (H / n);       // ys = fractions exactes des demi-fils (grille)
    paths.push(side === 'split'
      ? `M0,${H / 2} C ${W * 0.55},${H / 2} ${W * 0.45},${y} ${W},${y}`
      : `M0,${y} C ${W * 0.55},${y} ${W * 0.45},${H / 2} ${W},${H / 2}`);
  }
  const dot = side === 'split' ? 0.6 : W - 0.6;
  return html`<svg class="conn" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    ${paths.map(d => html`<path d=${d} fill="none" stroke="var(--line)" stroke-width="2" vector-effect="non-scaling-stroke" />`)}
    <circle cx=${dot} cy=${H / 2} r="3" fill="var(--accent)" vector-effect="non-scaling-stroke" />
  </svg>`;
}

// ── GRILLE des chaînes (docs/designer-grid.md) : layoutChain (pur) -> rendu 12 colonnes ──
// Les payloads (head/zone/tail/out) sont des vnodes déjà construits (Tile/PlusBtn/pills) ;
// meta = {hdr, lanes:[{tag,muted,onPw,onDel}]} pour l'en-tête ⇉/Σ + puces de lane sur la fourche.
const LANE_YS = [0.235, 0.765];                            // centres des demi-rangées (76+10+76 → 38/162, 124/162)
// `cols` : le moteur l'accepte depuis toujours, seul le rendu le figeait à 12. Une lane de config
// porte 2 ou 3 cases pour toute la largeur — à 12 colonnes une case fait ~70 px, trop peu pour un
// terminal, qui débordait alors DANS LA CASE VOISINE et chevauchait la tuile. On élargit la
// colonne au lieu de laisser le contenu sortir : c'est la grille qui doit suivre le contenu.
// Lanes de CONFIG : 7 colonnes, pas 12. Elles ne portent jamais plus de 3 cases, et il leur faut
// des colonnes assez larges pour un terminal (~112 px) — sinon il empiète sur sa voisine.
const CFG_COLS = 7;
// Largeur d'une pastille d'entrée en cellule — DOIT suivre le `max-width` de
// `.gc-cell > .io-pill` dans style.css, sinon le ＋ qui la longe se décale.
const PILL_W = 112;

function GridChain({ head, zone, tail, out, meta, cols = 12 }) {
  const { rows } = layoutChain({ cols, head, zone, tail: tail || [], out });
  // EFFACER UNE BRANCHE = DEUX TOUCHERS (2026-10-27, tools/check-use.py) : un seul toucher sur ce petit « × », collé
  // au ⏻ de la lane, effaçait ampli, baffle et la suite — et la sauvegarde automatique l'enregistrait aussitôt.
  // Le premier toucher ARME (« sure? », 2,5 s), le second efface : le même geste que les presets de bloc et les kits.
  const [armDel, setArmDel] = useState(null);
  const delBranch = (li, onDel) => {
    if (armDel !== li) { setArmDel(li); setTimeout(() => setArmDel(a => a === li ? null : a), 2500); return; }
    setArmDel(null); onDel();
  };
  const pct = v => (v / cols * 100).toFixed(3) + '%';
  const Cell = (r, c) => {
    if (c.kind === 'fork') return html`<div class="gc-cell fork" style=${'grid-column:' + (c.col + 1)}>
      <${Connector} n=${2} side="split" ys=${LANE_YS} />
      ${meta ? meta.hdr : ''}
      ${meta ? meta.lanes.map((m, li) => html`<span class=${'gc-chip ' + (li ? 'chip-b' : 'chip-a')}>
        <b>${m.tag}</b>
        <button class=${cls('gc-pw', !m.muted && 'on')} onClick=${m.onPw}
          title=${m.muted ? 'lane muted in this scene — tap to enable' : 'lane plays in this scene — tap to mute'}>⏻</button>
        <button class=${cls('gc-x', armDel === li && 'arm')} onClick=${() => delBranch(li, m.onDel)}
          title=${armDel === li ? 'tap again to delete this branch' : 'delete branch'}>${armDel === li ? 'sure?' : '×'}</button></span>`) : ''}
    </div>`;
    if (c.kind === 'join') return html`<div class="gc-cell join" style=${'grid-column:' + (c.col + 1)}>
      <${Connector} n=${2} side="merge" ys=${LANE_YS} /></div>`;
    if (c.kind === 'wrapout' || c.kind === 'wrapin')           // demi-blocs de retour à la ligne (façon QC)
      return html`<div class=${'gc-cell ln-c wr-' + (c.kind === 'wrapout' ? 'out' : 'in')} style=${'grid-column:' + (c.col + 1)}>
        <span class="gc-half" title=${c.kind === 'wrapout' ? 'the chain continues on the next line' : 'chain continued'}>${c.kind === 'wrapout' ? '⤵' : '⤷'}</span></div>`;
    return html`<div class=${cls('gc-cell', 'ln-' + c.lane, c.kind === 'ghost' && 'ghost')}
        style=${'grid-column:' + (c.col + 1)}>
      ${c.kind === 'item' ? c.it : ''}
    </div>`;
  };
  return html`<div class="gc" style=${cols !== 12 ? '--gc-cols:' + cols : undefined}>
    ${rows.map(r => html`
      <div class=${cls('gc-row', r.tall && 'tall')}>
        ${r.wires.map(w => html`<i class=${'gc-wire w-' + w.lane} style=${`left:${pct(w.from)};width:${pct(w.to - w.from)}`}></i>`)}
        ${/* le ＋ se pose SUR le bord droit de la tuile qui le précède. À 12 colonnes la case (80 px)
              vaut la tuile (78 px) : la frontière de colonne EST le bord. Sur une lane de config
              (7 colonnes, case de ~137 px, tuile centrée) la frontière flotte 30 px plus loin —
              retour 2026-09-09 : on recule d'une demi-marge (case − tuile) / 2. */''}
        ${/* Le ＋ chevauche le BORD DROIT de la case précédente — pas dedans, pas détaché. En 12
              colonnes la case vaut la tuile, la frontière EST le bord. Sur une lane de config
              (colonnes larges) le contenu est centré : on recule d'une demi-marge, avec la largeur
              RÉELLE du voisin — 78 px pour une tuile, 112 px pour une pastille d'entrée
              (`max-width` de .gc-cell > .io-pill). Prendre 78 pour une pastille ramenait le ＋ DANS
              la box (16 px de chevauchement, Players, retour 2026-09-12). */''}
        ${(r.adds || []).map(a => html`<span class=${'gc-add ga-' + a.lane}
          style=${cols === 12 ? `left:${pct(a.col)}`
                 : `left:calc(${pct(a.col)} - (100% / ${cols} - ${a.edge ? PILL_W : 78}px) / 2)`}>${a.it}</span>`)}
        ${r.cells.map(c => Cell(r, c))}
      </div>
      ${r.ret ? html`<div class="gc-ret" aria-hidden="true"></div>` : ''}`)}
  </div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Feuille du bloc ARRANGEMENT — la structure du morceau dans le temps.
// Contrat : docs/arrangement.md. Ce fichier couvre l'UI (§9) ; le moteur de cues (§8) vit dans
// le bridge et n'existe pas encore — ce qu'on construit ici est donc lisible mais pas encore joué.
//
// ── UN ONGLET, PAS UN TIROIR (décision 2026-07-30) ──
// Ce fut d'abord une feuille de bloc à deux sous-onglets. Deux mesures ont tranché : le corps du
// Designer fait 481 px contre 257 pour un tiroir (+87 %), et éditer la structure d'un morceau
// passait par CINQ niveaux (Designer > ⚙ Config > tuile > tiroir > sous-onglet). Avec la page, la
// piste est pleine largeur et le panneau de section vit À CÔTÉ — plus de sous-onglets du tout.
// Le bloc, lui, reste : il porte les données, le switch au pied et le on/off. La page est son
// ÉDITEUR, pas son remplaçant. Il est PERMANENT (créé par la migration, comme Rec et Click) :
// on n'ajoute plus un arrangement, on écrit la structure du morceau.
//
// ── LA RÈGLE QUI TIENT TOUT ──
// L'arrangement ne fabrique AUCUN son : il séquence des scènes. Le panneau Section est donc
// d'abord un LECTEUR — il montre ce que la scène choisie va faire — avec un raccourci vers
// l'éditeur de scène. S'il devenait un second éditeur de son, il y aurait deux endroits où
// définir le son de la guitare au refrain, et un jour ils ne diraient pas la même chose.
import { html, useState, useEffect, useRef, useAsync, cls, esc } from './lib.js';
import { sectionLook, PART_COLOR as PART_COLOR_SHARED, SCENE_FALLBACK, ANIM_STYLES, animClass, animPackOf, ensurePackCss, ICON, ROLE_ICON, blkColor, normLanes, laneStateAt, laneLineName, laneMutedIn, resolveStarts, drumsAt, grooveName } from './designer-model.js';
import { EffectPicker } from './designer-sheets.js';

// Les 7 étiquettes du contrat (§2). Réutilisables : `verse` peut apparaître trois fois avec des
// cues différentes — ce sont des étiquettes, pas du contenu.
export const PART_LIBRARY = ['intro', 'verse', 'pre-chorus', 'chorus', 'bridge', 'solo', 'outro'];
const PART_COLOR = PART_COLOR_SHARED;   // source unique (designer-model) — cf. sectionLook
const DENOMINATORS = [1, 2, 4, 8, 16];
// groupements usuels proposés en un tap (§5.2) — 7 et 5 sont ceux qu'on écrit à la main sinon
const COMMON_GROUPS = { 5: [[3, 2], [2, 3]], 7: [[3, 2, 2], [2, 2, 3]], 9: [[3, 3, 3], [2, 2, 2, 3]] };

export const sigOf = (sec, base) => ({
  num: (sec.sig && sec.sig.num) || (base && base.num) || 4,
  den: (sec.sig && sec.sig.den) || (base && base.den) || 4,
  groups: (sec.sig && sec.sig.groups) || null,
});
const isOwnSig = sec => !!(sec.sig && sec.sig.num);

// durée d'une section, en secondes. LE BPM DÉSIGNE LA NOIRE (convention Reaper, contrat §5.2) :
//   durée_pulsation = (4/den) × 60/bpm      durée_mesure = num × durée_pulsation
// 7/8 à 120 -> 1,75 s la mesure ; 9/4 à 120 -> 4,5 s.
export const secSeconds = (sec, base, bpm) => {
  const s = sigOf(sec, base);
  return (sec.bars || 0) * s.num * (4 / s.den) * (60 / (bpm || 120));
};
const mmss = s => Math.floor(s / 60) + ':' + String(Math.round(s % 60)).padStart(2, '0');
// durée d'UNE mesure de la métrique de base — l'unité dans laquelle on compte la longueur du
// morceau. Avec des métriques mélangées, « 123 mesures » n'a de sens que rapporté à une base.
const baseBarSec = (base, bpm) => (base.num || 4) * (4 / (base.den || 4)) * (60 / (bpm || 120));
// zoom « Bars » : à 13 px une mesure ne se compte pas au doigt (un groupe de 4 faisait 52 px).
// À 18, le groupe fait 72 px et la grille devient dénombrable. 128 mesures = 2,4 écrans, acceptable.
const PX_PER_BAR = 18;
// PAS d'abréviation (décision) : on lit « Intro », pas « INT ». Un nom tronqué par le
// débordement reste plus lisible qu'un code de trois lettres en capitales — et le titre complet
// est de toute façon dans l'infobulle.
// marqueur de la zone libre : elle se compte dans la métrique de BASE du morceau.
const REST = { name: '', bars: 0 };

// ── UN NOMBRE QU'ON PEUT RETAPER (bug du 2026-09-22, « c'est 4 par défaut et après ça se
// bloque à 1 ») ─────────────────────────────────────────────────────────────────────────────────
// Le champ « bars » réécrivait `Number(valeur) || 1` à CHAQUE frappe : effacer le 4 posait aussitôt
// 1 (le champ ne pouvait jamais être vide), et taper « 16 » derrière donnait 116. Ici le texte tapé
// vit localement pendant la saisie : un champ vide ou incomplet n'écrit rien, un nombre valide est
// transmis dès qu'il l'est, et quitter le champ vide rend la valeur réelle.
function CountField({ value, min, max, onCommit }) {
  const [txt, setTxt] = useState(null);             // null = pas en saisie : on montre la valeur réelle
  return html`<input type="number" min=${min} max=${max} value=${txt != null ? txt : value}
    onFocus=${() => setTxt(String(value))}
    onInput=${e => {
      const t = e.target.value; setTxt(t);
      const n = Math.round(Number(t));
      if (t.trim() !== '' && Number.isFinite(n) && n >= min) onCommit(Math.min(max, n));
    }}
    onBlur=${() => setTxt(null)} />`;
}

export function ArrangementPage({ block, bpm, scenes, lanes, footBlocks, backingSec, modeOk, modeName,
                                 onParam, onFoot, onBypass, onEditScene, onSampleAdd, preset,
                                 entries, inputmap, onNewScene, onScenes, rig, onPlay, onStop, backingLinked, takenSwitches, onLinkStems, onAddSample, barMap }) {
  // ▶ LECTURE (2026-09-24) : ce que le bridge dit de l'arrangement qui TOURNE — seulement s'il tourne sur
  // ce preset (la page chanson édite Paper Kite pendant que le rig peut jouer autre chose)
  const liveArr = (((rig || {}).state || {}).arrangement) || {};
  const playing = !!(liveArr.running && ((rig || {}).state || {}).preset_id === (preset || {}).id);
  const playIdx = playing && !liveArr.counting ? Number(liveArr.index) : -1;
  // le HUD se met à jour 10× par seconde pendant la lecture (tête de lecture, temps du décompte) —
  // sur l'horloge du navigateur, calée sur les bornes que le bridge publie (sec_from/sec_to, count_*)
  const [tick, setTick] = useState(0);
  useEffect(() => { if (!playing) return; const t = setInterval(() => setTick(x => x + 1), 100); return () => clearInterval(t); }, [playing]);
  // contenu d'un bloc pour la scène d'une SECTION : scene.params[id][param] > base
  const secContent = (b, sec) => {
    if (!b.cparam) return null;
    const sc = (scenes || []).find(x => x.id === (sec || {}).scene);
    const v = ((sc && sc.params && sc.params[b.id]) || {})[b.cparam] ?? b.cbase;
    return v ? String(v).split('/').pop().replace(/\.(vital|sfz|golemkit|xml)$/i, '').replace(/_/g, ' ') : null;
  };
  const [animPick, setAnimPick] = useState(false);
  // TIROIR v2 (maquette mockups/arr-drawer-v2.html, 2026-10-08) : le Look et la signature dans des panneaux
  // ouverts depuis l'en-tête, les blocs par partie dans un accordéon replié
  const [lookOpen, setLookOpen] = useState(false);
  const [sigOpen, setSigOpen] = useState(false);
  const [drumOpen, setDrumOpen] = useState(false);       // le groove de la partie (2026-10-20)
  const [blkOpen, setBlkOpen] = useState(false);
  const pm = (block && block.params) || {};
  const base = pm.sig || { num: 4, den: 4 };
  const sections = Array.isArray(pm.sections) ? pm.sections : [];
  const [sel, setSel] = useState(null);   // null = la page montre la PISTE, pas un détail
  const [zoom, setZoom] = useState('fit');
  const [selMark, setSelMark] = useState(null);   // marqueur de sample ouvert dans la feuille
  // ── L'ARRANGEMENT SE LIT PAR ENTRÉE (2026-09-10, mockups/setlist-arrangement.html A) : on
  // choisit un musicien (« Guitar 1 · IN 1 — le mainteneur ») et ses changements se lisent SOUS la structure,
  // alignés dessus, une ligne par bloc. Taper une section ne fait plus que la SÉLECTIONNER : le
  // découpage se règle ailleurs, et le détail d'une partie s'ouvre par « ✎ » dans l'en-tête. ──
  const [who, setWho] = useState(null);
  const [partSheet, setPartSheet] = useState(false);   // le détail COMPLET (signature, accents, look)
  const [libPick, setLibPick] = useState(false);  // ＋ from library : sélecteur ouvert
  const [libSaid, setSaid] = useState('');        // ce qu'on vient d'écrire dans le bloc sample
  useEffect(() => { if (!libSaid) return; const t = setTimeout(() => setSaid(''), 4200);
    return () => clearTimeout(t); }, [libSaid]);
  const { data: libD } = useAsync(() => fetch('/api/kits').then(r => r.json()), []);
  // switches occupés par un AUTRE bloc que l'arrangement (reconstruit depuis footBlocks)
  // `takenSwitches` (page chanson) compte AUSSI Click/Rec, que footBlocks — les blocs commutables par partie —
  // ne porte pas : Paper Kite a Click sur le 4, et le 4 ne se disait pas pris
  const taken = new Set(takenSwitches || (footBlocks || [])
    .filter(f => f.foot && f.id !== (block || {}).id).map(f => f.foot));
  const cur = sections[sel] || null;
  // ── LES CASES « When the song starts » (docs/arrangement.md §5-6) ──
  // `pm.starts` = ce que la CHANSON a coché. Une case jamais touchée affiche ce que le rack fait sans elle
  // (bridge arrangement.starts_of : backing et samples oui, click si son bloc est actif, prise si Rec est
  // sur le switch de l'arrangement) — l'écran ne doit pas montrer décoché ce qui partira.
  const [swOpen, setSwOpen] = useState(false);
  const stx = pm.starts || {};
  const cfgOf = lane => ((((preset || {}).config || {})[lane] || {}).blocks || []).filter(Boolean);
  const smpBlk = cfgOf('gen').find(b => b.type === 'sample');
  // LA BOÎTE À RYTHMES DU MORCEAU (docs/arrangement.md §6, 2026-10-20) : elle part avec la chanson, chaque partie choisit
  // son groove parmi les motifs du bloc (section.drums = numéro, « stop », ou rien = celui d'avant)
  const drumBlk = cfgOf('gen').find(b => b.type === 'drums');
  const drumPats = ((drumBlk || {}).params || {}).patterns || [];
  const modeCard = ((rig || {}).state || {}).mode || {};
  const resolved = resolveStarts(stx, preset);
  const startOn = k => resolved[k];
  const setStart = (k, v) => onParam('starts', { ...stx, [k]: v });
  const startsRow = [
    { key: 'backing', label: 'Backing', color: '#1ab7b0', on: startOn('backing'),
      title: 'the stems start from the top with the first part, after the count-in — and stop with the song',
      // la carte des mesures (docs/bars-format.md) : les parties tombent sur les mesures RÉELLES
      sub: !backingSec ? (backingLinked ? 'stems not on the rack yet' : 'no stems linked')
        : (barMap && barMap.present) ? 'stems ✓ · bar map ' + barMap.bars + ' bars' : 'stems ✓ · no bar map',
      warn: !backingSec, action: !backingLinked && onLinkStems ? { label: 'Link', fn: onLinkStems } : null },
    { key: 'click', label: 'Click', color: '#e8c547', on: startOn('click'),
      // avec une carte et ses temps, le click joue les VRAIS temps de la backing ; sinon un tempo constant
      sub: modeCard.click_mode === 'off' ? 'off in ' + (modeCard.name || 'this mode')
        : (barMap && barMap.present && startOn('backing')) ? ('on the song\u2019s beats' + (barMap.approx_beats ? ' · ' + barMap.approx_beats + ' bars approximated' : ''))
        : 'constant ' + (bpm || 120) + ' BPM',
      warn: modeCard.click_mode === 'off',
      title: (barMap && barMap.present) ? 'the click plays the real beats of the backing (bar map from golem.fm, ' + barMap.bars + ' bars, ' + barMap.confirmed + ' checked by ear)'
        : 'no bar map for this backing: the click keeps a constant tempo — a band recorded without a click will drift from it' },
    { key: 'rec', label: 'Record', color: '#ff4b4b', on: startOn('rec'),
      title: 'a take starts with the song and stops when it ends',
      sub: modeCard.rec_scope === 'set' ? 'the whole set is recorded' : 'a take, stopped with the song' },
    { key: 'drums', label: 'Drums', color: '#7fd4a8', absent: !drumBlk, on: !!drumBlk && startOn('drums'),
      title: drumBlk ? 'the drum machine starts with the song — each part picks its groove (the 🥁 chip of a part)' : 'this preset has no drum machine',
      sub: drumBlk ? drumPats.length + ' groove' + (drumPats.length === 1 ? '' : 's') + ' · one per part' : 'not in this preset', warn: !drumBlk },
    { key: 'sample', label: 'Sample', color: '#8fbf5a', absent: !smpBlk, on: !!smpBlk && startOn('sample'),
      title: smpBlk ? 'the sample markers of the song fire' : 'this preset has no sampler',
      sub: smpBlk ? 'the sample markers' : 'not in this preset', warn: !smpBlk,
      action: !smpBlk && onAddSample ? { label: 'Add', fn: onAddSample } : null },
  ];

  const put = next => onParam('sections', next);
  // ── GLISSER-DÉPOSER (décision — l'agent UX le déconseillait, à tort ici) ──────────────
  // Sa réserve était réelle : en zoom Bars la piste défile horizontalement, un glissé serait
  // ambigu. On lève l'ambiguïté par un APPUI LONG (260 ms) — l'idiome de réordonnancement
  // tactile : un tap sélectionne, un appui long SOULÈVE puis on déplace. Le défilement garde
  // le glissé court, la section garde le glissé long, et rien ne se marche dessus.
  // Le réordonnancement est APPLIQUÉ EN CONTINU (pas de fantôme suivi d'un dépôt) : on voit
  // le morceau se réécrire sous le doigt, ce qui est la seule façon de viser juste sans souris.
  // ── GLISSER-DÉPOSER : un tap SÉLECTIONNE, un APPUI LONG (260 ms) SOULÈVE ─────────────────
  // L'appui long lève l'ambiguïté avec le défilement horizontal du zoom Bars — glissé court =
  // on défile, glissé long = on prend la section. Le réordonnancement est appliqué EN CONTINU :
  // on voit le morceau se réécrire sous le doigt, seule façon de viser juste sans souris.
  //
  // ⚠ DEUX PIÈGES, tous deux trouvés parce que MON TEST VALIDAIT UN GESTE QUE PERSONNE NE FAIT
  //   (il tenait le bouton immobile 400 ms avant de partir) :
  //   1. `onPointerLeave` annulait le minuteur — c'est-à-dire DÈS QU'ON COMMENCE À GLISSER. Un
  //      vrai geste appuie et bouge tout de suite. Il n'y a donc PLUS de `onPointerLeave`.
  //   2. `setPointerCapture` sur la région : le réordonnancement re-rend la liste et REMPLACE le
  //      nœud capturé, le pointeur perd son destinataire et le glissé meurt sans un mot. Les
  //      écouteurs vivent sur `window`, posés DÈS L'APPUI (pour que le relâchement nettoie même
  //      si le doigt est parti ailleurs). Même idiome que PFader, qui écoute window depuis
  //      toujours pour cette raison.
  const drag = useRef({ on: false, from: -1, timer: null, moved: false });
  const [dragI, setDragI] = useState(-1);
  // largeur RÉELLE de la voie : c'est elle qui fixe l'échelle en zoom Fit, et elle sert aussi à
  // décider si la grille d'une région est encore dénombrable. Un ResizeObserver plutôt qu'une
  // supposition — la voie ne fait pas la même largeur à 1024 et à 800.
  // ⚠ UNE LARGEUR NULLE N'EST PAS UNE LARGEUR (2026-10-07, Paper Kite, ■ Stop sur /songs) : la
  // frise entière tassée dans 40 px — 18 sections à leur minimum de 2 px, donc laneW = 0. Un nœud
  // caché ou détaché mesure 0, et Fit en tirait une échelle nulle. Et l'observateur posé UNE fois au
  // montage restait accroché à l'ancien nœud si la voie était re-rendue : il ne voyait plus jamais la
  // vraie. D'où une ref-callback STABLE qui ré-observe le nœud courant, et un 0 ignoré.
  const trackRef = useRef(null);
  const roRef = useRef(null);
  const [laneW, setLaneW] = useState(940);
  const setTrackEl = useRef(el => {
    if (el === trackRef.current) return;
    trackRef.current = el;
    if (roRef.current) { roRef.current.disconnect(); roRef.current = null; }
    if (!el || typeof ResizeObserver === 'undefined') return;
    roRef.current = new ResizeObserver(e => { const w = Math.round(e[0].contentRect.width); if (w > 0) setLaneW(w); });
    roRef.current.observe(el);
  }).current;
  useEffect(() => () => { if (roRef.current) roRef.current.disconnect(); }, []);
  const secsRef = useRef(sections);
  secsRef.current = sections;

  // le glisser marche sur la frise ET sur le rail du tiroir : `drag.current.sel` dit quelles cases sont les parties
  const hitIndex = x => {
    const kids = [...document.querySelectorAll(drag.current.sel || '.arr-lanes .arr-track .arr-sec')];
    if (!kids.length) return -1;
    for (let i = 0; i < kids.length; i++) {
      const r = kids[i].getBoundingClientRect();
      if (x < r.left + r.width / 2) return i;
    }
    return kids.length - 1;
  };
  const onWinMove = e => {
    if (!drag.current.on) return;              // pas encore soulevé : on laisse le geste au défilement
    e.preventDefault();
    const to = hitIndex(e.clientX);
    const from = drag.current.from;
    if (to < 0 || to === from) return;
    const n = secsRef.current.slice();
    n.splice(to, 0, n.splice(from, 1)[0]);
    drag.current.from = to; drag.current.moved = true;
    setDragI(to); setSel(to); put(n);
  };
  const onWinUp = () => {
    clearTimeout(drag.current.timer);
    window.removeEventListener('pointermove', onWinMove);
    window.removeEventListener('pointerup', onWinUp);
    window.removeEventListener('pointercancel', onWinUp);
    drag.current.on = false; drag.current.from = -1;
    setDragI(-1);
  };
  const onSecDown = (i, sel) => {
    onWinUp();                                 // un geste en cours ? on le solde avant d'en ouvrir un
    drag.current.moved = false;
    drag.current.sel = sel || null;
    window.addEventListener('pointermove', onWinMove, { passive: false });
    window.addEventListener('pointerup', onWinUp);
    window.addEventListener('pointercancel', onWinUp);
    drag.current.timer = setTimeout(() => { drag.current.on = true; drag.current.from = i; setDragI(i); }, 260);
  };
  useEffect(() => onWinUp, []);                // le composant part, les écouteurs aussi

  // ── glisser un MARQUEUR : on aimante à la mesure. Écouteurs FENÊTRE (le doigt sort du
  // marqueur de 24 px dès qu'il bouge — la leçon du drag de sections, et de la sortie de mode).
  const mdrag = useRef({ mi: -1, on: false });
  const onMarkMove = e => {
    if (!mdrag.current.on) return;
    e.preventDefault(); drag.current.moved = true;
    const el = trackRef.current;
    if (!el) return;
    const x = e.clientX - el.getBoundingClientRect().left + el.scrollLeft;
    const bar = Math.max(1, barAt(Math.max(0, x)));
    const m = marks[mdrag.current.mi];
    if (m && m.bar !== bar) patchMark(mdrag.current.mi, { bar });
  };
  const onMarkUp = () => {
    mdrag.current.on = false;
    window.removeEventListener('pointermove', onMarkMove);
    window.removeEventListener('pointerup', onMarkUp);
    window.removeEventListener('pointercancel', onMarkUp);
  };
  const onMarkDown = mi => {
    onMarkUp();
    drag.current.moved = false;
    mdrag.current = { mi, on: true };
    window.addEventListener('pointermove', onMarkMove, { passive: false });
    window.addEventListener('pointerup', onMarkUp);
    window.addEventListener('pointercancel', onMarkUp);
  };

  const patch = (i, kv) => put(sections.map((s, j) => (j === i ? { ...s, ...kv } : s)));
  // 4 mesures par défaut (décision) : on tape une partie, elle s'ajoute à la suite, et on
  // la déplace. Pas de formulaire, pas de choix à faire avant de voir quelque chose.
  const add = name => { put([...sections, { name, bars: 4 }]); setSel(sections.length); };

  // ── LES ENTRÉES : un musicien = une lane = une entrée de la carte (docs/arrangement.md §9 ter).
  // La personne vient du patch de la carte (Settings ▸ Mode ▸ Inputs of) : c'est la même vérité
  // partout, on ne la redemande pas ici. Une entrée qui ne change jamais rien reste listée, grise.
  const ents = entries && entries.length ? entries : [];
  const inEntry = e => {
    const im = inputmap || {};
    if (e.midi) return ((im.usb || []).find(u => u.bound && (!e.in_role || u.role === e.in_role)) || (im.usb || []).find(u => u.bound) || null);
    const byName = e.in_role && e.in_nth != null
      && (im.inputs || []).find(x => x.role === e.in_role && Number(x.nth) === Number(e.in_nth));
    return byName || (im.inputs || []).find(x => String(x.ch) === String(e.in_sel)) || null;
  };
  const entPort = e => { const p2 = inEntry(e); return e.midi ? ('USB ' + ((p2 && p2.port) || 1)) : (e.in_sel === 'NONE' ? '—' : 'IN ' + e.in_sel); };
  const entWho = e => { const p2 = inEntry(e); return (p2 && p2.person_name) || null; };
  const entMoves = e => sections.reduce((n, s2) => n + (e.blocks.some(b => (s2.blocks || {})[b.id] !== undefined) ? 1 : 0), 0);
  const cur3 = ents.find(e => e.id === who) || ents.find(e => e.blocks.length) || ents[0] || null;
  // les lanes du preset, telles que le rack les porte (avec leurs ÉTATS) : les lignes d'accord du tableau
  const arrLanes = preset && preset.lanes_v === 2 ? normLanes(preset) : [];

  // scène EFFECTIVE à une section : la dernière posée avant elle (le contrat dit « la partie
  // d'avant garde » — la case doit donc montrer ce qui joue vraiment, en pâle)
  const sceneAt = i => { for (let k = i; k >= 0; k--) if (sections[k].scene) return sections[k].scene; return null; };
  const sceneIds = (scenes || []).map((sc, i) => sc.id || String.fromCharCode(65 + i));
  const cycleScene = i => { const c = sections[i].scene;
    const k = c ? sceneIds.indexOf(c) : -1;
    patch(i, { scene: k < 0 ? (sceneIds[0] || null) : (k + 1 < sceneIds.length ? sceneIds[k + 1] : null) }); };
  // on → off → hérité : le même tour que les puces de stomps de la feuille (une seule loi)
  // ── CE QUE LA CASE MONTRE : l'état RÉEL du bloc à cette section (2026-09-10) ──
  // Le moteur applique la scène d'abord, les bascules ensuite (docs/arrangement.md §3 bis) : une
  // case « héritée » doit donc afficher ce que LA SCÈNE fait, pas un vide. On lit dans l'ordre :
  // bascule explicite de la section > scene.blocks[id] > scene.blocks[type] > bypass de base.
  const sceneObj = id => (scenes || []).find((sc, k) => (sc.id || String.fromCharCode(65 + k)) === id) || null;
  const effOf = (i, bk) => {
    const v = (sections[i].blocks || {})[bk.id];
    if (v !== undefined) return { on: !!v, forced: true };
    const sb = (sceneObj(sceneAt(i)) || {}).blocks || {};
    if (bk.id in sb) return { on: !!sb[bk.id], forced: false };
    if (bk.type in sb) return { on: !!sb[bk.type], forced: false };
    return { on: !bk.bypass, forced: false };
  };
  const cycleBlock = (i, id) => { const nb = { ...(sections[i].blocks || {}) };
    const v = nb[id];
    if (v === undefined) nb[id] = true; else if (v === true) nb[id] = false; else delete nb[id];
    patch(i, { blocks: nb }); };
  const del = i => { put(sections.filter((_, j) => j !== i)); setSel(Math.max(0, i - 1)); };
  const dup = i => { const n = sections.slice(); n.splice(i + 1, 0, JSON.parse(JSON.stringify(sections[i]))); put(n); setSel(i + 1); };
  // la mesure où commence chaque partie (1-based) : la frise et le rail l'affichent (2026-10-08)
  const barStart = []; sections.reduce((b, x) => { barStart.push(b); return b + Math.max(0, x.bars || 0); }, 1);
  const move = (i, d) => {
    const j = i + d;
    if (j < 0 || j >= sections.length) return;
    const n = sections.slice(); [n[i], n[j]] = [n[j], n[i]]; put(n); setSel(j);
  };

  const written = sections.reduce((t, s) => t + secSeconds(s, base, bpm), 0);
  const barSec = baseBarSec(base, bpm);
  // ── LA LONGUEUR DU MORCEAU : dérivée quand elle existe, déclarée sinon ──────────────────
  // Un backing lié PORTE la vérité (duration_sec) : 246,6 s à 120 en 4/4 = 123 mesures. Ce n'est
  // pas un réglage à inventer. Sans backing, `pm.bars` la déclare ; à 0 la piste fait exactement
  // ce qui est écrit (comportement d'origine).
  const declaredSec = (pm.bars || 0) * barSec;
  const songSec = backingSec || declaredSec || 0;
  const total = Math.max(written, songSec);
  // AVEC UNE CARTE DES MESURES (docs/bars-format.md) la longueur du morceau se COMPTE en mesures — 109 pour
  // Paper Kite — au lieu de se déduire de la durée à tempo fixe : un groupe joué sans click n'a pas un tempo,
  // et « durée ÷ mesure à 87 » annonçait « 3 bars over » sur un arrangement juste (2026-10-07).
  const mapBars = (barMap && barMap.present && barMap.bars) || 0;
  const countBars = sections.reduce((n, x) => n + Math.max(0, x.bars || 0), 0);
  const restBars = mapBars ? mapBars - countBars : Math.round((songSec ? songSec - written : 0) / barSec);
  const restSec = mapBars ? restBars * barSec : (songSec ? songSec - written : 0);
  const writtenBars = mapBars ? countBars : Math.round(written / barSec);
  // ⚠ LARGEUR PROPORTIONNELLE AU TEMPS, jamais au nombre de mesures (§5.2) : huit mesures de 7/8
  // durent 14 s là où huit de 4/4 en durent 16. Les dessiner pareil ferait MENTIR la piste sur
  // l'endroit où on se trouve — or c'est exactement ce qu'on regarde en jouant.
  // FIT : tout tient dans la vue (on lit la FORME du morceau). BARS : px/mesure fixe, la piste
  // défile dans son conteneur et les graduations se comptent — c'est ça, la valeur du zoom SD3,
  // pas le facteur d'agrandissement. Deux niveaux, pas trois : un troisième ajouterait une
  // décision sans ajouter une capacité, et sur tactile chaque tap se paie.
  const barsMode = zoom === 'bars';
  // en zoom Bars, la voie SUIT la section qui joue (elle défile, la page non)
  useEffect(() => {
    if (!barsMode || playIdx < 0 || !trackRef.current) return;
    const el = trackRef.current.querySelector('.arr-sec.arr-play');
    if (el && el.scrollIntoView) el.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
  }, [playIdx, barsMode]);
  // ── L'ÉCHELLE ────────────────────────────────────────────────────────────────────────────
  // UNE seule règle : des pixels par seconde. Tout — sections ET zone libre — s'y plie, donc la
  // piste est proportionnelle PARTOUT et il n'y a nulle part de largeur inventée.
  //   Bars : échelle fixe (PX_PER_BAR sur la mesure de base), on défile. On vient compter.
  //   Fit  : échelle calculée pour que TOUT le morceau tienne dans la vue…
  //          …AVEC UN PLANCHER. Sans lui, un morceau à peine commencé (16 mesures écrites sur
  //          123) écrase les blocs à leur min-width et devient illisible. Le plancher relève
  //          l'échelle jusqu'à ce que la plus petite section fasse MIN_SEC px — et la piste
  //          déborde alors, donc elle défile. C'est le seul compromis honnête : on ne compresse
  //          RIEN, on montre tout, et on défile quand ça ne rentre pas.
  //          (Premier jet : une « amorce » de 96 px à la fin pour la zone libre. Elle mentait
  //           sur l'échelle et le mainteneur l'a vue tout de suite.)
  // ── DETTE DE ROADMAP RÉGLÉE (2026-09-10) : « le zoom Fit qui ne tient pas ». ────────────
  // Deux causes, aucune n'était le plancher lui-même :
  //  1. FIT s'échelonnait sur `total`, qui contient la ZONE VIDE (le morceau déclaré moins ce
  //     qui est écrit). Sur 16 mesures écrites d'un morceau de 123, l'échelle était donc fixée
  //     par du VIDE : les parties tombaient sous le plancher, et la piste débordait. Or le vide
  //     n'est pas le morceau, c'est son absence — et le compteur de l'en-tête dit déjà
  //     « 16/123 bars ». FIT tient donc sur ce qui est ÉCRIT ; la zone vide reste dessinée à la
  //     MÊME échelle (pas d'amorce, pas de largeur inventée — c'est le premier jet que le mainteneur
  //     avait vu mentir), simplement au-delà du bord droit.
  //  2. Le plancher valait 52 px parce que la frise était la surface d'ÉDITION : il fallait lire
  //     et viser une partie dessus. Depuis le grand tiroir (§9 ter), un tap n'importe où sur la
  //     partie ouvre tout en pleine largeur — la frise ne sert plus qu'à lire la FORME. 28 px
  //     suffisent à viser, et le libellé s'efface sous 34 px plutôt que d'imposer sa largeur.
  // ── FIT TIENT, POINT (2026-09-24 : « j'aimerais que Fit tienne sur la page quitte à ce que ce soit
  // petit, et Bars qui défile »). Le plancher de 28 px par section faisait de Fit un Bars déguisé : une
  // section d'UNE mesure imposait 28 px/mesure, et 107 mesures = 3 000 px (mesuré). Plus de plancher :
  // une petite section est une couleur qu'on vise quand même (le tiroir s'ouvre au tap), le libellé
  // s'efface sous 34 px comme avant. Le seul minimum est 2 px — pour qu'une mesure reste VISIBLE.
  const scale = (() => {
    if (barsMode) return PX_PER_BAR / barSec;
    const span = Math.max(written || total, 0.001);
    return laneW / span;
  })();
  // ⚠ LARGEURS ENTIÈRES, et les repères calculés SUR CES MÊMES ENTIERS. Le navigateur arrondit
  // la largeur posée de chaque région ; en additionnant dix régions, l'écart s'accumule et la
  // règle finit DÉCALÉE de plusieurs pixels par rapport aux traits de la grille — un décalage
  // qui grandit vers la droite, exactement ce que le mainteneur a vu. En arrondissant NOUS-MÊMES et en
  // faisant partir la règle du même total cumulé, les deux ne peuvent plus diverger.
  // ⚠ RÉPARTIR L'ARRONDI, NE PAS L'ACCUMULER — l'autre moitié de la dette « Fit ne tient pas ».
  // Douze largeurs arrondies chacune dans son coin dépassaient la voie de 4 px (mesuré : voie 620,
  // contenu 624). On arrondit la POSITION cumulée et la largeur est la différence de deux positions
  // entières : la somme vaut alors exactement round(span × échelle), au pixel près, et « Fit » tient
  // vraiment. C'est le même principe que la règle, qui partait déjà du total cumulé.
  const _wmap = new Map();
  (() => { let acc = 0, prev = 0;
    for (const s of sections) { acc += secSeconds(s, base, bpm);
      const x = Math.round(acc * scale); _wmap.set(s, Math.max(2, x - prev)); prev = x; } })();
  const wPx = s => (_wmap.has(s) ? _wmap.get(s) : Math.round(secSeconds(s, base, bpm) * scale));
  const restPx = Math.round(restSec * scale);

  // ── LANE DE SAMPLES : mêmes entiers que la piste, jamais un calcul parallèle ────────────
  const smpBlocks = ((((preset || {}).config || {}).gen || {}).blocks || [])
    .filter(b => b && b.type === 'sample' && b.id && ((b.params || {}).samples || []).length);
  const marks = (pm.samples || []).filter(m => m && m.block);
  // ⚠ une entrée de liste vaut "chemin.wav" OU {file, foot:false} (§21) : passer l'objet à
  // String() affichait « [object Object] » sur chaque chip et chaque marqueur.
  const fileOf = e => (typeof e === 'string' ? e : (e || {}).file) || '';
  const fileLabel = f => fileOf(f).split('/').pop().replace(/\.(wav|flac|ogg|mp3)$/i, '').replace(/[-_]/g, ' ');
  const smpName = m => { const b = smpBlocks.find(x => x.id === m.block);
    return b ? fileLabel((b.params.samples || [])[m.idx]) : null; };
  // x d'une mesure : on CUMULE les largeurs entières des sections, comme la règle
  const barX = (bar, beat) => {
    let x = 0, at = 1;
    for (const s2 of sections) {
      const n = Math.max(0, s2.bars || 0);
      if (bar < at + n) { const w = wPx(s2);
        return x + (bar - at) * (w / Math.max(1, n)) + ((beat || 1) - 1) * (w / Math.max(1, n) / 4); }
      x += wPx(s2); at += n;
    }
    return x + Math.max(0, bar - at) * Math.round(barSec * scale);
  };
  // mesure inverse (glisser) + mesure de départ d'une section
  const barAt = px => {
    let x = 0, at = 1;
    for (const s2 of sections) {
      const w = wPx(s2), n = Math.max(1, s2.bars || 1);
      if (px < x + w) return at + Math.floor(((px - x) / w) * n);
      x += w; at += (s2.bars || 0);
    }
    return at;
  };
  const barOfSection = i => sections.slice(0, i).reduce((a, s2) => a + (s2.bars || 0), 1);
  const sectionAtBar = bar => { let at = 1;
    for (const s2 of sections) { const n = s2.bars || 0;
      if (bar < at + n) return '— in ' + (s2.name || 'part'); at += n; }
    return '— past the end'; };
  const setMarks = next => onParam('samples', next);
  const addMark = (idx, blockId) => { const bar = sel != null ? barOfSection(sel) : 1;
    setMarks([...marks, { block: blockId || smpBlocks[0].id, idx, bar, beat: 1, anchor: 'start', stop: 'ring' }]);
    setSelMark(marks.length); };
  // ── ＋ FROM LIBRARY ──────────────────────────────────────────────────────────────────────
  // La bibliothèque complète (/api/kits — la même source que la feuille du bloc). On ajoute au
  // PREMIER lanceur, en « song only » : on vient de l'arrangement, pas du pédalier, et gonfler
  // la rotation au pied avec les sons du morceau est exactement ce que le drapeau §21 évite.
  const libAll = ((libD || {}).samples || []);
  const inBlock = new Set((((smpBlocks[0] || {}).params || {}).samples || []).map(fileOf));
  const libLeft = libAll.filter(s => !inBlock.has(s.file));
  const smpLabel = smpBlocks.length ? (smpBlocks[0].label || 'Sample') : '';
  const addFromLib = file => {
    const b = smpBlocks[0]; if (!b) return;
    const list = (b.params || {}).samples || [];
    const at = list.findIndex(e => fileOf(e) === file);
    // déjà présent : on ne duplique pas, on pose juste le marqueur sur l'entrée existante
    if (at >= 0) { addMark(at, b.id); setLibPick(false);
      setSaid('Already in ' + smpLabel + ' — marker set on it.'); return; }
    onSampleAdd(b.id, file);
    addMark(list.length, b.id);
    setLibPick(false);
    setSaid('Added to ' + smpLabel + ' · song only — put it on the foot from the block if you want it under the pedal.');
  };
  const patchMark = (mi, kv) => setMarks(marks.map((m, i) => i === mi ? { ...m, ...kv } : m));
  const delMark = mi => { setMarks(marks.filter((_, i) => i !== mi)); setSelMark(null); };
  const width = s => wPx(s) + 'px';
  const restWidth = () => restPx + 'px';
  const pxOf = s => wPx(s);
  const spanPx = sections.reduce((n, s) => n + wPx(s), 0) + (restBars > 0 ? restPx : 0);

  const sigLabel = s => { const g = sigOf(s, base); return g.num + '/' + g.den; };
  const changesSig = i => i === 0 ? isOwnSig(sections[0]) : sigLabel(sections[i]) !== sigLabel(sections[i - 1]);

  // ── REPÈRES DE MESURE (pas d'horloge) ────────────────────────────────────────────────────
  // On MARCHE les sections mesure par mesure : chacune a sa propre durée de mesure (7/8 ≠ 4/4),
  // donc l'abscisse d'une mesure ne se déduit d'aucune formule globale. Le NUMÉRO, lui, est
  // cumulatif et sans ambiguïté — une mesure reste une mesure, seule sa durée change.
  // Le pas suit la place disponible : on ne numérote pas toutes les 4 mesures s'il y a 3 px
  // entre deux (le contrat interdit de mentir, l'illisible est une façon de mentir).
  const allBars = sections.reduce((n, s) => n + (s.bars || 0), 0) + Math.max(0, restBars);
  // Densité -> pas de numérotation. On ne numérote pas toutes les 4 mesures s'il reste 3 px
  // entre deux : l'illisible est une façon de mentir.
  const dens = spanPx / Math.max(1, allBars);
  const step = dens >= 26 ? 4 : dens >= 13 ? 8 : 16;
  const ticks = [];
  const sigMarks = [];
  {
    let x = 0, bar = 1, prevSig = null;
    const walk = (bars, w, lb) => {
      if (prevSig !== null && lb !== prevSig) sigMarks.push({ x: x + 'px', sig: lb });
      prevSig = lb;
      for (let b = 0; b < bars; b++) {
        // l'abscisse d'une mesure DANS la région suit la même division que sa grille CSS
        // (`calc(100% / --bars)`), donc les traits et les numéros tombent au même endroit.
        if ((bar - 1) % step === 0) {
          ticks.push({ x: (x + Math.round((b * w) / Math.max(1, bars))) + 'px', bar,
                       strong: (bar - 1) % (step * 2) === 0 });
        }
        bar += 1;
      }
      x += w;
    };
    sections.forEach(s => walk(s.bars || 0, wPx(s), sigLabel(s)));
    // …ET LA ZONE LIBRE : la numérotation s'arrêtait là où le morceau n'était pas écrit.
    if (restBars > 0) walk(restBars, restPx, base.num + '/' + base.den);
  }

  return html`<div class="arrpage">
    <div class="arr-hd">
      ${/* l'onglet est une ICÔNE (▤) : sans titre, on ne sait pas où l'on arrive (retour) */''}
      <b class="arr-title">Arrangement</b>
      ${/* DEUX NIVEAUX, tous deux légitimes : le MODE dit si l'automation tourne dans cette
            situation, le PRESET si CE morceau en a une. Le bouton doit donc dire la vérité —
            « Armed » en mode Home était un mensonge : rien ne se serait déclenché. */''}
      ${modeOk === false
        ? html`<span class="ph-power off arr-modeoff"
            title="this mode does not run arrangements — open it in Settings ▸ Mode. You can still write it here.">
            ⏻ Off in ${esc(modeName || 'this mode')}</span>`
        : html`<button class=${cls('ph-power', block && block.bypass && 'off')} data-doc="arr.power" onClick=${onBypass}
            title=${block && block.bypass ? 'this song has no automation — tap to turn it on' : 'the scenes follow the parts when the song plays — tap to turn it off'}>
            ⏻ ${block && block.bypass ? 'Automation off' : 'Automation on'}</button>`}
      ${/* UN SEUL badge (agent UX 2026-07-31) : « 9 sections · 2:48 @120 » et « 84 / 123 bars »
            disaient deux moitiés de la même arithmétique — 206 px pour une information. Le
            dépassement du backing reste ce qu'on ne doit PAS découvrir sur scène : il prend
            tout le badge et sa couleur d'alerte. */''}
      <span class=${cls('arr-total', songSec && restBars < 0 && 'over')} data-doc="arr.total"
        title=${songSec ? (backingSec ? 'the linked backing track is ' + mmss(songSec) + ' long — that is the song'
                                      : 'song length declared in « song bars »') : 'what you have written'}>
        ${songSec && restBars < 0 ? '⚠ ' + (-restBars) + ' bars over' : html`
          ${sections.length} sec · ${mmss(written)} · ${writtenBars}${mapBars ? '/' + mapBars : songSec ? '/' + Math.round(songSec / barSec) : ''} bars @${bpm || 120}`}
      </span>
      <span class="grow"></span>
      ${/* ▶ PLAY / ■ STOP (2026-09-24) : la page où l'on ÉCRIT le morceau est aussi celle où on le
            LANCE — décompte (count-in, en mesures, dans la métrique de la première section), puis les scènes
            aux frontières, au tempo de la chanson. Le rig charge le preset de la chanson s'il ne joue pas déjà. */''}
      ${onPlay ? html`<div class="arr-transport">
        ${playing ? html`<button class="primary arr-stop" onClick=${onStop} title=${liveArr.backing ? 'stop the arrangement and the stems — the current scene stays' : 'stop the arrangement — the current scene stays'}>■ Stop</button>
            ${liveArr.counting ? html`<span class="arr-counting">count-in…</span>`
              : html`<span class="arr-now" title="section playing now">${esc(liveArr.name || '')}${liveArr.next ? html` <small>→ ${esc(liveArr.next)}</small>` : ''}</span>`}`
          : html`<button class="primary arr-play edit-only" data-doc="arr.play" disabled=${!sections.length || (block && block.bypass) || modeOk === false}
              title=${modeOk === false ? 'this mode does not run arrangements — Settings ▸ Mode' : !sections.length ? 'write a part first' : (block && block.bypass) ? 'automation is off for this song — turn it on first' : 'count-in, then the scenes follow the parts at ' + (bpm || 120) + ' BPM' + (backingLinked ? ' — and the stems start with the first part' : '')}
              onClick=${onPlay}>▶ Play</button>`}
      </div>` : ''}
    </div>

    ${/* ── WHEN THE SONG STARTS (docs/arrangement.md §5, FIGÉ 2026-10-07 — maquette
          mockups/arrangement-controls.html, écran 3) ── UNE rangée dit ce que lance le départ : le décompte (un
          seul), une case par bloc pilotable, le switch. Coché = part avec le morceau ; décoché = reste à la main.
          La petite ligne sous chaque case dit ce qui l'empêcherait de partir. Le nom ouvre le réglage du SON du
          bloc (onOpenBlock), la case ne règle que le QUAND. Switch et « next part » appartiennent au PRESET :
          étiquette « preset », ils valent pour toutes ses chansons (§4 bis). */''}
    <div class="arr-pop arr-ws" data-doc="arr.start">
      <span class="arr-ws-lb">When the song starts</span>
      <label class="arr-ci" data-doc="arr.count-in" title="bars counted BEFORE the song starts, in the first section's own meter. Always audible — even when the click stays silent for the song. A backing with its own count-in? Set 0.">
        count-in
        <input type="number" min="0" max="8" value=${pm.count_in || 0}
          onInput=${e => onParam('count_in', Math.max(0, Math.min(8, Number(e.target.value) || 0)))} />
      </label>
      ${startsRow.map(c => html`<div class=${cls('arr-ck', c.on && 'on', c.absent && 'absent')} style=${'--ckc:' + c.color}>
        ${c.absent ? html`<span class="arr-ck-box" title=${c.title}><i></i>${c.label}</span>`
          : html`<button class="arr-ck-box" title=${c.title} onClick=${() => setStart(c.key, !c.on)}><i>${c.on ? '✓' : ''}</i>${c.label}</button>`}
        <small class=${cls(c.warn && 'w')}>${c.sub}${c.action ? html` · <a onClick=${c.action.fn}>${c.action.label}</a>` : ''}</small>
      </div>`)}
      <span class="arr-ws-break"></span>
      <div class="arr-swpick" data-doc="arr.switch">
        <button class=${cls('arr-sw', 'arr-swbtn', block && block.foot && 'on')} title="the footswitch that starts the song — shared by every song on this preset"
          onClick=${e => { const r = e.currentTarget.getBoundingClientRect();
            setSwOpen(swOpen ? false : { x: Math.max(8, Math.min(r.left, window.innerWidth - 260)), y: r.bottom + 6 }); }}>switch ${(block && block.foot) || '—'} ▾</button><span class="arr-pre" title=${'shared by every song on the preset « ' + ((preset || {}).name || 'this preset') + ' » — the switch belongs to the pedalboard, not to the song'}>shared</span>
        ${/* FIXE, calé sous le bouton (2026-10-08) : ancré à droite d'un bouton collé au bord gauche, il sortait
              du panneau qui le coupait (overflow). Deux rangées comme le pédalier : 6-10 en haut, 1-5 en bas. */''}
        ${swOpen ? html`<div class="arr-swscrim" onClick=${() => setSwOpen(false)}></div><div class="arr-swpop" style=${`left:${swOpen.x}px;top:${swOpen.y}px`}>
          ${[6, 7, 8, 9, 10, 1, 2, 3, 4, 5].map(n => html`<button
            class=${cls('arr-sw', (block || {}).foot === n && 'on', taken.has(n) && 'busy')}
            title=${(taken.has(n) ? 'switch ' + n + ' is already used by another block' : 'switch ' + n)
              + (n <= 5 && scenes && scenes[n - 1] ? ' — scene ' + scenes[n - 1].id + ' can no longer be reached from the pedalboard' : '')}
            onClick=${() => { onFoot((block || {}).foot === n ? null : n); setSwOpen(false); }}>${n}</button>`)}
        </div>` : ''}
      </div>
      <span class="arr-ci">next part</span>
      <div class="tb-seg" data-doc="arr.advance" title="bars = the cues fire on their own (needs a click or a backing) · foot = one tap advances one section, no drift possible">
        <button class=${cls((pm.advance || 'bars') !== 'foot' && 'on')} onClick=${() => onParam('advance', 'bars')}>bars</button>
        <button class=${cls(pm.advance === 'foot' && 'on')} onClick=${() => onParam('advance', 'foot')}>foot</button>
      </div><span class="arr-pre" title=${'shared by every song on the preset « ' + ((preset || {}).name || 'this preset') + ' » — how the parts advance is a rule of the rig'}>shared</span>
      ${!backingSec ? html`<label class="arr-ci" title="how long the song is, in bars of the base signature. 0 = as long as what you have written. With a backing track linked, its real duration wins.">
        song bars
        <input type="number" min="0" max="999" value=${pm.bars || 0}
          onInput=${e => onParam('bars', Math.max(0, Math.min(999, Number(e.target.value) || 0)))} />
      </label>` : ''}
      ${/* CE QUE /LIVE MONTRE PENDANT LE MORCEAU (règle 2026-09-24 : l'arrangement suit le lecteur) — par
            chanson. Défaut = le pupitre pendant que ça joue ; « stomps » = je garde mon pédalier, une pastille suffit. */''}
      <span class="arr-ci" title="what the rack screen shows while this song plays">on /live</span>
      <div class="tb-seg" data-doc="arr.live-view" title="what the rack screen shows while this song plays: the stage board (parts, now/next, count-in) — or your stomps, with just a pill">
        <button class=${cls(pm.live_view !== 'Pedalboard' && 'on')} onClick=${() => onParam('live_view', null)}>Stage board</button>
        <button class=${cls(pm.live_view === 'Pedalboard' && 'on')} onClick=${() => onParam('live_view', 'Pedalboard')}>Stomps</button>
      </div>
      <span class="grow"></span>
      <div class="tb-seg" title="Fit = the whole song in view · Bars = a fixed width per bar, with ticks you can count">
        <button class=${cls(!barsMode && 'on')} onClick=${() => setZoom('fit')}>Fit</button>
        <button class=${cls(barsMode && 'on')} onClick=${() => setZoom('bars')}>Bars</button>
      </div>
    </div>

    ${/* ── LA PISTE, façon SD3 (référence docs/QC UI/SD3-Grooves.jpg) ────────────────────
          Trois corrections après la première revue : la règle compte des MESURES et non des
          minutes (« je veux des bars, pas une horloge ») ; la grille court sur TOUTE la zone,
          espace libre compris ; et la scène vit DANS le bloc, en seconde ligne — c'est ce que
          fait SD3 (« Hats Tight Tip » en tête, « Verse » en pied) et c'est ce qui rend sa
          timeline FINE. Une voie de cues séparée coûtait 26 px pour la même information. */''}
    ${/* ── LE HUD (2026-09-24 : « je suis en aveugle ») : pendant la lecture, ce qu'on doit lire à deux
          mètres — le décompte en grand (dans la métrique de la première section), NOW / NEXT, la scène
          active, la progression dans la section, écoulé / restant. Sur la page où l'on construit : on
          vérifie, on corrige, on relance sans bouger. Sur scène, /live montre le pupitre (même règle). */''}
    ${playing ? (() => {
      const now = Date.now() / 1000;
      if (liveArr.counting && liveArr.count_from && liveArr.count_to) {
        const s0 = sections[0] || {}, sg0 = sigOf(s0, base);
        const beatSec = (4 / (sg0.den || 4)) * (60 / (bpm || 120));
        const el = Math.max(0, now - liveArr.count_from), total = Math.max(0.001, liveArr.count_to - liveArr.count_from);
        const beat = Math.floor(el / beatSec), num = sg0.num || 4;
        const bar = Math.floor(beat / num) + 1, inBar = (beat % num) + 1;
        return html`<div class="arr-hud counting">
          <span class="arr-hud-lb">count-in</span>
          <b class="arr-hud-big">${inBar}</b>
          <span class="arr-hud-beats">${Array.from({ length: num }, (_, k) => html`<i class=${cls(k < inBar && 'on')}></i>`)}</span>
          <span class="arr-hud-sub">bar ${bar} of ${Math.max(1, Math.round(total / (beatSec * num)))} · ${sg0.num}/${sg0.den}</span>
          <span class="grow"></span>
          <span class="arr-hud-next">then <b>${esc((sections[0] || {}).name || '')}</b></span>
        </div>`;
      }
      const from = liveArr.sec_from || 0, to = liveArr.sec_to || 0;
      const f = to > from ? Math.max(0, Math.min(1, (now - from) / (to - from))) : 0;
      const sc = sceneObj(liveArr.scene);
      const elapsed = liveArr.started_at ? Math.max(0, now - liveArr.started_at) : 0;
      return html`<div class=${cls('arr-hud', liveArr.done && 'done')}>
        <span class="arr-hud-lb">${liveArr.done ? 'end' : 'now'}</span>
        <b class="arr-hud-big" style=${'--pc:' + sectionLook(sections[playIdx] || {}).color}>${esc(liveArr.name || '—')}</b>
        ${liveArr.scene ? html`<span class="arr-hud-sc" title=${sc && sc.name ? sc.name : 'scene'}><b>${esc(liveArr.scene)}</b>${sc && sc.name ? html` <small>${esc(sc.name)}</small>` : ''}</span>` : ''}
        <span class="arr-hud-bar"><i style=${'width:' + Math.round(f * 100) + '%'}></i></span>
        <span class="arr-hud-sub">${liveArr.bars ? liveArr.bars + ' bars' : ''} · ${mmss(elapsed)} / ${mmss(written)}</span>
        <span class="grow"></span>
        ${liveArr.next ? html`<span class="arr-hud-next">next <b>${esc(liveArr.next)}</b></span>` : html`<span class="arr-hud-next muted">last part</span>`}
      </div>`;
    })() : ''}
    ${/* la voie défile dans les DEUX zooms : en Fit aussi, dès que le plancher fait
          déborder la piste. La page, elle, ne défile jamais. */''}
    <div class="arr-lanes arr-zoomed" data-doc="arr.track" ref=${setTrackEl}>
      ${/* largeur EXPLICITE : les repères sont positionnés en absolu, ils ne poussent
            donc pas la règle. Sans ça elle s'arrête au bord de la vue et la
            numérotation semble s'interrompre en plein morceau. */''}
      <div class="arr-ruler" style=${`width:${spanPx}px`}>
        ${ticks.map(t => html`<span class=${cls('arr-tick', t.strong && 'arr-tick-hi')}
          style=${`left:${t.x}`}><b>${t.bar}</b></span>`)}
        ${sigMarks.map(m => html`<span class="arr-sigmark" style=${`left:${m.x}`}>⟨${m.sig}⟩</span>`)}
      </div>

      <div class="arr-track">
        ${!sections.length ? html`<p class="muted arr-empty">Nothing yet — pick a part below. They play
          end to end, in order, and each one fires its cues when it starts.</p>` : ''}
        ${sections.map((s, i) => {
          const w = pxOf(s);
          return html`<button data-doc=${'arr.part.' + (i + 1)}
            class=${cls('arr-sec', i === sel && 'arr-cur', !s.scene && 'arr-nocue', i === playIdx && 'arr-play',
              animClass(sectionLook(s).anim),
                        changesSig(i) && i > 0 && 'arr-sigcut', dragI === i && 'arr-lift')}
            style=${`width:${width(s)}; --pc:${sectionLook(s).color}; --bars:${Math.max(1, s.bars || 1)}`}
            title=${esc(s.name) + ' — ' + s.bars + (s.bars === 1 ? ' bar in ' : ' bars in ') + sigLabel(s) + ' · ' + mmss(secSeconds(s, base, bpm))}
            onPointerDown=${() => onSecDown(i)}
            onClick=${() => { if (!drag.current.moved) { setSel(i); setSelMark(null); setPartSheet(true); }
              drag.current.moved = false; }}>
            ${i === playIdx && liveArr.sec_to > liveArr.sec_from ? html`<i class="arr-phead" style=${'left:' + Math.round(Math.max(0, Math.min(1, (Date.now() / 1000 - liveArr.sec_from) / (liveArr.sec_to - liveArr.sec_from))) * 100) + '%'}></i>` : ''}
            ${w >= 18 ? html`<span class="arr-cap"><i class="arr-bn">${barStart[i]}</i>${w >= 46 ? esc(s.name) : ''}</span>` : ''}
            <span class=${cls('arr-body', (w / Math.max(1, s.bars)) >= 5 && 'arr-grid')}>
              <span class="arr-meta">
                ${s.scene ? html`<b class="arr-sc">${s.scene}</b>` : ''}${w >= 78 ? ' ' + s.bars + ' bars' : ''}
              </span>
            </span>
          </button>`;
        })}
        ${/* ⚠ LA ZONE VIDE NE CRÉE RIEN. Elle le faisait, et ça donnait un « part » anonyme —
              « le mode partition de gparted, c'est non » . On n'écrit pas un morceau en
              découpant du vide : on pose une partie NOMMÉE depuis la bibliothèque, puis on la
              déplace. Le vide est un ÉTAT, pas un bouton. */''}
        ${restBars > 0 ? html`<div class="arr-rest" style=${`width:${restWidth()}; --bars:${restBars}`}
          title=${restBars + ' bars of the song not written yet'}></div>` : ''}
      </div>


      ${/* ── LANE DE SAMPLES (docs/arrangement.md §14) ────────────────────────────────────
            Un marqueur vit à une MESURE DU MORCEAU, pas dans une section : un riser traverse
            une frontière, un sub-drop tombe au milieu d'un solo. Elle partage la largeur et
            l'échelle de la piste (mêmes wPx cumulés — jamais un calcul parallèle, sinon les
            deux divergent vers la droite, cf. le décalage règle/grille déjà vécu).
            CONDITIONNELLE : un morceau sans bloc sample ne paie pas ses 34 px. */''}
      ${smpBlocks.length ? html`<div class="arr-smplane" style=${`width:${spanPx}px`}
        title="samples fired by the song — tap a marker to set it, drag to move it">
        <span class="arr-smplane-lb">SMP</span>
        ${marks.map((m, mi) => html`<button
          class=${cls('arr-mark', selMark === mi && 'on', m.anchor === 'land' && 'land')}
          style=${`left:${barX(m.bar, m.beat)}px`}
          title=${(smpName(m) || 'sample') + ' — bar ' + m.bar + (m.anchor === 'land' ? ' (lands here)' : '')
                  + (m.stop === 'section' ? ' · cut at next section' : ' · lets it ring')}
          onPointerDown=${() => onMarkDown(mi)}
          onClick=${() => { if (!drag.current.moved) { setSelMark(mi); setSel(null); } drag.current.moved = false; }}>
          <i>${m.anchor === 'land' ? '◗' : '▸'}</i>${esc(smpName(m) || '—')}
        </button>`)}
      </div>` : ''}
    </div>

    ${smpBlocks.length ? html`<div class="arr-smpadd">
      ${/* poser un marqueur : on choisit LE SAMPLE, il se pose à la mesure de la section
            sélectionnée (ou à 1). Pas de zone vide cliquable — même loi que les parties :
            « le vide est un ÉTAT, pas un bouton ». */''}
      ${(smpBlocks[0].params.samples || []).map((f, i) => html`<button class="arr-smpchip"
        title=${'add « ' + fileLabel(f) + ' » at bar ' + (sel != null ? barOfSection(sel) : 1)}
        onClick=${() => addMark(i)}>▸ ${esc(fileLabel(f))}</button>`)}
      ${/* ＋ FROM LIBRARY (§21) : la lane ne montre que ce que le BLOC porte déjà. Sans ça, il
            fallait quitter l'arrangement, ouvrir ⚙ Config, la tuile, la feuille, ajouter, et
            revenir — pour un son qu'on voulait poser à la mesure 21. Le chip fait le trajet à
            notre place ET LE DIT : on écrit dans un autre bloc que celui qu'on édite, une
            modification silencieuse serait un piège. */''}
      ${onSampleAdd ? html`<button class=${cls('arr-smpchip', 'arr-smpmore', libPick && 'on')}
        title="pick a sample from Library ▸ Samples — it joins this block, for the song only"
        onClick=${() => setLibPick(!libPick)}>＋ from library</button>` : ''}
    </div>` : ''}

    ${libPick && onSampleAdd ? html`<div class="arr-smplib">
      ${libLeft.length ? libLeft.map(s => html`<button class="p-chip"
        title=${'add « ' + esc(s.name) + ' » to ' + (smpBlocks[0].name || 'the sample block')
                + ' and drop a marker at bar ' + (sel != null ? barOfSection(sel) : 1)}
        onClick=${() => addFromLib(s.file)}>${esc(s.name)}</button>`)
        : html`<span class="muted">Library ▸ Samples is empty (or everything is already in this block).</span>`}
    </div>` : ''}
    ${libSaid ? html`<p class="arr-said">${esc(libSaid)}</p>` : ''}

    <div class="arr-lib" data-doc="arr.library">
      ${PART_LIBRARY.map(n => html`<button class="arr-part" style=${`--pc:${PART_COLOR[n]}`}
        title=${(/^[aeiou]/i.test(n) ? 'add an ' : 'add a ') + n + ' — 4 bars at the end, then drag it where you want'} onClick=${() => add(n)}>${n}</button>`)}
      <button class="arr-part arr-free" title="a section with a name of your own" onClick=${() => add('part')}>+ custom</button>
    </div>

    ${/* LA MÊME FEUILLE, autre contenu (direction B) : un marqueur de sample ne coûte donc
          pas un pixel de panneau — c'est l'argument qui a fait choisir la feuille. */''}
    ${selMark != null && marks[selMark] ? (() => {
      const m = marks[selMark];
      const b = smpBlocks.find(x => x.id === m.block) || smpBlocks[0];
      return html`<div class="sheet-scrim arr-scrim" onClick=${e => e.target.classList.contains('arr-scrim') && setSelMark(null)}>
       <div class="sheet arr-sheet arr-sheet-mark">
        <button class="sheet-tab arr-sheet-tab" style="--tc:var(--sect,#e5468f)"
          title="close" onClick=${() => setSelMark(null)}>
          <span class="sheet-ic">▸</span><b>${esc(smpName(m) || 'sample')}</b><span class="sheet-tab-x">▾</span></button>
        <div class="arr-d-cols">
          <div class="arr-d-col arr-d-col-set">
            <div class="arr-d-row"><span class="arr-d-lb">Sample</span>
              <div class="arr-chips">
                ${((b || {}).params?.samples || []).map((f, i) => html`<button
                  class=${cls('arr-chip', m.idx === i && 'on')}
                  onClick=${() => patchMark(selMark, { idx: i })}>${esc(fileLabel(f))}</button>`)}
              </div>
            </div>
            <div class="arr-d-row"><span class="arr-d-lb">Bar</span>
              <div class="arr-chips" style="align-items:center">
                <input type="number" class="arr-mk-num" min="1" max="999" value=${m.bar}
                  onInput=${e => patchMark(selMark, { bar: Math.max(1, Math.min(999, Number(e.target.value) || 1)) })} />
                <span class="muted" style="font-size:11px">· beat</span>
                <input type="number" class="arr-mk-num" min="1" max="16" value=${m.beat || 1}
                  onInput=${e => patchMark(selMark, { beat: Math.max(1, Math.min(16, Number(e.target.value) || 1)) })} />
                <span class="muted" style="font-size:11px">${sectionAtBar(m.bar)}</span>
              </div>
            </div>
          </div>
          <div class="arr-d-col arr-d-col-lanes">
            ${/* L'ANCRE : un riser ne se DÉCLENCHE pas à la mesure 21, il doit y ARRIVER. Le
                  rack connaît la durée du WAV et recule le départ. Sans ça on pose les risers
                  à l'oreille en tâtonnant (docs/arrangement.md §14). */''}
            <div class="arr-d-row"><span class="arr-d-lb">Anchor</span>
              <div class="arr-chips" style="align-items:center">
                <div class="tb-seg">
                  <button class=${cls(m.anchor !== 'land' && 'on')}
                    title="the sample STARTS at this bar" onClick=${() => patchMark(selMark, { anchor: 'start' })}>▸ starts at</button>
                  <button class=${cls(m.anchor === 'land' && 'on')}
                    title="the sample LANDS on this bar — the rack backs off by its length" onClick=${() => patchMark(selMark, { anchor: 'land' })}>◗ lands at</button>
                </div>
              </div>
            </div>
            <div class="arr-d-row"><span class="arr-d-lb">Stop</span>
              <div class="arr-chips" style="align-items:center">
                <div class="tb-seg">
                  <button class=${cls(m.stop !== 'section' && 'on')}
                    title="it rings out — other samples can overlap it" onClick=${() => patchMark(selMark, { stop: 'ring' })}>let it ring</button>
                  <button class=${cls(m.stop === 'section' && 'on')}
                    title="cut when the next section starts" onClick=${() => patchMark(selMark, { stop: 'section' })}>next section</button>
                </div>
                <button class="mini danger" title="remove this marker"
                  onClick=${() => delMark(selMark)}>🗑</button>
              </div>
            </div>
          </div>
        </div>
       </div>
      </div>`;
    })() : ''}

    ${/* ── LE GRAND TIROIR (2026-09-10) ────────────────────────────────────────────────
          En ligne on ne garde que le SIMPLE : la frise et les puces qui créent les parties. Tout le
          reste — l'identité de la partie, les entrées, la grille du morceau entier — s'ouvre EN GRAND
          au clic sur une partie. La zone en ligne faisait cent pixels de haut : rien n'y tenait. */''}
    ${partSheet && cur ? (() => {
      const sg = sigOf(cur, base);
      const own = isOwnSig(cur);
      const setSig = kv => patch(sel, { sig: { ...sg, ...kv } });
      const gSum = (sg.groups || []).reduce((a, b) => a + b, 0);
      // ── FEUILLE BASSE (direction B de l'agent UX, 2026-07-31) ────────────────────────
      // Le panneau ne tenait déjà pas AVANT les samples : −17 px à 1024, −128 à 800 (45 % hors
      // champ). Le pilote de hauteur était la colonne des instruments, haute PARCE QU'ELLE EST
      // ÉTROITE. En pleine largeur la grille passe de 3 à 7 colonnes : Guitar tombe de 100 à
      // 30 px SANS RIEN RETIRER. Et un marqueur de sample ouvrira la MÊME feuille : la lane
      // ne coûte alors pas un pixel de panneau.
      // Motif repris du Designer (.sheet-scrim/.sheet + poignée) — pas un second idiome de tiroir.
      return html`<div class="sheet-scrim arr-scrim" onClick=${e => e.target.classList.contains('arr-scrim') && setPartSheet(false)}>
       <div class=${cls('sheet', 'arr-sheet', blkOpen && 'tall')} data-doc="arr.part-sheet">
        <button class="sheet-tab arr-sheet-tab" style=${`--tc:${sectionLook(cur).color}`}
          title="close" onClick=${() => setPartSheet(false)}>
          <span class="sheet-ic">▤</span><b>${esc(cur.name || 'part')}</b><span class="sheet-tab-x">▾</span></button>
        ${/* MINI-BANDE : garde le contexte quand la feuille couvre la piste, et remplace les
              ←/→ retirés — on tape la section suivante SANS jamais fermer. */''}
        <div class="arr-d-hd">
          ${/* LA PASTILLE PORTE LE LOOK (2026-09-10) : la couleur et l'animation d'une partie
                vivaient dans une rangée du tiroir, loin de la pastille qui les MONTRE. Elles sont
                maintenant DEDANS, au clic — une rangée de moins, et l'objet qu'on règle est celui
                qu'on regarde. Cascade honnête, inchangée : rien de choisi = la scène décide, pas de
                scène = la couleur de la partie. */''}
          ${/* LA PASTILLE MONTRE le look ; le régler se fait DANS le tiroir (colonne Look), plus dans un
                popover — il s'ouvrait sous le bord de l'écran (mesuré à y=585 sur 600, 2026-09-24). */''}
          <button class=${cls('arr-d-dot', (cur.look || {}).color || (cur.look || {}).anim != null ? 'ovr' : '')}
            style=${'--pc:' + sectionLook(cur).color} title="color and animation of this part — tap to set them"
            onClick=${() => { setLookOpen(!lookOpen); setSigOpen(false); }}></button>
          <input class="arr-d-nm" value=${cur.name} onInput=${e => patch(sel, { name: e.target.value.slice(0, 24) })} />
          <label class="arr-d-bars">bars
            <${CountField} value=${cur.bars} min=${1} max=${512} onCommit=${n => patch(sel, { bars: n })} /></label>
          ${/* LA SCÈNE, EN CLAIR (2026-09-24 : il l'a cherchée, elle se « cyclait » en tapant une case).
                Un bouton par scène du preset, avec son nom ; « same » = rien de posé ici, la scène d'avant
                continue. C'est LE réglage qui fait qu'une section fait quelque chose au pied. */''}
          ${/* « same » RETIRÉ (2026-10-08 : « à quoi sert-il ? ») — sa fonction reste, dite autrement : une partie
                sans scène montre EN POINTILLÉS celle qui continue (posée plus tôt), et re-taper la scène allumée l'enlève. */''}
          <div class="arr-scpick" title="the scene this part switches to — the whole rig follows. Tap the lit one again to clear it: the scene before keeps playing">
            ${sceneIds.map(id => { const so = sceneObj(id);
              const inh = !cur.scene && sceneAt(sel) === id;
              return html`<button class=${cls('arr-scbtn', cur.scene === id && 'on', inh && 'cont')}
                title=${cur.scene === id ? 'set here — tap again to clear it (the scene before keeps playing)'
                  : inh ? 'scene ' + id + ' keeps playing from an earlier part — tap to set it here' : (so && so.name ? so.name : 'scene ' + id)}
                onClick=${() => patch(sel, { scene: cur.scene === id ? null : id })}>
                <b>${id}</b>${so && so.name && so.name !== id ? html`<small>${esc(so.name)}</small>` : ''}</button>`; })}
          </div>
          ${/* SIGNATURE : une puce « 4/4 » (pointillée = héritée) ; le réglage s'ouvre dans un panneau */''}
          <button class=${cls('arr-sigchip', !own && 'inh')} title=${own ? 'this part has its own signature — tap to change' : 'inherited from the song — tap to give this part its own'}
            onClick=${() => { setSigOpen(!sigOpen); setLookOpen(false); setDrumOpen(false); }}>${sg.num}/${sg.den}</button>
          ${drumBlk && drumPats.length ? (() => { const v = drumsAt(sections, sel); const own = cur.drums != null;
            return html`<button class=${cls('arr-sigchip', 'arr-drumchip', !own && 'inh')}
              title=${(own ? 'the groove of this part' : 'the groove of an earlier part keeps playing') + ' — tap to choose'}
              onClick=${() => { setDrumOpen(!drumOpen); setSigOpen(false); setLookOpen(false); }}>🥁 ${v === 'stop' ? 'stop' : grooveName(drumPats[v] || drumPats[0])}</button>`; })() : ''}
          <span class="arr-d-len">${mmss(secSeconds(cur, base, bpm))} · bars ${barStart[sel]}–${barStart[sel] + Math.max(1, cur.bars || 1) - 1}</span>
          <span class="grow"></span>
          <button class="mini" disabled=${sel <= 0} title="previous part" onClick=${() => { setSel(sel - 1); setLookOpen(false); setSigOpen(false); }}>‹</button>
          <button class="mini" disabled=${sel >= sections.length - 1} title="next part" onClick=${() => { setSel(sel + 1); setLookOpen(false); setSigOpen(false); }}>›</button>
          ${drumOpen && drumBlk ? html`<div class="arr-pop2 arr-pop-sig">
            <div class="arr-d-row"><span class="arr-d-lb">Drums</span>
              <div class="arr-chips">
                ${drumPats.map((f, k) => html`<span class=${cls('arr-chip', cur.drums === k && 'on')} title=${f}
                  onClick=${() => { patch(sel, { drums: k }); setDrumOpen(false); }}>${grooveName(f)}</span>`)}
                <span class=${cls('arr-chip', cur.drums === 'stop' && 'on')} title="the drums stop at the start of this part"
                  onClick=${() => { patch(sel, { drums: 'stop' }); setDrumOpen(false); }}>stop</span>
                ${cur.drums != null ? html`<button class="mini" title="keep the groove of the part before"
                  onClick=${() => { patch(sel, { drums: null }); setDrumOpen(false); }}>↺ inherit</button>` : ''}
              </div></div>
            <p class="muted arr-d-hint">The groove changes on the first beat of this part — golem sends it during the last beat before.</p>
          </div>` : ''}
          ${sigOpen ? html`<div class="arr-pop2 arr-pop-sig">
            <div class="arr-d-row"><span class="arr-d-lb">Signature</span>
              <div class="arr-sigctl">
                <input type="number" min="1" max="32" value=${sg.num}
                  onInput=${e => setSig({ num: Math.max(1, Math.min(32, Number(e.target.value) || 4)) })} />
                <span class="arr-slash">/</span>
                <select onChange=${e => setSig({ den: Number(e.target.value) })}>
                  ${DENOMINATORS.map(d => html`<option value=${d} selected=${sg.den === d}>${d}</option>`)}
                </select>
                ${own ? html`<button class="mini" title="follow the song's signature again"
                    onClick=${() => patch(sel, { sig: null })}>↺ inherit</button>`
                      : html`<span class="muted arr-inherit">inherited ${base.num}/${base.den}</span>`}
              </div>
            </div>
            ${(COMMON_GROUPS[sg.num] || []).length ? html`<div class="arr-d-row"><span class="arr-d-lb">Accents</span>
              <div class="arr-chips">
                ${(COMMON_GROUPS[sg.num] || []).map(g => html`<span
                  class=${cls('arr-chip', (sg.groups || []).join('+') === g.join('+') && 'on')}
                  title=${'count it ' + g.join('+')} onClick=${() => setSig({ groups: g })}>${g.join('+')}</span>`)}
                <span class=${cls('arr-chip', !sg.groups && 'on')} title="accent the first pulse only"
                  onClick=${() => setSig({ groups: null })}>flat</span>
                ${sg.groups && gSum !== sg.num ? html`<span class="arr-warn"
                  title="the groups must add up to the numerator">⚠ ${gSum} ≠ ${sg.num}</span>` : ''}
              </div>
            </div>` : ''}
            ${sg.num !== 4 || sg.den !== 4 ? html`<p class="muted arr-d-hint">Nobody counts a 7 flat —
              you count it 3+2+2. The click accents the first pulse of each group.</p>` : ''}
          </div>` : ''}
          ${lookOpen ? (() => {
            const lk = sectionLook(cur);
            const lown = (cur.look || {});
            const setLook = d => patch(sel, { look: { ...lown, ...d } });
            const isOwn = !!(lown.color || lown.anim != null);
            return html`<div class="arr-pop2 arr-pop-look">
              <b>Look of « ${esc(cur.name || 'part')} »</b>
              <div class="arr-chips arr-look">
                <span class=${cls('arr-swatch', !lown.color && 'on')} title="auto — the color that goes with this part's name"
                  style=${'--pc:' + lk.color} onClick=${() => setLook({ color: null })}>auto</span>
                ${SCENE_FALLBACK.map(c => html`<span class=${cls('arr-swatch', lown.color === c && 'on')}
                  style=${'--pc:' + c} title=${'use ' + c} onClick=${() => setLook({ color: c })}></span>`)}
              </div>
              <div class="arr-chips">
                <button class=${cls('arr-animbtn', animClass(lk.anim))} style=${'--pc:' + lk.color}
                  title="animation shown on the Live timeline — tap to choose (it plays in the picker)"
                  onClick=${() => setAnimPick(true)}>
                  <span>${(ANIM_STYLES.find(a => a[0] === lk.anim) || ANIM_STYLES[0])[1]}</span></button>
                ${isOwn ? html`<button class="mini" title="back to auto — the color that goes with this part's name"
                  onClick=${() => patch(sel, { look: null })}>↺ auto</button>` : ''}
              </div>
              <p class="muted arr-d-hint">A part keeps its color from one rehearsal to the next.</p>
              ${animPick ? html`<${EffectPicker} current=${lk.anim} pc=${lk.color}
                onPick=${v => { setLook({ anim: v }); setAnimPick(false); }} onClose=${() => setAnimPick(false)} />` : ''}
            </div>`;
          })() : ''}
        </div>
        ${/* ── LE MORCEAU ENTIER, PAR ENTRÉE (maquette A) : on choisit un musicien, on lit et on
              écrit ses changements d'un bout à l'autre — la partie ouverte est mise en avant. C'est
              ce qui remplace les rangées « Scene » et « Stomps » de cette feuille : elles ne
              parlaient que d'UNE partie et se lisaient bloc par bloc. ── */''}
        ${/* ── LA BANDE D'ENTRÉES : un musicien = une lane = une entrée de la carte. On en choisit un,
              et la grille ci-dessous ne montre QUE ses changements — c'est ce qui rendait l'écran
              illisible à sept lanes (2026-09-10). Le compte dit s'il bouge dans ce morceau. */''}
        ${ents.length ? html`<div class="arr-who">
          ${/* LES OUTILS DE LA PARTIE vivent ICI, hors du tableau (2026-10-08 : une ligne d'outils au milieu
                « casse la dynamique de tableau bien aligné » — le rail des parties est le titre de ses colonnes) */''}
          ${(() => { const tools = html`<span class="arr-ptools">
            <b class="muted">part ${sel + 1}/${sections.length}</b>
            <button class="mini" disabled=${sel <= 0} onClick=${() => move(sel, -1)} title="move this part one place left (or hold it in the rail and drag)">◀</button>
            <button class="mini" disabled=${sel >= sections.length - 1} onClick=${() => move(sel, 1)} title="move this part one place right (or hold it in the rail and drag)">▶</button>
            <button class="mini" onClick=${() => dup(sel)} title="duplicate — a copy of this part, right after it">⧉</button>
            <button class="mini danger" onClick=${() => del(sel)} title="delete this part from the song">🗑</button>
            ${onNewScene ? html`<button class="mini arr-newsc" onClick=${() => onNewScene(sel)}
              title=${'a new scene named « ' + (cur.name || 'part') + ' », starting from the scene playing here — then pick what each lane plays in it'}>＋ Scene</button>` : ''}
            ${onScenes ? html`<button class="mini" onClick=${onScenes} title="what each lane plays in each scene — Designer ▸ Scenes">▦</button>` : ''}
          </span>`; return tools; })()}
          ${ents.map(e => { const n = entMoves(e), w2 = entWho(e);
            return html`<button class=${cls('arr-wcard', cur3 && e.id === cur3.id && 'on', !n && 'quiet')}
              title=${e.name + ' · ' + entPort(e) + (w2 ? ' — ' + w2 : '')
                      + ' · ' + (n ? n + ' part' + (n > 1 ? 's' : '') + ' change something' : 'never changes anything in this song')}
              onClick=${() => setWho(e.id)}>
              <span class="arr-wava">${ROLE_ICON[e.role] || (e.midi ? '🎹' : '·')}</span>
              <span class="arr-wt"><b>${esc(e.name)}</b><small>${entPort(e)}${w2 ? ' · ' + esc(w2) : ''}</small></span>
              <span class="arr-wn">${n}</span></button>`; })}
        </div>` : ''}
          ${/* ── LA GRILLE PAR ENTRÉE ────────────────────────────────────────────────────────────
                DANS le conteneur qui défile, et avec les MÊMES largeurs que les sections : c'est ce
                qui garantit qu'une case reste sous sa partie dans les deux zooms. Un calcul parallèle
                divergerait vers la droite — on l'a déjà vécu entre la règle et la grille. ── */''}
          ${cur3 ? html`<div class="arr-sheetgrid"><div class="arr-rows">
            ${/* ── LE RAIL DES PARTIES (maquette arr-drawer-v2, écran 2) : chaque partie avec sa mesure de départ ; on la
                  déplace à l'appui long + glisser, ou avec les outils juste dessous (◀ ▶, dupliquer, supprimer) ── */''}
            <div class="arr-grow arr-g-struct">
              <span class="arr-g-lb"><b>Song</b></span>
              <div class="arr-g-cells">
                ${sections.map((s2, i) => html`<button class=${cls('arr-cell', 'arr-cell-part', i === sel && 'cur', dragI === i && 'arr-lift')}
                  style=${`width:${width(s2)}; --pc:${sectionLook(s2).color}`}
                  title=${(s2.name || 'part') + ' — bar ' + barStart[i] + ', ' + s2.bars + ' bars · tap to edit · hold and drag to move'}
                  onPointerDown=${() => onSecDown(i, '.arr-sheet .arr-g-struct .arr-cell-part')}
                  onClick=${() => { if (drag.current.moved) { drag.current.moved = false; return; } setSel(i); }}>
                  <i class="arr-bn">${barStart[i]}</i>${esc(s2.name || 'part')}</button>`)}
              </div>
            </div>
            <div class="arr-grow">
              <span class="arr-g-lb"><b>Scene</b><em title="a scene is the whole rig — it changes for everyone">all</em></span>
              <div class="arr-g-cells">
                ${/* ── UNE SCÈNE HÉRITÉE N'EST PAS UNE VALEUR, C'EST LA MÊME QUI CONTINUE ────────
                      La case portait la LETTRE héritée : changer la scène du couplet faisait donc
                      « bouger » le pré-refrain d'à côté, qui n'a pourtant rien d'écrit. Le
                      comportement était juste, sa lecture ne l'était pas — « pas facile à capter »
                      (2026-09-10). La continuation est maintenant une BARRE, sans lettre :
                      comme une cellule fusionnée, la valeur ne s'écrit qu'une fois, là où elle est
                      posée. Elle ne peut donc plus avoir l'air de changer toute seule. La lettre
                      reste dans l'infobulle, avec le nom de la partie qui la pose. */''}
                ${sections.map((s2, i) => { const at = sceneAt(i);
                  const src = !s2.scene && at ? (sections.slice(0, i).reverse().find(x => x.scene) || {}).name : null;
                  return html`<button class=${cls('arr-cell', 'arr-cell-sc', s2.scene ? 'set' : (at ? 'cont' : 'none'))}
                    style=${`width:${width(s2)}`} onClick=${() => cycleScene(i)}
                    title=${(s2.name || 'part') + (s2.scene ? ' — scene ' + s2.scene + ', set here'
                              : at ? ' — scene ' + at + ' keeps playing, set on « ' + (src || 'a part before') + ' »'
                                   : ' — no scene yet, and none before')
                            + ' · tap to change'}>
                    ${s2.scene || (at ? '' : '·')}</button>`; })}
              </div>
            </div>
            ${/* ── L'ACCORD, PAR LANE (docs/band-scenes.md, écran 2) : ce que chaque musicien joue dans chaque
                  partie — le nom de l'état que la scène y choisit, sinon le bloc qui fait l'identité de la
                  lane. EN LECTURE : on n'écrit ici que la scène (un seul axe, arrangement.md §3). Même
                  état que la partie d'avant = pointillé, sans répéter le nom qu'on vient de lire. ── */''}
            ${arrLanes.map(L => html`<div class="arr-grow arr-g-lane">
              <span class="arr-g-lb" title=${L.name + ' — reads the scene'}><i>${ROLE_ICON[L.role] || (L.midi ? '🎹' : '·')}</i><b>${esc(L.name)}</b></span>
              <div class="arr-g-cells">
                ${sections.map((s2, i) => { const sc = sceneObj(sceneAt(i));
                  if (!sc) return html`<span class="arr-cell arr-cell-ln none" style=${`width:${width(s2)}`}>·</span>`;
                  const st = laneStateAt(preset, L, sc);
                  const psc = i > 0 ? sceneObj(sceneAt(i - 1)) : null;
                  const same = !!psc && (laneStateAt(preset, L, psc) || {}).id === (st || {}).id;
                  const muted = laneMutedIn(sc, L);
                  const nm = laneLineName(preset, L, sc);
                  return html`<span class=${cls('arr-cell', 'arr-cell-ln', same && 'same', muted && 'mute', st && st.implicit && 'own')}
                    style=${`width:${width(s2)}`}
                    title=${(s2.name || 'part') + ' — ' + L.name + ' plays ' + (muted ? 'nothing (muted in scene ' + sc.id + ')' : '« ' + nm + ' »')
                            + ' · scene ' + sc.id + (same ? ', same as the part before' : '')}>${muted ? 'muted' : same ? '' : esc(nm)}</span>`; })}
              </div>
            </div>`)}
            ${/* ── LES BLOCS PAR PARTIE, REPLIÉS (2026-10-08 : « les stomps ne devraient pas être visibles sans
                  déplier un accordéon ») : le résumé dit combien de blocs CETTE partie force — c'est ce qui dit s'il
                  vaut la peine de l'ouvrir. ── */''}
            ${cur3.blocks.length ? (() => { const forced = cur3.blocks.filter(bk => effOf(sel, bk).forced).length;
              return html`<button class=${cls('arr-acc', blkOpen && 'open')} onClick=${() => setBlkOpen(!blkOpen)}>
                <b>${blkOpen ? '▾' : '▸'} Blocks per part</b>
                <small>${cur3.blocks.length} block${cur3.blocks.length > 1 ? 's' : ''} · ${cur3.blocks.slice(0, 4).map(bk => bk.name).join(', ')}${cur3.blocks.length > 4 ? '…' : ''}</small>
                ${forced ? html`<em>${forced} set in « ${esc(cur.name || 'part')} »</em>` : ''}
                <span class="grow"></span><small>${blkOpen ? 'tap to fold' : 'tap to open'}</small></button>`; })() : ''}
            ${cur3.blocks.length && blkOpen ? html`<div class="arr-blkscroll">${[...cur3.blocks].sort((x, y) => (x.foot ? 0 : 1) - (y.foot ? 0 : 1) || (x.foot || 0) - (y.foot || 0)).map(bk => html`<div class="arr-grow">
              <span class="arr-g-lb"><i>${ICON[bk.type] || '•'}</i><b>${esc(bk.name)}</b>${bk.foot ? html`<em>SW${bk.foot}</em>` : ''}</span>
              <div class="arr-g-cells">
                ${sections.map((s2, i) => { const e2 = effOf(i, bk);
                  return html`<button class=${cls('arr-cell', e2.on ? 'on' : 'off', !e2.forced && 'inh')}
                    style=${`width:${width(s2)}`} onClick=${() => cycleBlock(i, bk.id)}
                    title=${(s2.name || 'part') + ' — ' + bk.name + ' : ' + (e2.on ? 'on' : 'off')
                      + (e2.forced ? ' (forced by this part)' : ' (from scene ' + (sceneAt(i) || '—') + ')')
                      + ' · tap: on → off → follow the scene'}>
                    ${e2.on ? 'on' : 'off'}</button>`; })}
              </div>
            </div>`)}</div>` : cur3.blocks.length ? '' : html`<div class="arr-none">
              <span class="arr-none-ic">${ROLE_ICON[cur3.role] || (cur3.midi ? '🎹' : '·')}</span>
              <b>${esc(cur3.name)}</b>
              <span>${entPort(cur3)}${entWho(cur3) ? ' · ' + esc(entWho(cur3)) : ''} — nothing to switch here</span>
              <em>add pedals to this lane in the Designer, then they show up as rows</em>
            </div>`}
          </div></div>` : ''}
       </div>
      </div>`;
    })() : ''}
  </div>`;
}

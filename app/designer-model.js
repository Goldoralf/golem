// SPDX-License-Identifier: GPL-3.0-or-later
// Modèle du Designer — constantes, couleurs/glyphes, normalisation de chaîne. PUR (zéro DOM/fetch).
import { post, html } from './lib.js';
import { ICONS } from './icons.js';
import { GLYPHS } from './glyphs.js';

export const SCENE_IDS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

// La clé de catalogue d'un `ref` de capture. Deux formes désignent le même tone : l'id du catalogue (« 36827 », ce
// que le Designer écrit) et l'UID DE PACK (« t3k:36827 », ce que portent les patches de golem.fm). Le moteur accepte
// les deux (bridge/resolver.py `_resolve`) ; le tiroir ne connaissait que la première — le potard « Capture »
// disparaissait sur tout bloc venu de golem.fm (2026-10-13, « Singing Clean »).
export const refKey = r => String(r == null ? '' : r).replace(/^.*\//, '').replace(/^t3k:/, '');

// L'id d'une scène EST sa position (A = 1re, B = 2e…) : c'est ainsi qu'`addScene` les crée et que
// la barre de scènes les affiche. Supprimer la scène B laissait [A, C] — et la barre montrait
// « A C C » (le slot suivant s'appelle SCENE_IDS[longueur]). Mesuré sur le patch 1983,
// 2026-09-14. Ici, la RÈGLE : toute édition et tout chargement rendent les ids positionnels.
// Rend le document tel quel (muté) ; rien d'autre dans le document ne pointe une scène par id.
// UNE TÊTE A TOUJOURS SON BAFFLE, VISIBLE (2026-09-14 : « quand on a un bloc head il faut le cab
// derrière, ça n'a pas de sens sinon, il faut que cela s'affiche »). Le compile fondait un Mesa 4x12 par
// défaut derrière une tête isolée SANS le montrer : Sunfunk faisait passer un Fender Twin dans un Recto
// sans que personne le voie. Ici, une tête (`amp-nam`) sans `cab` ni `amp` après elle dans sa zone
// reçoit un bloc cab VIDE juste derrière — IR à choisir en tapant dessus ; vide, le compile y met le
// même défaut qu'avant, donc le son ne change pas, mais le baffle existe et se règle. Appliqué à
// chaque édition et chargement (setP), comme renumberScenes.
export function ensureHeadCabs(p) {
  const fix = arr => {
    if (!Array.isArray(arr)) return;
    for (let i = 0; i < arr.length; i++) {
      const b = arr[i];
      if (!b || b.type !== 'amp-nam') continue;
      const after = arr.slice(i + 1);
      if (!after.some(x => x && (x.type === 'cab' || x.type === 'amp'))) arr.splice(i + 1, 0, { type: 'cab', id: bid('cab') });
    }
  };
  const chain = c => { if (!c) return; fix(c.pre); fix(c.post); fix(c.chain); (((c.split || {}).branches) || []).forEach(br => fix(br.blocks)); };
  (p.lanes || []).forEach(L => chain(L.chain));
  chain(p.guitar); chain(p.voice); chain(p.keys);
  return p;
}

// LA WHAMMY EST TOUJOURS PREMIÈRE (2026-09-14, Hollow Choir : golem.fm l'avait posée après gate et
// comp, et le Designer, qui l'épingle en tête et refuse de la déplacer, laissait le mainteneur coincé). C'est
// une pédale PHYSIQUE, branchée avant l'interface : sa place dans la chaîne est la première, par
// nature, quel que soit l'auteur du patch. Appliqué à chaque édition et chargement (setP).
export function pinWhammyFirst(p) {
  const fix = arr => {
    if (!Array.isArray(arr)) return;
    const i = arr.findIndex(b => b && b.type === 'whammy-dt');
    if (i > 0) arr.unshift(arr.splice(i, 1)[0]);
  };
  (p.lanes || []).forEach(L => L.chain && fix(L.chain.pre));
  if (p.guitar) fix(p.guitar.pre);
  return p;
}

export function renumberScenes(p) {
  if (!p || !Array.isArray(p.scenes)) return p;
  p.scenes.forEach((s, i) => { if (s && s.id !== SCENE_IDS[i]) s.id = SCENE_IDS[i] || ('S' + (i + 1)); });
  return p;
}

// ── LOOK d'une section d'arrangement (2026-07-31) — UNE seule règle pour DEUX écrans : le
// visualiseur du Designer et le rail de /live timeline lisaient deux vérités différentes
// (couleur par NOM de partie ici, couleur de SCÈNE là-bas). Cascade, du plus explicite au
// plus automatique :
//   1. sec.look {color, anim}  — choisi à la main sur la PASTILLE de la partie
//   2. le NOM de la partie     — intro bleu, chorus orange… (rien n'est jamais gris par défaut)
//
// ⚠ LA SCÈNE NE COLORE PLUS RIEN (2026-09-10). Elle était l'étage 2 de cette cascade : faire
// défiler la scène d'une colonne dans le tableau d'arrangement REPEIGNAIT la partie, sa pastille
// et sa tuile sur /live. « Quand je switch une scène ça change les couleurs ? What ! » — et il a
// raison : la couleur d'une partie est son IDENTITÉ (on repère « le pont » à sa teinte d'un bout
// à l'autre du morceau), pas une conséquence du son qu'on y joue. Une scène change à chaque
// répétition, un pont reste un pont. La règle reste UNE pour les deux écrans.
export const PART_COLOR = {
  intro: '#5b8fb9', verse: '#6aa06a', 'pre-chorus': '#b99a5b', chorus: '#c9683a',
  bridge: '#8a6ab0', solo: '#c94f6d', outro: '#6b7480',
};
export const SCENE_FALLBACK = ['#3f7fd6', '#12a3a0', '#cc1f1f', '#7a2a52', '#2f5e23'];   // = LIVE_PALETTE

// ── CE QUI PART AVEC LE MORCEAU (docs/arrangement.md §5-6) ─────────────────────────────────────
// `starts` = les cases de la CHANSON ({backing, click, rec, sample}, null = jamais touchée). Une case jamais
// touchée vaut ce que le rack fait sans elle — MÊME règle que le bridge (arrangement.starts_of + app.py) :
// backing et samples oui, click si son bloc est actif, pas de prise (l'empilement de Rec sur le switch est migré).
// UNE fonction pour la page chanson ET le Designer : deux copies de cette règle finiraient par diverger.
// ── LES CATÉGORIES DE BLOCS SPÉCIAUX (2026-10-08) : [libellé, couleur]. /live encadre ses cases avec (maquette
// live-specials-scenes, variante 2), le mini-pédalier du Designer les colore (maquette designer-preset-glance, 3).
// UNE table pour les deux écrans : deux copies finiraient par donner deux couleurs au même bloc.
export const SPECIAL_CAT = { arrangement: ['Song', '#e0954a'],
  'backing-track': ['Players', '#1ab7b0'], drums: ['Players', '#1ab7b0'], sample: ['Players', '#1ab7b0'],
  standard: ['Players', '#1ab7b0'], looper: ['Players', '#1ab7b0'],
  // Riff a SON nom sur son bandeau (2026-10-14 : deux cases « REC » côte à côte sur SW9/SW10) — même couleur, même famille
  rec: ['Rec', '#ff4b4b'], compo: ['Riff', '#ff4b4b'], click: ['Click', '#e8c547'], tuner: ['Tool', '#c9d3e0'] };

// + `drums` (2026-10-20) : la boîte à rythmes part avec le morceau, chaque partie choisit son groove (section.drums)
export const STARTS_TYPES = { backing: 'backing-track', click: 'click', rec: 'rec', sample: 'sample', drums: 'drums' };
export function resolveStarts(starts, preset) {
  const st = starts || {};
  const cfg = lane => ((((preset || {}).config || {})[lane] || {}).blocks || []).filter(Boolean);
  const click = cfg('rec').find(b => b.type === 'click');
  const sample = cfg('gen').find(b => b.type === 'sample');
  const drums = cfg('gen').find(b => b.type === 'drums');
  const dflt = { backing: true, click: !!click && !click.bypass, sample: true, rec: false, drums: true };
  const out = {};
  for (const k of Object.keys(STARTS_TYPES)) out[k] = st[k] != null ? !!st[k] : dflt[k];
  out.sample = out.sample && !!sample;                     // un bloc absent ne part pas, quoi que dise la case
  out.drums = out.drums && !!drums;
  return out;
}

// LE GROOVE D'UNE PARTIE (bridge/arrangement.py drums_at) : la dernière consigne posée à `i` ou avant (un numéro de
// motif du bloc drums, ou « stop ») ; sans aucune, le premier motif. Même règle des deux côtés.
export function drumsAt(sections, i) {
  for (let j = Math.min(i, (sections || []).length - 1); j >= 0; j--) {
    const v = (sections[j] || {}).drums;
    if (v === 'stop' || v === false) return 'stop';
    if (Number.isInteger(v)) return v;
  }
  return 0;
}
// « golem-rock-8.mid » -> « rock 8 » : le nom d'un groove tel qu'on le dit
export const grooveName = rel => String(rel || '').split('/').pop().replace(/\.mid$/i, '').replace(/^golem-/, '').replace(/[-_]+/g, ' ');

export function sectionLook(sec) {
  const lk = (sec && sec.look) || {};
  return {
    color: lk.color || PART_COLOR[(sec || {}).name] || '#7a8290',
    anim: lk.anim != null ? lk.anim : '',
    // d'où ça vient — la pastille le DIT (crayon), pour qu'on sache ce qu'on écrase
    from: lk.color || lk.anim != null ? 'section' : 'part',
  };
}
export const LANE_LETTER = i => String.fromCharCode(65 + i);
export const MAX_BLOCKS = 18;                 // blocs max par lane (2 rangées pleines ~16 utiles + blocs système) — le CPU s'en moque, la LISIBILITÉ est la vraie limite ; au-delà -> split
// couleurs des tuiles Live (paramétrables par preset) : défaut = palette par colonne (cf. page-live.js)
export const LIVE_STOMPS = ['boost', 'delay', 'reverb', 'tremolo', 'whammy'];
// animations des tuiles Live (choisies dans une liste, comme la couleur) — '' = défaut (pulse)
// défaut = '' = None (aucune animation). Pulse est une option explicite. (page-live : anims[k] non défini -> None)
// ── PACKS d'animations (docs/anim-packs.md) — « default » est le socle livré (20 tuiles,
// verrouillé) ; les autres arrivent par golem.fm. Une valeur d'animation vaut « effet » (pack
// default, forme historique) ou « pack/effet ». La CLASSE CSS suit : anim-fire · anim-neon-glow.
export const animClass = v => {
  const s2 = String(v || '');
  if (!s2) return '';
  const i2 = s2.indexOf('/');
  return i2 < 0 ? 'anim-' + s2 : 'anim-' + s2.slice(0, i2) + '-' + s2.slice(i2 + 1);
};
export const animPackOf = v => { const i2 = String(v || '').indexOf('/'); return i2 < 0 ? 'default' : v.slice(0, i2); };
// le CSS d'un pack est chargé À LA DEMANDE, une fois (le rack n'embarque que le default)
const _packCss = {};
export function ensurePackCss(pid) {
  if (!pid || pid === 'default' || _packCss[pid]) return;
  _packCss[pid] = true;
  const el = document.createElement('link');
  el.rel = 'stylesheet'; el.href = '/api/anim-pack/' + encodeURIComponent(pid) + '/css';
  el.onerror = () => console.warn('[anim-packs] pack « ' + pid + ' » indisponible — tuiles sans animation');
  document.head.appendChild(el);
}

export const ANIM_STYLES = [['', 'None'], ['pulse', 'Pulse'], ['heartbeat', 'Heartbeat'], ['wave', 'Wave'], ['sheen', 'Sheen'],
  ['scanner', 'Scanner'], ['ember', 'Ember'], ['vu', 'VU reactive'], ['ripple', 'Ripple (drop)'], ['rain', 'Rain'], ['snow', 'Snow'],
  ['lightning', 'Lightning'], ['strobe', 'Strobe'], ['monster', 'Monster'], ['stars', 'Stars'], ['aurora', 'Aurora'],
  ['fire', 'Fire'], ['smoke', 'Smoke'], ['vortex', 'Vortex'], ['glitch', 'Glitch']];

// couleur par catégorie (le liseré des tuiles, comme le QC)
export const CAT_COLOR = {
  dynamics: '#8a94a3', preamp: '#d9a441', drive: '#ffb03a', lofi: '#e07a3a', filter: '#5ec8e0', amp: '#ff5a3c', cab: '#1ab7b0', eq: '#3d9be9',
  modulation: '#2ecc71', delay: '#5a7cff', reverb: '#5a7cff', pitch: '#b06cf0', utility: '#8a94a3',
  keys: '#e0b23a', hardware: '#e06ac0', 'vst-host': '#8b9fd7', mine: '#f4f4f4',
};
// libellé d'une catégorie quand la capitalisation CSS ne suffit pas (« lofi » → « Lo-Fi »)
export const CAT_LABEL = { lofi: 'Lo-Fi', 'vst-host': 'VST Host' };
export const catLabel = c => CAT_LABEL[c] || c;

export const BLOCK_COLOR = {
  'pedal-nam': '#ffb03a', 'preamp-nam': '#d9a441', 'comp-nam': '#8a94a3', grit: '#e07a3a',
  amp: '#ff5a3c', 'amp-nam': '#ff5a3c', cab: '#1ab7b0', boost: '#ffb03a', drive: '#ffb03a',
  gate: '#8a94a3', comp: '#8a94a3', eq: '#3d9be9',
  wah: '#5ec8e0', 'wah-color': '#5ec8e0', autowah: '#5ec8e0',
  chorus: '#2ecc71', flanger: '#2ecc71', phaser: '#2ecc71', tremolo: '#2ecc71', mod: '#2ecc71',
  delay: '#5a7cff', reverb: '#5a7cff', pitch: '#b06cf0', whammy: '#b06cf0', 'whammy-dt': '#b06cf0', 'midi-pedal': '#e06ac0',
  volume: '#8a94a3', 'clean-boost': '#ffb03a', 'vst-host': '#8b9fd7', vital: '#e0b23a', pads: '#d97742', organ: '#b06ad4', piano: '#4aa3df', ep: '#e0669a',
};
export const blkColor = t => BLOCK_COLOR[t] || '#8a94a3';

// LES GLYPHES DE golem-fx (2026-11-13, docs/designer-glyphs-pedals.md) : un SVG par type de bloc, au trait, en
// currentColor — il prend la couleur de la tuile comme le caractère Unicode qu'il remplace. Un nœud NEUF à chaque
// lecture : Preact ne doit pas monter le même vnode à deux endroits (la pile de /live montre un même type deux fois).
export const glyph = (type, cls) => {
  const g = GLYPHS[type];
  return g ? html`<svg class=${'glyph' + (cls ? ' ' + cls : '')} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
    dangerouslySetInnerHTML=${{ __html: g.svg }}></svg>` : null;
};
// le caractère d'avant, pour un contexte TEXTE (un title, une chaîne) — jamais un nœud
export const glyphText = type => (GLYPHS[type] && GLYPHS[type].uni) || ICON_UNI[type] || '•';

// glyphes monochromes (héritent la couleur de la tuile) — évite les emojis colorés type ⬛. Ce sont désormais les
// REPLIS Unicode : ICON[type] rend le glyphe SVG quand golem-fx en a un (le proxy plus bas).
const ICON_UNI = {
  'pedal-nam': '⬢', 'preamp-nam': '⬡', 'comp-nam': '◈', grit: '◩',
  gate: '⊓', comp: '◇', boost: '△', drive: '△', amp: '▦', 'amp-nam': '▦', cab: '◨',
  wah: '◑', 'wah-color': '◑', autowah: '◠',
  eq: '∿', chorus: '≈', flanger: '⋈', phaser: '◍', tremolo: '∿', mod: '≈', click: '◔',
  delay: '⇉', reverb: '❈', pitch: '♯', 'whammy-dt': '↕', whammy: '↕', 'midi-pedal': '⇄', volume: '▮', 'clean-boost': '△',
  // les blocs-INSTRUMENTS (2026-10-14) : des pictogrammes au trait, monochromes — plus les emojis colorés
  vital: ICONS.synth, organ: ICONS.organ, piano: ICONS.keys, ep: ICONS.ep, pads: ICONS.pads, drums: ICONS.drums,
  drumkit: ICONS.drumkit,
};
export const ICON = new Proxy(ICON_UNI, {
  get: (t, k) => (typeof k === 'string' && GLYPHS[k] ? glyph(k) : t[k]),
});
// ces types gardent leur pictogramme : le glyphe du catalogue (un emoji) ne l'écrase pas
const ICON_SVG = new Set(['vital', 'organ', 'piano', 'ep', 'pads', 'drums', 'drumkit']);

// noms courts du catalogue (effects.json) — vide au boot, hydraté au fetch ; la page Live s'en
// sert pour libeller les stomps ("Wah + Pedal" plutôt que le type brut "wah")
export const NAME = {};
export const SHORT = {};        // nom COURT du catalogue (« Tape », « PEQ ») : la pile de /live n'a pas la place du nom complet
export const ARCH_NAME = {};    // archétype nommé (pédales/amplis d'effects.json) : id -> « Big Muff »

// hydrate ICON/BLOCK_COLOR depuis effects.json = SOURCE UNIQUE de l'identité visuelle
// (golem.fm Ré-réponse 5) : un bloc ajouté au catalogue avec color/glyph est dessiné sans
// éditer ce fichier. Les maps ci-dessus restent des SEEDS (premier rendu avant chargement).
// CONTENU CHARGÉ par bloc (docs : décision 2026-07-31) — quel PARAMÈTRE fait office
// d'identité pour les blocs qui n'ont pas de capture : vital→preset, drums→kit, piano→sfz…
// Le catalogue le déclare (`content_param`), le code n'a aucun cas particulier.
export const CONTENT_PARAM = {};
// les types que le moteur ACTIF joue par un plugin golem-fx (/api/effects `golem_fx` ; vide sous REAPER) : fond
// « terre cuite » dans le Designer, colonne golem FX du tiroir, pédale golem-fx dans la vue pédalier
export const GOLEM_FX = new Set();
// le crate golem-fx de chaque type de la table (/api/effects `gfx_crates`) : la pédale qu'il dessine
export const GFX_CRATES = {};

export function hydrateBlockMeta(effects, catalog) {
  // `catalog` = le document effects.json entier (pedals/amps/cabs nommés) quand l'appelant l'a : les
  // archétypes nommés servent à la pile de /live (« Big Muff » plutôt que le titre de la capture)
  for (const a of [...((catalog || {}).pedals || []), ...((catalog || {}).amps || []), ...((catalog || {}).cabs || [])]) if (a && a.id && a.name) ARCH_NAME[a.id] = a.name;
  if (catalog && Array.isArray(catalog.golem_fx)) { GOLEM_FX.clear(); for (const t of catalog.golem_fx) GOLEM_FX.add(t); }
  if (catalog && catalog.gfx_crates) Object.assign(GFX_CRATES, catalog.gfx_crates);
  for (const b of (effects || [])) {
    if (b && b.type) {
      // ⚠ `glyph` PUIS `icon` : le catalogue porte les deux, et tous les blocs n'ont pas de
      // `glyph` (le Standard n'a que `icon: '♭'`). Ne lire que `glyph` laissait donc /live
      // retomber sur son point d'interrogation générique — un rond ⊙ — pendant que le Designer,
      // qui essaie `icon` en second recours, affichait la note. Le même bloc portait deux
      // identités selon la page. La table est la SOURCE UNIQUE : elle résout les deux ici, une
      // fois, plutôt que chaque page à sa façon.
      if ((b.glyph || b.icon) && !ICON_SVG.has(b.type)) ICON[b.type] = b.glyph || b.icon;
      if (b.color) BLOCK_COLOR[b.type] = b.color;
      if (b.name) NAME[b.type] = b.name;
      if (b.short) SHORT[b.type] = b.short;
      if (b.content_param) CONTENT_PARAM[b.type] = b.content_param;
    }
  }
}

// Le contenu d'un bloc pour une SCÈNE donnée. « 3 Vital sur la lane, un seul chargé par
// scène » : le badge doit dire celui de la scène COURANTE, pas la valeur de base — sinon il
// ment au moment où il sert le plus. scene.params[id][param] > block.params[param].
export function blockContent(b, scene) {
  const key = CONTENT_PARAM[(b || {}).type];
  if (!key) return null;
  const ovr = (((scene || {}).params || {})[(b || {}).id] || {})[key];
  const v = ovr !== undefined ? ovr : ((b.params || {})[key]);
  if (v == null || v === '') return null;
  // les valeurs sont des noms de fichiers/presets : on montre le nom, pas le chemin
  return String(v).split('/').pop().replace(/\.(vital|sfz|golemkit|xml)$/i, '').replace(/_/g, ' ');
}

// chaîne KEYS (lane In3, contrôleur MIDI GoleM USB) : v1 = un seul bloc possible, Vital.
export const toKeys = keys => ({
  chain: (((keys || {}).chain) || []).map(b =>
  (b.id ? b : { ...b, id: bid(b.type) })) });

// ── lane CONFIG (docs/blocks-doctrine.md — 2026-07-21) : les blocs SERVICE transversaux vivent hors
// des chaînes de signal, dans p.config = { gen:{blocks,out}, rec:{blocks,tap} }. gen = « Players »
// (générateurs + looper, IN capture + OUT façade) ; rec = « Recorder » (le rec, IN seule, tap). ──
// `standard` (docs/standards.md) est un GÉNÉRATEUR au même titre que la boîte à rythmes :
// il ne prend aucune entrée, il en fabrique une (piano + walking bass depuis une grille).
export const CONFIG_GEN_TYPES = ['looper', 'backing-track', 'sample', 'drums', 'standard'];
export const CONFIG_REC_TYPES = ['rec', 'click', 'compo'];   // Recorder lane : magnétophone + métronome (le guide sonore Preview
// n'est PLUS un bloc — il se génère depuis Library « Listen to your preset », DI auto par style/rôle).
// lane `arr` — le CHEF D'ORCHESTRE (docs/arrangement.md §7) : sans audio, il commande les autres.
// PLUS dans le tiroir d'ajout : le bloc est permanent et s'édite dans son onglet ▤.
// LE BLOC ARRANGEMENT EST DE RETOUR DANS L'ONGLET ⚙ (2026-09-16, docs/arrangement.md §4 bis + §7).
// Il ne porte PAS les parties — elles vivent sur la ligne de setlist depuis le 2026-09-08 — mais ce qui
// appartient au rig : sa PÉDALE et la règle d'avance. Son tiroir ouvre les parties de la chanson liée.
export const CONFIG_ARR_TYPES = ['arrangement'];
const DROPPED_TYPES = ['preview'];   // blocs retirés du produit : strippés à la normalisation
export const CONFIG_SERVICE_TYPES = [...CONFIG_GEN_TYPES, ...CONFIG_REC_TYPES, ...CONFIG_ARR_TYPES];

// Migre les blocs service hors des chaînes vers la lane config. Idempotent. Mute le preset en place.
// Miroir front du bridge store.migrate_config — le bridge fait autorité (load/save), ici c'est pour
// que l'éditeur voie tout de suite la bonne forme (anciens presets chargés dans le sandbox).
export const migrateConfig = p => {
  const cfg = (p.config && typeof p.config === 'object') ? p.config : {};
  cfg.gen = cfg.gen && typeof cfg.gen === 'object' ? cfg.gen : {};
  cfg.rec = cfg.rec && typeof cfg.rec === 'object' ? cfg.rec : {};
  cfg.arr = cfg.arr && typeof cfg.arr === 'object' ? cfg.arr : {};
  if (!Array.isArray(cfg.gen.blocks)) cfg.gen.blocks = [];
  if (!cfg.gen.out) cfg.gen.out = '1-2';
  if (!Array.isArray(cfg.rec.blocks)) cfg.rec.blocks = [];
  if (!cfg.rec.tap) cfg.rec.tap = 'post';
  if (!Array.isArray(cfg.arr.blocks)) cfg.arr.blocks = [];
  // bloc Arrangement PERMANENT : il a son onglet, on ne l'ajoute jamais à la main (miroir du
  // bridge, qui fait autorité au load/save).
  if (!cfg.arr.blocks.some(b => b && b.type === 'arrangement')) {
    cfg.arr.blocks.push({ id: 'arrangement', type: 'arrangement',
                          params: { advance: 'bars', sections: [] } });
  }
  p.config = cfg;
  const take = arr => {
    if (!Array.isArray(arr)) return;
    for (let i = arr.length - 1; i >= 0; i--) {
      const b = arr[i]; const t = b && b.type;
      if (DROPPED_TYPES.includes(t)) { arr.splice(i, 1); }   // bloc retiré du produit (preview)
      else if (CONFIG_GEN_TYPES.includes(t)) { cfg.gen.blocks.unshift(b); arr.splice(i, 1); }
      else if (CONFIG_REC_TYPES.includes(t)) { cfg.rec.blocks.unshift(b); arr.splice(i, 1); }
      else if (CONFIG_ARR_TYPES.includes(t)) { cfg.arr.blocks.unshift(b); arr.splice(i, 1); }
    }
  };
  const g = p.guitar || {};
  take(g.pre); take(g.chain);
  ((g.split || {}).branches || []).forEach(br => take(br.blocks));
  take(g.post);
  take((p.voice || {}).chain);
  take((p.keys || {}).chain);
  cfg.gen.blocks = cfg.gen.blocks.filter(b => !DROPPED_TYPES.includes(b && b.type));
  cfg.rec.blocks = cfg.rec.blocks.filter(b => !DROPPED_TYPES.includes(b && b.type));
  // chantiers REC + CLICK : les blocs Rec et Click sont PERMANENTS (config globale, hydratée par
  // le bridge au load ; seule l'assignation au pied est locale) — un preset neuf naît avec
  if (!cfg.rec.blocks.some(b => b && b.type === 'rec')) cfg.rec.blocks.unshift({ id: 'rec-global', type: 'rec' });
  // le Click naît BYPASSÉ (cf. bridge) : en mode « preset », bloc actif = le métronome joue
  if (!cfg.rec.blocks.some(b => b && b.type === 'click')) cfg.rec.blocks.push({ id: 'click-global', type: 'click', bypass: true });
  // bloc Compo PERMANENT (docs/compo.md §2) : même contrat — config globale hydratée par le bridge
  if (!cfg.rec.blocks.some(b => b && b.type === 'compo')) cfg.rec.blocks.push({ id: 'compo-global', type: 'compo' });
  return p;
};

// ── COMPO : les lanes de chaque PERSONNE de la carte (docs/compo.md §4) ────────────────────────
// Une lane occupe une entrée numérotée (rôle + n°) ou, à défaut, l'entrée physique choisie ; l'entrée
// porte la personne (carte du mode). Miroir de bridge/compo.lanes_of_person — même résolution, pour
// que le tiroir montre exactement ce que le rack capturera.
export function lanesByPerson(preset, patch) {
  const inputs = (patch && patch.inputs) || [], usb = (patch && patch.usb) || [];
  const byCh = {}; inputs.forEach(e => { byCh[String(e.ch)] = e; });
  const byRn = {}; inputs.forEach(e => { if (e.role && e.nth) byRn[e.role + ':' + e.nth] = e; });
  const out = {};
  ((preset && preset.lanes) || []).forEach(L => {
    if (!L) return;
    let e = null;
    if (L.midi) {
      const sel = String(L.in_sel || 'usb'); const port = sel === 'usb' ? 1 : (parseInt(sel.replace(/\D/g, ''), 10) || 1);
      e = usb.find(u => Number(u.port) === port) || null;
    } else if (L.in_role && L.in_nth) e = byRn[L.in_role + ':' + L.in_nth] || null;
    else e = byCh[String(L.in_sel || '')] || null;
    if (!e || !e.person) return;
    // `input` : l'entrée que la lane occupe ("1"… ou "usb") — le tiroir Riff dit si le Rec l'enregistre
    (out[e.person] = out[e.person] || []).push({ id: L.id, name: L.name || L.id, role: L.role,
                                                 input: L.midi ? 'usb' : String(e.ch) });
  });
  return out;
}

// ids stables côté client (nécessaires aux toggles par scène + au push param live)
// id de bloc : suffixe ALÉATOIRE (base36) — un simple compteur repartait à 0 à chaque rechargement
// de page et re-générait des ids déjà pris (ex. « pedal-nam-1 » posé par l'IA + re-créé à la main
// -> ids dupliqués -> compile refusée -> auditions silencieusement mortes ; bug Frusciante 2026-07-10).
export const bid = t => `${t}-${Math.random().toString(36).slice(2, 6)}`;
// assure un id sur chaque bloc d'une chaîne {pre, split, post}
export const ensureIds = g => {
  const fix = arr => (arr || []).forEach(b => { if (!b.id) b.id = bid(b.type); });
  fix(g.pre);
  if (g.split) g.split.branches.forEach(br => { if (!br.id) br.id = bid('br'); fix(br.blocks); });
  fix(g.post);
  return g;
};

// chaîne VOIX : même modèle riche que la guitare ({id,type,params,bypass}) — rétro-compat avec
// l'ancien modèle simplifié (liste de types nus), normalisé au chargement.
// ⚠ les normaliseurs REBÂTISSENT le realm : toute clé hors-chaîne doit être re-portée
// explicitement. C'est ce qui fait qu'ils sont AUSSI l'endroit où le lien de patch s'efface :
// il n'est plus re-porté (docs/patches.md §15 — modèle COPIE), donc il disparaît de lui-même au
// prochain enregistrement de chaque preset. Pas de migration, pas de réécriture d'autorité.
export const toVoice = voice => ({
  chain: (((voice || {}).chain) || []).map(b =>
  typeof b === 'string' ? { type: b, id: bid(b) } : (b.id ? b : { ...b, id: bid(b.type) })) });

// guitar (nouveau {pre,split,post} OU ancien chain|lanes) -> forme éditable {pre, split, post}.
// pre = chaîne linéaire partagée ; split = {mode:'fanout'|'merge', branches:[{id,blocks,out}], gain} ; post = après Σ (merge).
export const toChain = guitar => {
  const g = guitar || {};
  let c;
  if ('pre' in g || 'split' in g) c = { pre: g.pre || [], split: g.split || null, post: g.post || [] };
  else if (g.lanes) c = { pre: [], post: g.post || [],                      // ancien lanes = split merge @début
    split: { mode: 'merge', gain: (g.merge && g.merge.gain) ?? -3,
      branches: g.lanes.map((L, i) => ({ id: L.id || ('b' + (i + 1)), blocks: L.blocks || [] })) } };
  else c = { pre: (g.chain || []).slice(), split: null, post: [] };         // ancien linéaire
  // la Whammy DT est physiquement AVANT l'entrée : ancrée en tête de lane (les anciens presets
  // peuvent l'avoir au milieu, et le bloc n'a plus de flèches -> on la recale au chargement)
  if (c.pre.some(b => b && b.type === 'whammy-dt'))
    c.pre = [...c.pre.filter(b => b && b.type === 'whammy-dt'), ...c.pre.filter(b => !b || b.type !== 'whammy-dt')];
  return ensureIds(c);               // (le lien de patch n'est plus re-porté : §15, modèle copie)
};

// Nouveau preset = UNE lane VIDE. Le bloc Volume (master lié à EXP) est un UTILITAIRE système garanti
// côté bridge (store.ensure_volume) — jamais dans la chaîne du Designer, donc plus de tuile parasite.
// Le reste se remplit à la main (+ bloc) ; la lane Keys naît vide (tap = Vital).
// La lane CONFIG passe par migrateConfig, comme tout document chargé : les blocs PERMANENTS (Rec, Click, Riff) y
// naissent. Sans cela, un patch tout neuf montrait un onglet ⚙ vide jusqu'au rechargement de la page (2026-11-13).
export const blank = () => toLanesV2(migrateConfig({ id: 'nouveau-preset', name: 'New preset', style: 'metal', bpm: 120,
  guitar: toChain({ chain: [] }),
  voice: { chain: [] },
  keys: { chain: [] },
  config: { gen: { blocks: [], out: '1-2' }, rec: { blocks: [], tap: 'post' } },
  scenes: [{ id: 'A', name: 'base', blocks: {}, voice: true, levels: { guitar: -6 } }] }));

// ── LES LANES v2 (audit N lanes 2026-09-08, lot 3) ───────────────────────────────────────────
// Le document que le Designer édite est une LISTE de lanes ; les trois clés d'origine (guitar /
// voice / keys) sont des miroirs regénérés par le bridge pour les lecteurs non migrés. Miroir
// client de bridge/store.lanes_of : même dérivation depuis un preset legacy, mêmes champs.
export const LEGACY_LANES = [['guitar', '1', 'Input 1'], ['voice', '2', 'Input 2'], ['keys', 'k', 'Keys']];
export const MIDI_ROLES = ['keys', 'pads', 'keys-pads'];
export const richChain = c => { c = c || {};
  if ('pre' in c || 'split' in c || 'post' in c) return ensureIds({ pre: c.pre || [], split: c.split || null, post: c.post || [] });
  return ensureIds({ pre: (c.chain || []).map(b => typeof b === 'string' ? { type: b, id: bid(b) } : b), split: null, post: [] }); };
// LA LANE EST-ELLE ENCORE LE PATCH ? (2026-10-21) Le dépôt d'un patch dans un preset renomme ses blocs (`eq` -> `eq-2`,
// un id par preset) et réattribue les switchs (`foot` appartient au pédalier du preset) : comparer le JSON brut disait
// « · edited » sur CHAQUE lane de CHAQUE preset d'usine, jamais touchée. Le son, c'est le reste : on ignore ces deux clés.
const soundOf = x => Array.isArray(x) ? x.map(soundOf)
  : (x && typeof x === 'object') ? Object.fromEntries(Object.keys(x).filter(k => k !== 'id' && k !== 'foot').sort().map(k => [k, soundOf(x[k])]))
  : x;
export const sameSound = (a, b) => { const n = c => { const r = richChain(c); return JSON.stringify(soundOf({ pre: r.pre, split: r.split, post: r.post })); };
  return n(a) === n(b); };
export const laneBlocks = L => { const c = (L && L.chain) || {};
  return [...(c.pre || []), ...(((c.split || {}).branches) || []).flatMap(br => br.blocks || []), ...(c.post || [])].filter(Boolean); };
// LE SON RETOUCHÉ DANS LA FENÊTRE DE VITAL (2026-10-14) remplace celui d'origine PARTOUT où ce bloc le jouait :
// en base et dans chaque scène qui le reprenait. Une scène qui jouait un AUTRE son garde le sien — on a retouché un
// son, pas le bloc. `from` vide = le bloc jouait son défaut (aucun preset posé) : la base prend le son retouché.
export const swapVitalPreset = (p, blockId, from, to) => {
  const b = ((p && p.lanes) || []).flatMap(laneBlocks).find(x => x && x.id === blockId);
  if (!b || !to) return false;
  b.params = b.params || {};
  if (!b.params.preset || b.params.preset === from) b.params.preset = to;
  for (const sc of (p.scenes || [])) {
    const o = sc.params && sc.params[blockId];
    if (o && o.preset === from) o.preset = to;
  }
  return true;
};
export const isV2 = p => !!p && p.lanes_v === 2 && Array.isArray(p.lanes);
export const newLaneId = () => 'ln-' + Math.random().toString(36).slice(2, 7);
// ── UNE LANE = UNE ENTRÉE COCHÉE (décision 2026-09-09, docs/input-map.md §3.2) ──
// L'ordre des onglets est une CONSTANTE DE CONTRAT, pas un réglage. CORRIGÉ 2026-09-13  :
// l'ordre est celui de la CARTE — les entrées physiques d'abord, IN 1, IN 2, … ; puis les ports
// USB, USB 1, USB 2, … ; une lane sans entrée (NONE) ferme la marche. Plus de rang par rôle : on
// lit les onglets comme on lit la façade du rack. Le bridge ne trie pas — l'app écrit le document
// déjà trié, tout lecteur voit le même ordre.
const laneGroup = L => (L.midi || /^usb/i.test(String(L.in_sel || '')) || L.in_sel === 'k') ? 1 : L.none ? 2 : 0;
const laneNum = L => { const s = String(L.in_sel || '');
  if (laneGroup(L) === 1) return parseInt((s.match(/usb(\d+)/i) || [])[1], 10) || 1;   // « usb » legacy = USB 1
  return parseInt(s, 10) || 99; };                                                       // « 3-4 » → 3 ; NONE → dernier
const sortFlat = ls => [...(ls || [])].map((L, i) => [L, i]).sort(([a, ia], [b, ib]) =>
  (laneGroup(a) - laneGroup(b)) || (laneNum(a) - laneNum(b)) || String(a.name || '').localeCompare(String(b.name || '')) || (ia - ib))
  .map(([L]) => L);
// ── UN GROUPE DE BATTERIE RESTE CONTIGU (docs/drums-kit.md §6.6) ────────────────────────────
// Le tri par entrée suffit tant qu'un kit occupe des entrées qui se suivent. Il ne suffit PAS
// dès qu'on intercale : kit sur IN 3-4 et 7-8, voix sur IN 5, et la voix tombe AU MILIEU du kit —
// l'en-tête replié couvrirait alors une lane qui ne lui appartient pas. On trie donc à plat, puis
// on ramène chaque `drumset` derrière sa PREMIÈRE lane, sans toucher à l'ordre du reste.
export const sortLanes = ls => {
  const flat = sortFlat(ls);
  const out = [], done = new Set();
  for (const L of flat) {
    const ds = L.drumset;
    if (!ds) { out.push(L); continue; }
    if (done.has(ds)) continue;
    done.add(ds);
    out.push(...flat.filter(x => x.drumset === ds));
  }
  return out;
};
// les lanes d'un groupe, dans l'ordre de l'écran ; [] si l'id ne nomme aucun groupe
export const drumsetLanes = (ls, ds) => ds ? sortLanes(ls).filter(L => L.drumset === ds) : [];
// les ids de groupe présents, dans l'ordre de l'écran (un preset en a zéro, rarement deux)
export const drumsetsOf = ls => [...new Set(sortLanes(ls).map(L => L.drumset).filter(Boolean))];
// l'id d'une lane neuve DÉRIVE de son entrée (« guitar-2 ») : le même objet sur la Volt et sur le XR18 ;
// les lanes existantes gardent leur id (rien à y gagner, tout à y casser — scènes, niveaux, Companion)
export const laneIdFor = (role, nth, taken = []) => { const base = nth ? role + '-' + nth : role; let id = base, k = 2;
  while (taken.includes(id)) id = base + '-' + (k++); return id; };
export const ROLE_ICON = { guitar: '🎸', bass: '🎸', voice: '🎤', keys: '🎹', pads: '▦', 'keys-pads': '🎹', drums: '🥁', line: '〜' };
// une lane v2 telle qu'elle est stockée -> complète (id, key, role, name, in_sel, out_sel, chain riche, midi)
const normLane = (L, i) => {
  const id = String(L.id || newLaneId());
  const leg = LEGACY_LANES.find(x => x[0] === id);
  // l'instrument et le nom d'une lane liée à une entrée numérotée SONT ceux de l'entrée (le mainteneur
  // 2026-09-09 : « Lane et Instrument se résolvent par l'input ») — le patch de la carte décide
  const bound = !L.midi && L.in_role && L.in_nth != null && !MIDI_ROLES.includes(L.in_role);
  const role = String((bound && L.in_role) || L.role || (L.midi ? 'keys' : 'guitar'));
  const midi = !!L.midi || MIDI_ROLES.includes(role) || /^usb/.test(String(L.in_sel || ''));   // un port USB = MIDI, quel que soit le rôle (module de batterie)
  // les trois champs du GROUPE DE BATTERIE (drumset, drumset_module, element — docs/drums-kit.md
  // §6.3) passent par le `...L` ci-dessous et n'ont rien à normaliser. C'est écrit ici parce qu'un
  // jour quelqu'un remplacera cet étalement par une liste de clés, et les perdra en silence.
  return { ...L, id, key: String(L.key || (leg ? leg[1] : id)), role, midi,
    name: String((bound && L.in_name) || L.name || (leg ? leg[2] : 'Lane ' + (i + 1))),
    in_sel: String(L.in_sel || (leg && !midi ? leg[1] : midi ? 'usb' : String(i + 1))),
    out_sel: String(L.out_sel || '1-2'), chain: richChain(L.chain) };
};
// preset legacy -> lanes (roleOf(key) = le rôle patché sur l'entrée, fourni par l'appelant)
export const lanesFromLegacy = (p, roleOf) => LEGACY_LANES.filter(([id]) => p[id] && typeof p[id] === 'object').map(([id, key, dflt], i) => {
  const src = p[id] || {};
  const chain = id === 'guitar' ? toChain(src) : richChain({ chain: (src.chain || []) });
  const ins = p.in || {}, outs = p.out || {}, names = p.names || {};
  const lane = { id, key, role: (roleOf && roleOf(key)) || (id === 'keys' ? 'keys' : id), name: names[key] || dflt,
    in_sel: ins[key] || (id === 'keys' ? 'usb' : key), out_sel: outs[key] || '1-2', chain, midi: id === 'keys' };
  if (src.patch_from) lane.patch_from = src.patch_from;
  return lane;
});
export const normLanes = (p, roleOf) => sortLanes(isV2(p) ? p.lanes.map(normLane) : lanesFromLegacy(p || {}, roleOf));
// passe un document en v2 EN PLACE : la liste devient la vérité (les clés legacy restent, le bridge les regénère)
export const toLanesV2 = (p, roleOf) => { p.lanes = normLanes(p, roleOf); p.lanes_v = 2; return p; };
// les options d'ENTRÉE d'une lane audio, depuis le patch de la carte (N canaux) ; NONE = lane coupée
// [valeur, libellé, nom libre] : « IN 3 · Voice 1 » — le nom vient du patch de la carte (Settings ▸ Mode / Soundcard)
// LES ENTRÉES OÙ UNE LANE PEUT SE BRANCHER (2026-09-17) : les entrées audio de la carte ET les
// ports USB liés, dans la MÊME liste — une lane batterie se joue en MIDI (le kit du rack sonne) ou en
// audio (le module sonne), et on doit pouvoir basculer SANS détruire la chaîne. `cur` garde l'option
// courante visible même si elle n'est plus proposée (port générique « usb » d'un brouillon de patch).
export const inOptsOf = (patch, cur) => [
  ...((patch && patch.inputs) || []).map(e => [String(e.ch), 'IN ' + e.ch + (e.name ? ' · ' + e.name : (e.person_name ? ' · ' + e.person_name : '')), e.name || null]),
  ...((patch && patch.usb) || []).filter(u => u.bound && u.role && u.role !== 'none')
     .map(u => [String(u.ch), 'USB ' + u.port + (u.name ? ' · ' + u.name : ''), u.name || null]),
  ...(String(cur || '') === 'usb' ? [['usb', 'USB · auto (by role)', null]] : []),
  ['NONE', 'NONE', null]];

// blocs « à modèle » : ampli/cab qui chargent une capture (NAM) ou une IR. Ajout = 3e volet (choix du sim).
// gears TONE3000 proposés par type : NAM+Cab -> captures amp+cab complètes ; tête seule -> têtes ; cab -> IR.
// outboard (2026-09-14) : préampli et compresseur CAPTURÉS (TONE3000 gear=outboard, .nam) — deux
// types, une nature ; un pack outboard au format IR n'entre dans aucun bloc (v2, convolveur dédié).
export const MODEL_GEARS = { amp: ['amp-cab'], 'amp-nam': ['amp'], cab: ['cab'], 'pedal-nam': ['pedal'],
                             'preamp-nam': ['outboard'], 'comp-nam': ['outboard'],
                             // un IR d'effet joué entier (docs/library-tones.md §8) : outboard IR, pédale de réverbe en IR
                             'ir-fx': ['outboard', 'pedal'] };
export const needsModel = type => !!MODEL_GEARS[type];

// ── rattachement capture -> archétype nommé (ampli/pédale d'effects.json) — RÈGLE UNIQUE,
// partagée par Library ▸ Amps/Pedals et le tiroir du Designer : mots-clés match+aliases en
// substring, le mot-clé LE PLUS LONG qui matche gagne (l'Uberschall bat le Bogner générique). ──
export const capText = t => ((t.amp || t.title || '') + ' ' + (t.brand || '') + ' ' + (t.makes || []).join(' ')).toLowerCase();
export const archKws = a => [a.match, ...(a.aliases || [])].filter(Boolean).map(s => String(s).toLowerCase());
export const archOf = (archs, t) => { const txt = capText(t); let best = null, bl = 0;
  for (const a of archs) for (const k of archKws(a)) if (k.length > bl && txt.includes(k)) { best = a; bl = k.length; }
  return best; };


// ── LE BROUILLON D'UN PATCH — une seule vérité, deux appelants ────────────────────────────
// La page Patches et le sélecteur du Designer construisaient le même objet ; le jour où l'un
// des deux aurait oublié les scènes (c'est déjà arrivé), le bug n'aurait existé que d'un côté.
export const PATCH_REALM = { voice: 'voice', keys: 'keys', 'keys-pads': 'keys', pads: 'keys' };

// EN MODE PATCH, LA LANE PORTE LE RÔLE DU PATCH (2026-09-17 : « j'ai tout » dans le tiroir d'un patch
// batterie). Un brouillon créé avant que New patch pose `L.role` gardait la lane du realm en `guitar` alors que
// `__patch.role` disait `drums` — et le tiroir lit la LANE. Idempotent : à appliquer à tout document en mode
// patch (chargement du buffer, création, ouverture d'un patch). Une batterie est MIDI (le kit du rack joue) :
// port « usb » générique = le module lié au rôle drums, sinon entrée vide et dite — jamais l'AKAI.
// ── L'ÉCRAN MONTRE L'ENTRÉE QUE LE MOTEUR JOUE (2026-10-10 : « j'ai bien IN 2 sur mon patch full vst et je
// n'ai pas de son ») ──────────────────────────────────────────────────────────────────────────────────────────
// Une lane liée par NOM (in_role, in_nth) est résolue par le bridge sur la carte du moment (preset_view._norm_lane :
// la liaison PASSE DEVANT le numéro). L'écran, lui, affichait le numéro stocké (`in_sel`). Les deux divergeaient sans
// que rien ne le dise : le brouillon de « full vst » portait in_sel '2' mais une liaison « Voice 1 » (posée sur la
// carte Linux du mode, où IN 2 = voix) — l'onglet disait IN 2, le moteur jouait IN 1, la guitare passait nue par la
// lane voix. Même écart pour un preset fait en Gig (Voice 1 = IN 3) ouvert en Home, et pour un patch ouvert (lié à
// (rôle, 1), in_sel '1' par défaut). Remède : `in_sel` est RECALCULÉ depuis la liaison, avec la règle du bridge.
// Une liaison absente de cette carte ne touche à rien (la lane attend sa carte, et l'écran le dit). Rend le nombre
// de lanes réalignées. Pur, testé (designer-model.test.mjs).
export const alignBoundInputs = (p, imap) => {
  const ins = (imap && imap.inputs) || [];
  let n = 0;
  ((p && p.lanes) || []).forEach(L => {
    if (!L || L.midi || L.drumset || !L.in_role || L.in_nth == null || L.in_sel === 'NONE' || MIDI_ROLES.includes(L.in_role)) return;
    const e = ins.find(x => x.role === L.in_role && Number(x.nth) === Number(L.in_nth));
    if (e && String(e.ch) !== String(L.in_sel)) { L.in_sel = String(e.ch); n += 1; }
  });
  return n;
};
// UN PATCH NEUF S'ASSIED SUR L'ENTRÉE DE SON INSTRUMENT (2026-10-10 : « quand je crée un patch guitar, il
// faudrait que par rapport aux réglages de la soundcard il me sélectionne automatiquement IN 2 »). Le « ＋ New »
// partait d'un preset vierge dont la lane guitare est figée sur l'entrée '1', SANS rôle — un patch OUVERT, lui, se
// lie par (rôle, 1) depuis toujours (patchDraft). Ici : la lane du realm prend le rôle du patch et la PREMIÈRE
// entrée de la carte qui le porte (nth le plus bas) — IN 2 si la guitare est sur 2, IN 1 pour la voix. Un clavier
// ou des pads : le port USB qui porte ce rôle. Rien sur la carte : la lane garde son entrée, et l'écran le dit déjà
// (« IN x is not on this card »). Pur, testé (designer-model.test.mjs).
export const seatPatchLane = (p, imap) => {
  if (!p || !p.__patch || !p.__patch.role || p.__patch.drumset) return p;
  const role = p.__patch.role;
  const L = (p.lanes || []).find(l => l.id === p.__patch.realm) || (p.lanes || [])[0];
  if (!L || role === 'drums') return p;
  const byNth = (a, b) => (Number(a.nth) || 1) - (Number(b.nth) || 1);
  if (L.midi || MIDI_ROLES.includes(role)) {
    const roles = role === 'keys-pads' ? ['keys-pads', 'keys', 'pads'] : [role, 'keys-pads'];
    const u = ((imap || {}).usb || []).filter(x => roles.includes(x.role)).sort(byNth)[0];
    if (u) { L.midi = true; L.in_sel = 'usb' + (u.port || String(u.ch || '').replace(/\D/g, '') || 1); }
    return p;
  }
  const e = ((imap || {}).inputs || []).filter(x => x.role === role).sort(byNth)[0];
  L.role = role; L.in_role = role; L.in_nth = e ? (Number(e.nth) || 1) : 1;
  if (e) L.in_sel = String(e.ch);
  // ⚠ LES AUTRES LANES DU PRESET VIERGE (2026-10-10) : il porte aussi une lane voix sur '2' et un clavier. Assise
  // sur IN 2, la guitare partageait son entrée avec la voix vide — et dans REAPER, une entrée = une piste : la lane
  // voix effaçait les VST au rebuild. Un patch n'est que SA lane (patchDraft monte un patch ouvert ainsi) : les
  // lanes vides des autres rôles s'en vont ; une lane qui porte des blocs reste, l'entrée dédoublée est dite.
  p.lanes = (p.lanes || []).filter(x => x === L || laneBlocks(x).length);
  return p;
};

export const patchLaneFix = p => {
  if (!p || !p.__patch || !p.__patch.role) return p;
  // un patch de KIT (docs/drums-kit.md §6.7) porte N lanes AUDIO : ne rien forcer, et surtout pas
  // MIDI — c'est le module qui fait le son, pas le rack. Sans cette sortie, la première lane du
  // kit repassait en `usb` à chaque montage et le groupe se cassait en silence.
  if (p.__patch.drumset) return p;
  const L = (p.lanes || []).find(l => l.id === p.__patch.realm) || (p.lanes || [])[0];
  if (!L) return p;
  L.role = p.__patch.role;
  if (L.role === 'drums' && !L.midi) { L.midi = true; L.in_sel = 'usb'; }
  return p;
};

// ⚠ TOUJOURS par migrateConfig (2026-10-18) : les flèches ◀ ▶ du Designer ouvraient le patch suivant SANS cette étape,
// donc sans les blocs PERMANENTS de l'onglet Config — le Click manquait, un rechargement de la page le faisait revenir.
export const patchDraft = x => migrateConfig(patchDraftOf(x));
const patchDraftOf = x => {
  const p = blank();
  p.id = 'nouveau-preset';
  p.name = '⛓ ' + x.name;
  // ── UN PATCH v2 EST DÉJÀ UN PRESET (docs/patches.md §3) ─────────────────────────────
  // La forme se LIT (lanes_v 2 + lanes[]), jamais `kind`. Ses lanes montent telles quelles ; chacune se
  // lie par (rôle, 1) — le bridge la résout vers l'entrée de ce rôle sur la carte du moment (input-map.md
  // §2) ; une lane MIDI (claviers, pads, batterie en USB) prend le port générique. Un kit garde ses
  // entrées NOMINALES. Le ⚙ du patch (looper, sample, grooves), ses pédales EXP et ses couleurs suivent.
  if (x.lanes_v === 2 && Array.isArray(x.lanes) && x.lanes.length) {
    const seen = {};                                   // k-ième lane d'un rôle -> « Rôle k » (bridge patches.as_preset)
    p.lanes = x.lanes.map((L, i) => {
      const o = { ...JSON.parse(JSON.stringify(L)), key: L.key || L.id, out_sel: L.out_sel || '1-2', chain: richChain(L.chain) };
      if (L.drumset) o.in_sel = L.in_sel || String(i + 1);
      // une BATTERIE (hors kit à N entrées audio) joue son Drum Kit en MIDI, comme le chemin v1 plus bas — sinon la lane
      // se liait à une entrée audio « Drums » que la carte n'a pas, et le menu n'offrait aucun USB (2026-10-13)
      else if (L.midi || MIDI_ROLES.includes(L.role) || L.role === 'drums') { o.midi = true; o.in_sel = 'usb'; }
      else { seen[L.role] = (seen[L.role] || 0) + 1; o.in_role = L.role; o.in_nth = seen[L.role]; o.in_sel = o.in_sel || '1'; }
      return o;
    });
    p.lanes_v = 2;
    if (Array.isArray(x.scenes) && x.scenes.length) p.scenes = JSON.parse(JSON.stringify(x.scenes));
    const gen = ((x.config || {}).gen) || null;
    if (gen) p.config = { ...(p.config || {}), gen: JSON.parse(JSON.stringify(gen)) };
    // + LE SWITCH DE REC ET DE RIFF (2026-10-17 : « Jazz Clean » montait sur l'établi avec SW9 « free » — le patch
    // a Rec sur SW9). Ces blocs sont des singletons globaux : le patch ne porte que leur pied (patches.v2_fields) ;
    // on le pose sur les blocs permanents du banc, le bridge (migrate) complète leurs réglages
    const feet = (((x.config || {}).rec || {}).blocks || []).filter(b => b && b.type && Number.isInteger(b.foot));
    if (feet.length) {
      const rec = JSON.parse(JSON.stringify(((p.config || {}).rec) || { blocks: [] }));
      rec.blocks = rec.blocks || [];
      feet.forEach(f => {
        const b = rec.blocks.find(y => y && y.type === f.type);
        if (b) b.foot = f.foot; else rec.blocks.push({ id: f.id || f.type + '-global', type: f.type, foot: f.foot });
      });
      p.config = { ...(p.config || {}), rec };
    }
    // + la BACKING (patch-as-preset.md §4, amendé le 2026-09-30) : elle vit au niveau du document, comme dans un preset
    Object.keys(x).forEach(k => { if (/^exp\d*$/.test(k) || k === 'colors' || k === 'anims' || k === 'backing') p[k] = JSON.parse(JSON.stringify(x[k])); });
    if (x.bpm) p.bpm = x.bpm;
    const L0 = p.lanes[0];
    p.__patch = { realm: L0.id, id: x.id, name: x.name, role: x.role || L0.role, ...(L0.drumset ? { drumset: L0.drumset } : {}) };
    return p;
  }
  // ── UN PATCH DE KIT OUVRE N LANES (docs/drums-kit.md §6.7) ────────────────────────────────
  // Retour de le 2026-09-20 : « je veux créer un drum patch et je n'ai pas les nouvelles
  // interfaces ». Le mode patch se repliait à UNE lane — vrai pour une guitare, faux pour un kit,
  // qui est justement l'objet que le lot D venait de créer. Un patch à `elements` monte donc un
  // banc à N lanes, groupées, et le Designer s'y retrouve comme dans un preset.
  if (Array.isArray(x.elements) && x.elements.length) {
    const ds = x.id || 'kit';
    p.lanes = x.elements.map((e, i) => ({
      id: 'drums-' + (i + 1), key: 'drums-' + (i + 1), role: 'drums',
      name: e.element || ('Element ' + (i + 1)), midi: false,
      // un banc de patch n'a pas de carte : les entrées sont NOMINALES et se rebranchent à la pose
      in_sel: String(i + 1), out_sel: '1-2', chain: richChain(e.chain),
      drumset: ds, drumset_module: x.drumset_module || ds, element: e.element,
      ...(Array.isArray(e.scenes) && e.scenes.length ? { states: [] } : {}),
    }));
    p.lanes_v = 2;
    p.__patch = { realm: p.lanes[0].id, id: x.id, name: x.name, role: 'drums', drumset: ds };
    if (x.scenes && x.scenes.length) p.scenes = renumberScenes(x.scenes.map(sc => ({ ...sc })));
    return p;
  }
  const realm = PATCH_REALM[x.role] || 'guitar';
  const c = x.chain || {};
  if (realm === 'guitar') p.guitar = toChain({ pre: c.pre || [], split: c.split || null, post: c.post || [] });
  else if (realm === 'voice') p.voice = toVoice({ chain: c.chain || [] });
  else p.keys = toKeys({ chain: c.chain || [] });
  const L = p.lanes.find(l => l.id === realm); if (L) { L.chain = richChain(c); L.role = x.role || L.role;
    // patch BATTERIE (docs/drums-kit.md) : la lane du brouillon est MIDI — c'est le seul moyen d'entendre un
    // kit ; « usb » sans numéro = le module lié au rôle drums, sinon entrée vide, dite (jamais l'AKAI)
    if (L.role === 'drums') { L.midi = true; L.in_sel = 'usb'; } }
  // marqueur du MODE PATCH du Designer : un seul onglet, sauvegarde auto vers le catalogue
  // ⚠ LE RÔLE VOYAGE AVEC. Le realm ne suffit pas : une basse vit dans le realm `guitar`,
  // donc sans le rôle l'IA lui proposerait des amplis de guitare — en toute logique, puisqu'on
  // ne lui aurait pas dit. C'est le rôle qui cadre les blocs, les captures et la chaîne.
  p.__patch = { realm, id: x.id, name: x.name, role: x.role || realm };
  // §13 : les SCÈNES du patch montent dans le draft — tester = taper A-E et jouer.
  // ⚠ ON PART DES SCÈNES DU PATCH, pas de celles du brouillon. Premier jet : un `map` sur
  // `p.scenes`, qui vient de `blank()` et n'en contient qu'UNE (A). Les scènes B, C, D d'un
  // patch étaient donc jetées en silence — la bande A-E affichait B comme « ajouter » et
  // C..E désactivées, et on ne pouvait pas essayer le son qu'on venait d'ouvrir. Le NOM des
  // scènes vient du patch quand il en a un (l'IA nomme ses scènes, patches.py scenes_of les
  // garde depuis le 2026-09-08) ; sinon un neutre. Dans un MORCEAU, ce sont ses noms qui font foi.
  if (x.scenes && x.scenes.length) {
    // ⚠ NE JAMAIS INVENTER UN NIVEAU. Avant, chaque scène d'un patch sans niveau recevait le
    // `levels: {guitar: -6}` du brouillon vide — puis l'auto-save l'écrivait dans le fichier comme
    // s'il venait de l'utilisateur, et le miroir l'envoyait à golem.fm par-dessus le leur (mesuré
    // par golem.fm le 2026-09-14 : 11 scènes sur 11 à -6, un +3 de Sunfunk écrasé). Un patch sans
    // niveau reste sans niveau : le moteur le joue à 0 dB, comme depuis le web.
    const base = { blocks: {}, voice: true };
    p.scenes = x.scenes.map(pe => {
      const sc = { ...base, id: pe.id, name: 'scene ' + pe.id };
      return { ...sc, ...(pe.name ? { name: pe.name } : {}),
               blocks: { ...(pe.blocks || {}) }, params: { ...(pe.params || {}) },
               // le MUTE PAR BRANCHE du split s'appelle `branches` depuis le 2026-09-08 (ex-`lanes`) ;
               // ce lecteur ne connaissait que l'ancien nom : un patch sauvé avec ses branches muettes
               // rouvrait les deux branches allumées (1983, 2026-09-14). Les deux clés passent.
               ...(pe.branches ? { branches: { ...pe.branches } } : {}),
               ...(pe.lanes ? { lanes: { ...pe.lanes } } : {}),
               ...(pe.levels ? { levels: { ...pe.levels } } : {}),
               ...('level' in pe ? { levels: { ...(sc.levels || {}), [realm]: pe.level } } : {}),
               ...('voice' in pe ? { voice: pe.voice } : {}) };
    });
    // LES NOMS VOYAGENT (docs/band-scenes.md, lot 1) : les scènes du patch sont les ÉTATS de la lane,
    // avec leur nom ; chaque scène du brouillon pointe le sien — /live et la feuille de scène les lisent
    if (L) {
      L.states = x.scenes.map(pe => ({ id: 'st-' + realm + '-' + pe.id, name: (pe.name && String(pe.name).trim()) || String(pe.id),
        blocks: { ...(pe.blocks || {}) }, params: { ...(pe.params || {}) }, branches: { ...(pe.branches || pe.lanes || {}) } }));
      p.scenes.forEach(sc => { sc.branches = sc.branches || {};
        sc.lanes = { ...(sc.lanes || {}), [realm]: { ...((sc.lanes || {})[realm] || {}), state: 'st-' + realm + '-' + sc.id } }; });
    }
  }
  // ── UN PATCH v1 SE LIE PAR SON RÔLE, COMME UN v2 (docs/patches.md §3 ; 2026-10-13) ──────────
  // Ce chemin partait du brouillon VIERGE : guitare figée sur '1', une lane voix vide sur '2', un clavier — et la
  // lane du patch ne portait aucun rôle. Sur une carte où la voix est en 1 et la guitare en 2 (la Volt du mainteneur), la
  // lane du patch écoutait le micro, et la guitare tombait dans la lane voix VIDE qui la sortait sèche : « je n'ai
  // plus aucun son de patch », pédale de volume comprise. Et comme le brouillon du Designer passe avant le fichier
  // (store._load_patch_preset), ▶ Play et le pied jouaient ce branchement-là. Tous les patches de golem.fm sont v1.
  // La lane se lie donc à (rôle, 1) — le bridge la résout vers l'entrée de ce rôle sur la carte du moment
  // (preset_view, liaison par nom) — et les lanes vides des autres rôles s'en vont, comme dans `seatPatchLane`.
  if (L && L.role !== 'drums') {
    if (MIDI_ROLES.includes(L.role)) { L.midi = true; L.in_sel = 'usb'; }
    else { L.in_role = L.role; L.in_nth = 1; L.in_sel = L.in_sel || '1'; }
    p.lanes = p.lanes.filter(x => x === L || laneBlocks(x).length);
  }
  return p;
};


// ── ARRANGEMENT sur la LIGNE de setlist (docs/setlists.md §9, arrangement.md §4) ─────────────
// Les mêmes aides que l'onglet ▤ du Designer utilisait, sorties d'ici pour que le détail d'une
// ligne (Songs ▸ Setlists) monte l'éditeur avec la palette du preset de la ligne.
export const ARR_NEVER = ['volume', 'tuner'];
export const emptyArrangement = () => ({ type: 'arrangement', id: 'arr-line',
  params: { advance: 'bars', sig: { num: 4, den: 4 }, sections: [] } });
// ce qu'une section peut forcer = les pédales : ni ampli/cab (une décision de SON = une scène),
// ni le volume système, ni les services — groupées par lane et par branche
// les blocs d'une chaîne qu'une SECTION peut forcer (ni ampli/cab — une décision de son est une
// scène —, ni service, ni volume système) : la règle est ici, partagée par les deux vues
const arrKeep = (arr, fxDefs) => {
  const def = t => (fxDefs || []).find(e => e.type === t) || {};
  return (arr || []).filter(b => b && b.id
    && !CONFIG_SERVICE_TYPES.includes(b.type) && !ARR_NEVER.includes(b.type)
    && !['amp', 'cab'].includes(def(b.type).category))
    .map(b => ({ id: b.id, type: b.type, name: b.label || def(b.type).short || def(b.type).name || b.type,
                 foot: b.foot || null, bypass: !!b.bypass,
                 cparam: CONTENT_PARAM[b.type] || null,
                 cbase: CONTENT_PARAM[b.type] ? (b.params || {})[CONTENT_PARAM[b.type]] : null }));
};

// LES ENTRÉES d'un arrangement = les MUSICIENS (une lane = une entrée de la carte = quelqu'un),
// avec de quoi les nommer (« Guitar 1 · IN 1 — le mainteneur ») et ce qu'ils peuvent forcer. Contrairement à
// `arrangementLanes`, une lane SANS bloc reste dans la liste : elle existe dans le morceau, elle ne
// change simplement rien — et le dire vaut mieux que la faire disparaître (2026-09-10).
export const arrangementEntries = (p, fxDefs) => normLanes(p || {}).map(L => {
  const c = L.chain || {};
  const blocks = [...arrKeep(c.pre, fxDefs), ...arrKeep(c.post, fxDefs),
                  ...(((c.split || {}).branches) || []).flatMap(br => arrKeep(br.blocks, fxDefs))];
  return { id: L.id, key: L.key, name: L.name, role: L.role, midi: !!L.midi,
           in_sel: L.in_sel, in_role: L.in_role, in_nth: L.in_nth, blocks };
});

export const arrangementLanes = (p, fxDefs, laneName) => {
  const def = t => (fxDefs || []).find(e => e.type === t) || {};
  const nm = laneName || (k => k === '2' ? 'Voice' : k === 'k' ? 'Keys' : 'Guitar');
  const keep = arr => arrKeep(arr, fxDefs);
  const out = [];
  normLanes(p || {}).forEach(L => {
    const c = L.chain, label = L.name || nm(L.key);
    const gl = [...keep(c.pre || []), ...keep(c.post || [])];
    if (gl.length) out.push({ key: L.key, label, blocks: gl });
    (((c.split || {}).branches) || []).forEach((br, i) => {
      const bl = keep(br.blocks || []);
      if (bl.length) out.push({ key: L.key + '/br' + i, label: label + ' · ' + String(br.id || ('lane ' + (i + 1))).replace(/^lane-/, ''), blocks: bl });
    });
  });
  return out;
};
// tous les blocs à id du preset (lanes + config) avec leur switch : les switches déjà pris
export const footBlocksOf = p => {
  const out = [];
  const walk = arr => (arr || []).forEach(b => { if (b && b.id) out.push({ id: b.id, type: b.type, foot: b.foot, label: b.label }); });
  normLanes(p || {}).forEach(L => walk(laneBlocks(L)));
  const cfg = (p && p.config) || {};
  // + `arr` (2026-09-30) : l'arrangement a sa lane à part et n'était pas recensé — son switch n'était pas
  // « pris » pour les autres blocs. MÊME liste que store._foot_blocks côté rack.
  ['gen', 'rec', 'arr'].forEach(k => walk((cfg[k] || {}).blocks));
  return out;
};

// ── LES ÉTATS DE LANE (docs/band-scenes.md) — miroir client de bridge/store.ensure_lane_states ──
// Une lane porte ses ÉTATS nommés (« Pick », « Fuzz ») ; une scène en choisit un par lane
// (`scene.lanes[<lane>].state`). La table plate de la scène (blocks / params / branches) reste ce que
// le moteur lit : elle est le MIROIR de l'état. Toute écriture passe par ces aides — le Designer les
// appelle, le bridge refait la même réconciliation au load/save pour les autres écrivains.
const sortedStr = x => JSON.stringify(x, (k, v) => (v && typeof v === 'object' && !Array.isArray(v))
  ? Object.keys(v).sort().reduce((o, kk) => { o[kk] = v[kk]; return o; }, {}) : v);
export const laneSets = L => {
  const ids = new Set(), types = new Set(), brs = new Set();
  laneBlocks(L).forEach(b => { if (b && b.id) ids.add(String(b.id)); if (b && b.type) types.add(String(b.type)); });
  ((((L && L.chain) || {}).split || {}).branches || []).forEach(br => { if (br && br.id) brs.add(String(br.id)); });
  return { ids, types, brs };
};
const pick = (o, keep) => Object.fromEntries(Object.entries(o || {}).filter(([k]) => keep(k)));
export const laneSlice = (sc, L) => { const { ids, types, brs } = laneSets(L); sc = sc || {};
  return { blocks: pick(sc.blocks, k => ids.has(k) || types.has(k)), params: pick(sc.params, k => ids.has(k)),
           branches: pick(sc.branches, k => brs.has(k)) }; };
const otherTypesOf = (p, laneId) => { const t = new Set();
  ((p && p.lanes) || []).filter(L => L && L.id !== laneId).forEach(L => laneSets(L).types.forEach(x => t.add(x))); return t; };
export const writeLaneSlice = (sc, L, content, otherTypes) => { const { ids, types, brs } = laneSets(L);
  const ot = otherTypes || new Set();
  sc.blocks = { ...pick(sc.blocks, k => !ids.has(k) && !(types.has(k) && !ot.has(k))), ...((content || {}).blocks || {}) };
  sc.params = { ...pick(sc.params, k => !ids.has(k)), ...((content || {}).params || {}) };
  sc.branches = { ...pick(sc.branches, k => !brs.has(k)), ...((content || {}).branches || {}) }; };
export const laneStateId = (laneId, sceneId) => 'st-' + laneId + '-' + sceneId;
// l'état qu'une scène joue sur une lane — réel, ou VIRTUEL (implicite pas encore écrit par le bridge)
export const laneStateAt = (p, L, sc) => {
  if (!L || !sc) return null;
  const sid = ((sc.lanes || {})[L.id] || {}).state;
  const st = (L.states || []).find(x => x && x.id === sid);
  if (st) return st;
  return { id: laneStateId(L.id, sc.id), name: (sc.name && String(sc.name).trim()) || String(sc.id), implicit: true, virtual: true,
           ...laneSlice(sc, L) };
};
// matérialise états implicites et pointeurs manquants (sans réconciliation) : avant tout geste d'attribution
export const ensureLaneStates = n => {
  if (!isV2(n)) return n;
  (n.lanes || []).forEach(L => {
    L.states = (L.states || []).filter(x => x && x.id);
    (n.scenes || []).forEach(sc => {
      sc.branches = sc.branches || {};
      const ent = (sc.lanes || {})[L.id] || {};
      if (ent.state && L.states.some(x => x.id === ent.state)) return;
      let sid = laneStateId(L.id, sc.id);
      const taken = L.states.find(x => x.id === sid);
      if (taken && !taken.implicit) { let k = 2; while (L.states.some(x => x.id === sid + '-' + k)) k++; sid = sid + '-' + k; }
      if (!L.states.some(x => x.id === sid)) L.states.push({ id: sid, name: (sc.name && String(sc.name).trim()) || String(sc.id), implicit: true, ...laneSlice(sc, L) });
      sc.lanes = { ...(sc.lanes || {}), [L.id]: { ...ent, state: sid } };
    });
  });
  return n;
};
// la scène d'index `si` joue l'état `stateId` sur la lane : pointeur + tranche recopiée dans la table plate
export const assignLaneState = (n, laneId, si, stateId) => {
  ensureLaneStates(n);
  const L = (n.lanes || []).find(x => x.id === laneId), sc = (n.scenes || [])[si];
  const st = L && (L.states || []).find(x => x.id === stateId);
  if (!L || !sc || !st) return false;
  writeLaneSlice(sc, L, st, otherTypesOf(n, laneId));
  sc.lanes = { ...(sc.lanes || {}), [laneId]: { ...((sc.lanes || {})[laneId] || {}), state: stateId } };
  // un état pointé par plusieurs scènes cesse d'être « la copie d'une scène » : il garde son nom, il devient un objet de la lane
  if ((n.scenes || []).filter(s => ((s.lanes || {})[laneId] || {}).state === stateId).length > 1) delete st.implicit;
  return true;
};
// un état NEUF, copie de ce que la scène joue sur cette lane, et la scène le joue
export const newLaneState = (n, laneId, si, name) => {
  ensureLaneStates(n);
  const L = (n.lanes || []).find(x => x.id === laneId), sc = (n.scenes || [])[si];
  if (!L || !sc) return null;
  let k = 1, id; do { id = 'st-' + laneId + '-n' + (k++); } while ((L.states || []).some(x => x.id === id));
  L.states.push({ id, name: name || 'New state', ...laneSlice(sc, L) });
  sc.lanes = { ...(sc.lanes || {}), [laneId]: { ...((sc.lanes || {})[laneId] || {}), state: id } };
  return id;
};
export const renameLaneState = (n, laneId, stateId, name) => {
  ensureLaneStates(n);
  const st = (((n.lanes || []).find(x => x.id === laneId) || {}).states || []).find(x => x.id === stateId);
  if (!st) return; st.name = String(name || '').slice(0, 24); delete st.implicit;
};
// ÉDITER UNE SCÈNE, C'EST ÉDITER SON ÉTAT : toute tranche qui change dans une scène dont le pointeur n'a
// pas bougé est recopiée dans l'état et dans les autres scènes qui le pointent (« Pick » est le même son
// sur A, B et D). Appelé par l'`upd` du Designer après chaque mutation.
export const propagateLaneStates = (prev, n) => {
  if (!isV2(n) || !prev) return n;
  (n.lanes || []).forEach(L => {
    const ot = otherTypesOf(n, L.id);
    (n.scenes || []).forEach((sc, k) => {
      const ps = (prev.scenes || [])[k];
      if (!ps || ps.id !== sc.id) return;
      const sid = ((sc.lanes || {})[L.id] || {}).state;
      if (!sid || sid !== ((ps.lanes || {})[L.id] || {}).state) return;
      const PL = (prev.lanes || []).find(x => x.id === L.id);
      const now = laneSlice(sc, L), before = laneSlice(ps, PL || L);
      if (sortedStr(now) === sortedStr(before)) return;
      const st = (L.states || []).find(x => x.id === sid);
      if (st) Object.assign(st, now);
      (n.scenes || []).forEach((o, j) => { if (j !== k && ((o.lanes || {})[L.id] || {}).state === sid) writeLaneSlice(o, L, now, ot); });
    });
  });
  return n;
};
// le bloc qui fait l'IDENTITÉ d'une lane dans une scène (ampli, capture, instrument) — le nom d'une ligne
// quand l'état n'a pas d'autre nom que celui de la scène. Même règle que store.scene_lane_states.
const IDENTITY_TYPES = ['amp', 'amp-nam', 'pedal-nam', 'preamp-nam', 'vital', 'piano', 'organ', 'ep', 'pads', 'drive', 'comp'];
export const blockOnInScene = (b, sc) => { const sb = (sc && sc.blocks) || {};
  if (b.id != null && b.id in sb) return sb[b.id] !== false;
  if (b.type in sb) return sb[b.type] !== false;
  return !b.bypass; };
export const laneIdentity = (L, sc) => { const bs = laneBlocks(L).filter(b => b && b.type);
  return bs.find(b => IDENTITY_TYPES.includes(b.type) && blockOnInScene(b, sc)) || bs.find(b => IDENTITY_TYPES.includes(b.type)) || bs[0] || null; };
export const shortBlockName = bk => { if (!bk) return '';
  if (bk.variant && ARCH_NAME[bk.variant]) return ARCH_NAME[bk.variant];
  const lb = String(bk.label || '').trim();
  if (lb && lb.length <= 16) return lb;
  if (lb) { const nb = lb.split(/\s+/).slice(1).join(' '); if (nb.length && nb.length <= 16) return nb; }
  return SHORT[bk.type] || (NAME[bk.type] || bk.type).split(' (')[0]; };
// ce qu'une ligne d'accord affiche pour une lane dans une scène : le nom de l'état, sinon le bloc d'identité
export const laneLineName = (p, L, sc) => { const st = laneStateAt(p, L, sc);
  return st && !st.implicit ? st.name : (shortBlockName(laneIdentity(L, sc)) || (L && L.name) || ''); };
export const laneMutedIn = (sc, L) => ((((sc || {}).lanes || {})[L.id]) || {}).mute === true;
// `scene.lanes[x]` est un ANCIEN mute de BRANCHE s'il porte `mute` sans `state` ni `level` ; sinon c'est une
// entrée de lane (coupure, niveau, état). UN critère, le même que store.is_legacy_branch_mute et golem.fm.
export const isLegacyBranchMute = v => !!v && typeof v === 'object' && 'mute' in v && !('state' in v) && !('level' in v);

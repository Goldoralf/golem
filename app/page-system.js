// SPDX-License-Identifier: GPL-3.0-or-later
// Page Système — 3 sous-onglets :
//   Dashboard : santé LIVE (WebSocket) avec ACTIONS dans les tuiles en défaut (restart bridge/Reaper,
//               resync OSC, gouverneur) + buffer audio Reaper réglable (chips 64…512).
//   Content   : inventaire (presets/scènes, amps/cabs/pédales, blocs FX, templates, slots FCB).
//   Update    : mise à jour git bornée aux RELEASES (tags) — check réseau + bascule + restart bridge.
import { HealthPage } from './page-health.js';
import { healthDot } from './health-model.mjs';
import { html, useAsync, useState, useEffect, useRef, post, del, cls, esc, go, shellTabletSheet, setTopAction } from './lib.js';
import { Icon, ModeIcon } from './icons.js';
import { RecPanel } from './designer-sheets.js';
import { FootListButton, FootListPicker } from './foot-list-picker.js';   // la liste au pied d'un mode (2026-10-15)

// faisabilité par taille de buffer (guitare live @48 kHz, Volt en USB)
const BUF_HINT = {
  64: 'aggressive — USB dropouts likely, try only with perf governor',
  96: 'tight — great feel, watch xruns',
  128: 'live sweet spot (default)',
  192: 'safe live',
  256: 'comfortable — latency starts to be felt',
  384: 'high latency — studio/mix only',
  512: 'high latency — studio/mix only',
  1024: 'very high latency — mixing only',
  2048: 'very high latency — mixing only',
};

// tuile de statut : LED (ok/warn/bad, pulse si non-ok) + nom + détail + ACTION optionnelle
// action = {label, onClick, busy, nav} — le bouton vit DANS la tuile (agir là où c'est rouge). `nav` = il ne fait
// qu'emmener ailleurs : il reste en lecture seule ; une action (restart, boost) disparaît (edit-only, docs/shell.md §2).
const Tile = (name, detail, state, action) => html`<div class=${cls('tile-st', state)}>
  <span class="tile-led"></span>
  <div class="tile-txt"><div class="tile-nm">${name}</div><div class="tile-dt">${detail}</div></div>
  ${action ? html`<button class=${cls('tile-act', !action.nav && 'edit-only')} disabled=${!!action.busy}
    onClick=${action.onClick}>${action.busy ? '⏳' : action.label}</button>` : ''}
  ${!action && (state === 'bad' || state === 'warn') ? html`<span class="tile-flag">!</span>` : ''}
</div>`;

// ── sous-onglet Mode (docs/modes.md) — le « contrat d'attention » ─────────────
// 4 cartes (une par mode livré) : icône, description, services montés, verrou.
// Le mode courant vient du state WS (rig.state.mode) ; bascule = POST /api/mode.
// vocabulaire ALIGNÉ sur les instruments du patch Soundcard (patch.INSTRUMENTS : guitar/bass/
// voice/keys/drums/pads/line) + les outils logiciels de la lane Players/Recorder du Designer
const SVC_LABELS = { guitar: 'Guitar', bass: 'Bass', voice: 'Voice', drums: 'Drums', line: 'Line',
  keys: 'Keys', pads: 'Pads', looper: 'Looper', backing: 'Backing', sample: 'Sample', perfrec: 'Rec',
  standard: 'Standards', drummachine: 'Drum machine', arrangement: 'Arrangement', compo: 'Riff' };
// couture Mode ⇄ Soundcard (2026-07-19) : les services d'ENTRÉE parlent le langage
// du patch (icônes/labels de la carte), les OUTILS logiciels sont séparés.
// « Rec » a quitté Tools (2026-09-08) : le REC n'est pas un outil qu'on joue, c'est une décision
// sur ce que devient la soirée — la rangée REC porte les trois états (Off · Global · Custom).
const TOOL_SVCS = ['backing', 'standard', 'sample', 'drummachine', 'looper', 'compo'];   // + Compo (docs/compo.md §7)   // ordre 2026-09-08   // + Standards, Drum machine (2026-09-08)
// politique du métronome par mode (docs/modes.md) : sa config est globale, son DÉCLENCHEMENT
// dépend de la situation de jeu — un click qui fuit en façade sur scène, jamais.
const CLICK_MODES = [
  ['off', 'Off', 'the metronome never starts in this mode'],
  ['preset', 'Per preset', "the Click block of the loaded preset decides — active = it plays"],
  ['manual', 'Manual', 'a plain on/off switch, independent from presets'],
];
// vues de la page Live (mode.ui.live) — miroir de modes.LIVE_VIEWS côté bridge.
// docs/live-pages.md (2026-10-15) : la Timeline devient deux pages ; l'id `timeline` reste celui du Concert
const LIVE_VIEWS = [
  ['pedalboard', 'Pedalboard', 'the FCB mirror — stomps, scenes, banks. What your feet can reach.'],
  ['rehearsal', 'Rehearsal', 'pick a section of the song, start the band from it, loop it.'],
  ['timeline', 'Concert', 'the music stand — readable from 2 m: the section, the bar, what comes next.'],
];

// LA PAGE MODE (mockups/mode-page.html, propositions C + E retenues le 2026-10-20) : les modes en LISTE à gauche (le mode
// se lit avant d'être choisi : nom, ce qu'il fait, le point du mode actif, 🔒) et la fiche à droite, en UNE colonne dans
// l'ordre du 2026-09-08, rangée en trois temps — Who and where · On stage · Time and takes. Seconde vue : tous les modes
// côte à côte (#/system/mode/compare), un réglage par ligne ; le sélecteur de vue est dans la barre du haut.
export function ModePanel({ rig, desktop, platform, view }) {
  const { data, reload } = useAsync(() => fetch('/api/modes').then(r => r.json()), []);
  const { data: cards, reload: reloadCards } = useAsync(() => fetch('/api/cards').then(r => r.json()), []);
  const { data: roster } = useAsync(() => fetch('/api/band').then(r => r.json()), []);
  // la LISTE AU PIED par défaut du mode (docs/patches.md §7) : setlists ▤ et banks de sons ⛓
  const { data: lists } = useAsync(() => fetch('/api/setlists').then(r => r.json()).catch(() => null), []);
  const cur = (((rig && rig.state) || {}).mode) || {};
  // mode ACTIF : /api/modes.current (refetché par api() après chaque action -> toujours frais),
  // le state WS en repli — ceinture et bretelles contre une page qui raterait un push
  const curId = (data && data.current) || cur.id;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const api = async (path, body) => {
    setBusy(true); setErr(null);
    // un non-2xx avec un corps JSON (409 needs_confirm, verrou…) revient COMME réponse : c'est
    // `pick` qui sait quoi en faire ; sans corps, l'erreur brute s'affiche
    const r = await post(path, body).catch(e => (e && e.body && typeof e.body === 'object') ? { ...e.body, status: e.status } : { error: String(e) });
    if (r && r.error && !r.needs_confirm) setErr(r.error);
    await reload();
    setBusy(false);
    return r;
  };
  // Un mode peut déclarer l'ESPACE de destination des prises. Quand la bascule tombe pendant
  // un enregistrement ou depuis un mode verrouillé, le bridge répond 409 needs_confirm : la
  // prise EN COURS ne bouge pas (son tag est gelé à son départ), c'est la SUIVANTE qui change
  // — et ça se dit avant, pas après.
  const pick = async id => {
    if (id === curId || busy) return;
    const r = await api('/api/mode', { id });
    if (r && r.needs_confirm) {
      const name = ((((roster || {}).bands) || []).find(b => b.id === r.band) || {}).name || r.band;
      setErr(null);
      if (confirm(r.message + '\n\nSwitch anyway, and record to ' + name + ' from now on?')) {
        await api('/api/mode', { id, confirm: true });
      }
    }
  };
  const svcVal = (m, k) => (m.services || {})[k] !== false;   // absent = autorisé
  // toggle : préserve les services déjà posés + bascule k. Le backend filtre sur modes.SERVICES
  // et un service absent = autorisé -> n'envoyer que les vetos suffit. Édition DIRECTE (plus de
  // crayon, décision 2026-07-26) : chaque chip est togglable en place, sur toutes les cartes.
  const toggleSvc = (m, k) => {
    const services = { ...(m.services || {}) };
    services[k] = !svcVal(m, k);
    api('/api/mode/update', { id: m.id, services });
  };
  const reset = m => api('/api/mode/reset', { id: m.id });

  const modes = (data && data.modes) || [];
  // le patch de la carte ACTIVE (state WS) — la carte de mode affiche SES entrées
  const patchSt = (((rig && rig.state) || {}).inputmap) || {};
  // ── section Inputs = dérivée du PATCH (couture Soundcard) : chaque instrument patché devient un
  // chip du mode, avec son label/icône de la carte. Le 1er instrument mélodique (guitar/bass) est
  // l'instrument PRINCIPAL, toujours monté (fixe) ; les autres entrées (2e guitare, basse, voix,
  // line) + le contrôleur (keys/pads) sont des services togglables. Plus de liste codée en dur. ──
  const audioIns = (patchSt.inputs || []).filter(x => x.role && !['none', 'other'].includes(x.role));
  const primaryIn = audioIns.find(x => ['guitar', 'bass'].includes(x.role));
  const midiCtl = patchSt.midi;                  // contrôleur MIDI USB (keys / pads / keys-pads)
  // chips d'entrée audio SUPPLÉMENTAIRES (hors principal) : {key=role, icon=role, label}
  const extraIns = audioIns.filter(x => x !== primaryIn).map(x => ({ key: x.role, icon: x.role, label: x.label || SVC_LABELS[x.role] || x.role }));
  // chips du contrôleur MIDI : keys et/ou pads selon son rôle (keys-pads = les deux)
  const midiIns = !midiCtl || midiCtl.role === 'none' ? []
    : (midiCtl.role === 'keys-pads' ? ['keys', 'pads'] : [midiCtl.role]).map(k => ({ key: k, icon: k, label: SVC_LABELS[k] || k }));
  const inChips = [...extraIns, ...midiIns];      // tous les services d'entrée togglables du mode
  // ── carte DÉCLARÉE par le mode : « Any » + toutes les cartes déjà rencontrées (registre
  // gear-registry) + celle qui est branchée. Déclarer une carte, c'est ce qui permet au rack
  // de RAPPELER le mode quand on adopte cette carte (docs/modes.md §4) — et ce qui allume le
  // badge « not connected » quand elle n'est pas là.
  // les cartes marquées « jamais proposée » (l'audio générique d'un dock) sont hors registre ici :
  // ce sont des interfaces qu'on ne joue pas, elles n'ont rien à faire dans un choix de mode.
  const cardIds = [...new Set(((cards || {}).registry || []).filter(c => !c.ignored).map(c => 'hw:' + c.id)
    .concat(patchSt.card ? [patchSt.card] : []))];
  const cardChoices = [{ id: '', label: 'Any' },
    ...cardIds.map(id => ({ id, label: id.replace(/^hw:/, '') }))];
  // ── ESPACE déclaré par le mode : « Home » enregistre pour l'espace perso, « Rehearsal » et
  // « Gig » pour le groupe. Le musicien ne tague plus rien, il choisit un mode. Même contrat
  // que la carte : « Keep current » = le mode ne touche à rien (défaut des 5 modes d'usine).
  // La valeur est un bands[].id opaque, jamais un slug — on n'affiche que le nom.
  const spaces = ((roster || {}).bands) || [];
  // Pas de « Keep current » (retour 2026-09-07) : ce troisième sens — « le mode ne touche
  // à rien » — n'existe pas ici, on choisit l'espace et c'est tout. Le désarmement, lui, existe
  // toujours : il était un RE-TAP sur la pastille active, que rien à l'écran n'annonçait ; il
  // s'appelle « None » depuis que la rangée est un segmenté (2026-09-20). Même geste, un nom.
  const spaceChoices = [{ id: '', label: 'None' },
    ...spaces.map(b => ({ id: b.id, label: (b.kind === 'personal' ? '👤 ' : '') + (b.name || b.id) }))];
  const spaceName = id => (spaces.find(b => b.id === id) || {}).name;
  const svcChip = (m, it) => html`<span
    class=${cls('mode-svc', 'tog', svcVal(m, it.key) && 'on')}
    title=${it.label + (svcVal(m, it.key) ? ' — allowed, tap to turn off' : ' — off in this mode, tap to allow')}
    onClick=${() => !busy && toggleSvc(m, it.key)}>
    <${Icon} id=${it.icon} /> ${it.label}</span>`;
  // chip d'un OUTIL logiciel (looper/backing/sample/rec) — pas d'entrée patch, juste le label
  const toolChip = (m, k) => html`<span
    class=${cls('mode-svc tog ro-inert', svcVal(m, k) && 'on')}
    title=${SVC_LABELS[k] + (svcVal(m, k) ? ' — allowed, tap to turn off' : ' — off in this mode, tap to allow')}
    onClick=${() => !busy && toggleSvc(m, k)}>${SVC_LABELS[k]}</span>`;

  // ── MAÎTRE / DÉTAIL (refonte 2026-07-29, rapport de l'agent UX) ───────────────────────────
  // La grille de 8 cartes de 362 px ne tenait pas dans l'écran (2,9 écrans à 800×480 : Gig et
  // Show sous la ligne de flottaison), et surtout elle rendait le geste RARE (éditer un chip)
  // intapable — 70 cibles de 21 px séparées de 4 px, soit la moitié du plancher tactile, où un
  // faux tap DÉMONTE une entrée en silence. On le découvrait au concert.
  //
  // Règle qui fait tout marcher : **le bandeau SÉLECTIONNE, il n'ACTIVE pas.** Lire Gig ne doit
  // pas verrouiller l'UI. L'activation est une action primaire LIBELLÉE dans le détail. Ça coûte
  // un tap de plus, sur des cibles de 118 px et 46 px au lieu de 34 : basculer démonte et remonte
  // le rig, ça mérite d'être dit avant de le faire.
  const [sel, setSel] = useState(null);
  const cur2 = modes.find(m => m.id === (sel || curId)) || modes[0] || null;
  // le tiroir du REC depuis la page Modes (2026-09-08) : il édite LA config globale — la même
  // que le bloc Rec du Designer. Pas de réglage par mode : un mode enregistre (avec la globale) ou pas.
  const [recOpen, setRecOpen] = useState(false);
  const [footPick, setFootPick] = useState(false);     // le modal de la liste au pied (foot-list-picker.js)
  const [inArm, setInArm] = useState(null);             // la pastille d'entrée qui laisserait le mode muet, armée
  // LES ENTRÉES DE LA CARTE DU MODE (2026-09-09) : Home sur la Volt = IN 1 Guitar, IN 2 Voice ;
  // Gig sur la 8×8 = IN 1 Guitar 1 … IN 7 Keys. Le patch appartient à la CARTE (input-map.md) ; le
  // mode la déclare et NOMME ses entrées — éditable même débranchée (/api/inputmap?card=).
  const [ioOpen, setIoOpen] = useState(false);
  // « Prepare its patch → » sur Soundcard (rangée CARD, carte attendue par le mode) : on arrive ici la feuille ouverte
  useEffect(() => { try { if (sessionStorage.getItem('golem.openInputs')) { sessionStorage.removeItem('golem.openInputs'); setIoOpen(true); } } catch (e) {} }, []);
  const [ioMap, setIoMap] = useState(null);
  const ioCard = cur2 && cur2.card ? cur2.card.replace(/^hw:/, '') : (patchSt.card || '').replace(/^hw:/, '');
  const loadIo = () => ioCard && fetch('/api/inputmap?card=' + encodeURIComponent(ioCard)).then(r => r.json()).then(setIoMap).catch(() => setIoMap(null));
  useEffect(() => { loadIo(); }, [ioCard]);                 // la rangée Inputs en a besoin, pas seulement la feuille
  // les ENTRÉES NUMÉROTÉES de la carte du mode, chacune on/off pour CE mode (2026-09-09 : « dans
  // Gig je devrais avoir la liste complète ») — remplace les quatre vetos par instrument de la carte branchée
  // entrées audio de la carte du mode + ports USB du RACK (liés) — même clé rôle#numéro pour les deux
  const inputChips = [...(((ioMap || {}).inputs || [])), ...(((ioMap || {}).usb || []).filter(u => u.bound))]
    .filter(e => e.role && e.role !== 'none' && e.nth != null)
    .map(e => ({ key: e.role + '#' + e.nth, label: e.name, icon: e.role, person: e.person_name }));
  const inputOff = (m, k) => ((m && m.inputs_off) || []).includes(k);
  // COUPER LA DERNIÈRE ENTRÉE JOUÉE demande un second tap (docs/modes.md §3.2, 2026-10-24) : un testeur Windows avait
  // coupé « Guitar 1 », sa seule entrée, dans Pedalboard — chaque son guitare était refusé, sans qu'il le relie au mode
  const toggleInput = (m, k) => { const off = new Set(m.inputs_off || []);
    if (!off.has(k) && inArm !== k && inputChips.every(c => c.key === k || off.has(c.key))) {
      setInArm(k); setTimeout(() => setInArm(a => a === k ? null : a), 3000); return; }
    setInArm(null);
    if (off.has(k)) off.delete(k); else off.add(k);
    api('/api/mode/update', { id: m.id, inputs_off: [...off] }); };
  const ioSet = async body => { await post('/api/inputmap', { card: ioCard, kind: 'input', ...body })
    .catch(e => setErr((e && e.body && e.body.error) || String(e)));   // « nothing plugged on USB 3 » doit se LIRE
    loadIo(); };
  // DÉCLARER UNE CARTE À LA MAIN (2026-09-09) : « jouer en répète avec la carte du batteur » — elle
  // n'a jamais été branchée ici, on la décrit (nom, entrées, sorties), le mode la déclare, on nomme ses entrées
  const [newCard, setNewCard] = useState(null);
  const declareCard = async () => {
    const r = await post('/api/cards/declare', newCard).catch(e => ({ error: String(e) }));
    if (r && r.error) { setErr(r.error); return; }
    setNewCard(null);
    // ⚠ pas de rechargement de page : il masquait un refus (mode actif et verrouillé -> 409) et la
    // carte déclarée restait « Any » sans un mot (vécu, 2026-09-09). Le registre se relit.
    await reloadCards();
    await api('/api/mode/update', { id: cur2.id, card: 'hw:' + r.card.id });
  };
  const { data: recD, reload: reloadRec } = useAsync(() => fetch('/api/recorder').then(r => r.json()).catch(() => null), []);
  const recGlobal = recD || { in1: true, in2: true, usb: true, mode: 'mix', mix: true };
  const recSummary = r => [[r.in1, 'IN 1'], [r.in2, 'IN 2'], [r.usb, 'USB']].filter(x => x[0]).map(x => x[1]).join('+')
    + ' · ' + ({ mix: 'Mix', tracks: 'Multi', tracks_di: r.mix !== false ? 'Mix + Multi + DI' : 'Multi + DI' })[r.mode || 'mix']
    + (r.transcribe === 'auto' ? ' · auto-transcribe' : '');
  const setRec = async (k, v) => {                      // k au vocabulaire de la feuille (rec_mode) -> celui du fichier (mode)
    await post('/api/recorder', { [k === 'rec_mode' ? 'mode' : k]: v }).catch(() => null);
    reloadRec();
  };

  // ancre de doc (docs/user-docs.md §4) : mode.row.<rangée> — « Live screen » -> mode.row.live-screen
  const sectionRow = (label, body) => html`<div class="mode-sec" data-doc=${'mode.row.' + label.toLowerCase().replace(/ /g, '-')}>
    <span class="mode-sec-lb">${label}</span><div class="mode-svcs">${body}</div></div>`;

  // ── DEUX SÉMANTIQUES, DEUX FORMES (2026-09-20 : « les boutons on/off sont placés
  // aléatoirement sans logique ») ───────────────────────────────────────────────────────────────
  // Ce panneau mélangeait deux choses derrière LA MÊME pastille verte : « UN choix parmi
  // plusieurs » (Live screen, Click, REC, Arrangement, Card) et « N interrupteurs indépendants »
  // (Inputs, Tools). L'œil ne pouvait pas les distinguer — et l'ordre s'y ajoutait : REC disait
  // « Off · On » pendant qu'Arrangement disait « ON · OFF », en capitales.
  //   choix exclusif  -> SEGMENTÉ (`.tb-seg`, la forme que le produit emploie déjà partout pour
  //                      « un parmi N » : rôle de la Library, banks des presets) ;
  //   interrupteurs   -> pastilles (inchangées) ;
  //   ordre           -> le MOINS actif d'abord, toujours : Off · On, Off · Per preset · Manual ;
  //   casse           -> « Off » / « On », jamais « OFF » / « ON ».
  // Une ACTION (✎, ＋ card) ne rentre jamais dans le segment : elle n'est pas un des choix.
  const segRow = (label, opts, cur, onPick, after) => sectionRow(label, html`
    <div class="tb-seg mode-seg">
      ${opts.map(([v, lb, ttl]) => html`<button class=${cls('ro-inert', v === cur && 'on')} title=${ttl}
        onClick=${() => !busy && v !== cur && onPick(v)}>${lb}</button>`)}
    </div>${after || ''}`);

  return html`<div class="pg-body mode-body">
    ${err ? html`<p class="mode-err">✗ ${err}</p>` : ''}

    ${view === 'compare' ? html`<${ModeCompare} modes=${modes} curId=${curId} spaceName=${spaceName} lists=${lists}
        patchCard=${patchSt.card} onOpen=${id => { setSel(id); go('system/mode'); }} />` : html`<div class="mode-split">
    ${/* LA LISTE (proposition C) : chaque mode se LIT — nom, ce qu'il fait, le point du mode actif, 🔒 d'un mode verrouillé.
          Elle SÉLECTIONNE, elle n'active pas (règle du 2026-07-29) : l'activation reste « ⏻ Switch to » dans la fiche. */''}
    <nav class="mode-side" data-doc="mode.list">
      ${modes.map(m => html`<button class=${cls('ms-item', cur2 && m.id === cur2.id && 'ms-sel', m.id === curId && 'ms-live')}
        data-doc=${'mode.item:' + m.id} title=${m.desc || m.name} onClick=${() => setSel(m.id)}>
        <span class="ms-ico"><${ModeIcon} mode=${m} /></span>
        <span class="ms-txt"><b>${m.name}${m.ui && m.ui.locked ? ' 🔒' : ''}</b><small>${(m.desc || '').split(/ — |\. /).slice(0, 2).join(' — ')}</small></span>
      </button>`)}
      ${/* LE SÉLECTEUR DE VUE (« un bouton switch quelque part », 2026-10-20) : en bas de la liste ici, en bas du tableau
            dans la vue comparée — la barre du haut n'a pas la place (il y masquait Connect et About) */''}
      <button class="ms-view" data-doc="mode.compare" onClick=${() => go('system/mode/compare')} title="every mode side by side">▦ All modes side by side</button>
      <span class="ms-hint muted">The red dot is the mode the rig runs.</span>
    </nav>
    ${cur2 ? html`<section class="mode-detail" data-doc="mode.detail">
      <header class="mode-dh">
        <span class="mode-ico"><${ModeIcon} mode=${cur2} /></span>
        <div class="mode-dh-txt">
          <b>${cur2.name}${cur2.ui && cur2.ui.locked ? html` <span title="locked UI — only Live is reachable">🔒</span>` : ''}
            ${cur2._custom ? html` <em class="mode-flag">custom</em>` : cur2._modified ? html` <em class="mode-flag">edited</em>` : ''}
            ${cur2.perf_boost && (!desktop || platform === 'win32') ? html` <em class="mode-flag" title="switching to this mode turns the CPU boost on (Dashboard) — other modes turn it off">⚡ CPU boost</em>` : ''}</b>
          ${/* ce qu'une prise faite ici dira d'elle-même à golem.fm — Show / Gig / Rehearsal */''}
          <span class="mode-desc"><em class="mode-flag rec-kind" title="recordings made in this mode carry this tag for golem.fm">REC · ${
            ({ show: 'Show', gig: 'Gig' })[cur2.take_kind || (cur2.id === 'gig' ? 'gig' : cur2.id === 'show' ? 'show' : 'rehearsal')] || 'Rehearsal'}</em> ${cur2.desc}${cur2.card
            ? html` · waits for ${esc(cur2.card.replace(/^hw:/, ''))}${patchSt.card && cur2.card !== patchSt.card
                ? html` <em class="mode-flag">not connected</em>` : ''}`
            : ''}${cur2.band
            ? html` · records to ${spaceName(cur2.band)
                ? esc(spaceName(cur2.band))
                : html`<em class="mode-flag">space unknown</em>`}`
            : ''}</span>
        </div>
        <span class="grow"></span>
        ${cur2.id === curId
          ? html`<span class="mode-live" data-doc="mode.state" title="this is the mode the rig is running">⏻ Active</span>`
          : html`<button class="primary mode-switch edit-only" data-doc="mode.state" disabled=${busy}
              title=${'switch the rig to ' + cur2.name + ' — the current mode turns off'}
              onClick=${() => pick(cur2.id)}>⏻ Switch to ${cur2.name}</button>`}
        ${cur2._modified ? html`<button class="mini edit-only" disabled=${busy} title="back to the shipped definition"
          onClick=${() => reset(cur2)}>↺</button>` : ''}
        ${cur2._custom ? html`<button class="mini danger edit-only" disabled=${busy || cur2.id === curId}
          title=${cur2.id === curId ? 'switch mode first' : 'delete this custom mode'}
          onClick=${() => { reset(cur2); setSel(null); }}>🗑</button>` : ''}
      </header>

      ${/* UNE COLONNE (retour 2026-09-08, après deux colonnes le 07) : les rangées dans l'ordre du mainteneur — Space,
            Card, Inputs · Tools, Live screen, Foot list · Click, REC, Arrangement — en trois temps (2026-10-20). La liste
            des modes à gauche a rendu la hauteur des tuiles : la fiche tient. */''}
      <div class="mode-secs">
      <div class="mode-grp" data-doc="mode.group.who">Who and where</div>
      ${spaces.length ? segRow('Space',
        spaceChoices.map(b => [b.id, b.label, b.id ? 'takes recorded in this mode go to ' + b.label
                                                   : 'this mode declares no space — takes stay where the rig already sends them']),
        cur2.band || '', v => api('/api/mode/update', { id: cur2.id, band: v })) : ''}
      ${/* CARTE attendue par le mode : « Any » = le mode ne réclame rien et survit à un
            changement d'interface ; un id = il attend CETTE carte. ＋ card déclare une carte
            jamais branchée ici (le 8×8 du batteur) — c'est une action, donc hors du segment. */''}
      ${segRow('Card',
        cardChoices.map(c => [c.id, c.label,
          c.id ? (c.id === patchSt.card ? c.id + ' — connected right now' : c.id + ' — this mode waits for that card')
               : 'any card — this mode never gets swapped out']),
        cur2.card || '', v => api('/api/mode/update', { id: cur2.id, card: v }),
        html`<span class="mode-svc tog io-edit edit-only" title="declare a card that was never plugged here (the drummer's 8×8) — name it, count its inputs, then name them"
          onClick=${() => setNewCard({ id: '', name: '', inputs: 8, outputs: 8 })}>＋ card</span>`)}
      ${sectionRow('Inputs', html`
        ${inputChips.map(it => html`<span class=${cls('mode-svc tog ro-inert', !inputOff(cur2, it.key) && 'on', inArm === it.key && 'arm')}
          title=${it.label + (it.person ? ' · ' + it.person : '') + (inputOff(cur2, it.key) ? ' — off in this mode, tap to play it' : ' — played in this mode, tap to leave it out')}
          onClick=${() => !busy && toggleInput(cur2, it.key)}><${Icon} id=${it.icon} /> ${inArm === it.key ? 'tap again — nothing would play in this mode' : esc(it.label)}</span>`)}
        ${!inputChips.length ? html`<span class="mode-svc absent" title="no input patched — tap ✎ to assign instruments">— none patched</span>` : ''}
        ${ioCard ? html`<span class="mode-svc tog io-edit edit-only" title=${'name and assign the inputs of ' + ioCard + (cur2.card ? '' : ' (the connected card — declare a card above to prepare another one)')}
          onClick=${() => setIoOpen(true)}>✎ ${esc(ioCard)}</span>` : ''}`)}
      <div class="mode-grp" data-doc="mode.group.stage">On stage</div>
      ${sectionRow('Tools', TOOL_SVCS.map(k => toolChip(cur2, k)))}
      ${/* TOOLS : des interrupteurs INDÉPENDANTS, d'où des pastilles et non un segmenté —
            on peut allumer Backing sans éteindre Looper. Même grammaire pour Inputs. */''}
      ${/* La page Live n'est pas la même selon la situation : au pied on veut le miroir du
            pédalier, en Show on veut le pupitre (setlist, PLAY, position). C'est une DONNÉE du
            mode — cf. docs/archive/show-mode.md §6. Sans ce réglage, Show affichait le pédalier et ne
            servait à rien. */''}
      ${segRow('Live screen', LIVE_VIEWS, (cur2.ui || {}).live || 'pedalboard',
        v => api('/api/mode/update', { id: cur2.id, live_view: v }))}
      ${/* LA LISTE AU PIED (patch-as-preset §7, 2026-09-30) : un DÉFAUT posé en entrant dans le mode —
            « Keep » = le mode ne touche pas au pied ; le tap « On the foot » reste libre ensuite */''}
      ${/* un BOUTON qui ouvre un modal, plus un segmenté : une case par setlist débordait dès la septième (2026-10-15) */''}
      ${sectionRow('Foot list', html`<${FootListButton} lists=${lists} value=${cur2.foot_list || ''} onOpen=${() => setFootPick(true)} />`)}
      ${footPick ? html`<${FootListPicker} lists=${lists} value=${cur2.foot_list || ''} modeName=${cur2.name}
        onPick=${v => v !== (cur2.foot_list || '') && api('/api/mode/update', { id: cur2.id, foot_list: v })}
        onClose=${() => setFootPick(false)} />` : ''}
      <div class="mode-grp" data-doc="mode.group.time">Time and takes</div>
      ${segRow('Click', CLICK_MODES, cur2.click_mode || 'manual',
        v => api('/api/mode/update', { id: cur2.id, click_mode: v }))}
      ${/* Off = le veto du service `perfrec` (l'enregistrement ne démarre pas ici, l'arrêt passe
            toujours) ; On = ce mode enregistre, avec LA config globale ; ✎ ouvre son tiroir — le
            même panneau que la feuille du bloc Rec du Designer, la même config, hors du segment
            parce que c'est une action et pas un troisième choix. */''}
      ${segRow('REC',
        [[false, 'Off', "this mode never records — the recorder can't start here (stop always works)"],
         [true, 'On', 'this mode records — with the recorder settings (✎), shared by every mode and preset']],
        !!svcVal(cur2, 'perfrec'), () => toggleSvc(cur2, 'perfrec'),
        html`<span class="mode-svc tog edit-only" title=${'recorder settings, shared by every mode and preset: ' + recSummary(recGlobal) + ' — tap to edit'}
          onClick=${() => setRecOpen(true)}>✎</span>
        <small class="mode-rec-sum" title=${recSummary(recGlobal)}>${recSummary(recGlobal)}</small>`)}

      ${/* ARRANGEMENT (2026-09-08) : le service existait dans la donnée depuis le 30 juillet
            mais aucune rangée ne le montrait — Off en Gig et Pedalboard sans que rien ne le dise.
            Le mode dit si l'automation TOURNE ici ; le preset dit s'il en a une (docs/arrangement.md §7 bis). */''}
      ${segRow('Arrangement',
        [[false, 'Off', 'no automation in this mode — the block stays editable, it just does not fire'],
         [true, 'On', 'the arrangement of the loaded song plays in this mode']],
        !!svcVal(cur2, 'arrangement'), () => toggleSvc(cur2, 'arrangement'))}
      </div>
      ${newCard ? html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && setNewCard(null)}>
        <div class="detail-card sm">
          <button class="close" onClick=${() => setNewCard(null)}>×</button>
          <h2>Declare a card</h2>
          <p class="sub muted">A card you don't have here yet. Describe it, this mode will declare it, then name its inputs. When it is plugged for real, the rack measures it and keeps your names.</p>
          <div class="set-row"><label>Id</label><input class="name-in" style="flex:1" placeholder="X88" value=${newCard.id} autofocus onInput=${e => setNewCard({ ...newCard, id: e.target.value })} /></div>
          <div class="set-row"><label>Name</label><input class="name-in" style="flex:1" placeholder="Behringer UMC1820" value=${newCard.name} onInput=${e => setNewCard({ ...newCard, name: e.target.value })} /></div>
          <div class="set-row"><label>Inputs</label><input type="number" min="1" max="64" style="width:84px" value=${newCard.inputs} onInput=${e => setNewCard({ ...newCard, inputs: +e.target.value })} /></div>
          <div class="set-row"><label>Outputs</label><input type="number" min="0" max="64" style="width:84px" value=${newCard.outputs} onInput=${e => setNewCard({ ...newCard, outputs: +e.target.value })} /></div>
          <div class="mode-add-acts"><button class="chip" onClick=${() => setNewCard(null)}>Cancel</button>
            <button class="primary" disabled=${!newCard.id.trim()} onClick=${declareCard}>Declare & use in « ${esc(cur2.name)} »</button></div>
        </div></div>` : ''}
      ${ioOpen ? html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && setIoOpen(false)}>
        <div class="detail-card io-sheet">
          <button class="close" onClick=${() => setIoOpen(false)}>×</button>
          <h2>Inputs of « ${esc(ioCard)} »</h2>
          <p class="sub muted">What is plugged where, and how it is called. A preset lane binds to an input by its name — « Voice 1 » stays « Voice 1 » from one card to the next.${patchSt.card && patchSt.card.replace(/^hw:/, '') === ioCard ? '' : ' This card is not connected: you are preparing its patch.'}</p>
          ${!ioMap ? html`<p class="muted">loading…</p>` : html`<div class="io-rows">
            <div class="io-row io-hd io-nth"><span>Input</span><span>Instrument</span><span>#</span><span>= name</span><span>Who</span></div>
            ${/* « Guitar » + « 1 » = « Guitar 1 » (2026-09-09) : un numéro par instrument, unique sur la carte —
                  simple, générique, et une clé que toute carte satisfait */''}
            ${(ioMap.inputs || []).map(e => { const taken = n => (ioMap.inputs || []).some(x => x !== e && x.role === e.role && x.nth === n);
              return html`<div class="io-row io-nth">
              <b>IN ${e.ch}</b>
              <select onChange=${ev => ioSet({ ch: e.ch, role: ev.target.value })}>
                ${(ioMap.instruments || []).map(i => html`<option value=${i.id} selected=${i.id === e.role}>${i.name}</option>`)}
              </select>
              ${e.role && e.role !== 'none' ? html`<select onChange=${ev => ioSet({ ch: e.ch, nth: +ev.target.value })}>
                ${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => html`<option value=${n} selected=${n === e.nth} disabled=${taken(n)}>${n}${taken(n) ? ' · taken' : ''}</option>`)}
              </select>` : html`<span class="muted">—</span>`}
              <span class=${cls(!e.name && 'muted')}>${e.name ? esc(e.name) : '—'}</span>
              ${/* QUI (2026-09-09 : « Guitar 2 fait aussi Piano 1 et c'est le mainteneur ») : la personne est une propriété de
                    l'ENTRÉE, depuis le roster golem.fm — une personne peut tenir plusieurs entrées */''}
              ${((roster || {}).people || []).length ? html`<select onChange=${ev => ioSet({ ch: e.ch, person: ev.target.value || null })}>
                <option value="" selected=${!e.person}>—</option>
                ${roster.people.map(pe => html`<option value=${pe.id} selected=${pe.id === e.person}>${esc(pe.name)}</option>`)}
              </select>` : html`<span class="muted" title="pair the rack with golem.fm to get the band roster">—</span>`}
            </div>`; })}
            ${/* PORTS USB = le RACK, pas la carte (2026-09-09) : le contrôleur est sur le serveur GoleM en
                  Home comme en Show. Quatre ports, toujours listés ; le numéro est partagé avec l'audio. */''}
            ${(ioMap.usb || []).map(u => { const all = [...(ioMap.inputs || []), ...(ioMap.usb || [])];
              const taken = n => all.some(x => x !== u && x.role === u.role && x.nth === n);
              return html`<div class=${cls('io-row io-nth io-usb-row', !u.bound && 'none')}>
              <b>USB ${u.port}</b>
              <select onChange=${ev => ioSet({ ch: u.ch, role: ev.target.value })} title=${u.device ? 'plugged: ' + u.device : 'assigning binds the controller detected on this port'}>
                ${[['none', u.bound ? 'Unassigned' : '— nothing bound'], ['keys-pads', 'Keys + Pads'], ['keys', 'Keys'], ['pads', 'Pads']].map(([id, nm]) => html`<option value=${id} selected=${id === u.role}>${nm}</option>`)}
              </select>
              ${u.bound && u.role !== 'none' ? html`<select onChange=${ev => ioSet({ ch: u.ch, nth: +ev.target.value })}>
                ${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => html`<option value=${n} selected=${n === u.nth} disabled=${taken(n)}>${n}${taken(n) ? ' · taken' : ''}</option>`)}
              </select>` : html`<span class="muted">—</span>`}
              <span class=${cls(!u.name && 'muted')}>${u.name ? esc(u.name) : '—'}${u.device ? html` <small class="muted">· ${esc(u.device)}</small>` : ''}</span>
              ${u.bound && ((roster || {}).people || []).length ? html`<select onChange=${ev => ioSet({ ch: u.ch, person: ev.target.value || null })}>
                <option value="" selected=${!u.person}>—</option>
                ${roster.people.map(pe => html`<option value=${pe.id} selected=${pe.id === u.person}>${esc(pe.name)}</option>`)}
              </select>` : html`<span class="muted">—</span>`}
            </div>`; })}
          </div>`}
          <div class="sbs-ft"><span class="muted io-hint">One person can hold several inputs. Which inputs a mode plays: the chips on the Inputs row.</span><span class="grow"></span><button class="primary" onClick=${() => setIoOpen(false)}>Done</button></div>
        </div></div>` : ''}
      ${recOpen ? html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && setRecOpen(false)}>
        <div class="detail-card rec-mode-card">
          <button class="close" onClick=${() => setRecOpen(false)}>×</button>
          <h2>● Recorder settings</h2>
          <p class="sub">One setting for the whole rack — every mode that records, every preset. The Rec block in the Designer edits the same thing.</p>
          <${RecPanel} svc=${{ recSrc: { ...recGlobal, rec_mode: recGlobal.mode }, onRecSrc: setRec, recInputs: (patchSt.inputs || []).filter(e => e.role && e.role !== 'none') }} />
          <div class="sbs-ft"><span class="grow"></span><button class="primary" onClick=${() => setRecOpen(false)}>Done</button></div>
        </div></div>` : ''}
      <p class="muted mode-foot">
        What's mounted and touchable. A joined bar is one choice · separate pills switch on and off.
        <a class="mode-link" href="#/system/gear/sound">✎ Patch inputs on Soundcard →</a>
        ${cur.ui && cur.ui.locked ? html` <b>Locked mode — hold the golem logo 2 s to exit.</b>` : ''}
      </p>
    </section>` : ''}
    </div>`}
  </div>`;
}


// ── TOUS LES MODES CÔTE À CÔTE (proposition E, 2026-10-20) ───────────────────────────────────────────────────────
// Une ligne par réglage, une colonne par mode : ce qui distingue Gig de Rehearsal se voit d'un coup. Chaque case est
// LUE dans le mode (jamais écrite à la main) ; un tap ouvre ce mode dans la fiche. Les entrées se comptent sur la
// carte que le mode attend (sa configuration d'entrées, /api/inputmap?card=) : jouées / déclarées.
function ModeCompare({ modes, curId, spaceName, lists, patchCard, onOpen }) {
  const cardOf = m => (m.card || patchCard || '').replace(/^hw:/, '');
  const [maps, setMaps] = useState({});
  useEffect(() => {
    [...new Set(modes.map(cardOf).filter(Boolean))].forEach(c => fetch('/api/inputmap?card=' + encodeURIComponent(c))
      .then(r => r.json()).then(d => setMaps(x => ({ ...x, [c]: d }))).catch(() => {}));
  }, [modes.map(m => m.id + m.card).join()]);
  const on = (m, k) => (m.services || {})[k] !== false;
  const inputs = m => {
    const d = maps[cardOf(m)];
    if (!d) return '…';
    const all = [...(d.inputs || []), ...((d.usb || []).filter(u => u.bound))].filter(e => e.role && e.role !== 'none' && e.nth != null);
    const roleOn = r => r === 'keys-pads' ? (on(m, 'keys') || on(m, 'pads')) : on(m, r);
    const played = all.filter(e => roleOn(e.role) && !((m.inputs_off || []).includes(e.role + '#' + e.nth)));
    if (!all.length) return '—';
    return played.length === 1 && all.length > 1 ? played[0].name + ' only' : played.length + ' of ' + all.length;
  };
  const tools = m => { const n = TOOL_SVCS.filter(k => on(m, k)); return n.length === 1 ? '1 of 6 (' + SVC_LABELS[n[0]] + ')' : n.length + ' of 6'; };
  const foot = m => { if (m.foot_list === '@instrument') return "instrument's bank";   // docs/modes.md §2
    const x = ((lists || {}).setlists || []).find(l => l.id === m.foot_list); return x ? x.name || x.id : m.foot_list ? m.foot_list : 'keep'; };
  const label = (opts, v) => (opts.find(o => o[0] === v) || [, v])[1];
  const ROWS = [
    ['Space', m => spaceName(m.band) || '—'],
    ['Card', m => m.card ? m.card.replace(/^hw:/, '') : 'Any'],
    ['Inputs', inputs],
    ['Tools', tools],
    ['Live screen', m => label(LIVE_VIEWS, (m.ui || {}).live || 'pedalboard')],
    ['Foot list', foot],
    ['Click', m => label(CLICK_MODES, m.click_mode || 'manual')],
    ['REC', m => on(m, 'perfrec') ? 'On' : 'Off'],
    ['Arrangement', m => on(m, 'arrangement') ? 'On' : 'Off'],
  ];
  const tone = v => (v === 'Off' || v === '—' || v === 'keep' || v === 'Any') ? 'mc-no' : v === 'On' ? 'mc-on' : '';
  const live = modes.find(m => m.id === curId);
  return html`<section class="mode-cmp" data-doc="mode.table">
    <div class="mode-cmp-h"><b>Modes side by side</b><span class="muted">tap a column to open that mode · the dot is the mode the rig runs</span></div>
    <table class="mode-mx"><thead><tr><th></th>${modes.map(m => html`<th class=${cls(m.id === curId && 'mx-live')} onClick=${() => onOpen(m.id)}>
      <span class="mx-ico"><${ModeIcon} mode=${m} /></span>${m.name}${m.ui && m.ui.locked ? ' 🔒' : ''}${m.id === curId ? ' ●' : ''}</th>`)}</tr></thead>
    <tbody>${ROWS.map(([k, f]) => html`<tr><td class="mx-k">${k}</td>${modes.map(m => { const v = f(m);
      return html`<td class=${cls(tone(v), m.id === curId && 'mx-live')} onClick=${() => onOpen(m.id)}>${v}</td>`; })}</tr>`)}</tbody></table>
    <div class="mode-cmp-f"><button class="ms-view" onClick=${() => go('system/mode')} title="back to one mode, every setting">▤ One mode</button>
      <span class="muted">The inputs one by one and the six tools: open a mode.</span><span class="grow"></span>
      ${live ? html`<button class="mode-live" onClick=${() => onOpen(live.id)}>⏻ Active: ${live.name}</button>` : ''}</div>
  </section>`;
}


// ── sous-onglet Dashboard ─────────────────────────────────────────────────────
const fmtUp = s => s == null ? '—' : s >= 86400 ? Math.floor(s / 86400) + 'd ' + Math.floor(s % 86400 / 3600) + 'h'
  : s >= 3600 ? Math.floor(s / 3600) + 'h ' + Math.floor(s % 3600 / 60) + 'm' : Math.floor(s / 60) + 'm';

// ── CET ORDINATEUR (docs/installer.md §4, FIXÉ 2026-10-16) : la boîte dédiée est un RÉGLAGE, plus un choix
// d'installation. « Start golem with this computer » (golem server au démarrage, sans fenêtre) et, sous Linux seul,
// « Lock down this machine » (harden.sh : un geste séparé, qui touche toute la machine et demande le mot de passe de
// l'utilisateur — jamais gardé). Admin seulement (le bridge refuse les autres : bridge/auth.py ADMIN_PATHS).
function MachineRow({ platform, acts }) {
  const { data: au0, reload: reloadAu } = useAsync(() => fetch('/api/system/autostart').then(r => r.ok ? r.json() : null).catch(() => null), []);
  const [auNow, setAuNow] = useState(null);             // la réponse du geste fait foi (elle porte le nouvel état)
  const au = auNow || au0;
  const { data: hd, reload: reloadHd } = useAsync(() => fetch('/api/system/harden').then(r => r.ok ? r.json() : null).catch(() => null), []);
  // une lecture ratée (bridge en train de redémarrer, ou encore à l'ancienne version) se RETENTE : la ligne restait
  // sur « … » pour toujours (2026-10-16)
  useEffect(() => {
    if (au && hd) return;
    const t = setInterval(() => { if (!au) reloadAu(); if (!hd) reloadHd(); }, 5000);
    return () => clearInterval(t);
  }, [au, hd]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [lock, setLock] = useState(false);              // le panneau « Lock down this machine »
  const linux = platform === 'linux' || (hd && hd.available);
  const on = !!(au && au.on);
  const toggle = async () => {
    if (busy || !au) return;
    setBusy(true); setErr('');
    const r = await post('/api/system/autostart', { on: !on }).catch(e => e.body || { ok: false, why: String(e) });
    setBusy(false);
    if (!r.ok) setErr(r.why || r.error || 'failed');
    if (r && typeof r.on === 'boolean') setAuNow({ ...au, ...r });
  };
  // la phrase dit ce que fait l'interrupteur ICI ; sous Windows/macOS, l'ouverture de session automatique (hint du bridge)
  const explain = !au ? '…' : au.hint;
  return html`<div class="dash-pc">
      <button class=${cls('switch ro-inert', on && 'on', busy && 'busy')} disabled=${!au || busy} onClick=${toggle}
        aria-pressed=${on} aria-label="Start golem with this computer">
        <span class="switch-knob"></span><span class="switch-lbl">${busy ? '…' : on ? 'ON' : 'OFF'}</span></button>
      <div class="dash-pc-txt"><b>Start golem with this computer</b>
        <span class=${cls('muted', err && 'bad')}>${err ? '✗ ' + err : explain}</span></div>
      ${linux ? html`<button class=${cls('dash-pc-lock edit-only', hd && hd.applied && 'done')} disabled=${!hd || (hd && hd.phase === 'running')}
          onClick=${() => setLock(true)}>
        ${!hd ? '…' : hd.phase === 'running' ? '⏳ locking down…' : hd.applied ? '✓ Locked down' : '🔒 Lock down'}</button>` : ''}
      ${acts || ''}
      ${lock ? html`<${LockSheet} hd=${hd} close=${() => { setLock(false); reloadHd(); }} reload=${reloadHd} />` : ''}
    </div>`;
}

function LockSheet({ hd, close, reload }) {
  const [pw, setPw] = useState('');
  const [msg, setMsg] = useState('');
  const [st, setSt] = useState(hd);
  const running = st && st.phase === 'running';
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const d = await fetch('/api/system/harden').then(r => r.json()).catch(() => null);
      if (d) { setSt(d); if (d.phase !== 'running') { reload(); setMsg(d.phase === 'done' ? '✓ this machine is locked down' : '✗ ' + (d.error || 'failed')); } }
    }, 2000);
    return () => clearInterval(t);
  }, [running]);
  const go = async () => {
    if (!pw) return;
    setMsg('checking the password…');
    const r = await post('/api/system/harden', { password: pw }).catch(e => e.body || { ok: false, why: String(e) });
    setPw('');                                        // jamais gardé dans la page non plus
    if (!r.ok) { setMsg('✗ ' + (r.why || r.error || 'failed')); return; }
    setSt(r); setMsg(r.phase === 'done' ? '✓ this machine is locked down' : 'locking down — this takes a minute…');
  };
  const last = st && st.log && st.log.length ? st.log[st.log.length - 1] : '';
  return html`<div class="detail cfm-scrim" onClick=${e => e.target.classList.contains('cfm-scrim') && !running && close()}>
    <div class="detail-card cfm-card dash-lock" role="dialog" aria-modal="true">
      <h3>Lock down this machine</h3>
      <p class="muted">For a computer that is only golem — the rack in the rehearsal room. It changes the whole machine:</p>
      <ul class="dash-lock-list muted">
        <li><b>Firewall</b>: everything closed except golem, mDNS and SSH</li>
        <li><b>Automatic updates frozen</b>: you update by hand, never the day before a gig</li>
        <li><b>USB autosuspend off</b>: the audio interface and the pedalboard stay awake</li>
        <li><b>CPU at full speed</b> from boot; <b>golem.local</b> on the network; SSH by key only if a key is set up</li>
      </ul>
      <p class="muted">It cannot be undone from here: the golem uninstaller puts the machine back as it was.</p>
      ${st && st.applied && !running ? html`<p class="ok">✓ This machine is already locked down.</p>` : html`
        <div class="dash-lock-pw"><label for="lock-pw">Your password</label>
          <input id="lock-pw" type="password" autocomplete="current-password" value=${pw} disabled=${running}
            onInput=${e => setPw(e.target.value)} onKeyDown=${e => e.key === 'Enter' && go()} />
          <span class="muted">used once, never kept</span></div>`}
      ${msg || running ? html`<p class=${cls('muted', msg.startsWith('✗') && 'bad', msg.startsWith('✓') && 'ok')}>${msg}${running && last ? ' · ' + last : ''}</p>` : ''}
      <div class="cfm-nav"><button class="chip" disabled=${running} onClick=${close}>${st && st.applied && !running ? 'Close' : 'Cancel'}</button>
        ${st && st.applied && !running ? '' : html`<button class="primary cfm-danger" disabled=${!pw || running} onClick=${go}>Lock down</button>`}</div>
    </div>
  </div>`;
}

function DashboardPanel({ rig, admin, acts }) {
  const { data, reload } = useAsync(() => fetch('/api/system').then(r => r.json()), []);
  // santé machine (3e rangée : Golem CPU / RAM / process Reaper) — poll léger toutes les 5 s
  const [hp, setHp] = useState(null);
  // le disque et le verdict de Health : les faits du bridge (cache 5 s) — le Dashboard ne refait pas Health, il y mène
  const [hf, setHf] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => {
      fetch('/api/system/health').then(r => r.json()).then(d => alive && setHp(d)).catch(() => {});
      fetch('/api/health/facts').then(r => r.json()).then(d => alive && setHf(d)).catch(() => {});
    };
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const [perf, setPerf] = useState('');                   // '' | '…' (en cours) | message d'erreur
  const [busy, setBusy] = useState({});                   // {bridge|reaper|osc: true} pendant une action
  const s = (rig && rig.state) || {};
  const wsUp = !!(rig && rig.wsUp);                        // bridge = WebSocket vivant (temps réel)
  const running = !!s.reaper_running, osc = !!s.reaper_connected;
  const gov = data && data.cpu_governor;
  const lat = s.latency_ms ?? (data && data.audio_latency_ms), xr = s.xruns_recent || 0;
  const desktopAudio = data && (data.platform === 'win32' || data.platform === 'darwin');
  const audioReady = !!data && (!desktopAudio || Object.prototype.hasOwnProperty.call(data, 'audio_latency_ms'));
  const audioRate = (data && data.audio_srate) || 48000;
  const latencySource = (s.audio_metrics && s.audio_metrics.source) || (data && data.audio_latency_source);

  // boost off = état NORMAL (LED grise, pas d'alerte orange) — le détail suffit à inciter avant de jouer
  const govState = gov === 'performance' ? 'ok' : 'idle';

  // les états live (wsUp/running/osc) redeviennent verts d'eux-mêmes -> on relâche le busy
  useEffect(() => { if (wsUp) setBusy(b => b.bridge ? { ...b, bridge: false } : b); }, [wsUp]);
  useEffect(() => { if (running) setBusy(b => b.reaper ? { ...b, reaper: false } : b); }, [running]);
  useEffect(() => { if (osc) setBusy(b => b.osc ? { ...b, osc: false } : b); }, [osc]);

  const act = (key, path) => async () => {
    setBusy(b => ({ ...b, [key]: true }));
    await post(path).catch(e => setPerf((e.body && e.body.error) || String(e)));
    setTimeout(() => setBusy(b => ({ ...b, [key]: false })), key === 'osc' || key === 'xruns' ? 1500 : 30000);  // filet
  };
  // ── EN DEUX TEMPS, comme « ⏻ Stop golem » : redémarrer REAPER ou le bridge coupe le son — un doigt qui glisse sur la
  // tuile ne doit pas le faire. Le premier appui arme (« restart — sure? », 3 s), le second agit. Trouvé par la tournée
  // des commandes (tools/check-ui.py --press, 2026-10-20) : restart postait sans question.
  const [arm, setArm] = useState(null);
  useEffect(() => { if (!arm) return; const t = setTimeout(() => setArm(null), 3000); return () => clearTimeout(t); }, [arm]);
  const armed = (key, path, label) => ({
    label: arm === key ? label.replace(/^[^\w]*/, '') + ' — sure?' : label, busy: busy[key],
    onClick: arm === key ? () => { setArm(null); act(key, path)(); } : () => setArm(key) });
  const setGov = async on => {
    setPerf('…');
    const r = await post('/api/perf-mode', { on }).catch(e => ({ ok: false, output: String(e) }));
    setPerf(r.ok ? '' : (r.hint || r.output || 'failed'));
    reload();
  };

  // ── buffer audio Reaper : applique + redémarre le moteur ; le retour vient du live (latency_ms/xruns)
  const [applying, setApplying] = useState(null);          // taille en cours d'application | null
  const bsize = data && data.audio_bsize;
  const sizes = (data && data.audio_bsizes) || [64, 96, 128, 192, 256, 384, 512];
  // Windows : les tailles que le PILOTE ASIO accepte (bridge/asio_probe.py) ; null = on n'en sait rien, tout reste ouvert
  const okSizes = data && data.audio_bsizes_ok;
  const setBuf = async size => {
    if (!audioReady) { setPerf('Restart the golem desktop launcher to load audio controls'); return; }
    if (size === bsize || applying) return;
    setApplying(size);
    const r = await post('/api/audio-buffer', { size }).catch(e => ({ ok: false, error: (e.body && e.body.error) || String(e) }));
    if (!r.ok) { setApplying(null); setPerf(r.error || 'failed'); }
  };
  // fin de relance = la latence MESURÉE (hw_params ALSA) correspond à la théorique du nouveau buffer.
  useEffect(() => {
    if (!applying || desktopAudio) return;
    const theo = 2 * applying / audioRate * 1000;
    if (running && lat != null && Math.abs(lat - theo) < 0.7) { setApplying(null); reload(); }
    const t = setTimeout(() => { setApplying(null); reload(); }, 45000);   // filet : ne jamais rester bloqué
    return () => clearTimeout(t);
  }, [applying, running, lat, desktopAudio, audioRate]);
  useEffect(() => {
    if (!applying || !desktopAudio) return;
    const t = setInterval(async () => {
      try {
        const status = await fetch('/api/desktop/audio/status').then(r => r.json());
        if (status.phase === 'error') {
          setPerf(status.error || 'Audio configuration failed'); setApplying(null);
        } else if (status.phase === 'done') {
          const current = await fetch('/api/system').then(r => r.json());
          if (current.audio_bsize !== applying) setPerf(`REAPER opened ${current.audio_bsize || 'an unknown buffer'} instead of ${applying} samples`);
          setApplying(null); reload();
        }
      } catch (e) { setPerf(String(e)); setApplying(null); }
    }, 2000);
    return () => clearInterval(t);
  }, [applying, desktopAudio]);

  return html`
      <div class=${cls('pg-body dash2', admin && 'dash2-pc')}>
        ${/* LE DASHBOARD ALLÉGÉ (mockups/settings-nav.html, écran 2) : les MESURES de la machine en haut, ses COMMANDES
              ensuite. Les tuiles d'état que Health montre déjà (lien REAPER, pédalier, latence, dropouts) sont parties : leurs
              gestes sont les réparations de Health (resync, MIDI, buffer), le pédalier se ré-sonde dans Gear ▸ Pedalboard. */''}
        ${(() => { const disk = ((hf && hf.facts) || []).find(f => f.id === 'disk'); const v = (hf && hf.verdict) || {};
          return html`<div class="status-grid dash-meas">
          ${Tile('CPU', hp ? hp.cpu_pct + ' %' + (hp.temp_c ? ' · ' + Math.round(hp.temp_c) + ' °C' : '') : '…',
                 !hp ? 'idle' : hp.cpu_pct >= 80 ? 'bad' : hp.cpu_pct >= 55 ? 'warn' : 'ok')}
          ${Tile('RAM', hp && hp.ram ? hp.ram.used_pct + ' % of ' + (hp.ram.total_mb / 1024).toFixed(0) + ' GB' : '…',
                 !hp || !hp.ram ? 'idle' : hp.ram.used_pct >= 90 ? 'bad' : hp.ram.used_pct >= 75 ? 'warn' : 'ok')}
          ${Tile('Disk', disk ? disk.text : '…', disk ? (disk.level === 'wait' ? 'idle' : disk.level) : 'idle')}
          ${Tile('Health', v.title ? v.title.replace(/\.$/, '') : '…', !v.level || v.level === 'wait' ? 'idle' : v.level,
                 { label: 'Health →', nav: true, onClick: () => go('system/sys/health') })}
          </div>`; })()}
        <div class="status-grid">
          ${/* UNE tuile Reaper (2026-09-08) : « Reaper process » (pid/RAM/uptime, sonde santé)
                et « Audio engine » (running + relance) disaient la même chose en deux cartes. */''}
          ${Tile('Reaper',
                 running
                   ? (hp && hp.reaper && hp.reaper.running
                        ? `running · pid ${hp.reaper.pid} · ${hp.reaper.rss_mb / 1000 >= 1 ? (hp.reaper.rss_mb / 1000).toFixed(1) + ' GB' : hp.reaper.rss_mb + ' MB'}${hp.reaper.uptime_s != null ? ' · up ' + fmtUp(hp.reaper.uptime_s) : ''}`
                        : 'running')
                   : 'not running',
                 running ? 'ok' : 'bad',
                 running ? armed('reaper', '/api/system/reaper-restart', '↻ restart')
                   : { label: '▶ start', onClick: act('reaper', '/api/system/reaper-restart'), busy: busy.reaper })}
          ${Tile('golem service', wsUp ? 'bridge · connected live to this screen' : 'bridge · offline', wsUp ? 'ok' : 'bad',
                 desktopAudio ? null : armed('bridge', '/api/system/bridge-restart', '↻ restart'))}
          ${/* Windows aussi (2026-10-03) : le boost y est le plan d'alimentation « Performance » (bridge/desktop_power.py) */''}
          ${!desktopAudio || data.platform === 'win32' ? Tile('CPU boost', gov ? (gov === 'performance' ? (desktopAudio ? 'on · Performance power plan' : 'on · live ready') : 'off · turn on before playing') : '…', govState,
                 gov ? { label: gov === 'performance' ? '↓ turn off' : '⚡ boost',
                         onClick: () => setGov(gov !== 'performance'), busy: perf === '…' } : null) : ''}
        </div>
        ${perf && perf !== '…' ? html`<div class="dash-gov"><span class="perf-err" title=${perf}>✗ ${perf.includes('sudo') ? 'sudo not set up — run ./provision/setup-perf-sudo.sh once' : perf}</span></div>` : ''}

        <div class="dash-buf">
          <div class="dash-buf-head">
            <b>Audio buffer</b>
            <span class="muted">${desktopAudio ? 'device latency' : 'round-trip = 2 × buffer @ 48 kHz'} — ${desktopAudio ? (latencySource === 'reaper' ? 'REAPER reports' : 'nominal estimate') : 'measured live'}: ${lat != null ? html`<b>${lat} ms</b>` : '—'}${desktopAudio ? '' : ` · xruns ${xr}`}</span>
          </div>
          <div class="dash-buf-chips">
            ${sizes.map(sz => { const off = !!(okSizes && !okSizes.includes(sz) && sz !== bsize);
              return html`<button
              class=${cls('buf-chip ro-inert', sz === bsize && 'on', applying === sz && 'busy', off && 'buf-off')}
              disabled=${!!applying || !audioReady || off} onClick=${() => setBuf(sz)}
              title=${off ? `${(data && data.audio_driver) || 'Your audio driver'} does not offer ${sz} samples` : BUF_HINT[sz] || ''}>
              <b>${sz}</b><span>${(2 * sz / audioRate * 1000).toFixed(1)} ms</span>
            </button>`; })}
          </div>
          <div class="dash-buf-hint">
            ${!audioReady && desktopAudio ? html`<span class="dash-hint">Restart the golem desktop launcher to load Windows audio controls.</span>`
              : applying ? html`<span class="dash-hint">⏳ applying ${applying} — audio engine restarting (~10 s)…</span>`
              : html`<span class="muted">${bsize ? `${bsize} smp — ${BUF_HINT[bsize] || ''}` : '…'}${!desktopAudio && xr > 0 ? ' · ⚠ xruns > 0 : step the buffer UP' : ''}</span>`}
            ${/* LE PILOTE GARDE LA MAIN (2026-10-18) : sa latence ne suit pas le buffer demandé — le réglage vit dans son
                  panneau (Focusrite Control, ASIO Configuration de REAPER…), pas ici */''}
            ${desktopAudio && !applying && data && data.audio_driver_override ? html`<span class="dash-hint warn">
              ⚠ ${(data.audio_driver_override.driver ? esc(data.audio_driver_override.driver) + ' reports ' : 'Your audio driver reports ')
              + data.audio_driver_override.reported_ms} ms where ${bsize || 'this'} samples should give about ${data.audio_driver_override.expected_ms} ms:
              the driver keeps its own buffer. Set it in the card's control panel (Focusrite Control, or REAPER ▸ Preferences ▸
              Audio ▸ Device ▸ ASIO Configuration), turn off any “Safe Mode”, then restart REAPER from the Reaper tile.</span>` : ''}
          </div>
        </div>
        ${admin && data ? html`<${MachineRow} platform=${data.platform} acts=${acts} />` : ''}
      </div>`;
}

// ── sous-onglet Content : inventaire de la bibliothèque et du pédalier ───────
const Stat = (num, label, sub, state) => html`<div class=${cls('stat-card', state)}>
  <b class="stat-num">${num ?? '…'}</b>
  <div class="stat-lbl">${label}</div>
  ${sub ? html`<div class="stat-sub">${sub}</div>` : ''}
</div>`;

const fmtBytes = n => !n ? '—' : n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(0) + ' kB'
  : n < 1073741824 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1073741824).toFixed(2) + ' GB';
const fmtDate = t => { try { return new Date(t * 1000).toLocaleString(); } catch { return ''; } };

// LA BARRE DE SETTINGS (mockups/settings-nav.html, validée le 2026-10-20) : System ne garde que la machine — ses
// commandes et ses mesures (Dashboard), son état et ses réparations (Health). Mode est un onglet de tête ; Audio
// Engine et Separation Engine vivent dans Engines, Storage et Factory dans Content (app/page-systeme.js redirige
// les anciennes adresses #/system/sys/…).
const SUB_TABS = [['dash', 'Dashboard'], ['health', 'Health']];

export function SystemPage({ rig, sub }) {
  // #/system/sys/health/<fait> : la ligne de Health qu'une puce de /live désigne (docs/assistant.md §3)
  const focus = sub && sub.startsWith('health/') ? sub.slice(7) : null;
  if (focus) sub = 'health';
  const valid = id => SUB_TABS.some(([tid]) => tid === id);
  const [tab, setTabRaw] = useState(sub && valid(sub) ? sub : 'dash');
  // deep-link vivant du SOUS-onglet : #/system/sys/health (puce de /live).
  // Un clic de sous-onglet ÉCRIT l'URL (source de vérité, comme les onglets du hub).
  useEffect(() => { if (sub && valid(sub)) setTabRaw(sub); }, [sub]);
  const setTab = id => { setTabRaw(id); go('system/sys/' + id); };
  // LA PLAQUE (2026-09-24, docs/connect.md §4.5) : le numéro à vie du golem, attribué par golem.fm à la
  // MACHINE — c'est le nom public du rack. Dans la ligne des onglets : le dashboard n'a pas une ligne libre.
  const { data: sys } = useAsync(() => fetch('/api/system').then(r => r.json()), []);
  const serial = (sys && sys.serial) || {};
  // ⏻ ARRÊTER GOLEM (docs/installer.md §4, 2026-10-06) : en server, il n'y a pas de fenêtre, donc pas
  // de ⏻ de coquille. L'APPAREIL PRINCIPAL seulement (admin, ou cet ordinateur) : le bridge refuse les
  // autres (/api/ui/quit est au palier admin, bridge/auth.py) — on ne leur montre donc pas le bouton.
  const { data: who } = useAsync(() => fetch('/api/auth/whoami').then(r => r.json()).catch(() => null), []);
  const canStop = !!(who && (who.local || (who.device && who.device.admin)));
  const [halt, setHalt] = useState(0);                 // 0 repos · 1 armé (« sure? ») · 2 arrêté
  useEffect(() => { if (halt !== 1) return; const t = setTimeout(() => setHalt(0), 3000); return () => clearTimeout(t); }, [halt]);
  const stopGolem = async () => {
    if (halt !== 1) { setHalt(1); return; }
    setHalt(2);
    await post('/api/ui/quit', { stop: true }).catch(() => null);   // le bridge meurt en répondant
  };
  // ── PASSER D'UN USAGE À L'AUTRE, dans les deux sens (docs/installer.md §4) ──────────────────────────────
  // Dans la fenêtre golem (la coquille device.html) : « Continue on a tablet », le MÊME panneau que son 📱, qui
  // ferme la fenêtre à la fin. Ailleurs (une tablette, un téléphone, un onglet) : « Show on this computer » rouvre
  // la fenêtre sur l'ordinateur — grisé, AVEC SA RAISON en clair, quand il n'a pas d'écran (ui.can_show).
  const tabletSheet = shellTabletSheet();
  const ui = (rig && rig.state && rig.state.ui) || {};
  const cs = ui.can_show || { ok: false, why: 'asking golem…' };
  const [showMsg, setShowMsg] = useState('');
  useEffect(() => { if (!showMsg || showMsg === 'opening…') return; const t = setTimeout(() => setShowMsg(''), 6000); return () => clearTimeout(t); }, [showMsg]);
  const showHere = async () => {
    if (!cs.ok) { setShowMsg('✗ ' + cs.why); return; }
    setShowMsg('opening…');
    const r = await post('/api/ui/show', {}).catch(e => e.body || { ok: false, why: String(e) });
    setShowMsg(r.ok ? '✓ golem opened its window on the computer — the sound did not stop' : '✗ ' + (r.why || r.error || 'failed'));
  };
  return html`
    <div class="system pg-fit">
      <div class="sys-tabs sub-tabs">
        ${SUB_TABS.map(([id, label]) => { const dot = id === 'health' ? (healthDot((rig || {}).state) || {}).badge : null;
          return html`<button class=${cls('sys-tab', tab === id && 'on')} title=${dot ? 'something needs your attention in Health' : ''}
          onClick=${() => setTab(id)}>${label}${dot ? html`<i class=${'svc-dot ' + dot}></i>` : ''}</button>`; })}
        ${/* PROVISOIRE (2026-09-29) : un numéro rendu par un serveur qui n'est pas golem.fm (une base de
              dev) n'est pas gravé — il se montre grisé, avec son serveur, pour ne jamais passer pour le nom
              public du rack. */''}
        ${serial.name ? html`<span class=${cls('sys-plate', serial.conflict && 'bad', serial.provisional && 'prov')}
            title=${serial.provisional ? `provisional number from ${serial.server || 'a test server'} — only golem.fm issues this rack’s lifetime number`
                  : serial.conflict ? `golem.fm now answers ${serial.conflict} for this machine — the number kept here is ${serial.name}; tell golem.fm`
                                    : 'this rack’s lifetime number on golem.fm' + (serial.issued_at ? ' · issued ' + serial.issued_at.slice(0, 10) : '')}>
          ${serial.conflict ? '⚠ ' : ''}${serial.name}${serial.provisional ? html`<small> · test</small>` : ''}</span>` : ''}
      </div>
      ${showMsg && halt !== 2 ? html`<div class=${cls('sys-note', showMsg.startsWith('✗') && 'bad')}>${showMsg}</div>` : ''}
      ${halt === 2 ? html`<div class="sys-stopped">golem stopped — Reaper and the bridge are off. Start it again on the computer (the golem icon, or <code>golem server</code>).</div>` : ''}
      ${tab === 'dash' ? html`<${DashboardPanel} rig=${rig} admin=${canStop} acts=${canStop ? html`
          ${tabletSheet ? html`<button class="sys-pc-btn" onClick=${() => tabletSheet()}
              title="the address and its QR for a tablet, then this window closes — golem keeps running">Continue on a tablet</button>`
            : html`<button class=${cls('sys-pc-btn edit-only', !cs.ok && 'off')} aria-disabled=${!cs.ok}
              title=${cs.ok ? 'open the golem window on the computer — the sound does not stop' : cs.why} onClick=${showHere}>
              Show on this computer</button>`}
          <button class=${cls('sys-halt', halt === 1 && 'arm')} disabled=${halt === 2}
            title="stop golem: Reaper, the bridge and its windows — the sound stops" onClick=${stopGolem}>
            ${halt === 1 ? 'Stop golem — sure?' : halt === 2 ? 'stopping…' : '⏻ Stop golem'}</button>` : null} />`
      : html`<${HealthPage} focus=${focus} />`}
    </div>`;
}

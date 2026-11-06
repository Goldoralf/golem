// SPDX-License-Identifier: GPL-3.0-or-later
// Les LANES du Designer (audit 2026-09-13, M7 — extrait de page-designer.js, 1 800 lignes en un
// composant) : aides PURES sur (lane, patch de la carte) + la feuille « Lanes & inputs ». Rien ici ne
// ferme sur l'état du Designer : tout arrive en argument, tout se teste au navigateur sans le monter.
import { html, cls, esc } from './lib.js';
import { sortLanes, laneIdFor, newLaneId, ROLE_ICON, MIDI_ROLES } from './designer-model.js';
import { Icon } from './icons.js';

// LE PORT QU'UNE LANE MIDI JOUE (2026-11-02) : « usbN » le dit ; un « usb » nu (lanes Keys des presets d'usine) n'est
// PAS l'USB 1 — c'est le port où le moteur trouve le meilleur appareil de son rôle (bridge/vital.lane_port, servi dans
// l'input map : `lane_ports`). Avant, l'écran affichait « USB 1 » et sa couleur suivait l'USB 1 quand le MPK jouait en USB 2.
export const usbPortOf = (L, pt) => {
  const m = String((L && L.in_sel) || '').match(/^usb(\d)$/);
  if (m) return Number(m[1]);
  const lp = (pt && pt.lane_ports) || null;
  return lp ? (lp[L && L.role === 'drums' ? 'drums' : 'keys'] || 0) : 1;
};

export const laneDisabled = L => !!L && (L.in_sel === 'NONE' || L.out_sel === 'NONE');
// l'entrée demandée n'existe pas sur la carte branchée (preset venu d'une 8×8 sur une Volt) : la lane
// n'est PAS montée par le bridge, et l'onglet le dit — plutôt qu'une lane muette sans explication
// liée PAR NOM (in_role + in_nth) : l'entrée existe si la carte a CE (rôle, numéro) — jamais le numéro brut
// (« Guitar 2 » sur la Volt tomberait sur IN 2 = le micro) ; sinon, par numéro comme avant
export const onPatch = (pt, L) => L.in_role && L.in_nth != null && (pt.inputs || []).some(e => e.nth != null)
  ? (pt.inputs || []).some(e => e.role === L.in_role && Number(e.nth) === Number(L.in_nth))
  : (pt.inputs || []).some(e => String(e.ch) === String(L.in_sel) || String(e.ch).split('-').includes(String(L.in_sel).split('-')[0]));
export const laneOffCard = (L, patch) => !!L && !L.midi && L.in_sel !== 'NONE' && ((patch || {}).inputs || []).length > 0 && !onPatch(patch, L);
// …mais si l'entrée EXISTE sur la carte du mode (XR18 déclaré, pas encore branché), la lane n'est pas
// fausse, elle ATTEND sa carte — on le dit autrement (2026-09-09 : « je peux la configurer »)
export const laneWaitsCard = (L, patch, modePatch) => laneOffCard(L, patch) && !!modePatch && onPatch(modePatch, L);

// une lane telle qu'elle est stockée, depuis sa spec — partagée par la feuille (coche) et le preset neuf
export const laneObj = ({ id: wantId, name, role, in_sel, in_role, in_nth, in_name }) => {
  const id = wantId || newLaneId(); const midi = MIDI_ROLES.includes(role) || /^usb/.test(String(in_sel || ''));   // drums sur un port USB = lane MIDI
  return { id, key: id, role, name: name || role, midi,
    in_sel: midi ? (in_sel || 'usb1') : (in_sel || 'NONE'), out_sel: '1-2', chain: { pre: [], split: null, post: [] },
    ...(in_role && in_nth != null ? { in_role, in_nth, in_name } : {}) };
};
// la spec d'une lane depuis une LIGNE de la feuille (entrée de la carte, ou port USB lié)
export const laneSpecOf = (r, ids) => ({ id: laneIdFor(r.e.role, r.e.nth, ids), name: r.name, role: r.e.role,
  in_sel: r.kind === 'midi' ? r.e.ch : String(r.e.ch), in_role: r.e.nth != null ? r.e.role : undefined, in_nth: r.e.nth,
  in_name: r.kind === 'midi' ? r.name : r.e.name });

// ── la feuille « Lanes & inputs » = les ENTRÉES de la carte éditée, cochées ou non (2026-09-09 :
// « le champ Lane et Instrument se résolvent par l'entrée ») : une lane par entrée cochée, nom / rôle /
// numéro pris au patch, ordre du contrat. Les lanes d'une autre carte (orphelines) restent listées,
// cochées, pour pouvoir être décochées. Les entrées sans instrument ne sont pas cochables.
export const sheetRowsFor = (lanes, pt) => {
  const ins = (pt || {}).inputs || [];
  const laneFor = e => lanes.find(L => !L.midi && (String(L.in_sel) === String(e.ch)
    || (e.nth != null && e.role && L.in_role === e.role && Number(L.in_nth) === Number(e.nth))));
  const rows = ins.filter(e => e.role && e.role !== 'none').map(e => { const L = laneFor(e) || null; return { kind: 'in', e, lane: L,
    role: e.role, in_sel: String(e.ch), in_nth: e.nth, name: e.name || ('IN ' + e.ch), who: e.person_name,
    // une chaîne d'un autre instrument sur cette entrée (lane legacy liée par numéro : « voice » sur IN 2 = Guitar 2 du XR18)
    mismatch: L && !L.in_role && L.role !== e.role && !(MIDI_ROLES.includes(L.role) && MIDI_ROLES.includes(e.role)) ? L.role : null }; });
  // les entrées SANS instrument : une seule ligne, pas onze (XR18 : IN 8…18)
  const free = ins.filter(e => !e.role || e.role === 'none').map(e => String(e.ch));
  if (free.length) rows.push({ kind: 'free', none: true, role: 'zz', in_sel: free[0], in_nth: 99, name: free.length === 1 ? 'IN ' + free[0] : 'IN ' + free[0] + ' – ' + free[free.length - 1], count: free.length });
  // PORTS USB du rack (2026-09-09) : un port lié = une ligne cochable (« Keys + Pads 1 · USB 1 ») ;
  // une lane MIDI occupe un port (« usb » legacy = USB 1). Les ports vides tiennent sur une ligne.
  const usbLaneFor = u => lanes.find(L => L.midi && (String(L.in_sel) === u.ch || ((L.in_sel === 'usb' || !L.in_sel) && u.port === usbPortOf(L, pt))));
  const freeUsb = [];
  if (pt && pt.usb) pt.usb.forEach(u => { if (u.bound && u.role && u.role !== 'none') rows.push({ kind: 'midi', e: u, lane: usbLaneFor(u) || null,
      role: u.role, in_sel: u.ch, in_nth: u.nth, name: u.name || u.label || 'Keys', who: u.person_name }); else freeUsb.push(u.port); });
  else { const midi = pt && pt.midi && pt.midi.role && pt.midi.role !== 'none' ? pt.midi : null, midiLane = lanes.find(L => L.midi);   // état d'avant
    if (midi || midiLane) rows.push({ kind: 'midi', e: midi ? { ...midi, ch: 'usb1', port: 1 } : null, lane: midiLane || null, role: midi ? midi.role : midiLane.role,
      in_sel: 'usb1', in_nth: 0, name: midi ? (midi.label || 'Keys') : midiLane.name }); }
  if (freeUsb.length) rows.push({ kind: 'free', usb: true, none: true, role: 'zz', in_sel: 'usb' + freeUsb[0], in_nth: 100 + freeUsb[0],
    name: freeUsb.length === 1 ? 'USB ' + freeUsb[0] : 'USB ' + freeUsb[0] + ' – ' + freeUsb[freeUsb.length - 1], count: freeUsb.length });
  const seen = new Set(rows.map(r => r.lane && r.lane.id).filter(Boolean));
  lanes.filter(L => !seen.has(L.id)).forEach(L => rows.push({ kind: 'orphan', lane: L, role: L.role, in_sel: L.in_sel, in_nth: L.in_nth, name: L.name }));
  return sortLanes(rows);
};

// ── AJOUTER UN INSTRUMENT (2026-09-28) ──────────────────────────────────────────────────
// Avant : la batterie avait son bouton (« Add a drum kit ») et les autres instruments passaient par
// « Lanes & inputs », qui ne cochait QUE des entrées déjà baptisées dans Soundcard — sur la Volt
// (IN 1 guitare, IN 2 voix) aucune basse n'était possible, et l'écran ne disait pas pourquoi.
// Maintenant on choisit l'INSTRUMENT, puis son entrée. Le §3.2 de docs/input-map.md tient : le
// rôle s'écrit toujours dans le patch de la CARTE (POST /api/inputmap), jamais dans le preset —
// ce geste ne fait que l'y écrire depuis ici.
export const ADD_ROLES = [
  { id: 'guitar', label: 'Guitar', icon: 'guitar' }, { id: 'bass', label: 'Bass', icon: 'bass' },
  { id: 'voice', label: 'Voice', icon: 'voice' }, { id: 'keys', label: 'Keys', icon: 'keys' },
  { id: 'drums', label: 'Drums', icon: 'drumkit' },
];
const KEYS_USB = ['keys', 'keys-pads', 'pads'];
// les entrées de la carte éditée, chacune avec ce qu'un tap y ferait pour `role` :
//   add   = l'entrée est déjà de cet instrument, sans lane ici — tap = la lane
//   has   = une lane joue déjà cette entrée — tap = y aller
//   free  = entrée sans instrument — tap = la baptiser `role` sur la carte, puis la lane
//   other = entrée d'un autre instrument — deux taps : la rebaptiser (touche tous les presets)
export const addChoicesFor = (role, lanes, pt) => {
  const ins = (pt || {}).inputs || [];
  const laneOn = e => lanes.find(L => !L.midi && (String(L.in_sel) === String(e.ch)
    || (e.nth != null && e.role && L.in_role === e.role && Number(L.in_nth) === Number(e.nth))));
  const rows = ins.map(e => { const cur = e.role && e.role !== 'none' ? e.role : null, L = laneOn(e) || null;
    const state = cur === role ? (L ? 'has' : 'add') : (!cur && !L) ? 'free' : 'other';
    return { kind: 'in', e, ch: String(e.ch), lane: L, state, cur, name: e.name || ('IN ' + e.ch), who: e.person_name }; });
  // un clavier se branche aussi en USB : les ports LIÉS en keys / pads (le binding d'un appareil,
  // lui, reste dans Soundcard — on ne lie pas un port vide depuis ici)
  if (role === 'keys') ((pt || {}).usb || []).forEach(u => { if (!u.bound || !KEYS_USB.includes(u.role)) return;
    const L = lanes.find(x => x.midi && (String(x.in_sel) === String(u.ch) || ((x.in_sel === 'usb' || !x.in_sel) && u.port === usbPortOf(x, pt))));
    rows.push({ kind: 'midi', e: u, ch: String(u.ch), lane: L || null, state: L ? 'has' : 'add', cur: u.role,
      name: u.name || u.label || 'Keys', who: u.person_name, usb: u.port }); });
  const rank = { add: 0, free: 1, has: 2, other: 3 };
  return rows.sort((a, b) => rank[a.state] - rank[b.state]);
};

// La feuille elle-même : tout arrive en props, elle ne décide de rien.
export function IoSheet({ rows, lanes, inTab, patch, modePatch, modeCard, modeName, cardName, inputsCount, rmLaneArm,
                          laneBlocks, onToggle, onRemove, onClose,
                          addRole, addRows, addArm, onAddRole, onAddRow }) {
  const role = ADD_ROLES.find(x => x.id === addRole);
  const card = modePatch ? modeCard : cardName;
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card io-sheet">
      <button class="close" onClick=${onClose}>×</button>
      ${role ? html`
      <h2><button class="mini io-back" onClick=${() => onAddRole(null)} title="back">‹</button> Add ${esc(role.label.toLowerCase())} — on which input?</h2>
      <p class="sub muted">An input's instrument belongs to the card « ${esc(card)} »: naming it here names it for every preset.
        ${modePatch ? html`<br/><b>« ${esc(modeCard)} »</b> is the card ${esc(modeName || 'this mode')} prefers, <b>not connected</b>: the lane mounts when it is plugged in.` : ''}</p>
      <div class="io-rows">
        ${addRows.length ? addRows.map(r => { const L = r.lane, armed = addArm === r.ch;
          return html`<button class=${cls('io-row io-add', 'st-' + r.state, armed && 'armed')} onClick=${() => onAddRow(r)}>
            <span class="io-name"><i>${ROLE_ICON[r.cur] || '·'}</i> ${esc(r.cur ? r.name : 'No instrument')}</span>
            <b>${r.kind === 'midi' ? 'USB ' + r.usb : 'IN ' + r.ch.replace('-', '·')}</b>
            <span class="muted io-who">${r.who ? esc(r.who) : '—'}</span>
            <span class="io-state">${
              r.state === 'add' ? html`<span class="chip io-go">＋ Add lane</span>`
              : r.state === 'has' ? html`<small class="muted">already a lane${L && L.name ? ' · ' + esc(L.name) : ''} — open it</small>`
              : r.state === 'free' ? html`<span class="chip io-go">Make it ${esc(role.label)} ＋ lane</span>`
              : armed ? html`<small class="warn">tap again: IN ${esc(r.ch)} becomes ${esc(role.label)} in every preset${L ? ' — the « ' + esc(L.name || r.name) + ' » lane here goes silent' : ''}</small>`
              : html`<small class="muted">${esc(r.name)} — tap to make it ${esc(role.label)}</small>`}</span>
          </button>`; })
        : html`<p class="muted">No input on « ${esc(card)} ».</p>`}
        ${addRole === 'keys' && !addRows.some(r => r.kind === 'midi') ? html`<p class="muted io-hint">No keyboard on USB yet — plug it in, then bind it in Settings ▸ Gear ▸ Soundcard.</p>` : ''}
      </div>` : html`
      <h2>Add an instrument</h2>
      <p class="sub muted">Pick the instrument, then its input. A preset plays one lane per input.</p>
      <div class="io-roles">
        ${ADD_ROLES.map(x => html`<button class="io-role" onClick=${() => onAddRole(x.id)}>
          <span class="io-role-ic"><${Icon} id=${x.icon} /></span>${x.label}</button>`)}
      </div>
      ${modePatch ? html`<p class="sub muted"><b>Inputs of « ${esc(modeCard)} »</b> — the card ${esc(modeName || 'this mode')} prefers, <b>not connected</b>: lanes bound here mount when it is plugged in.</p>` : ''}
      <span class="io-sec">In this preset</span>
      <div class="io-rows">
        <div class="io-row io-chk io-hd"><span></span><span>Lane</span><span>Input</span><span>Who</span><span></span></div>
        ${rows.filter(r => r.lane).map(r => { const L = r.lane, nb = L ? laneBlocks(L).length : 0, armed = L && rmLaneArm === L.id;
          const waits = L && laneWaitsCard(L, patch, modePatch), off = L && laneOffCard(L, patch) && !waits, last = L && lanes.length === 1;
          return html`<label class=${cls('io-row io-chk', L && 'on', L && inTab === L.id && 'cur', r.none && 'none', r.kind === 'orphan' && 'orphan')}>
          <input type="checkbox" checked=${!!L} disabled=${(r.none && !L) || last}
            title=${last ? 'a preset keeps at least one lane' : r.none && !L ? 'assign an instrument to this input first' : L ? 'uncheck to drop this lane' : 'check to add a lane on this input'}
            onChange=${() => onToggle(r)} />
          <span class="io-name"><i>${ROLE_ICON[r.role] || '·'}</i> ${esc(r.name)}${r.mismatch ? html` <small class="muted">· ${esc(L.name)}</small>` : ''}</span>
          <b>${r.kind === 'midi' ? 'USB ' + (r.e ? r.e.port : 1) : r.kind === 'free' ? (r.count > 1 ? r.count + (r.usb ? ' USB' : ' IN') : (r.usb ? r.name : 'IN ' + r.in_sel)) : 'IN ' + r.in_sel}</b>
          <span class="muted io-who">${r.who ? esc(r.who) : '—'}</span>
          <span class="io-state">
            ${armed ? html`<button class="mini danger" onClick=${e => { e.preventDefault(); onRemove(L.id); }}>remove lane & ${nb} block${nb === 1 ? '' : 's'}?</button>`
            : r.none && r.usb ? html`<small class="muted">nothing bound — plug a controller, assign it in Inputs of « ${esc(cardName)} »</small>`
            : r.none ? html`<small class="muted">no instrument — assign ${r.count > 1 ? 'them' : 'it'} in Inputs of « ${esc(cardName)} »</small>`
            : r.mismatch ? html`<small class="lane-off warn">⚠ ${esc(r.mismatch)} chain on a ${esc(r.role)} input — uncheck to drop it</small>`
            : waits ? html`<small class="lane-off waits">⏳ waits for « ${esc(modeCard)} »</small>`
            : off ? html`<small class="lane-off warn">⚠ not on this card${r.kind === 'orphan' ? ' — uncheck to drop' : ''}</small>`
            : L && nb ? html`<small class="muted">${nb} block${nb === 1 ? '' : 's'}</small>` : ''}
          </span>
        </label>`; })}
      </div>`}
      <div class="sbs-ft">
        <span class="muted io-hint">${lanes.length} lane${lanes.length === 1 ? '' : 's'} · ${inputsCount} input${inputsCount === 1 ? '' : 's'} on ${modePatch ? '« ' + modeCard + ' »' : 'this card'} — uncheck a lane to remove it</span>
        <span class="grow"></span>
        <button class="primary" onClick=${onClose}>Done</button>
      </div>
    </div></div>`;
}


// La barre d'onglets des lanes : un onglet PAR LANE, généré depuis la liste — titre de la lane,
// entrée en petit (≥ 4 lanes : deux lignes nettes, classe `dense` posée par le parent). En mode
// PATCH, un seul onglet : la lane du patch, titrée par le patch.
export function LaneTabs({ lanes, patch, patchMode, pmTab, pmTitle, inTab, laneTitle, onPick, folded, unmounted }) {
  // LE VERDICT DU MOTEUR SE LIT ICI (audit 2026-10-10) : une lane que scene_bake n'a pas montée (deux lanes sur
  // la même entrée, une entrée absente) portait un onglet vert — « un garde-fou qu'on ne consulte pas n'est pas
  // un garde-fou ». Orange, et la raison en titre.
  const unm = L => (unmounted || []).find(u => u && u.id === L.id) || null;
  const nIn = ((patch || {}).inputs || []).length;
  // ── UN GROUPE DE BATTERIE REPLIÉ = UN SEUL ONGLET (docs/drums-kit.md §6.6) ────────────────
  // Sept entrées font sept lanes, mais un batteur est UN musicien : replié, le groupe occupe un
  // onglet « Drums », et l'onglet reste actif quel que soit l'élément ouvert en dessous. Déplié,
  // chaque élément reprend son onglet — c'est la barre qui change, pas le modèle.
  const fold = new Set(folded || []);
  const seen = new Set();
  // EN MODE PATCH DE KIT, les onglets se comportent comme dans un preset : un patch de kit EST
  // multi-lanes (docs/drums-kit.md §6.7). Se replier à `pmTab` masquait six éléments sur sept —
  // le trou signalé le 2026-09-20 (« je n'ai pas les nouvelles interfaces »).
  const kitMode = patchMode && patchMode.drumset;
  const list = (lanes || []).filter(L => {
    if (patchMode && !kitMode) return L.id === pmTab;
    if (kitMode && L.drumset !== patchMode.drumset) return false;
    const ds = L.drumset;
    if (!ds || !fold.has(ds)) return true;
    if (seen.has(ds)) return false;
    seen.add(ds); return true;
  });
  return list.map(L => { const um = patchMode ? null : unm(L); const off = !patchMode && (laneOffCard(L, patch) || !!um);
    const ds = L.drumset && fold.has(L.drumset) && (!patchMode || kitMode) ? L.drumset : null;
    if (ds) {
      const grp = (lanes || []).filter(x => x.drumset === ds);
      const cur = grp.some(x => x.id === inTab);
      const nOff = grp.filter(x => laneOffCard(x, patch)).length;
      return html`<button class=${cls('sys-tab', 'ds-tab', cur && 'on', nOff === grp.length && 'offcard')}
        title=${nOff ? nOff + ' of ' + grp.length + ' inputs are not on this card' : grp.length + ' inputs — one lane per element'}
        onClick=${() => onPick((grp.find(x => x.id === inTab) || grp[0]).id)}><${Icon} id="drumkit" /> Drums<small
          class=${cls(nOff === 0 && 'in-on', nOff === grp.length && 'in-off')}>${grp.length} IN</small></button>`;
    }
    // L'ENTRÉE DIT SA DISPONIBILITÉ PAR SA COULEUR (2026-09-17) : vert = présente sur la carte
    // branchée, orange = absente — sans ⚠ (la couleur suffit, l'icône encombrait la barre). Une lane
    // MIDI suit son port USB (lié = vert), « IN — » reste neutre.
    const usbPort = L.midi ? usbPortOf(L, patch) : 0;
    const usbOn = L.midi && !!(((patch || {}).usb || []).find(u => Number(u.port) === usbPort) || {}).bound;
    const avail = patchMode || L.in_sel === 'NONE' ? null : (L.midi ? usbOn : !off);
    return html`<button class=${cls('sys-tab', inTab === L.id && 'on', !patchMode && laneDisabled(L) && 'dis', off && 'offcard')} data-doc=${'designer.lane:' + L.id}
      title=${um ? 'not mounted — ' + um.reason
             : off && L.in_role ? 'waiting for a ' + L.in_role + ' input — this card has none (' + nIn + ' inputs); assign one in Soundcard ▸ Inputs'
             : off ? 'IN ' + L.in_sel + ' is not on this card (' + nIn + ' inputs) — this lane is not mounted; pick another input'
             : L.midi && !usbOn && !patchMode ? 'USB ' + usbPort + ' has no device bound — this lane is not mounted' : ''}
      onClick=${() => onPick(L.id)}>${patchMode && !kitMode ? esc(pmTitle) : esc(laneTitle(L))}<small class=${cls(avail === true && 'in-on', avail === false && 'in-off')}>${patchMode && !kitMode ? (patchMode.role || patchMode.realm) + ' patch'
        /* UNE LANE LIÉE PAR RÔLE SANS ENTRÉE SUR CETTE CARTE N'A PAS DE NUMÉRO (2026-10-13 : « comment je me
           retrouve avec BASS en IN 1 ?! ») : le numéro qu'elle garde en mémoire est celui d'une AUTRE carte — ici
           c'est le micro. Le moteur ne la monte pas ; l'onglet ne doit pas davantage l'y afficher. */
        : (L.midi ? ('USB ' + usbPort) : (L.in_sel === 'NONE' || (off && L.in_role)) ? 'IN —' : 'IN ' + L.in_sel)}</small></button>`; });
}

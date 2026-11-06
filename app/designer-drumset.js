// SPDX-License-Identifier: GPL-3.0-or-later
// Le GROUPE DE BATTERIE du Designer (docs/drums-kit.md §6) : N entrées audio d'un module, posées
// d'un geste, repliées à l'écran sous UN instrument. Rien ici ne ferme sur l'état du Designer —
// tout arrive en props, tout se teste au navigateur sans monter la page.
//
// ⚠ LE GROUPE N'EST PAS UN CONTENEUR. Sept lanes se matérialisent comme sept lanes, I_RECINPUT
// compris ; le groupe vit dans trois champs de lane (`drumset`, `drumset_module`, `element`) et
// dans cet écran. Le jour où quelqu'un voudra en faire un objet du modèle, relire le §6.2 d'abord.
import { html, cls, esc, go } from './lib.js';
import { laneIdFor } from './designer-model.js';
import { Icon } from './icons.js';

export const KIT_MIX = 'kit-mix';

// Un élément → son libellé d'écran. L'UI est en ANGLAIS (CLAUDE.md) ; la clé, elle, est le
// vocabulaire fermé de bridge/drumkits.py ELEMENTS, partagé avec la traduction MIDI.
export const EL_LABEL = {
  kick: 'Kick', snare: 'Snare', 'snare-rim': 'Snare rim', 'snare-xstick': 'Cross-stick',
  tom1: 'Tom 1', tom2: 'Tom 2', tom3: 'Tom 3', tom4: 'Tom 4',
  'tom1-rim': 'Tom 1 rim', 'tom2-rim': 'Tom 2 rim', 'tom3-rim': 'Tom 3 rim', 'tom4-rim': 'Tom 4 rim',
  'hh-open': 'Hi-hat open', 'hh-half': 'Hi-hat half', 'hh-closed': 'Hi-hat', 'hh-pedal': 'Hi-hat pedal',
  'hh-splash': 'Hi-hat splash', 'hh-open-edge': 'Hi-hat open edge', 'hh-closed-edge': 'Hi-hat edge',
  crash1: 'Crash 1', 'crash1-edge': 'Crash 1 edge', crash2: 'Crash 2', 'crash2-edge': 'Crash 2 edge',
  ride: 'Ride', 'ride-edge': 'Ride edge', 'ride-bell': 'Ride bell',
  splash: 'Splash', china: 'China', ext: 'Extra', 'ext-rim': 'Extra rim',
  aux1: 'Aux 1', aux2: 'Aux 2', aux3: 'Aux 3',
  'aux1-rim': 'Aux 1 rim', 'aux2-rim': 'Aux 2 rim', 'aux3-rim': 'Aux 3 rim',
  [KIT_MIX]: 'Kit mix',
};
export const elLabel = e => EL_LABEL[e] || (e ? String(e) : '—');

// ── LES FORMES DE CÂBLAGE ───────────────────────────────────────────────────────────────────
// Ce qu'on a BRANCHÉ ce soir, pas ce que le module PEUT faire : un TD-50X câblé en stéréo est une
// lane, pas huit. Une forme que le module n'a pas est ÉTEINTE, jamais cachée — une commande qui
// disparaît fait douter de ce qu'on a vu la seconde d'avant (même règle que `.tb-seg button.dead`).
export const formsFor = (outs, freeIn) => {
  const o = outs || {}, direct = Math.min(Number(o.direct) || 0, freeIn);
  return [
    { id: 'midi', label: 'MIDI only', n: 0, ok: true,
      hint: 'One cable, the rack makes the sound. No audio input used.' },
    { id: 'stereo', label: 'Stereo pair', n: 2, ok: o.master === 'stereo' && freeIn >= 2,
      hint: o.master !== 'stereo' ? 'This module has no stereo master out.'
        : freeIn < 2 ? 'Needs 2 free inputs on the card.'
        : "The module's own sound, 2 inputs. One lane, one chain." },
    { id: 'mono', label: 'Mono', n: 1, ok: o.master === 'mono' && freeIn >= 1,
      hint: o.master === 'mono' ? 'One input, one chain.' : 'This module has a stereo master out.' },
    { id: 'direct', label: 'Direct outs', n: direct, ok: direct >= 2,
      hint: !(Number(o.direct) > 0) ? (o.declared ? 'This module has no direct outs.' : 'Unknown for this module — nobody filled it in.')
        : direct < Number(o.direct) ? `Only ${freeIn} free input(s) on the card, the module has ${o.direct}.`
        : 'One input per element. One lane per element, one kit.' },
  ];
};

// ── LE PLAN : ce que « Add N lanes » va poser ───────────────────────────────────────────────
// PUR, et c'est voulu : le plan se lit à l'écran AVANT d'exister, et se teste sans Designer.
// `freeIn` = les entrées libres de la carte, dans l'ordre ; `pairs` = celles qui peuvent se lier.
// La dernière entrée d'un câblage `direct` ne devient PAS `kit-mix` : le mix sort du MASTER, qui
// est une AUTRE prise. Si on veut les deux, on ajoute la paire ensuite — l'écran le dit.
export const drumsetPlan = ({ outs, form, freeIn, defaults, module: mod, taken = [] }) => {
  const o = outs || {}, ids = [...taken], rows = [];
  const take = (element, chans) => {
    const in_sel = chans.join('-');
    const id = laneIdFor('drums', null, ids) + (rows.length ? '-' + (rows.length + 1) : '');
    ids.push(id);
    rows.push({ id, element, in_sel, stereo: chans.length > 1, label: elLabel(element) });
  };
  if (form === 'midi') return [];
  if (form === 'stereo' || form === 'mono') {
    const n = form === 'stereo' ? 2 : 1;
    if (freeIn.length < n) return [];
    take(KIT_MIX, freeIn.slice(0, n));
    return rows.map(r => ({ ...r, drumset: mod, drumset_module: mod }));
  }
  const n = Math.min(Number(o.direct) || 0, freeIn.length);
  const els = (defaults && defaults.length ? defaults : []).slice(0, n);
  for (let i = 0; i < n; i++) take(els[i] || 'aux' + Math.min(3, i + 1), [freeIn[i]]);
  return rows.map(r => ({ ...r, drumset: mod, drumset_module: mod }));
};

// ── LE TIROIR ────────────────────────────────────────────────────────────────────────────────
export function DrumsetSheet({ pick, form, plan, freeIn, elements, cardName, portable,
                               onForm, onElement, onAdd, onClose }) {
  // `pick` = le module CALIBRÉ du rack (Calibration ▸ Drums), jamais un choix fait ici — docs/calibration.md,
  // addendum 2026-09-23 (« on a naïvement déporté le choix du kit dans les patches »). Sans module
  // calibré, `pick.generic` : les formes génériques restent offertes, et la ligne dit où aller.
  const outs = (pick && pick.audio_outs) || {};
  const forms = formsFor(outs, freeIn.length);
  const cur = forms.find(f => f.id === form) || forms[0];
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card ds-sheet">
      <button class="close" onClick=${onClose}>×</button>
      <h2><${Icon} id="drumkit" /> Add a drum kit</h2>
      <p class="sub muted">The module is the rack's — calibrated in Settings. Here you only say what you cabled tonight.</p>

      <span class="ds-lbl">Module</span>
      <div class="ds-modline">
        ${pick && !pick.generic ? html`<b>${esc(pick.name)}</b>
            <span class=${cls('pb-prov', pick.confidence || 'unknown')}>${pick.confidence === 'verified' ? '✓ verified' : pick.confidence === 'reported' ? '~ reported' : '? unconfirmed'}</span>
            ${pick.confidence !== 'verified' ? html`<button class="chip" onClick=${() => go('system/gear/drums')}>Measure it</button>` : ''}`
          : html`<span class="muted">No drum module calibrated on this rack.</span>
            <button class="chip" onClick=${() => go('system/gear/drums')}>Settings ▸ Gear ▸ Drums</button>`}
      </div>

      ${/* TANT QU'AUCUN MODULE N'EST CHOISI, les formes sont ÉTEINTES et on le DIT. Sans ça
            « Stereo pair » et « Direct outs » s'affichaient grisés d'entrée de jeu, ce qui se lit
            « ce rack ne sait pas faire » alors que ça veut dire « je ne sais pas encore de quoi
            tu parles » (mesuré au rendu le 2026-09-20). */''}
      <span class="ds-lbl">What you cabled${pick ? '' : html` <small class="muted"> — pick a module first</small>`}</span>
      <div class=${cls('ds-forms', !pick && 'ds-wait')}>
        ${forms.map(f => html`<button class=${cls('ds-form', pick && form === f.id && 'on', (!pick || !f.ok) && 'dead')}
          disabled=${!pick || !f.ok} title=${pick ? f.hint : 'pick a module first'}
          onClick=${() => pick && f.ok && onForm(f.id)}>
          <b>${f.label}${pick && f.id === 'direct' && f.n ? html` <span class="chip ds-n">${f.n}</span>` : ''}</b>
          <small>${pick ? f.hint : 'Pick a module above.'}</small></button>`)}
      </div>

      ${plan.length ? html`
        <span class="ds-lbl">Card inputs for the module's audio outs
          <small class="muted"> — what you cable tonight, not a calibration. ${portable
            ? 'A patch is portable: these inputs bind to a card when you load it.'
            : html`${freeIn.length} free input${freeIn.length === 1 ? '' : 's'} on ${esc(cardName || 'this card')}.`}</small></span>
        <div class="ds-map">
          ${plan.map((r, i) => html`<div class="ds-row">
            <b>${r.stereo ? '⛓ ' : ''}IN ${r.in_sel.replace('-', '·')}</b>
            <span class="ds-el">${esc(r.label)}</span>
            <select value=${r.element} onChange=${e => onElement(i, e.target.value)}>
              ${[KIT_MIX, ...(elements || [])].map(el => html`<option value=${el}>${elLabel(el)}</option>`)}
            </select>
            <span class="ds-st">${(outs.generic && form === 'direct') ? 'generic' : 'declared'}</span>
          </div>`)}
        </div>` : ''}

      <div class="sbs-ft ds-ft">
        <span class="chip ds-warn">⚠ declared, not measured</span>
        <span class="muted ds-hint">The rack reads the CARD's inputs. What the module sends on each one, only the module says.</span>
        <span class="grow"></span>
        <button class="chip" onClick=${onClose}>Cancel</button>
        <button class="primary" disabled=${!pick || (form !== 'midi' && !plan.length)}
          title=${form === 'midi' ? 'adds one MIDI lane on a USB port' : 'adds one lane per input, in one go'}
          onClick=${onAdd}>${!pick ? 'Add' : form === 'midi' ? 'Add MIDI lane'
            : 'Add ' + plan.length + ' lane' + (plan.length === 1 ? '' : 's')}</button>
      </div>
    </div></div>`;
}

// ── L'EN-TÊTE DU GROUPE ──────────────────────────────────────────────────────────────────────
// Replié par DÉFAUT (2026-09-20) : on ouvre le Designer pour voir un morceau, pas un
// patchbay. Déplié, chaque élément retrouve sa lane entière — c'est la barre d'onglets qui change,
// pas le contenu : une lane d'élément est une lane comme les autres.
export function DrumsetHead({ ds, lanes, moduleName, who, open, onToggle, onPick, curId }) {
  const n = lanes.length;
  return html`<div class=${cls('ds-head', open && 'open')}>
    <span class="ds-ico"><${Icon} id="drumkit" /></span>
    <h4>Drums <small>${esc(moduleName || ds)}${n ? ' · ' + n + ' input' + (n === 1 ? '' : 's') : ''}</small></h4>
    <span class="grow"></span>
    ${who ? html`<span class="chip ds-who">${esc(who)}</span>` : ''}
    <button class="mini ds-fold" onClick=${onToggle}
      title=${open ? 'fold the kit back into one instrument' : 'show one lane per element'}>
      ${open ? '▴ Fold' : '▾ Show elements'}</button>
  </div>
  ${!open ? html`<div class="ds-els">
    ${lanes.map(L => html`<button class=${cls('ds-el-pill', curId === L.id && 'on', L.__off && 'off')}
      title=${L.__off ? elLabel(L.element) + ' — IN ' + L.in_sel + ' is not on this card' : 'open ' + elLabel(L.element)}
      onClick=${() => onPick(L.id)}>${esc(elLabel(L.element))}<small>${L.in_sel.replace('-', '·')}</small></button>`)}
  </div>` : ''}`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Barre de navigation de /live — BANK #NN · preset, les flèches ◀▶, et les deux navigateurs
// (les lignes de la liste au pied d'un tap sur le label, la liste elle-même d'un tap sur la puce de la topbar).
//
// ── POURQUOI ELLE EST SORTIE DE LA VUE PÉDALIER (2026-08-04) ────────────────────────────────
// La vue d'un preset n'est plus un choix de scène : elle DÉCOULE de ce que le preset contient
// (un bloc Standard -> la grille, un bloc Arrangement -> le pupitre, sinon le pédalier). Le
// sélecteur de vue de la topbar a donc disparu — et avec lui le seul chemin qui ramenait vers
// le pédalier. Sans cette barre, un preset à grille devenait un cul-de-sac : plus de ◀▶, donc
// plus de morceau suivant sans passer par le pied.
//
// D'où la règle : **la navigation appartient à la PAGE, pas à une vue.** Les trois vues
// affichent la même barre, au même endroit, et se contentent de remplir ce qu'il y a dessous.
import { html, useState, useEffect, useAsync, post, cls, esc, pad2, bankNo, setTopSlot, go, openInDesigner } from './lib.js';
import { patchDraft } from './designer-model.js';

const recall = (preset, scene) => post('/api/recall', { preset, scene });

// le label de la ligne (tap) ouvre LES LIGNES DE LA LISTE AU PIED (LivePicker, plus bas) — tap = la ligne, comme ◀ ▶
// OUVRIR CE QUI JOUE DANS LE DESIGNER (2026-10-15) : le preset, ou le PATCH joué comme un preset (`patch:<id>`,
// ouvert par son brouillon comme depuis Songs ▸ Patches) ; un essai du Designer (`sandbox-try`) y est déjà : on y retourne.
async function openPlaying(id) {
  if (!id) return;
  if (id === 'sandbox-try') { go('designer'); return; }
  if (id.startsWith('patch:')) {
    const pid = id.slice(6);
    const x = await fetch('/api/patches').then(r => r.json()).then(d => (d.patches || []).find(p => p.id === pid)).catch(() => null);
    if (x) openInDesigner(patchDraft(x)); else go('designer');
    return;
  }
  openInDesigner(id);
}

// LES LIGNES DE LA LISTE AU PIED (2026-10-22) : la fenêtre montrait TOUS les presets du golem, alors que le bouton
// de la topbar choisit déjà ce que joue le pédalier. Elle montre maintenant les chansons de la setlist (ou les sons de la
// bank) choisie là-haut, dans l'ordre des banks ; un tap charge LA LIGNE — sa chanson, son tempo, ses stems, son
// arrangement — comme ◀ ▶ et le pied. Un preset quelconque se joue depuis Songs ▸ Presets.
function LivePicker({ foot, rows, slot, current, playingId, onPick, onClose }) {
  const kind = !playingId ? null : playingId === 'sandbox-try' ? 'draft' : playingId.startsWith('patch:') ? 'patch' : 'preset';
  const sounds = foot && foot.kind === 'sounds';
  return html`<div class="live-picker" onClick=${onClose}>
    <div class="live-picker-card" data-doc="live.songs" onClick=${e => e.stopPropagation()}>
      <div class="live-picker-h"><b><span class=${'slv-type ' + (sounds ? 'bank' : 'setlist')}>${sounds ? '⛓ BANK' : '▤ SETLIST'}</span>
        ${esc((foot && foot.name) || '—')} <small>${sounds ? 'a sound per bank' : 'its songs, in bank order'}</small></b>
        <span class="grow"></span>
        ${kind ? html`<button class="mini lp-designer" title=${'open what is playing now — ' + (current && current.name ? current.name : playingId) + ' — in the Designer'}
          onClick=${() => { onClose(); openPlaying(playingId); }}>✎ Open ${kind} in Designer</button>` : ''}
        <button class="close" style="position:static" onClick=${onClose}>×</button></div>
      <div class="live-picker-grid">
        ${rows.map(r => html`<button class=${cls('live-pick', r.slot === slot && 'on')} onClick=${() => onPick(r.slot)}>
          <span class="lp-n">#${bankNo(r.slot)}</span> ${esc(r.title)}${r.sub ? html`<small>${esc(r.sub)}</small>` : ''}</button>`)}
        ${!rows.length ? html`<div class="muted" style="padding:24px">${sounds ? 'No sound in this bank yet' : 'No song in this setlist yet'} — build it in Songs ▸ Banks & Setlists.</div>` : ''}
      </div>
    </div>
  </div>`;
}

// choix de setlist depuis la scène (appui long sur le nom). Changer de setlist change ce que fait
// le PIED : c'est le seul geste de cette page qui se confirme en 2 taps, et il annonce ce qu'il va
// remplacer. On ne quitte pas /live pour ça — décider « ce soir je joue le set du Bar du Port »
// n'a jamais lieu dans un écran de bibliothèque.
function LiveSetlistPicker({ current, onDone, onClose }) {
  const { data } = useAsync(() => fetch('/api/setlists').then(r => r.json()), []);
  const [arm, setArm] = useState(null);
  const sets = (data || {}).setlists || [];
  const pick = async s => {
    if (s.id === current) return onClose();
    if (arm !== s.id) { setArm(s.id); setTimeout(() => setArm(a => a === s.id ? null : a), 2600); return; }
    await post('/api/setlists/' + s.id + '/activate');
    // ET ON LA CHARGE (bug 2026-10-14) : activer changeait la barre (« SETLIST #01 ») mais laissait jouer le patch de
    // la bank d'avant — les cases restaient les siennes jusqu'à un ◀▶. On rappelle la 1re ligne JOUABLE (un patch, ou
    // un preset présent sur ce poste), le même geste que la flèche.
    try {
      const fl = await fetch('/api/foot-list').then(r => r.json());
      const ids = new Set((await fetch('/api/presets').then(r => r.json())).map(p => p.id));
      const first = (fl.lines || []).findIndex(l => l.patch || (l.preset && ids.has(l.preset)));
      if (first >= 0) await post('/api/recall', { slot: first });
    } catch (e) { /* la liste reste active ; ◀▶ la chargera */ }
    onDone();
  };
  return html`<div class="live-picker" onClick=${onClose}>
    <div class="live-picker-card lsp" data-doc="live.setlists" onClick=${e => e.stopPropagation()}>
      ${/* LE TITRE DIT LES DEUX (2026-10-08) : on choisit ici une SETLIST de morceaux OU une BANK de sons — les
            deux groupes portent les étiquettes de « Banks & Setlists » et les mots de l'en-tête (SETLIST #NN / BANK #NN) */''}
      <div class="live-picker-h"><b>What the pedalboard plays <small>a setlist of songs or a bank of sounds</small></b>
        <button class="close" style="position:static" onClick=${onClose}>×</button></div>
      ${/* DEUX COLONNES (2026-10-15) : setlists à gauche, banks à droite — empilées, la bank tombait sous le pli et
            les deux listes se lisaient comme une seule. Chaque colonne défile seule et reste là même vide. */''}
      <div class="lsp-cols">
      ${[['songs', '▤ SETLIST', 'setlist', 'songs — UP/DOWN goes from song to song', 'No setlist yet.'],
         ['sounds', '⛓ BANK', 'bank', 'sounds — UP/DOWN goes from patch to patch', 'No bank yet.']].map(([k, tag, cl, sub, none]) => {
        const grp = sets.filter(x => (x.kind === 'sounds' ? 'sounds' : 'songs') === k);
        return html`<div class="lsp-col">
          <div class="live-pick-grp"><span class=${'slv-type ' + cl}>${tag}</span><small>${sub}</small></div>
          <div class="lsp-list">
            ${grp.map(s => html`<button class=${cls('live-pick', s.id === current && 'on', arm === s.id && 'arm')}
              onClick=${() => pick(s)}>
              ${esc(s.name)}
              <small>${arm === s.id ? 'play this one?' : s.id === current ? 'on the pedalboard' : s.count + (k === 'sounds' ? ' sound' : ' song') + (s.count === 1 ? '' : 's')}</small>
            </button>`)}
            ${!grp.length ? html`<div class="muted lsp-none">${data ? none : 'Loading…'}</div>` : ''}
          </div>
        </div>`; })}
      </div>
    </div>
  </div>`;
}

// `badges` = ce que la VUE veut afficher dans le label (la pastille ● REC vit avec la logique
// d'enregistrement, qui appartient au pédalier). Le whammy, lui, se lit dans l'état : il est ici.
export function BankBar({ rig, presets, badges, trial }) {
  const st = rig.state;
  const [bkTick, setBkTick] = useState(0);
  const { data: banks } = useAsync(() => fetch('/api/foot-list').then(r => r.json()), [bkTick]);
  const [picker, setPicker] = useState(false);
  // setlist : le nom est AFFICHÉ dans la topbar (l'objet qui décide de ce que fait le pied ne doit
  // pas être invisible là où le pied joue) et changeable par appui long — même idiome que le
  // picker de presets, et le seul geste de cette page qui mérite une confirmation.
  const [slPick, setSlPick] = useState(false);
  const list = presets || [];
  // un ESSAI ou un PATCH joué (docs/patches.md) n'est pas dans la liste : sa fiche arrive à part,
  // sinon l'en-tête disait « no preset » pendant que Pearl Jam sonnait
  const current = list.find(p => p.id === st.preset_id) || trial || null;

  // LA LIGNE (docs/setlists.md §9) : trois lignes peuvent porter le même preset, donc la bank du
  // moment est celle de la LIGNE rappelée (st.song.line), pas la 1re occurrence du preset.
  const bankPresets = (banks && banks.presets) || [];
  const lines = (banks && banks.lines) || [];
  const song = st.song || null;
  const lineSlot = song && song.line ? lines.findIndex(l => l.id === song.line) : -1;
  const slot = lineSlot >= 0 ? lineSlot : (current ? bankPresets.indexOf(current.id) : -1);
  // ⚠ LE PRESET JOUE SANS SA CHANSON (docs/arrangement.md §4, 2026-10-07) : chargé depuis le Designer
  // ou le sélecteur, le preset n'a ni parties ni stems — et l'en-tête affichait quand même « BANK #01 », la
  // bank de sa ligne. On le DIT, et un tap charge la ligne (sa chanson avec). Seulement si la ligne a une
  // chanson à perdre : un preset de sons purs n'a rien à signaler.
  const lone = lineSlot < 0 && slot >= 0 && !(song && song.band_song) && !!lines[slot]
    && !!(lines[slot].band_song || lines[slot].arrangement || lines[slot].backing);
  const titleOf = i => { const l = lines[i]; const p = l && list.find(x => x.id === l.preset);
    return (l && l.title) || (p ? p.name : (l && l.preset ? l.preset : '—')); };

  // navigation ◀▶ : par BANK (lignes avec un rig, dans l'ordre du pied) sinon la liste des presets
  // Une bank de sons joue un patch ; ignorer les presets absents de ce poste.
  const navSlots = lines.length ? lines.map((l, i) => (l.patch || (l.preset && list.some(p => p.id === l.preset))) ? i : -1).filter(i => i >= 0) : [];
  const navOrder = navSlots.length ? navSlots : list.map(p => p.id);
  const bySlot = navSlots.length > 0;
  const pos = bySlot ? navSlots.indexOf(slot) + 1 : (current ? navOrder.indexOf(current.id) + 1 : 0);
  const navStep = d => {
    if (!navOrder.length) return;
    const i = bySlot ? navSlots.indexOf(slot) : navOrder.indexOf(current ? current.id : null);
    const nxt = i < 0 ? navOrder[d > 0 ? 0 : navOrder.length - 1]
      : navOrder[(i + d + navOrder.length) % navOrder.length];
    if (bySlot) post('/api/recall', { slot: nxt }); else recall(nxt, null);
  };
  // « peek » du voisin (±1 dans l'ordre des banks), affiché en petit à côté des flèches
  const peek = d => {
    if (navOrder.length < 2) return null;
    const i = bySlot ? navSlots.indexOf(slot) : navOrder.indexOf(current ? current.id : null);
    const nxt = i < 0 ? navOrder[d > 0 ? 0 : navOrder.length - 1]
      : navOrder[(i + d + navOrder.length) % navOrder.length];
    if (bySlot) return '#' + bankNo(nxt) + ' · ' + titleOf(nxt);
    const p = list.find(x => x.id === nxt);
    return p ? p.name : '—';                       // preset absent : un tiret, pas un id fantôme
  };

  // La setlist vit dans la TOPBAR, pas dans la page (retrait 2026-07-28) : c'est un repère
  // permanent, pas un contrôle — sur scène, la hauteur appartient aux stomps. Le slot contextuel
  // de la topbar est justement libre sur /live. Le geste (appui long = en changer) le suit.
  useEffect(() => {
    // UN TAP, PLUS UN APPUI LONG (2026-10-08 : « comment je sélectionne simplement une bank ? je ne trouve pas ») :
    // l'appui long était le seul chemin vers « quelle setlist joue le pédalier », et rien ne le disait.
    setTopSlot(html`<button class="tb-setlist" data-doc="live.setlist" onClick=${() => setSlPick(true)}
      title=${(banks && banks.kind === 'sounds' ? 'sound list « ' : 'setlist « ') + ((banks && banks.name) || '—') + ' » on the pedalboard and Live — tap to change'}>
      <span class="tb-sl-ic">${banks && banks.kind === 'sounds' ? '⛓' : '▤'}</span>${esc((banks && banks.name) || '—')}
      <small>${navOrder.length}/${(banks && banks.capacity) || 19}</small>
    </button>`);
    return () => setTopSlot(null);
  }, [banks, navOrder.length]);

  // CE QUI JOUE N'EST PAS DANS LA SETLIST DU PIED (2026-10-17 : un patch ouvert depuis le Designer s'affichait
  // « SETLIST — · 0/8 », et ◀ ▶ menaient aux presets d'une setlist qui ne le contient pas) : la barre dit ce qui joue —
  // PATCH ou PRESET — sans numéro ni flèches. La setlist reste à un tap, dans la topbar.
  const alone = slot < 0 && !!current;
  const aloneKind = String(st.preset_id || '').startsWith('patch:') ? 'PATCH' : st.preset_id === 'sandbox-try' ? 'DRAFT' : 'PRESET';
  return html`<div class="live2-bank" data-doc="live.bank">
    ${alone ? html`<span class="live2-nav off"></span><div class="live2-peek prev"></div>` : html`
    <button class="live2-nav" data-doc="live.prev" onClick=${() => navStep(-1)} title="previous preset">◀</button>
    <div class="live2-peek prev">${peek(-1) || ''}</div>`}
    ${/* UN TAP, PLUS UN APPUI LONG (2026-10-08) : rien ne disait que BANK #NN s'ouvrait à l'appui long */''}
    <div class="live2-bank-lbl" data-doc="live.song" onClick=${() => setPicker(true)}
      title=${banks && banks.kind === 'sounds' ? 'tap: the sounds of this bank' : 'tap: the songs of this setlist'}>
      ${/* BANK pour une liste de SONS (patches), SETLIST pour une setlist de chansons (2026-10-08) : le même
            numéro ne dit pas la même chose — un son du pédalier, ou la place d'un morceau dans l'ordre du concert */''}
      <b>${alone ? aloneKind : html`${banks && banks.kind === 'sounds' ? 'BANK' : 'SETLIST'} ${slot >= 0 ? '#' + bankNo(slot) : '—'}${navOrder.length ? ` · ${pos}/${navOrder.length}` : ''}`}</b>
      ${(badges || st.whammy_on || lone) ? html`<div class="live2-badges">
        ${badges || ''}
        ${lone ? html`<button class="live2-badge lone" onClick=${e => { e.stopPropagation(); post('/api/recall', { slot }); }}
          title="this preset was loaded on its own — its song (parts, stems, click) is not. Tap to load the song from its bank.">no song · sounds only — load it</button>` : ''}
        ${st.whammy_on ? html`<span class="live2-badge whammy" title="whammy engaged">▲ ${st.whammy_mode || 'whammy'}</span>` : ''}
      </div>` : ''}
      ${/* le TITRE de la ligne sur scène (« Aerials »), le preset en petit dessous quand il diffère */''}
      <span>${song && song.title ? esc(song.title) : (current ? esc(current.name) : 'no preset')}</span>
      ${!alone && song && song.title && current && song.title !== String(current.name || '').replace(/^⛓\s*/, '') ? html`<small class="live2-rig">${esc(current.name)}${song.bpm ? ' · ♩ ' + song.bpm : ''}</small>` : ''}
    </div>
    ${/* POURQUOI PAS DE FLÈCHES (docs/setlists.md §6, 2026-10-24) : un testeur a pris leur absence pour un bug. La
          place du voisin suivant, vide ici, dit ce qui se passe et donne le geste — le même sélecteur que la topbar */''}
    ${alone ? html`<div class="live2-peek next">${banks && banks.name ? html`<button class="live2-notin"
        onClick=${e => { e.stopPropagation(); setSlPick(true); }}
        title="what plays is not in the list on the pedalboard — tap to choose another list">not in « ${esc(banks.name)} » — tap to change</button>` : ''}</div>
      <span class="live2-nav off"></span>` : html`
    <div class="live2-peek next">${peek(1) || ''}</div>
    <button class="live2-nav" data-doc="live.next" onClick=${() => navStep(1)} title="next preset">▶</button>`}
    ${picker ? html`<${LivePicker} foot=${banks} slot=${slot} current=${current} playingId=${st.preset_id}
      rows=${navSlots.map(i => { const l = lines[i], p = l.preset && list.find(x => x.id === l.preset);
        const name = p ? String(p.name || '').replace(/^⛓\s*/, '') : '';
        return { slot: i, title: titleOf(i), sub: l.patch ? 'patch' : (name && name !== titleOf(i) ? name : '') }; })}
      onPick=${i => { post('/api/recall', { slot: i }); setPicker(false); }} onClose=${() => setPicker(false)} />` : ''}
    ${slPick ? html`<${LiveSetlistPicker} current=${(banks && banks.id) || ''}
      onDone=${() => { setSlPick(false); setBkTick(t => t + 1); }} onClose=${() => setSlPick(false)} />` : ''}
  </div>`;
}

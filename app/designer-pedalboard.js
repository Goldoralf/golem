// SPDX-License-Identifier: GPL-3.0-or-later
// ── L'ÉDITEUR DU PÉDALIER (2026-09-15 : « pour le MIDI assign c'est trop compliqué ») ──
// Un onglet du Designer, à côté des lanes et de ⚙, qui montre les dix cases telles que /live
// les affiche — une PILE, une ligne par bloc avec l'étiquette de sa lane — et où tout
// s'assigne en DEUX TAPS : on tape ce qu'on veut poser (palette à gauche, rangée par lane,
// ou une ligne déjà posée), puis la case. L'en-tête « ⇄ all » d'une case déplace la case
// ENTIÈRE, chaque bloc gardant potards, scènes et lane. La croix d'une ligne la retire du pied.
// Aucun mode, aucun menu : la sélection est l'unique état, et elle se voit (cases-cibles qui
// clignotent, texte d'aide en bas de la palette).
//
// Ce que cet écran NE règle PAS : couleurs et animations (Preset settings), les potards (le
// tiroir du bloc). Il n'écrit qu'UN champ : `block.foot`. Les règles de placement sont celles
// du pied (docs/blocks-doctrine.md) : stomps 6-10 pour tout bloc ; rangée 1-5 seulement pour
// les blocs à `foot_scene_claim` (backing, rec, tuner, boost…), qui REMPLACENT le slot de
// scène ; le looper (foot_mode transport) ne se pose pas : il POSSÈDE ses switches.
import { html, useState, cls, esc } from './lib.js';
import { ICON, SHORT, NAME, ARCH_NAME, ROLE_ICON } from './designer-model.js';

const STOMPS = [6, 7, 8, 9, 10];
const SCENE_SW = [1, 2, 3, 4, 5];
const LANE_TAG = { guitar: 'GTR', bass: 'BASS', voice: 'VOX', keys: 'KEYS', 'keys-pads': 'KEYS', pads: 'PADS', drums: 'DRUM', line: 'LINE', service: 'SVC' };
const laneCls = role => role === 'voice' ? 'vox' : role === 'service' ? 'svc' : role === 'bass' ? 'bass' : role === 'drums' ? 'drums' : role === 'keys' || role === 'keys-pads' || role === 'pads' ? 'keys' : 'gtr';

// le nom qui tient sur UNE ligne — MÊME règle que la pile de /live (page-live.js pileName) :
// l'archétype nommé, sinon le libellé de la capture sans sa marque, sinon le nom court du catalogue
export const pileName = bk => {
  if (bk.variant && ARCH_NAME[bk.variant]) return ARCH_NAME[bk.variant];
  const lb = String(bk.label || '').trim();
  if (lb && lb.length <= 16) return lb;
  if (lb) { const noBrand = lb.split(/\s+/).slice(1).join(' '); if (noBrand.length && noBrand.length <= 16) return noBrand; }
  return SHORT[bk.type] || (NAME[bk.type] || bk.type).split(' (')[0];
};

// items : [{ b, role, laneId, laneName }] — tous les blocs assignables du preset (lanes + services)
// services : [{ type, name }] — services PAS ENCORE dans le preset, qu'un tap ajoute ET pose
// scenes / sceneIdx / colorOf(k, i) : comme la page Live (colors[String(sw)])
// looperOwned : switches possédés par le looper (mode looper), verrouillés ici
// fxDef(type) : la fiche catalogue (foot_scene_claim, foot_mode)
// onPut(id, sw) · onRemove(id) · onMoveSwitch(from, to) · onAddService(type, sw)
export function PedalboardEditor({ items, services, scenes, sceneIdx, colorOf, looperOwned, fxDef, fxIcon, onPut, onRemove, onMoveSwitch, onAddService, onSettings, sceneLines, onFreeSwitch }) {
  // la SÉLECTION, seul état : {kind:'block', id} | {kind:'svc', type} | {kind:'switch', from} | null
  const [sel, setSel] = useState(null);
  // la lane AFFICHÉE dans la palette (2026-09-15 : « la colonne est trop longue, ça devrait être un
  // sélecteur ») — clé de groupe : id de lane, ou '__svc' ; null = la première
  const [tab, setTab] = useState(null);
  const owned = looperOwned || [];
  const byId = id => items.find(x => x.b.id === id);
  const onSwitch = n => items.filter(x => x.b.foot === n);
  const claim = type => !!fxDef(type).foot_scene_claim;
  const transport = type => fxDef(type).foot_mode === 'transport';
  // une case peut-elle RECEVOIR la sélection ?
  const canDrop = n => {
    if (!sel || owned.includes(n)) return false;
    if (sel.kind === 'scene') return n === sel.n;                  // une scène sans pied ne reprend QUE son switch (ids = positions)
    if (sel.kind === 'switch') {
      if (n === sel.from) return false;
      // ÉCHANGE : ce qui part sur la rangée des scènes (1-5) doit pouvoir y aller, dans les deux sens
      return (n > 5 || onSwitch(sel.from).every(x => claim(x.b.type)))
          && (sel.from > 5 || onSwitch(n).every(x => claim(x.b.type)));
    }
    const type = sel.kind === 'svc' ? sel.type : (byId(sel.id) || { b: {} }).b.type;
    if (sel.kind === 'block' && (byId(sel.id) || { b: {} }).b.foot === n) return false;
    return n > 5 || claim(type);
  };
  const drop = n => {
    if (!canDrop(n)) return;
    if (sel.kind === 'scene') onFreeSwitch(n);
    else if (sel.kind === 'switch') onMoveSwitch(sel.from, n);
    else if (sel.kind === 'svc') onAddService(sel.type, n);
    else onPut(sel.id, n);
    setSel(null);
  };
  const pick = s => setSel(cur => cur && cur.kind === s.kind && cur.id === s.id && cur.type === s.type && cur.from === s.from && cur.n === s.n ? null : s);
  const selName = () => !sel ? '' : sel.kind === 'scene' ? 'scene ' + ((scenes[sel.n - 1] || {}).id || '') : sel.kind === 'switch' ? 'switch ' + sel.from
    : sel.kind === 'svc' ? (fxDef(sel.type).name || sel.type) : pileName((byId(sel.id) || { b: {} }).b);
  const isSel = (kind, key) => !!sel && sel.kind === kind && (kind === 'block' ? sel.id === key : kind === 'svc' ? sel.type === key : kind === 'scene' ? sel.n === key : sel.from === key);

  // ── la palette : un groupe par lane (dans l'ordre des onglets), puis les services ──
  const groups = [];
  items.forEach(x => { const k = x.role === 'service' ? '__svc' : x.laneId;
    let g = groups.find(y => y.key === k);
    if (!g) { g = { key: k, role: x.role, name: x.role === 'service' ? 'Services' : x.laneName, items: [] }; groups.push(g); }
    g.items.push(x); });
  let svcG = groups.find(g => g.key === '__svc');
  if (!svcG && services.length) { svcG = { key: '__svc', role: 'service', name: 'Services', items: [] }; groups.push(svcG); }
  // les services viennent en dernier, quel que soit l'ordre de découverte
  groups.sort((a, b) => (a.key === '__svc') - (b.key === '__svc'));
  const cur = groups.find(g => g.key === tab) || groups[0] || null;
  const groupKey = x => x.role === 'service' ? '__svc' : x.laneId;
  // ── LE PÉDALIER SUIT L'ONGLET (2026-10-08 : « sinon il y a trop d'infos ») : les cases ne montrent que les
  // blocs du groupe choisi (Voice 1, Guitar 1, Services…) ; ce qu'un switch porte d'AUTRE se résume en une ligne
  // grise (« + 2 other ») — la case n'est pas libre, et on le voit sans tout lire. Les cases de scène ne gardent
  // que la ligne de la lane choisie.
  const mine = x => !cur || groupKey(x) === cur.key;

  const item = x => { const b = x.b, tr = transport(b.type);
    return html`<button class=${cls('pbe-it', b.foot && 'placed', isSel('block', b.id) && 'sel', tr && 'transport')}
      disabled=${tr}
      title=${tr ? 'the looper owns switches ' + owned.join(', ') + ' — nothing to place'
        : b.foot ? pileName(b) + ' is on switch ' + b.foot + ' — tap, then a switch to move it' : 'tap, then a switch to put it there'}
      onClick=${() => pick({ kind: 'block', id: b.id })}>
      <i class="pbe-g">${fxIcon ? fxIcon(b.type) : (ICON[b.type] || '•')}</i><span>${esc(pileName(b))}</span>
      ${b.foot ? html`<small>#${b.foot}</small>` : tr ? html`<small>owns ${owned.join('·')}</small>` : ''}
    </button>`; };
  const svcItem = s => html`<button class=${cls('pbe-it', 'new', isSel('svc', s.type) && 'sel')}
      title=${'not in this preset yet — tap, then a switch: the block is added and put there'}
      onClick=${() => pick({ kind: 'svc', type: s.type })}>
      <i class="pbe-g">${fxIcon ? fxIcon(s.type) : (ICON[s.type] || '•')}</i><span>${esc(s.name)}</span><small>＋</small>
    </button>`;

  // ── une case : la pile de /live, chaque ligne sélectionnable, sa croix la retire ──
  const line = (x, n) => { const b = x.b;
    return html`<span class=${cls('pbe-l', isSel('block', b.id) && 'sel')} role="button"
      title=${'tap, then another switch to move ' + pileName(b) + ' · ✕ takes it off the foot'}
      onClick=${e => { e.stopPropagation();
        // la case est une CIBLE (un bloc à poser, une scène à qui rendre son switch) : taper n'importe où
        // dedans dépose — sinon le tap au centre tombait sur une ligne et la sélectionnait à la place
        if (canDrop(n)) { drop(n); return; }
        setTab(groupKey(x)); pick({ kind: 'block', id: b.id }); }}>
      <i class="pbe-g">${fxIcon ? fxIcon(b.type) : (ICON[b.type] || '•')}</i>
      <b>${esc(pileName(b))}</b>
      <em class=${'pbe-lane ' + laneCls(x.role)}>${LANE_TAG[x.role] || String(x.role || '').toUpperCase()}</em>
      <u class="pbe-x" title="take it off the foot" onClick=${e => { e.stopPropagation(); setSel(null); onRemove(b.id); }}>✕</u>
    </span>`; };
  const cell = (n, i) => { const bs = onSwitch(n); const used = bs.length > 0; const tgt = canDrop(n);
    const sc = n <= 5 ? scenes[n - 1] : null; const isOwned = owned.includes(n);
    const scene = n <= 5 && !used;
    return html`<div class=${cls('pbe-cell', used && 'used', !used && !sc && 'empty', scene && sc && 'scene', tgt && 'target', isOwned && 'owned', isSel('switch', n) && 'sel')}
      style=${'--pc:' + colorOf(String(n), i)}
      onClick=${() => tgt ? drop(n) : undefined}>
      <span class="pbe-sw">#${n}
        ${used && bs.length && !isOwned ? html`<button class=${cls('pbe-mv', isSel('switch', n) && 'on')} title="move the whole switch — every block on it follows, each keeping its settings, scenes and lane"
          onClick=${e => { e.stopPropagation(); pick({ kind: 'switch', from: n }); }}>⇄ all</button>` : ''}
        ${scene && sc ? html`<small class="pbe-fixed">${i === sceneIdx ? 'scene · active' : 'scene'}</small>` : ''}
      </span>
      ${isOwned ? html`<span class="pbe-hint">looper</span>`
        : used ? (() => { const vis = bs.filter(mine), rest = bs.length - vis.length;
            return html`<span class="pbe-pile">${vis.map(x => line(x, n))}
              ${rest ? html`<span class="pbe-other" title=${bs.filter(x => !mine(x)).map(x => pileName(x.b) + ' (' + (x.role === 'service' ? 'service' : x.laneName) + ')').join(' · ')}>
                + ${rest} other${vis.length ? '' : rest > 1 ? ' blocks' : ' block'}</span>` : ''}</span>`; })()
        : scene && sc ? html`<span class="pbe-schd"><b>${esc(sc.id)}</b><em>${esc(sc.name || 'scene ' + sc.id)}</em></span>
            ${sceneLines ? html`<span class="pbe-pile pbe-acc">${sceneLines(sc).filter(r => !cur || cur.key === '__svc' ? false : (r.laneId ? r.laneId === cur.key : true)).map(r => html`<span class=${cls('pbe-al', r.off && 'off')}>
              <i class="pbe-g">${r.g}</i><b>${esc(r.t)}</b><em class=${'pbe-lane ' + laneCls(r.lane)}>${LANE_TAG[r.lane] || String(r.lane || '').toUpperCase()}</em></span>`)}</span>` : ''}`
        : html`<span class="pbe-hint">${tgt ? html`tap to put<br/><b>${esc(selName())}</b> here` : n <= 5 ? 'no scene' : 'free'}</span>`}
      ${tgt && sel.kind === 'scene' ? html`<span class="pbe-give">tap: give it back to scene <b>${esc((scenes[n - 1] || {}).id)}</b> — ${esc(bs.map(x => pileName(x.b)).join(' + '))} goes back to the palette</span>` : ''}
    </div>`; };

  return html`<div class="pbe">
    <div class="pbe-pal">
      ${groups.length ? html`<div class="pbe-sel" role="tablist">
        ${groups.map(g => { const n = g.items.filter(x => x.b.foot).length;
          return html`<button role="tab" aria-selected=${cur && g.key === cur.key} class=${cls('pbe-seltab', cur && g.key === cur.key && 'on')}
            title=${n ? n + ' block' + (n > 1 ? 's' : '') + ' of ' + g.name + ' on the foot' : 'nothing of ' + g.name + ' on the foot yet'}
            onClick=${() => setTab(g.key)}><i class=${'pbe-dot ' + laneCls(g.role)}></i><span>${esc(g.name)}</span>${n ? html`<small>${n}</small>` : ''}</button>`; })}
      </div>` : ''}
      ${cur ? html`<div class="pbe-items">${cur.items.map(item)}${cur.key === '__svc' ? services.map(svcItem) : ''}</div>` : ''}
      ${!groups.length ? html`<p class="muted">No block in this preset yet — add some in the lanes first.</p>` : ''}
      <p class="pbe-help">${sel
        ? sel.kind === 'scene' ? html`<b>${esc(selName())}</b> is selected — tap switch <b>${sel.n}</b> to give it back its switch.`
        : html`<b>${esc(selName())}</b> is selected — tap a switch to ${sel.kind === 'switch' ? 'move it there' : 'put it there'}${sel.kind !== 'switch' && !claim(sel.kind === 'svc' ? sel.type : (byId(sel.id) || { b: {} }).b.type) ? ' (stomps 6–10)' : ''}.
 <button class="mini" onClick=${() => setSel(null)}>cancel</button>`
        : html`Tap a block, then a switch. <b>⇄ all</b> moves a whole switch.
            ${onSettings ? html`<button class="mini" onClick=${onSettings}>Colors & animations</button>` : ''}`}</p>
    </div>
    <div class="pbe-board">
      ${(() => {
        // ── LA CAPACITÉ DU PIED (docs/band-scenes.md, écran 4) : combien de scènes ont un switch, combien
        // de switches de scène sont pris par des services, et quelles scènes n'en ont pas — dit ici,
        // plutôt que découvert sur scène au moment de chercher le solo.
        const onFoot = scenes.slice(0, 5).filter((x, i) => !onSwitch(i + 1).length && !owned.includes(i + 1)).length;
        const taken = SCENE_SW.filter(k => onSwitch(k).length);
        const hidden = scenes.map((x, i) => ({ sc: x, n: i + 1 })).filter(h => h.n > 5 || onSwitch(h.n).length || owned.includes(h.n));
        return html`<div class="pbe-cap">
          <span><i class="pbe-capdot sc"></i><b>${onFoot} scene${onFoot === 1 ? '' : 's'}</b> on the foot</span>
          ${taken.length ? html`<span><i class="pbe-capdot svc"></i><b>${taken.length} switch${taken.length === 1 ? '' : 'es'}</b> taken by services (${taken.map(k => k + ' ' + onSwitch(k).map(x => pileName(x.b)).join('+')).join(' · ')})</span>` : ''}
          ${hidden.length ? html`<span class="warn"><i class="pbe-capdot hid"></i><b>${hidden.length} without a switch</b>: ${hidden.map(h => h.sc.id + (h.sc.name ? ' ' + h.sc.name : '')).join(', ')} — the arrangement or the screen can still call ${hidden.length === 1 ? 'it' : 'them'}</span>` : ''}
        </div>
        ${hidden.length ? html`<div class="pbe-hidden">
          ${hidden.map(h => { const free = h.n <= 5 && !owned.includes(h.n);
            return html`<button class=${cls('pbe-hs', isSel('scene', h.n) && 'sel', !free && 'locked')} disabled=${!free}
              title=${free ? 'tap, then switch ' + h.n + ' to give it back to scene ' + h.sc.id : h.n > 5 ? 'scenes after E have no switch on a 5-scene pedalboard' : 'the looper owns switch ' + h.n}
              onClick=${() => free && setSel(cur => cur && cur.kind === 'scene' && cur.n === h.n ? null : { kind: 'scene', n: h.n })}>
              <b>${esc(h.sc.id)}</b><span>${esc(h.sc.name || 'scene ' + h.sc.id)}</span><small>${free ? 'switch ' + h.n + ' is taken' : h.n > 5 ? 'no switch' : 'looper'}</small></button>`; })}
        </div>` : ''}`;
      })()}
      <div class="pbe-rowlbl">Stomps · switches 6 – 10</div>
      <div class="pbe-row">${STOMPS.map((n, i) => cell(n, i))}</div>
      <div class="pbe-rowlbl">Scenes · switches 1 – 5 — a service (backing, rec, tuner…) may take a slot</div>
      <div class="pbe-row">${SCENE_SW.map((n, i) => cell(n, i))}</div>
    </div>
  </div>`;
}

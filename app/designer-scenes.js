// SPDX-License-Identifier: GPL-3.0-or-later
// ── SCENES & SOUNDS : NOMMER LE SON DE CHAQUE INSTRUMENT DANS CHAQUE SCÈNE (2026-10-08) ─────────
// Maquette validée : mockups/scenes-sounds.html. Ouvert par « ⋯ ▸ Scenes & sounds » du Designer.
// Lignes = lanes (GTR, VOX, BASS…), colonnes = scènes ; une case = le SON que la lane joue dans la
// scène (un « état », docs/band-scenes.md §4) : son NOM en gros — ou, pas encore nommé, le bloc qui
// fait l'identité de la lane, en italique gris — et ce bloc en petit dessous.
//
// Ce tableau ne fait QU'UNE chose : nommer. Taper une case ouvre un champ DANS la case, des
// suggestions en un tap, Entrée ou toucher ailleurs = enregistré. L'ancienne barre d'attribution
// (liste des états, « Same as », « New state », niveau, mute, « Open … ») est partie : le choix du
// son se fait sur la chaîne de la lane, scène par scène ; le niveau et le mute dans la feuille de
// scène. Un son joué par plusieurs scènes est le MÊME son : le nommer le nomme partout, et la case le
// dit. En bas, « On Live » : les cases de scène telles que /live les affichera (page-live.js, .linst).
import { html, useState, useEffect, useAsync, cls, esc, LIVE_PALETTE } from './lib.js';
import { laneStateAt, laneIdentity, shortBlockName, laneMutedIn } from './designer-model.js';

const LANE_TAG = { guitar: 'GTR', bass: 'BASS', voice: 'VOX', keys: 'KEYS', 'keys-pads': 'KEYS', pads: 'PADS', drums: 'DRUM', line: 'LINE' };
const laneCls = r => r === 'voice' ? 'vox' : r === 'bass' ? 'bass' : r === 'drums' ? 'drums' : r === 'keys' || r === 'keys-pads' || r === 'pads' ? 'keys' : 'gtr';
// les noms usuels d'un son, par rôle — un tap les écrit dans le champ
const SUGGEST = {
  guitar: ['Clean', 'Crunch', 'Drive', 'Fuzz', 'Lead', 'Rhythm'],
  bass: ['Pick', 'Finger', 'Drive', 'Fuzz', 'Clean'],
  voice: ['Verse', 'Chorus', 'Lead', 'Backing', 'FX'],
  keys: ['Piano', 'Pad', 'Organ', 'Lead', 'Strings'],
};

// p = le document du Designer ; lanes = p.lanes ; sceneIdx = la scène active
// claimOf(n) -> nom du service qui prend le switch n (1-5), sinon null
// onRename(laneId, stateId, name) : l'écriture — elle passe par l'upd du Designer
export function SceneDictionary({ p, lanes, sceneIdx, claimOf, laneTitle, inTagOf, onPickScene, onRename }) {
  const scenes = p.scenes || [];
  const [edit, setEdit] = useState(null);           // {lane, si, v} : la case en cours de nommage
  // LES NOMS DU PATCH D'ORIGINE EN TÊTE DES SUGGESTIONS (2026-10-08) : une lane déposée depuis un patch garde
  // `patch_from` ; les scènes de ce patch sont nommées (« Main », « Slapback », « Radio »…) — exactement des noms de
  // sons. En SUGGESTION seulement : le preset ne dit pas quelle scène du patch joue dans quelle scène.
  const { data: pat } = useAsync(() => fetch('/api/patches').then(r => r.json()).catch(() => null), []);
  const patchNames = L => { const id = ((L && L.patch_from) || {}).id; const x = id && (((pat || {}).patches) || []).find(y => y.id === id);
    return x ? [...new Set((x.scenes || []).map(sc => String(sc.name || '').trim()).filter(Boolean))] : []; };
  // le champ prend le focus à l'ouverture de la case (un `ref` ne suffisait pas : le clic qui ouvre la case
  // rend le focus au document après le montage)
  const editKey = edit ? edit.lane + '/' + edit.si : '';
  useEffect(() => { if (!editKey) return; const t = setTimeout(() => { const el = document.querySelector('.sdx-in');
    if (el) { el.focus(); el.select(); } }, 0); return () => clearTimeout(t); }, [editKey]);
  const stOf = (L, sc) => laneStateAt(p, L, sc) || {};
  const nameOf = st => st && !st.implicit && st.name ? st.name : '';
  const gearOf = (L, sc) => shortBlockName(laneIdentity(L, sc)) || '';
  const usedBy = (L, id) => scenes.filter(s => stOf(L, s).id === id).map(s => s.id);

  // `val` : une suggestion tapée nomme d'un coup (un tap), sans repasser par le champ
  const commit = val => {
    if (!edit) return;
    const L = lanes.find(x => x.id === edit.lane), sc = scenes[edit.si];
    const v = String(val != null ? val : edit.v || '').trim();
    setEdit(null);
    if (!L || !sc || !v) return;                    // vide = rien ne change (un son ne se « dénomme » pas ici)
    const st = stOf(L, sc);
    if (st.id && v !== nameOf(st)) onRename(L.id, st.id, v);
  };

  const header = (sc, i) => { const cl = i < 5 ? claimOf(i + 1) : null;
    const where = i >= 5 ? 'no switch — arrangement or screen' : cl ? 'SW' + (i + 1) + ' taken by ' + cl : 'SW' + (i + 1);
    return html`<button class=${cls('sdx-col', i === sceneIdx && 'on', (i >= 5 || cl) && 'nofoot')} title=${'scene ' + sc.id + ' — ' + where + ' · tap to play it'}
      onClick=${() => onPickScene(i)}>
      <b>${esc(sc.id)}<em>${esc(sc.name || '')}</em></b><small>${esc(where)}</small></button>`; };

  const cell = (L, sc, si) => {
    const st = stOf(L, sc), nm = nameOf(st), gear = gearOf(L, sc);
    const prev = si > 0 ? scenes[si - 1] : null;
    const same = !!prev && stOf(L, prev).id === st.id;
    const muted = laneMutedIn(sc, L);
    if (edit && edit.lane === L.id && edit.si === si) {
      const others = usedBy(L, st.id).filter(x => x !== sc.id);
      return html`<div class="sdx-c edit">
        <input class="sdx-in" maxlength="24" value=${edit.v} placeholder=${gear || 'Name this sound'}
          onInput=${e => setEdit({ ...edit, v: e.target.value })}
          onKeyDown=${e => { if (e.key === 'Enter') commit(e.target.value); if (e.key === 'Escape') setEdit(null); }}
          onBlur=${e => commit(e.target.value)} />
        ${(() => { const fromPatch = patchNames(L);
          const usual = (SUGGEST[L.role] || SUGGEST[laneCls(L.role) === 'keys' ? 'keys' : 'guitar']).filter(x => !fromPatch.includes(x));
          const chip = (x, pt) => html`<button class=${cls(x === edit.v && 'on', pt && 'pt')} onMouseDown=${e => e.preventDefault()}
            title=${pt ? 'a scene of the patch « ' + (L.patch_from.name || L.patch_from.id) + ' »' : ''} onClick=${() => commit(x)}>${pt ? '⛓ ' : ''}${x}</button>`;
          return html`<div class="sdx-sug">${fromPatch.map(x => chip(x, true))}${usual.map(x => chip(x, false))}</div>`; })()}
        ${others.length ? html`<span class="sdx-note">also played in ${others.join(', ')} — renamed there too</span>` : ''}
      </div>`;
    }
    return html`<button class=${cls('sdx-c', same && 'same', muted && 'mute')}
      title=${(nm ? '« ' + nm + ' »' : 'not named yet') + ' on ' + laneTitle(L) + (same ? ' — same sound as scene ' + prev.id : '') + ' · tap to name it'}
      onClick=${() => setEdit({ lane: L.id, si, v: nm })}>
      ${nm ? html`<span class="sdx-nm">${esc(nm)}</span>`
           : html`<span class="sdx-nm ph">${same ? '—' : esc(gear || laneTitle(L)) + ' — tap to name'}</span>`}
      <span class="sdx-gear">${muted ? 'muted in this scene' : same ? 'same as ' + esc(prev.id) : esc(gear || '—')}</span></button>`;
  };

  // ── ON LIVE : les cases de scène de /live, avec les noms (même grammaire que page-live.js) ──
  const colors = p.colors || {};
  const preview = () => html`<div class="sdx-live"><span class="sdx-live-lb">On Live</span>
    <div class="sdx-live-row">${scenes.map((sc, i) => { const per = {}, seen = {};
      lanes.forEach(L => { per[L.role] = (per[L.role] || 0) + 1; });
      return html`<div class=${cls('sdx-pt', i === sceneIdx && 'on')} style=${'--pc:' + (colors[sc.id] || LIVE_PALETTE[i % LIVE_PALETTE.length])}>
        <b>${esc(sc.id)}<em>${esc(sc.name || '')}</em></b>
        ${lanes.map(L => { seen[L.role] = (seen[L.role] || 0) + 1;
          const tag = (LANE_TAG[L.role] || String(L.role || '').toUpperCase()) + (per[L.role] > 1 ? ' ' + seen[L.role] : '');
          const muted = laneMutedIn(sc, L), nm = muted ? 'silent' : nameOf(stOf(L, sc));
          return html`<span class=${cls('sdx-pr', muted && 'off')}><i class=${'li-tag ' + laneCls(L.role)}>${tag}</i>${nm ? esc(nm) : ''}</span>`; })}
      </div>`; })}</div></div>`;

  return html`<div class="sdx" style=${'--ncol:' + Math.max(1, scenes.length) + ';--nrow:' + Math.max(1, lanes.length)}>
    <div class="sdx-grid">
      <div class="sdx-corner"></div>
      ${scenes.map(header)}
      ${lanes.map(L => html`
        <div class="sdx-row"><i class=${'li-tag ' + laneCls(L.role)}>${LANE_TAG[L.role] || String(L.role || '').toUpperCase()}</i>
          <small>${esc(laneTitle(L))} · ${esc(inTagOf(L))}</small></div>
        ${scenes.map((sc, si) => cell(L, sc, si))}`)}
    </div>
    ${preview()}
  </div>`;
}

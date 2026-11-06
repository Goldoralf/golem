// SPDX-License-Identifier: GPL-3.0-or-later
// LA LIGNE ARRANGEMENT DE L'ONGLET ⚙ — une TUILE et la chanson lisible à côté (2026-10-01, maquette
// « Arrangement block ») ; avant : un panneau sans tuile (2026-09-16, version B), qui laissait l'arrangement seul
// bloc qu'on ne mettait pas au pied par un appui long. Le choix de la chanson et l'avance vivent dans le TIROIR.
//
// Le bloc n'a ni entrée ni sortie audio : les pastilles IN/OUT mentaient sur sa nature. À la place : la
// setlist, la chanson, la pédale (rig), la règle d'avance (rig), le bouton des parties, et la FRISE des
// parties dessous — ce qui rend l'arrangement reconnaissable en une seconde, et dit tout de suite si la
// chanson a déjà ses parties. Le panneau EST le bloc : plus de tuile.
//
// Trois états : aucune chanson (le sélecteur devient une phrase, un seul geste utile : ajouter le rig à la
// setlist), plusieurs chansons sur ce rig (le sélecteur porte « N more » et un liseré), chanson liée sans
// parties (la frise vide invite à les poser, le bouton change de verbe).
import { html, useState, cls, esc, go, longPress, lpFired, useAsync } from './lib.js';
import { sectionLook } from './designer-model.js';
import { FOOTSW } from './icons.js';
import { linesOfPreset } from './designer-arrsheet.js';

const partsOf = ln => (((ln || {}).arrangement || {}).params || {}).sections || [];
const secs = (parts, bpm) => parts.reduce((a, s) => a + (s.bars || 0), 0) * 4 * 60 / (bpm || 120);
const mmss = t => Math.floor(t / 60) + ':' + String(Math.round(t % 60)).padStart(2, '0');

export function ArrangementLane({ preset, block, setlists, pick, onPick, onOpen, onSwitch, onAdvance,
                                 automation, drives, onAutomation, loneLoad, songs }) {
  // CE QUE LA MIGRATION A DÉPLACÉ (arrangement-controls §7, lot 3) — dit UNE fois par preset et par écran :
  // le « vu » est une commodité d'affichage (localStorage), pas un état du rack
  const { data: moved } = useAsync(() => fetch('/api/arrangement/stacks-moved').then(r => r.json()).catch(() => null), []);
  const mv = (((moved || {}).items) || []).find(x => x && x.preset === preset.id) || null;
  const mvKey = mv ? 'golem.arrMoved.' + preset.id + '.' + Math.round(mv.at || 0) : null;
  const [mvSeen, setMvSeen] = useState(0);
  const mvShow = (() => { if (!mvKey) return false; try { return !localStorage.getItem(mvKey); } catch (e) { return true; } })() && !mvSeen;
  const mvName = t => ({ rec: 'Rec', click: 'Click', 'backing-track': 'Backing' }[t] || t);
  const all = (setlists && setlists.setlists) || [];
  const rows = linesOfPreset(setlists, preset.id);
  // la setlist affichée : celle du choix, sinon celle de la première ligne qui joue ce rig, sinon l'active
  const sid = (pick && pick.sid) || (rows[0] && rows[0].sid) || (all.find(s => s.active) || all[0] || {}).id || null;
  const sl = all.find(s => s.id === sid) || null;
  const here = rows.filter(r => r.sid === sid);
  const cur = here.find(r => pick && r.line.id === pick.lid) || here[0] || null;
  const parts = cur ? partsOf(cur.line) : [];
  const advance = ((block || {}).params || {}).advance || 'bars';
  const title = r => r.line.title || preset.name || preset.id;
  // LOT D (2026-09-24) : les parties s'écrivent dans SONGS — un seul point d'entrée. Une ligne qui est une
  // chanson y va directement ; une ligne libre ouvre encore le tiroir (qui dit d'en faire une chanson).
  const openParts = () => (cur && cur.line.band_song) ? go('songs/songs/' + encodeURIComponent(cur.line.band_song)) : onOpen && onOpen();

  // une CHANSON du répertoire qui joue ce preset sans être sur une setlist (sheet.preset) : elle existe, on la dit
  const song = !cur ? ((songs || [])[0] || null) : null;
  const openSong = s => go('songs/songs/' + encodeURIComponent(s.song));

  const tag = !cur && song ? html`<span class="arl-tag song" title="the song is in your repertoire — put it in a setlist from Songs">in Songs · on no setlist</span>`
    : !cur ? html`<span class="arl-tag">no song</span>`
    : html`${rows.length > 1 ? html`<span class="arl-tag warn">${rows.length} songs use this preset</span>` : ''}
        ${parts.length ? html`<span class="arl-tag song" title="the parts belong to the song — they are written in Songs, every setlist that plays it follows">written in Songs</span>` : html`<span class="arl-tag ok">linked · no parts yet</span>`}`;

  // ── LA TUILE REVIENT (2026-10-01, maquette « Arrangement block » validée) : tous les blocs se mettent au
  // pied par un appui long sur LEUR tuile — l'arrangement était le seul à y échapper, et personne ne pensait à lui
  // donner un switch. Une tuile SANS pastilles IN/OUT (elles mentaient, §4 bis) ; à côté, la chanson et sa frise,
  // lisibles d'un coup d'œil. Tap = le tiroir (chanson, avance, parties lues) ; appui long = MIDI assign.
  // LA PASTILLE = « ⏻ Automation » DE LA CHANSON (docs/arrangement.md §4) — l'interrupteur qui
  // n'existait que sur la page chanson. Éteinte, aucun liseré : chaque bloc retrouve son comportement propre.
  const on = !!automation;
  const tile = html`<button class=${cls('tile', 'arl-tile', !on && 'byp')} style="--tc:#c98a2e"
      title="tap = settings · long press = put it on a footswitch (start · stop)"
      onClick=${() => { if (lpFired()) return; onOpen && onOpen(); }} ...${longPress(() => onSwitch && onSwitch())}>
    <span class="tile-ic">▤</span><span class="tile-nm">Arrangement</span>
    ${block && block.foot ? html`<span class="tile-foot" title=${'pedalboard footswitch ' + block.foot + ' — start · stop'}><${FOOTSW} />${block.foot}</span>` : ''}
    <span class=${cls('tile-dot', !on && 'ko')} onClick=${e => { e.stopPropagation(); cur && onAutomation && onAutomation(); }}
      title=${!cur ? 'no song linked to this preset' : on ? 'automation on — the song drives the outlined blocks · tap to turn it off'
        : 'automation off — tap to turn it on'}></span>
  </button>`;

  return html`<div class=${cls('cfg-lane', 'arl', on && drives && 'arl-drives')}>
    <div class="cfg-lane-hd"><b>Arrangement</b><small title="A preset plays several songs: the parts live on the song. The block carries what belongs to the preset — its switch and how it advances.">the song this preset plays</small>
      ${on && drives ? html`<small class="arl-drv" title="the outlined blocks start and stop with the song — tick or untick them in Songs ▸ When the song starts">▤ drives the outlined blocks</small>` : ''}
      ${loneLoad ? html`<small class="arl-lone" title="the rack is playing this preset on its own — its song (parts, stems) is not loaded. Load it from its bank on /live.">⚠ loaded without its song — sounds only</small>` : ''}
      <span class="grow"></span>${tag}</div>
    ${mvShow ? html`<div class="arl-moved">
      <span>${mv.moved.map(mvName).join(' + ')} left switch ${mv.switch}: ${mv.moved.length > 1 ? 'they now start' : 'it now starts'} with the song — ticked in <b>Songs ▸ When the song starts</b>${mv.songs > 1 ? ' (' + mv.songs + ' songs)' : ''}.</span>
      <button class="mini" onClick=${() => { try { localStorage.setItem(mvKey, '1'); } catch (e) {} setMvSeen(1); }}>OK</button>
    </div>` : ''}
    <div class="arl-body">
      ${tile}
      <div class="arl-song">
        <div class="arl-row">
          ${cur ? html`
            <span class="arl-cur" title=${'the song this preset is arranged for — in « ' + ((sl || {}).name || '') + ' »'}>
              ▤ ${esc((sl || {}).name || '')} <em>·</em> <b>${String(cur.n).padStart(2, '0')} · ${esc(title(cur))}</b></span>
            <span class="arl-meta">${parts.length ? parts.length + ' part' + (parts.length > 1 ? 's' : '') + ' · ' + mmss(secs(parts, preset.bpm)) + ' · ' : ''}next part <b>${advance === 'foot' ? 'on tap' : 'auto · bars'}</b></span>
            ${here.length > 1 || rows.length > 1 ? html`<span class="arl-more">${rows.length - 1} more</span>` : ''}`
          : song ? html`
            <span class="arl-cur" title="a song of your repertoire plays this preset">▤ <b>${esc(song.title || song.song)}</b></span>
            ${(songs || []).length > 1 ? html`<span class="arl-more">${songs.length - 1} more</span>` : ''}`
          : html`
            ${/* PAS DE CHANSON = UN ÉTAT, PAS UNE ALERTE (2026-10-24) : un gros « ＋ Add « preset » to « Factory Golem » »
                  prenait la ligne, et ajoutait une ligne libre à la setlist active. Un petit bouton ouvre le tiroir, qui
                  relie une chanson ou en crée une. */''}
            <span class="arl-cur muted">No song for this preset yet</span>
            <button class="mini edit-only" onClick=${() => onOpen && onOpen()} title="link a song of your repertoire, or make one from this preset">Link to a song…</button>`}
        </div>
        ${!cur && song ? html`<button class="arl-strip empty go" onClick=${() => openSong(song)}>Its parts are written in Songs — open « ${esc(song.title || song.song)} »</button>`
          : !cur ? html`<div class="arl-strip empty">Without a song, this preset plays its scenes under your foot — no automation.</div>`
          : !parts.length ? html`<button class="arl-strip empty go" onClick=${openParts}>No parts yet — write them in Songs: intro, verse, chorus…</button>`
          : html`<button class="arl-strip" onClick=${() => onOpen && onOpen()} title=${parts.length + ' parts · ' + mmss(secs(parts, preset.bpm)) + ' — tap for the details'}>
              ${parts.map(s => html`<i style=${'--pc:' + sectionLook(s).color + ';--w:' + Math.max(1, s.bars || 1)}><span>${esc(s.name)}</span>${s.scene ? html`<b>${s.scene}</b>` : ''}</i>`)}
            </button>`}
      </div>
    </div>
  </div>`;
}

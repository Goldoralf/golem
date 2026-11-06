// SPDX-License-Identifier: GPL-3.0-or-later
// LE TIROIR DU BLOC ARRANGEMENT (docs/arrangement.md §4 bis — maquette « Designer allégé », 2026-09-16).
//
// LOT D (2026-09-24, « un seul point d'entrée, /songs ») : ce tiroir N'ÉDITE PLUS les parties. Il
// garde ce qui appartient au RIG — la pédale et la règle d'avance — et LISTE les chansons que ce preset
// joue, chacune avec « Open in Songs ». Avant, il embarquait l'éditeur complet : deux portes sur le même
// objet, dont une invisible à celui qui construit son arrangement dans Songs. Ce qui suit dans l'en-tête
// historique décrit l'ancien double-écriture ; il n'en reste que la moitié rig.
//
// Le bloc vit dans l'onglet ⚙, sa propre lane juste après le Click (§7). Il porte ce qui appartient au RIG :
// sa PÉDALE et la règle d'avance (§6, « chaque preset porte sa règle »). Les PARTIES, elles, appartiennent
// à la chanson : elles vivent sur la ligne de setlist depuis le 2026-09-08, parce qu'un même rig sert trois
// morceaux de structures différentes. Ce tiroir est donc une FENÊTRE sur la chanson, jamais une copie.
//
// ⚠ IL ÉCRIT DANS DEUX OBJETS, et l'écran le dit : les parties partent dans la LIGNE (POST /api/setlists/
// <set>/line, comme le détail de ligne), la pédale et l'avance dans le BROUILLON du preset (upd). Sans
// l'étiquette « saves into the song », « enregistré » voudrait dire deux choses au même endroit.
//
// Trois états : aucune chanson (lecture seule, on propose d'en relier une), une chanson (tout est éditable),
// plusieurs chansons sur ce rig (on nomme celle qu'on montre et on laisse choisir).
import { html, useState, useAsync, cls, esc, go } from './lib.js';
import { ArrRead } from './arr-read.js';
import { SongCard, songOfCtx } from './designer-song.js';   // l'encadré de la chanson chargée (le même que Backing Track)
import { AssignBoard } from './designer-sheets.js';


// les lignes de TOUTES les setlists qui jouent ce preset — l'arrangement d'un rig est toujours celui
// d'un morceau, et un rig peut en servir plusieurs
export const linesOfPreset = (data, pid) => {
  const out = [];
  ((data && data.setlists) || []).forEach(s => (s.lines || []).forEach((ln, i) => {
    if (ln && ln.preset === pid) out.push({ sid: s.id, sname: s.name, active: !!s.active, n: i + 1, line: ln });
  }));
  return out.sort((a, b) => (b.active - a.active) || a.sname.localeCompare(b.sname) || a.n - b.n);
};
// DONNER UNE CHANSON À CE PRESET (2026-10-24) — à la place de « ＋ Add « preset » to a setlist », qui posait une LIGNE
// libre dans la setlist active (une bank de plus au pédalier, une setlist d'usine modifiée) sans créer de chanson : les
// parties, qui appartiennent à la chanson, ne pouvaient toujours pas s'écrire. Deux gestes, dans l'ordre du modèle : relier
// une chanson du répertoire, ou en créer une depuis ce preset. La setlist se choisit ensuite, dans Songs.
export function LinkSong({ ctx, presetName }) {
  const { data } = useAsync(() => fetch('/api/songs').then(r => r.json()).catch(() => null), []);
  const songs = ((data || {}).songs || []).slice().sort((a, b) => (a.title || '').localeCompare(b.title || ''));
  const [pick, setPick] = useState('');
  const [title, setTitle] = useState(presetName || '');
  const [kind, setKind] = useState('');
  const chosen = songs.find(s => s.id === pick) || null;
  const other = chosen && (chosen.sheet || {}).preset;
  if (ctx.draft) return html`<div class="arr-link"><span class="arrsh-note">Save the preset first: a draft cannot be a song's preset.</span></div>`;
  return html`<div class="arr-link">
    <div class="arr-link-hd"><b>Give this preset a song</b>
      <span class="arrsh-note">the parts — intro, verse, chorus… — belong to the song</span></div>
    <div class="arr-link-row">
      <select class="arl-sel big" value=${pick} onChange=${e => setPick(e.target.value)}>
        <option value="">A song of your repertoire…</option>
        ${songs.map(s => html`<option value=${s.id}>${s.title}${s.artist ? ' — ' + s.artist : ''}${(s.sheet || {}).preset ? ' · plays « ' + s.sheet.preset + ' »' : ''}</option>`)}
      </select>
      <button class="mini" disabled=${!pick || !!ctx.busy} onClick=${() => ctx.linkSong(pick)}>${ctx.busy === 'link' ? '…' : 'Link'}</button>
    </div>
    ${other ? html`<span class="arrsh-note warn">« ${esc(chosen.title)} » plays « ${esc(other)} » now — linking it makes it play this preset instead</span>` : ''}
    <div class="arr-link-row">
      <input class="arl-in" value=${title} placeholder="title of a new song" onInput=${e => setTitle(e.target.value)} />
      <div class="tb-seg" title="a cover, or your own song — golem.fm needs to know before it can travel">
        <button class=${cls(kind === 'cover' && 'on')} onClick=${() => setKind('cover')}>cover</button>
        <button class=${cls(kind === 'original' && 'on')} onClick=${() => setKind('original')}>original</button>
      </div>
      <button class="mini" disabled=${!title.trim() || !kind || !!ctx.busy} onClick=${() => ctx.newSong(title.trim(), kind)}>${ctx.busy === 'new' ? '…' : 'New song'}</button>
    </div>
    <span class="arrsh-note">Then put the song in a setlist from Songs.${ctx.said ? ' ' : ''}${ctx.said ? html`<b class="bad">${ctx.said}</b>` : ''}</span>
  </div>`;
}

const titleOf = (row, presetName) => row.line.title || presetName || row.line.preset;
const partsOf = ln => (((ln || {}).arrangement || {}).params || {}).sections || [];

export function ArrangementSheet({ block, preset, presetId, presetName, fx, fxIcon, fxName, fxShort, imap,
                                  scenes, sceneIdx, pedals, blocks, sceneClaim, transport, transportLoops,
                                  transportLanes, tab, onTab, onFoot, onAdvance, onRemove, onClose, pick, onPick, songCtx }) {
  const { data } = useAsync(() => fetch('/api/setlists').then(r => r.json()).catch(() => null), []);
  const rows = linesOfPreset(data, presetId);
  const advance = ((block || {}).params || {}).advance || 'bars';

  const nSongs = songCtx && songCtx.used ? (songCtx.used.songs || []).length + (songCtx.used.lines || []).length : rows.length;
  const head = html`<div class="arrsh-hd">
    <span class="arrsh-ic">▤</span><b>Arrangement</b>
    ${rows.length ? '' : (presetId === 'sandbox-try' || presetId === 'nouveau-preset')
      ? html`<span class="arrsh-tag warn" title="a trial or a new bench has no song: name it (Save) or open the real preset from the Library">this is a trial — no song can link to it</span>`
      : html`<span class="arrsh-tag warn">no song linked</span>`}
    ${/* des CHANSONS, pas des lignes : Paper Kite dans deux setlists est UNE chanson (vu le 2026-10-18) */''}
    ${nSongs > 1 ? html`<span class="arrsh-tag warn" title="the same preset plays several songs — each has its own parts">${nSongs} songs use this preset</span>` : ''}
    <span class="grow"></span>
    ${onRemove ? html`<button class="mini danger" title="remove the arrangement block from this preset" onClick=${onRemove}>🗑</button>` : ''}
    <button class="mini" onClick=${onClose}>✕</button>
  </div>`;

  // ── LE TIROIR DE LA MAQUETTE « Arrangement block » (2026-10-01) : Song (lue, « Change song »),
  // Next part (auto · bars | on tap, dit en clair), Parts (la piste de Songs, LUE) — modifier = Songs.
  const [changing, setChanging] = useState(false);
  const all = (data && data.setlists) || [];
  const sid = (pick && pick.sid) || (rows[0] && rows[0].sid) || (all.find(x => x.active) || all[0] || {}).id || null;
  const here = rows.filter(r => r.sid === sid);
  const cur = here.find(r => pick && r.line.id === pick.lid) || here[0] || null;
  const parts = cur ? partsOf(cur.line) : [];
  const bs = cur && cur.line.band_song;
  const openSong = () => { onClose && onClose(); bs ? go('songs/songs/' + encodeURIComponent(bs)) : go('songs/setlists/' + cur.sid + '/' + cur.line.id); };

  // LA CHANSON CHARGÉE (docs/designer-song.md, 2026-10-18) : le même encadré que le tiroir Backing Track — l'arrangement
  // appartient à la chanson comme sa backing. « Change song » (deux listes de lignes) n'a plus lieu d'être : deux lignes
  // de la même chanson jouent les mêmes parties, et une autre chanson se CHARGE.
  const loadedSong = songOfCtx(songCtx);
  // les parties de la chanson chargée se lisent dans SA FICHE (la source) — pas dans la première ligne qui joue ce
  // preset, qui peut être une autre chanson quand celle-ci n'est sur aucune setlist
  const partsShown = loadedSong ? ((((songCtx.sheet || {}).arrangement || {}).params || {}).sections || []) : [];
  const sec = partsShown.reduce((n, x) => n + (+x.bars || 0), 0);
  const songCard = songCtx ? html`<${SongCard} song=${loadedSong}
      label="The song loaded now · its arrangement plays"
      chips=${loadedSong ? [{ t: partsShown.length ? partsShown.length + ' part' + (partsShown.length > 1 ? 's' : '') + ' · ' + sec + ' bars' : 'no parts yet', cls: partsShown.length ? 'ok' : 'warn' }] : []}
      emptyTitle="No song loaded — the arrangement belongs to the song"
      songs=${(songCtx.used || {}).songs || []} busy=${songCtx.busy} said=${songCtx.said}
      onLoad=${id => songCtx.load(id)} onUnload=${() => songCtx.unload()}
      onOpen=${() => { onClose && onClose(); go('songs/songs/' + encodeURIComponent(loadedSong.id)); }}
      extra=${!rows.length && !((songCtx.used || {}).songs || []).length ? html`<${LinkSong} ctx=${songCtx} presetName=${presetName} />` : ''} />` : null;

  const settings = () => html`<div class="arrsh-set">
    <div class="arrsh-top">
      <span class="arrsh-note">this preset's own — not global</span>
      <span class="grow"></span>
      <span class="arrsh-note">on the foot</span>
      <button class="arrsh-sw" onClick=${() => onTab && onTab('assign')} title="tap to choose the footswitch">
        ${block.foot ? 'SW ' + block.foot + ' · start / stop' : 'no switch yet — choose one'}</button>
    </div>
    ${songCard || ''}
    <div class="arrsh-grid">
      ${songCard ? '' : html`<b>Song</b>
      <div class="arrsh-songrow">
        ${cur && !changing ? html`
          <span class="arl-cur">▤ ${esc(cur.sname)} <em>·</em> <b>${String(cur.n).padStart(2, '0')} · ${esc(titleOf(cur, presetName))}</b></span>
          ${rows.length > 1 ? html`<span class="arrsh-note">${rows.length - 1} more line${rows.length > 2 ? 's' : ''} play${rows.length > 2 ? '' : 's'} this preset</span>` : ''}
          <button class="mini" onClick=${() => setChanging(true)}>Change song</button>`
        : cur ? html`
          <select class="arl-sel" value=${sid} onChange=${e => onPick && onPick({ sid: e.target.value, lid: null })}>
            ${all.map(x => html`<option value=${x.id} selected=${x.id === sid}>▤ ${x.name}${x.active ? ' · on the foot' : ''}</option>`)}
          </select>
          <select class="arl-sel big" value=${cur.line.id} onChange=${e => onPick && onPick({ sid, lid: e.target.value })}>
            ${here.map(r => html`<option value=${r.line.id} selected=${r.line.id === cur.line.id}>${String(r.n).padStart(2, '0')} · ${esc(titleOf(r, presetName))}${partsOf(r.line).length ? '' : ' — no parts'}</option>`)}
          </select>
          <button class="mini" onClick=${() => setChanging(false)}>Done</button>`
        : songCtx ? html`<${LinkSong} ctx=${songCtx} presetName=${presetName} />`
        : html`<span class="arrsh-note">No song plays this preset yet — give it one in Songs.</span>`}
      </div>`}
      <b>Next part</b>
      <div class="arrsh-songrow">
        <div class="tb-seg">
          <button class=${cls(advance !== 'foot' && 'on')} onClick=${() => onAdvance && onAdvance('bars')}>auto · bars</button>
          <button class=${cls(advance === 'foot' && 'on')} onClick=${() => onAdvance && onAdvance('foot')}>on tap</button>
        </div>
        <span class="arrsh-note">${advance === 'foot'
          ? 'one tap of the switch moves on to the next part — no drift possible'
          : "moves on by itself when the part's bars are played — needs the click or the backing running"}</span>
      </div>
    </div>
    ${songCard ? (loadedSong ? (partsShown.length
        ? html`<${ArrRead} title="Parts" parts=${partsShown} bpm=${(songCtx.sheet || {}).bpm || (preset || {}).bpm} preset=${preset}
            onEdit=${() => { onClose && onClose(); go('songs/songs/' + encodeURIComponent(loadedSong.id)); }} editLabel="Open in Songs" />`
        : html`<div class="arr-ro"><div class="arr-ro-hd"><b>Parts</b><span class="muted">no parts yet</span>
            <span class="grow"></span><button class="linkish" onClick=${() => { onClose && onClose(); go('songs/songs/' + encodeURIComponent(loadedSong.id)); }}>Write them in Songs ›</button></div></div>`) : '')
      : !cur ? html`<p class="arrsh-note">Without a song, this preset plays its scenes under your foot — no automation. Parts belong to a song: add this preset to a setlist, make the line a song, and write its arrangement in Songs.</p>`
      : parts.length ? html`<${ArrRead} title="Parts" parts=${parts} bpm=${cur.line.bpm || (preset || {}).bpm} preset=${preset}
          onEdit=${openSong} editLabel=${bs ? 'Open in Songs' : 'Open the line'} />`
      : html`<div class="arr-ro"><div class="arr-ro-hd"><b>Parts</b><span class="muted">no parts yet</span>
          <span class="grow"></span><button class="linkish" onClick=${openSong}>${bs ? 'Write them in Songs' : 'Open the line'} ›</button></div></div>`}
  </div>`;

  const body = () => {
    if (tab === 'assign') {
      return html`<div class="arrsh-assign"><${AssignBoard} block=${block} blocks=${blocks} scenes=${scenes}
        sceneIdx=${sceneIdx} sceneClaim=${sceneClaim} transport=${transport} transportLoops=${transportLoops}
        transportLanes=${transportLanes} expOn=${false} canExp=${false} pedals=${pedals}
        fxIcon=${fxIcon} fxName=${fxName} fxShort=${fxShort} onSwitch=${onFoot} /></div>`;
    }
    return settings();
  };

  return html`<div class="sheet-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && onClose()}>
    <div class="sheet arrsh">
      ${head}
      <div class="sheet-tabs2">
        <button class=${cls('sheet-tab2', (tab || 'params') === 'params' && 'on')} onClick=${() => onTab && onTab('params')}>Settings</button>
        <button class=${cls('sheet-tab2', tab === 'assign' && 'on')} onClick=${() => onTab && onTab('assign')}>MIDI assign</button>
      </div>
      ${body()}
    </div>
  </div>`;
}

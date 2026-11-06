// SPDX-License-Identifier: GPL-3.0-or-later
// Tiroir du bloc BACKING TRACK (docs/song-backing.md, maquette validée le 2026-10-18).
//
// LA BACKING APPARTIENT À LA CHANSON. Le preset ne choisit plus de chanson (l'ancien tiroir faisait lier une chanson à
// un preset : c'était l'envers du modèle) ; il est le LECTEUR — son pied — et il porte la RÈGLE des stems : il sait ce
// qu'on joue en live, puisqu'il connaît ses lanes. Le tiroir montre donc :
//   · la chanson CHARGÉE (si elle joue ce preset) : c'est sa backing qui joue ;
//   · « The stems this preset mutes — in every song » : la règle, tuile par famille, avec sa raison ;
//   · « Used by » : les chansons et les lignes qui jouent ce preset — calculé par le golem, jamais stocké.
// « Change… » n'existe plus : c'est la chanson qui choisit son preset, pas l'inverse.
import { html, useState, useEffect, useRef, post, cls, esc, go, bankNo } from './lib.js';
import { SongCard } from './designer-song.js';   // l'encadré de la chanson chargée, le même que le tiroir Arrangement

const FAMS = [['guitar', 'Guitar'], ['bass', 'Bass'], ['piano', 'Piano'], ['drums', 'Drums'], ['vocals', 'Vocals'], ['other', 'Other']];
const dur = s => s ? Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0') : '';
const asset = (slug, k) => '/api/backing/asset/' + encodeURIComponent(slug) + '/' + k;

// la règle du preset, calculée ICI sur le brouillon (miroir de bridge/backing_owner.rule) : {famille: raison}
export function presetRule(params, own) {
  const out = {};
  if ((params || {}).mute_own !== false) {
    Object.entries(own || {}).forEach(([f, lane]) => { out[f] = 'you play it — ' + String(lane).toLowerCase() + ' lane'; });
  }
  Object.entries((params || {}).stems || {}).forEach(([f, how]) => {
    if (how === 'play') delete out[f];
    else if (how === 'mute') out[f] = 'muted by this preset';
  });
  return out;
}

// le tap sur une tuile, côté PRESET : l'exception la plus courte qui donne l'état voulu (rien si la règle le donne déjà)
export function toggleStem(params, own, fam) {
  const p = params || {};
  const stems = { ...(p.stems || {}) };
  const muted = !!presetRule(p, own)[fam];
  const base = p.mute_own !== false && !!(own || {})[fam];
  const want = !muted;
  if (want === base) delete stems[fam]; else stems[fam] = want ? 'mute' : 'play';
  return stems;
}

export function BackingDrawer({ preset, params, onParam, foot, onHead }) {
  const p = params || {};
  const [d, setD] = useState(null);
  const [tick, setTick] = useState(0);
  const [layer, setLayer] = useState('preset');        // ce que les tuiles éditent : la règle du preset, ou la chanson
  const [hear, setHear] = useState(false);
  // le preset TEL QU'IL EST dans le Designer (brouillon compris) : ses lanes disent ce qu'il joue
  const sig = JSON.stringify([(preset || {}).id, (preset || {}).lanes, (preset || {}).inputs]);
  useEffect(() => {
    let live = true;
    post('/api/backing/drawer', { preset }).then(r => live && setD(r)).catch(() => live && setD({ own: {}, used_by: { songs: [], lines: [] } }));
    return () => { live = false; };
  }, [sig, tick]);
  const song = d && d.song;
  const loaded = !!(song && song.slug);
  const listen = async () => {
    if (hear) { setHear(false); await post('/api/backing/listen', {}).catch(() => null); return; }
    if (!loaded) return;
    setHear(true);
    const r = await post('/api/backing/listen', { slug: song.slug }).catch(() => null);
    if (!r || !r.ok) setHear(false);
  };
  // ▶ Listen et le pied montent dans la rangée ⏻ (designer-sheets, onHead) — la grammaire du tiroir Standard
  const act = useRef({}); act.current = { listen };
  useEffect(() => {
    if (!onHead) return undefined;
    onHead(html`<span class=${cls('bkd-sw', !foot && 'none')}>${foot ? 'SW' + foot + ' · ▶ / ■' : 'no switch'}</span>
      <button class=${cls('mini', 'bkd-listen', hear && 'on')} disabled=${!loaded && !hear}
        title=${loaded ? 'listen to the original of the song loaded' : 'no song loaded — open this preset from a song'}
        onClick=${() => act.current.listen()}>${hear ? '■ Stop' : '▶ Listen'}</button>`);
    return undefined;
  }, [loaded, hear, foot]);
  useEffect(() => () => onHead && onHead(null), []);

  const own = (d && d.own) || {};
  const rule = presetRule(p, own);
  const songMuted = new Set((song && song.muted) || []);
  const has = f => !loaded || !(song.stems || []).length || (song.stems || []).some(s => String(s).split('-')[0] === f);
  const tap = async f => {
    if (layer === 'song' && loaded) {
      await post('/api/backing/mix/' + encodeURIComponent(song.slug), { stem: f, mute: songMuted.has(f) ? 0 : 1 }).catch(() => null);
      setTick(t => t + 1);
      return;
    }
    const stems = toggleStem(p, own, f);
    onParam('stems', Object.keys(stems).length ? stems : undefined);
  };
  const used = (d && d.used_by) || { songs: [], lines: [] };
  // CHARGER une chanson de ce preset, sans la lancer (POST /api/arrangement {op: select}) : sa backing s'arme, le
  // tiroir passe à « The song loaded now » — sans aller chercher la chanson ailleurs
  const [loading, setLoading] = useState(null);
  const [said, setSaid] = useState('');
  const load = async sid => {
    setLoading(sid); setSaid('');
    const r = await post('/api/arrangement', { op: 'select', song: sid }).catch(e => ({ error: (e.body && e.body.error) || String(e) }));
    setLoading(null);
    if (r && r.error) { setSaid(r.error); return; }
    setTimeout(() => setTick(t => t + 1), 400);
  };
  // DÉCHARGER : le preset reste, seul (plus de chanson, plus de backing) — retenu au redémarrage comme le chargement
  const unload = async () => {
    setLoading('-'); setSaid('');
    if (hear) { setHear(false); await post('/api/backing/listen', {}).catch(() => null); }
    const r = await post('/api/arrangement', { op: 'unselect' }).catch(e => ({ error: (e.body && e.body.error) || String(e) }));
    setLoading(null);
    if (r && r.error) { setSaid(r.error); return; }
    setTimeout(() => setTick(t => t + 1), 400);
  };
  const usedN = used.songs.length + used.lines.length;

  return html`<div class="bkd">
    ${/* 1. LA CHANSON CHARGÉE — sa backing joue ; sans chanson, le tiroir le dit */''}
    ${!d ? html`<p class="muted">…</p>` : html`<${SongCard}
      song=${loaded ? { id: song.id, title: song.title, artist: song.artist, from: song.from,
                        cover: song.has_cover ? asset(song.slug, 'cover') : null, photo: song.has_photo ? asset(song.slug, 'photo') : null } : null}
      label="The song loaded now · its backing plays"
      chips=${loaded ? [song.duration_sec && { t: dur(song.duration_sec) },
                        song.cached ? { t: '● stems on this golem', cls: 'ok' } : { t: 'stems not on this golem', cls: 'warn' }] : []}
      emptyTitle=${song && song.no_backing ? 'The song loaded has no backing' : 'No song loaded — the backing belongs to the song'}
      emptyText=${song && song.no_backing ? html`« ${esc(song.title || '')} » carries no stems on this golem — get them on golem.fm, or link a backing in the song.` : null}
      songs=${song && song.no_backing ? [] : used.songs} busy=${loading} said=${said}
      onLoad=${load} onUnload=${unload} onOpen=${() => go('songs/songs/' + encodeURIComponent(song.id))} />`}

    ${/* 2. LA RÈGLE DES STEMS — dans le preset, pour toutes ses chansons ; la chanson peut couper en plus */''}
    <div class="bkd-rule">
      <div class="bkd-rh"><span class="bkd-lbl">${layer === 'song' && loaded ? 'The stems this song mutes — this song only' : 'The stems this preset mutes — in every song'}</span>
        <span class="grow"></span>
        ${loaded ? html`<div class="bkd-seg">
          <button class=${cls(layer === 'preset' && 'on')} onClick=${() => setLayer('preset')}>This preset</button>
          <button class=${cls(layer === 'song' && 'on')} onClick=${() => setLayer('song')}>This song</button></div>` : ''}
        ${layer === 'preset' || !loaded ? html`<button class=${cls('bkd-tog', p.mute_own !== false && 'on')}
          onClick=${() => onParam('mute_own', p.mute_own === false)}><i></i>Mute what this preset plays</button>` : ''}
      </div>
      <div class="bkd-parts">${FAMS.map(([f, label]) => {
        const byPreset = rule[f], bySong = songMuted.has(f);
        const state = byPreset ? 'off' : bySong ? 'song' : 'on';
        const why = byPreset || (bySong ? 'muted by this song' : has(f) ? 'plays' : 'not in this song');
        return html`<button class=${cls('bkd-part', 'p-' + f, state, !has(f) && 'absent')} onClick=${() => tap(f)}
          title=${layer === 'song' && loaded ? 'tap: mute or play it in this song only' : 'tap: mute or play it in every song of this preset'}>
          ${label}<small>${why}</small></button>`; })}</div>
      <span class="muted bkd-hint">${layer === 'song' && loaded
        ? 'Saved with the song, on this golem. A stem muted by the preset stays muted.'
        : Object.keys(own).length
          ? 'This preset plays ' + Object.keys(own).map(f => FAMS.find(x => x[0] === f)[1]).join(' and ') + ' on this golem (a lane with an input). Tap a part to override.'
          : 'No lane of this preset has an input on this golem: nothing is muted for you. Tap a part to mute it anyway.'}</span>
    </div>

    ${/* 3. USED BY — calculé, jamais stocké dans le preset */''}
    <div class="bkd-used">${usedN ? html`Used by
        ${used.songs.map(s => html`<button class="bkd-chip" onClick=${() => go('songs/songs/' + encodeURIComponent(s.song))}>♪ ${esc(s.title || s.song)}</button>
          ${loaded && s.song !== song.id ? html`<button class="bkd-chip load" disabled=${!!loading} onClick=${() => load(s.song)}>${loading === s.song ? '⏳' : '▶ Load'}</button>` : ''}
          ${(s.lines || []).length ? html` in ${s.lines.map(l => html`<button class="bkd-chip" onClick=${() => go('songs/setlists/' + encodeURIComponent(l.setlist))}>${esc(l.name || l.setlist)} #${bankNo(l.bank)} ›</button>`)}` : ''}`)}
        ${used.lines.map(l => html`<button class="bkd-chip" onClick=${() => go('songs/setlists/' + encodeURIComponent(l.setlist))}>${esc(l.title || 'a line')} · ${esc(l.name || l.setlist)} #${bankNo(l.bank)} ›</button>`)}
        <span class="muted">(found by golem, not stored in the preset)</span>`
      : html`<span class="muted">No song uses this preset yet — a song picks its preset on its page (Songs).</span>`}</div>
  </div>`;
}

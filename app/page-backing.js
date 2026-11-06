// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Backing (hub Library) — backing tracks golem.fm : catalogue du serveur fusionné avec le
// CACHE local (assets/backing/<slug>/, 6 stems séparés + meta). C'est aussi la page de gestion du
// cache : usage disque, téléchargement, suppression, et « lié aux presets… » (via /api/presets).
// Cache-first : golem.fm éteint, la page montre le cache et tout reste jouable.
// Pas de « + New » (2026-10-08) : un backing ARRIVE — de golem.fm, ou en important un .golem sur le golem.
// Composer un backing local à partir de samples a été RETIRÉ ; ceux qui existent se jouent et se suppriment encore.
import { html, useState, useEffect, useRef, useAsync, cls, esc, setSubToolbar } from './lib.js';
import { useGenreLabel, songGenresText } from './genres.js';

// la bande des instruments de la carte golem.fm (lib/parts.ts) : mêmes sigles, même ordre (le bridge l'ordonne)
export const PART_SHORT = { guitar: 'GTR', bass: 'BASS', piano: 'KEYS', drums: 'DRUMS', voice: 'VOX' };
export const PARTS = ['guitar', 'bass', 'piano', 'drums', 'voice'];
export const PART_LABEL = { guitar: 'Guitar', bass: 'Bass', piano: 'Piano', drums: 'Drums', voice: 'Voice' };
const fmtBytes = b => !b ? '—' : b > 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b > 1e6 ? (b / 1e6).toFixed(0) + ' MB' : Math.round(b / 1e3) + ' kB';
// le titre normalisé (casse, accents, ponctuation ignorés) — la même règle que inventory._norm_title et golem.fm
const normTitle = t => (t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
const fmtDur = s => s ? Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0') : '';

// `vocals` : l'onglet Tracks ▸ Vocals (2026-10-16) — les LIGNES VOCALS (cache `k-*` de golem.fm, `.golem` de
// catégorie « vocals » : de l'audio et des paroles, golemfile.category). Backings montre tout le reste. Comme sur
// golem.fm, une carte Vocals n'a pas de bande d'instruments : la bande vient de la tab, c'est celle de /songs.
export function BackingPage({ vocals = false } = {}) {
  const genreLabel = useGenreLabel();               // le style d'une chanson = ses genres (docs/genres.md)
  const [tick, setTick] = useState(0);
  const { data: cat } = useAsync(() => fetch('/api/backing/catalog').then(r => r.json()), [tick]);
  const [playing, setPlaying] = useState(null);   // slug dont on écoute le MIX ORIGINAL (un seul)
  const [listenMsg, setListenMsg] = useState('');
  // ▶ = l'ORIGINAL joué par REAPER, sur les enceintes du rack (2026-10-17) — plus par le navigateur, qui sortait
  // sur une autre carte que celle que REAPER tient. Sans original (une ligne Vocals), le rack joue la somme des stems.
  const listen = async s => {
    if (playing === s.slug) { setPlaying(null); fetch('/api/backing/listen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); return; }
    setPlaying(s.slug); setListenMsg('');
    const r = await fetch('/api/backing/listen', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: s.slug }) }).then(x => x.json()).catch(() => ({ error: 'golem unreachable' }));
    if (r.error) { setPlaying(p => (p === s.slug ? null : p)); setListenMsg(r.error); }
  };
  // l'écoute s'arrête d'elle-même à la fin de la chanson (sa durée) ; quitter la page la coupe
  const playingRef = useRef(null);
  playingRef.current = playing;
  useEffect(() => () => { if (playingRef.current) fetch('/api/backing/listen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); }, []);
  useEffect(() => {
    const s = ((cat || {}).songs || []).find(x => x.slug === playing);
    if (!s || !s.duration_sec) return;
    const t = setTimeout(() => setPlaying(p => (p === s.slug ? null : p)), (s.duration_sec + 1) * 1000);
    return () => clearTimeout(t);
  }, [playing]);
  const { data: cache } = useAsync(() => fetch('/api/backing/cache').then(r => r.json()), [tick]);
  const { data: presets } = useAsync(() => fetch('/api/presets').then(r => r.json()), [tick]);
  const { data: mst } = useAsync(() => fetch('/api/golemfm/status').then(r => r.json()), [tick]);
  const [q, setQ] = useState('');
  const [dl, setDl] = useState(null);              // slug en téléchargement
  const pollRef = useRef(null);
  useEffect(() => () => clearInterval(pollRef.current), []);
  const cachedBy = {};
  ((cache || {}).songs || []).forEach(s => { cachedBy[s.slug] = s; });
  // un preset lié à l'ancienne entrée du cache que la chanson de la bibliothèque remplace (`aliases`) lui reste lié
  const linkedBy = (slug, also = []) => (presets || []).filter(p => [slug, ...also].some(k => (p.backing || []).includes(k)));

  const download = slug => {
    fetch('/api/backing/dl', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug }) });
    setDl(slug);
    pollRef.current = setInterval(async () => {
      const st = await fetch('/api/backing/dl/status').then(r => r.json()).catch(() => null);
      if (st && st.state !== 'busy') { clearInterval(pollRef.current); setDl(null); setTick(x => x + 1); }
    }, 1200);
  };

  // VOCALS = « ce qu'un chanteur peut chanter » (golem.fm, 2026-10-17) : les lignes Vocals, PLUS toute chanson qui a des
  // paroles synchronisées (une tab n'y change rien) — une seule fois par titre, la ligne Vocals l'emporte
  const all = (cat || {}).songs || [];
  const voiced = new Set(all.filter(s => s.vocals).map(s => normTitle(s.title)));
  const inTab = s => vocals ? (s.vocals || (s.lyrics && !voiced.has(normTitle(s.title)))) : (!s.vocals || s.also_song);
  const list = all.filter(inTab).filter(s =>
    !q || ((s.title || '') + ' ' + (s.artist || '') + ' ' + s.slug).toLowerCase().includes(q.toLowerCase()));

  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search songs…" onInput=${e => setQ(e.target.value)} />
      <span class=${cls('t3k-dot', mst && mst.authed && 'on')} title=${!mst ? 'checking…' : mst.authed ? 'golem.fm online'
        : mst.configured ? 'golem.fm offline — cache only' : 'not paired (Settings ▸ Connect ▸ golem.fm)'}></span>
      <span class="bkg-disk muted" title="local stems cache">💾 ${fmtBytes((cache || {}).bytes)}</span>
      ${listenMsg ? html`<span class="muted std-msg">${listenMsg}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [mst && mst.authed, (cache || {}).bytes, listenMsg]);

  return html`<div class="bkg-page">
    <div class="bkg-grid">
      ${list.map(s => {
        const c = cachedBy[s.slug];
        const links = linkedBy(s.slug, s.aliases);
        const on = playing === s.slug;
        const art = k => '/api/backing/asset/' + encodeURIComponent(s.slug) + '/' + k;
        // LA CARTE DE CHANSON DE golem.fm (Catalogue ▸ song-card) : pochette 80 px à gauche, titre, artiste précédé de sa
        // photo ronde, album · année, tonalité en pastille ; en pied les étiquettes à gauche et les gestes à droite. Le
        // ▶ reste TOUJOURS visible sur la pochette : l'écran est tactile, il n'y a pas de survol.
        // CARTE COMPACTE (2026-10-16 : « on perd de l'espace ») : ni taille de fichier ni pastille verte (le liseré
        // vert de la carte dit déjà « sur le rack »). PAS DE 🗑 ICI (2026-10-17) : une chanson se supprime dans
        // Songs, le ménage du cache se fait dans Settings ▸ Storage. Seul geste : ⬇ sync d'un titre pas encore sur le rack.
        const actions = (s.local || c || s.library) ? ''
          : html`<button class="mini" disabled=${dl === s.slug || !(mst && mst.authed)} onClick=${() => download(s.slug)}>
              ${dl === s.slug ? '⬇ …' : '⬇ sync'}</button>`;
        const genre = (s.genres && s.genres.length) ? songGenresText(s.genres, genreLabel) : s.style ? genreLabel(s.style) : '';
        return html`<div class=${cls('bkg-card', (c || s.library) && 'cached', on && 'on')}>
          <div class="bkg-top">
            <div class="bkg-art">
              <span class="bkg-noart" aria-hidden="true">♪</span>
              ${s.has_cover ? html`<img src=${art('cover')} alt="" loading="lazy"
                onError=${e => { e.target.style.display = 'none'; }} />` : ''}
              <button class="bkg-play edit-only" title=${on ? 'stop the original' : 'listen to the original track'}
                onClick=${() => listen(s)}>${on ? '❚❚' : '▶'}</button>
            </div>
            <div class="bkg-info">
              <b class="bkg-title" title=${esc(s.title || s.slug)}>${esc(s.title || s.slug)}</b>
              ${s.artist ? html`<div class="bkg-artist">
                ${s.has_photo ? html`<img class="bkg-face" src=${art('photo')} alt="" loading="lazy"
                  onError=${e => { e.target.style.display = 'none'; }} />` : ''}
                <span>${esc(s.artist)}</span>
              </div>` : ''}
              ${s.album ? html`<div class="bkg-card-meta muted">${esc(s.album)}${s.year ? ' · ' + s.year : ''}</div>` : ''}
              <div class="bkg-chips">
                ${s.key ? html`<span class="bkg-tag bkg-tag-key" title="detected key">${esc(s.key)}</span>` : ''}
                ${genre ? html`<span class="bkg-tag">${esc(genre)}</span>` : ''}
                ${s.duration_sec ? html`<span class="bkg-chip">${fmtDur(s.duration_sec)}</span>` : ''}
                ${s.difficulty != null ? html`<span class="bkg-chip" title="difficulty (golem.fm)">lvl ${s.difficulty}</span>` : ''}
                ${s.local ? html`<span class="bkg-chip" title="local backing — its stems are song samples of this rack">local</span>` : ''}
                ${links.length ? html`<span class="bkg-links" title="presets using this song">⚡ ${links.map(p => esc(p.name)).join(', ')}</span>` : ''}
              </div>
            </div>
          </div>
          ${actions ? html`<div class="bkg-card-act">${actions}</div>` : ''}
          ${!vocals && s.parts && s.parts.length ? html`<div class="bkg-strip-parts" role="group" aria-label="Instruments in this song">
            ${PARTS.map(p => {
              // LES CINQ, toujours (golem.fm /songs, 2026-10-17) ; un absent garde son sigle, grisé. Sans tab : pas de bande
              // du tout — « rien d'affirmé » n'est pas « tout absent »
              const on = s.parts.includes(p);
              return html`<span class=${cls('bkg-part', 'bkg-part-' + p, !on && 'off')}
                title=${on ? PART_LABEL[p] + ' part' : 'No ' + PART_LABEL[p].toLowerCase() + ' part'}>${PART_SHORT[p]}</span>`;
            })}
          </div>` : ''}

        </div>`;
      })}
      ${/* appairé mais hors d'atteinte ≠ pas appairé : « Pair with golem.fm » se disait à un golem appairé hors ligne (2026-10-22) */''}
      ${cat && !list.length ? html`<p class="muted bkg-empty">No ${vocals ? 'songs to sing along' : 'songs'}${q ? ' matching' : ''}.
        ${q || !mst || mst.authed ? '' : mst.paired ? ' golem.fm is out of reach — only the songs already on this golem show here.'
          : html` Make them on this golem: <a href="#/system/engines/separation">Separate a folder</a> of your own recordings,
            or drop a <b>.golem</b> file in Songs ▸ ⤓ Drop a file.`}</p>` : ''}
    </div>
  </div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Standards (hub Library) — les grilles d'accords que le rack JOUE pendant que tu
// joues le thème. Contrat docs/standards.md.
//
// ── LE RACK N'A PAS DE CATALOGUE ─────────────────────────────────────────────────────────
// Décision le mainteneur (2026-08-03) : cette page n'affiche PAS une liste de standards à parcourir.
// Elle montre ce que le rack A : ce que golem.fm lui a envoyé (« Send to <golem> ») et ce que portent ses
// dossiers de chansons. Plus un miroir des étoiles (2026-10-08) : ↻ Sync met à jour, n'ajoute ni ne retire.
//
// D'où la même forme que l'onglet Backings : de grandes cartes, une par morceau qu'on
// possède. Un backing a une pochette ; un standard n'en a pas — ce qu'on veut VOIR de lui,
// c'est sa GRILLE. Elle tient donc la place de la pochette (même raisonnement que le
// piano-roll des grooves : montrer le contenu, pas une icône).
import { useFactoryShow, keepFactory } from './factory-show.js';
import { html, useState, useEffect, useAsync, useRef, cls, esc, setTopAction, setSubToolbar } from './lib.js';

const post = (url, body) => fetch(url, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body || {}),
}).then(r => r.json()).catch(e => ({ error: String(e) }));

// La grille complète : une mesure = une case, 4 par ligne, coupée à chaque changement de
// SECTION — un chorus se lit par sections (A A B A), pas comme un ruban de 32 mesures.
// Exportée : le tiroir du bloc Standard affiche la MÊME grille (designer-standard.js).
const PAGE = 30;                  // cartes rendues par tranche du défilement infini

export function Chart({ bars, cur, big }) {
  if (!bars || !bars.length) return html`<div class="std-chart empty">—</div>`;
  const rows = [];
  let row = null;
  bars.forEach((b, i) => {
    if (!row || row.section !== b.section || row.cells.length >= 4) {
      row = { section: b.section, cells: [] };
      rows.push(row);
    }
    row.cells.push({ ...b, i });
  });
  return html`<div class=${cls('std-chart', big && 'big')}>
    ${rows.map(r => html`<div class="std-row">
      <span class="std-sec">${esc(String(r.section || '').replace(/\d+$/, ''))}</span>
      ${r.cells.map(c => html`<span class=${cls('std-bar', c.i === cur && 'on')}>
        ${c.chords.length
          ? c.chords.map(ch => html`<b class="std-sym">${esc(ch.sym)}</b>`)
          : html`<i class="std-hold">%</i>`}
      </span>`)}
      ${Array.from({ length: 4 - r.cells.length }, () => html`<span class="std-bar pad"></span>`)}
    </div>`)}
  </div>`;
}

// La « pochette » d'un standard = son APERÇU D'ACCORDS (golem.fm StandardCard `.std-chords`, 2026-10-17) : une barre par
// mesure des 32 premières, plus haute quand la mesure porte plus d'accords — l'harmonie qui bouge se voit, et la 1ʳᵉ
// barre de chaque groupe de 4, plus vive, fait lire la carrure. Calculé par le bridge (`shape`) : aucune requête par carte.
function ChordShape({ shape }) {
  return html`<div class="sta-chords" aria-hidden="true">
    ${(shape || []).map(n => html`<i style=${'height:' + Math.min(100, 26 + 18 * n) + '%'}></i>`)}
  </div>`;
}

const FEEL_LABEL = { swing: 'Swing', bossa: 'Bossa', latin: 'Latin', ballad: 'Ballad', waltz: 'Waltz', funk: 'Funk',
  even: 'Even 8ths', straight: 'Straight', samba: 'Samba', rock: 'Rock' };
const feelLabel = f => FEEL_LABEL[f] || (f ? f[0].toUpperCase() + f.slice(1) : '');

export function StandardsPage() {
  const facShow = useFactoryShow();          // l'usine masquée par sorte (Settings ▸ Content ▸ Factory)
  const [tick, setTick] = useState(0);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [armDel, setArmDel] = useState(null);
  const [charts, setCharts] = useState({});          // slug -> aperçu (grille + méta)
  const [live, setLive] = useState(null);
  const [open, setOpen] = useState(null);            // slug dont on déplie la grille entière

  // la liste ENTIÈRE (`limit=0`) : la route coupe à 200 par défaut, et la page — recherche comprise — ne voyait que les
  // 200 premiers des ~2 800 standards (2026-10-17)
  const { data } = useAsync(() => fetch('/api/standards?limit=0').then(r => r.json()), [tick]);
  const { data: mst } = useAsync(() => fetch('/api/golemfm/status').then(r => r.json()), [tick]);
  const { data: presets } = useAsync(() => fetch('/api/presets').then(r => r.json()), [tick]);
  const list = (data && data.standards) || [];

  useEffect(() => { setTopAction(null); }, []);

  // ── DÉFILEMENT INFINI (2026-10-16 : « scroll infini, c'est ça la pagination ») ── 8 standards -> ~2 800 : la
  // liste entière, mais RENDUE par tranches de PAGE — une sentinelle en bas de la grille en ajoute une quand on
  // descend. 2 800 cartes d'un coup (et ~22 000 cases d'accords) étaient trop lourdes pour une tablette. La recherche
  // filtre, et repart de la première tranche.
  const usedBy = slug => (presets || []).filter(p => (p.standards || []).includes(slug));
  const pool = list.filter(keepFactory(facShow, 'standards'));
  const ql = q.toLowerCase();
  const matches = !q ? pool : pool.filter(s => (s.title + ' ' + (s.composer || '')).toLowerCase().includes(ql));
  const [limit, setLimit] = useState(PAGE);
  // une nouvelle recherche repart de la première tranche, liste remontée en haut (sinon la sentinelle, restée en vue
  // tout en bas, rechargeait tout d'un coup)
  useEffect(() => { setLimit(PAGE); const g = document.querySelector('.sta-grid'); if (g) g.scrollIntoView({ block: 'start' }); }, [q]);
  const shown = matches.slice(0, limit);
  const sentinel = useRef(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el || shown.length >= matches.length) return;
    const io = new IntersectionObserver(es => {
      if (es.some(e => e.isIntersecting)) setLimit(l => l + PAGE);
    }, { root: null, rootMargin: '400px' });   // l'écran : la grille n'est pas toujours ce qui défile (sa hauteur suit
                                              // son contenu) ; vue de l'écran, le conteneur qui coupe est pris en compte
    io.observe(el);
    return () => io.disconnect();
  }, [shown.length, matches.length]);

  // la grille complète (dans sa tonalité d'origine), demandée pour la seule carte OUVERTE ou jouée — la carte, elle,
  // n'a besoin de rien (son aperçu vient de la liste)
  const asked = useRef({});
  useEffect(() => {
    [open, live && live.playing ? live.standard : null].filter(Boolean).forEach(slug => {
      if (asked.current[slug]) return;
      asked.current[slug] = true;
      post('/api/standards/' + encodeURIComponent(slug) + '/preview', {})
        .then(r => !r.error && setCharts(c => ({ ...c, [slug]: r })));
    });
  }, [open, live && live.standard]);

  const playing = live && live.playing ? live.standard : null;
  useEffect(() => {
    const t = setInterval(() => fetch('/api/standards/state').then(r => r.json())
      .then(setLive).catch(() => {}), playing ? 600 : 3000);
    return () => clearInterval(t);
  }, [playing]);

  const sync = async () => {
    setBusy(true); setMsg(null);
    const r = await post('/api/standards/sync');
    setBusy(false);
    if (r.ok) {
      asked.current = {};
      // la synchro MET À JOUR ce que le rack a — elle n'ajoute ni ne retire (2026-10-08 : l'étoile est partie)
      setMsg((r.updated ? `${r.updated} updated` : 'all up to date')
        + (r.failed && r.failed.length ? ` · ${r.failed.length} failed` : ''));
    } else {
      setMsg(r.not_implemented ? "golem.fm doesn't serve standards yet"
                               : (r.error || 'sync failed'));
    }
    setTick(t => t + 1);
  };

  const remove = async slug => {
    if (armDel !== slug) { setArmDel(slug); setTimeout(() => setArmDel(a => a === slug ? null : a), 2500); return; }
    setArmDel(null);
    await fetch('/api/standards/synced/' + encodeURIComponent(slug), { method: 'DELETE' }).catch(() => {});
    setTick(t => t + 1);
  };

  const play = s => post('/api/standards/play', { standard: s.slug, motion: 'comp', loop: true });
  const stop = () => post('/api/standards/stop');

  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder=${pool.length > PAGE ? `Search ${pool.length} standards…` : 'Search…'}
        onInput=${e => setQ(e.target.value.trim())} />
      ${/* jamais appairé : ni ↻ Sync ni pastille — les grilles d'usine jouent sans golem.fm (audit 31/10) */''}
      ${mst && mst.paired ? html`<button class="mini edit-only" disabled=${busy} onClick=${sync}>${busy ? 'syncing…' : '↻ Sync'}</button>
      <span class=${cls('t3k-dot', mst.authed && 'on')} title=${mst.authed ? 'golem.fm online' : 'golem.fm offline'}></span>` : ''}
      ${msg ? html`<span class="muted std-msg">${esc(msg)}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [busy, msg, mst && mst.authed, mst && mst.paired, pool.length]);

  return html`<div class="bkg-page">
    <div class="sta-grid">
      ${shown.map(s => {
        const c = charts[s.slug];
        const on = playing === s.slug;
        const used = usedBy(s.slug);
        const isOpen = open === s.slug;
        // LA CARTE DE STANDARD DE golem.fm (2026-10-17) : l'aperçu d'accords à la place d'une pochette, le titre et le
        // compositeur ; en pied la tonalité, le style, la mesure, et la FORME à droite. Ce qui est au golem seul : le ▶
        // (le rack JOUE la grille), le tempo auquel il la joue, les presets liés. Toucher la carte ouvre la grille
        // complète ; la 🗑 y vit, pas sur la liste (on ne supprime pas d'un geste en passant).
        return html`<div class=${cls('sta-card', on && 'on', isOpen && 'open')} data-doc=${'standards.card:' + s.slug}
            onClick=${() => setOpen(isOpen ? null : s.slug)} title=${isOpen ? '' : 'open the full chart'}>
          <div class="sta-top">
            <div class="sta-artwrap">
              <${ChordShape} shape=${s.shape} />
              <button class="bkg-play edit-only" title=${on ? 'stop' : 'hear the rack play this grid'}
                onClick=${e => { e.stopPropagation(); on ? stop() : play(s); }}>${on ? '❚❚' : '▶'}</button>
            </div>
            <div class="sta-info">
              <b class="sta-title" title=${esc(s.title)}>${esc(s.title)}</b>
              <span class="sta-composer">${esc(s.composer || 'Unknown composer')}</span>
              ${used.length ? html`<span class="bkg-links" title="presets using this standard">⚡ ${used.map(p => esc(p.name)).join(', ')}</span>` : ''}
            </div>
          </div>
          <div class="sta-bottom">
            <span class="bkg-tag bkg-tag-key" title=${s.key_inferred ? 'inferred from the last chord — not in the source data' : 'key'}>
              ${esc(s.key || '?')}${s.key_inferred ? ' ?' : ''}</span>
            ${s.feel ? html`<span class="bkg-tag">${esc(feelLabel(s.feel))}</span>` : ''}
            <span class="bkg-chip">${esc(s.meter)}</span>
            <span class="bkg-chip">${s.tempo} bpm</span>
            ${s.seeded ? html`<span class="sta-seed" title="a sample standard, not from golem.fm — the next real sync replaces it">seed</span>` : ''}
            ${s.folder ? html`<span class="sta-seed" title=${s.folder}>📁 folder</span>` : ''}
            <span class="sta-form" title="form">${esc(s.form || '—')}</span>
          </div>
          ${isOpen ? html`<div class="sta-full" data-doc="standards.chart" onClick=${e => e.stopPropagation()}>
            <${Chart} bars=${c && c.bars} cur=${on ? live.bar : -1} />
            <div class="sta-full-act">
              ${s.folder
                // lu dans un DOSSIER DE CHANSONS (song-folders.md §2.3) : rien à retirer ici — on peut l'adopter
                ? html`<button class="mini" title="copy it into this golem — the folder copy is untouched"
                    onClick=${async () => { const r = await post('/api/song-folders/adopt', { path: s.folder }); setMsg(r.ok ? 'Added to this golem — the folder copy is untouched' : (r.why || r.error || 'refused')); setTick(t => t + 1); }}>Use on this golem</button>`
                : html`<button class=${cls('mini', 'bkg-del edit-only', armDel === s.slug && 'armed')}
                    title="remove from this golem" onClick=${() => remove(s.slug)}>
                    ${armDel === s.slug ? 'sure ?' : '🗑 Remove'}</button>`}
            </div>
          </div>` : ''}
        </div>`;
      })}
      ${shown.length < matches.length ? html`<div class="sta-sentinel" ref=${sentinel} aria-hidden="true"></div>` : ''}
      ${data && !shown.length ? html`<div class="empty sta-empty">
        ${q ? html`No match.` : html`
          <b>Nothing synced yet.</b>
          <p>This rack doesn't browse a catalogue — standards come from <b>golem.fm</b>: open one there and
          use <b>Send to your golem</b> (or keep its .golem in a song folder, Settings ▸ Content ▸ Storage). The rack
          plays the chord grid (piano and walking bass) while you play the head, and changing
          the key just works — that's what a grid does and a backing track never will.</p>
          `}
      </div>` : ''}
    </div>
  </div>`;
}

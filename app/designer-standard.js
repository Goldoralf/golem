// SPDX-License-Identifier: GPL-3.0-or-later
// Tiroir du bloc STANDARD (docs/standards.md) — le rack tient la section rythmique, tu joues
// le thème. Modelé sur le tiroir Backing Track : bande de cartes compactes + panneau de
// l'élément sélectionné, tout DANS le tiroir ouvert (pas de second modal — règle 
// 2026-07-20).
//
// ── CE QUI LE SÉPARE DU TIROIR BACKING ──────────────────────────────────────────────────
// Un backing arrive en STEMS : il faut les télécharger, ils pèsent, et le mix par stem est
// l'essentiel du réglage. Un standard arrive en DONNÉES : rien à télécharger au sens lourd,
// et l'essentiel du réglage c'est **comment on le joue** — tonalité, mouvement, qui joue.
//
// ── MISE EN PAGE v2 (2026-08-03, maquette mockups/standard-drawer.html) ─────────────────
// Le tiroir dispose de 980×422 MESURÉS. Trois bandes :
//   bande de standards   ── pleine largeur, 74 px, DÉFILE sans barre visible (Sync centré)
//   sélecteur de panneau ── Song · Piano · Bass · Drums | Grid, + le transport à droite
//   panneau              ── tout le reste
//
// ⚠ UN SEUL SÉLECTEUR, pas deux. « Grid » a été demandé comme un second bouton ; deux
// sélecteurs côte à côte se seraient concurrencés (lequel gagne quand les deux ont un état
// actif ?). C'est le même mécanisme — quel panneau s'affiche — donc un seul contrôle, avec
// un séparateur : à gauche des RÉGLAGES, à droite une VUE.
//
// La bande montre les standards synchronisés depuis golem.fm — et il n'y a rien d'autre à
// montrer : le rack ne connaît pas de catalogue (docs/standards.md, Addendum 3).
import { html, useState, useEffect, useAsync, useRef, cls, esc } from './lib.js';
import { Chart } from './page-standards.js';

const KEYS = ['Original', 'C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B',
  'Cm', 'C#m', 'Dm', 'Ebm', 'Em', 'Fm', 'F#m', 'Gm', 'G#m', 'Am', 'Bbm', 'Bm'];
const MOTIONS = [['comp', 'Comp'], ['block', 'Block'], ['arp', 'Arp'], ['arp+bass', 'Arp + bass']];
// du plus doux au plus rapide : la 1re chose qu'on essaie ne doit pas être la plus frénétique
const ARPS = ['Off', 'Up 1/4', 'Up 1/8', 'Down 1/8', 'Up-Down 1/8', 'Up 1/16', 'Up-Down 1/16', 'Up 2 oct'];
const FEELS = ['auto', 'swing', 'bossa', 'latin', 'samba', 'funk', 'ballad', 'even', 'waltz'];
// Le groove ÉCRIT reprend les mêmes noms que le feel : `auto` = il SUIT le feel du standard.
const WRITTEN = FEELS;

// ── clavier ──────────────────────────────────────────────────────────────────────────────
// « as-written » d'abord : la grille a raison par défaut, et un défaut qui invente des notes
// est un piège. Les autres ajoutent (ou retirent) au-dessus de ce qui est écrit.
const SIZES = [['as-written', 'As written'], ['triad', 'Triad'], ['7th', '7th'],
  ['9', '+9'], ['9-13', '+9 13'], ['alt', 'Altered']];
const STYLES = [['rootless', 'Rootless'], ['shell', 'Shell'], ['drop2', 'Drop 2'], ['full', 'Full']];
const REGISTERS = [['low', 'Low — G2…G4'], ['mid', 'Mid — G3…G5'], ['high', 'High — G4…G6']];
const DENSITIES = [['auto', 'Auto'], ['1', '1 — whole'], ['2', '2'],
  ['4', '4'], ['charleston', 'Charleston'], ['sparse', 'Sparse']];

// ── basse ────────────────────────────────────────────────────────────────────────────────
// Nommés par ce qu'ils JOUENT, pas par un jargon : « Root–5th » se comprend sans glossaire.
const BASS_MODES = [
  ['auto', 'Auto', 'follows the feel'], ['walk', 'Walking', '4 to the bar'],
  ['roots', 'Roots', '1 per chord'], ['two', 'Two-feel', '1 & 3'],
  ['root5', 'Root–5th', 'alternating'], ['pedal', 'Pedal', 'holds one note'],
  ['bossa', 'Bossa', '1 · 3+']];
const APPROACHES = [['chromatic', 'Chromatic'], ['diatonic', 'Diatonic'], ['none', 'None']];
const OCTS = [[-1, '−1'], [0, '0'], [1, '+1']];

// ── batterie ─────────────────────────────────────────────────────────────────────────────
// Un plugin = un kit acoustique complet (avldrums). La boîte à rythmes garde les kits RS5k,
// DrumGizmo multi-micros et SFZ : un standard n'a besoin ni de micros séparés ni de songs.
const KITS = [['black-pearl', 'Black Pearl'], ['red-zeppelin', 'Red Zeppelin'], ['blonde-bop', 'Blonde Bop']];
const FILLS = [['off', 'Off'], ['8', '8 bars'], ['section', 'Section'], ['chorus', 'Chorus']];

const TABS = [['song', 'Song'], ['piano', 'Piano'], ['bass', 'Bass'], ['drums', 'Drums'], ['guitar', 'Guitar']];
// LA FORMATION (refonte du tiroir, 2026-10-17, maquette validée) : une rangée remplace les trois boutons « Parts ».
// Manouche = la pompe + la contrebasse, sans piano ni batterie (docs/standards.md §10).
const LINEUPS = [['combo', 'Combo', 'piano · bass · drums'], ['manouche', 'Manouche', 'pompe · bass'],
                 ['custom', 'Custom', 'pick the parts']];
const LINEUP_PARTS = { combo: { keys: true, bass: true, drums: true, guitar: false },
                       manouche: { keys: false, bass: true, drums: false, guitar: true } };
const lineupOf = p => {
  const on = { keys: p.keys !== false, bass: p.bass !== false, drums: !!p.drums, guitar: !!p.guitar };
  return Object.keys(LINEUP_PARTS).find(k => Object.entries(LINEUP_PARTS[k]).every(([n, v]) => on[n] === v)) || 'custom';
};
// un standard manouche choisi -> la formation manouche d'office (le style vient de la grille)
const isGypsy = s => /manouche|gypsy/i.test((s && (s.rhythm || s.style)) || '');
// la pompe : le style par défaut suit la métrique, le feel et le tempo du preset (bridge/standards.pompe_style)
const POMPES = [['auto', 'Auto', 'from the tune'], ['pompe', 'Pompe', 'the classic 4'],
  ['pompe-fast', 'Fast', '2 and 4 only'], ['ballad', 'Ballad', 'longer, softer'],
  ['valse', 'Valse', 'the gypsy waltz'], ['bolero', 'Bolero', '1 · 2-and · 3 · 4'],
  ['rumba', 'Rumba', '3-3-2'], ['bossa', 'Bossa', 'two-bar figure']];
const COUNTIN = ['Off', '1 bar', '2 bars'];
const cap1 = s => (s || '').charAt(0).toUpperCase() + (s || '').slice(1);
// l'aperçu d'accords d'une grille (la carte de golem.fm, Library ▸ Standards) : une barre par mesure
const Shape = ({ shape, big }) => html`<span class=${cls('std-shape', big && 'big')} aria-hidden="true">${(shape || [])
  .map(n => html`<i style=${'height:' + Math.min(100, 26 + 18 * n) + '%'}></i>`)}</span>`;
const PICK_PAGE = 30;

// « Change… » : le sélecteur des standards — recherche, styles, défilement infini (la grammaire de Library ▸ Standards).
// Remplace le carrousel horizontal de 2 800 cartes sans recherche (le standard choisi n'y était même pas visible).
function StandardPicker({ list, current, used, onPick, onClose }) {
  const [q, setQ] = useState('');
  const [style, setStyle] = useState('all');
  const [limit, setLimit] = useState(PICK_PAGE);
  const styles = Object.entries(list.reduce((m, s) => { m[s.rhythm] = (m[s.rhythm] || 0) + 1; return m; }, {}))
    .sort((a, b) => b[1] - a[1]).slice(0, 6);
  const ql = q.trim().toLowerCase();
  const pool = list.filter(s => (style === 'all' || (style === 'used' ? used.includes(s.slug) : s.rhythm === style))
    && (!ql || (s.title + ' ' + (s.composer || '')).toLowerCase().includes(ql)));
  const shown = pool.slice(0, limit);
  const sentinel = useRef(null);
  useEffect(() => { setLimit(PICK_PAGE); }, [q, style]);
  useEffect(() => {
    const el = sentinel.current;
    if (!el || shown.length >= pool.length) return;
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) setLimit(l => l + PICK_PAGE); },
      { root: null, rootMargin: '300px' });
    io.observe(el);
    return () => io.disconnect();
  }, [shown.length, pool.length]);
  return html`<div class="std-pk-scrim" onClick=${onClose}>
    <div class="std-pk" onClick=${e => e.stopPropagation()}>
      <div class="std-pk-hd"><b>Pick a standard</b>
        <input class="search" type="search" autofocus placeholder=${`Search ${list.length} standards — title or composer…`}
          value=${q} onInput=${e => setQ(e.target.value)} />
        <button class="mini" onClick=${onClose} aria-label="close">✕</button></div>
      <div class="std-pk-styles">
        <button class=${cls('std-chip', style === 'all' && 'on')} onClick=${() => setStyle('all')}>All <small>${list.length}</small></button>
        ${styles.map(([k, n]) => html`<button class=${cls('std-chip', style === k && 'on')} onClick=${() => setStyle(k)}>${cap1(k)} <small>${n}</small></button>`)}
        ${used.length ? html`<button class=${cls('std-chip', style === 'used' && 'on')} onClick=${() => setStyle('used')}>Used here <small>${used.length}</small></button>` : ''}
      </div>
      <div class="std-pk-grid">
        ${shown.map(s => html`<button class=${cls('std-pk-card', s.slug === current && 'cur')} onClick=${() => onPick(s.slug)}>
          <${Shape} shape=${s.shape} /><span class="std-pk-tx"><b>${esc(s.title)}</b>
          <small>${esc(s.composer || '—')} · ${esc(s.key || '?')} · ${Math.round(s.tempo)} bpm · ${esc(s.rhythm)}</small></span></button>`)}
        ${shown.length < pool.length ? html`<span class="std-pk-sent" ref=${sentinel}></span>` : ''}
        ${!pool.length ? html`<p class="muted std-nosync">No standard matches.</p>` : ''}
      </div>
    </div>
  </div>`;
}
const cap = s => (s || '').replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const famLabel = f => f.split('/').map(cap).join(' · ');

const post = (url, body) => fetch(url, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body || {}),
}).then(r => r.json()).catch(e => ({ error: String(e) }));

// Les réglages de jeu envoyés au moteur. UNE liste, partagée par l'aperçu et l'audition :
// deux listes divergent toujours, et le jour où elles divergent l'aperçu ment.
const playOf = p => ({
  size: p.size || 'as-written', style: p.style || 'rootless', register: p.register || 'mid',
  density: p.density || 'auto', anticip: p.anticip !== false, move: p.move !== false,
  passing: !!p.passing, approach: p.approach || 'chromatic', bass_oct: p.bass_oct || 0,
  ghost: !!p.ghost, land: !!p.land, fill: p.fill || 'off', pompe: p.pompe || 'auto',
});
const partsOf = p => ({ keys: p.keys !== false, bass: p.bass !== false, drums: !!p.drums, guitar: !!p.guitar });

// ── l'aperçu piano-roll ─────────────────────────────────────────────────────────────────
// Dire ce que le réglage FAIT, pas seulement son nom. Sans ce dessin, « Charleston » et
// « Drop 2 » sont deux étiquettes qu'il faut lancer pour comprendre.
function Roll({ roll, lane }) {
  const ns = ((roll && roll.notes) || []).filter(n => n.l === lane);
  if (!ns.length) return html`<div class="std-roll"><span class="std-rcap">no notes here</span></div>`;
  const beats = ((roll.beats || 4) * (roll.bars || 2)) || 8;
  const lo = Math.min(...ns.map(n => n.n)), hi = Math.max(...ns.map(n => n.n));
  const span = Math.max(6, hi - lo);
  return html`<div class="std-roll">
    ${Array.from({ length: beats }, (_, i) => html`<span
      class=${cls('std-rbeat', i % (roll.beats || 4) === 0 && 'b1')}
      style=${`left:${(i / beats) * 100}%`}></span>`)}
    ${ns.map(n => html`<i class=${cls('std-rnote', lane === 1 && 'b', lane === 4 && 'g')} style=${
      `left:${(n.b / beats) * 100}%;width:${Math.max(2.2, 92 / beats)}%;`
      + `bottom:${6 + ((n.n - lo) / span) * 56}px;opacity:${0.35 + (n.v / 127) * 0.6}`}></i>`)}
  </div>`;
}

export function StandardSheet({ params, onParam, bpm, onBpm, onHead }) {
  const p = params || {};
  const slug = p.standard || null;
  const [tab, setTab] = useState('song');
  const [chart, setChart] = useState(null);
  const [live, setLive] = useState(null);
  const [open, setOpen] = useState(null);       // style ouvert dans l'arbre des grooves
  const [hear, setHear] = useState(null);       // prise en cours d'écoute (▶ d'une ligne)

  // ce que le rack possède — c'est-à-dire ce que golem.fm lui a synchronisé
  const { data: synced } = useAsync(
    () => fetch('/api/standards?limit=0').then(r => r.json()), []);   // ENTIÈRE : la route coupe à 200
  const { data: presetList } = useAsync(() => fetch('/api/presets').then(r => r.json()).catch(() => []), []);
  const [picking, setPicking] = useState(false);
  // les grooves JOUÉS que le rack possède. Vide si aucun pack : le groupe « Played »
  // disparaît alors, plutôt que d'offrir un choix qui ne jouerait rien.
  const { data: tree } = useAsync(
    () => fetch('/api/standards/grooves/tree').then(r => r.json()), []);
  const packs = (tree && tree.packs) || [];

  const playing = live && live.playing;
  useEffect(() => {
    const t = setInterval(() => fetch('/api/standards/state').then(r => r.json())
      .then(setLive).catch(() => {}), playing ? 600 : 3000);
    return () => clearInterval(t);
  }, [playing]);

  const play = playOf(p);
  const playSig = JSON.stringify(play);
  // aperçu : la grille TRANSPOSÉE telle que le rack la jouera, sans rien lancer
  useEffect(() => {
    if (!slug) { setChart(null); return; }
    let alive = true;
    post('/api/standards/' + encodeURIComponent(slug) + '/preview', {
      key: p.key && p.key !== 'Original' ? p.key : null,
      feel: p.feel && p.feel !== 'auto' ? p.feel : null,
      // UN chorus : la grille montre la FORME (×N est dit à côté) — quatre chorus déroulés faisaient 128 mesures
      motion: p.motion || 'comp', choruses: 1,
      voicing: (p.style || 'rootless') === 'full' ? 'full' : 'rootless',
      bass_mode: p.bass_mode || 'auto', groove: p.groove || 'auto',
      groove_take: p.groove_take || null, bpm, play, parts: partsOf(p),
    }).then(r => alive && !r.error && setChart(r));
    return () => { alive = false; };
  }, [slug, p.key, p.feel, p.motion, p.bass_mode, p.groove, p.groove_take,
      bpm, playSig, JSON.stringify(partsOf(p))]);

  const audition = () => { setHear(null); return post('/api/standards/play', {
    standard: slug, key: p.key && p.key !== 'Original' ? p.key : null,
    feel: p.feel && p.feel !== 'auto' ? p.feel : null,
    motion: p.motion || 'comp', arp: p.arp || 'Off', choruses: p.choruses || 1,
    count_in: p.count_in || 0,
    voicing: (p.style || 'rootless') === 'full' ? 'full' : 'rootless',
    bass_mode: p.bass_mode || 'auto', groove: p.groove || 'auto',
    groove_take: p.groove_take || null,
    kit: p.kit || 'black-pearl', bpm, play,
    parts: partsOf(p), loop: true,
  }); };
  const stop = () => { setHear(null); return post('/api/standards/stop'); };
  // le ▶ d'une ligne : on écoute la prise SANS toucher au réglage du bloc
  const hearTake = (fam, take, isFill) => {
    setHear(`${fam}#${take.bpm}${isFill ? 'f' : ''}`);
    post('/api/standards/grooves/audition', {
      family: fam, bpm: take.bpm, meter: take.meter, bars: isFill ? 1 : 2,
      kit: p.kit || 'black-pearl', fill: !!isFill });
  };

  // la métrique sur laquelle le moteur filtre les prises (dite par l'aperçu, pas devinée)
  const gm = (chart && chart.groove_meter) || null;
  const list = (synced && synced.standards) || [];
  const cur = chart || null;
  const isArp = (p.motion || 'comp').startsWith('arp');
  const sel = list.find(s => s.slug === slug)
    || (cur ? { slug, title: cur.title, key: cur.key } : null);
  const usedHere = [...new Set((presetList || []).flatMap(x => x.standards || []))];
  const form = (cur && cur.bars && cur.bars.length) || 0;
  const curBar = playing && typeof live.bar === 'number' && live.bar >= 0 && form ? live.bar % form : -1;
  const lineup = lineupOf(p);
  const setLineup = v => { if (LINEUP_PARTS[v]) Object.entries(LINEUP_PARTS[v]).forEach(([n, x]) => onParam(n, x));
    else if (v === 'custom' && lineupOf(p) === 'combo') onParam('drums', false); };
  const step = (lb, v, txt, dec, inc) => html`<div class="std-f">${lb}
    <div class="std-step"><button onClick=${dec} aria-label="less">−</button><b>${txt}</b>
      <button onClick=${inc} aria-label="more">+</button></div></div>`;

  // la famille choisie, retrouvée dans l'arbre — c'est elle qui porte tempos, métrique, fills
  let famNode = null;
  packs.forEach(pk => pk.styles.forEach(st => st.kits.forEach(k => {
    if (k.family === p.groove) famNode = { ...k, pack: pk.pack, style: st.style };
  })));
  // ── QUELLE PRISE JOUE ? ────────────────────────────────────────────────────────────
  // `autoTake` = celle que le rack déduit du tempo, faute de mieux. `p.groove_take` = celle
  // que l'utilisateur a DÉSIGNÉE (son tempo l'identifie, un fichier par tempo). Deux prises
  // d'une même famille ne se ressemblent pas — densité, ghost notes, ride — donc écouter au ▶
  // sans pouvoir garder ce qu'on aime n'avait pas de sens.
  // ⚠ On revalide le choix contre la famille COURANTE : un `groove_take` hérité d'une autre
  // famille (ou d'un pack réimporté) doit s'effacer à l'écran, pas afficher un tempo fantôme
  // — le moteur, lui, retombe déjà sur le choix au tempo.
  // ⚠ TOUT SE CALCULE SUR LES PRISES JOUABLES. Le moteur filtre sur la métrique du morceau
  // (`gm`) ; une prise d'une autre métrique ne sortira jamais. Badger « AUTO » ou « PICKED »
  // sur une de celles-là, c'est promettre un groove qu'on n'entendra pas — et c'est ce que
  // faisait l'écran : « Take Five » est en 5/4, aucun pack n'a de prise en 5/4, et une ligne
  // s'affichait quand même comme choisie.
  const usable = famNode ? famNode.takes.filter(t => !gm || !t.meter || t.meter === gm) : [];
  const autoTake = usable.length ? usable.reduce(
    (a, b) => (Math.abs(b.bpm - (bpm || 120)) < Math.abs(a.bpm - (bpm || 120)) ? b : a), usable[0]) : null;
  const chosen = p.groove_take ? usable.find(t => t.bpm === p.groove_take) || null : null;
  const pickedTempo = chosen || autoTake;          // la prise EFFECTIVE (écoute d'un fill, résumé)
  // changer de famille NE DOIT PAS traîner la prise de l'ancienne : on choisit les deux d'un coup
  const setGroove = (fam) => { onParam('groove', fam); onParam('groove_take', null); };

  const fld = (lb, v, opts, on, dis) => html`<label class=${cls('std-f', dis && 'off')}>${lb}
    <select value=${v} disabled=${dis} onChange=${e => on(e.target.value)}>
      ${opts.map(o => { const [ov, ol] = Array.isArray(o) ? o : [o, o];
        return html`<option value=${ov} selected=${String(ov) === String(v)}>${ol}</option>`; })}
    </select></label>`;
  const chips = (lb, v, opts, on, hint) => html`<div class="std-f">${lb}
    <div class="std-chips">${opts.map(o => { const [ov, ol] = Array.isArray(o) ? o : [o, o];
      return html`<button class=${cls('std-chip', String(ov) === String(v) && 'on')}
        onClick=${() => on(ov)}>${ol}</button>`; })}</div>
    ${hint ? html`<span class="std-hint">${hint}</span>` : ''}</div>`;
  const tog = (lb, v, on, hint) => html`<button class=${cls('std-chip', v && 'on')}
    onClick=${() => on(!v)} title=${hint || ''}>${lb}</button>`;

  // la mesure courante suit la lecture : la grille affiche 8-9 lignes, un chorus long en fait
  // plus — sans ça on regarde une grille figée pendant que le rack joue ailleurs.
  const viewRef = useRef(null);
  useEffect(() => {
    const el = viewRef.current && viewRef.current.querySelector('.std-bar.on');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }, [playing, live && live.bar]);
  // Même règle pour l'arbre des grooves : la famille choisie doit être VISIBLE. Sans ça
  // « Jazz » restait sous le pli alors que c'était la sélection — l'arbre montrait Blues.
  const treeRef = useRef(null);
  useEffect(() => {
    const el = treeRef.current && treeRef.current.querySelector('.std-tr.on');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }, [tab, p.groove, packs.length]);

  // « Change… » / « Audition » vivent dans la rangée ⏻ du tiroir (designer-sheets, onHead) : on lui passe
  // des boutons qui appellent la version COURANTE des actions (ref), pour ne pas figer les réglages d'avant
  const act = useRef({});
  act.current = { audition, stop, pick: () => setPicking(true) };
  useEffect(() => {
    if (!onHead) return undefined;
    onHead(html`${hear ? html`<span class="std-barn">auditioning a take</span>` : ''}
      <button class="mini std-change" onClick=${() => act.current.pick()}>${slug ? 'Change…' : 'Pick a standard…'}</button>
      ${slug ? (playing ? html`<button class="mini std-play on" onClick=${() => act.current.stop()}>■ Stop</button>`
                        : html`<button class="mini std-play" onClick=${() => act.current.audition()}>▶ Audition</button>`) : ''}`);
    return undefined;
  }, [slug, !!playing, !!hear]);
  useEffect(() => () => onHead && onHead(null), []);

  return html`<div class="std-sheet">
    ${/* 1. LE STANDARD CHOISI, EN GRAND (refonte 2026-10-17) — le compositeur suit le titre, et les onglets
          montent à droite : une ligne gagnée. « Change… » et « Audition » sont dans la rangée ⏻ (onHead). */ ''}
    <div class="std-head">
      ${slug && sel ? html`<${Shape} shape=${sel.shape} big=${true} />
        <div class="std-head-t"><div class="std-head-l1"><b>${esc(sel.title || slug)}</b>
            <span class="muted">${esc(sel.composer || '')}</span></div>
          <div class="std-head-tags">
            <span class="bkg-tag bkg-tag-key">${esc((cur && cur.key) || sel.key || '?')}</span>
            ${(cur && cur.feel) || sel.feel ? html`<span class="bkg-tag">${esc(cap1((cur && cur.feel) || sel.feel))}</span>` : ''}
            ${sel.tempo ? html`<span class="bkg-chip">${Math.round(sel.tempo)} bpm</span>` : ''}
            <span class="std-head-form">${esc(sel.form || '')}${form ? ' · ' + form + ' bars' : ''}</span>
            ${cur && cur.key_inferred ? html`<span class="std-warn" title="Not in the source data — inferred from the last chord of the form.">key inferred</span>` : ''}
          </div></div>`
        : html`<div class="std-head-t muted">No standard yet — pick one.</div>`}
      <span class="grow"></span>
      ${slug ? html`<div class="std-head-r">
        <div class="std-seg">
          ${TABS.map(([id, lb]) => {
            const off = (id === 'piano' && p.keys === false) || (id === 'bass' && p.bass === false)
              || (id === 'drums' && !p.drums) || (id === 'guitar' && !p.guitar);
            return html`<button class=${cls('std-tab', tab === id && 'on', off && 'mute')}
              onClick=${() => setTab(id)}>${lb}${id !== 'song'
                ? html`<span class=${cls('std-dot', !off && 'lit')}></span>` : ''}</button>`;
          })}
        </div>
        ${tab === 'drums' || curBar >= 0 ? html`<div class="std-head-r2">
          ${tab === 'drums' ? html`<span class="std-lbl2">Kit</span>
            <div class="std-chips">${KITS.map(([v, l]) => html`<button
              class=${cls('std-chip', (p.kit || 'black-pearl') === v && 'on')}
              onClick=${() => onParam('kit', v)}>${l}</button>`)}</div>` : ''}
          ${curBar >= 0 ? html`<span class="std-barn">bar ${curBar + 1} / ${form}</span>` : ''}
        </div>` : ''}
      </div>` : ''}
    </div>
    ${picking ? html`<${StandardPicker} list=${list} current=${slug} used=${usedHere}
      onPick=${v => { onParam('standard', v); if (isGypsy(list.find(s => s.slug === v))) setLineup('manouche');
        setPicking(false); }} onClose=${() => setPicking(false)} />` : ''}
    ${!list.length && synced ? html`<p class="muted std-nosync">No standards on this golem yet — they come from
      <b>golem.fm</b> (Send to your golem) or a song folder.</p>` : ''}

    ${!slug ? html`<p class="muted std-blank">Pick a standard — the rack plays piano and walking bass,
      you play the head. Change the key and it just works: that's what a grid does and a
      backing track never will.</p>` : html`

      ${/* 3. le panneau */ ''}
      <div class="std-panel">
        ${tab === 'song' ? html`
          <div class="std-col std-col-set">
            ${/* LA FORMATION remplace les trois boutons « Parts » : Combo = les trois ; Custom les montre */ ''}
            <div class="std-f">Line-up
              <div class="std-lineup">${LINEUPS.map(([v, l, h]) => html`<button
                class=${cls('std-chip', 'std-chip-2', lineup === v && 'on')}
                onClick=${() => setLineup(v)}>${l}<span class="std-hint">${h}</span></button>`)}</div>
              ${lineup === 'custom' ? html`<div class="std-chips">
                <button class=${cls('std-chip', p.keys !== false && 'on')} onClick=${() => onParam('keys', p.keys === false)}>Piano</button>
                <button class=${cls('std-chip', p.bass !== false && 'on')} onClick=${() => onParam('bass', p.bass === false)}>Bass</button>
                <button class=${cls('std-chip', p.drums && 'on')} onClick=${() => onParam('drums', !p.drums)}>Drums</button>
                <button class=${cls('std-chip', p.guitar && 'on')} onClick=${() => onParam('guitar', !p.guitar)}>Guitar</button>
              </div>` : ''}</div>
            <div class="std-g2">
              ${fld('Key', p.key || 'Original', KEYS.map(k => [k, k === 'Original'
                ? 'Original (' + ((sel && sel.key) || (cur && cur.key) || '?') + ')' : k]),
                v => onParam('key', v))}
              ${fld('Feel', p.feel || 'auto', FEELS.map(f => [f, cap1(f)]), v => onParam('feel', v))}
              ${step('Choruses', p.choruses || 1, String(p.choruses || 1),
                () => onParam('choruses', Math.max(1, (p.choruses || 1) - 1)), () => onParam('choruses', Math.min(16, (p.choruses || 1) + 1)))}
              ${step('Count-in', p.count_in || 0, COUNTIN[p.count_in || 0],
                () => onParam('count_in', Math.max(0, (p.count_in || 0) - 1)), () => onParam('count_in', Math.min(2, (p.count_in || 0) + 1)))}
            </div>
            ${/* Le bloc NE PORTE PAS de tempo : preset.bpm est la seule vérité (contrat §2). Il PROPOSE celui du standard. */ ''}
            ${cur && onBpm && cur.tempo && cur.tempo !== bpm ? html`<div class="std-tempo">
              Usually <b>${cur.tempo} bpm</b> · plays at <b>${bpm}</b><span class="grow"></span>
              <button class="mini" onClick=${() => onBpm(cur.tempo)}>Use ${cur.tempo}</button></div>`
              : html`<div class="std-tempo muted">Tempo follows the preset — ${bpm} bpm</div>`}
          </div>
          <div class="std-col std-view" ref=${viewRef}>
            <div class="std-panel-top">
              <b>One chorus</b>
              <span class="muted">× ${p.choruses || 1}${cur && cur.semis ? ' · transposed ' + (cur.semis > 0 ? '+' : '') + cur.semis + ' st' : ''} · the form, the solos and the ending belong to Arrangement</span>
              ${cur && cur.unknown && cur.unknown.length ? html`<span class="std-warn">unreadable: ${cur.unknown.join(' ')}</span>` : ''}
            </div>
            <${Chart} bars=${cur && cur.bars} cur=${curBar} />
          </div>` : ''}

        ${tab === 'piano' ? html`
          <div class="std-col" style="flex:1">
            ${chips('Chord size — what gets added on top', p.size || 'as-written', SIZES,
              v => onParam('size', v))}
            ${chips('Voicing', p.style || 'rootless', STYLES, v => onParam('style', v),
              'Rootless leaves the bottom to the bass — two players, not one doubling the other.')}
            ${chips('How the chord is played', p.motion || 'comp', MOTIONS, v => onParam('motion', v))}
            <div class="std-g2">
              ${fld('Arpeggiator', p.arp || 'Off', ARPS, v => onParam('arp', v), !isArp)}
              ${fld('Register', p.register || 'mid', REGISTERS, v => onParam('register', v))}
            </div>
          </div>
          <div class="std-col" style="width:404px;flex:none">
            ${chips('Hits per bar', p.density || 'auto', DENSITIES, v => onParam('density', v),
              'Auto follows the feel of the grid. The rest force a density whatever the style.')}
            <div class="std-f">Feel details
              <div class="std-chips">
                ${tog('Anticipations', p.anticip !== false, v => onParam('anticip', v),
                  'The next chord lands half a beat early, across the bar line.')}
                ${tog('Voicing moves', p.move !== false, v => onParam('move', v),
                  'A held chord gets re-voiced instead of repeating identically.')}
                ${tog('Passing chords', !!p.passing, v => onParam('passing', v),
                  'A dominant a half-step above the next chord, on the last beat.')}
              </div>
              <span class="std-hint">Anticipations push the next chord half a beat early — the thing that stops it sounding typed in.</span></div>
            <div class="std-f std-rlbl">Two bars, as it will play</div>
            <${Roll} roll=${cur && cur.roll} lane=${0} />
          </div>` : ''}

        ${tab === 'bass' ? html`
          <div class="std-col" style="flex:1">
            <div class="std-f">Pattern
              <div class="std-g3">${BASS_MODES.map(([v, l, h]) => html`<button
                class=${cls('std-chip', 'std-chip-2', (p.bass_mode || 'auto') === v && 'on')}
                onClick=${() => onParam('bass_mode', v)}>${l}<span class="std-hint">${h}</span></button>`)}</div>
              <span class="std-hint">Auto follows the grid's feel — a bossa gets the bossa figure without asking.</span></div>
            <div class="std-g3">
              ${fld('Approach notes', p.approach || 'chromatic', APPROACHES, v => onParam('approach', v))}
              ${fld('Octave', p.bass_oct || 0, OCTS, v => onParam('bass_oct', +v))}
            </div>
          </div>
          <div class="std-col" style="width:404px;flex:none">
            <div class="std-f">Detail
              <div class="std-chips">
                ${tog('Ghost notes', !!p.ghost, v => onParam('ghost', v),
                  'A soft note between the beats — the push of a real bass player.')}
                ${tog('Land on the root at each section', !!p.land, v => onParam('land', v),
                  'The line re-anchors low when a new section starts.')}
              </div></div>
            <div class="std-f std-rlbl">Two bars, as it will play
              <span class="std-hint2">faded = ghost / approach</span></div>
            <${Roll} roll=${cur && cur.roll} lane=${1} />
          </div>` : ''}

        ${tab === 'guitar' ? html`
          <div class="std-col" style="flex:1">
            <div class="std-f">Style
              <div class="std-g4">${POMPES.map(([v, l, h]) => html`<button
                class=${cls('std-chip', 'std-chip-2', (p.pompe || 'auto') === v && 'on')}
                onClick=${() => onParam('pompe', v)}>${l}<span class="std-hint">${h}</span></button>`)}</div>
              <span class="std-hint">The gypsy rhythm guitar: short strokes on 1 and 3, accented on 2 and 4.
                Auto plays a valse in 3/4, a bossa or rumba on latin feels, and only 2 and 4 above 230 bpm.</span></div>
            ${!p.guitar ? html`<span class="std-hint">The guitar is off — pick <b>Manouche</b> in Song, or add it in Custom.</span>` : ''}
          </div>
          <div class="std-col" style="width:404px;flex:none">
            <div class="std-f std-rlbl">Two bars, as it will play</div>
            <${Roll} roll=${cur && cur.roll} lane=${4} />
            <span class="std-hint">Rhythm guitar only — the lead is yours.</span>
          </div>` : ''}

        ${tab === 'drums' ? html`
          <div class="std-col std-drums">
            <div class="std-browse">
              ${/* 30 % à gauche : l'arbre. Les motifs ÉCRITS y sont une racine comme les
                    autres — sinon « auto » n'aurait pas de place et resterait un cas à part. */ ''}
              <div class="std-tree" ref=${treeRef}>
                ${/* Replié par défaut : déplié, les 9 motifs écrits occupaient tout l'arbre
                      et repoussaient les packs hors du champ — mesuré à l'écran. */ ''}
                <div class="std-tr pack"><span class="std-sw" style="background:#5d6673"></span>Written<span class="std-n">${WRITTEN.length}</span></div>
                ${open === 'written' || WRITTEN.includes(p.groove || 'auto')
                  ? WRITTEN.map(g => html`<button class=${cls('std-tr', 'sub', (p.groove || 'auto') === g && 'on')}
                      onClick=${() => setGroove(g)}>${g}</button>`)
                  : html`<button class="std-tr sub" onClick=${() => setOpen('written')}>
                      swing · bossa · latin…</button>`}
                ${packs.map(pk => html`
                  <div class="std-tr pack"><span class="std-sw" style=${`background:var(--${pk.pack === 'jazz' ? 'jazz' : 'blues'})`}></span>${cap(pk.pack)}<span class="std-n">${pk.takes}</span></div>
                  ${pk.styles.map(st => {
                    const fam0 = st.kits[0];
                    const mine = st.kits.some(k => k.family === p.groove);
                    const key = pk.pack + '/' + st.style;
                    // ⚠ DIRE ICI ce qui peut jouer. Le moteur filtre sur la métrique du morceau :
                    // un style dont AUCUNE prise n'est dans cette métrique ne sortira jamais un
                    // son. On pouvait le choisir sans le moindre signe, et la batterie restait
                    // muette — « Take Five » est en 5/4, `Walk Brushes` en 4/4, et rien ne le
                    // disait (vécu, 2026-08-07). La métrique s'affiche donc dès qu'elle DIFFÈRE
                    // de celle du morceau, au lieu de « tout sauf 4/4 » qui ne voulait rien dire
                    // sous une valse.
                    const fits = !gm || st.kits.some(k => (k.takes || []).some(
                      t => !t.meter || t.meter === gm));
                    const mt = [...new Set(st.kits.flatMap(k => (k.takes || []).map(t => t.meter)))]
                      .filter(Boolean);
                    return html`<button class=${cls('std-tr', 'sub', mine && 'on', !fits && 'off')}
                      title=${fits ? '' : `${mt.join(' · ')} — this tune is in ${gm}`}
                      onClick=${() => { setOpen(key); if (!mine) setGroove(fam0.family); }}>
                      ${cap(st.style)}${(gm ? !fits : fam0.meter !== '4/4')
                        ? html` <span class="std-mt">${mt.join('·') || fam0.meter}</span>` : ''}
                      <span class="std-n">${st.kits.reduce((a, k) => a + k.takes.length, 0)}</span></button>`;
                  })}`)}
              </div>
              ${/* 70 % à droite : les prises. Un ▶ par ligne — comparer deux grooves ne doit
                    pas obliger à changer le réglage puis à le remettre. */ ''}
              <div class="std-takes">
                ${famNode ? html`
                  <div class="std-takes-top">
                    ${(packs.find(x => x.pack === famNode.pack).styles
                        .find(x => x.style === famNode.style).kits).map(k => html`<button
                      class=${cls('std-chip', k.family === p.groove && 'on')}
                      onClick=${() => setGroove(k.family)}>${cap(k.kit || 'default')}</button>`)}
                    <span class="grow"></span>
                    ${/* Le retour à l'automatique doit être une CIBLE, pas une devinette : sans
                          lui, on ne pourrait plus jamais rendre la main au tempo une fois qu'on
                          a choisi. Il s'allume quand aucune prise n'est désignée. */ ''}
                    <button class=${cls('std-chip', !chosen && 'on')} title=${
                      'let the tempo choose — currently ' + (autoTake ? autoTake.bpm + ' bpm' : '—')}
                      onClick=${() => onParam('groove_take', null)}>Auto</button>
                    ${usable.length
                      ? html`<span class="std-hint">${usable.length}/${famNode.takes.length} takes playable</span>`
                      : html`<span class="std-warn2">⚠ none of them is in ${gm} — this family cannot play under this tune</span>`}
                  </div>
                  <div class="std-th"><span>#</span><span>Density</span><span>Tempo</span><span>Bars</span><span>Hits</span><span>Meter</span><span></span></div>
                  <div class="std-takes-scroll">
                    ${famNode.takes.map((t, i) => {
                      const mx = Math.max(...famNode.takes.map(x => x.hits)) || 1;
                      const isMine = chosen && t.bpm === chosen.bpm;      // DÉSIGNÉE par l'utilisateur
                      const isAuto = !chosen && autoTake && t.bpm === autoTake.bpm;  // déduite du tempo
                      // ⚠ Une prise d'une AUTRE métrique ne jouera pas : le moteur filtre
                      // dessus (un 6/8 sous un morceau en 4/4 est faux) et retomberait sur le
                      // choix au tempo. La proposer serait un clic qui « marche » sans rien
                      // changer — on la montre, grisée, en disant pourquoi.
                      const off = gm && t.meter && t.meter !== gm;
                      // La ligne ENTIÈRE choisit. Le ▶ garde son rôle — écouter sans rien
                      // changer — donc il stoppe la propagation : comparer deux prises ne doit
                      // pas modifier le réglage, c'est la raison d'être du navigateur.
                      return html`<div class=${cls('std-tk', (isMine || isAuto) && 'on', isMine && 'mine', off && 'off')}
                        role="button" tabindex=${off ? -1 : 0} aria-disabled=${off ? 'true' : 'false'}
                        title=${off ? `${t.meter} — this tune is in ${gm}, it would not play`
                                    : isMine ? 'this take is set — Auto gives the choice back to the tempo'
                                             : 'use this take'}
                        onClick=${() => !off && onParam('groove_take', t.bpm)}
                        onKeyDown=${e => { if (!off && (e.key === 'Enter' || e.key === ' ')) {
                          e.preventDefault(); onParam('groove_take', t.bpm); } }}>
                        <span class="std-no">${String(i + 1).padStart(2, '0')}</span>
                        <span class="std-dens" style=${`width:${Math.round((t.hits / mx) * 100)}%`}></span>
                        <span class="std-tp">${t.bpm} bpm${
                          isMine ? html`<b class="std-pk">PICKED</b>`
                          : isAuto ? html`<b class="std-pk auto">AUTO</b>` : ''}</span>
                        <span>${t.bars}</span><span>${t.hits}</span><span>${t.meter}</span>
                        <button class=${cls('std-pl', hear === `${famNode.family}#${t.bpm}` && 'on')}
                          title="hear it — changes nothing"
                          onClick=${e => { e.stopPropagation(); hearTake(famNode.family, t, false); }}>▶</button>
                      </div>`;
                    })}
                  </div>
                  <span class="std-takes-fade"></span>`
                : html`<p class="muted std-nosync">A written pattern is selected — it follows the
                    feel and needs no pack. Pick a family on the left to hear a real drummer.</p>`}
              </div>
            </div>
            ${/* les fills : ils ne viennent QUE d'un pack. Un fill écrit à la main serait le
                  même à chaque fois, donc pire que pas de fill. On le DIT quand il n'y en a pas. */ ''}
            <div class="std-fills">
              <span class="std-lbl2">Fill at the end of</span>
              <div class="std-chips">${FILLS.map(([v, l]) => html`<button
                class=${cls('std-chip', (p.fill || 'off') === v && 'on', v !== 'off' && !(famNode && famNode.fills) && 'dis')}
                disabled=${v !== 'off' && !(famNode && famNode.fills)}
                onClick=${() => onParam('fill', v)}>${l}</button>`)}</div>
              ${famNode && famNode.fills
                ? html`<span class="std-hint">${famNode.fills} fill takes${
                    cur && (p.fill || 'off') !== 'off'
                      ? ` · ${cur.fills} placed in this grid` : ''}</span>`
                : html`<span class="std-warn2">No fills in this family.</span>`}
              ${famNode && famNode.fills ? html`<button class="mini"
                onClick=${() => hearTake(famNode.family, pickedTempo, true)}>▶ hear a fill</button>` : ''}
            </div>
          </div>` : ''}

      </div>

      ${/* Live view : un choix d'AFFICHAGE, sorti des réglages musicaux (refonte 2026-10-17) */ ''}
      <div class="std-bottom">
        <span class="std-lbl2">On /live while it plays</span>
        <div class="std-chips">${['Chart', 'Pedalboard'].map(v => html`<button
          class=${cls('std-chip', (p.live_view || 'Chart') === v && 'on')} onClick=${() => onParam('live_view', v)}
          title=${v === 'Chart' ? '/live turns to the grid while the standard plays, back to the stomps when it stops'
                                : '/live never turns: the stomps stay on screen'}>${v}</button>`)}</div>
        <span class="grow"></span>
        <p class="muted std-foot">Foot: tap to start and stop · long-press restarts the form</p>
      </div>`}
  </div>`;
}

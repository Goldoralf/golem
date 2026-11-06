// SPDX-License-Identifier: GPL-3.0-or-later
// Songs ▸ Setlists — les setlists (contrat docs/setlists.md, §9 lots 1-3).
//
// DÉCISION 2026-07-28 : **une setlist = un concert, ça tient sur le pédalier.** 19 slots, pas un
// de plus — c'est la taille du matériel (banks 00-18 en accès direct au pied). La GRILLE du
// pédalier (SetlistGrid) reste la vue qui place les rigs : dans une liste un trou est invisible,
// au pied il existe.
//
// LOT 3 (le mainteneur, maquettes mockups/setlist-song.html, 2026-09-08) : deux temps. La VITRINE — une
// carte par set, « Open » pour y entrer, « On the foot » pour le mettre sur le pédalier sans
// l'ouvrir. Puis la SETLIST OUVERTE — la page EST le set : les morceaux à gauche dans l'ordre des
// banks, le morceau choisi à droite (titre, tempo, rangée « Song blocks », arrangement). L'URL
// porte l'état : #/songs/setlists/<sid>[/<line id>]. On sort par le fil d'Ariane.
//
// La ligne porte l'USAGE (ce que les blocs du rig jouent pour CE morceau), le preset la CAPACITÉ
// (quels blocs, sur quel switch) — ligne > preset > global, rien n'est jamais désactivé (§9.9).
//
// L'INSTANTANÉ reste un objet DIFFÉRENT : il fige le CONTENU des presets. La setlist ne prétend
// jamais protéger les sons — c'est l'instantané qui le fait, et on sait qu'on l'a demandé.
import { useFactoryShow, keepFactory } from './factory-show.js';
import { isHome } from './startup-model.mjs';
import { fmPaired } from './services-model.mjs';   // ☁ seulement sur un golem appairé   // l'accueil au démarrage (mockups/startup-home.html)
import { html, useState, useEffect, useRef, useAsync, cls, esc, bankNo, setTopAction, setSubToolbar, openInDesigner, go, del } from './lib.js';
import { CONFIG_GEN_TYPES, hydrateBlockMeta, patchDraft } from './designer-model.js';
import { ArrRead } from './arr-read.js';   // la piste de Songs, lue — partagée avec le tiroir Arrangement du Designer
import { SampleListEd } from './designer-sheets.js';
import { SongPicker } from './page-repertoire.js';
import { BankPicker } from './page-setlists.js';          // la feuille « quelle bank ? », partagée avec le Designer
import { makeSongFromPatch } from './page-patches.js';   // « ▤ Make a song » (patch-as-preset §4 bis)

const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(b || {}) }).then(r => r.json());
const fmtDate = s => { const d = new Date((s || '').replace(' ', 'T'));
  return isNaN(d) ? (s || '') : d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); };

const CAP = 19;                    // = setlists.MAX_SLOTS côté bridge (qui refuse au-delà)

// les blocs de SERVICE du rig (lanes config gen + rec) tels que la ligne les voit (§9.9)
const SVC = { click: { ic: '◔', name: 'Click' }, sample: { ic: '▦', name: 'Sampler' }, 'backing-track': { ic: '🎵', name: 'Backing' },
  rec: { ic: '●', name: 'REC' }, looper: { ic: '↻', name: 'Looper' }, drums: { ic: '▩', name: 'Drums' }, standard: { ic: '♫', name: 'Standards' } };
const PER_SONG = ['click', 'sample', 'backing-track'];        // ce qui se règle PAR MORCEAU — et rien d'autre
// ── LE VOCABULAIRE COMPLET, EN LECTURE SEULE (2026-09-10) ─────────────────────────────
// Retirer les tuiles fantômes (« ici sampler ne sert à rien ») a coûté une information : on ne
// voyait plus ce qu'un morceau POURRAIT porter, seulement ce qu'il porte. « Il manque drum machine
// et sample » — non, ils ne manquaient pas, ce preset ne les a pas ; mais rien ne le disait. La
// bande dit les deux, et elle ne se clique pas : une tuile fantôme INVITAIT à agir depuis la page
// du morceau, une puce grise INFORME. C'est toute la différence, et elle tient au geste.
// Le REC n'y est pas, pour la même raison qu'il n'est pas dans les tuiles : il se règle au MODE.
// DÉRIVÉE, pas recopiée : un service ajouté au Designer entre ici tout seul (le premier essai
// listait les six types à la main — la liste aurait dérivé au premier bloc de service suivant).
const AVAIL = [...PER_SONG, ...CONFIG_GEN_TYPES.filter(t => !PER_SONG.includes(t))];
// ce que la ligne dit d'un bloc : sa surcharge, ou rien
const ovOf = (ln, b) => ((ln && ln.blocks) || {})[b.id] || null;
const lineSets = (ln, b) => b.type === 'backing-track' ? !!(ln && ln.backing) : !!ovOf(ln, b);
const icoRow = ln => [['▤', !!ln.arrangement, 'arrangement'], ['♫', !!ln.backing, 'backing'],
  ['▦', !!(ln.blocks && Object.keys(ln.blocks).length), 'song blocks']];

export function SetlistGroupsPage({ rig, sub }) {
  const facShow = useFactoryShow();          // l'usine masquée par sorte (Settings ▸ Content ▸ Factory)
  const [tick, setTick] = useState(0);
  const { data } = useAsync(() => fetch('/api/setlists').then(r => r.json()), [tick]);
  const [arm, setArm] = useState(null);           // clé du geste à confirmer (2-tap)
  const [snapConf, setSnapConf] = useState({});   // instantané -> sons modifiés depuis (le serveur prévient AVANT d'écraser)
  const [busy, setBusy] = useState(null);
  const [rename, setRename] = useState(null);     // {id, name} en cours d'édition
  const [editing, setEditing] = useState(null);   // id de la setlist ouverte dans la GRILLE des banks
  const [creating, setCreating] = useState(false);
  const [picking, setPicking] = useState(false);   // « ＋ Add a song » : le sélecteur du répertoire (docs/songs.md §9.6)
  const [pickingPatch, setPickingPatch] = useState(false);   // « + Add a patch » d'une bank de sons (patch-as-preset §7)
  const [push, setPush] = useState(null);         // compte rendu du dernier envoi golem.fm
  const [err, setErr] = useState('');
  const { data: presetsD } = useAsync(() => fetch('/api/presets').then(r => r.json()), [tick]);
  const allPresets = Array.isArray(presetsD) ? presetsD : ((presetsD || {}).presets || []);
  // une SOUND LIST range des patches : sa grille et sa feuille de bank les nomment sous l'id qu'elle joue (`patch:<id>`)
  const { data: patchesD } = useAsync(() => fetch('/api/patches').then(r => r.json()).catch(() => ({ patches: [] })), [tick]);
  const allPatches = (((patchesD || {}).patches) || []).map(x => ({ ...x, id: 'patch:' + x.id, pid: x.id }));
  const reload = () => setTick(t => t + 1);
  const armed = k => arm === k;
  const confirm = (k, run) => { if (!armed(k)) { setArm(k); setTimeout(() => setArm(a => a === k ? null : a), 2600); return; }
    setArm(null); run(); };

  const sets = (data || {}).setlists || [];
  // LE FILTRE SETLIST | BANK (2026-10-13) : deux sortes de listes sur une page (docs/setlists.md §10) — retenu par
  // appareil, comme la liste regardée (confort, jamais une donnée)
  const [kindF, setKindF0] = useState(() => { try { return localStorage.getItem('golem.slv.kind') || 'all'; } catch (e) { return 'all'; } });
  const setKindF = v => { setKindF0(v); try { localStorage.setItem('golem.slv.kind', v); } catch (e) { /* stockage indisponible */ } };
  // …et FACTORY | MINE : l'usine du golem (docs/factory.md) contre ce que l'utilisateur a fait. ⚠ PROVISOIRE : l'usine
  // se reconnaît à son id (`factory…`) en attendant le marqueur `factory` de la phase 4 (docs/factory.md §6 bis).
  const [ownF, setOwnF0] = useState(() => { try { return localStorage.getItem('golem.slv.own') || 'all'; } catch (e) { return 'all'; } });
  const setOwnF = v => { setOwnF0(v); try { localStorage.setItem('golem.slv.own', v); } catch (e) { /* stockage indisponible */ } };
  const isFactory = s => !!s.factory || /^factory(-|$)/.test(String(s.id || ''));
  const visSets = sets.filter(s => !(isFactory(s) && facShow.setlists === false));   // usine masquée : pas rendue
  const byOwn = visSets.filter(s => ownF === 'all' || (ownF === 'factory' ? isFactory(s) : !isFactory(s)));
  const byKind = visSets.filter(s => kindF === 'all' || (kindF === 'banks' ? s.kind === 'sounds' : s.kind !== 'sounds'));
  const nSet = byOwn.filter(s => s.kind !== 'sounds').length, nBank = byOwn.length - nSet;
  const nFac = byKind.filter(isFactory).length, nMine = byKind.length - nFac;
  const shown = byOwn.filter(s => kindF === 'all' || (kindF === 'banks' ? s.kind === 'sounds' : s.kind !== 'sounds'));
  const snaps = (data || {}).snapshots || [];
  // troisième segment : ce qu'on vient VOIR dans la ligne (#/songs/setlists/<set>/<ligne>/arrangement).
  // Sans lui, l'arrangement d'un morceau se cherchait en quatre clics et un coup d'œil — retour 2026-09-16.
  const [sid, lid, focus] = (sub || '').split('/');
  const opened = sets.find(s => s.id === sid) || null;

  const act = async (fn, msg) => {
    setBusy(msg); setErr('');
    const r = await fn().catch(e => ({ error: String(e) }));
    if (r && r.error) setErr(r.error);
    setBusy(null); reload();
    return r;
  };
  // RESTAURER un instantané : sans conflit, il restaure tout de suite ; si des sons ont changé depuis, le serveur
  // refuse et les nomme (400 + conflicts) — le bouton les montre, un second tap confirme l'écrasement
  const restoreSnap = sn => act(async () => {
    try {
      const r = await post('/api/snapshots/' + sn.id + '/restore', { overwrite: !!snapConf[sn.id] });
      setSnapConf(c => ({ ...c, [sn.id]: null }));
      return r;
    } catch (e) {
      const b = (e && e.body) || {};
      if ((b.conflicts || []).length) { setSnapConf(c => ({ ...c, [sn.id]: b.conflicts })); return {}; }
      return { error: b.error || String(e) };
    }
  }, 'restoring…');
  const setOrder = (sid2, arr) => act(() => post('/api/setlists/' + sid2 + '/presets', { presets: arr }), 'saving…');
  const nameOf = id => { const p = allPresets.find(x => x.id === id); return p ? (p.name || p.id) : id; };
  const activate = s => confirm('a:' + s.id, () => act(() => post('/api/setlists/' + s.id + '/activate'), 'activating…'));
  const doPush = s => confirm('p:' + s.id, () => act(async () => {
    const r = await post('/api/setlists/' + s.id + '/push'); setPush({ id: s.id, r }); return r; }, 'pushing…'));
  const remove = s => confirm('d:' + s.id, () => act(async () => {
    const r = await fetch('/api/setlists/' + s.id, { method: 'DELETE' }).then(x => x.json());
    if (!r.error && opened && opened.id === s.id) go('songs/setlists');
    return r; }, 'deleting…'));

  // ⚠ setTopAction est un EFFET DE BORD : l'appeler pendant le rendu reboucle à l'infini.
  // Vitrine : « + Add » (même verbe que Patches/Presets — retour 2026-08-02). Setlist ouverte :
  // le set sous le pied, ou le bouton qui l'y met (maquette ②).
  useEffect(() => {
    setTopAction(opened
      ? html`<div class="tb-action">
          ${opened.active ? html`<span class="chip slo-onfoot is-on" title="this setlist is on the pedalboard">● On the foot</span>`
            : html`<button class="chip slo-onfoot edit-only" title="use this setlist on the footswitch" onClick=${() => activate(opened)}>
                ${armed('a:' + opened.id) ? 'change the foot?' : '▶ On the foot'}</button>`}</div>`
      : html`<div class="tb-action"><button class="primary tb-new" title="create a setlist" onClick=${() => setCreating(true)}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, [opened && opened.id, opened && opened.active, arm]);
  // le fil d'Ariane vit dans la barre des sous-onglets : c'est par là qu'on SORT du set
  useEffect(() => {
    setSubToolbar(opened ? html`<span class="slo-crumb"><button class="mini" onClick=${() => go('songs/setlists')}>‹ All setlists</button>
      <span class="muted">/</span><b><i class=${cls('slo-crumb-ic', opened.kind === 'sounds' && 'snd')}>${opened.kind === 'sounds' ? '⛓' : '▤'}</i> ${esc(opened.name)}</b></span>`
      : html`<span class="slv-kindf">
          <div class="tb-seg" title="setlists of songs, banks of sounds">${[['all', 'All', byOwn.length], ['setlists', 'Setlists', nSet], ['banks', 'Banks', nBank]].map(([k, lb, n]) =>
            html`<button class=${cls(kindF === k && 'on')} onClick=${() => setKindF(k)}>${lb} <small>${n}</small></button>`)}</div>
          <div class="tb-seg" title="what golem ships, or what you made">${[['all', 'All', byKind.length], ['factory', 'Factory', nFac], ['mine', 'Mine', nMine]].map(([k, lb, n]) =>
            html`<button class=${cls(ownF === k && 'on')} onClick=${() => setOwnF(k)}>${lb} <small>${n}</small></button>`)}</div></span>`);
    return () => setSubToolbar(null);
  }, [opened && opened.id, opened && opened.name, opened && opened.kind, kindF, ownF, nSet, nBank, nFac, nMine, byOwn.length, byKind.length]);

  const notices = html`
    ${busy ? html`<div class="rec-day-lb">${esc(busy)}</div>` : ''}
    ${err ? html`<div class="sl-push ko" onClick=${() => setErr('')}>⚠ ${esc(err)}<small>tap to dismiss</small></div>` : ''}
    ${push ? html`<div class=${cls('sl-push', (push.r || {}).error && 'ko')} onClick=${() => setPush(null)}>
      ${(push.r || {}).error
        ? html`⚠ ${esc(push.r.error)}`
        : html`☁ « ${esc(push.id)} » sent — ${push.r.presets} preset${push.r.presets > 1 ? 's' : ''} in the bundle${
            (push.r.missing || []).length
              ? html`, <b>${push.r.missing.length} missing on this rack</b> (${esc((push.r.missing || []).join(', '))}) — they will NOT arrive`
              : ''}`}
      <small>tap to dismiss</small></div>` : ''}`;

  const modals = html`
    ${editing && sets.find(s => s.id === editing) ? html`<${SetlistGrid} sl=${sets.find(s => s.id === editing)}
      presets=${sets.find(s => s.id === editing).kind === 'sounds' ? allPatches : allPresets}
      onClose=${() => setEditing(null)} onOrder=${arr => setOrder(editing, arr)} />` : ''}
    ${creating ? html`<${NewSetlist} active=${sets.find(s => s.active)} onClose=${() => setCreating(false)}
      onCreate=${async body => { const r = await act(() => post('/api/setlists', body), 'creating…');
        // une bank de SONS n'a pas de grille de presets : on l'ouvre, on y ajoute des patches (patch-as-preset §7)
        if (r && !r.error) { setCreating(false); if (r.id) { if (r.kind !== 'sounds') setEditing(r.id); go('songs/setlists/' + r.id); } } return r; }} />` : ''}
    ${pickingPatch && opened ? html`<${PatchBankPicker} sl=${opened} onClose=${() => setPickingPatch(false)}
      onAdded=${() => { setPickingPatch(false); reload(); }} />` : ''}`;

  // ── ② LA SETLIST OUVERTE ────────────────────────────────────────────────────────────────
  if (opened) {
    const s = opened;
    const bank = s.kind === 'sounds';                      // une bank de SONS : des patches, pas des morceaux
    const line = (s.lines || []).find(l => l.id === lid) || null;
    // une bank LIBRE (trou voulu dans la grille) n'est pas un son : elle ne se compte pas
    const nLines = bank ? (s.lines || []).filter(l => l.patch || l.title).length : (s.lines || []).length;
    // « ＋ Add a song » = un CHOIX DANS LE RÉPERTOIRE (docs/songs.md §9.6, 2026-09-22 : « sans créer
    // la chanson via setlist »). Avant, ce geste fabriquait une ligne vide « New song » — une chanson
    // qui n'existait que dans cette setlist et mourait avec elle.
    const addSong = () => bank ? setPickingPatch(true) : setPicking(true);
    // « Remove from setlist » (2026-09-14) : la ligne s'en va, le preset reste. Deux taps,
    // comme la corbeille des setlists ; puis retour à la liste (la ligne n'existe plus).
    const removeLine = ln => confirm('l:' + ln.id, () => act(async () => {
      const r = await fetch('/api/setlists/' + s.id + '/line/' + encodeURIComponent(ln.id), { method: 'DELETE' }).then(x => x.json());
      if (!r.error) go('songs/setlists/' + s.id);
      return r; }, 'removing…'));
    return html`<div class="library slo-page">
      ${notices}
      <div class="slo">
        <div class="slo-left">
          <div class="slo-hd">
            ${/* LA NATURE DE LA LISTE, DITE UNE FOIS ET EN GRAND (maquette 2026-09-30) : rien ne distinguait
                  une setlist de morceaux d'une sound list une fois ouverte — même en-tête, mêmes lignes */''}
            <div class="slo-kind" data-doc="setlists.kind">
              <span class=${cls('slo-kindtag', bank && 'snd')}>${bank ? '⛓ Sound list · patches' : '▤ Setlist · songs'}</span>
              <span class=${cls('slo-foot', s.active && 'on')}>${s.active ? '● on the foot' : 'not on the foot'}</span>
            </div>
            <h3>${rename && rename.id === s.id
              ? html`<input class="sl-rename" value=${rename.name} autofocus
                  onInput=${e => setRename({ ...rename, name: e.target.value })}
                  onKeyDown=${e => { if (e.key === 'Enter') { act(() => post('/api/setlists/' + s.id + '/rename', { name: rename.name }), 'renaming…'); setRename(null); }
                                     if (e.key === 'Escape') setRename(null); }} />`
              : html`<span class="rec-name" title="double-tap to rename" onDblClick=${() => setRename({ id: s.id, name: s.name })}>${esc(s.name)}</span>`}
              <button class="mini slo-edit" title=${'lay the ' + (bank ? 'patches' : 'presets') + ' out on the pedalboard (banks)'} onClick=${() => setEditing(s.id)}>✎</button></h3>
            <div class="slo-meta"><span>${nLines} ${bank ? 'sound' : 'song'}${nLines === 1 ? '' : 's'} · ${CAP} banks max</span>
              ${(s.origin === 'golemfm' || s.origin === 'maestrium') ? html`<span class="rec-ctx m-pedalboard">☁ golem.fm${s.rev ? ' · rev ' + s.rev : ''}</span>` : (s.rev ? html`<span class="sset-org">rev ${s.rev}</span>` : '')}
              ${s.missing && s.missing.length ? html`<span class="rec-ctx m-gig" title=${'missing: ' + s.missing.join(', ')}>${s.missing.length} missing</span>` : ''}</div>
          </div>
          <div class="slo-lines" data-doc="setlists.lines">
            ${bank ? (s.lines || []).map((ln, i) => !ln.patch && !ln.title
              ? html`<div class="slo-ln free"><b>${bankNo(i)}</b><span class="t muted">free bank<small>⇅ Banks to place a patch here</small></span></div>`
              : html`<button class=${cls('slo-ln', ln.id === lid && 'sel', !ln.patch && 'gone')}
                onClick=${() => go('songs/setlists/' + s.id + '/' + ln.id)}>
              <b>${bankNo(i)}</b>
              <span class="t">⛓ ${esc(ln.title || ln.patch || '—')}<small>${ln.patch ? 'patch' : 'patch deleted — this slot plays nothing'}</small></span>
            </button>`) : ''}
            ${bank ? '' : (s.lines || []).map((ln, i) => html`<button class=${cls('slo-ln', ln.id === lid && 'sel', !ln.preset && 'norig', (s.missing || []).includes(ln.preset) && 'gone')}
                data-doc=${'setlists.line.' + (i + 1)} onClick=${() => go('songs/setlists/' + s.id + '/' + ln.id)}>
              <b>${bankNo(i)}</b>
              <span class="t">${esc(ln.title || nameOf(ln.preset) || 'New song')}<small>${!ln.preset ? 'no preset yet' : (s.missing || []).includes(ln.preset) ? ln.preset + ' — not on this rack'
                : esc(nameOf(ln.preset)) + (ln.title && !ln.arrangement && !ln.backing && !ln.blocks ? ' · preset as is' : '')}</small></span>
              ${ln.bpm ? html`<em class="bpm">♩${ln.bpm}</em>` : ''}
              <span class="ico">${icoRow(ln).map(([g, on, t]) => t === 'arrangement'
                ? html`<i class=${cls(on && 'on', 'go')} role="button" tabindex="0"
                    title=${on ? 'the parts of this song — intro, verse, chorus' : 'lay out the parts of this song'}
                    onClick=${e => { e.stopPropagation(); go('songs/setlists/' + s.id + '/' + ln.id + '/arrangement'); }}
                    onKeyDown=${e => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); e.preventDefault(); go('songs/setlists/' + s.id + '/' + ln.id + '/arrangement'); } }}>${g}</i>`
                : html`<i class=${cls(on && 'on')} title=${t}>${g}</i>`)}</span>
            </button>`)}
            ${(s.lines || []).length < CAP ? html`<button class="slo-ln add" onClick=${addSong}>${bank ? '+ Add a patch' : '+ Add a song'}</button>` : ''}
          </div>
          <div class="slo-ft">
            ${/* une bank de sons : ni grille de presets, ni copie, ni envoi de presets, ni instantané de presets */''}
            <button class="mini" data-doc="setlists.banks" title=${'move the ' + (bank ? 'patches' : 'presets') + ' across the banks'} onClick=${() => setEditing(s.id)}>⇅ Banks</button>
            ${bank ? '' : html`<button class="mini edit-only" title="duplicate" onClick=${() => act(() => post('/api/setlists/' + s.id + '/duplicate'), 'copying…')}>⧉</button>
            ${fmPaired(rig) ? html`<button class="mini edit-only" title="push this setlist AND its presets to golem.fm" onClick=${() => doPush(s)}>${armed('p:' + s.id) ? 'send?' : '☁'}</button>` : ''}
            <button class="mini edit-only" title="freeze the SOUNDS of these presets (snapshot)" onClick=${() => act(() => post('/api/setlists/' + s.id + '/snapshot'), 'freezing…')}>📷</button>`}
            ${!s.active ? html`<button class=${cls('mini edit-only', !armed('d:' + s.id) && 'slv-ic', armed('d:' + s.id) && 'danger')} title="delete the setlist (never the presets)" onClick=${() => remove(s)}>${armed('d:' + s.id) ? 'sure?' : '🗑'}</button>` : ''}
          </div>
        </div>
        <div class="slo-right" data-doc="setlists.detail">
          ${line && bank ? html`<${PatchLineDetail} line=${line} sl=${s} patches=${allPatches} onMoved=${reload}
              onRemove=${() => removeLine(line)} removeArmed=${armed('l:' + line.id)} />`
            : line ? html`<${LineDetail} key=${line.id + ':' + (line.band_song || '')} sid=${s.id} line=${line} focus=${focus} presets=${allPresets} missing=${(s.missing || []).includes(line.preset)}
              onChanged=${reload} onRemove=${() => removeLine(line)} removeArmed=${armed('l:' + line.id)} />`
            : html`<div class="slo-pick empty">${bank ? ((s.lines || []).length ? 'Pick a patch on the left — or add one.' : 'Empty list. Add your patches: each one takes a bank (#) on the pedalboard.')
                : (s.lines || []).length ? 'Pick a song on the left — or add one.' : 'Empty set. Add a song, or lay presets out with ⇅ Banks.'}</div>`}
        </div>
      </div>
      ${modals}
      ${picking ? html`<${SongPicker} setlist=${s} onClose=${() => setPicking(false)}
        onAdded=${r => { setPicking(false); reload(); const nl = ((r || {}).added || [])[0]; if (nl) go('songs/setlists/' + s.id + '/' + nl); }} />` : ''}
    </div>`;
  }

  // ── ① LA VITRINE ──────────────────────────────────────────────────────────────────────────
  const card = s => html`<div class=${cls('slv-card', s.active && 'act')} data-doc=${'setlists.card:' + s.id}>
    ${/* L'ÉTIQUETTE (2026-10-08) : BANK = une liste de sons (patches), SETLIST = une liste de morceaux — les
          mots que /live affiche en tête (« BANK #01 » / « SETLIST #02 ») */''}
    <h3><span class=${cls('slv-type', s.kind === 'sounds' ? 'bank' : 'setlist')}>${s.kind === 'sounds' ? '⛓ BANK' : '▤ SETLIST'}</span>${isFactory(s) ? html`<span class="slv-own" title="ships with golem — read-only in a coming update; edit a copy">◆ factory</span>` : ''}
      <span class="slv-name">${esc(s.name)}</span>
      ${/* le TAG d'origine, lisible sans filtre (2026-10-13) : collé au tag de type, AVANT le titre — un titre encadré
            de deux tags ne se lit plus . « Mine » est l'absence de tag, pas un second badge sur chaque carte */''}
      ${s.active ? html`<span class="rec-ctx m-studio">on the foot</span>` : ''}
      ${(s.origin === 'golemfm' || s.origin === 'maestrium') ? html`<span class="rec-ctx m-pedalboard">☁ golem.fm</span>` : ''}</h3>
    <div class="slv-meta"><span>${(s.lines || []).length} ${s.kind === 'sounds' ? 'sound' : 'song'}${(s.lines || []).length === 1 ? '' : 's'}</span>
      ${s.rev ? html`<span>rev ${s.rev}</span>` : ''}
      ${s.missing && s.missing.length ? html`<span class="rec-ctx m-gig" title=${'missing: ' + s.missing.join(', ')}>${s.missing.length} missing</span>` : ''}</div>
    <ol>
      ${(s.lines || []).slice(0, 3).map((ln, i) => html`<li><b>${bankNo(i)}</b><span>${ln.patch ? '⛓ ' : ''}${esc(ln.title || nameOf(ln.preset) || '—')}</span>
        <em>${ln.patch ? 'patch' : html`${ln.bpm ? '♩' + ln.bpm : ''}${icoRow(ln).filter(x => x[1]).map(x => ' ' + x[0]).join('') || (ln.bpm ? '' : 'preset as is')}`}</em></li>`)}
      ${(s.lines || []).length > 3 ? html`<li class="more">+ ${(s.lines || []).length - 3} more</li>` : ''}
      ${!(s.lines || []).length ? html`<li class="more">Empty — open it to lay it out on the pedalboard.</li>` : ''}
    </ol>
    <div class="slv-foot">
      <button class=${cls('mini', s.active && 'primary-ish')} onClick=${() => go('songs/setlists/' + s.id)}>Open</button>
      ${!s.active ? html`<button class="mini slo-onfoot edit-only" title="use this setlist on the footswitch" onClick=${() => activate(s)}>${armed('a:' + s.id) ? 'change the foot?' : '▶ On the foot'}</button>` : ''}
      <span class="grow"></span>
      ${(() => { const st0 = ((rig || {}).state || {}).startup, on = isHome(st0, { kind: 'setlist', id: s.id }) && (st0 || {}).policy === 'home';
        return html`<button class=${cls('mini edit-only', !on && 'slv-ic', on && 'primary-ish')}
          title=${on ? 'golem opens this ' + (s.kind === 'sounds' ? 'bank' : 'setlist') + ' at startup (its first line) — tap to remove'
                     : 'open this ' + (s.kind === 'sounds' ? 'bank' : 'setlist') + ' at startup — it goes on the foot, on its first line'}
          onClick=${() => on ? del('/api/startup/home').catch(() => {}) : post('/api/startup/home', { kind: 'setlist', id: s.id, name: s.name }).catch(() => {})}>${on ? '⌂ startup' : '⌂'}</button>`; })()}
      ${s.kind === 'sounds' ? '' : html`<button class="mini slv-ic edit-only" title="duplicate" onClick=${() => act(() => post('/api/setlists/' + s.id + '/duplicate'), 'copying…')}>⧉</button>`}
      ${!s.active ? html`<button class=${cls('mini edit-only', armed('d:' + s.id) && 'danger')} title="delete the setlist (never the presets)" onClick=${() => remove(s)}>${armed('d:' + s.id) ? 'sure?' : '🗑'}</button>` : ''}
    </div>
  </div>`;

  return html`<div class="library">
    <div class="lib-grid">
      ${notices}
      <div class="slv-grid">${shown.map(card)}
        ${!sets.length ? html`<div class="empty">No setlist yet — tap + Add.</div>` : ''}</div>
      <div class="rec-day slv-snaps">
        <div class="rec-day-lb">Snapshots<em>frozen sounds — the only way back</em></div>
        <div class="rec-grid">
          ${snaps.length ? snaps.map(sn => html`<div class="rec-card solo"><div class="rec-body">
            <div class="wv-row">
              <span class="wv-n">📷</span>
              <span class="wv-info">
                <b class="wv-name">${esc(sn.name)}</b>
                <em class="wv-tech">${fmtDate(sn.created_at)} · ${sn.count} preset${sn.count > 1 ? 's' : ''} frozen${(sn.missing || []).length ? ' · ' + sn.missing.length + ' were already missing' : ''}</em>
              </span>
              <button class=${cls('mini', snapConf[sn.id] && 'danger')}
                title=${snapConf[sn.id] ? 'changed since the snapshot: ' + snapConf[sn.id].map(c => c.name || c.id || c).join(', ')
                  : 'put these sounds back (asks first if some changed since), then create a setlist'}
                onClick=${() => restoreSnap(sn)}>
                ${snapConf[sn.id] ? 'overwrite ' + snapConf[sn.id].length + ' changed?' : '↺ Restore'}</button>
            </div>
          </div></div>`)
          : html`<div class="empty">No snapshot yet. A setlist follows your edits — a snapshot
            freezes the sounds as they are today. Tap 📷 in a setlist before replacing everything.</div>`}
        </div>
      </div>
    </div>
    ${modals}
  </div>`;
}


// ── LA GRILLE : une setlist telle qu'elle existe sous le pied ────────────────────────────────
// 19 cases, les vides VISIBLES (au pied, un trou existe — et il est sûr : une bank vide est un
// no-op silencieux, elle ne change pas le preset courant). Deux gestes, pas plus :
//   case libre  -> choisir un preset (le cas courant)
//   case pleine -> la sélectionner, puis taper une autre case pour la DÉPLACER (échange si occupée)
// Le reste (vider, remplacer) est dans la barre d'actions de la sélection. Pas de flèches ◀▶ :
// à 19 cases, déplacer d'un cran à la fois est une punition.
function SetlistGrid({ sl, presets, onClose, onOrder }) {
  // une SOUND LIST pose des patches (`presets` = les patches, ids `patch:<id>`) — même grille, mêmes gestes
  const what = sl.kind === 'sounds' ? 'patch' : 'preset';
  const [sel, setSel] = useState(null);          // index sélectionné
  const [picking, setPicking] = useState(null);  // index où l'on choisit un preset
  const [q, setQ] = useState('');
  const arr = () => { const a = [...(sl.presets || [])]; while (a.length < CAP) a.push(''); return a.slice(0, CAP); };
  const nameOf = id => { const p = (presets || []).find(x => x.id === id); return p ? (p.name || p.id) : id; };
  const missing = id => (sl.missing || []).includes(id);
  // on renvoie au bridge la liste SANS les trous de fin (un slot vide en queue n'a pas de sens),
  // mais on garde les trous du milieu : ils sont voulus (une bank libre pour un rappel).
  const commit = a => { const b = [...a]; while (b.length && !b[b.length - 1]) b.pop(); onOrder(b); };

  const put = (i, pid) => { const a = arr(); a[i] = pid; setPicking(null); setSel(null); commit(a); };
  const clear = i => { const a = arr(); a[i] = ''; setSel(null); commit(a); };
  const move = (from, to) => { const a = arr(); const t = a[to]; a[to] = a[from]; a[from] = t; setSel(null); commit(a); };

  const onCell = i => {
    const a = arr();
    if (sel !== null && sel !== i) return move(sel, i);       // déplacer / échanger
    if (sel === i) return setSel(null);
    if (!a[i]) return setPicking(i);                          // case libre -> choisir
    setSel(i);
  };

  const used = arr().filter(Boolean).length;
  const list = (presets || []).filter(p => !q ||
    ((p.name || '') + ' ' + p.id).toLowerCase().includes(q.toLowerCase()));

  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card bp slg" data-doc="setlists.grid">
      <button class="close" onClick=${onClose}>×</button>
      <h2>${esc(sl.name)} <small class="slg-count">${used}/${CAP} banks</small></h2>
      <p class="muted">The grid IS the pedalboard: bank <b>${bankNo(0)}</b> is the first switch.
        Tap a free bank to place a ${what} · tap a filled one, then another bank, to move it.
        ${sl.active ? html` <b>This setlist is on the foot right now.</b>` : ''}</p>

      <div class="bp-grid">
        ${arr().map((pid, i) => html`<button
          class=${cls('bp-cell', !pid && 'free', sel === i && 'armed', pid && missing(pid) && 'gone')}
          title=${pid ? (missing(pid) ? pid + ' — not on this rack' : esc(nameOf(pid))) : 'free bank'}
          onClick=${() => onCell(i)}>
          <b>${bankNo(i)}</b>
          <span>${pid ? esc(nameOf(pid)) : (sel !== null ? 'move here' : 'free')}</span>
        </button>`)}
      </div>

      ${sel !== null && arr()[sel] ? html`<div class="slg-bar">
        <b>#${bankNo(sel)} · ${esc(nameOf(arr()[sel]))}</b>
        <span class="muted">tap another bank to move it</span>
        <button class="mini" onClick=${() => setPicking(sel)}>Replace…</button>
        <button class="mini danger" onClick=${() => clear(sel)}>Clear bank</button>
        <button class="mini" onClick=${() => setSel(null)}>Done</button>
      </div>` : html`<div class="slg-bar muted">
        ${used >= CAP ? 'All 19 banks are taken — clear one to add another ' + what + '.'
                      : (CAP - used) + ' free bank' + (CAP - used > 1 ? 's' : '') + ' left.'}
      </div>`}
    </div>

    ${picking !== null ? html`<div class="add-scrim" onClick=${() => setPicking(null)}>
      <div class="add-menu sl-add" onClick=${e => e.stopPropagation()}>
        <b>Bank #${bankNo(picking)} <small>pick a ${what}</small></b>
        <input class="search slg-q" placeholder="Search…" autofocus value=${q}
          onInput=${e => setQ(e.target.value)} />
        <div class="sl-add-list">
          ${list.map(p => html`<button class="row-btn" onClick=${() => put(picking, p.id)}>
            ${esc(p.name || p.id)}<small>${esc(p.role || p.pid || p.id)}</small></button>`)}
          ${list.length ? '' : html`<p class="muted">No ${what} matches.</p>`}
        </div>
      </div></div>` : ''}
  </div>`;
}


// ── création : on NOMME, et on dit d'où l'on part ────────────────────────────────────────────
function NewSetlist({ active, onClose, onCreate }) {
  const [name, setName] = useState('');
  const [from, setFrom] = useState('empty');
  const [kind, setKind] = useState('songs');          // FIXÉ à la création (patch-as-preset §11)
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const go = async () => {
    if (!name.trim()) return;
    setBusy(true); setErr('');
    const r = await onCreate({ name: name.trim(), kind, from_banks: kind === 'songs' && from === 'active' });
    if (r && r.error) { setErr(r.error); setBusy(false); }
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card mode-add">
      <button class="close" onClick=${onClose}>×</button>
      <h2>New list</h2>
      <p class="sub">${kind === 'sounds' ? 'Your patches on the pedalboard — one sound per bank' : 'One gig, laid out on the pedalboard'} — ${CAP} banks max.</p>

      ${/* LA NATURE, D'ABORD (docs/patches.md §7) : fixée ici, une liste ne change jamais de nature */''}
      <label class="mode-add-lb">What goes in it</label>
      <div class="mode-add-from">
        <button class=${cls('chip', kind === 'songs' && 'on')} onClick=${() => setKind('songs')}>▤ Songs · a setlist</button>
        <button class=${cls('chip', kind === 'sounds' && 'on')} onClick=${() => setKind('sounds')}>⛓ Sound list · your patches</button>
      </div>

      <label class="mode-add-lb">Name</label>
      <input class="mode-add-in" autofocus placeholder="Harbor Bar · March 12" value=${name}
        onInput=${e => setName(e.target.value)}
        onKeyDown=${e => { if (e.key === 'Enter' && name.trim() && !busy) go(); }} />

      ${kind === 'sounds' ? '' : html`<label class="mode-add-lb">Start from</label>
      <div class="mode-add-from">
        <button class=${cls('chip', from === 'empty' && 'on')} onClick=${() => setFrom('empty')}>
          Empty grid</button>
        <button class=${cls('chip', from === 'active' && 'on')} onClick=${() => setFrom('active')}
          disabled=${!active || (active || {}).kind === 'sounds'}>Copy of « ${esc((active || {}).name || '—')} »</button>
      </div>`}
      <p class="mode-add-hint">Nothing is « saved » here : bank assignments are written as you make
        them. Creating a setlist just gives you another pedalboard layout.</p>

      ${err ? html`<p class="mode-err">✗ ${esc(err)}</p>` : ''}
      <div class="mode-add-acts">
        <button class="chip" onClick=${onClose}>Cancel</button>
        <button class="primary" disabled=${busy || !name.trim()} onClick=${go}>
          ${busy ? '⏳ Creating…' : 'Create & lay out'}</button>
      </div>
    </div>
  </div>`;
}


// ── LE DÉTAIL D'UNE LIGNE (docs/setlists.md §9, lots 2-3) : la chanson — titre, tempo, rig, les
// BLOCS PAR MORCEAU et l'ARRANGEMENT. L'éditeur d'arrangement est celui de l'ancien onglet ▤ du
// Designer, monté sur la palette du PRESET de la ligne. Chaque retouche part vers la ligne
// (rev +1, push miroir). L'état local `ln` suit la réponse du bridge, jamais une supposition.
// ── LA LIGNE D'UNE CHANSON, EN LECTURE (docs/songs.md §5) ───────────────────────────────────
// Ce que la chanson dit, et un bouton pour l'ouvrir. Si la chanson n'est pas encore sur ce rack
// (setlist reçue avant le répertoire), on affiche ce que la LIGNE porte et on le DIT : une ligne
// muette sans explication est la panne qu'on répare partout ailleurs dans ce dépôt.
// ── CE QU'UNE LIGNE JOUE, EN LECTURE SEULE (maquette « Setlist line detail », 2026-09-30) ──────────
// Une setlist est un ORDRE DE PASSAGE : l'arrangement et les blocs spéciaux s'y LISENT, ils se changent là où
// ils vivent (la chanson, le Designer). Pas de tiroir grisé : un éditeur « désactivé » est une garde qu'une autre
// couche peut défaire (CLAUDE.md, `hidden`) — ici on ne rend que du texte, et un lien vers l'endroit qui écrit.

// ── LES DEUX PREMIÈRES RANGÉES, communes à toutes les lignes (2026-09-30) ────────────────────────────────
// 1. Preset · Tempo · Tuning · Capo — grisée pour un patch (un son n'a ni morceau ni tempo) ;
// 2. les blocs SPÉCIAUX : TOUS, allumés ceux que le rig porte. Un allumé se tape (sa fiche) ; un éteint informe.
const SPECIALS = [...AVAIL, 'rec'];
function FactRow({ facts, off }) {
  return html`<div class=${cls('sl-read-rows', off && 'off')} data-doc="setlists.facts">
    ${facts.map(f => html`<${f.onClick ? 'button' : 'div'} class=${cls('sl-rd', f.onClick && 'tap')} onClick=${f.onClick}
        disabled=${off ? true : undefined} title=${f.title || ''}>
      <span class="k">${f.k}</span>
      ${f.input ? f.input : html`<span class=${cls('v', f.v == null && 'none')}>${f.v == null || off ? '—' : esc(String(f.v))}</span>`}
      ${f.warn ? html`<small class="lane-off warn">⚠ ${f.warn}</small>` : ''}<//>`)}
  </div>`;
}

function SpecialRow({ preset, backing, onPick, set }) {
  const cfg = (preset && preset.config) || {};
  const all = [...(((cfg.gen || {}).blocks) || []), ...(((cfg.rec || {}).blocks) || [])];
  return html`<div class="pl-ro-chips sp-row" data-doc="setlists.players">${SPECIALS.map(t => {
    const b = all.find(x => x && x.type === t);
    const d = SVC[t] || { ic: '•', name: t };
    const what = t === 'backing-track' && b ? (backing || 'no song picked') : null;
    const own = b && set && set(b);
    return html`<button class=${cls('pl-chip', b ? 'on' : 'off', t === 'backing-track' && b && 'bk', own && 'song')}
        disabled=${!b} onClick=${() => b && onPick({ b, global: t === 'click' || t === 'rec', what })}
        title=${b ? d.name + (own ? ' — set for this song' : '') + ' — tap to see how it is set' : d.name + ' — not in this ' + (preset && preset.kind === 'patch' ? 'patch' : 'preset')}>
      <i>${d.ic}</i>${d.name}${what ? html`<span class="w">${esc(what)}</span>` : ''}${b && b.foot ? html`<span class="sw">SW${b.foot}</span>` : ''}</button>`; })}
  </div>`;
}

function PlayerCard({ pick, from, onEdit, editLabel, onClose }) {
  const { b, global, what } = pick;
  const d = SVC[b.type] || { ic: '•', name: b.type };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card sm pl-card">
      <button class="close" aria-label="Close" onClick=${onClose}>×</button>
      <h2><i>${d.ic}</i> ${d.name} <small>read-only</small></h2>
      <div class="pl-card-rows">
        ${what ? html`<span class="k">Song</span><span>${esc(what)}</span>` : ''}
        <span class="k">Foot</span><span>${b.foot ? html`<b class="sw">SW${b.foot}</b>` : 'not on a switch'}</span>
        <span class="k">State</span><span>${b.bypass ? 'bypassed' : 'active'}</span>
        <span class="k">Comes from</span><span>${global ? 'the rack — every song, every patch' : esc(from)}</span>
      </div>
      ${onEdit ? html`<div class="pl-card-act"><button class="primary" onClick=${() => { onClose(); onEdit(pick); }}>✎ ${editLabel} ›</button></div>` : ''}
    </div></div>`;
}

function SongLine({ sid, line, presetName, missing, onRemove, removeArmed }) {
  const bs = line.band_song;
  const { data } = useAsync(() => fetch('/api/song/' + encodeURIComponent(bs))
    .then(r => r.ok ? r.json() : null).catch(() => null), [bs]);
  const song = (data || {}).song || null;
  const sh = song ? (song.sheet || {}) : {};
  // la ligne arrive RÉSOLUE par le bridge (setlists.view_line, docs/songs.md §9.7) : la fiche de la
  // chanson, surchargée par les SEULES exceptions déclarées de la ligne. `sh` n'est qu'un repli.
  const val = k => (line[k] != null && line[k] !== '' ? line[k] : sh[k]);
  const pid = val('preset');
  // le rig qu'elle joue : ses scènes nomment et colorent la bande, son ⚙ donne les blocs spéciaux
  const { data: rig } = useAsync(() => pid && !missing ? fetch('/api/preset/' + encodeURIComponent(pid)).then(r => r.ok ? r.json() : null).catch(() => null)
    : Promise.resolve(null), [pid, missing]);
  const [pick, setPick] = useState(null);
  const openSong = () => go('songs/songs/' + encodeURIComponent(bs));
  const parts = (((val('arrangement') || {}).params || {}).sections) || [];
  const facts = [{ k: 'Preset', v: presetName || pid || null, warn: missing ? 'not on this rack' : null },
                 { k: 'Tempo', v: val('bpm') ? val('bpm') + ' BPM' : null }, { k: 'Tuning', v: val('tuning') },
                 { k: 'Capo', v: val('capo') || null }];
  return html`<div class="ld sl-read">
    <div class="ld-head">
      <span class="sl-title">${esc(line.title || (song || {}).title || presetName || 'Song')}</span>
      ${(song || {}).artist ? html`<small class="muted">${esc(song.artist)}</small>` : ''}
      <span class="grow"></span>
      ${song ? '' : html`<span class="chip warn" title="this line names a song that is not on this rack yet — it plays what the line carries">song not here yet</span>`}
      <button class="mini" data-doc="setlists.edit-song" title="everything below belongs to the song — open it to change any of it" onClick=${openSong}>✎ Edit the song ›</button>
      ${onRemove ? html`<button class=${cls('mini edit-only', removeArmed && 'danger')} title="take this song out of the setlist"
        onClick=${onRemove}>${removeArmed ? 'remove?' : '🗑'}</button>` : ''}
    </div>
    <${FactRow} facts=${facts} />
    <${SpecialRow} preset=${rig} backing=${val('backing')} onPick=${setPick} />
    ${parts.length ? html`<${ArrRead} parts=${parts} bpm=${val('bpm') || (rig || {}).bpm} preset=${rig} onEdit=${openSong} />`
      : html`<div class="arr-ro"><div class="arr-ro-hd"><b>Arrangement</b><span class="muted">no parts yet — the scenes change at your foot</span>
          <span class="grow"></span><button class="linkish" onClick=${openSong}>Lay them out in the song ›</button></div></div>`}
    ${pick ? html`<${PlayerCard} pick=${pick} from=${pick.b.type === 'backing-track' ? 'the song — every setlist that plays it' : 'the preset « ' + (presetName || pid) + ' »'}
      editLabel=${pick.b.type === 'backing-track' ? 'Change it in the song' : 'Change it in the Designer'}
      onEdit=${pk => pk.b.type === 'backing-track' ? openSong() : openInDesigner(pid, 'cfg')} onClose=${() => setPick(null)} />` : ''}
  </div>`;
}

function LineDetail({ sid, line, focus, presets, missing, onChanged, onRemove, removeArmed }) {
  const [ln, setLn] = useState(line);
  useEffect(() => setLn(line), [line.id, line.rev]);
  const [mk, setMk] = useState(false);              // « ◆ Make it a song » : la question de la nature ouverte
  const makeSong = async kind => {
    const r = await post('/api/setlists/' + sid + '/line/' + encodeURIComponent(ln.id) + '/to-song', { kind }).catch(e => ({ error: String(e) }));
    setMk(false);
    if (r && r.error) setSaid('✗ ' + r.error); else onChanged && onChanged();
  };
  const pid = ln.preset;
  const { data: preset } = useAsync(() => pid ? fetch('/api/preset/' + encodeURIComponent(pid)).then(r => r.json()) : Promise.resolve(null), [pid]);
  // le catalogue HYDRATE les noms courts (« Comp », « Big Muff ») que lisent les lignes d'accord du tableau
  const { data: fxD } = useAsync(() => fetch('/api/effects').then(r => r.json()).then(d => { hydrateBlockMeta(d.effects || d, d); return d; }), []);
  const { data: catD } = useAsync(() => fetch('/api/backing/catalog').then(r => r.json()).catch(() => []), []);
  // le patch de la carte : c'est lui qui nomme les entrées et dit QUI les tient (docs/input-map.md §3)
  const catalog = Array.isArray(catD) ? catD : ((catD || {}).songs || []);
  const [meta, setMeta] = useState({ title: ln.title || '', bpm: ln.bpm || '' });
  useEffect(() => setMeta({ title: ln.title || '', bpm: ln.bpm || '' }), [ln.id]);
  // CE QU'IL FAUT PRÉPARER (docs/devices-people.md, lot F) : accordage, capo, une note — lus par la page
  // « Between songs » des téléphones. Dans un petit volet : la tête de ligne n'a pas la place de trois champs.
  const [prepOpen, setPrepOpen] = useState(false);
  const [said, setSaid] = useState('');
  const [sheet, setSheet] = useState(null);          // le bloc dont on ouvre la feuille « par morceau »
  const [pickRig, setPickRig] = useState(false);
  const [q, setQ] = useState('');
  // arrivé par l'icône ▤ d'une ligne : on AMÈNE l'arrangement sous les yeux, et on le souligne deux
  // secondes. Sans ça le lien ouvrait la fiche et laissait chercher la carte sous « Song blocks ».
  const arrRef = useRef(null);
  useEffect(() => {
    if (focus !== 'arrangement' || !arrRef.current) return;
    arrRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [focus, line.id]);
  const save = async (fields, quiet) => {
    const r = await post('/api/setlists/' + sid + '/line', { id: ln.id, ...fields }).catch(e => ({ error: String(e) }));
    if (r && r.error) { setSaid('✗ ' + r.error); }
    else { const nl = (r.lines || []).find(l => l.id === ln.id); if (nl) setLn(nl); if (!quiet) setSaid('✓ saved'); onChanged && onChanged(); }
    setTimeout(() => setSaid(''), 1800);
    return r;
  };
  const arr = ln.arrangement || null;
  // la surcharge d'un bloc : `null` la retire ; `{}` côté bridge = plus aucune surcharge
  const setOv = (b, ov) => { const blocks = { ...(ln.blocks || {}) }; if (ov) blocks[b.id] = ov; else delete blocks[b.id]; return save({ blocks }); };
  const presetName = ((presets || []).find(x => x.id === pid) || {}).name || pid || '—';
  // ⚠ PLUS DE TUILES FANTÔMES (2026-09-09 : « ici sampler ne sert à rien ») : une ligne de
  // setlist règle ce que le preset PORTE — un bloc absent n'a rien à y régler, et proposer de
  // l'ajouter renvoie au Designer depuis une page où l'on prépare le morceau, pas le rig.
  const list = (presets || []).filter(p => !q || ((p.name || '') + ' ' + p.id).toLowerCase().includes(q.toLowerCase()));

  // ── UNE LIGNE DE CHANSON NE S'ÉDITE PAS ICI (docs/songs.md §5, 2026-09-20) ────────────
  // « On agrège les chansons, mais on ne les modifie pas ici. L'arrangement se fait maintenant
  // dans songs. » Une setlist est un ORDRE DE PASSAGE : ce que la chanson dit s'y LIT, et se
  // change en ouvrant la chanson. Une ligne SANS `band_song` (a cappella, invité) reste maîtresse
  // de son contenu et garde tout l'éditeur — elle n'a pas de chanson à ouvrir.
  if (ln.band_song) return html`<${SongLine} sid=${sid} line=${ln} presetName=${presetName}
    missing=${missing} onRemove=${onRemove} removeArmed=${removeArmed} />`;

  // ── MÊME PAGE QUE LES LIGNES DE CHANSON (2026-09-30) : 1. Preset · Tempo · Tuning · Capo ; 2. TOUS les blocs
  // spéciaux, allumés ceux que le preset porte ; 3. l'arrangement, LU. Une ligne libre reste maîtresse de ce qu'elle
  // porte (songs.md §5) : ses tuiles se tapent (preset, tempo, préparation) et ses blocs « par morceau » s'ouvrent.
  const [pick, setPick] = useState(null);
  const facts = [
    { k: 'Preset', v: pid ? presetName : 'pick a preset', warn: missing ? 'not on this rack' : null,
      onClick: () => setPickRig(true), title: pid ? 'the preset this song plays — tap to change it' : 'no preset yet — tap to pick one' },
    { k: 'Tempo', title: "tempo of this song — empty = the preset's", input: html`<input class="sl-rd-in" type="number" min="20" max="400"
        value=${meta.bpm} placeholder=${(preset || {}).bpm || 120}
        onInput=${e => setMeta({ ...meta, bpm: e.target.value })}
        onChange=${e => save({ bpm: e.target.value === '' ? null : +e.target.value })} />` },
    { k: 'Tuning', v: ln.tuning || null, onClick: () => setPrepOpen(!prepOpen), title: 'what the band prepares before this song' },
    { k: 'Capo', v: ln.capo || null, onClick: () => setPrepOpen(!prepOpen), title: 'what the band prepares before this song' }];
  return html`<div class="ld sl-read">
    <div class="ld-head">
      <input class="ld-title" value=${meta.title} placeholder=${pid ? presetName : 'Song title'}
        onInput=${e => setMeta({ ...meta, title: e.target.value })}
        onChange=${e => save({ title: e.target.value.trim() })} />
      <span class="ld-said">${said}</span>
      ${pid && !missing ? html`<button class="mini" title="open this preset in the Designer" onClick=${() => openInDesigner(pid)}>✎ Designer</button>` : ''}
      ${/* ◆ MAKE IT A SONG (docs/songs.md §9.6) : une ligne LIBRE — née avant le répertoire — devient
            une chanson d'un tap ; ses champs passent dans la chanson, la ligne ne garde que sa place.
            La nature se demande ICI, sans défaut (chez golem.fm une chanson sans nature = reprise publiable). */''}
      ${mk ? html`<span class="ld-mk">cover or original?
          ${[['cover', 'Cover'], ['original', 'Original']].map(([k, lb]) => html`<button class="mini" onClick=${() => makeSong(k)}>${lb}</button>`)}
          <button class="mini" title="cancel" onClick=${() => setMk(false)}>✕</button></span>`
        : html`<button class="mini ld-mksong edit-only" title="make this line a song of the repertoire — it can then sit in other setlists"
            onClick=${() => setMk(true)}>◆ Make it a song</button>`}
      ${onRemove ? html`<button class=${cls('mini ld-remove edit-only', removeArmed && 'danger')} title="remove this song from the setlist (the preset stays)"
        onClick=${onRemove}>${removeArmed ? 'sure?' : '🗑'}</button>` : ''}
    </div>
    <${FactRow} facts=${facts} />
    ${prepOpen ? html`<div class="ld-prepbox">
      <label>Tuning<input id="ld-tuning" maxlength="24" placeholder="standard" value=${ln.tuning || ''}
        onChange=${e => save({ tuning: e.target.value.trim() || null })} /></label>
      <label>Capo<input id="ld-capo" type="number" min="0" max="12" placeholder="—" value=${ln.capo || ''}
        onChange=${e => save({ capo: +e.target.value || null })} /></label>
      <label class="wide">Note for the band<input id="ld-note" maxlength="140" placeholder="Ju takes the acoustic · starts with the drum loop" value=${ln.note || ''}
        onChange=${e => save({ note: e.target.value.trim() || null })} /></label>
      <button class="mini" onClick=${() => setPrepOpen(false)}>Done</button>
    </div>` : ''}
    ${!pid ? html`<p class="muted ld-hint">No preset on this song yet — pick one (Preset), then set what it plays here.</p>`
    : missing ? html`<p class="muted ld-hint">The preset « ${esc(pid)} » is not on this rack — pick another (Preset), or pull it from golem.fm.</p>`
    : !preset ? html`<p class="muted ld-hint">Loading the preset…</p>`
    : html`
      <${SpecialRow} preset=${preset} backing=${ln.backing || null} set=${b => PER_SONG.includes(b.type) && lineSets(ln, b)}
        onPick=${pk => PER_SONG.includes(pk.b.type) ? setSheet(pk.b) : setPick(pk)} />
      ${/* L'ARRANGEMENT SE FAIT DANS SONGS (2026-09-30, « on a dit » — docs/songs.md §5) : ici il se LIT.
            Une ligne libre n'a pas encore de chanson : le lien la fait devenir une chanson, où il s'édite. */''}
      <div class=${cls('ld-arr', focus === 'arrangement' && 'seen')} ref=${arrRef}>
        ${((arr && arr.params && arr.params.sections) || []).length
          ? html`<${ArrRead} parts=${arr.params.sections} bpm=${meta.bpm || preset.bpm} preset=${preset}
              onEdit=${() => setMk(true)} editLabel="Make it a song to edit it" />`
          : html`<div class="arr-ro"><div class="arr-ro-hd"><b>Arrangement</b><span class="muted">no parts — the scenes change at your foot</span>
              <span class="grow"></span><button class="linkish" onClick=${() => setMk(true)}>Make it a song to lay them out ›</button></div></div>`}
      </div>`}
    ${pick ? html`<${PlayerCard} pick=${pick} from=${'the preset « ' + presetName + ' »'} editLabel="Change it in the Designer"
      onEdit=${() => openInDesigner(pid, 'cfg')} onClose=${() => setPick(null)} />` : ''}

    ${sheet ? html`<${SongBlockSheet} block=${sheet} ln=${ln} preset=${preset} catalog=${catalog} title=${meta.title || presetName}
        onOv=${ov => setOv(sheet, ov)} onBacking=${slug => save({ backing: slug || null })} onBpm=${v => { setMeta({ ...meta, bpm: v }); save({ bpm: v === '' ? null : +v }); }}
        onDesigner=${() => openInDesigner(pid, 'cfg')} onClose=${() => setSheet(null)} />` : ''}
    ${pickRig ? html`<div class="add-scrim" onClick=${() => setPickRig(false)}>
      <div class="add-menu sl-add" onClick=${e => e.stopPropagation()}>
        <b>Preset for « ${esc(meta.title || presetName)} » <small>pick a preset</small></b>
        <input class="search slg-q" placeholder="Search…" autofocus value=${q} onInput=${e => setQ(e.target.value)} />
        <div class="sl-add-list">
          ${list.map(p => html`<button class=${cls('row-btn', p.id === pid && 'on')} onClick=${() => { setPickRig(false); save({ preset: p.id }); }}>
            ${esc(p.name || p.id)}<small>${esc(p.id)}</small></button>`)}
          ${list.length ? '' : html`<p class="muted">No preset matches.</p>`}
        </div>
      </div></div>` : ''}
  </div>`;
}

// la ligne de valeur d'une tuile : ce qui se JOUE pour ce morceau (ligne, sinon rig)

// ── LA FEUILLE D'UN BLOC « PAR MORCEAU » (maquette ③) : on ne voit QUE ce qui appartient à la
// ligne. Le kit, le switch, la sortie restent dans le Designer — le bouton y mène.
// le choix du backing d'un MORCEAU : tout le catalogue étoilé sur golem.fm (pas seulement le cache —
// cas 2026-09-08 : deux chansons de Stone sur un preset, une seule en cache), les stems se
// tirent d'ici (« ⬇ Get stems », même chemin que la feuille du bloc dans le Designer).
function BackingPick({ ln, preset, onBacking }) {
  const { data, reload } = useAsync(() => fetch('/api/backing/catalog').then(r => r.json()).catch(() => null), []);
  const [dl, setDl] = useState(null);
  const pollRef = useRef(null);
  useEffect(() => () => clearInterval(pollRef.current), []);
  const list = (data || {}).songs || [];
  const rs = (((preset.backing || {}).songs) || [])[0];
  const dur = x => x.duration_sec ? Math.floor(x.duration_sec / 60) + ':' + String(Math.floor(x.duration_sec % 60)).padStart(2, '0') : '';
  const download = x => {
    fetch('/api/backing/dl', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ slug: x.slug }) });
    setDl(x.slug);
    pollRef.current = setInterval(async () => {
      const st = await fetch('/api/backing/dl/status').then(r => r.json()).catch(() => null);
      if (st && st.state !== 'busy') { clearInterval(pollRef.current); setDl(null); reload(); }
    }, 1200);
  };
  return html`
    <div class="sbs-row"><b>Backing track</b><small class="muted">${data && !data.online ? '⚠ golem.fm unreachable — cached songs only' : 'the songs starred for this band on golem.fm'}</small></div>
    <div class="sbs-list">
      <button class=${cls('row-btn sm', !ln.backing && 'on')} onClick=${() => onBacking('')}>
        ${rs ? 'the preset\'s own — ' + esc(rs.title || rs.slug) : 'No backing'}<small>${rs ? 'what the preset plays when the song says nothing' : 'the song plays without stems'}</small></button>
      ${list.map(x => html`<div class=${cls('sbs-song', x.slug === ln.backing && 'on', !x.cached && 'far')}>
        <button class="row-btn sm" disabled=${!x.cached} title=${x.cached ? 'use these stems for this song' : 'stems not on the rack yet — get them first'}
          onClick=${() => onBacking(x.slug)}>${esc(x.title || x.slug)}${x.artist ? ' — ' + esc(x.artist) : ''}
          <small>${dur(x)}${x.bpm ? ' · ' + x.bpm + ' bpm' : ''}${x.cached ? ' · ● on the rack' : ' · not on the rack'}</small></button>
        ${!x.cached ? html`<button class="mini" disabled=${dl === x.slug} onClick=${() => download(x)}>${dl === x.slug ? 'downloading…' : '⬇ Get stems'}</button>` : ''}
      </div>`)}
      ${data && !list.length ? html`<p class="muted">No song here — star the songs you play on golem.fm, and the rack lists them.</p>` : ''}
      ${!data ? html`<p class="muted">loading…</p>` : ''}
    </div>
    <p class="muted">A song without stems on golem.fm can't be picked: build its backing there first (star it, add the stems), it then shows up here.</p>`;
}

function SongBlockSheet({ block: b, ln, preset, catalog, title, onOv, onBacking, onBpm, onDesigner, onClose }) {
  const ov = ovOf(ln, b) || {};
  const d = SVC[b.type];
  const rigPrm = b.params || {};
  const setPrm = (k, v) => onOv({ ...ov, params: { ...(ov.params || {}), [k]: v } });
  const body = b.type === 'click' ? (() => {
    const on = ov.bypass != null ? !ov.bypass : !b.bypass;
    const beats = (ov.params || {}).beats || rigPrm.beats || 4, den = (ov.params || {}).den || rigPrm.den || 4;
    return html`
      <div class="sbs-row"><b>Plays on this song</b>
        <button class=${cls('chip', on && 'on')} onClick=${() => onOv({ ...ov, bypass: on })}>${on ? '◔ On' : 'Off'}</button>
        <small class="muted">preset: ${b.bypass ? 'off' : 'on'}</small></div>
      <div class="sbs-row"><b>Tempo</b><label class="ld-bpm">♩ <input type="number" min="20" max="400" value=${ln.bpm || ''} placeholder=${preset.bpm || 120}
          onChange=${e => onBpm(e.target.value)} /></label><small class="muted">empty = the preset's ${preset.bpm || 120}</small></div>
      <div class="sbs-row"><b>Beats per bar</b>${[2, 3, 4, 5, 6, 7].map(n => html`<button class=${cls('chip', beats === n && 'on')} onClick=${() => setPrm('beats', n)}>${n}</button>`)}</div>
      <div class="sbs-row"><b>Note value</b>${[4, 8].map(n => html`<button class=${cls('chip', den === n && 'on')} onClick=${() => setPrm('den', n)}>1/${n}</button>`)}</div>
      <p class="muted">Level and output are global (Settings). What the preset sets by default: ${rigPrm.beats || 4}/${rigPrm.den || 4}.</p>`; })()
  : b.type === 'sample' ? html`
      <div class="sbs-row"><b>Samples for this song</b><small class="muted">${ov.params && ov.params.samples ? 'this song has its own list' : 'showing the preset\'s list — any change makes a list for this song'}</small></div>
      <${SampleListEd} files=${(ov.params && ov.params.samples) || rigPrm.samples || []} onChange=${v => setPrm('samples', v)} />
      <p class="muted">Numbered ones cycle under the foot, in order; the arrangement can fire any of them.</p>`
  : b.type === 'backing-track' ? html`<${BackingPick} ln=${ln} preset=${preset} onBacking=${onBacking} />`
  : html`<p class="muted">Nothing to set per song.</p>`;
  const has = b.type === 'backing-track' ? !!ln.backing : !!ovOf(ln, b);
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card sbs">
      <button class="close" onClick=${onClose}>×</button>
      <h2>${d.ic} ${d.name} <span class="chip sbs-song">${esc(title)}</span></h2>
      <p class="sub">for this song${b.foot ? ' · switch ' + b.foot : ''} · the preset's own settings stay in the Designer</p>
      ${body}
      <div class="sbs-ft">
        <button class="mini" disabled=${!has} onClick=${() => b.type === 'backing-track' ? onBacking('') : onOv(null)}>↺ Reset to preset</button>
        <span class="grow"></span>
        <button class="mini" onClick=${() => { onClose(); onDesigner(); }}>Open the preset's ${d.name} in the Designer ›</button>
      </div>
    </div></div>`;
}


// ── UNE LIGNE DE BANK DE SONS (docs/patches.md §7) : un patch, rien d'autre — pas de preset, pas
// d'arrangement. On le joue, on l'ouvre dans le Designer, on le retire de la bank (jamais le patch lui-même).
function PatchLineDetail({ line, sl, patches, onMoved, onRemove, removeArmed }) {
  const [said, setSaid] = useState('');
  const [bankPick, setBankPick] = useState(false);
  // la POSITION de la ligne est sa bank (setlists.md §0) : on la montre, et on la choisit ici
  const slots = (sl && sl.presets) || [];
  const pid = line.patch ? 'patch:' + line.patch : null;
  const slot = pid ? slots.indexOf(pid) : -1;
  const moveTo = async (to) => {
    const n = [...slots]; while (n.length <= to) n.push('');
    const from = n.indexOf(pid);
    const there = n[to];
    n[to] = pid; if (from >= 0 && from !== to) n[from] = there || '';     // la case prise ÉCHANGE sa place
    while (n.length && !n[n.length - 1]) n.pop();
    // `post` de CETTE page rend déjà le JSON (en tête de fichier) : un second .json() levait, et la
    // pastille affichait « ✗ TypeError » après un déplacement pourtant écrit
    const r = await post('/api/setlists/' + encodeURIComponent(sl.id) + '/presets', { presets: n })
      .catch(e => ({ error: String(e) }));
    setBankPick(false);
    if (r && r.error) { setSaid('✗ ' + r.error); return; }
    setSaid('✓ bank #' + bankNo(to)); setTimeout(() => setSaid(''), 3000); onMoved && onMoved();
  };
  const play = async () => {
    const r = await fetch('/api/patches/' + encodeURIComponent(line.patch) + '/play', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(x => x.json()).catch(e => ({ error: String(e) }));
    setSaid(r && r.error ? '✗ ' + r.error : '▶ playing'); setTimeout(() => setSaid(''), 4000);
  };
  const open = async () => {
    const x = await fetch('/api/patches').then(r => r.json()).then(d => (d.patches || []).find(p => p.id === line.patch)).catch(() => null);
    if (x) openInDesigner(patchDraft(x));
  };
  // le patch tel qu'il JOUE (servi comme un preset) : ses scènes, ses stomps, ses players
  const { data: rig } = useAsync(() => line.patch ? fetch('/api/preset/' + encodeURIComponent('patch:' + line.patch)).then(r => r.ok ? r.json() : null).catch(() => null)
    : Promise.resolve(null), [line.patch]);
  const [pick, setPick] = useState(null);
  const role = rig && (rig.lanes || [])[0] ? rig.lanes[0].role : null;
  const bk = rig && rig.backing && (rig.backing.songs || [])[0];
  // MÊME PAGE QU'UNE LIGNE DE MORCEAU (2026-09-30) : la rangée Preset · Tempo · Tuning · Capo est GRISÉE
  // (un son n'a ni morceau, ni tempo, ni accordage de soirée), les blocs spéciaux sont là, et l'arrangement —
  // qu'un patch n'a pas (patch-as-preset §4 bis) — devient le lien vers « Make a song ».
  const facts = [{ k: 'Preset' }, { k: 'Tempo' }, { k: 'Tuning' }, { k: 'Capo' }];
  const mkSong = async () => { const r = await makeSongFromPatch(line.patch); if (r && r.error) setSaid('✗ ' + r.error); };
  return html`<div class="slo-detail pld">
    <div class="pld-hd">
      <span class="pld-ic">⛓</span><b class="pld-name">${esc(line.title || line.patch || '—')}</b>
      ${role ? html`<span class=${'pld-role r-' + role}>${role}</span>` : ''}
      ${pid ? html`<button class=${cls('bank-pill', 'on')} title=${'bank #' + bankNo(slot) + ' of « ' + (sl.name || sl.id) + ' » — tap to move'}
          onClick=${() => setBankPick(true)}>🎹 #${bankNo(slot)}<small>${sl.active ? 'on the foot' : 'not on the foot'}</small></button>` : ''}
      <span class="grow"></span>
      ${line.patch ? html`<button class="mini" onClick=${open}>✎ Edit in Designer ›</button>` : ''}
    </div>
    ${!line.patch ? html`<p class="muted">This patch was deleted: the slot stays, it plays nothing. Remove it, or add another patch.</p>`
    : html`
      <${FactRow} facts=${facts} off=${true} />
      <${SpecialRow} preset=${rig ? { ...rig, kind: 'patch' } : null} backing=${bk ? (bk.title || bk.slug) : null} onPick=${setPick} />
      <div class="arr-ro"><div class="arr-ro-hd"><b>Arrangement</b>
        <span class="muted">a patch has none — you change scenes at your foot</span>
        <span class="grow"></span><button class="linkish" onClick=${mkSong}>Create a preset with this patch ›</button></div></div>
      <span class="grow"></span>
      <div class="pld-acts">
        <button class="primary" onClick=${play}>▶ Play</button>
        ${said ? html`<span class=${cls('muted', said.startsWith('✗') && 'warn')}>${esc(said)}</span>` : ''}
        <span class="grow"></span>
        <button class=${cls('mini', removeArmed && 'danger')} title="remove from this list — the patch itself stays in your library"
          onClick=${onRemove}>${removeArmed ? 'remove? tap again' : '− Remove from list'}</button>
      </div>`}
    ${!line.patch ? html`<div class="pld-acts"><button class=${cls('mini', removeArmed && 'danger')} onClick=${onRemove}>${removeArmed ? 'remove? tap again' : '− Remove from list'}</button></div>` : ''}
    ${pick ? html`<${PlayerCard} pick=${pick} from=${'this patch'} editLabel="Change it in the Designer"
      onEdit=${() => open()} onClose=${() => setPick(null)} />` : ''}
    ${bankPick ? html`<${BankPicker} pid=${pid} banks=${slots} presets=${patches} footLines=${sl.lines}
        footName=${sl.name || sl.id} onFoot=${!!sl.active} sounds=${true} onPick=${slot2 => moveTo(slot2)} onClose=${() => setBankPick(false)} />` : ''}
  </div>`;
}

// ── « + Add a patch » : le sélecteur des patches de la bibliothèque, par instrument ────────────────────────
function PatchBankPicker({ sl, onClose, onAdded }) {
  const { data } = useAsync(() => fetch('/api/patches').then(r => r.json()).catch(() => ({ patches: [] })), []);
  const [err, setErr] = useState('');
  const have = new Set((sl.lines || []).map(l => l.patch).filter(Boolean));
  const list = ((data && data.patches) || []).slice().sort((a, b) => (a.role || '').localeCompare(b.role || '') || (a.name || '').localeCompare(b.name || ''));
  const add = async x => {
    const r = await fetch('/api/setlists/' + encodeURIComponent(sl.id) + '/patches', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [x.id] }) }).then(r => r.json()).catch(e => ({ error: String(e) }));
    if (r && r.error) setErr(r.error); else onAdded(r);
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card pbp">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Add a patch <small>to « ${esc(sl.name)} »</small></h2>
      ${err ? html`<p class="mode-err">✗ ${esc(err)}</p>` : ''}
      <div class="pbp-list">
        ${!data ? html`<p class="muted">…</p>` : !list.length ? html`<p class="muted">No patch yet — make one in Songs ▸ Patches.</p>`
          : list.map(x => html`<button class="row-btn pbp-row" disabled=${have.has(x.id)} onClick=${() => add(x)}>
              <b>⛓ ${esc(x.name || x.id)}</b><small>${esc(x.role || '')}${have.has(x.id) ? ' · already in this list' : ''}</small></button>`)}
      </div>
    </div></div>`;
}

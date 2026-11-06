// SPDX-License-Identifier: GPL-3.0-or-later
// Hub Songs — CE QUE TU JOUES (décision 2026-07-30, maquettes patches v2) : les objets
// quotidiens sortent de Library et remontent au niveau nav. Presets (le stock), Setlists
// (l'ordre de passage), Recordings (ce que le rack a produit — les prises perf-rec).
// Library garde CE QUE TU POSSÈDES (amplis, captures, kits, backings…). Le critère de la
// frontière : le sens du flux — importé = Library, produit = Songs.
// À venir ici : l'onglet Patches (le son d'un musicien, docs/patches.md) — Lots 2-3.
import { html, useState, useEffect, setTopIO, cls, go, useSubToolbar } from './lib.js';
import { IoModal } from './io-modal.js';
import { SetlistsPage } from './page-setlists.js';
import { PatchesPage } from './page-patches.js';
import { SetlistGroupsPage } from './page-setlist-groups.js';
import { RepertoirePage } from './page-repertoire.js';

// même grammaire que le SubHub de Library : l'URL #/songs/<sub> est la source de vérité,
// la barre de sous-onglets héberge la toolbar publiée par la page active (recherche/filtres).
// ordre décidé (2026-07-31) : Patches d'abord — la brique avant les morceaux.
// L'alias '' reste sur Presets : #/songs atterrit sur le STOCK (l'objet quotidien), l'onglet
// Patches est premier dans la barre sans devenir la page d'atterrissage.
const SUBS = [
  // ── LE RÉPERTOIRE EST PREMIER, ET C'EST L'ATTERRISSAGE (docs/songs.md, 2026-09-20) ──
  // La chanson est l'objet ; le patch, le preset et la setlist sont ses pièces. `#/songs` menait
  // au stock de presets faute de mieux — il mène maintenant à ce qu'on joue.
  { id: 'songs', alias: '', label: 'Songs', Page: RepertoirePage },
  { id: 'patches', label: 'Patches', Page: PatchesPage },
  { id: 'presets', label: 'Presets', Page: SetlistsPage },
  // « Banks & Setlists » (2026-10-08) : l'onglet tient les DEUX sortes de listes — banks de sons (⛓) et
  // setlists de morceaux (▤) ; chaque carte porte son étiquette BANK / SETLIST, les mots de /live
  { id: 'setlists', label: 'Banks & Setlists', Page: SetlistGroupsPage },
  // Recordings a QUITTÉ Songs (2026-09-15) : Library ▸ Tracks ▸ Recordings — une prise est un
  // matériau qui se joue (comme un stem ou une grille), Songs reste « ce que je joue »
];

export function SongsPage(props) {
  // Lot 6 (maquette M6) : le mode dit COMBIEN vous êtes, pas qui tu es — un mode peut masquer
  // des sous-onglets (ui.tabs.songs = liste blanche). Le mode CACHE, il ne détruit jamais :
  // un morceau lié à des patches se joue à l'identique, l'URL directe retombe sur Presets.
  const mode = (((props.rig || {}).state) || {}).mode || {};
  const allow = (mode.ui && mode.ui.tabs && mode.ui.tabs.songs) || null;
  const subs = allow ? SUBS.filter(s => allow.includes(s.id)) : SUBS;
  const [init, ...rest] = (props.sub || '').split('/');
  // URL legacy #/songs/recordings | #/songs/loops -> Library ▸ Tracks ▸ Recordings
  useEffect(() => { if (init === 'recordings' || init === 'loops') go('library/tracks/recordings'); }, [init]);
  const cur = subs.find(s => s.id === init || s.alias === init) || subs[0];
  const toolbar = useSubToolbar();
  // ⇅ I/O : les presets/setlists se sauvegardent ici aussi (même modal que Library,
  // famille pré-sélectionnée). Chrome de HUB -> slot I/O, jamais topAction (piège setTopAction).
  const [io, setIo] = useState(false);
  useEffect(() => {
    setTopIO(html`<button class="chip tb-io" title="import / export your songs (backups, vault)"
      onClick=${() => setIo(true)}>⇅ I/O</button>`);
    return () => setTopIO(null);
  }, []);
  return html`<div class="lib-subhub">
    <div class="lib-subtabs">
      ${subs.map(s => html`<button class=${cls('lib-subtab', s.id === cur.id && 'on')}
        onClick=${() => go('songs/' + s.id)}>${s.label}</button>`)}
      <div class="lib-toolbar">${toolbar}</div>
    </div>
    <div class="lib-subpage"><${cur.Page} rig=${props.rig} sub=${rest.join('/') || undefined} /></div>
  </div>
  ${io ? html`<${IoModal} family="presets" onClose=${() => setIo(false)} />` : ''}`;
}

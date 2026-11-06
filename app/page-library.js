// SPDX-License-Identifier: GPL-3.0-or-later
// Hub Library — CE QUE TU POSSÈDES : l'inventaire (amplis, captures, kits, IRs, backings),
// regroupé par RÔLE d'instrument (audit docs/library-audit.md). Les objets qu'on JOUE
// (presets, setlists, recordings) ont déménagé dans le hub ♫ Songs (décision 2026-07-30) —
// le critère de la frontière : importé = Library, produit = Songs.
import { html, HubPage, useState, useEffect, useAsync, setTopAction, setTopIO, post, cls, go, useSubToolbar } from './lib.js';
import { IoModal } from './io-modal.js';
import { AmpsPage } from './page-amps.js';
import { FxBlocksPage } from './page-fxblocks.js';
import { IRPage } from './page-ir.js';
import { KitsPage } from './page-kits.js';
import { SamplesPage } from './page-samples.js';
import { GroovesPage } from './page-grooves.js';
import { SynthPage } from './page-synth.js';
import { BackingPage } from './page-backing.js';
import { LoopsPage } from './page-loops.js';
import { OutboardPage } from './page-outboard.js';
import { KeysInstrumentsPage } from './page-keys-instruments.js';
import { MODEL_GEARS } from './designer-model.js';
import { StandardsPage } from './page-standards.js';

// Les briques du son par instrument : Guitar & Bass (Amps/Pedals/Cabs), Keys (Synths…),
// Drums (Kits/Grooves/Samples), Tracks (Backings/Standards — ce que le rack JOUE comme un
// morceau). URL à 2 niveaux : /library/<group>/<subtab>. Scalable (Keys/Drums grossiront).
// ── LES GROUPES (audit docs/archive/audit-library-2026-09-15.md, décisions le mainteneur du 15/09) ──────────────
// Tones = les captures (TONE3000), filtrées par RÔLE dans la sous-barre (Guitar · Bass · Voice) :
//   ce qu'un rôle peut charger vient de effects.json `role_categories` × MODEL_GEARS, la même
//   table que le tiroir du Designer et que golem.fm — une voix ne voit que l'outboard.
// Keys = les presets Vital (pas des packs TONE3000 : hors du filtre de rôle) + les INSTRUMENTS livrés
//   avec le rack (piano SFZ, e-piano DX7, orgue), en lecture seule.
// Drums = les batteries d'usine (lecture seule) · les kits de pads · les grooves.
// Samples = Short (one-shots) · Songs (fichiers longs, stems d'un backing local).
// Tracks = ce qui a une ligne de temps et se joue : les stems, les grilles, les prises.
// Songs reste « ce que je joue » : Patches · Presets · Setlists.
const GROUPS = [
  { id: 'tones', label: 'Tones', role: true, subs: [
    { id: 'amps', label: 'Amps', Page: AmpsPage },
    { id: 'pedals', label: 'Pedals', Page: FxBlocksPage },
    { id: 'cabs', label: 'Cabs', Page: IRPage },
    { id: 'outboard', label: 'Outboard', Page: OutboardPage },
  ] },
  { id: 'keys', label: 'Keys', subs: [
    { id: 'synth', label: 'Synths', Page: SynthPage },
    // ce que le rack LIVRE pour la lane Keys (piano SFZ, e-piano DX7, orgue) — lecture seule, comme Drums ▸ Drums
    { id: 'instruments', label: 'Instruments', Page: KeysInstrumentsPage },
  ] },
  { id: 'drums', label: 'Drums', subs: [
    { id: 'drums', label: 'Drums', Page: p => html`<${KitsPage} mode="drums" />` },
    { id: 'kits', label: 'Kits', Page: p => html`<${KitsPage} mode="kits" />` },
    { id: 'grooves', label: 'Grooves', Page: GroovesPage },
  ] },
  // Samples = un groupe à part (2026-09-15, aligné sur golem.fm) : deux natures d'un même fichier
  // audio local — Short (one-shots des pads, bloc Sample) · Songs (un fichier long : stem d'un backing
  // local, docs/samples-backings.md). Le type est CHOISI par l'onglet où l'on dépose.
  { id: 'samples', label: 'Samples', subs: [
    { id: 'short', label: 'Short', Page: p => html`<${SamplesPage} kind="short" />` },
    { id: 'songs', label: 'Songs', Page: p => html`<${SamplesPage} kind="song" />` },
  ] },
  { id: 'tracks', label: 'Tracks', subs: [
    { id: 'backing', label: 'Backings', Page: BackingPage },
    // les lignes Vocals (de l'audio et des paroles), comme la page Vocals de golem.fm (2026-10-16)
    { id: 'vocals', label: 'Vocals', Page: p => html`<${BackingPage} vocals=${true} />` },
    { id: 'standards', label: 'Standards', Page: StandardsPage },
    // les prises quittent Songs (2026-09-15) : une prise est un matériau qui se joue, pas un
    // geste de jeu — alias 'loops' = nom historique
    { id: 'recordings', alias: 'loops', label: 'Recordings', Page: LoopsPage },
  ] },
];
// URL legacy #/library/guitar/… (le groupe s'appelait « Guitar & Bass ») -> tones
const LEGACY_GROUP = { guitar: 'tones' };
const LEGACY_SUB = { 'drums/samples': 'samples/short' };

// ── le RÔLE du groupe Tones : ce qu'il peut charger = role_categories × MODEL_GEARS ────────────
export const TONE_ROLES = [['guitar', 'Guitar'], ['bass', 'Bass'], ['voice', 'Voice']];
export function gearsForRole(effects, role) {
  const rc = (effects && effects.role_categories) || {};
  const cats = rc[role];
  if (!Array.isArray(cats)) return null;                       // rôle absent (guitar) = tout
  const out = new Set();
  for (const e of (effects && effects.effects) || []) {
    if (!cats.includes(e.category)) continue;
    if (e.roles && !e.roles.includes(role)) continue;
    for (const g of MODEL_GEARS[e.type] || []) out.add(g);
  }
  return out;
}

// niveau 2 : barre de sous-onglets rendue DANS le corps du groupe. L'URL /library/<group>/<sub>
// reste la source de vérité (clic = go(), même règle que HubPage — sinon liens non recliquables).
function SubHub({ subs, base, sub, rig, roleSeg }) {
  const [init, ...rest] = (sub || '').split('/');
  const cur = subs.find(s => s.id === init || s.alias === init) || subs[0];
  const toolbar = useSubToolbar();                 // recherche/filtres publiés par la page active
  // l'ACTION de la page (+ Add / + New) est rendue dans la TOPBAR, à droite — la charte (2026-10-08), qui
  // renverse la règle 3 du 2026-09-18 (docs/ui-architecture.md). Les onglets du hub se resserrent pour la place.
  // segment de RÔLE (groupe Tones) : mémorisé entre les pages, jamais dans l'URL — c'est un filtre,
  // pas une entrée de menu (règle golem.fm « un hub = un niveau », reprise ici)
  const [role, setRole] = useState(() => { try { return localStorage.getItem('lib.tones.role') || 'guitar'; } catch (_e) { return 'guitar'; } });
  const pickRole = r => { setRole(r); try { localStorage.setItem('lib.tones.role', r); } catch (_e) { /* privé */ } };
  const { data: effects } = useAsync(() => roleSeg ? fetch('/api/effects').then(r => r.json()) : Promise.resolve(null), [roleSeg]);
  const gears = roleSeg ? gearsForRole(effects, role) : null;
  return html`<div class="lib-subhub">
    <div class="lib-subtabs">
      ${subs.map(s => html`<button class=${cls('lib-subtab', s.id === cur.id && 'on')}
        onClick=${() => go(base + '/' + s.id)}>${s.label}</button>`)}
      ${/* le segment de RÔLE vit DANS la barre de filtres, en tête (2026-10-09) : à part, il était centré sur la
            rangée des onglets — 2-3 px plus bas que les filtres — et restait collé à gauche quand la barre partait à droite */''}
      <div class="lib-toolbar">${roleSeg ? html`<div class="tb-seg lib-role" title="Which instrument is this for — the same rule as the Designer drawer">
        ${TONE_ROLES.map(([r, l]) => html`<button class=${cls(r === role && 'on')} onClick=${() => pickRole(r)}>${l}</button>`)}
      </div>` : ''}${toolbar}</div>
    </div>
    <div class="lib-subpage"><${cur.Page} rig=${rig} sub=${rest.join('/') || undefined} role=${roleSeg ? role : undefined} gears=${gears} /></div>
  </div>`;
}

// groupes sans sous-onglets (Presets) -> Page directe ; avec sous-onglets -> SubHub.
const TABS = GROUPS.map(g => g.subs
  ? { id: g.id, label: g.label,
      Page: p => html`<${SubHub} subs=${g.subs} base=${'library/' + g.id} sub=${p.sub} rig=${p.rig} roleSeg=${!!g.role} />` }
  : { id: g.id, label: g.label, Page: g.Page });

// ── chip topbar : miroir de TOUTE la lib vers golem.fm ──────
// Poussé automatiquement à chaque mutation du catalogue (bridge, débouncé) ;
// le chip montre l'état et permet un sync manuel. Absent si non appairé.
function TonesSyncChip() {
  const [s, setS] = useState(null);
  const busy = !!(s && ['build', 'packs', 'blobs'].includes(s.state));
  const load = () => fetch('/api/tones-sync').then(r => r.json()).then(setS).catch(() => {});
  useEffect(() => { load(); }, []);
  useEffect(() => {                                       // poll pendant un sync
    if (!busy) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [busy]);
  if (!s || !s.paired) return null;
  // « ☁ sync » (2026-10-24) : « ☁ ✓ 214 packs » allongeait la barre au point d'écraser ses onglets ; le nombre de packs
  // et l'heure passent au survol
  const label = busy ? `⏳ ${s.done}/${s.total || '…'}`
    : s.state === 'error' ? '☁ ✗ sync' : '☁ sync';       // « ☁ sync » reste lisible ; le détail est au survol
  const title = busy ? s.msg
    : s.state === 'error' ? 'golem.fm sync failed — ' + (s.error || '') + ' · tap to retry'
    : s.last ? `Library mirrored to golem.fm — ${s.last.packs} packs, ${s.last.at} (rev ${s.last.rev}) · tap to sync now`
    : 'Push the library to golem.fm';
  return html`<button class=${cls('chip', 'tones-sync', s.state === 'error' && 'err')}
    disabled=${busy} title=${title}
    onClick=${async () => { await post('/api/tones-sync').catch(() => {}); load(); }}>${label}</button>`;
}

// ── chip topbar : les PRÊTS du groupe (docs/library-loans.md) ──────
// Un coéquipier prête un son : il ne descend qu'à la demande (un preset qui le joue). Ce chip est le
// geste qui tire TOUT d'un coup — absent quand rien n'attend.
function LentChip() {
  const [s, setS] = useState(null);
  const run = !!(s && s.pull_all && s.pull_all.running);
  const load = () => fetch('/api/library/lent').then(r => r.json()).then(setS).catch(() => {});
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!run) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [run]);
  if (!s || (!s.pending && !run)) return null;
  const pa = s.pull_all || {};
  return html`<button class="chip tones-lent" disabled=${run}
    title="download all lent — sounds your bandmates lend to your bands download when a preset plays them; this gets them all now"
    onClick=${async () => { await post('/api/library/lent/pull-all').catch(() => {}); load(); }}>
    ${run ? `⏳ ${pa.done}/${pa.total}` : `⬇ Lent (${s.pending})`}</button>`;
}

export function LibraryPage(props) {
  // ⇅ I/O : import/export de contenu AU MÊME ENDROIT que le contenu (ex-Settings ▸ Content,
  // supprimé — décision 2026-07-24). La famille de l'onglet courant est pré-mise en avant.
  const [io, setIo] = useState(false);
  const famOfHash = () => {
    const seg = (location.hash || '').split('/').slice(2);   // #/library/<group>/<sub>
    // la catégorie de sauvegarde de l'onglet ouvert, cochée d'avance dans Export (refonte I/O, 2026-10-09)
    const map = { 'tones amps': 'amps', 'tones pedals': 'pedals', 'tones cabs': 'cabs', 'tones outboard': 'pedals',
                  'keys synth': 'synths', 'drums kits': 'kits', 'drums grooves': 'grooves', 'samples': 'kits',
                  'tracks recordings': 'recordings', 'tracks loops': 'recordings', 'tracks standards': 'standards' };
    return map[seg.join(' ')] || map[seg[0]] || null;
  };
  // ⚠ Le hub publiait le chip de sync dans setTopAction — LE MÊME SLOT que les pages utilisent
  // pour leur action (« + Add » des Presets, « + New setlist » des Setlists). Les effets du parent
  // s'exécutant APRÈS ceux de l'enfant, le hub écrasait systématiquement le bouton de la page :
  // ces boutons avaient purement disparu de l'écran (constaté 2026-07-28). I/O et sync sont de la
  // chrome de HUB, ils vivent donc ensemble dans le slot I/O ; `topAction` appartient à la PAGE.
  useEffect(() => {
    setTopIO(html`<${LentChip} /><${TonesSyncChip} />
      <button class="chip tb-io" title="import / export your content (backups, vault)"
        onClick=${() => setIo(true)}>⇅ I/O</button>`);
    return () => setTopIO(null);
  }, []);
  // URL legacy (#/library/guitar/…) : on réécrit, on ne casse pas
  useEffect(() => {
    const [g, ...rest] = (props.sub || '').split('/');
    if (LEGACY_GROUP[g]) go(['library', LEGACY_GROUP[g], ...rest].join('/'));
    else if (LEGACY_SUB[g + '/' + (rest[0] || '')]) go('library/' + LEGACY_SUB[g + '/' + rest[0]]);
  }, [props.sub]);
  return html`<${HubPage} tabs=${TABS} rig=${props.rig} initial=${props.sub} base="library" />
    ${io ? html`<${IoModal} family=${famOfHash()} onClose=${() => setIo(false)} />` : ''}`;
}

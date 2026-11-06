// SPDX-License-Identifier: GPL-3.0-or-later
// Hub Settings — LA BARRE (mockups/settings-nav.html, validée le 2026-10-20) : sept onglets, chacun un domaine.
//   Mode · System (Dashboard, Health) · Gear (Soundcard + Calibration) · Engines (Audio, Separation) ·
//   Content (Storage, Factory) · Connect (Wi-Fi, Devices, golem.fm, TONE3000) · About (version, mises à jour, licences)
// Avant : System · Soundcard · Network · Calibration · API · Licenses, et un System ▸ System à sept sous-onglets de
// natures différentes. Aucune fonction n'a été retirée : seules les places ont changé, et chaque ancienne adresse
// redirige (LEGACY) — les puces de /live, les liens de Health et les raccourcis de l'app continuent de marcher.
import { html, HubPage, go, cls, useState, useEffect, useAsync } from './lib.js';
import { SystemPage, ModePanel } from './page-system.js';
import { SoundcardPage } from './page-soundcard.js';
import { serviceBadges, withDemo } from './services-model.mjs';
import { NetworkPage } from './page-network.js';
import { DevicesPanel } from './page-devices.js';
import { PedalboardPage } from './page-pedalboard.js';
import { ApiPage } from './page-api.js';
import { LicensesPage } from './page-licenses.js';
import { EnginePanel } from './page-engine.js';
import { SeparationPage } from './page-separation.js';
import { StoragePage } from './page-storage.js';
import { FactoryPanel } from './page-factory.js';
import { healthDot } from './health-model.mjs';

// une barre de sous-onglets ; un clic ÉCRIT l'URL (la source de vérité, comme les onglets du hub)
function SubBar({ base, tabs, cur, badges, right }) {
  return html`<div class="sys-tabs sub-tabs">
    ${tabs.map(([id, label]) => { const b = badges && badges[id];
      return html`<button class=${cls('sys-tab', cur === id && 'on')} title=${b ? b.text || '' : ''}
        onClick=${() => go('system/' + base + '/' + id)}>${label}${b ? html`<i class=${'svc-dot ' + (b.kind || b)}></i>` : ''}</button>`; })}
    ${right || ''}
  </div>`;
}
const pick = (tabs, sub) => { const id = (sub || '').split('/')[0]; return tabs.some(([t]) => t === id) ? id : tabs[0][0]; };

// MODE, en tête (2026-10-20) — mockups/mode-page.html, C + E : la fiche d'un mode (#/system/mode) ou tous les
// modes côte à côte (#/system/mode/compare) ; le sélecteur de vue est dans la page (ModePanel)
function ModeTab({ rig, sub }) {
  const { data: sys } = useAsync(() => fetch('/api/system').then(r => r.json()), []);
  const desktop = sys && (sys.platform === 'win32' || sys.platform === 'darwin');
  return html`<div class="system pg-fit"><${ModePanel} rig=${rig} desktop=${desktop} platform=${sys && sys.platform}
    view=${sub === 'compare' ? 'compare' : 'detail'} /></div>`;
}

// GEAR : « mon matériel » — la carte son, puis les quatre sous-onglets de l'ancienne Calibration
const GEAR = [['sound', 'Soundcard'], ['controllers', 'Controllers'], ['pedals', 'Pedals'], ['board', 'Pedalboard'], ['drums', 'Drums']];
function GearPage({ rig, sub }) {
  const cur = pick(GEAR, sub);
  return html`<div class="system pg-fit">
    <${SubBar} base="gear" tabs=${GEAR} cur=${cur} />
    ${cur === 'sound' ? html`<${SoundcardPage} rig=${rig} />` : html`<${PedalboardPage} rig=${rig} sub=${cur} bare=${true} />`}
  </div>`;
}

// ENGINES : ce qui tourne quand golem est libre — l'audio, la séparation (sur cette machine seulement : les services
// payants en ligne et leur feuille de clés sont retirés de la v0.6, 2026-10-31 — l'ancienne adresse …/separation/keys
// ouvre la liste)
const ENGINES = [['audio', 'Audio'], ['separation', 'Separation']];
function EnginesPage({ rig, sub }) {
  const cur = pick(ENGINES, sub);
  return html`<div class="system pg-fit">
    <${SubBar} base="engines" tabs=${ENGINES} cur=${cur} />
    ${cur === 'audio' ? html`<${EnginePanel} rig=${rig} />` : html`<${SeparationPage} />`}
  </div>`;
}

// CONTENT : ce qu'il y a sur ce golem
const CONTENT = [['storage', 'Storage'], ['factory', 'Factory']];
function ContentPage({ sub }) {
  const cur = pick(CONTENT, sub);
  return html`<div class="system pg-fit">
    <${SubBar} base="content" tabs=${CONTENT} cur=${cur} />
    ${cur === 'factory' ? html`<${FactoryPanel} />` : html`<${StoragePage} />`}
  </div>`;
}

// CONNECT : comment ce golem parle au monde — le réseau, les appareils, les comptes liés (« API » était du vocabulaire
// de développeur)
const CONNECT = [['wifi', 'Wi-Fi'], ['devices', 'Devices'], ['golemfm', 'golem.fm'], ['tone3000', 'TONE3000']];
function ConnectPage({ rig, sub }) {
  const cur = pick(CONNECT, sub);
  const sb = serviceBadges(withDemo((rig || {}).state));
  return html`<div class="system pg-fit">
    <${SubBar} base="connect" tabs=${CONNECT} cur=${cur} badges=${{ golemfm: sb.fm, tone3000: sb.t3k }} />
    ${cur === 'wifi' ? html`<${NetworkPage} sub="connect" bare=${true} />`
      : cur === 'devices' ? html`<${DevicesPanel} />`
      : html`<${ApiPage} rig=${rig} sub=${cur === 'golemfm' ? 'mst' : 't3k'} bare=${true} />`}
  </div>`;
}

const TABS = [
  { id: 'mode', label: 'Mode', Page: ModeTab },
  { id: 'sys', label: 'System', Page: SystemPage },
  { id: 'gear', label: 'Gear', Page: GearPage },
  { id: 'engines', label: 'Engines', Page: EnginesPage },
  { id: 'content', label: 'Content', Page: ContentPage },
  { id: 'connect', label: 'Connect', Page: ConnectPage },
  { id: 'about', label: 'About', Page: LicensesPage },
];

// LES ANCIENNES ADRESSES — chacune vers sa nouvelle place. Les liens des docs, des messages et de golem.fm vers
// #/system/… restent bons ; une adresse inconnue ouvre le hub comme avant.
const LEGACY = [
  [/^sep$/, 'engines/separation'], [/^health$/, 'sys/health'],
  [/^sys\/mode$/, 'mode'], [/^sys\/audio-engine$/, 'engines/audio'], [/^sys\/separation$/, 'engines/separation'],
  [/^sys\/(storage|folders)$/, 'content/storage'], [/^sys\/factory$/, 'content/factory'], [/^sys\/devices$/, 'connect/devices'],
  [/^sound$/, 'gear/sound'], [/^pedal$/, 'gear/controllers'], [/^pedal\/(controllers|pedals|board|drums)$/, m => 'gear/' + m[1]],
  [/^net(\/connect)?$/, 'connect/wifi'], [/^net\/devices$/, 'connect/devices'],
  [/^api(\/t3k)?$/, 'connect/tone3000'], [/^api\/mst$/, 'connect/golemfm'], [/^api\/sep$/, 'engines/separation'],
  [/^lic$/, 'about/golem'], [/^lic\/(golem|reaper|libs)$/, m => 'about/' + m[1]],
];
export const legacyRoute = sub => {
  for (const [re, to] of LEGACY) { const m = re.exec(sub || ''); if (m) return typeof to === 'function' ? to(m) : to; }
  return null;
};

// About : une pastille quand une release plus récente est connue de cette machine (les tags déjà présents — aucun
// réseau ici ; « Check again » dans About va les chercher). Une information, pas une alerte.
function useUpdateDot() {
  const [dot, setDot] = useState(null);
  useEffect(() => { fetch('/api/system/update').then(r => r.json())
    .then(u => setDot(u && u.status === 'update-available' ? { kind: 'info', text: (u.latest || 'a new version') + ' is available' } : null)).catch(() => {}); }, []);
  return dot;
}

export const SystemePage = props => {
  const to = legacyRoute(props.sub);
  if (to) { go('system/' + to); return null; }
  return html`<${SystemeHub} ...${props} />`;
};
function SystemeHub(props) {
  const upd = useUpdateDot();
  const st = (props.rig || {}).state;
  return html`<${HubPage} tabs=${TABS} rig=${props.rig} initial=${props.sub} base="system"
    badges=${{ connect: serviceBadges(withDemo(st)).api, sys: (healthDot(st) || {}).badge, about: upd ? 'info' : null }} />`;
}

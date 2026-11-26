// SPDX-License-Identifier: GPL-3.0-or-later
// Companion ▸ SYSTEM (docs/devices-people.md §5, maquettes validées le 2026-11-26, S1-S5). Pas le Settings du rack :
// quatre pages — This golem (ses adresses, pour ouvrir golem sans connexion), Pair a device, golem.fm (appairer le
// rack), Account (se connecter avec golem.fm). Ce qui demande un droit le dit sur sa ligne, AVANT qu'on tape : les
// droits viennent de whoami.rights (auth.rights_of), jamais recopiés ici.
import { html, useState, useEffect, useRef, post, cls } from './lib.js';

const api = p => fetch(p).then(r => { if (!r.ok) throw new Error(p); return r.json(); });
const errOf = e => (e && e.body && e.body.error) || String((e && e.message) || e);
const mmss = s => Math.floor(Math.max(0, s) / 60) + ':' + String(Math.floor(Math.max(0, s) % 60)).padStart(2, '0');

function Copy({ text }) {
  const [ok, setOk] = useState(false);
  const copy = () => {
    const done = () => { setOk(true); setTimeout(() => setOk(false), 1500); };
    try { navigator.clipboard.writeText(text).then(done, () => {}); } catch (_) { /* http hors localhost : pas de presse-papiers */ }
  };
  return html`<div class="cs-url"><span>${text}</span><button class="c-mini" onClick=${copy}>${ok ? 'Copied' : 'Copy'}</button></div>`;
}

// une matrice 0/1 (/api/golemfm/pair) dessinée en SVG — même forme que Settings ▸ Connect ▸ golem.fm
const QrMatrix = ({ m }) => !m || !m.length ? '' : html`<svg class="cs-qr" viewBox=${'0 0 ' + m.length + ' ' + m.length} shape-rendering="crispEdges">
  <rect width="100%" height="100%" fill="#fff" />${m.map((row, y) => row.map((v, x) => v ? html`<rect x=${x} y=${y} width="1" height="1" fill="#000" />` : ''))}</svg>`;

const Crumb = ({ title, onBack }) => html`<div class="cc-crumb"><button class="c-mini" onClick=${onBack}>‹ System</button><b>${title}</b></div>`;

// ── S1 · LE MENU ──
function Menu({ who, rights, local, go, fm }) {
  const dev = (who && who.device) || {};
  const signed = rights && rights.signed_in;
  return html`<div class="c-page">
    <div class="cs-acc"><span class="cs-av">${local ? '⌂' : signed ? (dev.person_name || '?').charAt(0).toUpperCase() : '?'}</span>
      <div><b>${local ? "The rack's own screen" : signed ? 'Signed in with golem.fm' : 'Not signed in'}</b>
        <small>${local ? 'everything is allowed here' : (dev.name || 'this phone') + (dev.conductor || dev.admin ? ' · conductor' : '') + (signed && rights.band_role ? ' · ' + rights.band_role : '')}</small></div></div>
    <div class="cs-menu">
      <button class="cs-mi" onClick=${() => go('connect')}><span class="ic">ⓘ</span><div><b>This golem</b><small>its addresses on this network</small></div><em>›</em></button>
      ${local ? '' : html`<button class="cs-mi" onClick=${() => go('display')}><span class="ic">▭</span><div><b>Display</b>
        <small>phone display, or the tablet display sideways</small></div><em>›</em></button>`}
      <button class="cs-mi" onClick=${() => go('pair')}><span class="ic">＋</span><div><b>Pair a phone or tablet</b><small>a QR to scan with the other device</small></div>
        ${rights && rights.pair_devices ? html`<em>›</em>` : html`<span class="cs-need">OWNER</span>`}</button>
      <button class="cs-mi" onClick=${() => go('golem.fm')}><span class="ic">◎</span><div><b>golem.fm</b>
        <small>${!fm ? 'checking…' : fm.paired ? 'this golem is paired' : 'pair this golem with golem.fm'}</small></div>
        <span class=${cls('cs-need', fm && fm.paired && 'ok')}>${!fm ? '' : fm.paired ? 'ON' : 'OFF'}</span></button>
      ${local ? '' : html`<button class="cs-mi" onClick=${() => go('account')}><span class="ic">→</span><div><b>${signed ? 'Account' : 'Sign in with golem.fm'}</b>
        <small>${signed ? 'what this phone can do' : "unlocks pairing for the band's owner"}</small></div><em>›</em></button>`}
    </div>
    <p class="c-sub pad cc-push">The rest of the settings live on the rack screen or the tablet.</p>
  </div>`;
}

// ── S2 · THIS GOLEM (« la page /connect ») ──
function ThisGolem({ st, back }) {
  const [w, setW] = useState(null);
  const [sys, setSys] = useState(null);
  useEffect(() => { api('/api/connect/where').then(setW).catch(() => setW({}));
    api('/api/system').then(setSys).catch(() => setSys({})); }, []);
  const urls = (w && w.urls) || [];
  const ip = (urls.find(u => /^http:\/\/\d/.test(u)) || '').replace(/^http:\/\/|:\d+$/g, '');
  const wifi = (w && w.wifi) || {};
  const plate = sys && sys.serial;
  return html`<div class="c-page">
    <${Crumb} title="This golem" onBack=${back} />
    <div class="c-card"><div class="cs-kv">
      <span>Name</span><b>${(plate && (plate.label || plate.name)) || (w && w.name) || '…'}</b>
      <span>Mode</span><b>${(st.mode || {}).name || '—'}</b>
      <span>Network</span><b>${wifi.ap ? 'its own Wi-Fi “' + (wifi.ap_ssid || 'golem') + '”' : wifi.ssid ? 'Wi-Fi “' + wifi.ssid + '”' : w ? 'wired or unknown' : '…'}</b>
      <span>IP</span><b>${ip || (w ? '—' : '…')}</b>
      ${w && w.host ? html`<span>Name on the network</span><b>${w.host}</b>` : ''}
    </div></div>
    <span class="c-lbl pad">Open golem on this network, no sign-in</span>
    ${urls.length ? [...urls].sort((a, b) => (/\.local/.test(b) ? 1 : 0) - (/\.local/.test(a) ? 1 : 0)).map(u => html`<${Copy} text=${u} />`)
      : html`<p class="c-sub pad">${w ? 'No address found. Is the rack on a network?' : 'Loading…'}</p>`}
    <p class="c-sub pad">The name follows the golem from home to the gig. If a phone can't open it, use the IP. A new phone still needs a pass: pair it from “Pair a phone or tablet”, or from golem.fm/connect.</p>
  </div>`;
}

// ── DISPLAY : l'affichage de CE téléphone (docs/devices-people.md §4 ter) ──
function DisplayPage({ back }) {
  const [err, setErr] = useState('');
  const pick = async d => {
    setErr('');
    try { await post('/api/auth/display', { display: d }); if (d === 'tablet') location.replace('/app/m.html'); }
    catch (e) { setErr(errOf(e)); }
  };
  return html`<div class="c-page">
    <${Crumb} title="Display" onBack=${back} />
    <div class="cs-menu">
      <button class="cs-mi" onClick=${back}><span class="ic">📱</span><div><b>Phone display</b><small>the Companion: upright, one hand. This is the current display.</small></div><span class="cs-need ok">ON</span></button>
      <button class="cs-mi" onClick=${() => pick('tablet')}><span class="ic">▭</span><div><b>Tablet display</b><small>the full golem app, sideways and smaller. The 📱 button in a corner brings you back.</small></div><em>›</em></button>
    </div>
    <p class="c-sub pad">The display never changes what this phone may do: loading songs, scenes and stomps still need the conductor right.</p>
    ${err ? html`<p class="c-err">${err}</p>` : ''}
  </div>`;
}

// ── S3 · PAIR A DEVICE ──
function PairDevice({ rights, back, goAccount }) {
  const [kind, setKind] = useState('Phone');
  const [band, setBand] = useState(null);
  const [who, setWho] = useState(null);           // id du roster, ou 'guest'
  const [guest, setGuest] = useState('');
  const [disp, setDisp] = useState('phone');
  const [inv, setInv] = useState(null);
  const [err, setErr] = useState('');
  const [, tick] = useState(0);
  useEffect(() => { api('/api/band').then(setBand).catch(() => setBand({})); }, []);
  useEffect(() => { if (!inv) return; const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t); }, [inv]);
  if (!rights || !rights.pair_devices) return html`<div class="c-page">
    <${Crumb} title="Pair a device" onBack=${back} />
    <div class="cc-lock"><i>🔒</i><div><b>Only the band's owner can pair a device.</b>
      <span>Sign in with golem.fm as the owner or an admin of the band, or pair it from the rack screen (Settings ▸ Connect ▸ Devices).</span></div></div>
    <button class="c-btn wide" onClick=${goAccount}><b>Sign in with golem.fm</b></button></div>`;
  const people = ((band && band.band) || {}).people || [];
  const create = async () => {
    setErr('');
    const body = kind === 'Tablet' ? { kind } : { kind, display: disp, ...(who === 'guest' ? { guest: guest.trim(), days: 1 } : { person: who }) };
    try { const r = await post('/api/auth/devices', body); setInv({ ...r, at: Date.now() / 1000 }); }
    catch (e) { setErr(errOf(e)); }
  };
  const left = inv ? 15 * 60 - (Date.now() / 1000 - inv.at) : 0;
  return html`<div class="c-page">
    <${Crumb} title="Pair a device" onBack=${back} />
    ${inv ? html`
      <div class="c-card cs-center"><span class="c-lbl">${inv.name || kind} · scan with the other device</span>
        <img class="cs-qr" src=${'/api/auth/qr?invite=' + encodeURIComponent(inv.id)} alt="pairing QR code" />
        <span class="c-sub">${left > 0 ? 'Expires in ' + mmss(left) + '. It works once.' : 'Expired. Make a new one.'}</span></div>
      <button class="c-btn wide" onClick=${() => setInv(null)}><b>${left > 0 ? 'Done' : 'New QR'}</b></button>`
    : html`
      <div class="c-seg">${[['Phone', '📱 Phone'], ['Tablet', '▭ Tablet']].map(([k, lb]) => html`<button class=${cls(kind === k && 'on')} onClick=${() => setKind(k)}>${lb}</button>`)}</div>
      ${kind === 'Phone' ? html`<span class="c-lbl pad">Who is it for?</span>
        <div class="c-list">${people.map(p => html`<button class=${cls('c-row', 'cc-tap', who === p.id && 'cur')} onClick=${() => setWho(p.id)}>
            <span class="cc-t">${p.name}</span><small>${(p.roles || []).join(' · ')}</small></button>`)}
          <button class=${cls('c-row', 'cc-tap', who === 'guest' && 'cur')} onClick=${() => setWho('guest')}><span class="cc-t">A guest…</span><small>1 day</small></button></div>
        ${who === 'guest' ? html`<input class="cs-in" id="guest-name" placeholder="First name" value=${guest} onInput=${e => setGuest(e.target.value)} />` : ''}
        <span class="c-lbl pad">Display on that phone</span>
        <div class="c-seg">${[['phone', 'Phone display'], ['tablet', 'Tablet display']].map(([k, lb]) => html`<button class=${cls(disp === k && 'on')} onClick=${() => setDisp(k)}>${lb}</button>`)}</div>
        ${disp === 'tablet' ? html`<p class="c-sub pad">The full app, sideways and smaller. It can switch back in System ▸ Display.</p>` : ''}`
      : html`<p class="c-sub pad">A tablet opens the full golem app. It belongs to the band, not to a person.</p>`}
      ${err ? html`<p class="c-err">${err}</p>` : ''}
      <button class="c-start cc-push" disabled=${kind === 'Phone' && (!who || (who === 'guest' && !guest.trim()))} onClick=${create}>
        <b>Show the QR</b><small>VALID 15 MIN · ONE DEVICE</small></button>`}
  </div>`;
}

// ── S4 · GOLEM.FM : appairer le rack ──
function GolemFm({ rights, back, fm, reloadFm }) {
  const [pair, setPair] = useState(null);
  const [err, setErr] = useState('');
  const poll = useRef(null);
  useEffect(() => () => clearInterval(poll.current), []);
  const start = async () => {
    setErr('');
    try {
      const d = await post('/api/golemfm/pair', { device_name: 'golem rack' });
      if (!d || !d.ok) { setErr((d && d.error) || 'golem.fm did not answer'); return; }
      setPair(d);
      clearInterval(poll.current);
      poll.current = setInterval(async () => {
        const s = await api('/api/golemfm/pair/status').catch(() => null);
        if (s && s.approved) { clearInterval(poll.current); setPair(null); reloadFm(); }
        else if (s && !s.active) { clearInterval(poll.current); setPair(null); setErr('The code expired. Start again.'); }
      }, 2000);
    } catch (e) { setErr(errOf(e)); }
  };
  const can = rights && rights.pair_golemfm;
  return html`<div class="c-page">
    <${Crumb} title="golem.fm" onBack=${back} />
    <div class="c-card"><span class="c-lbl">This golem</span>
      <div class=${cls('c-big', fm && (fm.paired ? 'cs-ok' : 'cs-warn'))}>${!fm ? 'Checking…' : fm.paired ? 'Paired' : 'Not paired'}</div>
      <span class="c-sub">${fm && fm.paired ? (fm.reachable === false ? "golem.fm can't be reached right now. The rack keeps playing." : "It gets the band's songs and patches, sends its takes, and shows up on golem.fm/connect.")
        : "Paired, it gets the band's songs and patches, sends its takes, and shows up on golem.fm/connect."}</span></div>
    ${pair ? html`
      <div class="c-card cs-center"><span class="c-lbl">Code</span><div class="cs-code">${pair.code}</div>
        <span class="c-sub">Approve it on golem.fm, signed in as the person who will own this golem.</span></div>
      <a class="c-start cs-link" href=${pair.approve_url} target="_blank" rel="noopener"><b>Approve on golem.fm</b><small>OPENS GOLEM.FM IN THIS BROWSER</small></a>
      <details class="cs-more"><summary>Approve from another device</summary><${QrMatrix} m=${pair.qr} /></details>
      <p class="c-sub pad">Waiting for the approval…</p>`
    : can ? html`<button class="c-start" onClick=${start}><b>${fm && fm.paired ? 'Pair again' : 'Pair this golem'}</b>
        <small>${fm && fm.paired ? 'REPLACES THE CURRENT LINK' : 'A CODE TO APPROVE ON GOLEM.FM'}</small></button>`
    : html`<div class="cc-lock"><i>🔒</i><div><b>${fm && fm.paired ? "Only the band's owner can pair this golem again." : 'Only a conductor or the owner can pair this golem.'}</b>
        <span>Sign in with golem.fm as the band's owner, or do it on the rack screen (Settings ▸ Connect ▸ golem.fm).</span></div></div>`}
    ${err ? html`<p class="c-err">${err}</p>` : ''}
  </div>`;
}

// ── S5 · ACCOUNT : se connecter avec golem.fm ──
const RIGHTS_ROWS = [
  ['Watch the song, lyrics, your lines', () => true, 'paired'],
  ['Your pedals, marks in the take', () => true, 'paired'],
  ['Load songs, scenes, stomps', r => r.control, 'conductor'],
  ['Pair a phone or tablet', r => r.pair_devices, 'owner'],
  ['Pair this golem with golem.fm', r => r.pair_golemfm, 'owner'],
];
function Account({ who, rights, back, reload, fm }) {
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const dev = (who && who.device) || {};
  const signed = rights && rights.signed_in;
  const signIn = async () => {
    setErr(''); setBusy(true);
    try { const r = await post('/api/auth/signin', {}); location.href = r.url; }
    catch (e) { setErr(errOf(e)); setBusy(false); }
  };
  const signOut = async () => { setErr(''); try { await post('/api/auth/signout', {}); reload(); } catch (e) { setErr(errOf(e)); } };
  return html`<div class="c-page">
    <${Crumb} title="Account" onBack=${back} />
    <div class="cs-acc"><span class="cs-av">${signed ? (dev.person_name || '?').charAt(0).toUpperCase() : '?'}</span>
      <div><b>${signed ? (dev.person_name || 'Signed in') : 'Not signed in'}</b>
        <small>${signed ? 'golem.fm · ' + (rights.band_role || 'member') + ' of the band' : 'paired as “' + (dev.name || 'this phone') + '”'}</small></div></div>
    <span class="c-lbl pad">What this phone can do</span>
    <div class="cs-rights">${RIGHTS_ROWS.map(([lb, f, need]) => { const ok = !!(rights && f(rights));
      return html`<div class="cs-rg"><span>${lb}</span><b class=${ok ? 'cs-ok' : 'cs-no'}>${ok ? '✓' : '—'} ${need}</b></div>`; })}</div>
    ${err ? html`<p class="c-err">${err}</p>` : ''}
    ${signed ? html`<p class="c-sub pad">Signed in until ${new Date(rights.signed_until * 1000).toLocaleDateString()}. Signing out keeps this phone paired.</p>
        <button class="c-btn wide cc-push" onClick=${signOut}><b>Sign out</b><small>keeps the pairing</small></button>`
      : html`<p class="c-sub pad">golem.fm tells the rack who you are. The band's owner can then pair devices and golem.fm from this phone. Playing never needs it.</p>
        <button class="c-start cc-push" disabled=${busy || (fm && !fm.paired)} onClick=${signIn}>
          <b>Sign in with golem.fm</b><small>${fm && !fm.paired ? 'PAIR THIS GOLEM WITH GOLEM.FM FIRST' : 'YOU COME BACK HERE'}</small></button>`}
  </div>`;
}

export function SystemPage({ st, who, local, page, setPage, reloadWho }) {
  const rights = local ? { control: true, pair_devices: true, pair_golemfm: true } : ((who && who.rights) || {});
  const [fm, setFm] = useState(null);
  const loadFm = () => api('/api/golemfm/status').then(setFm).catch(() => setFm({}));
  useEffect(() => { loadFm(); }, []);
  const back = () => setPage(null);
  if (page === 'connect') return html`<${ThisGolem} st=${st} back=${back} />`;
  if (page === 'display' && !local) return html`<${DisplayPage} back=${back} />`;
  if (page === 'pair') return html`<${PairDevice} rights=${rights} back=${back} goAccount=${() => setPage('account')} />`;
  if (page === 'golem.fm') return html`<${GolemFm} rights=${rights} back=${back} fm=${fm} reloadFm=${() => { loadFm(); reloadWho(); }} />`;
  if (page === 'account' && !local) return html`<${Account} who=${who} rights=${rights} back=${back} reload=${reloadWho} fm=${fm} />`;
  return html`<${Menu} who=${who} rights=${rights} local=${local} go=${setPage} fm=${fm} />`;
}

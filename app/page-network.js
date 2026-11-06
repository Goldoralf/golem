// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Network (hub Settings) — WiFi du rack : station + AP, joignabilité, QR tablette.
// CÂBLÉ sur le bridge (routes_network.py) : GET /api/network (+scan/known/qr),
// POST join/confirm/forget/ap. Les mutations passent par le wrapper sudo
// /usr/local/sbin/golem-net (provision/setup-net-sudo.sh) — sur une machine de
// dev sans wrapper, elles échouent proprement (bandeau d'erreur), rien ne
// bascule le WiFi. Le QR scannable est généré par le bridge (SVG, pas de CDN).
//
// DEUX SOUS-ONGLETS (2026-10-03 : « je ne saisis plus la différence entre Network et Remote
// devices ») : Connect = COMMENT on joint GoleM (WiFi, point d'accès, adresse, QR) ; Devices = QUI a le
// droit d'entrer (les appareils appairés — l'ancien Settings ▸ Connect ▸ Devices, déménagé ici).
import { html, useState, useEffect, useRef, cls, go } from './lib.js';
import { DevicesPanel } from './page-devices.js';

const NET_TABS = [['connect', 'Connect'], ['devices', 'Devices']];

export function NetworkPage({ sub, bare }) {
  const tab = NET_TABS.some(([id]) => id === sub) ? sub : 'connect';
  // `bare` : Connect porte la barre (Wi-Fi · Devices · golem.fm · TONE3000 — mockups/settings-nav.html)
  return html`<div class="net-hub pg-fit">
    ${bare ? '' : html`<div class="sys-tabs sub-tabs">
      ${NET_TABS.map(([id, label]) => html`<button class=${cls('sys-tab', tab === id && 'on')}
        onClick=${() => go('system/net/' + id)}>${label}</button>`)}
    </div>`}
    ${tab === 'devices' ? html`<${DevicesPanel} />` : html`<${ConnectPanel} />`}
  </div>`;
}

const jfetch = async (url, opts) => {
  const r = await fetch(url, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const post = (url, body) => jfetch(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
});

// barres de signal (0-100 -> 4 barres)
const Bars = ({ v }) => html`<span class="net-bars">${[25, 50, 75, 95].map(t =>
  html`<i class=${cls('net-bar', v >= t && 'on')}></i>`)}</span>`;

function ConnectPanel() {
  const [net, setNet] = useState(null);                 // GET /api/network
  const [scan, setScan] = useState([]);                 // GET /api/network/scan
  const [known, setKnown] = useState([]);               // GET /api/network/known
  const [scanning, setScanning] = useState(false);
  const [scanOpen, setScanOpen] = useState(null);       // ssid du formulaire mdp ouvert
  const [joinPw, setJoinPw] = useState('');
  const [reveal, setReveal] = useState(false);          // afficher le mdp de l'AP
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [apDraft, setApDraft] = useState(null);         // édition SSID/mdp AP non appliquée
  const [qrKey, setQrKey] = useState(0);                // cache-bust du QR après édition AP
  const alive = useRef(true);

  const refresh = async () => {
    try {
      const s = await jfetch('/api/network');
      // une lecture vide (pas de nmcli, pas de radio) n'a pas de `ap` : `net.ap.up` faisait planter la page et
      // l'app restait bloquée dessus (2026-10-31) — on pose une forme sûre
      if (alive.current) setNet({ ...(s || {}), ap: { up: false, ...((s && s.ap) || {}) }, station: (s && s.station) || {} });
    } catch (e) { if (alive.current) setErr(String(e.message || e)); }
  };
  const refreshKnown = async () => {
    try { const k = await jfetch('/api/network/known'); if (alive.current) setKnown(k.known || []); }
    catch { /* nmcli absent : liste vide */ }
  };
  const doScan = async () => {
    setScanning(true);
    try { const s = await jfetch('/api/network/scan'); if (alive.current) setScan(s.networks || []); }
    catch (e) { setErr(String(e.message || e)); }
    finally { if (alive.current) setScanning(false); }
  };

  useEffect(() => {
    alive.current = true;
    refresh(); refreshKnown(); doScan();
    const id = setInterval(refresh, 5000);
    return () => { alive.current = false; clearInterval(id); };
  }, []);

  const act = fn => async (...a) => {
    setErr(null); setBusy(true);
    try { await fn(...a); await refresh(); await refreshKnown(); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const joinNet = act(async (ssid) => {
    await post('/api/network/join', { ssid, psk: joinPw || undefined });
    setScanOpen(null); setJoinPw('');
  });
  const confirmNet = act(() => post('/api/network/confirm'));
  const forget = act(name => post('/api/network/forget', { name }));
  const toggleAp = act(() => post('/api/network/ap', { on: !(net && net.ap.up) }));
  const openFirewall = act(() => post('/api/network/open'));
  const applyAp = act(async () => {
    await post('/api/network/ap', { on: !!(net && net.ap.up), ...apDraft });
    setApDraft(null); setQrKey(k => k + 1);
  });

  // LA PAGE D'ABORD, LES VALEURS ENSUITE (2026-10-03) : la 1re lecture de l'état réseau prend
  // quelques secondes (sous Windows : netsh + PowerShell), et l'écran restait vide sur « Loading network
  // state… ». La page se dessine tout de suite, avec un état « en cours » : badges qui pulsent, gestes
  // inactifs, aucun bandeau affirmé tant que rien n'est su. Le scan et les QR partent en parallèle.
  const loading = !net;
  const n = net || { ap: { up: false, ssid: '', clients: 0 }, station: {}, eth: {}, nm_available: true,
                     reachable: [], golem: null };
  const ap = { ssid: (apDraft && apDraft.ssid != null) ? apDraft.ssid : n.ap.ssid,
               psk: (apDraft && apDraft.psk != null) ? apDraft.psk : '' };
  // Windows (bridge/desktop_network.py) : le WiFi et le point d'accès mobile de Windows ; pas de badge
  // Ethernet (le rack s'en sert comme porte de secours, un poste n'en a pas besoin) — inconnu tant que ça charge
  const win = !!n.windows;
  // macOS (2026-10-04, docs/platforms.md M4) : le WiFi appartient à macOS, GoleM ne le pilote pas —
  // la page dit OÙ on joint GoleM (adresse, QR) et ce qui l'en empêche, sans offrir de geste que le bridge refuse
  const mac = !!n.macos;
  const reach = loading
    ? [{ k: 'sta', label: 'WiFi', hint: 'on the LAN' }, { k: 'ap', label: 'Access Point', hint: 'tablet direct' }]
      .map(b => ({ ...b, on: false, pending: true, detail: 'checking…' }))
    : mac ? [{ k: 'sta', on: !!n.station.ip, label: 'Network', detail: n.station.ip || 'off network', hint: 'set in macOS' }]
    : reach0();
  // le reste de la page lit `net` : pendant le chargement, le squelette en tient lieu
  return renderConnect({ net: n, loading, ap, win, mac, reach });

  function reach0() {
  return [
      ...(win ? [] : [{ k: 'eth', on: n.eth.up, label: 'Ethernet', detail: n.eth.up ? n.eth.ip : 'unplugged', hint: 'admin access, always' }]),
      { k: 'sta', on: !!n.station.ssid, label: win ? 'WiFi' : 'Station', detail: n.station.ssid ? `${n.station.ssid} · ${n.station.ip || ''}` : 'off network', hint: 'on the LAN' },
      { k: 'ap', on: n.ap.up, label: 'Access Point', detail: n.ap.up ? `${n.ap.ssid}${n.ap.ip ? ' · ' + n.ap.ip : ''}` : 'off', hint: win ? 'Windows mobile hotspot' : 'tablet direct' },
    ];
  }

  function renderConnect({ net, loading, ap, win, mac, reach }) {
  return html`<div class=${cls('net', 'pg-fit', loading && 'net-loading')}>
    <div class="net-head">
      <div class="net-reach">
        ${reach.map(b => html`<div class=${cls('net-badge', b.pending ? 'pending' : b.on ? 'on' : 'off')}>
          <span class="net-dot"></span>
          <div class="net-badge-tx"><b>${b.label}</b><span>${b.detail}</span></div>
          <em class="net-badge-hint">${b.hint}</em>
        </div>`)}
      </div>
      ${!net.nm_available ? html`<span class="net-demo" title="NetworkManager not reachable">NM unavailable</span>` : ''}
    </div>

    ${/* Windows (2026-10-03) : GoleM ouvert au réseau — ce qui empêche ENCORE une tablette de l'ouvrir, et le geste qui le lève */''}
    ${loading ? '' : net.local_only ? html`<div class="net-revert"><span>ⓘ golem listens on <b>this computer only</b> (127.0.0.1): a tablet or a phone cannot open it.</span></div>`
      : mac && net.firewall_open === false ? html`<div class="net-revert"><span>⚠ The macOS firewall blocks golem. Allow <b>Python</b> in System Settings ▸ Network ▸ Firewall ▸ Options.</span></div>`
      : win && net.firewall_open === false ? html`<div class="net-revert"><span>⚠ The Windows firewall keeps golem closed to the network. Opening it needs Windows’ permission, once.</span>
          <button class="chip on" disabled=${busy} onClick=${openFirewall}>Open to my network</button></div>`
      : html`<div class="net-revert net-ok"><span>✓ On a phone or a tablet: <b>${(net.golem && net.golem.mdns) ? net.golem.url : ((net.reachable || [])[0] || '')}</b>${(net.golem && net.golem.mdns) && (net.reachable || [])[0] ? html` <em class="muted">(or ${net.reachable[0]})</em>` : ''} — then pair it in <a href="#/system/connect/devices">Devices</a>.</span></div>`}
    ${net.ap && net.ap.error ? html`<div class="net-revert"><span>✗ ${net.ap.error}</span></div>` : ''}
    ${err ? html`<div class="net-revert"><span>✗ ${err}</span>
      <button class="chip" onClick=${() => setErr(null)}>Dismiss</button></div>` : ''}

    ${net.pending_confirm ? html`<div class="net-revert">
      <span>⏱ Network changed — <b>confirm within ${net.confirm_window_s} s</b> or it reverts automatically. <em class="muted">Ethernet stays your rescue door.</em></span>
      <button class="chip on" onClick=${confirmNet}>Confirm</button>
    </div>` : ''}

    ${mac && !loading ? html`<div class="net-grid">
      <section class="card-panel net-col">
        <div class="net-col-head"><h3>Open golem <span class="muted">— from a phone or a tablet</span></h3></div>
        <div class="net-qr-wrap net-qr-pair">
          <figure><img class="net-qr" src=${'/api/network/open-qr?v=' + qrKey} alt="Open golem"
            onError=${e => { e.target.style.display = 'none'; }} />
            <figcaption class="net-qr-cap"><b>${(net.golem && net.golem.host) || 'golem'}</b><em class="muted">opens golem</em></figcaption></figure>
        </div>
      </section>
      <section class="card-panel net-col">
        <div class="net-col-head"><h3>WiFi <span class="muted">— managed by macOS</span></h3></div>
        <p class="muted">${net.why}</p>
        <p class="muted">Join a network in <b>System Settings ▸ Wi-Fi</b>, on this Mac. The phone or the tablet must be on the same network.
          ${net.firewall_open === null ? html` The first time a phone opens golem, macOS may ask whether <b>Python</b> can accept incoming connections: click <b>Allow</b>.` : ''}</p>
      </section>
    </div>` : html`<div class="net-grid">

      <!-- ── Access Point (stage) ────────────────────────────────────────── -->
      <section class="card-panel net-col">
        <div class="net-col-head">
          <h3>Access Point <span class="muted">— the tablet joins golem directly</span></h3>
          <button class=${cls('switch ro-inert', net.ap.up && 'on')} role="switch" aria-checked=${net.ap.up}
            disabled=${busy || loading} onClick=${toggleAp}>
            <span class="switch-knob"></span><span class="switch-lbl">${net.ap.up ? 'ON' : 'OFF'}</span>
          </button>
        </div>
        <div class="net-ap">
          <div class=${cls('net-ap-form', !net.ap.up && 'net-ap-off')}>
            <label class="net-field"><span>SSID</span>
              <input class="net-inp" value=${ap.ssid} disabled=${loading} placeholder=${loading ? '…' : ''}
                onInput=${e => setApDraft(d => ({ ...(d || {}), ssid: e.target.value }))} /></label>
            <label class="net-field"><span>Password</span>
              <span class="net-inp-wrap">
                <input class="net-inp" type=${reveal ? 'text' : 'password'} value=${ap.psk}
                  placeholder="unchanged" disabled=${loading}
                  onInput=${e => setApDraft(d => ({ ...(d || {}), psk: e.target.value }))} />
                <button class="net-eye" onClick=${() => setReveal(!reveal)} title="Show/hide">${reveal ? '🙈' : '👁'}</button>
              </span></label>
            <div class="net-field-row">
              ${apDraft ? html`<button class="chip on edit-only" disabled=${busy} onClick=${applyAp}>Apply</button>
                <button class="chip" onClick=${() => setApDraft(null)}>Cancel</button>` : ''}
              <div class="net-field"><span>Clients</span><b class="net-clients">${net.ap.up ? net.ap.clients : '—'}</b></div>
            </div>
          </div>
          ${/* DEUX QR (2026-10-03) : un QR ne fait qu'une chose — le 1er fait rejoindre le WiFi, le 2nd ouvre
                golem à son nom (http://golem.local), l'adresse à garder sur l'écran d'accueil du téléphone */''}
          <div class="net-qr-wrap net-qr-pair">
            <figure class=${cls(!net.ap.up && 'net-ap-off')}><img class="net-qr" src=${'/api/network/qr?v=' + qrKey} alt=${'WiFi QR ' + net.ap.ssid}
              onError=${e => { e.target.style.display = 'none'; }} />
              <figcaption class="net-qr-cap"><b>1 · ${net.ap.ssid || '…'}</b><em class="muted">joins the WiFi</em></figcaption></figure>
            <figure><img class="net-qr" src=${'/api/network/open-qr?v=' + qrKey} alt="Open golem"
              onError=${e => { e.target.style.display = 'none'; }} />
              <figcaption class="net-qr-cap"><b>2 · ${(net.golem && net.golem.host) || 'golem'}</b><em class="muted">opens golem</em></figcaption></figure>
          </div>
        </div>
      </section>

      <!-- ── Station (studio / home) ─────────────────────────────────────── -->
      <section class="card-panel net-col">
        <div class="net-col-head">
          <h3>Station <span class="muted">— joins an existing network</span></h3>
          <button class="chip" disabled=${scanning} onClick=${doScan}>${scanning ? '… scanning' : '⟳ Scan'}</button>
        </div>
        <div class="net-current">
          ${loading ? html`<span class="muted">checking the current network…</span>`
            : net.station.ssid
            ? html`<span class="net-cur-on">● Connected to <b>${net.station.ssid}</b> · ${net.station.ip || ''}</span>`
            : html`<span class="muted">Off WiFi</span>`}
        </div>
        <div class="net-scan">
          ${scan.map(s => html`<div class="net-scan-row">
            <button class="net-scan-main" onClick=${() => setScanOpen(scanOpen === s.ssid ? null : s.ssid)}>
              <${Bars} v=${s.signal} />
              <span class="net-ssid">${s.ssid}</span>
              ${s.security && s.security !== '--' ? html`<span class="net-lock">🔒</span>` : html`<span class="net-lock net-open">open</span>`}
              ${s.in_use ? html`<span class="net-inuse">connected</span>` : ''}
            </button>
            ${scanOpen === s.ssid && !s.in_use ? html`<div class="net-join">
              ${s.security && s.security !== '--' ? html`<input class="net-inp" type="password" placeholder="password" value=${joinPw}
                onInput=${e => setJoinPw(e.target.value)} />` : ''}
              <button class="chip on" disabled=${busy} onClick=${() => joinNet(s.ssid)}>Join</button>
            </div>` : ''}
          </div>`)}
          ${!scan.length && !scanning ? html`<p class="muted">No networks found.</p>` : ''}
        </div>
        <div class="net-known">
          <span class="muted">Known networks:</span>
          ${known.map(k => html`<span class="net-known-chip">${k.name}<button class="net-forget edit-only" title="Forget" onClick=${() => forget(k.name)}>×</button></span>`)}
        </div>
      </section>
    </div>`}

    <div class="net-foot muted">
      ${loading || mac ? '' : win ? html`The access point is Windows’ <b>mobile hotspot</b>: it shares this computer’s Internet connection, next to its WiFi. A switch that drops the current link asks for confirmation (auto-revert).`
        : html`${net.radios >= 2
        ? html`<b>2 radios</b> → <b>station + AP simultaneously</b>`
        : html`<b>1 radio</b> → station <b>or</b> AP (exclusive)`}. Ethernet = guaranteed admin access. A switch that drops the current link asks for confirmation (auto-revert).`}
    </div>
  </div>`;
  }
}

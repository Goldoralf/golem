// SPDX-License-Identifier: GPL-3.0-or-later
// « Continue on a tablet » (docs/installer.md §4) : desktop -> server, SANS couper le son. UN SEUL panneau, ouvert par
// le 📱 de la coquille (app/device.html) et par Settings ▸ System ▸ Dashboard quand golem a une fenêtre — la page de l'app appelle
// alors celui de la coquille (lib.js shellTabletSheet), qui couvre toute la fenêtre et la ferme à la fin.
// DOM nu, sans Preact : la coquille n'est pas l'app. Il vit dans le document qui l'a importé.
//
// Le moteur ne bouge pas : seule la fenêtre s'en va (onClose — le chemin d'Échap, /api/ui/quit sans stop). Avant, on
// donne ce dont la tablette a besoin : l'adresse qui MARCHE (le nom s'il répond, sinon l'IP — /api/network/open-url),
// son QR, et un code d'appairage si aucun appareil principal n'existe encore : sans lui, une tablette ne pourrait pas
// arrêter golem, et sans fenêtre personne d'autre ne le peut.

const CSS = `
#tab-sheet{position:fixed; inset:0; z-index:30; display:flex; align-items:center; justify-content:center;
  background:rgba(7,8,10,.78)}
#tab-sheet[data-off]{display:none}
.ts-card{width:min(560px, calc(100vw - 32px)); background:#15171b; border:1px solid #2a2e35; border-radius:14px;
  padding:18px 20px; color:#e7ecf2; font:13px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  display:flex; flex-direction:column; gap:12px; box-shadow:0 18px 48px rgba(0,0,0,.6)}
.ts-card h2{margin:0; font-size:17px}
.ts-card .ts-row{display:flex; gap:16px; align-items:center}
.ts-card img{width:150px; height:150px; background:#fff; border-radius:10px; padding:6px; flex:none}
.ts-card .ts-url{font:600 15px ui-monospace,monospace; word-break:break-all}
.ts-card .ts-mute{color:#8a94a3}
.ts-card .ts-code{font:700 26px ui-monospace,monospace; letter-spacing:.18em; color:#ffb020}
.ts-card .ts-foot{display:flex; gap:10px; justify-content:flex-end; align-items:center}
.ts-card button{height:40px; padding:0 16px; border-radius:9px; border:1px solid #2a2e35; background:#1c2028;
  color:#e7ecf2; font:600 13px system-ui,sans-serif; cursor:pointer}
.ts-card button.go{background:var(--accent, #ff5a3c); border-color:var(--accent, #ff5a3c); color:#fff}
.ts-card button.link{height:auto; padding:0; border:none; background:none; color:#8a94a3; text-decoration:underline}
`;

const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

/** Ouvre le panneau. `onClose` : ferme la fenêtre golem (absent = on n'est pas dans une fenêtre : « Done »). */
export async function openTabletSheet({ onClose } = {}) {
  if (!document.getElementById('tab-sheet-css')) {
    const st = document.createElement('style');
    st.id = 'tab-sheet-css'; st.textContent = CSS;
    document.head.appendChild(st);
  }
  let el = document.getElementById('tab-sheet');
  if (!el) {
    el = document.createElement('div');
    el.id = 'tab-sheet';
    el.onclick = e => { if (e.target === el) el.dataset.off = ''; };
    document.body.appendChild(el);
  }
  delete el.dataset.off;
  el.innerHTML = '<div class="ts-card"><h2>Continue on a tablet</h2><p class="ts-mute">reading the address…</p></div>';
  const j = u => fetch(u, { cache: 'no-store' }).then(r => r.ok ? r.json() : null).catch(() => null);
  const [open, devs] = await Promise.all([j('/api/network/open-url'), j('/api/auth/devices')]);
  const url = (open && open.url) || ('http://' + location.hostname + ':' + location.port + '/');
  const main = ((devs && devs.devices) || []).some(d => d.admin);
  const pairUrl = url.replace(/\/app\/?$/, '/').replace(/\/?$/, '/') + 'app/pair.html';
  el.innerHTML = `<div class="ts-card">
    <h2>Continue on a tablet</h2>
    <div class="ts-row"><img src="/api/network/open-qr?v=${Date.now()}" alt="QR: open golem">
      <div><div class="ts-mute">On the tablet, scan or open</div><div class="ts-url">${esc(url)}</div>
        ${open && !open.named ? '<div class="ts-mute">on the same Wi-Fi as this computer</div>' : ''}</div></div>
    <div id="ts-pair">${main
      ? '<span class="ts-mute">Your main tablet opens golem directly.</span> <button class="link" id="ts-new">Pair another tablet</button>'
      : '<span class="ts-mute">No tablet is paired yet — it needs a code once.</span> <button class="link" id="ts-new">Show a pairing code</button>'}</div>
    <div class="ts-mute">${onClose
      ? 'This window closes; golem keeps running and the sound does not stop. Open golem again to get the window back.'
      : 'golem keeps running; the sound does not stop.'}</div>
    <div class="ts-foot">${onClose ? '<button id="ts-cancel">Cancel</button><button class="go" id="ts-go">Close this window</button>'
      : '<button class="go" id="ts-cancel">Done</button>'}</div>
  </div>`;
  document.getElementById('ts-cancel').onclick = () => { el.dataset.off = ''; };
  const go = document.getElementById('ts-go');
  if (go) go.onclick = () => onClose();
  document.getElementById('ts-new').onclick = async () => {
    const box = document.getElementById('ts-pair');
    const r = await fetch('/api/auth/pair-code', { method: 'POST' }).then(r => r.ok ? r.json() : null).catch(() => null);
    box.innerHTML = r && r.code
      ? `<div class="ts-mute">On the tablet, open <b>${esc(pairUrl)}</b> and type (valid 10 min, once):</div><div class="ts-code">${esc(r.code)}</div><div class="ts-mute">That tablet becomes the main device: it can also stop golem.</div>`
      : '<span class="ts-mute">Could not create a code — try Settings ▸ Connect ▸ Devices.</span>';
  };
}

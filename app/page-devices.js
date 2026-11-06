// SPDX-License-Identifier: GPL-3.0-or-later
// REMOTE DEVICES RANGÉS PAR GROUPE (docs/devices-people.md §8, maquette validée le 2026-09-16).
//
// Le « Who » n'est plus une liste de prénoms au moment d'ajouter un appareil : c'est un GROUPE. On choisit
// le groupe et on voit ses membres, chacun avec ses droits (golem.fm), ses instruments, les entrées
// qu'il joue SUR CE RACK (la carte du mode actif) et tous ses appareils. Ajouter un appareil part de la
// carte d'une personne — la question « qui ? » est posée par le geste, plus par un formulaire.
//
// Trois choses ne vivent PAS dans la vue d'un groupe, et c'est voulu : les invités (locaux au rack, avec
// une durée), les écrans du rack (sans personne, admin) et les appareils appairés avant que la personne
// n'existe. Ils ont leur propre puce, avec les outils système — on ne touche pas au code d'appairage en
// ajoutant le téléphone du bassiste.
//
// ⚠ Choisir une puce ici ne change PAS l'espace courant du rack (celui où partent les prises) : ça reste
// le mode et la feuille du bloc REC (docs/identity.md §3). La puce du courant porte un point vert.
import { html, useState, useEffect, useAsync, post, del, cls, go } from './lib.js';

const KIND_ICO = { Phone: '📱', Tablet: '⬛', Computer: '💻' };
const GUEST_DAYS = [[1, '1 day'], [7, '1 week'], [30, '1 month'], [0, 'No end']];   // 0 = jusqu'à ce qu'on retire l'appareil
const ROLE_TAG = { guitar: 'gtr', bass: 'bass', voice: 'vox', keys: 'keys', 'keys-pads': 'keys', pads: 'pads', drums: 'drums', line: 'line' };
const GUESTS = '~guests';                       // la puce « Guests & screens »

const isGuest = p => !!p && String(p).startsWith('guest:');
const initials = n => String(n || '?').trim().charAt(0).toUpperCase();
const AV_COLORS = ['#ff8a6b', '#e0b23a', '#5fce8f', '#a98bff', '#3f7fd6', '#c74b8f'];
const avColor = id => AV_COLORS[[...String(id)].reduce((a, c) => a + c.charCodeAt(0), 0) % AV_COLORS.length];

const _ago = ts => {
  if (!ts) return 'never seen';
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 90) return 'just now';
  if (s < 5400) return Math.round(s / 60) + ' min ago';
  if (s < 172800) return Math.round(s / 3600) + ' h ago';
  return Math.round(s / 86400) + ' d ago';
};
const leftFor = ts => {
  const s = Math.max(0, Math.round(ts - Date.now() / 1000));
  if (s >= 172800) return Math.round(s / 86400) + ' days left';
  if (s >= 3600) return Math.round(s / 3600) + ' h left';
  return Math.max(1, Math.round(s / 60)) + ' min left';
};

export function DevicesPanel() {
  const { data, err, reload } = useAsync(() => fetch('/api/auth/devices').then(r => r.json()), []);
  const { data: band, reload: reloadBand } = useAsync(() => fetch('/api/band').then(r => r.json()).catch(() => null), []);
  const { data: imap } = useAsync(() => fetch('/api/inputmap').then(r => r.json()).catch(() => null), []);
  const [space, setSpace] = useState(null);           // id d'espace | GUESTS | null (= le courant)
  const [sheet, setSheet] = useState(null);           // {kind:'add'|'guest'|'invite'|'sync', person?}
  const [pair, setPair] = useState(null);
  const [wifi, setWifi] = useState(false);
  const [busy, setBusy] = useState('');
  const [, tick] = useState(0);
  // RÉVOQUER SE CONFIRME (2026-10-22) : le 🗑 d'un appareil et « Revoke all » agissaient au premier tap, seuls de l'app —
  // un doigt qui frôle la ligne coupait le téléphone d'un musicien. Deux taps, comme toutes les suppressions.
  const [arm, setArm] = useState('');
  const armed = key => { if (arm === key) { setArm(''); return true; } setArm(key); setTimeout(() => setArm(a => a === key ? '' : a), 3000); return false; };

  const devices = (data && data.devices) || [], invites = (data && data.invites) || [];
  const pending = invites[0] || null;
  const bands = (band && band.bands) || [], current = ((band && band.band) || {}).id || null;
  const cur = space || current || (bands[0] || {}).id || GUESTS;
  const shown = bands.find(b => b.id === cur) || null;
  const members = (shown && shown.people) || [];
  // tout le monde, tous espaces confondus : le sélecteur « Who? » de la vue des invités n'a pas d'espace
  const everyone = Object.values(bands.reduce((acc, b) => {
    (b.people || []).forEach(p => { if (p && p.id) acc[p.id] = p; });
    return acc;
  }, {}));

  // un QR (ou un code) qui attend se fait consommer par le scan : on suit jusqu'à ce que l'appareil arrive
  useEffect(() => {
    if (!pending && !pair) return;
    const t = setInterval(() => { reload(); tick(x => x + 1); }, 2500);
    return () => clearInterval(t);
  }, [!!pending, !!pair]);
  useEffect(() => { if (pending && sheet && sheet.kind === 'invite') setSheet(null); }, [!!pending]);

  const devicesOf = pid => devices.filter(d => d.person === pid && !d.screen);
  const guests = devices.filter(d => isGuest(d.person) && !d.screen);
  const screens = devices.filter(d => d.screen);
  const loose = devices.filter(d => !d.person && !d.screen);
  // les entrées de la carte ACTIVE, par personne : « IN 1 · USB 1 » — ce que le téléphone montrera
  const slotsOf = pid => imap ? [...(imap.inputs || []).filter(e => e.person === pid).map(e => 'IN ' + e.ch),
                                 ...(imap.usb || []).filter(u => u.person === pid).map(u => 'USB ' + u.port)] : [];
  const orphans = imap ? [...(imap.inputs || []).filter(e => e.role && !['none', 'other'].includes(e.role) && !e.person).map(e => (e.name || e.label) + ' · IN ' + e.ch),
                          ...(imap.usb || []).filter(u => u.bound && !u.person).map(u => (u.name || u.label) + ' · USB ' + u.port)] : [];

  const act = async (fn) => { setBusy('1'); try { await fn(); } finally { setBusy(''); reload(); } };
  const drop = id => act(() => del('/api/auth/devices/' + id).catch(() => {}));
  // la feuille RESTE ouverte : l'invitation créée devient `pending`, et la même feuille montre son QR. Avant,
  // elle se fermait — il fallait la rouvrir pour voir le QR (2026-10-03). Le type d'appareil n'est plus
  // demandé : le bridge le lit au scan (auth.kind_from_ua).
  const addDevice = (person, guest, days) => act(async () => {
    await post('/api/auth/devices', guest ? { guest, days } : { person }).catch(() => {});
  });
  // « + Add a device for le mainteneur » : rien à choisir — on crée l'invitation tout de suite, le QR s'affiche
  const addFor = p => { setSheet({ kind: 'add', person: p }); if (!pending) addDevice(p.id, null, null); };
  const makePair = async () => { const r = await post('/api/auth/pair-code', {}).catch(() => null); if (r && r.code) setPair(r); };
  const syncNow = () => act(async () => { await post('/api/band/sync', {}).catch(() => {}); reloadBand(); });

  const devRow = d => html`<div class=${cls('dv-dev', d.expired && 'exp')} key=${d.id}>
    <span class="k">${KIND_ICO[d.kind] || '📱'}</span>
    <div class="dn"><b>${isGuest(d.person) ? d.person_name || 'Guest' : (d.model || d.kind || d.name)}${d.role && !d.person ? ' · ' + d.role : ''}</b>
      <small>${[isGuest(d.person) ? (d.model || d.kind) : d.kind, d.via === 'golem.fm' ? 'via golem.fm' : null,
        isGuest(d.person) && !d.expires ? 'no end' : d.guest_days ? GUEST_DAYS.filter(g => g[0] === d.guest_days).map(g => g[1])[0] || d.guest_days + ' days' : null,
        d.expires ? (d.expired ? 'expired' : leftFor(d.expires)) : null, _ago(d.last_seen)].filter(Boolean).join(' · ')}</small></div>
    ${d.expires ? html`<button class="dv-mini edit-only" title="give this guest more time"
      onClick=${() => act(() => post('/api/auth/extend', { id: d.id, days: d.guest_days || 1 }))}>Extend</button>` : ''}
    ${d.kind === 'Phone' && !d.screen ? html`<button class=${cls('dv-fl ro-inert', d.conductor && 'on')}
      title=${d.conductor ? 'conductor — loads, starts and stops the songs; tap to remove' : 'make this phone the conductor'}
      onClick=${() => act(() => post('/api/auth/conductor', { id: d.id, conductor: !d.conductor }))}>🎼</button>` : ''}
    ${isGuest(d.person) ? '' : html`<button class=${cls('dv-fl ro-inert', d.admin && 'on')}
      title=${d.admin ? 'admin — update, flash, network; tap to demote' : 'promote to admin'}
      onClick=${() => act(() => post('/api/auth/promote', { id: d.id, admin: !d.admin }))}>${d.admin ? '★' : '☆'}</button>`}
    <button class="dv-fl danger" title="revoke this device only" onClick=${() => armed('d:' + d.id) && drop(d.id)}>${arm === 'd:' + d.id ? 'sure?' : '🗑'}</button>
  </div>`;

  const memberCard = p => {
    const mine = devicesOf(p.id), slots = slotsOf(p.id);
    return html`<div class="dv-mb" key=${p.id}>
      <div class="dv-mh">
        ${/* la PHOTO de golem.fm quand le membre en a une (roster.fetch_avatars, en cache sur le rack), sinon l'initiale */''}
        ${p.has_avatar ? html`<img class="dv-av dv-av-img" src=${'/api/band/avatar/' + encodeURIComponent(p.id)} alt=${p.name || p.id}
            onError=${e => { e.target.replaceWith(Object.assign(document.createElement('span'), { className: 'dv-av', textContent: initials(p.name) })); }} />`
          : html`<span class="dv-av" style=${'background:' + avColor(p.id)}>${initials(p.name)}</span>`}
        <span class="nm">${p.name || p.id}</span>
        ${p.rights && p.rights !== 'member' ? html`<span class=${'dv-right ' + p.rights}>${p.rights}</span>`
          : html`<span class="dv-right">member</span>`}
        ${(p.roles || []).slice(0, 3).map(r => html`<span class=${'dv-tag ' + (ROLE_TAG[r] || '')}>${r}</span>`)}
        <span class="dv-ins">${slots.length ? slots.join(' · ') : 'no input'}</span>
      </div>
      ${mine.length ? mine.map(devRow) : html`<p class="dv-none">No device yet.</p>`}
      <button class="dv-add" onClick=${() => addFor(p)}>＋ Add a device for ${p.name || p.id}</button>
    </div>`;
  };

  const guestCard = () => html`<div class="dv-col">
    <h4>Guests <small>no golem.fm account · access ends on its own</small></h4>
    ${guests.length ? guests.map(devRow) : html`<p class="dv-none">No guest.</p>`}
    <button class="dv-add" onClick=${() => setSheet({ kind: 'guest' })}>＋ Guest for a day, a week or a month</button>
    ${loose.length ? html`<h4 class="sp">Not assigned <small>paired before people existed</small></h4>
      ${loose.map(d => html`<div class="dv-dev" key=${d.id}>
        <span class="k">${KIND_ICO[d.kind] || '📱'}</span>
        <div class="dn"><b>${d.model || d.kind}${d.role ? ' · ' + d.role : ''}</b><small>${[d.mac && d.mac.toUpperCase(), _ago(d.last_seen)].filter(Boolean).join(' · ')}</small></div>
        <select id=${'dv-who-' + d.id} class="dv-who" title="who uses this device — no need to scan again"
          onChange=${e => act(() => post('/api/auth/devices/' + d.id + '/person', e.target.value ? { person: e.target.value } : {}))}>
          <option value="">Who?</option>
          ${everyone.map(pp => html`<option value=${pp.id}>${pp.name}</option>`)}
        </select>
        <button class="dv-fl danger" onClick=${() => armed('d:' + d.id) && drop(d.id)}>${arm === 'd:' + d.id ? 'sure?' : '🗑'}</button></div>`)}
      <p class="dv-none">Pick a name and the device moves to that card, token kept.</p>` : ''}
  </div>`;

  const screenCard = () => html`<div class="dv-col">
    <h4>Rack screens <small>no person · admin</small></h4>
    ${screens.length ? screens.map(devRow) : html`<p class="dv-none">A tablet can serve as the rack's display: give it the pairing code.</p>`}
    <div class="dv-row">
      <button class="chip edit-only" title="a six-digit code for a tablet that will be the rack's screen — open /app/pair.html on it"
        onClick=${makePair}>▣ Pairing code for a screen</button>
      <button class=${cls('chip', wifi && 'on')} title="the QR of the rack's own Wi-Fi, for a room without network"
        onClick=${() => setWifi(!wifi)}>Wi-Fi QR</button>
    </div>
    ${pair ? html`<div class="dv-pair"><b>${pair.code}</b><span>Open <code>${location.host}/app/pair.html</code> on the tablet · one use, 10 min</span>
      <button class="dv-fl" onClick=${() => setPair(null)}>✕</button></div>` : ''}
    ${wifi ? html`<img class="dv-wifi" src="/api/network/qr" alt="rack Wi-Fi QR"
      onError=${e => { e.target.replaceWith(Object.assign(document.createElement('span'), { className: 'dv-none', textContent: 'The rack has no Wi-Fi access point configured.' })); }} />` : ''}
    <div class="sp"></div>
    <div class="dv-row end">
      <button class="chip edit-only" title="the rack's touchscreen keeps working" onClick=${() => armed('all') && act(() => post('/api/auth/revoke'))}>${arm === 'all' ? 'Tap again: revoke every remote device' : '↻ Revoke all remote devices'}</button>
    </div>
  </div>`;

  const sheetView = () => {
    if (!sheet) return '';
    const close = () => setSheet(null);
    if (sheet.kind === 'add' || sheet.kind === 'guest') return html`<${AddSheet} sheet=${sheet} pending=${pending} fm=${bands.length > 0}
      onClose=${close} onCancel=${() => drop(pending.id)} onAdd=${addDevice} busy=${busy} />`;
    if (sheet.kind === 'invite') return html`<${InviteSheet} space=${shown} onClose=${close} onGuest=${() => setSheet({ kind: 'guest' })} />`;
    return html`<${SyncSheet} band=${band} bands=${bands} onClose=${close} onSync=${syncNow} busy=${busy} />`;
  };

  return html`<section class="card-panel dv-panel">
    <div class="dv-bar">
      ${bands.map(b => html`<button class=${cls('dv-space', cur === b.id && 'on')} onClick=${() => setSpace(b.id)}>
        ${b.id === current ? html`<i class="cur" title="the current space — takes go here"></i>` : ''}
        ${b.name}<em>${(b.people || []).length}</em></button>`)}
      <button class=${cls('dv-space', cur === GUESTS && 'on')} onClick=${() => setSpace(GUESTS)}>
        Guests & screens<em>${guests.length + screens.length + loose.length}</em></button>
      <span class="sp"></span>
      ${band && band.synced ? html`<button class="dv-sync" onClick=${() => setSheet({ kind: 'sync' })}
        title="what comes from golem.fm, and what goes back">✓ <b>Synced</b> ${_ago(Date.parse(band.synced) / 1000)}</button>` : ''}
      ${shown && shown.kind !== 'personal' ? html`<button class="chip accent" onClick=${() => setSheet({ kind: 'invite' })}>＋ Invite to ${shown.name}</button>` : ''}
    </div>
    ${err ? html`<p class="dv-none">⚠ can't load the device list.</p>` : ''}
    ${/* DEUX BLOCS SUR UNE LIGNE (2026-10-03 : « ces 2 labels sont peu lisibles ») : ce qui manque
          (les entrées sans personne, chacune en pastille, et le geste qui le règle) et où vont les prises.
          L'explication longue passe dans l'infobulle — elle se lit une fois, la pastille à chaque coup d'œil. */''}
    ${cur !== GUESTS && (orphans.length || current) ? html`<div class="dv-notes">
      ${orphans.length ? html`<div class="dv-note warn" title="a phone shows the lanes of its person — an input with no one shows on no phone">
        <span class="dv-note-k">⚠ No one on</span>
        ${orphans.map(o => html`<span class="dv-pill">${o}</span>`)}
        <button class="dv-note-go" onClick=${() => go('system/mode')}>Set who ›</button>
      </div>` : ''}
      ${current ? html`<div class="dv-note" title="the current space is set in Mode or on the REC block, not here">
        <span class="dv-note-k">Takes go to</span>
        <span class="dv-pill on"><i class="cur"></i>${(bands.find(b => b.id === current) || {}).name}</span>
      </div>` : ''}
    </div>` : ''}

    ${cur === GUESTS ? html`<div class="dv-cols2">${guestCard()}${screenCard()}</div>`
      : !bands.length ? html`<p class="dv-none">This rack is not linked to golem.fm yet: it has no band, so every device here is a guest of this rack.
        Link it in Settings ▸ Connect ▸ golem.fm, or add guests from the <b>Guests &amp; screens</b> tab.</p>`
      : members.length ? html`<div class="dv-members">${members.map(memberCard)}</div>`
      : html`<p class="dv-none">No member in ${shown ? shown.name : 'this space'} yet.</p>`}
    ${sheetView()}
  </section>`;
}

// ── ajouter un appareil : la personne est déjà connue, il ne reste que « quel appareil » ─────────────
function AddSheet({ sheet, pending, onClose, onCancel, onAdd, busy, fm }) {
  const guest = sheet.kind === 'guest';
  const [name, setName] = useState('');
  const [days, setDays] = useState(7);
  const who = guest ? (name.trim() || 'the guest') : (sheet.person.name || sheet.person.id);
  const ready = !guest || name.trim().length > 0;
  return html`<div class="dv-sheet-wrap" onClick=${e => e.target.classList.contains('dv-sheet-wrap') && onClose()}>
    <div class="dv-sheet">
      <h3>${guest ? 'Add a guest' : 'Add a device for ' + who}<button class="dv-fl" onClick=${onClose}>✕</button></h3>
      ${pending ? html`<div class="dv-qrbox">
        <img class="dv-qr" src=${'/api/auth/qr?invite=' + pending.id} alt="device invite QR" onError=${e => { e.target.style.display = 'none'; }} />
        <div class="dv-steps">
          <p><i>1</i><span>${pending.person_name || who} scans this with the phone camera.<br /><small>One device · 15 min</small></span></p>
          <p><i>2</i><span>The app opens already authorized, on that person's lines.</span></p>
          ${/* golem.fm/connect ne trouve qu'un golem APPAIRÉ (son roster vient de golem.fm) : sinon, rien à promettre */''}
          ${fm ? html`<p class="dv-alt"><b>Internet on the rack?</b> No QR needed: open <b>golem.fm/connect</b> on the phone, logged in.</p>` : ''}
          <button class="chip" onClick=${onCancel}>✕ Cancel this invite</button>
        </div>
      </div>` : html`<div class="dv-form">
        ${guest ? html`<label class="dv-lbl">Name<input id="dv-guest" class="dv-field" maxlength="24" autofocus
          placeholder="Guest's first name" value=${name} onInput=${e => setName(e.target.value)} /></label>` : ''}
        ${guest ? html`<span class="dv-lbl">Access</span>
          <div class="dv-chips">${GUEST_DAYS.map(([d, label]) => html`<button class=${cls('dv-chip', days === d && 'on')}
            onClick=${() => setDays(d)}>${label}</button>`)}</div>
          <p class="dv-alt">A guest lives on this rack only: ${guest && name.trim() ? name.trim() + ' plays' : 'they play'} with the band,
            ${guest && name.trim() ? 'gets' : 'get'} their lines and their takes. ${days ? 'The access ends on its own unless someone extends it.' : 'The access lasts until you remove the device.'}</p>` : ''}
        <div class="dv-acts">
          <button class="chip accent" disabled=${!ready || !!busy}
            onClick=${() => onAdd(guest ? null : sheet.person.id, guest ? name.trim() : null, guest ? days : null)}>
            ${guest ? 'Add ' + who : 'Show the QR'}</button>
        </div>
      </div>`}
    </div></div>`;
}

// ── inviter dans le groupe : le rack MONTRE l'invitation de golem.fm, il ne crée pas de membre ───────
function InviteSheet({ space, onClose, onGuest }) {
  // l'invitation est celle de l'espace AFFICHÉ, pas du courant : on regarde le groupe en enregistrant
  // pour l'espace perso, et c'est bien dans le groupe qu'on veut inviter
  const sid = (space && space.id) || '';
  const { data } = useAsync(() => fetch('/api/band/invite?space=' + encodeURIComponent(sid)).then(r => r.ok ? r.json() : null).catch(() => null), [sid]);
  const url = data && data.url;
  return html`<div class="dv-sheet-wrap" onClick=${e => e.target.classList.contains('dv-sheet-wrap') && onClose()}>
    <div class="dv-sheet">
      <h3>Invite to ${space ? space.name : 'the band'}<button class="dv-fl" onClick=${onClose}>✕</button></h3>
      <div class="dv-qrbox">
        ${url ? html`<img class="dv-qr" src=${'/api/band/invite/qr?space=' + encodeURIComponent(sid)} alt="golem.fm band QR" onError=${e => { e.target.style.display = 'none'; }} />` : ''}
        <div class="dv-steps">
          ${url ? html`<p><i>1</i><span>Scan to open <b>${space ? space.name : 'the band'}</b> on golem.fm, where you invite by link or by email.</span></p>
            <p><i>2</i><span>The new member shows up here within five minutes.</span></p>
            <p class="dv-alt"><code>${url}</code></p>`
            : html`<p class="dv-alt">This rack is not linked to golem.fm, so it cannot show the band's invitation.
              Link it in <b>Settings ▸ Connect ▸ golem.fm</b>.</p>`}
          <p class="dv-alt"><b>No golem.fm account?</b> Add them as a guest of this rack instead, for a day, a week or a month.</p>
          <button class="chip" onClick=${onGuest}>＋ Guest instead</button>
        </div>
      </div>
    </div></div>`;
}

// ── la synchro : ce qui descend, ce qui monte, ce qui ne sort jamais ─────────────────────────────────
function SyncSheet({ band, bands, onClose, onSync, busy }) {
  const { data: conn } = useAsync(() => fetch('/api/connect').then(r => r.json()).catch(() => null), []);
  const people = bands.reduce((n, b) => n + ((b.people || []).length), 0);
  const withRights = bands.reduce((n, b) => n + (b.people || []).filter(p => p.rights).length, 0);
  const withPrefs = bands.reduce((n, b) => n + (b.people || []).filter(p => p.prefs && Object.keys(p.prefs).length).length, 0);
  const row = (what, now, state, cls_) => html`<div class="dv-srow"><b>${what}</b><span>${now}</span><em class=${'st ' + (cls_ || '')}>${state}</em></div>`;
  return html`<div class="dv-sheet-wrap" onClick=${e => e.target.classList.contains('dv-sheet-wrap') && onClose()}>
    <div class="dv-sheet wide">
      <h3>Sync with golem.fm<button class="dv-fl" onClick=${onClose}>✕</button></h3>
      <div class="dv-sync-table">
        <div class="dv-sgrp">From golem.fm to this rack · every 5 min and at startup</div>
        ${row('Spaces & members', bands.map(b => b.name + ' ' + (b.people || []).length).join(' · ') || 'none', people + ' people', 'ok')}
        ${row('Rights', 'owner, admin or member — sets conductor by default on a phone', withRights ? withRights + ' served' : 'not served yet', withRights ? 'ok' : 'wait')}
        ${row('Personal settings', 'lyrics size, tuner reference — read only', withPrefs ? withPrefs + ' served' : 'not served yet', withPrefs ? 'ok' : 'wait')}
        <div class="dv-sgrp">From this rack to golem.fm</div>
        ${row('Where to find this rack', 'local addresses and Wi-Fi name, for golem.fm/connect',
          conn ? (conn.presence ? 'on' : 'off') : '…', conn && conn.presence ? 'ok' : 'wait')}
        ${row('Who plays which input', 'with the 5 min beat — a guest goes without their name', 'on', 'ok')}
        ${row('Devices and their people', 'stays on this rack', 'never', 'never')}
      </div>
      <div class="dv-acts">
        <small class="dv-none">${band && band.synced ? 'Last sync ' + _ago(Date.parse(band.synced) / 1000) : 'never synced'} · the box is in Settings ▸ Connect ▸ golem.fm</small>
        <button class="chip" disabled=${!!busy} onClick=${onSync}>↻ Sync now</button>
      </div>
    </div></div>`;
}

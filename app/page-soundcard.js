// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Settings ▸ Gear ▸ Soundcard — vue I/O de la carte façon QC (io-settings) : les prises du rack
// dessinées en SVG (combo XLR/jack, jack 6.35, MIDI DIN, USB host ×2, casque), VERTES quand
// branchées/actives (flux ALSA tenu, subscriptions MIDI, périph USB détecté). Tap sur une prise
// -> panneau détail en bas (état + futur : choix des blocs instruments par prise USB).
import { html, useAsync, useState, useEffect, cls, esc, post, go } from './lib.js';
import { Icon } from './icons.js';
import { DesktopAudioPage } from './page-desktop-audio.js';
import { setupRows, chipLabel } from './card-setups-model.mjs';

// « hw:V276 », « V276 », « ALSA V276 » : la même carte — on compare l'identifiant nu, sans préfixe ni casse
const sameCard = (a, b) => { const n = x => String(x || '').replace(/^(ALSA\s+)?(hw:)?/i, '').trim().toLowerCase(); return !!n(a) && n(a) === n(b); };

// — glyphes SVG (stroke=currentColor : gris au repos, vert quand actif) —
const G = {
  combo: html`<svg viewBox="0 0 64 64" class="sc-g xl"><circle cx="32" cy="32" r="28" fill="none" stroke="currentColor" stroke-width="3"/>
    <circle cx="32" cy="32" r="10" fill="currentColor" opacity=".9"/>
    <circle cx="32" cy="15" r="4" fill="currentColor"/><circle cx="17" cy="41" r="4" fill="currentColor"/><circle cx="47" cy="41" r="4" fill="currentColor"/></svg>`,
  jack: html`<svg viewBox="0 0 64 64" class="sc-g"><circle cx="32" cy="32" r="26" fill="none" stroke="currentColor" stroke-width="3"/>
    <circle cx="32" cy="32" r="14" fill="none" stroke="currentColor" stroke-width="3"/>
    <circle cx="32" cy="32" r="6" fill="currentColor"/></svg>`,
  din: html`<svg viewBox="0 0 64 64" class="sc-g"><circle cx="32" cy="32" r="26" fill="none" stroke="currentColor" stroke-width="3"/>
    <circle cx="32" cy="46" r="3.2" fill="currentColor"/><circle cx="18" cy="38" r="3.2" fill="currentColor"/><circle cx="46" cy="38" r="3.2" fill="currentColor"/>
    <circle cx="21" cy="24" r="3.2" fill="currentColor"/><circle cx="43" cy="24" r="3.2" fill="currentColor"/><rect x="29" y="8" width="6" height="7" rx="1.5" fill="currentColor"/></svg>`,
  usb: html`<svg viewBox="0 0 64 44" class="sc-g usb"><rect x="6" y="8" width="52" height="28" rx="4" fill="none" stroke="currentColor" stroke-width="3"/>
    <rect x="14" y="15" width="36" height="9" rx="1.5" fill="currentColor" opacity=".85"/></svg>`,
  phones: html`<svg viewBox="0 0 64 64" class="sc-g"><circle cx="32" cy="36" r="22" fill="none" stroke="currentColor" stroke-width="3"/>
    <circle cx="32" cy="36" r="7" fill="currentColor"/>
    <path d="M20 14a12 12 0 0 1 24 0" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/></svg>`,
};

// une prise v2 — hiérarchie (haut -> bas) : TAG de l'input map (instrument, icône SVG + nom, AU-DESSUS
// de l'icône), glyphe du connecteur, nom TECHNIQUE dessous (INPUT 1...), sous-titre optionnel.
// Le slot tag est toujours rendu (nbsp) pour garder les prises d'un groupe alignées.
const Jack = ({ glyph, label, tag, sub, on, sel, veto, onTap }) => html`
  <button class=${cls('sc-jack', on && 'on', sel && 'sel', veto && 'veto')} onClick=${onTap}>
    <span class="sc-tag">${tag || '\u00A0'}</span>
    ${glyph}<span class="sc-lbl">${label}</span>
    <span class="sc-sub">${sub || '\u00A0'}</span>
  </button>`;

// groupe de prises avec son intitulé (USB · MIDI · OUTPUTS · INPUTS)
const Group = (label, jacks, k) => html`<div class=${cls('sc-group', k)}><div class="sc-group-lbl">${label}</div>
  <div class="sc-group-jacks">${jacks}</div></div>`;

// PASTILLE compacte (maquette mockups/soundcard-rack.html, 2026-09-09) : au-delà de 6 jacks dans un
// groupe (XR18 : 18 entrées), les glyphes ronds deviennent des pastilles 44 px en lignes de 9 —
// numéro + icône d'instrument ; le nom complet et la personne vivent dans le détail au tap.
const Pin = ({ n, icon, on, sel, pair, pair2, veto, onTap, title }) => html`
  <button class=${cls('sc-pin', on && 'on', sel && 'sel', pair && 'pair', pair2 && 'pair2', veto && 'veto')} onClick=${onTap} title=${title}>
    <b>${n}</b><span>${icon || '·'}</span></button>`;
const Pins = pins => html`<div class="sc-pins">${pins}</div>`;


export function SoundcardPage({ rig }) {
  const { data: sc, reload } = useAsync(() => fetch('/api/soundcard').then(r => r.json()), []);
  const { data: imap, reload: reloadImap } = useAsync(() => fetch('/api/inputmap').then(r => r.json()), []);
  const { data: band } = useAsync(() => fetch('/api/band').then(r => r.json()).catch(() => ({ people: [] })), []);
  const [sel, setSel] = useState(null);
  const [audioOpen, setAudioOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  // appareils CONNUS du rack (docs/gear-registry.md addendum 2026-09-23) : ceux qui ne sont pas branchés
  // sont dits sur un port vide — ils ne disparaissent plus
  const { data: devs } = useAsync(() => fetch('/api/devices').then(r => r.json()).catch(() => null), [sc && (sc.usb || []).length]);
  const knownOff = ((devs && devs.devices) || []).filter(k => k.known && !k.connected);
  const [knownOpen, setKnownOpen] = useState(false);   // les cartes connues : un chip, un popover
  // ── LA MÊME CARTE SUR UN AUTRE RACK (docs/card-setups-exchange.md, maquette mockups/soundcard-sync.html) ──
  // golem.fm rend les configurations SŒURS de la carte branchée ; un chip orange tant qu'une sœur diffère (ou
  // qu'une proposition attend), la comparaison entrée par entrée au tap, et la question de la première rencontre.
  // Rien n'est appliqué sans un geste ; golem.fm injoignable = pas de chip, rien ne casse.
  const { data: cs, reload: reloadCs } = useAsync(() => imap && imap.card
    ? fetch('/api/card-setups?card=' + encodeURIComponent(imap.card)).then(r => r.json()).catch(() => null)
    : Promise.resolve(null), [imap && imap.card]);
  const [syncOpen, setSyncOpen] = useState(/[?&]sync=open/.test(location.search));   // ?sync=open : la comparaison ouverte d'emblée (captures de vérification)
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');
  const flashSync = m => { setSyncMsg(m); setTimeout(() => setSyncMsg(''), 4000); };
  const syncDo = async (path, body, okMsg) => {
    setSyncBusy(true);
    const r = await post(path, { card: imap && imap.card, ...body }).catch(e => (e && e.body) || { error: String(e) });
    setSyncBusy(false);
    if (r && r.error) { flashSync('✗ ' + r.error); return false; }
    const sk = (r && (r.skipped || (r.result || {}).skipped)) || [];
    flashSync(okMsg + (sk.length ? ' — ' + sk.length + ' skipped: ' + sk.join('; ') : ''));
    reloadImap(); reloadCs(); setSyncOpen(false);
    return true;
  };
  const people = {}; ((band && band.people) || []).forEach(p => { people[p.id] = p.name; });
  const [dk, setDk] = useState(null);   // descripteurs de kit de batterie (docs/drums-kit.md)
  useEffect(() => { fetch('/api/drumkits').then(r => r.json()).then(setDk).catch(() => setDk({ kits: [] })); }, []);
  useEffect(() => { const t = setInterval(reload, 3000); return () => clearInterval(t); }, []);   // suit les branchements

  const s = (rig && rig.state) || {};
  useEffect(() => { reloadImap(); }, [(s.cards || {}).active]);
  // les rangs USB n suivent la détection : une prise DIN choisie, un clavier branché, et les prises
  // glissent — l'input map (rôles affichés sur chaque prise) doit suivre, pas rester sur l'ancien rang
  useEffect(() => { reloadImap(); }, [sc && JSON.stringify(sc.binding)]);
  const cap = !!(sc && sc.capture_open), pb = !!(sc && sc.playback_open);
  const midi = (sc && sc.midi) || {};
  const usb = (sc && sc.usb) || [];
  const usbAt = i => usb[i] || null;
  const lat = s.latency_ms ?? (sc && sc.latency_ms);
  const desktop = !!(sc && (sc.platform === 'win32' || sc.platform === 'darwin'));
  const inputNames = (sc && sc.card && sc.card.input_names) || [];
  const outputNames = (sc && sc.card && sc.card.output_names) || [];

  // ── input map d'entrées/sorties (docs/input-map.md) : instrument par connecteur ──
  // N-canaux (audit 2026-08-12 §3 chantier ④) : le NOMBRE de prises vient de l'inputmap,
  // semée par le bridge depuis le probe de la carte — plus rien de codé en dur pour la Volt.
  const pIn = ch => ((imap && imap.inputs) || []).find(x => String(x.ch) === String(ch) || String(x.ch).split('-').includes(String(ch)));
  const pOut = ch => ((imap && imap.outputs) || []).find(x => String(x.ch) === String(ch) || String(x.ch).split('-').includes(String(ch)));
  const maxCh = list => { let m = 0; for (const x of list || []) for (const c of String(x.ch).split('-')) m = Math.max(m, parseInt(c, 10) || 0); return m; };
  const nIn = desktop && sc.card.inputs != null ? sc.card.inputs : Math.max(2, maxCh(imap && imap.inputs));
  const nOut = desktop && sc.card.outputs != null ? sc.card.outputs : Math.max(2, maxCh(imap && imap.outputs));
  const pairAt = ch => { const e = pIn(String(ch)); return !!(e && String(e.ch).includes('-')); };
  const pairBase = ch => (ch % 2 === 1 ? ch : ch - 1);       // paires matérielles impaire+paire (1+2, 3+4…)
  const setRole = async (kind, ch, role) => {
    await post('/api/inputmap', { kind, ch, role }).catch(() => {});
    reloadImap();
  };
  const setPair = async (a, linked) => {
    await post('/api/inputmap/pair', { kind: 'input', a: String(a), b: String(a + 1), linked }).catch(() => {});
    reloadImap(); setSel(linked ? 'in' + a : sel);
  };
  // rangée de chips-icônes (saisie SANS clavier — doctrine kiosk ; icônes SVG du pack)
  const ROLE_LBL = { input: 'Instrument', output: 'Feeds', midi_in: 'Listens to', midi_out: 'Drives' };
  const RoleChips = (kind, ch, cur, catalog) => html`<div class="sc-drow sc-roles"><span>${ROLE_LBL[kind] || 'Role'}</span>
    ${(catalog || []).filter(it => !it.soon).map(it => html`<button class=${cls('sc-chip', cur === it.id && 'onn', it.soon && 'off')}
      disabled=${!!it.soon} title=${it.soon ? it.name + ' — coming with the DIN keyboard wiring (bloc C)' : it.name}
      onClick=${() => setRole(kind, ch, it.id)}><${Icon} id=${it.id} fallback=${it.icon} /> ${it.name}${it.soon ? ' · soon' : ''}</button>`)}
  </div>`;
  // tag = icône SVG + label du rôle (rendu AU-DESSUS du connecteur)
  const roleTag = e => e && e.role && e.role !== 'none'
    ? html`<${Icon} id=${e.role} fallback=${e.icon} /> ${e.label}` : null;
  const dinCur = k => (imap && imap[k]) || {};
  const dinName = k => { const e = dinCur(k); return e.role === 'none' ? '· off' : roleTag(e); };
  // tag USB : le rôle du binding (Keys / Pads / Keys + Pads) — le nom du périphérique
  // détecté reste affiché SOUS le nom technique (placement validé avec l'agent UX)
  const usbTag = i => {
    const u = usbOf(i);
    if (!u || !u.bound || !u.role || u.role === 'none') return null;
    return html`<${Icon} id=${u.role} fallback=${u.icon} /> ${u.name || u.label}`;
  };
  const usbSub = i => { const u = usbOf(i), d = usbAt(i); const dev = (u && u.bound && u.device) || (d && d.name) || '';
    if (!dev) return null; return u && u.person_name ? dev + ' · ' + u.person_name : (d && !(u && u.bound) ? dev + ' · unbound' : dev); };
  const inBody = ch => {
    const e = pIn(ch);
    const a = pairBase(parseInt(ch, 10)), linked = pairAt(a);
    // retour 2026-09-09 : ni vu-mètre ni phrase d'explication ; la paire stéréo sur la ligne Person
    const pairBtn = a + 1 <= nIn ? html`<span class="sc-sep"></span><button class=${cls('sc-chip edit-only', linked ? 'onn' : 'off')} onClick=${() => setPair(a, !linked)}
          title=${`link inputs ${a}+${a + 1} as ONE stereo instrument (e.g. a drum module L/R)`}><${Icon} id="link" /> IN ${a}+${a + 1} ${linked ? 'linked' : 'unlinked'}</button>` : '';
    return html`
      ${RoleChips('input', (e && e.ch) || ch, e && e.role, imap && imap.instruments)}
      <div class="sc-drow sc-roles"><span>Person</span>
        ${(band && band.people && band.people.length) ? html`
          <button class=${cls('sc-chip', !(e && e.person) && 'onn')} title="no one — solo rig"
            onClick=${async () => { await post('/api/inputmap', { kind: 'input', ch: (e && e.ch) || ch, person: null }); reloadImap(); }}>·</button>
          ${band.people.map(pe => html`<button class=${cls('sc-chip', e && e.person === pe.id && 'onn')}
            title=${'this input is ' + pe.name + '’s line — their patches come first in the Designer'}
            onClick=${async () => { await post('/api/inputmap', { kind: 'input', ch: (e && e.ch) || ch, person: pe.id }); reloadImap(); }}>${esc(pe.name)}</button>`)}`
        : html`<span class="muted">pair the rack with golem.fm to get the band roster</span>`}
        ${pairBtn}
      </div>
      ${vetoIn(ch) ? html`<p class="sc-veto-note">This input is turned off by the active mode (${modeSt.name}) — Mode tab to change it.</p>` : ''}`;
  };
  const outBody = ch => {
    const e = pOut(ch);
    const a = pairBase(parseInt(ch, 10));
    const dflt = a + 1 <= nOut ? `${a}-${a + 1}` : String(a);
    return html`
      ${RoleChips('output', (e && e.ch) || dflt, e && e.role, imap && imap.out_roles)}
      <p class="muted">${a === 1 ? 'Main pair' : `Output pair ${a}/${a + 1}`} · buffer ${sc && sc.bsize} smp${lat != null ? ` · ${desktop ? 'REAPER device latency' : 'round-trip'} ${lat} ms` : ''}</p>`;
  };
  // ── couture Mode ⇄ Soundcard : un connecteur veto-é par le MODE ACTIF s'atténue ──
  const modeSt = s.mode || {};
  const svcOff = k => (modeSt.services || {})[k] === false;
  const offNumbered = e => !!(e && e.role && e.nth != null && ((modeSt.inputs_off || []).includes(e.role + '#' + e.nth)));
  const vetoIn = ch => {                    // entrée audio : service du RÔLE (voice, drums…) OU entrée numérotée coupée par le mode
    const e = pIn(ch);
    return !!(e && ((e.role && svcOff(e.role)) || offNumbered(e)));
  };
  // PORTS USB = le rack (docs/input-map.md §3.3) : l'input map les sert pour toute carte, nommés et numérotés
  const usbOf = i => (((imap && imap.usb) || [])[i]) || null;
  const vetoUsb = i => {                    // contrôleur MIDI : services keys/pads OU port numéroté coupé
    const u = usbOf(i);
    if (!u || !u.bound) return false;
    const roles = u.role === 'keys-pads' ? ['keys', 'pads'] : [u.role];
    return roles.every(r => svcOff(r)) || offNumbered(u);
  };
  const vetoTag = () => html`<span class="sc-veto">off in ${modeSt.name || 'this'} mode</span>`;
  const inName = ch => roleTag(pIn(ch));
  const outName = ch => roleTag(pOut(ch));
  const outLbl = c => (nOut === 2 ? (c === 1 ? 'OUT L' : 'OUT R') : `OUT ${c}`);

  // fiche détail par prise — status = phrase d'état, body = contenu riche optionnel.
  // Prises audio : DYNAMIQUES (in<N> / out<N>, autant que la carte en a) ; le reste est fixe.
  const inDetail = c => {
    const ch = String(c), linked = pairAt(c), first = c % 2 === 1;
    if (linked && !first) return {
      name: html`INPUT ${c} — linked with INPUT ${c - 1} (stereo pair)`,
      status: cap ? 'active' : 'engine not holding the card',
      body: html`<div class="sc-drow"><span>Stereo pair</span>
        <button class="sc-chip onn" onClick=${() => setPair(c - 1, false)}><${Icon} id="link" /> unlink</button></div>` };
    const clip = ((s.clip || {})[`in${c}`]);                // écrêtage d'entrée (state.clip, 2026-09-14)
    return { name: html`INPUT ${c} — ${desktop ? (inputNames[c - 1] || 'audio input') : (inName(ch) || 'combo XLR / jack')}${linked ? ` (stereo ${c}+${c + 1})` : ''}`,
      status: clip && clip.age < 3 ? `⚠ clipping — input hits 0 dBFS: lower the gain on the interface (${clip.count}×)`
        : clip ? `active — clipped ${clip.count}× this session: lower the gain on the interface` : cap ? 'active — captured by the audio engine' : 'engine not holding the card',
      body: inBody(ch) };
  };
  const outDetail = c => ({
    name: html`${outLbl(c)} — ${desktop ? (outputNames[c - 1] || 'audio output') : (outName(String(c)) || 'monitor')}`,
    status: pb ? 'active — engine playing to the card' : 'engine not holding the card',
    body: outBody(String(c)) });
  // ── Windows/macOS : les prises DIN sont des ports MIDI CHOISIS (bridge/desktop_midi.py) — sous Linux
  // c'est le MIDI de la carte son, rien à choisir. Un port ne s'ouvre qu'une fois sous Windows : REAPER
  // doit le lâcher, ce qu'il ne fait qu'en redémarrant (bandeau « restart » plus haut).
  const deskStatus = k => {
    const port = midi[k + '_port'], active = midi[k + '_active'], present = midi[k + '_present'];
    if (active) return `active — ${k === 'in' ? 'golem is listening on' : 'golem is sending to'} ${port}`;
    if (!port) return `no port chosen — pick the ${k === 'in' ? 'pedalboard' : 'Whammy'}’s MIDI port below`;
    if (!present) return `${port} is not plugged in`;
    if (k === 'out') return `ready — ${port} opens with the first message golem sends`;
    return midi.restart_needed ? `${port} is held by REAPER — tap « Restart for MIDI » above` : `${port} chosen, not open yet`;
  };
  const PortPicker = k => {
    // un clavier lié à une lane (USB n) n'est pas proposé : il ne peut pas être aussi le pédalier
    const boundNames = Object.values((sc && sc.binding) || {}).map(b => String(b.device || '').toLowerCase());
    const isBound = p => boundNames.some(b => b && (b.includes(p.toLowerCase()) || p.toLowerCase().includes(b)));
    const list = (((midi.ports || {})[k]) || []).filter(p => !isBound(p) && !/wavetable/i.test(p)), cur = midi[k + '_port'];
    const fromEnv = midi[k + '_source'] === 'env';
    const pick = async port => { await post('/api/soundcard/midi-port', { kind: k, port }).catch(() => {}); reload(); reloadImap(); };
    return html`<div class="sc-drow sc-roles"><span>Port</span>
      <button class=${cls('sc-chip', !cur && 'onn')} disabled=${fromEnv} onClick=${() => pick(null)}>· none</button>
      ${list.map(p => html`<button class=${cls('sc-chip', cur && cur.toLowerCase() === p.toLowerCase() && 'onn')}
        disabled=${fromEnv} onClick=${() => pick(p)}>${p}</button>`)}
      ${cur && !list.some(p => p.toLowerCase() === cur.toLowerCase()) ? html`<button class="sc-chip onn" disabled>${cur} · unplugged</button>` : ''}
    </div>
    ${fromEnv ? html`<p class="muted">Set by ${k === 'in' ? 'GOLEM_FCB_PORT' : 'GOLEM_MIDI_PORT'} on this computer — remove that variable to choose here.</p>` : ''}`;
  };
  const restartEngine = async () => { setRestarting(true); await post('/api/system/reaper-restart', {}).catch(() => {});
    setTimeout(() => { setRestarting(false); reload(); }, 15000); };
  const DETAILS = {
    phones: () => ({ name: 'PHONES', status: pb ? 'mirrors the main mix' : 'engine not holding the card',
      body: html`<p class="muted">Hardware headphone out of the card — level knob on the unit.</p>` }),
    midiin: () => ({ name: html`MIDI IN — ${dinName('midi_in') || 'DIN'}`,
      status: dinCur('midi_in').role === 'none' ? 'OFF — incoming MIDI ignored (kill-switch)'
        : desktop ? deskStatus('in') : midi.in_active ? 'active — golem is listening' : (midi.present ? 'port up, nothing listening' : 'no MIDI port'),
      body: html`
        ${desktop ? PortPicker('in') : ''}
        ${RoleChips('midi_in', null, dinCur('midi_in').role, imap && imap.midi_in_roles)}
        <p class="muted">${dinCur('midi_in').role === 'none'
          ? 'A rogue MIDI cable can no longer drive anything — re-enable before playing with the pedalboard.'
          : 'Pedalboard (FCB1010) → scenes, stomps, presets, EXP pedals.'}</p>` }),
    midiout: () => ({ name: html`MIDI OUT — ${dinName('midi_out') || 'DIN'}`,
      status: dinCur('midi_out').role === 'none' ? 'OFF — outbound performance MIDI muted'
        : desktop ? deskStatus('out') : midi.out_active ? 'active — golem is sending' : (midi.present ? 'port up, nothing sending' : 'no MIDI port'),
      body: html`
        ${desktop ? PortPicker('out') : ''}
        ${RoleChips('midi_out', null, dinCur('midi_out').role, imap && imap.midi_out_roles)}
        <p class="muted">${dinCur('midi_out').role === 'none'
          ? 'Whammy glue muted (scenes arming it are logged, never silent). FCB1010 SysEx flash stays available — maintenance, not performance.'
          : 'Outboard control (Whammy DT : pitch CC11, mode PC) + FCB1010 flash.'}</p>` }),
    usb1: () => usbDetail(0), usb2: () => usbDetail(1), usb3: () => usbDetail(2), usb4: () => usbDetail(3),
  };
  const usbDetail = i => {
    const d = usbAt(i);
    const bind = (sc && sc.binding && sc.binding['usb' + (i + 1)]) || null;
    const roles = (bind && bind.roles) || ['keys', 'pads'];       // rétro-compat : sans roles = les deux
    const toggle = async () => {
      await post('/api/soundcard/usb', { port: i + 1, enabled: !bind }).catch(() => {});
      reload();
    };
    // rôles du contrôleur (P0 claviers) : un 88 dédié = keys seul, il PRIME alors sur
    // l'hybride AKAI pour les touches ; les pads restent à qui a le rôle pads.
    const kits = (dk && dk.kits) || [];
    const kitOf = ((imap && imap.usb) || [])[i] && imap.usb[i].kit;   // résolu par le bridge (choisi, ou identifié par USB)
    const setRole = async r => {
      // drums est EXCLUSIF (un module de batterie n'est ni un clavier ni des pads) ; keys/pads se combinent
      const next = r === 'drums' ? ['drums'] : (roles.includes(r) ? roles.filter(x => x !== r) : [...roles.filter(x => x !== 'drums'), r]);
      if (!next.length) return;                                   // au moins un rôle
      await post('/api/soundcard/usb', { port: i + 1, enabled: true, roles: next }).catch(() => {});
      reload();
    };
    return { name: `USB ${i + 1} — golem USB`, status: d ? `${d.name} connected (${d.kind})` : 'nothing connected',
      body: html`
        <div class="sc-drow"><span>MIDI lane</span>
          <button class=${cls('sc-chip', bind ? 'onn' : 'off')} disabled=${!d && !bind} onClick=${toggle}>
            ${bind ? html`<${Icon} id=${roles.includes('drums') ? 'drums' : 'keys'} /> enabled — ${bind.device}` : '＋ enable MIDI lane'}</button>
          ${bind ? html`<span class="muted">${roles.includes('drums') ? 'presets get a Drums lane driven by this drum module' : 'presets get a Keys lane (Designer ▸ Keys) driven by this controller'}</span>` : ''}
        </div>
        ${bind ? html`<div class="sc-drow"><span>Roles</span>
          <button class=${cls('sc-chip', roles.includes('keys') ? 'onn' : 'off')} onClick=${() => setRole('keys')}><${Icon} id="keys" /> keys</button>
          <button class=${cls('sc-chip', roles.includes('pads') ? 'onn' : 'off')} onClick=${() => setRole('pads')}><${Icon} id="pads" /> pads</button>
          <button class=${cls('sc-chip', roles.includes('drums') ? 'onn' : 'off')} onClick=${() => setRole('drums')} title="an electronic drum module over USB-MIDI — the rack plays its kits (docs/drums-kit.md)"><${Icon} id="drums" /> drums</button>
          <span class="muted">${roles.includes('drums') ? 'a drum module: its pads play the rack kits' : 'a keys-only controller (88-key board) takes over the keys — unplug it and the hybrid falls back'}</span>
        </div>` : ''}
        ${bind && roles.includes('drums') ? html`<div class="sc-drow"><span>Kit</span>
          ${/* docs/calibration.md addendum 2026-09-23 : le descripteur ne se CHOISIT plus ici — il s'identifie
                par le nom USB et se MESURE dans Calibration ▸ Drums. Le `select` d'avant était un binding qui
                croyait un fichier sur parole (la Nitro : faux sur quatre points). Ici, une lecture et le lien. */''}
          <span class="sc-kit">${kitOf ? html`<b>${esc(kitOf.name)}</b> ${kitOf.confidence === 'verified' ? html`<span class="pb-prov verified" title="measured on this very module">✓ verified</span>`
            : kitOf.fallback ? html`<span class="pb-prov unconfirmed" title="nothing matches this USB name — measure it to create a descriptor">? GM fallback</span>`
            : html`<span class=${cls('pb-prov', kitOf.confidence || 'unknown')} title="never measured on this rig">${kitOf.confidence === 'reported' ? '~ reported' : '? unconfirmed'}</span>`}` : '…'}</span>
          <button class="sc-chip off" onClick=${() => go('system/gear/drums')} title="Settings ▸ Gear ▸ Drums — measure this module pad by pad">
            ${kitOf && kitOf.confidence === 'verified' ? 'Re-measure' : 'Calibrate'}</button>
          <span class="muted">${kitOf ? (kitOf.confidence === 'verified' ? 'measured on this kit' : kitOf.fallback ? 'no descriptor matches — measure this kit' : 'table from a manual — not measured yet') : ''}</span>
        </div>` : ''}
        ${!d && !bind ? html`<p class="muted">Plug a MIDI controller (e.g. AKAI MPK mini, an 88-key board) or a drum module into this port.
          ${knownOff.length ? html`<br />Known, not connected: ${knownOff.map(k => html`<b>${esc(k.name)}</b> (${(k.roles || []).join(' + ')}${k.person_name ? ' · ' + k.person_name : ''}) `)}— plug it in, it activates by itself.` : ''}</p>` : ''}` };
  };
  const detailFor = id => {
    if (!id) return null;
    let m;
    if ((m = /^in(\d+)$/.exec(id))) return inDetail(parseInt(m[1], 10));
    if ((m = /^out(\d+)$/.exec(id))) return outDetail(parseInt(m[1], 10));
    return DETAILS[id] ? DETAILS[id]() : null;
  };
  const det = detailFor(sel);

  // J(id, glyphe, nom technique, actif, TAG input-map au-dessus, sous-titre en-dessous)
  const J = (id, glyph, label, on, tag, sub, veto) => html`<${Jack} glyph=${glyph} label=${label}
    tag=${veto ? vetoTag() : tag} sub=${sub} on=${on && !veto} veto=${veto}
    sel=${sel === id} onTap=${() => setSel(sel === id ? null : id)} />`;

  // cartes CANDIDATES au switch (branchées, non actives, non ignorées) — gear-registry É2/É3 :
  // adopter = probe + registre + reaper.ini + restart moteur (~10 s) ; l'input map de l'ancienne
  // carte reste sauvé dans config/patches/ (retour sans reconfiguration)
  const cands = ((s.cards || {}).candidates) || [];
  const known = ((s.cards || {}).known) || [];        // le registre : branché ou non, préparé ou non
  const [adopting, setAdopting] = useState(null);
  const adopt = async id => {
    setAdopting(id);
    await post('/api/cards/adopt', { id }).catch(() => {});
    setTimeout(() => setAdopting(null), 15000);   // filet : l'UI suit le restart via le WS
  };
  // veille hotplug (audit 2026-08-12 §3, chantier ⑤) : appareils MIDI USB identifiés à
  // l'insertion — une bannière discrète par appareil qui a quelque chose à proposer
  // (contrôleur calibré non bindé, pédalier USB en cours de sonde, inconnu). Pas un centre
  // de notifications : bindé/actif = silence, et binder reste un GESTE (les prises USB dessous).
  const hplug = (((s.hotplug || {}).devices) || []).filter(d => d.propose);
  const hplugHint = d =>
    d.kind === 'controller' ? html`${esc(d.label)} — <b>bind it below (USB ports)</b>`
    : d.kind === 'pedalboard' ? html`${esc(d.label)} — identity probe running`
    : d.kind === 'drums' ? html`${esc(d.label)} — <b>bind it below as drums (USB ports)</b>, then measure it in Settings ▸ Gear ▸ Drums`
    : html`unknown MIDI device — calibrate it in Settings ▸ Gear ▸ Controllers`;
  return html`
    <div class="sc-page pg-fit">
      ${!desktop ? cands.map(c => html`<div class="sc-newcard">
        <span>⚡ <b>${esc(c.name)}</b> detected${c.known ? '' : ' (new)'}</span>
        <button class="primary" disabled=${!!adopting}
          title="probe the card, save it to the registry, switch Reaper to it and restart the engine (~10 s) — the current card's setup is kept"
          onClick=${() => adopt(c.id)}>${adopting === c.id ? '⏳ switching…' : 'Switch to it'}</button>
        <button class="mini" disabled=${!!adopting} title="never suggest this card (e.g. the dock's audio)"
          onClick=${() => post('/api/cards/ignore', { id: c.id }).catch(() => {})}>ignore</button>
      </div>`) : ''}
      ${hplug.map(d => html`<div class="sc-newcard sc-hotplug">
        <span>🎛 <b>${esc(d.name)}</b> detected — ${hplugHint(d)}</span>
      </div>`)}
      <div class="sc-head">
        <b>${sc && sc.card && sc.card.present ? (sc.card.name || sc.card.alsa) : 'soundcard not detected'}</b>
        <span class="muted">${sc && sc.card ? `${sc.card.backend || 'ALSA'} ${sc.card.alsa}` : ''}${desktop && sc.card.inputs != null ? ` · ${nIn} enabled in / ${nOut} enabled out` : ''}${sc && sc.bsize ? ` · ${sc.bsize} smp` : ''}${lat != null ? ` · ${lat} ms${desktop ? ' REAPER' : ''}` : ''}</span>
        ${desktop ? html`<button class="mini" onClick=${() => setAudioOpen(true)}>Configure ${sc.card.backend || 'audio'}…</button>` : ''}
        ${desktop && (midi.restart_needed || restarting) ? html`<button class="mini sc-restart" disabled=${restarting} onClick=${restartEngine}
          title="REAPER opens and releases MIDI ports only when it starts: the pedalboard port must be released, a bound keyboard opened">
          ${restarting ? '⏳ restarting…' : '⟳ Restart for MIDI'}</button>` : ''}
        ${modeSt.id ? html`<a class="sc-mode-chip" href="#/system/mode" title="active mode — tap to open the Mode tab">
          <${Icon} id=${modeSt.id} fallback=${modeSt.icon} /> ${modeSt.name}</a>` : ''}
        ${/* ── LES CARTES CONNUES, branchées ou non (gear-registry É3) — EN CHIP, PLUS EN RANGÉE (2026-09-24 :
              « ça décale toute l'UX vers le bas et le détail d'une entrée n'est plus visible »). Mesuré : la
              rangée faisait 64 px sur deux lignes et poussait le détail à y = 553 (bas à 657 sur 600). Une carte
              absente garde son patch (config/inputmaps/hw-<id>.json) : ça reste vrai, ça ne coûte plus une ligne. */''}
        ${cs && chipLabel(cs) ? html`<span class="sc-known-wrap sc-sync-wrap">
          <button class=${cls('sc-known-chip sc-sync-chip', syncOpen && 'on')} onClick=${() => setSyncOpen(!syncOpen)}
            title=${(cs.offers || []).length ? 'another rack offers its setup for this card — tap to compare' : 'this card is also set up on another rack, differently — tap to compare'}>
            ${chipLabel(cs)}</button>
          ${syncOpen ? html`<div class="sc-known-pop sc-sync-pop" onClick=${e => e.stopPropagation()}>
            ${(() => { const offer = (cs.offers || [])[0] || null;
              const sib = offer ? null : (cs.siblings || []).find(s => !s.same && !s.separate) || null;
              const other = offer ? offer.setup : sib, who = offer ? (offer.from_name || offer.from_rack || 'another rack') : ((sib || {}).rack_name || 'Rack');
              const whoSub = offer ? 'offered ' + (offer.offered_at || '').slice(0, 10) : ((sib || {}).os || '') + ' · ' + ((sib || {}).card || '');
              const rows = setupRows(cs.local, other, (imap || {}).instruments, people);
              return html`<div class="sc-sync-t"><b>${offer ? 'Setup offered by ' + esc(who) : 'Same card, two setups'}</b><span>${esc(sc && sc.card ? (sc.card.name || sc.card.alsa) : '')} · USB ${esc(cs.usb || '')}</span></div>
                <table class="sc-sync-tbl"><tr><th></th><th class="here">here · ${esc(cs.local && cs.local.os ? cs.local.os : 'this computer')}</th><th class="there">${esc(who)} · ${esc(whoSub)}</th></tr>
                  ${rows.map(r => html`<tr><td class="k">${r.k}</td><td class=${r.same ? 'same' : 'd'}>${esc(r.here)}</td><td class=${r.same ? 'same' : 'd'}>${esc(r.there)}</td></tr>`)}
                </table>
                <div class="sc-sync-acts">
                  ${offer ? html`<button class="p" disabled=${syncBusy} onClick=${() => syncDo('/api/card-setups/offers/' + encodeURIComponent(offer.offer_id) + '/reply', { status: 'applied' }, '✓ setup applied')}>Use it here</button>
                      <button disabled=${syncBusy} onClick=${() => syncDo('/api/card-setups/offers/' + encodeURIComponent(offer.offer_id) + '/reply', { status: 'declined' }, 'offer declined')}>Decline</button>`
                    : html`<button class="p" disabled=${syncBusy} onClick=${() => syncDo('/api/card-setups/apply', { rack: sib.rack }, '✓ ' + who + '\'s setup applied here')}>Use the ${esc(who)}'s setup here</button>
                      <button disabled=${syncBusy} onClick=${() => syncDo('/api/card-setups/offer', { to_rack: sib.rack }, '✓ offered to ' + who + ' — it decides at its next check-in')}>Offer this setup to ${esc(who)}</button>
                      <button class="q" disabled=${syncBusy} onClick=${() => syncDo('/api/card-setups/separate', { rack: sib.rack }, 'kept separate')}>Keep them separate</button>`}
                </div>
                <p class="sc-sync-note">Presets are not touched: a lane bound to <b>Guitar 1</b> follows whichever input carries that name.${offer ? '' : ' Offering goes through golem.fm: the other rack decides on the spot.'}</p>`; })()}
          </div>` : ''}
        </span>` : ''}
        ${syncMsg ? html`<span class="sc-sync-msg">${esc(syncMsg)}</span>` : ''}
        ${known.length > 1 ? html`<span class="sc-known-wrap">
          <button class=${cls('sc-known-chip', knownOpen && 'on')} onClick=${() => setKnownOpen(!knownOpen)}
            title="the cards this rack knows — plugged in or not; an absent card keeps its input patch">
            ${known.length - 1} more known ▾</button>
          ${knownOpen ? html`<div class="sc-known-pop" onClick=${e => e.stopPropagation()}>
            ${known.map(k => html`<span class=${cls('sc-kcard', k.active && 'on', !k.connected && 'away')}
                title=${k.active ? 'active — this is the card the engine holds'
                  : k.connected ? 'plugged in — switch to it below'
                  : (k.prepared ? 'not plugged in — its input patch is ready and waiting'
                                : 'not plugged in — no input patch yet (name its inputs in Settings ▸ Mode)')}>
              <b>${esc(k.name || k.id)}</b>
              <i>${k.inputs != null ? k.inputs + ' in' : ''}${k.outputs != null ? ' · ' + k.outputs + ' out' : ''}</i>
              ${k.active ? html`<u class="ok">active</u>`
                : !k.connected ? html`<u>${k.prepared ? 'ready · not plugged in' : 'not plugged in'}</u>`
                : html`<u class="ok">plugged in</u>`}
            </span>`)}
          </div>` : ''}
        </span>` : ''}
      </div>
      ${/* LA FACE ARRIÈRE EN DEUX RANGÉES (maquette validée 2026-09-09) : la CARTE branchée (entrées, sorties,
            PHONES) et le RACK (USB 1..4 + MIDI DIN, propriété du serveur, toujours là). Au-delà de 6 jacks dans
            un groupe : pastilles en lignes de 9. La carte que le mode attend se replie dans la rangée carte. */''}
      <div class="sc-board2">
        <div class="sc-row">
          <div class="sc-rl"><b>CARD</b><small class=${cls(!(sc && sc.card && sc.card.present) && 'off')}>${sc && sc.card && sc.card.present ? esc(sc.card.name || sc.card.alsa) : 'none'}</small></div>
          ${Group('INPUTS', nIn > 6
            ? Pins(Array.from({ length: nIn }, (_, i) => { const c = i + 1, e = pIn(String(c)), linked = pairAt(c), first = c % 2 === 1;
                return html`<${Pin} n=${c} icon=${e && e.role && e.role !== 'none' ? html`<${Icon} id=${e.role} fallback=${e.icon} />` : null}
                  on=${cap && !!(e && e.role && e.role !== 'none')} sel=${sel === 'in' + c} pair=${linked && first} pair2=${linked && !first} veto=${vetoIn(String(c))}
                  title=${e && e.name ? e.name + (e.person_name ? ' · ' + e.person_name : '') : 'IN ' + c + ' — unassigned'}
                  onTap=${() => setSel(sel === 'in' + c ? null : 'in' + c)} />`; }))
            : (() => {                                        // N prises + maillon ⛓ entre chaque paire matérielle
                const js = [];
                for (let c = 1; c <= nIn; c++) {
                  const linked = pairAt(c), first = c % 2 === 1;
                  js.push(J('in' + c, G.combo, `INPUT ${c}`, cap,
                            linked && !first ? '(stereo pair)' : inName(String(c)),
                            desktop ? inputNames[c - 1] : ((pIn(String(c)) || {}).person_name || null), vetoIn(String(c))));
                  if (first && c + 1 <= nIn) js.push(html`<button class=${cls('sc-link edit-only', linked && 'onn')}
                    title=${linked ? `stereo pair ${c}+${c + 1} — tap to unlink` : `link ${c}+${c + 1} as one stereo instrument`}
                    onClick=${() => setPair(c, !linked)}><${Icon} id="link" /></button>`);
                }
                return js;
              })(), nIn > 6 && 'pins')}
          ${Group('OUTPUTS', nOut > 6
            ? Pins(Array.from({ length: nOut }, (_, i) => { const c = i + 1, e = pOut(String(c)), pairO = !!(e && String(e.ch).includes('-')), first = c % 2 === 1;
                return html`<${Pin} n=${c} icon=${e && e.role && e.role !== 'none' && e.role !== 'other' ? html`<${Icon} id=${e.role} fallback=${e.icon} />` : null}
                  on=${pb && !!(e && e.role && e.role !== 'other')} sel=${sel === 'out' + c} pair2=${pairO && !first}
                  title=${e && e.label ? e.label + ' · OUT ' + e.ch : 'OUT ' + c} onTap=${() => setSel(sel === 'out' + c ? null : 'out' + c)} />`; }))
            : [...Array.from({ length: nOut }, (_, i) => { const c = i + 1, e = pOut(String(c)), pairO = !!(e && String(e.ch).includes('-'));
                 // comme les entrées et comme sous Linux : le RÔLE au-dessus (Monitors…), le nom du canal du
                 // pilote ASIO/CoreAudio dessous — il prenait la place du rôle (2026-10-02)
                 return J('out' + c, G.jack, outLbl(c), pb, pairO && c % 2 === 0 ? '(stereo pair)' : outName(String(c)),
                          desktop ? outputNames[c - 1] : null); }),
               ...(desktop ? [] : [J('phones', G.phones, 'PHONES', pb, null, 'mirrors main')])], nOut > 6 && 'pins')}
          ${nOut > 6 && !desktop ? Group('', [J('phones', G.phones, 'PHONES', pb, null, 'mirrors main')]) : ''}
          ${modeSt.card && sc && sc.card && !sc.card.backend && !sameCard(sc.card.alsa, modeSt.card) ? html`<div class="sc-group sc-waitgrp">
            <div class="sc-wait">
              <span>⏳</span>
              <span><b>${esc(modeSt.name)} prefers « ${esc(String(modeSt.card).replace(/^hw:/, ''))} »</b> — not connected${sc.card.present ? ', using the ' + esc(sc.card.name || sc.card.alsa) : ''}. Lanes bound to its inputs wait.</span>
              <button class="mini" title="name the inputs of that card now — the patch is ready when it is plugged in"
                onClick=${() => { try { sessionStorage.setItem('golem.openInputs', '1'); } catch (e) {} go('system/mode'); }}>Prepare its patch →</button>
            </div></div>` : ''}
        </div>
        <div class="sc-row">
          ${/* Windows/macOS aussi depuis le 2026-10-02 (« je n'ai pas de 2e ligne USB et MIDI ») :
                USB n = les autres ports MIDI de l'OS, MIDI IN/OUT = les ports choisis (bridge/desktop_midi.py) */''}
          <div class="sc-rl"><b>${desktop ? 'MIDI' : 'RACK'}</b><small>${desktop ? 'this computer' : 'golem'}</small></div>
          ${Group('USB', [0, 1, 2, 3].map(i => J('usb' + (i + 1), G.usb, 'USB ' + (i + 1), !!(usbOf(i) && usbOf(i).bound) || !!usbAt(i), usbTag(i), usbSub(i), vetoUsb(i))), 'usb')}
          ${Group('MIDI', [J('midiin', G.din, 'MIDI IN', !!midi.in_active && dinCur('midi_in').role !== 'none', dinName('midi_in'), desktop ? midi.in_port : null),
                           J('midiout', G.din, 'MIDI OUT', !!midi.out_active && dinCur('midi_out').role !== 'none', dinName('midi_out'), desktop ? midi.out_port : null)])}
        </div>
      </div>
      <div class=${cls('sc-detail', !det && 'empty')}>
        ${det ? html`<div class="sc-dhead"><b>${det.name}</b><span class=${cls('sc-status', det.status.startsWith('active') || det.status.includes('connected (') || det.status.startsWith('mirrors') ? 'on' : '')}>${det.status}</span></div>${det.body}`
              : html`<span class="muted">Tap a jack to see its status — green = plugged / in use.</span>`}
      </div>
      ${/* LA PREMIÈRE RENCONTRE (maquette, écran 2) : la carte vient d'être semée sous un nom nouveau et golem.fm la
            connaît d'un autre rack — une question, une fois ; « Later » sème les défauts et laisse le chip */''}
      ${cs && cs.ask && (cs.siblings || []).length && !audioOpen ? (() => { const sib = cs.siblings[0];
        const rows = setupRows(null, sib, (imap || {}).instruments, people).filter(r => r.kind !== 'midi' || sib.midi_in || sib.midi_out);
        const mine = setupRows(cs.local, null, (imap || {}).instruments, people);
        return html`<div class="sc-audio-overlay"><div class="sc-audio-dialog sc-ask" onClick=${e => e.stopPropagation()}>
          <h2>New setup for ${esc(sc && sc.card ? (sc.card.name || sc.card.alsa) : 'this card')} on this computer</h2>
          <p class="sub">golem.fm knows this card from your <b>${esc(sib.rack_name || 'rack')}</b> (${esc(sib.os || '')}, ${esc(sib.card || '')}). Which inputs do what here?</p>
          <div class="sc-ask-opt rec"><div><b>Start from the ${esc(sib.rack_name || 'rack')}'s setup</b><span>Same cabling as that rack. You can change any input afterwards.</span>
            <div class="ins">${rows.map(r => html`<i>${r.k} <u>·</u> ${esc(r.there)}</i>`)}</div></div>
            <button class="p" disabled=${syncBusy} onClick=${() => syncDo('/api/card-setups/apply', { rack: sib.rack }, '✓ setup applied')}>Use this setup</button></div>
          <div class="sc-ask-opt"><div><b>Keep this computer’s setup</b><span>Cabled differently here — what this computer has stays.</span>
            <div class="ins">${mine.filter(r => r.kind === 'in').map(r => html`<i>${r.k} <u>·</u> ${esc(r.here)}</i>`)}</div></div>
            <button disabled=${syncBusy} onClick=${() => syncDo('/api/card-setups/later', {}, 'kept this computer’s setup — compare any time from the ⇄ chip')}>Keep it</button></div>
          <p class="sc-sync-note">Your presets bind to input <b>names</b> (“Guitar 1”), not numbers: they play on whichever input you choose here.</p>
        </div></div>`; })() : ''}
      ${audioOpen ? html`<div class="sc-audio-overlay" onClick=${() => setAudioOpen(false)}>
        <div class="sc-audio-dialog" onClick=${e => e.stopPropagation()}>
          <button class="mini sc-audio-close" onClick=${() => setAudioOpen(false)}>Close</button>
          <${DesktopAudioPage} onDone=${() => { reload(); reloadImap(); }} />
        </div>
      </div>` : ''}
    </div>`;
}

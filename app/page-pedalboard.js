// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Calibration (hub Settings) : Controllers · Pedals · Pedalboard · Drums (2026-09-23).
// Pedalboard est un MIROIR — il montre ce que le rack VOIT du pédalier branché, en direct, et rien
// d'autre. Ce qui est rare part en prise plein cadre : `Set up` (la procédure du descripteur) et
// `⋯ ▸ Teach` (apprendre un pédalier inconnu à l'écoute).
// Interface en ANGLAIS ; commentaires en français.
import { html, useState, useEffect, useRef, useAsync, post, cls, esc, LoadGuard } from './lib.js';
import { PedalsPage, InstallSteps } from './page-pedals.js';
import { ControllersPanel } from './calibration.js';
import { DrumsPanel } from './calibration-drums.js';   // Drums (addendum 2026-09-23) : le module se MESURE ici

// Le stepper d'installation N'EST PLUS ICI : il vit en DONNÉES, dans le fichier de l'appareil
// (mappings/<id>.json → `install.phases`), contrat docs/pedal-registry.md. Ce panneau est devenu
// un LECTEUR générique : il déroule les phases de n'importe quel appareil et rend les gestes que
// le rack sait offrir (`step.action`, aujourd'hui `fcb-flash`). Le process FCB1010 lui-même —
// 4 phases, 14 étapes, validé au pied le 2026-07-24 — n'a pas changé d'un mot, il a changé de
// place : une procédure d'installation est de la donnée d'appareil, pas du code d'écran.

// ── le panneau SUIT le pédalier branché (contrat docs/pedalboards.md) ─────────────────────
// Il ne connaît AUCUN modèle : tout — le contrat affiché, les capacités, la procédure,
// l'intitulé du bouton de charge — vient du descripteur de l'appareil actif. Une phrase écrite
// à la main est une phrase qui finira par mentir : celle d'avant annonçait encore « UnO 1.0.4,
// MIDI channel 1 » alors que la puce avait changé et parlait sur le canal 2.

// « measured » = la puce s'est identifiée (firmware + série à l'appui). « declared » = personne
// n'a répondu, on affiche ce qui est coché. La distinction est VISIBLE parce que la confondre
// fait chercher la panne au mauvais étage — et parce qu'une seule des deux puces sait répondre.
function SourceBadge({ active }) {
  // aucun pédalier déclaré ni mesuré (install neuve, 2026-11-03 : plus d'appareil par défaut)
  if (active.source === 'fallback') return html`<span class="pb-src declared"
    title="No pedalboard is selected and none answered — pick yours in ⋯, or plug it in and tap Detect">○ none selected</span>`;
  const measured = active.source === 'measured';
  return html`<span class=${cls('pb-src', measured ? 'measured' : 'declared')}
    title=${measured ? 'The chip answered the identity request'
                     : 'Nothing answered — this is what is selected, not what was found'}>
    ${measured ? '● measured' : '○ declared'}
  </span>`;
}

// Une suite contiguë se dit « 20–24 », pas « 20/21/22/23/24 » : sur 1024×600 chaque ligne
// gagnée sur la fiche est une ligne rendue à la procédure, qui est ce qu'on lit vraiment.
const span = (xs) => {
  if (!xs.length) return '—';
  const contiguous = xs.every((v, i) => i === 0 || v === xs[i - 1] + 1);
  return contiguous && xs.length > 1 ? `${xs[0]}–${xs[xs.length - 1]}` : xs.join('/');
};

// DEUX QUESTIONS DIFFÉRENTES, et les confondre coûte cher :
//   « mesuré / déclaré »  -> est-ce bien CETTE puce qui est branchée ?
//   la provenance          -> a-t-on de bonnes raisons de croire ce que le fichier en dit ?
// Un descripteur écrit d'après une doc constructeur ressemble EXACTEMENT à un descripteur mesuré
// au pied. Sans ce badge, une table jamais éprouvée aurait l'air d'une vérité — et c'est pire
// que pas de descripteur du tout, parce qu'on ne la remet pas en question.
const PROVENANCE = {
  verified:    ['✓ verified',    'checked on the actual hardware'],
  reported:    ['~ reported',    'comes from a manual or a third party — not checked here'],
  unconfirmed: ['? unconfirmed', 'never checked on this rig — treat as a lead, not a fact'],
};

function ProvenanceBadge({ provenance }) {
  const p = provenance || {};
  const [label, why] = PROVENANCE[p.confidence] || ['? unknown', 'no provenance declared'];
  return html`<span class=${cls('pb-prov', p.confidence || 'unknown')}
    title=${why + (p.source ? ` · source: ${p.source}` : '') + (p.note ? `\n\n${p.note}` : '')}>
    ${label}
  </span>`;
}

function Contract({ contract, device, unmet }) {
  const caps = device.capabilities || {};
  const goto = caps.goto_bank || {};
  const scenes = contract.scenes || [], stomps = contract.stomps || [];
  const names = scenes.map(s => s.name);
  const facts = [
    ['MIDI channel', device.channel],
    ['Setlist slots', contract.slots],
    ['Scenes', `${names[0] || '—'}–${names[names.length - 1] || '—'} · CC ${span(scenes.map(s => s.cc))}`],
    ['Stomps', `SW ${span(stomps.map(s => s.switch))} · CC ${span(stomps.map(s => s.cc))}`],
    ['Expression', (contract.expression || []).map(e => `EXP${e.pedal}=CC${e.cc}`).join(' · ')],
  ];
  const chips = [
    [caps.identifies, 'identifies itself', 'cannot be detected'],
    [caps.gestures, 'press/release edges', 'no release edges'],
    [goto.supported, 'goto bank (ch ' + (goto.channel || '?') + ')', 'no remote bank'],
    [caps.load === 'wire', 'loads over the wire', 'needs foot setup too'],
  ];
  // Deux rangées de pastilles plutôt qu'une grille légendée : la fiche DÉCRIT, le stepper FAIT
  // FAIRE — sur 1024×600 la hauteur doit aller à celui qui fait faire.
  return html`<section class="card-panel pb-contract">
    <div class="pb-facts">
      ${facts.map(([k, v]) => html`<span class="pb-fact"><i>${k}</i>${esc(String(v ?? '—'))}</span>`)}
    </div>
    <div class="pb-caps">
      ${chips.map(([on, yes, no]) => html`<span class=${cls('pb-cap', on && 'on')}>${on ? yes : no}</span>`)}
      <${ProvenanceBadge} provenance=${device.provenance} />
    </div>
    ${unmet && unmet.length ? html`<p class="muted warn">⚠ Switch ${unmet.join(', ')} asks for
      press/release edges and this chip cannot give them — no long press there. Hardware limit,
      not a setting.</p>` : ''}
  </section>`;
}

// ── ÉCOUTE : apprendre un pédalier au lieu de le programmer ───────────────────────────────
// C'est le cas GÉNÉRAL. Les deux FCB sont des exceptions : on les programme pour qu'ils parlent
// le contrat GoleM. Tous les autres envoient ce qu'ils envoient — et les docs constructeur sont
// formelles (contrat §8 bis) : un ENGL Z9 ou un Diezel Columbus n'émettent QUE des Program
// Change, sans Note ni front de relâchement. Aucun réglage ne changera ça, donc c'est au rack
// de s'adapter.
const TARGETS = [
  ...['A', 'B', 'C', 'D', 'E'].map(n => ({ key: 'scene' + n, label: 'Scene ' + n, kind: 'scene', name: n })),
  ...[6, 7, 8, 9, 10].map(n => ({ key: 'stomp' + n, label: 'Stomp ' + n, kind: 'stomp', switch: n })),
  { key: 'exp1', label: 'Expression 1', kind: 'expression', pedal: 1, sweep: true },
  { key: 'exp2', label: 'Expression 2', kind: 'expression', pedal: 2, sweep: true },
];

const evKey = e => e && `${e.type}:${e.channel}:${e.number}`;
const evLabel = e => !e ? '—'
  : `${e.type === 'pc' ? 'PC' : e.type === 'cc' ? 'CC' : 'Note'} ${e.number} · ch ${e.channel + 1}`;

function LearnPanel({ onDone, onBack }) {
  const [on, setOn] = useState(false);
  const [name, setName] = useState('');
  const [live, setLive] = useState(null);
  const [bound, setBound] = useState({});     // key de cible -> événement capturé
  const [cursor, setCursor] = useState(0);
  const [saved, setSaved] = useState(null);
  const seenSeq = useRef(0);

  // Poll du flux d'écoute. On ne capture QUE si le curseur pointe une cible non remplie —
  // sinon le moindre appui parasite s'assignerait tout seul.
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => fetch('/api/pedalboard/learn/live').then(r => r.json()).then(d => {
      setLive(d);
      if (!d.last || d.seq === seenSeq.current) return;
      seenSeq.current = d.seq;
      const target = TARGETS[cursor];
      if (!target) return;
      const ev = d.last;
      // UNE COMMANDE PHYSIQUE, UN SEUL RÔLE. Sans ça, le contrôle qu'on vient d'assigner remplit
      // aussi le suivant : une pédale d'expression continue d'émettre après avoir été reconnue,
      // et le sondage suivant la voit encore. Mesuré à l'écran — les deux pédales avaient capturé
      // le même CC.
      if (Object.values(bound).some(b => evKey(b) === evKey(ev))) return;
      const stat = (d.seen || []).find(s => evKey(s) === evKey(ev)) || {};
      // Une pédale d'expression se PROUVE par le balayage : tant qu'on n'a pas vu passer
      // plusieurs valeurs, c'est peut-être un switch, et on ne veut pas se tromper de rôle.
      if (target.sweep && (stat.values || 0) < 5) return;
      // Un switch se déclare à l'APPUI. Le relâchement (valeur 0) arrive juste après et
      // écraserait la capture par le même événement — on l'ignore.
      if (!target.sweep && ev.type !== 'pc' && ev.value === 0) return;
      setBound(b => ({ ...b, [target.key]: { ...ev, values: stat.values || 1 } }));
      setCursor(c => Math.min(c + 1, TARGETS.length));
    }).catch(() => {}), 200);
    return () => clearInterval(t);
  }, [on, cursor, bound]);

  const start = async () => {
    setBound({}); setCursor(0); setSaved(null); seenSeq.current = 0;
    await post('/api/pedalboard/learn/start').catch(() => null);
    setOn(true);
  };
  const stop = async () => { await post('/api/pedalboard/learn/stop').catch(() => null); setOn(false); };

  const filled = Object.keys(bound).length;
  const channels = [...new Set(Object.values(bound).map(e => e.channel))];
  // Un switch qui envoie deux valeurs (127 puis 0) porte son ÉTAT et ses fronts : gestes
  // possibles. Un Program Change n'en porte aucun — pas d'appui long sur cet appareil.
  const edges = Object.entries(bound).some(([k, e]) => k.startsWith('stomp') && e.type !== 'pc' && e.values >= 2);
  const missing = TARGETS.filter(t => !bound[t.key]);

  const save = async () => {
    const bindings = Object.entries(bound).map(([key, ev]) => {
      const t = TARGETS.find(x => x.key === key);
      const intent = t.kind === 'scene' ? { kind: 'scene', name: t.name }
        : t.kind === 'stomp' ? { kind: 'stomp', switch: t.switch, absolute: ev.values >= 2, edges: ev.values >= 2 }
        : { kind: 'expression', pedal: t.pedal };
      return { event: { type: ev.type, channel: ev.channel, number: ev.number }, intent };
    });
    const r = await post('/api/pedalboard/learn/save', {
      name: name.trim() || 'Learned pedalboard', channel: (channels[0] ?? 0) + 1, bindings, edges,
    }).catch(e => ({ error: String(e) }));
    setSaved(r); setOn(false);
    if (r && r.ok && onDone) onDone();
  };

  return html`<div class="pb-learn">
    <section class="card-panel pb-head">
      <div class="pb-who">
        ${/* Une prise plein cadre DOIT porter sa sortie, visible en permanence : un mode sans
              échappatoire enferme l'utilisateur, et c'est arrivé (Alt+F4 pour en sortir). */''}
        <button class="chip" onClick=${async () => { await post('/api/pedalboard/learn/stop').catch(() => null); onBack && onBack(); }}>← Pedalboard</button>
        <b>Listen & learn</b>
        <span class="muted">press a switch, the rack writes it down</span>
      </div>
      <div class="pb-pick">
        <input placeholder="Pedalboard name" value=${name} onInput=${e => setName(e.target.value)} />
        ${on ? html`<button class="chip" onClick=${stop}>■ Stop</button>`
             : html`<button class="primary" onClick=${start}>● Listen</button>`}
      </div>
      <p class="muted">While listening, the pedalboard drives <b>nothing</b> — otherwise pressing a
        switch to declare it would change the song under your feet. Every channel is listened to:
        an unknown device's channel is part of what we learn.</p>
    </section>

    <section class="card-panel pb-learn-grid">
      ${TARGETS.map((t, i) => {
        const ev = bound[t.key];
        const active = on && i === cursor;
        return html`<button class=${cls('pb-slot', ev && 'got', active && 'arm')}
          onClick=${() => on && setCursor(i)}>
          <i>${t.label}</i>
          <b>${ev ? evLabel(ev) : active ? (t.sweep ? 'sweep it…' : 'press it…') : '—'}</b>
        </button>`;
      })}
    </section>

    <section class="card-panel pb-learn-foot">
      ${on && live ? html`<span class="muted">last seen: <b>${evLabel(live.last)}</b>
        ${live.last ? html` · value ${live.last.value}` : ''}</span>` : ''}
      ${filled ? html`<span class="muted">${filled} assigned${
        channels.length > 1 ? html` · <b class="warn">${channels.length} different channels</b>` : ''}${
        !edges ? html` · <b class="warn">no press/release edges — no long press</b>` : ''}</span>` : ''}
      ${filled && missing.length ? html`<span class="muted">not assigned: ${missing.map(t => t.label).join(', ')}</span>` : ''}
      <button class="primary" disabled=${!filled} onClick=${save}>Save & use it</button>
      ${saved && saved.ok ? html`<span class="flash-ok">✓ saved — this pedalboard now drives the rack.</span>` : ''}
      ${saved && saved.error ? html`<span class="flash-ko">✗ ${esc(saved.error)}</span>` : ''}
    </section>
  </div>`;
}

// ── LE MIROIR : ce que le rack VOIT du pédalier, en direct ────────────────────────────────
// La question quotidienne n'est pas « quelle puce est branchée » mais « est-ce que le rack
// m'entend ». Ce n'est PAS la même panne : une puce peut s'identifier parfaitement et pas un
// appui n'arriver — câble de jeu débranché, MIDI IN coupé dans l'input map. D'où « heard N ago »
// et la tuile qui s'allume : c'est la seule preuve que la chaîne pied -> rack fonctionne.
const ago = (t) => {
  if (!t) return null;
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 2 ? 'now' : s < 60 ? s + ' s ago' : s < 3600 ? Math.round(s / 60) + ' min ago' : 'a while ago';
};

function Mirror({ rig, contract, device, unmet, onFire }) {
  const st = (rig && rig.state) || {};
  const caps = device.capabilities || {};
  const goto = caps.goto_bank || {};
  const stomps = st.stomps || {};
  const heard = ago(st.foot_heard);
  const exps = contract.expression || [];
  const roles = st.pedals || { volume: 'exp1', block: 'exp2' };

  const tile = (label, sub, lit, bad) => html`<div class=${cls('pb-tile', lit && 'lit', bad && 'bad')}>
    <i>${label}</i><b>${sub}</b></div>`;

  return html`<div class="pb-mirror">
    <section class="card-panel pb-grid-wrap">
      <div class="pb-tiles">
        <div class="pb-row5">
          ${(contract.scenes || []).map(s => tile('Scene ' + s.name, 'CC ' + s.cc,
            st.scene_id === s.name))}
        </div>
        <div class="pb-row5">
          ${(contract.stomps || []).map(s => tile('Stomp ' + s.switch,
            (unmet || []).includes(s.switch) ? '⚠ no edges' : 'CC ' + s.cc,
            !!stomps[String(s.switch)], (unmet || []).includes(s.switch)))}
        </div>
      </div>
      <dl class="pb-side">
        <div><dt>channel</dt><dd>${device.channel}</dd></div>
        <div><dt>slots</dt><dd>${contract.slots}</dd></div>
        <div><dt>identifies</dt><dd class=${cls(caps.identifies && 'yes')}>${caps.identifies ? '✓' : '—'}</dd></div>
        <div><dt>edges</dt><dd class=${cls(caps.gestures && 'yes')}>${caps.gestures ? '✓' : '—'}</dd></div>
        <div><dt>goto bank</dt><dd class=${cls(goto.supported && 'yes')}>${goto.supported ? '✓' : '—'}</dd></div>
        <div><dt>loads</dt><dd class=${cls(caps.load === 'wire' && 'yes')}>${caps.load === 'wire' ? 'wire' : 'wire+foot'}</dd></div>
      </dl>
    </section>
    <section class="card-panel pb-exps">
      ${exps.map(e => {
        // Le CC PHYSIQUE et le RÔLE GoleM décrivent la même pédale : ils vivaient dans deux
        // écrans différents avec deux vocabulaires, le lecteur devait faire la jointure.
        const key = 'exp' + e.pedal;
        const val = st[key] || 0;
        const mine = roles.volume === key ? 'volume' : 'block';
        return html`<div class="pb-exp">
          <i>EXP ${e.pedal}</i><span class="muted">CC ${e.cc}</span>
          <div class="pb-bar"><div style=${`width:${Math.round(val / 127 * 100)}%`} /></div>
          <b>${val}</b>
          <span class="muted">role</span>
          <div class="tb-seg">
            ${[['volume', 'Volume'], ['block', 'Effect']].map(([r, lbl]) => html`<button
              class=${cls('ro-inert', mine === r && 'on')}
              onClick=${() => mine !== r && post('/api/pedals', { [r]: key })}>${lbl}</button>`)}
          </div>
        </div>`;
      })}
      ${!exps.length ? html`<span class="muted">This pedalboard has no expression pedal.</span>` : ''}
    </section>
  </div>`;
}

// La prise d'installation prend TOUT l'écran : le stepper de la 1.0.4 fait 14 étapes, et il
// n'avait que 119 px quand trois panneaux le précédaient. Ici il a le corps entier.
function SetupSheet({ device, mode, os, held: held0, onBack }) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [held, setHeld] = useState(!!held0);
  const [copied, setCopied] = useState(null);
  const [flashed, setFlashed] = useState(null);
  const load = async () => {
    setBusy(true); setRes(null);
    const r = await post('/api/pedalboard/load').catch(e => ({ error: String(e) }));
    setRes(r); setBusy(false);
  };
  const hold = async (on) => {
    const r = await post('/api/pedalboard/hold', { on }).catch(() => null);
    if (r) setHeld(!!r.ports_held);
  };
  // Windows / macOS : le setup TEXTE (vérifié côté bridge) part dans le presse-papiers. 127.0.0.1 est
  // un contexte sûr, mais un navigateur peut refuser l'API : on retombe sur une sélection + copie.
  const copy = async () => {
    setCopied({ busy: true });
    const r = await fetch('/api/pedalboard/setup-text').then(x => x.json()).catch(e => ({ error: String(e) }));
    if (r.error) { setCopied({ error: r.error }); return; }
    let ok = false;
    try { await navigator.clipboard.writeText(r.text); ok = true; } catch (e) { /* repli plus bas */ }
    if (!ok) {
      const ta = document.createElement('textarea');
      ta.value = r.text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
    }
    setCopied({ ...r, ok, lines: r.text.split('\n').length - 1 });
  };
  const declare = async () => {
    const r = await post('/api/pedalboard/flashed').catch(e => ({ error: String(e) }));
    setFlashed(r);
    if (r && r.ok) setHeld(false);            // le bridge a repris le port lui-même
  };
  const editor = device.editor || {};
  const actions = {
    'pedalboard-load': () => html`<div class="fcb-flash">
      <button class="primary big" disabled=${busy} onClick=${load}>
        ${busy ? '⏳ Loading…' : '⚡ ' + ((device.load || {}).label || 'Load')}
      </button>
      ${res && res.ok ? html`<span class="flash-ok">
        ${res.confirmed ? '✓ The chip confirmed.'
          : `✓ ${res.bytes} bytes sent — this chip confirms nothing, check its display.`}
      </span>` : ''}
      ${res && res.error ? html`<span class="flash-ko">✗ ${esc(res.error)}</span>` : ''}
    </div>`,
    'pedalboard-editor': () => html`<div class="fcb-flash">
      ${[['windows', 'Windows'], ['macos', 'macOS']].filter(([k]) => editor[k]).map(([k, lbl]) => html`<a
        class=${cls('chip', 'pb-nocap', k === os && 'primary')} href=${editor[k]} target="_blank" rel="noopener">⬇ ${esc(editor.name || 'Editor')} for ${lbl}</a>`)}
      <span class="muted">from ${esc(editor.by || 'the chip maker')}</span>
    </div>`,
    'pedalboard-hold': () => html`<div class="fcb-flash">
      ${held ? html`<button class="chip pb-nocap" onClick=${() => hold(false)}>↩ Take it back</button>
        <span class="flash-ok">✓ Released — golem ignores the pedalboard until you take it back.</span>`
      : html`<button class="primary" onClick=${() => hold(true)}>Release the pedalboard</button>`}
    </div>`,
    'pedalboard-copy': () => html`<div class="fcb-flash">
      <button class="primary" disabled=${copied && copied.busy} onClick=${copy}>${copied && copied.busy ? '⏳ Building…' : '⧉ Copy the setup'}</button>
      ${copied && copied.ok ? html`<span class="flash-ok">✓ Copied — ${copied.lines} lines, ${copied.used} / ${copied.budget} bytes in the chip.</span>` : ''}
      ${copied && copied.ok === false ? html`<span class="flash-ko">✗ The browser refused to copy — select the text below and copy it yourself.</span>` : ''}
      ${copied && copied.error ? html`<span class="flash-ko">✗ ${esc(copied.error)}</span>` : ''}
      ${copied && copied.ok === false && copied.text ? html`<textarea class="pb-setup-text" readonly value=${copied.text}
        onFocus=${e => e.target.select()} />` : ''}
    </div>`,
    'pedalboard-flashed': () => html`<div class="fcb-flash">
      <button class="primary" disabled=${flashed && flashed.ok} onClick=${declare}>✓ I sent it from Control Center</button>
      ${flashed && flashed.ok ? html`<span class="flash-ok">✓ Recorded — golem took the pedalboard back.</span>` : ''}
      ${flashed && flashed.error ? html`<span class="flash-ko">✗ ${esc(flashed.error)}</span>` : ''}
    </div>`,
  };
  // Windows (2026-10-03) : GoleM envoie lui-même (mode « wire ») ; l'éditeur du fabricant reste un
  // secours d'UN geste, si l'envoi direct n'aboutit pas avec ce pilote MIDI.
  // macOS (2026-10-04, M5) : l'inverse — l'éditeur d'abord (le bridge envoie déjà par CoreMIDI, mais
  // personne ne l'a joué sur un Mac), l'envoi direct à UN geste pour que la recette puisse l'essayer.
  const [useEditor, setUseEditor] = useState(mode === 'editor');
  const install = useEditor && device.install_desktop ? device.install_desktop : device.install;
  const canSwitch = (os === 'windows' || os === 'macos') && device.install_desktop;
  return html`<div class="pb-sheet">
    <section class="card-panel pb-sheet-head">
      <button class="chip" onClick=${onBack}>← Pedalboard</button>
      <b>Set up — ${esc(device.name)}</b>
      <span class="muted warn">⚠ Loading OVERWRITES the pedalboard memory</span>
      ${canSwitch ? html`<button class="chip pb-nocap" onClick=${() => setUseEditor(!useEditor)}>
        ${useEditor ? '⚡ Send it from golem instead' : `Use ${esc((device.editor || {}).name || 'the maker’s editor')} instead`}</button>` : ''}
    </section>
    <section class="card-panel fcb-intro">
      ${/* onDone : sans lui, le « Done » de la dernière étape ne faisait RIEN (2026-10-03) */''}
      <${InstallSteps} install=${install} name=${device.name} actions=${actions} onDone=${onBack}
        doneLabel="Done → back to the pedalboard" />
    </section>
  </div>`;
}

function BoardPanel({ rig, view, setView }) {
  const { data, err, reload } = useAsync(() => fetch('/api/pedalboard').then(r => r.json()), []);
  const [busy, setBusy] = useState('');
  const [menu, setMenu] = useState(false);

  if (!data || !data.active) return html`<${LoadGuard} err=${err} reload=${reload} label="Reading the pedalboard…" />`;
  const { active, device, contract, devices, unmet_gestures: unmet } = data;

  const detect = async () => {
    setBusy('detect');
    await post('/api/pedalboard/detect').catch(() => null);
    setBusy(''); reload();
  };
  const select = async (id) => {
    setMenu(false);
    if (id === active.id) return;
    await post('/api/pedalboard/select', { id }).catch(() => null);
    reload();
  };

  if (view === 'setup') return html`<${SetupSheet} device=${device} mode=${data.load_mode} os=${data.os} held=${data.ports_held}
                                      onBack=${() => { setView('mirror'); reload(); }} />`;
  if (view === 'learn') return html`<${LearnPanel} onDone=${() => { setView('mirror'); reload(); }}
                                      onBack=${() => setView('mirror')} />`;

  const heard = ago((rig && rig.state || {}).foot_heard);
  return html`<div class="pb-mirror-wrap">
    <section class="card-panel pb-bar-head">
      <b>${esc(active.name)}</b>
      <${SourceBadge} active=${active} />
      ${active.firmware ? html`<span class="muted">fw ${esc(active.firmware)}${
        active.serial ? ` · s/n ${esc(active.serial)}` : ''}</span>` : ''}
      <span class=${cls('pb-heard', heard && 'yes')}
        title="When the rack last received a message FROM the pedalboard. Not the same question as which chip is plugged in.">
        ${heard ? '✓ heard ' + heard : '· never heard'}
      </span>
      <${ProvenanceBadge} provenance=${device.provenance} />
      <span class="pb-spacer" />
      <button class="chip edit-only" disabled=${!!busy} onClick=${detect}>${busy === 'detect' ? '⏳' : '⟳'} Detect</button>
      <button class="chip edit-only" onClick=${() => setView('setup')}>Set up</button>
      <button class="chip edit-only" onClick=${() => setMenu(m => !m)}>⋯</button>
      ${menu ? html`<div class="pb-menu">
        <span class="muted">Pedalboard</span>
        ${(devices || []).map(d => html`<button class=${cls(d.id === active.id && 'on')}
          onClick=${() => select(d.id)}>${d.name}</button>`)}
        <hr />
        <button onClick=${() => { setMenu(false); setView('learn'); }}>Teach a new pedalboard…</button>
      </div>` : ''}
    </section>
    <${Mirror} rig=${rig} contract=${contract} device=${device} unmet=${unmet} />
  </div>`;
}

// ── onglet CALIBRATION (docs/calibration.md, 2026-07-26) — ex-« Pedalboard » ──
// Trois royaumes : Controllers (stepper MIDI-learn -> profils), Pedals (hub Whammy + vérif de
// mapping + wizard nouvelle pédale), Pedalboard (l'existant intact : rôles d'expression + flash).
const SUB_TABS = [
  ['controllers', 'Controllers'],
  ['pedals', 'Pedals'],
  ['board', 'Pedalboard'],
  ['drums', 'Drums'],       // docs/calibration.md addendum 2026-09-23 : le module de batterie est un fait du rack
];

export function PedalboardPage({ rig, sub, bare }) {
  const [tab, setTab] = useState(SUB_TABS.some(([id]) => id === sub) ? sub : 'controllers');
  // deep-link VIVANT : #/system/gear/drums depuis un autre sous-onglet doit basculer (Soundcard ▸ Calibrate)
  useEffect(() => { if (sub && SUB_TABS.some(([id]) => id === sub)) setTab(sub); }, [sub]);
  // Plus de troisième niveau de navigation. Le segmented à 3 positions posait trois TÂCHES au
  // rang de trois OBJETS — et `.tb-seg` sert de filtre partout ailleurs dans l'app : le widget
  // disait « je filtre » et il naviguait. Installation et apprentissage sont désormais des
  // prises plein cadre, atteintes depuis l'en-tête, avec leur propre retour.
  const [boardView, setBoardView] = useState('mirror');      // mirror | setup | learn
  // `bare` : Gear porte la barre (Soundcard · Controllers · Pedals · Pedalboard · Drums — mockups/settings-nav.html) ;
  // la page suit son `sub` et revient au miroir quand on change de sous-onglet
  useEffect(() => { setBoardView('mirror'); }, [sub]);
  return html`<div class="pedalboard">
    ${bare ? '' : html`<div class="sys-tabs sub-tabs">
      ${SUB_TABS.map(([id, label]) => html`<button class=${cls('sys-tab', tab === id && 'on')}
        onClick=${() => { setTab(id); setBoardView('mirror'); }}>${label}</button>`)}
    </div>`}
    ${tab === 'controllers' ? html`<${ControllersPanel} />`
      // La page Pedals porte désormais SA propre colonne de pédales (+ New pedal, Verify) : les
      // deux chips de PedalCalib qui flottaient au-dessus n'ont plus lieu d'être — une action qui
      // crée une pédale appartient à la liste des pédales.
      : tab === 'pedals' ? html`<${PedalsPage} rig=${rig} />`
      : tab === 'drums' ? html`<${DrumsPanel} />`
      : html`<${BoardPanel} rig=${rig} view=${boardView} setView=${setBoardView} />`}
  </div>`;
}

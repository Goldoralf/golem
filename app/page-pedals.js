// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Calibration ▸ Pedals — LES PÉDALES MIDI PHYSIQUES du rig.
//
// Refonte 2026-07-28  : deux panneaux, maître-détail. À gauche une COLONNE de cartes, une
// par pédale branchée ; à droite, large, les paramètres de celle qu'on a sélectionnée. Le rig
// n'a qu'une Whammy DT aujourd'hui, mais une page qui ne sait afficher qu'un seul objet doit
// être réécrite le jour où il y en a deux — celle-ci part avec la liste.
//
// Une « pédale » = un mapping de mappings/*.json qui porte des modes (GET /api/mappings). Le
// layout du FCB1010 vit dans le même dossier mais n'est pas une pédale d'effet : il n'a pas de
// modes, il ne remonte donc pas ici.
//
// Panneau de droite : le sélecteur des fonctions de la face avant + la grille de modes, un Test ▶
// par mode. L'envoi passe par /api/whammy pour la Whammy (ce chemin tient AUSSI l'état du rig,
// le badge whammy de la page Live en dépend) et par /api/calibrate/midi pour toute autre pédale.
import { html, useState, useEffect, useAsync, post, cls, esc, LoadGuard } from './lib.js';
import { VerifyMapping, NewPedalWizard } from './calibration.js';

// Fonctions de la face avant de la Whammy DT. Drop Tune regroupe les 2 familles data drop/raise
// (= le switch de direction du hardware).
const WHAMMY_FUNCTIONS = [
  { id: 'whammy',   label: 'Whammy',    fams: ['whammy'],       treadle: true },
  { id: 'harmony',  label: 'Harmony',   fams: ['harmony'],      treadle: true },
  { id: 'droptune', label: 'Drop Tune', fams: ['drop', 'raise'], treadle: false },
];
const DIRS = [{ id: 'drop', label: '↓ Drop' }, { id: 'raise', label: '↑ Raise' }];

// Valeur "grosse" au centre d'une tuile Drop Tune (accordage fixe -> les demi-tons priment).
function bigVal(m) {
  const sign = m.family === 'raise' ? '+' : '−';
  if (/Octave/i.test(m.name)) return sign + '1 Oct' + (/dry/i.test(m.name) ? '+' : '');
  const mt = m.name.match(/(\d+)\s*semitone/i);
  return mt ? sign + mt[1] + ' st' : m.name;
}

// ── page = colonne de pédales + panneau de paramètres ────────────────────────────────────────
export function PedalsPage({ rig }) {
  const [tick, setTick] = useState(0);
  const { data, err, reload } = useAsync(() => fetch('/api/mappings').then(r => r.json()), [tick]);
  const [sel, setSel] = useState(null);
  const [justAdded, setJustAdded] = useState(null);  // pédale à peine installée -> on enchaîne
  const [add, setAdd] = useState(false);      // catalogue des modèles connus
  const [wizard, setWizard] = useState(false); // dernier recours : pédale inconnue
  const pedals = (data || {}).pedals || [];
  const cur = pedals.find(p => p.id === sel) || pedals[0] || null;

  if (!data) return html`<${LoadGuard} err=${err} reload=${reload} label="Loading pedals…" />`;

  return html`<div class="pdl">
    <aside class="pdl-col">
      <div class="pdl-col-h">Pedals<em>${pedals.length}</em></div>
      ${pedals.map(p => html`<button class=${cls('pdl-card', cur && p.id === cur.id && 'on')}
        onClick=${() => setSel(p.id)}>
        <b>${esc(p.name)}</b>
        <span class="pdl-dev">${esc(p.device || '—')}</span>
        <span class="pdl-meta">${p.modes} modes${p.treadle_cc ? ' · treadle CC' + p.treadle_cc : ''}</span>
        <span class="pdl-meta">Ch ${p.channel}${p.midi_out ? ' · ' + esc(p.midi_out) : ''}</span>
        ${p.confidence ? html`<span class=${cls('pdl-badge', p.confidence)}>${p.confidence === 'verified' ? 'verified on the hardware'
          : p.confidence === 'reported' ? 'reported — not verified here' : 'unconfirmed'}</span>` : ''}
      </button>`)}
      ${!pedals.length ? html`<p class="muted pdl-empty">No MIDI pedal yet. Add one below — golem
        sends the program changes, you write down what the pedal displays.</p>` : ''}
      <button class="chip pdl-add" onClick=${() => setAdd(true)}
        title="install a pedal golem already knows, or map an unknown one">+ Add pedal</button>
    </aside>

    <section class="pdl-main">
      ${cur ? html`<${PedalPanel} key=${cur.id} head=${cur} rig=${rig} setup=${justAdded === cur.id ? 'install' : null}
        onRemoved=${() => { setSel(null); setTick(t => t + 1); }} />`
            : html`<div class="empty">Pick a pedal on the left.</div>`}
    </section>

    ${add ? html`<${AddPedal} onClose=${() => setAdd(false)}
      onDone=${id => { setAdd(false); setTick(t => t + 1); if (id) { setSel(id); setJustAdded(id); } }}
      onWizard=${() => { setAdd(false); setWizard(true); }} />` : ''}
    ${wizard ? html`<${NewPedalWizard} onClose=${() => { setWizard(false); setTick(t => t + 1); }} />` : ''}
  </div>`;
}


// ── panneau de droite : les paramètres de LA pédale sélectionnée ─────────────────────────────
function PedalPanel({ head, rig, onRemoved, setup: setup0 }) {
  const [armRm, setArmRm] = useState(false);
  const [menu, setMenu] = useState(false);
  // `setup` : null = la pédale, telle qu'on la joue · 'install' = la procédure · 'verify' = les
  // contrôles. Une pédale qu'on vient d'installer entre par la procédure — c'est là qu'un
  // premier branchement se joue, pas dans une grille de 39 modes.
  const [setup, setSetup] = useState(setup0 || null);
  const { data: w, err, reload } = useAsync(() => fetch('/api/mapping/' + head.id).then(r => r.json()), [head.id]);
  const isWhammy = head.id === 'whammy-dt';
  // Fonctions de la face avant : celles de la Whammy si c'est elle, sinon les familles déclarées
  // par le mapping (le wizard pose « custom » quand la pédale n'a pas de familles nommées).
  const fns = isWhammy ? WHAMMY_FUNCTIONS
    : (head.families || []).map(f => ({ id: f.id, label: f.label, fams: [f.id], treadle: !!head.treadle_cc }));
  const [fnId, setFnId] = useState(null);
  const [dir, setDir] = useState('drop');
  const [sent, setSent] = useState(null);
  const [flash, setFlash] = useState('');
  const [verify, setVerify] = useState(false);

  if (!w || !w.id) return html`<${LoadGuard} err=${err} reload=${reload} label=${'Loading ' + head.name + '…'} />`;

  const allModes = w.modes || [];
  // ⚠ Une pédale IMPORTÉE n'a ni procédure ni contrôles (un MIDNAM est une TABLE, pas une
  // recette) : entrer en 'install' masquait la grille pour n'afficher… rien — panneau vide après
  // installation. On ne reste jamais dans une étape qui n'existe pas.
  const hasPhases = !!((w.install || {}).phases || []).length;
  const hasChecks = !!((w.verify || {}).checks || []).length;
  const stage = (setup === 'install' && !hasPhases) ? (hasChecks ? 'verify' : null)
              : (setup === 'verify' && !hasChecks) ? null : setup;
  const vh = ((w.provenance || {}).verified_here) || null;      // ce que CE rack a constaté
  const hasSetup = !!((w.install && (w.install.phases || []).length) || (w.verify && (w.verify.checks || []).length));
  // une pédale sans familles nommées (wizard) : une seule vue, tous ses modes
  const list = fns.length ? fns : [{ id: 'all', label: 'Modes', fams: null, treadle: !!head.treadle_cc }];
  const fn = list.find(f => f.id === fnId) || list[0];
  const fam = fn.id === 'droptune' ? dir : (fn.fams ? fn.fams[0] : null);
  const modes = fam ? allModes.filter(m => m.family === fam) : allModes;

  const send = async (m, active) => {
    setSent({ name: m.name, active });
    try {
      // La Whammy garde son chemin dédié : il tient l'état du rig (badge « ▲ whammy » de /live).
      // Toute autre pédale part par l'émission MIDI brute — même fil, sans état à maintenir.
      const r = isWhammy
        ? await post('/api/whammy', { mode: m.name, active })
        : await post('/api/calibrate/midi', { pc: active ? m.active_pc : m.bypass_pc, channel: w.channel || 1 });
      const pc = active ? m.active_pc : m.bypass_pc;
      setFlash((r && r.ok !== false ? '✓ ' : '✕ ') + (active ? 'PC' + pc : 'bypass PC' + pc) + ' · ' + m.name);
    } catch (e) { setFlash('✕ ' + m.name + ' (' + e.message + ')'); }
  };

  const Tile = m => {
    const live = sent && sent.name === m.name;
    let primary = esc(m.name), sub = '';
    if (fn.id === 'droptune') { primary = bigVal(m); sub = esc(m.name); }
    else if (fn.id === 'harmony') { primary = esc(m.name.replace(/^Harmony\s+/, '')); }
    return html`
      ${/* classes PRÉFIXÉES : « live » tout court est la classe de la PAGE Live
            (`min-height:100vh`) — posée sur une tuile, elle la faisait bondir à la hauteur du
            viewport au premier TEST. Un nom d'état générique dans une feuille de style globale
            finit toujours par percuter quelqu'un. */''}
      <div class=${cls('pd-tile', live && (sent.active ? 'pd-live' : 'pd-live-bypass'), m._confirm && 'confirm')}>
        <div class="pd-top">
          ${fn.treadle ? html`<span class="pd-glyph">↕</span>` : ''}
          <b class="pd-name">${primary}</b>
          ${m._confirm ? html`<span class="pd-q" title="Label to confirm in Test">?</span>` : ''}
          <span class="pd-pc">PC ${m.active_pc}</span>
        </div>
        ${sub ? html`<div class="pd-sub">${sub}</div>` : ''}
        <div class="pd-bot">
          <button class="pd-test" onClick=${() => send(m, true)}>TEST ▶</button>
          ${m.bypass_pc != null
            ? html`<button class="pd-byp" title=${'Bypass · PC' + m.bypass_pc} onClick=${() => send(m, false)}>⊘ ${m.bypass_pc}</button>`
            : ''}
        </div>
      </div>`;
  };

  return html`
    <div class="pedals">
      ${/* 3) le rôle du DIN OUT vit dans une AUTRE page (Soundcard) : s'il ne pointe pas vers
             cette pédale, aucun PC ne sort et la grille de modes ment. On le dit ICI. */''}
      ${(() => {
        const mo = ((rig && rig.state && rig.state.inputmap) || {}).midi_out || {};
        if (!w.modes || !w.modes.length) return '';
        if (mo.role === w.id) return '';
        return html`<div class="pdl-warn">
          ⚠ The card's MIDI OUT is set to <b>${esc(mo.label || mo.role || 'none')}</b> — nothing
          sent from here will reach ${esc(w.name)}.
          <a href="#/system/gear/sound">Set it on Soundcard →</a></div>`;
      })()}
      <div class="pdl-head">
        <h2>${esc(w.name || head.name)}</h2>
        <span class="pd-chip">${esc(w.midi_out || '—')} · Ch ${w.channel || 1}${w.treadle_cc ? ' · treadle CC' + w.treadle_cc + ' ●' : ''}</span>
        <span class="grow"></span>
        ${/* Un ÉTAT, une ACTION, et le reste dans le ⋯ (retour 2026-07-29 : « on comprend pas
             tout ce qu'ils font »). Trois boutons de même poids racontaient trois choses de
             fréquences très différentes : une mise en route se fait UNE fois, un audit de table
             presque jamais. Le badge dit où on en est, le bouton propose la seule chose qu'on
             ait envie de faire, le menu garde le rare. */''}
        ${vh ? html`<span class=${cls('pdl-vstate', vh.ok ? 'ok' : 'ko')}
            title=${(vh.scope === 'full' ? 'every mode checked' : 'canonical checks') + ' · ' + (vh.at || '').slice(0, 10)}>
            ${vh.ok ? '✓ works here' : '⚠ ' + (vh.failed || []).length + ' failed here'}</span>`
          : html`<span class="pdl-vstate" title="nothing has been checked on THIS rack yet">not checked here</span>`}
        ${!stage && hasSetup ? html`<button class="chip primary"
            onClick=${() => setSetup(vh ? 'verify' : 'install')}>
            ${vh ? '✓ Check again' : '⚙ Set it up'}</button>`
          : (!stage && !vh && (w.modes || []).length) ? html`<button class="chip primary"
              title="this table comes from a third-party file — nothing has been checked on this rack"
              onClick=${() => setVerify(true)}>✓ Check the modes</button>` : ''}
        <div class="prow-menu" onClick=${e => e.stopPropagation()}>
          <button class="mini" onClick=${() => { setMenu(!menu); setArmRm(false); }}>⋯</button>
          ${menu ? html`<div class="save-pop">
            ${(w.install && (w.install.phases || []).length) ? html`<button class="row-btn"
              onClick=${() => { setMenu(null); setSetup('install'); }}>⚙ Setup steps<small>what to set ON the pedal</small></button>` : ''}
            ${(w.verify && (w.verify.checks || []).length) ? html`<button class="row-btn"
              onClick=${() => { setMenu(null); setSetup('verify'); }}>✓ Quick check<small>${(w.verify.checks || []).length} canonical controls</small></button>` : ''}
            ${(w.modes || []).length ? html`<button class="row-btn"
              onClick=${() => { setMenu(null); setVerify(true); }}>↻ Check every mode<small>audit the ${(w.modes || []).length} programs, one by one</small></button>` : ''}
            <button class=${cls('row-btn danger', armRm && 'armed')}
              onClick=${() => { if (!armRm) { setArmRm(true); setTimeout(() => setArmRm(false), 2600); return; }
                setMenu(null); fetch('/api/pedals/' + head.id, { method: 'DELETE' }).then(() => onRemoved && onRemoved()); }}>
              ${armRm ? '⏏ Sure ? tap again' : '⏏ Uninstall'}<small>the catalog keeps it — one tap to reinstall</small></button>
          </div>` : ''}
        </div>
      </div>

      ${stage === 'install'
        ? html`<${InstallSteps} install=${w.install} name=${w.name}
            onDone=${() => setSetup((w.verify && (w.verify.checks || []).length) ? 'verify' : null)} />`
        : stage === 'verify'
        ? html`<${VerifyChecks} pedal=${w} onDone=${() => { setSetup(null); reload(); }} />` : ''}

      <div class="pd-strip" style=${stage ? 'display:none' : ''}>
        <div class="pd-fam">
          ${list.map(f => html`<button class=${cls('pd-seg', f.id === fn.id && 'on')}
            onClick=${() => setFnId(f.id)}>${f.label}</button>`)}
        </div>
        ${fn.id === 'droptune'
          ? html`<div class="pd-fam sub">${DIRS.map(d => html`<button class=${cls('pd-seg', d.id === dir && 'on')} onClick=${() => setDir(d.id)}>${d.label}</button>`)}</div>`
          : ''}
        <div class="pd-strip-end">
          ${flash ? html`<span class=${cls('pd-flash', flash[0] === '✓' && 'ok', flash[0] === '✕' && 'ko')}>${flash}</span>` : ''}
        </div>
      </div>

      <div class="pd-grid" style=${stage ? 'display:none' : ''}>${modes.map(Tile)}</div>
      ${!modes.length ? html`<p class="muted">This mapping has no mode in that group yet.</p>` : ''}
      ${verify ? html`<${VerifyMapping} pedal=${w} onClose=${() => setVerify(false)}
        onDone=${() => { setVerify(false); reload(); }} />` : ''}
    </div>`;
}


// ── « + Add pedal » : d'abord ce que GoleM CONNAÎT ───────────────────────────────────────────
// La leçon du premier test réel (2026-07-29) : après avoir supprimé la Whammy, le seul chemin
// était le wizard manuel — 39 modes à taper, et il ne sait même pas capturer les PC de bypass,
// donc le fichier obtenu aurait été MOINS BON que celui qu'on venait d'effacer. Une pédale
// connue s'installe, elle ne se recalibre pas. Le wizard redevient ce qu'il doit être : le
// dernier recours, pour un modèle que personne n'a encore décrit.
function AddPedal({ onClose, onDone, onWizard }) {
  const { data } = useAsync(() => fetch('/api/pedals/catalog').then(r => r.json()), []);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState('');
  const list = (data || {}).pedals || [];
  const install = async p => {
    setBusy(p.id); setErr('');
    const r = await post('/api/pedals/install', { id: p.id }).catch(e => ({ error: String(e) }));
    setBusy(null);
    if (r && r.error) { setErr(r.error); return; }
    onDone(p.id);
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card mode-add">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Add a pedal</h2>
      <p class="sub">golem already knows these — installing copies their program table, no
        calibration to redo. The badge tells you how much to trust it: <b>verified</b> was checked
        on the hardware, <b>unconfirmed</b> comes from a third-party file and deserves a run
        through « check every mode » before a gig.</p>
      <div class="pdl-cat">
        ${list.map(p => html`<button class=${cls('pdl-cat-row', p.installed && 'off')}
          disabled=${p.installed || busy === p.id} onClick=${() => install(p)}>
          <b>${esc(p.name)}</b>
          <span>${esc(p.brand || '')}${p.firmware ? ' · ' + esc(p.firmware) : ''} · ${p.modes} modes${p.steps ? ' · ' + p.steps + ' install steps' : ''}</span>
          <em class=${cls('pdl-badge', p.confidence)}>${p.installed ? 'already installed' : (p.confidence || '')}</em>
        </button>`)}
        ${data && !list.length ? html`<p class="muted">The catalog is empty.</p>` : ''}
      </div>
      ${err ? html`<p class="mode-err">✗ ${esc(err)}</p>` : ''}
      <p class="mode-add-hint">Your pedal isn't listed? Map it by hand — golem sends the program
        changes, you write down what the pedal displays. Slower, and it can't capture bypass
        programs: prefer contributing a descriptor afterwards.</p>
      <div class="mode-add-acts">
        <button class="chip" onClick=${onClose}>Cancel</button>
        <button class="chip" onClick=${onWizard}>Map an unknown pedal…</button>
      </div>
    </div>
  </div>`;
}


// ── la PROCÉDURE : ce qu'il faut régler SUR la pédale ────────────────────────────────────────
// Tier `install` du descripteur (docs/pedal-registry.md §2). Aucune donnée ne remplace un geste
// physique — canal MIDI, réception à activer, merge à couper — et jusqu'ici ces étapes étaient
// écrites dans le fichier sans qu'aucun écran ne les montre. C'est ce qui séparait « la table
// est juste » de « ça marche chez toi ».
// Exporté : le stepper du FCB1010 (page-pedalboard) s'en sert aussi — un seul dérouleur.
export function InstallSteps({ install, name, onDone, actions, doneLabel }) {
  const [i, setI] = useState(0);
  const phases = (install || {}).phases || [];
  const flat = phases.flatMap((ph, pi) => (ph.steps || []).map(st => ({ ...st, phase: ph.name, pi })));
  if (!flat.length) return '';
  const st = flat[Math.min(i, flat.length - 1)];
  const act = (actions || {})[st.action];
  const last = i >= flat.length - 1;
  return html`<section class="card-panel fcb-wiz pdl-setup">
    ${(install.needs || []).length ? html`<p class="muted fcb-hint">🔌 ${install.needs.join(' · ')}</p>` : ''}
    <div class="fcb-wiz-head">
      <span class="fcb-wiz-phase">${esc(st.phase || (name || ''))}</span>
      <span class="fcb-wiz-count">${i + 1} / ${flat.length}</span>
    </div>
    <div class="fcb-wiz-dots">
      ${flat.map((x, j) => html`<span class=${cls('fcb-dot', j === i && 'on', j < i && 'done', 'p' + x.pi)}
        onClick=${() => setI(j)} />`)}
    </div>
    <div class="fcb-wiz-body">
      <h3>${esc(st.title)} ${st.badge ? html`<em class="fcb-badge">${esc(st.badge)}</em>` : ''}</h3>
      <p>${esc(st.do)}</p>
      ${st.hint ? html`<p class="muted fcb-hint">💡 ${esc(st.hint)}</p>` : ''}
      ${act ? act(st) : ''}
    </div>
    <footer class="fcb-wiz-nav">
      <button class="chip" disabled=${!i} onClick=${() => setI(i - 1)}>← Back</button>
      ${st.badge ? html`<button class="chip" onClick=${() => setI(i + 1)}>Skip</button>` : ''}
      <button class="chip primary" onClick=${() => last ? (onDone && onDone()) : setI(i + 1)}>
        ${last ? (onDone ? (doneLabel || 'Done → check it') : 'Done') : 'Next →'}</button>
    </footer>
  </section>`;
}


// ── la VÉRIFICATION : est-ce que ça marche VRAIMENT sur CE rack ? ────────────────────────────
// Tier `verify`. Le rack envoie, l'utilisateur écoute et répond. Le verdict est écrit dans le
// fichier installé : « verified » au catalogue veut dire « vérifié par quelqu'un, quelque part » ;
// ici on note ce que CE rack a constaté — et un échec dégrade la confiance au lieu de la taire.
function VerifyChecks({ pedal, onDone }) {
  const checks = (pedal.verify || {}).checks || [];
  const [i, setI] = useState(0);
  const [res, setRes] = useState({});
  const [saved, setSaved] = useState(null);
  const cur = checks[i];
  const send = c => post('/api/calibrate/midi', { ...(c.send || {}), channel: pedal.channel || 1 }).catch(() => {});
  useEffect(() => { if (cur) send(cur); }, [i]);
  const answer = async ok => {
    const r = { ...res, [cur.label]: ok };
    setRes(r);
    if (i < checks.length - 1) { setI(i + 1); return; }
    const failed = Object.keys(r).filter(k => !r[k]);
    // `checked` : combien de contrôles ont été JOUÉS — sans lui le verdict disait « 0 vérifié » (2026-10-03)
    const v = await post('/api/pedals/' + pedal.id + '/verify', { failed, checked: Object.keys(r).length, scope: 'quick' })
      .catch(e => ({ error: String(e) }));
    setSaved(v && v.error ? { error: v.error } : { failed });
  };
  if (saved) {
    const ko = (saved.failed || []).length;
    return html`<section class="card-panel pdl-setup">
      <h3>${ko ? '⚠ ' + ko + ' check' + (ko > 1 ? 's' : '') + ' failed' : '✓ Verified on this rack'}</h3>
      <p class="muted">${ko
        ? 'Written to the mapping — this pedal no longer claims to be verified here. Check the wiring and the MIDI channel, then run it again.'
        : 'Written to the mapping, with today\'s date. « Verified » in the catalog means someone, somewhere ; this means YOUR rack.'}</p>
      ${ko ? html`<ul class="cal-review">${(saved.failed || []).map(f => html`<li>✗ ${esc(f)}</li>`)}</ul>` : ''}
      <div class="fcb-wiz-nav"><span class="grow"></span>
        <button class="chip" onClick=${() => { setSaved(null); setRes({}); setI(0); }}>↻ Run again</button>
        <button class="chip primary" onClick=${onDone}>Done</button></div>
    </section>`;
  }
  if (!cur) return '';
  return html`<section class="card-panel pdl-setup">
    <div class="fcb-wiz-head">
      <span class="fcb-wiz-phase">Check it</span>
      <span class="fcb-wiz-count">${i + 1} / ${checks.length}</span>
    </div>
    <div class="fcb-wiz-body">
      <h3>${esc(cur.label)}</h3>
      <p>${esc(cur.expect)}</p>
      <p class="muted fcb-hint">golem just sent it. Play something — do you hear it?</p>
      <button class="chip" onClick=${() => send(cur)}>↻ Send again</button>
    </div>
    <footer class="fcb-wiz-nav">
      <span class="grow"></span>
      <button class="chip" onClick=${() => answer(false)}>✗ No</button>
      <button class="chip primary" onClick=${() => answer(true)}>✓ Yes</button>
    </footer>
  </section>`;
}

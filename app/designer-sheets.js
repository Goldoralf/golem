// SPDX-License-Identifier: GPL-3.0-or-later
// Bottom sheets du Designer : potards (Knob/ParamSheet), assign, réglages preset (extraits, P3).
import { html, useState, useEffect, useRef, useAsync, cls, esc, LIVE_PALETTE, GENRE_FAMILIES } from './lib.js';
import { ANIM_STYLES, blkColor, ICON, animClass, animPackOf, ensurePackCss, refKey } from './designer-model.js';
import { PCell, PDial, PToggle, PFader, PFaderBank, fmtVal, EqCurve, DynMeter } from './designer-widgets.js';
import { BlockPresetsList } from './designer-block-presets.js';   // l'onglet « Presets » (mockups/block-presets-list.html)
import { StandardSheet } from './designer-standard.js';
import { BackingDrawer } from './designer-backing.js';
import { ClickSongCols, PerSongNote, SongLayer, sheetBlocks } from './designer-song.js';   // la chanson chargée (docs/designer-song.md)     // le tiroir Backing Track (docs/song-backing.md)
import { PadsDrawer } from './pads-drawer.js';   // le tiroir du bloc Pads v2 (mockups/pads-drawer-v2.html)
import { Icon } from './icons.js';
import { orderModels, describe as capDescribe } from './capture-gain.js';
import { useGestures, GestureLegend } from './gestures.js';   // la légende des gestes au pied, en phrases
import { ParametricControls } from './capture-parametric.js';
import { CaptureModuleControls } from './capture-module.js';

// ── potard circulaire (drag vertical) ── overridden = réglé pour la scène active (liseré + valeur de base)
export function Knob({ label, value, min, max, unit, overridden, base, onChange }) {
  const [drag, setDrag] = useState(false);
  const st = useRef({ y: 0, v: 0 });
  const v = value == null ? min : value;
  const norm = Math.max(0, Math.min(1, (v - min) / (max - min || 1)));
  useEffect(() => {
    if (!drag) return;
    const mv = e => { const dy = st.current.y - (e.clientY ?? 0); const nv = st.current.v + dy / 140 * (max - min);
      onChange(Math.max(min, Math.min(max, Math.round(nv * 100) / 100))); };
    const up = () => setDrag(false);
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    return () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); };
  }, [drag]);
  const ang = -135 + norm * 270;
  const disp = Math.abs(v) >= 100 ? Math.round(v) : (Math.round(v * 10) / 10);
  return html`<div class=${cls('knob', overridden && 'ovr')} onDblClick=${() => onChange(null)}
      title=${overridden ? 'scene override — double-click = back to base' : ''}>
    <div class=${cls('knob-dial', drag && 'act')} onPointerDown=${e => { st.current = { y: e.clientY, v }; setDrag(true); }}
      style=${`background:conic-gradient(from -135deg, var(--accent) ${norm * 270}deg, var(--line) ${norm * 270}deg 270deg, transparent 270deg)`}>
      <span class="knob-pin" style=${`transform:rotate(${ang}deg)`}></span>
    </div>
    <div class="knob-val">${disp}${unit ? html`<i>${unit}</i>` : ''}</div>
    <div class="knob-lbl">${label}</div>
    ${overridden ? html`<div class="knob-base" title="base value (inherited by other scenes)">base ${base}${unit ? ' ' + unit : ''}</div>` : ''}
  </div>`;
}

// ── captures multi-modèles = GAIN SWEEP (packs « Drive 7 Tone 7 Level 9 », g1..g9…) ──
// Parse les réglages depuis le nom, trie du clean vers le chaud, alimente le Capture dial.
const CAP_KEYS = [['drive', 'Drive'], ['gain', 'Gain'], ['g', 'Gain'], ['tone', 'Tone'],
                  ['level', 'Level'], ['vol', 'Level'], ['bass', 'Bass'], ['mid', 'Mid'],
                  ['treble', 'Treble'], ['presence', 'Presence'], ['t', 'Tone'], ['b', 'Bass']];
function capParse(name) {
  const out = {};
  const re = /\b(drive|gain|tone|level|volume|vol|bass|mid|treble|presence|[gtb])\s*[-_ ]?(\d+(?:[.,]\d+)?)/gi;
  let m;
  while ((m = re.exec(String(name || '')))) {
    const k = m[1].toLowerCase();
    if (!(k in out)) out[k] = parseFloat(m[2].replace(',', '.'));
  }
  return out;
}
function capOrder(models) {
  // ORDRE = spec capture-gain v0.1 (golem.fm 2026-09-14, capture-gain.js, table de cas partagée) :
  // off < gains croissants < max, chaud après le même gain, canal 1 < aucun < 2, illisibles après,
  // doublons 44.1k retirés. Elle lit « Pre 60 », « 70 dB Hard », « Gain -10 », « G70 »… — là où
  // l'ancien tri (drive|gain|g + nombre) rendait 5 packs sur 15 dans l'ordre (mesuré).
  const arr = orderModels(models).map(r => ({ m: r.m, kv: capParse(r.m.name), g: r.g }));
  // une SEULE clé varie sur tout le pack ? -> le dial prend son nom (« Drive ») : vraie pédale
  const varying = CAP_KEYS.filter(([k]) => {
    const vals = arr.filter(x => x.kv[k] != null).map(x => x.kv[k]);
    return vals.length === arr.length && new Set(vals).size > 1;
  });
  const label = varying.length === 1 ? varying[0][1] : null;
  return { arr, label };
}
function capSig(kv, name, g) {
  const parts = [];
  const seen = new Set();
  for (const [k, lb] of CAP_KEYS) {
    if (kv[k] != null && !seen.has(lb)) { parts.push(lb + ' ' + kv[k]); seen.add(lb); }
    if (parts.length >= 4) break;
  }
  if (parts.length) return parts.join(' · ');
  const d = capDescribe(g);                       // lecture outboard (« gain 40 · ch 1 · mic »)
  return d || String(name || '').slice(0, 40);
}

// ── panneau de réglages (bottom sheet) ──
// le bouton ⏻ d'un tiroir (2026-10-14) : l'état que le moteur joue ; avec plusieurs scènes, il dit laquelle
export const PowerBtn = ({ on, onPower, sceneId }) => html`<button class=${cls('ph-power', !on && 'off')} onClick=${() => onPower(!on)}
  title=${sceneId ? (on ? 'on in scene ' + sceneId + ' — tap to switch it off in this scene' : 'off in scene ' + sceneId + ' — tap to switch it on in this scene')
    : (on ? 'block is active — tap to bypass' : 'block is bypassed — tap to engage')}>⏻ ${on ? 'Active' : (sceneId ? 'Off' : 'Bypassed')}${sceneId ? html` <i class="ph-scope">in ${sceneId}</i>` : ''}</button>`;

export function ParamSheet({ block, def, tones, ovr, sceneId, sceneOff, fxIcon, exp2, pedals, svc, bpm, laneInst, tab, onTab, assign, onExp, expVol, onExpVol, onParam, onBypass, onScene, onModel, onApplyAll, onLoadPreset, onMove, onRemove, onPickRef, onClose, vstOpen, onRename, onCaptureFoot, powerOn, onPower, multiScene }) {
  // les boutons qu'un tiroir de service remonte dans la rangée ⏻ (le Standard : Change… / Audition, 2026-10-17)
  const [headX, setHeadX] = useState(null);
  // la COUCHE éditée par le tiroir Sample (docs/designer-song.md §4) : la liste du preset, ou celle de la chanson chargée
  const [songLayer, setSongLayer] = useState('preset');
  // capture d'un VST (2026-10-05) : le bloc garde son moteur, la fiche dit d'où il vient et se renomme
  const vo = block.origin && block.origin.kind === 'vst-capture' ? block.origin : null;
  const voPlug = vo ? String(vo.plugin || '').replace(/^(VST3?i?|CLAPi?):\s*/, '').replace(/\s*\(.*\)\s*$/, '') : '';
  // Whammy DT : les modes viennent du mapping (source de vérité), pas de l'enum figé d'effects.json.
  const isWhammy = block.type === 'whammy-dt';
  const { data: wmap } = useAsync(() => isWhammy ? fetch('/api/mapping/whammy-dt').then(r => r.json()) : Promise.resolve(null), [isWhammy]);
  const wModes = (wmap && wmap.modes) || [];
  // pédale MIDI générique (bloc midi-pedal) : les réglages viennent de SON descripteur (block.ref)
  const isHwPedal = block.type === 'midi-pedal';
  const { data: hwmap } = useAsync(() => isHwPedal && block.ref
    ? fetch('/api/mapping/' + encodeURIComponent(block.ref)).then(r => r.json()) : Promise.resolve(null), [isHwPedal, block.ref]);
  const hwModes = (hwmap && hwmap.modes) || [];
  const hwTreadle = hwmap && ((hwmap.treadle || {}).cc || hwmap.treadle_cc);
  const isAmpCab = ['amp', 'amp-nam', 'cab'].includes(block.type);
  const hasCapture = isAmpCab || ['pedal-nam', 'preamp-nam', 'comp-nam', 'ir-fx'].includes(block.type);   // pedal-nam / outboard ont AUSSI une capture (le nom réel de l'appareil)
  const tone = hasCapture && block.ref ? (tones || []).find(t => String(t.id) === refKey(block.ref)) : null;
  const captureControls = tone?.capture_module?.controls;
  const params0 = captureControls ? [] : (def.params || []);
  // Vital (lane Keys) : la liste des presets .vital vient de la bibliothèque (library/synth/vital)
  const isVital = block.type === 'vital';
  // écho LIVE des potards AKAI (2026-07-23) : tant que la feuille d'un bloc à knobs est
  // ouverte, on poll /api/knobs/live (golem_knobs publie les CC frais, expirés à 2 s) et les
  // dials SUIVENT le potard physique — affichage seul, rien n'est écrit au preset.
  const hasKnobs = !!(def.knobs && def.knobs.targets);
  const [liveKnobs, setLiveKnobs] = useState({});
  useEffect(() => {
    if (!hasKnobs) return;
    let alive = true;
    const t = setInterval(() => fetch('/api/knobs/live').then(r => r.json()).then(d => {
      if (!alive) return;
      const m = {};
      for (const k of (d.knobs || [])) if (k.stamp === 'golem:' + block.id) m[String(k.pname).toLowerCase()] = k.v;
      setLiveKnobs(prev => JSON.stringify(prev) !== JSON.stringify(m) ? m : prev);
    }).catch(() => {}), 180);
    return () => { alive = false; clearInterval(t); };
  }, [hasKnobs, block.id]);
  // la liste se relit quand la fenêtre de Vital vient de ranger un son retouché (page-designer, 2026-10-14)
  const [vpRev, setVpRev] = useState(0);
  const [winWhy, setWinWhy] = useState(false);              // le bouton grisé de Vital a été tapé : dire pourquoi
  useEffect(() => { const on = () => setVpRev(x => x + 1); window.addEventListener('golem:vital-presets', on); return () => window.removeEventListener('golem:vital-presets', on); }, []);
  const { data: vps } = useAsync(() => isVital ? fetch('/api/vital/presets').then(r => r.json()) : Promise.resolve(null), [isVital, vpRev]);
  const vPresets = (vps && vps.presets) || [];
  // macros Vital : la feuille parle la langue du PATCH — nom du sound-designer sur le dial
  // (« Grit », « Air »…) et valeur de base = celle du .vital chargé (settings.macro_control_N).
  const params = (() => {
    if (!isVital) return params0;
    const cur = (ovr && ovr.preset != null) ? ovr.preset : (block.params || {}).preset;   // scene-first
    const vp = vPresets.find(x => x.id === cur);
    if (!vp) return params0;
    return params0.map(pm => {
      const m = /^macro([1-4])$/.exec(pm.id);
      if (!m) return pm;
      const i = +m[1] - 1;
      return { ...pm, label: (vp.macros || [])[i] || pm.label,
               default: (vp.macro_vals || [])[i] ?? pm.default };
    });
  })();
  // Tuner : les ACCORDAGES que la lane peut prendre (2026-10-08) — guitare 6/7/8 cordes, basse 4/5 ;
  // la table est une copie de golem.fm (library/catalog/tunings.json, GET /api/tunings?role=)
  const isTuner = block.type === 'tuner';
  const { data: tund } = useAsync(() => isTuner ? fetch('/api/tunings?role=' + encodeURIComponent(laneInst || 'guitar')).then(r => r.json()) : Promise.resolve(null), [isTuner, laneInst]);
  // Piano (lane Keys) : instruments .sfz de library/sfz
  const isPiano = block.type === 'piano';
  const { data: sfzd } = useAsync(() => isPiano ? fetch('/api/sfz').then(r => r.json()) : Promise.resolve(null), [isPiano]);
  const sfzList = (sfzd && sfzd.instruments) || [];
  // E-Piano (lane Keys) : banques DX7 de library/dx7 (Dexed)
  const isEp = block.type === 'ep';
  const { data: dxd } = useAsync(() => isEp ? fetch('/api/dx7').then(r => r.json()) : Promise.resolve(null), [isEp]);
  const dx7Banks = (dxd && dxd.banks) || [];
  // Pads (lane Keys) + Drums : kits de la bibliothèque (library/kits). Pads = éditeur de kit ;
  // Drums = picker de kit batterie (role:drum) + picker de grooves (.mid) pour patterns/fills.
  const isPads = block.type === 'pads';
  const isDrums = block.type === 'drums' || block.type === 'drumkit';   // boîte à rythmes ET Drum Kit (lane Drums) lisent library/kits
  const [kitsRev, setKitsRev] = useState(0);            // bump après save/upload -> refetch
  const { data: kd } = useAsync(() => (isPads || isDrums) ? fetch('/api/kits').then(r => r.json()) : Promise.resolve(null), [isPads, isDrums, kitsRev]);
  const kits = (kd && kd.kits) || [];
  const [grvRev, setGrvRev] = useState(0);              // bump après import .mid -> refetch
  const { data: grd } = useAsync(() => isDrums ? fetch('/api/grooves').then(r => r.json()) : Promise.resolve(null), [isDrums, grvRev]);
  const grooves = (grd && grd.grooves) || [];
  const grvName = f => { const g = grooves.find(x => x.file === f);
    return g ? g.name : String(f || '').split('/').pop().replace(/\.midi?$/i, ''); };
  // ＋ des rails Grooves/Fills -> MODAL picker (onglet Grooves) ; ⤓ Load a song -> même modal,
  // onglet SONGS en premier citoyen. L'import fichier reste relégué au pied de l'onglet Grooves.
  const [grvPicker, setGrvPicker] = useState(null);     // {pid:'patterns'|'fills', tab?:'songs'} | null
  // appliquer une SONG remplit TOUT : séquence + banque Grooves + kit suggéré + mode Loop/1-shot
  const applySong = s => {
    const files = (s.steps || []).map(st => 'library/grooves/' + st.id + '.mid');
    onParam('sequence', (s.steps || []).map((st, i) => ({ file: files[i], times: st.times })));
    onParam('seq_mode', s.mode || 'once');
    const bank = Array.isArray(val({ id: 'patterns' })) ? val({ id: 'patterns' }) : [];
    onParam('patterns', [...bank, ...files.filter((f, i) => files.indexOf(f) === i && !bank.includes(f))]);
    if (!val({ id: 'kit' }) && s.kit && kits.some(k => k.id === s.kit)) onParam('kit', s.kit);
  };
  const grvInpRef = useRef(null);
  const grvTarget = useRef(null);                       // {pid, cur} : où ajouter après l'upload
  const importGrv = async files => {
    const t = grvTarget.current; if (!t) return;
    const added = [];
    for (const f of Array.from(files || [])) {
      const r = await fetch('/api/groove/import?name=' + encodeURIComponent(f.name), { method: 'POST', body: f })
        .then(x => x.json()).catch(() => null);
      if (r && r.ok && r.groove) added.push(r.groove.file);
    }
    if (added.length) onParam(t.pid, [...t.cur, ...added.filter(f => !t.cur.includes(f))]);
    setGrvRev(x => x + 1);
  };
  // capture choisie -> ses modèles (IRs d'un pack cab, variantes mic/EQ d'un ampli). >1 => sélecteur.
  const models = (tone && tone.models) || [];
  // nom RÉEL du matériel capturé (ampli/pédale) : label du bloc, sinon résolu depuis le catalogue par ref
  const capName = (block.label && block.label[0] !== '(' ? block.label : null) || (tone && (tone.amp || tone.title)) || null;
  const curModel = block.model != null ? block.model : (models[0] && models[0].id);
  // valeur effective (SCÈNE-FIRST) = override de la scène active -> sinon base (block.params) -> sinon défaut.
  const o = ovr || {};
  const isOvr = pm => o[pm.id] != null;
  const baseVal = pm => (block.params && block.params[pm.id] != null) ? block.params[pm.id] : pm.default;
  const val = pm => isOvr(pm) ? o[pm.id] : baseVal(pm);
  // Kit courant du bloc drums. S'il tourne sur DrumGizmo, il porte un mix D'USINE (un micro par
  // canal) -> la feuille gagne un onglet « Mix ». Un kit avldrums/rs5k n'en a pas : l'onglet
  // DISPARAÎT, d'où le badge « multi-mic · N » posé à côté du sélecteur (sinon deux kits se
  // ressemblent et l'onglet a l'air d'aller et venir tout seul).
  const curKit = isDrums ? kits.find(k => k.id === val({ id: 'kit' })) : null;
  const kitMix = (curKit && curKit.engine === 'drumgizmo' && Array.isArray(curKit.mix)) ? curKit.mix : null;
  // Whammy : le Treadle n'a de sens que si le mode courant est balayé (treadle:true). Drop/Raise = fixe.
  const modeParam = params.find(pm => pm.id === 'mode');
  const curWMode = isWhammy && modeParam ? wModes.find(m => m.name === val(modeParam)) : null;
  // zones clavier (P2 splits/layers) : zone_lo/zone_hi/transpose rendus par le
  // contrôle KeyZone (bande clavier à poignées), pas en potards
  const ZONE_IDS = ['zone_lo', 'zone_hi', 'transpose'];
  const hasZone = params.some(pm => pm.id === 'zone_lo');
  // orgue : les 9 tirettes quittent les potards pour le contrôle DrawbarsCtl (P3)
  const DB_IDS = ['db16', 'db513', 'db8', 'db4', 'db223', 'db2', 'db135', 'db113', 'db1'];
  const isOrgan = block.type === 'organ';
  const ORGAN_SIDE = ['leslie', 'vibrato'];       // colonne droite du duo tirettes|états (2026-07-23)
  // LA FEUILLE golem FX (docs/golem-fx-sheet.md) : un bloc que golem-fx joue ici montre les réglages de SA pédale —
  // la face avant dans Settings, les groupes experts (et leur interrupteur « Custom ») dans l'onglet Expert
  const gsheet = def.gfx_sheet || null;
  const isExpert = pm => !!(gsheet && pm.gfx && pm.gfx.group);
  const visible = params.filter(pm => !pm.hidden && !isExpert(pm) &&                  // hidden = plomberie (masque de notes fat1…)
    !(hasZone && ZONE_IDS.includes(pm.id)) && !(isOrgan && (DB_IDS.includes(pm.id) || ORGAN_SIDE.includes(pm.id))) &&
    // midi-pedal : le Treadle n'existe que si le DESCRIPTEUR déclare un CC de pédale d'expression
    !(isHwPedal && pm.id === 'pedal' && !hwTreadle) &&
    !(isPads && pm.id === 'kit'));                     // Pads v2 : le kit se choisit dans la rangée du tiroir
  const expertAll = params.filter(pm => !pm.hidden && isExpert(pm));
  const xGroups = gsheet ? (gsheet.groups || []).filter(g => expertAll.some(pm => pm.gfx.group === g.id)) : [];
  const hasExpert = xGroups.length > 0;
  const [xg, setXg] = useState(null);
  const xCur = xGroups.find(g => g.id === xg) || xGroups[0] || null;
  // le groupe courant : son interrupteur « Custom » d'abord, puis ses réglages (grisés tant qu'il est éteint : depends)
  const xList = xCur ? [...expertAll.filter(pm => pm.id === xCur.custom), ...expertAll.filter(pm => pm.gfx.group === xCur.id && pm.id !== xCur.custom)] : [];
  const ovrCount = visible.filter(isOvr).length;
  const expHints = params.some(pm => pm.exp);
  const enumOpts = pm =>
    pm.dynamic === 'whammy-modes' ? wModes.filter(m => m.family === 'whammy' || m.family === 'harmony').map(m => m.name)
    : pm.dynamic === 'drop-modes' ? wModes.filter(m => m.family === 'drop' || m.family === 'raise').map(m => m.name)
    : pm.dynamic === 'pedal-settings' ? hwModes.map(m => m.name)
    : (pm.options || []);
  // params CONDITIONNELS (patron neural-split-mix2 : visibles mais grisés tant que la
  // condition n'est pas remplie). pm.depends = { <pid>: <valeur attendue> }.
  const depOff = pm => pm.depends && Object.entries(pm.depends).some(([k, w]) => {
    const d2 = params.find(x => x.id === k);
    return d2 && String(val(d2)) !== String(w);
  });
  const ctl = pm => {
    // patchs DX7 (bloc ep, session UI 2026-07-23) : la banque .syx porte les 32 NOMS de patchs
    // (extraits du SysEx par /api/dx7) — le « potard numérique 0..31 » devient un vrai sélecteur
    // nommé (TINE E.PNO, RHODES---, …), même famille de contrôle que les autres pickers (◀ ▶).
    if (pm.dynamic === 'dx7-patches') {
      const bankId = val(params.find(x => x.id === 'bank') || { id: 'bank' });
      const bk = dx7Banks.find(x => x.id === bankId);
      const names = (bk && bk.patches && bk.patches.length === 32) ? bk.patches
        : Array.from({ length: 32 }, (_, i) => 'Patch ' + (i + 1));
      const cur = Math.max(0, Math.min(31, Number(val(pm)) || 0));
      const cyc = d => onParam(pm.id, (cur + d + 32) % 32);
      return html`<div class=${cls('p-enum', isOvr(pm) && 'ovr')}>${pm.label || pm.name}
        <div class="p-cyc-row">
          <select onChange=${e => onParam(pm.id, Number(e.target.value))}>
            ${names.map((nm, i) => html`<option value=${i} selected=${i === cur}>${(i + 1) + ' · ' + esc(nm)}</option>`)}
          </select>
          <button class="p-cyc-btn" title="previous patch" onClick=${() => cyc(-1)}>◀</button>
          <button class="p-cyc-btn" title="next patch" onClick=${() => cyc(1)}>▶</button>
        </div></div>`;
    }
    if (pm.type === 'bool') {
      const on = !!val(pm);
      return html`<${PCell} label=${pm.label || pm.name} value=${on ? 'On' : 'Off'} ovr=${isOvr(pm)} off=${depOff(pm)} wide=${pm.size === 2}>
        <${PToggle} on=${on} onChange=${v => onParam(pm.id, v)} />
      </${PCell}>`;
    }
    if (pm.type === 'enum') {
      // presets Vital : nom + flèches ◀ ▶ (défilement façon top-menu) — même famille de contrôle
      if (pm.dynamic === 'vital-presets') {
        const list = vPresets, cur = val(pm), idx = list.findIndex(x => x.id === cur);
        const cyc = d => { if (list.length) onParam(pm.id, idx < 0 ? list[d > 0 ? 0 : list.length - 1].id : list[(idx + d + list.length) % list.length].id); };
        return html`<div class=${cls('p-enum', isOvr(pm) && 'ovr')}>${pm.name}
          <div class="p-cyc-row">
            <select onChange=${e => onParam(pm.id, e.target.value || null)}>
              ${/* AUCUN PRESET POSÉ = Vital joue son son vierge (2026-10-14 : le menu montrait « Analog Brass »,
                   sa première entrée, alors que rien n'était chargé — « le preset n'est pas chargé »). On le dit. */''}
              ${!list.some(x => x.id === cur) ? html`<option value="" selected>Init — Vital's blank sound</option>` : ''}
              ${list.map(x => html`<option value=${x.id} selected=${x.id === cur}>${esc(x.name)}</option>`)}
            </select>
            <button class="p-cyc-btn" title="previous preset" onClick=${() => cyc(-1)}>◀</button>
            <button class="p-cyc-btn" title="next preset" onClick=${() => cyc(1)}>▶</button>
            ${svc && svc.vitalWindow ? html`<button class=${cls('p-cyc-btn p-win-btn', svc.vitalWindowOpen && 'on', svc.vitalWindowWhy && 'dim')}
              title="Open Vital's own window — your changes are kept in this patch when you close it"
              onClick=${() => svc.vitalWindowWhy ? setWinWhy(w => !w) : svc.vitalWindow(cur)}><${Icon} id="window" /><span>${svc.vitalWindowOpen ? 'Open' : 'Edit'}</span></button>` : ''}
          </div>${winWhy && svc && svc.vitalWindowWhy ? html`<span class="muted p-enum-hint">${svc.vitalWindowWhy}</span>` : ''}</div>`;
      }
      // accordage du bloc Tuner : groupé par famille (6/7/8 cordes, basse 4/5), défaut du rôle quand vide
      if (pm.dynamic === 'tunings') {
        const list = (tund && tund.tunings) || [], cur = val(pm) || (tund && tund.default) || '';
        const fams = [...new Set(list.map(x => x.family))];
        const famLb = { '6-string': '6-string', '7-string': '7-string', '8-string': '8-string', 'bass-4': 'Bass 4', 'bass-5': 'Bass 5' };
        const t = list.find(x => x.id === cur);
        return html`<div class=${cls('p-enum', isOvr(pm) && 'ovr')}>${pm.name}
          <div class="p-cyc-row">
            <select onChange=${e => onParam(pm.id, e.target.value)}>
              ${fams.map(f => html`<optgroup label=${famLb[f] || f}>
                ${list.filter(x => x.family === f).map(x => html`<option value=${x.id} selected=${x.id === cur}>${esc(x.label)}</option>`)}</optgroup>`)}
            </select>
          </div>
          ${t ? html`<span class="muted p-enum-hint">${t.midi.length} strings · ${esc((t.notes || []).join(' '))} — the Live tuner shows these strings</span>` : ''}
        </div>`;
      }
      // instruments SFZ (piano) : même famille de contrôle (select + ◀ ▶) + note de patience
      // (un gros sample set — Salamander ≈ 20 s — charge en silence après un changement)
      if (pm.dynamic === 'sfz-instruments') {
        const list = sfzList, cur = val(pm), idx = list.findIndex(x => x.id === cur);
        const cyc = d => { if (list.length) onParam(pm.id, list[((idx < 0 ? 0 : idx) + d + list.length) % list.length].id); };
        return html`<div class=${cls('p-enum', isOvr(pm) && 'ovr')}>${pm.name}
          <div class="p-cyc-row">
            <select onChange=${e => onParam(pm.id, e.target.value)}>
              ${!list.length ? html`<option value="">— no instrument —</option>` : ''}
              ${list.map(x => html`<option value=${x.id} selected=${x.id === cur}>${esc(x.name)}</option>`)}
            </select>
            <button class="p-cyc-btn" title="previous" onClick=${() => cyc(-1)}>◀</button>
            <button class="p-cyc-btn" title="next" onClick=${() => cyc(1)}>▶</button>
          </div>
          <span class="muted p-enum-hint">Large sample sets load silently for ~20 s after a change.</span>
        </div>`;
      }
      // banques DX7 (ep) : même famille de contrôle (select + ◀ ▶)
      if (pm.dynamic === 'dx7-banks') {
        const list = dx7Banks, cur = val(pm), idx = list.findIndex(x => x.id === cur);
        const cyc = d => { if (list.length) onParam(pm.id, list[((idx < 0 ? 0 : idx) + d + list.length) % list.length].id); };
        return html`<div class=${cls('p-enum', isOvr(pm) && 'ovr')}>${pm.name}
          <div class="p-cyc-row">
            <select onChange=${e => onParam(pm.id, e.target.value)}>
              ${!list.length ? html`<option value="">— no bank —</option>` : ''}
              ${list.map(x => html`<option value=${x.id} selected=${x.id === cur}>${esc(x.name)}</option>`)}
            </select>
            <button class="p-cyc-btn" title="previous" onClick=${() => cyc(-1)}>◀</button>
            <button class="p-cyc-btn" title="next" onClick=${() => cyc(1)}>▶</button>
          </div></div>`;
      }
      // kits de pads : même famille de contrôle que les presets Vital (select + ◀ ▶)
      if (pm.dynamic === 'pad-kits') {
        // les kits de PADS seulement (Library ▸ Drums ▸ Kits) : une batterie (avldrums, drumgizmo, sfz) ne se joue pas
        // sur un bloc Pads (RS5k) — elle se choisissait ici et le bloc restait muet (2026-10-13)
        const list = kits.filter(k => k.role !== 'drum' && !['sfz', 'avldrums', 'drumgizmo'].includes(k.engine));
        const cur = val(pm), idx = list.findIndex(x => x.id === cur);
        const cyc = d => { if (list.length) onParam(pm.id, list[((idx < 0 ? 0 : idx) + d + list.length) % list.length].id); };
        return html`<div class=${cls('p-enum', isOvr(pm) && 'ovr')}>${pm.name}
          <div class="p-cyc-row">
            <select onChange=${e => onParam(pm.id, e.target.value)}>
              ${!list.length ? html`<option value="">— no kit yet —</option>` : ''}
              ${list.map(x => html`<option value=${x.id} selected=${x.id === cur}>${esc(x.name)}</option>`)}
            </select>
            <button class="p-cyc-btn" title="previous kit" onClick=${() => cyc(-1)}>◀</button>
            <button class="p-cyc-btn" title="next kit" onClick=${() => cyc(1)}>▶</button>
          </div></div>`;
      }
      const opts = enumOpts(pm);
      // widget:"chips" (redesign organ 2026-07-23) : les options en BOUTONS directs — un état de
      // performance (Leslie stop/slow/fast, scanner V1..C3) se lit et se bascule d'un tap, pas
      // d'un dropdown. La cellule est large, la valeur active = chip allumée.
      if (pm.widget === 'chips') {
        return html`<${PCell} label=${pm.label || pm.name} value=${html`<span class="pcell-opt">${esc(String(val(pm) ?? '—'))}</span>`}
            ovr=${isOvr(pm)} off=${depOff(pm)} wide=${pm.size === 2 || opts.length > 4}>
          <div class="pcell-chips">
            ${opts.map(op => html`<button class=${cls('p-chip', op === val(pm) && 'on')}
              onClick=${() => onParam(pm.id, op)}>${op}</button>`)}
          </div>
        </${PCell}>`;
      }
      // enum générique -> CELLULE (patron « UNISON SOURCE » de tiroirs.jpg) : la sélection EST
      // la grande valeur, le contrôle = select (dropdown, fiable au doigt quel que soit le nombre
      // d'options). ⚠ value=${op} OBLIGATOIRE : sans lui Preact pose value="" sur chaque <option>
      // et onChange émet toujours "" (bug Playwright : le preset Vital se committait vide).
      return html`<${PCell} label=${pm.label || pm.name} value=${html`<span class="pcell-opt">${esc(String(val(pm) ?? '—'))}</span>`}
          ovr=${isOvr(pm)} off=${depOff(pm)} wide=${pm.size === 2 || opts.some(o => String(o).length > 8)}>
        <select class="pcell-sel" onChange=${e => onParam(pm.id, e.target.value)}>
          ${opts.map(op => html`<option value=${op} selected=${op === val(pm)}>${op}</option>`)}
        </select>
      </${PCell}>`;
    }
    // kit batterie (bloc drums) : select des kits role:drum (Black Pearl…), famille de contrôle des pads
    if (pm.type === 'kitref') {
      // la boîte à rythmes (bloc drums) joue AUSSI les kits de pads (RS5k, en GM depuis le 2026-10-13 — golem_drums les
      // sait jouer) ; la lane Drums (drumkit) reste aux batteries
      const list = kits.filter(k => (k.role || 'pad') === 'drum' || (block.type === 'drums' && (k.engine || 'rs5k') === 'rs5k'));
      // bloc Drum Kit (lane Drums) : seuls les moteurs portés sur une lane se choisissent (avldrums au lot 2,
      // docs/drums-kit.md) — les autres restent visibles, désactivés, et disent pourquoi
      // + PRÉSENT SUR CETTE MACHINE (2026-10-03) : `available` vient du bridge (inventaire de Reaper, fichiers
      // du kit) — un kit dont le moteur ou les échantillons manquent ici se voit, désactivé, avec sa raison
      const engineOk = k => block.type !== 'drumkit' || k.engine === 'avldrums' || k.engine === 'drumgizmo';   // drumgizmo porté le 2026-09-23
      const playable = k => engineOk(k) && k.available !== false;
      const whyNot = k => !engineOk(k) ? 'not on a lane yet (' + (k.engine || '?') + ')' : (k.unavailable_why || 'not available here');
      const cur = val(pm), idx = list.findIndex(x => x.id === cur);
      const cyc = d => { const ok = list.filter(playable); if (!ok.length) return;
        const i = ok.findIndex(x => x.id === cur); onParam(pm.id, ok[((i < 0 ? 0 : i) + d + ok.length) % ok.length].id); };
      return html`<div class=${cls('p-enum', isOvr(pm) && 'ovr')}>${pm.name}
        <div class="p-cyc-row">
          <select onChange=${e => onParam(pm.id, e.target.value || null)}>
            <option value="" selected=${!cur}>${list.length ? '— pick a kit —' : '— no kit yet —'}</option>
            ${list.map(x => html`<option value=${x.id} selected=${x.id === cur} disabled=${!playable(x)}>${esc(x.name)}${playable(x) ? '' : ' — ' + whyNot(x)}</option>`)}
          </select>
          <button class="p-cyc-btn" title="previous kit" onClick=${() => cyc(-1)}>◀</button>
          <button class="p-cyc-btn" title="next kit" onClick=${() => cyc(1)}>▶</button>
        </div></div>`;
    }
    // grooves (bloc drums, params patterns/fills) : picker multi-sélection ORDONNÉE de .mid (Library ▸
    // Grooves). Clic = ajoute/retire ; l'ordre (1· 2· …) = ordre de lecture (le pied cycle dedans).
    if (pm.type === 'midilist') {
      // rail DENSE : seulement les grooves CHOISIS (✕ = retirer) ; ＋ -> picker modal de la Library.
      const cur = Array.isArray(val(pm)) ? val(pm) : [];
      const ordered = pm.id === 'patterns';       // grooves numérotés (le pied cycle dedans) ; fills non
      return html`<div class=${cls('drum-rail', isOvr(pm) && 'ovr')}>
        <span class="drum-rail-lb">${pm.name}${ordered ? html` <em>⟳ foot cycles</em>` : ''}</span>
        <div class="p-groove-chips">
          ${cur.map((file, i) => html`<button class="p-chip on grv-chip" title=${'remove ' + esc(grvName(file))}
            onClick=${() => onParam(pm.id, cur.filter(f => f !== file))}>${ordered ? (i + 1) + '· ' : ''}${esc(grvName(file))}<span class="grv-x">✕</span></button>`)}
          <button class="p-chip grv-add" title="add grooves from the library"
            onClick=${() => setGrvPicker({ pid: pm.id })}>＋</button>
        </div>
        ${!cur.length ? html`<span class="muted grv-empty">Empty — tap ＋ to pick from the library.</span>` : ''}
      </div>`;
    }
    // EXP <n> = les RÔLES (volume / bloc) sont mappés aux pédales par la config (Système ▸ Pedalboard).
    // Rôle bloc : assigner ce potard (une seule cible par preset ; re-tap = désassigner).
    // Rôle volume : le gain du bloc volume est piloté d'office — pas d'assignation.
    const volN = (pedals && pedals.volume) === 'exp2' ? 2 : 1, blkN = 3 - volN;
    const isVolPedal = block.type === 'volume' && pm.id === 'gain';
    const onPedal = exp2 && exp2.block === block.id && exp2.param === pm.id;
    if (isVolPedal) {
      // pédale de volume : cellule large + éditeur de plage EXP (cas unique, garde son rendu riche)
      return html`<${PCell} label=${pm.name} value=${fmtVal(val(pm), pm)} unit=${pm.unit} wide=${true}
          ovr=${isOvr(pm)} base=${isOvr(pm) ? fmtVal(baseVal(pm), pm) : null}
          extra=${html`<span class="exp-chip on" title=${'driven by expression pedal EXP ' + volN + ' (volume)'}>EXP ${volN}</span>`}>
        <${PDial} value=${val(pm)} min=${pm.min} max=${pm.max} onChange=${v => onParam(pm.id, v)} />
        ${onExpVol ? html`<${ExpRange} a=${expVol} onChange=${onExpVol} />` : ''}
      </${PCell}>`;
    }
    // potard standard -> CELLULE QC (label / valeur+unité / potard SVG à arc, cf. tiroirs.jpg)
    // un bloc qui DÉCLARE ses potards à pédale (pm.exp, catalogue v21) n'offre l'EXP que sur eux —
    // le Smooth d'un kill switch sous le pied n'a pas de sens. Une cible déjà posée reste visible
    // (sinon plus moyen de la désassigner). Sans déclaration : l'EXP sur chaque potard, comme avant.
    const expOk = !expHints || pm.exp || onPedal;
    const extra = onExp && expOk ? html`<button class=${cls('exp-chip', onPedal && 'on')}
      title=${onPedal ? `EXP ${blkN} drives this knob — tap to unassign` : `assign to expression pedal EXP ${blkN}`}
      onClick=${() => onExp(pm)}>EXP ${blkN}</button>` : '';
    // potard physique en mouvement (echo live) : le dial SUIT, la valeur affichée aussi (● sur le sub)
    const lvN = pm.name && liveKnobs[String(pm.name).toLowerCase()];
    const lv = (lvN != null && pm.min != null && pm.max != null) ? pm.min + lvN * (pm.max - pm.min) : null;
    return html`<${PCell} label=${pm.label || pm.name} value=${fmtVal(lv != null ? lv : val(pm), pm)} unit=${pm.unit}
        sub=${lv != null && pm.sub ? pm.sub + ' ●' : pm.sub}
        ovr=${isOvr(pm)} base=${isOvr(pm) ? fmtVal(baseVal(pm), pm) : null} off=${depOff(pm)}
        wide=${pm.size === 2} extra=${extra}
        title=${lv != null ? 'following the hardware knob (display only — dial it here to write)' : isOvr(pm) ? 'scene override — double-tap the dial = back to base' : ''}>
      <${PDial} value=${lv != null ? lv : val(pm)} min=${pm.min} max=${pm.max} onChange=${v => onParam(pm.id, v)} />
    </${PCell}>`;
  };
  // ── grille QC (patron tiroirs.jpg) : cellules 4/rangée, en-têtes de groupe (pm.group),
  // les contrôles « larges » (selects dynamiques, kits, grooves) prennent la rangée entière. ──
  const isCellParam = pm => !(pm.type === 'kitref' || pm.type === 'midilist' || (pm.type === 'enum' && pm.dynamic));
  // l'onglet « Presets » existe dès que le bloc a des paramètres qu'un preset de bloc sait porter
  const hasPresets = !!onLoadPreset && def.engine !== 'virtual' && def.engine !== 'mode' && visible.some(isCellParam);
  const renderGrid = (list, lead) => {
    const out = lead ? [lead] : []; let g = null, i = 0;
    while (i < list.length) {
      const pm = list[i];
      if ((pm.group || null) !== g) {
        g = pm.group || null;
        if (g) out.push(html`<div class="pgrid-sec">${g}</div>`);
      }
      if (pm.widget === 'fader') {
        // bandes contiguës widget:"fader" -> UNE banque de jauges (EQ graphique façon GE-7)
        const run = [];
        while (i < list.length && list[i].widget === 'fader' && (list[i].group || null) === g) { run.push(list[i]); i++; }
        out.push(html`<${PFaderBank} items=${run.map(p2 => ({ pm: p2, value: val(p2), ovr: isOvr(p2), onChange: v => onParam(p2.id, v) }))} />`);
        continue;
      }
      out.push(isCellParam(pm) ? ctl(pm) : html`<div class="pgrid-wide">${ctl(pm)}</div>`);
      i++;
    }
    // Piano / E-Piano (2026-10-14 : « moderniser, prendre moins de hauteur ») : une grille compacte
    return html`<div class=${cls('pgrid', ['piano', 'ep'].includes(block.type) && 'pgrid-keys')}>${out}</div>`;
  };
  // ── Capture dial (cellule x2) : parcourt les N captures d'un pack au potard cranté —
  // un pack « gain sweep » (Drive 1..8) devient LE potard de la pédale (idée 2026-07-23).
  const capCell = (() => {
    if (!(models.length > 1) || tone?.parametric) return null;
    const { arr, label } = capOrder(models);
    const idx = Math.max(0, arr.findIndex(x => String(x.m.id) === String(curModel)));
    const cur = arr[idx] || arr[0];
    return html`<${PCell} label=${label || (block.type === 'cab' ? 'IR' : 'Capture')} wide=${true}
        value=${(idx + 1) + '/' + arr.length}
        ${/* POIDS : ici c'est le modèle EXACTEMENT choisi qui est en jeu, pas le pack — c'est donc
              l'endroit le plus actionnable des deux (on tourne le potard et le coût change). */''}
        sub=${html`${capSig(cur.kv, cur.m.name, cur.g)}${String(cur.m.arch) === '2' ? ' · A2' : ''}${cur.m.load === 'heavy' || cur.m.load === 'light' ? html` · <span class=${'cap-load ' + cur.m.load}>${cur.m.load}</span>` : ''}`}
        title=${esc(String(cur.m.name || ''))}>
      <${PDial} value=${idx + 1} min=${1} max=${arr.length}
        onChange=${v => { if (v == null) { onModel(arr[0].m.id); return; }
          const i2 = Math.max(1, Math.min(arr.length, Math.round(v)));
          if (i2 !== idx + 1) onModel(arr[i2 - 1].m.id); }} />
    </${PCell}>`;
  })();
  return html`<div class="sheet-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && onClose()}>
    <div class="sheet" data-doc="designer.sheet" style=${'--tc:' + (vo ? '#8b9fd7' : blkColor(block.type))}>
      <button class="sheet-tab" onClick=${onClose} title="close">
        <span class="sheet-ic">${vo ? '◈' : fxIcon(block.type)}</span>
        <b>${esc(vo ? (block.label || 'VST capture') : (def.name || block.type))}</b>
        ${vo ? html`<em>VST capture · ${esc(voPlug)}</em>`
          : capName ? html`<em title=${'capture : ' + esc(capName)}>${esc(capName)}</em>` : ''}
        <span class="sheet-tab-x">▾</span>
      </button>
      ${assign || kitMix || hasPresets || hasExpert ? html`<div class="sheet-tabs2">
        <button class=${cls('sheet-tab2', (tab || 'params') === 'params' && 'on')} data-doc="designer.sheet.settings" onClick=${() => onTab && onTab('params')}>Settings</button>
        ${hasExpert ? html`<button class=${cls('sheet-tab2', tab === 'expert' && 'on')} data-doc="designer.sheet.expert" onClick=${() => onTab && onTab('expert')}
          title="the pedal's expert settings, group by group — a group follows the profile until its Custom switch is on">Expert</button>` : ''}
        ${hasPresets ? html`<button class=${cls('sheet-tab2', tab === 'presets' && 'on')} data-doc="designer.sheet.presets" onClick=${() => onTab && onTab('presets')} title="block presets — this block's settings, not golem presets">Presets</button>` : ''}
        ${kitMix ? html`<button class=${cls('sheet-tab2', tab === 'mix' && 'on')} onClick=${() => onTab && onTab('mix')}>Mix</button>` : ''}
        ${assign ? html`<button class=${cls('sheet-tab2', tab === 'assign' && 'on')} data-doc="designer.sheet.assign" onClick=${() => onTab && onTab('assign')}>MIDI assign</button>` : ''}
      </div>` : ''}
      ${vo ? html`<div class="vc-origin">
        <span>Captured from <b>${esc(voPlug)}</b>${vo.patch ? html` in “${esc(vo.patch)}”` : ''}${vo.at ? ' · ' + esc(vo.at) : ''}${vo.part && vo.part !== 'full' ? ' · ' + esc(vo.part) : ''}${vo.null_db != null ? html` · matches the plugin to ${esc(String(vo.null_db))} dB` : ''}</span>
        ${onRename ? html`<label class="vc-name">Name <input value=${block.label || ''} onChange=${e => onRename(e.target.value.trim() || block.label)} /></label>` : ''}
      </div>` : ''}
      ${tone?.parametric && !captureControls ? html`<${ParametricControls} tone=${tone} model=${curModel} onModel=${onModel} />` : ''}
      <div class="sheet-head">
        ${vstOpen ? html`<button class="mini edit-only" onClick=${vstOpen}>Open plugin window</button>` : ''}
        ${hasCapture ? html`<button class="mini edit-only" onClick=${onPickRef}>${block.ref ? 'change the capture' : 'choose a capture'}</button>` : ''}
        ${def.scene_invariant
          ? html`<button class=${cls('ph-power', !powerOn && 'off')} onClick=${() => onPower(!powerOn)}
              title="this block ignores scene changes — a recorded loop must survive the chorus">⏻ ${powerOn ? 'Active' : 'Bypassed'}</button>`
          : html`<${PowerBtn} on=${powerOn} onPower=${onPower} sceneId=${multiScene ? sceneId : null} />`}
        ${multiScene && ovrCount ? html`<button class="mini edit-only" onClick=${onApplyAll} title="this scene's knob values become the block's settings in every scene">Use in all scenes</button>` : ''}
        <span class="grow"></span>
        ${block.type === 'standard' || block.type === 'backing-track' ? headX : ''}
        ${!isWhammy ? html`<button class="mini edit-only" onClick=${() => onMove(-1)} title="move back">←</button>
        <button class="mini edit-only" onClick=${() => onMove(1)} title="move forward">→</button>` : html`<span class="mini muted" title="the Whammy sits physically BEFORE the input — anchored at the head of the lane">⚓</span>`}
        ${onRemove ? html`<button class="mini danger" onClick=${onRemove}>🗑</button>`
          : html`<span class="mini muted" title="permanent global service — its settings are shared by every preset; only the foot assignment is per-preset">🌐 global — all presets</span>`}
      </div>
      ${isDrums ? html`<input ref=${grvInpRef} type="file" accept=".mid,.midi" multiple style="display:none"
        onChange=${e => { importGrv(e.target.files); e.target.value = ''; }} />` : ''}
      ${grvPicker ? (() => { const cur = Array.isArray(val({ id: grvPicker.pid })) ? val({ id: grvPicker.pid }) : [];
        return html`<${GroovePicker} title=${grvPicker.pid === 'fills' ? 'Fills' : 'Grooves'}
          tab0=${grvPicker.tab || 'grooves'} songs=${(grd && grd.songs) || []}
          grooves=${grooves} cur=${cur}
          onSong=${s => { applySong(s); setGrvPicker(null); }}
          onToggle=${f => onParam(grvPicker.pid, cur.includes(f) ? cur.filter(x => x !== f) : [...cur, f])}
          onImport=${() => { grvTarget.current = { pid: grvPicker.pid, cur }; grvInpRef.current && grvInpRef.current.click(); }}
          onClose=${() => setGrvPicker(null)} />`; })() : ''}

      <div class="sheet-bodies">
      ${/* L'ONGLET « PRESETS » (2026-10-11) : l'étagère de chips a quitté le corps Settings — la liste, à la VST,
            vit dans son onglet (designer-block-presets.js), avec le réglage courant et la sauvegarde à côté */''}
      ${hasPresets ? html`<div class=${cls('sheet-body', 'bpl-body', tab !== 'presets' && 'ghosted')}>
        <${BlockPresetsList} btype=${block.type} inst=${laneInst || 'guitar'} blockName=${def.name || block.type}
          defs=${[...visible, ...expertAll].filter(isCellParam)}
          current=${Object.fromEntries([...visible, ...expertAll].filter(isCellParam).map(pm => [pm.id, val(pm)]))}
          sig=${ps => bpSig(ps, [...visible, ...expertAll].filter(isCellParam))}
          onLoad=${onLoadPreset} /></div>` : ''}
      ${assign ? html`<div class=${cls('sheet-body', tab !== 'assign' && 'ghosted')}><${AssignBoard} block=${block} fxIcon=${fxIcon} ...${assign} /></div>` : ''}
      ${kitMix ? html`<div class=${cls('sheet-body', tab !== 'mix' && 'ghosted')}>
        <${DrumMixer} kit=${curKit} block=${block} onParam=${onParam} /></div>` : ''}
      ${hasExpert ? html`<div class=${cls('sheet-body', 'gx-body', tab !== 'expert' && 'ghosted')}>
        <div class="tb-seg gx-groups">${xGroups.map(g => html`<button class=${cls(xCur && xCur.id === g.id && 'on')}
          onClick=${() => setXg(g.id)}>${esc(g.name)}</button>`)}</div>
        ${renderGrid(xList)}
      </div>` : ''}
      <div class=${cls('sheet-body', ((tab === 'assign' && assign) || (tab === 'mix' && kitMix) || (tab === 'presets' && hasPresets) || (tab === 'expert' && hasExpert)) && 'ghosted')}>
        ${captureControls ? html`<${CaptureModuleControls} controls=${captureControls}
          values=${{ ...(block.params || {}), ...(ovr || {}) }} foot=${block.capture_foot}
          scene=${sceneId} onChange=${onParam} onFoot=${onCaptureFoot} />` : ''}
        ${captureControls ? html`<a class="gcap-export" href=${'/api/vst-host/capture/module/download?ref=' + encodeURIComponent(tone.id)} download>Export autonomous module</a>` : ''}
        ${/* PER SONG (docs/setlists.md §9.9) : ce bloc garde ici sa CAPACITÉ (switch, sortie, kit par
              défaut) ; son USAGE par morceau vit sur la ligne de setlist — l'encart nomme les morceaux
              qui le surchargent et y mène. Un tableau vide dit que rien ne le surcharge encore. */''}
        ${/* LA CHANSON CHARGÉE (docs/designer-song.md §4, 2026-10-18) remplace l'encart « Per song · set in the setlist »
              qui listait chaque ligne (deux fois Paper Kite quand deux setlists la jouent) : une ligne, et le Click
              montre les valeurs de la chanson à côté de celles du preset */''}
        ${svc && svc.songCtx && ['click', 'sample'].includes(block.type) ? html`<${PerSongNote} ctx=${svc.songCtx} />` : ''}
        ${svc && svc.songCtx && svc.songCtx.sid && block.type === 'click' ? html`<${ClickSongCols} ctx=${svc.songCtx} block=${block}
            presetBpm=${bpm || (svc.preset || {}).bpm} setlists=${svc.setlists} />` : ''}

        ${def.engine === 'virtual' || def.engine === 'mode' ? html`
          <div class=${cls('svc-panel', isDrums && 'drum-wide', block.type === 'standard' && 'std-wide', block.type === 'backing-track' && 'bkd-wide', block.type === 'looper' && 'loop-wide')}>
            ${block.type === 'standard' ? html`
              <${StandardSheet} params=${block.params || {}} onParam=${onParam}
                bpm=${bpm} onBpm=${svc && svc.onBpm} onHead=${setHeadX} />`
            : block.type === 'backing-track' ? html`
              ${/* LA BACKING APPARTIENT À LA CHANSON (docs/song-backing.md, 2026-10-18) : le preset est le lecteur et porte la
                    règle des stems ; il ne choisit plus de chanson (l'ancien catalogue « tap ✚ to link » est parti) */''}
              <${BackingDrawer} preset=${svc && svc.preset} params=${block.params || {}} onParam=${onParam}
                foot=${block.foot} onHead=${setHeadX} />`
            : block.type === 'rec' ? html`<${RecPanel} svc=${svc} />`
            : block.type === 'compo' ? html`<${CompoPanel} svc=${svc} params=${block.params || {}} onParam=${svc && svc.onRecSrc} />`
            : block.type === 'tuner' ? html`
              ${/* l'ACCORDAGE de la lane (2026-10-08) : il décide des cordes que l'accordeur de /live affiche */''}
              ${(def.params || []).filter(pm => pm.id === 'tuning').map(ctl)}
              <p class="muted">Listens to this lane's input. Long-press the tile to put it on a footswitch —
                including the scene row (e.g. switch 5 replaces scene E). Engage = tuner overlay, output muted behavior follows the tuner.</p>`
            : block.type === 'sample' ? (() => {
              // la liste de la CHANSON chargée (sa fiche : blocks[id].params.samples) ou celle du preset
              const ctx = svc && svc.songCtx;
              const onSong = !!(ctx && ctx.sid) && songLayer === 'song';
              const songList = ctx && ctx.sid ? ((((ctx.sheet.blocks || {})[block.id] || {}).params || {}).samples) : null;
              const presetList = Array.isArray(val({ id: 'samples' })) ? val({ id: 'samples' }) : [];
              return html`
              ${ctx && ctx.sid ? html`<${SongLayer} ctx=${ctx} layer=${songLayer} onLayer=${setSongLayer} own=${Array.isArray(songList)} />` : ''}
              <div class="svc-row"><b>Samples <em>— the foot cycles the numbered ones, in order</em></b>
                ${onSong && Array.isArray(songList) ? html`<button class="mini" onClick=${() => ctx.saveSheet({ blocks: sheetBlocks(ctx.sheet, block.id, { params: { samples: null } }) })}>↺ use the preset's</button>` : ''}</div>
              <${SampleListEd} files=${onSong && Array.isArray(songList) ? songList : presetList}
                onChange=${v => onSong ? ctx.saveSheet({ blocks: sheetBlocks(ctx.sheet, block.id, { params: { samples: v } }) }) : onParam('samples', v)} />
              <p class="muted">Foot: tap = cut the playing sample + launch the NEXT numbered one (at rest = the
                first; single-sample list = retrigger) · hold ≥0.6 s = stop. Tap a number to make a sample
                <b>song only</b> — the arrangement can still fire it, the footswitch skips it. One-shots play to
                the end and survive scene changes. Long-press the tile to put it on a footswitch.</p>`; })()
            : block.type === 'looper' ? html`
              <div class="svc-row"><b>Under your feet — while this preset is loaded</b>
                <em>tap a source to change it · scene-invariant: a recorded loop survives scene changes</em></div>
              <${LooperTutor} loops=${val({ id: 'loops' })} lanes=${(svc && svc.loopLanes) || null}
                blocks=${(svc && svc.footBlocks) || []} fxIcon=${fxIcon} fxShort=${svc && svc.fxShort}
                onLoops=${v => onParam('loops', v)}
                scenes=${(svc && svc.scenes) || []}
                sceneIdx=${((svc && svc.scenes) || []).findIndex(s => (s.id || '') === sceneId)} />
              ${(() => {                       // le calage de la 1re boucle (docs/looper.md, addendum 2026-10-14)
                const free = val({ id: 'length' }) === 'free';
                const ci = val({ id: 'count_in' }) !== false;
                const rd = val({ id: 'rec_dub' }) === true;
                return html`<div class="lp-tm">
                  <div class="lp-tm__c"><span class="lp-tm__k">Loop length</span>
                    <div class="tb-seg">
                      <button class=${cls(!free && 'on')} onClick=${() => onParam('length', 'auto')}>Auto</button>
                      <button class=${cls(free && 'on')} onClick=${() => onParam('length', 'free')}>Free</button></div>
                    <em>${free ? 'as long as your two taps, like a Ditto' : 'closes on the bar when a beat plays'}</em></div>
                  <div class="lp-tm__c"><span class="lp-tm__k">Count-in</span>
                    <div class="tb-seg">
                      <button disabled=${free} class=${cls(!free && ci && 'on')} onClick=${() => onParam('count_in', true)}>1 bar</button>
                      <button disabled=${free} class=${cls((free || !ci) && 'on')} onClick=${() => onParam('count_in', false)}>Off</button></div>
                    <em>${free ? 'Auto only' : 'nothing plays: one bar of click, the first loop starts on the 1'}</em></div>
                  <div class="lp-tm__c"><span class="lp-tm__k">After a take</span>
                    <div class="tb-seg">
                      <button class=${cls(!rd && 'on')} onClick=${() => onParam('rec_dub', false)}>Play</button>
                      <button class=${cls(rd && 'on')} onClick=${() => onParam('rec_dub', true)}>Overdub</button></div>
                    <em>${rd ? 'Rec → Dub: closing a new loop starts a layer on it' : 'closing a loop plays it — double-tap for a layer'}</em></div>
                </div>`; })()}`
            : block.type === 'drums' ? (() => {
              // layout « console compacte » + timeline SD3 (agent UX 2026-07-22) : Kit + Σ durée +
              // mode + ⤓ Load a song sur une ligne, banques à gauche, TIMELINE proportionnelle à droite.
              const P = id => params.find(x => x.id === id) || { id };
              const seqMode = val({ id: 'seq_mode' }) || 'loop';
              const seqCur = Array.isArray(val({ id: 'sequence' })) ? val({ id: 'sequence' }) : [];
              const barsOf = f => { const g = grooves.find(x => x.file === f); return (g && g.bars) || 1; };
              const totalBars = seqCur.reduce((n, s) => n + barsOf(s.file) * (s.times === 0 ? 1 : (s.times || 1)), 0);
              const hasInf = seqCur.some(s => s.times === 0);
              const secs = bpm ? Math.round(totalBars * 4 / bpm * 60) : 0;
              const mmss = Math.floor(secs / 60) + ':' + String(secs % 60).padStart(2, '0');
              return html`<div class="drum-cfg">
                <div class="drum-top">
                  ${ctl(P('kit'))}
                  ${kitMix ? html`<span class="dmx-tag" title="multi-mic kit — one output per microphone. Its balance lives in the Mix tab.">multi-mic · ${kitMix.filter(m => m.group !== 'trig').length}</span>` : ''}
                  <span class="grow"></span>
                  ${seqCur.length ? html`<span class="seq-total" title="sequence length at the preset BPM">
                    Σ ${totalBars}${hasInf ? '+' : ''} bars · ${mmss} @${bpm || '—'}</span>` : ''}
                  <div class="tb-seg" title="Loop = the whole sequence repeats · 1-shot = plays once then silence">
                    <button class=${cls(seqMode !== 'once' && 'on')} onClick=${() => onParam('seq_mode', 'loop')}>Loop</button>
                    <button class=${cls(seqMode === 'once' && 'on')} onClick=${() => onParam('seq_mode', 'once')}>1-shot</button>
                  </div>
                  <button class="mini drum-loadsong" title="load a song from the library — fills the whole drum machine"
                    onClick=${() => setGrvPicker({ pid: 'patterns', tab: 'songs' })}>⤓ Load a song</button>
                </div>
                <div class="drum-tl-row">
                  <${DrumSongEditor}
                    seq=${seqCur} bank=${Array.isArray(val(P('patterns'))) ? val(P('patterns')) : []}
                    grooves=${grooves} bpm=${bpm}
                    onSeq=${v => onParam('sequence', v)} />
                </div>
                <${GrooveLib} grooves=${grooves} songs=${(grd && grd.songs) || []}
                  patterns=${Array.isArray(val(P('patterns'))) ? val(P('patterns')) : []}
                  fills=${Array.isArray(val(P('fills'))) ? val(P('fills')) : []}
                  onStep=${f => onParam('sequence', [...seqCur, { file: f, times: 1 }])}
                  onBank=${(pid, f, on) => { const cur = Array.isArray(val(P(pid))) ? val(P(pid)) : [];
                    onParam(pid, on ? [...cur, f] : cur.filter(x => x !== f)); }}
                  onOrder=${(pid, arr) => onParam(pid, arr)}
                  onSong=${applySong} />
                <p class="drum-foot">Foot: tap = play · tap while playing = stop · hold 0.6–1.5 s = next groove
                  · hold ≥1.5 s = stop — everything follows the preset BPM (transport-free).</p>
              </div>`;
            })()
            : block.type === 'click' ? html`<${ClickPanel} params=${block.params || {}} onParam=${onParam} />`
            : html`<span class="muted">Service block — no exposed settings.</span>`}
          </div>`
        : (visible.length || capCell) ? html`
            ${block.type === 'eq-para' ? html`<${EqCurve}
              vals=${Object.fromEntries(params.map(pm => [pm.id, val(pm)]))}
              onParam=${onParam} />` : ''}
            ${['gate', 'comp', 'limiter'].includes(block.type) ? html`<${DynMeter}
              blockId=${block.id} kind=${block.type} />` : ''}
            ${isOrgan ? html`<div class="organ-top">
              <${DrawbarsCtl} vals=${DB_IDS.map(id => val(params.find(x => x.id === id) || { id }))}
                ovr=${DB_IDS.some(id => isOvr({ id }))} onChange=${(i, v) => onParam(DB_IDS[i], v)} />
              <div class="organ-side">
                ${ORGAN_SIDE.map(id => { const pm = params.find(x => x.id === id); return pm ? ctl(pm) : ''; })}
              </div>
            </div>` : ''}
            ${renderGrid(visible, capCell)}` : (isPads || captureControls) ? '' : html`<span class="muted">This block has no exposed settings.</span>`}
        ${hasZone ? html`<${KeyZoneCtl}
          lo=${val(params.find(x => x.id === 'zone_lo'))} hi=${val(params.find(x => x.id === 'zone_hi'))}
          tr=${val(params.find(x => x.id === 'transpose'))}
          ovr=${ZONE_IDS.some(id => isOvr({ id }))}
          onChange=${(id, v) => onParam(id, v)} />` : ''}
        ${isPads && kd ? html`<${PadsDrawer} data=${kd} kitId=${val(params.find(x => x.id === 'kit') || { id: 'kit' })}
          blockId=${block.id} onKit=${kid => onParam('kit', kid)}
          onSaved=${kid => { setKitsRev(kitsRev + 1); onParam('kit', kid); }} />` : ''}
      </div>
      </div>
    </div></div>`;
}

// ── tirettes d'orgue (P3) : 9 drawbars verticales tactiles, drag comme sur un B3 ──
// couleurs Hammond : 16/5⅓ marron, 8/4/2⅔ blanc, 2/1⅗/1⅓/1 blanc — ici sub=ambre,
// fondamentales=claires, harmoniques=accent. Scène-first (liseré ovr).
const DB_LABELS = ["16'", "5⅓'", "8'", "4'", "2⅔'", "2'", "1⅗'", "1⅓'", "1'"];
// v2 (redesign 2026-07-23) : les tirettes sont le HÉROS de la feuille (posées EN TÊTE, grandes),
// couleurs Hammond authentiques — 16'/5⅓' marron (sub), 8'/4'/2'/1' blanches (fondamentales),
// 2⅔'/1⅗'/1⅓' noires (mutations). Mécanique inchangée : tirer VERS SOI (bas) = plus fort.
const DB_COLORS = ['brown', 'brown', 'white', 'white', 'black', 'white', 'black', 'black', 'white'];
function DrawbarsCtl({ vals, ovr, onChange }) {
  const drag = (i, e) => {
    const col = e.currentTarget;
    const move = ev => {
      const r = col.getBoundingClientRect();
      const v = Math.max(0, Math.min(8, Math.round((ev.clientY - r.top) / r.height * 8)));
      onChange(i, v);                              // tirette B3 : tirer VERS SOI (bas) = plus fort
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
    move(e);
  };
  return html`<div class=${cls('dbars', 'hero', ovr && 'ovr')}>
    ${DB_LABELS.map((lb, i) => { const v = Number(vals[i]) || 0;
      return html`<div class=${'dbar c' + DB_COLORS[i]}
          onPointerDown=${e => drag(i, e)} title=${lb + ' = ' + v}>
        <div class="dbar-rail"><div class="dbar-pull" style=${`height:${(v / 8 * 100).toFixed(0)}%`}>
          <span class="dbar-knob">${v}</span></div></div>
        <small>${lb}</small>
      </div>`; })}
  </div>`;
}

// ── zone clavier (P2 splits/layers) : bande 128 notes à deux poignées ────────
// façon LED du Nord Stage : la plage active est colorée, drag des poignées lo/hi,
// transpose en stepper ±. Scène-first comme tout param (liseré ovr).
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const noteName = n => NOTE_NAMES[n % 12] + (Math.floor(n / 12) - 1);
// v2 (2026-07-23) : la bande = LE CLAVIER PHYSIQUE (kb_range de config/knobs.json — les
// 25 touches de l'AKAI), pas un piano 128 notes. Geste principal : GLISSER la bande = TRANSPOSE
// (les noms de notes défilent — « je décale mes 2 octaves vers le haut/bas »), double-tap = 0.
// Les bornes de SPLIT (zone_lo/hi, layers P2) restent éditables via les petites poignées hautes,
// exprimées DANS la plage physique (c'est là qu'un split a un sens sur un 25 touches).
function KeyZoneCtl({ lo, hi, tr, ovr, onChange }) {
  const { data: kcfg } = useAsync(() => fetch('/api/knobs/config').then(r => r.json()), []);
  const [KB_LO, KB_HI] = (kcfg && kcfg.kb_range) || [48, 72];
  const KB_N = KB_HI - KB_LO + 1;
  const kbName = (kcfg && kcfg.kb_name) || 'keyboard';
  const t = tr || 0;
  const L = Math.min(lo ?? 0, hi ?? 127), H = Math.max(lo ?? 0, hi ?? 127);
  const stRef = useRef(null);
  const setTr = v => onChange('transpose', Math.max(-24, Math.min(24, v)));
  // drag CORPS = transpose (delta en touches depuis le point de saisie)
  const dragTr = e => {
    e.preventDefault();
    const r = stRef.current.getBoundingClientRect();
    const kw = r.width / KB_N;
    const x0 = e.clientX, t0 = t;
    const move = ev => setTr(t0 + Math.round((ev.clientX - x0) / kw));
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  };
  const BG_LO0 = 21, BG_HI0 = 108, BG_N0 = BG_HI0 - BG_LO0 + 1;
  // drag POIGNÉE = borne de split : pointeur -> note du grand piano -> note PHYSIQUE (retire t)
  const dragZone = (which, e) => {
    e.stopPropagation(); e.preventDefault();
    const move = ev => {
      const r = stRef.current.getBoundingClientRect();
      const n = Math.max(KB_LO, Math.min(KB_HI,
        Math.round(BG_LO0 + (ev.clientX - r.left) / r.width * BG_N0 - 0.5) - t));
      if (which === 'lo') onChange('zone_lo', Math.min(n, H));
      else onChange('zone_hi', Math.max(n, L));
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
    move(e);
  };
  // grand piano de FOND (88 touches, contexte) : le « petit piano » (la fenêtre = les touches
  // physiques, décalées de t) coulisse dedans — sa POSITION est la hauteur jouée par l'AKAI.
  const BG_LO = 21, BG_HI = 108, BG_N = BG_HI - BG_LO + 1;      // A0..C8 (piano 88)
  const isBlack = n => [1, 3, 6, 8, 10].includes(n % 12);
  const pcBg = n => ((n - BG_LO) / BG_N * 100);
  const winLo = KB_LO + t, winHi = KB_HI + t;                   // ce que SONNE le clavier physique
  const zl = Math.max(L, KB_LO), zh = Math.min(H, KB_HI);
  const splitActive = L > KB_LO || H < KB_HI;
  const bgKeys = []; for (let n = BG_LO; n <= BG_HI; n++) bgKeys.push(n);
  const winKeys = []; for (let n = KB_LO; n <= KB_HI; n++) winKeys.push(n);
  return html`<div class=${cls('kz', ovr && 'ovr')}>
    <div class="kz-head"><span>${kbName}</span>
      <b>sounds ${noteName(winLo)} – ${noteName(winHi)}</b>
      ${splitActive ? html`<span class="kz-split" title="split active — this instrument only plays these keys">split ${noteName(zl)}–${noteName(zh)}</span>` : ''}
      <span class="kz-tr">
        <button class="p-cyc-btn" onClick=${() => setTr(t - 12)} title="-1 octave">−8va</button>
        <button class="p-cyc-btn" onClick=${() => setTr(t - 1)}>−</button>
        <em title="transpose (semitones) — slide your keyboard along the big piano, double-tap = reset">${t > 0 ? '+' + t : t} st</em>
        <button class="p-cyc-btn" onClick=${() => setTr(t + 1)}>＋</button>
        <button class="p-cyc-btn" onClick=${() => setTr(t + 12)} title="+1 octave">+8va</button>
      </span>
    </div>
    <div class="kz3-strip" ref=${stRef} onDblClick=${() => setTr(0)}
      onPointerDown=${e => {
        // saisie DANS la fenêtre = glissement relatif ; ailleurs = la fenêtre SAUTE sous le doigt.
        // La fenêtre s'accroche aux DO (remarque : coulisse d'octave en octave — transpose
        // multiple de 12 ; l'affinage au demi-ton reste possible via − / ＋).
        const oct = v => Math.round(v / 12) * 12;
        const r = stRef.current.getBoundingClientRect();
        const n = BG_LO + (e.clientX - r.left) / r.width * BG_N;
        const jump = (n < winLo || n > winHi + 1);
        const t0 = jump ? oct(n - (KB_LO + KB_HI + 1) / 2) : t;
        if (jump) setTr(t0);
        e.preventDefault();
        const kw = r.width / BG_N;
        const x0 = e.clientX;
        const move = ev => setTr(oct(t0 + (ev.clientX - x0) / kw));
        const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
        window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
      }}
      title="slide your keyboard window along the piano — snaps to C (octaves); − / ＋ for semitones">
      ${bgKeys.map(n => html`<div class=${cls('kz3-bgkey', isBlack(n) && 'black')}
        style=${`left:${pcBg(n)}%;width:${100 / BG_N}%`}>
        ${n % 12 === 0 ? html`<i>${noteName(n)}</i>` : ''}
      </div>`)}
      <div class="kz3-win" style=${`left:${pcBg(winLo)}%;width:${KB_N / BG_N * 100}%`}>
        ${winKeys.map(n => html`<div class=${cls('kz2-key', isBlack(n + t) && 'black', !(n >= L && n <= H) && 'off')}
          style=${`left:${(n - KB_LO) / KB_N * 100}%;width:${100 / KB_N}%`}></div>`)}
        <span class="kz3-name">${splitActive ? '' : 'YOUR KEYS'}</span>
        <span class="kz2-grip lo" style=${`left:${(zl - KB_LO) / KB_N * 100}%`} onPointerDown=${e => dragZone('lo', e)}
          title="split — lowest key this instrument plays"></span>
        <span class="kz2-grip hi" style=${`left:${(zh - KB_LO + 1) / KB_N * 100}%`} onPointerDown=${e => dragZone('hi', e)}
          title="split — highest key this instrument plays"></span>
      </div>
    </div>
  </div>`;
}

// ── Mixeur de batterie multi-micros (onglet « Mix » du bloc drums, moteur drumgizmo) ────────
// POURQUOI UN ONGLET ET PAS UNE SECTION : le corps de la feuille fait 257 px à 1024×600 et
// l'onglet Settings en occupe déjà 221 (kit 34 + timeline 56 + bibliothèque 108 + pied 23).
// Il restait 30 px — mesuré. Un banc de 14 tranches n'y entre pas, et le tasser aurait donné
// des cibles sous le plancher tactile (le piège de la page Mode, deux fois en un jour).
//
// LE MIX EST UN RÉGLAGE DE PRESET, PAS DE SCÈNE. Le bloc drums est `scene_invariant` : ses
// params vivent en BASE (page-designer.setParam le force). Donc pas de liseré d'override ici —
// ce serait mentir sur un mécanisme qui refuse d'exister pour ce bloc.
//
// DEUX SOURCES, UNE VALEUR : le kit porte le mix D'USINE, le preset ne stocke que les ÉCARTS
// (params `mic<N>_gain` / `mic<N>_pan`). Double-tap sur une tranche efface l'écart et rend la
// valeur du kit — d'où « double-tap = kit ». Aucun de ces params n'est déclaré dans effects.json :
// leur nombre et leurs noms viennent du KIT, pas du type de bloc (un autre kit aura 8 micros).
const MIXG = [['kick', 'Kick'], ['snare', 'Snare'], ['toms', 'Toms'], ['cym', 'Cymbals'],
              ['oh', 'OH'], ['room', 'Room'], ['other', '·']];

function DrumMixer({ kit, block, onParam }) {
  const [mode, setMode] = useState('gain');            // gain | pan — bascule TOUT le banc
  const bp = block.params || {};
  const mix = kit.mix || [];
  const pid = (ch, what) => 'mic' + ch + '_' + what;
  const eff = (m, what) => { const v = bp[pid(m.ch, what)]; return v == null ? (m[what] || 0) : v; };
  const nOvr = mix.reduce((n, m) => n + (bp[pid(m.ch, 'gain')] != null ? 1 : 0)
                                      + (bp[pid(m.ch, 'pan')] != null ? 1 : 0), 0);
  const master = bp.mix_master == null ? -6 : bp.mix_master;
  const bleed = bp.mix_bleed == null ? (kit.bleed == null ? 1 : kit.bleed) : bp.mix_bleed;

  // pousse le mix AFFICHÉ vers le moteur : la boîte à rythmes ne relit son kit qu'au `play`,
  // or on mixe en écoutant. L'UI possède les valeurs qu'elle montre -> elle les envoie telles quelles.
  // DÉBOUNCÉ : un glissé de fader émet ~20 valeurs, et le canal bridge->Reaper est un fichier de
  // commande à SLOT UNIQUE — inonder ce slot pendant 2 s peut écraser une commande d'un autre
  // service. 120 ms suffit à rester « temps réel » à l'oreille.
  // ⚠ PIÈGE DE FERMETURE : `onParam` déclenche un re-rendu, mais la fonction qui pousse est
  // celle du rendu COURANT — elle voit encore les anciens params. Envoyer « plus tard » (setTimeout)
  // n'y change rien : c'est la valeur capturée qui est fausse, pas le moment. On passe donc la
  // modification EN ARGUMENT et on l'applique par-dessus la base ; sinon le rig joue toujours
  // un cran en retard sur ce que l'écran affiche.
  const pushT = useRef(null);
  const withOvr = (over, key, fallback) => {
    const v = Object.prototype.hasOwnProperty.call(over, key) ? over[key] : bp[key];
    return v == null ? fallback : v;
  };
  const push = (over = {}) => {
    clearTimeout(pushT.current);
    const body = JSON.stringify({
      block: block.id,
      master: withOvr(over, 'mix_master', -6),
      bleed: withOvr(over, 'mix_bleed', kit.bleed == null ? 1 : kit.bleed),
      mix: mix.map(m => ({ ch: m.ch,
        gain: withOvr(over, pid(m.ch, 'gain'), m.gain || 0),
        pan: withOvr(over, pid(m.ch, 'pan'), m.pan || 0) })),
    });
    // DÉBOUNCÉ : un glissé de fader émet ~20 valeurs, et le canal bridge->Reaper est un fichier de
    // commande à SLOT UNIQUE — l'inonder pendant 2 s peut écraser la commande d'un autre service.
    // 120 ms reste « temps réel » à l'oreille.
    pushT.current = setTimeout(() => fetch('/api/drums/mix',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }).catch(() => {}), 120);
  };
  const set = (ch, what, v) => { const k = pid(ch, what); onParam(k, v); push({ [k]: v }); };

  const strip = m => {
    const what = mode === 'pan' ? 'pan' : 'gain';
    const v = eff(m, what);
    const trig = m.group === 'trig';
    return html`<div class=${cls('dmx-strip', trig && 'dmx-trig')}
        title=${esc(m.name) + ' — ch ' + m.ch + (trig ? ' (trigger output, not audio)' : '')}>
      <${PFader} label=${''} h=${118}
        value=${v} min=${what === 'pan' ? -1 : -60} max=${what === 'pan' ? 1 : 12}
        ovr=${bp[pid(m.ch, what)] != null}
        onChange=${nv => set(m.ch, what, nv)} />
      <span class="dmx-lb">${esc(m.short || m.name)}</span>
      <span class="dmx-ch">${m.ch}</span>
    </div>`;
  };
  const audio = MIXG.map(([g, lb]) => [lb, mix.filter(m => m.group === g)]).filter(([, a]) => a.length);
  const trig = mix.filter(m => m.group === 'trig');

  return html`<div class="dmx">
    <div class="dmx-top">
      <b>${esc(kit.name)}</b>
      <span class="dmx-tag">multi-mic · ${mix.length - trig.length}${trig.length ? '+' + trig.length : ''}</span>
      <span class="grow"></span>
      <label class="dmx-bleed" title="how much each drum leaks into the OTHER microphones — the whole point of a multi-mic kit. Preset-level: it lives in the plugin's state, so it is applied when the kit is (re)built, not while a groove plays.">
        Bleed
        <input type="range" min="0" max="1" step="0.05" value=${bleed}
          onInput=${e => { const v = Number(e.target.value); onParam('mix_bleed', v); push({ mix_bleed: v }); }} />
        <span class="dmx-val">${Math.round(bleed * 100)}%</span>
      </label>
      ${nOvr ? html`<button class="mini" title="drop every change and go back to the kit's factory mix"
        onClick=${() => { const z = { mix_master: null, mix_bleed: null };
          mix.forEach(m => { z[pid(m.ch, 'gain')] = null; z[pid(m.ch, 'pan')] = null; });
          Object.keys(z).forEach(k => onParam(k, null)); push(z); }}>↺ kit</button>` : ''}
    </div>
    <div class="dmx-bank">
      ${audio.map(([lb, arr]) => html`<div class="dmx-grp">
        <div class="dmx-grp-hd">${lb}</div>
        <div class="dmx-grp-row">${arr.map(strip)}</div>
      </div>`)}
      ${trig.length ? html`<div class="dmx-grp dmx-grp-trig">
        <div class="dmx-grp-hd" title="trigger outputs — spikes meant to drive an external module, not audio. Summing them puts a click on every hit.">trig</div>
        <div class="dmx-grp-row">${trig.map(strip)}</div>
      </div>` : ''}
    </div>
    <div class="dmx-foot">
      <div class="tb-seg" title="the faders show gains, or pans — a drum mix is panned once, not while playing">
        <button class=${cls(mode !== 'pan' && 'on')} onClick=${() => setMode('gain')}>Gain</button>
        <button class=${cls(mode === 'pan' && 'on')} onClick=${() => setMode('pan')}>Pan</button>
      </div>
      <label class="dmx-master">Master
        <input type="range" min="-24" max="12" step="0.5" value=${master}
          onInput=${e => { const v = Number(e.target.value); onParam('mix_master', v); push({ mix_master: v }); }} />
        <span class="dmx-val">${master > 0 ? '+' : ''}${master} dB</span>
      </label>
      <span class="grow"></span>
      <span class="muted">${nOvr ? nOvr + ' changed · ' : ''}double-tap resets</span>
    </div>
  </div>`;
}

// ── LE LOOPER : LA CARTE, ET SON ÉDITEUR ──────────────────────────────────────────────────────
// Contrat : docs/looper.md. Le pédalier tel que la puce le joue — 6/7/8/9 portent les boucles
// DÉCLARÉES par le preset (une ligne = un switch, une source, un libellé), 10 = tout effacer,
// 5 = tout jouer / tout arrêter à la place de la scène E.
// UNE SEULE source pour les deux endroits qui la montrent (corps du tiroir, où elle s'ÉDITE, et
// onglet MIDI assign, où elle se LIT) : deux copies divergeraient, et l'aide qui contredit le
// pied coûte une soirée. C'est déjà arrivé — l'onglet assign a porté « 9 = all, 10 = clear »
// longtemps après la bascule vers 5/9/10.
export const LOOP_SW = { rows: [1, 2, 3, 4], clear: 10, all: 5, stomps: [6, 7, 8, 9] };   // amendement 2026-10-14 : la rangée PROCHE
const LEGACY_LOOP_SW = { 6: 1, 7: 2, 8: 3, 9: 4 };   // une table d'avant se lit sur la rangée proche, dans le même ordre
export const DEFAULT_LOOPS = [{ sw: 1, src: '1' }, { sw: 2, src: '2' }, { sw: 3, src: 'k' }];

// Table du preset -> lignes propres, TRIÉES PAR SWITCH. Le tri rend l'affectation prévisible
// (6 = paire 1, puis 7, puis…) : sans lui, ajouter une boucle sur 7 après une sur 9 déplacerait
// silencieusement le contenu déjà enregistré d'une paire à l'autre.
export function loopRows(loops) {
  const src = (Array.isArray(loops) && loops.length) ? loops : DEFAULT_LOOPS;
  return src.map(r => r && ({ ...r, sw: LEGACY_LOOP_SW[+r.sw] || +r.sw }))
    .filter(r => r && LOOP_SW.rows.includes(+r.sw) && r.src)
    .map(r => ({ sw: +r.sw, src: String(r.src), label: r.label || '' }))
    .filter((r, i, a) => a.findIndex(x => x.sw === r.sw) === i)
    .sort((a, b) => a.sw - b.sw)
    .slice(0, LOOP_SW.rows.length);
}

export function LooperBoard({ loops, lanes, onLoops, scenes, sceneIdx, blocks, fxIcon, fxShort, expCol }) {
  const rows = loopRows(loops);
  const lns = lanes || [{ key: '1', label: 'Input 1', ok: true }, { key: '2', label: 'Input 2', ok: true },
                        { key: 'k', label: 'Keys', ok: true }];
  const laneOf = k => lns.find(l => l.key === k);
  const nameOf = k => { const l = laneOf(k); return l ? l.label : k === 'k' ? 'Keys' : 'Input ' + k; };
  const blocksOn = n => (blocks || []).filter(b => b.foot === n);
  const edit = !!onLoops;
  // tap = source suivante, puis « aucune » (la ligne disparaît). On ne propose que les lanes que
  // le preset offre VRAIMENT : une source absente donnerait une boucle qui enregistre du silence.
  const cycle = (sw, cur) => {
    const usable = lns.filter(l => l.ok).map(l => l.key);
    const i = cur ? usable.indexOf(cur) : -1;
    const next = i + 1 >= usable.length ? null : usable[i + 1];
    const kept = rows.filter(r => r.sw !== sw);
    onLoops(next ? [...kept, { sw, src: next, label: cur ? (rows.find(r => r.sw === sw) || {}).label : '' }]
                     .sort((a, b) => a.sw - b.sw)
                 : kept);
  };
  const rename = (sw, v) => onLoops(rows.map(r => r.sw === sw ? { ...r, label: v } : r));

  const swCell = (n, i) => {
    const row = rows.find(r => r.sw === n);
    const bs = blocksOn(n);
    if (row) {
      const dead = !(laneOf(row.src) || {}).ok;
      const title = 'loop ' + (i + 1) + ' — records ' + nameOf(row.src)
        + (dead ? ' · THIS LANE IS NOT IN THE PRESET: the loop would record silence' : '')
        + (edit ? ' · tap the source to change it' : '')
        + (bs.length ? ' · eclipses ' + bs.map(b => fxShort ? fxShort(b.type) : b.type).join(' + ') : '');
      return html`<div class=${cls('asg-sw used lt-loop', dead && 'lt-dead')} title=${title}>
        <span class="asg-n">${n}</span>
        ${edit ? html`<input class="lt-name" value=${row.label} placeholder=${nameOf(row.src)}
                        title="name this loop — the tile on /live shows it"
                        onInput=${e => rename(n, e.target.value)} />`
               : html`<b class="asg-letter sm">${esc(row.label || nameOf(row.src))}</b>`}
        ${edit ? html`<button class=${cls('lt-src', dead && 'dead')} onClick=${() => cycle(n, row.src)}
                        title="tap = next source">⇄ ${esc(nameOf(row.src))}${dead ? ' ⚠' : ''}</button>`
               : html`<em class="asg-name">${esc(nameOf(row.src))}${dead ? ' ⚠' : ''}</em>`}
      </div>`;
    }
    if (bs.length) return html`<div class="asg-sw used" title=${'switch ' + n + ' — ' + bs.map(b => fxShort ? fxShort(b.type) : b.type).join(' + ')}>
      <span class="asg-n">${n}</span>
      <span class="asg-fx">${bs.slice(0, 3).map(b => html`<i><u>${fxIcon ? fxIcon(b.type) : '•'}</u><em>${esc(fxShort ? fxShort(b.type) : b.type)}</em></i>`)}</span>
      ${edit ? html`<button class="lt-src add" onClick=${() => cycle(n, null)}
                      title=${'tap = turn switch ' + n + ' into a loop (it would eclipse this block)'}>+ loop</button>` : ''}
    </div>`;
    return html`<div class=${cls('asg-sw lt-free')} title=${'switch ' + n + ' is free — assign any effect, or add a loop here'}>
      <span class="asg-n">${n}</span>
      <b class="asg-letter sm lt-dim">free</b>
      ${edit ? html`<button class="lt-src add" onClick=${() => cycle(n, null)} title="tap = add a loop here">+ loop</button>`
             : html`<em class="asg-name">any effect you like</em>`}
    </div>`;
  };
  const clearCell = html`<div class="asg-sw used lt-danger" title="hold to wipe every loop at once">
    <span class="asg-n">${LOOP_SW.clear}</span>
    <b class="asg-letter sm">✕ clear all</b><em class="asg-name">hold 1.2 s</em></div>`;
  // la rangée du FOND : des stomps ordinaires (ce que le preset y pose) — plus jamais une boucle
  const stCell = n => { const bs = blocksOn(n);
    return bs.length ? html`<div class="asg-sw used" title=${'switch ' + n + ' — ' + bs.map(b => fxShort ? fxShort(b.type) : b.type).join(' + ')}>
        <span class="asg-n">${n}</span>
        <span class="asg-fx">${bs.slice(0, 3).map(b => html`<i><u>${fxIcon ? fxIcon(b.type) : '•'}</u><em>${esc(fxShort ? fxShort(b.type) : b.type)}</em></i>`)}</span></div>`
      : html`<div class="asg-sw lt-free" title=${'switch ' + n + ' is free — assign any effect'}>
        <span class="asg-n">${n}</span><b class="asg-letter sm lt-dim">free</b><em class="asg-name">any effect you like</em></div>`; };
  const scCell = i => { const sc = (scenes || [])[i]; const n = 1 + i;
    return html`<div class=${cls('asg-sw scene', !sc && 'void', sc && i === sceneIdx && 'here')}
      title=${sc ? 'scene ' + sc.id + (i === sceneIdx ? ' (active)' : '') : 'no scene'}>
      <span class="asg-n">${n}</span>
      <b class="asg-letter">${sc ? sc.id : '·'}</b><em class="asg-name">${sc ? esc(sc.name || '') : '—'}</em></div>`; };
  const allCell = html`<div class="asg-sw used lt-all" title="play every loop together / stop them all">
    <span class="asg-n">${LOOP_SW.all}</span>
    <b class="asg-letter sm">▶ play all</b><em class="asg-name">/ stop all</em></div>`;
  return html`<div class="asg-board lt-board">
    <div class="asg-col">
      <div class="asg-row5">${LOOP_SW.stomps.map(stCell)}${clearCell}</div>
      <div class="asg-row5">${LOOP_SW.rows.map(swCell)}${allCell}</div>
    </div>
    ${expCol || ''}
  </div>`;
}

// Le tuto : la carte + les trois gestes + la seule chose qui surprend un débutant (la première
// boucle fermée fixe la longueur, et une boucle grave le son TEL QU'IL SORT).
export function LooperTutor(props) {
  const n = loopRows(props.loops).length;
  const takes9 = false;           // amendement 2026-10-14 : les boucles ne prennent plus jamais un stomp
  return html`<div class="lt-wrap">
    <${LooperBoard} ...${props} />
    <dl class="lt-gest">
      <dt>tap</dt><dd>empty → <b>records</b> · recording → <b>closes the loop</b> and plays · playing → <b>stops</b></dd>
      <dt>double-tap</dt><dd><b>overdub</b> — stacks another layer on that loop</dd>
      <dt>hold</dt><dd><b>clears that loop</b> <em>(0.6 s)</em> — the only way to redo it</dd>
    </dl>
    <p class="lt-note">The <b>first closed loop sets the length</b>; the other ${n > 2 ? n - 1 : 'one'} align to it.
      A loop records the sound <b>as it comes out</b>, scene included — so the scenes shape what you
      play <b>on top</b>, not what is already looped, and two loops on the same source are simply two moments.
      Loops sit on the <b>row closest to your foot</b> (1-4); switches 6-9 stay free for your effects. A loop
      preset needs <b>one scene only</b>: everything you play is already loaded. Name your loops — the name is what
      you will read on <b>/live</b>.${takes9 ? html` <b class="lt-warn">Switch 9 now carries
      a loop — this preset has no footswitch left for an effect.</b>` : ''}</p>
  </div>`;
}

// Assign = mini-pédalier : on pose CE bloc sur un footswitch (6-10, plusieurs blocs par switch OK,
// ex. 7 = delay + reverb) OU sur la pédale EXP (son potard principal). Scènes en bas = lecture seule.
// Assign = le PÉDALIER en miniature : rangée haute = 5 stomps (6-10, logo + nom court de CHAQUE
// effet contrôlé), rangée basse = 5 scènes (cliquables pour les blocs à foot_scene_claim), colonne
// droite = les 2 pédales EXP. Depuis 2026-07-20 c'est le CONTENU de l'onglet « MIDI assign » du
// tiroir de bloc (l'ancien modal a disparu — appui long = tiroir ouvert sur cet onglet).
export function AssignBoard({ block, blocks, scenes, sceneIdx, sceneClaim, transport, transportLoops, transportLanes, expOn, expLabel, canExp, pedals, fxIcon, fxName, fxShort, onSwitch, onExp, onBoard }) {
  const gt = useGestures();                        // en tête : il y a un retour anticipé (bloc transport) plus bas
  const volN = (pedals && pedals.volume) === 'exp2' ? 2 : 1;
  // ── LA PORTÉE « ce bloc / tout le switch » EST RETIRÉE (2026-09-15 : « trop compliqué ») ──
  // Déplacer une case entière, voir ce que chaque switch porte sur toutes les lanes : c'est
  // l'onglet PÉDALIER du Designer (designer-pedalboard.js). Ici, on pose CE bloc, rien d'autre.
  const move = n => onSwitch(n);
  const swCell = n => { const bs = blocks.filter(b => b.foot === n); const here = block.foot === n;
    return html`<button class=${cls('asg-sw', here && 'here', bs.length && !here && 'used')}
      title=${(bs.length ? bs.map(b => fxName(b.type)).join(' + ') + ' — ' : '') + (here ? 'tap = remove this block' : 'tap = put this block here')}
      onClick=${() => here ? onSwitch(null) : move(n)}>
      <span class="asg-n">${n}</span>
      ${bs.length ? html`<span class="asg-fx">${bs.slice(0, 3).map(b => html`<i><u>${fxIcon(b.type)}</u><em>${esc(fxShort(b.type))}</em>${b.in && b.in !== '1' ? html`<b class="asg-in">${b.in === 'k' ? 'USB' : 'IN' + b.in}</b>` : ''}</i>`)}</span>`
                  : html`<span class="asg-empty">—</span>`}
    </button>`; };
  const scCell = i => { const s = scenes[i]; const n = 1 + i;
    const claimed = blocks.filter(b => b.foot === n);            // blocs spéciaux déjà posés ici
    const here = block.foot === n;
    // doctrine foot_scene_claim (2026-07-20) : les blocs spéciaux (tuner, whammy, backing)
    // peuvent REMPLACER un slot de scène — la rangée devient cliquable pour eux.
    if (sceneClaim) return html`<button class=${cls('asg-sw scene claim', here && 'here', claimed.length && !here && 'used')}
      title=${here ? 'tap = remove this block (the slot goes back to being the scene)'
        : (s ? 'tap = replace scene ' + s.id + ' with this block on switch ' + n : 'tap = put this block on switch ' + n)}
      onClick=${() => here ? onSwitch(null) : move(n)}>
      <span class="asg-n">${n}</span>
      ${claimed.length ? html`<span class="asg-fx">${claimed.slice(0, 2).map(b => html`<i><u>${fxIcon(b.type)}</u><em>${esc(fxShort(b.type))}</em></i>`)}</span>`
        : html`<b class="asg-letter">${s ? s.id : '·'}</b><em class="asg-name">${s ? esc(s.name || '') : '—'}</em>`}
    </button>`;
    return html`<div class=${cls('asg-sw scene', s && i === sceneIdx && 'here', !s && 'void')}
      title=${claimed.length ? 'switch ' + n + ' = ' + claimed.map(b => fxName(b.type)).join(' + ') + ' (special block)' : (s ? 'scene ' + s.id + (i === sceneIdx ? ' (active)' : '') + ' — read-only here' : 'no scene')}>
      <span class="asg-n">${n}</span>
      ${claimed.length ? html`<span class="asg-fx">${claimed.slice(0, 2).map(b => html`<i><u>${fxIcon(b.type)}</u><em>${esc(fxShort(b.type))}</em></i>`)}</span>`
        : html`<b class="asg-letter">${s ? s.id : '·'}</b><em class="asg-name">${s ? esc(s.name || '') : '—'}</em>`}
    </div>`; };
  const expCell = n => n === volN
    ? html`<div class="asg-sw exp void" title=${'volume pedal (role set in Settings ▸ Pedalboard)'}>
        <b class="asg-letter sm">EXP ${n}</b><em class="asg-name">volume</em></div>`
    : html`<button class=${cls('asg-sw exp', expOn && 'here')} disabled=${!canExp && !expOn}
        title=${canExp ? 'tap = drive this block\'s main knob with the expression pedal' : 'no continuous knob to map'}
        onClick=${onExp}>
        <b class="asg-letter sm">EXP ${n}</b>
        <em class="asg-name">${expOn ? '● this block' : (expLabel ? esc(expLabel) : 'assign')}</em>
      </button>`;
  // bloc TRANSPORT (foot_mode, ex. looper) : il ne se pose pas sur UN switch — c'est sa table de
  // boucles qui décide lesquels il prend (docs/looper.md). Ici on la LIT ; elle s'édite dans
  // l'onglet Settings du même tiroir, sur la MÊME image.
  if (transport) {
    return html`<div class="asg-embed">
      <${GestureLegend} t=${gt} block="looper-slot" extra=${gt ? [
        { label: 'Switch 5', gestures: gt.blocks['looper-all'].states.any.gestures },
        { label: 'Switch 10', gestures: gt.blocks['looper-kill'].states.any.gestures }] : []} />
      <p class="muted">Transport block — the looper owns the switches its <b>loops</b> sit on, plus
        <b>10</b> (clear all) and <b>5</b> (play/stop all, in place of scene E). Nothing to assign to a switch:
        change which loop goes where in the <b>Settings</b> tab. A switch a loop takes is a switch you no
        longer have for an effect.</p>
      <${LooperBoard} loops=${transportLoops} lanes=${transportLanes}
        scenes=${scenes} sceneIdx=${sceneIdx} blocks=${blocks}
        fxIcon=${fxIcon} fxShort=${fxShort}
        expCol=${html`<div class="asg-expcol">${expCell(1)}${expCell(2)}</div>`} />
    </div>`;
  }
  // ── CE QUE LE PARTAGE D'UN SWITCH COÛTE, dit AU MOMENT où on le fait (2026-09-21) ──
  // Deux blocs sur un switch doivent parler le même langage de gestes. Rec + Backing = UN geste
  // « prise » (un tap lance les deux depuis le début, un tap arrête) : le backing y perd son
  // double-tap et son appui long. Un bloc piloté par des GESTES (sample, drums, standard) garde la
  // main sur son switch : les autres blocs posés là ne partent pas du pied (app.py _do_stomp).
  const GESTURE = { 'backing-track': 1, sample: 1, drums: 1, standard: 1 };
  const mates = block.foot ? blocks.filter(b => b.foot === block.foot && b.id !== block.id) : [];
  const group = block.foot ? [block, ...mates] : [];
  const has = t => group.some(b => b.type === t);
  const notes = [];
  // LE SWITCH DU MORCEAU (docs/arrangement.md §7) : ce qui part avec lui se COCHE sur la chanson
  // (« When the song starts »). On n'empile plus rien sur ce switch — un bloc posé là ne part pas du pied.
  if (has('arrangement')) {
    notes.push('Switch ' + block.foot + ' starts the song. What starts with it — backing, click, the take, samples — is ticked on the song: Songs ▸ When the song starts. Tap again stops everything (in Foot mode: next part, then stop after the last one); the song also stops by itself at its end.');
    const left = group.filter(b => b.type !== 'arrangement');
    if (left.length) notes.push(left.map(b => fxName(b.type)).join(' + ') + ' will not fire from the pedalboard here: the song keeps switch ' + block.foot + ' to itself. To start it with the song, tick it in Songs ▸ When the song starts.');
  } else if (has('rec') && has('backing-track'))
    notes.push('Switch ' + block.foot + ' is one gesture: a tap starts the take and the backing from the top (after the Rec count-in), a tap stops both. The backing loses its double-tap (restart) and long-press (stop) on this switch.');
  else if (mates.length && group.some(b => GESTURE[b.type]) && group.some(b => !GESTURE[b.type]))
    notes.push(group.filter(b => GESTURE[b.type]).map(b => fxName(b.type)).join(' + ') + ' is driven by tap / hold gestures and keeps switch ' + block.foot
      + ' to itself: ' + group.filter(b => !GESTURE[b.type]).map(b => fxName(b.type)).join(' + ') + ' will not fire from the pedalboard here.');
  if (block.foot >= 1 && block.foot <= 5 && scenes[block.foot - 1])
    notes.push('Scene ' + scenes[block.foot - 1].id + ' can no longer be reached from the pedalboard (it still is from the screen).');
  return html`<div class="asg-embed">
      <p class="muted">Tap a footswitch to put this block on it (several effects can share one switch) ·
        EXP = drive its main knob with your foot.</p>
      ${/* LA LÉGENDE EN PHRASES, TOUJOURS VISIBLE (2026-09-21 : le « ? » de la maquette vit ICI,
            pas sur /live où la barre du haut est pleine). Même table que les glyphes de /live. */''}
      <${GestureLegend} t=${gt} block=${has('rec') && has('backing-track') ? 'take' : block.type}
        extra=${[...(gt && !gt.blocks[block.type] && !(has('rec') && has('backing-track'))
                     ? [{ label: '', gestures: [{ g: 'tap', text: 'On / off' }] }] : []),
                 ...(gt && block.foot === gt.select_switch
                     ? [{ label: 'Switch ' + gt.select_switch, gestures: gt.blocks.select.states.any.gestures }] : [])]} />
      ${notes.map(n => html`<p class="asg-note">⚠ ${n}</p>`)}
      ${onBoard ? html`<div class="asg-scope">
        <span>Move a whole switch, or see what every switch holds across the lanes</span>
        <button class="mini" onClick=${onBoard}>Open the pedalboard</button></div>` : ''}
      <div class="asg-board">
        <div class="asg-col">
          <div class="asg-row5">${[6, 7, 8, 9, 10].map(swCell)}</div>
          <div class="asg-row5">${[0, 1, 2, 3, 4].map(scCell)}</div>
        </div>
        <div class="asg-expcol">${expCell(1)}${expCell(2)}</div>
      </div>
    </div>`;
}

// tous les blocs « réels » (dict) du preset qui portent une assignation de footswitch (.foot 6-10)
const footBlocksOf = p => {
  const g = p.guitar || {}, out = [];
  const push = a => (a || []).forEach(b => b && typeof b === 'object' && out.push(b));
  push(g.pre); ((g.split || {}).branches || []).forEach(br => push(br.blocks)); push(g.post);
  push((p.voice || {}).chain); push((p.keys || {}).chain);
  return out;
};

// réglages du preset — présentés en PÉDALIER (façon Live/Assign) : rangée haute = 5 stomps (switches
// 6-10), rangée basse = 5 scènes. Chaque tuile = couleur + animation (« effet ») de la case sur la
// page Live. CLÉ des couleurs/anims = numéro de switch pour les stomps (comme la page Live lit
// colors[sw]/anims[sw]) et id de scène pour les scènes — l'ancien keying par TYPE ne s'appliquait pas.
export function PresetSettings({ p, upd, onClose }) {
  const blocks = footBlocksOf(p);
  const STOMP_SW = [6, 7, 8, 9, 10];
  const scenes = (p.scenes || []).slice(0, 5);
  const colorOf = (k, i) => (p.colors || {})[k] || LIVE_PALETTE[i % 5];
  const animOf = k => (p.anims || {})[k] || '';
  const animLabel = v => (ANIM_STYLES.find(a => a[0] === v) || ANIM_STYLES[0])[1];
  const setColor = (k, v) => upd(n => { n.colors = n.colors || {}; n.colors[k] = v; });
  const setAnim = (k, v) => upd(n => { n.anims = n.anims || {}; if (!v) delete n.anims[k]; else n.anims[k] = v; });
  // ⚠ 2026-09-15 (le mainteneur, premier pack venu de golem.fm) : la tuile de la modale fabriquait sa classe
  // par « 'anim-' + valeur » — juste pour le pack default (« fire » → anim-fire), faux pour un pack
  // (« u1/lurk » → « anim-u1/lurk », une classe avec un slash que rien ne stylise). animClass() est
  // LA règle (anim-u1-lurk), et le CSS du pack se charge ici aussi, pas seulement dans le picker.
  useEffect(() => { Object.values(p.anims || {}).forEach(v => ensurePackCss(animPackOf(v))); }, [JSON.stringify(p.anims || {})]);
  const [fxFor, setFxFor] = useState(null);          // {k, pc} : tuile dont on choisit l'effet (double-modal)

  // tuile-pédale : liseré LED coloré + libellé + choix couleur + BOUTON d'effet (ouvre le picker)
  const pad = (k, i, kind, head, sub, icons, dim) => html`
    <div class=${cls('set-pad', kind, dim && 'empty', animClass(animOf(k)))} style=${'--pc:' + colorOf(k, i)}>
      <div class="set-pad-hd"><b class="set-pad-k">${head}</b>${icons ? html`<span class="set-pad-ic">${icons}</span>` : ''}</div>
      <div class="set-pad-name">${sub}</div>
      <input type="color" value=${colorOf(k, i)} onInput=${e => setColor(k, e.target.value)} title="tile color on the Live page" />
      <button class="set-pad-fx" onClick=${() => setFxFor({ k, pc: colorOf(k, i) })} title="animation effect on the Live page">
        ${animLabel(animOf(k))}<span class="cr">▾</span></button>
    </div>`;
  const stompPad = (n, i) => {
    const bs = blocks.filter(b => Number(b.foot) === n);
    const icons = bs.slice(0, 3).map(b => ICON[b.type] || '•');      // des nœuds (glyphes SVG), pas une chaîne
    const name = bs.length === 0 ? '—' : bs.length === 1 ? esc(bs[0].label || bs[0].type) : bs.length + ' fx';
    return pad(n, i, 'stomp', '#' + n, name, bs.length ? icons : '', bs.length === 0);
  };
  const scenePad = i => {
    const n = 1 + i;
    // slot revendiqué (foot_scene_claim) : la tuile Live est celle du SERVICE — couleur/anim
    // éditables ici, CLÉ = numéro de switch (1-5), comme les stomps (retour UX 2026-07-20)
    const claimed = blocks.filter(b => Number(b.foot) === n);
    if (claimed.length) {
      const b0 = claimed[0];
      return pad(String(n), i, 'scene claim', '#' + n, esc(b0.label || b0.type), ICON[b0.type] || '•', false);
    }
    const s = scenes[i];
    // slot SANS scène : la tuile existe quand même sur /live (fantôme « #4 D ») — le mainteneur veut pouvoir
    // configurer TOUTES les cases du pédalier (2026-09-15). Clé = numéro de switch, comme un slot
    // revendiqué ; la page Live lit colors["4"] / anims["4"] pour ce fantôme.
    if (!s) return pad(String(n), i, 'scene', '#' + n, 'no scene ' + 'ABCDE'[i], '', true);
    return pad(s.id, i, 'scene', s.id, esc(s.name || '—'), '', false);
  };

  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card set-cfg">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Preset settings</h2>
      <div class="set-row"><label>Name</label>
        <input class="set-name" value=${p.name} onInput=${e => upd(n => n.name = e.target.value)} /></div>
      ${/* STYLE = des FAMILLES de genre, 0 à 2, ORDONNÉES (docs/genres.md, 2026-10-06) : le sous-genre est
            pour les chansons, chez golem.fm. Le chiffre dit l'ordre : la 1re range le preset dans la liste. */''}
      <div class="set-row"><label>Style</label>
        <div class="chips set-genres">${GENRE_FAMILIES.map(([id, label]) => { const sel = (p.styles || (p.style ? [p.style] : []));
          const at = sel.indexOf(id);
          return html`<button class=${'chip' + (at >= 0 ? ' on' : '')}
            title=${at >= 0 ? 'tap to remove' : sel.length >= 2 ? 'max 2 — replaces the oldest' : 'tap to add (max 2)'}
            onClick=${() => upd(n => { let cur = (n.styles || (n.style ? [n.style] : [])).slice();
              if (cur.includes(id)) cur = cur.filter(x => x !== id);
              else { cur.push(id); if (cur.length > 2) cur = cur.slice(-2); }
              n.styles = cur; n.style = cur[0] || null; })}>${label}${at >= 0 ? html`<sup class="set-genre-n">${at + 1}</sup>` : ''}</button>`; })}</div></div>

      <div class="set-board">
        <div class="set-board-line">
          <span class="set-vlbl">STOMPS</span>
          <div class="set-row5">${STOMP_SW.map(stompPad)}</div>
        </div>
        <div class="set-board-line">
          <span class="set-vlbl">SCENES</span>
          <div class="set-row5">${[0, 1, 2, 3, 4].map(scenePad)}</div>
        </div>
      </div>

      ${fxFor ? html`<${EffectPicker} current=${animOf(fxFor.k)} pc=${fxFor.pc}
        onPick=${(v, color) => { setAnim(fxFor.k, v);
          // la COULEUR du pack (manifeste `effects[].color` ou `palette.primary`, golem.fm 2026-09-15) devient
          // celle de la tuile au moment du choix — l'ambiance est fixée par le pack, l'utilisateur peut la rechanger
          if (color) setColor(fxFor.k, color);
          setFxFor(null); }} onClose=${() => setFxFor(null)} />` : ''}
    </div></div>`;
}

// plage de la pédale de VOLUME (remarque 2026-07-20) : talon -> heel dB, pointe -> toe dB.
// Écrit preset.exp1 {block,param,min,max}, lu par _apply_exp côté bridge (défauts -60 / 0 :
// talon ≈ silence, pointe = unité). Steppers ±3 dB — pas de champ texte (kiosk).
function ExpRange({ a, onChange }) {
  const min = (a && a.min != null) ? a.min : -60, max = (a && a.max != null) ? a.max : 0;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const row = (lb, v, set, lo, hi) => html`<div class="expr-row"><em>${lb}</em>
    <button class="mini" onClick=${() => set(clamp(v - 3, lo, hi))}>−</button>
    <b>${v} dB</b>
    <button class="mini" onClick=${() => set(clamp(v + 3, lo, hi))}>+</button></div>`;
  return html`<div class="exp-range" title="pedal range: heel (down) → toe (up)">
    ${row('toe', max, v => onChange(min, v), -24, 6)}
    ${row('heel', min, v => onChange(v, max), -60, 0)}
  </div>`;
}

// picker d'effet (DOUBLE-MODAL, même taille que Preset settings) : grille de tuiles qui PRÉVISUALISENT
// chaque animation (comme la page de démo). Tap = sélectionne et revient à Preset settings. Rendu
// par-dessus (2e .detail) ; on stoppe la propagation du clic de fond pour ne pas fermer le modal parent.
export function EffectPicker({ current, pc, onPick, onClose }) {
  const bg = e => { if (e.target.classList.contains('detail')) { e.stopPropagation(); onClose(); } };
  // ── PACKS (docs/anim-packs.md) : 20 tuiles par pack. « default » est livré et verrouillé ;
  // les autres s'installent par golem.fm — d'où un sélecteur, jamais un bouton « + ajouter ».
  const { data: pk } = useAsync(() => fetch('/api/anim-packs').then(r => r.json()).catch(() => ({ packs: [] })), []);
  const packs = (pk && pk.packs) || [];
  const [pid, setPid] = useState(animPackOf(current));
  const pack = packs.find(x => x.id === pid) || packs[0];
  useEffect(() => { ensurePackCss(pid); }, [pid]);
  // le default garde ses valeurs NUES (compat des presets écrits avant les packs)
  const valOf = eid => (pid === 'default' ? eid : (eid ? pid + '/' + eid : ''));
  const items = pack ? pack.effects : ANIM_STYLES.map(([v, l]) => ({ id: v, name: l }));
  return html`<div class="detail" onClick=${bg}>
    <div class="detail-card set-cfg">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Animation effect</h2>
      <div class="fx-pick-hd">
        <p class="muted">Tap an effect — it plays on this tile on the Live page.</p>
        ${packs.length > 1
          ? html`<select class="flt-sel fx-packsel" value=${pid} title="tile pack — new packs arrive from golem.fm"
              onChange=${e => setPid(e.target.value)}>
              ${packs.map(x => html`<option value=${x.id} selected=${x.id === pid}>${esc(x.name)}${x.locked ? '' : ' ·'} ${x.effects.length}</option>`)}
            </select>`
          : html`<span class="fx-packsel one" title="tile packs of 20 — new ones arrive from golem.fm">
              ▦ ${esc((pack && pack.name) || 'Default')} <em>${items.length}</em></span>`}
      </div>
      <div class="fx-pick-grid">
        ${items.map(e2 => { const v = valOf(e2.id);
          // couleur portée par le pack : par effet (`color`) sinon par pack (`palette.primary`) ; le default n'en a pas
          const okc = c => /^#[0-9a-fA-F]{6}$/.test(String(c || '')) ? c : null;
          const packColor = okc(e2.color) || okc(((pack && pack.palette) || {}).primary) || null;
          return html`<button class=${cls('fx-opt', animClass(v), current === v && 'on')}
            style=${'--pc:' + (packColor || pc || '#3f7fd6')} onClick=${() => onPick(v, packColor)}>
            <span class="fx-opt-nm">${esc(e2.name)}</span>
          </button>`; })}
      </div>
    </div></div>`;
}

// routage I/O (lecture) + lien vers Système ▸ Routing pour éditer
// popover de choix de sortie d'une chaîne : OUT 1 / OUT 2 / OUT 1·2 (les 2 baffles).
// Fonction pure (rendue inline dans .io-out-wrap) — pas un composant à état.
export function Picker(current, onPick, opts, side) {
  return html`<div class=${cls('out-pop', side === 'right' && 'right')} onClick=${e => e.stopPropagation()}>
    ${opts.map(([v, lbl]) => html`<button class=${cls('out-opt', v === current && 'on', v === 'NONE' && 'none')}
      onClick=${e => { e.stopPropagation(); onPick(v); }}>${lbl}</button>`)}
  </div>`;
}
export const OUT_OPTS = [['1', 'OUT 1'], ['2', 'OUT 2'], ['1-2', 'OUT 1·2'], ['NONE', 'NONE']];
export const IN_OPTS = [['1', 'IN 1'], ['2', 'IN 2'], ['NONE', 'NONE']];

// feuille « nommer / dupliquer » : saisit un nom puis sauve (en place si Enregistrer d'un preset neuf,
// ou nouvelle copie si Dupliquer). Un seul champ + Entrée pour valider.
// `kind` : ce qu'on NOMME. Un patch essayé se sauvait en preset ; corrigé le 2026-09-12, mais la
// feuille, elle, continuait d'annoncer « Name preset » — donc le geste juste portait le mauvais
// mot, et le mainteneur a cru que le mode patch n'était pas actif. Une feuille qui ment sur ce qu'elle
// enregistre est aussi grave que l'enregistrement au mauvais endroit : c'est elle qu'on lit.
export function NameSheet({ initial, dup, kind, fixed, onOk, onClose }) {
  const PATCH = kind === 'patch';
  // `fixed` : le nom vient de golem.fm et il est l'IDENTITÉ du patch — on le montre, on ne le
  // modifie pas ici. Le renommer fabriquerait un second objet sans lien avec la source, et les
  // révisions suivantes ne le retrouveraient plus (docs/archive/patch-sync-avis.md). Un autre nom = un
  // autre patch : c'est le geste « dupliquer », pas celui-ci.
  const [name, setName] = useState(initial || '');
  const submit = () => { if (name.trim()) onOk(name); };
  // ⚠ `autofocus` ne prend pas sur un élément monté APRÈS le chargement : il fallait taper dans le
  // champ, puis sélectionner le nom proposé pour l'effacer (2026-09-08). Au montage : focus
  // ET tout sélectionné — on tape, ça remplace.
  const inRef = useRef(null);
  useEffect(() => { const el = inRef.current; if (el) { el.focus(); el.select(); } }, []);
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card sm">
      <button class="close" onClick=${onClose}>×</button>
      <h2>${dup ? 'Duplicate the preset' : PATCH ? 'Name this patch' : 'Name preset'}</h2>
      <p class="muted">${dup ? "A copy is created under this name (the original stays intact)."
        : PATCH ? "It goes to your patch library — one musician's sound, not a whole rig. No song is affected."
        : "Give this preset a name to save it."}</p>
      ${fixed ? html`<div class="name-in name-fixed" title="this name is the patch's identity on golem.fm — kept so later versions stay linked">${name}</div>
        <p class="muted" style="margin:6px 0 0; font-size:12px">Name kept from golem.fm — it keeps future versions linked. Want another name? Save, then duplicate.</p>`
      : html`<input class="name-in" ref=${inRef} value=${name} placeholder=${PATCH ? 'Patch name' : 'Preset name'}
        onInput=${e => setName(e.target.value)} onKeyDown=${e => e.key === 'Enter' && submit()} />`}
      <button class="primary" style="margin-top:14px" onClick=${submit} disabled=${!name.trim()}>
        ${dup ? '⧉ Duplicate' : '💾 Save'}</button>
    </div></div>`;
}

// feuille Scène (re-tap de l'onglet actif) : renommer · niveau PAR LANE (lot 3) · supprimer
// ── Feuille SCÈNE (appui long sur l'onglet d'une scène) ───────────────────────────────────
// Refaite le 2026-09-11 (retour : « il est un peu moche ») : c'étaient trois `set-row`
// génériques et un bouton rouge posé en bas. Trois principes, les mêmes que partout ici :
//   · ce que la scène EST se lit d'un coup d'œil — sa lettre dans la pastille des onglets, son
//     nom en clair, et une phrase qui dit ce qu'une scène rappelle (on l'oublie vite) ;
//   · les niveaux se règlent AU DOIGT — un fader, pas un champ numérique à viser au stylet ;
//     la valeur se tape pour revenir au défaut ;
//   · la suppression S'ARME en deux taps, comme le retrait d'une lane : sur un écran tactile,
//     un effleurement ne doit pas emporter une scène et ses réglages.
export function SceneSheet({ sc, lanes, canDelete, onName, onLevel, onDelete, onClose }) {
  const [arm, setArm] = useState(false);
  useEffect(() => { if (!arm) return; const t = setTimeout(() => setArm(false), 4000); return () => clearTimeout(t); }, [arm]);
  const rows = lanes && lanes.length ? lanes : [{ id: 'guitar', name: 'Guitar', level: (sc.levels || {}).guitar }];
  const dflt = id => (id === 'guitar' ? -6 : 0);
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card scn-card" data-doc="designer.scene-sheet">
      <button class="close" onClick=${onClose}>×</button>
      <div class="scn-head">
        <span class="scn-badge">${sc.id}</span>
        <input class="scn-name" value=${sc.name || ''} placeholder="Name this scene"
          onInput=${e => onName(e.target.value)} />
      </div>
      <p class="scn-sub muted">Blocks on/off, knob overrides and the levels below are recalled together when you step on ${sc.id}.</p>
      <div class="scn-sect">Levels in ${sc.id}</div>
      <div class="scn-levels">
        ${rows.map(L => { const v = L.level ?? dflt(L.id);
          return html`<label class="scn-lvl">
            <span class="scn-lname" title=${esc(L.name) + (L.state ? ' — state « ' + L.state + ' » in this scene' : '')}>${L.icon ? html`<i>${L.icon}</i>` : ''}<b>${esc(L.name)}</b>${L.state ? html`<small class="scn-state">${esc(L.state)}</small>` : ''}</span>
            <input type="range" min="-24" max="12" step="0.5" value=${v}
              onInput=${e => onLevel(L.id, +e.target.value)} />
            <b class="scn-val" onClick=${() => onLevel(L.id, dflt(L.id))}
              title=${'tap to go back to ' + dflt(L.id) + ' dB'}>${v > 0 ? '+' : ''}${Number(v).toFixed(1)}</b>
            <span class="scn-unit muted">dB</span>
          </label>`; })}
      </div>
      <div class="scn-danger">
        ${!canDelete ? html`<span class="scn-last muted">A preset keeps at least one scene.</span>`
          : arm ? html`<button class="mini danger armed scn-del" onClick=${onDelete}>Delete ${sc.id}${sc.name ? ' « ' + esc(sc.name) + ' »' : ''} — tap again to confirm</button>`
                : html`<button class="mini danger scn-del" onClick=${() => setArm(true)}>✕ Delete this scene</button>`}
      </div>
    </div></div>`;
}

// popover du + de scène : Nouvelle / Dupliquer / Importer d'un preset
export function ScenePlus({ presets, activeName, onNew, onDup, onImport, onClose }) {
  const [tab, setTab] = useState('choose');
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card sm">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Add scene</h2>
      ${tab === 'choose' ? html`
        <button class="row-btn" onClick=${onNew}>＋ New (empty)</button>
        <button class="row-btn" onClick=${onDup}>⧉ Duplicate « ${esc(activeName)} »</button>
        <button class="row-btn" onClick=${() => setTab('import')}>⤵ Import from a preset…</button>
      ` : html`
        <p class="muted" style="margin:0 0 10px">Choose a scene from a preset — it's added here (non-destructive).</p>
        <div class="import-list">
          ${presets.map(pr => html`<div class="import-preset">
            <div class="import-pname">${esc(pr.name || pr.id)}</div>
            ${(pr.scenes || []).length ? (pr.scenes).map(s => html`<button class="row-btn sm" onClick=${() => onImport(pr.id, s.id)}>${s.id} · ${esc(s.name || '')}</button>`) : html`<span class="muted" style="font-size:12px">no scene</span>`}
          </div>`)}
        </div>
        <button class="mini" style="margin-top:10px" onClick=${() => setTab('choose')}>← back</button>
      `}
    </div></div>`;
}

// ── éditeur de SÉQUENCE du bloc drums (mode song, façon SD3 — contrat 2026-07-22) ──
// La séquence = étapes ordonnées {file, times} (times 0 = ∞). Tuile = groove + badge ×n ;
// tap = sélection (mini-éditeur : ±passages, ∞, ◀▶, 🗑), drag & drop souris + flèches tactiles.
// Loop = toute la séquence reboucle ; 1-shot = silence net à la fin (le pied redémarre).
// Songs = arrangements poussés par golem.fm (groove-pack `song`) : 1 tap les applique
// (+ suggestion de kit si le bloc n'en a pas).
export function DrumSongEditor({ seq, bank, grooves, bpm, onSeq }) {
  const [selI, setSelI] = useState(-1);
  const [adding, setAdding] = useState(false);
  const [dragI, setDragI] = useState(null);
  const nameOf = f => { const g = grooves.find(x => x.file === f);
    return g ? g.name : String(f || '').split('/').pop().replace(/\.midi?$/i, ''); };
  const step = seq[selI];
  const upd = (i, patch) => onSeq(seq.map((s, k) => k === i ? { ...s, ...patch } : s));
  const move = (i, d) => { const j = i + d; if (j < 0 || j >= seq.length) return;
    const a = [...seq]; [a[i], a[j]] = [a[j], a[i]]; onSeq(a); setSelI(j); };
  const drop = i => { if (dragI == null || dragI === i) { setDragI(null); return; }
    const a = [...seq]; const [x] = a.splice(dragI, 1); a.splice(i, 0, x); onSeq(a); setDragI(null); setSelI(i); };
  const tLabel = s => (s.times === 0 ? '∞' : '×' + (s.times || 1));
  // timeline proportionnelle (patron SD3) : largeur ∝ mesures × passages (flex-grow, min 56px
  // tactile) ; teinte STABLE par groove (hash du nom) ; ∞ = slab hachuré à poids fixe.
  const hueOf = s => { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 360; };
  const barsOf = f => { const g = grooves.find(x => x.file === f); return (g && g.bars) || 1; };
  const growOf = s => barsOf(s.file) * (s.times === 0 ? 3 : Math.min(s.times || 1, 8));
  const playedBars = s => barsOf(s.file) * (s.times === 0 ? 1 : (s.times || 1));
  return html`<div class="seq-ed">
    ${seq.length ? (() => { let acc = 1; return html`<div class="seq-tl">
      ${seq.map((s, i) => html`<button class=${cls('seq-block', i === selI && 'on', dragI === i && 'drag', s.times === 0 && 'inf')}
        style=${`flex-grow:${growOf(s)};--gh:${hueOf(nameOf(s.file))}`} draggable="true"
        onDragStart=${() => setDragI(i)} onDragOver=${e => e.preventDefault()} onDrop=${() => drop(i)}
        onClick=${() => setSelI(i === selI ? -1 : i)} title=${esc(nameOf(s.file))}>
        <span class="n">${i + 1}</span><span class="nm">${esc(nameOf(s.file))}</span>
        <span class="band">${tLabel(s)}</span>
      </button>`)}
      <button class=${cls('seq-block', 'add', adding && 'on')} title="add a step (from the Grooves bank)"
        onClick=${() => setAdding(!adding)}>＋</button>
    </div>
    <div class="seq-ruler">
      ${seq.map(s => { const st = acc; acc += playedBars(s); return html`<span style=${`flex-grow:${growOf(s)}`}>${st}</span>`; })}
      <span class="end">${seq.some(s => s.times === 0) ? '∞' : acc}</span>
    </div>`; })() : ''}
    ${!seq.length ? html`<div class="seq-empty-row">
      <button class="seq-block add" title="add a step (from the Grooves bank)" onClick=${() => setAdding(!adding)}>＋</button>
      <span class="muted">No sequence — the foot loops the first groove. Build a song (verse ×4, chorus ×2…)
        or load one from the library (⤓).</span>
    </div>` : ''}
    ${adding ? html`<div class="p-groove-chips seq-bank">
      ${bank.length ? bank.map(f => html`<button class="p-chip"
          onClick=${() => { onSeq([...seq, { file: f, times: 1 }]); setSelI(seq.length); }}>${esc(nameOf(f))}</button>`)
        : html`<span class="muted">The Grooves bank is empty — add grooves on the left first.</span>`}
    </div>` : ''}
    ${seq.some((s, i) => s.times === 0 && i < seq.length - 1) ? html`
      <div class="muted seq-warn">⚠ steps after an ∞ step will never play — move ∞ last (or make it finite).</div>` : ''}
    ${step ? html`<div class="seq-tools">
      <span class="seq-tl-lb">passes</span>
      <button class="mini" onClick=${() => upd(selI, { times: Math.max(1, (step.times || 1) - 1) })}>−</button>
      <b class="seq-times">${tLabel(step)}</b>
      <button class="mini" onClick=${() => upd(selI, { times: Math.min(99, (step.times || 0) + 1) })}>+</button>
      <button class=${cls('mini', step.times === 0 && 'on')} title="loop this step forever (open outro — live actions still work)"
        onClick=${() => upd(selI, { times: step.times === 0 ? 1 : 0 })}>∞</button>
      <span class="grow"></span>
      <button class="mini" onClick=${() => move(selI, -1)} title="move earlier">◀</button>
      <button class="mini" onClick=${() => move(selI, 1)} title="move later">▶</button>
      <button class="mini danger" onClick=${() => { onSeq(seq.filter((_, k) => k !== selI)); setSelI(-1); }}>🗑</button>
    </div>` : ''}
  </div>`;
}

// ── éditeur de la LISTE de samples du bloc Sample (2026-07-23) : liste ORDONNÉE = ordre de
// cycle au pied (tap = suivant). Ajout depuis Library ▸ Samples ou upload direct ; ▶ = pré-écoute
// navigateur ; sets = modèles nommés (library/sample-sets, poussés par golem.fm ou sauvés ici).
// ── ÉDITEUR DE LA LISTE D'UN LANCEUR ──────────────────────────────────────────────────────
// Une entrée vaut "chemin.wav" (forme historique) OU {file, foot:false}. Le drapeau ▸ règle le
// vrai problème : cette liste EST l'ordre de rotation du pied, et un morceau à douze cues
// d'arrangement ferait défiler douze sons sous la pédale. « Rotation au pied à la carte »
// (décision 2026-07-31, docs/arrangement.md §21). Le rang affiché ne compte QUE les
// entrées au pied — c'est ce que le pied fait réellement.
export function SampleListEd({ files, onChange }) {
  const { data } = useAsync(() => fetch('/api/kits').then(r => r.json()), []);
  const { data: setsD, reload: reloadSets } = useAsync(() => fetch('/api/sample-sets').then(r => r.json()), []);
  const all = ((data || {}).samples || []).filter(s => (s.kind || 'short') === 'short');   // les `song` sont des stems de backing, pas des one-shots
  const sets = (setsD || {}).sets || [];
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);       // panneau « Load a set »
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [playing, setPlaying] = useState(null);
  const audRef = useRef(null);
  const fileRef = useRef(null);
  useEffect(() => () => { if (audRef.current) audRef.current.pause(); }, []);
  const fileOf = e => (typeof e === 'string' ? e : (e || {}).file) || '';
  const footOf = e => (typeof e === 'string' ? true : (e || {}).foot !== false);
  const toggleFoot = i => onChange(files.map((e, j) => j !== i ? e
    : (footOf(e) ? { file: fileOf(e), foot: false } : fileOf(e))));
  const nameOf = e => { const f = fileOf(e); const s = all.find(x => x.file === f);
    return s ? s.name : String(f || '').split('/').pop(); };
  const move = (i, d) => { const j = i + d; if (j < 0 || j >= files.length) return;
    const a = [...files]; [a[i], a[j]] = [a[j], a[i]]; onChange(a); };
  const preview = f => {
    if (audRef.current) audRef.current.pause();
    if (playing === fileOf(f)) { setPlaying(null); return; }
    const a = new Audio('/api/sample?file=' + encodeURIComponent(fileOf(f)));
    audRef.current = a; setPlaying(fileOf(f));
    a.onended = () => setPlaying(null);
    a.play().catch(() => setPlaying(null));
  };
  const upload = async fl => {
    const added = [];
    for (const f of Array.from(fl || [])) {
      const r = await fetch('/api/sample/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f })
        .then(x => x.json()).catch(() => null);
      if (r && r.ok && r.file) added.push(r.file);
    }
    if (added.length) onChange([...files, ...added]);
  };
  const saveSet = async () => {
    if (!name.trim() || !files.length) return;
    await fetch('/api/sample-sets', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), samples: files.map(f => ({ file: fileOf(f), name: nameOf(f) })) }) })
      .catch(() => null);
    setSaving(false); setName(''); reloadSets();
  };
  return html`<div class="smp-ed">
    ${(() => { let rank = 0; return files.length ? files.map((f, i) => { const onFoot = footOf(f);
      if (onFoot) rank++;
      return html`<div class=${cls('smp-row', !onFoot && 'nofoot')}>
      <button class=${cls('smp-n', 'smp-n-btn', !onFoot && 'off')}
        title=${onFoot ? 'on the foot — position ' + rank + ' in the rotation. Tap: song only.'
                       : 'song only — the arrangement can fire it, the footswitch skips it. Tap: put it back on the foot.'}
        onClick=${() => toggleFoot(i)}>${onFoot ? rank : '·'}</button>
      <b>${esc(nameOf(f))}</b>
      ${!onFoot ? html`<em class="smp-songonly" title="not in the foot rotation">song only</em>` : ''}
      <span class="grow"></span>
      <button class=${cls('mini', playing === fileOf(f) && 'on')} title="preview in the browser" onClick=${() => preview(f)}>${playing === fileOf(f) ? '■' : '▶'}</button>
      <button class="mini" title="move earlier" onClick=${() => move(i, -1)}>◀</button>
      <button class="mini" title="move later" onClick=${() => move(i, 1)}>▶</button>
      <button class="mini danger" onClick=${() => onChange(files.filter((_, k) => k !== i))}>✕</button>
    </div>`; }) : html`<p class="muted">No samples — the footswitch has nothing to launch. Add files below.</p>`; })()}
    <div class="smp-tools">
      <button class=${cls('mini', adding && 'on')} onClick=${() => { setAdding(!adding); setLoading(false); }}>＋ Add</button>
      <button class="mini" onClick=${() => fileRef.current && fileRef.current.click()}>⬆ Upload</button>
      <span class="grow"></span>
      <button class=${cls('mini', loading && 'on')} disabled=${!sets.length}
        title=${sets.length ? 'replace the list with a saved set' : 'no saved set yet'}
        onClick=${() => { setLoading(!loading); setAdding(false); }}>⤓ Load a set</button>
      <button class=${cls('mini', saving && 'on')} disabled=${!files.length}
        onClick=${() => setSaving(!saving)}>💾 Save as set</button>
      <input ref=${fileRef} type="file" accept=".wav,.mp3,.flac,.ogg,.aif,.aiff,audio/*" multiple hidden
        onChange=${e => { upload(e.target.files); e.target.value = ''; }} />
    </div>
    ${/* ⚠ le filtre compare des CHEMINS, jamais les entrées : depuis le drapeau au pied une
          entrée peut être un objet, et `files.includes(s.file)` ne matchait plus rien — la
          bibliothèque proposait alors d'ajouter ce qui était déjà là. */''}
    ${adding ? (() => { const has = f => files.some(e => fileOf(e) === f);
      const left = all.filter(s => !has(s.file));
      return html`<div class="p-groove-chips">
      ${left.map(s => html`<button class="p-chip"
          onClick=${() => onChange([...files, s.file])}>${esc(s.name)}</button>`)}
      ${!left.length ? html`<span class="muted">Library ▸ Samples is empty (or everything is already in the list).</span>` : ''}
    </div>`; })() : ''}
    ${loading ? html`<div class="p-groove-chips">
      ${sets.map(st => html`<button class="p-chip set" title=${(st.samples || []).map((x, i) => (i + 1) + '· ' + x.name).join('  ')}
        onClick=${() => { onChange((st.samples || []).map(x => x.file)); setLoading(false); }}>
        ▤ ${esc(st.name)} <b>×${(st.samples || []).length}</b></button>`)}
    </div>` : ''}
    ${saving ? html`<div class="smp-save">
      <input placeholder="set name…" value=${name} onInput=${e => setName(e.target.value)}
        onKeyDown=${e => e.key === 'Enter' && saveSet()} />
      <button class="mini on" disabled=${!name.trim()} onClick=${saveSet}>Save</button>
    </div>` : ''}
  </div>`;
}

// ── bibliothèque de grooves INLINE (maquette SD3 2026-07-23) : sous la timeline, patron
// SD3-Grooves.jpg inversé (chez eux le browser est AU-DESSUS). Recherche + onglets
// Grooves|Songs ; par groove : ＋ Step (ajoute à la séquence), chips Bank/Fill (appartenance
// aux banques du pied). Songs : tap = applique l'arrangement complet (applySong).
// v2 FUSION TOTALE (choix option A de l'audit UX 2026-07-23) : plus de colonne banques —
// l'appartenance vit SUR chaque ligne : pill [G n] = banque Grooves avec le n° d'ORDRE du cycle
// au pied, pill [F] = banque Fills. Filtres All | In Grooves | In Fills (les vues In-* sont
// ordonnées comme la banque et offrent le réordonnancement ◀▶).
export function GrooveLib({ grooves, songs, patterns, fills, onStep, onBank, onOrder, onSong }) {
  const [tab, setTab] = useState('grooves');
  const [flt, setFlt] = useState('all');                 // all | patterns | fills
  const [q, setQ] = useState('');
  const match = s => !q || s.toLowerCase().includes(q.toLowerCase());
  const mg = g => match(g.name + ' ' + (g.genre || '') + ' ' + (g.pack || ''));
  const byFile = f => grooves.find(g => g.file === f);
  // vues In-* : l'ORDRE de la banque fait foi (pas l'ordre de la bibliothèque)
  const shown = flt === 'all' ? grooves.filter(mg)
    : (flt === 'patterns' ? patterns : fills).map(byFile).filter(Boolean).filter(mg);
  const shownSongs = (songs || []).filter(s => match(s.name || ''));
  const bump = (pid, f, d) => { const arr = [...(pid === 'patterns' ? patterns : fills)];
    const i = arr.indexOf(f), j = i + d;
    if (i < 0 || j < 0 || j >= arr.length) return;
    [arr[i], arr[j]] = [arr[j], arr[i]]; onOrder(pid, arr); };
  return html`<div class="grvlib">
    <div class="grvlib-hd">
      <div class="grv-tabs">
        <button class=${cls('grv-tab', tab === 'grooves' && 'on')} onClick=${() => setTab('grooves')}>♩ Grooves</button>
        <button class=${cls('grv-tab', tab === 'songs' && 'on')} onClick=${() => setTab('songs')}>♫ Songs</button>
      </div>
      ${tab === 'grooves' ? html`<div class="grvlib-flt">
        ${[['all', 'All'], ['patterns', `In Grooves${patterns.length ? ' · ' + patterns.length : ''}`],
           ['fills', `In Fills${fills.length ? ' · ' + fills.length : ''}`]].map(([k, lb]) => html`
          <button class=${cls('p-chip', flt === k && 'on')} onClick=${() => setFlt(k)}>${lb}</button>`)}
      </div>` : ''}
      <input class="grvlib-q" placeholder="search…" value=${q} onInput=${e => setQ(e.target.value)} />
    </div>
    <div class="grvlib-list">
      ${tab === 'grooves' ? (shown.length ? shown.map(g => { const gi = patterns.indexOf(g.file);
          return html`<div class="grvlib-row">
          <b>${esc(g.name)}</b>
          <span class="muted">${g.bars || 1} bar${(g.bars || 1) > 1 ? 's' : ''}${g.genre ? ' · ' + esc(g.genre) : ''}${g.pack ? ' · ' + esc(g.pack) : ''}</span>
          <span class="grow"></span>
          ${flt !== 'all' ? html`
            <button class="mini" title="earlier in the cycle" onClick=${() => bump(flt, g.file, -1)}>◀</button>
            <button class="mini" title="later in the cycle" onClick=${() => bump(flt, g.file, 1)}>▶</button>` : ''}
          <button class=${cls('grv-pill', gi >= 0 && 'on')} title="Grooves bank — the foot cycles through it, in this order"
            onClick=${() => onBank('patterns', g.file, gi < 0)}>G${gi >= 0 ? gi + 1 : ''}</button>
          <button class=${cls('grv-pill', fills.includes(g.file) && 'on')} title="Fills bank — tap while playing"
            onClick=${() => onBank('fills', g.file, !fills.includes(g.file))}>F${fills.includes(g.file) ? '●' : ''}</button>
          <button class="mini" title="append to the song sequence" onClick=${() => onStep(g.file)}>＋ Step</button>
        </div>`; })
        : html`<p class="muted">${flt === 'all' ? (q ? 'No groove matches.' : 'No grooves yet — import .mid files in Library ▸ Kits.')
            : flt === 'patterns' ? 'The foot bank is empty — tap G on a groove (view: All).'
            : 'No fills — tap F on a groove (view: All).'}</p>`)
      : (shownSongs.length ? shownSongs.map(s => html`<div class="grvlib-row">
          <b>${esc(s.name)}</b>
          <span class="muted">${(s.steps || []).length} steps${s.kit ? ' · kit ' + esc(s.kit) : ''}</span>
          <span class="grow"></span>
          <button class="mini" title="fills the whole drum machine (sequence + bank + kit + mode)"
            onClick=${() => onSong(s)}>⤓ Apply</button>
        </div>`) : html`<p class="muted">No songs — push one from golem.fm (groove-pack) or save one here.</p>`)}
    </div>
  </div>`;
}

// ── picker « Drum library » (bloc drums) : MODAL 2 onglets au-dessus de la feuille —
// SONGS (1er citoyen : tap = applique l'arrangement COMPLET — séquence + banque + kit + mode —
// puis ferme) | GROOVES (multi-sélection LIVE vers le rail cible, recherche, meta bars·genre).
// L'import .mid reste possible mais RELÉGUÉ au pied de l'onglet Grooves (le vrai import = Library).
export function GroovePicker({ title, tab0, songs, grooves, cur, onSong, onToggle, onImport, onClose }) {
  const [tab, setTab] = useState(tab0 || 'grooves');
  const [q, setQ] = useState('');
  const shown = grooves.filter(g => !q || (g.name + ' ' + (g.genre || '') + ' ' + (g.pack || '')).toLowerCase().includes(q));
  const shownSongs = (songs || []).filter(s => !q || (s.name || '').toLowerCase().includes(q));
  return html`<div class="grv-scrim" onClick=${e => e.target.classList.contains('grv-scrim') && onClose()}>
    <div class="grv-picker">
      <div class="grv-picker-hd">
        <div class="grv-tabs">
          <button class=${cls(tab === 'songs' && 'on')} onClick=${() => setTab('songs')}>♫ Songs</button>
          <button class=${cls(tab === 'grooves' && 'on')} onClick=${() => setTab('grooves')}>Grooves → ${title}</button>
        </div>
        <button class="primary grv-done" onClick=${onClose}>Done</button></div>
      <input class="search" type="search" placeholder=${tab === 'songs' ? 'Search songs…' : 'Search grooves…'}
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      ${tab === 'songs' ? html`<div class="grv-picker-list">
        ${shownSongs.map(s => html`<div class="grv-song-row" title="load this song — fills sequence, bank, kit & mode"
            onClick=${() => onSong(s)}>
          <b>♫ ${esc(s.name)}</b>
          <span class="meta">${s.kit ? 'kit · ' + esc(s.kit) + ' · ' : ''}${s.mode === 'once' ? '1-shot' : 'Loop'} · ${(s.steps || []).length} steps</span>
        </div>`)}
        ${!shownSongs.length ? html`<div class="muted grv-picker-none">No songs${q ? ' matching' : ''} —
          songs are arrangements pushed by golem.fm (groove-packs with a song section).</div>` : ''}
      </div>`
      : html`<div class="grv-picker-list">
        ${shown.map(g => { const on = cur.includes(g.file);
          return html`<div class=${cls('grv-picker-row', on && 'on')} onClick=${() => onToggle(g.file)}>
            <b>${on ? '✓ ' : ''}${esc(g.name)}</b>
            <span class="meta">${g.bars != null ? g.bars + ' bar' + (g.bars > 1 ? 's' : '') : ''}${g.genre ? ' · ' + esc(g.genre) : ''}${g.pack ? ' · ♫ ' + esc(g.pack) : ''}</span>
          </div>`; })}
        ${!shown.length ? html`<div class="muted grv-picker-none">No grooves${q ? ' matching' : ''} —
          import .mid below or in Library ▸ Drums ▸ Grooves.</div>` : ''}
      </div>
      <div class="grv-picker-ft">
        <button class="mini" onClick=${onImport}>⬆ Import .mid…</button>
        <span class="muted">${cur.length} in ${title}</span>
      </div>`}
    </div></div>`;
}

// ── presets PAR BLOC, CLASSÉS PAR INSTRUMENT (tiroirs v2 + agent UX 2026-07-23) ──
// La rangée ne montre QUE l'instrument de la lane (le GoleM le connaît — avantage sur un VST) :
// [scope 🟠Guitar] chips(inst) · [∞ any] … 💾 Save (inst=lane) … ⋯ all (navigateur modal).
// Défaut PAR (type, instrument) : ● sur le défaut effectif de la lane (inst sinon repli any).
const INST_LB = { guitar: 'Guitar', bass: 'Bass', voice: 'Voice', drums: 'Drums', keys: 'Keys', any: 'Any' };
const INSTS = ['guitar', 'bass', 'voice', 'drums', 'keys', 'any'];

// signature d'un preset : les 3 premiers réglages formatés (« Thresh -50 dB · Atk 3 ms · … »)
function bpSig(params, defs) {
  const parts = [];
  for (const pm of defs || []) {
    if (params[pm.id] == null) continue;
    parts.push((pm.label || pm.name) + ' ' + fmtVal(params[pm.id], pm) + (pm.unit ? ' ' + pm.unit : ''));
    if (parts.length >= 3) break;
  }
  return parts.join(' · ');
}

export function BlockPresets({ btype, inst, defs, current, onLoad }) {
  const [rev, setRev] = useState(0);
  const { data } = useAsync(() => fetch('/api/block-presets/' + encodeURIComponent(btype)).then(r => r.json()), [btype, rev]);
  const list = (data && data.presets) || [];
  const [saving, setSaving] = useState(false);
  const [nm, setNm] = useState('');
  const [svInst, setSvInst] = useState(null);          // instrument du Save (défaut = lane)
  const [browse, setBrowse] = useState(false);
  const mine = list.filter(p => p.inst === inst);
  const anys = inst === 'any' ? [] : list.filter(p => p.inst === 'any');
  // défaut EFFECTIF de la lane : (type, inst) sinon repli (type, any)
  const effDef = (list.find(p => p.default && p.inst === inst) || list.find(p => p.default && p.inst === 'any') || {}).id;
  // étagère inline PLAFONNÉE (1 ligne garantie) : défaut d'abord, puis instrument, puis ∞ any ;
  // le reste vit dans le navigateur (« ⋯ +N ») — décision affichage delays 2026-07-23.
  const MAX_INLINE = 99;   // étagère en UNE ligne à scroll horizontal (2026-07-23) — plus de cap visuel
  const ordered = [...mine, ...anys].sort((a, b) => (b.id === effDef) - (a.id === effDef));
  const shown = ordered.slice(0, MAX_INLINE);
  const extra = ordered.length - shown.length;
  const save = async () => {
    const name = nm.trim(); if (!name) return;
    await fetch('/api/block-presets/' + encodeURIComponent(btype), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, params: current, inst: svInst || inst }) }).catch(() => null);
    setSaving(false); setNm(''); setSvInst(null); setRev(r => r + 1);
  };
  const chip = pr => html`<button class=${cls('p-chip', pr.inst === 'any' && 'any')}
    title=${'load « ' + esc(pr.name) + ' » — applies to ALL scenes (clears this block\'s scene overrides)'}
    onClick=${() => onLoad(pr.params)}>${esc(pr.name)}${pr.id === effDef ? html`<span class="bp-def" title="loaded when the block is added on this lane"> ●</span>` : ''}</button>`;
  return html`<div class=${'bp-row inst-' + (inst || 'any')}>
    <span class="bp-lb">Presets</span>
    <button class="bp-scope" title=${'presets for this lane\'s instrument — tap to browse all'}
      onClick=${() => setBrowse(true)}><span class="dot"></span>${INST_LB[inst] || inst}</button>
    <div class="bp-chips">
      ${shown.filter(p => p.inst !== 'any').map(chip)}
      ${shown.some(p => p.inst === 'any') ? html`<span class="bp-div"></span>${shown.filter(p => p.inst === 'any').map(chip)}` : ''}
      ${saving ? html`
        <input class="bp-name" value=${nm} placeholder="preset name…" autofocus
          onInput=${e => setNm(e.target.value)} onKeyDown=${e => e.key === 'Enter' && save()} />
        <span class="muted" style="font-size:11px">for</span>
        <select class="bp-inst" value=${svInst || inst} onChange=${e => setSvInst(e.target.value)}>
          ${INSTS.map(i => html`<option value=${i} selected=${i === (svInst || inst)}>${INST_LB[i]}</option>`)}
        </select>
        <button class="mini" onClick=${save}>Save</button>
        <button class="mini" onClick=${() => { setSaving(false); setNm(''); setSvInst(null); }}>✕</button>`
      : html`<button class="p-chip bp-save" title="save the current settings as a block preset"
          onClick=${() => setSaving(true)}>💾 Save…</button>`}
      <button class="p-chip bp-more" title="browse presets for every instrument" onClick=${() => setBrowse(true)}>⋯ ${extra > 0 ? '+' + extra : 'all'}</button>
    </div>
    ${browse ? html`<${PresetBrowser} btype=${btype} inst=${inst} defs=${defs} list=${list} current=${current}
      onLoad=${ps => { onLoad(ps); setBrowse(false); }}
      onChanged=${() => setRev(r => r + 1)} onClose=${() => setBrowse(false)} />` : ''}
  </div>`;
}

// navigateur modal (shell du GroovePicker) : onglets = instruments POURVUS (+ lane courante),
// rangées = nom + signature + [default]/[set def] + ✕ (perso seulement), Save vers l'onglet actif.
export function PresetBrowser({ btype, inst, defs, list, current, onLoad, onChanged, onClose }) {
  const tabs = INSTS.filter(i => i === inst || list.some(p => p.inst === i));
  const [tabI, setTabI] = useState(inst);
  const [nm, setNm] = useState('');
  const [armDel, setArmDel] = useState(null);
  const rows = list.filter(p => p.inst === tabI);
  const setDef = async id => {
    await fetch('/api/block-presets/' + encodeURIComponent(btype) + '/' + encodeURIComponent(id) + '/set-default',
      { method: 'POST' }).catch(() => null);
    onChanged();
  };
  const del = async id => {
    if (armDel !== id) { setArmDel(id); setTimeout(() => setArmDel(a => a === id ? null : a), 2500); return; }
    setArmDel(null);
    await fetch('/api/block-presets/' + encodeURIComponent(btype) + '/' + encodeURIComponent(id), { method: 'DELETE' }).catch(() => null);
    onChanged();
  };
  const save = async () => {
    const name = nm.trim(); if (!name) return;
    await fetch('/api/block-presets/' + encodeURIComponent(btype), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, params: current, inst: tabI }) }).catch(() => null);
    setNm(''); onChanged();
  };
  return html`<div class="grv-scrim" onClick=${e => e.target.classList.contains('grv-scrim') && onClose()}>
    <div class=${'grv-picker inst-' + tabI}>
      <div class="grv-picker-hd">
        <div class="grv-tabs">
          ${tabs.map(i => html`<button class=${cls(i === tabI && 'on', 'pk-tab', i === inst && 'cur')}
            onClick=${() => setTabI(i)}>${INST_LB[i]}</button>`)}
        </div>
        <button class="primary grv-done" onClick=${onClose}>Done</button></div>
      <div class="grv-picker-list">
        ${rows.map(p => html`<div class="grv-picker-row">
          <b class="pk-nm" title="load this preset" onClick=${() => onLoad(p.params)}>${p.default ? '● ' : ''}${esc(p.name)}</b>
          <span class="sig">${esc(bpSig(p.params, defs))}</span>
          ${p.default ? html`<span class="pk-def">default</span>`
            : html`<button class="pk-setdef" title="make this the default for this instrument (loaded at block add)"
                onClick=${() => setDef(p.id)}>set def</button>`}
          ${!p.factory ? html`<button class=${cls('bp-x', armDel === p.id && 'arm')}
            onClick=${() => del(p.id)}>${armDel === p.id ? '?' : '✕'}</button>` : ''}
        </div>`)}
        ${!rows.length ? html`<div class="muted grv-picker-none">No ${INST_LB[tabI]} presets for this block yet —
          save one below.</div>` : ''}
      </div>
      <div class="grv-picker-ft">
        <input class="bp-name" value=${nm} placeholder=${'save current settings as a ' + INST_LB[tabI] + ' preset…'}
          onInput=${e => setNm(e.target.value)} onKeyDown=${e => e.key === 'Enter' && save()} />
        <button class="mini" onClick=${save}>💾 Save</button>
      </div>
    </div></div>`;
}



// ── LE PANNEAU DU MAGNÉTOPHONE — un seul composant pour deux foyers (2026-09-08) : la feuille
// du bloc Rec dans le Designer et le tiroir REC de Settings ▸ Mode. Les deux éditent LA MÊME config
// globale (config/recorder.json) — il n'y a pas de réglage par mode ni par preset.
export function RecPanel({ svc }) {
  const locked = false;
  const panel = (() => {
              const recMode = (svc && svc.recSrc && svc.recSrc.rec_mode) || 'mix';
              return html`
              <div class="svc-row"><b>Record inputs</b>
                <div class="src-chips">
                  ${/* N CASES (lot 4 cosmétique) : une par entrée de la carte (svc.recInputs), plus USB */''}
                  ${[...(((svc && svc.recInputs) || []).length ? svc.recInputs.map(e => ['in' + String(e.ch), 'IN ' + e.ch]) : [['in1', 'IN 1'], ['in2', 'IN 2']]), ['usb', 'USB']].map(([k, lb]) => {
                    const on = !(svc && svc.recSrc) || svc.recSrc[k] !== false;
                    return html`<button class=${cls('p-chip', on && 'on')}
                      onClick=${() => !locked && svc && svc.onRecSrc && svc.onRecSrc(k, !on)}>${lb}</button>`; })}
                </div>
              </div>
              <div class="svc-row"><b>Mode</b>
                <div class="src-chips">
                  ${(() => {
                    // « Mix + Multitrack + DI » n'est pas un 4e mode moteur : c'est tracks_di AVEC
                    // la coche mix. On l'expose comme un choix EXCLUSIF de la même rangée parce que
                    // c'est ainsi qu'on le lit — « Song mix » isolé plus bas ne voulait rien dire
                    // sans la rangée au-dessus (retour 2026-07-27).
                    const keepMix = !(svc && svc.recSrc) || svc.recSrc.mix !== false;
                    const sel = recMode === 'mix' ? 'mix' : recMode === 'tracks' ? 'tracks'
                              : keepMix ? 'all' : 'tracks_di';
                    const pick = k => !locked && svc && svc.onRecSrc && (k === 'all'
                      ? (svc.onRecSrc('rec_mode', 'tracks_di'), svc.onRecSrc('mix', true))
                      : (svc.onRecSrc('rec_mode', k), svc.onRecSrc('mix', false)));
                    return [['mix', 'Mix'], ['tracks', 'Multitrack'], ['tracks_di', 'Multitrack + DI'],
                            ['all', 'Mix + Multitrack + DI']].map(([k, lb]) => html`
                      <button class=${cls('p-chip', sel === k && 'on')}
                        onClick=${() => pick(k)}>${lb}</button>`);
                  })()}
                </div>
              </div>
              ${/* « Transcribe takes » — docs/archive/tablature-study.md §12. Le réglage vit ICI et pas
                    dans un bloc Tablature : la transcription est une CONSÉQUENCE de
                    l'enregistrement, pas quelque chose que le rig fait pendant qu'on joue. Et la
                    garantie « il faut du DI » se lit dans le MÊME tiroir, au lieu de traverser
                    deux blocs comme le prévoyait la décision abandonnée. */''}
              ${/* ── OÙ VONT LES PRISES ────────────────────────────────────────────────
                    Le groupe est une DESTINATION, pas un réglage de son : sa place est sur le
                    bloc qui enregistre, pas dans la topbar (retirée le 2026-09-07).

                    ⚠ Cette rangée n'apparaît QUE si le rack connaît des espaces — donc
                    seulement après un appairage à golem.fm. Un golem qui ne s'est jamais
                    connecté ne prononce pas le mot « groupe » : la notion vient du cloud, et
                    ses prises attendent simplement sur le disque, sans tag et sans rien à
                    régler. C'est le comportement natif, pas un cas dégradé.

                    ⚠ Et ce n'est PAS un paramètre du bloc : c'est le miroir de l'état du rack.
                    Graver une destination dans un preset collerait un groupe à un SON — or le
                    même son sert dans deux groupes. */''}
              ${(svc && (svc.spaces || []).length) ? (() => {
                const cur = svc.space;
                return html`<div class="svc-row"><b>Takes go to</b>
                  <div class="src-chips">
                    ${/* Pas de « none » (retour 2026-09-07) : on choisit le groupe qu'on
                          veut. Re-taper la chip ACTIVE la désarme — les prises repartent alors
                          sans tag et attendent sur le disque, ce qui reste vrai et ne perd rien,
                          mais ça ne mérite pas un bouton permanent dans la rangée. */''}
                    ${svc.spaces.map(b => { const on = cur && cur.id === b.id;
                      return html`<button class=${cls('p-chip', on && 'on')}
                        title=${on ? 'takes are tagged ' + (b.name || b.id) + ' — tap again to record without a space'
                                   : 'takes recorded from now on are tagged ' + (b.name || b.id)
                                     + ' — each take keeps its own tag, changing this never moves a past take'}
                        onClick=${() => svc.onSpace(on ? null : b.id)}>${b.kind === 'personal' ? '👤 ' : '◈ '}${esc(b.name || b.id)}</button>`; })}

                  </div>
                  <span class="tr-lock" title="the machine mode sets this on its own — Home to your own space, Rehearsal and Gig to the band. Changing it here holds until the next mode switch.">
                    ⛓ set by the mode</span>
                </div>`;
              })() : ''}
              ${/* LE DÉCOMPTE (2026-09-21) : une prise lancée au pied part TOUJOURS du début du
                    morceau — sans décompte on n'a le temps de poser ni le pied ni les mains. Le click
                    est forcé audible le temps du décompte, puis rend la main. */''}
              <div class="svc-row"><b>Count-in</b>
                <div class="src-chips">
                  ${[[0, 'Off'], [1, '1 bar'], [2, '2 bars']].map(([k, lb]) => html`
                    <button class=${cls('p-chip', ((svc && svc.recSrc && svc.recSrc.count_in) || 0) === k && 'on')}
                      title=${k ? 'the click counts ' + lb + ' before a take started from the pedalboard — the take and the backing then start from the top'
                                : 'a take started from the pedalboard starts at once, from the top'}
                      onClick=${() => !locked && svc && svc.onRecSrc && svc.onRecSrc('count_in', k)}>${lb}</button>`)}
                </div>
              </div>
              <div class="svc-row"><b>Transcribe takes</b>
                <div class="src-chips">
                  ${(() => {
                    const cur = (svc && svc.recSrc && svc.recSrc.transcribe) || 'manual';
                    const hasDI = recMode === 'tracks_di';
                    // « Starred » (transcrire ce qu'on a étoilé) a été RETIRÉ le 2026-09-08  : la
                    // notation des prises n'existe pas, un bouton grisé promettait dans le vide.
                    return [['manual', 'Manual'], ['auto', 'Automatic']].map(([k, lb]) => html`
                      <button class=${cls('p-chip', cur === k && 'on')}
                        title=${k === 'auto'
                            ? 'every take is transcribed as soon as it is closed — background, lowest priority'
                            : 'transcribe from the take, in Library ▸ Tracks ▸ Recordings'}
                        onClick=${() => !locked && svc && svc.onRecSrc && svc.onRecSrc('transcribe', k)}>${lb}</button>`);
                  })()}
                </div>
                ${(svc && svc.recSrc && svc.recSrc.transcribe) === 'auto' && recMode !== 'tracks_di'
                  ? html`<span class="tr-lock warn" title="a take without DI has nothing clean to transcribe">
                      ⛓ needs Multi + DI</span>`
                  : recMode === 'tracks_di'
                  ? html`<span class="tr-lock" title="the DI is the clean signal the engine reads">⛓ Multi + DI ✓</span>`
                  : ''}
              </div>
              <p class="muted">${recMode === 'mix'
                ? 'One stereo file: the mix you hear from the ticked inputs — backing track & looper always included.'
                : recMode === 'tracks'
                ? 'One file per track (guitar, voice, keys, looper…) in a per-take folder — remix later. The backing track is NOT duplicated as a separate file: you already own it, and the take links back to the song.'
                : ((!(svc && svc.recSrc) || svc.recSrc.mix !== false)
                  ? 'One file per track, plus the RAW DI of each physical input (pre-FX), plus the full stereo mix — everything, in a per-take folder. '
                  : 'One file per track, plus the RAW DI of each physical input (pre-FX) — no stereo mix. ')
                  + 'The DI is the clean signal used to transcribe what you played into scores & tabs. The backing track is NOT duplicated as a separate file: you already own it, and the take links back to the song.'}
                Takes land in Library ▸ Tracks ▸ Recordings. Long-press the tile to put it on a footswitch (scene row allowed).
                ${(svc && svc.recSrc && svc.recSrc.transcribe) === 'auto' ? html`<b> Automatic transcription is on:
                  every closed take is turned into a score in the background, at the lowest priority — never while you
                  play. MIDI sources (keys, pads, drums) are exact; audio is a draft.</b>` : ''}</p>`; })();
  return html`<div class="rec-panel">${panel}</div>`;
}


// ── LE PANNEAU CLICK : SON VOLUME (2026-09-30 : « je n'ai aucun réglage de level dans le bloc Click ») ────
// Le niveau existait (catalogue, golem_click.jsfx, config/click.json à −12 dB) sans aucun écran pour le changer :
// le tiroir tombait sur « no exposed settings ». UN réglage pour TOUS les clicks — métronome, décompte du Rec,
// click d'une prise de riff — écrit tout de suite (POST /api/click/level) et gardé dans le bloc pour le save.
export function ClickPanel({ params, onParam }) {
  const [lv, setLv] = useState(params.level != null ? Number(params.level) : -12);
  const [said, setSaid] = useState('');
  // le niveau JOUÉ est le global (config/click.json) : la copie du bloc pouvait être vieille — le curseur affichait 0 dB
  // pendant que le click jouait à -12 (vu le 2026-10-18)
  useEffect(() => { fetch('/api/click').then(r => r.json()).then(c => { if (c && c.level != null) setLv(Math.round(Number(c.level))); }).catch(() => null); }, []);
  const commit = v => {
    onParam && onParam('level', v);
    fetch('/api/click/level', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: v }) }).then(r => r.json())
      .then(r => setSaid(r.ok ? '✓ ' + r.level + ' dB' : '✗ ' + (r.error || 'not saved'))).catch(() => setSaid('✗ not saved'));
  };
  return html`
    <div class="svc-row"><b>Level</b>
      <div class="click-level">
        <input type="range" min="-60" max="6" step="1" value=${lv} aria-label="click level"
          onInput=${e => setLv(Number(e.target.value))} onChange=${e => commit(Number(e.target.value))} />
        <b class="click-db">${lv > 0 ? '+' : ''}${lv} dB</b>
        ${[-18, -12, -6, 0].map(v => html`<button class=${cls('p-chip', lv === v && 'on')} onClick=${() => { setLv(v); commit(v); }}>${v} dB</button>`)}
        <span class="muted">${said}</span>
      </div>
    </div>
    <p class="muted">One level for every click: the metronome, the Rec count-in and the click of a riff take.
      The count-in plays a little louder so you hear the « 1 » coming.</p>`;
}


// ── LE PANNEAU COMPO (docs/compo.md §2, §4, §10 — FIGÉ 2026-09-17) ────────────────────────────
// Config GLOBALE (config/compo.json), éditée ici dans block.params et extraite au save comme le Rec.
// Quatre lignes, rien d'autre : les lanes de chaque personne (une bascule par lane — ce que COMPO
// capture quand CETTE personne tape), « keep the last », la transcription, à qui appartient le
// switch du pédalier du rack. La destination n'est pas un réglage : c'est l'espace courant.
export function CompoPanel({ svc, params, onParam }) {
  const persons = (svc && svc.compoPersons) || {};
  const names = (svc && svc.personNames) || {};
  const targets = (svc && svc.compoTargets) || {};
  const pids = Object.keys(persons);
  const offOf = pid => new Set((((params.persons || {})[pid] || {}).off) || []);
  const setOff = (pid, laneId, off) => {
    const cur = offOf(pid); if (off) cur.add(laneId); else cur.delete(laneId);
    const next = { ...(params.persons || {}) };
    if (cur.size) next[pid] = { off: [...cur] }; else delete next[pid];
    onParam && onParam('persons', next);
  };
  const footP = params.foot_person || null;
  const space = svc && svc.space;
  // ── LA COLONNE REC (2026-09-30, solution A) : Riff enregistre PAR le Rec — ses réglages décident de ce
  // qu'un riff peut capter. On les montre ici, en LECTURE SEULE, avec un verdict par ligne, et toute la colonne
  // est UN bouton qui mène au tiroir du Rec (écran tactile : pas de survol, un tap suffit). Rien n'y est éditable :
  // une seule porte pour écrire le Rec, son tiroir.
  const rc = (svc && svc.recCfg) || {};
  const recMode = rc.rec_mode || 'mix';
  const inputsUsed = [...new Set(pids.flatMap(pid => (persons[pid] || []).filter(L => !offOf(pid).has(L.id)).map(L => L.input)).filter(Boolean))];
  const recOn = k => rc[k] !== false;
  const fmtOk = recMode !== 'mix';
  const rows = [
    { k: 'Recorder', v: (svc && svc.recAllowed) === false ? 'off in ' + ((svc && svc.modeName) || 'this mode') : 'on in ' + ((svc && svc.modeName) || 'this mode'),
      ok: (svc && svc.recAllowed) !== false, why: (svc && svc.recAllowed) === false ? 'a riff is a take — the mode must allow the recorder' : '' },
    { k: 'Format', v: recMode === 'mix' ? 'Mix' : recMode === 'tracks' ? 'Multitrack' : 'Multitrack + DI',
      ok: fmtOk, why: fmtOk ? (recMode === 'tracks' ? 'no DI: no score' : '') : 'a riff needs one track per input' },
    // la prise d'un riff enregistre les entrées de SES lanes, quelles que soient les cases du Rec (store.rec_sources force)
    ...inputsUsed.map(inp => ({ k: inp === 'usb' ? 'USB' : 'IN ' + inp, v: 'recorded', ok: true,
      why: recOn(inp === 'usb' ? 'usb' : 'in' + inp) ? '' : 'for riffs — the Rec block leaves it out of other takes' })),
    { k: 'Count-in', v: rc.count_in ? rc.count_in + ' bar' + (rc.count_in > 1 ? 's' : '') : 'off', ok: true },
  ];
  return html`<div class="compo-cols">
    <button class="compo-rec" onClick=${() => svc && svc.onOpenRec && svc.onOpenRec()}
      title="Riff records through the Rec block — tap to set it up">
      <span class="cr-hd">REC <small>read-only</small></span>
      ${rows.map(r => html`<span class=${cls('cr-row', !r.ok && 'ko')}>
        <em>${r.k}</em><b>${r.v}</b><i>${r.ok ? (r.why ? '!' : '✓') : '✗'}</i>
        ${r.why ? html`<small>${r.why}</small>` : ''}</span>`)}
      ${!inputsUsed.length ? html`<span class="cr-row"><small>no input carries a person yet</small></span>` : ''}
      <span class="cr-go">Set up Rec ›</span>
    </button>
    <div class="compo-own">
    <div class="svc-row"><b>What Riff records</b><em>— per person: the lanes on their inputs, tap to leave one out</em></div>
    ${pids.length ? pids.map(pid => html`
      <div class="svc-row compo-person">
        <span class="compo-who" title=${'inputs of ' + (names[pid] || pid) + ' on this card'}>${esc(names[pid] || pid)}</span>
        <div class="src-chips">
          ${persons[pid].map(L => { const on = !offOf(pid).has(L.id);
            return html`<button class=${cls('p-chip', on && 'on')}
              title=${on ? L.name + ' is captured when ' + (names[pid] || pid) + ' taps — tap to leave it out'
                         : L.name + ' is left out — tap to capture it'}
              onClick=${() => setOff(pid, L.id, on)}>${esc(L.name)}</button>`; })}
        </div>
        ${targets[pid] ? html`<small class="compo-target" title="armed from golem.fm (Follow Golem) — the next tap writes into this song">→ ${esc(targets[pid].title || targets[pid].id)} · ${targets[pid].mode}</small>` : ''}
      </div>`)
      : html`<p class="muted">No one is set on the inputs of this card — assign people in Settings ▸ Mode (✎ inputs). Without a person, a tap has no author and records nothing.</p>`}
    ${/* « Keep the last » (15/30/60 s) est RETIRÉ de l'écran tant que la rétro-capture n'existe pas (docs/compo.md
          §11) : un réglage qui n'agit pas est pire qu'un réglage absent. La valeur reste dans config/compo.json. */''}
    <div class="svc-row"><b>Transcribe on the rack</b>
      <div class="src-chips">
        ${[[true, 'On'], [false, 'Off']].map(([v, lb]) => html`<button class=${cls('p-chip', (params.transcribe !== false) === v && 'on')}
          title=${v ? 'a MusicXML tab (from the DI) travels with the riff — the composer opens it already written' : 'audio only'}
          onClick=${() => onParam && onParam('transcribe', v)}>${lb}</button>`)}
      </div>
    </div>
    <div class="svc-row"><b>Rack footswitch belongs to</b>
      <div class="src-chips">
        ${pids.map(pid => html`<button class=${cls('p-chip', (footP ? footP === pid : pid === pids[0]) && 'on')}
          title="who is the author when the rack pedalboard taps Riff (a phone always taps as its own person)"
          onClick=${() => onParam && onParam('foot_person', pid)}>${esc(names[pid] || pid)}</button>`)}
        ${!pids.length ? html`<span class="muted">— nobody yet</span>` : ''}
      </div>
    </div>
    <p class="muted">Tap = start, tap = stop. Riffs go to ${space ? html`<b>${esc(space.name || space.id)}</b>` : 'the current space (pair with golem.fm first)'} 20 s after they end — Drop on /live before that.</p>
    </div>
  </div>`;
}

// SPDX-License-Identifier: GPL-3.0-or-later
// LE PLEIN ÉCRAN DES TÉLÉPHONES ET TABLETTES (2026-11-26 : « comment être en plein écran sur Android ? »). Le golem est
// servi en http : Chrome n'y installe pas d'app (il faut https), donc le manifeste ne sert pas. L'API Fullscreen, elle,
// marche en http, après un tap : elle cache la barre d'adresse ET la barre d'état. Pas d'API sur iPhone (Safari).
//
// LE PREMIER TAP (Settings ▸ System ▸ Display ▸ Full screen, vrai par défaut, bridge/display.py) : le navigateur refuse
// d'entrer en plein écran sans geste — au chargement, impossible. On pose donc un voile transparent sur toute la page :
// le premier tap le touche, lui seul, et met l'app en plein écran. Il ne déclenche RIEN d'autre (un tap pour « réveiller »
// l'écran ne doit pas basculer un stomp). Le voile couvre aussi les iframes (affichage tablette, Control couché), qu'un
// écouteur sur la page ne verrait pas. Il revient après un rechargement ou une sortie par le système (geste retour) ; pas
// après « Leave full screen » : c'est un choix, on ne le reprend pas au tap suivant.
// Jamais sur l'écran local du rack (sa fenêtre l'est déjà), jamais dans une iframe (la page hôte s'en charge), jamais
// à la souris (un portable qui ouvre l'app n'a pas à basculer au premier clic), jamais dans un navigateur déjà plein cadre.
import { useState, useEffect } from './lib.js';
import { isLocalHost } from './anim-stepper.mjs';

const el = () => document.documentElement;
export const canFullscreen = () => !!(el().requestFullscreen || el().webkitRequestFullscreen);
const current = () => document.fullscreenElement || document.webkitFullscreenElement || null;

let _userLeft = false;       // sorti par notre bouton : on ne réarme pas avant un rechargement
let _failed = false;         // le navigateur a refusé : on ne mange pas les taps suivants pour rien
let _pref = null;            // le réglage du rack (null = pas encore lu)
let _veil = null;
let _started = false;

function enter() {
  const f = el().requestFullscreen || el().webkitRequestFullscreen;
  const p = f.call(el(), { navigationUI: 'hide' });
  return p && p.catch ? p.catch(e => { _failed = true; console.warn('[fullscreen] refusé :', e); sync(); }) : p;
}

export function toggleFullscreen() {
  if (current()) { _userLeft = true; return (document.exitFullscreen || document.webkitExitFullscreen).call(document); }
  _userLeft = false;
  return enter();
}

export function useFullscreen() {
  const [on, setOn] = useState(!!current());
  useEffect(() => {
    const f = () => setOn(!!current());
    document.addEventListener('fullscreenchange', f); document.addEventListener('webkitfullscreenchange', f);
    return () => { document.removeEventListener('fullscreenchange', f); document.removeEventListener('webkitfullscreenchange', f); };
  }, []);
  return on;
}

// le navigateur couvre déjà tout l'écran (mode kiosque d'une tablette) : rien à gagner, un tap à perdre
const kiosk = () => Math.abs(screen.width - innerWidth) < 2 && Math.abs(screen.height - innerHeight) < 2;

function sync() {
  const want = _pref === true && !_userLeft && !_failed && !current() && !kiosk();
  if (want && !_veil && document.body) {
    _veil = document.createElement('div');
    _veil.className = 'fs-veil';
    _veil.setAttribute('aria-hidden', 'true');
    _veil.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:transparent;touch-action:none;-webkit-tap-highlight-color:transparent';
    // ⚠ PAS de preventDefault sur touchstart/pointerdown : il annule le `click` d'un doigt, et le voile ne partait jamais.
    // Rien d'autre ne reçoit le tap de toute façon : le voile est au-dessus de tout, c'est lui la cible.
    const stop = e => e.stopPropagation();
    _veil.addEventListener('pointerdown', stop);
    _veil.addEventListener('touchstart', stop, { passive: true });
    _veil.addEventListener('click', e => { e.preventDefault(); stop(e); drop(); enter(); });   // click : le geste que le navigateur accepte
    document.body.appendChild(_veil);
  } else if (!want && _veil) drop();
}
function drop() { if (_veil) { _veil.remove(); _veil = null; } }

// le réglage arrive par l'état diffusé (main.js, mobile.js) : appliqué sans recharger
export function setFullscreenPref(v) {
  if (typeof v !== 'boolean' || v === _pref) return;
  _pref = v; if (_started) sync();
}

export function startAutoFullscreen() {
  if (_started || window.top !== window || isLocalHost(location.hostname)) return;
  if (!canFullscreen() || !matchMedia('(pointer: coarse)').matches) return;
  _started = true;
  document.addEventListener('fullscreenchange', sync); document.addEventListener('webkitfullscreenchange', sync);
  addEventListener('resize', sync);
  if (_pref === null) fetch('/api/system/display').then(r => r.json()).then(d => setFullscreenPref(d.fullscreen !== false))
    .catch(() => setFullscreenPref(true)).finally(sync);
  else sync();
}

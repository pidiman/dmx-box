"use strict";
// Virtuálne svetlá: kreslí PartyBar4, moving head, Belku a dym z DMX rámca (/ws/dmx),
// plus všetky svetlá pridané v appke (podľa funkcií ich kanálov) – na druhej rampe.

const cv = document.getElementById("c");
const g = cv.getContext("2d");
let W = 0, H = 0, DPR = 1;
let FX = {};                 // kanálové mapy z /api/fixtures
let dmx = new Array(512).fill(0);
let bpm = 120, silent = true;
let haze = 0;                // 0–1 hustota dymu v miestnosti
let puffs = [];

function resize() {
  DPR = Math.min(2, window.devicePixelRatio || 1);
  W = cv.width = Math.floor(innerWidth * DPR);
  H = cv.height = Math.floor(innerHeight * DPR);
}
addEventListener("resize", resize);
resize();

// --- DMX helpers ----------------------------------------------------------------
const ch = (fx, name) => {
  const f = FX[fx];
  if (!f || f.channels[name] == null) return 0;
  return dmx[f.start + f.channels[name] - 2] || 0;
};
const rgba = (r, gg, b, a) => `rgba(${r | 0},${gg | 0},${b | 0},${a})`;
function hsv(h, s = 1, v = 1) {
  const i = Math.floor(h * 6), f = h * 6 - i, p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  const m = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][((i % 6) + 6) % 6];
  return m.map((x) => x * 255);
}
// RGBW (0–255) → RGB, biela pridáva jas
const rgbw = (r, gg, b, w) => [Math.min(255, r + w), Math.min(255, gg + w), Math.min(255, b + w)];
// strobo: v rytme `hz` svieti krátky záblesk
const blink = (t, hz) => ((t * hz) % 1) < 0.35;

// --- kreslenie primitív ---------------------------------------------------------------
function glow(x, y, r, col, a) {
  if (a <= 0.01) return;
  const gr = g.createRadialGradient(x, y, 0, x, y, r);
  gr.addColorStop(0, rgba(...col, a));
  gr.addColorStop(0.4, rgba(...col, a * 0.35));
  gr.addColorStop(1, rgba(...col, 0));
  g.fillStyle = gr;
  g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
}

function beam(x, y, ex, ey, w0, w1, col, a) {
  if (a <= 0.01) return;
  a = Math.min(1, a * (0.75 + haze * 0.9));
  const ang = Math.atan2(ey - y, ex - x) + Math.PI / 2;
  const dx = Math.cos(ang), dy = Math.sin(ang);
  const gr = g.createLinearGradient(x, y, ex, ey);
  gr.addColorStop(0, rgba(...col, a * 0.55));
  gr.addColorStop(1, rgba(...col, a * 0.06));
  g.fillStyle = gr;
  g.beginPath();
  g.moveTo(x - dx * w0, y - dy * w0);
  g.lineTo(x + dx * w0, y + dy * w0);
  g.lineTo(ex + dx * w1, ey + dy * w1);
  g.lineTo(ex - dx * w1, ey - dy * w1);
  g.closePath(); g.fill();
}

function lamp(x, y, r, col, a) {
  g.fillStyle = "#1b1b24"; g.beginPath(); g.arc(x, y, r * 1.25, 0, Math.PI * 2); g.fill();
  g.fillStyle = a > 0.02 ? rgba(...col.map((c) => c * 0.4 + 60 * a), 1) : "#26262f";
  g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
  glow(x, y, r * 4, col, a);
}

// --- scéna ---------------------------------------------------------------------
function room() {
  const floor = H * 0.78;
  const bg = g.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#07070c"); bg.addColorStop(0.78, "#0d0d16"); bg.addColorStop(1, "#050508");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  g.strokeStyle = "#1a1a26"; g.lineWidth = 2 * DPR;
  g.beginPath(); g.moveTo(0, floor); g.lineTo(W, floor); g.stroke();
  // truss
  g.fillStyle = "#14141c"; g.fillRect(W * 0.05, H * 0.1 - 6 * DPR, W * 0.9, 12 * DPR);
  return floor;
}

// MAX PartyBar4: celá lišta jedna farba; makrá kanála 1 simulované
function drawParbar(t, floor) {
  if (!FX.parbar) return;
  const macro = ch("parbar", "macro"), speed = ch("parbar", "speed") / 255;
  const dim = ch("parbar", "dimmer") / 255;
  let col = rgbw(ch("parbar", "red"), ch("parbar", "green"), ch("parbar", "blue"), ch("parbar", "white"));
  let a = dim;
  const cm = ch("parbar", "color_macro") / 255;
  if (macro >= 201) { col = [255, 255, 255]; a = blink(t, 2 + speed * 18) ? 1 : 0; }
  else if (macro >= 151) col = hsv(Math.floor(t * bpm / 60) * 0.17 % 1);           // sound
  else if (macro >= 101) col = hsv((t * (0.05 + speed * 0.5)) % 1);                 // fade
  else if (macro >= 51) col = hsv(Math.floor(t * (0.5 + speed * 6)) * 0.23 % 1);   // jump
  else if (macro >= 11) col = hsv(cm);                                              // static
  const x0 = W * 0.1, step = W * 0.06, y = H * 0.1 + 18 * DPR;
  g.fillStyle = "#16161e"; g.fillRect(x0 - step * 0.6, y - 14 * DPR, step * 4.2, 28 * DPR);
  for (let i = 0; i < 4; i++) {
    const x = x0 + i * step;
    if (a > 0.01) beam(x, y, x + (i - 1.5) * W * 0.035, floor, 8 * DPR, W * 0.05, col, a * 0.8);
    lamp(x, y, 10 * DPR, col, a);
    if (a > 0.01) glow(x + (i - 1.5) * W * 0.035, floor, W * 0.07, col, a * 0.35);
  }
  label("PartyBar4", x0 + step * 1.5, y + 34 * DPR);
}

const HEAD_WHEEL = [[0, [255, 255, 255]], [10, [255, 30, 30]], [20, [255, 230, 0]], [30, [40, 60, 255]],
  [40, [30, 255, 60]], [50, [255, 140, 0]], [60, [255, 60, 200]], [70, [0, 230, 255]]];

function headColor(v, t) {
  if (v >= 140) return hsv((t * (0.1 + (v - 140) / 115)) % 1);
  let best = HEAD_WHEEL[0];
  for (const w of HEAD_WHEEL) if (Math.abs(w[0] - v) < Math.abs(best[0] - v)) best = w;
  if (v >= 80) { // polovičné farby
    const i = Math.min(7, Math.floor((v - 80) / 8));
    return HEAD_WHEEL[i][1].map((c, k) => (c + HEAD_WHEEL[(i + 1) % 8][1][k]) / 2);
  }
  return best[1];
}

// Fractal Mini LED Gobo Spot
// zotrvačnosť motora: skutočná hlava prejde celý pan asi za 1,6 s, tilt za ~1 s
// (pt_speed 255 = pomaly); viz ukazuje, kam hlava naozaj stihne dôjsť, nie len cieľ z DMX
const HEAD = { pan: 0.5, tilt: 0.5 };
const PAN_RATE = 0.62, TILT_RATE = 1.0;
function drawHead(t, floor, dt = 0.016) {
  if (!FX.movinghead) return;
  const onFloor = FX.movinghead.mount === "floor";       // stojí na zemi: lúč ide hore, DMX pan/tilt je otočený
  const ceil = H * 0.1 + 8 * DPR;
  const x = W * 0.5, y = onFloor ? floor - 34 * DPR : H * 0.1 + 26 * DPR;
  const slow = 1 - 0.85 * (ch("movinghead", "pt_speed") / 255);
  const step = (cur, target, rate) => cur + Math.max(-rate * slow * dt, Math.min(rate * slow * dt, target - cur));
  HEAD.pan = step(HEAD.pan, ch("movinghead", "pan") / 255, PAN_RATE);
  HEAD.tilt = step(HEAD.tilt, ch("movinghead", "tilt") / 255, TILT_RATE);
  const pan = onFloor ? 1 - HEAD.pan : HEAD.pan, tilt = onFloor ? 1 - HEAD.tilt : HEAD.tilt;
  let a = ch("movinghead", "dimmer") / 255;
  const st = ch("movinghead", "strobe");
  if (st > 0 && a > 0) a = blink(t, 1 + (st / 255) * 18) ? a : 0;
  const col = headColor(ch("movinghead", "color"), t);
  // pan → vodorovný smer, tilt → ako ďaleko do miestnosti/na stenu
  const ang = (pan - 0.5) * Math.PI * 1.15;
  const reach = onFloor ? y - ceil : floor - y;
  const ex = x + Math.sin(ang) * reach * (0.6 + tilt * 1.1);
  const ey = onFloor ? Math.max(ceil, y - reach * (0.25 + 0.75 * tilt)) : Math.min(floor, y + reach * (0.25 + 0.75 * tilt));
  const hit = onFloor ? ey <= ceil + 1 : ey >= floor - 1;  // spot dopadá na strop/podlahu (sploštený)
  const ly = onFloor ? y - 10 * DPR : y + 10 * DPR;        // ústie lúča
  const gv = ch("movinghead", "gobo");
  // telo hlavy (podstavec hore pri zavesenej, dole pri stojacej)
  g.fillStyle = "#1d1d27"; g.fillRect(x - 22 * DPR, onFloor ? y + 6 * DPR : y - 20 * DPR, 44 * DPR, 14 * DPR);
  g.save(); g.translate(x, onFloor ? y - 6 * DPR : y + 6 * DPR); g.rotate(Math.atan2(ex - x, ey - y) * -1);
  g.fillStyle = "#24242f"; g.fillRect(-14 * DPR, onFloor ? -20 * DPR : -10 * DPR, 28 * DPR, 30 * DPR);
  g.restore();
  // LED krúžok
  const ring = ch("movinghead", "led_ring");
  if (ring > 0) for (let i = 0; i < 12; i++) {
    const aa = (i / 12) * Math.PI * 2 + t * 2;
    glow(x + Math.cos(aa) * 26 * DPR, ly + Math.sin(aa) * 10 * DPR, 7 * DPR, hsv((i / 12 + t * 0.3) % 1), 0.8);
  }
  const name = onFloor ? "Moving head (na zemi)" : "Moving head";
  const lblY = onFloor ? y + 32 * DPR : y + 42 * DPR;
  if (a <= 0.01) { label(name, x, lblY); return; }
  beam(x, ly, ex, ey, 5 * DPR, W * 0.03, col, a);
  // spot s gobom
  const r = W * 0.045;
  g.save(); g.translate(ex, ey); g.scale(1, hit ? 0.35 : 0.8);
  glow(0, 0, r * 1.8, col, a * 0.6);
  g.fillStyle = rgba(...col, a * 0.9);
  if (gv < 8) { g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.fill(); }
  else {
    const idx = gv >= 128 ? 4 : Math.max(1, Math.min(7, Math.floor((gv >= 64 ? gv - 64 : gv) / 8)));
    let rot = gv >= 128 ? t * (1 + (gv - 128) / 40) : 0;
    if (gv >= 64 && gv < 128) rot = Math.sin(t * 20) * 0.25;            // trasenie
    g.rotate(rot);
    const n = 3 + idx;                                                    // počet lúčov gobo vzoru
    for (let i = 0; i < n; i++) {
      const aa = (i / n) * Math.PI * 2;
      g.beginPath(); g.arc(Math.cos(aa) * r * 0.55, Math.sin(aa) * r * 0.55, r * (0.18 + idx * 0.02), 0, Math.PI * 2); g.fill();
    }
  }
  g.restore();
  lamp(x, ly, 6 * DPR, col, a);
  label(name, x, lblY);
}

// Light4Me Belka: 2 PAR, derby, laser, strobo/UV modul
let laserDots = [], laserT = 0;
function drawBelka(t, floor) {
  if (!FX.belka) return;
  const cx = W * 0.8, y = H * 0.1 + 18 * DPR, half = W * 0.11;
  g.fillStyle = "#16161e"; g.fillRect(cx - half, y - 12 * DPR, half * 2, 24 * DPR);

  // strobo / UV
  const su = ch("belka", "strobe_uv") / 255, ss = ch("belka", "strobe_speed");
  if (su > 0) {
    if (ss === 0) {           // stály UV
      g.fillStyle = rgba(120, 40, 255, 0.18 * su); g.fillRect(0, 0, W, H);
      lamp(cx, y + 22 * DPR, 7 * DPR, [150, 60, 255], su);
    } else if (blink(t, 1 + (ss / 255) * 22)) {
      g.fillStyle = rgba(255, 255, 255, 0.55 * su); g.fillRect(0, 0, W, H);
      lamp(cx, y + 22 * DPR, 7 * DPR, [255, 255, 255], su);
    }
  }

  // PAR
  const par = rgbw(ch("belka", "par_red"), ch("belka", "par_green"), ch("belka", "par_blue"), ch("belka", "par_white"));
  const pa = Math.max(...par) / 255;
  for (const dx of [-half * 0.75, half * 0.75]) {
    const x = cx + dx, ex = x + dx * 0.35;
    if (pa > 0.01) { beam(x, y, ex, floor, 9 * DPR, W * 0.06, par, pa * 0.85); glow(ex, floor, W * 0.08, par, pa * 0.35); }
    lamp(x, y, 11 * DPR, par, pa);
  }

  // derby: farebné lúče, rotácia podľa motora
  const dr = [ch("belka", "derby_red"), ch("belka", "derby_green"), ch("belka", "derby_blue"), ch("belka", "derby_white")];
  const da = Math.max(...dr) / 255;
  const motor = ch("belka", "derby_motor") / 255;
  const cols = [[255, 40, 40], [40, 255, 60], [50, 80, 255], [255, 255, 255]].filter((_, i) => dr[i] > 8);
  const dx0 = cx - half * 0.3;
  if (da > 0.01 && cols.length) {
    const rot = t * motor * 2.5;
    for (let i = 0; i < 14; i++) {
      const aa = Math.sin(rot + i * 0.9) * 0.9 + (i - 7) * 0.08;
      const ex = dx0 + Math.sin(aa) * (floor - y) * 0.55, ey = floor;
      const c = cols[i % cols.length];
      beam(dx0, y, ex, ey, 1.5 * DPR, 6 * DPR, c, da * 0.9);
      glow(ex, ey, 10 * DPR, c, da * 0.7);
    }
  }
  lamp(dx0, y, 8 * DPR, cols[0] || [40, 40, 40], da);

  // laser
  const lv = ch("belka", "laser");
  const lr = FX.belka.ranges.laser || {};
  const inR = (k) => lr[k] && lv >= lr[k][0] && lv <= lr[k][1];
  const red = inR("red") || inR("both"), green = inR("green") || inR("both");
  const lx = cx + half * 0.3;
  if (red || green) {
    if (t - laserT > 0.12) {
      laserT = t;
      laserDots = Array.from({ length: 70 }, () => [Math.random() * W, H * 0.25 + Math.random() * (floor - H * 0.25), Math.random() < 0.5]);
    }
    for (const [x, yy, isRed] of laserDots) {
      const c = (isRed && red) || !green ? [255, 20, 20] : [30, 255, 60];
      if ((isRed && !red) || (!isRed && !green)) continue;
      g.fillStyle = rgba(...c, 0.9); g.fillRect(x, yy, 3 * DPR, 3 * DPR);
      glow(x, yy, 6 * DPR, c, 0.4);
    }
    lamp(lx, y, 5 * DPR, red ? [255, 30, 30] : [30, 255, 60], 1);
  } else lamp(lx, y, 5 * DPR, [40, 40, 40], 0);

  label("Belka", cx, y + 34 * DPR);
}

// U'King dymostroj na zemi + opar, v ktorom sú lúče výraznejšie
function drawFog(t, floor, dt) {
  if (!FX.fog) return;
  const on = ch("fog", "fog") > 10;
  const col = [ch("fog", "red"), ch("fog", "green"), ch("fog", "blue")];
  const lit = Math.max(...col) / 255;
  const x = W * 0.3, y = floor - 18 * DPR;
  haze = Math.max(0, Math.min(1, haze + (on ? dt * 0.25 : -dt * 0.015)));
  if (on && puffs.length < 160) for (let i = 0; i < 4; i++)
    puffs.push({ x: x + 30 * DPR, y: y, vx: (80 + Math.random() * 140) * DPR, vy: -(Math.random() * 30) * DPR, r: 8 * DPR, a: 0.5 });
  g.globalCompositeOperation = "source-over";
  for (const p of puffs) {
    p.x += p.vx * dt; p.y += p.vy * dt; p.vx *= 0.985; p.r += 26 * DPR * dt; p.a -= 0.12 * dt;
    if (p.a > 0) glow(p.x, p.y, p.r, lit > 0.05 ? col.map((c) => 90 + c * 0.6) : [140, 140, 155], p.a * 0.35);
  }
  puffs = puffs.filter((p) => p.a > 0);
  if (haze > 0.01) { g.fillStyle = rgba(150, 150, 170, haze * 0.12); g.fillRect(0, 0, W, floor); }
  // telo dymostroja + LED
  g.fillStyle = "#1c1c26"; g.fillRect(x - 34 * DPR, y - 14 * DPR, 64 * DPR, 30 * DPR);
  for (let i = 0; i < 6; i++) lamp(x - 24 * DPR + i * 9 * DPR, y - 18 * DPR, 2.5 * DPR, col, lit);
  label(on ? "Dym ●" : "Dym", x, y + 30 * DPR);
  g.globalCompositeOperation = "lighter";
}

// --- svetlá pridané v appke: kreslené podľa funkcií kanálov ---------------------------------------
const fnv = (key, fn) => {                       // hodnota prvého kanála s danou funkciou
  const f = FX[key];
  for (const [n, k] of Object.entries(f.fns || {})) if (k === fn) return ch(key, n);
  return null;
};
const hasFn = (key, fn) => Object.values(FX[key].fns || {}).includes(fn);
const POS_X = { left: 0.22, center: 0.5, right: 0.78 };

function genericSlots() {
  const keys = Object.keys(FX).filter((k) => !FX[k].known);
  const groups = {};
  for (const k of keys) (groups[FX[k].position || "center"] ||= []).push(k);
  const out = [];
  for (const [pos, ks] of Object.entries(groups))
    ks.forEach((k, i) => out.push([k, W * ((POS_X[pos] ?? 0.5) + (i - (ks.length - 1) / 2) * 0.1)]));
  return out;
}

function drawGenericLaser(key, x, y, t, floor) {
  const f = FX[key];
  const mode = fnv(key, "laser") ?? fnv(key, "macro") ?? 0;
  const on = mode >= 64;                         // typicky 0–63 = vypnutý, vyššie = ručný/auto/zvuk
  const effects = Object.entries(f.fns).filter(([, k]) => k === "effect").map(([n]) => ch(key, n));
  const pat = effects[0] || 0;
  const auto = mode >= 128;
  lamp(x, y, 6 * DPR, on ? [60, 255, 90] : [40, 40, 40], on ? 1 : 0);
  if (!on) return;
  const cx = x + Math.sin(t * (auto ? 0.7 : 0.25)) * W * 0.12, cy = H * 0.5;
  const sides = 3 + Math.floor((auto ? t * bpm / 240 : pat / 16)) % 6;
  const r = H * 0.22 * (0.6 + 0.4 * Math.sin(t * (auto ? 1.3 : 0.4)));
  const rot = t * (auto ? 1.5 : 0.5);
  const hueBase = auto ? (t * 0.15) % 1 : (pat / 255);
  for (let i = 0; i < sides; i++) {
    const a0 = rot + (i / sides) * Math.PI * 2, a1 = rot + ((i + 1) / sides) * Math.PI * 2;
    const col = hsv((hueBase + i / sides * 0.33) % 1);
    const p0 = [cx + Math.cos(a0) * r, cy + Math.sin(a0) * r], p1 = [cx + Math.cos(a1) * r, cy + Math.sin(a1) * r];
    g.strokeStyle = rgba(...col, 0.95); g.lineWidth = 2 * DPR;
    g.beginPath(); g.moveTo(...p0); g.lineTo(...p1); g.stroke();
    g.strokeStyle = rgba(...col, 0.12 + haze * 0.25); g.lineWidth = 1 * DPR;
    g.beginPath(); g.moveTo(x, y); g.lineTo(...p0); g.stroke();
    glow(...p0, 6 * DPR, col, 0.6);
  }
}

function drawGeneric(t, floor) {
  const slots = genericSlots();
  if (!slots.length) return;
  const y = H * 0.24;
  g.globalCompositeOperation = "source-over";
  g.fillStyle = "#14141c"; g.fillRect(W * 0.1, y - 22 * DPR, W * 0.8, 8 * DPR);
  g.globalCompositeOperation = "lighter";
  for (const [key, x] of slots) {
    const f = FX[key];
    const name = `${f.label || key}${f.name ? " · " + f.name : ""}`;
    g.globalCompositeOperation = "source-over";
    g.fillStyle = "#1a1a24"; g.fillRect(x - 18 * DPR, y - 14 * DPR, 36 * DPR, 18 * DPR);
    g.globalCompositeOperation = "lighter";
    if (hasFn(key, "laser") || /laser/i.test(`${f.name} ${f.profile}`)) {
      drawGenericLaser(key, x, y, t, floor);
      label(name, x, y + 26 * DPR);
      continue;
    }
    const r = fnv(key, "red") ?? 0, gg = fnv(key, "green") ?? 0, b = fnv(key, "blue") ?? 0;
    const w = (fnv(key, "white") ?? 0) + (fnv(key, "amber") ?? 0) * 0.6;
    let col = rgbw(r, gg, b, w);
    const uv = fnv(key, "uv") ?? 0;
    if (uv > 0 && Math.max(...col) < 20) col = [140, 50, 255];
    const dimFn = fnv(key, "dimmer");
    let a = (Math.max(...col, uv) / 255) * (dimFn == null ? 1 : dimFn / 255);
    const st = fnv(key, "strobe") ?? 0;
    if (st > 10 && a > 0) a = blink(t, 2 + (st / 255) * 16) ? a : 0;
    const sat = Math.max(1, ...col) / 255;
    const c = col.map((v) => v / sat);
    const pan = fnv(key, "pan"), tilt = fnv(key, "tilt");
    let ex = x, ey = floor;
    if (pan != null || tilt != null) {
      const fl = f.mount === "floor";
      let p = (pan ?? 128) / 255, tl = (tilt ?? 128) / 255;
      if (fl) { p = 1 - p; tl = 1 - tl; }
      const ang = (p - 0.5) * Math.PI * 1.1;
      const top = H * 0.1 + 8 * DPR;
      const reach = fl ? y - top : floor - y;
      ex = x + Math.sin(ang) * reach * (0.6 + tl);
      ey = fl ? Math.max(top, y - reach * (0.25 + 0.75 * tl)) : Math.min(floor, y + reach * (0.25 + 0.75 * tl));
    }
    if (a > 0.01) { beam(x, y, ex, ey, 6 * DPR, W * 0.04, c, a * 0.8); glow(ex, ey, W * 0.06, c, a * 0.35); }
    lamp(x, y, 8 * DPR, c, a);
    label(name, x, y + 26 * DPR);
  }
}

function label(text, x, y) {
  g.fillStyle = "#555569"; g.font = `${11 * DPR}px system-ui, sans-serif`; g.textAlign = "center";
  g.fillText(text, x, y);
}

let lastMs = 0;
function frame(ms) {
  const t = ms / 1000;
  const dt = Math.min(0.1, (ms - lastMs) / 1000 || 0.016);
  lastMs = ms;
  const floor = room();
  g.globalCompositeOperation = "lighter";
  drawFog(t, floor, dt);
  g.globalAlpha = 1;
  drawParbar(t, floor);
  drawHead(t, floor, dt);
  drawBelka(t, floor);
  drawGeneric(t, floor);
  g.globalCompositeOperation = "source-over";
  if (running) rafId = requestAnimationFrame(frame);
}

// --- panel DMX kanálov -----------------------------------------------------------
const panel = document.getElementById("dmx");
let NCH = 36;
function buildPanel() {
  const names = {};
  NCH = Math.max(36, ...Object.values(FX).map((f) => f.start + Math.max(0, ...Object.values(f.channels)) - 1));
  panel.style.gridTemplateColumns = `repeat(${innerWidth < 700 ? Math.ceil(NCH / 2) : NCH}, 1fr)`;
  for (const [key, f] of Object.entries(FX))
    for (const [n, rel] of Object.entries(f.channels)) names[f.start + rel - 1] = [key, n];
  panel.innerHTML = "";
  for (let i = 1; i <= NCH; i++) {
    const [key, n] = names[i] || ["", ""];
    const d = document.createElement("div");
    d.className = "c " + (key && !FX[key].known ? "gen" : key);
    d.title = `${i} ${key}.${n}`;
    d.innerHTML = `<div class="bar"><i id="b${i}"></i></div><b id="v${i}">0</b><small>${i} ${n.replace("_", " ")}</small>`;
    panel.appendChild(d);
  }
}
function updatePanel() {
  if (panel.classList.contains("hidden")) return;
  for (let i = 1; i <= NCH; i++) {
    const v = dmx[i - 1] || 0;
    document.getElementById("b" + i).style.height = `${(v / 255) * 100}%`;
    document.getElementById("v" + i).textContent = v;
  }
}
document.getElementById("toggle").onclick = () => panel.classList.toggle("hidden");

// --- dáta ---------------------------------------------------------------------
// Viz beží až po ťuknutí na SPUSTIŤ: dovtedy žiadne spojenie s boxom, žiadne kreslenie.
let running = false, ws = null, rafId = 0, fxTimer = 0, retry = 0;
function connect() {
  if (!running) return;
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/dmx`);
  const conn = document.getElementById("conn");
  ws.onopen = () => { conn.textContent = "online"; conn.className = "pill"; };
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    dmx = d.ch.concat(new Array(512 - d.ch.length).fill(0));
    bpm = d.bpm || 120; silent = d.silent;
    document.getElementById("bpm").textContent = silent ? "ticho"
      : `${Math.round(bpm)} BPM · ${d.style || ""}${d.section && d.section !== "main" ? " · " + d.section.toUpperCase() : ""}`;
    updatePanel();
  };
  ws.onclose = () => {
    conn.textContent = running ? "offline" : "zastavené"; conn.className = "pill off";
    if (running) retry = setTimeout(connect, 1500);
  };
}

// zoznam svetiel sa môže zmeniť v appke → počas behu každých 5 s skontroluj
let fxSig = "";
async function loadFixtures() {
  try {
    const f = await (await fetch("/api/fixtures")).json();
    const sig = JSON.stringify(f);
    if (sig !== fxSig) { fxSig = sig; FX = f; buildPanel(); }
  } catch { /* box offline */ }
}

const startEl = document.getElementById("start"), stopBtn = document.getElementById("stop");
async function start() {
  if (running) return;
  running = true;
  startEl.hidden = true; stopBtn.hidden = false;
  await loadFixtures();
  connect();
  fxTimer = setInterval(loadFixtures, 5000);
  lastMs = performance.now();
  rafId = requestAnimationFrame(frame);
}
function stop() {
  running = false;
  clearTimeout(retry); clearInterval(fxTimer); cancelAnimationFrame(rafId);
  if (ws) { ws.onmessage = null; ws.close(); ws = null; }
  dmx = new Array(512).fill(0);
  g.clearRect(0, 0, cv.width, cv.height);
  document.getElementById("bpm").textContent = "--- BPM";
  startEl.hidden = false; stopBtn.hidden = true;
}
document.getElementById("start-btn").onclick = start;
stopBtn.onclick = stop;

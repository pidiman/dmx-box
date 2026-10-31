"use strict";
// Virtuálne svetlá: kreslí PartyBar4, moving head a Belku z DMX rámca (/ws/dmx).

const cv = document.getElementById("c");
const g = cv.getContext("2d");
let W = 0, H = 0, DPR = 1;
let FX = {};                 // kanálové mapy z /api/fixtures
let dmx = new Array(512).fill(0);
let bpm = 120, silent = true;

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
function drawHead(t, floor) {
  if (!FX.movinghead) return;
  const x = W * 0.5, y = H * 0.1 + 26 * DPR;
  const pan = ch("movinghead", "pan") / 255, tilt = ch("movinghead", "tilt") / 255;
  let a = ch("movinghead", "dimmer") / 255;
  const st = ch("movinghead", "strobe");
  if (st > 0 && a > 0) a = blink(t, 1 + (st / 255) * 18) ? a : 0;
  const col = headColor(ch("movinghead", "color"), t);
  // pan → vodorovný smer, tilt → ako ďaleko do miestnosti/na stenu
  const ang = (pan - 0.5) * Math.PI * 1.15;
  const reach = floor - y;
  const ex = x + Math.sin(ang) * reach * (0.6 + tilt * 1.1);
  const ey = Math.min(floor, y + reach * (0.25 + 0.75 * tilt));
  const gv = ch("movinghead", "gobo");
  // telo hlavy
  g.fillStyle = "#1d1d27"; g.fillRect(x - 22 * DPR, y - 20 * DPR, 44 * DPR, 14 * DPR);
  g.save(); g.translate(x, y + 6 * DPR); g.rotate(Math.atan2(ex - x, ey - y) * -1);
  g.fillStyle = "#24242f"; g.fillRect(-14 * DPR, -10 * DPR, 28 * DPR, 30 * DPR);
  g.restore();
  // LED krúžok
  const ring = ch("movinghead", "led_ring");
  if (ring > 0) for (let i = 0; i < 12; i++) {
    const aa = (i / 12) * Math.PI * 2 + t * 2;
    glow(x + Math.cos(aa) * 26 * DPR, y + 8 * DPR + Math.sin(aa) * 10 * DPR, 7 * DPR, hsv((i / 12 + t * 0.3) % 1), 0.8);
  }
  if (a <= 0.01) { label("Moving head", x, y + 42 * DPR); return; }
  beam(x, y + 10 * DPR, ex, ey, 5 * DPR, W * 0.03, col, a);
  // spot s gobom
  const r = W * 0.045;
  g.save(); g.translate(ex, ey); g.scale(1, ey >= floor - 1 ? 0.35 : 0.8);
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
  lamp(x, y + 10 * DPR, 6 * DPR, col, a);
  label("Moving head", x, y + 42 * DPR);
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

function label(text, x, y) {
  g.fillStyle = "#555569"; g.font = `${11 * DPR}px system-ui, sans-serif`; g.textAlign = "center";
  g.fillText(text, x, y);
}

function frame(ms) {
  const t = ms / 1000;
  const floor = room();
  g.globalCompositeOperation = "lighter";
  drawParbar(t, floor);
  drawHead(t, floor);
  drawBelka(t, floor);
  g.globalCompositeOperation = "source-over";
  requestAnimationFrame(frame);
}

// --- panel DMX kanálov -----------------------------------------------------------
const panel = document.getElementById("dmx");
function buildPanel() {
  const names = {};
  for (const [key, f] of Object.entries(FX))
    for (const [n, rel] of Object.entries(f.channels)) names[f.start + rel - 1] = [key, n];
  panel.innerHTML = "";
  for (let i = 1; i <= 32; i++) {
    const [key, n] = names[i] || ["", ""];
    const d = document.createElement("div");
    d.className = "c " + key;
    d.title = `${i} ${key}.${n}`;
    d.innerHTML = `<div class="bar"><i id="b${i}"></i></div><b id="v${i}">0</b><small>${i} ${n.replace("_", " ")}</small>`;
    panel.appendChild(d);
  }
}
function updatePanel() {
  if (panel.classList.contains("hidden")) return;
  for (let i = 1; i <= 32; i++) {
    const v = dmx[i - 1] || 0;
    document.getElementById("b" + i).style.height = `${(v / 255) * 100}%`;
    document.getElementById("v" + i).textContent = v;
  }
}
document.getElementById("toggle").onclick = () => panel.classList.toggle("hidden");

// --- dáta ---------------------------------------------------------------------
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/dmx`);
  const conn = document.getElementById("conn");
  ws.onopen = () => { conn.textContent = "online"; conn.className = "pill"; };
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    dmx = d.ch.concat(new Array(512 - d.ch.length).fill(0));
    bpm = d.bpm || 120; silent = d.silent;
    document.getElementById("bpm").textContent = silent ? "ticho" : `${Math.round(bpm)} BPM`;
    updatePanel();
  };
  ws.onclose = () => { conn.textContent = "offline"; conn.className = "pill off"; setTimeout(connect, 1500); };
}

fetch("/api/fixtures").then((r) => r.json()).then((f) => {
  FX = f;
  buildPanel();
  connect();
  requestAnimationFrame(frame);
});

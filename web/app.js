"use strict";

const $ = (s) => document.querySelector(s);
const NAMES = {
  beat_chase: "Beat chase", bass_pump: "Bass pump", color_step: "Color step", rainbow: "Dúha",
  split: "Split", kick_flash: "Kick flash", build_up: "Build-up", derby_party: "Derby party",
  jump: "Skoky", circle_slow: "Kruh", sweep: "Sweep", tilt_bounce: "Tilt", snap: "Snap",
  audience: "Nad hlavy", gobo_beat: "Gobo beat", hold: "Stoj",
};
const PALETTE_SW = {
  party: ["#f00", "#f0f", "#00f", "#0ff", "#0f0", "#f90"],
  cool: ["#00f", "#0ff", "#80f", "#4af"],
  warm: ["#f00", "#f60", "#f3a", "#fb3"],
  ice: ["#fff", "#6cf", "#00f", "#8ff"],
  fire: ["#f00", "#f50", "#f90", "#f44"],
  urban: ["#90f", "#f90", "#f09", "#20f"],
};
// legenda kolies (texty podľa docs/OVLADANIE.md)
const FX_INFO = {
  color: {
    title: "Farby – čo robí ktorý efekt",
    intro: "Koleso <b>Farby</b> riadi farby a jas lišty, Belky (PAR, derby, laser, strobo) a farbu moving headu. <b>Ťuk na efekt</b> ho zapne a vypne AUTO – potom svieti len tento efekt. AUTO ich strieda sám podľa štýlu hudby.",
    items: {
      beat_chase: ["Každú dobu nová farba z palety. Farby „bežia“ po svetlách, jas pulzuje do rytmu, laser každú 4. dobu.", ["univerzálny", "pop", "house"]],
      bass_pump: ["Jas všetkých svetiel podľa sily basov, farba sa mení každý takt.", ["výrazná basa", "pomalšie časti"]],
      color_step: ["Stála plná farba, mení sa každý takt, derby sa točí pomaly.", ["pokojné skladby", "čistý vzhľad"]],
      rainbow: ["Plynulý dúhový prechod cez 16 dôb, svetlá posunuté o tretinu kruhu. Ak je povolené UV, jemný UV podklad.", ["chill", "úvod", "breakdown"]],
      split: ["Lišta a Belka PAR sa striedajú na dobu, derby svieti na nepárne doby, laser každú 2. dobu.", ["rytmické", "rock", "pop"]],
      kick_flash: ["Biely záblesk na každý úder basového bubna, inak tlmená farba. Derby a laser na silný úder.", ["DnB", "techno", "hip-hop"]],
      build_up: ["Blikanie zrýchľuje s energiou hudby, keď je hudba naplno, zapne strobo Belky.", ["nástup pred dropom", "stúpajúce časti"]],
      derby_party: ["V refréne derby naplno a laser na každú dobu, v tichších častiach derby tlmene a UV podklad.", ["refrény", "párty vrcholy"]],
    },
  },
  move: {
    title: "Pohyb – čo robí ktorý efekt",
    intro: "Koleso <b>Pohyb</b> riadi moving head: smer, gobo a pohyb. Motor nestíha rýchle plynulé pohyby, preto rýchle efekty <b>skáču medzi pozíciami</b> na dobu a plynulé sú pomalé. Tilt je obmedzený, aby hlava nesvietila do očí. <b>Ťuk na efekt</b> ho zapne a vypne AUTO.",
    items: {
      jump: ["Skok na ďalšiu z 10 pozícií v miestnosti na každú dobu, gobo sa mení každý takt.", ["hlavný režim", "párty"]],
      circle_slow: ["Pomalý kruh cez 8 dôb, otvorené svetlo bez gobo.", ["pomalá hudba", "chill"]],
      sweep: ["Pan zľava doprava a späť na každú dobu.", ["rytmické", "house"]],
      tilt_bounce: ["Hore-dole na každú dobu, pan sa posunie každý takt.", ["rytmické", "pop"]],
      snap: ["Náhodná pozícia a gobo každé 2 doby, na kick sa rozsvieti naplno.", ["DnB", "techno"]],
      audience: ["Pomalý plynulý pohyb nad hlavami ľudí cez 16 dôb, rotujúce gobo.", ["breakdown", "atmosféra"]],
      gobo_beat: ["Hlava stojí, na každú dobu iné gobo, na silný kick gobo zatrasie.", ["kick", "hip-hop"]],
      hold: ["Hlava stojí v strede a svieti.", ["statická scéna", "spev"]],
    },
  },
};

const SECTION_NAMES = { main: "hrá", breakdown: "breakdown", build: "build-up", drop: "DROP" };
let styleNames = {};

let settings = {};
let presets = new Set();
let dragging = null;   // slider, ktorý práve ťahám – WS ho neprepíše

async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401 && !path.startsWith("/api/auth")) { location.href = "/lock.html?next=" + encodeURIComponent(location.pathname + location.hash); throw new Error("zadaj PIN"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}
const patch = (obj) => api("POST", "/api/settings", obj).then(apply).catch(err);

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 1400);
}
function err(e) { toast("Chyba: " + e.message); }

// --- FX kolesá -------------------------------------------------------------
function buildWheel(el, list, key) {
  el.innerHTML = "";
  list.forEach((name, i) => {
    const b = document.createElement("button");
    const ang = (i / list.length) * 2 * Math.PI - Math.PI / 2;
    b.style.left = `${37.5 + 36 * Math.cos(ang)}%`;
    b.style.top = `${37.5 + 36 * Math.sin(ang)}%`;
    b.textContent = NAMES[name] || name;
    b.dataset.fx = name;
    b.onclick = () => api("POST", "/api/fx", { wheel: key === "color_fx" ? 1 : 2, fx: name })
      .then(apply).catch(err);
    el.appendChild(b);
  });
}

function buildStyles(list) {
  const box = $("#styles"); box.innerHTML = "";
  [{ key: "auto", name: "AUTO" }, ...list].forEach((st) => {
    styleNames[st.key] = st.name;
    const b = document.createElement("button");
    b.dataset.style = st.key;
    b.textContent = st.key === "auto" ? "AUTO" : st.name.replace("Drum & Bass", "DnB").replace("Pop / party", "Pop");
    b.onclick = () => patch({ style: st.key, auto: true });
    box.appendChild(b);
  });
}

function buildPalettes(list) {
  const box = $("#palettes");
  box.querySelectorAll(".chip:not(#pal-style)").forEach((c) => c.remove());
  $("#pal-style").onclick = () => patch({ style_palette: true, manual_color: null });
  list.forEach((p) => {
    const b = document.createElement("button");
    b.className = "chip"; b.dataset.p = p;
    b.innerHTML = `<span class="sw">${(PALETTE_SW[p] || []).map((c) => `<i style="background:${c}"></i>`).join("")}</span><b>${p}</b>`;
    b.onclick = () => patch({ palette: p, style_palette: false, manual_color: null });
    box.appendChild(b);
  });
}

function buildPresets() {
  const box = $("#presets"); box.innerHTML = "";
  for (let n = 1; n <= 50; n++) {
    const b = document.createElement("button");
    b.textContent = n; b.dataset.n = n;
    let timer = null, saved = false;
    const down = () => {
      saved = false; b.classList.add("holding");
      timer = setTimeout(async () => {
        saved = true; b.classList.remove("holding");
        await api("PUT", `/api/preset/${n}`).catch(err);
        presets.add(n); paintPresets(); toast(`Preset ${n} uložený`);
      }, 700);
    };
    const up = () => {
      clearTimeout(timer); b.classList.remove("holding");
      if (!saved) api("POST", `/api/preset/${n}`).then((s) => { apply(s); toast(`Preset ${n}`); })
        .catch(() => toast(`Preset ${n} je prázdny – podrž pre uloženie`));
    };
    b.addEventListener("pointerdown", down);
    b.addEventListener("pointerup", up);
    b.addEventListener("pointerleave", () => { clearTimeout(timer); b.classList.remove("holding"); });
    box.appendChild(b);
  }
}
function paintPresets() {
  document.querySelectorAll("#presets button").forEach((b) =>
    b.classList.toggle("saved", presets.has(+b.dataset.n)));
}

// --- aplikovanie stavu do UI --------------------------------------------------
function hex(rgbw) {
  const [r, g, b, w] = rgbw.map(Number);
  const c = (v) => Math.round(Math.min(1, v + w) * 255).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

function apply(s) {
  settings = s;
  for (const id of ["master", "size", "fade"]) if (dragging !== id) $("#" + id).value = s[id];
  if (dragging !== "delay") { $("#delay").value = s.light_delay_ms; $("#delay-out").textContent = s.light_delay_ms + " ms"; }
  document.querySelectorAll("#speed button").forEach((b) => b.classList.toggle("on", +b.dataset.v === s.speed));
  $("#auto").classList.toggle("on", s.auto);
  $("#auto-bars").value = String(s.auto_bars);
  $("#blackout").classList.toggle("on", s.blackout);
  for (const id of ["laser", "uv", "line_in", "fog_auto"]) $("#" + id).checked = !!s[id];
  if (dragging !== "fog_burst_s") { $("#fog_burst_s").value = s.fog_burst_s; $("#burst-out").textContent = s.fog_burst_s + " s"; }
  const palStyle = s.auto && s.style_palette;
  document.querySelectorAll(".chip").forEach((b) => b.classList.toggle("on", !s.manual_color &&
    (b.dataset.p === "__style" ? palStyle : !palStyle && b.dataset.p === s.palette)));
  document.querySelectorAll("#styles button").forEach((b) => b.classList.toggle("on", s.auto && b.dataset.style === s.style));
  if (s.manual_color) $("#manual").value = hex(s.manual_color);
}

function live(d) {
  const a = d.audio;
  $("#bpm").textContent = a.silent ? "---" : Math.round(a.bpm);
  $("#beat").style.opacity = a.silent ? 0.15 : Math.max(0.15, 1 - a.phase * 1.6);
  if (d.viz) { spec.l = d.viz.l.map((v) => v / 99); spec.r = d.viz.r.map((v) => v / 99); }
  spec.silent = a.silent;
  const tr = d.track, tb = $("#track");
  const showTrack = !!(tr && tr.title);
  tb.hidden = !showTrack;
  if (showTrack) {
    $("#track-title").textContent = tr.title;
    $("#track-artist").textContent = [tr.artist, tr.source && `· ${tr.source}`].filter(Boolean).join(" ");
  }
  sysStats(d.sys);
  speakerState(d.speaker);
  const dmx = $("#dmx");
  dmx.textContent = d.dmx.driver === "dry" ? "DMX dry" : "DMX";
  dmx.className = d.dmx.connected ? "on" : "off";
  const e = d.engine;
  if (lastFx.color !== e.color_fx || lastFx.move !== e.move_fx) {
    lastFx = { color: e.color_fx, move: e.move_fx };
    if (infoOpen) renderInfo();
  }
  $("#cur-color").textContent = e.idle ? "ticho" : (NAMES[e.color_fx] || e.color_fx);
  $("#cur-move").textContent = e.idle ? "" : (NAMES[e.move_fx] || e.move_fx);
  document.querySelectorAll("#wheel-color button").forEach((b) => b.classList.toggle("active", b.dataset.fx === e.color_fx));
  document.querySelectorAll("#wheel-move button").forEach((b) => b.classList.toggle("active", b.dataset.fx === e.move_fx));
  const m = d.music;
  if (m) {
    const sure = Math.round(m.confidence * 100);
    $("#style-detect").textContent = a.silent ? "ticho" : `rozpoznané: ${m.name} · ${sure} %`;
    $("#style-now").textContent = e.idle ? "" : (styleNames[e.style] || e.style) + (e.style_auto ? "" : " (pevne)");
    const sec = $("#section");
    sec.textContent = a.silent ? "—" : SECTION_NAMES[e.section] + (e.section === "build" ? ` ${Math.round(m.build * 100)} %` : "");
    sec.className = "pill sec-" + e.section;
  }
  const f = d.fog || {}, fb = $("#fog");
  fb.style.display = f.present === false ? "none" : "";
  fb.classList.toggle("on", !!f.on);
  fb.classList.toggle("wait", !f.on && !f.ready);
  $("#fog-info").textContent = f.on ? "ide" : f.ready ? "pripravený" : `⏳ ${Math.ceil(f.cooldown)} s`;
  if (JSON.stringify(d.settings) !== JSON.stringify(settings)) apply(d.settings);
}

// --- vizualizácia hudby: zrkadlové spektrum L (hore) / R (dole) ------------------------
const spec = { l: [], r: [], silent: true, sl: [], sr: [] };
function drawSpec() {
  const cv = $("#spec");
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const n = Math.max(spec.l.length, 24), mid = h / 2, gap = 2, bw = (w - gap * (n - 1)) / n;
  // plynulý prechod medzi správami z boxu (20×/s → 60 fps)
  for (const [src, dst] of [[spec.l, spec.sl], [spec.r, spec.sr]]) {
    for (let i = 0; i < n; i++) {
      const target = spec.silent ? 0 : (src[i] || 0);
      dst[i] = (dst[i] || 0) + (target - (dst[i] || 0)) * 0.35;
    }
  }
  g.fillStyle = "#303046"; g.fillRect(0, mid - 0.5, w, 1);
  for (let i = 0; i < n; i++) {
    const x = i * (bw + gap), k = i / (n - 1);
    g.fillStyle = `rgb(${Math.round(41 + 214 * k)},${Math.round(211 - 165 * k)},${Math.round(255 - 129 * k)})`;
    const hl = Math.max(1.5, spec.sl[i] * (mid - 3)), hr = Math.max(1.5, spec.sr[i] * (mid - 3));
    g.globalAlpha = 1; g.fillRect(x, mid - 1 - hl, bw, hl);
    g.globalAlpha = 0.85; g.fillRect(x, mid + 1, bw, hr);
  }
  g.globalAlpha = 1;
  requestAnimationFrame(drawSpec);
}
requestAnimationFrame(drawSpec);

// --- WebSocket -------------------------------------------------------------
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => setOnline(true);
  ws.onmessage = (m) => live(JSON.parse(m.data));
  ws.onclose = () => { setOnline(false); setTimeout(connect, 1500); };
}
// vyťaženie Pi: zelená < 60 %, oranžová 60–85 %, červená > 85 %; teplota 70 / 80 °C
const lvl = (v, w, b) => (v == null ? "" : v >= b ? "lv-bad" : v >= w ? "lv-warn" : "lv-ok");
const RING = 2 * Math.PI * 15;
function sysStats(st) {
  const box = $("#sysg"), menu = $("#menu-sys");
  box.hidden = menu.hidden = !st;
  if (!st) return;
  for (const k of ["cpu", "ram", "sd"]) {
    const v = st[k], g = box.querySelector(`[data-k="${k}"]`);
    g.className = "g " + lvl(v, 60, 85);
    g.querySelector(".fg").style.strokeDasharray = `${(RING * (v ?? 0)) / 100} ${RING}`;
    g.querySelector("text").textContent = v ?? "–";
    const m = $("#ms-" + k); m.textContent = `${k.toUpperCase()} ${v ?? "–"}%`; m.className = lvl(v, 60, 85);
  }
  const t = st.temp, tl = lvl(t, 70, 80), te = $("#sys-temp");
  te.className = "t " + tl; te.querySelector("b").textContent = t == null ? "–" : `${Math.round(t)}°`;
  te.hidden = t == null;
  const mt = $("#ms-temp"); mt.textContent = t == null ? "" : `${Math.round(t)} °C`; mt.className = tl; mt.hidden = t == null;
}
// --- legenda kolies (i) -------------------------------------------------------
let infoOpen = null, lastFx = { color: null, move: null };
function renderInfo() {
  const w = infoOpen, info = FX_INFO[w], cur = lastFx[w];
  const list = $("#sh-list"); list.innerHTML = "";
  for (const [k, [desc, when]] of Object.entries(info.items)) {
    const li = document.createElement("li");
    if (k === cur) li.className = "on";
    li.innerHTML = `<span class="sw"></span><b>${NAMES[k] || k}${k === cur ? "<em>PRÁVE BEŽÍ</em>" : ""}</b><p></p><div class="when"></div>`;
    li.querySelector("p").textContent = desc;
    for (const t of when) { const sp = document.createElement("span"); sp.textContent = t; li.querySelector(".when").append(sp); }
    list.append(li);
  }
}
let infoReturn = null;
function openInfo(w, btn) {
  infoOpen = w; infoReturn = btn;
  const sheet = $("#info-sheet .sheet");
  sheet.classList.toggle("move", w === "move");
  $("#sh-title").textContent = FX_INFO[w].title;
  $("#sh-intro").innerHTML = FX_INFO[w].intro;
  renderInfo();
  $("#info-sheet").hidden = false;
  sheet.scrollTop = 0;
  $("#sh-close").focus();
}
function closeInfo() {
  if (!infoOpen) return;
  infoOpen = null; $("#info-sheet").hidden = true;
  if (infoReturn) infoReturn.focus();
}
document.querySelectorAll(".info-btn").forEach((b) => b.addEventListener("click", (ev) => { ev.stopPropagation(); openInfo(b.dataset.info, b); }));
$("#sh-close").addEventListener("click", closeInfo);
$("#info-sheet").addEventListener("click", (ev) => { if (ev.target.id === "info-sheet") closeInfo(); });
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeInfo(); });

// --- BT reproduktor v menu ----------------------------------------------------------
let spkBusy = false;
function speakerState(sp) {
  const row = $("#spk-row"), arow = $("#spk-auto-row");
  row.hidden = arow.hidden = !(sp && sp.available);
  if (row.hidden) return;
  const b = $("#st-spk");
  if (sp.connected) { b.textContent = sp.name || "pripojený"; b.className = "on"; }
  else if (sp.reconnecting) { b.textContent = `pripájam ${sp.name || ""}…`; b.className = "warn"; }
  else if (sp.mac) { b.textContent = sp.paused ? `${sp.name} · odpojený ručne` : `${sp.name} · odpojený`; b.className = "off"; }
  else { b.textContent = "žiadny"; b.className = ""; }
  b.title = b.textContent;
  if (!spkBusy) $("#spk-auto").checked = !!sp.auto;
}
$("#spk-auto").addEventListener("change", async (ev) => {
  spkBusy = true;
  try {
    const r = await fetch("/api/system/bt/autoreconnect", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ on: ev.target.checked }) });
    if (!r.ok) throw new Error();
    toast(ev.target.checked ? "Auto pripojenie reproduktora zapnuté" : "Auto pripojenie vypnuté");
  } catch { ev.target.checked = !ev.target.checked; toast("Nepodarilo sa uložiť"); }
  spkBusy = false;
});

function setOnline(on) {
  const c = $("#conn"), t = on ? "Box online" : "Box offline";
  c.className = "live " + (on ? "on" : "off"); c.title = t; c.setAttribute("aria-label", t);
  const st = $("#st-conn"); st.textContent = on ? "online" : "offline"; st.className = on ? "on" : "off";
}

// --- hamburger menu --------------------------------------------------------
{
  const btn = $("#menu-btn"), menu = $("#menu");
  const show = (open) => { menu.hidden = !open; btn.setAttribute("aria-expanded", String(open)); };
  btn.addEventListener("click", (ev) => { ev.stopPropagation(); show(menu.hidden); });
  document.addEventListener("click", (ev) => { if (!menu.hidden && !menu.contains(ev.target)) show(false); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") show(false); });
  menu.addEventListener("click", (ev) => { if (ev.target.closest("a")) show(false); });
}

// --- ovládacie prvky ---------------------------------------------------------
function bindSlider(id, key, conv = Number) {
  const el = $("#" + id);
  let t = null;
  el.addEventListener("input", () => {
    dragging = id;
    if (id === "delay") $("#delay-out").textContent = el.value + " ms";
    clearTimeout(t); t = setTimeout(() => patch({ [key]: conv(el.value) }), 60);
  });
  el.addEventListener("change", () => { dragging = null; patch({ [key]: conv(el.value) }); });
}

function bindControls() {
  bindSlider("master", "master");
  bindSlider("size", "size");
  bindSlider("fade", "fade");
  bindSlider("delay", "light_delay_ms", (v) => parseInt(v, 10));
  document.querySelectorAll("#speed button").forEach((b) => (b.onclick = () => patch({ speed: +b.dataset.v })));
  $("#auto").onclick = () => api("POST", "/api/auto", { on: !settings.auto }).then(apply).catch(err);
  $("#auto-bars").onchange = (e) => patch({ auto_bars: +e.target.value });
  $("#tap").onclick = () => api("POST", "/api/tap").catch(err);
  $("#bpm-auto").onclick = () => api("POST", "/api/bpm", { bpm: null }).then(() => toast("BPM automaticky")).catch(err);
  document.querySelectorAll("[data-bpm]").forEach((b) =>
    (b.onclick = () => api("POST", "/api/bpm", { factor: +b.dataset.bpm }).catch(err)));
  $("#blackout").onclick = () => api("POST", "/api/blackout", { on: !settings.blackout }).then(apply).catch(err);

  const st = $("#strobe");
  const strobe = (on) => { st.classList.toggle("on", on); api("POST", "/api/strobe", { on }).catch(err); };
  st.addEventListener("pointerdown", (e) => { e.preventDefault(); strobe(true); });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) st.addEventListener(ev, () => settings.strobe && strobe(false));

  $("#manual").addEventListener("input", (e) => {
    const v = e.target.value;
    const rgb = [1, 3, 5].map((i) => parseInt(v.substr(i, 2), 16) / 255);
    patch({ manual_color: [...rgb, 0] });
  });
  $("#manual-off").onclick = () => patch({ manual_color: null });
  for (const id of ["laser", "uv", "line_in", "fog_auto"]) $("#" + id).onchange = (e) => patch({ [id]: e.target.checked });
  bindSlider("fog_burst_s", "fog_burst_s");
  $("#fog_burst_s").addEventListener("input", (e) => ($("#burst-out").textContent = e.target.value + " s"));

  const fb = $("#fog");
  const fog = (on) => api("POST", "/api/fog", { on }).catch(err);
  fb.addEventListener("pointerdown", (e) => { e.preventDefault(); fog(true); });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) fb.addEventListener(ev, () => settings.fog && fog(false));
}

async function init() {
  const d = await api("GET", "/api/state");
  buildWheel($("#wheel-color"), d.catalog.color_fx, "color_fx");
  buildWheel($("#wheel-move"), d.catalog.move_fx, "move_fx");
  buildStyles(d.catalog.styles || []);
  buildPalettes(d.catalog.palettes);
  buildPresets();
  presets = new Set(d.presets); paintPresets();
  bindControls();
  apply(d.settings); live(d);
  connect();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}
init().catch(err);

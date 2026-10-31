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
};

let settings = {};
let presets = new Set();
let dragging = null;   // slider, ktorý práve ťahám – WS ho neprepíše

async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
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

function buildPalettes(list) {
  const box = $("#palettes"); box.innerHTML = "";
  list.forEach((p) => {
    const b = document.createElement("button");
    b.className = "chip"; b.dataset.p = p;
    b.innerHTML = `<span class="sw">${(PALETTE_SW[p] || []).map((c) => `<i style="background:${c}"></i>`).join("")}</span><b>${p}</b>`;
    b.onclick = () => patch({ palette: p, manual_color: null });
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
  for (const id of ["laser", "uv", "line_in"]) $("#" + id).checked = !!s[id];
  document.querySelectorAll(".chip").forEach((b) => b.classList.toggle("on", b.dataset.p === s.palette && !s.manual_color));
  if (s.manual_color) $("#manual").value = hex(s.manual_color);
}

function live(d) {
  const a = d.audio;
  $("#bpm").textContent = a.silent ? "---" : Math.round(a.bpm);
  $("#beat").style.opacity = a.silent ? 0.15 : Math.max(0.15, 1 - a.phase * 1.6);
  $("#vu-bass").style.width = `${a.bass * 100}%`;
  $("#vu-mid").style.width = `${a.mid * 100}%`;
  $("#vu-high").style.width = `${a.high * 100}%`;
  const dmx = $("#dmx");
  dmx.textContent = d.dmx.driver === "dry" ? "DMX dry" : "DMX";
  dmx.className = "pill " + (d.dmx.connected ? "on" : "off");
  const e = d.engine;
  $("#cur-color").textContent = e.idle ? "ticho" : (NAMES[e.color_fx] || e.color_fx);
  $("#cur-move").textContent = e.idle ? "" : (NAMES[e.move_fx] || e.move_fx);
  document.querySelectorAll("#wheel-color button").forEach((b) => b.classList.toggle("active", b.dataset.fx === e.color_fx));
  document.querySelectorAll("#wheel-move button").forEach((b) => b.classList.toggle("active", b.dataset.fx === e.move_fx));
  if (JSON.stringify(d.settings) !== JSON.stringify(settings)) apply(d.settings);
}

// --- WebSocket -------------------------------------------------------------
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { $("#conn").textContent = "online"; $("#conn").className = "pill on"; };
  ws.onmessage = (m) => live(JSON.parse(m.data));
  ws.onclose = () => {
    $("#conn").textContent = "offline"; $("#conn").className = "pill off";
    setTimeout(connect, 1500);
  };
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
  for (const id of ["laser", "uv", "line_in"]) $("#" + id).onchange = (e) => patch({ [id]: e.target.checked });
}

async function init() {
  const d = await api("GET", "/api/state");
  buildWheel($("#wheel-color"), d.catalog.color_fx, "color_fx");
  buildWheel($("#wheel-move"), d.catalog.move_fx, "move_fx");
  buildPalettes(d.catalog.palettes);
  buildPresets();
  presets = new Set(d.presets); paintPresets();
  bindControls();
  apply(d.settings); live(d);
  connect();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}
init().catch(err);

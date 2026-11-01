"use strict";
// Nastavenia boxu bez SSH: Wi-Fi, hotspot, Bluetooth, zvuk, Spotify, aktualizácia, vypnutie.

const $ = (s) => document.querySelector(s);
let sys = null, wifiScan = null, btFound = null, busy = {}, showPass = false;
const NAME = () => sys?.system?.hostname || "fajny-dmx-box";
const SSID = () => sys?.wifi?.hotspot?.ssid || NAME();

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k.nodeType ? k : document.createTextNode(k));
  return el;
}
async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || r.statusText);
  return d;
}
function toast(msg, ms = 2800) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms);
}
// akcia s potvrdením druhým ťuknutím (bez systémových dialógov)
function confirmBtn(label, confirmLabel, fn, cls = "") {
  const b = h("button", { class: cls }, label);
  let armed = false, t;
  b.onclick = () => {
    if (!armed) { armed = true; b.textContent = confirmLabel; t = setTimeout(() => { armed = false; b.textContent = label; }, 3500); return; }
    clearTimeout(t); armed = false; b.textContent = label; fn();
  };
  return b;
}
async function act(key, fn, okMsg) {
  busy[key] = true; render();
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); }
  catch (e) { toast("Chyba: " + e.message, 5000); }
  busy[key] = false; await refresh();
}
const item = (left, ...acts) => h("div", { class: "item" }, left, acts.length ? h("div", { class: "acts" }, ...acts) : null);
const lbl = (title, sub, subCls = "") => h("div", { class: "l" }, h("b", {}, title), sub ? h("small", { class: subCls }, sub) : null);
const spin = (text) => h("span", {}, h("span", { class: "spin" }), " ", text);

// --- sieť ---------------------------------------------------------------------------
function renderWifi() {
  const g = $("#g-wifi"); g.innerHTML = "";
  const w = sys.wifi;
  if (!w.available) { g.append(item(lbl("Wi-Fi sa tu nedá spravovať", "NetworkManager nie je dostupný (nie Raspberry Pi?)"))); return; }
  g.append(item(lbl(w.mode === "client" ? w.ssid : w.mode === "hotspot" ? `Hotspot ${SSID()}` : "Nepripojené",
    w.mode === "client" ? `pripojené · ${w.ip || ""} · ${NAME()}.local` :
    w.mode === "hotspot" ? `bez internetu · ${w.hotspot.ip}` : "", w.mode === "client" ? "ok" : "")));
  for (const n of w.saved.filter((x) => !x.active)) {
    g.append(item(lbl(n.ssid, "uložená sieť"),
      h("button", { onclick: () => act("wc", () => api("POST", "/api/system/wifi/connect", { ssid: n.ssid }),
        `Prepínam na ${n.ssid}… Tablet sa odpojí – pripoj ho na rovnakú sieť a otvor ${NAME()}.local`) }, "Pripojiť"),
      confirmBtn("Zmazať", "Naozaj?", () => act("wd", () => api("POST", "/api/system/wifi/delete", { ssid: n.ssid }), "Zmazané"))));
  }
  // pridať sieť
  const ssid = h("input", { type: "text", placeholder: "Meno siete (SSID)", autocomplete: "off", autocapitalize: "off" });
  const pass = h("input", { type: "password", placeholder: "Heslo", autocomplete: "off" });
  const scanBtn = h("button", { disabled: !!busy.scan, onclick: async () => {
    busy.scan = true; render();
    try { wifiScan = (await api("GET", "/api/system/wifi/scan")).result; } catch (e) { toast("Chyba: " + e.message); }
    busy.scan = false; render();
  } }, busy.scan ? spin("Hľadám…") : "Nájsť siete v okolí");
  const form = h("div", { class: "form" },
    h("b", {}, "Pridať Wi-Fi sieť"),
    wifiScan ? h("div", { class: "chips" }, wifiScan.slice(0, 12).map((n) =>
      h("button", { class: "chip-s", style: "min-height:36px;border:0", onclick: () => { ssid.value = n.ssid; pass.focus(); } },
        `${n.ssid} · ${n.signal}%`))) : null,
    scanBtn, ssid, pass,
    h("button", { onclick: () => {
      if (!ssid.value.trim()) return toast("Zadaj meno siete");
      act("wa", () => api("POST", "/api/system/wifi", { ssid: ssid.value.trim(), password: pass.value }),
        "Sieť uložená. Box sa na ňu pripojí sám, keď bude v dosahu.");
    } }, "Uložiť sieť"),
    h("span", { class: "hint" }, "Sieť si môžeš uložiť aj vopred (napr. u kamaráta). Keď box nenájde žiadnu známu sieť, zapne vlastný hotspot."));
  g.append(form);
}

function renderHotspot() {
  const g = $("#g-hotspot"); g.innerHTML = "";
  const w = sys.wifi;
  if (!w.available) return;
  const hs = w.hotspot;
  g.append(item(lbl(`Wi-Fi ${SSID()}`, w.mode === "hotspot" ? "beží – tablety sa pripájajú sem" : "vypnutý", w.mode === "hotspot" ? "ok" : ""),
    w.mode === "hotspot"
      ? confirmBtn("Vypnúť", "Naozaj? Tablet sa odpojí", () => act("ho", () => api("POST", "/api/system/hotspot", { on: false }), "Hotspot sa vypína, box sa pripojí na známu Wi-Fi"))
      : confirmBtn("Zapnúť", "Naozaj? Tablet sa odpojí", () => act("ho", () => api("POST", "/api/system/hotspot", { on: true }), `Hotspot sa zapína – pripoj tablet na Wi-Fi ${SSID()} a otvor 10.42.0.1`))));
  g.append(item(lbl("Heslo hotspotu", hs.password ? (showPass ? hs.password : "••••••••") : "nedá sa zistiť"),
    hs.password ? h("button", { onclick: () => { showPass = !showPass; render(); } }, showPass ? "Skryť" : "Ukázať") : null));
  const np = h("input", { type: "text", placeholder: "Nové heslo (min. 8 znakov)", autocomplete: "off", autocapitalize: "off" });
  g.append(h("div", { class: "form" }, np, h("button", { onclick: () => {
    if (np.value.length < 8) return toast("Heslo musí mať aspoň 8 znakov");
    act("hp", () => api("POST", "/api/system/hotspot/password", { value: np.value }), "Heslo zmenené (platí od ďalšieho zapnutia hotspotu)");
  } }, "Zmeniť heslo")));
  const auto = h("input", { type: "checkbox", checked: hs.auto, onchange: (e) =>
    act("ha", () => api("POST", "/api/system/hotspot/auto", { on: e.target.checked }), e.target.checked ? "Automatický hotspot zapnutý" : "Automatický hotspot vypnutý") });
  g.append(h("label", { class: "item" }, lbl("Zapnúť sám bez Wi-Fi", "keď box nenájde známu sieť do 40 s"), auto));
}

// --- Bluetooth -------------------------------------------------------------------------
function renderBt() {
  const g = $("#g-bt"); g.innerHTML = "";
  const b = sys.bt;
  if (!b.available) { g.append(item(lbl("Bluetooth nie je dostupný"))); return; }
  const disc = h("input", { type: "checkbox", checked: b.discoverable, onchange: (e) =>
    act("bd", () => api("POST", "/api/system/bt/discoverable", { on: e.target.checked }), e.target.checked ? "Viditeľný pre nové mobily" : "Skrytý – spárované zariadenia sa pripoja ďalej") });
  g.append(h("label", { class: "item" }, lbl(`Viditeľný ako ${b.name || NAME()}`, "vypni, keď nechceš, aby sa pripájali cudzí"), disc));
  if (!b.devices.length) g.append(item(lbl("Žiadne spárované zariadenia")));
  for (const d of b.devices) {
    g.append(item(lbl(d.name, (d.speaker ? "reproduktor · " : "") + (d.connected ? "pripojený" : "spárovaný"), d.connected ? "ok" : ""),
      d.connected ? h("button", { onclick: () => act("bx", () => api("POST", "/api/system/bt/disconnect", { mac: d.mac }), "Odpojené") }, "Odpojiť")
        : d.speaker ? h("button", { onclick: () => act("bc", () => api("POST", "/api/system/bt/connect", { mac: d.mac }), "Pripojené") }, "Pripojiť") : null,
      confirmBtn("Zabudnúť", "Naozaj?", () => act("bf", () => api("POST", "/api/system/bt/forget", { mac: d.mac }), "Zabudnuté"))));
  }
  const scan = h("button", { class: "linkbtn", disabled: !!busy.bs, onclick: async () => {
    busy.bs = true; render();
    try { btFound = (await api("GET", "/api/system/bt/scan")).result; if (!btFound.length) toast("Nič som nenašiel – je zariadenie v režime párovania?"); }
    catch (e) { toast("Chyba: " + e.message); }
    busy.bs = false; render();
  } }, busy.bs ? spin("Hľadám 12 s…") : "+ Pridať Bluetooth reproduktor");
  g.append(h("div", { class: "item" }, scan));
  for (const d of btFound || []) {
    g.append(item(lbl(d.name, d.mac), h("button", { onclick: () => act("bp", () => api("POST", "/api/system/bt/connect", { mac: d.mac }), `${d.name} spárovaný`) }, "Spárovať")));
  }
}

// --- zvuk --------------------------------------------------------------------------------
function renderAudio() {
  const g = $("#g-audio"); g.innerHTML = "";
  const a = sys.audio;
  if (!a.available) { g.append(item(lbl("Zvuk sa tu nedá spravovať"))); return; }
  for (const s of a.sinks) {
    g.append(item(lbl(s.label, s.default ? "práve hrá sem" : s.description, s.default ? "ok" : ""),
      s.default ? null : h("button", { onclick: () => act("ao", () => api("POST", "/api/system/audio/output", { value: s.name }), `Zvuk ide do: ${s.label}`) }, "Použiť")));
  }
  if (a.volume != null) {
    const out = h("output", {}, `${a.volume} %`);
    g.append(h("label", { class: "item", style: "display:grid" }, h("span", {}, "Hlasitosť ", out),
      h("input", { type: "range", min: 0, max: 100, value: a.volume,
        oninput: (e) => { out.textContent = `${e.target.value} %`; },
        onchange: (e) => act("av", () => api("POST", "/api/system/audio/volume", { value: +e.target.value })) })));
  }
  const sp = sys.spotify;
  if (sp.installed) {
    const t = h("input", { type: "checkbox", checked: sp.active, onchange: (e) =>
      act("sp", () => api("POST", "/api/system/spotify", { on: e.target.checked }), e.target.checked ? "Spotify Connect zapnutý" : "Spotify Connect vypnutý") });
    g.append(h("label", { class: "item" }, lbl("Spotify Connect", "box ako reproduktor v appke Spotify (Premium, internet)"), t));
  } else g.append(item(lbl("Spotify Connect", "nenainštalovaný (install.sh --spotify)")));
}

// --- svetlá a systém ------------------------------------------------------------------------
function renderDmx() {
  const g = $("#g-dmx"); g.innerHTML = "";
  const d = sys.dmx;
  g.append(item(lbl("DMX dongle", d.driver === "dry" ? "naprázdno (test bez donglu)" : d.connected ? "pripojený" : "nenájdený – skontroluj USB", d.connected && d.driver !== "dry" ? "ok" : "")));
  g.append(item(lbl("Svetlá", d.fixtures.join(", ")), h("a", { class: "pill", href: "viz.html" }, "Náhľad")));
}

function renderSys() {
  const g = $("#g-sys"); g.innerHTML = "";
  const s = sys.system;
  g.append(item(lbl("Verzia", [s.version, s.date].filter(Boolean).join(" · ") || "—")));
  if (s.temp || s.throttled) {
    const okPower = !s.throttled || s.throttled === "0x0";
    g.append(item(lbl("Teplota a napájanie", `${s.temp || "?"} · ${okPower ? "napájanie OK" : "slabý zdroj (" + s.throttled + ")"}`, okPower ? "ok" : "")));
  }
  g.append(item(lbl("Aktualizovať z GitHubu", "stiahne novú verziu a reštartuje appku (treba internet)"),
    h("button", { disabled: !!busy.up, onclick: () => act("up", () => api("POST", "/api/system/update"), (r) => `Hotovo: ${r.result}`) }, busy.up ? spin("…") : "Aktualizovať")));
  g.append(item(lbl("Reštartovať appku", "pri zaseknutých svetlách"),
    confirmBtn("Reštart", "Naozaj?", () => act("ra", () => api("POST", "/api/system/restart"), "Appka sa reštartuje (~10 s)"))));
  g.append(item(lbl("Reštartovať box", "trvá asi minútu"),
    confirmBtn("Reštart", "Naozaj?", () => act("rb", () => api("POST", "/api/system/power", { value: "reboot" }), "Box sa reštartuje"))));
  g.append(item(lbl("Vypnúť box", "potom môžeš vytiahnuť zo zásuvky"),
    confirmBtn("Vypnúť", "Naozaj vypnúť?", () => act("po", () => api("POST", "/api/system/power", { value: "poweroff" }), "Box sa vypína – po 20 s ho môžeš odpojiť"), "danger")));
}

function render() {
  if (!sys) return;
  document.title = `${NAME()} – nastavenia`;
  renderWifi(); renderHotspot(); renderBt(); renderAudio(); renderDmx(); renderSys();
}
async function refresh() {
  try { sys = await api("GET", "/api/system"); render(); }
  catch { toast("Box neodpovedá – skontroluj Wi-Fi", 4000); }
}
refresh();
// obnova stavu, ale nie keď používateľ píše do formulára
setInterval(() => { if (!document.activeElement || !["INPUT"].includes(document.activeElement.tagName)) refresh(); }, 8000);

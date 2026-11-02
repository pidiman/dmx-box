"use strict";
// Vstupná obrazovka: výber scenára a krátky sprievodca. Pôvodné ovládanie je na /ovladanie.

const $ = (s) => document.querySelector(s);
const STYLES = [
  ["auto", "AUTO", "Štýl podľa hudby"], ["party", "Párty", "Pestré, všetko"],
  ["chill", "Chill", "Pomaly, bez strobo"], ["dnb", "DnB", "Rýchle, ostré"],
  ["techno", "Techno", "Biela, modrá"], ["house", "House", "Teplé, groove"],
  ["hiphop", "Hip-hop", "Fialová, zlatá"],
];
const TINT = { airplay: "#f2f2f7", bt: "#29d3ff", spotify: "#6be3a0", linein: "#ffc65a", btspeaker: "#b79bff", ambient: "#ff8fb8", demo: "#9a9ab0" };
const BADGE = { airplay: "AP", bt: "BT", spotify: "SC", linein: "IN", btspeaker: "SP", ambient: "AM", demo: "DE" };

let sys = null, list = [], last = null, settings = {}, choice = null, audio = { level: 0, silent: true, bpm: 0 };
let pollTimer = null;
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
  if (r.status === 401 && !path.startsWith("/api/auth")) { location.href = "/lock.html?next=" + encodeURIComponent(location.pathname + location.hash); throw new Error("zadaj PIN"); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || r.statusText);
  return d;
}
function toast(msg, ms = 2600) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms);
}

// --- stav boxu ------------------------------------------------------------------
async function loadSys() {
  try { sys = await api("GET", "/api/system"); } catch { sys = null; }
}
function sinkLabel(name) {
  const s = sys?.audio?.sinks?.find((x) => x.name === name);
  return s ? s.label : "—";
}
function renderChips() {
  const c = $("#chips"); c.innerHTML = "";
  if (!sys) { c.append(h("span", { class: "chip-s bad" }, "Box neodpovedá")); return; }
  const w = sys.wifi;
  if (w.mode === "client") c.append(h("span", { class: "chip-s ok" }, `● Wi-Fi ${w.ssid}`));
  else if (w.mode === "hotspot") c.append(h("span", { class: "chip-s warn" }, `● Hotspot ${SSID()} (bez internetu)`));
  else if (w.available) c.append(h("span", { class: "chip-s bad" }, "● Bez Wi-Fi"));
  const d = sys.dmx;
  if (d.driver === "dry") c.append(h("span", { class: "chip-s warn" }, "DMX naprázdno (test)"));
  else c.append(h("span", { class: "chip-s " + (d.connected ? "ok" : "bad") }, d.connected ? `● DMX · ${d.fixtures.length} svetlá` : "● DMX dongle nepripojený"));
  if (sys.audio.default) c.append(h("span", { class: "chip-s" }, "Zvuk: " + sinkLabel(sys.audio.default)));
}

// --- domov --------------------------------------------------------------------------
function renderHome() {
  const box = $("#cards"); box.innerHTML = "";
  for (const s of list) {
    box.append(h("button", { class: "card", onclick: () => openSetup(s.id) },
      h("span", { class: "ic", style: `background:${TINT[s.id]}` }, BADGE[s.id]),
      h("span", {},
        h("strong", {}, s.name),
        h("p", {}, s.desc),
        h("span", {}, s.tags.map((t) => h("span", { class: "tag" }, t))),
        s.warn ? h("span", { class: "warn-t" }, s.warn) : null)));
  }
  const r = $("#resume");
  if (last && last.id) {
    const sc = list.find((x) => x.id === last.id);
    $("#resume-name").textContent = sc ? sc.name : last.id;
    const st = STYLES.find((x) => x[0] === (last.style || "auto"));
    $("#resume-sub").textContent = `svetlá ${st ? st[1] : last.style}` + (last.output ? ` · ${sinkLabel(last.output)}` : "");
    r.hidden = false;
    r.onclick = () => start(last);
  } else r.hidden = true;
}

// --- sprievodca -----------------------------------------------------------------------
function defaultOutput() {
  const sinks = (sys?.audio?.sinks || []).filter((s) => s.kind !== "bluetooth");
  const cur = sinks.find((s) => s.default);
  return (cur || sinks.find((s) => s.kind === "usb") || sinks.find((s) => s.kind === "jack") || sinks[0] || {}).name || null;
}

function openSetup(id) {
  const s = list.find((x) => x.id === id);
  choice = { id, style: id === "ambient" ? "chill" : (last?.id === id && last.style) || "auto",
             laser: settings.laser ?? true, fog_auto: settings.fog_auto ?? false };
  if (["bt", "airplay", "spotify", "linein"].includes(id)) choice.output = (last?.id === id && last.output) || defaultOutput();
  if (id === "btspeaker") { choice.source = last?.source || "airplay"; choice.delay_ms = last?.delay_ms ?? 200; }
  $("#s-title").textContent = s.name;
  $("#s-desc").textContent = s.desc;
  $("#home").hidden = true; $("#setup").hidden = false;
  window.scrollTo(0, 0);
  history.pushState({ setup: id }, "", "#" + id);
  renderSteps();
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => { await loadSys(); renderSteps(true); }, 5000);
}
function closeSetup() {
  clearInterval(pollTimer);
  $("#setup").hidden = true; $("#home").hidden = false;
  renderChips(); renderHome();
}

function step(n, title, ...body) {
  return h("div", { class: "step" }, h("h2", {}, h("span", {}, String(n)), title), ...body);
}
function row(ok, text, extra) {
  return h("div", { class: "status-row " + (ok === true ? "ok" : ok === false ? "bad" : "") }, h("span", {}, text), extra || null);
}

function stepPhone(n) {
  const phones = (sys?.bt?.devices || []).filter((d) => d.connected && !d.speaker);
  return step(n, "Spáruj mobil",
    h("p", {}, "V mobile otvor Nastavenia → Bluetooth a vyber ", h("b", {}, sys?.bt?.name || NAME()), ". PIN netreba."),
    phones.length ? phones.map((p) => row(true, `● ${p.name} · pripojený`)) : row(null, "Zatiaľ žiadny mobil – po pripojení sa tu objaví"),
    h("button", { onclick: async () => {
      try { await api("POST", "/api/system/bt/discoverable", { on: true }); toast(`${sys?.bt?.name || NAME()} je viditeľný pre nové mobily`); }
      catch (e) { toast("Chyba: " + e.message); }
    } }, sys?.bt?.discoverable ? "Pripojiť iný mobil (box je viditeľný)" : "Zviditeľniť box pre nový mobil"));
}

function stepSpotify(n) {
  const sp = sys?.spotify || {};
  const net = sys?.wifi?.mode === "client";
  return step(n, `Vyber ${NAME()} v Spotify`,
    h("p", {}, "V appke Spotify ťukni na ikonu zariadení (dole pri prehrávaní) a vyber ", h("b", {}, NAME()), ". Treba Spotify Premium."),
    !sp.installed ? row(false, "Spotify Connect nie je v boxe nainštalovaný") : row(sp.active ? true : null, sp.active ? "● Spotify Connect beží" : "Spustí sa po ťuknutí na Spustiť show"),
    net ? null : row(false, "Box nemá internet (hotspot) – Spotify nepôjde. Pripoj box na Wi-Fi v nastaveniach."),
    h("p", { class: "small", style: "color:#ffc65a" }, "Ak Spotify ostane na „Connecting“, tvoj účet ho nepodporuje – použi scenár Bluetooth z mobilu."));
}

function stepAirplay(n) {
  const ap = sys?.airplay || {};
  const hotspot = sys?.wifi?.mode === "hotspot";
  return step(n, "Vyber box v AirPlay",
    h("p", {}, "Na iPhone/iPade otvor Ovládacie centrum → v okienku s hudbou ťukni na ikonu AirPlay → vyber ", h("b", {}, NAME()), ". Ide to z akejkoľvek appky."),
    !ap.installed ? row(false, "AirPlay nie je v boxe nainštalovaný (spusti znova install.sh)")
      : row(ap.active ? true : null, ap.active ? "● AirPlay beží" : "Spustí sa po ťuknutí na Spustiť show"),
    h("p", { class: "small" }, hotspot
      ? "Box je v hotspote: iPhone musí byť pripojený na Wi-Fi boxu. Streamovanie (Spotify, Apple Music) bez internetu nepôjde – len stiahnutá hudba."
      : "iPhone musí byť v rovnakej Wi-Fi ako box."));
}

function stepLinein(n) {
  const usb = (sys?.audio?.sinks || []).some((s) => s.kind === "usb");
  return step(n, "Zapoj kábel",
    h("p", {}, "Kábel z DJ pultu alebo PC zapoj do vstupu (IN) zvukovej karty UCA202 v boxe."),
    usb ? row(true, "● UCA202 pripojená") : row(false, "UCA202 nenájdená – zapoj ju do USB portu boxu"));
}

let scanning = false, found = [];
function stepSpeaker(n) {
  const spk = (sys?.bt?.devices || []).filter((d) => d.speaker);
  const btn = (label, fn) => h("button", { onclick: fn }, label);
  const connect = async (mac, name) => {
    toast(`Pripájam ${name}…`, 8000);
    try { await api("POST", "/api/system/bt/connect", { mac }); toast(`${name} pripojený`); }
    catch (e) { toast("Nepodarilo sa: " + e.message + " (zapni na reproduktore párovanie)", 5000); }
    found = []; await loadSys(); renderSteps(true);
  };
  return step(n, "Bluetooth reproduktor",
    h("p", {}, "Zapni reproduktor a prepni ho do režimu párovania (bliká). Mobily od boxu odpoj – Bluetooth v boxe zvládne naraz len jeden smer."),
    spk.map((d) => row(d.connected ? true : null, `${d.connected ? "● " : ""}${d.name}${d.connected ? " · pripojený" : ""}`,
      d.connected ? null : btn("Pripojiť", () => connect(d.mac, d.name)))),
    found.map((d) => row(null, d.name, btn("Spárovať", () => connect(d.mac, d.name)))),
    h("button", { disabled: scanning, onclick: async () => {
      scanning = true; renderSteps(true);
      try { found = (await api("GET", "/api/system/bt/scan")).result; if (!found.length) toast("Nič som nenašiel – je reproduktor v režime párovania?"); }
      catch (e) { toast("Chyba: " + e.message); }
      scanning = false; renderSteps(true);
    } }, scanning ? h("span", {}, h("span", { class: "spin" }), " Hľadám (20 s)…") : "Hľadať reproduktory"));
}

function stepSource(n) {
  const opt = (id, title, hint) => h("button", { class: "opt" + (choice.source === id ? " on" : ""), onclick: () => { choice.source = id; renderSteps(true); } },
    h("span", { class: "r" }), h("span", {}, h("b", {}, title), h("small", {}, hint)));
  return step(n, "Odkiaľ pôjde hudba", h("div", { class: "opts" },
    opt("airplay", "AirPlay z iPhonu / iPadu", `Ovládacie centrum → AirPlay → ${NAME()}`),
    opt("spotify", "Spotify Connect", `V Spotify vyber zariadenie ${NAME()}`),
    opt("linein", "Kábel do UCA202", "DJ pult, PC, prehrávač")),
    step2Delay());
}
function step2Delay() {
  const out = h("output", {}, `${choice.delay_ms} ms`);
  const inp = h("input", { type: "range", min: 0, max: 500, step: 10, value: choice.delay_ms,
    oninput: (e) => { choice.delay_ms = +e.target.value; out.textContent = `${choice.delay_ms} ms`; } });
  return h("label", { style: "display:grid;gap:6px;font-size:14px;color:#a3a3b8" }, h("span", {}, "Oneskorenie svetiel za zvukom ", out), inp,
    h("span", { class: "small" }, "BT reproduktor hrá s oneskorením ~150–250 ms. Doladíš aj neskôr v Nastaveniach ovládania."));
}

function stepOutput(n) {
  const sinks = (sys?.audio?.sinks || []).filter((s) => s.kind !== "bluetooth");
  const vol = sys?.audio?.volume;
  return step(n, "Kam pôjde zvuk",
    sinks.length ? h("div", { class: "opts" }, sinks.map((s) =>
      h("button", { class: "opt" + (choice.output === s.name ? " on" : ""), onclick: () => { choice.output = s.name; renderSteps(true); } },
        h("span", { class: "r" }), h("span", {}, h("b", {}, s.label), h("small", {}, s.kind === "usb" ? "AUX reproduktora do výstupu UCA202" : s.kind === "jack" ? "Kábel do 3,5 mm jacku na Pi" : s.description)))))
      : row(false, "Žiadny zvukový výstup. Zapoj UCA202 do USB, alebo zapni jack na Pi (návod: Riešenie problémov v docs/PREVADZKA.md) a reštartuj box."),
    vol != null ? h("label", { style: "display:grid;gap:6px;font-size:14px;color:#a3a3b8" }, "Hlasitosť boxu",
      h("input", { type: "range", min: 0, max: 100, value: choice.volume ?? vol, onchange: (e) => { choice.volume = +e.target.value; } })) : null);
}

const meter = h("i");
const listenText = h("span", { class: "small" }, "…");
function stepListen(n) {
  return step(n, "Skúška zvuku",
    h("p", {}, "Pusti hudbu. Keď ju box počuje, ukáže tempo."),
    h("div", { class: "status-row" }, h("div", { class: "meter" }, meter), listenText));
}
function updateListen() {
  meter.style.width = `${Math.round((audio.silent ? 0 : audio.level) * 100)}%`;
  listenText.textContent = audio.silent ? "ticho – pusti hudbu" : `počujem hudbu · ${Math.round(audio.bpm)} BPM`;
  listenText.style.color = audio.silent ? "#a3a3b8" : "#6be3a0";
}

function stepStyle(n) {
  const fogOk = (sys?.dmx?.fixtures || []).some((f) => /fog|dym/i.test(f));
  return step(n, "Aká bude akcia",
    h("div", { class: "moods" }, STYLES.map(([id, title, hint]) =>
      h("button", { class: "mood" + (choice.style === id ? " on" : ""), onclick: () => { choice.style = id; renderSteps(true); } },
        h("b", {}, title), h("small", {}, hint)))),
    h("div", {},
      h("label", { class: "check" }, "Laser", h("input", { type: "checkbox", checked: choice.laser, onchange: (e) => { choice.laser = e.target.checked; } })),
      fogOk ? h("label", { class: "check" }, "Dym na drop", h("input", { type: "checkbox", checked: choice.fog_auto, onchange: (e) => { choice.fog_auto = e.target.checked; } })) : null));
}

function stepInfo(n, title, text) {
  return step(n, title, h("p", {}, text));
}

function renderSteps(keepScroll) {
  if (!choice) return;
  const y = window.scrollY;
  const box = $("#steps"); box.innerHTML = "";
  const id = choice.id;
  const add = (...els) => els.forEach((e) => e && box.append(e));
  if (id === "bt") add(stepPhone(1), stepOutput(2), stepListen(3), stepStyle(4));
  else if (id === "spotify") add(stepSpotify(1), stepOutput(2), stepListen(3), stepStyle(4));
  else if (id === "airplay") add(stepAirplay(1), stepOutput(2), stepListen(3), stepStyle(4));
  else if (id === "linein") add(stepLinein(1), stepOutput(2), stepListen(3), stepStyle(4));
  else if (id === "btspeaker") add(stepSpeaker(1), stepSource(2), stepListen(3), stepStyle(4));
  else if (id === "ambient") add(stepInfo(1, "Pokojné svetlá", "Svetlá pomaly menia farby a hlava sa pohybuje, hudba sa nepočúva. Stroboskop, laser ani dym nejdú. Späť na hudbu prepneš cez Scenáre."));
  else if (id === "demo") add(stepInfo(1, "Simulovaná hudba", "Box si sám „pustí“ DJ set (bez zvuku do reproduktora) a svetlá hrajú, akoby išla hudba. Žánre sa striedajú každú minútu."), stepStyle(2));
  updateListen();
  if (keepScroll) window.scrollTo(0, y);
}

// --- spustenie ------------------------------------------------------------------------
async function start(data) {
  const go = $("#go"); go.disabled = true;
  try {
    const r = await api("POST", "/api/scenario", data);
    if (r.warnings?.length) { toast(r.warnings.join(" · "), 5000); await new Promise((ok) => setTimeout(ok, 2500)); }
    location.href = "/ovladanie";
  } catch (e) {
    toast("Nepodarilo sa: " + e.message, 5000);
  } finally { go.disabled = false; }
}

// --- WebSocket: úroveň zvuku pre skúšku ---------------------------------------------------
function connectWs() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    audio = d.audio; settings = d.settings;
    updateListen();
  };
  ws.onclose = () => setTimeout(connectWs, 2000);
}

async function init() {
  $("#back").onclick = () => { if (history.state?.setup) history.back(); else { history.replaceState(null, "", location.pathname); closeSetup(); } };
  $("#go").onclick = () => start(choice);
  window.addEventListener("popstate", () => { if (!location.hash) closeSetup(); });
  const [sc, st] = await Promise.all([api("GET", "/api/scenarios"), api("GET", "/api/state"), loadSys()]);
  list = sc.scenarios; last = sc.last; settings = st.settings;
  renderChips(); renderHome();
  $("#brand-name").textContent = NAME(); document.title = NAME();
  const want = location.hash.slice(1);
  if (want && list.some((x) => x.id === want)) openSetup(want);
  connectWs();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}
init().catch((e) => toast("Chyba: " + e.message, 5000));

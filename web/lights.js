"use strict";
// Správa svetiel: mapa kanálov, zoznam, pridať/upraviť/vypnúť/zmazať, identifikovať, test kanálov, nový model.

const $ = (s) => document.querySelector(s);
const COLORS = ["#29d3ff", "#ff2e7e", "#ffc65a", "#6be3a0", "#b79bff", "#ff8a4c", "#7fe4ff", "#ff8fb8", "#c8f06a", "#9ab0ff"];
let rig = null, editing = null, testTimer = null;

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
  if (r.status === 401) { location.href = "/lock.html?next=/lights.html"; throw new Error("zadaj PIN"); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || r.statusText);
  return d;
}
function toast(msg, ms = 3000) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms);
}
function confirmBtn(label, confirmLabel, fn) {
  const b = h("button", {}, label);
  let armed = false, t;
  b.onclick = () => {
    if (!armed) { armed = true; b.textContent = confirmLabel; t = setTimeout(() => { armed = false; b.textContent = label; }, 3500); return; }
    clearTimeout(t); armed = false; fn();
  };
  return b;
}
const color = (id) => COLORS[rig.fixtures.findIndex((f) => f.id === id) % COLORS.length];
const pad3 = (n) => String(n).padStart(3, "0");
const profile = (id) => rig.profiles.find((p) => p.id === id);

// --- mapa kanálov a zoznam ------------------------------------------------------------
function renderMap() {
  const used = new Map();   // kanál → [fixture]
  for (const m of rig.map) for (let c = m.from; c <= m.to; c++) used.set(c, [...(used.get(c) || []), m]);
  const end = Math.max(48, ...rig.map.map((m) => m.to));
  const n = Math.min(512, Math.ceil((end + 4) / 16) * 16);
  const box = $("#chmap"); box.innerHTML = "";
  for (let c = 1; c <= n; c++) {
    const on = used.get(c) || [];
    const enabled = on.filter((m) => m.enabled);
    const m = on[0];
    const cell = h("span", { title: on.length ? `${c}: ${on.map((x) => x.label).join(", ")}` : `${c}: voľný` },
      m && c === m.from ? m.label : String(c));
    if (m) {
      cell.classList.add("used");
      cell.style.background = color(m.id);
      if (!enabled.length) cell.classList.add("off");
    }
    if (enabled.length > 1) {
      const mirror = enabled.every((x) => x.from === enabled[0].from) && rig.fixtures.some((f) => f.mirror && enabled.some((x) => x.id === f.id));
      if (!mirror) cell.classList.add("bad");
    }
    box.append(cell);
  }
  const lg = $("#legend"); lg.innerHTML = "";
  for (const m of rig.map) lg.append(h("span", { class: "tag-l" }, h("i", { style: `background:${color(m.id)}` }), `${m.label} ${m.from}–${m.to}${m.enabled ? "" : " (vypnuté)"}`));
  if (rig.dongle_limit) lg.append(h("span", { class: "tag-l", title: "Lacný USB-DMX dongle spoľahlivo zvláda asi toľko kanálov" }, `limit donglu ~${rig.dongle_limit}`));
}

function renderBanners(extra) {
  const b = $("#banners"); b.innerHTML = "";
  for (const e of rig.errors) b.append(h("div", { class: "banner bad" }, "Chyba v zozname: " + e));
  if (extra?.warning) b.append(h("div", { class: "banner warn" }, extra.warning));
}

function renderList() {
  const box = $("#list"); box.innerHTML = "";
  if (!rig.fixtures.length) box.append(h("div", { class: "item" }, h("span", { class: "muted" }, "Zatiaľ žiadne svetlá.")));
  for (const f of rig.fixtures) {
    box.append(h("div", { class: "fx-card", style: f.enabled ? "" : "opacity:.6" },
      h("div", { class: "fx-head" },
        h("span", { class: "label-chip", style: `background:${color(f.id)}` }, f.label),
        h("b", {}, f.name || f.model),
        f.enabled ? null : h("span", { class: "chip-s warn" }, "vypnuté"),
        f.mirror ? h("span", { class: "chip-s" }, "zrkadlené") : null,
        f.mount === "floor" ? h("span", { class: "chip-s" }, "na zemi") : null),
      h("div", { class: "small muted" }, `${f.model} · ${f.mode} · kanály ${f.address}–${f.end} · ${rig.positions[f.position] || "stred"}`),
      h("div", { class: "small" }, "Na svetle nastav adresu ", h("b", {}, pad3(f.address)), ` a mód ${f.mode.toUpperCase()}.`),
      h("div", { class: "fx-acts" },
        h("button", { onclick: () => identify(f) }, "Identifikovať"),
        h("button", { onclick: () => openTester(f) }, "Test kanálov"),
        h("button", { onclick: () => openEditor(f) }, "Upraviť"),
        h("button", { onclick: () => save(f.id, { enabled: !f.enabled }, f.enabled ? `${f.label} vypnuté` : `${f.label} zapnuté`) }, f.enabled ? "Vypnúť" : "Zapnúť"),
        confirmBtn("Zmazať", "Naozaj zmazať?", () => remove(f)))));
  }
}

function render(extra) { renderBanners(extra); renderMap(); renderList(); }

async function load() { rig = await api("GET", "/api/rig"); render(); }

async function save(id, body, msg) {
  try {
    rig = id ? await api("PUT", `/api/rig/fixture/${id}`, body) : await api("POST", "/api/rig/fixture", body);
    render(rig); if (msg) toast(msg); return true;
  } catch (e) { toast("Neuložené: " + e.message, 6000); return false; }
}
async function remove(f) {
  try { rig = await api("DELETE", `/api/rig/fixture/${f.id}`); render(rig); toast(`${f.label} zmazané (záloha ostala)`); }
  catch (e) { toast("Chyba: " + e.message); }
}
async function identify(f) {
  try { await api("POST", `/api/rig/identify/${f.id}`); toast(`${f.label} bliká na bielo 4 s`); }
  catch (e) { toast("Chyba: " + e.message); }
}

// --- pridať / upraviť ------------------------------------------------------------------------
function nextLabel() {
  let n = 1; const used = new Set(rig.fixtures.map((f) => f.label));
  while (used.has(`SVETLO${n}`)) n++;
  return `SVETLO${n}`;
}
function openEditor(f) {
  closeAll();
  editing = f ? { ...f } : { label: nextLabel(), name: "", profile: "generic-rgbw-par", mode: "", address: "", position: "center", mirror: false };
  if (!editing.mode) editing.mode = Object.keys(profile(editing.profile)?.modes || {})[0] || "";
  $("#ed-title").textContent = f ? `Upraviť ${f.label}` : "Nové svetlo";
  $("#editor").hidden = false;
  renderEditor();
  if (!f) findFree();
  $("#editor").scrollIntoView({ behavior: "smooth" });
}
function closeAll() {
  $("#editor").hidden = true; $("#tester").hidden = true; $("#profiler").hidden = true;
  stopTest();
}

let checkTimer = null;
function renderEditor() {
  const e = editing, form = $("#ed-form"); form.innerHTML = "";
  const prof = profile(e.profile);
  const groups = {};
  for (const p of rig.profiles) (groups[p.user ? "Moje modely" : "Knižnica"] ||= []).push(p);
  const sel = h("select", { class: "full", onchange: (ev) => {
    if (ev.target.value === "__new") { openProfiler(); return; }
    e.profile = ev.target.value; e.mode = Object.keys(profile(e.profile).modes)[0]; renderEditor(); check();
  } }, Object.entries(groups).map(([g, ps]) => h("optgroup", { label: g }, ps.map((p) => h("option", { value: p.id, selected: p.id === e.profile }, p.name)))),
    h("option", { value: "__new" }, "+ Nový model (podľa manuálu)…"));
  const modes = Object.keys(prof?.modes || {});
  const modeSel = h("select", { class: "full", onchange: (ev) => { e.mode = ev.target.value; check(); } },
    modes.map((m) => h("option", { value: m, selected: m === e.mode }, `${m} (${prof.modes[m].length} kanálov)`)));
  const label = h("input", { type: "text", value: e.label, maxlength: 12, autocapitalize: "characters", oninput: (ev) => { e.label = ev.target.value.toUpperCase(); check(); } });
  const name = h("input", { type: "text", value: e.name || "", placeholder: prof?.name || "napr. PAR vľavo", oninput: (ev) => { e.name = ev.target.value; } });
  const addr = h("input", { type: "text", inputmode: "numeric", value: e.address, id: "ed-addr", oninput: (ev) => { e.address = ev.target.value; check(); } });
  const pos = h("select", { class: "full", onchange: (ev) => { e.position = ev.target.value; } },
    Object.entries(rig.positions).map(([k, v]) => h("option", { value: k, selected: k === e.position }, v)));
  const mirror = h("input", { type: "checkbox", checked: !!e.mirror, onchange: (ev) => { e.mirror = ev.target.checked; check(); } });
  const isHead = prof?.type === "moving_head";
  const mount = isHead ? h("select", { class: "full", onchange: (ev) => { e.mount = ev.target.value; } },
    Object.entries(rig.mounts || {}).map(([k, v]) => h("option", { value: k, selected: k === (e.mount || "ceiling") }, v))) : null;
  form.append(...[
    h("label", { class: "f" }, "Model", sel),
    prof?.notes ? h("span", { class: "hint" }, prof.notes) : null,
    prof?.user ? h("button", { onclick: () => openProfiler(e) }, "Upraviť model (kanály, hodnoty)") : null,
    h("div", { class: "row2" }, h("label", { class: "f" }, "Mód", modeSel), h("label", { class: "f" }, "Značka (napr. SVETLO5)", label)),
    h("label", { class: "f" }, "Meno (nepovinné)", name),
    h("div", { class: "row2" },
      h("label", { class: "f" }, "DMX adresa (1–512)", addr),
      h("label", { class: "f" }, "Pozícia", pos)),
    h("button", { onclick: findFree }, "Nájsť voľnú adresu"),
    isHead ? h("label", { class: "f" }, "Montáž hlavy", mount,
      h("span", { class: "hint" }, "Na zemi box otočí pan aj tilt, aby pohyby mierili rovnako ako pri zavesenej – cez parket a nad hlavy, nie do očí.")) : null,
    h("label", { class: "check" }, h("span", {}, "Zrkadliť – rovnaký model na rovnakej adrese, svietia rovnako"), mirror),
    h("div", { id: "ed-check", class: "banner ok" }, "…"),
    h("div", { class: "row2" },
      h("button", { onclick: () => { closeAll(); } }, "Zrušiť"),
      h("button", { class: "toggle on", onclick: submit }, editing.id ? "Uložiť zmeny" : "Pridať svetlo"))].filter(Boolean));
  check();
}
async function check() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    const box = $("#ed-check"); if (!box) return;
    try {
      const r = await api("POST", "/api/rig/check", { ...editing, address: editing.address === "" ? 0 : editing.address });
      const end = (+editing.address || 0) + r.footprint - 1;
      if (!editing.address) { box.className = "banner warn"; box.textContent = `Model má ${r.footprint} kanálov. Zadaj adresu alebo ťukni „Nájsť voľnú“ (${r.free ?? "žiadna"}).`; return; }
      if (r.errors.length) { box.className = "banner bad"; box.textContent = r.errors.join(" · ") + (r.free ? ` – voľná je napr. ${r.free}.` : ""); }
      else { box.className = "banner ok"; box.textContent = `V poriadku: kanály ${editing.address}–${end}. Na svetle nastav ${pad3(editing.address)}.`; }
    } catch (e) { box.className = "banner bad"; box.textContent = e.message; }
  }, 250);
}
async function findFree() {
  try {
    const r = await api("POST", "/api/rig/check", { ...editing, address: 1 });
    if (r.free) { editing.address = r.free; const a = $("#ed-addr"); if (a) a.value = r.free; check(); }
    else toast("Nie je voľné miesto pre toľko kanálov");
  } catch (e) { toast(e.message); }
}
async function submit() {
  const e = editing;
  const body = { label: e.label, name: e.name, profile: e.profile, mode: e.mode, address: +e.address, position: e.position, mirror: !!e.mirror };
  if (profile(e.profile)?.type === "moving_head") body.mount = e.mount || "ceiling";
  if (await save(e.id, body, e.id ? `${e.label} uložené` : `${e.label} pridané – na svetle nastav adresu ${pad3(e.address)}`)) closeAll();
}

// --- test kanálov -----------------------------------------------------------------------------
let testVals = {};
function openTester(f) {
  closeAll();
  const prof = profile(f.profile);
  const chans = prof?.modes[f.mode] || [];
  testVals = Object.fromEntries(chans.map((c) => [c.name, 0]));
  $("#ts-title").textContent = `Test kanálov – ${f.label}`;
  const form = $("#ts-form"); form.innerHTML = "";
  form.append(h("span", { class: "hint" }, "Kým je test otvorený, svieti len toto svetlo s hodnotami nižšie. Ostatné svetlá sú zhasnuté."));
  chans.forEach((c, i) => {
    const out = h("output", {}, "0");
    form.append(h("label", { class: "f" }, h("span", {}, `${f.address + i} · ${c.name} `, h("small", {}, `(${rig.functions[c.fn] || c.fn})`)),
      h("div", { class: "slider" }, h("input", { type: "range", min: 0, max: 255, value: 0, oninput: (ev) => { testVals[c.name] = +ev.target.value; out.textContent = ev.target.value; sendTest(f); } }), out)));
  });
  form.append(h("button", { class: "toggle on", onclick: closeAll }, "Hotovo"));
  $("#tester").hidden = false;
  $("#tester").scrollIntoView({ behavior: "smooth" });
  sendTest(f);
  testTimer = setInterval(() => sendTest(f), 2000);    // udržiava test, kým je otvorený
}
let sending = false;
async function sendTest(f) {
  if (sending) return; sending = true;
  try { await api("POST", `/api/rig/test/${f.id}`, testVals); } catch { /* ignoruj */ }
  sending = false;
}
function stopTest() {
  if (testTimer) { clearInterval(testTimer); testTimer = null; api("POST", "/api/rig/test-stop").catch(() => {}); }
}

// --- nový model (editor kanálov podľa manuálu) ---------------------------------------------------
let draft = null;
function openProfiler(edit) {
  $("#editor").hidden = true;
  if (edit) {                                   // úprava existujúceho vlastného modelu
    const p = profile(edit.profile);
    draft = { id: p.id, name: p.name, type: p.type, mode: edit.mode,
      channels: (p.modes[edit.mode] || []).map((c) => ({ fn: c.fn, name: c.name, value: c.value ?? null })) };
  }
  draft = draft || { name: "", type: "par", mode: "", channels: [{ fn: "red" }, { fn: "green" }, { fn: "blue" }] };
  $("#profiler").hidden = false;
  $("#profiler h2").textContent = draft.id ? "Upraviť model" : "Nový model svetla";
  renderProfiler();
  $("#profiler").scrollIntoView({ behavior: "smooth" });
}
function renderProfiler() {
  const form = $("#pr-form"); form.innerHTML = "";
  const fnOpts = (sel) => Object.entries(rig.functions).map(([k, v]) => h("option", { value: k, selected: k === sel }, v));
  const count = h("input", { type: "text", inputmode: "numeric", value: draft.channels.length, onchange: (ev) => {
    const n = Math.max(1, Math.min(64, +ev.target.value || 1));
    while (draft.channels.length < n) draft.channels.push({ fn: "other" });
    draft.channels.length = n; renderProfiler();
  } });
  form.append(
    h("span", { class: "hint" }, "Podľa manuálu svetla: koľko kanálov má mód a čo robí každý kanál. Funkcia hovorí boxu, ako má kanál ovládať."),
    h("label", { class: "f" }, "Meno modelu", h("input", { type: "text", value: draft.name, placeholder: "napr. Stairville LED PAR 56", oninput: (ev) => { draft.name = ev.target.value; } })),
    h("div", { class: "row2" },
      h("label", { class: "f" }, "Typ", h("select", { class: "full", onchange: (ev) => { draft.type = ev.target.value; } },
        Object.entries(rig.types).map(([k, v]) => h("option", { value: k, selected: k === draft.type }, v)))),
      h("label", { class: "f" }, "Počet kanálov", count)),
    h("label", { class: "f" }, "Názov módu (nepovinné)", h("input", { type: "text", value: draft.mode, placeholder: `${draft.channels.length}ch`, oninput: (ev) => { draft.mode = ev.target.value; } })),
    h("span", { class: "hint" }, "Hodnota (nepovinné): pri funkcii Laser = čo poslať, keď má laser svietiť (bez nej 224 = zvukový mód). Pri Efekt / Makro / Program / Iné = pevná hodnota, ktorú box stále drží (napr. stred polohy). Prázdne = 0."),
    h("div", { class: "chrow hd" }, h("small", {}, ""), h("small", {}, "Funkcia"), h("small", {}, "Vlastný názov"), h("small", {}, "Hodnota")),
    ...draft.channels.map((c, i) => h("div", { class: "chrow" }, h("b", {}, `Kanál ${i + 1}`),
      h("select", { onchange: (ev) => { c.fn = ev.target.value; } }, fnOpts(c.fn)),
      h("input", { type: "text", placeholder: "vlastný názov", value: c.name || "", oninput: (ev) => { c.name = ev.target.value; } }),
      h("input", { type: "text", inputmode: "numeric", placeholder: "–", value: c.value ?? "", oninput: (ev) => { c.value = ev.target.value.trim() === "" ? null : ev.target.value.trim(); } }))),
    h("div", { class: "row2" },
      h("button", { onclick: () => { draft = null; $("#profiler").hidden = true; $("#editor").hidden = false; renderEditor(); } }, "Späť"),
      h("button", { class: "toggle on", onclick: saveProfile }, "Uložiť model")));
}
async function saveProfile() {
  try {
    rig = await api("POST", "/api/rig/profile", draft);
    const wasEdit = !!draft.id;
    editing.profile = rig.created; editing.mode = Object.keys(profile(rig.created).modes)[0];
    draft = null;
    if (wasEdit) { $("#profiler").hidden = true; $("#editor").hidden = false; renderEditor(); render(); toast("Model upravený – platí hneď"); return; }
    $("#profiler").hidden = true; $("#editor").hidden = false; renderEditor(); render();
    toast("Model uložený");
  } catch (e) { toast("Neuložené: " + e.message, 5000); }
}

// --- export / import ------------------------------------------------------------------------------
$("#export").onclick = async () => {
  const data = await api("GET", "/api/rig/export");
  const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })),
    download: `svetla-${new Date().toISOString().slice(0, 10)}.json` });
  document.body.append(a); a.click(); a.remove();
};
$("#import").onchange = async (ev) => {
  const file = ev.target.files[0]; if (!file) return;
  try { rig = await api("POST", "/api/rig/import", JSON.parse(await file.text())); render(rig); toast("Zoznam svetiel nahratý"); }
  catch (e) { toast("Import zlyhal: " + e.message, 6000); }
  ev.target.value = "";
};

$("#add").onclick = () => openEditor(null);
window.addEventListener("pagehide", stopTest);
load().catch((e) => toast("Chyba: " + e.message, 5000));

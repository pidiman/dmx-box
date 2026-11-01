"use strict";
// Zadanie PINu. Po úspechu server nastaví cookie (30 dní) a vrátime sa na pôvodnú stránku.

const $ = (s) => document.querySelector(s);
const MAX = 8;
let pin = "", busy = false;

function next() {
  const n = new URLSearchParams(location.search).get("next") || "/";
  return n.startsWith("/") && !n.startsWith("//") ? n : "/";
}
function paint() {
  const d = $("#dots"); d.innerHTML = "";
  const n = Math.max(4, pin.length);
  for (let i = 0; i < n; i++) { const e = document.createElement("i"); if (i < pin.length) e.className = "on"; d.append(e); }
}
async function submit() {
  if (busy || pin.length < 4) return;
  busy = true;
  try {
    const r = await fetch("/api/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ pin }) });
    const d = await r.json().catch(() => ({}));
    if (r.ok) { location.replace(next()); return; }
    $("#msg").textContent = d.detail || "Nesprávny PIN";
    $("#dots").classList.remove("bad"); void $("#dots").offsetWidth; $("#dots").classList.add("bad");
    pin = ""; paint();
  } catch { $("#msg").textContent = "Box neodpovedá"; }
  busy = false;
}
function press(k) {
  $("#msg").textContent = "";
  if (k === "del") pin = pin.slice(0, -1);
  else if (k === "ok") return submit();
  else if (pin.length < MAX) pin += k;
  paint();
}

const pad = $("#pad");
for (const k of ["1", "2", "3", "4", "5", "6", "7", "8", "9", "del", "0", "ok"]) {
  const b = document.createElement("button");
  b.textContent = k === "del" ? "Zmazať" : k === "ok" ? "OK" : k;
  if (k === "del" || k === "ok") b.className = "ghost";
  if (k === "ok") b.style.color = "var(--accent)";
  b.setAttribute("aria-label", k === "del" ? "Zmazať číslicu" : k === "ok" ? "Potvrdiť" : k);
  b.onclick = () => press(k);
  pad.append(b);
}
document.addEventListener("keydown", (e) => {
  if (/^[0-9]$/.test(e.key)) press(e.key);
  else if (e.key === "Backspace") press("del");
  else if (e.key === "Enter") press("ok");
});
paint();
// ak PIN nie je potrebný (vypnutý medzitým), rovno ďalej
fetch("/api/auth").then((r) => r.json()).then((d) => { if (!d.required || d.ok) location.replace(next()); }).catch(() => {});

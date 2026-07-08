"use strict";

const $ = (id) => document.getElementById(id);
const promptEl = $("prompt");
const irEl = $("ir");
const previewEl = $("preview");
const logEl = $("log");
const flyBtn = $("fly");
const validMsg = $("valid");
const compileMsg = $("compileMsg");

function setValid(ok, text) {
  validMsg.textContent = text || "";
  validMsg.className = "msg " + (ok ? "ok" : "bad");
  flyBtn.disabled = !ok;
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

async function compile() {
  const text = promptEl.value.trim();
  if (!text) return;
  compileMsg.textContent = "compiling…";
  compileMsg.className = "msg";
  const res = await postJSON("/api/compile", { text });
  if (res.ir) {
    irEl.value = JSON.stringify(res.ir, null, 2);
  }
  compileMsg.textContent = res.ir ? "parsed" : "";
  applyResult(res);
}

async function revalidate() {
  let ir;
  try {
    ir = JSON.parse(irEl.value);
  } catch (e) {
    setValid(false, "IR is not valid JSON: " + e.message);
    previewEl.textContent = "—";
    return;
  }
  const res = await postJSON("/api/preview", { ir });
  applyResult(res);
}

function applyResult(res) {
  if (res.valid) {
    previewEl.textContent = (res.preview || []).join("\n");
    setValid(true, "valid ✓");
  } else {
    previewEl.textContent = "—";
    setValid(false, res.error || "invalid");
  }
}

function fly() {
  let ir;
  try {
    ir = JSON.parse(irEl.value);
  } catch (e) {
    setValid(false, "IR is not valid JSON: " + e.message);
    return;
  }
  logEl.textContent = "";
  flyBtn.disabled = true;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/fly`);
  ws.onopen = () => ws.send(JSON.stringify({ ir }));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "log") appendLog(m.line);
    else if (m.type === "done") { appendLog("✔ mission complete"); flyBtn.disabled = false; }
    else if (m.type === "error") { appendLog("✖ " + m.message); flyBtn.disabled = false; }
  };
  ws.onerror = () => { appendLog("✖ websocket error"); flyBtn.disabled = false; };
  ws.onclose = () => { flyBtn.disabled = false; };
}

function appendLog(line) {
  logEl.textContent += (logEl.textContent ? "\n" : "") + line;
  logEl.scrollTop = logEl.scrollHeight;
}

async function health() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("health").textContent = `NL:${h.nl_backend} · ${h.pub}`;
  } catch { $("health").textContent = "offline"; }
}

$("compile").addEventListener("click", compile);
$("revalidate").addEventListener("click", revalidate);
flyBtn.addEventListener("click", fly);
irEl.addEventListener("input", () => setValid(false, "edited — re-validate"));
document.querySelectorAll("a.ex").forEach((a) =>
  a.addEventListener("click", (e) => {
    e.preventDefault();
    promptEl.value = a.textContent;
    compile();
  })
);
health();

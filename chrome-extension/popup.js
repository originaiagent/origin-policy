"use strict";

const $enabled = document.getElementById("enabled");
const $enabledLabel = document.getElementById("enabled-label");
const $logList = document.getElementById("log-list");
const $copy = document.getElementById("copy-log");
const $clear = document.getElementById("clear-log");

function send(type, extra) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type, ...(extra || {}) }, (resp) =>
      resolve(resp || {}),
    );
  });
}

async function refresh() {
  const cur = await chrome.storage.local.get({ enabled: true, log: [] });
  $enabled.checked = cur.enabled !== false;
  $enabledLabel.textContent = $enabled.checked ? "ON" : "OFF";
  renderLog(cur.log || []);
}

function renderLog(log) {
  if (!log.length) {
    $logList.textContent = "（検出ログなし）";
    return;
  }
  $logList.innerHTML = "";
  for (const e of log) {
    const row = document.createElement("div");
    row.className = `log-row sev-${e.severity || "warn"}`;
    const head = document.createElement("div");
    head.className = "log-head";
    head.textContent = `${e.ts || ""} [${e.rule}/${e.pattern_id}] ${e.severity}`;
    const body = document.createElement("div");
    body.className = "log-body";
    body.textContent = e.excerpt || "";
    row.appendChild(head);
    row.appendChild(body);
    $logList.appendChild(row);
  }
}

$enabled.addEventListener("change", async () => {
  await send("policy_gate.setEnabled", { enabled: $enabled.checked });
  $enabledLabel.textContent = $enabled.checked ? "ON" : "OFF";
});

$copy.addEventListener("click", async () => {
  const cur = await chrome.storage.local.get({ log: [] });
  const text = (cur.log || [])
    .map(
      (e) =>
        `${e.ts}\t${e.rule}/${e.pattern_id}\t${e.severity}\t${e.excerpt || ""}`,
    )
    .join("\n");
  try {
    await navigator.clipboard.writeText(text);
    $copy.textContent = "✅ コピー完了";
    setTimeout(() => ($copy.textContent = "違反ログをコピー"), 1500);
  } catch (e) {
    $copy.textContent = "❌ 失敗";
    setTimeout(() => ($copy.textContent = "違反ログをコピー"), 1500);
  }
});

$clear.addEventListener("click", async () => {
  await send("policy_gate.clearLog");
  refresh();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.log || changes.enabled) refresh();
});

refresh();

/**
 * Origin Policy Gate — service worker
 *
 * - Stores ON/OFF state and the recent detection log in chrome.storage.local.
 * - Provides a Lane 4 dashboard hook: when dashboard_url + dashboard_api_key
 *   are configured, future versions will POST log entries here. Phase 3 v1
 *   does not actually send (hook only).
 */

const LOG_LIMIT = 50;

chrome.runtime.onInstalled.addListener(async () => {
  const cur = await chrome.storage.local.get({ enabled: true, log: [] });
  await chrome.storage.local.set({
    enabled: cur.enabled !== false,
    log: Array.isArray(cur.log) ? cur.log : [],
  });
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== "object") return false;

  if (msg.type === "policy_gate.log") {
    const entries = Array.isArray(msg.entries) ? msg.entries : [];
    appendLog(entries).then(() => sendResponse({ ok: true }));
    return true; // async response
  }

  if (msg.type === "policy_gate.getLog") {
    chrome.storage.local.get({ log: [] }, (v) =>
      sendResponse({ ok: true, log: v.log || [] }),
    );
    return true;
  }

  if (msg.type === "policy_gate.clearLog") {
    chrome.storage.local.set({ log: [] }, () => sendResponse({ ok: true }));
    return true;
  }

  if (msg.type === "policy_gate.setEnabled") {
    const enabled = !!msg.enabled;
    chrome.storage.local.set({ enabled }, () =>
      sendResponse({ ok: true, enabled }),
    );
    return true;
  }

  return false;
});

// Serialize storage updates so concurrent appendLog calls cannot race
// (chrome.storage.local.get + set is not atomic).
let _logChain = Promise.resolve();
function appendLog(entries) {
  if (!entries.length) return Promise.resolve();
  _logChain = _logChain.then(async () => {
    const cur = await chrome.storage.local.get({ log: [] });
    const next = [...entries, ...(cur.log || [])].slice(0, LOG_LIMIT);
    await chrome.storage.local.set({ log: next });

    // Lane 4 hook (settings only — no fetch in Phase 3 v1).
    // const cfg = await chrome.storage.local.get({ dashboard_url: "", dashboard_api_key: "" });
    // if (cfg.dashboard_url && cfg.dashboard_api_key) { /* POST to dashboard */ }
  });
  return _logChain;
}

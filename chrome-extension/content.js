/**
 * Origin Policy Gate — content script
 *
 * Runs on https://claude.ai/*. Watches assistant message DOM nodes via
 * MutationObserver, scans new text against Tier 0 detectors loaded from
 * detectors.generated.js, displays banner + highlights on violations, and
 * intercepts the clipboard copy event to require explicit confirmation
 * when a violation is included in the selection.
 *
 * Detector source of truth: ../rules/tier0_detectors.yaml (committed via
 * detectors.generated.js — re-run scripts/build_detectors.js to refresh).
 */

(function () {
  "use strict";

  const D = window.__POLICY_GATE_DETECTORS__;
  if (!D) {
    console.warn("[policy-gate] detectors.generated.js not loaded; aborting.");
    return;
  }

  // --- State ---
  const STATE = {
    enabled: true,
    // Map of element → array of finding objects (ordered).
    findingsByNode: new WeakMap(),
    // Recent log (newest first), persisted via background.js.
    logBuffer: [],
  };

  const SELECTORS = [
    ".font-claude-message",
    '[data-testid="assistant-message"]',
    '[data-is-streaming]',
  ];

  // --- Storage hook (graceful if chrome.storage is unavailable) ---
  function loadEnabled() {
    if (!chrome?.storage?.local) return;
    chrome.storage.local.get({ enabled: true }, (v) => {
      STATE.enabled = v.enabled !== false;
    });
  }
  if (chrome?.storage?.onChanged) {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== "local") return;
      if (changes.enabled) STATE.enabled = changes.enabled.newValue !== false;
    });
  }
  loadEnabled();

  // --- R3 body/reference split ---
  // Note: \b does not work after Japanese kanji in JS regex (kanji are not
  // \w characters), so we match end-of-line / whitespace explicitly.
  const REFERENCE_HEADER_RE = /^\s*#{0,6}\s*参照(?:$|\s|:|：)/;
  function splitBodyAndReference(text) {
    const lines = text.split("\n");
    let refStart = -1;
    for (let i = 0; i < lines.length; i++) {
      if (REFERENCE_HEADER_RE.test(lines[i])) {
        refStart = i;
        break;
      }
      if (lines[i].trim() === "---" && i + 1 < lines.length) {
        if (REFERENCE_HEADER_RE.test(lines[i + 1])) {
          refStart = i;
          break;
        }
      }
    }
    if (refStart < 0) return { body: text, bodyOffset: 0 };
    const body = lines.slice(0, refStart).join("\n");
    return { body, bodyOffset: 0 };
  }

  // --- R3 excluded ranges (code blocks, URLs, file paths) ---
  const TRIPLE_BACKTICK_RE = /```[\s\S]*?```/g;
  const INLINE_BACKTICK_RE = /`[^`\n]+`/g;
  const URL_RE = /(?:https?|file|ftp):\/\/\S+/g;
  const FILE_PATH_RE =
    /(?:\.{0,2}\/[\w\-./]+\.[A-Za-z0-9]{1,8})|(?:[\w\-]+\/[\w\-./]+\.[A-Za-z0-9]{1,8})|(?:\/[\w\-./]+\/[\w\-]+)/g;

  function excludedRanges(text) {
    const ranges = [];
    function pushFrom(re) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(text)) !== null) {
        ranges.push([m.index, m.index + m[0].length]);
      }
    }
    pushFrom(TRIPLE_BACKTICK_RE);
    pushFrom(INLINE_BACKTICK_RE);
    pushFrom(URL_RE);
    pushFrom(FILE_PATH_RE);
    return ranges;
  }
  function isExcluded(start, end, ranges) {
    for (const [s, e] of ranges) {
      if (s <= start && end <= e) return true;
    }
    return false;
  }

  // --- Lite classifier (keyword match) ---
  // If any category keyword appears in the sentence, the question is treated
  // as classifiable into a human-judgment category and downgraded from BLOCK
  // (would-be R1 default) to WARN. No keyword → suspicious unclassifiable
  // question (still WARN by Phase-3 v1 policy; future versions may BLOCK).
  function classify(sentence) {
    for (const kw of D.category_keywords) {
      if (sentence.includes(kw)) return true;
    }
    return false;
  }

  function extractSentence(text, pos) {
    const boundary = "。！？!?\n";
    let s = pos;
    while (s > 0 && !boundary.includes(text[s - 1])) s--;
    let e = pos;
    while (e < text.length && !boundary.includes(text[e])) e++;
    return { text: text.slice(s, e).trim(), start: s, end: e };
  }

  // --- Detection ---
  function checkR3(text) {
    const findings = [];
    const { body } = splitBodyAndReference(text);
    const exc = excludedRanges(body);
    for (const p of D.r3_patterns) {
      const re = new RegExp(p.pattern, p.flags);
      let m;
      while ((m = re.exec(body)) !== null) {
        if (isExcluded(m.index, m.index + m[0].length, exc)) continue;
        findings.push({
          rule: "R3",
          pattern_id: p.id,
          severity: p.severity,
          message: p.message,
          match: m[0],
          start: m.index,
          end: m.index + m[0].length,
        });
        if (re.lastIndex === m.index) re.lastIndex++;
      }
    }
    return findings;
  }

  function checkR1(text) {
    const findings = [];
    const seenSentences = new Set();
    for (const t of D.r1_triggers) {
      const re = new RegExp(t.pattern, t.flags);
      let m;
      while ((m = re.exec(text)) !== null) {
        const matchStart = m.index;
        const matchEnd = m.index + m[0].length;
        if (t.type === "forbidden_phrase") {
          findings.push({
            rule: "R1",
            pattern_id: "forbidden_phrase",
            severity: t.severity || "block",
            message: t.message,
            match: m[0],
            start: matchStart,
            end: matchEnd,
          });
        } else if (t.type === "temptation_word") {
          findings.push({
            rule: "R1",
            pattern_id: "temptation_word",
            severity: t.severity || "warn",
            message: t.message,
            match: m[0],
            start: matchStart,
            end: matchEnd,
          });
        } else {
          // explicit_question / choice_offer / confirmation_request
          const sent = extractSentence(text, matchStart);
          if (seenSentences.has(sent.start)) {
            if (re.lastIndex === m.index) re.lastIndex++;
            continue;
          }
          seenSentences.add(sent.start);
          const classified = classify(sent.text);
          findings.push({
            rule: "R1",
            pattern_id: classified ? "classified_question" : "unclassifiable_question",
            severity: D.r1_default_question_severity || "warn",
            message: classified
              ? "質問・選択肢・確認依頼を検出（人間判断カテゴリの可能性）。爆速モード違反でないか確認。"
              : "質問・選択肢・確認依頼を検出（人間判断 13 カテゴリに該当しません）。AI 即決領域の可能性。",
            match: sent.text || m[0],
            start: matchStart,
            end: matchEnd,
            trigger_type: t.type,
          });
        }
        if (re.lastIndex === m.index) re.lastIndex++;
      }
    }
    return findings;
  }

  function checkExtraBakuso(text) {
    const findings = [];
    for (const p of D.extra_bakuso_patterns) {
      const re = new RegExp(p.pattern, p.flags);
      let m;
      while ((m = re.exec(text)) !== null) {
        findings.push({
          rule: "R1",
          pattern_id: p.id,
          severity: p.severity,
          message: p.message,
          match: m[0],
          start: m.index,
          end: m.index + m[0].length,
        });
        if (re.lastIndex === m.index) re.lastIndex++;
      }
    }
    return findings;
  }

  function detectAll(text) {
    return [...checkR3(text), ...checkR1(text), ...checkExtraBakuso(text)];
  }

  // --- Banner & highlight UI ---
  function ensureBanner(node, severity) {
    let banner = node.querySelector(":scope > .__pgate-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "__pgate-banner";
      node.insertBefore(banner, node.firstChild);
    }
    banner.dataset.severity = severity;
    banner.classList.toggle("__pgate-block", severity === "block");
    banner.classList.toggle("__pgate-warn", severity === "warn");
    return banner;
  }

  function renderBanner(node, findings) {
    if (!findings.length) return;
    const hasBlock = findings.some((f) => f.severity === "block");
    const sev = hasBlock ? "block" : "warn";
    const banner = ensureBanner(node, sev);
    const ruleSummary = [...new Set(findings.map((f) => f.rule))].join(", ");
    const matches = findings
      .map((f) => `[${f.rule}/${f.pattern_id}] ${truncate(f.match, 60)}`)
      .slice(0, 5)
      .join(" / ");
    banner.innerHTML = "";
    const label = document.createElement("strong");
    label.textContent =
      sev === "block"
        ? `🚫 Policy Gate BLOCK — ${ruleSummary}`
        : `⚠ Policy Gate WARN — ${ruleSummary}`;
    const detail = document.createElement("div");
    detail.className = "__pgate-detail";
    detail.textContent = matches;
    const bypass = document.createElement("button");
    bypass.type = "button";
    bypass.className = "__pgate-bypass";
    bypass.textContent = "誤検知として続行";
    bypass.addEventListener("click", () => {
      node.dataset.pgateBypassed = "1";
      banner.remove();
      clearHighlights(node);
    });
    banner.appendChild(label);
    banner.appendChild(detail);
    banner.appendChild(bypass);
  }

  function truncate(s, n) {
    s = (s || "").replace(/\s+/g, " ").trim();
    return s.length > n ? s.slice(0, n) + "…" : s;
  }

  // Highlight matches at exact offsets, computed against the same flat-text
  // representation that detectAll() saw (textContent of the body portion only).
  // We use Range.surroundContents — no innerHTML, no string templating, so
  // assistant content that happens to look like HTML can never escape.
  // Findings carry start/end in the body text, so exempt occurrences (code
  // blocks, 参照 section, URLs) are not highlighted.
  function highlightFindings(node, findings) {
    if (!findings.length) return;
    // Build a flat-position → text-node map identical to what detection used.
    // We must match what splitBodyAndReference fed into the detectors:
    //   text = node.textContent ; body = first part before 「参照」 marker.
    // The findings' offsets are relative to `body`. Since our highlight target
    // is the same node tree, walking textContent accumulates the same
    // characters in the same order. Findings that fall after the 参照 cutoff
    // are skipped (they would have been excluded by R3 anyway).
    const ranges = [];
    for (const f of findings) {
      if (typeof f.start !== "number" || typeof f.end !== "number") continue;
      ranges.push({ start: f.start, end: f.end });
    }
    if (!ranges.length) return;

    // Sort + merge overlapping ranges so surroundContents won't be called on
    // nested ranges.
    ranges.sort((a, b) => a.start - b.start);
    const merged = [];
    for (const r of ranges) {
      const last = merged[merged.length - 1];
      if (last && r.start <= last.end) {
        last.end = Math.max(last.end, r.end);
      } else {
        merged.push({ ...r });
      }
    }

    // Walk text nodes, mapping flat offsets to DOM positions.
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) =>
        n.parentElement && n.parentElement.closest(".__pgate-banner, .__pgate-mark")
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT,
    });
    const segments = [];
    let pos = 0;
    let cur;
    while ((cur = walker.nextNode())) {
      const len = cur.nodeValue.length;
      segments.push({ node: cur, start: pos, end: pos + len });
      pos += len;
    }

    function locate(offset) {
      // Binary search by start; segments are ordered.
      for (const s of segments) {
        if (offset >= s.start && offset <= s.end) {
          return { node: s.node, offsetInNode: offset - s.start };
        }
      }
      return null;
    }

    // Apply highlights in reverse order so earlier indices stay valid as we
    // mutate the DOM after each surroundContents.
    for (let i = merged.length - 1; i >= 0; i--) {
      const r = merged[i];
      const startLoc = locate(r.start);
      const endLoc = locate(r.end);
      if (!startLoc || !endLoc) continue;
      const range = document.createRange();
      try {
        range.setStart(startLoc.node, startLoc.offsetInNode);
        range.setEnd(endLoc.node, endLoc.offsetInNode);
        const mark = document.createElement("mark");
        mark.className = "__pgate-mark";
        // surroundContents throws if the range partially intersects a non-text
        // node boundary. In that case, fall back to extractContents+wrap.
        try {
          range.surroundContents(mark);
        } catch (_e) {
          const frag = range.extractContents();
          mark.appendChild(frag);
          range.insertNode(mark);
        }
      } catch (_outer) {
        // Range setup failed (e.g. nodes were removed mid-scan). Skip.
      }
    }
  }

  function clearHighlights(node) {
    node.querySelectorAll(".__pgate-mark").forEach((el) => {
      const parent = el.parentNode;
      if (!parent) return;
      while (el.firstChild) parent.insertBefore(el.firstChild, el);
      parent.removeChild(el);
      parent.normalize();
    });
  }

  // --- Logging (push to background.js for persistence) ---
  function logFindings(findings) {
    if (!findings.length) return;
    const entries = findings.map((f) => ({
      ts: new Date().toISOString(),
      rule: f.rule,
      pattern_id: f.pattern_id,
      severity: f.severity,
      excerpt: truncate(f.match, 80),
    }));
    STATE.logBuffer.unshift(...entries);
    if (STATE.logBuffer.length > 50) STATE.logBuffer.length = 50;
    if (chrome?.runtime?.sendMessage) {
      chrome.runtime.sendMessage({ type: "policy_gate.log", entries }, () => {
        // Ignore lastError — popup may not be open.
        void chrome.runtime.lastError;
      });
    }
  }

  // --- Per-node scan ---
  // Uses textContent (not innerText) to avoid forcing a layout/reflow on
  // every streamed character. Detection findings carry exact offsets so
  // highlightFindings can target them precisely.
  function scanNode(node) {
    if (!STATE.enabled) return;
    if (node.dataset.pgateBypassed === "1") return;
    const text = node.textContent || "";
    if (!text.trim()) return;
    const findings = detectAll(text);
    const prev = STATE.findingsByNode.get(node) || [];
    // Avoid re-rendering if findings haven't changed in count + matches.
    if (
      prev.length === findings.length &&
      prev.every((p, i) => p.match === findings[i].match)
    ) {
      return;
    }
    STATE.findingsByNode.set(node, findings);
    if (findings.length) {
      // Clear stale highlights before re-applying so offsets stay correct.
      clearHighlights(node);
      renderBanner(node, findings);
      highlightFindings(node, findings);
      logFindings(findings);
    } else {
      const banner = node.querySelector(":scope > .__pgate-banner");
      if (banner) banner.remove();
      clearHighlights(node);
    }
    node.dataset.pgateChecked = "1";
  }

  function isAssistantNode(el) {
    if (!(el instanceof Element)) return false;
    return SELECTORS.some((sel) => el.matches?.(sel) || el.closest?.(sel));
  }

  function findCandidates(root) {
    const set = new Set();
    for (const sel of SELECTORS) {
      root.querySelectorAll?.(sel).forEach((el) => set.add(el));
    }
    return [...set];
  }

  // --- MutationObserver ---
  // Performance: streaming responses fire characterData mutations dozens of
  // times per second. We coalesce dirty nodes and process them once per
  // animation frame, with a small additional setTimeout backoff so a busy
  // streaming token-by-token update doesn't fire detection on every keystroke.
  const SCAN_DEBOUNCE_MS = 120;
  const _pendingScans = new Set();
  let _scanScheduled = null;
  function scheduleScan(node) {
    _pendingScans.add(node);
    if (_scanScheduled) return;
    _scanScheduled = setTimeout(() => {
      _scanScheduled = null;
      const todo = [..._pendingScans];
      _pendingScans.clear();
      todo.forEach((n) => {
        if (n.isConnected) scanNode(n);
      });
    }, SCAN_DEBOUNCE_MS);
  }

  const observer = new MutationObserver((mutations) => {
    if (!STATE.enabled) return;
    for (const m of mutations) {
      if (m.type === "childList") {
        for (const n of m.addedNodes) {
          if (!(n instanceof Element)) continue;
          findCandidates(n).forEach(scheduleScan);
          if (isAssistantNode(n)) scheduleScan(n);
        }
      } else if (m.type === "characterData") {
        const parent = m.target?.parentElement?.closest?.(SELECTORS.join(","));
        if (parent) scheduleScan(parent);
      }
    }
  });

  function findObserveRoot() {
    // Prefer a narrower root than document.body to reduce mutation traffic.
    return (
      document.querySelector("main") ||
      document.querySelector('[role="main"]') ||
      document.body
    );
  }

  function startObserver() {
    const root = findObserveRoot();
    observer.observe(root, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    findCandidates(root).forEach(scheduleScan);
  }

  // --- Clipboard intercept ---
  // We listen at capture phase so we run before React handlers. If the current
  // selection includes any node that has been flagged with BLOCK-severity
  // findings, we cancel the copy and prompt the user. On confirmation we
  // re-inject the text via navigator.clipboard.writeText (async, but the
  // user gesture is preserved through the modal click).
  document.addEventListener(
    "copy",
    (event) => {
      if (!STATE.enabled) return;
      const sel = window.getSelection?.();
      if (!sel || sel.isCollapsed) return;
      const flagged = collectFlaggedInSelection(sel);
      if (!flagged.length) return;

      event.preventDefault();
      const text = sel.toString();
      showCopyConfirmModal(flagged, () => {
        navigator.clipboard.writeText(text).catch((e) => {
          console.warn("[policy-gate] writeText failed", e);
        });
      });
    },
    true,
  );

  function collectFlaggedInSelection(sel) {
    const out = [];
    for (let i = 0; i < sel.rangeCount; i++) {
      const r = sel.getRangeAt(i);
      const candidates = new Set();
      const walker = document.createTreeWalker(
        r.commonAncestorContainer,
        NodeFilter.SHOW_ELEMENT,
        null,
      );
      let cur = walker.currentNode;
      while (cur) {
        if (cur instanceof Element && r.intersectsNode(cur)) {
          if (
            cur.dataset?.pgateChecked === "1" &&
            cur.dataset?.pgateBypassed !== "1"
          ) {
            const findings = STATE.findingsByNode.get(cur);
            if (findings && findings.some((f) => f.severity === "block")) {
              candidates.add(cur);
            }
          }
        }
        cur = walker.nextNode();
      }
      candidates.forEach((c) => out.push(c));
    }
    return out;
  }

  function showCopyConfirmModal(flagged, onConfirm) {
    const existing = document.querySelector(".__pgate-modal-backdrop");
    if (existing) existing.remove();

    const backdrop = document.createElement("div");
    backdrop.className = "__pgate-modal-backdrop";

    const modal = document.createElement("div");
    modal.className = "__pgate-modal";
    backdrop.appendChild(modal);

    const title = document.createElement("h2");
    title.textContent = "🚫 違反内容コピー阻止";
    modal.appendChild(title);

    const body = document.createElement("p");
    body.textContent =
      "コピー対象に Tier 0 BLOCK 違反が含まれています。本当にコピーしますか?";
    modal.appendChild(body);

    const list = document.createElement("ul");
    flagged.slice(0, 5).forEach((node) => {
      const findings = STATE.findingsByNode.get(node) || [];
      findings
        .filter((f) => f.severity === "block")
        .slice(0, 3)
        .forEach((f) => {
          const li = document.createElement("li");
          li.textContent = `[${f.rule}/${f.pattern_id}] ${truncate(f.match, 60)}`;
          list.appendChild(li);
        });
    });
    modal.appendChild(list);

    const buttons = document.createElement("div");
    buttons.className = "__pgate-modal-buttons";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "__pgate-cancel";
    cancel.textContent = "キャンセル（コピーしない）";
    cancel.addEventListener("click", () => backdrop.remove());
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "__pgate-confirm";
    confirm.textContent = "それでもコピー";
    confirm.addEventListener("click", () => {
      backdrop.remove();
      onConfirm();
    });
    buttons.appendChild(cancel);
    buttons.appendChild(confirm);
    modal.appendChild(buttons);

    document.body.appendChild(backdrop);
  }

  // --- Bootstrap ---
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startObserver);
  } else {
    startObserver();
  }
})();

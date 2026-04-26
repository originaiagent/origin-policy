/**
 * test_detection.js — minimal Node-side smoke test for the JS-ported detectors.
 *
 * Loads detectors.generated.js into a sandboxed `window` and exercises a few
 * representative violations to confirm the regex patterns + lite classifier
 * behave as expected. Run with:
 *
 *   node chrome-extension/tests/test_detection.js
 *
 * Exits 1 on any failure.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..");
const generated = fs.readFileSync(
  path.join(root, "detectors.generated.js"),
  "utf-8",
);

const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(generated, sandbox);
const D = sandbox.window.__POLICY_GATE_DETECTORS__;

function assert(cond, msg) {
  if (!cond) {
    console.error(`FAIL: ${msg}`);
    process.exitCode = 1;
  } else {
    console.log(`PASS: ${msg}`);
  }
}

// --- Mirror of the detection helpers in content.js (kept in sync manually
// — these tests guard the regex + classifier behaviour, not the DOM glue).

const REFERENCE_HEADER_RE = /^\s*#{0,6}\s*参照(?:$|\s|:|：)/;
function splitBody(text) {
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (REFERENCE_HEADER_RE.test(lines[i])) return lines.slice(0, i).join("\n");
    if (
      lines[i].trim() === "---" &&
      i + 1 < lines.length &&
      REFERENCE_HEADER_RE.test(lines[i + 1])
    ) {
      return lines.slice(0, i).join("\n");
    }
  }
  return text;
}

const TRIPLE = /```[\s\S]*?```/g;
const INLINE = /`[^`\n]+`/g;
const URL = /(?:https?|file|ftp):\/\/\S+/g;
const FILE_PATH =
  /(?:\.{0,2}\/[\w\-./]+\.[A-Za-z0-9]{1,8})|(?:[\w\-]+\/[\w\-./]+\.[A-Za-z0-9]{1,8})|(?:\/[\w\-./]+\/[\w\-]+)/g;
function ranges(t) {
  const out = [];
  for (const re of [TRIPLE, INLINE, URL, FILE_PATH]) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(t)) !== null) out.push([m.index, m.index + m[0].length]);
  }
  return out;
}
function inExc(s, e, rs) {
  return rs.some(([a, b]) => a <= s && e <= b);
}

function detectR3(text) {
  const body = splitBody(text);
  const exc = ranges(body);
  const found = [];
  for (const p of D.r3_patterns) {
    const re = new RegExp(p.pattern, p.flags);
    let m;
    while ((m = re.exec(body)) !== null) {
      if (inExc(m.index, m.index + m[0].length, exc)) {
        if (re.lastIndex === m.index) re.lastIndex++;
        continue;
      }
      found.push({ id: p.id, severity: p.severity, match: m[0] });
      if (re.lastIndex === m.index) re.lastIndex++;
    }
  }
  return found;
}

function classify(sentence) {
  return D.category_keywords.some((kw) => sentence.includes(kw));
}

function detectR1(text) {
  const found = [];
  const seen = new Set();
  for (const t of D.r1_triggers) {
    const re = new RegExp(t.pattern, t.flags);
    let m;
    while ((m = re.exec(text)) !== null) {
      if (t.type === "forbidden_phrase") {
        found.push({ id: "forbidden_phrase", severity: t.severity || "block", match: m[0] });
      } else if (t.type === "temptation_word") {
        found.push({ id: "temptation_word", severity: t.severity || "warn", match: m[0] });
      } else {
        // sentence-level — find boundaries and classify
        const boundary = "。！？!?\n";
        let s = m.index;
        while (s > 0 && !boundary.includes(text[s - 1])) s--;
        let e = m.index;
        while (e < text.length && !boundary.includes(text[e])) e++;
        if (seen.has(s)) {
          if (re.lastIndex === m.index) re.lastIndex++;
          continue;
        }
        seen.add(s);
        const sent = text.slice(s, e).trim();
        const isClassified = classify(sent);
        found.push({
          id: isClassified ? "classified_question" : "unclassifiable_question",
          severity: D.r1_default_question_severity || "warn",
          match: sent,
        });
      }
      if (re.lastIndex === m.index) re.lastIndex++;
    }
  }
  return found;
}

function detectExtra(text) {
  const found = [];
  for (const p of D.extra_bakuso_patterns) {
    const re = new RegExp(p.pattern, p.flags);
    let m;
    while ((m = re.exec(text)) !== null) {
      found.push({ id: p.id, severity: p.severity, match: m[0] });
      if (re.lastIndex === m.index) re.lastIndex++;
    }
  }
  return found;
}

// --- Test cases ---

// 1. R3 full UUID in body → BLOCK
{
  const t = "Phase の続き。タスク id は aabbccdd-1234-5678-9abc-def012345678 です。";
  const r3 = detectR3(t);
  assert(
    r3.some((f) => f.id === "full_uuid" && f.severity === "block"),
    "R3 detects full UUID in body as BLOCK",
  );
}

// 2. R3 full UUID inside 「参照」 section → exempt
{
  const t = `本文です。\n\n## 参照\n- task_id: aabbccdd-1234-5678-9abc-def012345678\n`;
  const r3 = detectR3(t);
  assert(
    !r3.some((f) => f.id === "full_uuid"),
    "R3 exempts UUID inside 参照 section",
  );
}

// 3. R3 Phase ID in body → BLOCK
{
  const t = "次は Phase2a に着手します。";
  const r3 = detectR3(t);
  assert(
    r3.some((f) => f.id === "phase_id" && f.severity === "block"),
    "R3 detects Phase2a as BLOCK",
  );
}

// 4. R3 short UUID in code block → exempt
{
  const t = "コードは `aabbccdd` を参照してください。";
  const r3 = detectR3(t);
  assert(
    !r3.some((f) => f.id === "short_uuid"),
    "R3 exempts short UUID inside inline code",
  );
}

// 5. R1 forbidden_phrase (即決すべきなら) → BLOCK
{
  const t = "即決すべきなら言ってください。";
  const r1 = detectR1(t);
  assert(
    r1.some((f) => f.id === "forbidden_phrase" && f.severity === "block"),
    "R1 detects forbidden phrase '即決すべきなら' as BLOCK",
  );
}

// 6. R1 explicit_question (どちらにしますか) → WARN (Phase 3 v1 default)
{
  const t = "AとBどちらにしますか?";
  const r1 = detectR1(t);
  assert(
    r1.some((f) => f.id?.includes("question") && f.severity === "warn"),
    "R1 detects 'どちらにしますか' as WARN (Phase 3 v1 default)",
  );
}

// 7. R1 temptation_word (念のため) → WARN
{
  const t = "念のため確認させてください。";
  const r1 = detectR1(t);
  assert(
    r1.some((f) => f.id === "temptation_word" && f.severity === "warn"),
    "R1 detects '念のため' as WARN",
  );
}

// 8. extra_bakuso_word (区切り良いので) → WARN
{
  const t = "区切り良いので一旦止めます。";
  const extra = detectExtra(t);
  assert(
    extra.some((f) => f.id === "extra_bakuso_word" && f.severity === "warn"),
    "extra_bakuso detects '区切り良いので' as WARN",
  );
}

// 9. extra_bakuso_word (お疲れ様) → WARN
{
  const t = "本日はお疲れ様でした。";
  const extra = detectExtra(t);
  assert(
    extra.some((f) => f.id === "extra_bakuso_word" && f.severity === "warn"),
    "extra_bakuso detects 'お疲れ様' as WARN",
  );
}

// 10. clean text → no findings
{
  const t = "実装完了。テストも全部 PASS しました。";
  const r3 = detectR3(t);
  const r1 = detectR1(t);
  const extra = detectExtra(t);
  assert(
    r3.length === 0 && r1.length === 0 && extra.length === 0,
    "clean text triggers no findings",
  );
}

if (process.exitCode === 1) {
  console.error("\n❌ Some tests failed");
  process.exit(1);
} else {
  console.log("\n✅ All tests passed");
}

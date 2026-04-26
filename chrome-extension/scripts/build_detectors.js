#!/usr/bin/env node
/**
 * build_detectors.js
 *
 * Reads:
 *   - ../../rules/tier0_detectors.yaml   (origin-policy 正本、変更不可)
 *   - ../local_rules.yaml                 (拡張ローカル補完)
 *   - ../../rules/human_judgment_categories.yaml (R1 軽量分類器の keyword 源)
 *
 * Writes:
 *   - ../detectors.generated.js
 *
 * The output file is committed to the repo so the unpacked extension works
 * out of the box (no Node runtime required at load time).
 *
 * Run:
 *   node chrome-extension/scripts/build_detectors.js
 */

const fs = require("fs");
const path = require("path");

// Use a tiny built-in YAML parser (subset). To avoid adding a dependency to
// the extension itself, we shell out to Python (already used by policy_gate)
// for YAML parsing — we only need this at build time, not runtime.
const { execSync } = require("child_process");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const TIER0_YAML = path.join(REPO_ROOT, "rules", "tier0_detectors.yaml");
const CATEGORIES_YAML = path.join(REPO_ROOT, "rules", "human_judgment_categories.yaml");
const LOCAL_YAML = path.join(REPO_ROOT, "chrome-extension", "local_rules.yaml");
const OUTPUT = path.join(REPO_ROOT, "chrome-extension", "detectors.generated.js");

function loadYaml(filePath) {
  const py = `import json, sys, yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1], encoding='utf-8')), default=str))`;
  const out = execSync(`python3 -c "${py.replace(/"/g, '\\"')}" "${filePath}"`, {
    encoding: "utf-8",
  });
  return JSON.parse(out);
}

/**
 * Convert a Python re.UNICODE-style regex into a JS RegExp source + flags pair.
 * Handles inline flags like (?i) which are valid in Python but not in JS,
 * by stripping them and adding the equivalent JS flag.
 */
function pyRegexToJs(re) {
  let flags = "g"; // global so multiple matches in a string work
  let pattern = re;
  // Strip leading inline flags such as (?i), (?im), etc.
  const inline = pattern.match(/^\(\?([imsxu]+)\)/);
  if (inline) {
    pattern = pattern.slice(inline[0].length);
    if (inline[1].includes("i")) flags += "i";
    if (inline[1].includes("m")) flags += "m";
    if (inline[1].includes("s")) flags += "s";
    if (inline[1].includes("u")) flags += "u";
  }
  return { pattern, flags };
}

function extractKeywords(categoriesDoc) {
  // Build a flat keyword list that, if any token appears in a question
  // sentence, allows the question to "classify" into a human-judgment
  // category (→ severity downgraded from BLOCK to WARN).
  // Source of truth: rules/human_judgment_categories.yaml.
  const keywords = new Set();
  for (const cat of categoriesDoc.categories || []) {
    if (cat.label) {
      // tokenize labels lightly (split on punctuation / spaces)
      cat.label
        .split(/[\s・、。()（）\/]+/)
        .filter((s) => s.length >= 2)
        .forEach((s) => keywords.add(s));
    }
    for (const ex of cat.examples || []) {
      // Each example is a phrase; we extract notable nouns by splitting on
      // particles. This is a crude heuristic — false-positives (= classified
      // as human judgment, downgraded to WARN) are preferred over BLOCK.
      ex.split(/[\s・、。()（）\/「」]+/)
        .filter((s) => s.length >= 2)
        .forEach((s) => keywords.add(s));
    }
    for (const ex of cat.examples_human || []) {
      ex.split(/[\s・、。()（）\/「」]+/)
        .filter((s) => s.length >= 2)
        .forEach((s) => keywords.add(s));
    }
  }
  return [...keywords].sort();
}

function main() {
  const tier0 = loadYaml(TIER0_YAML);
  const categories = loadYaml(CATEGORIES_YAML);
  const local = fs.existsSync(LOCAL_YAML) ? loadYaml(LOCAL_YAML) : {};

  // R3 patterns
  const r3 = (tier0.r3_internal_id_in_body || {}).patterns || [];

  // R1 patterns
  const r1Spec = tier0.r1_question_detection || {};
  const r1Triggers = r1Spec.trigger_patterns || [];

  // Local extra bakuso words → append as additional WARN patterns
  const extra = (local.extra_bakuso_violation_words || {}).patterns || [];

  // Category keywords for the lite classifier
  const categoryKeywords = extractKeywords(categories);

  const data = {
    schema_version: "1.0",
    generated_at: new Date().toISOString(),
    source: {
      tier0: "rules/tier0_detectors.yaml",
      categories: "rules/human_judgment_categories.yaml",
      local: "chrome-extension/local_rules.yaml",
    },
    r3_patterns: r3.map((p) => {
      const { pattern, flags } = pyRegexToJs(p.regex);
      return {
        id: p.id,
        pattern,
        flags,
        severity: p.severity || "block",
        message: p.message || "",
      };
    }),
    r1_triggers: r1Triggers.map((p) => {
      const { pattern, flags } = pyRegexToJs(p.regex);
      return {
        pattern,
        flags,
        type: p.type || "explicit_question",
        severity: p.severity || null,
        message: p.message || "",
      };
    }),
    extra_bakuso_patterns: extra.map((p) => {
      const { pattern, flags } = pyRegexToJs(p.regex);
      return {
        id: p.id,
        pattern,
        flags,
        severity: p.severity || "warn",
        message: p.message || "",
      };
    }),
    category_keywords: categoryKeywords,
    // Phase-3 v1 policy: explicit_question / choice_offer / confirmation_request
    // are downgraded from BLOCK to WARN by default to avoid false-positive
    // disruption (Gemini design review CONCERN #1). Forbidden phrases stay BLOCK.
    r1_default_question_severity: "warn",
  };

  const banner = `// AUTO-GENERATED by chrome-extension/scripts/build_detectors.js
// Source: rules/tier0_detectors.yaml + rules/human_judgment_categories.yaml + chrome-extension/local_rules.yaml
// DO NOT EDIT — re-run \`node chrome-extension/scripts/build_detectors.js\` to regenerate.
`;
  const body =
    banner +
    "\nwindow.__POLICY_GATE_DETECTORS__ = " +
    JSON.stringify(data, null, 2) +
    ";\n";

  fs.writeFileSync(OUTPUT, body, "utf-8");
  console.log(`Wrote ${OUTPUT}`);
  console.log(
    `  R3 patterns: ${data.r3_patterns.length}, R1 triggers: ${data.r1_triggers.length}, extra bakuso: ${data.extra_bakuso_patterns.length}, category keywords: ${data.category_keywords.length}`,
  );
}

main();

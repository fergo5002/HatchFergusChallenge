const STORAGE_KEY = "hatch-ranker-source-records-v1";
const REQUIRED_FIELDS = ["ref", "title", "one_liner", "example_customer", "wedge"];

const nodes = {
  input: document.querySelector("#json-input"),
  file: document.querySelector("#json-file"),
  replace: document.querySelector("#replace-button"),
  append: document.querySelector("#append-button"),
  clear: document.querySelector("#clear-button"),
  export: document.querySelector("#export-button"),
  aiScan: document.querySelector("#ai-scan-button"),
  aiStatus: document.querySelector("#ai-scan-status"),
  status: document.querySelector("#status-message"),
  errors: document.querySelector("#error-list"),
  cards: document.querySelector("#cards"),
  empty: document.querySelector("#empty-state"),
  storedCount: document.querySelector("#stored-count"),
  summary: document.querySelector("#summary-stats"),
  rankingPanel: document.querySelector("#ranking"),
  tierSummary: document.querySelector("#tier-summary"),
};

const TIER_ORDER = [
  ["Top Tier", "top"],
  ["Strong", "strong"],
  ["Watch", "watch"],
  ["Lagging", "watch"],
  ["Trap", "trap"],
];

const TIER_MODIFIERS = new Map(TIER_ORDER);

let records = loadRecords();
let currentRanking = [];
let aiScanHasRun = false;
let rankingBusy = false;
let aiScanBusy = false;

nodes.replace.addEventListener("click", () => handleImport("replace"));
nodes.append.addEventListener("click", () => handleImport("append"));
nodes.clear.addEventListener("click", clearRecords);
nodes.export.addEventListener("click", exportSourceJson);
nodes.aiScan.addEventListener("click", runAiScan);
nodes.file.addEventListener("change", loadFileIntoTextarea);

renderStoredCount();
syncAiScanButton();
if (records.length > 0) {
  nodes.input.value = JSON.stringify(stripUiFields(records), null, 2);
  rankAndRender(records, { commit: false, message: "Loaded saved list from this browser." });
} else {
  renderEmpty();
}

async function handleImport(mode) {
  clearErrors();
  let incoming;
  try {
    incoming = extractRecordsFromText(nodes.input.value);
  } catch (error) {
    showIssues([{ index: -1, ref: "", field: "_json", message: error.message }]);
    setStatus("JSON could not be read.", "error");
    return;
  }

  const marked = markIncoming(incoming, mode === "append");
  const candidate = mode === "append" ? [...records, ...marked] : marked;
  const message = mode === "append"
    ? `Appended ${marked.length} idea${marked.length === 1 ? "" : "s"} and reranked.`
    : `Replaced list with ${marked.length} idea${marked.length === 1 ? "" : "s"}.`;

  await rankAndRender(candidate, { commit: true, message });
}

async function rankAndRender(candidate, options = {}) {
  const { commit = false, message = "" } = options;
  if (candidate.length === 0) {
    if (commit) {
      records = [];
      saveRecords();
    }
    aiScanHasRun = false;
    setAiStatus("", "neutral");
    renderEmpty();
    setStatus("The current list is empty.", "neutral");
    return true;
  }

  setBusy(true);
  setStatus("Ranking ideas...", "neutral");
  try {
    const response = await fetch("/api/rank", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: candidate }),
    });
    const payload = await response.json();

    if (!response.ok || !payload.ok) {
      showIssues(payload.issues || []);
      setStatus("Fix the listed JSON issues, then try again.", "error");
      return false;
    }

    clearErrors();
    if (commit) {
      records = candidate;
      saveRecords();
      nodes.input.value = JSON.stringify(stripUiFields(records), null, 2);
    }
    aiScanHasRun = false;
    setAiStatus("", "neutral");
    renderRanking(payload.ranking || []);
    setStatus(message || `Ranked ${payload.count} idea${payload.count === 1 ? "" : "s"}.`, "success");
    return true;
  } catch (error) {
    showIssues([{ index: -1, ref: "", field: "_network", message: error.message }]);
    setStatus("Could not reach the local ranker server.", "error");
    return false;
  } finally {
    setBusy(false);
  }
}

function extractRecordsFromText(text) {
  if (!text.trim()) {
    return [];
  }
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    throw new Error(`Invalid JSON at ${error.message.replace(/^JSON\.parse: /, "")}`);
  }
  if (Array.isArray(payload)) {
    return payload;
  }
  if (payload && typeof payload === "object") {
    if (Array.isArray(payload.theses)) {
      return payload.theses;
    }
    if (Array.isArray(payload.items)) {
      return payload.items;
    }
    throw new Error("JSON object must contain a list under 'theses' or 'items'.");
  }
  throw new Error("JSON must be a list, or an object with 'theses' or 'items'.");
}

function markIncoming(items, isNew) {
  return items.map((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return item;
    }
    return { ...item, is_new: isNew };
  });
}

function stripUiFields(items) {
  return items.map((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return item;
    }
    const clean = {};
    for (const field of REQUIRED_FIELDS) {
      if (Object.prototype.hasOwnProperty.call(item, field)) {
        clean[field] = item[field];
      }
    }
    return clean;
  });
}

function loadRecords() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveRecords() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
  renderStoredCount();
}

function clearRecords() {
  records = [];
  localStorage.removeItem(STORAGE_KEY);
  nodes.input.value = "";
  nodes.file.value = "";
  clearErrors();
  aiScanHasRun = false;
  setAiStatus("", "neutral");
  renderEmpty();
  renderStoredCount();
  setStatus("Cleared the saved list in this browser.", "neutral");
}

function exportSourceJson() {
  const source = stripUiFields(records);
  const blob = new Blob([JSON.stringify(source, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "hatch-ranker-source.json";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setStatus(`Exported ${source.length} idea${source.length === 1 ? "" : "s"} as source JSON.`, "success");
}

function loadFileIntoTextarea(event) {
  const [file] = event.target.files;
  if (!file) {
    return;
  }
  const reader = new FileReader();
  reader.addEventListener("load", () => {
    nodes.input.value = String(reader.result || "");
    setStatus(`Loaded ${file.name} into the editor. Choose Replace or Append to rank it.`, "neutral");
  });
  reader.addEventListener("error", () => {
    setStatus(`Could not read ${file.name}.`, "error");
  });
  reader.readAsText(file);
}

function renderRanking(cards) {
  currentRanking = Array.isArray(cards) ? cards : [];
  nodes.empty.hidden = cards.length > 0;
  renderTierSummary(cards);
  nodes.cards.replaceChildren(...cards.map(renderCard));
  renderStoredCount();
  renderSummary(cards);
  syncAiScanButton();
}

function renderCard(card) {
  const article = element("article", "rank-card");
  if (card.is_new) {
    article.classList.add("is-new");
  }
  article.setAttribute("aria-labelledby", `idea-${card.rank}-${safeId(card.ref)}`);

  const top = element("div", "card-top");
  top.append(
    element("div", "rank-number", card.rank),
    renderTitleStack(card),
    renderScoreBox(card),
  );

  const body = element("div", "card-body");
  body.append(
    element("p", "one-liner", valueOrBlank(card.source?.one_liner)),
    renderInfoGrid(card),
    element("p", "rationale", valueOrBlank(card.rationale)),
    renderTagRow(card),
    renderSmallestV1(card),
    renderDetails(card),
  );

  article.append(top, body);
  return article;
}

function renderTitleStack(card) {
  const stack = element("div", "title-stack");
  const titleLine = element("div", "title-line");
  const heading = element("h3", "", valueOrBlank(card.title));
  heading.id = `idea-${card.rank}-${safeId(card.ref)}`;
  titleLine.append(heading, renderTierBadge(card));
  if (card.is_new) {
    titleLine.append(element("span", "new-pill", "Appended"));
  }
  stack.append(
    titleLine,
    element("p", "ref-line", `${valueOrBlank(card.ref)} | rank ${card.rank}`),
  );
  return stack;
}

function renderTierBadge(card) {
  const tierName = typeof card.tier === "string" ? card.tier.trim() : "";
  const modifier = TIER_MODIFIERS.get(tierName) || "unknown";
  const percentileNum = Number(card.percentile);
  const percentileText = Number.isFinite(percentileNum) ? String(Math.round(percentileNum)) : "-";
  const label = tierName ? `${tierName} | ${percentileText}` : "-";
  return element("span", `tier-badge tier-badge--${modifier}`, label);
}

function renderScoreBox(card) {
  const box = element("div", "score-box");
  box.append(
    element("span", "score-label", "Score"),
    element("span", "score-value", formatNumber(card.score)),
  );
  return box;
}

function renderInfoGrid(card) {
  const grid = element("div", "info-grid");
  const customer = element("div");
  customer.append(element("strong", "", "Customer"), element("p", "", valueOrBlank(card.source?.example_customer)));
  const wedge = element("div");
  wedge.append(element("strong", "", "Wedge"), element("p", "", valueOrBlank(card.source?.wedge)));
  grid.append(customer, wedge);
  return grid;
}

function renderTagRow(card) {
  const row = element("div", "tag-row");
  const tags = Array.isArray(card.tags) ? card.tags : [];
  const traps = Array.isArray(card.traps) ? card.traps : [];
  const observations = getAiObservations(card);
  const saturationChip = renderSaturationChip(card);
  if (tags.length === 0 && traps.length === 0 && observations.length === 0 && !saturationChip) {
    row.append(element("span", "tag", "no tags"));
    return row;
  }
  if (saturationChip) {
    row.append(saturationChip);
  }
  for (const tag of tags) {
    row.append(element("span", "tag", tag));
  }
  for (const trap of traps) {
    row.append(element("span", "trap", `${trap.name} -${formatNumber(trap.penalty)}`));
  }
  for (const observation of observations) {
    row.append(renderAiChip(observation));
  }
  return row;
}

function renderSaturationChip(card) {
  const sat = card.saturation;
  if (!sat || typeof sat !== "object" || !sat.label) {
    return null;
  }
  const label = String(sat.label).toUpperCase();
  const densityNum = Number(sat.density);
  const densityText = Number.isFinite(densityNum) ? densityNum.toFixed(2) : "-";
  const details = element("details", "saturation");
  details.append(
    element("summary", "", `SATURATED | ${label} | DENSITY ${densityText}`),
  );
  if (sat.incumbents) {
    details.append(element("div", "incumbents", `Incumbents: ${sat.incumbents}`));
  }
  return details;
}

function renderSmallestV1(card) {
  const wrap = element("div", "smallest-v1");
  wrap.append(element("strong", "", "Smallest sellable v1: "), document.createTextNode(valueOrBlank(card.smallest_v1)));
  return wrap;
}

function renderDetails(card) {
  const details = element("details");
  const summary = element("summary", "", "Score logic and evidence");
  const panel = element("div", "logic-panel");
  const logic = card.score_logic || {};

  panel.append(
    element("p", "formula", `${logic.formula || "final = min(raw score, viability cap) - trap penalties"} = ${formatNumber(card.score)}`),
    renderMetricGrid(card, logic),
    renderCriteriaGrid(card.criteria || {}),
    renderConceptsFired(card.fired_concepts || {}),
    renderTrapList(card.traps || []),
    renderEvidenceList(card.evidence || []),
  );
  const aiSection = renderAiObservations(card);
  if (aiSection) {
    panel.append(aiSection);
  }
  details.append(summary, panel);
  return details;
}

function renderAiChip(observation) {
  const kind = observation.kind === "opportunity" ? "opportunity" : "risk";
  const chip = element("span", `ai-chip ai-chip--${kind}`, `AI ${kind}: ${observation.note}`);
  chip.title = observation.note;
  return chip;
}

function renderAiObservations(card) {
  const observations = getAiObservations(card);
  if (!aiScanHasRun && observations.length === 0) {
    return null;
  }
  const section = element("section", "ai-observations");
  section.append(element("strong", "", "AI observations (advisory — does not change rank or score)"));
  if (observations.length === 0) {
    section.append(element("p", "ai-observation-empty", "No edge cases flagged for this card."));
    return section;
  }

  const list = element("ul", "ai-observation-list");
  observations.forEach((observation) => {
    const kind = observation.kind === "opportunity" ? "opportunity" : "risk";
    const item = element("li", `ai-observation ai-observation--${kind}`);
    item.append(
      element("span", "ai-observation-kind", kind),
      element("span", "ai-observation-note", observation.note),
    );
    list.append(item);
  });
  section.append(list);
  return section;
}

async function runAiScan() {
  if (currentRanking.length === 0 || aiScanBusy) {
    return;
  }

  setAiBusy(true);
  setAiStatus("Scanning ranked ideas for edge cases...", "neutral");
  try {
    const response = await fetch("/api/ai-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ranking: currentRanking }),
    });
    const payload = await response.json();

    if (!response.ok || !payload.ok) {
      setAiStatus(payload.error || "AI scan could not complete.", "error");
      return;
    }

    const observationsByRef = groupAiObservations(payload.observations || []);
    aiScanHasRun = true;
    // Additive-only: map over the deterministic ranking in its existing order
    // and attach observations as a new `ai_observations` field. We never
    // re-sort and never touch score/rank/tier, so the AI advances the ranking
    // without interfering with it. Do not change this to sort by AI output.
    const merged = currentRanking.map((card) => ({
      ...card,
      ai_observations: observationsByRef.get(card.ref) || [],
    }));
    renderRanking(merged);

    const count = Number(payload.count ?? (payload.observations || []).length);
    const note = count === 1 ? "1 observation" : `${Number.isFinite(count) ? count : 0} observations`;
    setAiStatus(`AI scan complete: ${note} added.`, "success");
  } catch (error) {
    setAiStatus(`AI scan failed: ${error.message}`, "error");
  } finally {
    setAiBusy(false);
  }
}

function groupAiObservations(items) {
  const grouped = new Map();
  if (!Array.isArray(items)) {
    return grouped;
  }
  items.forEach((item) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const ref = String(item.ref || "").trim();
    const note = String(item.note || "").trim();
    if (!ref || !note) {
      return;
    }
    const kind = item.kind === "opportunity" ? "opportunity" : "risk";
    const list = grouped.get(ref) || [];
    list.push({ kind, note });
    grouped.set(ref, list);
  });
  return grouped;
}

function getAiObservations(card) {
  return Array.isArray(card.ai_observations) ? card.ai_observations : [];
}

function renderMetricGrid(card, logic) {
  const grid = element("div", "metric-grid");
  grid.append(
    renderMetric("Cash velocity", card.cash_velocity, "48%"),
    renderMetric("V1 viability", card.v1_viability, "36%"),
    renderMetric("Company potential", card.company_potential, "16%"),
    renderMetric("Viability cap", card.viability_cap, "cap"),
    renderMetric("Raw score", logic.raw_score, "before cap"),
    renderMetric("Capped score", logic.capped_score, "after cap"),
    renderMetric("Trap penalties", logic.trap_penalty, "subtract"),
    renderMetric("Final", card.score, "score"),
  );
  return grid;
}

function renderCriteriaGrid(criteria) {
  const grid = element("div", "criteria-grid");
  Object.entries(criteria).forEach(([key, value]) => {
    grid.append(renderCriterion(humanize(key), value));
  });
  return grid;
}

function renderConceptsFired(fired) {
  const section = element("section");
  section.append(element("strong", "", "Concepts fired"));
  const wrap = element("div", "concepts-fired");
  let any = false;
  if (fired && typeof fired === "object" && !Array.isArray(fired)) {
    for (const [criterion, list] of Object.entries(fired)) {
      if (!Array.isArray(list) || list.length === 0) {
        continue;
      }
      any = true;
      const row = element("div", "concept-row");
      row.append(element("span", "concept-row-label", `${humanize(criterion)}: `));
      list.forEach((concept, idx) => {
        const text = String(concept);
        const negative = text.startsWith("-");
        const display = humanize(negative ? text.slice(1) : text);
        const span = element(
          "span",
          negative ? "concept-neg" : "concept-pos",
          negative ? `-${display}` : display,
        );
        row.append(span);
        if (idx < list.length - 1) {
          row.append(document.createTextNode(", "));
        }
      });
      wrap.append(row);
    }
  }
  if (!any) {
    wrap.append(element("p", "concept-empty", "No concepts fired for this card."));
  }
  section.append(wrap);
  return section;
}

function renderTrapList(traps) {
  const section = element("section");
  section.append(element("strong", "", "Trap handling"));
  const list = element("ul", "trap-list");
  if (traps.length === 0) {
    list.append(element("li", "", "No hard trap detected by the rulebook."));
  } else {
    traps.forEach((trap) => {
      list.append(element("li", "", `${trap.name}: -${formatNumber(trap.penalty)}. ${trap.reason}`));
    });
  }
  section.append(list);
  return section;
}

function renderEvidenceList(items) {
  const section = element("section");
  section.append(element("strong", "", "Evidence and assumptions"));
  const list = element("ul", "evidence-list");
  if (items.length === 0) {
    list.append(element("li", "", "No evidence notes returned."));
  } else {
    items.forEach((item) => list.append(element("li", "", item)));
  }
  section.append(list);
  return section;
}

function renderMetric(label, value, note) {
  const metric = element("div", "metric");
  metric.append(
    element("span", "", `${label} | ${note}`),
    element("strong", "", formatNumber(value)),
  );
  return metric;
}

function renderCriterion(label, value) {
  const criterion = element("div", "criterion");
  criterion.append(element("span", "", label), element("strong", "", formatNumber(value)));
  return criterion;
}

function renderSummary(cards) {
  const appended = cards.filter((card) => card.is_new).length;
  const topTier = cards.filter((card) => card.tier === "Top Tier").length;
  const trapTier = cards.filter((card) => card.tier === "Trap").length;
  const top = cards[0]?.score;
  nodes.summary.replaceChildren(
    element("span", "summary-chip", `${cards.length} ranked`),
    element("span", "summary-chip", `top ${formatNumber(top)}`),
    element("span", "summary-chip", `${appended} appended`),
    element("span", "summary-chip", `${topTier} top tier`),
    element("span", "summary-chip", `${trapTier} traps`),
  );
}

function renderTierSummary(cards) {
  if (!nodes.tierSummary) {
    return;
  }
  if (!Array.isArray(cards) || cards.length === 0) {
    nodes.tierSummary.replaceChildren();
    return;
  }
  const children = [];
  for (const [name, modifier] of TIER_ORDER) {
    const members = cards.filter((card) => card.tier === name);
    if (members.length === 0) {
      continue;
    }
    const refs = members.map((card) => card.ref).filter(Boolean).join(", ");
    children.push(
      element("span", `tier-summary-label tier-summary-label--${modifier}`, name.toUpperCase()),
      element("span", "tier-summary-count", String(members.length)),
      element("span", "tier-summary-refs", refs),
    );
  }
  nodes.tierSummary.replaceChildren(...children);
}

function renderEmpty() {
  currentRanking = [];
  nodes.empty.hidden = false;
  nodes.cards.replaceChildren();
  nodes.summary.replaceChildren();
  if (nodes.tierSummary) {
    nodes.tierSummary.replaceChildren();
  }
  syncAiScanButton();
}

function renderStoredCount() {
  const appended = records.filter((record) => record && typeof record === "object" && record.is_new).length;
  nodes.storedCount.textContent = `${records.length} saved${appended ? `, ${appended} appended` : ""}`;
}

function showIssues(issues) {
  nodes.input.setAttribute("aria-invalid", "true");
  nodes.errors.replaceChildren();
  const heading = element("strong", "", "JSON issues");
  const list = element("ul");
  const visible = issues.length ? issues : [{ index: -1, ref: "", field: "_json", message: "Unknown validation error." }];
  visible.slice(0, 12).forEach((issue) => {
    const row = issue.index >= 0 ? `Row ${issue.index + 1}` : "Input";
    const ref = issue.ref ? ` (${issue.ref})` : "";
    const field = issue.field ? ` ${issue.field}:` : ":";
    list.append(element("li", "", `${row}${ref}${field} ${issue.message}`));
  });
  if (visible.length > 12) {
    list.append(element("li", "", `${visible.length - 12} more issue${visible.length - 12 === 1 ? "" : "s"} not shown.`));
  }
  nodes.errors.append(heading, list);
}

function clearErrors() {
  nodes.input.removeAttribute("aria-invalid");
  nodes.errors.replaceChildren();
}

function setBusy(isBusy) {
  rankingBusy = isBusy;
  nodes.rankingPanel.setAttribute("aria-busy", String(isBusy));
  [nodes.replace, nodes.append, nodes.clear, nodes.export].forEach((button) => {
    button.disabled = rankingBusy || aiScanBusy;
  });
  syncAiScanButton();
}

function setStatus(message, tone) {
  nodes.status.textContent = message;
  nodes.status.dataset.tone = tone;
}

function setAiBusy(isBusy) {
  aiScanBusy = isBusy;
  [nodes.replace, nodes.append, nodes.clear, nodes.export].forEach((button) => {
    button.disabled = rankingBusy || aiScanBusy;
  });
  syncAiScanButton();
}

function syncAiScanButton() {
  nodes.aiScan.disabled = rankingBusy || aiScanBusy || currentRanking.length === 0;
  nodes.aiScan.textContent = aiScanBusy ? "Scanning edge cases..." : "Run AI edge-case scan";
}

function setAiStatus(message, tone) {
  nodes.aiStatus.textContent = message;
  nodes.aiStatus.dataset.tone = tone;
}

function element(tag, className = "", text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  return node;
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "0.0";
  }
  return number.toFixed(number % 1 === 0 ? 0 : 1);
}

function humanize(key) {
  return key.replaceAll("_", " ");
}

function valueOrBlank(value) {
  if (value === undefined || value === null || value === "") {
    return "Not provided";
  }
  return String(value);
}

function safeId(value) {
  return String(value || "idea").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.author = "Roshan Rana";
pres.title = "LedgerLens — AI Systems Architecture Review";

// Palette (shared with the reference deck)
const NAVY = "14213D", INK = "1B2A41", WHITE = "FFFFFF", ICE = "DCE7F5", MINT = "2EC4B6",
  GOLD = "F2B134", MUTED = "6B7A90", CARD = "F3F6FA", LINE = "C9D3E0", CARD_D = "1C2B4F", RED = "D64550";
const HF = "Cambria", BF = "Calibri";
const ASSETS = "C:/Code-Central/LedgerLens/docs/assets/";

let n = 0;
function base(title, kicker) {
  const s = pres.addSlide();
  n += 1;
  s.background = { color: WHITE };
  if (kicker) s.addText(kicker.toUpperCase(), { x: 0.5, y: 0.28, w: 6, h: 0.25, fontFace: BF, fontSize: 10, bold: true, color: MINT, charSpacing: 2, isTextBox: true, margin: 0 });
  s.addText(title, { x: 0.5, y: 0.5, w: 9, h: 0.6, fontFace: HF, fontSize: 26, bold: true, color: NAVY, isTextBox: true, margin: 0 });
  s.addText(`LedgerLens · AI Systems Architecture Review · ${n}`, { x: 0.5, y: 5.25, w: 9, h: 0.25, fontFace: BF, fontSize: 8, color: MUTED, isTextBox: true, margin: 0 });
  return s;
}
function dark(title, sub) {
  const s = pres.addSlide();
  n += 1;
  s.background = { color: NAVY };
  s.addText(title, { x: 0.6, y: 1.9, w: 8.8, h: 0.9, fontFace: HF, fontSize: 34, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  if (sub) s.addText(sub, { x: 0.6, y: 2.85, w: 8.8, h: 0.6, fontFace: BF, fontSize: 15, italic: true, color: ICE, isTextBox: true, margin: 0 });
  return s;
}
function card(s, x, y, w, h, fill = CARD, line = LINE) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 0.75 }, rectRadius: 0.06 });
}
function box(s, x, y, w, h, title, body, opt = {}) {
  const fill = opt.fill || CARD, tcol = opt.tcol || NAVY, bcol = opt.bcol || INK, line = opt.line || LINE;
  card(s, x, y, w, h, fill, line);
  s.addText(title, { x: x + 0.1, y: y + 0.06, w: w - 0.2, h: 0.28, fontFace: BF, fontSize: opt.ts || 11, bold: true, color: tcol, isTextBox: true, margin: 0 });
  if (body) s.addText(body, { x: x + 0.1, y: y + 0.34, w: w - 0.2, h: h - 0.4, fontFace: BF, fontSize: opt.bs || 8.5, color: bcol, isTextBox: true, margin: 0, valign: "top" });
}
function arrow(s, x1, y1, x2, y2, color = MUTED, w = 1.25) {
  const flipH = x2 < x1, flipV = y2 < y1;
  s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.01, h: Math.abs(y2 - y1) || 0.01, line: { color, width: w, endArrowType: "triangle" }, flipH, flipV });
}
function bullets(s, items, x, y, w, h, fs = 11, color = INK) {
  s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } })), { x, y, w, h, fontFace: BF, fontSize: fs, color, isTextBox: true, margin: 0, paraSpaceAfter: 4, valign: "top" });
}
function table(s, rows, x, y, w, colW, fs = 8.5, rowH) {
  const data = rows.map((r, i) => r.map((c) => ({ text: c, options: i === 0 ? { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: fs } : { fontSize: fs, color: INK } })));
  s.addTable(data, { x, y, w, colW, fontFace: BF, border: { type: "solid", pt: 0.5, color: LINE }, autoPage: false, rowH });
}
function imgFit(s, path, x, y, maxW, maxH, pw, ph) {
  const r = Math.min(maxW / pw, maxH / ph);
  const w = pw * r, h = ph * r;
  s.addImage({ path, x: x + (maxW - w) / 2, y, w, h });
  return { w, h };
}
function caption(s, text, x, y, w) {
  s.addText(text, { x, y, w, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 1 Title
{
  const s = pres.addSlide(); n += 1; s.background = { color: NAVY };
  s.addText("LedgerLens", { x: 0.6, y: 1.35, w: 8, h: 0.9, fontFace: HF, fontSize: 48, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  s.addText("AI Systems Architecture Review", { x: 0.6, y: 2.25, w: 8, h: 0.5, fontFace: BF, fontSize: 22, color: ICE, isTextBox: true, margin: 0 });
  s.addText("Reconciles cheaply first, reasons expensively last, and explains every decision", { x: 0.6, y: 2.8, w: 8.6, h: 0.5, fontFace: BF, fontSize: 13, italic: true, color: ICE, isTextBox: true, margin: 0 });
  s.addText("AI-assisted financial reconciliation · Release 0.2.0 · 12 September 2026 · Roshan Rana, AI Systems Architect", { x: 0.6, y: 4.6, w: 8.8, h: 0.3, fontFace: BF, fontSize: 10, color: MUTED, isTextBox: true, margin: 0 });
  s.addShape(pres.shapes.OVAL, { x: 8.2, y: 1.2, w: 1.1, h: 1.1, fill: { color: MINT }, line: { color: MINT } });
  s.addText("L", { x: 8.2, y: 1.2, w: 1.1, h: 1.1, fontFace: HF, fontSize: 40, bold: true, color: NAVY, align: "center", valign: "middle", isTextBox: true, margin: 0 });
}

// ---------- 2 Executive summary
{
  const s = base("Executive summary", "Overview");
  const cols = [
    ["What it is", ["A reconciliation engine for messy bank, ledger and processor files: exact, rule and fuzzy tiers resolve the obvious pairs; a masked, cost-capped LLM adjudicates only the ambiguous middle band.", "A LangGraph review gate pauses the run at a real interrupt() until a named reviewer resolves every open task, resumable from any process."]],
    ["What it proves", ["105 tests, 6 / 6 golden checks, a review gate resumed 1 / 1 times cross-instance, 0 raw counterparty or reference strings leaked to the model or the MCP server (asserted against real sample data).", "Atomic runs with rollback; a Go match-worker validated by replaying real Python-exported events."]],
    ["Why it is enterprise-ready", ["Frozen interface contracts per design doc (docs/05), a single offline gate (`make check`: unit + golden + card-drift), and a numbered decision log for every consequential trade-off.", "Masking is one module used by both the LLM request and the human reviewer's tools — one perimeter, two consumers."]],
  ];
  cols.forEach((c, i) => {
    const x = 0.5 + i * 3.05;
    card(s, x, 1.3, 2.9, 3.25);
    s.addText(c[0], { x: x + 0.15, y: 1.4, w: 2.6, h: 0.35, fontFace: HF, fontSize: 15, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    bullets(s, c[1], x + 0.15, 1.85, 2.6, 2.6, 10.5);
  });
  s.addText("Ask of the audience: agree the pilot scope — which live LLM backend to validate first (Ollama, vLLM, Bedrock or Anthropic), the Postgres migration path, and whether the Kafka streaming profile is wanted for this client.", { x: 0.5, y: 4.7, w: 9, h: 0.45, fontFace: BF, fontSize: 10, italic: true, color: INK, isTextBox: true, margin: 0 });
}

// ---------- 3 Problem and users
{
  const s = base("The problem and the users", "Context");
  box(s, 0.5, 1.3, 4.3, 1.75, "The reconciliation problem", "Bank statements, ledger exports and processor files never share a schema, a sign convention or a posting date. The obvious matches are cheap to automate; the cost is the residue — pairs that look alike but are not, and pairs that are the same transaction wearing two descriptions. Sending every pair to an LLM is neither affordable nor auditable.", { bs: 10 });
  box(s, 5.2, 1.3, 4.3, 1.75, "The constraints", "A decision that reaches an auditor must be explainable and reproducible. Raw counterparty and reference strings must not leave the perimeter unmasked. A low-confidence decision must stay open until a named human resolves it — the run cannot silently mark itself complete.", { bs: 10 });
  table(s, [
    ["Actor", "Needs", "Frequency"],
    ["Reconciliation analyst", "Reviews exceptions, resolves review tasks with a decision and notes, completes the run", "Per run"],
    ["Controller / compliance", "Match rate, review-required rate, an audit trail from decision back to source rows", "On review"],
    ["Implementation engineer", "Onboards a new client source via a mapping profile, not a code change", "Per client"],
    ["Automation / AI assistant", "The same review gate over MCP (7 tools) or the JSON API, never raw source rows", "Ad hoc"],
  ], 0.5, 3.25, 9.0, [2.1, 5.3, 1.6], 9);
}

// ---------- 4 Solution at a glance
{
  const s = base("Solution at a glance", "Approach");
  const steps = [
    ["1", "Ingest", "Config-driven source profiles map client columns to a canonical shape; raw rows and file hashes are kept for provenance."],
    ["2", "Match ladder", "Exact fingerprint, then deterministic rules, then fuzzy scoring; only the ambiguous middle band continues."],
    ["3", "Adjudicate & gate", "The middle band goes to a masked, cached LLM call; low-confidence results open a review task and the graph interrupts."],
    ["4", "Resolve & finalize", "A reviewer resolves every task over the CLI, JSON API or MCP; `complete_review` resumes the graph from any process."],
  ];
  steps.forEach((st, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.35, 2.15, 2.15, CARD_D, CARD_D);
    s.addShape(pres.shapes.OVAL, { x: x + 0.15, y: 1.5, w: 0.4, h: 0.4, fill: { color: MINT }, line: { color: MINT } });
    s.addText(st[0], { x: x + 0.15, y: 1.5, w: 0.4, h: 0.4, fontFace: BF, fontSize: 14, bold: true, color: NAVY, align: "center", valign: "middle", isTextBox: true, margin: 0 });
    s.addText(st[1], { x: x + 0.65, y: 1.52, w: 1.4, h: 0.36, fontFace: BF, fontSize: 13, bold: true, color: WHITE, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(st[2], { x: x + 0.15, y: 2.0, w: 1.85, h: 1.4, fontFace: BF, fontSize: 9, color: ICE, isTextBox: true, margin: 0, valign: "top" });
    if (i < 3) arrow(s, x + 2.15, 2.4, x + 2.3, 2.4, MINT, 2);
  });
  box(s, 0.5, 3.75, 4.4, 1.3, "Surfaces", "Typer CLI · stdlib JSON API · MCP server (`ledgerlens-review`, 7 tools). All three call the same service functions over the same SQLite store; none re-implements the graph.", { bs: 10 });
  box(s, 5.1, 3.75, 4.4, 1.3, "One perimeter, two consumers", "`ledgerlens/llm/masking.py` masks every candidate pair the same way for the model and for the MCP reviewer's tools: hashed tokens for reference and counterparty, digit-run redaction, a version tag.", { bs: 10 });
}

// ---------- 5 System context (C4 L1)
{
  const s = base("System context", "Architecture · C4 level 1");
  const actors = [["Analyst", "CLI / API"], ["Reviewer", "MCP client"], ["Automation", "HTTP client"], ["Sidecar op", "Go / Kafka"]];
  actors.forEach((a, i) => { box(s, 0.5, 1.3 + i * 0.85, 1.6, 0.7, a[0], a[1], { bs: 8.5 }); arrow(s, 2.1, 1.65 + i * 0.85, 2.75, 2.85, MUTED, 1); });
  card(s, 2.8, 1.3, 3.4, 3.4, "EEF6F4", MINT);
  s.addText("LedgerLens", { x: 2.95, y: 1.38, w: 3, h: 0.3, fontFace: HF, fontSize: 14, bold: true, color: NAVY, isTextBox: true, margin: 0 });
  box(s, 2.95, 1.75, 3.1, 0.75, "Surfaces", "Typer CLI · stdlib JSON API · MCP server", { bs: 8.5 });
  box(s, 2.95, 2.6, 3.1, 1.0, "Core package `ledgerlens`", "ingestion · normalization · matching ladder · LangGraph agents/graph · masking · reporting", { bs: 8.5 });
  box(s, 2.95, 3.7, 3.1, 0.85, "SQLite store (WAL)", "run-scoped tables, audit events, checkpoints", { bs: 8.5 });
  box(s, 6.9, 1.3, 2.6, 0.75, "LLM providers", "fake (default) · Ollama · vLLM · Bedrock · Anthropic, one contract", { bs: 8 });
  box(s, 6.9, 2.2, 2.6, 0.75, "MCP clients", "Claude Desktop · Cursor · Claude Code · scripts", { bs: 8 });
  box(s, 6.9, 3.1, 2.6, 0.75, "Go match-worker", "candidate generation over a Kafka-compatible topic (optional)", { bs: 8 });
  box(s, 6.9, 4.0, 2.6, 0.7, "Event contracts", "7 JSON-Schema event types + envelope", { bs: 8 });
  arrow(s, 6.2, 3.0, 6.9, 1.67, MUTED, 1); arrow(s, 6.2, 3.1, 6.9, 2.57, MUTED, 1); arrow(s, 6.2, 3.2, 6.9, 3.47, MUTED, 1); arrow(s, 6.2, 3.3, 6.9, 4.35, MUTED, 1);
  s.addText("The fake adjudicator is the default and drives every test, the golden replay and CI; live providers are switched on by `--llm {ollama|vllm|bedrock|anthropic}` and a config file naming an environment variable, never a key.", { x: 0.5, y: 4.85, w: 9, h: 0.35, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 6 Component architecture (C4 L2)
{
  const s = base("Component architecture", "Architecture · C4 level 2");
  const groups = [
    { t: "Surfaces", x: 0.5, items: [["cli.py", "Typer commands"], ["api/server.py", "stdlib JSON API"], ["api/resources.py", "service functions"], ["mcp/server.py", "7 MCP tools"]] },
    { t: "Orchestration", x: 2.85, items: [["agents/graph.py", "LangGraph StateGraph"], ["agents/workflow.py", "WorkflowState, run modes"], ["matching/engine.py", "TieredMatcher"], ["matching/text.py", "fuzzy scoring"]] },
    { t: "Data & domain", x: 5.2, items: [["ingestion/*", "profiles, csv loader"], ["normalization/*", "canonical transactions"], ["domain/models.py", "typed records"], ["persistence/*", "SQLiteStore, checkpointer"]] },
    { t: "LLM & masking", x: 7.55, items: [["llm/schemas.py", "request/decision contract"], ["llm/fake.py", "deterministic default"], ["llm/live.py", "openai_compat · bedrock · anthropic"], ["llm/masking.py", "the one perimeter"]] },
  ];
  groups.forEach((g) => {
    card(s, g.x, 1.3, 2.15, 3.55);
    s.addText(g.t, { x: g.x + 0.1, y: 1.36, w: 2, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    g.items.forEach((it, i) => {
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: g.x + 0.1, y: 1.72 + i * 0.62, w: 1.95, h: 0.54, fill: { color: WHITE }, line: { color: LINE, width: 0.75 }, rectRadius: 0.05 });
      s.addText(it[0], { x: g.x + 0.18, y: 1.75 + i * 0.62, w: 1.8, h: 0.24, fontFace: "Courier New", fontSize: 8.5, bold: true, color: NAVY, isTextBox: true, margin: 0 });
      s.addText(it[1], { x: g.x + 0.18, y: 1.97 + i * 0.62, w: 1.8, h: 0.26, fontFace: BF, fontSize: 8, color: INK, isTextBox: true, margin: 0 });
    });
  });
  arrow(s, 2.65, 3.1, 2.85, 3.1, MINT, 2); arrow(s, 5.0, 3.1, 5.2, 3.1, MINT, 2); arrow(s, 7.35, 3.1, 7.55, 3.1, MINT, 2);
  s.addText("Dependency direction is left to right. The matching engine is stdlib-only; LLM and masking are the only modules a candidate pair's raw fields ever reach on the way out.", { x: 0.5, y: 4.9, w: 9, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 7 The critical flow
{
  const s = base("The reconciliation graph", "Architecture · critical flow");
  const stages = [
    ["Load & normalize", "load_run_context, normalize_batch: canonical transactions with raw provenance"],
    ["Candidates", "generate_candidates: bounded blocking by currency, amount and date window"],
    ["Exact + rule", "apply_exact_matches, apply_rule_matches: fingerprints and known accounting patterns"],
    ["Fuzzy scoring", "score_fuzzy_candidates: high matches, low becomes an exception, middle continues"],
    ["Adjudicate (masked)", "adjudicate_ambiguous_pairs: masked pair to the cached LLM contract"],
    ["Route & surface", "route_review_tasks, surface_unmatched_transactions: low confidence opens a task"],
    ["Persist & report", "persist_decisions, generate_report: rows and the preliminary report commit"],
    ["Gate", "[open tasks] → await_review interrupt(); reviewer resolves → finalize_run"],
  ];
  stages.forEach((st, i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = 0.5 + col * 2.3, y = 1.4 + row * 1.7;
    card(s, x, y, 2.15, 1.35, row === 0 ? CARD : "EEF6F4", row === 0 ? LINE : MINT);
    s.addText(`${i + 1}. ${st[0]}`, { x: x + 0.1, y: y + 0.08, w: 1.95, h: 0.3, fontFace: BF, fontSize: 10.5, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    s.addText(st[1], { x: x + 0.1, y: y + 0.4, w: 1.95, h: 0.9, fontFace: BF, fontSize: 8.3, color: INK, isTextBox: true, margin: 0, valign: "top" });
    if (col < 3) arrow(s, x + 2.15, y + 0.67, x + 2.3, y + 0.67, MUTED, 1.25);
  });
  arrow(s, 9.0, 2.75, 9.0, 3.1, MUTED, 1.25);
  s.addText("Thirteen nodes, one fixed order, no loops and no free-form tool calls. On the acme replay: 2 exact, 1 rule, 1 llm→needs_review, 1 human resolution; 4 of 12 transactions stay unmatched exceptions.", { x: 0.5, y: 4.85, w: 9, h: 0.35, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 8 Core mechanism
{
  const s = base("Deterministic first, masked LLM last: the perimeter", "Design · core mechanism");
  card(s, 0.5, 1.3, 4.6, 3.55, CARD_D, CARD_D);
  s.addText("What crosses the perimeter (masked pair)", { x: 0.65, y: 1.38, w: 4.3, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: MINT, isTextBox: true, margin: 0 });
  s.addText([
    '{ "id": "txn_23e4...", "date": "2026-05-04",', '  "amount": "-25.00", "currency": "USD",', '  "source_system": "bank",',
    '  "description": "bank service fee may",', '  "reference_token": "",', '  "counterparty_token": "aabfc736adc8",', '  "masking_version": "ledgerlens.masking.v1" }',
  ].join("\n"), { x: 0.65, y: 1.72, w: 4.3, h: 1.65, fontFace: "Courier New", fontSize: 8.5, color: WHITE, isTextBox: true, margin: 0, valign: "top" });
  s.addText("What the module guarantees", { x: 0.65, y: 3.4, w: 4.3, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: MINT, isTextBox: true, margin: 0 });
  bullets(s, ["id, date, amount, currency, source_system stay verbatim", "reference and counterparty become stable hashed tokens (equal tokens still mean equal values)", "description: digit runs of five or more redacted, capped at 80 chars", "the fake reads computed features only, so masking moved none of the golden numbers"], 0.65, 3.72, 4.3, 1.1, 8.5, ICE);
  const badges = [["exact · rule · fuzzy", "resolved without the model — 3 of 4 decisions on the acme replay", MINT], ["llm: needs_review", "masked pair, cached by pair, opens a review task", GOLD], ["human: match / no_match", "final decision; audited; the run cannot complete while it is open", RED]];
  badges.forEach((b, i) => {
    const y = 1.3 + i * 0.85;
    card(s, 5.4, y, 4.1, 0.72);
    s.addText(b[0], { x: 5.55, y: y + 0.06, w: 1.9, h: 0.6, fontFace: BF, fontSize: 10.5, bold: true, color: b[2], isTextBox: true, margin: 0, valign: "middle" });
    s.addText(b[1], { x: 7.35, y: y + 0.06, w: 2.05, h: 0.6, fontFace: BF, fontSize: 8.3, color: INK, isTextBox: true, margin: 0, valign: "middle" });
  });
  box(s, 5.4, 3.75, 4.1, 1.1, "Why this matters", "Only the ambiguous middle band ever reaches the model, and the model never sees the pair twice: `CachedLLMAdjudicator` keys on the pair and the model family, so fake and live decisions never collide.", { bs: 9 });
}

// ---------- 9 Data architecture
{
  const s = base("Data architecture: SQLite of record, events at the edge", "Architecture · data");
  box(s, 0.5, 1.3, 2.9, 1.75, "SQLite store (WAL)", "Run-scoped tables: source_files, normalized_transactions, candidate_pairs, match_decisions, review_tasks, audit_events, llm_cache. One file also hosts the LangGraph SqliteSaver checkpointer, so rows and checkpoints commit together.", { bs: 8.5 });
  box(s, 0.5, 3.2, 2.9, 1.65, "Masking as the export boundary", "Every payload that leaves the store for a model or an MCP client passes through `masking.py` first. Raw fields are read by matching and reporting only; nothing downstream sees them unmasked.", { bs: 8.5 });
  arrow(s, 3.4, 2.15, 4.1, 2.9, MINT, 2); arrow(s, 3.4, 4.0, 4.1, 3.2, MINT, 2);
  card(s, 4.1, 2.35, 2.2, 1.4, "EEF6F4", MINT);
  s.addText("7 event types", { x: 4.2, y: 2.42, w: 2, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: NAVY, isTextBox: true, margin: 0 });
  s.addText("statement.ingested\ntransaction.normalized\nmatch.candidate_created\nmatch.decision_created\nreview.required / resolved\nreport.generated", { x: 4.2, y: 2.75, w: 2, h: 1.0, fontFace: "Courier New", fontSize: 7.5, color: INK, isTextBox: true, margin: 0 });
  arrow(s, 6.3, 3.05, 6.95, 3.05, MINT, 2);
  box(s, 6.95, 1.3, 2.55, 3.55, "Contracts, not just tables", "One envelope schema (event_id, idempotency_key, run_id) plus 7 payload schemas under `contracts/schemas/`. Every fixture and example validates in CI: 12 / 12 emitted `transaction.normalized` events pass their declared schema.\n\nThe Go match-worker consumes the same contract the Python side exports, so a cross-language boundary is tested against real events, not a hand-written stub.", { bs: 8.5 });
  s.addText("Classification: masked/tokenised fields only ever leave the store for a model or a review tool; raw customer data stays inside the SQLite boundary and the process that reads it.", { x: 0.5, y: 4.95, w: 9, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 10 Integration / provider / live-mode design
{
  const s = base("LLM providers: one contract, five backends", "Architecture · integration");
  const rows = [["fake", "nothing (deterministic)", "default; drives tests, golden replay, CI"], ["ollama", "openai_compat → localhost:11434/v1", "no key; stdlib urllib"], ["vllm", "openai_compat → localhost:8000/v1", "VLLM_API_KEY"], ["bedrock", "boto3 converse, us-east-1", "AWS credential chain; [bedrock] extra"], ["anthropic", "Anthropic Messages API", "ANTHROPIC_API_KEY; [anthropic] extra"]];
  table(s, [["--llm", "Reaches", "Environment"], ...rows], 0.5, 1.3, 4.6, [1.0, 2.3, 1.3], 8);
  box(s, 5.3, 1.3, 4.2, 1.5, "One `LLMClient` protocol", "`build_prompt` states the task, the three allowed decisions and the exact JSON shape; `parse_decision` tolerates fences and prose. A live client retries once with the parse error appended, then raises `LLMError`.", { bs: 8.5 });
  box(s, 5.3, 2.95, 4.2, 1.05, "Config, never secrets", "`configs/llm/<name>.json` holds the backend, model, base URL or region and the *name* of the key's env var — never a value. A missing variable or package raises `LLMError` naming what to set.", { bs: 8.5 });
  box(s, 5.3, 4.15, 4.2, 0.75, "Cache-key separation", "`model_family` (`<backend>:<model>`) enters the cache key, so a live decision and the fake's decision for the same pair never collide.", { bs: 8.5 });
  s.addText("None of the three live backends has been run by the harness; their accuracy, latency and cost are pending — the results card says so rather than estimating.", { x: 0.5, y: 4.95, w: 9, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 11 Design choices
{
  const s = base("Design choices and why", "Design decisions");
  table(s, [
    ["Decision", "Alternatives considered", "Why this one"],
    ["LangGraph StateGraph + SqliteSaver (D-1)", "Hand-rolled node loop (0.1's actual approach)", "A checkpointer makes the pause resumable from any process, not just a status flag"],
    ["Checkpoints hold ids and counters only (D-2)", "Checkpoint the full WorkflowState", "The store is the record; the checkpoint is the cursor — small, cheap, replayable"],
    ["The gate finalises, it never re-adjudicates (D-3)", "Re-run adjudication after review", "Reviewer authority is final and auditable; the model is not consulted twice"],
    ["Resume validated in the service, not the node (D-4)", "Validate inside `await_review`", "LangGraph persists the resume value before the node runs; a raising node would wedge the thread"],
    ["One masking module for the model and MCP (D-5)", "Separate redaction per consumer", "One version tag, one perimeter; the fake is provably unaffected so golden numbers hold"],
    ["`openai_compat` over stdlib `urllib` (D-6)", "Vendor SDKs for Ollama and vLLM", "Ollama and vLLM need nothing installed; Bedrock/Anthropic stay optional lazy imports"],
    ["SQLite now, Postgres-shaped schema for later", "Postgres from day one", "Portable local demo; the run-scoped table design maps directly to a production database"],
  ], 0.5, 1.3, 9.0, [2.7, 2.6, 3.7], 8.3);
}

// ---------- 12 Major features
{
  const s = base("Major features", "Product");
  const feats = [
    ["Config-driven source onboarding", "A new client source is a mapping profile under `configs/clients/` plus one focused test — no matching-code change."],
    ["The tiered matching ladder", "Exact fingerprint → deterministic rules (date lag, reference variants) → fuzzy scoring with an explicit middle band."],
    ["Masked, cached LLM adjudication", "Only the ambiguous band reaches the model; decisions are cached per pair so a re-run never asks twice."],
    ["The LangGraph review gate", "A real `interrupt()` at `await_review`; `complete_review` resumes the graph from any process once every task is resolved."],
    ["The MCP review server", "`ledgerlens-review`: 7 tools over stdio for Claude Desktop, Cursor or a script — masked pairs only."],
    ["Atomic runs with rollback", "A run that fails before the interrupt rolls back completely, checkpoints included."],
    ["Go match-worker + event contracts", "7 JSON-Schema event types; the worker is validated by replaying real Python-exported events."],
    ["Source diagnostics", "Missing references, missing external ids, duplicate references — surfaced before matching starts."],
    ["The offline gate", "`make check`: 105 unit/e2e tests, the golden replay, and a results-card drift guard, no network, no key."],
  ];
  feats.forEach((f, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    box(s, 0.5 + col * 3.05, 1.3 + row * 1.2, 2.9, 1.05, f[0], f[1], { bs: 8.3 });
  });
}

// ---------- 13 Screenshot: demo run + gate pause
{
  const s = base("The reconciliation report — and the gate pause", "Screenshots · CLI demo");
  imgFit(s, ASSETS + "10-demo-run.png", 0.5, 1.2, 5.6, 3.75, 1200, 1261);
  box(s, 6.3, 1.2, 3.2, 1.8, "What you are looking at", "`ledgerlens.cli demo` ingests two acme sources, reconciles across every tier and prints the preliminary report: 2 exact, 1 rule, 1 llm review task, 4 unmatched. It ends `awaiting_review` — the run is paused, not finished.", { bs: 9 });
  box(s, 6.3, 3.15, 3.2, 1.75, "The tier breakdown is the product", "The report states what the model was asked (1 call, 0 cache hits) and what it was not asked — the other 3 decisions never reached it. This is the number that justifies the architecture to an operations lead.", { bs: 9 });
}

// ---------- 14 Screenshot: review gate sequence
{
  const s = base("The review gate: refuse, resolve, resume, finalize", "Screenshots · review gate");
  imgFit(s, ASSETS + "11-review-gate.png", 3.55, 1.2, 5.95, 3.9, 1200, 1456);
  box(s, 0.5, 1.2, 2.9, 1.85, "Refused, then resolved", "`review-complete` refuses while a task is open, with the exact reason. `review-resolve` records the analyst's decision and notes against the task.", { bs: 9 });
  box(s, 0.5, 3.2, 2.9, 1.8, "Resumed from a fresh process", "The second `review-complete` call opens a new workflow instance on the same database file and resumes the interrupted graph: `human:no_match` appears under Decisions By Tier, `run.finalized` under Audit, status `completed`.", { bs: 9 });
}

// ---------- 15 Screenshot: checkpoints + golden harness
{
  const s = base("Checkpoints and the golden harness", "Screenshots · verification");
  imgFit(s, ASSETS + "12-graph-history.png", 0.5, 1.25, 9.0, 1.35, 1400, 364);
  caption(s, "graph-history: 15 checkpoints for the gated demo, oldest first — every step of the run is replayable from the checkpointer.", 0.5, 2.68, 9);
  imgFit(s, ASSETS + "14-golden-summary.png", 0.5, 3.05, 9.0, 1.95, 1100, 910);
  caption(s, "make check, unpacked: 105 tests, the golden replay's 6 KPIs, the headline self-check, the card-drift guard and the Go worker's own tests.", 0.5, 5.0, 9);
}

// ---------- 16 Screenshot: MCP transcript
{
  const s = base("The MCP review server: masked, zero raw identifiers", "Screenshots · MCP");
  imgFit(s, ASSETS + "13-mcp-transcript.png", 0.5, 1.2, 5.6, 3.8, 1200, 812);
  box(s, 6.3, 1.2, 3.2, 1.9, "What a reviewer's tool sees", "`get_review_pair` returns the masked pair plus the machine's tier, decision, confidence and reason code — never the raw counterparty or reference. A test asserts 10 real strings from the sample CSVs against every tool result.", { bs: 9 });
  box(s, 6.3, 3.25, 3.2, 1.65, "The same gate, another door", "`resolve_review_task` and `complete_review` call the identical service functions the CLI and API use; the run cannot complete with an open task through any of the three surfaces.", { bs: 9 });
}

// ---------- 17 Security and compliance
{
  const s = base("Security and compliance controls", "Enterprise readiness · controls");
  table(s, [
    ["Boundary", "Risk", "Control in the code", "Evidence"],
    ["Masking perimeter", "raw counterparty / reference reaching a model or reviewer tool", "`llm/masking.py`: hashed tokens, digit-run redaction, version tag; one module for both consumers", "`test_masking.py` (12); MCP no-leak test (10 sample strings)"],
    ["MCP review server", "a tool result leaking a raw sample value", "every tool masks before returning; errors come back as `{\"error\": ...}`, never a raised exception", "`test_no_tool_result_contains_raw_counterparty_or_reference`"],
    ["LLM provider config", "a key committed to source", "`configs/llm/*.json` names an env var only; live backends are lazy imports behind extras", "`test_shipped_configs_have_expected_shape_and_no_secrets`"],
    ["Persistence / rollback", "a half-written run after a late failure", "`store.transaction()` covers ingestion through `generate_report`; checkpointer shares the connection and commits with it", "`test_persistent_workflow_rolls_back_partial_run_on_late_failure`"],
    ["Event contracts", "a malformed or unschematised event reaching the Go worker", "envelope + 7 payload JSON Schemas, validated in CI", "12 / 12 fixtures pass their declared schema"],
  ], 0.5, 1.3, 9.0, [1.5, 2.3, 3.4, 1.8], 8);
  s.addText("Residual risks, written down: no authentication in front of the API or MCP server (single-operator prototype); SQLite is not a multi-writer production database (a Postgres path is a design choice, not yet built); live LLM backends are untested against a real model.", { x: 0.5, y: 4.65, w: 9, h: 0.5, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 18 Enterprise readiness: process
{
  const s = base("Frozen contracts, one gate, a decision log", "Enterprise readiness · process");
  const gates = ["01 HLD", "02 LLD (multi-agent)", "03 demo runbook", "04 AI brief", "05 review-gate design (frozen §3-6)"];
  gates.forEach((g, i) => {
    const x = 0.5 + i * 1.8;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.35, w: 1.72, h: 0.62, fill: { color: CARD_D }, line: { color: CARD_D }, rectRadius: 0.05 });
    s.addText(g, { x: x + 0.04, y: 1.37, w: 1.64, h: 0.58, fontFace: BF, fontSize: 7.5, bold: true, color: WHITE, align: "center", valign: "middle", isTextBox: true, margin: 0 });
  });
  const stats = [["5", "design docs (01-05); doc 05's §3-6 interfaces are frozen contracts for the build"], ["6", "numbered decisions (D-1 .. D-6) in the review-gate design, each with its consequence"], ["3", "task packs (LL-1, LL-2, LL-3) scoped to one module each, with an acceptance checklist"], ["1", "gate command: `make check` runs unit + golden + card-drift; CI runs the same command"]];
  stats.forEach((st, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 2.2, 2.15, 1.25);
    s.addText(st[0], { x: x + 0.12, y: 2.25, w: 1.9, h: 0.5, fontFace: HF, fontSize: 28, bold: true, color: GOLD, isTextBox: true, margin: 0 });
    s.addText(st[1], { x: x + 0.12, y: 2.75, w: 1.9, h: 0.65, fontFace: BF, fontSize: 8.3, color: INK, isTextBox: true, margin: 0, valign: "top" });
  });
  box(s, 0.5, 3.65, 4.4, 1.25, "STATE.md tracks the truth", "Phase 7, task log LL-0 .. LL-4, each row done/blocked/next; deviations are recorded rather than silently absorbed (0.1 promised LangGraph, 0.2 delivered it — decision D-1).", { bs: 9 });
  box(s, 5.1, 3.65, 4.4, 1.25, "One command validates everything", "`python -m unittest discover -s tests`, `python -m metrics.golden`, `python -m unittest tests.golden.test_headline_metrics`, `python metrics/render.py --check` — the same four steps `make check` runs, and what CI runs on every push.", { bs: 9 });
}

// ---------- 19 Quality metrics (native chart)
{
  const s = base("Quality metrics from the gate", "Enterprise readiness · measurement");
  s.addChart(pres.charts.BAR, [{ name: "Value", labels: ["Golden checks", "Straight-through rate", "Schema conformance", "Review gate resumed"], values: [1.0, 0.75, 1.0, 1.0] }], {
    x: 0.5, y: 1.3, w: 5.2, h: 3.5, barDir: "bar", chartColors: [MINT], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", dataLabelFontSize: 9, dataLabelColor: INK,
    catAxisLabelColor: INK, catAxisLabelFontSize: 9, valAxisLabelColor: MUTED, valAxisLabelFontSize: 8, valAxisMinVal: 0, valAxisMaxVal: 1.1, valGridLine: { color: LINE, size: 0.5 }, catGridLine: { style: "none" }, showLegend: false, showTitle: true, title: "Ratios (1.0 = target met)", titleFontSize: 10, titleColor: NAVY,
  });
  table(s, [
    ["KPI", "Value", "Source"],
    ["Tests", "105 passed", "unittest discover"],
    ["Golden checks", "6 / 6", "vs expected_summary"],
    ["Match rate", "75%", "exact + rule + fuzzy"],
    ["Straight-through", "75%", "3 of 4 decisions"],
    ["Review required", "25%", "1 of 4 decisions"],
    ["Schema conformance", "12 / 12", "vs contracts/schemas"],
    ["Review gate resumed", "1 / 1", "cross-instance resume"],
    ["MCP raw-value leaks", "0 / 10", "sample strings"],
    ["Go worker packages", "2 / 2 ok", "go test, GOWORK=off"],
  ], 5.9, 1.3, 3.6, [1.5, 0.8, 1.3], 7.2, 0.32);
  s.addText("Live LLM adjudication accuracy is not a KPI here: the harness runs the deterministic fake with no key, so live-model rows in the results card are marked pending, not estimated.", { x: 0.5, y: 4.9, w: 9, h: 0.35, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 20 Quirks and limitations
{
  const s = base("Quirks and known limitations (stated, not hidden)", "Honesty");
  const q = [
    ["Live LLM backends are unexercised", "Ollama, vLLM, Bedrock and Anthropic ship behind the same contract and are unit-tested against fakes, but no live model has been run by the harness — accuracy, latency and cost are pending."],
    ["Only one client pair is golden-replayed", "`bank_statement.csv` / `ledger_export.csv` have no mapping profile under `configs/clients`, so only the acme pair is scored by `make golden`."],
    ["No per-pair precision/recall", "`expected_summary.json` carries aggregate thresholds only; there are no per-pair match labels to score against."],
    ["Matching is pairwise only", "One-to-many and many-to-many matching are not implemented (tracked in STATE.md's backlog)."],
    ["Go worker not in the offline gate", "`go test` needs `GOWORK=off` locally because `go.work` pins Go 1.22 while the worker module requires >= 1.23; the worker is validated by `scripts/verify.py --docker`, not by `make check`."],
    ["No HMAC on review resolutions yet", "A resolution is authenticated by the reviewer field only today; signing resolutions is next in STATE.md's backlog."],
    ["Masked description keeps its words", "Only digit runs of five or more are redacted from the description; short free text like \"bank service fee\" still reads as English, by design (features, not raw ids, drive the decision)."],
    ["Streaming profile is opt-in", "Redpanda/Kafka validates the boundary, not production throughput; the default demo path is file mode."],
  ];
  q.forEach((it, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    box(s, 0.5 + col * 4.6, 1.3 + row * 0.9, 4.45, 0.82, it[0], it[1], { bs: 7.8, ts: 9.5 });
  });
}

// ---------- 21 Cost and performance
{
  const s = base("Cost, performance and operability", "Enterprise readiness · operations");
  const cards = [["1 call", "LLM calls on the acme demo replay; the other 3 of 4 decisions never reach the model"], ["0 keys", "needed for tests, the golden replay, CI or the demo; live backends read an env-var name only"], ["15", "LangGraph checkpoints for one gated run, each replayable via `graph-history`"], ["14", "audit events recorded for the completed demo run, from `run.loaded` to `run.finalized`"]];
  cards.forEach((c, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.3, 2.15, 1.35);
    s.addText(c[0], { x: x + 0.12, y: 1.35, w: 1.9, h: 0.5, fontFace: HF, fontSize: 26, bold: true, color: GOLD, isTextBox: true, margin: 0 });
    s.addText(c[1], { x: x + 0.12, y: 1.87, w: 1.9, h: 0.75, fontFace: BF, fontSize: 8.3, color: INK, isTextBox: true, margin: 0, valign: "top" });
  });
  box(s, 0.5, 2.85, 4.4, 2.0, "Operability", "• `make check` — the one offline gate; no network, no key\n• `scripts/verify.py --docker required [--kafka-smoke]` — Go worker tests, container build, real-event replay, optional Redpanda round trip\n• `docs/03-demo-runbook.md` — a scripted, minute-by-minute demo with expected output at each step\n• Rollback: `store.transaction()` covers a run through the interrupt; a late failure leaves nothing partial behind", { bs: 8.7 });
  box(s, 5.1, 2.85, 4.4, 2.0, "Observability and audit", "• `audit_events` table: one typed row per state change (`match.decision_created`, `review.resolved`, `run.finalized`, ...)\n• `graph-history` replays every LangGraph checkpoint for a run, oldest first\n• Cache stats (`calls`, `cache hits`) are printed in every report, so cost is visible per run\n• The results card (`metrics/headline.json`) is regenerated by the gate and diff-checked against the committed copy", { bs: 8.7 });
}

// ---------- 22 Roadmap
{
  const s = base("Roadmap", "Next steps");
  const phases = [["Now", "Record a live run", ["Run one real Ollama adjudication and publish it as a recorded figure", "Compare its decision against the fake's on the same masked pair"]], ["Next", "Matching depth", ["One-to-many and many-to-many matching", "HMAC signing on review resolutions", "A second client profile replayed by the golden harness"]], ["Then", "Production shape", ["Postgres migration behind the existing SQLiteStore interface", "Wire the Go worker and a Kafka smoke into CI, not only `scripts/verify.py`", "Authentication in front of the API and MCP server"]], ["Later", "Scale the review workforce", ["Multiple reviewers with role-scoped MCP sessions", "A review-queue dashboard over the same service functions", "SLA and aging metrics on open review tasks"]]];
  phases.forEach((p, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.3, 2.15, 3.5, i === 0 ? "EEF6F4" : CARD, i === 0 ? MINT : LINE);
    s.addText(p[0], { x: x + 0.12, y: 1.36, w: 1.9, h: 0.28, fontFace: BF, fontSize: 9, bold: true, color: MINT, charSpacing: 1, isTextBox: true, margin: 0 });
    s.addText(p[1], { x: x + 0.12, y: 1.62, w: 1.9, h: 0.35, fontFace: HF, fontSize: 14, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    bullets(s, p[2], x + 0.12, 2.05, 1.9, 2.7, 8.7);
  });
  s.addText("Everything above is additive: the masking perimeter, the review gate and the event contracts do not change.", { x: 0.5, y: 4.95, w: 9, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 23 Appendix: decision log
{
  const s = base("Appendix A — Decision log (docs/05-langgraph-review-gate-design.md)", "Appendix");
  table(s, [
    ["ID", "Decision", "Consequence"],
    ["D-1", "LangGraph + langgraph-checkpoint-sqlite + mcp become core dependencies", "The README's dependency-free claim narrows to the matching engine, which stays stdlib"],
    ["D-2", "Checkpoints hold ids and counters only", "The store is the record; the checkpoint is the cursor; checkpoints stay small"],
    ["D-3", "The gate finalises the run; it does not re-adjudicate", "Reviewer decisions stand; the model is never consulted a second time"],
    ["D-4", "Resume payloads are validated in the service before Command(resume=...)", "LangGraph persists the resume value before the node runs; a raising node would wedge the thread"],
    ["D-5", "Masking is one module shared by the LLM request and the MCP server", "One version tag, one perimeter; the fake's golden numbers are provably unaffected"],
    ["D-6", "openai_compat uses stdlib urllib", "Ollama and vLLM need no extra install; Bedrock/Anthropic stay optional lazy imports"],
  ], 0.5, 1.3, 9.0, [0.7, 4.6, 3.7], 8);
}

// ---------- 24 Appendix: process stats and lessons
{
  const s = base("Appendix B — Build statistics and lessons", "Appendix");
  table(s, [
    ["Item", "Value", "Source"],
    ["Tests", "105 (unittest, offline)", "unittest discover -s tests"],
    ["Golden checks", "6 / 6", "metrics/golden.py vs data/golden/expected_summary.json"],
    ["Design docs", "5 (01 HLD, 02 LLD, 03 runbook, 04 AI brief, 05 review-gate)", "docs/"],
    ["Task packs", "3 (LL-1 graph-gate, LL-2 live backends, LL-3 MCP server)", "docs/tasks/"],
    ["Numbered decisions", "6 (D-1 .. D-6)", "docs/05-langgraph-review-gate-design.md"],
    ["Event contract types", "7 + 1 envelope schema", "contracts/schemas/"],
    ["Go packages tested", "2 / 2 ok (contracts, worker)", "go test ./... , GOWORK=off"],
  ], 0.5, 1.3, 9.0, [2.6, 3.4, 3.0], 8.3);
  box(s, 0.5, 3.75, 9.0, 1.15, "Lessons", "• A deviation belongs in STATE.md, not silently absorbed: 0.1 promised LangGraph and shipped a hand-rolled loop; 0.2 closed the gap and D-1 records why.\n• `go.work` pinning a lower Go version than a module needs is easy to miss locally; the runbook's own Docker command already sets `GOWORK=off` for exactly this reason.\n• Validate a resume payload before the graph touches it, not inside the node — LangGraph persists first (D-4), learned the hard way on a sibling project.", { bs: 8.7 });
}

// ---------- 25 Appendix: repository map
{
  const s = base("Appendix C — Repository map and how to run", "Appendix");
  s.addText(["ledgerlens/       cli, api/, mcp/, agents/ (graph, workflow),", "                  ingestion/, normalization/, matching/,", "                  llm/ (schemas, fake, live, masking, cache),", "                  persistence/, reporting/, domain/", "go/match-worker/  contracts, worker, file/kafka transport", "contracts/        event envelope + 7 schemas, fixtures", "configs/clients/  per-client column-mapping profiles", "configs/llm/      backend + model + env-var name, no secrets", "data/samples/     acme_bank_statement.csv, acme_ledger_export.csv", "data/golden/      expected_summary.json", "metrics/          golden.py, headline.json, render.py", "docs/             01-05 design docs, tasks/, mcp.md, pitch/", "tests/            105 tests: unit, contract, e2e, golden"].join("\n"), { x: 0.5, y: 1.3, w: 5.6, h: 3.4, fontFace: "Courier New", fontSize: 7.5, color: INK, isTextBox: true, margin: 0, valign: "top" });
  card(s, 6.3, 1.3, 3.2, 3.55, CARD_D, CARD_D);
  s.addText("Run it", { x: 6.45, y: 1.38, w: 3, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: MINT, isTextBox: true, margin: 0 });
  s.addText([".venv/Scripts/python.exe -m ledgerlens.cli \\", "  --db .ledgerlens/ledgerlens.db demo", "", "# review the gate", "review-list --run-id <run_id>", "review-resolve <task_id> --decision no_match \\", "  --notes \"...\" --reviewer analyst", "review-complete <run_id> --reviewer analyst", "", "# MCP server for a reviewer's tools", "python -m ledgerlens.mcp.server", "", "# the offline gate", "python -m unittest discover -s tests", "python -m metrics.golden", "python metrics/render.py --check"].join("\n"), { x: 6.45, y: 1.72, w: 3, h: 3.05, fontFace: "Courier New", fontSize: 8, color: WHITE, isTextBox: true, margin: 0, valign: "top" });
}

// ---------- 26 Close
{
  const s = dark("Questions", "LedgerLens · roshanrana/LedgerLens · release 0.2.0 · design docs and the review-gate design in the repository");
}

pres.writeFile({ fileName: "C:/Code-Central/LedgerLens/docs/pitch/ledgerlens-architecture-deck.pptx" }).then((f) => console.log("wrote", f, "slides", n));

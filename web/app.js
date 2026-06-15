"use strict";

// AgentOps Cockpit — vanilla ES-module client. Pure projection of the harness
// run artifacts served by app/cockpit. The top strip is the live "at a glance"
// (SSE trajectory + guard summary); the deep-dive tabs showcase the entire
// RunRecord plus the raw artifact files the backend wrote on disk.

const ICON = {
  play: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  pause: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>',
  download: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>',
};

const PHASE_LABEL = { plan: "plan", worker: "worker", enforce: "enforce", tests: "tests", review: "review" };
const RISK_TONE = { low: "t-green", medium: "t-amber", high: "t-red", critical: "t-red" };
const TIER_TONE = { auto: "b-green", ask: "b-amber", deny: "b-red" };
const SEV_TONE = { info: "b-mut", warning: "b-amber", error: "b-red" };
const VERDICT_TONE = {
  aligned: "t-green", pass: "t-green",
  incomplete: "t-amber", concern: "t-amber", drifted: "t-amber", overbuilt: "t-amber", unclear: "t-amber",
  fail: "t-red", not_evaluated: "t-mut",
};

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function fmtAge(iso) {
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}
const fmtDur = s => (s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`);
const fmtBytes = n => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);

async function api(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${resp.status} ${path}`);
  return resp.json();
}
async function apiText(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${resp.status}`);
  return resp.text();
}

const state = { runs: [], selected: null, es: null, wes: null, detail: null, tab: "plan", wfilter: "all" };

async function init() {
  await loadRuns();
  if (state.runs[0]) selectRun(state.runs[0].run_id);
}

async function loadRuns() {
  const data = await api("/cockpit/api/runs?limit=50");
  state.runs = data.runs;
  renderStats(data.stats);
  renderRunList();
}

function renderStats(s) {
  document.getElementById("kTotal").textContent = s.total;
  document.getElementById("kPass").textContent = `${s.pass_rate}%`;
  document.getElementById("kRisk").textContent = s.avg_risk;
  const ind = document.getElementById("liveInd");
  if (s.running > 0) {
    ind.className = "live on";
    ind.innerHTML = `<span class="dot pulse"></span>${s.running} live`;
  } else {
    ind.className = "live";
    ind.innerHTML = `<span class="dot"></span>idle`;
  }
}

function statusDot(run) {
  if (run.blocked) return '<span class="dot" style="background:var(--red)"></span>';
  if (run.status === "completed") return '<span class="dot" style="background:var(--green)"></span>';
  if (run.status === "failed") return '<span class="dot" style="background:var(--red)"></span>';
  return '<span class="dot pulse" style="background:var(--amber)"></span>';
}

function renderRunList() {
  const host = document.getElementById("runs");
  if (!state.runs.length) { host.innerHTML = '<div class="empty">No runs yet.</div>'; return; }
  host.innerHTML = state.runs.map(r => `
    <button class="run" data-id="${esc(r.run_id)}">
      <span style="margin-top:4px">${statusDot(r)}</span>
      <span class="run-main">
        <div class="run-task">${esc(r.task)}</div>
        <div class="run-meta">${esc(r.run_id.slice(0, 4))} · ${esc(fmtAge(r.completed_at))} · ${r.tests_passed}/${r.tests_total} tests</div>
      </span>
      <span class="risk ${RISK_TONE[r.risk_level] || "t-mut"}">${r.risk_score}</span>
    </button>`).join("");
  host.querySelectorAll(".run").forEach(b => b.addEventListener("click", () => selectRun(b.dataset.id)));
  markSelected();
}

function markSelected() {
  document.querySelectorAll(".run").forEach(b => b.classList.toggle("sel", b.dataset.id === state.selected));
}

function closeStreams() {
  if (state.es) { state.es.close(); state.es = null; }
  if (state.wes) { state.wes.close(); state.wes = null; }
}

async function selectRun(runId) {
  state.selected = runId;
  markSelected();
  closeStreams();
  const insp = document.getElementById("inspector");
  insp.innerHTML = '<div class="empty">Loading run…</div>';
  try {
    state.detail = await api(`/cockpit/api/runs/${runId}`);
  } catch (err) {
    insp.innerHTML = `<div class="empty">Failed to load: ${esc(err.message)}</div>`;
    return;
  }
  renderInspector(state.detail);
  streamTrajectory(runId);
}

function renderInspector(d) {
  const s = d.summary, rec = d.record;
  const statusTone = s.blocked ? "t-red" : s.status === "completed" ? "t-green" : "t-amber";
  const statusBg = s.blocked ? "var(--red-bg)" : s.status === "completed" ? "var(--green-bg)" : "var(--amber-bg)";
  document.getElementById("inspector").innerHTML = `
    <div class="insp-head">
      <div class="insp-head-l">
        <span class="pill ${statusTone}" style="background:${statusBg}">${esc(s.blocked ? "blocked" : s.status)}</span>
        <span class="insp-task">${esc(s.task)}</span>
      </div>
      <a class="dl-btn" href="/cockpit/api/runs/${esc(s.run_id)}/bundle.zip" download>${ICON.download}bundle.zip</a>
    </div>
    <div class="insp-meta">${esc(s.run_id.slice(0, 8))} · ${esc(s.worker)} · ${fmtDur(s.duration_seconds)} · attempt ${s.attempts} · converged ${s.converged} · ${esc(s.repo_path)}</div>
    <div class="ribbon">${d.phases.map(phaseEl).join("")}</div>
    <div class="insp-body">
      <div class="card">
        <div class="card-head">
          <span class="lbl"><span class="dot pulse" style="background:var(--green)" id="trajDot"></span>Governance loop <span class="sub">· outer (AgentOps)</span></span>
          <button class="btn-ghost" id="pauseBtn">${ICON.pause}<span>pause</span></button>
        </div>
        <div class="traj" id="traj"></div>
      </div>
      <div class="guards">${guardCards(s, rec)}</div>
    </div>
    <div class="deep">
      <div class="tabs" id="tabs">${TABS.map(t => tabBtn(t, d)).join("")}</div>
      <div class="tabbody" id="tabbody"></div>
    </div>`;
  document.getElementById("pauseBtn").addEventListener("click", togglePause);
  document.querySelectorAll("#tabs .tab").forEach(b => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  if (!TABS.some(t => t.key === state.tab)) state.tab = "plan";
  selectTab(state.tab);
}

const phaseEl = p => `<div class="phase ${p.status}"><span class="ph-icon">${phaseGlyph(p.status)}</span>${esc(PHASE_LABEL[p.name] || p.name)}</div>`;
function phaseGlyph(status) {
  if (status === "done") return "✓";
  if (status === "active") return ICON.play;
  if (status === "skipped") return "–";
  return "·";
}

function guardCards(s, rec) {
  const counts = tierCounts(rec.permission_report);
  const ev = rec.evidence_report || {};
  return `
    <div class="guard">
      <div class="g-lbl">Risk assessment</div>
      <div><span class="g-big ${RISK_TONE[s.risk_level] || "t-mut"}">${s.risk_score}</span>
        <span class="${RISK_TONE[s.risk_level] || "t-mut"}" style="font-size:12px">${esc(s.risk_level)}</span></div>
      <div class="g-val t-mut" style="margin-top:4px;font-size:12px">${esc((rec.risk_report?.factors || [])[0] || "")}</div>
    </div>
    <div class="guard">
      <div class="g-lbl">Permissions</div>
      <div class="g-val mono">${counts.auto} auto · ${counts.ask} ask · <span class="${counts.deny ? "t-red" : "t-green"}">${counts.deny} deny</span></div>
    </div>
    <div class="guard">
      <div class="g-lbl">Evidence guard</div>
      <div class="g-val ${ev.unsupported_claim_count ? "t-amber" : "t-green"}">
        ${ev.unsupported_claim_count ? `${ev.unsupported_claim_count} flag${ev.unsupported_claim_count === 1 ? "" : "s"}` : "✓ 0 flags · grounded"}</div>
    </div>
    <div class="guard">
      <div class="g-lbl">Product review</div>
      <div class="g-val"><span class="${VERDICT_TONE[s.product_verdict] || "t-mut"}">${esc(s.product_verdict.replace(/_/g, " "))}</span>
        <span class="t-mut" style="font-size:12px"> · ${lensSummary(rec.product_review)}</span></div>
    </div>`;
}

function tierCounts(perm) {
  const c = { auto: 0, ask: 0, deny: 0 };
  ((perm && perm.decisions) || []).forEach(x => { c[x.tier] = (c[x.tier] || 0) + 1; });
  return c;
}
function lensSummary(pr) {
  const lenses = Object.values((pr && pr.per_lens) || {});
  if (!lenses.length) return "4 lenses";
  return `${lenses.filter(v => v === "pass").length}/${lenses.length} lenses`;
}

// ── live trajectory via SSE ──────────────────────────────────────────────
function streamTrajectory(runId) {
  const host = document.getElementById("traj");
  if (!host) return;
  host.innerHTML = "";
  const es = new EventSource(`/cockpit/api/runs/${runId}/stream`);
  state.es = es;
  es.addEventListener("event", e => appendEvent(host, JSON.parse(e.data)));
  es.addEventListener("done", finishStream);
  es.addEventListener("error", finishStream);
}
function appendEvent(host, ev) {
  const row = document.createElement("div");
  row.className = `ev ${ev.tone || "info"}`;
  const node = ev.node || ev.raw || "";
  const ph = ev.phase && ev.phase !== "event" ? ev.phase : "";
  row.innerHTML = `<span class="idx">${ev.index}</span><span class="node">${esc(node)}</span>${ph ? `<span class="ph">${esc(ph)}</span>` : ""}`;
  host.appendChild(row);
  host.scrollTop = host.scrollHeight;
}
function finishStream() {
  if (state.es) { state.es.close(); state.es = null; }
  document.getElementById("trajDot")?.classList.remove("pulse");
  const btn = document.getElementById("pauseBtn");
  if (btn) btn.style.display = "none";
}
function togglePause() {
  if (state.es) {
    state.es.close(); state.es = null;
    document.getElementById("trajDot")?.classList.remove("pulse");
    const btn = document.getElementById("pauseBtn"); if (btn) btn.innerHTML = `${ICON.play}<span>resume</span>`;
  } else if (state.selected) {
    streamTrajectory(state.selected);
    const btn = document.getElementById("pauseBtn"); if (btn) btn.innerHTML = `${ICON.pause}<span>pause</span>`;
  }
}

// ── deep-dive tabs (full record showcase) ────────────────────────────────
const TABS = [
  { key: "plan", label: "Plan", count: d => d.record.plan?.steps?.length, render: tabPlan },
  { key: "diff", label: "Diff", count: d => d.record.changed_files?.length, render: tabDiff },
  { key: "tests", label: "Tests", count: d => d.record.test_results?.commands?.length, render: tabTests },
  { key: "worker", label: "Worker loop", count: d => d.worker?.count || undefined, render: tabWorker },
  { key: "governance", label: "Governance", render: tabGovernance },
  { key: "product", label: "Product", count: d => d.record.product_review?.findings?.length, render: tabProduct },
  { key: "graph", label: "Graph", render: tabGraph },
  { key: "report", label: "Report", render: tabReport },
  { key: "files", label: "Files", count: d => d.artifacts?.length, render: tabFiles },
];
const tabBtn = (t, d) => {
  const n = t.count ? t.count(d) : undefined;
  return `<button class="tab" data-tab="${t.key}">${t.label}${n != null ? `<span class="ct">${n}</span>` : ""}</button>`;
};
function selectTab(key) {
  state.tab = key;
  if (state.wes) { state.wes.close(); state.wes = null; }  // stop inner stream when leaving Worker tab
  document.querySelectorAll("#tabs .tab").forEach(b => b.classList.toggle("sel", b.dataset.tab === key));
  const body = document.getElementById("tabbody");
  const tab = TABS.find(t => t.key === key) || TABS[0];
  body.innerHTML = tab.render(state.detail);
  if (tab.after) tab.after(state.detail);
}

function sec(title, inner) { return `<div class="sec"><div class="sec-h">${esc(title)}</div>${inner}</div>`; }
function kv(rows) { return `<table class="kv">${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="mono">${v}</td></tr>`).join("")}</table>`; }
function chips(items) { return items?.length ? `<div class="chips">${items.map(x => `<span class="chip">${esc(x)}</span>`).join("")}</div>` : ""; }
function jsonView(obj) { return `<pre class="code">${esc(JSON.stringify(obj ?? {}, null, 2))}</pre>`; }
function emptyNote(t) { return `<div class="note">${esc(t)}</div>`; }

function tabPlan(d) {
  const p = d.record.plan || {};
  const steps = (p.steps || []).map((s, i) => `
    <div class="step">
      <div class="step-t">${i + 1}. ${esc(s.title || "")}</div>
      <div class="step-d">${esc(s.description || "")}</div>
      ${s.files_to_edit?.length ? `<div class="step-d" style="margin-top:5px">edit: ${chips(s.files_to_edit)}</div>` : ""}
      ${s.files_to_inspect?.length ? `<div class="step-d" style="margin-top:3px">inspect: ${chips(s.files_to_inspect)}</div>` : ""}
    </div>`).join("");
  return [
    p.summary ? sec("Summary", `<div class="finding-b">${esc(p.summary)}</div>`) : "",
    steps ? sec(`Steps (${p.steps.length})`, steps) : "",
    p.acceptance_criteria?.length ? sec("Acceptance criteria", `<ul>${p.acceptance_criteria.map(a => `<li class="finding-b">${esc(a)}</li>`).join("")}</ul>`) : "",
    p.tests_to_run?.length ? sec("Tests to run", chips(p.tests_to_run)) : "",
  ].join("") || emptyNote("No plan recorded.");
}

function tabDiff(d) {
  const rec = d.record;
  const hasPatch = (d.artifacts || []).some(a => a.name === "diff.patch");
  return [
    sec("Changed files", rec.changed_files?.length ? chips(rec.changed_files) : emptyNote("No files changed (observe mode makes no edits).")),
    rec.deleted_files?.length ? sec("Deleted files", chips(rec.deleted_files)) : "",
    rec.diff_summary ? sec("Diff summary", `<div class="finding-b">${esc(rec.diff_summary)}</div>`) : "",
    sec("Patch", hasPatch ? `<pre class="code" id="diffPane">loading diff.patch…</pre>` : emptyNote("No diff.patch artifact for this run.")),
  ].join("");
}
TABS.find(t => t.key === "diff").after = d => {
  const pane = document.getElementById("diffPane");
  if (!pane) return;
  apiText(`/cockpit/api/runs/${d.summary.run_id}/artifacts/diff.patch`)
    .then(txt => { pane.innerHTML = colorizeDiff(txt); })
    .catch(() => { pane.textContent = "Could not load diff.patch"; });
};
function colorizeDiff(txt) {
  return txt.split("\n").map(line => {
    const e = esc(line);
    if (line.startsWith("+")) return `<span class="da">${e}</span>`;
    if (line.startsWith("-")) return `<span class="dd">${e}</span>`;
    if (line.startsWith("@@") || line.startsWith("diff ") || line.startsWith("index ")) return `<span class="dm">${e}</span>`;
    return `<span class="dc">${e}</span>`;
  }).join("\n");
}

function tabTests(d) {
  const cmds = d.record.test_results?.commands || [];
  if (!cmds.length) return emptyNote("No test commands recorded.");
  return cmds.map(c => {
    const ok = c.exit_code === 0;
    const out = (c.stdout || "") + (c.stderr ? `\n${c.stderr}` : "");
    return sec("", `
      <div class="finding-h">
        <span class="badge ${ok ? "b-green" : "b-red"}">${ok ? "exit 0" : `exit ${c.exit_code}`}</span>
        <code class="cite">${esc(c.command)}</code>
        <span class="cite" style="margin-left:auto">${(c.duration_seconds ?? 0).toFixed(2)}s</span>
      </div>
      ${out.trim() ? `<pre class="code">${esc(out.trim().slice(0, 4000))}</pre>` : ""}`);
  }).join("");
}

function tabWorker(d) {
  const w = d.worker || {};
  if (!w.present) return workerEmpty(d);
  const s = w.summary || {}, sc = w.scorecard || {};
  const mach = `<div class="mach">
    ${machCell("Loop owner", s.loop_owner || "openhands_sdk")}
    ${machCell("Model", s.model || "—")}
    ${machCell("Observable events", w.count)}
    ${machCell("Status", s.status || "—")}
    ${machCell("Termination", s.termination_reason || "—")}
    ${machCell("AgentOps role", s.agentops_role || "outer_governor")}
  </div>`;
  const tools = s.tools_requested?.length ? sec("Inner agent tools", chips(s.tools_requested)) : "";
  const k = {};
  (w.events || []).forEach(e => { k[e.kind] = (k[e.kind] || 0) + 1; });
  const opt = (v, label) => `<option value="${v}">${label}</option>`;
  const toolbar = `<div class="wtoolbar">
    <span class="sec-h" style="margin:0"><span class="dot pulse" style="background:var(--green)" id="wDot"></span>Inner tool trajectory <span class="sub">· streaming ${w.count} events</span></span>
    <select class="csel" id="wfilter" style="margin-left:auto">
      ${opt("all", "all kinds")}${opt("action", `actions (${k.action || 0})`)}${opt("observation", `observations (${k.observation || 0})`)}${opt("message", `messages (${k.message || 0})`)}${opt("state", `state (${k.state || 0})`)}
    </select></div>`;
  const traj = `<div class="itraj" id="wtraj"></div>`;
  const scRows = [
    ["changed files", sc.changed_file_count],
    ["worker ran tests", sc.tests_attempted_by_worker],
    ["agentops tests passed", sc.agentops_tests_passed],
    ["permission violations", sc.permission_violations],
    ["unsupported claims", sc.unsupported_claims],
    ["convergence", sc.convergence_type],
  ].filter(([, v]) => v != null).map(([key, v]) => [key, esc(String(v))]);
  const scCard = scRows.length ? dd("Worker scorecard", kv(scRows), sc.convergence_type || "") : "";
  return mach + tools + toolbar + traj + scCard;
}
const machCell = (l, v) => `<div class="m"><div class="m-l">${esc(l)}</div><div class="m-v mono">${esc(v)}</div></div>`;
function ievRow(e) {
  const expandable = e.full && e.full.length > (e.summary || "").length;
  return `<div class="iev k-${esc(e.kind)}${expandable ? " exp" : ""}" data-kind="${esc(e.kind)}">
    <div class="iev-line">
      <span class="iev-chev">${expandable ? "›" : ""}</span>
      <span class="iev-type">${esc(e.type)}</span>
      ${e.tool ? `<span class="iev-tool">${esc(e.tool)}</span>` : ""}
      <span class="iev-sum">${esc(e.summary || e.source || "")}</span>
    </div>
    ${expandable ? `<pre class="iev-full" hidden>${esc(e.full)}</pre>` : ""}
  </div>`;
}
function applyFilterToRow(row) {
  row.style.display = (state.wfilter === "all" || row.dataset.kind === state.wfilter) ? "" : "none";
}
function streamWorker(runId) {
  const host = document.getElementById("wtraj");
  if (!host) return;
  host.innerHTML = "";
  const es = new EventSource(`/cockpit/api/runs/${runId}/worker/stream`);
  state.wes = es;
  es.addEventListener("event", e => {
    host.insertAdjacentHTML("beforeend", ievRow(JSON.parse(e.data)));
    applyFilterToRow(host.lastElementChild);
    host.scrollTop = host.scrollHeight;
  });
  const stop = () => { if (state.wes) { state.wes.close(); state.wes = null; } document.getElementById("wDot")?.classList.remove("pulse"); };
  es.addEventListener("done", stop);
  es.addEventListener("error", stop);
}
TABS.find(t => t.key === "worker").after = d => {
  if (!d.worker?.present) return;
  const sel = document.getElementById("wfilter");
  if (sel) {
    sel.value = state.wfilter;
    sel.addEventListener("change", () => {
      state.wfilter = sel.value;
      document.querySelectorAll("#wtraj .iev").forEach(applyFilterToRow);
    });
  }
  document.getElementById("wtraj")?.addEventListener("click", e => {
    const row = e.target.closest(".iev.exp");
    if (!row) return;
    row.classList.toggle("open");
    const full = row.querySelector(".iev-full");
    if (full) full.hidden = !row.classList.contains("open");
  });
  streamWorker(d.summary.run_id);
};
function dd(title, inner, tag = "", open = false) {
  return `<details class="dd"${open ? " open" : ""}><summary>${esc(title)}${tag ? `<span class="dd-tag sub">${esc(tag)}</span>` : ""}</summary><div class="dd-body">${inner}</div></details>`;
}
function workerEmpty(d) {
  return `<div class="bigempty">
    <div class="be-h">No inner loop recorded for this run</div>
    <div class="be-p">This run used the <b>${esc(d.summary.worker)}</b> path. The panel above streams the <b>outer</b> AgentOps governance loop — the node lifecycle that grades the work.</div>
    <div class="be-p">The <b>inner</b> loop is the model's own <code>prompt → tool → observation</code> iterations (50–200×). It only emits events for the OpenHands worker, captured live to <code>openhands_events.jsonl</code>.</div>
    <div class="be-p">Populate it with an edit run:<br><code>uv run agentops edit --repo &lt;repo&gt; --task "…" --worker-type openhands</code></div>
  </div>`;
}

function tabGovernance(d) {
  const rec = d.record;
  const risk = rec.risk_report || {};
  const perm = rec.permission_report || {};
  const ev = rec.evidence_report || {};
  const rev = rec.review_report || {};
  const conf = rec.conflict_report || {};
  const ver = rec.verification_bundle || {};

  const riskSec = dd("Risk guard", kv([
    ["score", `<span class="${RISK_TONE[risk.risk_level] || "t-mut"}">${risk.risk_score}</span>`],
    ["level", esc(risk.risk_level || "")],
    ["blocked", String(risk.blocked)],
    ["factors", (risk.factors || []).map(f => esc(f)).join("<br>") || "—"],
  ]), `${risk.risk_score} · ${risk.risk_level || ""}`, true);

  const decisions = (perm.decisions || []).map(x => `
    <div class="finding">
      <div class="finding-h"><span class="badge ${TIER_TONE[x.tier] || "b-mut"}">${esc(x.tier)}</span><code class="cite">${esc(x.action)}</code></div>
      <div class="finding-b">${esc(x.reason || "")} <span class="cite">(${esc(x.rule || "")})</span></div>
    </div>`).join("");
  const tiers = tierCounts(perm);
  const permSec = dd("Permission gate",
    (decisions || emptyNote("No classified actions."))
    + (perm.enforced_reverts?.length ? `<div class="note">enforced reverts: ${chips(perm.enforced_reverts)}</div>` : ""),
    `${tiers.auto}/${tiers.ask}/${tiers.deny} auto·ask·deny`);

  const evFindings = (ev.findings || []).map(f => `
    <div class="finding sev-${esc(f.severity)}">
      <div class="finding-h"><span class="badge ${SEV_TONE[f.severity] || "b-mut"}">${esc(f.severity)}</span><b>${esc(f.claim)}</b></div>
      <div class="finding-b">${esc(f.reason)}</div>
      ${f.citation ? `<div class="cite">cite: ${esc(f.citation)}</div>` : ""}
    </div>`).join("");
  const evSec = dd("Evidence guard", kv([
    ["grounded", `<span class="${ev.grounded ? "t-green" : "t-amber"}">${String(ev.grounded)}</span>`],
    ["unsupported claims", String(ev.unsupported_claim_count ?? 0)],
  ]) + (evFindings || `<div class="note" style="margin-top:8px">✓ all claims grounded in run evidence</div>`),
    `${ev.unsupported_claim_count ?? 0} flags`);

  const revSec = dd("Reviewer", `<div class="finding-b">${esc(rev.summary || "—")}</div>`
    + (rev.findings?.length ? jsonView(rev.findings) : ""));

  return riskSec + permSec + evSec + revSec
    + dd("Conflict auditor", isEmpty(conf) ? emptyNote("No conflicts recorded.") : jsonView(conf))
    + dd("Verification stack", isEmpty(ver) ? emptyNote("No verification bundle.") : jsonView(ver));
}
function isEmpty(o) { return !o || (typeof o === "object" && Object.values(o).every(v => v == null || (Array.isArray(v) && !v.length) || v === "" || v === false)); }

function tabProduct(d) {
  const pr = d.record.product_review || {};
  const perLens = Object.entries(pr.per_lens || {}).map(([lens, v]) =>
    `<span class="badge ${(VERDICT_TONE[v] || "t-mut").replace("t-", "b-")}">${esc(lens)}: ${esc(v)}</span>`).join(" ");
  const findings = (pr.findings || []).map(f => `
    <div class="finding v-${esc(f.verdict)}">
      <div class="finding-h">
        <span class="badge ${(VERDICT_TONE[f.verdict] || "t-mut").replace("t-", "b-")}">${esc(f.verdict)}</span>
        <b>${esc(f.lens)}</b><span class="cite">confidence: ${esc(f.confidence)}</span>
      </div>
      <div class="finding-b">${esc(f.observation)}</div>
      ${f.recommendation ? `<div class="finding-b" style="margin-top:4px"><b>→</b> ${esc(f.recommendation)}</div>` : ""}
      <div class="cite">cite: ${esc(f.citation || f.source_of_truth)}</div>
    </div>`).join("");
  return [
    sec("Overall verdict", `<span class="badge ${(VERDICT_TONE[pr.overall_verdict] || "t-mut").replace("t-", "b-")}">${esc((pr.overall_verdict || "").replace(/_/g, " "))}</span>${pr.summary ? `<div class="finding-b" style="margin-top:6px">${esc(pr.summary)}</div>` : ""}`),
    perLens ? sec("Per lens", `<div class="finding-h">${perLens}</div>`) : "",
    findings ? sec(`Findings (${pr.findings.length})`, findings) : emptyNote("No findings — author agentops.goals.yaml to enable product review."),
  ].join("");
}

function tabGraph(d) {
  const rec = d.record;
  const prof = rec.repo_profile || {};
  const cg = rec.changed_subgraph || {};
  const rg = rec.repo_graph || {};
  const profRows = Object.entries(prof).filter(([, v]) => typeof v !== "object").map(([k, v]) => [k, esc(v)]);
  return [
    profRows.length ? sec("Repo profile", kv(profRows)) : "",
    sec("Impacted subgraph", isEmpty(cg) ? emptyNote("No impacted nodes (no diff).") : jsonView(cg)),
    sec("Repo graph", isEmpty(rg) ? emptyNote("No repo graph.") : jsonView(graphCounts(rg))),
  ].join("");
}
function graphCounts(rg) {
  const out = {};
  for (const [k, v] of Object.entries(rg)) out[k] = Array.isArray(v) ? `${v.length} items` : v;
  return out;
}

function tabReport(d) {
  const md = d.record.final_report?.markdown || "";
  return md ? `<div class="md">${mdToHtml(md)}</div>` : emptyNote("No final report.");
}
function mdToHtml(md) {
  const lines = esc(md).split("\n");
  let html = "", inList = false;
  const inline = s => s.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  for (const ln of lines) {
    if (/^### /.test(ln)) { html += closeList(); html += `<h3>${inline(ln.slice(4))}</h3>`; }
    else if (/^## /.test(ln)) { html += closeList(); html += `<h2>${inline(ln.slice(3))}</h2>`; }
    else if (/^# /.test(ln)) { html += closeList(); html += `<h1>${inline(ln.slice(2))}</h1>`; }
    else if (/^[-*] /.test(ln)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(ln.slice(2))}</li>`; }
    else if (ln.trim() === "") { html += closeList(); }
    else { html += closeList(); html += `<p>${inline(ln)}</p>`; }
  }
  function closeList() { if (inList) { inList = false; return "</ul>"; } return ""; }
  return html + closeList();
}

function tabFiles(d) {
  const files = d.artifacts || [];
  if (!files.length) return emptyNote("No artifact files on disk for this run.");
  const rows = files.map(f => `<div class="filerow" data-name="${esc(f.name)}"><span>${esc(f.name)}</span><span class="filesize">${fmtBytes(f.size)}</span></div>`).join("");
  return `<div class="sec"><div class="sec-h">Run artifact directory — ${files.length} files</div>${rows}</div><pre class="code" id="filePane" style="display:none"></pre>`;
}
TABS.find(t => t.key === "files").after = d => {
  document.querySelectorAll("#tabbody .filerow").forEach(row => row.addEventListener("click", () => {
    document.querySelectorAll("#tabbody .filerow").forEach(r => r.classList.remove("sel"));
    row.classList.add("sel");
    const pane = document.getElementById("filePane");
    pane.style.display = "block";
    pane.textContent = "loading…";
    const name = row.dataset.name;
    apiText(`/cockpit/api/runs/${d.summary.run_id}/artifacts/${encodeURIComponent(name)}`)
      .then(txt => { pane.innerHTML = name.endsWith(".patch") ? colorizeDiff(txt) : esc(txt); })
      .catch(() => { pane.textContent = "Could not load file."; });
  }));
};

init();

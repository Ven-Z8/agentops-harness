"use strict";

export const ICON = {
  play: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  pause: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>',
  download: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>',
};

export const RISK_TONE = { low: "t-green", medium: "t-amber", high: "t-red", critical: "t-red" };
export const TIER_TONE = { auto: "b-green", ask: "b-amber", deny: "b-red" };
export const SEV_TONE = { info: "b-mut", warning: "b-amber", error: "b-red" };
export const VERDICT_TONE = {
  aligned: "t-green", pass: "t-green",
  incomplete: "t-amber", concern: "t-amber", drifted: "t-amber", overbuilt: "t-amber", unclear: "t-amber",
  fail: "t-red", not_evaluated: "t-mut",
};

export const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function fmtAge(iso) {
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}
export const fmtDur = s => (s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`);
export const fmtBytes = n => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);

export function renderStats(s) {
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

export function statusDot(run) {
  if (run.blocked) return '<span class="dot" style="background:var(--red)"></span>';
  if (run.status === "completed") return '<span class="dot" style="background:var(--green)"></span>';
  if (run.status === "failed") return '<span class="dot" style="background:var(--red)"></span>';
  return '<span class="dot pulse" style="background:var(--amber)"></span>';
}

export function renderRunList(runs, { selected, onSelectRun }) {
  const host = document.getElementById("runs");
  if (!runs.length) { host.innerHTML = '<div class="empty">No runs yet.</div>'; return; }
  host.innerHTML = runs.map(r => `
    <button class="run" data-id="${esc(r.run_id)}">
      <span style="margin-top:4px">${statusDot(r)}</span>
      <span class="run-main">
        <div class="run-task">${esc(r.task)}</div>
        <div class="run-meta">${esc(r.run_id.slice(0, 4))} · ${esc(fmtAge(r.completed_at))} · ${r.tests_passed}/${r.tests_total} tests</div>
      </span>
      <span class="risk ${RISK_TONE[r.risk_level] || "t-mut"}">${r.risk_score}</span>
    </button>`).join("");
  host.querySelectorAll(".run").forEach(b => b.addEventListener("click", () => onSelectRun(b.dataset.id)));
  markSelected(selected);
}

export function markSelected(selected) {
  document.querySelectorAll(".run").forEach(b => b.classList.toggle("sel", b.dataset.id === selected));
}

export function renderInspector(vm, {
  detail,
  tabs,
  selectedTab,
  onSelectTab,
  onTogglePause,
}) {
  const run = vm.run;
  const statusTone = run.blocked ? "t-red" : run.status === "completed" ? "t-green" : "t-amber";
  const statusBg = run.blocked ? "var(--red-bg)" : run.status === "completed" ? "var(--green-bg)" : "var(--amber-bg)";
  document.getElementById("inspector").innerHTML = `
    <div class="insp-head">
      <div class="insp-head-l">
        <span class="pill ${statusTone}" style="background:${statusBg}">${esc(run.blocked ? "blocked" : run.status)}</span>
        <span class="insp-task">${esc(run.task)}</span>
      </div>
      <a class="dl-btn" href="${esc(vm.artifacts.bundleUrl)}" download>${ICON.download}bundle.zip</a>
    </div>
    <div class="insp-meta">${esc(run.id.slice(0, 8))} · ${esc(run.worker)} · ${fmtDur(run.duration)} · attempt ${run.attempts} · converged ${run.converged} · ${esc(run.repository)}</div>
    <div class="ribbon">${vm.stages.map(phaseEl).join("")}</div>
    <div class="insp-body">
      <div class="card">
        <div class="card-head">
          <span class="lbl"><span class="dot pulse" style="background:var(--green)" id="trajDot"></span>Governance loop <span class="sub">· outer (AgentOps)</span></span>
          <button class="btn-ghost" id="pauseBtn">${ICON.pause}<span>pause</span></button>
        </div>
        <div class="traj" id="traj"></div>
      </div>
      <div class="guards">${guardCards(vm)}</div>
    </div>
    <div class="deep">
      <div class="tabs" id="tabs">${tabs.map(t => tabBtn(t, detail)).join("")}</div>
      <div class="tabbody" id="tabbody"></div>
    </div>`;
  document.getElementById("pauseBtn").addEventListener("click", onTogglePause);
  document.querySelectorAll("#tabs .tab").forEach(b => b.addEventListener("click", () => onSelectTab(b.dataset.tab)));
  if (!tabs.some(t => t.key === selectedTab)) selectedTab = "plan";
  renderModelState(vm);
  onSelectTab(selectedTab);
}

export function renderModelState(vm) {
  const inspector = document.getElementById("inspector");
  if (inspector) {
    inspector.dataset.mode = vm.mode;
    inspector.dataset.stage = vm.selection?.stage || "plan";
    inspector.dataset.eventOrder = String(vm.selection?.event?.order ?? "");
  }
  document.getElementById("trajDot")?.classList.toggle("pulse", vm.pulse);
}

const STAGE_CLASS = {
  pass: "done",
  warn: "active",
  blocked: "active",
  unavailable: "skipped",
};

export const phaseEl = stage => `<div class="phase ${STAGE_CLASS[stage.status] || ""}" data-stage="${esc(stage.id)}" data-status="${esc(stage.status)}"><span class="ph-icon">${phaseGlyph(stage.status)}</span>${esc(stage.label)}</div>`;
export function phaseGlyph(status) {
  if (status === "pass") return "✓";
  if (status === "warn") return ICON.play;
  if (status === "blocked") return "×";
  if (status === "unavailable") return "–";
  return "·";
}

export function guardCards(vm) {
  const risk = vm.proof.risk;
  const permissions = vm.proof.permissions;
  const evidence = vm.proof.evidence;
  const product = vm.proof.product;
  const productVerdict = product.verdict || product.overall_verdict || "not_evaluated";
  const evidenceUnavailable = evidence.available === false;
  const evidenceFlags = evidence.unsupported_claim_count || 0;
  const evidenceText = evidenceUnavailable
    ? "unavailable"
    : evidenceFlags
      ? `${evidenceFlags} flag${evidenceFlags === 1 ? "" : "s"}`
      : evidence.grounded === false
        ? "not grounded"
        : "✓ 0 flags · grounded";
  const counts = tierCounts(permissions);
  return `
    <div class="guard">
      <div class="g-lbl">Risk assessment</div>
      <div><span class="g-big ${RISK_TONE[risk.risk_level] || "t-mut"}">${risk.risk_score}</span>
        <span class="${RISK_TONE[risk.risk_level] || "t-mut"}" style="font-size:12px">${esc(risk.risk_level)}</span></div>
      <div class="g-val t-mut" style="margin-top:4px;font-size:12px">${esc((risk.factors || [])[0] || "")}</div>
    </div>
    <div class="guard">
      <div class="g-lbl">Permissions</div>
      <div class="g-val mono">${counts.auto} auto · ${counts.ask} ask · <span class="${counts.deny ? "t-red" : "t-green"}">${counts.deny} deny</span></div>
    </div>
    <div class="guard">
      <div class="g-lbl">Evidence guard</div>
      <div class="g-val ${evidenceUnavailable ? "t-mut" : evidenceFlags || evidence.grounded === false ? "t-amber" : "t-green"}">${evidenceText}</div>
    </div>
    <div class="guard">
      <div class="g-lbl">Product review</div>
      <div class="g-val"><span class="${VERDICT_TONE[productVerdict] || "t-mut"}">${esc(productVerdict.replace(/_/g, " "))}</span>
        <span class="t-mut" style="font-size:12px"> · ${lensSummary(product)}</span></div>
    </div>`;
}

export function tierCounts(perm) {
  const c = { auto: 0, ask: 0, deny: 0 };
  ((perm && perm.decisions) || []).forEach(x => { c[x.tier] = (c[x.tier] || 0) + 1; });
  return c;
}
export function lensSummary(pr) {
  const lenses = Object.values((pr && pr.per_lens) || {});
  if (!lenses.length) return "4 lenses";
  return `${lenses.filter(v => v === "pass").length}/${lenses.length} lenses`;
}


export function appendEvent(host, ev) {
  const row = document.createElement("div");
  row.className = `ev ${ev.tone || "info"}`;
  const node = ev.node || ev.raw || "";
  const ph = ev.phase && ev.phase !== "event" ? ev.phase : "";
  row.innerHTML = `<span class="idx">${ev.index}</span><span class="node">${esc(node)}</span>${ph ? `<span class="ph">${esc(ph)}</span>` : ""}`;
  host.appendChild(row);
  host.scrollTop = host.scrollHeight;
}

export const tabBtn = (t, d) => {
  const n = t.count ? t.count(d) : undefined;
  return `<button class="tab" data-tab="${t.key}">${t.label}${n != null ? `<span class="ct">${n}</span>` : ""}</button>`;
};

export function sec(title, inner) { return `<div class="sec"><div class="sec-h">${esc(title)}</div>${inner}</div>`; }
export function kv(rows) { return `<table class="kv">${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="mono">${v}</td></tr>`).join("")}</table>`; }
export function chips(items) { return items?.length ? `<div class="chips">${items.map(x => `<span class="chip">${esc(x)}</span>`).join("")}</div>` : ""; }
export function jsonView(obj) { return `<pre class="code">${esc(JSON.stringify(obj ?? {}, null, 2))}</pre>`; }
export function emptyNote(t) { return `<div class="note">${esc(t)}</div>`; }

export function tabPlan(d) {
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

export function tabDiff(d) {
  const rec = d.record;
  const hasPatch = (d.artifacts || []).some(a => a.name === "diff.patch");
  return [
    sec("Changed files", rec.changed_files?.length ? chips(rec.changed_files) : emptyNote("No files changed (observe mode makes no edits).")),
    rec.deleted_files?.length ? sec("Deleted files", chips(rec.deleted_files)) : "",
    rec.diff_summary ? sec("Diff summary", `<div class="finding-b">${esc(rec.diff_summary)}</div>`) : "",
    sec("Patch", hasPatch ? `<pre class="code" id="diffPane">loading diff.patch…</pre>` : emptyNote("No diff.patch artifact for this run.")),
  ].join("");
}

export function colorizeDiff(txt) {
  return txt.split("\n").map(line => {
    const e = esc(line);
    if (line.startsWith("+")) return `<span class="da">${e}</span>`;
    if (line.startsWith("-")) return `<span class="dd">${e}</span>`;
    if (line.startsWith("@@") || line.startsWith("diff ") || line.startsWith("index ")) return `<span class="dm">${e}</span>`;
    return `<span class="dc">${e}</span>`;
  }).join("\n");
}

export function tabTests(d) {
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

export function tabWorker(d) {
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
export const machCell = (l, v) => `<div class="m"><div class="m-l">${esc(l)}</div><div class="m-v mono">${esc(v)}</div></div>`;
export function ievRow(e) {
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
export function applyFilterToRow(row, filter) {
  row.style.display = (filter === "all" || row.dataset.kind === filter) ? "" : "none";
}

export function dd(title, inner, tag = "", open = false) {
  return `<details class="dd"${open ? " open" : ""}><summary>${esc(title)}${tag ? `<span class="dd-tag sub">${esc(tag)}</span>` : ""}</summary><div class="dd-body">${inner}</div></details>`;
}
export function workerEmpty(d) {
  return `<div class="bigempty">
    <div class="be-h">No inner loop recorded for this run</div>
    <div class="be-p">This run used the <b>${esc(d.summary.worker)}</b> path. The panel above streams the <b>outer</b> AgentOps governance loop — the node lifecycle that grades the work.</div>
    <div class="be-p">The <b>inner</b> loop is the model's own <code>prompt → tool → observation</code> iterations (50–200×). It only emits events for the OpenHands worker, captured live to <code>openhands_events.jsonl</code>.</div>
    <div class="be-p">Populate it with an edit run:<br><code>uv run agentops edit --repo &lt;repo&gt; --task "…" --worker-type openhands</code></div>
  </div>`;
}

export function tabGovernance(d) {
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
export function isEmpty(o) { return !o || (typeof o === "object" && Object.values(o).every(v => v == null || (Array.isArray(v) && !v.length) || v === "" || v === false)); }

export function tabProduct(d) {
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

export function tabGraph(d) {
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
export function graphCounts(rg) {
  const out = {};
  for (const [k, v] of Object.entries(rg)) out[k] = Array.isArray(v) ? `${v.length} items` : v;
  return out;
}

export function tabReport(d) {
  const md = d.record.final_report?.markdown || "";
  return md ? `<div class="md">${mdToHtml(md)}</div>` : emptyNote("No final report.");
}
export function mdToHtml(md) {
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

export function tabFiles(d) {
  const files = d.artifacts || [];
  if (!files.length) return emptyNote("No artifact files on disk for this run.");
  const rows = files.map(f => `<div class="filerow" data-name="${esc(f.name)}"><span>${esc(f.name)}</span><span class="filesize">${fmtBytes(f.size)}</span></div>`).join("");
  return `<div class="sec"><div class="sec-h">Run artifact directory — ${files.length} files</div>${rows}</div><pre class="code" id="filePane" style="display:none"></pre>`;
}

export function renderTab(tabs, key, viewModel, detail) {
  document.querySelectorAll("#tabs .tab").forEach(b => b.classList.toggle("sel", b.dataset.tab === key));
  const body = document.getElementById("tabbody");
  const tab = tabs.find(t => t.key === key) || tabs[0];
  body.innerHTML = tab.render(detail, viewModel);
  return tab;
}

export function bindWorkerPanel({ filter, onFilterChange }) {
  const sel = document.getElementById("wfilter");
  if (sel) {
    sel.value = filter;
    sel.addEventListener("change", () => {
      onFilterChange(sel.value);
      document.querySelectorAll("#wtraj .iev").forEach(row => applyFilterToRow(row, sel.value));
    });
  }
  document.getElementById("wtraj")?.addEventListener("click", event => {
    const row = event.target.closest(".iev.exp");
    if (!row) return;
    row.classList.toggle("open");
    const full = row.querySelector(".iev-full");
    if (full) full.hidden = !row.classList.contains("open");
  });
}

export function bindArtifactRows(onSelectArtifact) {
  document.querySelectorAll("#tabbody .filerow").forEach(row => row.addEventListener("click", () => {
    document.querySelectorAll("#tabbody .filerow").forEach(candidate => candidate.classList.remove("sel"));
    row.classList.add("sel");
    const pane = document.getElementById("filePane");
    pane.style.display = "block";
    pane.textContent = "loading…";
    onSelectArtifact({ name: row.dataset.name, pane });
  }));
}

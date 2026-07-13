import assert from "node:assert/strict";
import test from "node:test";

import {
  artifactFailureMessage,
  fmtDur,
  guardCards,
  phaseEl,
  proofCards,
  renderModelState,
  selectedStageEvidence,
  stageButton,
  tabPlan,
  tabWorker,
} from "../ui/panels.js";

function inspectorModel() {
  return {
    run: { blocked: false },
    proof: {
      risk: { risk_score: 18, risk_level: "low", factors: ["small diff"] },
      permissions: {
        decisions: [{ action: "edit app.py", tier: "auto", reason: "in scope" }],
      },
      evidence: { unsupported_claim_count: 0 },
      product: { verdict: "aligned", per_lens: { intent: "pass" } },
    },
  };
}

test("stage ribbon renders normalized stage labels and availability", () => {
  const html = phaseEl({
    id: "equip",
    label: "Equip",
    status: "unavailable",
    layer: "worker",
  });

  assert.match(html, /phase skipped/);
  assert.match(html, /Equip/);
  assert.match(html, /–/);
});

test("guard cards consume normalized proof instead of a raw run record", () => {
  const html = guardCards(inspectorModel());

  assert.match(html, /18/);
  assert.match(html, /1 auto · 0 ask/);
  assert.match(html, /0 flags · grounded/);
  assert.match(html, /aligned/);
});

test("guard cards do not claim grounding when evidence is unavailable", () => {
  const model = inspectorModel();
  model.proof.evidence.available = false;

  const html = guardCards(model);

  assert.match(html, /Evidence guard[\s\S]*unavailable/);
  assert.doesNotMatch(html, /0 flags · grounded/);
});

test("model state rendering reflects normalized mode and pulse", () => {
  const toggles = [];
  const inspector = { dataset: {} };
  const dot = { classList: { toggle: (...args) => toggles.push(args) } };
  const priorDocument = globalThis.document;
  globalThis.document = {
    getElementById: id => ({ inspector, trajDot: dot }[id] || null),
  };

  try {
    renderModelState({
      mode: "disconnected",
      pulse: false,
      selection: { stage: "guard", event: { order: 3 } },
    });
  } finally {
    globalThis.document = priorDocument;
  }

  assert.equal(inspector.dataset.mode, "disconnected");
  assert.equal(inspector.dataset.stage, "guard");
  assert.equal(inspector.dataset.eventOrder, "3");
  assert.deepEqual(toggles, [["pulse", false]]);
});

test("deep-dive plan rendering still accepts raw detail", () => {
  const html = tabPlan({
    record: {
      plan: {
        summary: "Inspect then edit.",
        steps: [{ title: "Edit", description: "Change the file." }],
      },
    },
  });

  assert.match(html, /Inspect then edit/);
  assert.match(html, /Change the file/);
});

test("semantic stage buttons expose descriptive labels and current state", () => {
  const html = stageButton({
    stage: { id: "equip", label: "Equip", status: "pass" },
    selected: true,
    viewModel: {
      pack: { available: true, name: "pydantic-v2", version: "1.0.0" },
      proof: {},
    },
  });

  assert.match(html, /aria-label="Equip, pass, capability pack pydantic-v2 version 1\.0\.0"/);
  assert.match(html, /aria-current="step"/);
  assert.match(html, /data-stage="equip"/);
});

test("selected-stage evidence links only available files and names every missing file", () => {
  const html = selectedStageEvidence({
    run: { id: "run/1" },
    selection: {
      stage: "work",
      evidence: {
        expected: ["openhands_events.jsonl", "diff.patch", "worker_result.json"],
        available: ["diff.patch"],
        missing: ["openhands_events.jsonl", "worker_result.json"],
      },
    },
    errors: {},
  });

  assert.match(html, /data-evidence-name="diff\.patch"/);
  assert.doesNotMatch(html, /data-evidence-name="openhands_events\.jsonl"/);
  assert.match(html, /Missing expected artifact: openhands_events\.jsonl/);
  assert.match(html, /Missing expected artifact: worker_result\.json/);
});

test("proof cards render six required categories without false success defaults", () => {
  const html = proofCards({
    proof: {
      tests: { available: false, passed: null, total: null },
      scope: { available: false, planSteps: null, changedFiles: null },
      risk: { available: false },
      permissions: { available: false },
      evidence: { available: false },
      verification: { available: false },
      finalVerdict: "Unavailable",
    },
  });

  for (const label of ["Tests", "Plan scope", "Risk", "Permissions", "Evidence", "Verification"]) {
    assert.match(html, new RegExp(label));
  }
  assert.doesNotMatch(html, /0\/0|100%|Accepted/);
  assert.match(html, /unavailable/);
});

test("artifact failure copy names only the affected artifact", () => {
  assert.equal(
    artifactFailureMessage("risk_report.json"),
    "Could not load risk_report.json. Other evidence remains available.",
  );
});

test("missing durations render as unavailable instead of a zero or NaN metric", () => {
  assert.equal(fmtDur(null), "unavailable");
  assert.equal(fmtDur(undefined), "unavailable");
});

test("recorded worker panel has no pulse or live label on its first render", () => {
  const html = tabWorker({
    summary: { worker: "openhands" },
    worker: {
      present: true,
      count: 1,
      summary: { status: "completed" },
      scorecard: {},
      events: [{ kind: "action", type: "ActionEvent", summary: "edit" }],
    },
  }, {
    mode: "recorded",
    modeLabel: "Recorded",
    pulse: false,
    errors: {},
  });

  assert.doesNotMatch(html, /class="dot pulse"/);
  assert.doesNotMatch(html, /\blive\b/i);
  assert.match(html, /Recorded · 1 event/);
});

import assert from "node:assert/strict";
import test from "node:test";

import { guardCards, phaseEl, renderModelState, tabPlan } from "../ui/panels.js";

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

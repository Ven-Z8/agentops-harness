import assert from "node:assert/strict";
import test from "node:test";

import {
  cameraPreset,
  interpolateCamera,
  stageVisual,
} from "../scene/transitions.js";
import * as transitions from "../scene/transitions.js";

const STAGES = ["plan", "equip", "work", "guard", "prove"];
const STATUSES = ["pending", "active", "pass", "warn", "blocked", "unavailable"];

test("each stage has a bounded camera preset", () => {
  for (const stage of STAGES) {
    const preset = cameraPreset(stage);
    assert.equal(preset.position.length, 3);
    assert.equal(preset.target.length, 3);
    assert.ok(preset.position.every(value => Math.abs(value) <= 18));
  }
});

test("camera interpolation clamps progress to the transition bounds", () => {
  const from = { position: [0, 2, 4], target: [0, 0, 0] };
  const to = { position: [8, 6, 12], target: [4, 2, 0] };

  assert.deepEqual(interpolateCamera(from, to, -1), from);
  assert.deepEqual(interpolateCamera(from, to, 2), to);
  assert.deepEqual(interpolateCamera(from, to, 0.5), {
    position: [4, 4, 8],
    target: [2, 1, 0],
  });
});

test("reduced motion applies the destination immediately", () => {
  const from = { position: [0, 0, 0], target: [0, 0, 0] };
  const to = cameraPreset("guard");
  assert.deepEqual(interpolateCamera(from, to, 0.25, true), to);
});

test("every stage status carries material and non-color meaning", () => {
  for (const status of STATUSES) {
    const visual = stageVisual(status);
    assert.equal(typeof visual.color, "number");
    assert.equal(typeof visual.emissive, "number");
    assert.equal(typeof visual.opacity, "number");
    assert.ok(visual.opacity > 0 && visual.opacity <= 1);
    assert.ok(visual.glyph.length > 0);
    assert.ok(visual.label.length > 0);
  }
});

test("unavailable is visibly distinct without color-only meaning", () => {
  assert.deepEqual(stageVisual("unavailable"), {
    color: 0x64748b,
    emissive: 0x0f172a,
    opacity: 0.42,
    glyph: "×",
    label: "Unavailable",
  });
});

test("hidden scene lifecycle cancels motion and visibility return does not resume it", () => {
  assert.equal(typeof transitions.pauseSceneForVisibility, "function");
  assert.equal(typeof transitions.sceneShouldAnimate, "function");
  const hidden = transitions.pauseSceneForVisibility({
    transition: { startedAt: 10 },
    playbackActive: true,
  });

  assert.deepEqual(hidden, { transition: null, playbackActive: false });
  assert.equal(transitions.sceneShouldAnimate({
    hidden: true,
    reducedMotion: false,
    ...hidden,
  }), false);
  assert.equal(transitions.sceneShouldAnimate({
    hidden: false,
    reducedMotion: false,
    ...hidden,
  }), false);
});

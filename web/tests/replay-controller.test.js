import assert from "node:assert/strict";
import test from "node:test";

import { createReplayState, reduceReplay } from "../replay-controller.js";

test("play pause restart and stage selection are deterministic", () => {
  let state = createReplayState({ length: 5 });
  state = reduceReplay(state, { type: "play" });
  state = reduceReplay(state, { type: "tick" });
  state = reduceReplay(state, { type: "pause" });
  assert.deepEqual(
    { playing: state.playing, cursor: state.cursor },
    { playing: false, cursor: 0 },
  );
  state = reduceReplay(state, { type: "select-stage", stage: "guard", cursor: 3 });
  assert.equal(state.selectedStage, "guard");
  state = reduceReplay(state, { type: "restart" });
  assert.equal(state.cursor, -1);
});

test("ticks stop at the final recorded event", () => {
  let state = createReplayState({ length: 2, intervalMs: 100, reducedMotion: true });
  state = reduceReplay(state, { type: "play" });
  state = reduceReplay(state, { type: "tick" });
  state = reduceReplay(state, { type: "tick" });

  assert.deepEqual(state, {
    length: 2,
    intervalMs: 100,
    reducedMotion: true,
    cursor: 1,
    playing: false,
    selectedStage: "plan",
  });
});

test("an empty replay cannot enter the playing state", () => {
  const state = reduceReplay(createReplayState({ length: 0 }), { type: "play" });

  assert.equal(state.playing, false);
  assert.equal(state.cursor, -1);
});

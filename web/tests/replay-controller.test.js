import assert from "node:assert/strict";
import test from "node:test";

import {
  createReplayController,
  createReplayState,
  reduceReplay,
} from "../replay-controller.js";

function fakeTimers() {
  const scheduled = [];
  const cleared = [];
  return {
    scheduled,
    cleared,
    setIntervalImpl(callback, intervalMs) {
      const id = scheduled.length + 1;
      scheduled.push({ id, callback, intervalMs });
      return id;
    },
    clearIntervalImpl(id) {
      cleared.push(id);
    },
  };
}

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

test("play owns one intervalMs timer whose callbacks tick and render", () => {
  const timers = fakeTimers();
  const renders = [];
  const controller = createReplayController({
    initialState: createReplayState({ length: 3, intervalMs: 125 }),
    onChange: (state, action) => renders.push({ state, action }),
    setIntervalImpl: timers.setIntervalImpl,
    clearIntervalImpl: timers.clearIntervalImpl,
  });

  controller.dispatch({ type: "play" });
  controller.dispatch({ type: "play" });

  assert.equal(timers.scheduled.length, 1);
  assert.equal(timers.scheduled[0].intervalMs, 125);
  timers.scheduled[0].callback();
  assert.equal(controller.getState().cursor, 0);
  assert.equal(renders.at(-1).action.type, "tick");
  assert.equal(renders.at(-1).state.cursor, 0);
});

test("pause stage selection and replay end clear the owned timer", () => {
  const timers = fakeTimers();
  const controller = createReplayController({
    initialState: createReplayState({ length: 2 }),
    onChange() {},
    setIntervalImpl: timers.setIntervalImpl,
    clearIntervalImpl: timers.clearIntervalImpl,
  });

  controller.dispatch({ type: "play" });
  controller.dispatch({ type: "pause" });
  controller.dispatch({ type: "play" });
  controller.dispatch({ type: "select-stage", stage: "guard", cursor: 0 });
  controller.dispatch({ type: "play" });
  timers.scheduled.at(-1).callback();

  assert.deepEqual(timers.cleared, [1, 2, 3]);
  assert.equal(controller.getState().playing, false);
  assert.equal(controller.timerActive, false);
});

test("restart resets the cursor without starting another timer", () => {
  const timers = fakeTimers();
  const controller = createReplayController({
    initialState: { ...createReplayState({ length: 4 }), cursor: 2 },
    onChange() {},
    setIntervalImpl: timers.setIntervalImpl,
    clearIntervalImpl: timers.clearIntervalImpl,
  });

  controller.dispatch({ type: "restart" });

  assert.equal(controller.getState().cursor, -1);
  assert.equal(controller.getState().playing, false);
  assert.equal(timers.scheduled.length, 0);
});

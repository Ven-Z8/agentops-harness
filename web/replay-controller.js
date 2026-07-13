"use strict";

export function createReplayState({ length, intervalMs = 420, reducedMotion = false }) {
  return {
    length,
    intervalMs,
    reducedMotion,
    cursor: -1,
    playing: false,
    selectedStage: "plan",
  };
}

export function reduceReplay(state, action) {
  switch (action.type) {
    case "play":
      return { ...state, playing: state.length > 0 };
    case "pause":
      return { ...state, playing: false };
    case "restart":
      return { ...state, cursor: -1, playing: false, selectedStage: "plan" };
    case "tick": {
      if (!state.playing) return state;
      const cursor = Math.min(state.cursor + 1, state.length - 1);
      return { ...state, cursor, playing: cursor < state.length - 1 };
    }
    case "select-stage":
      return {
        ...state,
        selectedStage: action.stage,
        cursor: action.cursor,
        playing: false,
      };
    default:
      return state;
  }
}

export function createReplayController({
  initialState,
  onChange,
  setIntervalImpl = globalThis.setInterval,
  clearIntervalImpl = globalThis.clearInterval,
}) {
  let state = initialState;
  let timerId = null;

  const stopTimer = () => {
    if (timerId === null) return;
    clearIntervalImpl(timerId);
    timerId = null;
  };

  const ensureTimer = () => {
    if (timerId !== null || !state.playing) return;
    timerId = setIntervalImpl(() => dispatch({ type: "tick" }), state.intervalMs);
  };

  const dispatch = action => {
    state = reduceReplay(state, action);
    if (state.playing) ensureTimer();
    else stopTimer();
    onChange(state, action);
    return state;
  };

  return {
    dispatch,
    getState: () => state,
    stop: stopTimer,
    get timerActive() {
      return timerId !== null;
    },
  };
}

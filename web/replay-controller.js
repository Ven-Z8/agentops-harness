"use strict";

export function createReplayState({ length, intervalMs = 420, reducedMotion = false }) {
  return {
    length,
    intervalMs,
    reducedMotion,
    cursor: -1,
    playing: false,
    selectedStage: "plan",
    selectedEventId: null,
  };
}

export function reduceReplay(state, action) {
  switch (action.type) {
    case "play":
      return { ...state, playing: state.length > 0 };
    case "pause":
      return { ...state, playing: false };
    case "disconnect":
      return { ...state, playing: false };
    case "set-length":
      return { ...state, length: Math.max(0, action.length) };
    case "restart":
      return {
        ...state,
        cursor: -1,
        playing: false,
        selectedStage: "plan",
        selectedEventId: null,
      };
    case "tick": {
      if (!state.playing) return state;
      const cursor = Math.min(state.cursor + 1, state.length - 1);
      return {
        ...state,
        cursor,
        playing: cursor < state.length - 1,
        selectedStage: action.stage || state.selectedStage,
        selectedEventId: action.eventId ?? null,
      };
    }
    case "select-stage":
      return {
        ...state,
        selectedStage: action.stage,
        cursor: action.cursor,
        playing: false,
        selectedEventId: action.eventId ?? null,
      };
    default:
      return state;
  }
}

export function resolveReplayEvent(state, timeline = []) {
  if (state.selectedEventId != null) {
    const selected = timeline.find(event => event.id === state.selectedEventId);
    if (selected) return selected;
  }
  return state.cursor >= 0 ? timeline[state.cursor] ?? null : null;
}

export function createReplayController({
  initialState,
  onChange,
  setIntervalImpl = globalThis.setInterval,
  clearIntervalImpl = globalThis.clearInterval,
  stageAtCursor = () => null,
  eventAtCursor = cursor => ({ stage: stageAtCursor(cursor), id: null }),
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
    timerId = setIntervalImpl(() => {
      const cursor = Math.min(state.cursor + 1, state.length - 1);
      const event = eventAtCursor(cursor) || {};
      dispatch({
        type: "tick",
        stage: event.stage || stageAtCursor(cursor),
        eventId: event.id ?? null,
      });
    }, state.intervalMs);
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

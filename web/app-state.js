"use strict";

const TERMINAL_STATUSES = new Set(["completed", "blocked", "failed"]);

export function modeForDetail(detail) {
  const capture = detail?.capture || detail?.showcase || detail?.manifest ||
    detail?.record?.capture || detail?.record?.showcase;
  if (capture) return "recorded";
  return TERMINAL_STATUSES.has(detail?.summary?.status) ? "replay" : "live";
}

function eventKey(event) {
  if (event?.index != null) return `index:${event.index}`;
  return JSON.stringify(event);
}

export function mergeEvidenceEvents(fetched = [], streamed = []) {
  const merged = [...fetched];
  const seen = new Set(fetched.map(eventKey));
  for (const event of streamed) {
    const key = eventKey(event);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(event);
  }
  return merged;
}

export function updateChannelErrors(errors, channel, status) {
  const next = { ...errors };
  if (status === "error") {
    next[channel] = { message: `${channel} stream disconnected` };
  } else if (status === "open") {
    delete next[channel];
  }
  return next;
}

export function createLatestRequestGate() {
  let generation = 0;
  const begin = () => {
    generation += 1;
    return generation;
  };
  const isCurrent = candidate => candidate === generation;
  return {
    begin,
    isCurrent,
    async run({ request, isScopeCurrent = () => true, onSuccess, onError }) {
      const candidate = begin();
      let value;
      try {
        value = await request();
      } catch (error) {
        if (!isCurrent(candidate) || !isScopeCurrent()) return { status: "stale" };
        onError?.(error);
        return { status: "error", error };
      }
      if (!isCurrent(candidate) || !isScopeCurrent()) return { status: "stale" };
      onSuccess?.(value);
      return { status: "success" };
    },
  };
}

export const streamShouldClose = status => status === "done";

"use strict";

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
  return {
    begin() {
      generation += 1;
      return generation;
    },
    isCurrent(candidate) {
      return candidate === generation;
    },
  };
}

export const streamShouldClose = status => status === "done";

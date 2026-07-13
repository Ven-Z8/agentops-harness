"use strict";

const CAMERA_PRESETS = Object.freeze({
  plan: Object.freeze({ position: [-8, 6, 13], target: [-8, -0.5, 0] }),
  equip: Object.freeze({ position: [-4, 5.6, 12.5], target: [-4, -0.5, 0] }),
  work: Object.freeze({ position: [0, 5.3, 12], target: [0, -0.5, 0] }),
  guard: Object.freeze({ position: [4, 5.6, 12.5], target: [4, -0.5, 0] }),
  prove: Object.freeze({ position: [8, 6, 13], target: [8, -0.5, 0] }),
});

const STAGE_VISUALS = Object.freeze({
  pending: Object.freeze({
    color: 0x334155,
    emissive: 0x0f172a,
    opacity: 0.58,
    glyph: "·",
    label: "Pending",
  }),
  active: Object.freeze({
    color: 0x38bdf8,
    emissive: 0x0c4a6e,
    opacity: 0.92,
    glyph: "▶",
    label: "Active",
  }),
  pass: Object.freeze({
    color: 0x22c55e,
    emissive: 0x14532d,
    opacity: 0.84,
    glyph: "✓",
    label: "Pass",
  }),
  warn: Object.freeze({
    color: 0xf59e0b,
    emissive: 0x78350f,
    opacity: 0.86,
    glyph: "!",
    label: "Warning",
  }),
  blocked: Object.freeze({
    color: 0xef4444,
    emissive: 0x7f1d1d,
    opacity: 0.9,
    glyph: "⊘",
    label: "Blocked",
  }),
  unavailable: Object.freeze({
    color: 0x64748b,
    emissive: 0x0f172a,
    opacity: 0.42,
    glyph: "×",
    label: "Unavailable",
  }),
});

const copyCamera = camera => ({
  position: [...camera.position],
  target: [...camera.target],
});

export function cameraPreset(stageId) {
  const preset = CAMERA_PRESETS[stageId];
  if (!preset) throw new RangeError(`Unknown stage: ${stageId}`);
  return copyCamera(preset);
}

export function interpolateCamera(from, to, progress, reducedMotion = false) {
  if (reducedMotion) return copyCamera(to);
  const amount = Math.min(1, Math.max(0, progress));
  const interpolateValues = (start, end) => start.map(
    (value, index) => value + ((end[index] - value) * amount),
  );
  return {
    position: interpolateValues(from.position, to.position),
    target: interpolateValues(from.target, to.target),
  };
}

export function stageVisual(status) {
  const visual = STAGE_VISUALS[status];
  if (!visual) throw new RangeError(`Unknown stage status: ${status}`);
  return { ...visual };
}

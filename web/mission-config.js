export const MISSIONS = Object.freeze({
  "governed-migration": Object.freeze({
    id: "governed-migration",
    title: "Governed Migration",
    summary: "Migrate a multi-file Pydantic v1 service to v2 under an equipped, governed worker.",
    recordedRunId: "showcase-governed-migration",
    initialStage: "plan",
  }),
});

export function missionFromLocation(search = window.location.search) {
  const id = new URLSearchParams(search).get("mission");
  return MISSIONS[id] ?? null;
}

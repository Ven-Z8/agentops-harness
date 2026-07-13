export const reconnectDelays = Object.freeze([1000, 2000, 4000]);

export function streamState({ attempt }) {
  return attempt >= reconnectDelays.length
    ? { status: "disconnected", retryable: true }
    : { status: "reconnecting", retryable: false };
}

export class CockpitDataClient {
  constructor({ fetchImpl = fetch, EventSourceImpl = EventSource } = {}) {
    this.fetchImpl = fetchImpl;
    this.EventSourceImpl = EventSourceImpl;
    this.sources = new Set();
  }

  async json(path) {
    const response = await this.fetchImpl(path);
    if (!response.ok) throw new Error(`${response.status} ${path}`);
    return response.json();
  }

  async text(path) {
    const response = await this.fetchImpl(path);
    if (!response.ok) throw new Error(`${response.status} ${path}`);
    return response.text();
  }

  listRuns(limit = 50) {
    return this.json(`/cockpit/api/runs?limit=${limit}`);
  }

  runDetail(runId) {
    return this.json(`/cockpit/api/runs/${encodeURIComponent(runId)}`);
  }

  openStream(path, handlers) {
    const source = new this.EventSourceImpl(path);
    this.sources.add(source);
    source.addEventListener("open", handlers.open);
    source.addEventListener("event", handlers.event);
    source.addEventListener("done", handlers.done);
    source.addEventListener("error", handlers.error);
    return source;
  }

  closeStream(source) {
    if (!this.sources.delete(source)) return;
    source.close();
  }

  closeStreams() {
    for (const source of this.sources) source.close();
    this.sources.clear();
  }
}

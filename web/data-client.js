export const reconnectDelays = Object.freeze([1000, 2000, 4000]);

export function streamState({ attempt }) {
  return attempt >= reconnectDelays.length
    ? { status: "disconnected", retryable: true }
    : { status: "reconnecting", retryable: false };
}

export class CockpitDataClient {
  constructor({
    fetchImpl = fetch,
    EventSourceImpl = EventSource,
    setTimeoutImpl = globalThis.setTimeout,
    clearTimeoutImpl = globalThis.clearTimeout,
  } = {}) {
    this.fetchImpl = fetchImpl;
    this.EventSourceImpl = EventSourceImpl;
    this.setTimeoutImpl = setTimeoutImpl;
    this.clearTimeoutImpl = clearTimeoutImpl;
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
    for (const name of ["open", "event", "done", "error"]) {
      if (typeof handlers[name] === "function") {
        source.addEventListener(name, handlers[name]);
      }
    }
    return source;
  }

  openResilientStream(path, handlers = {}) {
    let attempt = 0;
    let timer = null;
    let activeSource = null;
    let closed = false;

    const stopActiveSource = () => {
      if (!activeSource) return;
      activeSource.close();
      this.sources.delete(activeSource);
      activeSource = null;
    };

    const connect = () => {
      if (closed) return;
      timer = null;
      const source = this.openStream(path, {
        ...handlers,
        open: event => {
          if (closed || source !== activeSource) return;
          attempt = 0;
          handlers.open?.(event);
        },
        error: event => {
          if (closed || source !== activeSource) return;
          stopActiveSource();
          const connection = streamState({ attempt });
          handlers.error?.(event, connection);
          if (attempt < reconnectDelays.length) {
            timer = this.setTimeoutImpl(connect, reconnectDelays[attempt]);
            attempt += 1;
          }
        },
      });
      activeSource = source;
    };

    const handle = {
      close: () => {
        if (closed) return;
        closed = true;
        if (timer !== null) {
          this.clearTimeoutImpl(timer);
          timer = null;
        }
        stopActiveSource();
        this.sources.delete(handle);
      },
      retry: () => {
        if (closed || activeSource || timer !== null) return;
        attempt = 0;
        connect();
      },
    };
    this.sources.add(handle);
    connect();
    return handle;
  }

  closeStream(source) {
    if (!this.sources.delete(source)) return;
    source.close();
  }

  closeStreams() {
    for (const source of [...this.sources]) source.close();
    this.sources.clear();
  }
}

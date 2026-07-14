import assert from "node:assert/strict";
import test from "node:test";
import {
  CockpitDataClient,
  reconnectDelays,
  streamState,
} from "../data-client.js";

test("reconnect policy is bounded at one, two, and four seconds", () => {
  assert.deepEqual(reconnectDelays, [1000, 2000, 4000]);
  assert.deepEqual(streamState({ attempt: 3 }), {
    status: "disconnected",
    retryable: true,
  });
});

test("run methods use the existing Cockpit API paths", async () => {
  const paths = [];
  const client = new CockpitDataClient({
    fetchImpl: async path => {
      paths.push(path);
      return { ok: true, json: async () => ({ path }) };
    },
    EventSourceImpl: class {},
  });

  assert.deepEqual(await client.listRuns(), {
    path: "/cockpit/api/runs?limit=50",
  });
  assert.deepEqual(await client.listRuns(10), {
    path: "/cockpit/api/runs?limit=10",
  });
  assert.deepEqual(await client.runDetail("run/with spaces"), {
    path: "/cockpit/api/runs/run%2Fwith%20spaces",
  });
  assert.deepEqual(paths, [
    "/cockpit/api/runs?limit=50",
    "/cockpit/api/runs?limit=10",
    "/cockpit/api/runs/run%2Fwith%20spaces",
  ]);
});

test("default browser fetch is called with globalThis as its receiver", async t => {
  const originalFetch = globalThis.fetch;
  let receiver = null;
  globalThis.fetch = async function (path) {
    receiver = this;
    return { ok: true, json: async () => ({ path }) };
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  const client = new CockpitDataClient({ EventSourceImpl: class {} });

  assert.deepEqual(await client.json("/receiver-check"), {
    path: "/receiver-check",
  });
  assert.equal(receiver, globalThis);
});

test("json and text surface HTTP failures with the requested path", async () => {
  const client = new CockpitDataClient({
    fetchImpl: async path => ({
      ok: path === "/ok",
      status: 404,
      json: async () => ({ ok: true }),
      text: async () => "artifact",
    }),
    EventSourceImpl: class {},
  });

  assert.deepEqual(await client.json("/ok"), { ok: true });
  assert.equal(await client.text("/ok"), "artifact");
  await assert.rejects(client.json("/missing.json"), {
    message: "404 /missing.json",
  });
  await assert.rejects(client.text("/missing.txt"), {
    message: "404 /missing.txt",
  });
});

test("openStream registers handlers and closeStreams closes every source", () => {
  const instances = [];
  class FakeEventSource {
    constructor(path) {
      this.path = path;
      this.listeners = new Map();
      this.closed = false;
      instances.push(this);
    }

    addEventListener(name, handler) {
      this.listeners.set(name, handler);
    }

    close() {
      this.closed = true;
    }
  }
  const client = new CockpitDataClient({
    fetchImpl: async () => ({ ok: true }),
    EventSourceImpl: FakeEventSource,
  });
  const handlers = {
    open() {},
    event() {},
    done() {},
    error() {},
  };

  const first = client.openStream("/first", handlers);
  const second = client.openStream("/second", handlers);

  assert.equal(first.path, "/first");
  assert.equal(second.path, "/second");
  for (const source of instances) {
    assert.deepEqual([...source.listeners], Object.entries(handlers));
  }

  client.closeStreams();

  assert.equal(instances.every(source => source.closed), true);
  assert.equal(client.sources.size, 0);
});

test("closeStream closes only the selected source", () => {
  class FakeEventSource {
    constructor() {
      this.closed = false;
    }

    addEventListener() {}

    close() {
      this.closed = true;
    }
  }
  const client = new CockpitDataClient({
    fetchImpl: async () => ({ ok: true }),
    EventSourceImpl: FakeEventSource,
  });
  const handlers = { open() {}, event() {}, done() {}, error() {} };
  const first = client.openStream("/first", handlers);
  const second = client.openStream("/second", handlers);

  client.closeStream(first);

  assert.equal(first.closed, true);
  assert.equal(second.closed, false);
  assert.deepEqual([...client.sources], [second]);
});

function fakeTimeouts() {
  const scheduled = [];
  const cleared = [];
  return {
    scheduled,
    cleared,
    setTimeoutImpl(callback, delay) {
      const timer = { id: scheduled.length + 1, callback, delay, cleared: false };
      scheduled.push(timer);
      return timer.id;
    },
    clearTimeoutImpl(id) {
      const timer = scheduled.find(candidate => candidate.id === id);
      if (timer) timer.cleared = true;
      cleared.push(id);
    },
    run(id) {
      const timer = scheduled.find(candidate => candidate.id === id);
      if (timer && !timer.cleared) timer.callback();
    },
  };
}

function fakeEventSources() {
  const instances = [];
  class FakeEventSource {
    constructor(path) {
      this.path = path;
      this.listeners = new Map();
      this.closed = false;
      instances.push(this);
    }

    addEventListener(name, handler) {
      this.listeners.set(name, handler);
    }

    emit(name, event = { type: name }) {
      this.listeners.get(name)?.(event);
    }

    close() {
      this.closed = true;
    }
  }
  return { FakeEventSource, instances };
}

test("resilient streams retry after one two and four seconds then require manual retry", () => {
  const timers = fakeTimeouts();
  const sources = fakeEventSources();
  const connectionStates = [];
  const client = new CockpitDataClient({
    fetchImpl: async () => ({ ok: true }),
    EventSourceImpl: sources.FakeEventSource,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
  });

  const handle = client.openResilientStream("/stream", {
    error: (_event, connection) => connectionStates.push(connection),
  });

  for (let attempt = 0; attempt < 4; attempt += 1) {
    sources.instances.at(-1).emit("error");
    const retry = timers.scheduled[attempt];
    if (retry) timers.run(retry.id);
  }

  assert.deepEqual(timers.scheduled.map(timer => timer.delay), [1000, 2000, 4000]);
  assert.equal(sources.instances.length, 4);
  assert.deepEqual(connectionStates, [
    { status: "reconnecting", retryable: false },
    { status: "reconnecting", retryable: false },
    { status: "reconnecting", retryable: false },
    { status: "disconnected", retryable: true },
  ]);

  handle.retry();
  assert.equal(sources.instances.length, 5);
});

test("closeStreams cancels a resilient stream pending retry", () => {
  const timers = fakeTimeouts();
  const sources = fakeEventSources();
  const client = new CockpitDataClient({
    fetchImpl: async () => ({ ok: true }),
    EventSourceImpl: sources.FakeEventSource,
    setTimeoutImpl: timers.setTimeoutImpl,
    clearTimeoutImpl: timers.clearTimeoutImpl,
  });

  client.openResilientStream("/stream", {});
  sources.instances[0].emit("error");
  client.closeStreams();
  timers.run(timers.scheduled[0].id);

  assert.deepEqual(timers.cleared, [timers.scheduled[0].id]);
  assert.equal(sources.instances.length, 1);
  assert.equal(client.sources.size, 0);
});

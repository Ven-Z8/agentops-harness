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

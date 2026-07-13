import assert from "node:assert/strict";
import test from "node:test";

import * as THREE from "../vendor/three.module.min.js";

test("the local Three.js r185 module graph imports without a network dependency", () => {
  assert.equal(THREE.REVISION, "185");
});

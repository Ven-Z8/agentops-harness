import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("portfolio shell keeps semantic rails canvas fallback and deep-dive host", async () => {
  const html = await readFile(new URL("index.html", root), "utf8");

  assert.match(html, /id="modeBadge"/);
  assert.match(html, /id="replayBtn"[^>]*aria-pressed=/);
  assert.match(html, /class="mission-rail"/);
  assert.match(html, /id="cockpit3d"[^>]*aria-hidden="true"/);
  assert.match(html, /id="stageRibbon"/);
  assert.match(html, /id="show3dBtn"[^>]*>Show 3D architecture/);
  assert.match(html, /id="proofRail"/);
  assert.match(html, /id="inspector"/);
});

test("mobile and reduced-motion CSS default to semantic controls without pulses", async () => {
  const css = await readFile(new URL("styles.css", root), "utf8");

  assert.match(css, /@media \(max-width:820px\)[\s\S]*\.cockpit3d/);
  assert.match(css, /@media \(prefers-reduced-motion:reduce\)[\s\S]*\.pulse/);
});

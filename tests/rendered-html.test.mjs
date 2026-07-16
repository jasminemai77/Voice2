import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("ships the Voice2 control surface instead of the starter skeleton", async () => {
  const [page, layout, css, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(page, /本地运行时/);
  assert.match(page, /\/api\/v1\/speech/);
  assert.match(page, /consent_confirmed/);
  assert.match(page, /重新运行短基准/);
  assert.doesNotMatch(page, /SkeletonPreview|react-loading-skeleton/);
  assert.match(layout, /Voice2 · 本地语音运行时/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(packageJson, /"desktop:build"/);
});

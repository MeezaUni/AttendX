import { test } from "node:test";
import assert from "node:assert/strict";
import { startCamera } from "../src/lib/camera.ts";

function environment(getUserMedia) {
  globalThis.window = { isSecureContext: true };
  Object.defineProperty(globalThis, "navigator", {
    value: { mediaDevices: { getUserMedia } },
    configurable: true,
  });
}
test("stops the acquired camera if video playback fails", async () => {
  let stops = 0;
  const stream = { getTracks: () => [{ stop: () => stops++ }] };
  environment(async () => stream);
  await assert.rejects(
    startCamera({
      play: async () => {
        throw new Error("playback refused");
      },
    }),
  );
  assert.equal(stops, 1);
});
test("stops a pending camera acquisition when the component cancels", async () => {
  let release;
  let stops = 0;
  const stream = { getTracks: () => [{ stop: () => stops++ }] };
  environment(
    () =>
      new Promise((r) => {
        release = r;
      }),
  );
  const cancellation = new AbortController();
  const pending = startCamera(
    { play: async () => {}, videoWidth: 640 },
    cancellation.signal,
  );
  cancellation.abort();
  release(stream);
  await assert.rejects(pending);
  assert.equal(stops, 1);
});

test("QR scan can request the rear camera without changing the front-camera default", async () => {
  const requests = [];
  const stream = { getTracks: () => [] };
  environment(async (constraints) => {
    requests.push(constraints);
    return stream;
  });
  const video = { play: async () => {}, videoWidth: 640 };
  await startCamera(video, undefined, {
    facingMode: { ideal: "environment" },
    width: { ideal: 1920 },
  });
  assert.deepEqual(requests[0].video.facingMode, { ideal: "environment" });
  await startCamera(video);
  assert.equal(requests[1].video.facingMode, "user");
});

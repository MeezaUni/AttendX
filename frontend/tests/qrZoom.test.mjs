import { test } from "node:test";
import assert from "node:assert/strict";
import { drawQrFrame, qrScanRegion } from "../src/lib/qrZoom.ts";

test("QR zoom crops the same centered portrait region shown by the preview", () => {
  assert.deepEqual(qrScanRegion(1920, 1080, 1), {
    x: 555,
    y: 0,
    width: 810,
    height: 1080,
  });
  assert.deepEqual(qrScanRegion(1920, 1080, 2), {
    x: 757.5,
    y: 270,
    width: 405,
    height: 540,
  });
  assert.deepEqual(qrScanRegion(640, 480, 2), {
    x: 230,
    y: 120,
    width: 180,
    height: 240,
  });
  assert.deepEqual(qrScanRegion(640, 480, 99), {
    x: 275,
    y: 180,
    width: 90,
    height: 120,
  });
  assert.throws(() => qrScanRegion(0, 480, 1));
});

test("zoom changes decoder pixels rather than only enlarging CSS", () => {
  const video = { videoWidth: 1920, videoHeight: 1080 };
  const calls = [];
  const canvas = {
    getContext: () => ({ drawImage: (...args) => calls.push(args) }),
  };
  drawQrFrame(video, canvas, 2);
  assert.deepEqual(calls[0], [video, 757.5, 270, 405, 540, 0, 0, 480, 640]);
  assert.equal(canvas.width, 480);
  assert.equal(canvas.height, 640);
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transformWithOxc } from "vite";

const moduleUrl = (code) => `data:text/javascript,${encodeURIComponent(code)}`;
const source = await readFile(new URL("../src/pages/Classroom.tsx", import.meta.url), "utf8");
const compiled = (await transformWithOxc(source, "Classroom.tsx", { jsx: { runtime: "automatic" } })).code;
let sequence = 0;
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const flush = () => new Promise((resolve) => setImmediate(resolve));
async function until(condition) {
  for (let i = 0; i < 100 && !condition(); i++) await flush();
  assert.ok(condition(), "asynchronous operation did not reach the expected boundary");
}

// Execute the actual component and camera helper. The tiny renderer supplies only hooks,
// refs and JSX; browser devices, QR decoding and HTTP are controlled at their boundaries.
async function mount({ camera, response, readerReady = Promise.resolve(), phase = "entry", hash = "" } = {}) {
  const key = `__attendxClassroomTest${++sequence}`;
  const cells = [];
  let cursor = 0;
  let cleanup;
  let mounted = false;
  let requests = 0;
  let acquisitions = 0;
  const video = { videoWidth: 640, videoHeight: 480, play: async () => {}, srcObject: null };
  const state = {
    useState(initial) {
      const i = cursor++;
      if (!(i in cells)) cells[i] = i === 0 ? phase : initial;
      return [cells[i], (value) => { cells[i] = typeof value === "function" ? value(cells[i]) : value; }];
    },
    useRef(initial) {
      const i = cursor++;
      if (!(i in cells)) cells[i] = { current: initial };
      return cells[i];
    },
    useEffect(effect) { cursor++; if (!mounted) cleanup = effect; },
    jsx: (type, props) => ({ type, props }),
    readerReady,
    BrowserQRCodeReader: class {
      decodeFromCanvas() { return { getText: () => "https://classroom.test/classroom#session.1.signature" }; }
    },
  };
  globalThis[key] = state;
  const bridges = {
    react: `export const {useState,useRef,useEffect}=globalThis.${key};`,
    "react/jsx-runtime": `export const {jsx}=globalThis.${key}; export const jsxs=jsx; export const Fragment="fragment";`,
    "../components/ui": 'export const Alert="alert", Button="button", Field="field", Input="input";',
    "../components/Layouts": 'export const Logo="logo";',
    "../components/CameraGuidance": 'export const CameraGuidance="guidance";',
    "../lib/api": 'export const errorText=(error)=>error.message;',
    "@zxing/browser": `await globalThis.${key}.readerReady; export const {BrowserQRCodeReader}=globalThis.${key};`,
  };
  let code = compiled;
  for (const [specifier, bridge] of Object.entries(bridges)) {
    code = code.replaceAll(JSON.stringify(specifier), JSON.stringify(moduleUrl(bridge)));
  }
  for (const helper of ["camera", "qrZoom"]) {
    code = code.replaceAll(`"../lib/${helper}"`, JSON.stringify(new URL(`../src/lib/${helper}.ts`, import.meta.url).href));
  }
  globalThis.window = { isSecureContext: true, location: { hash }, history: { replaceState() {} } };
  globalThis.location = { origin: "https://classroom.test" };
  globalThis.document = { createElement: () => ({ getContext: () => ({ drawImage() {} }) }) };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia() { return (Array.isArray(camera) ? camera[acquisitions++] : (acquisitions++, camera)).promise; } } },
  });
  globalThis.fetch = async () => (Array.isArray(response) ? response[requests++] : (requests++, response)).promise;
  const Classroom = (await import(moduleUrl(code))).default;
  function render() {
    cursor = 0;
    const tree = Classroom();
    function attach(node) {
      if (!node || typeof node !== "object") return;
      if (node.type === "video") node.props.ref.current = video;
      for (const child of [node.props?.children].flat(Infinity)) attach(child);
    }
    attach(tree);
    return tree;
  }
  render();
  const effect = cleanup;
  cleanup = effect();
  mounted = true;
  return {
    video,
    get requests() { return requests; },
    get acquisitions() { return acquisitions; },
    text() {
      function text(node) {
        if (typeof node === "string") return node;
        if (!node || typeof node !== "object") return "";
        return [node.props?.children].flat(Infinity).map(text).join(" ");
      }
      return text(render());
    },
    button(label) {
      function find(node) {
        if (!node || typeof node !== "object") return;
        if (node.type === "button" && node.props.children === label) return node;
        for (const child of [node.props?.children].flat(Infinity)) { const match = find(child); if (match) return match; }
      }
      return find(render());
    },
    unmount() { cleanup(); delete globalThis[key]; },
  };
}

function cameraStream() {
  let stops = 0;
  return { getTracks: () => [{ stop: () => stops++ }], get stops() { return stops; } };
}

test("cancel before QR reader loads does not acquire a camera later", async (t) => {
  const reader = deferred();
  const h = await mount({ readerReady: reader.promise, camera: deferred(), response: deferred() });
  t.after(() => h.unmount());
  h.button("Scan attendance QR").props.onClick();
  h.button("Cancel scanning").props.onClick();
  reader.resolve();
  await flush();
  await flush();
  assert.equal(h.acquisitions, 0);
  assert.ok(h.button("Scan attendance QR"));
});

test("cancel during camera permission stops a late stream and leaves entry available", async (t) => {
  const camera = deferred();
  const h = await mount({ camera, response: deferred() });
  t.after(() => h.unmount());
  h.button("Scan attendance QR").props.onClick();
  await until(() => h.acquisitions === 1);
  h.button("Cancel scanning").props.onClick();
  const stream = cameraStream();
  camera.resolve(stream);
  await flush();
  await flush();
  assert.ok(stream.stops > 0, "cancelled acquisition must release its camera tracks");
  assert.equal(h.requests, 0);
  assert.ok(h.button("Scan attendance QR"));
});

for (const outcome of ["success", "failure"]) {
  test(`cancel ignores a late entry request ${outcome}`, async (t) => {
    const camera = deferred();
    const response = deferred();
    const h = await mount({ camera, response });
    t.after(() => h.unmount());
    h.button("Scan attendance QR").props.onClick();
    camera.resolve(cameraStream());
    await until(() => h.requests === 1);
    h.button("Cancel scanning").props.onClick();
    if (outcome === "success") response.resolve({ ok: true, json: async () => ({ attempt_token: "late-attempt" }) });
    else response.reject(new Error("late network failure"));
    await flush();
    await flush();
    assert.ok(h.button("Scan attendance QR"), "late response must not replace the cancelled entry screen");
    assert.equal(h.button("Open camera and begin"), undefined);
    assert.ok(!h.text().includes("late network failure"), "a cancelled scan must not display a late error");
  });
}

test("an old response cannot replace a new scan or clear ownership of its camera", async (t) => {
  const cameras = [deferred(), deferred()];
  const responses = [deferred(), deferred()];
  const streams = [cameraStream(), cameraStream()];
  const h = await mount({ camera: cameras, response: responses });
  t.after(() => h.unmount());
  h.button("Scan attendance QR").props.onClick();
  cameras[0].resolve(streams[0]);
  await until(() => h.requests === 1);
  h.button("Cancel scanning").props.onClick();
  h.button("Scan attendance QR").props.onClick();
  cameras[1].resolve(streams[1]);
  await until(() => h.requests === 2);
  responses[0].resolve({ ok: true, json: async () => ({ attempt_token: "old-attempt" }) });
  await flush();
  assert.ok(h.button("Cancel scanning"), "the replacement scan must remain visible");
  assert.equal(streams[1].stops, 0);
  h.button("Cancel scanning").props.onClick();
  assert.ok(streams[1].stops > 0, "replacement camera ownership must survive an old response");
});

test("unmount during camera permission stops the stream when acquisition finishes", async () => {
  const camera = deferred();
  const h = await mount({ camera, response: deferred() });
  h.button("Scan attendance QR").props.onClick();
  await until(() => h.acquisitions === 1);
  h.unmount();
  const stream = cameraStream();
  camera.resolve(stream);
  await flush();
  assert.ok(stream.stops > 0);
  assert.equal(h.requests, 0);
});

test("an uncancelled scan still reaches the roll-number form and stops its camera", async (t) => {
  const camera = deferred();
  const response = deferred();
  const stream = cameraStream();
  const h = await mount({ camera, response });
  t.after(() => h.unmount());
  h.button("Scan attendance QR").props.onClick();
  camera.resolve(stream);
  await until(() => h.requests === 1);
  response.resolve({ ok: true, json: async () => ({ attempt_token: "current-attempt" }) });
  await until(() => h.button("Open camera and begin"));
  assert.ok(stream.stops > 0);
});

test("Cancel cannot discard a delayed final submission that the server has accepted", async (t) => {
  const camera = deferred();
  const response = deferred();
  const stream = cameraStream();
  const h = await mount({ camera, response, phase: "match" });
  t.after(() => h.unmount());
  h.button("Scan fresh QR to submit").props.onClick();
  camera.resolve(stream);
  await until(() => h.requests === 1);
  const cancel = h.button("Cancel scanning");
  assert.equal(cancel.props.disabled, true, "final submission cannot be cancelled after sending it");
  // Exercise the guard too: an already queued click can predate the disabled render.
  cancel.props.onClick();
  response.resolve({ ok: true, json: async () => ({ message: "Submitted successfully. Awaiting faculty confirmation." }) });
  await until(() => h.text().includes("Submitted successfully."));
  assert.equal(h.button("Scan fresh QR to submit"), undefined);
  assert.ok(stream.stops > 0);
});

test("an expired final QR resumes cancellable scanning without discarding the MATCH", async (t) => {
  const camera = deferred();
  const response = deferred();
  const h = await mount({ camera, response, phase: "match" });
  t.after(() => h.unmount());
  h.button("Scan fresh QR to submit").props.onClick();
  camera.resolve(cameraStream());
  await until(() => h.requests === 1);
  assert.equal(h.button("Cancel scanning").props.disabled, true);
  response.resolve({ ok: false, json: async () => ({ detail: "QR expired or invalid; scan the current classroom QR" }) });
  await until(() => h.button("Cancel scanning")?.props.disabled === false);
  h.button("Cancel scanning").props.onClick();
  assert.ok(h.button("Scan fresh QR to submit"));
});

for (const outcome of ["success", "failure"]) {
  test(`a late URL entry ${outcome} cannot replace a manual scan`, async (t) => {
    const camera = deferred();
    const responses = [deferred(), deferred()];
    const stream = cameraStream();
    const h = await mount({ camera, response: responses, hash: "#initial-session.1.signature" });
    t.after(() => h.unmount());
    assert.equal(h.requests, 1);
    h.button("Scan attendance QR").props.onClick();
    camera.resolve(stream);
    await until(() => h.requests === 2);
    if (outcome === "success") responses[0].resolve({ ok: true, json: async () => ({ attempt_token: "superseded-url-attempt" }) });
    else responses[0].reject(new Error("late URL entry error"));
    await flush();
    assert.ok(h.button("Cancel scanning"), "the manual scan must retain the visible camera");
    assert.equal(h.button("Open camera and begin"), undefined);
    assert.ok(!h.text().includes("late URL entry error"));
    h.button("Cancel scanning").props.onClick();
    assert.ok(stream.stops > 0);
  });
}

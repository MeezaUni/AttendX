// Browser camera helpers. Frames are captured UNMIRRORED (exactly what the sensor sees); only the
// on-screen preview is mirrored with CSS so it feels like a mirror to the student.

export function cameraSupportProblem(): string | null {
  if (!window.isSecureContext) {
    return "The camera needs a secure (HTTPS) connection. Open AttendX through its https:// address.";
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return "This browser cannot access the camera. Use a recent Chrome, Safari or Edge.";
  }
  return null;
}

export function cameraErrorText(e: unknown): string {
  const name = (e as { name?: string })?.name;
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera permission was denied. Allow camera access for this site in your browser settings, then try again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No front camera was found on this device.";
    case "NotReadableError":
      return "The camera is being used by another app. Close it and try again.";
    default:
      return `Could not start the camera${e instanceof Error ? `: ${e.message}` : ""}.`;
  }
}

export async function startCamera(
  video: HTMLVideoElement,
  signal?: AbortSignal,
  constraints: MediaTrackConstraints = {
    facingMode: "user",
    width: { ideal: 640 },
    height: { ideal: 480 },
    frameRate: { ideal: 30 },
  },
): Promise<MediaStream> {
  const problem = cameraSupportProblem();
  if (problem) throw new Error(problem);
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: constraints,
  });
  try {
    signal?.throwIfAborted();
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    signal?.throwIfAborted();
    if (!video.videoWidth) {
      await new Promise<void>((resolve, reject) => {
        const cleanup = () => {
          video.removeEventListener("loadedmetadata", ready);
          signal?.removeEventListener("abort", abort);
        };
        const ready = () => {
          cleanup();
          resolve();
        };
        const abort = () => {
          cleanup();
          reject(new DOMException("Camera capture cancelled", "AbortError"));
        };
        video.addEventListener("loadedmetadata", ready, { once: true });
        signal?.addEventListener("abort", abort, { once: true });
        if (signal?.aborted) abort();
      });
    }
    signal?.throwIfAborted();
    return stream;
  } catch (error) {
    stopCamera(stream);
    if (video.srcObject === stream) video.srcObject = null;
    throw error;
  }
}

export function stopCamera(stream: MediaStream | null) {
  stream?.getTracks().forEach((t) => t.stop());
}

let canvas: HTMLCanvasElement | null = null;

/** Grab the current video frame as JPEG (unmirrored), scaled to ``maxWidth``. */
export function captureFrame(
  video: HTMLVideoElement,
  maxWidth = 448,
  quality = 0.72,
): Promise<Blob> {
  canvas ??= document.createElement("canvas");
  const scale = Math.min(1, maxWidth / video.videoWidth);
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const ctx = canvas.getContext("2d", { willReadFrequently: false })!;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas!.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("frame capture failed"))),
      "image/jpeg",
      quality,
    ),
  );
}

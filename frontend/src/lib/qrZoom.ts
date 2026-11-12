/** Center-crop the actual barcode decoder input, matching a portrait object-cover preview. */
export function qrScanRegion(width: number, height: number, zoom: number) {
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0
  )
    throw new Error("Camera frame is not ready");
  const factor = Math.min(4, Math.max(1, Number.isFinite(zoom) ? zoom : 1));
  const cropWidth = Math.min(width, height * 0.75) / factor;
  const cropHeight = Math.min(height, width / 0.75) / factor;
  return {
    x: (width - cropWidth) / 2,
    y: (height - cropHeight) / 2,
    width: cropWidth,
    height: cropHeight,
  };
}

export function drawQrFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  zoom: number,
) {
  const source = qrScanRegion(video.videoWidth, video.videoHeight, zoom);
  canvas.width = 480;
  canvas.height = 640;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("This browser cannot scan camera frames");
  context.imageSmoothingEnabled = false;
  context.drawImage(
    video,
    source.x,
    source.y,
    source.width,
    source.height,
    0,
    0,
    480,
    640,
  );
  return canvas;
}

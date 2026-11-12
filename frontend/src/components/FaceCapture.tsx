import { useEffect, useRef, useState } from "react";
import { cameraErrorText, captureFrame, startCamera, stopCamera } from "../lib/camera";
import { Alert, Button } from "./ui";

const PROMPTS = ["Look straight at the camera", "Tilt your head slightly left", "Tilt your head slightly right", "Look straight again", "Hold still"];

/** Live enrollment capture: five frames over ~3 seconds with gentle pose variation. */
export function FaceCapture({ onCaptured, busy }: { onCaptured: (frames: Blob[]) => void; busy?: boolean }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [state, setState] = useState<"idle" | "starting" | "ready" | "capturing">("idle");
  const [prompt, setPrompt] = useState(PROMPTS[0]);
  const [count, setCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => stopCamera(stream.current), []);

  const start = async () => {
    setError(null);
    setState("starting");
    try {
      stream.current = await startCamera(video.current!);
      setState("ready");
    } catch (e) {
      setError(cameraErrorText(e));
      setState("idle");
    }
  };

  const capture = async () => {
    setState("capturing");
    const frames: Blob[] = [];
    for (let i = 0; i < PROMPTS.length; i++) {
      setPrompt(PROMPTS[i]);
      await new Promise((r) => setTimeout(r, i === 0 ? 700 : 650));
      frames.push(await captureFrame(video.current!, 720, 0.9));
      setCount(i + 1);
    }
    stopCamera(stream.current);
    stream.current = null;
    setState("idle");
    setCount(0);
    onCaptured(frames);
  };

  return (
    <div className="space-y-3">
      {error && <Alert>{error}</Alert>}
      <div className="relative mx-auto aspect-[3/4] w-full max-w-xs overflow-hidden rounded-2xl bg-slate-900 sm:aspect-[4/3] sm:max-w-md">
        <video ref={video} className="h-full w-full -scale-x-100 object-cover" playsInline muted />
        {state === "idle" && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-300">Camera is off</div>
        )}
        {(state === "ready" || state === "capturing") && (
          <>
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="h-[62%] w-[52%] rounded-[50%] border-2 border-white/70" />
            </div>
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-3 text-center text-sm font-medium text-white">
              {state === "capturing" ? `${prompt} (${count}/${PROMPTS.length})` : "Centre your face in the oval, in good light"}
            </div>
          </>
        )}
      </div>
      <div className="flex justify-center gap-2">
        {state === "idle" && (
          <Button onClick={start} busy={busy}>
            Start camera
          </Button>
        )}
        {state === "starting" && <Button busy>Starting camera</Button>}
        {state === "ready" && <Button onClick={capture}>Capture 5 photos</Button>}
        {state === "capturing" && <Button busy>Capturing…</Button>}
      </div>
    </div>
  );
}

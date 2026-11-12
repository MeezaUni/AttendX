import { useEffect, useRef, useState } from "react";
import { Alert, Button } from "./ui";
import {
  cameraErrorText,
  captureFrame,
  startCamera,
  stopCamera,
} from "../lib/camera";

export function GuidedEnrollment({
  onCaptured,
}: {
  onCaptured: (photos: Blob[]) => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const lifetime = useRef(new AbortController());
  const [photos, setPhotos] = useState<Blob[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    lifetime.current = new AbortController();
    return () => {
      lifetime.current.abort();
      stopCamera(stream.current);
    };
  }, []);
  const prompts = [
    "Face forward with a neutral expression in good light.",
    "Capture a second clear sample. Remove spectacles if you wear them.",
    "Wear your usual spectacles if applicable. Otherwise use a slight natural pose or lighting change.",
  ];
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">
        Sample {Math.min(photos.length + 1, 3)} of 3:{" "}
        {prompts[Math.min(photos.length, 2)]}
      </p>
      <video
        ref={video}
        playsInline
        muted
        className="mx-auto aspect-[4/3] w-full max-w-md -scale-x-100 rounded-xl bg-slate-900 object-cover"
      />
      {error && <Alert>{error}</Alert>}
      {!ready ? (
        <Button
          busy={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            const signal = lifetime.current.signal;
            try {
              const acquired = await startCamera(video.current!, signal);
              if (signal.aborted) {
                stopCamera(acquired);
                return;
              }
              stream.current = acquired;
              setPhotos([]);
              setReady(true);
              onCaptured([]);
            } catch (e) {
              if (!signal.aborted) setError(cameraErrorText(e));
            } finally {
              if (!signal.aborted) setBusy(false);
            }
          }}
        >
          {photos.length === 3 ? "Retake three samples" : "Open camera"}
        </Button>
      ) : (
        <Button
          busy={busy}
          onClick={async () => {
            setBusy(true);
            const signal = lifetime.current.signal;
            try {
              const captured = await captureFrame(video.current!, 720, 0.9);
              if (signal.aborted) return;
              const next = [...photos, captured];
              setPhotos(next);
              if (next.length === 3) {
                stopCamera(stream.current);
                stream.current = null;
                setReady(false);
                onCaptured(next);
              }
            } catch (e) {
              if (!signal.aborted) setError(cameraErrorText(e));
            } finally {
              if (!signal.aborted) setBusy(false);
            }
          }}
        >
          Capture sample {photos.length + 1}
        </Button>
      )}
      <p className="text-xs text-slate-500">
        The server checks each sample for one face, lighting, blur and identity
        consistency. Invalid samples require recapture. Declining biometrics
        does not remove you from the attendance roster.
      </p>
    </div>
  );
}

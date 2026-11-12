export function CameraGuidance({
  action,
  prompt,
  scanning = false,
}: {
  action: string;
  prompt: string;
  scanning?: boolean;
}) {
  const direction =
    action === "turn_left"
      ? "left"
      : action === "turn_right"
        ? "right"
        : action === "look_up"
          ? "up"
          : "center";
  return (
    <div className="camera-guidance" data-action={action}>
      <div className="camera-guidance-heading">
        {scanning ? "FINAL QR SCAN" : "LIVE FACE CHECK"}
      </div>
      {scanning ? (
        <div className="qr-target" aria-hidden="true" />
      ) : (
        <div className="face-target" aria-hidden="true" />
      )}
      {!scanning && action === "blink_twice" && (
        <svg className="blink-cue" viewBox="0 0 120 50" aria-hidden="true">
          <g className="blink-eyes">
            <ellipse cx="30" cy="25" rx="24" ry="17" fill="white" />
            <ellipse cx="90" cy="25" rx="24" ry="17" fill="white" />
            <circle cx="30" cy="25" r="10" fill="#111827" />
            <circle cx="90" cy="25" r="10" fill="#111827" />
          </g>
        </svg>
      )}
      {!scanning && direction !== "center" && (
        <svg
          className={`direction-cue direction-${direction}`}
          viewBox="0 0 48 48"
          aria-hidden="true"
        >
          <path
            d="M8 24h30M26 12l12 12-12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
      <p className="camera-guidance-prompt" aria-live="assertive">
        {prompt}
      </p>
    </div>
  );
}

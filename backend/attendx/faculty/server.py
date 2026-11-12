"""Classroom student listener: hotspot subnet only, no central auth or faculty controls."""

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from attendx.config import PROJECT_DIR
from attendx.security import RateLimiter


def create_student_app(runtime, hotspot_ip, subnet, origin, *, static_dir=None, models_dir=None, diagnostic_only=False):
    address = ipaddress.ip_address(hotspot_ip)
    network = ipaddress.ip_network(subnet, strict=True)
    parsed = urlparse(origin)
    if address.is_loopback or address not in network or str(address) != parsed.hostname or parsed.scheme != "https":
        raise ValueError("student listener requires an HTTPS origin on the configured hotspot address")
    app = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
    limiter = RateLimiter()
    static_dir = Path(static_dir or PROJECT_DIR / "frontend" / "dist")

    @app.middleware("http")
    async def hotspot_only(request: Request, call_next):
        try:
            peer = ipaddress.ip_address(request.client.host)
            allowed = peer in network and not peer.is_loopback and peer != address
        except (ValueError, AttributeError):
            allowed = False
        if (
            not allowed
            or request.headers.get("forwarded")
            or request.headers.get("x-forwarded-for")
            or request.headers.get("x-forwarded-host")
            or request.url.scheme != "https"
            or request.headers.get("host") != parsed.netloc
        ):
            return JSONResponse({"detail": "connect directly through the faculty classroom hotspot"}, status_code=403)
        if request.method not in ("GET", "HEAD") and request.url.path.startswith("/classroom/api/"):
            if request.headers.get("origin") != origin or request.headers.get("x-requested-with") != "attendx":
                return JSONResponse({"detail": "invalid classroom request origin"}, status_code=403)
        if not runtime.unlocked:
            return JSONResponse({"detail": "faculty classroom service is locked"}, status_code=423)
        if not limiter.hit(f"request:{peer}", 180):
            return JSONResponse({"detail": "too many requests; ask faculty for assistance"}, status_code=429)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; "
                "worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'",
            }
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/", response_class=HTMLResponse)
    def root():
        if diagnostic_only:
            return """<!doctype html><html lang="en">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AttendX HTTPS camera check</title>
<body style="font:18px system-ui;max-width:36rem;margin:2rem auto;padding:1rem">
<h1>AttendX HTTPS camera check</h1><p>Verify a trusted HTTPS connection without bypassing certificate warnings.
This diagnostic has no attendance endpoints. Camera video stays on your phone.</p>
<button id="start">Check camera permission</button> <button id="stop">Stop camera</button>
<p id="result" role="status">Install and explicitly trust the classroom CA before continuing.</p>
<video id="preview" playsinline muted style="width:100%;max-height:55vh"></video>
<script src="/camera-check.js" defer></script></body></html>"""
        return (
            '<html lang="en"><title>AttendX classroom</title><body><h1>AttendX classroom</h1>'
            "<p>Scan the rotating attendance QR displayed by your faculty.</p></body></html>"
        )

    if diagnostic_only:

        @app.get("/camera-check.js")
        def camera_check():
            return Response(
                """let stream=null,serial=0;
const video=document.getElementById('preview'),message=document.getElementById('result');
function stop(){serial++;if(stream)stream.getTracks().forEach(track=>track.stop());stream=null;video.srcObject=null;}
document.getElementById('stop').onclick=()=>{stop();message.textContent='Camera stopped.';};
document.getElementById('start').onclick=async()=>{stop();const generation=serial;try{
if(!isSecureContext||!navigator.mediaDevices)throw new Error('A trusted HTTPS connection is required.');
const acquired=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:'user'}});
if(generation!==serial||document.hidden){acquired.getTracks().forEach(track=>track.stop());return;}
stream=acquired;
video.srcObject=stream;await video.play();message.textContent='Live camera opened. No frames are uploaded.';
}catch(error){stop();message.textContent=error.message;}};
addEventListener('pagehide',stop);addEventListener('visibilitychange',()=>{if(document.hidden)stop();});""",
                media_type="text/javascript",
            )

        return app  # Diagnostic mode never registers attendance, auth or template endpoints.

    @app.get("/classroom")
    def classroom():
        path = static_dir / "index.html"
        if not path.is_file():
            raise HTTPException(503, "classroom website not built; faculty must run the frontend build")
        return FileResponse(path)

    for name in ("assets",):
        if (static_dir / name).is_dir():
            app.mount("/" + name, StaticFiles(directory=static_dir / name), name=name)

    class Entry(BaseModel):
        qr_token: str = Field(min_length=20, max_length=200)

    class Claim(BaseModel):
        roll_number: str = Field(min_length=1, max_length=32)

    def attempt(request):
        value = request.headers.get("x-attendx-attempt", "")
        if not 20 <= len(value) <= 100:
            raise HTTPException(401, "scan a classroom entry QR first")
        return value

    @app.post("/classroom/api/entry")
    def enter(body: Entry, request: Request):
        ip = request.client.host
        if not limiter.hit(f"entry:{ip}", 10):
            raise HTTPException(429, "too many entry attempts; wait a minute")
        return runtime.enter(body.qr_token, ip)

    @app.post("/classroom/api/roll")
    def claim(body: Claim, request: Request):
        if not limiter.hit(f"roll:{request.client.host}", 6):
            raise HTTPException(429, "too many roll-number attempts; wait a minute")
        return runtime.claim(attempt(request), body.roll_number, request.client.host)

    @app.post("/classroom/api/verify")
    def verify(request: Request, frames: list[UploadFile] = File(...), timestamps: str = Form(...)):
        if not 6 <= len(frames) <= 200:
            raise HTTPException(400, "invalid frame count")
        if not limiter.hit(f"inference:{request.client.host}", 5):
            raise HTTPException(429, "verification rate limit reached")
        raw = [f.file.read(250_001) for f in frames]
        if any(len(b) > 250_000 for b in raw):
            raise HTTPException(413, "camera frame too large")
        try:
            ts = [float(v) for v in json.loads(timestamps)]
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "invalid timestamps") from exc
        return runtime.verify(attempt(request), raw, ts, request.client.host)

    @app.post("/classroom/api/submit")
    def submit(body: Entry, request: Request):
        return runtime.submit(attempt(request), body.qr_token, request.client.host)

    return app

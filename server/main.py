"""FastAPI backend for the NexImage 10 web GUI.

Endpoints:
  GET  /                          → serve index.html
  GET  /stream.mjpeg              → MJPEG stream (multipart/x-mixed-replace)
  POST /api/stream/start          → start capture with given format
  POST /api/stream/stop           → stop capture
  GET  /api/controls              → list all V4L2 controls
  PUT  /api/controls/{name}       → set a control value
  POST /api/capture               → capture one frame
  POST /api/record/start          → start SER recording
  POST /api/record/stop           → stop SER recording
  GET  /api/files                 → list saved files
  GET  /files/{filename}          → download a saved file
"""

import asyncio
import datetime
import logging
import pathlib
import threading
import time
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Pydantic models ────────────────────────────────────────────────────────────

class StreamConfig(BaseModel):
    width:        int = 1920
    height:       int = 1080
    pixel_format: str = "GRBG"


class ControlValue(BaseModel):
    value: int


class RecordConfig(BaseModel):
    duration_seconds: float = 10.0


# ── Shared camera state ────────────────────────────────────────────────────────

class CameraState:
    """Thread-safe shared state between the capture thread and FastAPI handlers."""

    def __init__(self) -> None:
        self._lock         = threading.Lock()
        self._latest_jpeg  = b""
        self._frame_count  = 0
        self._streaming    = False
        self._recording    = False
        self._stop_event   = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._record_stop_event = threading.Event()

    # ── Frame access ───────────────────────────────────────────────────────────

    def push_jpeg(self, jpeg: bytes) -> None:
        with self._lock:
            self._latest_jpeg = jpeg
            self._frame_count += 1

    def get_jpeg(self) -> bytes:
        with self._lock:
            return self._latest_jpeg

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def is_recording(self) -> bool:
        return self._recording


_state = CameraState()


# ── Capture thread ─────────────────────────────────────────────────────────────

def _capture_loop(
    device_path: str,
    width: int,
    height: int,
    pixel_format: str,
    stop_event: threading.Event,
    state: CameraState,
    output_dir: pathlib.Path,
) -> None:
    """Background thread: captures frames and pushes JPEGs into shared state."""
    try:
        from turbojpeg import TurboJPEG
        turbo = TurboJPEG()
        def encode(frame: np.ndarray) -> bytes:
            return turbo.encode(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), quality=85)
    except Exception:
        logger.warning("PyTurboJPEG not available; falling back to OpenCV JPEG encoding")
        def encode(frame: np.ndarray) -> bytes:
            _, buf = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
                                  [cv2.IMWRITE_JPEG_QUALITY, 85])
            return buf.tobytes()

    from camera import Camera
    from camera.export import SERWriter

    ser_writer: Optional[SERWriter] = None
    record_path: Optional[pathlib.Path] = None

    def maybe_start_recording():
        nonlocal ser_writer, record_path
        if state._recording and ser_writer is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            record_path = output_dir / f"neximage_{ts}.ser"
            ser_writer = SERWriter(str(record_path), width, height,
                                   color=(pixel_format != "Y800"))
            ser_writer.open()
            logger.info("SER recording started: %s", record_path)

    def maybe_stop_recording():
        nonlocal ser_writer, record_path
        if ser_writer is not None:
            ser_writer.close()
            logger.info("SER recording stopped: %s", record_path)
            ser_writer = None
            record_path = None

    with Camera(device_path) as cam:
        cam.set_format(width, height, pixel_format)
        state._streaming = True
        try:
            for frame in cam.stream():
                if stop_event.is_set():
                    break

                jpeg = encode(frame)
                state.push_jpeg(jpeg)

                maybe_start_recording()
                if ser_writer is not None:
                    ser_writer.write_frame(frame)

                if state._record_stop_event.is_set():
                    maybe_stop_recording()
                    state._recording = False
                    state._record_stop_event.clear()

        finally:
            maybe_stop_recording()
            state._streaming = False
            logger.info("Capture thread exited")


# ── MJPEG generator ────────────────────────────────────────────────────────────

async def _mjpeg_generator(state: CameraState):
    """Async generator that yields MJPEG multipart frames."""
    boundary = b"--frame"
    while state.is_streaming:
        jpeg = state.get_jpeg()
        if jpeg:
            yield (
                boundary + b"\r\n"
                + b"Content-Type: image/jpeg\r\n\r\n"
                + jpeg + b"\r\n"
            )
        await asyncio.sleep(0.033)  # ~30 fps poll rate; actual rate set by camera


# ── App factory ────────────────────────────────────────────────────────────────

def create_app(
    device_path: str = "/dev/video0",
    output_dir: str = "captures",
) -> FastAPI:
    app = FastAPI(title="NexImage 10 Control Panel")
    out = pathlib.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    static_dir = pathlib.Path(__file__).parent / "static"

    # ── Static files & index ───────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html = (static_dir / "index.html").read_text()
        return HTMLResponse(content=html)

    # ── MJPEG stream ───────────────────────────────────────────────────────────

    @app.get("/stream.mjpeg")
    async def stream_mjpeg():
        if not _state.is_streaming:
            raise HTTPException(status_code=503, detail="Stream not active")
        return StreamingResponse(
            _mjpeg_generator(_state),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    # ── Stream control ─────────────────────────────────────────────────────────

    @app.post("/api/stream/start")
    async def stream_start(cfg: StreamConfig):
        if _state.is_streaming:
            return {"status": "already_streaming"}

        _state._stop_event.clear()
        t = threading.Thread(
            target=_capture_loop,
            args=(device_path, cfg.width, cfg.height, cfg.pixel_format,
                  _state._stop_event, _state, out),
            daemon=True,
            name="capture",
        )
        _state._capture_thread = t
        t.start()

        # Wait briefly for stream to start
        for _ in range(20):
            if _state.is_streaming:
                break
            await asyncio.sleep(0.1)

        return {"status": "started", "width": cfg.width, "height": cfg.height,
                "pixel_format": cfg.pixel_format}

    @app.post("/api/stream/stop")
    async def stream_stop():
        _state._stop_event.set()
        if _state._capture_thread:
            _state._capture_thread.join(timeout=3.0)
        return {"status": "stopped"}

    # ── Camera controls ────────────────────────────────────────────────────────

    @app.get("/api/controls")
    async def get_controls():
        from camera import CameraControls
        try:
            with CameraControls(device_path) as ctrl:
                controls = ctrl.list_controls()
            return {name: info.to_dict() for name, info in controls.items()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.put("/api/controls/{name}")
    async def set_control(name: str, body: ControlValue):
        from camera import CameraControls
        try:
            with CameraControls(device_path) as ctrl:
                if name in ("exposure", "exposure_absolute"):
                    ctrl.set_exposure(body.value)
                else:
                    ctrl.set_control(name, body.value)
            return {"name": name, "value": body.value}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Single-frame capture ───────────────────────────────────────────────────

    @app.post("/api/capture")
    async def capture_frame(format: str = "png"):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if _state.is_streaming:
            # Grab the latest MJPEG frame and re-encode as PNG/TIFF/FITS
            jpeg = _state.get_jpeg()
            if not jpeg:
                raise HTTPException(status_code=503, detail="No frame available yet")
            arr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            frame = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        else:
            from camera import Camera
            with Camera(device_path) as cam:
                frame = cam.get_frame()

        ext = format.lower()
        filename = f"neximage_{ts}.{ext}"
        filepath = out / filename

        from camera import save_png, save_tiff, save_fits
        if ext in ("tif", "tiff"):
            save_tiff(frame, filepath)
        elif ext in ("fit", "fits"):
            save_fits(frame, filepath)
        else:
            save_png(frame, filepath)

        return {"filename": filename, "path": str(filepath)}

    # ── SER recording ──────────────────────────────────────────────────────────

    @app.post("/api/record/start")
    async def record_start(cfg: RecordConfig):
        if not _state.is_streaming:
            raise HTTPException(status_code=400, detail="Start the stream first")
        if _state._recording:
            return {"status": "already_recording"}

        _state._record_stop_event.clear()
        _state._recording = True

        # Auto-stop after duration
        async def _auto_stop():
            await asyncio.sleep(cfg.duration_seconds)
            _state._record_stop_event.set()

        asyncio.create_task(_auto_stop())
        return {"status": "recording", "duration_seconds": cfg.duration_seconds}

    @app.post("/api/record/stop")
    async def record_stop():
        _state._record_stop_event.set()
        return {"status": "stopped"}

    # ── File browser ───────────────────────────────────────────────────────────

    @app.get("/api/files")
    async def list_files():
        files = sorted(
            p.name for p in out.iterdir()
            if p.is_file() and p.suffix.lower() in (".png", ".tif", ".tiff", ".fits", ".fit", ".ser")
        )
        return {"files": files}

    app.mount("/files", StaticFiles(directory=str(out)), name="files")

    return app


# ── Standalone entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)

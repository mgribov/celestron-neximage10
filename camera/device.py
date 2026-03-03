"""V4L2 camera capture abstraction for the Celestron NexImage 10.

The camera is a standard UVC 1.10 device (The Imaging Source, USB ID 199e:8619).
The uvcvideo kernel driver creates /dev/video0 automatically.

Supported pixel formats:
  GRBG  — 8-bit raw Bayer (best supported, demosaiced via OpenCV)
  Y800  — 8-bit monochrome
  BA81  — 16-bit Bayer (kernel may reject; fall back if needed)
  Y16   — 16-bit monochrome
"""

import logging
from typing import Generator, Optional

import cv2
import numpy as np
from linuxpy.video.device import Device, VideoCapture

logger = logging.getLogger(__name__)

# Maps fourcc string → (bytes-per-pixel-raw, is_bayer, opencv_demosaic_code_or_None)
_FORMAT_INFO: dict[str, tuple[int, bool, Optional[int]]] = {
    "GRBG": (1, True,  cv2.COLOR_BAYER_GRBG2RGB),
    "Y800": (1, False, None),
    "BA81": (2, True,  cv2.COLOR_BAYER_GRBG2RGB),  # 16-bit; kernel may reject
    "Y16 ": (2, False, None),
    "Y16":  (2, False, None),
}

# (width, height, max_fps) tuples documented in the NexImage 10 manual
SUPPORTED_RESOLUTIONS: list[tuple[int, int, int]] = [
    (640,  480,  90),
    (1280, 720,  60),
    (1920, 1080, 30),
    (2560, 1440, 15),
    (3072, 2048, 10),
    (3872, 2764, 6),
]


class Camera:
    """V4L2 interface for the NexImage 10.

    Usage::

        with Camera() as cam:
            cam.set_format(1920, 1080, "GRBG")
            frame = cam.get_frame()      # → np.ndarray (H, W, 3) uint8 RGB
            for frame in cam.stream():   # continuous
                ...
    """

    def __init__(self, device_path: str = "/dev/video0") -> None:
        self.device_path = device_path
        self._device: Optional[Device] = None
        self._capture: Optional[VideoCapture] = None
        self._width = 1920
        self._height = 1080
        self._pixel_format = "GRBG"

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def open(self) -> None:
        self._device = Device(self.device_path)
        self._device.open()
        logger.info("Opened %s", self.device_path)

    def close(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
            logger.info("Closed %s", self.device_path)

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── Format negotiation ─────────────────────────────────────────────────────

    def list_formats(self) -> list[dict]:
        """Return list of pixel formats supported by the device.

        Each entry: {"pixel_format": str, "description": str}
        """
        self._require_open()
        result = []
        for fmt in self._device.info.formats:
            result.append({
                "pixel_format": fmt.pixel_format.name,
                "description":  fmt.description,
            })
        return result

    def set_format(
        self,
        width: int = 1920,
        height: int = 1080,
        pixel_format: str = "GRBG",
    ) -> None:
        """Negotiate capture format with the driver.

        Args:
            width:        Frame width in pixels.
            height:       Frame height in pixels.
            pixel_format: FourCC string, e.g. "GRBG", "Y800".
        """
        self._require_open()
        self._capture = VideoCapture(self._device)
        self._capture.set_format(width, height, pixel_format)
        self._width = width
        self._height = height
        self._pixel_format = pixel_format
        logger.info("Format set: %dx%d %s", width, height, pixel_format)

    # ── Capture ────────────────────────────────────────────────────────────────

    def get_frame(self) -> np.ndarray:
        """Capture a single frame.

        Returns:
            RGB image as (H, W, 3) uint8 numpy array.
        """
        self._require_capture()
        with self._capture:
            for frame in self._capture:
                return self._decode(bytes(frame))
        raise RuntimeError("No frame received from device")

    def stream(self) -> Generator[np.ndarray, None, None]:
        """Yield decoded RGB frames indefinitely.

        The caller must break or close the camera to stop.

        Yields:
            RGB image as (H, W, 3) uint8 numpy array per frame.
        """
        self._require_capture()
        with self._capture:
            for frame in self._capture:
                yield self._decode(bytes(frame))

    # ── Internal ───────────────────────────────────────────────────────────────

    def _decode(self, raw: bytes) -> np.ndarray:
        """Decode raw V4L2 frame bytes to (H, W, 3) uint8 RGB array."""
        fmt = self._pixel_format.strip()
        info = _FORMAT_INFO.get(fmt)
        if info is None:
            raise ValueError(f"Unsupported pixel format: {self._pixel_format!r}")

        bpp, is_bayer, cv2_code = info

        if bpp == 1:
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(self._height, self._width)
        else:
            arr = np.frombuffer(raw, dtype=np.uint16).reshape(self._height, self._width)
            # Shift 16-bit to 8-bit for OpenCV demosaic/display
            arr = (arr >> 8).astype(np.uint8)

        if is_bayer:
            return cv2.cvtColor(arr, cv2_code)
        else:
            return cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)

    def _require_open(self) -> None:
        if self._device is None:
            raise RuntimeError("Camera is not open. Call open() or use as context manager.")

    def _require_capture(self) -> None:
        self._require_open()
        if self._capture is None:
            raise RuntimeError("Format not set. Call set_format() before capturing.")

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def pixel_format(self) -> str:
        return self._pixel_format

    @property
    def device(self) -> Optional[Device]:
        return self._device

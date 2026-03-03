"""Frame export utilities for the NexImage 10.

Supports PNG, TIFF, FITS (astropy), and SER video format.

SER format reference:
  http://www.grischa-hahn.homepage.t-online.de/astro/ser/SER%20Doc%20V3b.pdf
"""

import datetime
import struct
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ── Single-frame exporters ─────────────────────────────────────────────────────

def save_png(frame: np.ndarray, path: str | Path) -> None:
    """Save an RGB numpy array as PNG.

    Args:
        frame: (H, W, 3) uint8 RGB array or (H, W) uint8/uint16 mono array.
        path:  Output file path.
    """
    img = _to_pil(frame)
    img.save(str(path), format="PNG")
    logger.info("Saved PNG: %s", path)


def save_tiff(frame: np.ndarray, path: str | Path) -> None:
    """Save an RGB numpy array as TIFF (lossless).

    Args:
        frame: (H, W, 3) uint8 RGB array or (H, W) uint8/uint16 mono array.
        path:  Output file path.
    """
    img = _to_pil(frame)
    img.save(str(path), format="TIFF", compression="tiff_lzw")
    logger.info("Saved TIFF: %s", path)


def save_fits(
    frame: np.ndarray,
    path: str | Path,
    metadata: Optional[dict] = None,
) -> None:
    """Save a frame as a FITS file with optional header metadata.

    Args:
        frame:    (H, W, 3) uint8 RGB array or (H, W) mono array.
        path:     Output file path.
        metadata: dict of extra FITS header key/value pairs (optional).
    """
    try:
        from astropy.io import fits
    except ImportError:
        raise ImportError("astropy is required for FITS export: pip install astropy") from None

    if frame.ndim == 3:
        # FITS convention: axes are (planes, rows, cols) = (3, H, W)
        data = np.moveaxis(frame, -1, 0).astype(np.uint16)
    else:
        data = frame.astype(np.uint16)

    hdu = fits.PrimaryHDU(data)
    hdu.header["INSTRUME"] = "NexImage 10"
    hdu.header["DATE-OBS"] = datetime.datetime.utcnow().isoformat()
    if metadata:
        for key, value in metadata.items():
            hdu.header[key[:8].upper()] = value

    fits.HDUList([hdu]).writeto(str(path), overwrite=True)
    logger.info("Saved FITS: %s", path)


# ── SER video writer ───────────────────────────────────────────────────────────

# SER ColorID constants
_SER_MONO    = 0
_SER_BAYER   = 8   # generic Bayer / color (use for RGB after demosaic)
_SER_RGB     = 100

# Ticks from 0001-01-01 00:00:00 to Unix epoch (1970-01-01)
_TICKS_PER_SEC = 10_000_000
_EPOCH_OFFSET  = 621_355_968_000_000_000  # 100-ns ticks


def _utc_ticks() -> int:
    dt = datetime.datetime.utcnow()
    unix_ns = int(dt.timestamp() * 1e9)
    return _EPOCH_OFFSET + unix_ns // 100


class SERWriter:
    """Write frames to a SER (Lucky Imaging) video file.

    SER is a simple binary format widely supported by planetary imaging
    software (PIPP, AutoStakkert!, etc.).

    Usage::

        with SERWriter("output.ser", 1920, 1080, color=True) as writer:
            for frame in camera.stream():
                writer.write_frame(frame)
    """

    HEADER_SIZE = 178  # bytes

    def __init__(
        self,
        path: str | Path,
        width: int,
        height: int,
        color: bool = True,
        bits_per_channel: int = 8,
        observer: str = "",
        instrument: str = "NexImage 10",
        telescope: str = "",
    ) -> None:
        self._path = Path(path)
        self._width = width
        self._height = height
        self._color = color
        self._bits = bits_per_channel
        self._observer = observer
        self._instrument = instrument
        self._telescope = telescope

        self._frame_count = 0
        self._timestamps: list[int] = []
        self._file = None

    def open(self) -> None:
        self._file = open(self._path, "wb")
        self._write_placeholder_header()
        logger.info("SER recording started: %s", self._path)

    def close(self) -> None:
        if self._file is None:
            return
        self._write_timestamp_trailer()
        self._rewrite_header()
        self._file.close()
        self._file = None
        logger.info("SER recording complete: %s (%d frames)", self._path, self._frame_count)

    def __enter__(self) -> "SERWriter":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def write_frame(self, frame: np.ndarray) -> None:
        """Write one frame to the SER file.

        Args:
            frame: (H, W, 3) uint8 RGB array (color) or (H, W) uint8/uint16 mono array.
        """
        if self._file is None:
            raise RuntimeError("SERWriter is not open")

        self._timestamps.append(_utc_ticks())

        if frame.ndim == 3 and not self._color:
            import cv2
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        elif frame.ndim == 2 and self._color:
            import cv2
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)

        if self._bits == 8:
            data = frame.astype(np.uint8)
        else:
            data = frame.astype(np.uint16)

        self._file.write(data.tobytes())
        self._frame_count += 1

    # ── Internal ───────────────────────────────────────────────────────────────

    def _make_header(self, frame_count: int, date_utc: int) -> bytes:
        color_id = _SER_RGB if self._color else _SER_MONO
        planes   = 3 if self._color else 1

        def padded(s: str, n: int) -> bytes:
            b = s.encode("ascii", errors="replace")
            return b[:n].ljust(n, b"\x00")

        header = (
            b"LUCAM-RECORDER"              # file ID (14 bytes)
            + struct.pack("<i", 0)         # LuID
            + struct.pack("<i", color_id)  # ColorID
            + struct.pack("<i", 0)         # LittleEndian (0 = big-endian pixel order per spec)
            + struct.pack("<i", self._width)
            + struct.pack("<i", self._height)
            + struct.pack("<i", self._bits)
            + struct.pack("<i", frame_count)
            + padded(self._observer,   40)
            + padded(self._instrument, 40)
            + padded(self._telescope,  40)
            + struct.pack("<q", date_utc)   # DateTime (local)
            + struct.pack("<q", date_utc)   # DateTimeUTC
        )
        assert len(header) == self.HEADER_SIZE, f"Header size mismatch: {len(header)}"
        return header

    def _write_placeholder_header(self) -> None:
        self._file.write(self._make_header(0, _utc_ticks()))

    def _rewrite_header(self) -> None:
        date_utc = self._timestamps[0] if self._timestamps else _utc_ticks()
        self._file.seek(0)
        self._file.write(self._make_header(self._frame_count, date_utc))

    def _write_timestamp_trailer(self) -> None:
        if self._timestamps:
            self._file.seek(0, 2)  # end of file
            for ts in self._timestamps:
                self._file.write(struct.pack("<q", ts))


# ── Internal helpers ───────────────────────────────────────────────────────────

def _to_pil(frame: np.ndarray) -> Image.Image:
    if frame.ndim == 3 and frame.shape[2] == 3:
        return Image.fromarray(frame.astype(np.uint8), mode="RGB")
    elif frame.ndim == 2:
        if frame.dtype == np.uint16:
            return Image.fromarray(frame, mode="I;16")
        return Image.fromarray(frame.astype(np.uint8), mode="L")
    raise ValueError(f"Unsupported frame shape: {frame.shape}")

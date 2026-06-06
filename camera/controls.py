"""V4L2 control interface for the NexImage 10.

Exposes standard UVC controls (exposure, gain, brightness) via linuxpy.video.
Extension Unit controls (white balance, gamma, ROI) require reverse
engineering and are not yet implemented here.
"""

import logging
from typing import Optional

from linuxpy.video.device import Device

logger = logging.getLogger(__name__)

# Standard V4L2 control names as used by uvcvideo / linuxpy
CONTROL_GAIN      = "gain"
CONTROL_BRIGHTNESS = "brightness"

# UVC ExposureTime (absolute, in 100µs units). Kernels disagree on the name:
# newer ones use "exposure_time_absolute", older ones "exposure_absolute". The
# actual control is resolved against the device at runtime.
EXPOSURE_NAMES: tuple[str, ...] = ("exposure_time_absolute", "exposure_absolute")

# Human-readable aliases → internal names. "exposure" is resolved dynamically
# (see _resolve_name), so it is not listed here.
ALIASES: dict[str, str] = {
    "gain":       CONTROL_GAIN,
    "brightness": CONTROL_BRIGHTNESS,
}

# Candidate V4L2 control names for automatic white balance. Different UVC
# drivers / kernels expose this under different names, so we probe all of them.
AUTO_WB_NAMES: tuple[str, ...] = (
    "white_balance_temperature_auto",
    "white_balance_automatic",
    "auto_white_balance",
)

# Candidate manual red/blue balance control names, used as a fallback when the
# camera has no auto-WB toggle.
RED_BALANCE_NAMES:  tuple[str, ...] = ("red_balance",  "white_balance_red_component")
BLUE_BALANCE_NAMES: tuple[str, ...] = ("blue_balance", "white_balance_blue_component")


class ControlInfo:
    """Snapshot of a V4L2 control's metadata and current value."""

    def __init__(self, name: str, value: int, minimum: int, maximum: int, step: int, default: int) -> None:
        self.name    = name
        self.value   = value
        self.minimum = minimum
        self.maximum = maximum
        self.step    = step
        self.default = default

    def __repr__(self) -> str:
        return (
            f"ControlInfo({self.name!r}, value={self.value}, "
            f"min={self.minimum}, max={self.maximum}, step={self.step})"
        )

    def to_dict(self) -> dict:
        return {
            "name":    self.name,
            "value":   self.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step":    self.step,
            "default": self.default,
        }


class CameraControls:
    """Read and write V4L2 controls for the NexImage 10.

    Can share a Device instance with Camera, or open its own.

    Usage::

        with CameraControls() as ctrl:
            ctrl.set_exposure(1000)       # µs
            ctrl.set_gain(20)
            info = ctrl.list_controls()
    """

    def __init__(
        self,
        device_path: str = "/dev/video0",
        device: Optional[Device] = None,
    ) -> None:
        self.device_path = device_path
        self._external_device = device is not None
        self._device: Optional[Device] = device

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def open(self) -> None:
        if self._external_device:
            return  # caller manages the device
        self._device = Device(self.device_path)
        self._device.open()

    def close(self) -> None:
        if not self._external_device and self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def __enter__(self) -> "CameraControls":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── High-level helpers ─────────────────────────────────────────────────────

    def set_exposure(self, microseconds: int) -> None:
        """Set exposure time.

        Args:
            microseconds: Exposure in µs. The UVC control internally uses
                100µs units; this method converts automatically.
        """
        # UVC ExposureAbsolute is in units of 100µs
        value = max(1, round(microseconds / 100))
        self.set_control("exposure", value)

    def get_exposure(self) -> int:
        """Return current exposure in µs."""
        return self.get_control("exposure") * 100

    def set_gain(self, value: int) -> None:
        self.set_control(CONTROL_GAIN, value)

    def get_gain(self) -> int:
        return self.get_control(CONTROL_GAIN)

    def set_brightness(self, value: int) -> None:
        self.set_control(CONTROL_BRIGHTNESS, value)

    def get_brightness(self) -> int:
        return self.get_control(CONTROL_BRIGHTNESS)

    # ── White balance ───────────────────────────────────────────────────────────

    def enable_auto_white_balance(self) -> bool:
        """Turn on the camera's hardware automatic white balance, if present.

        Raw Bayer data is green-dominant; without white balance the demosaiced
        image has a heavy green cast. This enables the device's auto-WB control
        so red/blue gains are corrected in hardware.

        Probes the known auto-WB control names (``AUTO_WB_NAMES``) and enables
        the first one the device exposes. If no auto toggle exists but manual
        red/blue balance controls do, those are reset to their defaults as a
        fallback.

        Returns:
            True if any white-balance control was applied, else False.
        """
        self._require_open()
        available = self._device.controls

        # Preferred path: a single auto-WB toggle.
        for name in AUTO_WB_NAMES:
            if name in available:
                try:
                    available[name].value = 1
                    logger.info("Enabled auto white balance via %r", name)
                    return True
                except Exception as exc:
                    logger.debug("Could not set auto-WB control %r: %s", name, exc)

        # Fallback: reset manual red/blue balance to their neutral defaults.
        applied = False
        for names in (RED_BALANCE_NAMES, BLUE_BALANCE_NAMES):
            for name in names:
                if name in available:
                    try:
                        ctrl = available[name]
                        ctrl.value = ctrl.default
                        logger.info("Set %r to default %d (manual WB)", name, ctrl.default)
                        applied = True
                    except Exception as exc:
                        logger.debug("Could not set WB control %r: %s", name, exc)
                    break
        if applied:
            return True

        logger.info(
            "No hardware white-balance control found "
            "(camera likely exposes WB via the Vendor Extension Unit only)."
        )
        return False

    # ── Generic control API ────────────────────────────────────────────────────

    def set_control(self, name: str, value: int) -> None:
        """Set a control by name.

        Accepts canonical names (e.g. "exposure_time_absolute") or aliases
        (e.g. "exposure").
        """
        self._require_open()
        name = self._resolve_name(name)
        ctrl = self._get_ctrl_obj(name)
        ctrl.value = value
        logger.debug("Set %s = %d", name, value)

    def get_control(self, name: str) -> int:
        """Get current value of a control by name."""
        self._require_open()
        name = self._resolve_name(name)
        return self._get_ctrl_obj(name).value

    def list_controls(self) -> dict[str, ControlInfo]:
        """Return a dict of all available controls keyed by name."""
        self._require_open()
        result: dict[str, ControlInfo] = {}
        for ctrl in self._device.controls.values():
            try:
                info = ControlInfo(
                    name=ctrl.name,
                    value=ctrl.value,
                    minimum=ctrl.minimum,
                    maximum=ctrl.maximum,
                    step=ctrl.step,
                    default=ctrl.default,
                )
                result[ctrl.name] = info
            except Exception as exc:
                logger.debug("Skipping control %r: %s", ctrl.name, exc)
        return result

    # ── Internal ───────────────────────────────────────────────────────────────

    def _resolve_name(self, name: str) -> str:
        """Map an alias or kernel-variant name to an actual device control name.

        Handles the ``exposure`` alias and the exposure_absolute /
        exposure_time_absolute kernel naming split by checking what the device
        actually exposes.
        """
        name = ALIASES.get(name, name)
        if name == "exposure" or name in EXPOSURE_NAMES:
            for candidate in EXPOSURE_NAMES:
                if candidate in self._device.controls:
                    return candidate
            return EXPOSURE_NAMES[0]  # fall through to a clear "not found" error
        return name

    def _get_ctrl_obj(self, name: str):
        try:
            return self._device.controls[name]
        except KeyError:
            available = list(self._device.controls.keys())
            raise ValueError(
                f"Control {name!r} not found. Available: {available}"
            ) from None

    def _require_open(self) -> None:
        if self._device is None:
            raise RuntimeError("CameraControls not open. Call open() or use as context manager.")

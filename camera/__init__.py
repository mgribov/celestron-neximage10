"""Celestron NexImage 10 camera package.

Provides V4L2-based capture, control, and export for the NexImage 10
(USB ID 199e:8619, OEM: The Imaging Source).
"""

from .device import Camera
from .controls import CameraControls
from .export import save_png, save_tiff, save_fits, SERWriter

__all__ = ["Camera", "CameraControls", "save_png", "save_tiff", "save_fits", "SERWriter"]

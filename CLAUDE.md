# CLAUDE.md

This file provides context for Claude Code working in this repository.

## Project

Linux capture software for the Celestron NexImage 10 planetary camera. The camera is OEM'd by The Imaging Source (USB ID `199e:8619`) and is a **standard UVC 1.10 device** — the `uvcvideo` kernel driver loads automatically and exposes `/dev/video0`. No low-level USB reverse-engineering is needed for core capture.

Camera USB identity: **"The Imaging Source Europe GmbH NexImage 10"** (as shown in `lsusb` output).

## Architecture

```
Camera (UVC 1.10)
    ↓ uvcvideo kernel driver
/dev/video0
    ↓ linuxpy.video (V4L2 ioctls)
camera/device.py   — capture, demosaic
camera/controls.py — exposure, gain, brightness
camera/export.py   — PNG / TIFF / FITS / SER
    ↓
cli.py             — Click CLI
server/main.py     — FastAPI: MJPEG stream + REST API
server/static/     — Vanilla JS frontend
```

## Key implementation details

- **V4L2 library**: `linuxpy.video` (replaced `v4l2py`, which is unmaintained). Import pattern: `from linuxpy.video.device import Device, VideoCapture`.
- **Streaming**: `VideoCapture` is a context manager — use `with capture: for frame in capture:`. Do not call `.start()`/`.stop()` manually.
- **Format listing**: `device.info.formats` (not `video_capture.get_format_descriptions()`).
- **Bayer demosaic**: `cv2.COLOR_BAYER_GRBG2RGB` for GRBG/BA81 frames.
- **Exposure units**: V4L2 `exposure_absolute` is in 100 µs units; `CameraControls.set_exposure()` accepts µs and converts.
- **SER format**: header is 178 bytes; timestamps written as 100-ns ticks from 0001-01-01.

## Available resources

- `NexImage_Astroimaging_Camera_Manual_English_Web.pdf` — camera manual
- `NexImage_Windows_Driver_Cam33U_setup_5.3.0.2793.exe` — Windows driver
- `iCap2.5_Installer.exe` — Windows capture software
- `open_source_software_install_mac-os.pdf` — Mac SDK reference

## Pixel formats

| FourCC | Depth | Status |
|---|---|---|
| `GRBG` | 8-bit Bayer | Works; primary format |
| `Y800` | 8-bit mono | Works |
| `BA81` | 16-bit Bayer | Kernel rejects; needs tiscamera or libusb fallback |
| `Y16` | 16-bit mono | Needs testing |

## Known gaps / future work

- **BA81 (16-bit Bayer)**: uvcvideo rejects it. Investigate `tiscamera` (Apache 2.0, github.com/TheImagingSource/tiscamera) or a libusb fallback.
- **Vendor Extension Unit**: white balance, gamma, ROI not yet mapped. Requires USB sniffing on Windows.
- **WSL2**: use `usbipd-win` for USB passthrough; high frame rates may be limited.

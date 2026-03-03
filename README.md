# Celestron NexImage 10 — Linux Support

Linux capture software for the [Celestron NexImage 10](https://www.celestron.com/products/neximage-10-solar-system-color-imager) planetary imaging camera. The camera is OEM'd from The Imaging Source (USB ID `199e:8619`) and is a standard UVC 1.10 device — no driver reverse-engineering needed. The `uvcvideo` kernel module recognises it automatically and exposes it as `/dev/video0`.

## Features

- **CLI** — capture frames, record SER video, adjust controls
- **Web GUI** — live MJPEG stream, exposure/gain/brightness sliders, histogram, file browser
- **Export formats** — PNG, TIFF, FITS (astropy), SER video

## Requirements

- Linux with `uvcvideo` loaded (standard on all modern kernels)
- Python 3.11+
- Camera plugged in and visible as `/dev/video0`

On WSL2, use [`usbipd-win`](https://github.com/dorssel/usbipd-win) to pass the USB device through:

```sh
# Windows PowerShell (admin)
usbipd list
usbipd bind --busid <busid>
usbipd attach --wsl --busid <busid>
```

## Installation

```sh
pip install -r requirements.txt
```

## Quick start

```sh
# Verify the camera is visible and list its pixel formats
python cli.py list-formats

# Capture a single frame
python cli.py capture --output shot.png

# Start the web GUI
python cli.py serve
# → open http://localhost:8000
```

## CLI reference

```
python cli.py [--device /dev/video0] [--verbose] <command>
```

| Command | Description |
|---|---|
| `list-formats` | Print pixel formats supported by the device |
| `list-controls` | Print V4L2 controls and their current values |
| `set-control <name> <value>` | Set a control (aliases: `exposure` µs, `gain`, `brightness`) |
| `capture` | Capture one frame (options: `--width`, `--height`, `--pixel-format`, `--output`) |
| `record` | Record to a SER file (options: `--duration`, `--output`) |
| `serve` | Start the web GUI (options: `--host`, `--port`, `--output-dir`) |

### Examples

```sh
python cli.py capture --width 1920 --height 1080 --pixel-format GRBG --output frame.png
python cli.py capture --output frame.fits          # FITS for astropy workflows
python cli.py set-control exposure 5000            # 5000 µs exposure
python cli.py set-control gain 20
python cli.py record --duration 60 --output jupiter.ser
python cli.py serve --port 8000 --output-dir captures/
```

## Pixel formats

| FourCC | Depth | Notes |
|---|---|---|
| `GRBG` | 8-bit Bayer | Default; demosaiced via OpenCV `COLOR_BAYER_GRBG2RGB` |
| `Y800` | 8-bit mono | Works out of the box |
| `BA81` | 16-bit Bayer | Kernel may reject; fall back to `GRBG` if so |
| `Y16` | 16-bit mono | Needs testing |

## Supported resolutions

| Resolution | Max fps |
|---|---|
| 640 × 480 | 90 |
| 1280 × 720 | 60 |
| 1920 × 1080 | 30 |
| 2560 × 1440 | 15 |
| 3072 × 2048 | 10 |
| 3872 × 2764 | 6 |

## Project structure

```
camera/
  __init__.py    — public API
  device.py      — Camera class: V4L2 capture via linuxpy.video, Bayer demosaic
  controls.py    — CameraControls class: exposure, gain, brightness
  export.py      — save_png, save_tiff, save_fits, SERWriter
server/
  main.py        — FastAPI backend: MJPEG stream, REST API, file browser
  static/
    index.html   — Vanilla JS frontend
cli.py           — Click CLI entry point
requirements.txt
```

## Known limitations / future work

- **16-bit Bayer (BA81)**: the `uvcvideo` kernel driver currently rejects this format. A `tiscamera` or libusb-based fallback is needed for 16-bit Bayer capture.
- **Vendor Extension Unit**: white balance, gamma, and ROI/subframe controls live in the UVC Extension Unit and are not yet mapped. Mapping them requires USB traffic capture on Windows.
- **WSL2 frame rates**: USB passthrough via `usbipd` may limit throughput at high frame rates.

#!/usr/bin/env python3
"""NexImage 10 command-line interface.

Usage examples::

    python cli.py list-formats
    python cli.py capture --output shot.png
    python cli.py capture --width 1920 --height 1080 --format tiff --output shot.tiff
    python cli.py set-control gain 20
    python cli.py set-control exposure 5000
    python cli.py list-controls
    python cli.py record --duration 30 --output capture.ser
    python cli.py serve            # start the web GUI
"""

import datetime
import logging
import pathlib
import sys

import click

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)


@click.group()
@click.option("--device", default="/dev/video0", show_default=True, help="V4L2 device path.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, device: str, verbose: bool) -> None:
    """NexImage 10 Linux capture tool."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    ctx.ensure_object(dict)
    ctx.obj["device"] = device


# ── list-formats ──────────────────────────────────────────────────────────────

@cli.command("list-formats")
@click.pass_context
def list_formats(ctx: click.Context) -> None:
    """List pixel formats supported by the camera."""
    from camera import Camera
    device_path = ctx.obj["device"]
    with Camera(device_path) as cam:
        fmts = cam.list_formats()
    if not fmts:
        click.echo("No formats found.")
        return
    click.echo(f"{'FourCC':<12} {'Description'}")
    click.echo("-" * 40)
    for f in fmts:
        click.echo(f"{f['pixel_format']:<12} {f['description']}")


# ── list-controls ─────────────────────────────────────────────────────────────

@cli.command("list-controls")
@click.pass_context
def list_controls(ctx: click.Context) -> None:
    """List V4L2 controls and their current values."""
    from camera import CameraControls
    device_path = ctx.obj["device"]
    with CameraControls(device_path) as ctrl:
        controls = ctrl.list_controls()
    if not controls:
        click.echo("No controls found.")
        return
    click.echo(f"{'Name':<30} {'Value':>8}  {'Min':>8}  {'Max':>8}  {'Step':>6}  {'Default':>8}")
    click.echo("-" * 80)
    for info in controls.values():
        click.echo(
            f"{info.name:<30} {info.value:>8}  {info.minimum:>8}  "
            f"{info.maximum:>8}  {info.step:>6}  {info.default:>8}"
        )


# ── set-control ───────────────────────────────────────────────────────────────

@cli.command("set-control")
@click.argument("name")
@click.argument("value", type=int)
@click.pass_context
def set_control(ctx: click.Context, name: str, value: int) -> None:
    """Set a V4L2 control by NAME to VALUE.

    NAME can be the full control name (e.g. exposure_absolute) or
    an alias: exposure, gain, brightness.

    Exposure values are in microseconds and are converted automatically.
    Other controls are passed directly to the driver.
    """
    from camera import CameraControls
    device_path = ctx.obj["device"]
    with CameraControls(device_path) as ctrl:
        if name in ("exposure", "exposure_absolute"):
            ctrl.set_exposure(value)
            click.echo(f"exposure set to {value} µs")
        else:
            ctrl.set_control(name, value)
            click.echo(f"{name} set to {value}")


# ── capture ───────────────────────────────────────────────────────────────────

@cli.command("capture")
@click.option("--width",  "-W", default=1920, show_default=True, type=int)
@click.option("--height", "-H", default=1080, show_default=True, type=int)
@click.option("--pixel-format", "-p", default="GRBG", show_default=True,
              help="Raw pixel format: GRBG, Y800, BA81, Y16")
@click.option("--output", "-o", default=None, help="Output file path (extension determines format).")
@click.option("--format", "-f", "export_fmt",
              type=click.Choice(["png", "tiff", "fits"], case_sensitive=False),
              default="png", show_default=True,
              help="Export format (overridden by output extension).")
@click.pass_context
def capture(
    ctx: click.Context,
    width: int,
    height: int,
    pixel_format: str,
    output: str | None,
    export_fmt: str,
) -> None:
    """Capture a single frame and save it."""
    from camera import Camera, save_png, save_tiff, save_fits

    device_path = ctx.obj["device"]

    if output is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"neximage_{ts}.{export_fmt}"

    output_path = pathlib.Path(output)
    suffix = output_path.suffix.lower().lstrip(".")
    if suffix in ("png", "tiff", "tif", "fits", "fit"):
        export_fmt = "tiff" if suffix in ("tiff", "tif") else suffix.rstrip("s")  # fits/fit → fit handled below

    click.echo(f"Opening {device_path} …")
    with Camera(device_path) as cam:
        cam.set_format(width, height, pixel_format)
        click.echo(f"Capturing {width}×{height} {pixel_format} …")
        frame = cam.get_frame()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    sfx = output_path.suffix.lower()
    if sfx in (".tif", ".tiff"):
        save_tiff(frame, output_path)
    elif sfx in (".fit", ".fits"):
        save_fits(frame, output_path)
    else:
        save_png(frame, output_path)

    click.echo(f"Saved → {output_path} ({frame.shape[1]}×{frame.shape[0]})")


# ── record ────────────────────────────────────────────────────────────────────

@cli.command("record")
@click.option("--width",  "-W", default=1920, show_default=True, type=int)
@click.option("--height", "-H", default=1080, show_default=True, type=int)
@click.option("--pixel-format", "-p", default="GRBG", show_default=True)
@click.option("--duration", "-d", default=10, show_default=True, type=float,
              help="Recording duration in seconds.")
@click.option("--output", "-o", default=None, help="Output .ser file path.")
@click.pass_context
def record(
    ctx: click.Context,
    width: int,
    height: int,
    pixel_format: str,
    duration: float,
    output: str | None,
) -> None:
    """Record frames to a SER file for the specified duration."""
    import time
    from camera import Camera, SERWriter

    device_path = ctx.obj["device"]

    if output is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"neximage_{ts}.ser"

    click.echo(f"Recording {duration:.1f}s → {output}")
    end_time = time.monotonic() + duration
    frame_count = 0

    with Camera(device_path) as cam:
        cam.set_format(width, height, pixel_format)
        with SERWriter(output, width, height, color=(pixel_format != "Y800")) as writer:
            for frame in cam.stream():
                writer.write_frame(frame)
                frame_count += 1
                if time.monotonic() >= end_time:
                    break

    click.echo(f"Done — {frame_count} frames saved to {output}")


# ── serve ─────────────────────────────────────────────────────────────────────

@cli.command("serve")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--output-dir", default="captures", show_default=True,
              help="Directory for captured files.")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int, output_dir: str) -> None:
    """Start the web GUI server."""
    import uvicorn
    from server.main import create_app

    device_path = ctx.obj["device"]
    app = create_app(device_path=device_path, output_dir=output_dir)
    click.echo(f"Web GUI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    cli()

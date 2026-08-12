"""CLI entry point for MarlinSIM simulator."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .core import SimulatorCore
from .models import list_models, load_model
from .server import WebServer


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for ``marlinsim-run``."""
    parser = argparse.ArgumentParser(
        prog="marlinsim-run",
        description=(
            "MarlinSIM — Full Marlin Firmware Simulator\n\n"
            "Runs real Marlin firmware on your PC with virtual hardware,\n"
            "LCD display streaming, and interactive Web UI."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version", action="version", version=f"marlinsim-run {__version__}"
    )

    # Printer model
    parser.add_argument(
        "-m", "--model",
        default="ender3v2_skr_mini_e3_v2",
        help=(
            "Printer model name or path to custom JSON model file. "
            "Use --list-models to see available models. "
            "(default: ender3v2_skr_mini_e3_v2)"
        ),
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available printer models and exit.",
    )

    # Marlin version
    parser.add_argument(
        "--marlin-version",
        default="2.1.x",
        help="Marlin git branch or tag to use (default: 2.1.x)",
    )
    parser.add_argument(
        "--marlin-repo",
        default="https://github.com/MarlinFirmware/Marlin.git",
        help="Marlin git repository URL",
    )

    # Build control
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building Marlin (use existing build)",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force fresh clone and rebuild",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Build workspace directory (default: ~/.marlinsim/builds)",
    )

    # Web UI
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Web UI bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Web UI port (default: 8080)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open the Web UI in a browser automatically",
    )

    # G-code input
    parser.add_argument(
        "-g", "--gcode",
        type=Path,
        default=None,
        help="G-code file to stream to the printer after startup",
    )

    # Verbosity
    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v info, -vv debug)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress all output except errors",
    )

    args = parser.parse_args(argv)

    # Configure logging
    if args.quiet:
        log_level = logging.ERROR
    elif args.verbose >= 2:
        log_level = logging.DEBUG
    elif args.verbose >= 1:
        log_level = logging.INFO
    else:
        log_level = logging.WARNING

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # List models
    if args.list_models:
        models = list_models()
        print("Available printer models:")
        print()
        for name in models:
            try:
                m = load_model(name)
                print(f"  {name:40s} {m.name} ({m.board.name})")
            except Exception as e:
                print(f"  {name:40s} (error loading: {e})")
        print()
        print("Use: marlinsim-run -m <model_name>")
        print("Or provide a custom JSON: marlinsim-run -m /path/to/model.json")
        return 0

    # Load printer model
    try:
        printer = load_model(args.model)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"╔══════════════════════════════════════════════════╗")
    print(f"║          MarlinSIM Firmware Simulator            ║")
    print(f"╠══════════════════════════════════════════════════╣")
    print(f"║  Printer:  {printer.name:<37s} ║")
    print(f"║  Board:    {printer.board.name:<37s} ║")
    print(f"║  MCU:      {printer.board.mcu:<37s} ║")
    print(f"║  Display:  {printer.display.type} {printer.display.width}x{printer.display.height:<24} ║")
    print(f"║  Marlin:   {args.marlin_version:<37s} ║")
    print(f"║  Web UI:   http://{args.host}:{args.port:<23} ║")
    print(f"╚══════════════════════════════════════════════════╝")
    print()

    # Run async main
    return asyncio.run(
        _async_main(args, printer)
    )


async def _async_main(args, printer) -> int:
    """Async main — starts simulator, web server, and runs the event loop."""
    sim = SimulatorCore(
        printer=printer,
        marlin_version=args.marlin_version,
        workspace=args.workspace,
        skip_build=args.skip_build,
    )

    web = WebServer(
        simulator=sim,
        host=args.host,
        port=args.port,
    )

    try:
        # Start simulator (clone, build, launch Marlin)
        print("Starting simulator ...")
        await sim.start()

        # Start web server
        print(f"Starting Web UI at http://{args.host}:{args.port} ...")
        await web.start()

        # Open browser
        if not args.no_browser:
            import webbrowser
            webbrowser.open(f"http://localhost:{args.port}")

        # If G-code file specified, stream it after a startup delay
        if args.gcode:
            asyncio.create_task(_stream_gcode(sim, args.gcode))

        # Run simulation loop
        print("Simulator running.  Press Ctrl+C to stop.")
        print()
        await sim.run()

    except KeyboardInterrupt:
        print("\nShutting down ...")
    except Exception as e:
        logging.getLogger(__name__).error("Fatal error: %s", e, exc_info=True)
        return 1
    finally:
        await sim.stop()
        await web.stop()

    print("Goodbye.")
    return 0


async def _stream_gcode(sim: SimulatorCore, path: Path, delay: float = 5.0) -> None:
    """Stream a G-code file to the simulator after a startup delay."""
    logger = logging.getLogger(__name__)
    logger.info("Will stream %s after %.1fs delay ...", path, delay)
    await asyncio.sleep(delay)

    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                sim.send_gcode(line)
                # Wait for ok response before next command
                await sim.read_response(timeout=10.0)
                await asyncio.sleep(0.01)  # small yield
    except FileNotFoundError:
        logger.error("G-code file not found: %s", path)
    except Exception as e:
        logger.error("Error streaming G-code: %s", e)


if __name__ == "__main__":
    sys.exit(main())

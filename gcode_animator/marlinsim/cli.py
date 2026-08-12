"""CLI entry point for marlinsim-gcode post-processor."""

import argparse
import sys
import os
import time

from .analyzer import GCodeAnalyzer
from .projector import IsometricProjector
from .rasterizer import Rasterizer
from .compressor import FrameCompressor
from .injector import GCodeInjector
from .profiles import get_profile, list_profiles


def main():
    parser = argparse.ArgumentParser(
        prog="marlinsim-gcode",
        description="MarlinSIM G-code post-processor: generates print progress "
                    "animation frames and injects them into G-code files.",
    )
    parser.add_argument(
        "input",
        help="Input G-code file path",
        nargs="?",
        default=None,
    )
    parser.add_argument(
        "-o", "--output",
        help="Output G-code file path (default: overwrite input)",
        default=None,
    )
    parser.add_argument(
        "--printer",
        help="Printer profile name (default: ender3v2)",
        default="ender3v2",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        help="Maximum number of animation frames (default: auto from layer count)",
        default=None,
    )
    parser.add_argument(
        "--keyframe-interval",
        type=int,
        help="Insert a full keyframe every N frames (default: 10)",
        default=10,
    )
    parser.add_argument(
        "--rotation",
        type=float,
        help="Isometric rotation angle in degrees (default: 35.264)",
        default=35.264,
    )
    parser.add_argument(
        "--list-printers",
        action="store_true",
        help="List available printer profiles and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and generate frames but don't write output",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.list_printers:
        print("Available printer profiles:")
        for name, desc in list_profiles():
            print(f"  {name:20s} — {desc}")
        return 0

    if not args.input:
        print("Error: Input file is required.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 1

    if not os.path.isfile(args.input):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        return 1

    output_path = args.output or args.input

    # Load printer profile
    try:
        profile = get_profile(args.printer)
    except KeyError:
        print(f"Error: Unknown printer profile: {args.printer}", file=sys.stderr)
        print("Use --list-printers to see available profiles.")
        return 1

    if args.verbose:
        print(f"MarlinSIM G-code Animator v{__import__('marlinsim').__version__}")
        print(f"Profile: {profile.name} ({profile.display_width}x{profile.display_height})")
        print(f"Input:   {args.input}")
        print(f"Output:  {output_path}")

    t0 = time.time()

    # Step 1: Analyze G-code — extract layers and geometry
    if args.verbose:
        print("\n[1/5] Analyzing G-code...")
    analyzer = GCodeAnalyzer()
    layers = analyzer.analyze(args.input)
    if args.verbose:
        print(f"       Found {len(layers)} layers, "
              f"bounds: X[{analyzer.bounds[0]:.1f}..{analyzer.bounds[1]:.1f}] "
              f"Y[{analyzer.bounds[2]:.1f}..{analyzer.bounds[3]:.1f}] "
              f"Z[{analyzer.bounds[4]:.1f}..{analyzer.bounds[5]:.1f}]")

    # Step 2: Determine frame count
    max_frames = args.max_frames
    if max_frames is None:
        # Auto: one frame per layer, but cap to reasonable amount
        max_frames = min(len(layers), 500)
    if args.verbose:
        print(f"\n[2/5] Generating {max_frames} animation frames...")

    # Step 3: Project and rasterize each frame
    projector = IsometricProjector(
        bounds=analyzer.bounds,
        display_width=profile.display_width,
        display_height=profile.display_height,
        rotation_deg=args.rotation,
    )
    rasterizer = Rasterizer(
        width=profile.display_width,
        height=profile.display_height,
    )

    frames = []  # list of 1-bit frame buffers (bytearray)
    layer_step = max(1, len(layers) // max_frames)

    for frame_idx in range(max_frames):
        layer_idx = min(frame_idx * layer_step, len(layers) - 1)
        # Project all layers up to current one
        segments = projector.project_layers(layers, 0, layer_idx + 1)
        bitmap = rasterizer.rasterize(segments)
        frames.append(bitmap)

    if args.verbose:
        raw_size = len(frames) * (profile.display_width * profile.display_height // 8)
        print(f"       Raw frame data: {raw_size} bytes")

    # Step 4: Compress frames
    if args.verbose:
        print(f"\n[3/5] Compressing frames (keyframe interval: {args.keyframe_interval})...")
    compressor = FrameCompressor(
        width=profile.display_width,
        height=profile.display_height,
        keyframe_interval=args.keyframe_interval,
    )
    compressed_frames = compressor.compress(frames)
    if args.verbose:
        total_compressed = sum(len(f.data) for f in compressed_frames)
        print(f"       Compressed: {total_compressed} bytes "
              f"({total_compressed * 100 // max(1, raw_size)}% of raw)")

    # Step 5: Map frames to G-code layers and inject
    if args.verbose:
        print(f"\n[4/5] Mapping frames to G-code lines...")

    frame_layer_map = []
    for frame_idx in range(max_frames):
        layer_idx = min(frame_idx * layer_step, len(layers) - 1)
        line_number = layers[layer_idx].start_line
        frame_layer_map.append((frame_idx, line_number, compressed_frames[frame_idx]))

    if args.dry_run:
        if args.verbose:
            print(f"\n[5/5] Dry run — not writing output.")
            elapsed = time.time() - t0
            print(f"\nDone in {elapsed:.2f}s")
        return 0

    if args.verbose:
        print(f"\n[5/5] Injecting into G-code...")
    injector = GCodeInjector(profile)
    injector.inject(args.input, output_path, frame_layer_map)

    elapsed = time.time() - t0
    if args.verbose:
        output_size = os.path.getsize(output_path)
        print(f"\nDone in {elapsed:.2f}s — output: {output_size} bytes")
    else:
        print(f"MarlinSIM: {max_frames} frames injected into {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

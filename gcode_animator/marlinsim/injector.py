"""G-code injector — embeds compressed animation frames into G-code files.

Inserts MarlinSIM frame data as specially formatted comments that the firmware
module can detect and parse during printing. The format is designed to be:

1. Invisible to standard G-code parsers (just comments)
2. Quick to identify (unique prefix)
3. Streamable (firmware reads frames one line at a time)
4. Small (hex-encoded compressed data)

Frame comment format:
    ; MSIM:H:WWWW:HHHH:FFFF          — Header (width, height, total frames)
    ; MSIM:F:NNNN:HEXDATA...          — Frame data (frame number, compressed hex)
    ; MSIM:K:NNNN:HEXDATA...          — Keyframe data
    ; MSIM:E                          — End marker

Long frames are split across multiple lines (max ~80 chars per line):
    ; MSIM:F:0001:AABBCCDD...         — First chunk
    ; MSIM:C:EEFF0011...              — Continuation chunk
"""

from __future__ import annotations

from typing import List, Tuple

from .compressor import CompressedFrame


# Maximum hex chars per G-code comment line (keep lines short for serial)
MAX_HEX_PER_LINE = 60


class GCodeInjector:
    """Injects MarlinSIM animation frame data into G-code files.

    Args:
        profile: Printer profile with display configuration
    """

    def __init__(self, profile):
        self.profile = profile

    def inject(
        self,
        input_path: str,
        output_path: str,
        frame_map: List[Tuple[int, int, CompressedFrame]],
    ):
        """Inject frame data into a G-code file.

        Args:
            input_path: Path to original G-code file
            output_path: Path for output G-code file
            frame_map: List of (frame_index, gcode_line_number, CompressedFrame)
        """
        # Build a lookup: line_number → list of frames to inject BEFORE that line
        inject_points: dict[int, List[Tuple[int, CompressedFrame]]] = {}
        for frame_idx, line_no, compressed in frame_map:
            if line_no not in inject_points:
                inject_points[line_no] = []
            inject_points[line_no].append((frame_idx, compressed))

        total_frames = len(frame_map)

        with open(input_path, "r") as fin, open(output_path, "w") as fout:
            # Write MarlinSIM header at top of file
            fout.write(f"; MarlinSIM Animation Data\n")
            fout.write(f"; MSIM:H:{self.profile.display_width:04X}"
                       f":{self.profile.display_height:04X}"
                       f":{total_frames:04X}\n")

            for line_no, line in enumerate(fin, start=1):
                # Check if we need to inject frames before this line
                if line_no in inject_points:
                    for frame_idx, compressed in inject_points[line_no]:
                        self._write_frame(fout, frame_idx, compressed)

                fout.write(line)

            # Write end marker
            fout.write("; MSIM:E\n")

    def _write_frame(self, fout, frame_idx: int, compressed: CompressedFrame):
        """Write a single compressed frame as G-code comments."""
        hex_data = compressed.to_hex()
        prefix = "K" if compressed.is_keyframe else "F"

        if len(hex_data) <= MAX_HEX_PER_LINE:
            fout.write(f"; MSIM:{prefix}:{frame_idx:04X}:{hex_data}\n")
        else:
            # Split across multiple lines
            chunk = hex_data[:MAX_HEX_PER_LINE]
            fout.write(f"; MSIM:{prefix}:{frame_idx:04X}:{chunk}\n")
            remaining = hex_data[MAX_HEX_PER_LINE:]
            while remaining:
                chunk = remaining[:MAX_HEX_PER_LINE]
                remaining = remaining[MAX_HEX_PER_LINE:]
                fout.write(f"; MSIM:C:{chunk}\n")


def format_header_comment(profile, total_frames: int) -> str:
    """Generate the MSIM header comment string."""
    return (f"; MSIM:H:{profile.display_width:04X}"
            f":{profile.display_height:04X}"
            f":{total_frames:04X}")

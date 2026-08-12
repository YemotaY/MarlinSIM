"""Tests for the G-code injector module."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcode_animator"))

from marlinsim.injector import GCodeInjector
from marlinsim.compressor import CompressedFrame
from marlinsim.profiles import get_profile


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_GCODE = os.path.join(FIXTURE_DIR, "sample.gcode")


class TestGCodeInjector:
    """Tests for the GCodeInjector class."""

    def setup_method(self):
        self.profile = get_profile("ender3v2")
        self.injector = GCodeInjector(self.profile)

    def test_inject_adds_header(self, tmp_path):
        """Injected file should contain MSIM header."""
        output = str(tmp_path / "output.gcode")
        self.injector.inject(SAMPLE_GCODE, output, [])

        with open(output) as f:
            content = f.read()
        assert "; MSIM:H:" in content

    def test_inject_adds_end_marker(self, tmp_path):
        """Injected file should contain MSIM end marker."""
        output = str(tmp_path / "output.gcode")
        self.injector.inject(SAMPLE_GCODE, output, [])

        with open(output) as f:
            content = f.read()
        assert "; MSIM:E" in content

    def test_inject_preserves_original(self, tmp_path):
        """Original G-code lines should be preserved."""
        output = str(tmp_path / "output.gcode")
        self.injector.inject(SAMPLE_GCODE, output, [])

        with open(SAMPLE_GCODE) as f:
            original_lines = set(f.read().strip().split("\n"))

        with open(output) as f:
            output_lines = set(f.read().strip().split("\n"))

        # All original lines should be in output
        for line in original_lines:
            assert line in output_lines, f"Missing line: {line}"

    def test_inject_frame_data(self, tmp_path):
        """Injected file should contain frame data comments."""
        output = str(tmp_path / "output.gcode")

        # Create fake compressed frames
        frames = [
            (0, 15, CompressedFrame(0, True, bytes([0x80, 0x8E, 0x00]))),
            (1, 25, CompressedFrame(1, False, bytes([0x00, 0x8E, 0x00]))),
        ]

        self.injector.inject(SAMPLE_GCODE, output, frames)

        with open(output) as f:
            content = f.read()

        assert "; MSIM:K:0000:" in content  # Keyframe
        assert "; MSIM:F:0001:" in content  # Delta frame

    def test_inject_header_format(self, tmp_path):
        """Header should contain correct display dimensions."""
        output = str(tmp_path / "output.gcode")
        self.injector.inject(SAMPLE_GCODE, output, [])

        with open(output) as f:
            content = f.read()

        # 128 = 0x0080, 64 = 0x0040
        assert "; MSIM:H:0080:0040:" in content

    def test_inject_long_frame_splits(self, tmp_path):
        """Long frame data should be split across continuation lines."""
        output = str(tmp_path / "output.gcode")

        # Create a frame with data longer than MAX_HEX_PER_LINE
        long_data = bytes([0x80] + [0xAA] * 40)  # 40 bytes = 80 hex chars
        frames = [
            (0, 15, CompressedFrame(0, True, long_data)),
        ]

        self.injector.inject(SAMPLE_GCODE, output, frames)

        with open(output) as f:
            content = f.read()

        assert "; MSIM:K:0000:" in content  # Start of frame
        assert "; MSIM:C:" in content  # Continuation line


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

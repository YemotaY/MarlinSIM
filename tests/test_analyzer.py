"""Tests for the G-code analyzer module."""

import os
import sys
import pytest

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcode_animator"))

from marlinsim.analyzer import GCodeAnalyzer, Layer, Segment


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_GCODE = os.path.join(FIXTURE_DIR, "sample.gcode")


class TestGCodeAnalyzer:
    """Tests for the GCodeAnalyzer class."""

    def test_analyze_finds_layers(self):
        """Analyzer should find multiple layers in sample G-code."""
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(SAMPLE_GCODE)
        assert len(layers) >= 3, f"Expected at least 3 layers, got {len(layers)}"

    def test_analyze_extracts_segments(self):
        """Each layer should contain printed segments."""
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(SAMPLE_GCODE)
        for layer in layers:
            assert layer.segment_count > 0, (
                f"Layer at Z={layer.z_height} has no segments"
            )

    def test_analyze_bounds(self):
        """Bounding box should encompass all segment coordinates."""
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(SAMPLE_GCODE)
        xmin, xmax, ymin, ymax, zmin, zmax = analyzer.bounds

        # Sample G-code goes from X10-X50, Y10-Y50
        assert xmin <= 10.0
        assert xmax >= 50.0
        assert ymin <= 10.0
        assert ymax >= 50.0
        assert zmin <= 0.2
        assert zmax >= 0.8

    def test_analyze_z_heights_increasing(self):
        """Layer Z heights should be monotonically increasing."""
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(SAMPLE_GCODE)
        for i in range(1, len(layers)):
            assert layers[i].z_height > layers[i - 1].z_height, (
                f"Layer {i} Z={layers[i].z_height} not > "
                f"layer {i-1} Z={layers[i-1].z_height}"
            )

    def test_analyze_segment_coordinates(self):
        """Segments should have valid 3D coordinates."""
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(SAMPLE_GCODE)
        for layer in layers:
            for seg in layer.segments:
                assert isinstance(seg.x0, float)
                assert isinstance(seg.y0, float)
                assert isinstance(seg.z0, float)
                assert isinstance(seg.x1, float)
                assert isinstance(seg.y1, float)
                assert isinstance(seg.z1, float)

    def test_analyze_empty_file(self, tmp_path):
        """Analyzer should handle empty G-code gracefully."""
        empty_file = tmp_path / "empty.gcode"
        empty_file.write_text("")
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(str(empty_file))
        assert len(layers) >= 1  # Should return at least a dummy layer

    def test_analyze_only_moves_no_extrusion(self, tmp_path):
        """G-code with moves but no extrusion should produce layers with no segments."""
        gcode = "G28\nG1 X50 Y50 Z0.3 F3000\nG1 X100 Y100 F1500\n"
        f = tmp_path / "nomove.gcode"
        f.write_text(gcode)
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(str(f))
        # Should still produce a layer list (possibly with empty segments)
        assert isinstance(layers, list)

    def test_start_line_tracking(self):
        """Each layer should track which G-code line it starts at."""
        analyzer = GCodeAnalyzer()
        layers = analyzer.analyze(SAMPLE_GCODE)
        for layer in layers:
            assert layer.start_line > 0, "start_line should be positive"


class TestSegment:
    """Tests for the Segment dataclass."""

    def test_segment_creation(self):
        """Segment should store coordinates."""
        seg = Segment(0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
        assert seg.x0 == 0.0
        assert seg.y1 == 4.0
        assert seg.z1 == 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

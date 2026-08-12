"""Tests for the frame compressor module."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcode_animator"))

from marlinsim.compressor import FrameCompressor, CompressedFrame


class TestRLEEncoding:
    """Tests for the RLE encoding/decoding."""

    def setup_method(self):
        self.compressor = FrameCompressor(width=16, height=8, keyframe_interval=5)
        self.frame_bytes = 2 * 8  # 16px wide = 2 bytes/row × 8 rows = 16 bytes

    def test_encode_all_zeros(self):
        """All-zero frame should compress to a short repeat run."""
        frame = bytearray(self.frame_bytes)
        encoded = FrameCompressor._rle_encode(frame)
        # Should be very small — one repeat run of 0x00
        assert len(encoded) < self.frame_bytes
        # Verify decode
        decoded = FrameCompressor._rle_decode(encoded, self.frame_bytes)
        assert decoded == frame

    def test_encode_all_ones(self):
        """All-0xFF frame should compress to a short repeat run."""
        frame = bytearray([0xFF] * self.frame_bytes)
        encoded = FrameCompressor._rle_encode(frame)
        assert len(encoded) < self.frame_bytes
        decoded = FrameCompressor._rle_decode(encoded, self.frame_bytes)
        assert decoded == frame

    def test_encode_alternating(self):
        """Alternating bytes should be stored as literals."""
        frame = bytearray([0xAA, 0x55] * (self.frame_bytes // 2))
        encoded = FrameCompressor._rle_encode(frame)
        decoded = FrameCompressor._rle_decode(encoded, self.frame_bytes)
        assert decoded == frame

    def test_encode_mixed(self):
        """Mixed data with runs and literals."""
        frame = bytearray(
            [0x00] * 8 +  # Run of zeros
            [0xAA, 0xBB, 0xCC, 0xDD] +  # Literals
            [0xFF] * 4  # Run of 0xFF
        )
        encoded = FrameCompressor._rle_encode(frame)
        decoded = FrameCompressor._rle_decode(encoded, len(frame))
        assert decoded == frame

    def test_roundtrip_random_like(self):
        """Pseudo-random data should survive encode/decode roundtrip."""
        # Deterministic "random" data
        frame = bytearray((i * 37 + 13) & 0xFF for i in range(self.frame_bytes))
        encoded = FrameCompressor._rle_encode(frame)
        decoded = FrameCompressor._rle_decode(encoded, self.frame_bytes)
        assert decoded == frame

    def test_empty_data(self):
        """Empty input should produce empty output."""
        encoded = FrameCompressor._rle_encode(bytearray())
        assert encoded == b""

    def test_single_byte(self):
        """Single byte should encode and decode correctly."""
        frame = bytearray([0x42])
        encoded = FrameCompressor._rle_encode(frame)
        decoded = FrameCompressor._rle_decode(encoded, 1)
        assert decoded == frame


class TestFrameCompression:
    """Tests for the full frame compression pipeline."""

    def setup_method(self):
        self.compressor = FrameCompressor(width=16, height=8, keyframe_interval=3)
        self.frame_bytes = 2 * 8

    def test_compress_single_frame(self):
        """Single frame should be a keyframe."""
        frames = [bytearray(self.frame_bytes)]
        result = self.compressor.compress(frames)
        assert len(result) == 1
        assert result[0].is_keyframe is True

    def test_keyframe_interval(self):
        """Keyframes should appear at the correct interval."""
        frames = [bytearray(self.frame_bytes) for _ in range(10)]
        result = self.compressor.compress(frames)
        for i, cf in enumerate(result):
            if i % 3 == 0:
                assert cf.is_keyframe, f"Frame {i} should be keyframe"
            else:
                assert not cf.is_keyframe, f"Frame {i} should be delta"

    def test_delta_compression(self):
        """Identical frames should produce very small deltas."""
        frame = bytearray([0xAA] * self.frame_bytes)
        frames = [bytearray(frame) for _ in range(5)]
        result = self.compressor.compress(frames)
        # Delta of identical frames = all zeros = tiny
        for cf in result:
            if not cf.is_keyframe:
                # Delta of identical frame is all-zero, compresses small
                assert cf.byte_count < self.frame_bytes

    def test_verify_frames(self):
        """All compressed frames should verify correctly."""
        # Create frames with progressive changes
        frames = []
        for i in range(6):
            f = bytearray(self.frame_bytes)
            for j in range(min(i * 3, self.frame_bytes)):
                f[j] = 0xFF
            frames.append(f)

        result = self.compressor.compress(frames)
        prev = None
        for i, cf in enumerate(result):
            assert self.compressor.verify_frame(cf, frames[i], prev)
            prev = bytearray(frames[i])

    def test_hex_output(self):
        """Compressed frame should produce valid hex string."""
        frames = [bytearray([0xAB] * self.frame_bytes)]
        result = self.compressor.compress(frames)
        hex_str = result[0].to_hex()
        assert all(c in "0123456789ABCDEF" for c in hex_str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

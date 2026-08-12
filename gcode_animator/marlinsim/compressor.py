"""Frame compressor — RLE + delta encoding for ultra-small frame data.

Compresses 1-bit animation frames for transmission inside G-code comments.
The compression scheme is designed to be decodable on MCUs with < 400 bytes
of RAM (like the STM32F103 on the SKR Mini E3 V2).

Compression pipeline:
1. Delta encoding: XOR current frame with previous frame (keyframes are full)
2. RLE encoding: Run-length encode the delta/full frame bytes
3. Hex encoding: Convert to hex string for safe G-code comment embedding

Format of compressed frame:
    - 1 byte header: bit 7 = keyframe flag, bits 0-6 = reserved
    - N bytes RLE data:
        - If byte < 0x80: literal run of (byte+1) bytes follows
        - If byte >= 0x80: repeat next byte (byte-0x80+2) times

This is similar to PackBits but simplified for MCU decoding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class CompressedFrame:
    """A single compressed animation frame."""
    frame_index: int
    is_keyframe: bool
    data: bytes  # raw compressed bytes (before hex encoding)

    def to_hex(self) -> str:
        """Convert to hex string for G-code injection."""
        return self.data.hex().upper()

    @property
    def byte_count(self) -> int:
        return len(self.data)


class FrameCompressor:
    """Compresses a sequence of 1-bit bitmaps using RLE + delta encoding.

    Args:
        width: Frame width in pixels
        height: Frame height in pixels
        keyframe_interval: Insert a full keyframe every N frames
    """

    def __init__(
        self,
        width: int = 128,
        height: int = 64,
        keyframe_interval: int = 10,
    ):
        self.width = width
        self.height = height
        self.row_bytes = (width + 7) // 8
        self.frame_bytes = self.row_bytes * height
        self.keyframe_interval = keyframe_interval

    def compress(self, frames: List[bytearray]) -> List[CompressedFrame]:
        """Compress a list of raw 1-bit bitmap frames.

        All frames use full RLE encoding (no inter-frame delta) to allow
        the firmware decoder to operate with minimal RAM — only one scanline
        buffer is needed, no previous-frame storage required.

        Delta encoding is done intra-frame: each byte is XOR'd with the
        previous byte in the same frame (byte-level delta), which improves
        RLE compression for gradual changes across the bitmap.

        Args:
            frames: List of bytearray bitmaps (each row_bytes * height long)

        Returns:
            List of CompressedFrame objects
        """
        result: List[CompressedFrame] = []

        for idx, frame in enumerate(frames):
            is_key = (idx % self.keyframe_interval == 0)

            if is_key:
                # Keyframe: compress full frame directly
                rle_data = self._rle_encode(frame)
                header = bytes([0x80])  # keyframe flag
            else:
                # Non-keyframe: use intra-frame byte delta + RLE
                # XOR each byte with the previous byte in the same frame
                delta = self._intra_delta_encode(frame)
                rle_data = self._rle_encode(delta)
                header = bytes([0x00])  # delta flag (intra-frame)

            compressed = header + rle_data
            result.append(CompressedFrame(
                frame_index=idx,
                is_keyframe=is_key,
                data=compressed,
            ))

        return result

    @staticmethod
    def _intra_delta_encode(data: bytearray) -> bytearray:
        """Intra-frame delta: XOR each byte with the previous byte."""
        if not data:
            return bytearray()
        result = bytearray(len(data))
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = data[i] ^ data[i - 1]
        return result

    @staticmethod
    def _intra_delta_decode(data: bytearray) -> bytearray:
        """Decode intra-frame delta encoding."""
        if not data:
            return bytearray()
        result = bytearray(len(data))
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = data[i] ^ result[i - 1]
        return result

    @staticmethod
    def _rle_encode(data: bytearray) -> bytes:
        """RLE encode a byte sequence using a PackBits-like scheme.

        Encoding rules:
        - Repeat run: 0x80 + (count-2), value_byte  (count 2..129)
        - Literal run: (count-1), byte0, byte1, ...  (count 1..128)

        Optimized for frames with large runs of 0x00 (empty areas) and 0xFF.
        """
        if not data:
            return b""

        result = bytearray()
        i = 0
        n = len(data)

        while i < n:
            # Check for a run of identical bytes
            run_byte = data[i]
            run_len = 1
            while i + run_len < n and run_len < 129 and data[i + run_len] == run_byte:
                run_len += 1

            if run_len >= 2:
                # Emit repeat run
                result.append(0x80 + run_len - 2)
                result.append(run_byte)
                i += run_len
            else:
                # Collect literal run
                lit_start = i
                lit_len = 0
                while i + lit_len < n and lit_len < 128:
                    # Check if next position starts a worthwhile run
                    if i + lit_len + 1 < n and data[i + lit_len] == data[i + lit_len + 1]:
                        # Check if run is at least 3 — worth breaking literal
                        peek = 2
                        while (i + lit_len + peek < n and peek < 4 and
                               data[i + lit_len + peek] == data[i + lit_len]):
                            peek += 1
                        if peek >= 3:
                            break
                    lit_len += 1

                if lit_len == 0:
                    lit_len = 1  # safety

                result.append(lit_len - 1)
                result.extend(data[lit_start:lit_start + lit_len])
                i += lit_len

        return bytes(result)

    @staticmethod
    def _rle_decode(data: bytes, output_size: int) -> bytearray:
        """Decode RLE data back to raw bytes (for verification)."""
        result = bytearray()
        i = 0

        while i < len(data) and len(result) < output_size:
            ctrl = data[i]
            i += 1

            if ctrl >= 0x80:
                # Repeat run
                count = ctrl - 0x80 + 2
                if i < len(data):
                    val = data[i]
                    i += 1
                    result.extend(bytes([val]) * count)
            else:
                # Literal run
                count = ctrl + 1
                result.extend(data[i:i + count])
                i += count

        return result[:output_size]

    def verify_frame(self, compressed: CompressedFrame, original: bytearray,
                     prev_frame: bytearray | None = None) -> bool:
        """Verify that a compressed frame decodes correctly."""
        is_key = compressed.data[0] & 0x80
        rle_data = compressed.data[1:]
        decoded = self._rle_decode(rle_data, self.frame_bytes)

        if is_key:
            return decoded == original
        else:
            # Intra-frame delta: decode delta then compare
            reconstructed = self._intra_delta_decode(decoded)
            return reconstructed == original

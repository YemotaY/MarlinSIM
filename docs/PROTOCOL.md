# MarlinSIM Protocol Specification

## Overview

MarlinSIM uses specially formatted G-code comments to embed animation frame
data. This document specifies the exact format of these comments.

## Design Goals

1. **G-code compatible**: All data is in comments — ignored by non-MarlinSIM firmware
2. **Streamable**: Firmware reads one line at a time, never needs to seek
3. **Low RAM**: Decodable with < 400 bytes of RAM
4. **Compact**: RLE + delta compression keeps frame data small

## Comment Format

All MarlinSIM data lines begin with `; MSIM:` followed by a type character.

### Header — `; MSIM:H:WWWW:HHHH:FFFF`

Placed at the top of the G-code file. Tells the firmware what to expect.

| Field  | Type     | Description                    |
|--------|----------|--------------------------------|
| `WWWW` | 4 hex    | Display width in pixels        |
| `HHHH` | 4 hex    | Display height in pixels       |
| `FFFF` | 4 hex    | Total number of frames         |

Example: `; MSIM:H:0080:0040:00C8` → 128×64 pixels, 200 frames

### Keyframe — `; MSIM:K:NNNN:HEXDATA`

A full frame (not delta-encoded). Used as reference for subsequent delta frames.

| Field     | Type     | Description                    |
|-----------|----------|--------------------------------|
| `NNNN`    | 4 hex    | Frame index (0-based)          |
| `HEXDATA` | hex str  | Compressed frame data          |

### Delta Frame — `; MSIM:F:NNNN:HEXDATA`

A delta frame — XOR difference from the previous frame.

Same fields as keyframe, but data is XOR-delta encoded.

### Continuation — `; MSIM:C:HEXDATA`

Continuation of a frame whose data exceeds one line.

| Field     | Type     | Description                    |
|-----------|----------|--------------------------------|
| `HEXDATA` | hex str  | Continuation of previous frame |

### End Marker — `; MSIM:E`

Marks the end of MarlinSIM data (placed at end of file).

## Compressed Data Format

### Byte 0: Frame Header

| Bit  | Meaning                |
|------|------------------------|
| 7    | 1 = Keyframe, 0 = Delta |
| 6-0  | Reserved (0)           |

### Bytes 1+: RLE Encoded Data

The RLE scheme is a simplified PackBits variant:

| Control Byte   | Meaning                                         |
|----------------|-------------------------------------------------|
| `0x00-0x7F`    | Literal run: next (N+1) bytes are literal data  |
| `0x80-0xFF`    | Repeat run: next byte is repeated (N-0x80+2) times |

### Delta Encoding

For delta frames (type `F`), the RLE-decoded data is XOR'd with the
previous frame to reconstruct the current frame.

### Pixel Layout

Pixels are packed MSB-first, row-major:
- Byte 0, bit 7 = pixel (0,0) — top-left
- Byte 0, bit 6 = pixel (1,0)
- ...
- Byte 0, bit 0 = pixel (7,0)
- Byte 1, bit 7 = pixel (8,0)
- etc.

Row stride = ceil(width / 8) bytes.

## Example

```gcode
; MarlinSIM Animation Data
; MSIM:H:0080:0040:0003
;
; --- Layer 1 ---
G28                          ; Home
G1 Z0.3 F1000               ; First layer height
; MSIM:K:0000:80FF00FF00FF00FF00FF00FF00FF00FF00
G1 X10 Y10 E1.0 F1500
;
; --- Layer 2 ---
G1 Z0.6
; MSIM:F:0001:0003020100
G1 X20 Y20 E2.0 F1500
;
; --- Layer 3 ---
G1 Z0.9
; MSIM:F:0002:0005030201FF00
G1 X30 Y30 E3.0 F1500
;
; MSIM:E
```

## Size Estimates

For a 128×64 monochrome display:
- Raw frame: 1024 bytes (128×64/8)
- Typical keyframe (RLE): 40-120 bytes
- Typical delta frame (RLE): 10-60 bytes
- 200 frames ≈ 4-12 KB added to G-code
- As hex in comments: 8-24 KB added to G-code

This is negligible compared to typical G-code files (10-100 MB).

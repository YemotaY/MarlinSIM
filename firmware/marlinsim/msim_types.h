/**
 * MarlinSIM Firmware Module — Shared Type Definitions
 *
 * Minimal type definitions shared between decoder, parser, and renderer.
 * Zero RAM overhead — these are all compile-time constructs.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include <stdint.h>
#include <stddef.h>

#include "msim_config.h"

#ifdef MARLINSIM_ENABLED

/**
 * Frame type flags — matches the header byte from Part A compressor
 */
enum MsimFrameType : uint8_t {
  MSIM_FRAME_DELTA    = 0x00,  // Delta frame (XOR with previous)
  MSIM_FRAME_KEYFRAME = 0x80,  // Full keyframe
};

/**
 * Parser state machine states
 */
enum MsimParseState : uint8_t {
  MSIM_PARSE_IDLE,        // Not inside an MSIM comment
  MSIM_PARSE_HEADER,      // Parsing MSIM:H header
  MSIM_PARSE_FRAME,       // Parsing MSIM:F or MSIM:K frame data
  MSIM_PARSE_CONTINUE,    // Parsing MSIM:C continuation data
  MSIM_PARSE_DONE,        // MSIM:E end marker seen
};

/**
 * Decoder state machine states
 */
enum MsimDecodeState : uint8_t {
  MSIM_DEC_IDLE,          // No data to decode
  MSIM_DEC_HEADER,        // Reading frame header byte
  MSIM_DEC_RLE_CTRL,      // Reading RLE control byte
  MSIM_DEC_RLE_REPEAT,    // In a repeat run
  MSIM_DEC_RLE_LITERAL,   // In a literal run
  MSIM_DEC_COMPLETE,      // Frame fully decoded
};

/**
 * Minimal ring/linear buffer for passing hex-decoded bytes
 * from parser to decoder without extra copies.
 */
struct MsimByteBuffer {
  uint8_t  data[MSIM_DECODE_BUF_SIZE];
  uint8_t  head;   // read position
  uint8_t  count;  // number of valid bytes

  void reset() { head = 0; count = 0; }

  bool empty() const { return count == 0; }
  bool full() const { return count >= MSIM_DECODE_BUF_SIZE; }

  uint8_t available() const { return count; }

  bool push(uint8_t b) {
    if (full()) return false;
    uint8_t pos = (head + count) % MSIM_DECODE_BUF_SIZE;
    data[pos] = b;
    count++;
    return true;
  }

  uint8_t pop() {
    if (empty()) return 0;
    uint8_t b = data[head];
    head = (head + 1) % MSIM_DECODE_BUF_SIZE;
    count--;
    return b;
  }

  uint8_t peek() const {
    if (empty()) return 0;
    return data[head];
  }
};

/**
 * Animation display state — the master state tracked by the main module
 */
struct MsimState {
  uint16_t display_width;     // From MSIM:H header
  uint16_t display_height;    // From MSIM:H header
  uint16_t total_frames;      // From MSIM:H header
  uint16_t current_frame;     // Currently displayed frame index
  uint8_t  progress_pct;      // 0-100 print progress
  bool     active;            // Animation is active
  bool     header_received;   // MSIM:H has been parsed
  bool     frame_ready;       // A new frame has been decoded and is ready
};

#endif // MARLINSIM_ENABLED

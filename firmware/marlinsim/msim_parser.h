/**
 * MarlinSIM Firmware Module — G-code Comment Parser
 *
 * Scans G-code comment lines for MSIM: prefixed data and extracts
 * hex-encoded frame data. Operates character-by-character to avoid
 * buffering entire comment lines.
 *
 * RAM usage: ~64 bytes (parse buffer) + state variables
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include "msim_types.h"

#ifdef MARLINSIM_ENABLED

class MsimParser {
public:
  /**
   * Initialize the parser state.
   */
  void init();

  /**
   * Process a single character from the G-code stream.
   * Call this from the G-code comment handler in Marlin.
   *
   * @param c  Character to process
   * @return true if a complete frame data chunk is available
   */
  bool feed(char c);

  /**
   * Called when end-of-line is reached.
   * Finalizes any pending parse state.
   *
   * @return true if data was finalized
   */
  bool end_of_line();

  /**
   * Get the byte buffer with decoded hex data.
   * Valid after feed() returns true or after end_of_line().
   */
  MsimByteBuffer& get_buffer() { return _buf; }

  /**
   * Get current parse state.
   */
  MsimParseState get_state() const { return _state; }

  /**
   * Get parsed header info (valid after MSIM:H is parsed).
   */
  uint16_t get_header_width() const  { return _hdr_width; }
  uint16_t get_header_height() const { return _hdr_height; }
  uint16_t get_header_frames() const { return _hdr_frames; }

  /**
   * Get current frame index being parsed.
   */
  uint16_t get_frame_index() const { return _frame_idx; }

  /**
   * Is current frame a keyframe?
   */
  bool is_keyframe() const { return _is_keyframe; }

  /**
   * Reset parser to idle state (e.g., on print cancel).
   */
  void reset();

private:
  MsimParseState _state;
  MsimByteBuffer _buf;

  // Parse position tracking
  uint8_t _match_pos;          // Position in prefix matching
  uint8_t _field_pos;          // Position within current field
  uint8_t _field_idx;          // Which field we're parsing (0,1,2,...)
  uint8_t _hex_nibble;         // Buffered high nibble for hex decode
  bool    _has_nibble;         // True if _hex_nibble holds a valid nibble

  // Parsed data
  uint16_t _hdr_width;
  uint16_t _hdr_height;
  uint16_t _hdr_frames;
  uint16_t _frame_idx;
  bool     _is_keyframe;

  // Internal helpers
  uint8_t _hex_val(char c) const;
  bool    _is_hex(char c) const;
  void    _start_prefix_match();
  void    _parse_type_char(char c);
  void    _parse_hex_data(char c);
  void    _parse_header_field(char c);
};

#endif // MARLINSIM_ENABLED

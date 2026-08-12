/**
 * MarlinSIM Firmware Module — G-code Comment Parser Implementation
 *
 * Parses MSIM: prefixed comments character by character.
 * Format: ; MSIM:T:FIELDS:HEXDATA
 *   T = H (header), F (delta frame), K (keyframe), C (continuation), E (end)
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "msim_parser.h"

#ifdef MARLINSIM_ENABLED

// The prefix we're looking for (after the ';' and optional space)
// "MSIM:" = 5 chars
static const char MSIM_PREFIX[] = "MSIM:";
static const uint8_t MSIM_PREFIX_LEN = 5;

void MsimParser::init() {
  reset();
}

void MsimParser::reset() {
  _state = MSIM_PARSE_IDLE;
  _buf.reset();
  _match_pos = 0;
  _field_pos = 0;
  _field_idx = 0;
  _hex_nibble = 0;
  _has_nibble = false;
  _hdr_width = 0;
  _hdr_height = 0;
  _hdr_frames = 0;
  _frame_idx = 0;
  _is_keyframe = false;
}

bool MsimParser::feed(char c) {
  switch (_state) {
    case MSIM_PARSE_IDLE:
      // Skip leading whitespace and semicolons (only before prefix starts)
      if (_match_pos == 0 && (c == ';' || c == ' ' || c == '\t')) {
        return false;
      }
      // Try to match "MSIM:" prefix
      if (_match_pos < MSIM_PREFIX_LEN) {
        if (c == MSIM_PREFIX[_match_pos]) {
          _match_pos++;
          if (_match_pos == MSIM_PREFIX_LEN) {
            // Prefix matched — next char is the type
            _field_pos = 0;
            _field_idx = 0;
            // Stay in IDLE, next char will be type
          }
        } else {
          // Not our comment — stop trying to match on this line
          // Set match_pos to PREFIX_LEN+1 as sentinel to skip rest of line
          _match_pos = MSIM_PREFIX_LEN + 1;
        }
        return false;
      }
      // If we previously failed matching, skip everything
      if (_match_pos > MSIM_PREFIX_LEN) {
        return false;
      }
      // We've matched the prefix, this char is the type indicator
      _parse_type_char(c);
      return false;

    case MSIM_PARSE_HEADER:
      if (c == ':') {
        _field_idx++;
        _field_pos = 0;
        return false;
      }
      _parse_header_field(c);
      return false;

    case MSIM_PARSE_FRAME:
    case MSIM_PARSE_CONTINUE:
      if (c == ':') {
        // Field separator — skip frame index field, go to hex data
        _field_idx++;
        _field_pos = 0;
        _has_nibble = false;
        return false;
      }
      if (_field_idx >= 1 && _state == MSIM_PARSE_FRAME) {
        // We're in the hex data portion of a frame line
        _parse_hex_data(c);
      } else if (_state == MSIM_PARSE_CONTINUE) {
        // Continuation lines: hex data starts immediately after "C:"
        _parse_hex_data(c);
      } else {
        // Still parsing frame index
        _field_pos++;
      }
      return false;

    case MSIM_PARSE_DONE:
      return false;

    default:
      return false;
  }
}

bool MsimParser::end_of_line() {
  bool had_data = false;

  switch (_state) {
    case MSIM_PARSE_HEADER:
      // Header fully parsed
      MSIM_LOG("Header parsed");
      had_data = true;
      break;

    case MSIM_PARSE_FRAME:
    case MSIM_PARSE_CONTINUE:
      // Frame data line complete — data in buffer is ready for decoder
      had_data = (_buf.count > 0);
      break;

    default:
      break;
  }

  // Reset to idle for next line
  _state = MSIM_PARSE_IDLE;
  _match_pos = 0;
  _field_pos = 0;
  _field_idx = 0;
  _has_nibble = false;

  return had_data;
}

void MsimParser::_parse_type_char(char c) {
  // After the type char, a ':' separator follows before the first data field.
  // By setting _field_idx to 255 here, the first ':' will increment it to 0
  // which represents the first actual data field.
  switch (c) {
    case 'H': case 'h':
      _state = MSIM_PARSE_HEADER;
      _field_idx = 255; // first ':' → 0 (width field)
      _field_pos = 0;
      _hdr_width = 0;
      _hdr_height = 0;
      _hdr_frames = 0;
      break;

    case 'F': case 'f':
      _state = MSIM_PARSE_FRAME;
      _field_idx = 255; // first ':' → 0 (frame index field)
      _field_pos = 0;
      _frame_idx = 0;
      _is_keyframe = false;
      _buf.reset();
      _has_nibble = false;
      break;

    case 'K': case 'k':
      _state = MSIM_PARSE_FRAME;
      _field_idx = 255; // first ':' → 0 (frame index field)
      _field_pos = 0;
      _frame_idx = 0;
      _is_keyframe = true;
      _buf.reset();
      _has_nibble = false;
      break;

    case 'C': case 'c':
      _state = MSIM_PARSE_CONTINUE;
      _field_idx = 0; // continuation: hex data starts after ':'
      _field_pos = 0;
      // Don't reset buffer — continuation appends
      _has_nibble = false;
      break;

    case 'E': case 'e':
      _state = MSIM_PARSE_DONE;
      break;

    default:
      // Not a recognized type — back to idle
      _state = MSIM_PARSE_IDLE;
      _match_pos = 0;
      break;
  }
}

void MsimParser::_parse_header_field(char c) {
  if (!_is_hex(c)) return;

  uint8_t val = _hex_val(c);

  // Header format: WWWW:HHHH:FFFF (3 fields of 4 hex chars each)
  switch (_field_idx) {
    case 0: // Width
      _hdr_width = (_hdr_width << 4) | val;
      break;
    case 1: // Height
      _hdr_height = (_hdr_height << 4) | val;
      break;
    case 2: // Total frames
      _hdr_frames = (_hdr_frames << 4) | val;
      break;
  }
  _field_pos++;
}

void MsimParser::_parse_hex_data(char c) {
  if (!_is_hex(c)) return;

  uint8_t val = _hex_val(c);

  if (!_has_nibble) {
    // High nibble
    _hex_nibble = val << 4;
    _has_nibble = true;
  } else {
    // Low nibble — push complete byte to buffer
    uint8_t byte = _hex_nibble | val;
    _buf.push(byte);
    _has_nibble = false;
  }
}

uint8_t MsimParser::_hex_val(char c) const {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return 0;
}

bool MsimParser::_is_hex(char c) const {
  return (c >= '0' && c <= '9') ||
         (c >= 'A' && c <= 'F') ||
         (c >= 'a' && c <= 'f');
}

#endif // MARLINSIM_ENABLED

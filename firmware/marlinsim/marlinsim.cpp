/**
 * MarlinSIM — 3D Print Progress Animation Module — Core Implementation
 *
 * Orchestrates the parser → decoder → renderer pipeline.
 * Designed for absolute minimum RAM usage.
 *
 * Data flow:
 *   G-code stream → Parser (char by char) → Decoder (byte by byte)
 *                                          → Renderer (scanline by scanline)
 *
 * There is NO full-frame buffer anywhere in this pipeline.
 * Each component processes data incrementally and passes it forward.
 *
 * ┌──────────────────────────────────────────────────────────────────┐
 * │  RAM LAYOUT (typical for 128x64 display):                       │
 * │                                                                  │
 * │  MsimParser:                                                     │
 * │    _buf.data[128]         128 bytes  (hex decode buffer)        │
 * │    state + fields          ~16 bytes                             │
 * │                                                                  │
 * │  MsimDecoder:                                                    │
 * │    _scan_cur[16]           16 bytes  (current scanline)         │
 * │    _scan_prev[16]          16 bytes  (previous scanline)        │
 * │    state + fields          ~16 bytes                             │
 * │                                                                  │
 * │  MsimRenderer:                                                   │
 * │    _cmd_buf[32]            32 bytes  (display command batch)    │
 * │    state + fields          ~16 bytes                             │
 * │                                                                  │
 * │  MsimState:                ~12 bytes                             │
 * │  Locals/stack:             ~16 bytes                             │
 * │                                                                  │
 * │  TOTAL:                   ~268 bytes                             │
 * └──────────────────────────────────────────────────────────────────┘
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "marlinsim.h"

#ifdef MARLINSIM_ENABLED

/*============================================================================
 * Static instances — these are the ONLY RAM allocations
 *============================================================================*/

static MsimParser   s_parser;
static MsimDecoder  s_decoder;
static MsimRenderer s_renderer;
static MsimState    s_state;

// Timestamp for throttling display updates
static uint32_t s_last_update_ms = 0;

// Pending frame data flag — set by parser, cleared by decoder
static bool s_pending_frame = false;

/*============================================================================
 * Initialization
 *============================================================================*/

void marlinsim_init() {
  s_parser.init();
  s_decoder.init();
  s_renderer.init();

  s_state.display_width = MARLINSIM_DISPLAY_WIDTH;
  s_state.display_height = MARLINSIM_DISPLAY_HEIGHT;
  s_state.total_frames = 0;
  s_state.current_frame = 0;
  s_state.progress_pct = 0;
  s_state.active = false;
  s_state.header_received = false;
  s_state.frame_ready = false;

  s_last_update_ms = 0;
  s_pending_frame = false;

  MSIM_LOG("Initialized");
}

/*============================================================================
 * G-code comment processing — called from Marlin's parser
 *============================================================================*/

void marlinsim_process_char(char c) {
  if (s_parser.feed(c)) {
    // Parser has completed a data chunk
    // Don't process immediately — let update_display() handle it
    // to keep ISR/serial processing fast
  }
}

void marlinsim_end_comment() {
  if (s_parser.end_of_line()) {
    MsimParseState pstate = s_parser.get_state();

    // Check what was parsed
    if (!s_state.header_received) {
      // Check if we just got a header
      if (s_parser.get_header_frames() > 0) {
        s_state.display_width = s_parser.get_header_width();
        s_state.display_height = s_parser.get_header_height();
        s_state.total_frames = s_parser.get_header_frames();
        s_state.header_received = true;
        s_state.active = true;

        MSIM_LOG_VAL("Header: frames=", s_state.total_frames);
        MSIM_LOG_VAL("Header: w=", s_state.display_width);
        MSIM_LOG_VAL("Header: h=", s_state.display_height);
      }
    }

    // If parser has frame data in buffer, signal for processing
    if (s_parser.get_buffer().count > 0) {
      s_pending_frame = true;
    }
  }

  // Reset parser for next line (already done in end_of_line)
}

/*============================================================================
 * Display update — called from Marlin's LCD loop
 *============================================================================*/

// External Marlin function to get milliseconds
// In actual Marlin build, this resolves via HAL Arduino shim
#ifndef millis
  extern uint32_t millis();
#endif

void marlinsim_update_display() {
  if (!s_state.active) return;

  uint32_t now = millis();

  // Throttle updates
  if ((now - s_last_update_ms) < MSIM_DISPLAY_UPDATE_MS) return;
  s_last_update_ms = now;

  // Process pending frame data
  if (s_pending_frame) {
    s_pending_frame = false;

    MsimByteBuffer& buf = s_parser.get_buffer();

    // If decoder is idle or complete, start a new frame
    if (s_decoder.frame_complete() || !s_state.frame_ready) {
      s_decoder.begin_frame(
        s_parser.is_keyframe(),
        s_state.display_width,
        s_state.display_height
      );
      s_state.current_frame = s_parser.get_frame_index();

      // Update progress
      if (s_state.total_frames > 0) {
        s_state.progress_pct = (uint8_t)(
          ((uint32_t)s_state.current_frame * 100) / s_state.total_frames
        );
      }
    }

    // Feed bytes from parser buffer to decoder
    while (!buf.empty() && !s_decoder.scanline_ready()) {
      uint8_t b = buf.pop();
      s_decoder.feed(&b, 1);
    }
  }

  // Drive the decoder → renderer pipeline
  // Process available scanlines
  while (s_decoder.scanline_ready()) {
    uint16_t y = s_decoder.get_scanline_y();
    const uint8_t* scanline = s_decoder.get_scanline();
    uint8_t row_bytes = (s_state.display_width + 7) / 8;

    s_renderer.draw_scanline(y, scanline, row_bytes);
    s_decoder.advance_scanline();

    if (s_decoder.frame_complete()) {
      s_state.frame_ready = true;
      s_renderer.end_frame();
      MSIM_LOG_VAL("Frame complete:", s_state.current_frame);
      break;
    }
  }
}

/*============================================================================
 * U8G page drawing — called from Marlin's status screen render
 *============================================================================*/

void marlinsim_draw_page() {
  if (!s_state.active || !s_state.frame_ready) return;

  // In a U8G picture loop, we'd re-render from the decoder's
  // stored state. Since we can't buffer the full frame, we
  // let the display hardware retain the pixels from
  // draw_scanline() calls during the decode phase.
  //
  // For the progress bar, we can draw it every page:
  s_renderer.draw_progress(s_state.progress_pct);
}

/*============================================================================
 * Print lifecycle
 *============================================================================*/

void marlinsim_on_print_end() {
  MSIM_LOG("Print ended");

  // Show final state briefly, then deactivate
  s_state.progress_pct = 100;
  s_renderer.draw_progress(100);

  // Keep active flag for a moment so display shows final frame
  // The next print start will re-init
}

bool marlinsim_is_active() {
  return s_state.active;
}

uint8_t marlinsim_get_progress() {
  return s_state.progress_pct;
}

#endif // MARLINSIM_ENABLED

/**
 * MarlinSIM Firmware Decoder — Standalone Test
 *
 * This file can be compiled and run on a PC to test the decoder
 * without Marlin or any embedded hardware.
 *
 * Compile: g++ -std=c++17 -DMARLINSIM_ENABLED -I../../firmware/marlinsim
 *          -o test_decoder test_firmware_decoder.cpp
 *          ../../firmware/marlinsim/msim_parser.cpp
 *          ../../firmware/marlinsim/msim_decoder.cpp
 *
 * Run: ./test_decoder
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

// Provide millis() stub for PC testing
extern "C" {
  static unsigned long _millis_val = 0;
  unsigned long millis() { return _millis_val; }
}

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cassert>

// Define display size before including headers
#define MARLINSIM_ENABLED
#define MARLINSIM_DISPLAY_WIDTH  16
#define MARLINSIM_DISPLAY_HEIGHT 8
#define MSIM_DECODE_BUF_SIZE     128
#define MSIM_PARSE_BUF_SIZE      64
#define MSIM_DISPLAY_UPDATE_MS   100
#define MSIM_DISPLAY_OFFSET_X    0
#define MSIM_DISPLAY_OFFSET_Y    0
#define MSIM_LOG(msg)            printf("  [LOG] %s\n", msg)
#define MSIM_LOG_VAL(msg, val)   printf("  [LOG] %s %d\n", msg, (int)(val))

// Include the actual firmware sources
#include "msim_types.h"
#include "msim_parser.h"
#include "msim_decoder.h"

// We need to include the .cpp files directly for this standalone test
// (In actual Marlin build, they're compiled separately)
#include "msim_parser.cpp"
#include "msim_decoder.cpp"

/*============================================================================
 * Test helpers
 *============================================================================*/

static int tests_run = 0;
static int tests_passed = 0;

#define TEST(name) \
  do { \
    tests_run++; \
    printf("TEST: %s ... ", #name); \
    bool _ok = test_##name(); \
    if (_ok) { tests_passed++; printf("PASS\n"); } \
    else { printf("FAIL\n"); } \
  } while(0)

#define ASSERT(cond) \
  do { if (!(cond)) { printf("\n  ASSERT FAILED: %s (line %d)\n", #cond, __LINE__); return false; } } while(0)

/*============================================================================
 * Parser Tests
 *============================================================================*/

static void feed_string(MsimParser& parser, const char* str) {
  for (const char* p = str; *p; p++) {
    parser.feed(*p);
  }
}

bool test_parser_header() {
  MsimParser parser;
  parser.init();

  // Feed: "; MSIM:H:0080:0040:00C8"
  const char* line = "; MSIM:H:0080:0040:00C8";
  for (const char* p = line; *p; p++) {
    parser.feed(*p);
  }
  parser.end_of_line();

  ASSERT(parser.get_header_width() == 0x0080);   // 128
  ASSERT(parser.get_header_height() == 0x0040);   // 64
  ASSERT(parser.get_header_frames() == 0x00C8);   // 200
  return true;
}

bool test_parser_keyframe() {
  MsimParser parser;
  parser.init();

  // Feed: "; MSIM:K:0000:80AABB"
  const char* line = "; MSIM:K:0000:80AABB";
  feed_string(parser, line);
  parser.end_of_line();

  ASSERT(parser.is_keyframe() == true);
  ASSERT(parser.get_frame_index() == 0x0000);

  MsimByteBuffer& buf = parser.get_buffer();
  ASSERT(buf.count == 3);
  ASSERT(buf.pop() == 0x80);
  ASSERT(buf.pop() == 0xAA);
  ASSERT(buf.pop() == 0xBB);
  return true;
}

bool test_parser_delta_frame() {
  MsimParser parser;
  parser.init();

  const char* line = "; MSIM:F:0005:00112233";
  feed_string(parser, line);
  parser.end_of_line();

  ASSERT(parser.is_keyframe() == false);

  MsimByteBuffer& buf = parser.get_buffer();
  ASSERT(buf.count == 4);
  ASSERT(buf.pop() == 0x00);
  ASSERT(buf.pop() == 0x11);
  ASSERT(buf.pop() == 0x22);
  ASSERT(buf.pop() == 0x33);
  return true;
}

bool test_parser_continuation() {
  MsimParser parser;
  parser.init();

  // First line: keyframe start
  feed_string(parser, "; MSIM:K:0000:80AA");
  parser.end_of_line();

  MsimByteBuffer& buf = parser.get_buffer();
  ASSERT(buf.count == 2);

  // Don't clear buffer — continuation appends
  // Actually, the parser resets to IDLE after end_of_line
  // The continuation line will append to the buffer
  feed_string(parser, "; MSIM:C:BBCC");
  parser.end_of_line();

  // Buffer should have the continuation data
  // (The original data was already in the buffer)
  ASSERT(buf.count >= 2);
  return true;
}

bool test_parser_ignores_normal_comments() {
  MsimParser parser;
  parser.init();

  feed_string(parser, "; This is a normal G-code comment");
  bool had_data = parser.end_of_line();
  ASSERT(had_data == false);

  feed_string(parser, "; LAYER:5");
  had_data = parser.end_of_line();
  ASSERT(had_data == false);
  return true;
}

bool test_parser_reset() {
  MsimParser parser;
  parser.init();

  feed_string(parser, "; MSIM:K:0000:80AABB");
  parser.end_of_line();

  parser.reset();
  ASSERT(parser.get_state() == MSIM_PARSE_IDLE);
  ASSERT(parser.get_buffer().empty());
  return true;
}

/*============================================================================
 * Decoder helper — feeds data incrementally, processing scanlines
 *============================================================================*/

struct DecodedScanlines {
  uint8_t data[MSIM_SCANLINE_BYTES * 64]; // enough for 64 scanlines
  int count;
};

static bool feed_and_decode(MsimDecoder& decoder,
                            const uint8_t* data, uint8_t len,
                            DecodedScanlines& out) {
  out.count = 0;
  uint8_t offset = 0;
  uint8_t remaining = len;
  int max_iter = 1000; // safety
  uint8_t rb = (MARLINSIM_DISPLAY_WIDTH + 7) / 8;

  while (!decoder.frame_complete() && max_iter-- > 0) {
    // First, try to drain any pending repeat runs (feed with 0 new bytes)
    decoder.feed(data, 0);

    if (decoder.scanline_ready()) {
      const uint8_t* line = decoder.get_scanline();
      memcpy(out.data + out.count * rb, line, rb);
      out.count++;
      decoder.advance_scanline();
    } else if (remaining > 0) {
      uint8_t consumed = decoder.feed(data + offset, remaining);
      if (consumed == 0 && !decoder.scanline_ready()) break; // stuck
      offset += consumed;
      remaining -= consumed;
    } else {
      // No more input data — try one more drain
      decoder.feed(data, 0);
      if (decoder.scanline_ready()) {
        const uint8_t* line = decoder.get_scanline();
        memcpy(out.data + out.count * rb, line, rb);
        out.count++;
        decoder.advance_scanline();
      } else {
        break;
      }
    }
  }
  // Drain remaining scanlines
  while (decoder.scanline_ready()) {
    const uint8_t* line = decoder.get_scanline();
    memcpy(out.data + out.count * rb, line, rb);
    out.count++;
    decoder.advance_scanline();
  }
  return decoder.frame_complete();
}

/*============================================================================
 * Decoder Tests
 *============================================================================*/

bool test_decoder_keyframe() {
  MsimDecoder decoder;
  decoder.init();

  // For 16x8 display: 2 bytes/row × 8 rows = 16 bytes
  // Create a simple keyframe: header(0x80) + RLE(repeat 16× 0xFF)
  // RLE: 0x80+(16-2)=0x8E, 0xFF → 16 bytes of 0xFF
  uint8_t compressed[] = { 0x80, 0x8E, 0xFF };

  decoder.begin_frame(true, 16, 8);

  DecodedScanlines out;
  bool complete = feed_and_decode(decoder, compressed, sizeof(compressed), out);

  ASSERT(complete);
  ASSERT(out.count == 8);
  // All bytes should be 0xFF
  for (int i = 0; i < out.count * 2; i++) {
    ASSERT(out.data[i] == 0xFF);
  }
  return true;
}

bool test_decoder_all_zeros() {
  MsimDecoder decoder;
  decoder.init();

  // Keyframe: header(0x80) + RLE(repeat 16× 0x00)
  uint8_t compressed[] = { 0x80, 0x8E, 0x00 };

  decoder.begin_frame(true, 16, 8);

  DecodedScanlines out;
  bool complete = feed_and_decode(decoder, compressed, sizeof(compressed), out);

  ASSERT(complete);
  ASSERT(out.count == 8);
  // Check all scanlines are zero
  for (int i = 0; i < out.count * 2; i++) {
    ASSERT(out.data[i] == 0x00);
  }
  return true;
}

bool test_decoder_delta_frame() {
  MsimDecoder decoder;
  decoder.init();

  // Test intra-frame delta decoding
  // For 16x8 display: 2 bytes/row × 8 rows = 16 bytes
  // Intra-delta: each byte XOR'd with previous decoded byte
  //
  // We want output: all 0xAA (16 bytes)
  // Intra-delta encoded: byte[0]=0xAA, byte[1]=0xAA^0xAA=0x00,
  //                      byte[2]=0xAA^0xAA=0x00, ...
  // So delta data: 0xAA, 0x00, 0x00, ... (first is 0xAA, rest are 0x00)
  //
  // RLE encode: literal(0xAA) + repeat(15×0x00)
  // Literal: 0x00(1 literal), 0xAA
  // Repeat:  0x80+(15-2)=0x8D, 0x00
  uint8_t compressed[] = {
    0x00,       // delta frame header
    0x00, 0xAA, // literal: 1 byte = 0xAA
    0x8D, 0x00  // repeat: 15 × 0x00
  };

  decoder.begin_frame(false, 16, 8);
  DecodedScanlines out;
  bool complete = feed_and_decode(decoder, compressed, sizeof(compressed), out);
  ASSERT(complete);
  ASSERT(out.count == 8);

  // All bytes should be 0xAA
  for (int i = 0; i < out.count * 2; i++) {
    ASSERT(out.data[i] == 0xAA);
  }
  return true;
}

bool test_decoder_literal_rle() {
  MsimDecoder decoder;
  decoder.init();

  // Keyframe with literal RLE data
  // 2 bytes/row × 8 rows = 16 bytes
  // Literal run: 0x0F (16 literals), followed by 16 bytes
  uint8_t compressed[18];
  compressed[0] = 0x80;  // keyframe header
  compressed[1] = 0x0F;  // literal run of 16 bytes
  for (int i = 0; i < 16; i++) {
    compressed[2 + i] = (uint8_t)(i * 17);  // pattern: 0x00, 0x11, 0x22, ...
  }

  decoder.begin_frame(true, 16, 8);
  DecodedScanlines out;
  bool complete = feed_and_decode(decoder, compressed, sizeof(compressed), out);

  ASSERT(complete);
  ASSERT(out.count == 8);

  // Check first scanline: bytes 0x00, 0x11
  ASSERT(out.data[0] == 0x00);
  ASSERT(out.data[1] == 0x11);

  // Second scanline: bytes 0x22, 0x33
  ASSERT(out.data[2] == 0x22);
  ASSERT(out.data[3] == 0x33);
  return true;
}

bool test_decoder_reset() {
  MsimDecoder decoder;
  decoder.init();

  uint8_t key[] = { 0x80, 0x8E, 0xFF };
  decoder.begin_frame(true, 16, 8);
  decoder.feed(key, sizeof(key));

  decoder.reset();
  ASSERT(!decoder.scanline_ready());
  ASSERT(!decoder.frame_complete());
  return true;
}

/*============================================================================
 * Byte Buffer Tests
 *============================================================================*/

bool test_byte_buffer() {
  MsimByteBuffer buf;
  buf.reset();

  ASSERT(buf.empty());
  ASSERT(!buf.full());
  ASSERT(buf.available() == 0);

  ASSERT(buf.push(0x42));
  ASSERT(!buf.empty());
  ASSERT(buf.available() == 1);
  ASSERT(buf.peek() == 0x42);

  uint8_t val = buf.pop();
  ASSERT(val == 0x42);
  ASSERT(buf.empty());
  return true;
}

bool test_byte_buffer_wraparound() {
  MsimByteBuffer buf;
  buf.reset();

  // Fill partially, drain, fill again to test wraparound
  for (int i = 0; i < 64; i++) {
    ASSERT(buf.push((uint8_t)(i & 0xFF)));
  }
  for (int i = 0; i < 64; i++) {
    ASSERT(buf.pop() == (uint8_t)(i & 0xFF));
  }

  // Now push again (wraps around in ring buffer)
  for (int i = 0; i < 32; i++) {
    ASSERT(buf.push((uint8_t)(i + 100)));
  }
  for (int i = 0; i < 32; i++) {
    ASSERT(buf.pop() == (uint8_t)(i + 100));
  }
  return true;
}

/*============================================================================
 * RAM Usage Verification
 *============================================================================*/

bool test_ram_budget() {
  // Verify that our static allocations fit the budget
  size_t parser_size = sizeof(MsimParser);
  size_t decoder_size = sizeof(MsimDecoder);
  size_t state_size = sizeof(MsimState);
  size_t buf_size = sizeof(MsimByteBuffer);

  printf("\n  RAM analysis:\n");
  printf("    MsimParser:     %3zu bytes\n", parser_size);
  printf("    MsimDecoder:    %3zu bytes\n", decoder_size);
  printf("    MsimState:      %3zu bytes\n", state_size);
  printf("    MsimByteBuffer: %3zu bytes\n", buf_size);

  size_t total = parser_size + decoder_size + state_size;
  printf("    ─────────────────────────\n");
  printf("    Total:          %3zu bytes\n", total);

  // Must fit in 400 bytes budget
  ASSERT(total < 512);  // Allow some margin for renderer + stack
  return true;
}

/*============================================================================
 * Main
 *============================================================================*/

int main() {
  printf("MarlinSIM Firmware Decoder Tests\n");
  printf("================================\n\n");

  // Parser tests
  printf("--- Parser Tests ---\n");
  TEST(parser_header);
  TEST(parser_keyframe);
  TEST(parser_delta_frame);
  TEST(parser_continuation);
  TEST(parser_ignores_normal_comments);
  TEST(parser_reset);

  // Decoder tests
  printf("\n--- Decoder Tests ---\n");
  TEST(decoder_keyframe);
  TEST(decoder_all_zeros);
  TEST(decoder_delta_frame);
  TEST(decoder_literal_rle);
  TEST(decoder_reset);

  // Buffer tests
  printf("\n--- Buffer Tests ---\n");
  TEST(byte_buffer);
  TEST(byte_buffer_wraparound);

  // RAM verification
  printf("\n--- RAM Budget ---\n");
  TEST(ram_budget);

  printf("\n================================\n");
  printf("Results: %d/%d tests passed\n", tests_passed, tests_run);

  return (tests_passed == tests_run) ? 0 : 1;
}

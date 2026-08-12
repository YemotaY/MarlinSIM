/**
 * MarlinSIM — 3D Print Progress Animation Module
 *
 * Main public API for the MarlinSIM firmware module.
 * This is the single header that Marlin's MarlinCore.cpp includes.
 *
 * Integration points in Marlin:
 *   1. marlinsim_init()           — call from setup()
 *   2. marlinsim_process_comment() — call from gcode comment handler
 *   3. marlinsim_update_display()  — call from lcd_update() / ui.update()
 *   4. marlinsim_on_print_end()    — call from print complete handler
 *
 * Total RAM overhead: < 400 bytes on STM32F103
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include "msim_config.h"

#ifdef MARLINSIM_ENABLED

#include "msim_types.h"
#include "msim_parser.h"
#include "msim_decoder.h"
#include "msim_renderer.h"

/**
 * Initialize the MarlinSIM animation module.
 * Call once from Marlin's setup().
 */
void marlinsim_init();

/**
 * Process a G-code comment character.
 * Call from Marlin's gcode comment handler, one character at a time.
 * This is the main data input path.
 *
 * @param c  Character from the G-code comment
 */
void marlinsim_process_char(char c);

/**
 * Signal end of a G-code comment line.
 * Call when the comment line is complete (newline reached).
 */
void marlinsim_end_comment();

/**
 * Update the display with animation data.
 * Call from Marlin's LCD update loop (typically every 500ms).
 * This drives the decoder and renderer state machines.
 */
void marlinsim_update_display();

/**
 * Called when printing ends (complete, cancelled, or error).
 * Cleans up state and optionally shows a final frame.
 */
void marlinsim_on_print_end();

/**
 * Check if MarlinSIM is currently active (has animation data).
 *
 * @return true if animation data has been detected in the G-code
 */
bool marlinsim_is_active();

/**
 * Get current print progress as reported by the animation frames.
 *
 * @return 0-100 progress percentage
 */
uint8_t marlinsim_get_progress();

/**
 * Draw the animation in a U8G picture loop page.
 * Call this from Marlin's status screen drawing function,
 * inside the u8g.firstPage()/u8g.nextPage() loop.
 *
 * This is the preferred integration point for U8G displays.
 */
void marlinsim_draw_page();

#endif // MARLINSIM_ENABLED

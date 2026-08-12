/**
 * MarlinSIM Web UI — Client Application
 *
 * Handles:
 *  - WebSocket connection to simulator backend
 *  - LCD framebuffer rendering on <canvas> (1-bit → pixel-scaled)
 *  - Encoder interaction (mouse wheel, click, buttons)
 *  - G-code terminal with command history
 *  - Live printer state display
 *  - Simple 3D wireframe visualization
 */

(function () {
    "use strict";

    // ---- State ----
    let ws = null;
    let displayWidth = 128;
    let displayHeight = 64;
    let lcdScale = 4;
    let commandHistory = [];
    let historyIndex = -1;
    let printerState = {};

    // ---- DOM refs ----
    const connStatus = document.getElementById("conn-status");
    const printerName = document.getElementById("printer-name");
    const marlinVersion = document.getElementById("marlin-version");
    const lcdCanvas = document.getElementById("lcd-canvas");
    const lcdCtx = lcdCanvas.getContext("2d");
    const lcdType = document.getElementById("lcd-type");
    const lcdResolution = document.getElementById("lcd-resolution");
    const gcodeInput = document.getElementById("gcode-input");
    const terminalOutput = document.getElementById("terminal-output");
    const btnSend = document.getElementById("btn-send");
    const btnEncCCW = document.getElementById("btn-enc-ccw");
    const btnEncClick = document.getElementById("btn-enc-click");
    const btnEncCW = document.getElementById("btn-enc-cw");
    const vizCanvas = document.getElementById("viz-canvas");
    const vizCtx = vizCanvas.getContext("2d");

    // ---- WebSocket ----
    function connect() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${location.host}/ws`;
        ws = new WebSocket(url);

        ws.onopen = () => {
            connStatus.textContent = "● Connected";
            connStatus.className = "status-connected";
            appendTerminal("System", "Connected to simulator", "cmd-recv");
        };

        ws.onclose = () => {
            connStatus.textContent = "● Disconnected";
            connStatus.className = "status-disconnected";
            appendTerminal("System", "Disconnected — reconnecting...", "cmd-error");
            setTimeout(connect, 2000);
        };

        ws.onerror = () => {
            connStatus.textContent = "● Error";
            connStatus.className = "status-disconnected";
        };

        ws.onmessage = (evt) => {
            const msg = JSON.parse(evt.data);
            handleMessage(msg);
        };
    }

    function sendWS(msg) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg));
        }
    }

    // ---- Message handler ----
    function handleMessage(msg) {
        switch (msg.type) {
            case "init":
                displayWidth = msg.display.width;
                displayHeight = msg.display.height;
                setupLCD();
                printerName.textContent = msg.printer;
                lcdType.textContent = msg.display.type.toUpperCase();
                lcdResolution.textContent = `${displayWidth}×${displayHeight}`;
                if (msg.state) updateState(msg.state);
                break;

            case "lcd":
                renderLCD(msg.data, msg.width, msg.height);
                break;

            case "state":
                updateState(msg.data);
                break;

            case "gcode_response":
                appendTerminal("TX", msg.command, "cmd-sent");
                for (const line of msg.response) {
                    appendTerminal("RX", line, "cmd-recv");
                }
                break;

            case "gcode_log":
                for (const line of msg.lines) {
                    const cls = line.startsWith(">") ? "cmd-sent" : "cmd-recv";
                    appendTerminal("", line, cls);
                }
                break;
        }
    }

    // ---- LCD Rendering ----
    function setupLCD() {
        lcdCanvas.width = displayWidth * lcdScale;
        lcdCanvas.height = displayHeight * lcdScale;
        lcdCtx.imageSmoothingEnabled = false;

        // Fill with LCD background color
        lcdCtx.fillStyle = "#6b7b3a";
        lcdCtx.fillRect(0, 0, lcdCanvas.width, lcdCanvas.height);
    }

    function renderLCD(base64Data, width, height) {
        const raw = atob(base64Data);
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) {
            bytes[i] = raw.charCodeAt(i);
        }

        const imgData = lcdCtx.createImageData(width * lcdScale, height * lcdScale);
        const pixels = imgData.data;

        // 1-bit packed framebuffer (MSB first, row-major)
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const byteIdx = y * Math.floor(width / 8) + Math.floor(x / 8);
                const bitIdx = 7 - (x % 8);
                const pixel = (bytes[byteIdx] >> bitIdx) & 1;

                // LCD colors: green-ish monochrome
                const r = pixel ? 0x1a : 0x6b;
                const g = pixel ? 0x2a : 0x7b;
                const b = pixel ? 0x0a : 0x3a;

                // Scale up
                for (let sy = 0; sy < lcdScale; sy++) {
                    for (let sx = 0; sx < lcdScale; sx++) {
                        const px = (x * lcdScale + sx);
                        const py = (y * lcdScale + sy);
                        const idx = (py * width * lcdScale + px) * 4;
                        pixels[idx] = r;
                        pixels[idx + 1] = g;
                        pixels[idx + 2] = b;
                        pixels[idx + 3] = 255;
                    }
                }
            }
        }

        lcdCtx.putImageData(imgData, 0, 0);
    }

    // ---- State Updates ----
    function updateState(state) {
        printerState = state;

        if (state.physics) {
            const ph = state.physics;

            // Thermal
            if (ph.thermal) {
                updateThermal("hotend", ph.thermal.hotend);
                updateThermal("bed", ph.thermal.bed);
            }

            // Axes
            if (ph.axes) {
                for (const [name, ax] of Object.entries(ph.axes)) {
                    updateAxis(name.toLowerCase(), ax);
                }
            }
        }

        // 3D visualization
        draw3DView();
    }

    function updateThermal(id, data) {
        if (!data) return;
        const tempEl = document.getElementById(`${id}-temp`);
        const targetEl = document.getElementById(`${id}-target`);
        const pwmEl = document.getElementById(`${id}-pwm`);
        const barEl = document.getElementById(`${id}-bar`);

        if (tempEl) tempEl.textContent = `${data.current.toFixed(1)}°C`;
        if (targetEl) targetEl.textContent = `→ ${data.target.toFixed(0)}°C`;
        if (pwmEl) pwmEl.textContent = `PWM: ${data.pwm}`;

        // Bar width: 0°C = 0%, 300°C = 100%
        if (barEl) {
            const pct = Math.min(100, Math.max(0, (data.current / 300) * 100));
            barEl.style.width = `${pct}%`;
        }
    }

    function updateAxis(id, data) {
        const row = document.getElementById(`axis-${id}`);
        if (!row) return;
        const cells = row.querySelectorAll("td");
        if (cells.length >= 5) {
            cells[1].textContent = data.position_mm.toFixed(3);
            cells[2].textContent = data.position_steps;
            cells[3].textContent = data.homed ? "✓" : "—";
            cells[4].textContent = data.endstop ? "🔴" : "—";
        }
    }

    // ---- 3D Wireframe View ----
    function draw3DView() {
        const w = vizCanvas.width;
        const h = vizCanvas.height;
        vizCtx.fillStyle = "#0a0a1a";
        vizCtx.fillRect(0, 0, w, h);

        // Simple isometric wireframe of the build volume
        const axes = printerState.physics?.axes || {};
        const bx = 220, by = 220, bz = 250; // build volume defaults

        const cx = w / 2, cy = h * 0.75;
        const scale = 0.8;

        function iso(x, y, z) {
            // Isometric projection
            const sx = (x - y) * Math.cos(Math.PI / 6) * scale + cx;
            const sy = -(x + y) * Math.sin(Math.PI / 6) * scale - z * scale + cy;
            return [sx, sy];
        }

        function drawLine(p1, p2, color, width) {
            vizCtx.beginPath();
            vizCtx.moveTo(p1[0], p1[1]);
            vizCtx.lineTo(p2[0], p2[1]);
            vizCtx.strokeStyle = color;
            vizCtx.lineWidth = width || 1;
            vizCtx.stroke();
        }

        // Normalize coordinates to screen
        const s = Math.min(w, h) / 600;

        function p(x, y, z) {
            return iso(x * s, y * s, z * s);
        }

        // Build volume wireframe
        const verts = [
            [0, 0, 0], [bx, 0, 0], [bx, by, 0], [0, by, 0],
            [0, 0, bz], [bx, 0, bz], [bx, by, bz], [0, by, bz],
        ];
        const edges = [
            [0,1],[1,2],[2,3],[3,0], // bottom
            [4,5],[5,6],[6,7],[7,4], // top
            [0,4],[1,5],[2,6],[3,7], // verticals
        ];

        for (const [a, b] of edges) {
            drawLine(p(...verts[a]), p(...verts[b]), "#2a2a4a", 1);
        }

        // Draw current nozzle position
        const nx = (axes.X?.position_mm || 0);
        const ny = (axes.Y?.position_mm || 0);
        const nz = (axes.Z?.position_mm || 0);

        // Nozzle crosshair
        const np = p(nx, ny, nz);
        vizCtx.beginPath();
        vizCtx.arc(np[0], np[1], 5, 0, Math.PI * 2);
        vizCtx.fillStyle = "#ff4444";
        vizCtx.fill();

        // Drop line to bed
        const np0 = p(nx, ny, 0);
        drawLine(np, np0, "#ff444466", 1);

        // Axis labels
        vizCtx.fillStyle = "#ff4444";
        vizCtx.font = "12px monospace";
        const xEnd = p(bx + 20, 0, 0);
        vizCtx.fillText("X", xEnd[0], xEnd[1]);

        vizCtx.fillStyle = "#44ff44";
        const yEnd = p(0, by + 20, 0);
        vizCtx.fillText("Y", yEnd[0], yEnd[1]);

        vizCtx.fillStyle = "#4444ff";
        const zEnd = p(0, 0, bz + 20);
        vizCtx.fillText("Z", zEnd[0], zEnd[1]);

        // Position text
        vizCtx.fillStyle = "#e0e0e0";
        vizCtx.font = "14px monospace";
        vizCtx.fillText(
            `X:${nx.toFixed(1)} Y:${ny.toFixed(1)} Z:${nz.toFixed(1)}`,
            10, 20
        );
    }

    // ---- Terminal ----
    function appendTerminal(prefix, text, cls) {
        const line = document.createElement("div");
        line.className = cls || "";
        line.textContent = prefix ? `[${prefix}] ${text}` : text;
        terminalOutput.appendChild(line);
        terminalOutput.scrollTop = terminalOutput.scrollHeight;

        // Limit lines
        while (terminalOutput.children.length > 500) {
            terminalOutput.removeChild(terminalOutput.firstChild);
        }
    }

    function sendGCode() {
        const cmd = gcodeInput.value.trim();
        if (!cmd) return;

        commandHistory.push(cmd);
        historyIndex = commandHistory.length;

        sendWS({ type: "gcode", command: cmd });
        appendTerminal("TX", cmd, "cmd-sent");
        gcodeInput.value = "";
    }

    // ---- Event Listeners ----

    // G-code input
    gcodeInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            sendGCode();
        } else if (e.key === "ArrowUp") {
            if (historyIndex > 0) {
                historyIndex--;
                gcodeInput.value = commandHistory[historyIndex];
            }
            e.preventDefault();
        } else if (e.key === "ArrowDown") {
            if (historyIndex < commandHistory.length - 1) {
                historyIndex++;
                gcodeInput.value = commandHistory[historyIndex];
            } else {
                historyIndex = commandHistory.length;
                gcodeInput.value = "";
            }
            e.preventDefault();
        }
    });

    btnSend.addEventListener("click", sendGCode);

    // Quick commands
    document.querySelectorAll(".qcmd").forEach((btn) => {
        btn.addEventListener("click", () => {
            const cmd = btn.dataset.cmd;
            sendWS({ type: "gcode", command: cmd });
            appendTerminal("TX", cmd, "cmd-sent");
        });
    });

    // Encoder buttons
    btnEncCCW.addEventListener("click", () => {
        sendWS({ type: "encoder_rotate", clicks: -1 });
    });
    btnEncCW.addEventListener("click", () => {
        sendWS({ type: "encoder_rotate", clicks: 1 });
    });
    btnEncClick.addEventListener("mousedown", () => {
        sendWS({ type: "encoder_click", pressed: true });
    });
    btnEncClick.addEventListener("mouseup", () => {
        sendWS({ type: "encoder_click", pressed: false });
    });

    // Mouse wheel on LCD = encoder rotate
    lcdCanvas.addEventListener("wheel", (e) => {
        e.preventDefault();
        const clicks = e.deltaY > 0 ? 1 : -1;
        sendWS({ type: "encoder_rotate", clicks: clicks });
    });

    // Click on LCD = encoder click
    lcdCanvas.addEventListener("mousedown", (e) => {
        if (e.button === 0) {
            sendWS({ type: "encoder_click", pressed: true });
        }
    });
    lcdCanvas.addEventListener("mouseup", (e) => {
        if (e.button === 0) {
            sendWS({ type: "encoder_click", pressed: false });
        }
    });

    // ---- Init ----
    setupLCD();
    draw3DView();
    connect();

})();

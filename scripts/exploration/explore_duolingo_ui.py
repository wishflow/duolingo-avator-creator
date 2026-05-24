#!/usr/bin/env python3
"""Explore Duolingo avatar editor UI structure."""
import asyncio, json, websockets, base64

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"

async def recv_response(ws, expected_id, timeout=10):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg

async def check():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await recv_response(ws, 1)

        # Find the main avatar canvas and UI elements
        e = """(function() {
            var result = {};

            // Find all large canvases
            var canvases = document.querySelectorAll('canvas');
            var riveCanvases = [];
            for (var i = 0; i < canvases.length; i++) {
                var c = canvases[i];
                if (c.width > 200 || c.height > 200) {
                    riveCanvases.push({
                        index: i,
                        id: c.id || '(none)',
                        size: c.width + 'x' + c.height,
                        className: c.className,
                    });
                }
            }
            result.riveCanvases = riveCanvases;

            // Find tab/category buttons
            var tabElements = document.querySelectorAll('[role="tab"], [data-test~="tab"], button[class*="tab"]');
            var tabs = [];
            for (var i = 0; i < tabElements.length; i++) {
                var t = tabElements[i];
                tabs.push({
                    text: (t.textContent || '').trim(),
                    className: t.className,
                    role: t.getAttribute('role'),
                });
            }
            result.tabs = tabs.slice(0, 20);

            // Find all buttons
            var allButtons = document.querySelectorAll('button');
            var buttons = [];
            for (var i = 0; i < allButtons.length; i++) {
                var b = allButtons[i];
                var text = (b.textContent || '').trim();
                if (text && text.length < 50) {
                    buttons.push(text);
                }
            }
            result.buttons = buttons.slice(0, 30);

            // Find the parent container of avatar canvas
            var parentEl = canvases[0] ? canvases[0].parentElement : null;
            var depth = 0;
            while (parentEl && depth < 10) {
                result['parent_' + depth] = {
                    tag: parentEl.tagName,
                    id: parentEl.id,
                    className: (parentEl.className || '').substring(0, 80),
                };
                parentEl = parentEl.parentElement;
                depth++;
            }

            return JSON.stringify(result, null, 2);
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print( resp.get("result",{}).get("result",{}).get("value","")[:8000])

asyncio.run(check())

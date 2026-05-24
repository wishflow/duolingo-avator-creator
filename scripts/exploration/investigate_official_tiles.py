#!/usr/bin/env python3
"""Investigate how the official Duolingo avatar editor handles tile rendering performance.

Connects to a Chrome DevTools instance that has the official avatar editor page open.
Usage: python3 scripts/exploration/investigate_official_tiles.py [--port 9222]
"""
import asyncio, json, sys, websockets

async def recv_response(ws, expected_id, timeout=15):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg

async def investigate(debug_port=9222):
    # Get the page target
    async with websockets.connect(f"ws://127.0.0.1:{debug_port}/devtools/browser") as bws:
        await bws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        resp = await recv_response(bws, 1)
        targets = resp.get("result", {}).get("targetInfos", [])
        page_targets = [t for t in targets if t.get("type") == "page"]
        if not page_targets:
            print("No page targets found. Open the official Duolingo avatar page first.")
            return
        # Use the first page
        target_id = page_targets[0]["targetId"]
        print(f"Using target: {page_targets[0].get('url', 'unknown')[:120]}")

    async with websockets.connect(
        f"ws://127.0.0.1:{debug_port}/devtools/page/{target_id}",
        max_size=100 * 1024 * 1024
    ) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await recv_response(ws, 1)

        # Investigation 1: Count all canvases and their sizes
        expr1 = """(function() {
            var result = {};
            var canvases = document.querySelectorAll('canvas');
            result.totalCanvases = canvases.length;
            var sizes = {};
            for (var i = 0; i < canvases.length; i++) {
                var c = canvases[i];
                var key = c.width + 'x' + c.height;
                sizes[key] = (sizes[key] || 0) + 1;
                if (c.width > 200 || c.height > 200) {
                    result['large_' + i] = {
                        id: c.id || '(none)',
                        size: c.width + 'x' + c.height,
                        className: (c.className || '').substring(0, 60),
                        visible: c.style.display !== 'none' && c.style.visibility !== 'hidden',
                        parentClass: (c.parentElement?.className || '').substring(0, 60),
                    };
                }
            }
            result.sizeDistribution = sizes;
            // Check for img elements that might be pre-rendered thumbnails
            var imgs = document.querySelectorAll('img');
            var tileImgs = [];
            for (var j = 0; j < imgs.length; j++) {
                var img = imgs[j];
                if (img.src && (img.src.includes('blob:') || img.src.includes('data:'))) {
                    tileImgs.push({src: img.src.substring(0, 50), size: img.width + 'x' + img.height});
                }
            }
            result.tileImages = tileImgs.slice(0, 10);
            return JSON.stringify(result, null, 2);
        })()"""
        await ws.send(json.dumps({"id": 10, "method": "Runtime.evaluate", "params": {"expression": expr1, "returnByValue": True}}))
        resp = await recv_response(ws, 10)
        print("\n=== Canvas/Image Inventory ===")
        print(resp.get("result", {}).get("result", {}).get("value", "error")[:4000])

        # Investigation 2: Look for Rive instances in React fiber or window scope
        expr2 = """(function() {
            var result = {};
            // Check if window.rive exists
            result.hasWindowRive = typeof window.rive !== 'undefined';
            if (result.hasWindowRive) {
                result.riveKeys = Object.keys(window.rive);
            }
            // Look for React fiber on the root element
            var root = document.getElementById('root') || document.querySelector('[data-reactroot]') || document.body.firstElementChild;
            if (root) {
                var fiberKey = Object.keys(root).find(function(k) { return k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'); });
                result.hasFiber = !!fiberKey;
                if (fiberKey) result.fiberKey = fiberKey;
            }
            // Check for any global that might hold Rive instances
            var possibleKeys = [];
            for (var key in window) {
                if (key.toLowerCase().includes('rive')) possibleKeys.push(key);
            }
            result.riveGlobals = possibleKeys.slice(0, 10);
            return JSON.stringify(result, null, 2);
        })()"""
        await ws.send(json.dumps({"id": 11, "method": "Runtime.evaluate", "params": {"expression": expr2, "returnByValue": True}}))
        resp = await recv_response(ws, 11)
        print("\n=== Rive Instance Detection ===")
        print(resp.get("result", {}).get("result", {}).get("value", "error")[:3000])

        # Investigation 3: Check for virtual scrolling / pagination in the options panel
        expr3 = """(function() {
            var result = {};
            // Find the options/thumbnails container
            var containers = document.querySelectorAll('[class*="option"], [class*="thumbnail"], [class*="tile"], [class*="grid"], [class*="scroll"]');
            var relevant = [];
            for (var i = 0; i < containers.length; i++) {
                var el = containers[i];
                var rect = el.getBoundingClientRect();
                if (rect.height > 100 && rect.width > 100) {
                    relevant.push({
                        tag: el.tagName,
                        className: (el.className || '').substring(0, 80),
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        childCount: el.children.length,
                        hasOverflow: el.scrollHeight > el.clientHeight + 10,
                    });
                }
            }
            result.scrollContainers = relevant.slice(0, 10);
            // Count visible vs total tile elements
            var tiles = document.querySelectorAll('[class*="tile"], [class*="thumbnail"], [class*="optionItem"]');
            var visibleTiles = 0;
            var tileSizes = {};
            for (var j = 0; j < tiles.length; j++) {
                var t = tiles[j];
                if (t.offsetParent !== null) visibleTiles++;
                var sz = t.offsetWidth + 'x' + t.offsetHeight;
                tileSizes[sz] = (tileSizes[sz] || 0) + 1;
            }
            result.totalTileElements = tiles.length;
            result.visibleTiles = visibleTiles;
            result.tileSizes = tileSizes;
            return JSON.stringify(result, null, 2);
        })()"""
        await ws.send(json.dumps({"id": 12, "method": "Runtime.evaluate", "params": {"expression": expr3, "returnByValue": True}}))
        resp = await recv_response(ws, 12)
        print("\n=== Options Panel / Tile Structure ===")
        print(resp.get("result", {}).get("result", {}).get("value", "error")[:4000])

        # Investigation 4: Monitor tab switching performance
        expr4 = """(function() {
            var result = {};
            // Find tab buttons
            var tabButtons = document.querySelectorAll('[role="tab"], button[class*="tab"], [data-test*="tab"]');
            result.tabCount = tabButtons.length;
            var tabInfo = [];
            for (var i = 0; i < Math.min(tabButtons.length, 12); i++) {
                var btn = tabButtons[i];
                tabInfo.push({
                    text: (btn.textContent || '').trim().substring(0, 30),
                    className: (btn.className || '').substring(0, 60),
                    ariaSelected: btn.getAttribute('aria-selected'),
                });
            }
            result.tabs = tabInfo;
            return JSON.stringify(result, null, 2);
        })()"""
        await ws.send(json.dumps({"id": 13, "method": "Runtime.evaluate", "params": {"expression": expr4, "returnByValue": True}}))
        resp = await recv_response(ws, 13)
        print("\n=== Tab Buttons ===")
        print(resp.get("result", {}).get("result", {}).get("value", "error")[:3000])

        # Investigation 5: Check how many Rive animation loops are running
        expr5 = """(function() {
            var result = {};
            // Count requestAnimationFrame callbacks (approximate)
            var rafCount = 0;
            var origRaf = window.requestAnimationFrame;
            // Check for any performance observers
            result.performanceObservers = typeof PerformanceObserver !== 'undefined' ? 'available' : 'unavailable';
            // Check if the page uses @rive-app/canvas or @rive-app/webgl
            var scripts = document.querySelectorAll('script[src]');
            var riveScripts = [];
            for (var i = 0; i < scripts.length; i++) {
                var src = scripts[i].src;
                if (src.includes('rive')) {
                    riveScripts.push(src.substring(src.lastIndexOf('/') + 1));
                }
            }
            result.riveScripts = riveScripts;
            // Check for canvas rendering contexts
            var canvases = document.querySelectorAll('canvas');
            var contexts = {};
            for (var j = 0; j < canvases.length; j++) {
                var c = canvases[j];
                // Try to detect context type via the canvas's getContext
                var isWebGL = false;
                try {
                    var gl = c.getContext('webgl') || c.getContext('webgl2');
                    isWebGL = !!gl;
                } catch(e) {}
                var is2d = false;
                try {
                    var ctx = c.getContext('2d');
                    is2d = !!ctx;
                } catch(e) {}
                var key = isWebGL ? 'webgl' : (is2d ? '2d' : 'unknown');
                contexts[key] = (contexts[key] || 0) + 1;
            }
            result.canvasContexts = contexts;
            return JSON.stringify(result, null, 2);
        })()"""
        await ws.send(json.dumps({"id": 14, "method": "Runtime.evaluate", "params": {"expression": expr5, "returnByValue": True}}))
        resp = await recv_response(ws, 14)
        print("\n=== Rendering Backend ===")
        print(resp.get("result", {}).get("result", {}).get("value", "error")[:3000])

if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 9222
    asyncio.run(investigate(port))

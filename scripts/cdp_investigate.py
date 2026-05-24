#!/usr/bin/env python3
"""CDP investigation tool — connect to a Chrome DevTools page and run JS queries.

This is the canonical tool for investigating pages via Chrome DevTools Protocol.
Use it to examine canvas architecture, Rive instances, rendering patterns, etc.

Usage:
  python3 scripts/cdp_investigate.py                        # auto-detect page
  python3 scripts/cdp_investigate.py --port 9222            # specific debug port
  python3 scripts/cdp_investigate.py --target "avatar"      # filter by URL substring
  python3 scripts/cdp_investigate.py --query custom.js      # run a custom JS file
  python3 scripts/cdp_investigate.py --interactive          # keep connection open

For the test suite (headless Chrome), see tests/test_avatar_explorer.py.
For the CDP client library, see src/cdp/client.py.
"""

import asyncio
import json
import sys
import websockets


async def recv_response(ws, expected_id, timeout=15):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg


async def evaluate(ws, expr, msg_id=10, timeout=15):
    """Run JS expression in the page and return the result value."""
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True},
    }))
    resp = await recv_response(ws, msg_id, timeout)
    return resp.get("result", {}).get("result", {}).get("value")


# -- Built-in investigation queries ------------------------------------------

INVESTIGATIONS = {
    "canvas": """(function() {
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
        return JSON.stringify(result, null, 2);
    })()""",

    "rive": """(function() {
        var result = {};
        // Check for @rive-app/canvas or @rive-app/webgl
        var scripts = document.querySelectorAll('script[src]');
        var riveScripts = [];
        for (var i = 0; i < scripts.length; i++) {
            var src = scripts[i].src;
            if (src.includes('rive')) riveScripts.push(src.substring(src.lastIndexOf('/') + 1));
        }
        result.riveScripts = riveScripts;
        // Detect canvas rendering contexts
        var canvases = document.querySelectorAll('canvas');
        var contexts = {};
        for (var j = 0; j < canvases.length; j++) {
            var c = canvases[j];
            var isWebGL = false, is2d = false;
            try { isWebGL = !!c.getContext('webgl') || !!c.getContext('webgl2'); } catch(e) {}
            try { is2d = !!c.getContext('2d'); } catch(e) {}
            var key = isWebGL ? 'webgl' : (is2d ? '2d' : 'unknown');
            contexts[key] = (contexts[key] || 0) + 1;
        }
        result.canvasContexts = contexts;
        return JSON.stringify(result, null, 2);
    })()""",

    "tabs": """(function() {
        var result = {};
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
    })()""",

    "scroll": """(function() {
        var result = {};
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
        return JSON.stringify(result, null, 2);
    })()""",

    "react": """(function() {
        var result = {};
        var root = document.getElementById('root') || document.querySelector('[data-reactroot]') || document.body.firstElementChild;
        if (root) {
            var fiberKey = Object.keys(root).find(function(k) {
                return k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance');
            });
            result.hasFiber = !!fiberKey;
            if (fiberKey) result.fiberKey = fiberKey;
        }
        return JSON.stringify(result, null, 2);
    })()""",
}


async def investigate(debug_port=9222, target_filter=None, queries=None, interactive=False):
    """Connect to a Chrome DevTools page and run investigation queries."""
    async with websockets.connect(
        f"ws://127.0.0.1:{debug_port}/devtools/browser"
    ) as bws:
        await bws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        resp = await recv_response(bws, 1)
        targets = resp.get("result", {}).get("targetInfos", [])
        page_targets = [t for t in targets if t.get("type") == "page"]

        if not page_targets:
            print("No page targets found. Open a page in Chrome first.")
            return

        # Find matching target
        target = page_targets[0]
        if target_filter:
            for t in page_targets:
                if target_filter.lower() in t.get("url", "").lower():
                    target = t
                    break

        target_id = target["targetId"]
        print(f"Target: {target.get('url', 'unknown')[:120]}\n")

    async with websockets.connect(
        f"ws://127.0.0.1:{debug_port}/devtools/page/{target_id}",
        max_size=100 * 1024 * 1024,
    ) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await recv_response(ws, 1)

        if interactive:
            print("Interactive mode — enter JS expressions (Ctrl+D to quit):\n")
            msg_id = 10
            while True:
                try:
                    expr = input(">>> ")
                    if not expr.strip():
                        continue
                except EOFError:
                    break
                result = await evaluate(ws, expr, msg_id)
                msg_id += 1
                print(json.dumps(result, indent=2)[:5000])
            return

        names = queries or ["canvas", "rive", "tabs", "scroll", "react"]
        for i, name in enumerate(names):
            expr = INVESTIGATIONS.get(name)
            if expr is None:
                # Treat as a file path
                with open(name) as f:
                    expr = f.read()
            print(f"=== {name.upper()} ===")
            result = await evaluate(ws, expr, 10 + i)
            print(str(result)[:5000])
            print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="CDP investigation tool — examine live pages via Chrome DevTools"
    )
    parser.add_argument("--port", type=int, default=9222,
                        help="Chrome remote debugging port (default: 9222)")
    parser.add_argument("--target", type=str, default=None,
                        help="Filter page targets by URL substring")
    parser.add_argument("--query", type=str, action="append", default=None,
                        help="Investigation name (canvas/rive/tabs/scroll/react) or path to JS file")
    parser.add_argument("--interactive", action="store_true",
                        help="Interactive mode: enter JS expressions at a prompt")
    args = parser.parse_args()

    asyncio.run(investigate(
        debug_port=args.port,
        target_filter=args.target,
        queries=args.query,
        interactive=args.interactive,
    ))

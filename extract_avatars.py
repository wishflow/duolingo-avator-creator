#!/usr/bin/env python3
"""Extract Duolingo avatar asset URLs via Chrome DevTools Protocol."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"
ASSETS_DIR = Path(__file__).parent / "assets"


async def send_cmd(ws, method, params=None, msg_id=1):
    """Send a CDP command and return the response."""
    cmd = {"id": msg_id, "method": method}
    if params:
        cmd["params"] = params
    await ws.send(json.dumps(cmd))


async def recv_response(ws, expected_id=None):
    """Receive CDP responses until we get the one matching expected_id."""
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if "id" in msg and (expected_id is None or msg["id"] == expected_id):
            return msg
        # If it's an event (like Network.responseReceived), print it
        if "method" in msg:
            method = msg.get("method", "")
            params = msg.get("params", {})
            if method == "Network.responseReceived":
                url = params.get("response", {}).get("url", "")
                mime = params.get("response", {}).get("mimeType", "")
                if any(k in url.lower() for k in ["avatar", "character", "sprite", "facial", "body", "eye", "mouth", "eyebrow", "nose", "hair", "accessory", "asset"]):
                    print(f"  [Network] {url}")
            elif method == "Network.loadingFinished":
                req_id = params.get("requestId", "")


async def enable_network(ws):
    """Enable Network domain for monitoring."""
    await send_cmd(ws, "Network.enable", {"maxTotalBufferSize": 100000000}, msg_id=10)
    # Wait for response
    await recv_response(ws, 10)
    print("[CDP] Network domain enabled")


async def get_network_resources(ws):
    """Get all network resources that might be avatar assets."""
    # Evaluate JS to get all image elements and network requests
    script = """
    (function() {
        const results = {images: [], dataUrls: [], configs: []};

        // Get all img elements
        document.querySelectorAll('img').forEach(img => {
            if (img.src && (img.src.includes('cloudfront') || img.src.includes('d35aaqx5ub95lt') ||
                img.src.includes('duolingo') || img.src.includes('avatar') || img.src.includes('character'))) {
                results.images.push(img.src);
            }
        });

        // Check all background images via computed style
        document.querySelectorAll('*').forEach(el => {
            const bg = getComputedStyle(el).backgroundImage;
            if (bg && bg !== 'none') {
                const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                if (match) results.images.push(match[1]);
            }
        });

        // Look for any data/config objects that might contain avatar asset URLs
        // Duolingo stores state in various places
        const allKeys = Object.keys(window).filter(k =>
            k.toLowerCase().includes('avatar') || k.toLowerCase().includes('character') ||
            k.toLowerCase().includes('asset') || k.toLowerCase().includes('duo') ||
            k.toLowerCase().includes('config') || k.toLowerCase().includes('state')
        );
        results.configs = allKeys;

        // Try to look for React fiber/props that might contain avatar data
        const root = document.getElementById('root') || document.body;
        function findReactProps(node, depth) {
            if (depth > 20 || !node) return null;
            const key = Object.keys(node).find(k => k.startsWith('__reactFiber'));
            if (key) {
                let fiber = node[key];
                let d = 0;
                while (fiber && d < 30) {
                    if (fiber.memoizedProps && fiber.memoizedProps.avatar) {
                        return JSON.stringify(fiber.memoizedProps.avatar);
                    }
                    if (fiber.memoizedState && fiber.memoizedState.avatar) {
                        return JSON.stringify(fiber.memoizedState.avatar);
                    }
                    fiber = fiber.return;
                    d++;
                }
            }
            for (const child of node.children || []) {
                const r = findReactProps(child, depth + 1);
                if (r) return r;
            }
            return null;
        }

        return JSON.stringify(results);
    })()
    """
    await send_cmd(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True}, msg_id=20)
    resp = await recv_response(ws, 20)
    if "result" in resp:
        result = resp["result"].get("result", {}).get("value", "")
        if result:
            try:
                data = json.loads(result)
                print(f"[Page] Found {len(data.get('images', []))} avatar images in DOM")
                print(f"[Page] Config keys on window: {data.get('configs', [])}")
                return data
            except:
                print(f"[Page] Raw result: {result[:2000]}")
    return None


async def get_network_request_bodies(ws):
    """Search through page source and scripts for avatar asset URLs."""
    script = """
    (function() {
        const urls = [];

        // Check inline scripts
        document.querySelectorAll('script').forEach(s => {
            if (s.textContent) {
                // Match cloudfront URLs with image extensions
                const matches = s.textContent.match(/https?:\\/\\/[^"'\s]*cloudfront[^"'\s]*\\.(png|svg|webp|jpg|jpeg)/gi) || [];
                urls.push(...matches);
                // Match any avatar-related URLs
                const avatarMatches = s.textContent.match(/https?:\\/\\/[^"'\s]*(?:avatar|character|facial|body_part)[^"'\s]*/gi) || [];
                urls.push(...avatarMatches);
            }
        });

        // Check all script src attributes
        document.querySelectorAll('script[src]').forEach(s => {
            urls.push(s.src);
        });

        return JSON.stringify([...new Set(urls)]);
    })()
    """
    await send_cmd(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True}, msg_id=30)
    resp = await recv_response(ws, 30)
    if "result" in resp:
        result = resp["result"].get("result", {}).get("value", "")
        if result:
            try:
                data = json.loads(result)
                print(f"[Scripts] Found {len(data)} avatar-related URLs in script tags")
                return data
            except:
                pass
    return []


async def deep_search(ws):
    """Deep search for avatar asset configuration in the page."""
    scripts = [
        # Look for any object/array containing lots of image URLs related to avatar parts
        """
        (function() {
            // Search all script text for SVG URL patterns related to avatar
            const scripts = document.querySelectorAll('script');
            let found = '';
            for (const s of scripts) {
                if (s.textContent) {
                    // Look for large JSON-like structures with avatar assets
                    const lines = s.textContent.split(/[;{}]/);
                    for (const line of lines) {
                        if ((line.includes('eyebrow') || line.includes('eye') || line.includes('mouth') ||
                             line.includes('nose') || line.includes('hair') || line.includes('face')) &&
                            line.includes('http')) {
                            found += line.substring(0, 500) + '\\n---\\n';
                        }
                    }
                }
            }
            return found || 'nothing found in script tags';
        })()
        """,
        # Try to access Duolingo's API responses cached in the page
        """
        (function() {
            // Check performance API for resources
            const resources = performance.getEntriesByType('resource');
            const avatarResources = resources.filter(r =>
                r.name.toLowerCase().includes('avatar') ||
                r.name.toLowerCase().includes('character') ||
                r.name.toLowerCase().includes('facial')
            );
            return JSON.stringify(avatarResources.map(r => ({url: r.name, type: r.initiatorType})));
        })()
        """,
        # Try to check the network cache / service worker
        """
        (function() {
            // Look for the avatar configuration response
            // Duolingo might load it from an API endpoint
            const entries = performance.getEntriesByType('resource');
            const relevant = entries.filter(r =>
                r.name.includes('duolingo') &&
                (r.name.includes('avatar') || r.name.includes('character') ||
                 r.name.includes('config') || r.name.includes('asset') ||
                 r.name.includes('manifest'))
            );
            return JSON.stringify(relevant.map(r => r.name));
        })()
        """,
        # Monitor for fetch/XHR that might contain avatar data
        """
        (function() {
            // Intercept fetch to catch avatar config data
            const originalFetch = window.fetch;
            const captured = [];
            window.fetch = function(...args) {
                const url = typeof args[0] === 'string' ? args[0] : args[0].url;
                if (url && url.includes('avatar')) {
                    captured.push(url);
                }
                return originalFetch.apply(this, args).then(r => {
                    if (url && url.includes('avatar') && r.clone) {
                        const clone = r.clone();
                        clone.text().then(t => {
                            if (t.length < 5000 && t.includes('http')) {
                                console.log('AVATAR_DATA:', t.substring(0, 2000));
                            }
                        }).catch(() => {});
                    }
                    return r;
                });
            };
            return 'fetch interceptor installed, will capture avatar requests';
        })()
        """,
    ]

    for i, script in enumerate(scripts):
        await send_cmd(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True}, msg_id=100 + i)
        resp = await recv_response(ws, 100 + i)
        if "result" in resp:
            result = resp["result"].get("result", {}).get("value", "")
            print(f"\n[DeepSearch {i}] {str(result)[:2000]}")

    # Now let's try to trigger the avatar editor to load all its assets
    # by looking at what API calls it makes
    print("\n[Action] Waiting for network events...")
    for _ in range(10):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            msg = json.loads(raw)
            method = msg.get("method", "")
            if method == "Network.requestWillBeSent":
                url = msg.get("params", {}).get("request", {}).get("url", "")
                if "avatar" in url.lower() or "d35aaqx5ub95lt" in url:
                    print(f"  [Request] {url}")
            elif method == "Network.responseReceived":
                url = msg.get("params", {}).get("response", {}).get("url", "")
                if "avatar" in url.lower() or "character" in url.lower():
                    print(f"  [Response] {url}")
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"  Error: {e}")


async def main():
    print(f"[*] Connecting to Duolingo avatar page via CDP...")
    try:
        async with websockets.connect(WS_URL, max_size=100 * 1024 * 1024) as ws:
            print("[*] Connected!")

            # Enable Network monitoring
            await enable_network(ws)

            # Get all network resources matching avatar patterns
            # But first, let's try to find the avatar config via scripts
            script_urls = await get_network_request_bodies(ws)

            # Get images from DOM
            await get_network_resources(ws)

            # Deep search
            await deep_search(ws)

    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

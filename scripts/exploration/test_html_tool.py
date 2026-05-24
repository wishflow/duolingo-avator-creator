#!/usr/bin/env python3
"""Open the HTML avatar explorer tool and verify it works via CDP."""
import asyncio, json, websockets

async def main():
    # First, open a new tab with the HTML tool
    import urllib.request
    open_url = "http://127.0.0.1:9222/json/new?http://localhost:8888/avatar_explorer.html"
    try:
        resp = urllib.request.urlopen(open_url)
        page_info = json.loads(resp.read())
        print(f"Opened new tab: {page_info.get('id', 'unknown')}")
        ws_url = page_info.get("webSocketDebuggerUrl")
        print(f"WebSocket: {ws_url}")
    except Exception as e:
        print(f"Error opening tab: {e}")
        import urllib.parse
        encoded = urllib.parse.quote("http://localhost:8888/avatar_explorer.html", safe="")
        url2 = f"http://127.0.0.1:9222/json/new?{encoded}"
        try:
            resp = urllib.request.urlopen(url2)
            page_info = json.loads(resp.read())
            print(f"Opened new tab (retry): {page_info.get('id', 'unknown')}")
            ws_url = page_info.get("webSocketDebuggerUrl")
        except Exception as e2:
            print(f"Retry also failed: {e2}")
            return

    if not ws_url:
        print("No WebSocket URL found")
        return

    # Connect to the page and check if Rive loaded
    async with websockets.connect(ws_url, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        resp = await ws.recv()
        print(f"Runtime enabled: {resp[:100]}")

        # Wait a bit for the page to auto-load the Rive file
        await asyncio.sleep(3)

        # Check page status
        script = """
        (function() {
            return JSON.stringify({
                fileLoaded: !!window.fileBuffer,
                hasRive: typeof rive !== 'undefined' || typeof Rive !== 'undefined',
                artboardCount: window.currentFile ? window.currentFile.artboardCount() : -1,
                smCount: window.currentFile ? window.currentFile.stateMachineCount() : -1,
                statusText: document.getElementById('statusDiv')?.textContent || 'N/A',
            });
        })()
        """
        await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                                   "params": {"expression": script, "returnByValue": True}}))
        resp = await ws.recv()
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\nPage status: {r}")

        # Get console messages
        await ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate",
                                   "params": {"expression": "document.getElementById('logBox')?.innerText || 'no log'",
                                              "returnByValue": True}}))
        resp = await ws.recv()
        log_text = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\nConsole log: {log_text[:3000]}")

asyncio.run(main())

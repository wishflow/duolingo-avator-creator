#!/usr/bin/env python3
import asyncio, json, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/88B207E3995C2DC2B3C96E76A4CAFA5F"

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await ws.recv()
        await asyncio.sleep(3)

        # Check status
        script = """
        (function() {
            return JSON.stringify({
                fileLoaded: !!window.fileBuffer,
                statusText: document.getElementById('statusDiv')?.textContent || 'N/A',
                artboardSelect: document.getElementById('artboardSelect')?.options?.length || 0,
                logText: document.getElementById('logBox')?.innerText || 'N/A',
            });
        })()
        """
        await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate",
                                   "params": {"expression": script, "returnByValue": True}}))
        resp = await ws.recv()
        print(resp.get("result", {}).get("result", {}).get("value", ""))

asyncio.run(main())

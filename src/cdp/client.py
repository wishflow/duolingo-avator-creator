"""Minimal Chrome DevTools Protocol client over WebSocket."""

import asyncio
import json
import base64


class CDPClient:
    """Async CDP client over a single WebSocket connection."""

    def __init__(self, ws_url, timeout=30):
        self.ws_url = ws_url
        self.ws = None
        self._req_id = 0
        self._timeout = timeout

    async def connect(self):
        import websockets
        self.ws = await websockets.connect(
            self.ws_url,
            max_size=100 * 1024 * 1024,
            ping_interval=30,
            ping_timeout=10,
        )
        # Drain init messages
        await asyncio.sleep(0.3)
        while True:
            try:
                await asyncio.wait_for(self.ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                break

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def _recv_id(self, eid):
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=self._timeout)
            msg = json.loads(raw)
            if msg.get("id") == eid:
                if "error" in msg:
                    raise RuntimeError(f"CDP error: {msg['error']}")
                return msg

    async def send(self, method, params=None):
        self._req_id += 1
        eid = self._req_id
        payload = {"id": eid, "method": method}
        if params:
            payload["params"] = params
        await self.ws.send(json.dumps(payload))
        return await self._recv_id(eid)

    async def evaluate(self, expression):
        """Run JS in the page, return the result value."""
        resp = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
        })
        return resp.get("result", {}).get("result", {}).get("value")

    async def evaluate_async(self, expression):
        """Run async JS, await the returned promise."""
        resp = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        return resp.get("result", {}).get("result", {}).get("value")

    async def screenshot(self):
        """Capture a PNG screenshot, return raw bytes."""
        resp = await self.send("Page.captureScreenshot", {"format": "png"})
        data = resp.get("result", {}).get("data", "")
        if data:
            return base64.b64decode(data)
        return None

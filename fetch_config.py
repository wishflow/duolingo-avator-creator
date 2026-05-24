#!/usr/bin/env python3
"""Fetch the avatar builder config and assets via CDP."""
import asyncio, json, sys
import websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"

async def send(ws, method, params=None, msg_id=1):
    cmd = {"id": msg_id, "method": method}
    if params:
        cmd["params"] = params
    await ws.send(json.dumps(cmd))

async def recv(ws, expected_id=None):
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if "id" in msg and (expected_id is None or msg["id"] == expected_id):
            return msg
        if "method" in msg:
            p = msg.get("params", {})
            if msg["method"] == "Runtime.consoleAPICalled":
                for arg in p.get("args", []):
                    val = arg.get("value", "")
                    if val and len(str(val)) > 10:
                        print(f"  [LOG] {str(val)[:500]}")

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await send(ws, "Runtime.enable", {}, 1)
        await recv(ws, 1)

        # Fetch the avatar builder config via in-browser fetch
        script = """
        (async function() {
            try {
                const configResp = await fetch('/users/1606465090/avatar-builder-config?uiLanguage=en');
                const config = await configResp.json();
                console.log('CONFIG_KEYS:', JSON.stringify(Object.keys(config)));

                const statesResp = await fetch('/users/1606465090/built-avatar-states');
                const states = await statesResp.json();
                console.log('STATES_KEYS:', JSON.stringify(Object.keys(states)));

                return JSON.stringify({
                    config: config,
                    states: states
                });
            } catch(e) {
                return 'ERROR: ' + e.message;
            }
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True}, 10)
        resp = await recv(ws, 10)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== Avatar Builder Config ===")
        print(r[:50000])

asyncio.run(main())

#!/usr/bin/env python3
"""Verify the fixed HTML tool - handles CDP events properly."""
import asyncio, json, sys, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/F3E73A8FFF299A8B46D098136D059C6A"

async def recv_response(ws, expected_id, timeout=30):
    """Receive messages until we get the response matching expected_id."""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg
        # Print important events
        method = msg.get("method", "")
        if method == "Runtime.consoleAPICalled":
            for arg in msg.get("params",{}).get("args",[]):
                v = arg.get("value","")
                if v: print(f"  [console] {v[:200]}")

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        # Enable Runtime + Log domains
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await ws.send(json.dumps({"id":2,"method":"Log.enable"}))
        await recv_response(ws, 1)
        await recv_response(ws, 2)
        print("=== Domains enabled, waiting for page to load ===")

        # Wait for the page to fully load (longer wait for Rive WASM + .riv file)
        for i in range(15):
            await asyncio.sleep(2)
            await ws.send(json.dumps({"id":100+i,"method":"Runtime.evaluate",
                "params":{"expression":"""
                    (function(){
                        var s=document.getElementById('statusDiv');
                        return s?s.textContent:'no status';
                    })()
                ""","returnByValue":True}}))
            try:
                resp = await recv_response(ws, 100+i, timeout=3)
                status = resp.get("result",{}).get("result",{}).get("value","")
                print(f"  [{i*2}s] status: {status}")
                if "已加载" in str(status) or "artboard" in str(status).lower():
                    print(f"\n*** SUCCESS: Page loaded! ***")
                    break
            except asyncio.TimeoutError:
                print(f"  [{i*2}s] timeout...")

        # Get full log
        await ws.send(json.dumps({"id":200,"method":"Runtime.evaluate",
            "params":{"expression":"""
                (function(){
                    var log=document.getElementById('logBox');
                    return log?log.innerText:'no log';
                })()
            ""","returnByValue":True}}))
        try:
            resp = await recv_response(ws, 200, timeout=5)
            print("\n=== Log output ===")
            print(resp.get("result",{}).get("result",{}).get("value",""))
        except:
            pass

asyncio.run(main())

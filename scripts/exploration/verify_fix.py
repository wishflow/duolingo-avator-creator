#!/usr/bin/env python3
"""Wait for the page to load and check if Rive loaded successfully."""
import asyncio, json, sys, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/16650AEAB28ECB206070EDDB717BD9D8"

async def recv_response(ws, expected_id, timeout=10):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg
        method = msg.get("method","")
        if method == "Runtime.consoleAPICalled":
            for arg in msg.get("params",{}).get("args",[]):
                v = arg.get("value","")
                if v: print(f"  [console] {str(v)[:300]}")

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await ws.send(json.dumps({"id":2,"method":"Log.enable"}))
        await recv_response(ws, 1)
        await recv_response(ws, 2)

        # Wait for loading in a loop
        for i in range(20):
            await asyncio.sleep(2)
            try:
                await ws.send(json.dumps({"id":100+i,"method":"Runtime.evaluate",
                    "params":{"expression":"document.getElementById('statusDiv')?.textContent||'?'",
                              "returnByValue":True}}))
                resp = await recv_response(ws, 100+i, timeout=3)
                status = resp.get("result",{}).get("result",{}).get("value","")
                if "已加载" in str(status):
                    print(f"\n*** SUCCESS [{i*2}s]: {status} ***")
                    # Get full log
                    await ws.send(json.dumps({"id":500,"method":"Runtime.evaluate",
                        "params":{"expression":"document.getElementById('logBox')?.innerText||'no log'",
                                  "returnByValue":True}}))
                    resp = await recv_response(ws, 500)
                    print(resp.get("result",{}).get("result",{}).get("value",""))
                    break
                elif "错误" in str(status) or "失败" in str(status):
                    print(f"\n*** FAIL [{i*2}s]: {status} ***")
                    await ws.send(json.dumps({"id":500,"method":"Runtime.evaluate",
                        "params":{"expression":"document.getElementById('logBox')?.innerText||'no log'",
                                  "returnByValue":True}}))
                    resp = await recv_response(ws, 500)
                    print(resp.get("result",{}).get("result",{}).get("value",""))
                    break
                else:
                    print(f"  [{i*2}s] {status}")
            except asyncio.TimeoutError:
                print(f"  [{i*2}s] timeout")

asyncio.run(main())

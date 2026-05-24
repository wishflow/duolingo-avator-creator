#!/usr/bin/env python3
"""Quickly check if the HTML tool loaded successfully."""
import asyncio, json, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CB4837F1B122A360413A05FDD9AAB40B"

async def recv_response(ws, expected_id, timeout=10):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg
        m = msg.get("method","")
        if m == "Runtime.consoleAPICalled":
            for a in msg.get("params",{}).get("args",[]):
                v = a.get("value","")
                if v: print(f"  [console] {str(v)[:300]}")

async def check():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await ws.send(json.dumps({"id":2,"method":"Log.enable"}))
        await recv_response(ws, 1)
        await recv_response(ws, 2)

        for i in range(15):
            await asyncio.sleep(2)
            await ws.send(json.dumps({"id":100+i,"method":"Runtime.evaluate",
                "params":{"expression":"document.getElementById('logBox')?.innerText||'?'",
                          "returnByValue":True}}))
            try:
                resp = await recv_response(ws, 100+i, timeout=3)
                log = resp.get("result",{}).get("result",{}).get("value","")
                if "成功" in str(log):
                    print(f"\n*** SUCCESS at {i*2}s ***")
                    print(log)
                    return
                if "错误" in str(log):
                    print(f"\n*** ERROR at {i*2}s ***")
                    print(log)
                    return
                last_line = str(log).strip().split('\n')[-1] if log else '?'
                print(f"  [{i*2}s] {last_line[:120]}")
            except asyncio.TimeoutError:
                print(f"  [{i*2}s] timeout")

asyncio.run(check())

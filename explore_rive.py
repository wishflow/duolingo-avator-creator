#!/usr/bin/env python3
"""Explore Rive file structure via browser's Rive runtime."""
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

async def main():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await send(ws, "Runtime.enable", {}, 1)
        await recv(ws, 1)
        print("[*] Connected")

        # First check if Rive runtime is available on the page
        script = """
        (function() {
            const result = {};

            // Check for Rive in the global scope
            result.hasRive = typeof rive !== 'undefined';

            // Check what webpack modules might have Rive
            const scripts = Array.from(document.querySelectorAll('script[src]'));
            const riveScripts = scripts.filter(s =>
                s.src.includes('rive') || s.src.includes('Rive')
            );
            result.riveScripts = riveScripts.map(s => s.src);

            return JSON.stringify(result);
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True}, 10)
        resp = await recv(ws, 10)
        print(f"Rive availability: {resp.get('result', {}).get('result', {}).get('value', '')}")

        # Try to load and parse the Rive file
        script2 = """
        (async function() {
            try {
                const riveUrl = 'https://avatars.duolingo.com/avatar-builder/avatar_builder_25_sept2025.riv';

                // Check if rive is available through module system
                let RiveModule = window.rive || window.Rive;

                // Try to import via dynamic import
                if (!RiveModule) {
                    try {
                        RiveModule = await import('@rive-app/canvas');
                    } catch(e) {
                        return 'RIVE_NOT_AVAILABLE: ' + e.message;
                    }
                }

                if (!RiveModule) {
                    return 'RIVE_NOT_AVAILABLE: no module found';
                }

                // Load the file
                const resp = await fetch(riveUrl);
                const buffer = await resp.arrayBuffer();
                const uint8Array = new Uint8Array(buffer);

                // Load the Rive file
                const riveFile = await RiveModule.default?.load?.(uint8Array) ||
                                  await RiveModule.load?.(uint8Array);

                if (!riveFile) {
                    return 'LOAD_FAILED: could not load rive file';
                }

                const info = {
                    artboardCount: riveFile.artboardCount?.() ?? riveFile.artboardCount ?? 'N/A',
                    animationCount: riveFile.animationCount?.() ?? 'N/A',
                    stateMachineCount: riveFile.stateMachineCount?.() ?? 'N/A',
                };

                // List all artboards
                const artboards = [];
                for (let i = 0; i < (riveFile.artboardCount?.() ?? 0); i++) {
                    const ab = riveFile.artboardByIndex?.(i) ?? riveFile.artboard(i);
                    artboards.push({
                        index: i,
                        name: ab.name,
                    });
                }
                info.artboards = artboards;

                // List all animations
                const animations = [];
                for (let i = 0; i < (riveFile.animationCount?.() ?? 0); i++) {
                    const anim = riveFile.animationByIndex?.(i) ?? riveFile.animation(i);
                    animations.push({
                        index: i,
                        name: anim?.name ?? 'unknown',
                    });
                }
                info.animations = animations.slice(0, 50);

                // List all state machines
                const stateMachines = [];
                for (let i = 0; i < (riveFile.stateMachineCount?.() ?? 0); i++) {
                    const sm = riveFile.stateMachineByIndex?.(i) ?? riveFile.stateMachine(i);
                    if (sm) {
                        const inputs = [];
                        for (let j = 0; j < (sm.inputCount?.() ?? 0); j++) {
                            const input = sm.inputByIndex?.(j) ?? sm.input(j);
                            if (input) {
                                inputs.push({index: j, name: input.name, type: input.type});
                            }
                        }
                        stateMachines.push({
                            index: i,
                            name: sm.name,
                            inputCount: sm.inputCount?.() ?? 0,
                            inputs: inputs.slice(0, 30),
                        });
                    }
                }
                info.stateMachines = stateMachines;

                return JSON.stringify(info);
            } catch(e) {
                return 'ERROR: ' + e.message + ' stack: ' + (e.stack || '').substring(0, 500);
            }
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script2, "returnByValue": True, "awaitPromise": True}, 20)
        resp = await recv(ws, 20)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        print(f"\n=== Rive File Structure ===")
        print(r[:10000])

asyncio.run(main())

#!/usr/bin/env python3
"""Find Rive instance on Duolingo page through React fiber or global scope."""
import asyncio, json, websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"

async def recv_response(ws, expected_id, timeout=10):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("id") == expected_id:
            return msg

async def check():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await recv_response(ws, 1)

        # Search for rive-related objects in React fiber tree
        e = """(function() {
            // Find the main avatar canvas (1002x1368)
            var canvases = document.querySelectorAll('canvas');
            var mainCanvas = null;
            for (var i = 0; i < canvases.length; i++) {
                if (canvases[i].width > 500 && canvases[i].height > 500) {
                    mainCanvas = canvases[i];
                    break;
                }
            }
            if (!mainCanvas) return 'no main canvas';

            // Walk React fiber tree to find Rive instances
            var fiberKey = Object.keys(mainCanvas).find(function(k) {
                return k.startsWith('__reactFiber');
            });
            if (!fiberKey) return 'no fiber key';

            var result = {foundRive: false};
            var fiber = mainCanvas[fiberKey];
            var depth = 0;
            var visited = new Set();

            // DFS search for rive instances in the fiber tree
            function searchFiber(fiber, d) {
                if (!fiber || d > 30 || visited.has(fiber)) return;
                visited.add(fiber);

                // Check memoizedState for hooks containing rive
                var state = fiber.memoizedState;
                while (state) {
                    try {
                        var val = state.memoizedState;
                        if (val && typeof val === 'object') {
                            // Check if it looks like a Rive instance
                            if (val.riveFile || val.artboard || val.stateMachineInputs) {
                                result.riveInstance = {
                                    depth: d,
                                    hasRiveFile: !!val.riveFile,
                                    hasAnimator: !!val.animator,
                                    keys: Object.keys(val).slice(0, 15),
                                };
                                result.foundRive = true;
                                return;
                            }
                            // Also check nested objects
                            for (var k in val) {
                                if (val[k] && typeof val[k] === 'object' && val[k].riveFile) {
                                    result.riveInstance = {
                                        depth: d,
                                        propName: k,
                                        hasRiveFile: !!val[k].riveFile,
                                        keys: Object.keys(val[k]).slice(0, 15),
                                    };
                                    result.foundRive = true;
                                    return;
                                }
                            }
                        }
                        // Check queue lastRenderedState
                        if (state.queue && state.queue.lastRenderedState) {
                            var lrs = state.queue.lastRenderedState;
                            if (lrs && typeof lrs === 'object') {
                                if (lrs.riveFile || lrs.Rive) {
                                    result.riveInQueue = Object.keys(lrs).slice(0, 10);
                                    result.foundRive = true;
                                    return;
                                }
                            }
                        }
                    } catch(e) {}
                    state = state.next;
                }

                // Check stateNode
                if (fiber.stateNode && typeof fiber.stateNode === 'object') {
                    var sn = fiber.stateNode;
                    if (sn.riveFile || sn.Rive || sn.stateMachines) {
                        result.riveInStateNode = Object.keys(sn).slice(0, 15);
                        result.foundRive = true;
                        return;
                    }
                }

                // Check pendingProps
                if (fiber.pendingProps) {
                    for (var k in fiber.pendingProps) {
                        var v = fiber.pendingProps[k];
                        if (v && typeof v === 'object' && (v.riveFile || v.stateMachineInputs)) {
                            result.riveInProps = {key: k, keys: Object.keys(v).slice(0, 15)};
                            result.foundRive = true;
                            return;
                        }
                    }
                }

                searchFiber(fiber.child, d + 1);
                searchFiber(fiber.sibling, d);
                fiber = fiber.return;
                d--;
            }

            searchFiber(fiber, 0);
            result.searchedDepth = visited.size;
            return JSON.stringify(result, null, 2);
        })()"""
        await ws.send(json.dumps({"id":10,"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
        resp = await recv_response(ws, 10)
        print( resp.get("result",{}).get("result",{}).get("value","")[:5000])

asyncio.run(check())

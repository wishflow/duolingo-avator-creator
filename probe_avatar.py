#!/usr/bin/env python3
"""Quick probe of Duolingo avatar page via CDP."""
import asyncio, json, sys
import websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"

async def probe():
    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        # Enable Network
        await ws.send(json.dumps({"id":1,"method":"Network.enable"}))
        resp = await ws.recv()
        print("Network enabled:", resp[:200])

        # Find where Duolingo stores its avatar data by looking at script content
        # Look for JSON-like data structures with avatar/character parts
        script = """
        (function() {
            const results = [];

            // Check all script tags for avatar-related data
            document.querySelectorAll('script').forEach(s => {
                const text = s.textContent || '';
                if (text.includes('eyebrow') || text.includes('avatar') || text.includes('character')) {
                    // Find all URL patterns in this script
                    const urls = text.match(/https?:\\/\\/[^"',;\\s]+\\.(?:svg|png|webp)/gi) || [];
                    if (urls.length > 0) {
                        results.push({type: 'script_with_avatar_urls', count: urls.length, sample: urls.slice(0, 3)});
                    }
                }
            });

            // Try to find React root component state
            const root = document.getElementById('root');
            if (root) {
                const fiberKey = Object.keys(root).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
                if (fiberKey) results.push({type: 'react_root_found', key: fiberKey});
            }

            // Search all JS objects on window for avatar data
            for (const key of Object.keys(window)) {
                try {
                    const val = window[key];
                    if (val && typeof val === 'object' && val.avatar) {
                        results.push({type: 'window_obj_with_avatar', key: key});
                    }
                } catch(e) {}
            }

            // Performance API - look for avatar/character related network requests
            const perfEntries = performance.getEntriesByType('resource');
            const avatarEntries = perfEntries.filter(e =>
                e.name.includes('avatar') || e.name.includes('character') ||
                e.name.includes('facial') || e.name.includes('d35aaqx5ub95lt')
            );
            results.push({type: 'performance_resources', count: avatarEntries.length,
                          urls: avatarEntries.slice(0, 20).map(e => e.name)});

            return JSON.stringify(results, null, 2);
        })()
        """
        await ws.send(json.dumps({"id":2,"method":"Runtime.evaluate",
                                   "params":{"expression":script,"returnByValue":True}}))
        resp = await ws.recv()
        print("\nPage probe result:")
        print(resp[:5000])

        # Also get all the JavaScript files loaded on the page
        script2 = """
        (function() {
            const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
            const relevant = scripts.filter(s =>
                s.includes('avatar') || s.includes('character') || s.includes('duolingo') ||
                s.includes('d35aaqx5ub95lt') || s.includes('cloudfront')
            );
            return JSON.stringify({allScriptCount: scripts.length, relevantScripts: relevant});
        })()
        """
        await ws.send(json.dumps({"id":3,"method":"Runtime.evaluate",
                                   "params":{"expression":script2,"returnByValue":True}}))
        resp = await ws.recv()
        print("\nScript sources:")
        print(resp[:3000])

asyncio.run(probe())

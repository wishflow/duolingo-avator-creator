#!/usr/bin/env python3
"""Download all Duolingo avatar builder assets."""
import asyncio, json, os, sys, hashlib
from pathlib import Path
import websockets

WS_URL = "ws://127.0.0.1:9222/devtools/page/CFC155B356ADF58BA85035F269DEA082"
ASSETS_DIR = Path(__file__).parent / "assets"

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
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    async with websockets.connect(WS_URL, max_size=100*1024*1024) as ws:
        await send(ws, "Runtime.enable", {}, 1)
        await recv(ws, 1)
        print("[*] CDP connected")

        # Step 1: Get the full config and all asset URLs via browser fetch
        script = """
        (async function() {
            const configResp = await fetch('/users/1606465090/avatar-builder-config?uiLanguage=en');
            const config = await configResp.json();
            const cfg = config.avatarBuilderConfig;

            const urls = [];

            // Add Rive file
            urls.push(cfg.riveFileUrl);
            urls.push(cfg.riveServerRenderingFileUrl);

            // Add all tab icons
            cfg.stateChooserTabs.forEach(tab => {
                if (tab.selectedIcon) {
                    urls.push(tab.selectedIcon.lightUrl);
                    urls.push(tab.selectedIcon.darkUrl);
                }
                if (tab.unselectedIcon) {
                    urls.push(tab.unselectedIcon.lightUrl);
                    urls.push(tab.unselectedIcon.darkUrl);
                }
            });

            return JSON.stringify({
                config: config,
                urls: urls
            });
        })()
        """
        await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True}, 10)
        resp = await recv(ws, 10)
        r = resp.get("result", {}).get("result", {}).get("value", "")
        data = json.loads(r)

        config = data["config"]
        urls = data["urls"]

        print(f"[*] Found {len(urls)} assets to download")
        print(f"[*] Rive files: {urls[:2]}")
        print(f"[*] SVG icons: {len(urls)-2}")

        # Save config
        config_path = ASSETS_DIR / "avatar_builder_config.json"
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"[+] Saved config to {config_path}")

        # Download each asset via browser fetch
        for url in urls:
            basename = url.split("/")[-1].split("?")[0]
            if not basename.endswith(".riv") and not basename.endswith(".svg"):
                basename += ".svg"

            filepath = ASSETS_DIR / basename
            if filepath.exists():
                print(f"  [skip] {basename}")
                continue

            script = f"""
            (async function() {{
                try {{
                    const resp = await fetch('{url}');
                    const blob = await resp.blob();
                    const reader = new FileReader();
                    return await new Promise((resolve) => {{
                        reader.onloadend = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                    }});
                }} catch(e) {{
                    return 'ERROR: ' + e.message;
                }}
            }})()
            """
            await send(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True}, 50)
            resp = await recv(ws, 50)
            result = resp.get("result", {}).get("result", {}).get("value", "")

            if result.startswith("ERROR"):
                print(f"  [FAIL] {basename}: {result}")
                continue

            if result.startswith("data:"):
                # Extract base64 data
                try:
                    header, b64data = result.split(",", 1)
                    import base64
                    binary = base64.b64decode(b64data)
                    with open(filepath, "wb") as f:
                        f.write(binary)
                    size_kb = len(binary) / 1024
                    print(f"  [+] {basename} ({size_kb:.1f} KB)")
                except Exception as e:
                    print(f"  [ERR] {basename}: {e}")
            else:
                print(f"  [UNKNOWN] {basename}: {result[:100]}")

        print(f"\n[DONE] All assets downloaded to {ASSETS_DIR}/")

        # Generate a summary JSON
        cfg = config["avatarBuilderConfig"]
        summary = {
            "riveFile": cfg["riveFileUrl"],
            "riveServerRenderingFile": cfg["riveServerRenderingFileUrl"],
            "tabs": []
        }

        for tab in cfg["stateChooserTabs"]:
            tab_info = {"name": tab["tabName"], "sections": []}
            for section in tab["sections"]:
                sec_info = {
                    "header": section.get("header", ""),
                    "buttonType": section.get("buttonType", ""),
                }
                if section.get("imageButtons"):
                    sec_info["imageButtons"] = section["imageButtons"]
                if section.get("featureButtons"):
                    sec_info["featureButtons"] = [
                        {"state": fb["state"], "value": fb["value"]}
                        for fb in section["featureButtons"]
                    ]
                tab_info["sections"].append(sec_info)
            summary["tabs"].append(tab_info)

        summary_path = ASSETS_DIR / "avatar_structure_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"[+] Saved structure summary to {summary_path}")

asyncio.run(main())

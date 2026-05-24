# Avatar Explorer — Duolingo Avatar Editor Clone

Rive-based avatar editor reverse-engineered from the official Duolingo avatar page.

## Project structure

```
crawler/
├── assets/
│   ├── avatar_explorer.html   # Main application (~680 lines, single-file)
│   └── avatar_builder_config.json
├── src/
│   └── cdp/
│       └── client.py          # CDPClient — async CDP over WebSocket
├── tests/
│   └── test_avatar_explorer.py  # 10 integration tests via CDP
└── scripts/
    └── exploration/           # One-shot investigation scripts (historical)
```

## Commands

```bash
# Run all tests
python3 tests/test_avatar_explorer.py

# Run single test
python3 tests/test_avatar_explorer.py --test 3

# Custom ports (to avoid conflicts with running Chrome instances)
python3 tests/test_avatar_explorer.py --port 8775 --debug-port 9228

# Keep browser open after tests for manual inspection
python3 tests/test_avatar_explorer.py --keep
```

## Test infrastructure

### Proven Chrome launch pattern

The ONLY reliable way to launch Chrome with DevTools debugging:

```bash
google-chrome \
  --remote-debugging-port=<port> \
  --user-data-dir=/tmp/chrome-test-profile \
  --no-first-run \
  --no-default-browser-check \
  --headless=new \
  --window-size=1440,900 \
  <url>
```

Key rules:
- **MUST use `--user-data-dir`** pointing to a NON-DEFAULT directory. Chrome refuses remote debugging when another instance holds the default profile.
- **NEVER use `pkill -f "chromium|chrome"`** without a specific port pattern — it will kill Claude Code (exit 143/144). The safe pattern is `pkill -f "remote-debugging-port=<port>"`.
- Even the safe pkill can cause issues — prefer checking if port is free with `ss -tlnp | grep <port>` before launching.
- **Do NOT use MCP chrome-devtools tools** for this project — they add overhead without benefit. Raw CDP via `websockets` is simpler and proven.

### Test architecture (`test_avatar_explorer.py`)

- `TestRunner.setup()`: Start HTTP server → kill old Chrome on debug port → launch Chrome headless → connect CDP → wait for `sharedRiveFile !== null && tileInstances.size > 0`
- Each test is an `async def test_NN(cdp: CDPClient)` function
- Uses `CDPClient.evaluate(expr)` for assertions — returns the JS value
- Tests run sequentially; the runner handles setup/teardown

### CDP investigation script pattern

When investigating the official Duolingo page (or any live page), use the `scripts/exploration/investigate_official_tiles.py` pattern:

```python
async with websockets.connect(f"ws://127.0.0.1:{port}/devtools/browser") as bws:
    # get page targets, then connect to /devtools/page/{targetId}
    ...
    await ws.send(json.dumps({"id": N, "method": "Runtime.evaluate",
        "params": {"expression": "...", "returnByValue": True}}))
```

The existing `investigate_official_tiles.py` has 5 ready-made investigations: canvas inventory, Rive instance detection, scroll/pagination structure, tab buttons, rendering backend.

## Architecture decisions (do NOT regress on these)

### 1. Per-tile Rive canvas instances (NOT pre-rendered images)

Every tile in the options panel gets its own `<canvas>` + Rive instance rendered via `drawFrame()`. This is what the official Duolingo page does. Do NOT go back to `<img>`-based thumbnails or shared canvases.

### 2. Shared RiveFile, per-instance render

- One `RiveFile` (WASM-parsed `.riv` data) shared across all instances — avoids re-parsing
- Each instance gets its own set of state machine inputs (cached in `instance._inputs`)
- `drawFrame()` renders to the instance's own canvas

### 3. Lazy tab rendering + dirty tracking

- Instances are created on-demand when a tab is first visited (`renderTabTiles`)
- `dirtyTabs` (Set) tracks which tabs need re-rendering due to state changes
- When switching back to a non-dirty tab with cached instances, it's instantaneous (no re-render)
- `setSMValue` marks other tabs dirty and updates current tab's instances via `updateTileInstancesForState`

### 4. rAF deduplication

- `tileDrawPending` flag ensures only ONE `requestAnimationFrame` callback fires per frame for tile updates
- This was a major perf win: went from 12+ redundant rAF callbacks to 1

### 5. Batched instance creation

- `renderTabTiles` creates instances in batches of 8 with `Promise.all`
- `await new Promise(r => setTimeout(r, 0))` between batches yields to the browser, preventing UI freeze

### 6. NO background pre-rendering

Background pre-rendering was tried and REMOVED (commit c913151). It caused main-thread contention between instance creation/destruction on other tabs and the main preview animation loop, producing visible frame drops. The lazy approach is fast enough — tabs render in under 1 second.

### 7. Input caching

- `instance._inputs = instance.stateMachineInputs('SMAvatar')` — cached once per instance on creation
- Avoids calling `stateMachineInputs()` (which creates ~19 wrapper objects) on every update
- Combined with visible-tab filtering: only current tab's cached inputs are updated

## Lessons learned (anti-patterns — DO NOT REPEAT)

### 1. Write tests FIRST, not after

Every behavioral change should have test coverage BEFORE implementing. The test script (`test_avatar_explorer.py`) is the single source of truth for whether the app works. Running it takes 30 seconds and catches regressions immediately.

### 2. Commit after every meaningful fix

After each change:
1. Run `python3 tests/test_avatar_explorer.py`
2. If 10/10 pass: `git add` + `git commit` with a descriptive message
3. Keep commits small and revertible

Do NOT batch multiple unrelated fixes into one commit.

### 3. Reuse proven patterns, don't create new ones

- Chrome launch: use the exact pattern from the test script, don't experiment with MCP tools
- CDP communication: use the `CDPClient` class or the raw websocket pattern from `investigate_official_tiles.py`
- Don't create new scripts when existing ones do the job

### 4. Reference the official implementation

When investigating performance or behavior:
- Launch Chrome with the proven pattern pointing to the official URL
- Use `investigate_official_tiles.py` as a template for CDP queries
- Actually READ the investigation results and apply findings to the code

### 5. Architecture before code

Before implementing, think about:
- What data structures are needed? (Map for tileInstances, Set for dirtyTabs)
- What's the rendering pipeline? (shared RiveFile → per-instance inputs → drawFrame)
- What gets created when? (lazy on tab switch, destroyed on dirty, preserved if clean)
- What's the main-thread budget? (animation runs at 60fps, tile creation must not block it)

## Git workflow

```bash
# After each fix:
python3 tests/test_avatar_explorer.py --port 8775 --debug-port 9228
git add <specific files>    # NEVER git add -A / git add .
git commit -m "type: brief description"
```

# Duolingo Avatar Creator

Reverse-engineered Duolingo avatar editor using Rive runtime.

Live avatar preview with per-tile Rive canvas instances, matching the official Duolingo avatar editor architecture.

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Start a local HTTP server
cd assets && python3 -m http.server 8769

# Open http://127.0.0.1:8769/avatar_explorer.html in a browser
```

The page needs to be served over HTTP (not `file://`) because the Rive runtime fetches the `.riv` file.

## Testing

```bash
# Run all tests (launches headless Chrome automatically)
python3 tests/test_avatar_explorer.py

# Custom ports
python3 tests/test_avatar_explorer.py --port 8775 --debug-port 9228

# Single test
python3 tests/test_avatar_explorer.py --test 3

# Keep browser open after tests
python3 tests/test_avatar_explorer.py --keep
```

Requirements: `google-chrome` (Chromium), Python 3.10+, `websockets`, `Pillow`.

## CDP Investigation

To examine a live page (e.g. the official Duolingo editor) via Chrome DevTools Protocol:

```bash
python3 scripts/cdp_investigate.py --port 9222
python3 scripts/cdp_investigate.py --interactive  # live JS REPL
```

## Project Structure

```
crawler/
├── assets/
│   ├── avatar_explorer.html       # Main application
│   ├── avatar_builder_config.json # Tab/tile configuration
│   └── avatar_builder_*.riv       # Rive animation files
├── src/cdp/
│   └── client.py                  # CDPClient — async CDP over WebSocket
├── tests/
│   └── test_avatar_explorer.py    # 10 integration tests
├── scripts/
│   ├── cdp_investigate.py         # CDP page investigation tool
│   └── exploration/               # Historical Rive API exploration scripts
├── CLAUDE.md                      # Detailed project documentation for AI assistants
├── requirements.txt
└── README.md
```

## Architecture

See [CLAUDE.md](CLAUDE.md) for detailed architecture decisions, anti-patterns, and lessons learned.
See [docs/architecture.md](docs/architecture.md) for the current end-to-end frontend, Worker, Generate, and Export flow.

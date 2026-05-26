#!/usr/bin/env python3
"""Generate and merge Codex manual labels for avatar semantic options."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:  # pragma: no cover - covered by CLI preflight.
    Image = None
    ImageChops = None
    ImageDraw = None

import semantic_catalog as catalog_lib

from src.cdp import CDPClient


PROJECT_DIR = catalog_lib.PROJECT_DIR
SITE_DIR = catalog_lib.SITE_DIR
OUTPUT_PATH = catalog_lib.OUTPUT_PATH
REVIEW_PATH = catalog_lib.REVIEW_PATH
CODEX_DIR = catalog_lib.CACHE_DIR / "codex"
TASKS_DIR = CODEX_DIR / "tasks"
IMAGES_DIR = CODEX_DIR / "images"
LABELS_DIR = CODEX_DIR / "labels"
REPORTS_DIR = CODEX_DIR / "reports"
DEFAULT_LABELS_PATH = LABELS_DIR / "labels.jsonl"
MERGE_REPORT_PATH = CODEX_DIR / "merge-report.json"
COMPARE_REPORT_PATH = CODEX_DIR / "compare-report.md"
REPORT_INDEX_PATH = REPORTS_DIR / "index.md"
TASK_MANIFEST_PATH = TASKS_DIR / "current-task-set.json"
REVIEW_THRESHOLD = 0.65
PANEL_SIZE = (384, 530)
LABEL_SCHEMA_VERSION = 2
TASK_SCHEMA_VERSION = 2
REVIEW_STATUSES = {"pending", "approved", "rejected"}
SMOKE_OPTION_IDS = [
    "FacialHair:1",
    "Headwear:10",
    "Glasses:1",
    "MainHair:48",
    "Expression:31",
]
REQUIRED_LABEL_FIELDS = {
    "schemaVersion",
    "optionId",
    "group",
    "tags",
    "attributes",
    "confidence",
    "needsReview",
    "reviewStatus",
    "evidence",
    "labelSource",
    "imagePath",
}


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def relpath(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_DIR))
    except ValueError:
        return str(resolved)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def option_maps() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    options = catalog_lib.enumerate_options(catalog_lib.load_config())
    return options, {option["optionId"]: option for option in options}


def split_option_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in re.split(r"[\s,]+", value.strip()):
            if item:
                result.append(item)
    return result


def select_task_options(args: argparse.Namespace, options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {option["optionId"]: option for option in options}
    selectors = int(bool(args.sample)) + int(args.smoke) + int(args.all_features) + int(bool(args.option_id))
    if selectors != 1:
        raise RuntimeError("Choose exactly one selector: --sample, --smoke, --all-features, or --option-id.")

    if args.smoke:
        option_ids = SMOKE_OPTION_IDS
    elif args.all_features:
        selected = [option for option in options if option.get("kind") == "feature"]
        if args.group:
            selected = [option for option in selected if option.get("group") == args.group]
        return selected
    else:
        option_ids = [args.sample] if args.sample else split_option_ids(args.option_id)

    missing = sorted(option_id for option_id in option_ids if option_id not in by_id)
    if missing:
        raise RuntimeError(f"Unknown optionId: {', '.join(missing)}")
    selected = [by_id[option_id] for option_id in option_ids]
    non_features = [option["optionId"] for option in selected if option.get("kind") != "feature"]
    if non_features:
        raise RuntimeError(f"Codex labeling only accepts feature options: {', '.join(non_features)}")
    return selected


def baseline_state_for_option(option: dict[str, Any], default_state: dict[str, Any]) -> dict[str, Any]:
    state = dict(default_state)
    for requirement in option.get("requires", []):
        if requirement.get("notValue") == 0:
            state[requirement["state"]] = 1
    return state


def compare_paths(option_id: str) -> dict[str, Path]:
    safe_id = catalog_lib.safe_filename(option_id)
    return {
        "baseline": IMAGES_DIR / f"{safe_id}.baseline.png",
        "option": IMAGES_DIR / f"{safe_id}.option.png",
        "diff": IMAGES_DIR / f"{safe_id}.diff.png",
        "compare": IMAGES_DIR / f"{safe_id}.compare.png",
    }


def build_capture_records(options: list[dict[str, Any]], default_state: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for option in options:
        baseline_state = baseline_state_for_option(option, default_state)
        option_state = catalog_lib.build_capture_state(option, default_state)
        records.append({
            "option": option,
            "baselineState": baseline_state,
            "optionState": option_state,
            "paths": compare_paths(option["optionId"]),
        })
    return records


def require_pillow() -> None:
    if Image is None or ImageChops is None or ImageDraw is None:
        raise RuntimeError("Pillow is required. Install requirements.txt first.")


def image_from_data_url(data_url: str) -> Any:
    require_pillow()
    match = re.match(r"data:image/png;base64,(.+)", data_url or "")
    if not match:
        raise RuntimeError("canvas did not return a PNG data URL")
    return Image.open(BytesIO(base64.b64decode(match.group(1)))).convert("RGBA")


def panel_image(image: Any) -> Any:
    require_pillow()
    image = image.convert("RGBA")
    image.thumbnail(PANEL_SIZE, Image.Resampling.LANCZOS)
    panel = Image.new("RGBA", PANEL_SIZE, (255, 255, 255, 255))
    left = (PANEL_SIZE[0] - image.width) // 2
    top = (PANEL_SIZE[1] - image.height) // 2
    panel.alpha_composite(image, (left, top))
    return panel


def diff_panel(baseline: Any, option: Any) -> Any:
    require_pillow()
    baseline_rgb = baseline.convert("RGB")
    option_rgb = option.convert("RGB")
    raw_diff = ImageChops.difference(baseline_rgb, option_rgb)
    mask = raw_diff.convert("L").point(lambda value: 255 if value > 18 else 0)
    muted_option = Image.blend(option.convert("RGBA"), Image.new("RGBA", PANEL_SIZE, (255, 255, 255, 255)), 0.45)
    highlight = Image.new("RGBA", PANEL_SIZE, (255, 38, 38, 170))
    muted_option.alpha_composite(Image.composite(highlight, Image.new("RGBA", PANEL_SIZE, (0, 0, 0, 0)), mask))
    return muted_option


def write_compare_image(baseline_raw: Any, option_raw: Any, paths: dict[str, Path]) -> None:
    require_pillow()
    paths["baseline"].parent.mkdir(parents=True, exist_ok=True)
    baseline = panel_image(baseline_raw)
    option = panel_image(option_raw)
    diff = diff_panel(baseline, option)

    baseline.save(paths["baseline"], "PNG")
    option.save(paths["option"], "PNG")
    diff.save(paths["diff"], "PNG")

    gutter = 16
    header = 34
    width = PANEL_SIZE[0] * 3 + gutter * 4
    height = PANEL_SIZE[1] + header + gutter
    combined = Image.new("RGBA", (width, height), (248, 249, 251, 255))
    draw = ImageDraw.Draw(combined)
    labels = ["baseline", "option", "diff"]
    panels = [baseline, option, diff]
    for index, panel in enumerate(panels):
        x = gutter + index * (PANEL_SIZE[0] + gutter)
        draw.text((x, 10), labels[index], fill=(31, 41, 55, 255))
        combined.alpha_composite(panel, (x, header))
        draw.rectangle((x, header, x + PANEL_SIZE[0] - 1, header + PANEL_SIZE[1] - 1), outline=(209, 213, 219, 255))
    combined.save(paths["compare"], "PNG")


async def wait_for_avatar_ready(cdp: CDPClient) -> None:
    for _ in range(60):
        ready = await cdp.evaluate(
            "window.__avatarTestHooks?.isReady?.() === true && window.__avatarTestHooks?.isSemanticCatalogReady?.() === true"
        )
        if ready:
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("Avatar editor did not become ready for Codex screenshot capture")


def metric_round(value: float) -> float:
    return round(float(value), 2)


def capture_attempt_metrics(result: dict[str, Any], elapsed_ms: float, strict: bool) -> dict[str, Any]:
    return {
        "strict": strict,
        "timingMs": metric_round(elapsed_ms),
        "hookTimingMs": metric_round(result.get("timingMs", 0)),
        "stable": bool(result.get("stable")),
        "frameCount": int(result.get("frameCount") or 0),
        "fallbackUsed": bool(result.get("fallbackUsed")),
    }


def capture_public_metrics(
    result: dict[str, Any],
    elapsed_ms: float,
    fallback_used: bool,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "timingMs": metric_round(elapsed_ms),
        "hookTimingMs": metric_round(result.get("timingMs", 0)),
        "stable": bool(result.get("stable")),
        "frameCount": int(result.get("frameCount") or 0),
        "fallbackUsed": fallback_used,
        "attemptCount": len(attempts),
        "attempts": attempts,
    }


def strip_capture_data_url(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "dataUrl"}


async def capture_state_attempt(cdp: CDPClient, state: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    result = await cdp.evaluate_async(f"""
        (async function() {{
            const hook = window.__avatarTestHooks && window.__avatarTestHooks.captureAvatarState;
            if (typeof hook !== 'function') {{
                throw new Error('captureAvatarState test hook is not available');
            }}
            return await hook({compact_json(state)}, {{ strict: {str(strict).lower()} }});
        }})()
    """)
    if not isinstance(result, dict) or not result.get("dataUrl"):
        raise RuntimeError("captureAvatarState did not return a PNG data URL")
    return result


async def capture_state(cdp: CDPClient, state: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    attempt_started = time.perf_counter()
    result = await capture_state_attempt(cdp, state, strict=False)
    attempts = [
        capture_attempt_metrics(result, (time.perf_counter() - attempt_started) * 1000, strict=False)
    ]
    fallback_used = False
    if not result.get("stable"):
        fallback_used = True
        attempt_started = time.perf_counter()
        result = await capture_state_attempt(cdp, state, strict=True)
        attempts.append(capture_attempt_metrics(result, (time.perf_counter() - attempt_started) * 1000, strict=True))
        if not result.get("stable"):
            raise RuntimeError(
                f"captureAvatarState remained unstable after strict fallback: {strip_capture_data_url(result)}"
            )

    elapsed_ms = (time.perf_counter() - started) * 1000
    return image_from_data_url(result["dataUrl"]), capture_public_metrics(result, elapsed_ms, fallback_used, attempts)


async def capture_compare_images_async(records: list[dict[str, Any]], args: argparse.Namespace) -> None:
    require_pillow()
    chrome_exec = catalog_lib.find_chrome_exec(args.chrome_exec)
    if not chrome_exec:
        raise RuntimeError(
            "Chrome/Chromium is required. Run `npx playwright install --with-deps chromium` or set CHROME_EXEC."
        )

    missing = [
        record for record in records
        if not args.resume or not all(path.exists() for path in record["paths"].values())
    ]
    if not missing:
        print(f"Reused existing Codex compare images for {len(records)} option(s)")
        return

    catalog_lib.run_site_build()
    http_port = args.port or catalog_lib.find_free_port()
    debug_port = args.debug_port or catalog_lib.find_free_port()
    http_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(http_port)],
        cwd=SITE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cdp: CDPClient | None = None
    chrome_proc: subprocess.Popen[str] | None = None
    with tempfile.TemporaryDirectory(prefix="avatar-semantic-codex-", ignore_cleanup_errors=True) as user_data_dir:
        try:
            chrome_proc = subprocess.Popen(
                [
                    chrome_exec,
                    f"--remote-debugging-port={debug_port}",
                    "--remote-debugging-address=127.0.0.1",
                    f"--user-data-dir={user_data_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1440,1200",
                    f"http://127.0.0.1:{http_port}/index.html",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            ws_url = catalog_lib.wait_for_debug_page(debug_port, http_port)
            cdp = CDPClient(ws_url)
            await cdp.connect()
            await cdp.send("Runtime.enable")
            await cdp.send("Page.enable")
            await wait_for_avatar_ready(cdp)
            captured_count = 0
            capture_started = time.perf_counter()
            fallback_states = 0
            for record in missing:
                option_started = time.perf_counter()
                baseline, baseline_metrics = await capture_state(cdp, record["baselineState"])
                option, option_metrics = await capture_state(cdp, record["optionState"])
                write_compare_image(baseline, option, record["paths"])
                total_ms = (time.perf_counter() - option_started) * 1000
                fallback_states += int(bool(baseline_metrics.get("fallbackUsed")))
                fallback_states += int(bool(option_metrics.get("fallbackUsed")))
                record["captureMetrics"] = {
                    "totalMs": metric_round(total_ms),
                    "baseline": baseline_metrics,
                    "option": option_metrics,
                }
                captured_count += 1
            if captured_count:
                elapsed_ms = (time.perf_counter() - capture_started) * 1000
                print(
                    "Captured "
                    f"{captured_count} Codex compare image set(s) in {metric_round(elapsed_ms)} ms "
                    f"(avg {metric_round(elapsed_ms / captured_count)} ms/option, "
                    f"fallbackStates={fallback_states})"
                )
            else:
                print(f"Reused existing Codex compare images for {len(records)} option(s)")
        finally:
            if cdp:
                await cdp.close()
            if chrome_proc:
                chrome_proc.terminate()
            http_proc.terminate()
            if chrome_proc:
                try:
                    chrome_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    chrome_proc.kill()
            try:
                http_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                http_proc.kill()


def task_prefix(args: argparse.Namespace) -> str:
    if args.sample:
        return f"sample-{catalog_lib.safe_filename(args.sample)}"
    if args.smoke:
        return "smoke"
    if args.option_id:
        return "custom"
    return "features"


def summarize_capture_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [
        record.get("captureMetrics")
        for record in records
        if isinstance(record.get("captureMetrics"), dict)
    ]
    total_ms = sum(float(item.get("totalMs") or 0) for item in metrics)
    fallback_states = 0
    unstable_states = 0
    for item in metrics:
        for key in ("baseline", "option"):
            state_metrics = item.get(key) if isinstance(item.get(key), dict) else {}
            fallback_states += int(bool(state_metrics.get("fallbackUsed")))
            unstable_states += int(not bool(state_metrics.get("stable", True)))
    captured_count = len(metrics)
    return {
        "capturedOptionCount": captured_count,
        "skippedOptionCount": len(records) - captured_count,
        "totalMs": metric_round(total_ms),
        "avgOptionMs": metric_round(total_ms / captured_count) if captured_count else None,
        "fallbackStateCount": fallback_states,
        "unstableStateCount": unstable_states,
    }


def task_option_record(record: dict[str, Any]) -> dict[str, Any]:
    option = record["option"]
    paths = record["paths"]
    result = {
        "optionId": option["optionId"],
        "state": option["state"],
        "value": option["value"],
        "group": option["group"],
        "tab": option["tab"],
        "section": option["section"],
        "index": option["index"],
        "referenceTags": option.get("tags", []),
        "currentTags": option.get("tags", []),
        "imagePath": relpath(paths["compare"]),
        "sourceImages": {
            "baseline": relpath(paths["baseline"]),
            "option": relpath(paths["option"]),
            "diff": relpath(paths["diff"]),
        },
        "baselineState": record["baselineState"],
        "optionState": record["optionState"],
        "outputTemplate": {
            "schemaVersion": LABEL_SCHEMA_VERSION,
            "optionId": option["optionId"],
            "group": option["group"],
            "tags": ["open visual tags generated from the image"],
            "attributes": {
                "dimensionName": "dimension value, array, number, boolean, or null",
            },
            "confidence": "0..1",
            "needsReview": False,
            "reviewStatus": "pending",
            "evidence": "short visual evidence",
            "labelSource": "codex_manual",
            "imagePath": relpath(paths["compare"]),
        },
    }
    if isinstance(record.get("captureMetrics"), dict):
        result["captureMetrics"] = record["captureMetrics"]
    return result


def write_task_batches(records: list[dict[str, Any]], args: argparse.Namespace) -> list[Path]:
    batch_size = args.batch_size
    if batch_size < 1:
        raise RuntimeError("--batch-size must be at least 1")

    prefix = task_prefix(args)
    task_paths = []
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    config = catalog_lib.load_config()
    source_version = config["avatarBuilderConfig"].get("riveFileVersion", "")
    for index in range(0, len(records), batch_size):
        batch_number = index // batch_size + 1
        batch = records[index:index + batch_size]
        batch_id = f"{prefix}-{batch_number:03d}"
        labels_path = LABELS_DIR / f"{batch_id}.jsonl"
        task = {
            "schemaVersion": TASK_SCHEMA_VERSION,
            "taskType": "codex_open_semantic_labeling",
            "batchId": batch_id,
            "createdAt": created_at,
            "sourceVersion": source_version,
            "instructions": [
                "Inspect each compare image: baseline, option, and diff.",
                "Return JSONL only, one object per option.",
                "Generate open visual tags. referenceTags/currentTags are examples only and do not limit the output.",
                "Use attributes to capture multi-dimensional visual traits such as length, shape, coverage, style, emotion, position, or size.",
                "Set reviewStatus to pending unless a human reviewer has explicitly approved or rejected this row.",
                "Set needsReview true when the visual difference is too small or ambiguous.",
            ],
            "labelsPath": relpath(labels_path),
            "reportPath": relpath(REPORTS_DIR / f"{batch_id}.md"),
            "captureMetrics": summarize_capture_metrics(batch),
            "options": [task_option_record(record) for record in batch],
        }
        path = TASKS_DIR / f"{batch_id}.json"
        write_json(path, task)
        task_paths.append(path)

    manifest = {
        "schemaVersion": LABEL_SCHEMA_VERSION,
        "createdAt": created_at,
        "taskFiles": [relpath(path) for path in task_paths],
        "optionIds": [record["option"]["optionId"] for record in records],
        "captureMetrics": summarize_capture_metrics(records),
    }
    write_json(TASK_MANIFEST_PATH, manifest)
    return task_paths


def run_tasks(args: argparse.Namespace) -> int:
    config = catalog_lib.load_config()
    options = catalog_lib.enumerate_options(config)
    selected = select_task_options(args, options)
    if not selected:
        raise RuntimeError("No feature options matched the requested selector.")
    default_state = config["avatarBuilderConfig"].get("defaultBuiltAvatarState", {})
    records = build_capture_records(selected, default_state)
    asyncio.run(capture_compare_images_async(records, args))
    task_paths = write_task_batches(records, args)
    print(f"Wrote {len(task_paths)} Codex task package(s)")
    for path in task_paths:
        print(f"Wrote {relpath(path)}")
    print(f"Wrote {relpath(TASK_MANIFEST_PATH)}")
    return 0


def parse_jsonl(path: Path) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    errors: list[str] = []
    if not path.exists():
        return rows, [f"input file not found: {path}"]
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"line {line_no}: JSON parse failed: {error}")
            continue
        if not isinstance(value, dict):
            errors.append(f"line {line_no}: JSONL row must be an object")
            continue
        rows.append((line_no, value))
    return rows, errors


def load_task_files(args: argparse.Namespace) -> tuple[list[Path], list[str]]:
    warnings: list[str] = []
    if args.task:
        return [Path(path) for path in args.task], warnings
    if TASK_MANIFEST_PATH.exists():
        manifest = read_json(TASK_MANIFEST_PATH)
        task_files = [PROJECT_DIR / rel for rel in manifest.get("taskFiles", [])]
        return task_files, warnings
    task_files = sorted(TASKS_DIR.glob("*.json"))
    task_files = [path for path in task_files if path.name != TASK_MANIFEST_PATH.name]
    if task_files:
        warnings.append("current-task-set.json not found; using every task JSON in the task directory")
    return task_files, warnings


def load_task_scope(args: argparse.Namespace) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    task_files, warnings = load_task_files(args)
    errors: list[str] = []
    task_options: dict[str, dict[str, Any]] = {}
    if not task_files:
        errors.append("No Codex task package found. Run `npm run semantic:codex:tasks` first or pass --task.")
        return task_options, errors, warnings
    for task_file in task_files:
        if not task_file.exists():
            errors.append(f"task file not found: {task_file}")
            continue
        try:
            task = read_json(task_file)
        except json.JSONDecodeError as error:
            errors.append(f"{task_file}: JSON parse failed: {error}")
            continue
        for option in task.get("options", []):
            option_id = option.get("optionId") if isinstance(option, dict) else None
            if not option_id:
                errors.append(f"{task_file}: task option missing optionId")
                continue
            if option_id in task_options:
                errors.append(f"duplicate optionId in task packages: {option_id}")
                continue
            task_options[option_id] = option
    return task_options, errors, warnings


def validate_label_row(
    line_no: int,
    label: dict[str, Any],
    enum_by_id: dict[str, dict[str, Any]],
    task_options: dict[str, dict[str, Any]],
    seen: set[str],
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    missing = REQUIRED_LABEL_FIELDS.difference(label)
    if missing:
        errors.append(f"line {line_no}: missing fields: {sorted(missing)}")
        return None, errors, warnings

    option_id = label.get("optionId")
    if not isinstance(option_id, str) or not option_id:
        errors.append(f"line {line_no}: optionId must be a non-empty string")
        return None, errors, warnings
    if option_id in seen:
        errors.append(f"line {line_no}: duplicate optionId: {option_id}")
    seen.add(option_id)
    option = enum_by_id.get(option_id)
    if not option:
        errors.append(f"line {line_no}: unknown optionId: {option_id}")
        return None, errors, warnings
    if option_id not in task_options:
        errors.append(f"line {line_no}: optionId is not in the current Codex task package: {option_id}")

    if label.get("schemaVersion") != LABEL_SCHEMA_VERSION:
        errors.append(f"line {line_no}: schemaVersion must be {LABEL_SCHEMA_VERSION}")
    if label.get("group") != option["group"]:
        errors.append(f"line {line_no}: group mismatch for {option_id}; expected {option['group']}")
    if label.get("labelSource") != "codex_manual":
        errors.append(f"line {line_no}: labelSource must be codex_manual")
    if not isinstance(label.get("needsReview"), bool):
        errors.append(f"line {line_no}: needsReview must be boolean")

    confidence = label.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        errors.append(f"line {line_no}: confidence must be a number from 0 to 1")

    tags = label.get("tags")
    if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) and tag for tag in tags):
        errors.append(f"line {line_no}: tags must be a non-empty string array")

    attributes = label.get("attributes")
    if not isinstance(attributes, dict) or isinstance(attributes, list):
        errors.append(f"line {line_no}: attributes must be an object")

    review_status = label.get("reviewStatus")
    if review_status not in REVIEW_STATUSES:
        errors.append(f"line {line_no}: reviewStatus must be one of {sorted(REVIEW_STATUSES)}")

    evidence = label.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        errors.append(f"line {line_no}: evidence must be a non-empty string")

    image_path = label.get("imagePath")
    if not isinstance(image_path, str) or not image_path:
        errors.append(f"line {line_no}: imagePath must be a non-empty string")
    else:
        task_image = task_options.get(option_id, {}).get("imagePath")
        if task_image and image_path != task_image:
            warnings.append(f"line {line_no}: imagePath differs from task package for {option_id}")
        if not (PROJECT_DIR / image_path).exists():
            warnings.append(f"line {line_no}: imagePath does not exist locally: {image_path}")

    if errors:
        return None, errors, warnings
    normalized = {
        "schemaVersion": LABEL_SCHEMA_VERSION,
        "optionId": option_id,
        "group": option["group"],
        "tags": list(dict.fromkeys(tags)),
        "attributes": attributes,
        "confidence": float(confidence),
        "needsReview": bool(label["needsReview"]),
        "reviewStatus": review_status,
        "evidence": evidence.strip()[:240],
        "labelSource": "codex_manual",
        "imagePath": image_path,
    }
    return normalized, errors, warnings


def validate_labels(
    input_path: Path,
    enum_by_id: dict[str, dict[str, Any]],
    task_options: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows, errors = parse_jsonl(input_path)
    warnings: list[str] = []
    labels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_no, row in rows:
        label, row_errors, row_warnings = validate_label_row(line_no, row, enum_by_id, task_options, seen)
        errors.extend(row_errors)
        warnings.extend(row_warnings)
        if label:
            labels.append(label)
    return labels, errors, warnings


def apply_codex_labels(catalog: dict[str, Any], labels: list[dict[str, Any]]) -> int:
    by_id = {
        option.get("optionId"): option
        for option in catalog.get("options", [])
        if isinstance(option, dict) and option.get("optionId")
    }
    changed = 0
    for label in labels:
        option = by_id.get(label["optionId"])
        if not option:
            continue
        option["tags"] = label["tags"]
        option["confidence"] = label["confidence"]
        option["needsReview"] = label["needsReview"] or label["confidence"] < REVIEW_THRESHOLD or "unclear" in label["tags"]
        option["labelSource"] = "codex_manual"
        option["evidence"] = label["evidence"]
        option["imagePath"] = label["imagePath"]
        option.pop("extraTags", None)
        option.pop("attributes", None)
        option.pop("reviewStatus", None)
        changed += 1
    catalog["labeling"] = {
        **(catalog.get("labeling") or {}),
        "mode": "deterministic_seed_with_codex_manual",
        "reviewThreshold": REVIEW_THRESHOLD,
    }
    return changed


def write_merge_report(report: dict[str, Any]) -> None:
    write_json(MERGE_REPORT_PATH, report)


def run_merge(args: argparse.Namespace) -> int:
    _, enum_by_id = option_maps()
    task_options, task_errors, task_warnings = load_task_scope(args)
    labels, label_errors, label_warnings = validate_labels(Path(args.input), enum_by_id, task_options)
    errors = task_errors + label_errors
    warnings = task_warnings + label_warnings
    report = {
        "status": "failed" if errors else "ok",
        "input": str(args.input),
        "checkOnly": args.check_only,
        "labelCount": len(labels),
        "taskOptionCount": len(task_options),
        "optionIds": [label["optionId"] for label in labels],
        "errors": errors,
        "warnings": warnings,
    }

    if errors:
        write_merge_report(report)
        for error in errors:
            print(f"codex semantic merge error: {error}", file=sys.stderr)
        print(f"Wrote {relpath(MERGE_REPORT_PATH)}", file=sys.stderr)
        return 1

    unapproved = [label["optionId"] for label in labels if label.get("reviewStatus") != "approved"]
    if unapproved:
        report["status"] = "failed"
        report["errors"] = [
            f"merge requires reviewStatus=approved; pending or rejected optionIds: {', '.join(unapproved)}"
        ]
        write_merge_report(report)
        for error in report["errors"]:
            print(f"codex semantic merge error: {error}", file=sys.stderr)
        print(f"Wrote {relpath(MERGE_REPORT_PATH)}", file=sys.stderr)
        return 1

    catalog = read_json(OUTPUT_PATH)
    changed = apply_codex_labels(catalog, labels)
    catalog_errors = catalog_lib.validate_catalog(catalog, catalog_lib.load_config())
    if catalog_errors:
        report["status"] = "failed"
        report["errors"] = catalog_errors
        write_merge_report(report)
        for error in catalog_errors:
            print(f"codex semantic merge error: {error}", file=sys.stderr)
        return 1

    report["mergedCount"] = changed
    if not args.check_only:
        OUTPUT_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        catalog_lib.write_review(catalog)
    write_merge_report(report)
    print(f"Validated {len(labels)} Codex label(s)")
    if args.check_only:
        print("Check-only mode: catalog was not modified")
    else:
        print(f"Wrote {relpath(OUTPUT_PATH)}")
        print(f"Wrote {relpath(REVIEW_PATH)}")
    print(f"Wrote {relpath(MERGE_REPORT_PATH)}")
    return 0


def labels_from_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows, errors = parse_jsonl(path)
    if errors:
        raise RuntimeError("; ".join(errors))
    return {row["optionId"]: row for _, row in rows if isinstance(row.get("optionId"), str)}


def labels_from_json(path: Path) -> dict[str, dict[str, Any]]:
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("options"), list):
        return {item["optionId"]: item for item in data["options"] if isinstance(item, dict) and item.get("optionId")}
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return {item["optionId"]: item for item in data["results"] if isinstance(item, dict) and item.get("optionId")}
    if isinstance(data, list):
        return {item["optionId"]: item for item in data if isinstance(item, dict) and item.get("optionId")}
    raise RuntimeError(f"Unsupported comparison input: {path}")


def load_label_map(path: Path) -> dict[str, dict[str, Any]]:
    if path.suffix == ".jsonl":
        return labels_from_jsonl(path)
    return labels_from_json(path)


def tag_set(item: dict[str, Any] | None) -> set[str]:
    if not item:
        return set()
    tags = item.get("tags")
    return set(tags if isinstance(tags, list) else [])


def run_compare(args: argparse.Namespace) -> int:
    codex = load_label_map(Path(args.codex))
    cloudflare = load_label_map(Path(args.cloudflare))
    all_ids = sorted(set(codex) | set(cloudflare))
    mismatches = []
    only_codex = []
    only_cloudflare = []
    for option_id in all_ids:
        if option_id not in cloudflare:
            only_codex.append(option_id)
            continue
        if option_id not in codex:
            only_cloudflare.append(option_id)
            continue
        codex_tags = tag_set(codex[option_id])
        cloudflare_tags = tag_set(cloudflare[option_id])
        if codex_tags != cloudflare_tags:
            mismatches.append((option_id, sorted(codex_tags), sorted(cloudflare_tags)))

    lines = [
        "# Codex / Cloudflare 语义标注对比",
        "",
        f"- Codex 输入: `{args.codex}`",
        f"- Cloudflare 输入: `{args.cloudflare}`",
        f"- Codex 数量: `{len(codex)}`",
        f"- Cloudflare 数量: `{len(cloudflare)}`",
        f"- tag 不一致: `{len(mismatches)}`",
        f"- 仅 Codex: `{len(only_codex)}`",
        f"- 仅 Cloudflare: `{len(only_cloudflare)}`",
        "",
        "## tag 差异",
        "",
        "| optionId | Codex tags | Cloudflare tags |",
        "| --- | --- | --- |",
    ]
    if mismatches:
        for option_id, codex_tags, cloudflare_tags in mismatches:
            lines.append(f"| `{option_id}` | {', '.join(codex_tags)} | {', '.join(cloudflare_tags)} |")
    else:
        lines.append("| - | - | - |")
    if only_codex:
        lines.extend(["", "## 仅 Codex", ""])
        lines.extend(f"- `{option_id}`" for option_id in only_codex)
    if only_cloudflare:
        lines.extend(["", "## 仅 Cloudflare", ""])
        lines.extend(f"- `{option_id}`" for option_id in only_cloudflare)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {relpath(output)}")
    return 0


def markdown_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(value, bool):
        text = str(value).lower()
    else:
        text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def markdown_link(target: Path, base_dir: Path) -> str:
    return os.path.relpath(target, start=base_dir).replace(os.sep, "/")


def capture_fallback_count(metrics: dict[str, Any] | None) -> int:
    if not isinstance(metrics, dict):
        return 0
    return sum(
        int(bool((metrics.get(key) if isinstance(metrics.get(key), dict) else {}).get("fallbackUsed")))
        for key in ("baseline", "option")
    )


def capture_summary_cell(metrics: dict[str, Any] | None) -> str:
    if not isinstance(metrics, dict) or not metrics:
        return "not captured"
    captured = metrics.get("capturedOptionCount")
    skipped = metrics.get("skippedOptionCount")
    total_ms = metrics.get("totalMs")
    avg_ms = metrics.get("avgOptionMs")
    fallback = metrics.get("fallbackStateCount")
    return (
        f"captured={captured}, skipped={skipped}, "
        f"totalMs={total_ms}, avgOptionMs={avg_ms}, fallbackStates={fallback}"
    )


def task_label_path(task: dict[str, Any]) -> Path:
    labels_path = task.get("labelsPath")
    if isinstance(labels_path, str) and labels_path:
        return PROJECT_DIR / labels_path
    batch_id = str(task.get("batchId") or "labels")
    return LABELS_DIR / f"{batch_id}.jsonl"


def task_report_path(task: dict[str, Any]) -> Path:
    report_path = task.get("reportPath")
    if isinstance(report_path, str) and report_path:
        return PROJECT_DIR / report_path
    batch_id = str(task.get("batchId") or "batch")
    return REPORTS_DIR / f"{batch_id}.md"


def validated_labels_for_task(task: dict[str, Any], labels_path: Path) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    options = task.get("options") if isinstance(task.get("options"), list) else []
    task_options = {
        option.get("optionId"): option
        for option in options
        if isinstance(option, dict) and isinstance(option.get("optionId"), str)
    }
    _, enum_by_id = option_maps()
    labels, errors, warnings = validate_labels(labels_path, enum_by_id, task_options)
    return {label["optionId"]: label for label in labels}, errors, warnings


def write_batch_report(task_path: Path, task: dict[str, Any]) -> dict[str, Any]:
    batch_id = str(task.get("batchId") or task_path.stem)
    report_path = task_report_path(task)
    labels_path = task_label_path(task)
    options = [option for option in task.get("options", []) if isinstance(option, dict)]
    capture_metrics = task.get("captureMetrics") if isinstance(task.get("captureMetrics"), dict) else {}
    labels_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    warnings: list[str] = []
    if labels_path.exists():
        labels_by_id, errors, warnings = validated_labels_for_task(task, labels_path)
    else:
        warnings.append(f"labels file not found: {relpath(labels_path)}")

    status_counts = {status: 0 for status in sorted(REVIEW_STATUSES)}
    missing_count = 0
    group_counts: dict[str, int] = {}
    for option in options:
        group = str(option.get("group") or "")
        if group:
            group_counts[group] = group_counts.get(group, 0) + 1
        label = labels_by_id.get(option.get("optionId"))
        if not label:
            missing_count += 1
            continue
        status = label.get("reviewStatus")
        if status in status_counts:
            status_counts[status] += 1

    lines = [
        f"# Codex Semantic Batch Report: {batch_id}",
        "",
        f"- task: `{relpath(task_path)}`",
        f"- labels: `{relpath(labels_path)}`",
        f"- optionCount: `{len(options)}`",
        f"- labeledCount: `{len(labels_by_id)}`",
        f"- missingCount: `{missing_count}`",
        f"- reviewStatus: `pending={status_counts.get('pending', 0)}`, `approved={status_counts.get('approved', 0)}`, `rejected={status_counts.get('rejected', 0)}`",
        f"- captureMetrics: `{capture_summary_cell(capture_metrics)}`",
        "",
    ]
    if errors:
        lines.extend(["## 校验错误", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")
    if warnings:
        lines.extend(["## 提示", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    lines.extend([
        "## 索引",
        "",
        "| optionId | group | reviewStatus | confidence | captureMs | fallback | tags |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for option in options:
        option_id = str(option.get("optionId") or "")
        label = labels_by_id.get(option_id)
        option_capture = option.get("captureMetrics") if isinstance(option.get("captureMetrics"), dict) else None
        lines.append(
            f"| `{option_id}` | `{markdown_cell(option.get('group'))}` | "
            f"`{markdown_cell(label.get('reviewStatus') if label else 'missing')}` | "
            f"`{markdown_cell(label.get('confidence') if label else '')}` | "
            f"`{markdown_cell(option_capture.get('totalMs') if option_capture else 'not captured')}` | "
            f"`{capture_fallback_count(option_capture)}` | "
            f"{markdown_cell(label.get('tags') if label else '')} |"
        )

    lines.extend(["", "## 详情", ""])
    for option in options:
        option_id = str(option.get("optionId") or "")
        label = labels_by_id.get(option_id)
        image_path = option.get("imagePath") or (label or {}).get("imagePath")
        lines.extend([f"### `{option_id}`", ""])
        if isinstance(image_path, str) and image_path:
            image_abs = PROJECT_DIR / image_path
            lines.append(f'<img src="{markdown_link(image_abs, report_path.parent)}" alt="{option_id} compare" width="100%">')
            lines.append("")
        lines.extend([
            "| 字段 | 内容 |",
            "| --- | --- |",
            f"| group | `{markdown_cell(option.get('group'))}` |",
            f"| referenceTags | {markdown_cell(option.get('referenceTags') or option.get('currentTags') or [])} |",
            f"| reviewStatus | `{markdown_cell(label.get('reviewStatus') if label else 'missing')}` |",
            f"| confidence | `{markdown_cell(label.get('confidence') if label else '')}` |",
            f"| needsReview | `{markdown_cell(label.get('needsReview') if label else '')}` |",
            f"| tags | {markdown_cell(label.get('tags') if label else [])} |",
            f"| attributes | {markdown_cell(label.get('attributes') if label else {})} |",
            f"| evidence | {markdown_cell(label.get('evidence') if label else '')} |",
            f"| captureMetrics | {markdown_cell(option.get('captureMetrics') or {})} |",
            "",
            "审核备注：",
            "",
            "- [ ] approved",
            "- [ ] rejected",
            "- notes:",
            "",
        ])

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "batchId": batch_id,
        "taskPath": relpath(task_path),
        "labelsPath": relpath(labels_path),
        "reportPath": relpath(report_path),
        "optionCount": len(options),
        "labeledCount": len(labels_by_id),
        "missingCount": missing_count,
        "statusCounts": status_counts,
        "groupCounts": group_counts,
        "captureMetrics": capture_metrics,
        "errorCount": len(errors),
        "warningCount": len(warnings),
    }


def run_report(args: argparse.Namespace) -> int:
    task_files, warnings = load_task_files(args)
    if not task_files:
        raise RuntimeError("No Codex task package found. Run `npm run semantic:codex:tasks` first or pass --task.")

    summaries = []
    errors = []
    for task_file in task_files:
        try:
            task = read_json(task_file)
        except json.JSONDecodeError as error:
            errors.append(f"{task_file}: JSON parse failed: {error}")
            continue
        summaries.append(write_batch_report(task_file, task))

    total_options = sum(item["optionCount"] for item in summaries)
    total_labeled = sum(item["labeledCount"] for item in summaries)
    total_missing = sum(item["missingCount"] for item in summaries)
    total_status = {status: sum(item["statusCounts"].get(status, 0) for item in summaries) for status in sorted(REVIEW_STATUSES)}
    total_capture = {
        "capturedOptionCount": sum((item.get("captureMetrics") or {}).get("capturedOptionCount") or 0 for item in summaries),
        "skippedOptionCount": sum((item.get("captureMetrics") or {}).get("skippedOptionCount") or 0 for item in summaries),
        "totalMs": metric_round(sum((item.get("captureMetrics") or {}).get("totalMs") or 0 for item in summaries)),
        "fallbackStateCount": sum((item.get("captureMetrics") or {}).get("fallbackStateCount") or 0 for item in summaries),
    }
    total_capture["avgOptionMs"] = (
        metric_round(total_capture["totalMs"] / total_capture["capturedOptionCount"])
        if total_capture["capturedOptionCount"]
        else None
    )
    group_counts: dict[str, int] = {}
    for item in summaries:
        for group, count in item["groupCounts"].items():
            group_counts[group] = group_counts.get(group, 0) + count

    lines = [
        "# Codex Semantic 标注审核索引",
        "",
        f"- generatedAt: `{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}`",
        f"- batchCount: `{len(summaries)}`",
        f"- optionCount: `{total_options}`",
        f"- labeledCount: `{total_labeled}`",
        f"- missingCount: `{total_missing}`",
        f"- reviewStatus: `pending={total_status.get('pending', 0)}`, `approved={total_status.get('approved', 0)}`, `rejected={total_status.get('rejected', 0)}`",
        f"- captureMetrics: `{capture_summary_cell(total_capture)}`",
        "",
        "## 批次索引",
        "",
        "| batch | task | labels | report | options | labeled | missing | captureMs | avgMs | fallback | pending | approved | rejected | errors | warnings |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in summaries:
        report_link = markdown_link(PROJECT_DIR / item["reportPath"], REPORT_INDEX_PATH.parent)
        item_capture = item.get("captureMetrics") or {}
        lines.append(
            f"| `{item['batchId']}` | `{item['taskPath']}` | `{item['labelsPath']}` | "
            f"[open]({report_link}) | `{item['optionCount']}` | `{item['labeledCount']}` | "
            f"`{item['missingCount']}` | `{item_capture.get('totalMs')}` | "
            f"`{item_capture.get('avgOptionMs')}` | `{item_capture.get('fallbackStateCount')}` | "
            f"`{item['statusCounts'].get('pending', 0)}` | "
            f"`{item['statusCounts'].get('approved', 0)}` | `{item['statusCounts'].get('rejected', 0)}` | "
            f"`{item['errorCount']}` | `{item['warningCount']}` |"
        )

    lines.extend(["", "## 分组统计", "", "| group | optionCount |", "| --- | --- |"])
    for group, count in sorted(group_counts.items()):
        lines.append(f"| `{group}` | `{count}` |")

    if warnings:
        lines.extend(["", "## 提示", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    if errors:
        lines.extend(["", "## 错误", ""])
        lines.extend(f"- {error}" for error in errors)

    REPORT_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_INDEX_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {relpath(REPORT_INDEX_PATH)}")
    for item in summaries:
        print(f"Wrote {item['reportPath']}")
    return 1 if errors else 0


def add_task_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sample", default="", help="Generate one task for this optionId")
    parser.add_argument("--smoke", action="store_true", help="Generate the 5-option smoke task package")
    parser.add_argument("--all-features", action="store_true", help="Generate task packages for every feature option")
    parser.add_argument("--option-id", action="append", default=[], help="Generate tasks for these optionIds; comma-separated values are allowed")
    parser.add_argument("--group", default="", help="Only include this semantic group with --all-features")
    parser.add_argument("--batch-size", type=int, default=10, help="Options per task package")
    parser.add_argument("--resume", action="store_true", help="Reuse existing compare images when present")
    parser.add_argument("--chrome-exec", default=None, help="Chrome/Chromium executable for screenshot capture")
    parser.add_argument("--port", type=int, default=0, help="HTTP port for screenshot capture")
    parser.add_argument("--debug-port", type=int, default=0, help="Chrome debug port for screenshot capture")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex semantic labeling helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    task_parser = subparsers.add_parser("tasks", help="Generate Codex task packages and compare images")
    add_task_args(task_parser)

    merge_parser = subparsers.add_parser("merge", help="Validate and merge Codex JSONL labels")
    merge_parser.add_argument("--input", default=str(DEFAULT_LABELS_PATH), help="Codex labels JSONL")
    merge_parser.add_argument("--task", action="append", default=[], help="Task package JSON to validate against; repeatable")
    merge_parser.add_argument("--check-only", action="store_true", help="Validate without modifying the catalog")

    compare_parser = subparsers.add_parser("compare", help="Compare Codex labels with Cloudflare labels")
    compare_parser.add_argument("--codex", required=True, help="Codex JSONL or catalog/report JSON")
    compare_parser.add_argument("--cloudflare", required=True, help="Cloudflare JSONL or catalog/report JSON")
    compare_parser.add_argument("--output", default=str(COMPARE_REPORT_PATH), help="Markdown report path")

    report_parser = subparsers.add_parser("report", help="Generate Codex batch reports and review index")
    report_parser.add_argument("--task", action="append", default=[], help="Task package JSON to report; repeatable")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "tasks":
            return run_tasks(args)
        if args.command == "merge":
            return run_merge(args)
        if args.command == "compare":
            return run_compare(args)
        if args.command == "report":
            return run_report(args)
    except RuntimeError as error:
        print(f"codex semantic error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

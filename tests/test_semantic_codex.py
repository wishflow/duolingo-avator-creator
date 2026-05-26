#!/usr/bin/env python3
"""Unit checks for Codex semantic labeling helpers."""

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import semantic_codex  # noqa: E402


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def task_file(tmp_path, option_id="FacialHair:1"):
    _, enum_by_id = semantic_codex.option_maps()
    option = enum_by_id[option_id]
    path = tmp_path / "task.json"
    write_json(path, {
        "schemaVersion": 2,
        "batchId": "test-001",
        "labelsPath": str(tmp_path / "labels.jsonl"),
        "options": [{
            "optionId": option["optionId"],
            "group": option["group"],
            "imagePath": ".cache/avatar-semantic/codex/images/FacialHair_1.compare.png",
            "referenceTags": option["tags"],
        }],
    })
    return path


def valid_label(**overrides):
    value = {
        "schemaVersion": 2,
        "optionId": "FacialHair:1",
        "group": "facial_hair",
        "tags": ["classic_mustache", "large_drooping_mustache"],
        "attributes": {
            "category": "mustache",
            "shape": ["large", "drooping"],
            "coverage": ["upper_lip"],
        },
        "confidence": 0.86,
        "needsReview": False,
        "reviewStatus": "pending",
        "evidence": "The option adds a large dark mustache above the mouth.",
        "labelSource": "codex_manual",
        "imagePath": ".cache/avatar-semantic/codex/images/FacialHair_1.compare.png",
    }
    value.update(overrides)
    return value


def validate_rows(tmp_path, rows, task_option_id="FacialHair:1"):
    _, enum_by_id = semantic_codex.option_maps()
    input_path = tmp_path / "labels.jsonl"
    write_jsonl(input_path, rows)
    task_path = task_file(tmp_path, task_option_id)
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task_options = {option["optionId"]: option for option in task["options"]}
    return semantic_codex.validate_labels(input_path, enum_by_id, task_options)


def test_validate_labels_accepts_open_tags_and_attributes(tmp_path):
    labels, errors, _ = validate_rows(tmp_path, [valid_label()])

    assert errors == []
    assert labels[0]["schemaVersion"] == 2
    assert labels[0]["tags"] == ["classic_mustache", "large_drooping_mustache"]
    assert labels[0]["attributes"]["category"] == "mustache"
    assert labels[0]["reviewStatus"] == "pending"


def test_validate_labels_requires_attributes(tmp_path):
    label = valid_label()
    del label["attributes"]

    _, errors, _ = validate_rows(tmp_path, [label])

    assert any("missing fields" in error and "attributes" in error for error in errors)


def test_validate_labels_rejects_invalid_review_status(tmp_path):
    _, errors, _ = validate_rows(tmp_path, [valid_label(reviewStatus="done")])

    assert any("reviewStatus must be one of" in error for error in errors)


def test_validate_labels_rejects_duplicate_option_id(tmp_path):
    _, errors, _ = validate_rows(tmp_path, [valid_label(), valid_label()])

    assert any("duplicate optionId" in error for error in errors)


def test_validate_labels_requires_current_task_scope(tmp_path):
    _, enum_by_id = semantic_codex.option_maps()
    input_path = tmp_path / "labels.jsonl"
    write_jsonl(input_path, [valid_label()])

    _, errors, _ = semantic_codex.validate_labels(input_path, enum_by_id, {})

    assert any("not in the current Codex task package" in error for error in errors)


def test_merge_rejects_pending_labels(tmp_path):
    input_path = tmp_path / "labels.jsonl"
    write_jsonl(input_path, [valid_label(reviewStatus="pending")])
    task_path = task_file(tmp_path)

    code = semantic_codex.run_merge(Namespace(input=str(input_path), task=[str(task_path)], check_only=True))

    assert code == 1


def test_merge_accepts_approved_labels_in_check_only(tmp_path):
    input_path = tmp_path / "labels.jsonl"
    write_jsonl(input_path, [valid_label(reviewStatus="approved")])
    task_path = task_file(tmp_path)

    code = semantic_codex.run_merge(Namespace(input=str(input_path), task=[str(task_path)], check_only=True))

    assert code == 0


def main():
    tests = [
        test_validate_labels_accepts_open_tags_and_attributes,
        test_validate_labels_requires_attributes,
        test_validate_labels_rejects_invalid_review_status,
        test_validate_labels_rejects_duplicate_option_id,
        test_validate_labels_requires_current_task_scope,
        test_merge_rejects_pending_labels,
        test_merge_accepts_approved_labels_in_check_only,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
    print("Codex semantic helper checks passed")


if __name__ == "__main__":
    main()

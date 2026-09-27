"""Evaluation runner for the code reviewer agent against known bug injections.

How to run:
    From the project root (/home/gpuserver1/projects/code-reviewer):
        uv run python -m eval.run_eval
    or
        python -m eval.run_eval
    or
        python eval/run_eval.py
"""

import json
import os
import re
import sys
from pathlib import Path

# Ensure src/ is on sys.path for direct script execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Ensure ALLOWED_REPO_ROOT is set so mcp_server allows inspecting the target repo
os.environ.setdefault("ALLOWED_REPO_ROOT", "/home/gpuserver1")

from code_reviewer.agent import extract_findings, run_review
from code_reviewer.models import Finding

REPO_UNDER_TEST = "/home/gpuserver1/P-T_backend_ts"
BASE_COMMIT = "f6b9bbb666d58640e1af8a47c3587a504f3b76a7"
HEAD_COMMIT = "8e3a3472850545d2751597093d0b78a53775ff20"


def normalize_path(finding_file: str, repo_root: str) -> str:
    """Strips repo_root (and any leading/trailing slashes) from finding_file if present,
    so both ground truth and findings compare as repo-relative paths.
    Handles both absolute paths like '/abs/path/to/repo/src/x.ts' -> 'src/x.ts'
    and already-relative paths unchanged."""
    clean_finding = finding_file.strip()
    clean_root = repo_root.rstrip("/")
    if clean_finding.startswith(clean_root):
        rel = clean_finding[len(clean_root) :]
        return rel.lstrip("/")
    return clean_finding.lstrip("/")


def parse_line_number(line_str: str | int | None) -> int | None:
    """Extracts a usable line number from a Finding's line field (e.g. '24', '18-21').
    For a range, uses the FIRST number found. Returns None if unparseable."""
    if line_str is None:
        return None
    match = re.search(r"\d+", str(line_str))
    if match:
        return int(match.group())
    return None


def match_findings(
    findings: list[Finding], ground_truth: list[dict], repo_root: str
) -> dict:
    """Match extracted findings against ground truth entries.

    Matching logic:
    A finding matches a ground truth entry if:
      normalize_path(finding.file, repo_root) == ground_truth["file"]
      AND abs(parse_line_number(finding.line) - ground_truth["line"]) <= 3
    If either line number is unparseable, it is treated as no match.
    """
    matched_bugs = []
    missed_bugs = []
    matched_finding_indices = set()

    for gt in ground_truth:
        gt_file = gt.get("file", "")
        gt_line = parse_line_number(gt.get("line"))

        match_found = None
        for idx, finding in enumerate(findings):
            if idx in matched_finding_indices:
                continue
            norm_f_file = normalize_path(finding.file, repo_root)
            f_line = parse_line_number(finding.line)

            if norm_f_file == gt_file and f_line is not None and gt_line is not None:
                if abs(f_line - gt_line) <= 3:
                    match_found = (idx, finding)
                    break

        if match_found is not None:
            idx, finding = match_found
            matched_finding_indices.add(idx)
            matched_entry = dict(gt)
            matched_entry["matched_finding"] = (
                finding.model_dump() if hasattr(finding, "model_dump") else dict(finding)
            )
            matched_bugs.append(matched_entry)
        else:
            missed_bugs.append(dict(gt))

    false_positives = [
        finding.model_dump() if hasattr(finding, "model_dump") else dict(finding)
        for idx, finding in enumerate(findings)
        if idx not in matched_finding_indices
    ]

    total_gt = len(ground_truth)
    total_findings = len(findings)

    recall = len(matched_bugs) / total_gt if total_gt > 0 else 1.0

    if total_findings == 0:
        precision = 1.0 if total_gt == 0 else 0.0
    else:
        precision = (total_findings - len(false_positives)) / total_findings

    return {
        "matched_bugs": matched_bugs,
        "missed_bugs": missed_bugs,
        "false_positives": false_positives,
        "recall": recall,
        "precision": precision,
    }


def run_single_eval(
    repo_path: str = REPO_UNDER_TEST,
    base: str = BASE_COMMIT,
    head: str = HEAD_COMMIT,
    ground_truth_path: str | Path | None = None,
) -> dict:
    """Run a single evaluation pass against the target repository."""
    if ground_truth_path is None:
        local_gt = PROJECT_ROOT / "eval" / "ground_truth_manual_test.json"
        target_gt = Path(repo_path) / "eval" / "ground_truth_manual_test.json"
        if local_gt.exists():
            ground_truth_path = local_gt
        elif target_gt.exists():
            ground_truth_path = target_gt
        else:
            raise FileNotFoundError(
                f"Ground truth not found at {local_gt} or {target_gt}"
            )

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    review_text = run_review(repo_path=repo_path, base=base, head=head)
    findings_result = extract_findings(review_text)

    match_result = match_findings(
        findings=findings_result.findings,
        ground_truth=ground_truth,
        repo_root=repo_path,
    )
    match_result["raw_findings"] = [f.model_dump() for f in findings_result.findings]
    match_result["review_text"] = review_text
    return match_result


def write_results_markdown(runs_data: list[dict], output_path: Path):
    """Write eval/results.md containing the summary table and analysis."""
    table_rows = []
    recalls = [r["recall"] for r in runs_data]
    precisions = [r["precision"] for r in runs_data]

    for idx, r in enumerate(runs_data, 1):
        matched_desc = "<br>".join(
            f"• {b['description']}" for b in r["matched_bugs"]
        ) or "None"
        missed_desc = "<br>".join(
            f"• {b['description']}" for b in r["missed_bugs"]
        ) or "None"
        table_rows.append(
            f"| Run {idx} | {r['recall']:.2f} ({int(r['recall']*100)}%) | "
            f"{r['precision']:.2f} ({int(r['precision']*100)}%) | "
            f"{len(r['false_positives'])} | {matched_desc} | {missed_desc} |"
        )

    consistent_recall = len(set(recalls)) == 1
    consistent_precision = len(set(precisions)) == 1
    if consistent_recall and consistent_precision:
        variance_summary = (
            f"Both recall ({recalls[0]:.2f}) and precision ({precisions[0]:.2f}) were "
            "consistent across all 3 evaluation runs with no variance."
        )
    else:
        variance_summary = (
            f"Recall ranged from {min(recalls):.2f} to {max(recalls):.2f} (Δ = {max(recalls)-min(recalls):.2f}), "
            f"while precision ranged from {min(precisions):.2f} to {max(precisions):.2f} (Δ = {max(precisions)-min(precisions):.2f}) across the 3 runs."
        )

    content = f"""# Code Reviewer Evaluation Results

## Evaluation Runs Summary

| Run | Recall | Precision | False Positives | Matched Bug Descriptions | Missed Bug Descriptions |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(table_rows)}

### Consistency Summary
{variance_summary}

## Methodology and Limitations

### Matching Rule
The matching rule compares findings to ground truth entries using exact file path equality and line proximity:
- File paths are normalized to be repository-relative, requiring an exact match (`normalize_path(finding.file) == ground_truth["file"]`).
- Line numbers are matched within a tolerance of ±3 lines (`abs(finding_line - ground_truth_line) <= 3`), using the first integer in any range or string format. If either line number cannot be parsed, the finding is treated as non-matching.

### Known Limitation
This heuristic cannot distinguish a correct diagnosis from a finding that locates the right line but reasons about it incorrectly (this happened with the otpService bug in manual testing — a finding can match by location while its suggested fix is actually wrong or a no-op).
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    print("=" * 60)
    print("Starting Evaluation (3 consecutive runs)...")
    print(f"Target Repo: {REPO_UNDER_TEST}")
    print(f"Base Commit: {BASE_COMMIT}")
    print(f"Head Commit: {HEAD_COMMIT}")
    print("=" * 60)

    runs_data = []

    for i in range(1, 4):
        print(f"\n--- Running Evaluation Run {i}/3 ---")
        run_result = run_single_eval()
        runs_data.append(run_result)

        recall = run_result["recall"]
        precision = run_result["precision"]
        fp_count = len(run_result["false_positives"])
        matched_count = len(run_result["matched_bugs"])
        missed_count = len(run_result["missed_bugs"])

        print(f"Run {i} Summary:")
        print(f"  Recall:          {recall:.2f} ({matched_count} matched, {missed_count} missed)")
        print(f"  Precision:       {precision:.2f}")
        print(f"  False Positives: {fp_count}")

    results_file = PROJECT_ROOT / "eval" / "results.md"
    write_results_markdown(runs_data, results_file)
    print(f"\nWrote full evaluation report to: {results_file}")


if __name__ == "__main__":
    main()

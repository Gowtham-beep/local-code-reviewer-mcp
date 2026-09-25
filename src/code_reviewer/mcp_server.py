import os
import subprocess
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("code-reviewer")
ALLOWED_REPO_ROOT = os.environ.get("ALLOWED_REPO_ROOT", "")


def _validate_repo_path(repo_path: str) -> Path:
    """Resolve repo_path and ensure it's inside ALLOWED_REPO_ROOT and is a git repo.

    Raises ValueError if the path is invalid or outside the allowed root —
    FastMCP will turn this into an MCP error result automatically.
    """
    if not ALLOWED_REPO_ROOT:
        raise ValueError("Server misconfigured: ALLOWED_REPO_ROOT is not set")

    allowed_root = Path(ALLOWED_REPO_ROOT).resolve()
    resolved = Path(repo_path).resolve()

    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise ValueError(f"Repo path {resolved} is outside of allowed root {allowed_root}")

    if not (resolved / ".git").is_dir():
        raise ValueError(f"Repo path {resolved} is not a git repository (missing .git directory)")

    return resolved


def _run_git(repo_path: Path, args: list[str]) -> str:
    """Run a git command in repo_path and return stdout, or raise ValueError on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


@mcp.tool()
def get_diff(repo_path: str, base: str, head: str) -> dict:
    """Get the diff between two git refs in a repository.

    Args:
        repo_path: Absolute path to the git repository.
        base: The git ref to diff from, e.g. "main".
        head: The git ref to diff to, e.g. "feature/xyz".
    """
    resolved = _validate_repo_path(repo_path)

    diff_range = f"{base}...{head}"
    diff_text = _run_git(resolved, ["diff", diff_range])
    stat_text = _run_git(resolved, ["diff", "--stat", diff_range])

    files_changed = []
    for line in stat_text.splitlines():
        if "|" in line:
            files_changed.append(line.split("|")[0].strip())

    insertions = 0
    deletions = 0
    summary_line = stat_text.strip().splitlines()[-1] if stat_text.strip() else ""
    for token in summary_line.split(","):
        token = token.strip()
        if "insertion" in token:
            insertions = int(token.split()[0])
        elif "deletion" in token:
            deletions = int(token.split()[0])

    return {
        "diff": diff_text,
        "files_changed": files_changed,
        "stats": {"insertions": insertions, "deletions": deletions},
    }


@mcp.tool()
def read_file(
    repo_path: str,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    """Read file content from a repository, optionally sliced by line range.

    Args:
        repo_path: Absolute path to the git repository.
        file_path: Path to the file relative to repo_path (e.g. "src/app.ts").
        start_line: Optional 1-indexed starting line number (inclusive).
        end_line: Optional 1-indexed ending line number (inclusive).
    """
    resolved_repo = _validate_repo_path(repo_path)

    resolved_file = (resolved_repo / file_path).resolve()
    if resolved_file != resolved_repo and resolved_repo not in resolved_file.parents:
        raise ValueError(f"File path {file_path} resolves outside repository {resolved_repo}")

    if not resolved_file.is_file():
        raise ValueError(f"File not found or is not a regular file: {file_path}")

    raw_text = resolved_file.read_text(encoding="utf-8", errors="replace")
    lines = raw_text.splitlines(keepends=True)
    total_lines = len(lines)

    if start_line is not None or end_line is not None:
        start_idx = max(0, start_line - 1) if start_line is not None else 0
        end_idx = end_line if end_line is not None else total_lines
        sliced_lines = lines[start_idx:end_idx]
        content = "".join(sliced_lines)
    else:
        content = raw_text

    max_chars = 50_000
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]

    return {
        "content": content,
        "total_lines": total_lines,
        "truncated": truncated,
    }


@mcp.tool()
def list_files(repo_path: str, glob: str | None = None) -> dict:
    """List tracked files in a git repository respecting .gitignore, optionally matching a glob pattern.

    Args:
        repo_path: Absolute path to the git repository.
        glob: Optional glob/pathspec pattern to filter files (e.g. "*.py", "src/**").
    """
    resolved_repo = _validate_repo_path(repo_path)

    git_args = ["ls-files"]
    if glob:
        git_args.extend(["--", glob])

    output = _run_git(resolved_repo, git_args)
    files = [f for f in output.splitlines() if f.strip()]

    return {
        "files": files,
        "count": len(files),
    }
import os 
import subprocess
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP('code-reviewer')
ALLOWED_REPO_ROOT=os.environ.get('ALLOWED_REPO_ROOT', '/home/gpuserver1/P-T_backend_ts')

def _validate_repo_path(repo_path:str)->Path:
    """Resolve repo_path and ensure it's inside ALLOWED_REPO_ROOT and is a git repo.

    Raises ValueError if the path is invalid or outside the allowed root —
    FastMCP will turn this into an MCP error result automatically.
    """
    if not ALLOWED_REPO_ROOT:
        raise ValueError("Server misconfigured: ALLOWED_REPO_ROOT is not set")

    allowedroot = Path(ALLOWED_REPO_ROOT).resolve()
    resolved=Path(repo_path).resolve()

    if resolved != allowedroot and allowedroot not in resolved.parents:
        raise ValueError(f"Repo path {resolved} is outside of allowed root {allowedroot}")

    if not (resolved / '.git').is_dir():
        raise ValueError(f"Repo path {resolved} is not a git repository (missing .git directory)")

    return resolved


if __name__ == "__main__":
    os.environ.setdefault("ALLOWED_REPO_ROOT", "/home/gpuserver1/P-T_backend_ts")  # adjust to a real path
    ALLOWED_REPO_ROOT = os.environ["ALLOWED_REPO_ROOT"]
    print(_validate_repo_path("/home/gpuserver1/P-T_backend_ts"))  # Should succeed
    try:
        _validate_repo_path("/etc")
    except ValueError as e:
        print("Correctly rejected:", e)
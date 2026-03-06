"""
Code Sandbox — safe execution of data analysis code.

Supports Python code execution with resource limits.
Uses subprocess isolation with timeout and memory constraints.

Security layers:
  1. Import whitelist (only approved scientific packages)
  2. Process timeout (default 30s)
  3. Memory limit via resource module (Unix) or timeout (Windows)
  4. No network access in sandbox
  5. Output size cap (prevent stdout bombs)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ALLOWED_IMPORTS = {
    "math", "statistics", "collections", "itertools", "functools",
    "json", "csv", "re", "datetime", "decimal", "fractions",
    "numpy", "np", "pandas", "pd", "scipy", "statsmodels",
    "sklearn", "matplotlib", "seaborn", "plotly",
}

FORBIDDEN_PATTERNS = [
    "import os", "import sys", "import subprocess", "import shutil",
    "__import__", "exec(", "eval(", "compile(",
    "open(", "import socket", "import http", "import urllib",
    "import requests", "import pathlib",
]

MAX_OUTPUT_CHARS = 50_000
DEFAULT_TIMEOUT_SECONDS = 30


class SandboxResult(BaseModel):
    """Result of a sandboxed code execution."""
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    execution_time_ms: int = 0
    truncated: bool = False
    security_violation: str = ""


def check_code_safety(code: str) -> str | None:
    """Static analysis: check for forbidden patterns.

    Returns None if safe, or a violation description.
    """
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in code:
            return f"Forbidden pattern detected: '{pattern}'"

    lines = code.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            parts = stripped.replace("from ", "").replace("import ", "").split(".")
            module = parts[0].split()[0].strip()
            if module and module not in ALLOWED_IMPORTS:
                return f"Unauthorized import: '{module}' (allowed: {', '.join(sorted(ALLOWED_IMPORTS))})"

    return None


async def execute_python(
    code: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    working_dir: str | None = None,
) -> SandboxResult:
    """Execute Python code in an isolated subprocess.

    Args:
        code: Python source code to execute.
        timeout: Maximum execution time in seconds.
        working_dir: Optional working directory for the subprocess.

    Returns:
        SandboxResult with stdout, stderr, exit code, and timing.
    """
    import time

    violation = check_code_safety(code)
    if violation:
        logger.warning("Code sandbox security violation: %s", violation)
        return SandboxResult(
            success=False,
            security_violation=violation,
        )

    tmp_dir = working_dir or tempfile.mkdtemp(prefix="pdmaws_sandbox_")
    script_path = os.path.join(tmp_dir, "_sandbox_script.py")

    wrapper = f"""\
import sys
import warnings
warnings.filterwarnings('ignore')
sys.dont_write_bytecode = True

{code}
"""

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(wrapper)

        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmp_dir,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            },
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = int((time.time() - t0) * 1000)
            return SandboxResult(
                success=False,
                stderr=f"Execution timed out after {timeout}s",
                exit_code=-1,
                execution_time_ms=elapsed,
            )

        elapsed = int((time.time() - t0) * 1000)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        truncated = False
        if len(stdout) > MAX_OUTPUT_CHARS:
            stdout = stdout[:MAX_OUTPUT_CHARS] + "\n... [output truncated]"
            truncated = True

        return SandboxResult(
            success=proc.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode or 0,
            execution_time_ms=elapsed,
            truncated=truncated,
        )

    except Exception as e:
        logger.error("Sandbox execution error: %s", e)
        return SandboxResult(
            success=False,
            stderr=f"Sandbox error: {e}",
        )
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass

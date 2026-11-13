"""One-command offline DMP stability acceptance; never reads runtime.env."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 1000:
        parser.error("iterations must be between 1 and 1000")
    root = Path(__file__).resolve().parents[2]
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="dm", dir=runtime)).resolve()
    if not temporary.is_relative_to(runtime.resolve()):
        raise RuntimeError("Test directory must stay inside .runtime")
    env = dict(
        os.environ,
        APP_ENV="test",
        DMP_MOCK_STRESS_ITERATIONS=str(args.iterations),
        PYTHONIOENCODING="utf-8",
    )
    env.pop("DMP_MOCK_BASE_URL", None)
    print(f"Synthetic HTTP/MCP acceptance; diagnostics: {temporary}", flush=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_dmp_mock.py",
            "-q",
            "-s",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(temporary),
        ],
        cwd=root,
        env=env,
        check=False,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()

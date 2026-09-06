"""Run local engineering gates and retain exact outputs; no external service credentials."""

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    commands = {
        "ruff-format": [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "src",
            "tests",
            "scripts",
        ],
        "ruff": [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
        "mypy": [sys.executable, "-m", "mypy", "src"],
        "dependencies": [
            str(Path(sys.executable).with_name("uv.exe" if sys.platform == "win32" else "uv")),
            "pip",
            "check",
        ],
        "pytest": [
            sys.executable,
            "-m",
            "pytest",
            "--cov=issue_agent",
            "--cov-branch",
            "--cov-report=term-missing",
            "--cov-report=json:artifacts/coverage.json",
            "--cov-report=xml:artifacts/coverage.xml",
            "--junitxml=artifacts/pytest.xml",
        ],
        "mcp-smoke": [sys.executable, "scripts/mcp_smoke.py"],
        "offline-eval": [sys.executable, "-m", "issue_agent.evaluation"],
    }
    results = {}
    for name, command in commands.items():
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        (artifacts / f"{name}.log").write_text(
            completed.stdout + completed.stderr, encoding="utf-8"
        )
        results[name] = {"command": command, "exit_code": completed.returncode}
        print(f"{name}: {'PASS' if completed.returncode == 0 else 'FAIL'}", flush=True)
    coverage = json.loads((artifacts / "coverage.json").read_text(encoding="utf-8"))
    totals = coverage["totals"]
    branch_percent = 100 * totals["covered_branches"] / totals["num_branches"]
    results["branch_coverage"] = {
        "percent": branch_percent,
        "target": 80,
        "passed": branch_percent >= 80,
    }
    licenses = []
    for dist in importlib.metadata.distributions():
        licenses.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "license": dist.metadata.get("License-Expression")
                or dist.metadata.get("License")
                or [
                    v for v in dist.metadata.get_all("Classifier", []) if v.startswith("License ::")
                ],
            }
        )
    (artifacts / "dependency-licenses.json").write_text(
        json.dumps(licenses, indent=2), encoding="utf-8"
    )
    (artifacts / "checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    if any(value.get("exit_code", 0) != 0 for value in results.values()) or branch_percent < 80:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

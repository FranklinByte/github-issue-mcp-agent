"""Read-only dated evidence capture from primary upstream repositories and PyPI."""

import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> None:
    result = {"retrieved_at": datetime.now(UTC).isoformat(), "repositories": []}
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for name in (
            "modelcontextprotocol/python-sdk",
            "github/github-mcp-server",
            "modelcontextprotocol/inspector",
            "langchain-ai/langchain-mcp-adapters",
            "modelcontextprotocol/servers",
        ):
            base = f"https://api.github.com/repos/{name}"
            meta = client.get(base).raise_for_status().json()
            releases = client.get(base + "/releases?per_page=1").raise_for_status().json()
            contents = (
                client.get(base + "/git/trees/" + meta["default_branch"] + "?recursive=1")
                .raise_for_status()
                .json()
            )
            paths = [entry["path"] for entry in contents.get("tree", []) if entry["type"] == "blob"]
            result["repositories"].append(
                {
                    "name": name,
                    "url": meta["html_url"],
                    "pushed_at": meta["pushed_at"],
                    "archived": meta["archived"],
                    "license_metadata": meta["license"],
                    "release": {
                        key: releases[0].get(key)
                        for key in ("tag_name", "published_at", "html_url")
                    }
                    if releases
                    else None,
                    "tree_sha": contents.get("sha"),
                    "test_paths_sample": [p for p in paths if "test" in p.lower()][:12],
                    "license_paths": [
                        p for p in paths if "license" in p.lower() and p.count("/") < 2
                    ],
                }
            )
        pypi = client.get("https://pypi.org/pypi/mcp/json").raise_for_status().json()
        result["mcp_pypi_latest"] = pypi["info"]["version"]
        result["mcp_installed"] = importlib.metadata.version("mcp")
        result["mcp_artifacts"] = [
            {
                "filename": u["filename"],
                "uploaded": u["upload_time_iso_8601"],
                "sha256": u["digests"]["sha256"],
            }
            for u in pypi["urls"]
        ]
    output = Path("artifacts/research-snapshot.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

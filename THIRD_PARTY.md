# Third-Party Dependencies and Attribution

This is an independently scoped, AI-assisted personal implementation, not a fork or renamed GitHub MCP Server. No upstream server code is vendored.

Direct runtime dependencies: official `mcp` Python SDK (MIT), FastAPI (MIT), Uvicorn (BSD-3-Clause), httpx (BSD-3-Clause), Pydantic (MIT), jsonschema (MIT). Exact direct/transitive versions and package hashes are recorded in `uv.lock`; installed license metadata is inventoried in `artifacts/dependency-licenses.json` by the verification script.

Development tools include pytest (MIT), pytest-asyncio (Apache-2.0), pytest-cov (MIT), coverage.py (Apache-2.0), Ruff (MIT), mypy (MIT), Playwright (Apache-2.0). Lucide icons (ISC) are used as UI assets; its license is retained alongside the local bundle. The synthetic evaluation cases and mock issue texts are original AI-assisted fixtures, not copied user content.

Architecture references and dated source links: [docs/reuse-decisions.md](docs/reuse-decisions.md). The reference servers repository is in a licensing transition and the current Inspector root license could not be resolved; neither is redistributed. Do not infer a license grant from an old README or a missing GitHub SPDX field.

This inventory is technical attribution, not a legal opinion. Before distributing new dependencies or copied material, inspect the license of the exact version.

import json
from pathlib import Path

from issue_agent.evaluation import evaluate, ratio


async def test_fixed_regression_set(tmp_path):
    dataset = Path("evals/cases.json")
    raw = json.loads(dataset.read_text(encoding="utf-8"))
    assert len(raw["cases"]) == 50
    assert len({case["id"] for case in raw["cases"]}) == 50
    summary = await evaluate(dataset, tmp_path / "report")
    assert summary["passed"] == 50
    assert summary["unauthorized_writes"] == 0
    assert summary["tool_selection_accuracy"] is None
    assert summary["usage"] is None and summary["cost_usd"] is None
    assert {"results.json", "cases.jsonl", "results.csv", "report.md"} == {
        path.name for path in (tmp_path / "report").iterdir()
    }


def test_empty_ratio():
    assert ratio([]) is None
    assert ratio([True, False]) == 0.5

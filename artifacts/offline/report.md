# Offline Evaluation

Source: AI-assisted synthetic regression set.
No real GitHub requests or writes. Scripted provider cases are control-flow fixtures, not model results.
Expected security rejections count as correct outcomes, not successful tool executions.
Schema pass rate includes deliberately invalid cases. Latency is local and not a production SLA.

| Metric | Value |
| --- | --- |
| mode | offline |
| source | AI-assisted synthetic regression set |
| case_count | 50 |
| passed | 50 |
| mcp_discovery_success_rate | 1.0 |
| tool_call_success_rate | 0.7608695652173914 |
| tool_selection_accuracy | not measured |
| parameter_schema_pass_rate | 0.8181818181818182 |
| permission_accuracy | 1.0 |
| forbidden_operation_block_rate | 1.0 |
| unauthorized_writes | 0 |
| duplicate_write_suppression_rate | 1.0 |
| e2e_expected_outcome_rate | 1.0 |
| p50_ms | 24.743 |
| p95_ms | 1278.831 |
| max_tool_rounds | 4 |
| tool_call_count | 92 |
| usage | not measured |
| cost_usd | not measured |

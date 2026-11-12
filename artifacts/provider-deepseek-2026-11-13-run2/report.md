# Provider Evaluation

Source: AI-assisted synthetic regression set.
No real GitHub requests or writes. Scripted provider cases are control-flow fixtures, not model results.
Expected security rejections count as correct outcomes, not successful tool executions.
Schema pass rate includes deliberately invalid cases. Latency is local and not a production SLA.

| Metric | Value |
| --- | --- |
| mode | provider |
| source | AI-assisted synthetic regression set |
| case_count | 7 |
| passed | 7 |
| mcp_discovery_success_rate | 1.0 |
| tool_call_success_rate | 1.0 |
| tool_selection_accuracy | 1.0 |
| parameter_schema_pass_rate | not measured |
| permission_accuracy | not measured |
| forbidden_operation_block_rate | not measured |
| unauthorized_writes | 0 |
| duplicate_write_suppression_rate | not measured |
| e2e_expected_outcome_rate | 1.0 |
| p50_ms | 19104.431 |
| p95_ms | 29699.633 |
| max_tool_rounds | 3 |
| tool_call_count | 42 |
| usage | [{'prompt_tokens': 17321, 'completion_tokens': 3135, 'total_tokens': 20456}, {'prompt_tokens': 14015, 'completion_tokens': 1586, 'total_tokens': 15601}, {'prompt_tokens': 13985, 'completion_tokens': 1036, 'total_tokens': 15021}, {'prompt_tokens': 14002, 'completion_tokens': 1136, 'total_tokens': 15138}, {'prompt_tokens': 13556, 'completion_tokens': 1642, 'total_tokens': 15198}, {'prompt_tokens': 14476, 'completion_tokens': 3161, 'total_tokens': 17637}, {'prompt_tokens': 9312, 'completion_tokens': 1015, 'total_tokens': 10327}] |
| cost_usd | not measured |

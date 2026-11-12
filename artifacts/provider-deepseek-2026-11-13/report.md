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
| p50_ms | 16416.721 |
| p95_ms | 24602.905 |
| max_tool_rounds | 3 |
| tool_call_count | 40 |
| usage | [{'prompt_tokens': 9872, 'completion_tokens': 1230, 'total_tokens': 11102}, {'prompt_tokens': 10032, 'completion_tokens': 1554, 'total_tokens': 11586}, {'prompt_tokens': 9567, 'completion_tokens': 927, 'total_tokens': 10494}, {'prompt_tokens': 13754, 'completion_tokens': 1345, 'total_tokens': 15099}, {'prompt_tokens': 13571, 'completion_tokens': 1287, 'total_tokens': 14858}, {'prompt_tokens': 15542, 'completion_tokens': 3299, 'total_tokens': 18841}, {'prompt_tokens': 13572, 'completion_tokens': 1181, 'total_tokens': 14753}] |
| cost_usd | not measured |

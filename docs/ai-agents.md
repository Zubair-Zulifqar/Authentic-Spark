# AI agents

```mermaid
sequenceDiagram
  participant UI
  participant API as Route (authz)
  participant O as run_agent()
  participant P as LLMProvider
  participant DB
  UI->>API: POST /agents/{key}/run {org, client, input}
  API->>API: require agent.permission on client
  API->>O: validated input
  O->>O: Pydantic input model
  O->>P: structured(system, input, JSON schema)
  P-->>O: output (or error)
  O->>O: safety invariants (e.g. explicit opt-out override)
  O->>DB: agent_executions (status, tokens, ms, error) + audit_logs
  O-->>UI: execution (awaiting_approval if required)
  UI->>API: POST /agent-executions/{id}/decision
  API->>DB: apply approved output (e.g. create scheduled emails)
```

| Agent | Permission | Approval | Purpose |
|---|---|---|---|
| email_calendar_planner | email:write | yes | dates/themes/deadlines from staff inputs (deterministic) |
| proofreader | email:read | no | mechanical issues in human copy |
| unsubscribe_classifier | compliance:write | no | opt-out intent; explicit phrases always win |
| task_extractor | campaigns:read | yes | action items from notes |
| summarizer | ai:read | no | internal summaries |
| data_classifier | ai:read | no | staff-defined categories |

Provider: `OpenAIProvider` (Chat Completions, `response_format=json_schema`, `strict=True`, temperature 0) when
`OPENAI_API_KEY` is set; otherwise `RuleBasedProvider`, recorded as `provider=rule_based`. Failures are recorded
(`status=failed`, HTTP 502) — never silently replaced. Policy prompt forbids persuasion, profiling and fabrication.

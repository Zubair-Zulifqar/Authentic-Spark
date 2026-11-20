# Multi-client architecture

```mermaid
flowchart TB
  subgraph Agency[Organization: agency]
    M1[Membership: ops manager<br/>client_id = NULL]
    M2[Membership: account manager<br/>client_id = Riverbend]
    subgraph C1[Client workspace: Riverbend]
      D1[(campaigns, calendars, lists,<br/>sms, ads, invoices, suppressions)]
    end
    subgraph C2[Client workspace: Coastal]
      D2[(...)]
    end
    G[(Global suppressions<br/>client_id = NULL)]
  end
  M1 --> C1 & C2
  M2 --> C1
  M2 -. 404 .-> C2
  G --> C1 & C2
```

- Every row carries `organization_id`/`client_id`; list endpoints compute the set of client IDs the caller may access
  for the needed permission (`client_ids_for`) and filter in SQL.
- Detail endpoints load the record and authorize on its own `client_id` (`load_scoped`).
- Client-specific settings (`clients.settings`): Asana project, QuickBooks customer, Google Ads customer, brand terms,
  banned terms, Slack channel routing. Client-specific integrations: `integration_connections.client_id`.
- Workspace UI hides modules the user cannot read; the API enforces the same rules independently.
- Cross-client references are rejected (e.g. an SMS campaign cannot use another client's contact list).

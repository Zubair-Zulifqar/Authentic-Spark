# NGP VAN integration

`NgpVanClient` (`app/services/integrations/crm.py`), based on https://docs.ngpvan.com/:

- Auth: HTTP Basic, username = application name, password = `<apiKey>|<dbMode>` (0 VoterFile, 1 MyCampaign).
- `POST /v4/echoes` — credential check (Integrations → Test connection).
- `POST /v4/bulkImportJobs` — submits a CSV by `sourceUrl` (a Cloud Storage V4 signed URL of the exported valid
  contacts) with column definitions and `loadMappedFile` action. Mapping types must match the mapping configured for
  your committee.
- `GET /v4/bulkImportJobs/{jobId}` — status polled by the `ngpvan_import_status` job; stored on the list.

Without `NGPVAN_APP_NAME`/`NGPVAN_API_KEY`, `MockNgpVan` returns synthetic job IDs. No voter-file data is read or
stored; only agency-acquired contact lists are pushed.

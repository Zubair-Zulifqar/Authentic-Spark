# Scale to Win integration

Scale to Win's API is available to customers under agreement and is not publicly documented, so no endpoints are
assumed here. The platform defines the `SmsProvider` interface (`app/services/integrations/sms.py`):

- `provision_campaign(name, body, sender_id, recipients) -> {reference, status}`
- `campaign_status(reference) -> {status, delivered, failed, opt_outs}`

Only `MockScaleToWin` (mode `mock`) ships. To go live: obtain API access and reference documentation, implement a
`ScaleToWinClient(HttpAdapter)` with those two methods, store the key in Secret Manager (`SCALETOWIN_API_KEY`), and
select it in `registry.get("scale_to_win")`. Opt-out webhooks from the provider should be pointed at the signed
inbound SMS endpoint. Sending/launch remains a human action in the provider console.

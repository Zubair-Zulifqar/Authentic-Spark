# Advertising creative management

Creatives (Meta `single_image`/`video`, Google `responsive_search`/`responsive_display`) store headlines,
descriptions, primary text, disclaimer, asset URI, tags, campaign reference and version.

Checks on every save: platform character limits and asset counts, proofreading (spelling/repeated words), political
"Paid for by" disclosure, client banned terms, brand capitalization, asset description for visuals.

Flow: draft → submit (checks must pass) → in_review → approved/rejected (`ads:approve`, or `compliance:approve` for
political ads). Approved creatives are locked; every edit creates an `ad_creative_versions` snapshot.

Google Ads: read-only REST (`customers:listAccessibleCustomers`, GAQL campaign metrics via `googleAds:search`) with
developer-token and optional login-customer-id headers. The platform does **not** create, activate or change budgets.
Political/electoral ad copy must be supplied and approved by authorized humans; no AI generation or targeting.

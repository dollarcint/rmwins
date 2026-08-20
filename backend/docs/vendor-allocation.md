# External supplier delivery

## Access model

- `VendorCommercialProfile` owns one immutable RM Wins `supplier_code`. It is the same across every client assigned to that supplier.
- This RM Wins supplier ID is separate from a client's upstream connection code (for example, Innovate supplier ID `508`); assigning more clients never changes either value.
- `VendorClientAllocation` grants a client. Every live project under that client is visible by default, subject to its CPI range and active window.
- `VendorSurveyAllocation` is optional. An active `is_excluded=true` row removes exactly one project; a non-exclusion row may retain a project-specific CPI/window override.
- Supplier quantity limits and reservation counters are not part of delivery. Legacy database columns remain inert during the compatibility period and are not exposed by the API or management UI.

## API inventory

Issue a revocable key from Supplier Management and send it as:

```http
X-API-Key: exh_...
```

`GET /api/v1/surveys/` returns only clients selected on that key and applies live project exclusions. The upstream client entry link is never exposed. Each row instead includes a signed `supplier_entry_link` containing a `[%%pid%%]` placeholder.

`GET /api/v1/vendors/supplier/clients/` returns the key's assigned clients, project counts and pre-filtered project URLs.

The response includes:

- `supplier_id`: the supplier's immutable RM Wins ID;
- `survey_id`: RM Wins Project ID by default, or Client Survey ID when `survey_id_mode=source_id`;
- `local_id` and `source_id`: explicit identifiers for diagnostics; and
- `supplier_entry_link`: the safe respondent entry template.

The supplier replaces `[%%pid%%]` with its respondent ID and opens the link. RM Wins verifies the API-key scope and link signature before creating an attempt.

## Outcome redirects

Each client allocation can configure URLs for complete, terminate, over-quota, quality/security and invalid-survey outcomes. RM Wins appends:

```text
pid=<supplier respondent ID>
status=<1|2|3|4>
survey_id=<configured project or client survey ID>
term_reason=<normalized upstream client reason>
hash=<optional HMAC-SHA256>
```

The normalized `term_reason` is the same provider outcome used in Traffic Reports and Termination Reasons. A failed InnovateMR callback hash is never credited as complete; it is stored as a quality/security invalid hit and uses the invalid URL when configured.

Redirect hashing is off by default. Generate/rotate a key in the supplier commercial policy, copy the plaintext once, and then enable signed redirects. The database stores its encrypted value and last-four display. The canonical HMAC input is:

```text
pid=...&status=...&survey_id=...&term_reason=...
```

The `hash` parameter is the lowercase HMAC-SHA256 hex digest of that URL-encoded canonical string.

## Management APIs

- `/api/v1/vendors/commercial-profiles/`: delivery mode, fixed supplier ID, survey-ID mode and redirect hash settings.
- `/api/v1/vendors/client-allocations/`: client access, CPI policy and outcome URLs.
- `/api/v1/vendors/survey-allocations/`: searchable project exclusions/overrides.
- `/api/v1/vendors/api-keys/`: issue, scope and revoke supplier API keys.
- `/api/v1/vendors/directory/`: supplier directory.

Supplier-scoped accounts remain read-only for owner-controlled commercial policies, exclusions and credentials.

# tap-qomon

`tap-qomon` is a Singer tap for [Qomon](https://qomon.app), a mobilization and CRM platform for campaigns and organizations.

Built with the [Hotglue Singer SDK](https://github.com/hotgluexyz/HotglueSingerSDK) for Singer Taps.

## Installation

```bash
pip install tap-qomon
```

Or install directly from the repository:

```bash
pip install git+https://github.com/hotgluexyz/tap-qomon.git
```

## Configuration

### Accepted Config Options

Settings match [`target-qomon`](https://github.com/hotgluexyz/target-qomon), so the same credentials work for both.

| Setting        | Required | Description                                                                       |
|----------------|----------|-----------------------------------------------------------------------------------|
| `api_key`      | Yes      | Qomon API key from space settings                                                  |
| `api_base_url` | No       | Qomon API base URL. Defaults to `https://incoming.qomon.app`                        |
| `start_date`   | No       | Earliest contact `UpdatedAt` to sync on the first run (ISO-8601)                    |

Example `config.json`:

```json
{
  "api_key": "YOUR_API_KEY",
  "api_base_url": "https://incoming.qomon.app",
  "start_date": "2023-01-01T00:00:00Z"
}
```

US-region spaces use `https://incoming-us.qomon.app` — set `api_base_url` accordingly.

A full list of supported settings and capabilities for this tap is available by running:

```bash
tap-qomon --about
```

### Configure using environment variables

This Singer tap will automatically import any environment variables within the working directory's
`.env` if the `--config=ENV` is provided, such that config values will be considered if a matching
environment variable is set either in the terminal context or in the `.env` file.

### Source Authentication and Authorization

Qomon uses a static API key. Create one in the Qomon UI under Settings > Integrations/API and use it with the `Authorization: Bearer <api_key>` header.

See the [Qomon developer docs](https://developers.qomon.com/pages/v1/getting-started.md) for details.

## Supported Streams

| Stream     | Replication Key | Primary Key | Description                                                                |
|------------|-----------------|-------------|----------------------------------------------------------------------------|
| `contacts` | `UpdatedAt`     | `id`        | Qomon contacts, including dynamically discovered custom field properties   |

### How contacts are read

Qomon exposes no contact listing endpoint, so contacts are read through the search API:

- `POST /search` with an `advanced_search` body, `per_page` 1000 (the API maximum), sorted by `lastchange` ascending
- Pages are requested with a 0-based `page` index until a page returns fewer records than `per_page`, since the response carries no total count
- Incremental runs add a `{"attr": "UpdatedAt", "ope": "gte", "value": <bookmark>}` condition, using the replication bookmark or `start_date`

### Custom fields

Custom field definitions are fetched from `/v1/forms/type/custom_fields` at discover time, and each one becomes a top-level property on the `contacts` schema named after the form's label. During sync, values from the contact's `custom_fields` and `formdatas` payloads are unfurled onto the record under those same names.

- Qomon returns every form answer as a string, so custom fields are typed as strings. Two form types differ: multi-answer forms (`checkbox`) are typed as arrays of strings, and `date` forms are typed as `date-time`, since Qomon stores those answers as ISO-8601 UTC timestamps (e.g. `2026-07-16T00:00:00.000Z`).
- For forms with predefined answers (`radio`, `select`, `checkbox`), the readable `refvalue` label is emitted rather than the stored slug — e.g. `Convinced`, not `convinced`. Free-input forms (`text`, `numeric`, `date`) emit the entry's `data` value.
- Custom fields whose label matches a standard contact property are skipped, so the built-in field always wins.
- The raw `custom_fields` array is dropped once unfurled, since the unfurled properties replace it. `formdatas` is still emitted, because it also carries answers to forms that are not custom fields (consents, level of support, tasks, surveys), which nothing else surfaces.

## Usage

You can easily run `tap-qomon` by itself or in a pipeline.

### Executing the Tap Directly

```bash
tap-qomon --version
tap-qomon --help
tap-qomon --config CONFIG --discover > ./catalog.json
tap-qomon --config CONFIG --catalog CATALOG > ./data.singer
```

## Developer Resources

### Initialize your Development Environment

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install ruff pytest
```

Create `.secrets/config.json` with your sandbox credentials:

```json
{
  "api_key": "YOUR_API_KEY",
  "api_base_url": "https://incoming.qomon.app"
}
```

### Verifying against a live space

Custom fields themselves are created in the Qomon UI (Settings > Contact fields) — the public API exposes no form-creation endpoint. Everything else can be checked with curl:

```bash
# List the custom field definitions the tap discovers
curl -s -H "Authorization: Bearer $QOMON_API_KEY" \
  https://incoming.qomon.app/v1/forms/type/custom_fields
```

```bash
# Give a contact custom field values, using the form_id / form_ref_id from above
curl -s -X POST -H "Authorization: Bearer $QOMON_API_KEY" -H "Content-Type: application/json" \
  -d '{"data":{"contact":{"firstname":"Tap","surname":"Qomon CFTest","mail":"tap-qomon-cftest@example.com","custom_fields":[{"form_id":120330,"form_ref_id":286643,"data":"Data Engineer"}]}}}' \
  https://incoming.qomon.app/contacts
```

```bash
# Read contacts back the way the tap does, filtered on UpdatedAt
curl -s -X POST -H "Authorization: Bearer $QOMON_API_KEY" -H "Content-Type: application/json" \
  -d '{"data":{"advanced_search":{"page":0,"per_page":1000,"sort_attr":"lastchange","sort_asc":true,"query":{"$all":[{"$all":[{"$condition":{"attr":"UpdatedAt","ope":"gte","value":"2026-01-01T00:00:00Z"}}]}]}}}}' \
  https://incoming.qomon.app/search
```

Note that `$all` at the top level takes groups, not bare conditions — a `$condition` placed directly in the outer `$all` is rejected with a 422.

### Create and Run Tests

Tests live in the `tap_qomon/tests` subfolder and read credentials from `.secrets/config.json`, skipping if it is absent. Run them with:

```bash
.venv/bin/pytest
```

You can also test the `tap-qomon` CLI interface directly:

```bash
.venv/bin/tap-qomon --help
```

Run lint:

```bash
.venv/bin/pip install tox
.venv/bin/tox
```

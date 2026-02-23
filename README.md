# Jira Integration Service (FastAPI)

Production-ready Jira integration backend with ticket-id or keyword lookup, structured JSON output, and attachment support for any file type.

## Features

- Jira credentials from environment variables only:
  - `JIRA_BASE_URL`
  - `JIRA_EMAIL`
  - `JIRA_API_TOKEN`
- Basic Auth with email + API token
- Input routing:
  - `^[A-Z]+-[0-9]+$` => ticket id lookup
  - anything else => JQL search (`summary ~ "<input>" OR description ~ "<input>"`)
- Multi-result search response for user selection
- Full issue fetch with `expand=names,renderedFields`
- Acceptance criteria extraction from custom field or description parsing fallback
- Attachment metadata for all file types (no type restrictions)
- Structured logging, retries, timeout handling, graceful API errors
- UI sections:
  - Search Input
  - Basic Info
  - Description
  - Acceptance Criteria
  - Attachments

## Environment Variables

Create `.env`:

```env
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your_jira_api_token

REQUEST_CONNECT_TIMEOUT_SECONDS=5
REQUEST_READ_TIMEOUT_SECONDS=20
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_SECONDS=0.5
ENABLE_RESPONSE_CACHE=true
CACHE_TTL_SECONDS=180
LOG_LEVEL=INFO
```

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- UI: `http://127.0.0.1:8000/`
- API Docs: `http://127.0.0.1:8000/docs`

## Main Endpoints

- `GET /jira/lookup?input=<value>`
  - Accepts ticket id or search text.
  - Returns:
    - `mode=single` + `data` for one resolved issue
    - `mode=multiple` + `matches` for selection
    - `mode=none` + not-found message
- `GET /jira/{issue_key}`
  - Direct issue fetch by ticket id
- `GET /jira/{issue_key}/attachments/{attachment_id}`
  - Streams attachment through backend
- `POST /tools/jira.get_issue`
  - Tool-friendly endpoint by issue key
- `GET /health`
  - Health status

## Issue JSON Shape

```json
{
  "ticket_id": "ABC-123",
  "summary": "Example summary",
  "description": "<p>Rendered description</p>",
  "acceptance_criteria": "<p>Rendered acceptance criteria</p>",
  "status": "In Progress",
  "priority": "High",
  "issue_type": "Task",
  "assignee": "Jane User",
  "reporter": "John User",
  "created": "2026-02-19T10:00:00.000+0000",
  "updated": "2026-02-19T11:00:00.000+0000",
  "attachments": [
    {
      "name": "spec.pdf",
      "type": "application/pdf",
      "size": 12345,
      "download_url": "https://your-domain.atlassian.net/secure/attachment/10001/spec.pdf"
    }
  ],
  "metadata": {
    "names": {},
    "has_rendered_fields": true
  }
}
```

## Tests

```bash
python -m pytest -q
```

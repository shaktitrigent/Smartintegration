# Jira Integration Service (FastAPI)

A production-ready Jira integration backend built with Python and FastAPI.

## Features

- Jira REST API v3 integration (`/rest/api/3/issue/{issueIdOrKey}` with `expand=renderedFields,changelog`)
- Structured issue response (no raw Jira payload returned)
- Retry with exponential backoff for transient Jira 5xx errors
- Request timeout handling (connect + read)
- Secure attachment proxy streaming endpoint
- Optional in-memory response caching (2 to 5 minutes)
- JSON structured logging
- Issue key input validation (e.g., `ABC-123`)
- Web UI at `/` for entering a ticket ID and viewing formatted ticket details
- Health check endpoint
- LLM/tool-friendly endpoint
- Basic unit tests with mocked Jira calls
- Docker support

## Project Structure

- `main.py`
- `jira_service.py`
- `config.py`
- `schemas.py`
- `requirements.txt`
- `tests/test_main.py`
- `tests/test_jira_service.py`
- `Dockerfile`

## Requirements

- Python 3.11+

## Environment Variables

Create a `.env` file in the project root:

```env
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your_jira_api_token

# Optional tuning
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

Open:

- UI: `http://127.0.0.1:8000/`
- Docs: `http://127.0.0.1:8000/docs`

## Ports

- Backend (FastAPI API): `8000`
- Frontend (UI at `/`): `8000` (served by the same FastAPI app)

If you run in Docker with `-p 8000:8000`, then:

- Host port: `8000`
- Container port: `8000`

## API Endpoints

- `GET /`
  - HTML UI for fetching ticket details
- `GET /jira/{issue_key}`
  - Returns structured Jira issue data
- `GET /jira/{issue_key}/attachments/{attachment_id}`
  - Streams attachment content via backend proxy
- `POST /tools/jira.get_issue`
  - LLM/function-call style endpoint
- `GET /health`
  - Service health status

## Example Response (`GET /jira/{issue_key}`)

```json
{
  "issue_key": "SCRUM-1",
  "summary": "Improve login flow",
  "description": "<p>Rendered description...</p>",
  "status": "In Progress",
  "issue_type": "Task",
  "priority": "High",
  "assignee": "John Doe",
  "reporter": "Jane Doe",
  "created": "2026-02-19T10:00:00.000+0000",
  "updated": "2026-02-19T11:00:00.000+0000",
  "comments": [],
  "attachments": [
    {
      "filename": "spec.pdf",
      "size": 12345,
      "mimeType": "application/pdf",
      "download_url": "/jira/SCRUM-1/attachments/10001"
    }
  ]
}
```

## Run Tests

```bash
python -m pytest -q
```

## Docker

Build image:

```bash
docker build -t jira-integration .
```

Run container:

```bash
docker run --env-file .env -p 8000:8000 jira-integration
```

## Notes

- Do not expose Jira API credentials to clients.
- Attachment downloads should use the proxy endpoint.
- Cache is in-memory only and resets on service restart.

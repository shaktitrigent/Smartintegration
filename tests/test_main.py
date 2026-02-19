import os

os.environ.setdefault("JIRA_BASE_URL", "https://example.atlassian.net")
os.environ.setdefault("JIRA_EMAIL", "user@example.com")
os.environ.setdefault("JIRA_API_TOKEN", "token")

from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_issue_key_format_returns_422():
    response = client.get("/jira/not-valid-key")
    assert response.status_code == 422


def test_tool_endpoint_success():
    async def fake_get_issue(issue_key: str):
        return {
            "issue_key": issue_key,
            "summary": "Summary",
            "description": None,
            "status": None,
            "issue_type": None,
            "priority": None,
            "assignee": None,
            "reporter": None,
            "created": None,
            "updated": None,
            "comments": [],
            "attachments": [],
        }

    original = main.jira_service.get_issue
    main.jira_service.get_issue = fake_get_issue
    try:
        response = client.post("/tools/jira.get_issue", json={"issue_key": "ABC-123"})
    finally:
        main.jira_service.get_issue = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["issue_key"] == "ABC-123"

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


def test_lookup_returns_not_found_message_when_no_matches():
    async def fake_search_issues(_query: str, max_results: int = 10):
        return []

    original = main.jira_service.search_issues
    main.jira_service.search_issues = fake_search_issues
    try:
        response = client.get("/jira/lookup", params={"input": "this query has no results"})
    finally:
        main.jira_service.search_issues = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "none"
    assert payload["message"] == "Ticket not found. Please verify ID or try keyword search."


def test_tool_endpoint_success():
    async def fake_get_issue(_issue_key: str):
        return {
            "ticket_id": "ABC-123",
            "summary": "Summary",
            "description": None,
            "acceptance_criteria": None,
            "status": None,
            "priority": None,
            "issue_type": None,
            "assignee": None,
            "reporter": None,
            "created": None,
            "updated": None,
            "attachments": [],
            "metadata": {},
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
    assert payload["data"]["ticket_id"] == "ABC-123"

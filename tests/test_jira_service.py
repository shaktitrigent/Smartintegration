from unittest.mock import Mock, patch

from config import Settings
from jira_service import JiraService


def _mock_response(status_code=200, json_body=None, text=""):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    response.close.return_value = None
    return response


def test_retry_on_transient_5xx_then_success():
    settings = Settings(
        jira_base_url="https://example.atlassian.net",
        jira_email="user@example.com",
        jira_api_token="token",
        retry_max_attempts=3,
        retry_backoff_seconds=0,
        enable_response_cache=False,
    )
    service = JiraService(settings)

    issue_payload = {
        "key": "ABC-123",
        "fields": {
            "summary": "Test issue",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Task"},
            "priority": {"name": "High"},
        },
        "renderedFields": {},
    }

    responses = [
        _mock_response(status_code=502, text="bad gateway"),
        _mock_response(status_code=200, json_body=issue_payload),
    ]

    with patch("jira_service.requests.get", side_effect=responses) as mocked_get, patch(
        "jira_service.time.sleep", return_value=None
    ):
        raw = service._fetch_issue_raw("ABC-123")

    assert raw["key"] == "ABC-123"
    assert mocked_get.call_count == 2


def test_issue_response_contains_proxy_attachment_url():
    settings = Settings(
        jira_base_url="https://example.atlassian.net",
        jira_email="user@example.com",
        jira_api_token="token",
        enable_response_cache=False,
    )
    service = JiraService(settings)

    raw = {
        "key": "ABC-123",
        "fields": {
            "summary": "Issue",
            "attachment": [
                {
                    "id": "10001",
                    "filename": "spec.pdf",
                    "size": 123,
                    "mimeType": "application/pdf",
                    "content": "https://example/content/10001",
                }
            ],
        },
        "renderedFields": {},
    }

    issue = service._to_issue_response(raw)
    assert issue.attachments[0].download_url == "/jira/ABC-123/attachments/10001"

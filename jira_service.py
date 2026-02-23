import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException, Timeout

from config import Settings
from schemas import JiraAttachment, JiraIssueResponse, JiraSearchMatch


logger = logging.getLogger(__name__)

TICKET_ID_REGEX = re.compile(r"^[A-Z]+-\d+$")


class JiraError(Exception):
    """Base Jira integration error."""


class JiraNotFoundError(JiraError):
    """Raised when a Jira issue key or attachment does not exist."""


class JiraUnauthorizedError(JiraError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class JiraNetworkError(JiraError):
    """Raised when Jira API cannot be reached."""


class JiraTimeoutError(JiraError):
    """Raised when Jira API times out."""


@dataclass
class AttachmentStream:
    chunks: Iterator[bytes]
    media_type: str
    headers: Dict[str, str]


class JiraService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._auth = HTTPBasicAuth(
            self._settings.jira_email,
            self._settings.jira_api_token,
        )
        self._issue_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._cache_lock = threading.Lock()

    def normalize_ticket_id(self, value: str) -> str:
        return value.strip().upper()

    def is_ticket_id(self, value: str) -> bool:
        return bool(TICKET_ID_REGEX.match(self.normalize_ticket_id(value)))

    async def get_issue(self, issue_key: str) -> JiraIssueResponse:
        issue_data = await asyncio.to_thread(self._get_issue_raw_cached, issue_key)
        return self._to_issue_response(issue_data)

    async def search_issues(self, query: str, max_results: int = 10) -> List[JiraSearchMatch]:
        return await asyncio.to_thread(self._search_issues_sync, query, max_results)

    async def get_attachment_stream(
        self, issue_key: str, attachment_id: str
    ) -> AttachmentStream:
        return await asyncio.to_thread(
            self._get_attachment_stream_sync, issue_key, attachment_id
        )

    def _get_issue_raw_cached(self, issue_key: str) -> Dict[str, Any]:
        normalized_key = self.normalize_ticket_id(issue_key)
        if not normalized_key:
            raise JiraNotFoundError("Invalid issue key")

        if self._settings.enable_response_cache:
            with self._cache_lock:
                cached = self._issue_cache.get(normalized_key)
                if cached and (time.monotonic() - cached[0]) < self._settings.cache_ttl_seconds:
                    logger.info("Issue cache hit", extra={"issue_key": normalized_key})
                    return cached[1]

        issue_data = self._fetch_issue_raw(normalized_key)

        if self._settings.enable_response_cache:
            with self._cache_lock:
                self._issue_cache[normalized_key] = (time.monotonic(), issue_data)

        return issue_data

    def _fetch_issue_raw(self, issue_key: str) -> Dict[str, Any]:
        url = (
            f"{self._settings.jira_base_url}/rest/api/3/issue/{quote(issue_key, safe='')}"
        )
        params = {"expand": "names,renderedFields"}

        logger.info("Fetching Jira issue", extra={"issue_key": issue_key, "url": url})

        response = self._request_with_retry(url=url, params=params)

        if response.status_code == 404:
            response.close()
            raise JiraNotFoundError("Ticket not found. Please verify ID or try keyword search.")
        if response.status_code in (401, 403):
            response.close()
            raise JiraUnauthorizedError(
                "Unauthorized or permission denied for Jira issue",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            logger.error(
                "Unexpected Jira API response",
                extra={"status_code": response.status_code, "body": response.text[:300]},
            )
            response.close()
            raise JiraError("Failed to fetch issue from Jira")

        try:
            payload = response.json()
        except ValueError as exc:
            logger.exception("Jira API returned non-JSON response")
            raise JiraError("Jira API returned invalid response") from exc
        finally:
            response.close()

        return payload

    def _search_issues_sync(self, query: str, max_results: int = 10) -> List[JiraSearchMatch]:
        text = query.strip()
        if not text:
            return []

        url = f"{self._settings.jira_base_url}/rest/api/3/search"
        jql_text = self._sanitize_jql_text(text)
        jql = f'summary ~ "{jql_text}" OR description ~ "{jql_text}"'
        params = {
            "jql": jql,
            "maxResults": str(max_results),
            "fields": "summary,status,priority",
        }

        logger.info("Searching Jira issues", extra={"jql": jql})
        response = self._request_with_retry(url=url, params=params)

        if response.status_code in (401, 403):
            response.close()
            raise JiraUnauthorizedError(
                "Unauthorized or permission denied for Jira search",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            response.close()
            raise JiraError("Failed to search issues in Jira")

        try:
            payload = response.json()
        except ValueError as exc:
            raise JiraError("Jira search returned invalid response") from exc
        finally:
            response.close()

        matches: List[JiraSearchMatch] = []
        for issue in payload.get("issues") or []:
            fields = issue.get("fields") or {}
            matches.append(
                JiraSearchMatch(
                    ticket_id=issue.get("key") or "",
                    summary=fields.get("summary"),
                    status=self._get_nested(fields, "status", "name"),
                    priority=self._get_nested(fields, "priority", "name"),
                )
            )
        return matches

    def _get_attachment_stream_sync(
        self, issue_key: str, attachment_id: str
    ) -> AttachmentStream:
        issue_data = self._get_issue_raw_cached(issue_key)
        attachments = (issue_data.get("fields") or {}).get("attachment") or []

        attachment = next(
            (item for item in attachments if str(item.get("id")) == attachment_id),
            None,
        )
        if not attachment:
            raise JiraNotFoundError("Attachment not found for this issue")

        content_url = attachment.get("content")
        if not content_url:
            raise JiraNotFoundError("Attachment download URL is unavailable")

        response = self._request_with_retry(url=content_url, stream=True)

        if response.status_code == 404:
            response.close()
            raise JiraNotFoundError("Attachment not found")
        if response.status_code in (401, 403):
            response.close()
            raise JiraUnauthorizedError(
                "Unauthorized or permission denied for attachment",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            response.close()
            raise JiraError("Failed to fetch attachment from Jira")

        filename = attachment.get("filename") or f"attachment-{attachment_id}"
        media_type = attachment.get("mimeType") or "application/octet-stream"
        size = attachment.get("size")

        def iterator() -> Iterator[bytes]:
            try:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        yield chunk
            finally:
                response.close()

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
        if size is not None:
            headers["Content-Length"] = str(size)

        return AttachmentStream(chunks=iterator(), media_type=media_type, headers=headers)

    def _request_with_retry(
        self,
        url: str,
        params: Optional[Dict[str, str]] = None,
        stream: bool = False,
    ) -> requests.Response:
        attempts = self._settings.retry_max_attempts

        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    auth=self._auth,
                    timeout=self._settings.request_timeout,
                    stream=stream,
                )
            except Timeout as exc:
                logger.warning(
                    "Jira request timed out",
                    extra={"url": url, "attempt": attempt, "attempts": attempts},
                )
                raise JiraTimeoutError("Jira request timed out") from exc
            except RequestException as exc:
                logger.exception("Network error while calling Jira API")
                raise JiraNetworkError("Unable to connect to Jira API") from exc

            if response.status_code < 500 or attempt == attempts:
                return response

            backoff = self._settings.retry_backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Transient Jira 5xx, retrying",
                extra={
                    "url": url,
                    "status_code": response.status_code,
                    "attempt": attempt,
                    "attempts": attempts,
                    "backoff_seconds": backoff,
                },
            )
            response.close()
            time.sleep(backoff)

        raise JiraError("Unexpected Jira retry state")

    def _to_issue_response(self, issue: Dict[str, Any]) -> JiraIssueResponse:
        fields = issue.get("fields") or {}
        rendered_fields = issue.get("renderedFields") or {}
        names = issue.get("names") or {}
        ticket_id = issue.get("key") or ""

        description = self._extract_rendered_or_adf("description", fields, rendered_fields)
        acceptance = self._extract_acceptance_criteria(fields, rendered_fields, names, description)

        return JiraIssueResponse(
            ticket_id=ticket_id,
            summary=fields.get("summary"),
            description=description,
            acceptance_criteria=acceptance,
            status=self._get_nested(fields, "status", "name"),
            issue_type=self._get_nested(fields, "issuetype", "name"),
            priority=self._get_nested(fields, "priority", "name"),
            assignee=self._get_nested(fields, "assignee", "displayName"),
            reporter=self._get_nested(fields, "reporter", "displayName"),
            created=fields.get("created"),
            updated=fields.get("updated"),
            attachments=self._extract_attachments(fields, ticket_id),
            metadata={
                "names": names,
                "has_rendered_fields": bool(rendered_fields),
            },
        )

    def _extract_attachments(self, fields: Dict[str, Any], ticket_id: str) -> List[JiraAttachment]:
        raw_attachments = fields.get("attachment") or []
        attachments: List[JiraAttachment] = []

        for attachment in raw_attachments:
            attachment_id = attachment.get("id")
            proxy_url = None
            if attachment_id and ticket_id:
                proxy_url = f"/jira/{ticket_id}/attachments/{attachment_id}"
            attachments.append(
                JiraAttachment(
                    name=attachment.get("filename"),
                    type=attachment.get("mimeType"),
                    size=attachment.get("size"),
                    download_url=proxy_url,
                    content=attachment.get("content"),
                )
            )
        return attachments

    def _extract_rendered_or_adf(
        self,
        field_name: str,
        fields: Dict[str, Any],
        rendered_fields: Dict[str, Any],
    ) -> Optional[str]:
        rendered = rendered_fields.get(field_name)
        if isinstance(rendered, str) and rendered.strip():
            return self._clean_text(rendered)

        return self._extract_adf_text(fields.get(field_name))

    def _extract_acceptance_criteria(
        self,
        fields: Dict[str, Any],
        rendered_fields: Dict[str, Any],
        names: Dict[str, str],
        description: Optional[str],
    ) -> Optional[str]:
        ac_custom_key = self._find_acceptance_custom_field_key(names, fields)
        if ac_custom_key:
            rendered_custom = rendered_fields.get(ac_custom_key)
            if isinstance(rendered_custom, str) and rendered_custom.strip():
                return self._clean_text(rendered_custom)
            custom_value = fields.get(ac_custom_key)
            custom_text = self._extract_adf_text(custom_value)
            if custom_text:
                return custom_text

        return self._parse_acceptance_from_description(description)

    def _find_acceptance_custom_field_key(
        self,
        names: Dict[str, str],
        fields: Dict[str, Any],
    ) -> Optional[str]:
        if names:
            for field_id, display_name in names.items():
                if not field_id.startswith("customfield_"):
                    continue
                if isinstance(display_name, str) and "acceptance criteria" in display_name.lower():
                    return field_id

        for field_id in fields.keys():
            if field_id.startswith("customfield_") and "acceptance_criteria" in field_id.lower():
                return field_id

        return None

    def _parse_acceptance_from_description(self, description: Optional[str]) -> Optional[str]:
        if not description:
            return None

        plain = self._strip_html(description)
        if not plain:
            return None

        pattern = re.compile(
            r"acceptance\s*criteria\s*[:\-]?\s*(.+?)(?:\n\s*\n|\n[A-Z][^:\n]{0,80}:\s|\Z)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(plain)
        if not match:
            return None
        return self._clean_text(match.group(1))

    def _sanitize_jql_text(self, value: str) -> str:
        sanitized = value.replace("\\", "\\\\").replace('"', '\\"')
        sanitized = re.sub(r"[\r\n\t]+", " ", sanitized)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized

    def _extract_adf_text(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            return self._clean_text(value)
        if not isinstance(value, dict):
            return None

        fragments: List[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                text = node.get("text")
                if isinstance(text, str):
                    fragments.append(text)
                for child in node.get("content") or []:
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value.get("content") or [])
        extracted = " ".join(part.strip() for part in fragments if part and part.strip()).strip()
        return self._clean_text(extracted) if extracted else None

    def _strip_html(self, value: str) -> str:
        no_tags = re.sub(r"<[^>]+>", " ", value)
        return self._clean_text(no_tags) or ""

    def _clean_text(self, value: str) -> Optional[str]:
        cleaned = re.sub(r"\s+", " ", value or "").strip()
        return cleaned or None

    def _get_nested(self, data: Dict[str, Any], *keys: str) -> Optional[Any]:
        current: Any = data
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
            if current is None:
                return None
        return current

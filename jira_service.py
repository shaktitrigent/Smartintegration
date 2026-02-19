import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException, Timeout

from config import Settings
from schemas import JiraAttachment, JiraComment, JiraIssueResponse


logger = logging.getLogger(__name__)


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

    async def get_issue(self, issue_key: str) -> JiraIssueResponse:
        issue_data = await asyncio.to_thread(self._get_issue_raw_cached, issue_key)
        return self._to_issue_response(issue_data)

    async def get_attachment_stream(
        self, issue_key: str, attachment_id: str
    ) -> AttachmentStream:
        return await asyncio.to_thread(
            self._get_attachment_stream_sync, issue_key, attachment_id
        )

    def _get_issue_raw_cached(self, issue_key: str) -> Dict[str, Any]:
        normalized_key = issue_key.strip().upper()
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
        params = {"expand": "renderedFields,changelog"}

        logger.info("Fetching Jira issue", extra={"issue_key": issue_key, "url": url})

        response = self._request_with_retry(url=url, params=params)

        if response.status_code == 404:
            response.close()
            raise JiraNotFoundError("Invalid issue key")
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
        issue_key = issue.get("key") or ""

        return JiraIssueResponse(
            issue_key=issue_key,
            summary=fields.get("summary"),
            description=self._extract_description(fields, rendered_fields),
            status=self._get_nested(fields, "status", "name"),
            issue_type=self._get_nested(fields, "issuetype", "name"),
            priority=self._get_nested(fields, "priority", "name"),
            assignee=self._get_nested(fields, "assignee", "displayName"),
            reporter=self._get_nested(fields, "reporter", "displayName"),
            created=fields.get("created"),
            updated=fields.get("updated"),
            comments=self._extract_comments(fields, rendered_fields),
            attachments=self._extract_attachments(fields, issue_key),
        )

    def _extract_description(
        self, fields: Dict[str, Any], rendered_fields: Dict[str, Any]
    ) -> Optional[str]:
        rendered = rendered_fields.get("description")
        if isinstance(rendered, str) and rendered.strip():
            return rendered
        return self._extract_adf_text(fields.get("description"))

    def _extract_comments(
        self, fields: Dict[str, Any], rendered_fields: Dict[str, Any]
    ) -> List[JiraComment]:
        raw_comments = (fields.get("comment") or {}).get("comments") or []
        rendered_comments = (rendered_fields.get("comment") or {}).get("comments") or []

        comments: List[JiraComment] = []
        for idx, comment in enumerate(raw_comments):
            rendered_body: Optional[str] = None
            if idx < len(rendered_comments):
                rendered_body = rendered_comments[idx].get("body")

            comments.append(
                JiraComment(
                    author=self._get_nested(comment, "author", "displayName"),
                    body=rendered_body or self._extract_adf_text(comment.get("body")),
                    created=comment.get("created"),
                )
            )
        return comments

    def _extract_attachments(
        self, fields: Dict[str, Any], issue_key: str
    ) -> List[JiraAttachment]:
        raw_attachments = fields.get("attachment") or []
        attachments: List[JiraAttachment] = []

        for attachment in raw_attachments:
            attachment_id = attachment.get("id")
            proxy_url = None
            if attachment_id:
                proxy_url = f"/jira/{issue_key}/attachments/{attachment_id}"

            attachments.append(
                JiraAttachment(
                    filename=attachment.get("filename"),
                    size=attachment.get("size"),
                    mimeType=attachment.get("mimeType"),
                    download_url=proxy_url,
                )
            )
        return attachments

    def _extract_adf_text(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            return value
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
        return extracted or None

    def _get_nested(self, data: Dict[str, Any], *keys: str) -> Optional[Any]:
        current: Any = data
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
            if current is None:
                return None
        return current

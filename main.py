import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from config import get_settings
from jira_service import (
    JiraError,
    JiraNetworkError,
    JiraNotFoundError,
    JiraService,
    JiraTimeoutError,
    JiraUnauthorizedError,
)
from schemas import (
    HealthResponse,
    JiraIssueResponse,
    JiraLookupResponse,
    JiraToolRequest,
    JiraToolResponse,
    ToolError,
)


TICKET_ID_PATTERN = r"^[A-Z]+-\d+$"
ATTACHMENT_ID_PATTERN = r"^\d+$"
NOT_FOUND_TEXT = "Ticket not found. Please verify ID or try keyword search."


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        standard = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
        }

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in standard and not key.startswith("_")
        }
        if extras:
            payload["extra"] = extras

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging() -> logging.Logger:
    settings = get_settings()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    return logging.getLogger(__name__)


logger = configure_logging()
app = FastAPI(
    title="Jira Integration Service",
    version="2.0.0",
    description="Production-ready FastAPI backend for Jira issue lookup and retrieval.",
)
jira_service = JiraService(get_settings())


ROOT_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Jira Ticket Viewer</title>
  <style>
    :root {
      --bg-start: #f9fafb;
      --bg-end: #e8eef7;
      --card: #ffffff;
      --text: #1d293d;
      --muted: #637085;
      --primary: #1b6ef3;
      --primary-hover: #1255bd;
      --border: #d6deeb;
      --error-bg: #fff1f1;
      --error-text: #b3261e;
      --surface: #f6f8fc;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background: linear-gradient(150deg, var(--bg-start), var(--bg-end));
      color: var(--text);
      display: flex;
      justify-content: center;
      padding: 24px;
    }
    .wrap {
      width: 100%;
      max-width: 980px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 10px 28px rgba(8, 20, 36, 0.08);
      padding: 24px;
    }
    h1 {
      margin: 0;
      font-size: 30px;
      letter-spacing: 0.2px;
    }
    .hint {
      margin: 10px 0 18px;
      color: var(--muted);
      font-size: 14px;
    }
    .search-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    input[type="text"] {
      flex: 1;
      min-width: 280px;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
      font-size: 16px;
      outline: none;
    }
    input[type="text"]:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(27, 110, 243, 0.18);
    }
    button {
      border: 0;
      border-radius: 10px;
      background: var(--primary);
      color: #fff;
      font-size: 15px;
      font-weight: 600;
      padding: 12px 16px;
      cursor: pointer;
    }
    button:hover { background: var(--primary-hover); }
    .message {
      margin-top: 14px;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid transparent;
      display: none;
    }
    .message.info {
      display: block;
      background: var(--surface);
      border-color: var(--border);
      color: var(--muted);
    }
    .message.error {
      display: block;
      background: var(--error-bg);
      border-color: #ffd5d2;
      color: var(--error-text);
    }
    .matches {
      display: none;
      margin-top: 16px;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--surface);
      padding: 12px;
    }
    .matches.show { display: block; }
    .match-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #fff;
      padding: 10px;
      margin: 8px 0;
    }
    .match-meta {
      color: var(--muted);
      font-size: 13px;
      margin-top: 3px;
    }
    .ticket {
      display: none;
      margin-top: 18px;
      border-top: 1px solid var(--border);
      padding-top: 18px;
    }
    .ticket.show { display: block; }
    .section {
      margin-top: 18px;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      background: #fff;
    }
    .section h3 {
      margin: 0 0 10px;
      font-size: 14px;
      letter-spacing: 0.08em;
      color: var(--muted);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
    }
    .kv {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px;
      min-height: 68px;
    }
    .kv b {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 5px;
    }
    .rich {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      background: var(--surface);
      line-height: 1.5;
      overflow-x: auto;
    }
    .attachments { margin: 0; padding-left: 0; list-style: none; }
    .attachments li {
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--surface);
      margin: 8px 0;
      padding: 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .file-meta {
      font-size: 13px;
      color: var(--muted);
      margin-top: 4px;
    }
    .download-btn {
      text-decoration: none;
      background: var(--primary);
      color: #fff;
      padding: 7px 12px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      white-space: nowrap;
    }
    @media (max-width: 700px) {
      .wrap { padding: 16px; }
      h1 { font-size: 24px; }
      input[type="text"] { min-width: 180px; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <h1>Jira Search Input</h1>
    <p class="hint">Use a ticket id (example: ABC-123) or enter keywords to search title/description.</p>

    <div class="search-row">
      <input id="searchInput" type="text" placeholder="ABC-123 or payment gateway timeout" autocomplete="off" />
      <button id="searchButton" type="button">Search</button>
    </div>

    <div id="message" class="message info">Enter input to fetch ticket details.</div>

    <section id="matchesSection" class="matches">
      <div id="matchesList"></div>
    </section>

    <section id="ticketSection" class="ticket" aria-live="polite">
      <div class="section">
        <h3>--- BASIC INFO ---</h3>
        <div class="grid">
          <div class="kv"><b>Ticket ID</b><span id="ticketId">-</span></div>
          <div class="kv"><b>Summary</b><span id="summary">-</span></div>
          <div class="kv"><b>Status</b><span id="status">-</span></div>
          <div class="kv"><b>Priority</b><span id="priority">-</span></div>
        </div>
      </div>

      <div class="section">
        <h3>--- DESCRIPTION ---</h3>
        <div id="description" class="rich"></div>
      </div>

      <div class="section">
        <h3>--- ACCEPTANCE CRITERIA ---</h3>
        <div id="acceptanceCriteria" class="rich"></div>
      </div>

      <div class="section">
        <h3>--- ATTACHMENTS ---</h3>
        <ul id="attachments" class="attachments"></ul>
      </div>
    </section>
  </main>

  <script>
    const inputEl = document.getElementById("searchInput");
    const buttonEl = document.getElementById("searchButton");
    const messageEl = document.getElementById("message");
    const ticketSectionEl = document.getElementById("ticketSection");
    const matchesSectionEl = document.getElementById("matchesSection");
    const matchesListEl = document.getElementById("matchesList");

    const ticketIdEl = document.getElementById("ticketId");
    const summaryEl = document.getElementById("summary");
    const statusEl = document.getElementById("status");
    const priorityEl = document.getElementById("priority");
    const descriptionEl = document.getElementById("description");
    const acceptanceEl = document.getElementById("acceptanceCriteria");
    const attachmentsEl = document.getElementById("attachments");

    function safeValue(value) {
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    }

    function showMessage(text, type) {
      messageEl.className = "message " + type;
      messageEl.textContent = text;
    }

    function clearTicket() {
      ticketSectionEl.classList.remove("show");
      ticketIdEl.textContent = "-";
      summaryEl.textContent = "-";
      statusEl.textContent = "-";
      priorityEl.textContent = "-";
      descriptionEl.innerHTML = "";
      acceptanceEl.innerHTML = "";
      attachmentsEl.innerHTML = "";
    }

    function clearMatches() {
      matchesSectionEl.classList.remove("show");
      matchesListEl.innerHTML = "";
    }

    function renderIssue(issue) {
      clearMatches();
      ticketIdEl.textContent = safeValue(issue.ticket_id);
      summaryEl.textContent = safeValue(issue.summary);
      statusEl.textContent = safeValue(issue.status);
      priorityEl.textContent = safeValue(issue.priority);
      descriptionEl.innerHTML = issue.description && issue.description.trim()
        ? issue.description
        : "<em>No description available.</em>";
      acceptanceEl.innerHTML = issue.acceptance_criteria && issue.acceptance_criteria.trim()
        ? issue.acceptance_criteria
        : "<em>No acceptance criteria available.</em>";

      attachmentsEl.innerHTML = "";
      const attachments = Array.isArray(issue.attachments) ? issue.attachments : [];
      if (!attachments.length) {
        const li = document.createElement("li");
        li.innerHTML = "<div>No attachments.</div>";
        attachmentsEl.appendChild(li);
      } else {
        attachments.forEach((item) => {
          const li = document.createElement("li");
          const left = document.createElement("div");
          const name = document.createElement("div");
          const meta = document.createElement("div");
          name.textContent = safeValue(item.name);
          meta.className = "file-meta";
          meta.textContent = "Type: " + safeValue(item.type) + " | Size: " + safeValue(item.size);
          left.appendChild(name);
          left.appendChild(meta);

          const right = document.createElement("div");
          if (item.download_url) {
            const link = document.createElement("a");
            link.className = "download-btn";
            link.href = item.download_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = "Download";
            right.appendChild(link);
          } else {
            right.textContent = "No download URL";
          }

          li.appendChild(left);
          li.appendChild(right);
          attachmentsEl.appendChild(li);
        });
      }

      ticketSectionEl.classList.add("show");
    }

    async function fetchByTicketId(ticketId) {
      const response = await fetch("/jira/" + encodeURIComponent(ticketId));
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload && payload.detail ? String(payload.detail) : "Failed to fetch ticket.";
        throw new Error(detail);
      }
      return payload;
    }

    function renderMatches(matches) {
      clearTicket();
      matchesListEl.innerHTML = "";
      matches.forEach((item) => {
        const row = document.createElement("div");
        row.className = "match-item";

        const left = document.createElement("div");
        const title = document.createElement("div");
        title.textContent = safeValue(item.ticket_id) + " | " + safeValue(item.summary);
        const meta = document.createElement("div");
        meta.className = "match-meta";
        meta.textContent = "Status: " + safeValue(item.status) + " | Priority: " + safeValue(item.priority);
        left.appendChild(title);
        left.appendChild(meta);

        const selectBtn = document.createElement("button");
        selectBtn.type = "button";
        selectBtn.textContent = "Select";
        selectBtn.addEventListener("click", async () => {
          selectBtn.disabled = true;
          selectBtn.textContent = "Loading...";
          try {
            const issue = await fetchByTicketId(item.ticket_id);
            renderIssue(issue);
            showMessage("Selected ticket loaded.", "info");
          } catch (error) {
            showMessage(String(error.message || error), "error");
          } finally {
            selectBtn.disabled = false;
            selectBtn.textContent = "Select";
          }
        });

        row.appendChild(left);
        row.appendChild(selectBtn);
        matchesListEl.appendChild(row);
      });

      matchesSectionEl.classList.add("show");
    }

    async function runLookup() {
      const rawInput = inputEl.value || "";
      const q = rawInput.trim();
      clearMatches();
      clearTicket();

      if (!q) {
        showMessage("Please enter ticket ID or search text.", "error");
        return;
      }

      buttonEl.disabled = true;
      buttonEl.textContent = "Searching...";
      showMessage("Fetching ticket data...", "info");

      try {
        const url = "/jira/lookup?input=" + encodeURIComponent(q);
        const response = await fetch(url);
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
          const detail = payload && payload.detail ? String(payload.detail) : "Failed to fetch ticket.";
          showMessage(detail, "error");
          return;
        }

        if (payload.mode === "single" && payload.data) {
          renderIssue(payload.data);
          showMessage("Ticket loaded.", "info");
          return;
        }

        if (payload.mode === "multiple") {
          const matches = Array.isArray(payload.matches) ? payload.matches : [];
          if (!matches.length) {
            showMessage("Ticket not found. Please verify ID or try keyword search.", "error");
            return;
          }
          renderMatches(matches);
          showMessage("Multiple tickets found. Select one.", "info");
          return;
        }

        showMessage(payload.message || "Ticket not found. Please verify ID or try keyword search.", "error");
      } catch (error) {
        showMessage("Jira API failure. Please try again.", "error");
      } finally {
        buttonEl.disabled = false;
        buttonEl.textContent = "Search";
      }
    }

    buttonEl.addEventListener("click", runLookup);
    inputEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") runLookup();
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, operation_id="root")
async def root() -> HTMLResponse:
    return HTMLResponse(content=ROOT_PAGE_HTML)


async def _fetch_issue(issue_key: str) -> JiraIssueResponse:
    normalized = jira_service.normalize_ticket_id(issue_key)
    try:
        return await jira_service.get_issue(normalized)
    except JiraNotFoundError as exc:
        logger.warning("Issue not found", extra={"issue_key": normalized})
        detail = str(exc) if str(exc) else NOT_FOUND_TEXT
        raise HTTPException(status_code=404, detail=detail) from exc
    except JiraUnauthorizedError as exc:
        logger.warning(
            "Unauthorized Jira access",
            extra={"issue_key": normalized, "status_code": exc.status_code},
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except JiraTimeoutError as exc:
        logger.warning("Jira upstream timeout", extra={"issue_key": normalized})
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except JiraNetworkError as exc:
        logger.exception("Network error while fetching Jira issue")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JiraError as exc:
        logger.exception("Jira service error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/jira/lookup",
    response_model=JiraLookupResponse,
    operation_id="jira_lookup",
    tags=["jira"],
)
async def jira_lookup(
    input_value: Annotated[str, Query(alias="input", min_length=1, max_length=300)]
) -> JiraLookupResponse:
    normalized = jira_service.normalize_ticket_id(input_value)
    is_ticket = jira_service.is_ticket_id(input_value)

    if is_ticket:
        issue = await _fetch_issue(normalized)
        return JiraLookupResponse(
            mode="single",
            query=input_value,
            normalized_input=normalized,
            is_ticket_id=True,
            data=issue,
            matches=[],
            message=None,
        )

    try:
        matches = await jira_service.search_issues(input_value)
    except JiraUnauthorizedError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except JiraTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except JiraNetworkError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not matches:
        return JiraLookupResponse(
            mode="none",
            query=input_value,
            normalized_input=input_value.strip(),
            is_ticket_id=False,
            data=None,
            matches=[],
            message=NOT_FOUND_TEXT,
        )

    if len(matches) == 1:
        issue = await _fetch_issue(matches[0].ticket_id)
        return JiraLookupResponse(
            mode="single",
            query=input_value,
            normalized_input=input_value.strip(),
            is_ticket_id=False,
            data=issue,
            matches=[],
            message=None,
        )

    return JiraLookupResponse(
        mode="multiple",
        query=input_value,
        normalized_input=input_value.strip(),
        is_ticket_id=False,
        data=None,
        matches=matches,
        message="Multiple tickets found. Select one ticket.",
    )


@app.get(
    "/jira/{issue_key}",
    response_model=JiraIssueResponse,
    operation_id="jira_get_issue",
    tags=["jira"],
)
async def get_jira_issue(
    issue_key: Annotated[
        str,
        Path(
            pattern=TICKET_ID_PATTERN,
            description="Jira issue key in format PROJECT-123",
        ),
    ]
) -> JiraIssueResponse:
    return await _fetch_issue(issue_key)


@app.get(
    "/jira/{issue_key}/attachments/{attachment_id}",
    operation_id="jira_get_attachment",
    tags=["jira"],
)
async def proxy_jira_attachment(
    issue_key: Annotated[
        str,
        Path(pattern=TICKET_ID_PATTERN, description="Jira issue key in format PROJECT-123"),
    ],
    attachment_id: Annotated[
        str,
        Path(pattern=ATTACHMENT_ID_PATTERN, description="Numeric Jira attachment ID"),
    ],
):
    try:
        stream = await jira_service.get_attachment_stream(issue_key, attachment_id)
        return StreamingResponse(
            stream.chunks,
            media_type=stream.media_type,
            headers=stream.headers,
        )
    except JiraNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JiraUnauthorizedError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except JiraTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except JiraNetworkError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/tools/jira.get_issue",
    response_model=JiraToolResponse,
    operation_id="tool_jira_get_issue",
    tags=["tools"],
)
async def jira_tool_get_issue(payload: JiraToolRequest) -> JiraToolResponse:
    try:
        issue = await jira_service.get_issue(payload.issue_key)
        return JiraToolResponse(ok=True, data=issue, error=None)
    except JiraNotFoundError:
        return JiraToolResponse(
            ok=False,
            data=None,
            error=ToolError(code="NOT_FOUND", message=NOT_FOUND_TEXT),
        )
    except JiraUnauthorizedError as exc:
        return JiraToolResponse(
            ok=False,
            data=None,
            error=ToolError(code="UNAUTHORIZED", message=str(exc)),
        )
    except JiraTimeoutError as exc:
        return JiraToolResponse(
            ok=False,
            data=None,
            error=ToolError(code="TIMEOUT", message=str(exc)),
        )
    except JiraNetworkError as exc:
        return JiraToolResponse(
            ok=False,
            data=None,
            error=ToolError(code="NETWORK_ERROR", message=str(exc)),
        )
    except JiraError as exc:
        return JiraToolResponse(
            ok=False,
            data=None,
            error=ToolError(code="JIRA_ERROR", message=str(exc)),
        )


@app.get("/health", response_model=HealthResponse, operation_id="health_check")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")

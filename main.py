import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path
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
    JiraToolRequest,
    JiraToolResponse,
    ToolError,
)


ISSUE_KEY_PATTERN = r"^[A-Z][A-Z0-9]+-\d+$"
ATTACHMENT_ID_PATTERN = r"^\d+$"


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
    version="1.1.0",
    description="FastAPI backend for Jira issue retrieval with structured responses.",
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
      --bg: #f3f5f9;
      --card: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --primary: #0f62fe;
      --primary-hover: #0043ce;
      --border: #e5e7eb;
      --error-bg: #fef2f2;
      --error-text: #b91c1c;
      --success-bg: #f9fafb;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(160deg, #f8fafc 0%, #eef2ff 100%);
      color: var(--text);
      display: grid;
      place-items: center;
      padding: 24px;
    }

    .card {
      width: 100%;
      max-width: 860px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
      padding: 28px;
    }

    h1 {
      margin: 0 0 18px;
      font-size: 28px;
      letter-spacing: 0.2px;
    }

    .subtitle {
      margin: 0 0 22px;
      color: var(--muted);
      font-size: 14px;
    }

    .controls {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }

    input[type="text"] {
      flex: 1;
      min-width: 220px;
      padding: 12px 14px;
      font-size: 16px;
      border: 1px solid var(--border);
      border-radius: 10px;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }

    input[type="text"]:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(15, 98, 254, 0.18);
    }

    button {
      border: none;
      border-radius: 10px;
      padding: 12px 16px;
      background: var(--primary);
      color: #fff;
      font-weight: 600;
      font-size: 15px;
      cursor: pointer;
      transition: background-color 0.2s, transform 0.02s;
    }

    button:hover {
      background: var(--primary-hover);
    }

    button:active {
      transform: translateY(1px);
    }

    .message {
      display: none;
      margin-bottom: 16px;
      padding: 10px 12px;
      border-radius: 10px;
      font-size: 14px;
    }

    .message.error {
      display: block;
      background: var(--error-bg);
      color: var(--error-text);
      border: 1px solid #fecaca;
    }

    .message.info {
      display: block;
      background: var(--success-bg);
      color: var(--muted);
      border: 1px solid var(--border);
    }

    .ticket {
      display: none;
      border-top: 1px solid var(--border);
      padding-top: 18px;
      margin-top: 4px;
    }

    .ticket.show {
      display: block;
    }

    .ticket-title {
      margin: 0 0 8px;
      font-size: 26px;
      line-height: 1.3;
    }

    .ticket-key {
      color: var(--muted);
      margin: 0 0 18px;
      font-size: 14px;
    }

    .section-title {
      margin: 18px 0 8px;
      font-size: 16px;
    }

    .description {
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #fcfcfd;
      line-height: 1.6;
      font-size: 15px;
      overflow-x: auto;
    }

    .meta {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px 16px;
      margin-top: 12px;
    }

    .meta-row {
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #fff;
      min-height: 66px;
    }

    .meta-label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 6px;
    }

    .meta-value {
      font-size: 15px;
      word-break: break-word;
    }

    .attachments {
      margin: 8px 0 0;
      padding-left: 18px;
    }

    .attachments li {
      margin: 6px 0;
    }

    .attachments a {
      color: var(--primary);
      text-decoration: none;
    }

    .attachments a:hover {
      text-decoration: underline;
    }
  </style>
</head>
<body>
  <main class="card">
    <h1>Jira Ticket Viewer</h1>
    <p class="subtitle">Enter a ticket ID like <strong>SCRUM-1</strong> to fetch issue details.</p>

    <div class="controls">
      <input id="issueKeyInput" type="text" placeholder="SCRUM-1" autocomplete="off" />
      <button id="fetchButton" type="button">Fetch Ticket</button>
    </div>

    <div id="message" class="message" role="alert"></div>

    <section id="ticket" class="ticket" aria-live="polite">
      <h2 id="ticketSummary" class="ticket-title"></h2>
      <p id="ticketKey" class="ticket-key"></p>

      <h3 class="section-title">Description</h3>
      <div id="ticketDescription" class="description"></div>

      <h3 class="section-title">Details</h3>
      <div class="meta">
        <div class="meta-row"><span class="meta-label">Status</span><div id="status" class="meta-value">-</div></div>
        <div class="meta-row"><span class="meta-label">Priority</span><div id="priority" class="meta-value">-</div></div>
        <div class="meta-row"><span class="meta-label">Issue Type</span><div id="issueType" class="meta-value">-</div></div>
        <div class="meta-row"><span class="meta-label">Assignee</span><div id="assignee" class="meta-value">-</div></div>
        <div class="meta-row"><span class="meta-label">Reporter</span><div id="reporter" class="meta-value">-</div></div>
        <div class="meta-row"><span class="meta-label">Created</span><div id="created" class="meta-value">-</div></div>
        <div class="meta-row"><span class="meta-label">Updated</span><div id="updated" class="meta-value">-</div></div>
      </div>

      <h3 class="section-title">Attachments</h3>
      <ul id="attachments" class="attachments"></ul>
    </section>
  </main>

  <script>
    const input = document.getElementById("issueKeyInput");
    const button = document.getElementById("fetchButton");
    const message = document.getElementById("message");
    const ticketSection = document.getElementById("ticket");

    const summaryEl = document.getElementById("ticketSummary");
    const keyEl = document.getElementById("ticketKey");
    const descriptionEl = document.getElementById("ticketDescription");

    const statusEl = document.getElementById("status");
    const priorityEl = document.getElementById("priority");
    const issueTypeEl = document.getElementById("issueType");
    const assigneeEl = document.getElementById("assignee");
    const reporterEl = document.getElementById("reporter");
    const createdEl = document.getElementById("created");
    const updatedEl = document.getElementById("updated");
    const attachmentsEl = document.getElementById("attachments");

    function safeValue(value) {
      if (value === null || value === undefined || value === "") {
        return "-";
      }
      return String(value);
    }

    function showMessage(text, type) {
      message.textContent = text;
      message.className = "message " + type;
    }

    function clearMessage() {
      message.textContent = "";
      message.className = "message";
    }

    function clearTicket() {
      ticketSection.classList.remove("show");
      summaryEl.textContent = "";
      keyEl.textContent = "";
      descriptionEl.innerHTML = "";
      statusEl.textContent = "-";
      priorityEl.textContent = "-";
      issueTypeEl.textContent = "-";
      assigneeEl.textContent = "-";
      reporterEl.textContent = "-";
      createdEl.textContent = "-";
      updatedEl.textContent = "-";
      attachmentsEl.innerHTML = "";
    }

    function renderTicket(data) {
      summaryEl.textContent = safeValue(data.summary);
      keyEl.textContent = safeValue(data.issue_key);
      descriptionEl.innerHTML = data.description && data.description.trim() ? data.description : "<em>No description provided.</em>";

      statusEl.textContent = safeValue(data.status);
      priorityEl.textContent = safeValue(data.priority);
      issueTypeEl.textContent = safeValue(data.issue_type);
      assigneeEl.textContent = safeValue(data.assignee);
      reporterEl.textContent = safeValue(data.reporter);
      createdEl.textContent = safeValue(data.created);
      updatedEl.textContent = safeValue(data.updated);

      attachmentsEl.innerHTML = "";
      const attachments = Array.isArray(data.attachments) ? data.attachments : [];
      if (!attachments.length) {
        const li = document.createElement("li");
        li.textContent = "No attachments";
        attachmentsEl.appendChild(li);
      } else {
        attachments.forEach((attachment) => {
          const li = document.createElement("li");
          const link = document.createElement("a");
          link.textContent = safeValue(attachment.filename);
          link.href = attachment.download_url || "#";
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          if (!attachment.download_url) {
            link.style.pointerEvents = "none";
            link.style.opacity = "0.6";
          }
          li.appendChild(link);
          attachmentsEl.appendChild(li);
        });
      }

      ticketSection.classList.add("show");
    }

    async function fetchTicket() {
      const issueKey = input.value.trim().toUpperCase();
      clearMessage();

      if (!issueKey) {
        clearTicket();
        showMessage("Please enter a ticket ID.", "error");
        return;
      }

      button.disabled = true;
      button.textContent = "Fetching...";

      try {
        const response = await fetch("/jira/" + encodeURIComponent(issueKey));
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
          clearTicket();
          if (response.status === 404) {
            showMessage("Ticket not found. Please check the issue key and try again.", "error");
          } else if (response.status === 422) {
            showMessage("Invalid ticket format. Use something like SCRUM-1.", "error");
          } else {
            const detail = payload && payload.detail ? String(payload.detail) : "Failed to fetch ticket.";
            showMessage(detail, "error");
          }
          return;
        }

        renderTicket(payload);
      } catch (error) {
        clearTicket();
        showMessage("Network error while fetching ticket. Please try again.", "error");
      } finally {
        button.disabled = false;
        button.textContent = "Fetch Ticket";
      }
    }

    button.addEventListener("click", fetchTicket);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        fetchTicket();
      }
    });

    showMessage("Enter a ticket ID to begin.", "info");
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, operation_id="root")
async def root() -> HTMLResponse:
    return HTMLResponse(content=ROOT_PAGE_HTML)


async def _fetch_issue(issue_key: str) -> JiraIssueResponse:
    try:
        return await jira_service.get_issue(issue_key)
    except JiraNotFoundError as exc:
        logger.warning("Issue not found", extra={"issue_key": issue_key})
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JiraUnauthorizedError as exc:
        logger.warning(
            "Unauthorized Jira access",
            extra={"issue_key": issue_key, "status_code": exc.status_code},
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except JiraTimeoutError as exc:
        logger.warning("Jira upstream timeout", extra={"issue_key": issue_key})
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except JiraNetworkError as exc:
        logger.exception("Network error while fetching Jira issue")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JiraError as exc:
        logger.exception("Jira service error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
            pattern=ISSUE_KEY_PATTERN,
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
        Path(pattern=ISSUE_KEY_PATTERN, description="Jira issue key in format PROJECT-123"),
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
            error=ToolError(code="NOT_FOUND", message="Invalid issue key"),
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

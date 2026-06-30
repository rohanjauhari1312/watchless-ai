import json
from datetime import datetime

import anthropic
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import ANTHROPIC_API_KEY, VISION_MODEL
from app.models import Alert, AlertEvent, Frame
from app.validation import validate_chat_answer

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MAX_TOOL_ITERATIONS = 5

TOOLS = [
    {
        "name": "search_frames",
        "description": (
            "Search this camera's stored frame log. Each frame is a timestamped structured "
            "observation (people, objects, summary) sampled periodically from the footage. "
            "Use start_time/end_time to narrow a time window and keyword to filter by text "
            "appearing in the observation (e.g. an object type, color, or action). Returns up "
            "to 100 matching frames ordered oldest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_time": {"type": "string", "description": "ISO8601 lower bound, omit for no lower bound"},
                "end_time": {"type": "string", "description": "ISO8601 upper bound, omit for no upper bound"},
                "keyword": {"type": "string", "description": "Substring to filter observations by, case-insensitive"},
            },
        },
    },
    {
        "name": "get_alert_history",
        "description": "Get every alert that has fired for this camera, with the condition, reason, and timestamp.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _search_frames(db: Session, camera_id: int, start_time: str | None, end_time: str | None, keyword: str | None):
    q = db.query(Frame).filter(Frame.camera_id == camera_id)
    if start_time:
        q = q.filter(Frame.timestamp >= datetime.fromisoformat(start_time))
    if end_time:
        q = q.filter(Frame.timestamp <= datetime.fromisoformat(end_time))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(Frame.summary.ilike(like), Frame.analysis_json.ilike(like)))
    frames = q.order_by(Frame.timestamp.asc()).limit(100).all()
    return [
        {"timestamp": f.timestamp.isoformat(), "summary": f.summary, "analysis": f.analysis_json}
        for f in frames
    ]


def _get_alert_history(db: Session, camera_id: int):
    events = (
        db.query(AlertEvent)
        .join(Alert)
        .filter(Alert.camera_id == camera_id)
        .order_by(AlertEvent.triggered_at.asc())
        .all()
    )
    return [
        {
            "condition": e.alert.condition_text,
            "triggered_at": e.triggered_at.isoformat(),
            "reason": e.reason,
        }
        for e in events
    ]


def _execute_tool(db: Session, camera_id: int, name: str, tool_input: dict):
    if name == "search_frames":
        return _search_frames(
            db, camera_id,
            tool_input.get("start_time"),
            tool_input.get("end_time"),
            tool_input.get("keyword"),
        )
    if name == "get_alert_history":
        return _get_alert_history(db, camera_id)
    return {"error": f"unknown tool {name}"}


SYSTEM_PROMPT = """You are answering questions about footage from a security camera (camera_id={camera_id}). You don't have the footage directly — use search_frames and get_alert_history to look it up. Frames are sampled roughly every {interval} seconds.

Search strategy — follow this order:
1. Search with a specific keyword from the question (e.g. "dog", "car", "person").
2. If that returns nothing, immediately search again with no keyword to retrieve all frames. Never stop after one empty result.
3. If the user asks about a role or label ("thief", "intruder", "student"), also search for appearance terms ("person", "man", "woman", "individual", "black", "hoodie") — the vision model describes what it sees, not what the person is.
4. Once you have frames, reason about what was actually observed. A person in all-black clothing entering an empty home IS suspicious even if no alert fired. Describe what you see and draw a reasonable inference.

Rules:
- Never ask the user for more context. You have the footage — search it and reason from what you find.
- If only one frame exists, describe what that frame shows and answer as best you can from it.
- Do not say "no evidence" until you have searched with at least two different approaches (specific keyword + no keyword).
- Keep answers concise. No bullet lists asking clarifying questions.

Format in plain markdown. When citing a specific moment, include its ISO 8601 timestamp (e.g. 2026-06-29T14:23:15) — the UI makes these clickable."""


def answer_question(db: Session, camera_id: int, question: str, interval_seconds: int) -> str:
    has_frames = db.query(Frame).filter(Frame.camera_id == camera_id).first() is not None
    if not has_frames:
        return "There's no footage recorded for this camera yet."

    system = SYSTEM_PROMPT.format(camera_id=camera_id, interval=interval_seconds)
    messages = [{"role": "user", "content": question}]
    gathered_evidence = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=VISION_MODEL,
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text_blocks = [b.text for b in response.content if b.type == "text"]
            answer = "\n".join(text_blocks).strip() or "I couldn't determine an answer from the footage."
            return _validated(question, answer, gathered_evidence, messages, response, system)

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _execute_tool(db, camera_id, block.name, block.input)
                gathered_evidence.append({"tool": block.name, "input": block.input, "result": result})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
        messages.append({"role": "user", "content": tool_results})

    return "I wasn't able to find a clear answer after searching the footage log."


def _validated(question: str, answer: str, evidence: list, messages: list, last_response, system: str) -> str:
    if not evidence:
        return answer  # nothing to fact-check an answer against (e.g. "no footage" replies)

    check = validate_chat_answer(question, answer, evidence)
    if check.get("valid", True):
        return answer

    # one corrective pass, grounded in the reviewer's specific objection
    messages.append({"role": "assistant", "content": last_response.content})
    messages.append({
        "role": "user",
        "content": (
            f"A reviewer flagged an issue with that answer: {check.get('note', '')}. "
            "Revise your answer to be strictly accurate given only the evidence you already gathered. "
            "Don't call any more tools, just correct the answer."
        ),
    })
    retry = client.messages.create(model=VISION_MODEL, max_tokens=1024, system=system, messages=messages)
    text_blocks = [b.text for b in retry.content if b.type == "text"]
    return "\n".join(text_blocks).strip() or answer

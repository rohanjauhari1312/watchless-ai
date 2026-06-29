import json

import anthropic
from sqlalchemy.orm import Session

from app.config import ANTHROPIC_API_KEY, VISION_MODEL
from app.models import Alert, AlertEvent, Frame

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MAX_AGENTIC_ITERATIONS = 4

MATCH_PROMPT = """A user has set up this alert condition for their camera: "{condition}"

Here is what was observed in the latest frame:
{analysis}

Does this frame satisfy the alert condition? Respond with ONLY a JSON object: {{"matches": true or false, "reason": "short explanation"}}"""

AGENTIC_TOOLS = [
    {
        "name": "get_recent_frames",
        "description": "Get the N most recent frames observed on this camera before the current one, oldest first, for context on what's normal or already in progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "How many prior frames to fetch, default 10"},
            },
        },
    },
    {
        "name": "get_recent_alert_events",
        "description": "Get the most recent times this alert already fired, to avoid re-alerting on the same ongoing situation.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "submit_verdict",
        "description": "Submit your final decision on whether this alert should fire. Always call this exactly once to finish.",
        "input_schema": {
            "type": "object",
            "properties": {
                "matches": {"type": "boolean", "description": "True if this is a new, genuinely alert-worthy situation"},
                "reason": {"type": "string", "description": "Short explanation grounded in what you observed"},
            },
            "required": ["matches", "reason"],
        },
    },
]

AGENTIC_SYSTEM_PROMPT = """You are a security monitoring agent watching one camera for: "{condition}"

You've just received a new observation from the camera:
{analysis}
(captured at {timestamp})

Decide whether this is genuinely alert-worthy. Use get_recent_frames to see what was happening just before this, so you can tell ongoing/normal activity apart from something new or escalating. Use get_recent_alert_events to check whether you already flagged this same situation recently — if a person you already alerted on is simply still in frame doing the same thing, don't alert again; only alert again if something has materially changed (they did something new, a second person showed up, etc).

When you've decided, call submit_verdict exactly once with your answer. Don't explain your reasoning outside of that tool call."""


def _get_recent_frames(db: Session, camera_id: int, before_frame_id: int, count: int):
    frames = (
        db.query(Frame)
        .filter(Frame.camera_id == camera_id, Frame.id < before_frame_id)
        .order_by(Frame.timestamp.desc())
        .limit(count)
        .all()
    )
    return [
        {"timestamp": f.timestamp.isoformat(), "summary": f.summary, "analysis": f.analysis_json}
        for f in reversed(frames)
    ]


def _get_recent_alert_events(db: Session, alert_id: int):
    events = (
        db.query(AlertEvent)
        .filter(AlertEvent.alert_id == alert_id)
        .order_by(AlertEvent.triggered_at.desc())
        .limit(5)
        .all()
    )
    return [{"triggered_at": e.triggered_at.isoformat(), "reason": e.reason} for e in events]


def _evaluate_simple(db: Session, alert: Alert, frame: Frame):
    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": MATCH_PROMPT.format(
                    condition=alert.condition_text,
                    analysis=frame.analysis_json,
                ),
            }
        ],
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return
    if result.get("matches"):
        db.add(AlertEvent(alert_id=alert.id, frame_id=frame.id, reason=result.get("reason", "")))


def _evaluate_agentic(db: Session, alert: Alert, frame: Frame):
    system = AGENTIC_SYSTEM_PROMPT.format(
        condition=alert.condition_text,
        analysis=frame.analysis_json,
        timestamp=frame.timestamp.isoformat(),
    )
    messages = [{"role": "user", "content": "Evaluate the current observation now."}]

    for _ in range(MAX_AGENTIC_ITERATIONS):
        response = client.messages.create(
            model=VISION_MODEL,
            max_tokens=512,
            system=system,
            tools=AGENTIC_TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            return  # model didn't submit a verdict within budget; skip this frame

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        verdict = None
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_verdict":
                verdict = block.input
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": "recorded"})
                continue
            if block.name == "get_recent_frames":
                result = _get_recent_frames(db, alert.camera_id, frame.id, block.input.get("count", 10))
            elif block.name == "get_recent_alert_events":
                result = _get_recent_alert_events(db, alert.id)
            else:
                result = {"error": f"unknown tool {block.name}"}
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})

        if verdict is not None:
            if verdict.get("matches"):
                db.add(AlertEvent(alert_id=alert.id, frame_id=frame.id, reason=verdict.get("reason", "")))
            return

        messages.append({"role": "user", "content": tool_results})


def evaluate_alerts(db: Session, frame: Frame):
    alerts = (
        db.query(Alert)
        .filter(Alert.camera_id == frame.camera_id, Alert.active == True)  # noqa: E712
        .all()
    )
    if not alerts:
        return

    for alert in alerts:
        if alert.is_agentic:
            _evaluate_agentic(db, alert, frame)
        else:
            _evaluate_simple(db, alert, frame)
    db.commit()

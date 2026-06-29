import json

import anthropic
from sqlalchemy.orm import Session

from app.config import ANTHROPIC_API_KEY, VISION_MODEL
from app.models import Alert, AlertEvent, Frame

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MATCH_PROMPT = """A user has set up this alert condition for their camera: "{condition}"

Here is what was observed in the latest frame:
{analysis}

Does this frame satisfy the alert condition? Respond with ONLY a JSON object: {{"matches": true or false, "reason": "short explanation"}}"""


def evaluate_alerts(db: Session, frame: Frame):
    alerts = (
        db.query(Alert)
        .filter(Alert.camera_id == frame.camera_id, Alert.active == True)  # noqa: E712
        .all()
    )
    if not alerts:
        return

    for alert in alerts:
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
            continue

        if result.get("matches"):
            event = AlertEvent(
                alert_id=alert.id,
                frame_id=frame.id,
                reason=result.get("reason", ""),
            )
            db.add(event)
    db.commit()

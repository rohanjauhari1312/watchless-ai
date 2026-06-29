import base64
import json

import anthropic

from app.config import ANTHROPIC_API_KEY, VISION_MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ALERT_VALIDATION_PROMPT = """An automated alert system is about to notify a user that this camera frame matches the condition: "{condition}"

Its proposed reasoning was: "{reason}"

Look at the image yourself, independently, and judge whether this reasoning is actually correct and well-supported by what's visible. Be skeptical — the goal is to catch false positives before they reach the user. Respond with ONLY a JSON object: {{"valid": true or false, "reason": "short explanation of your independent judgment"}}"""

CHAT_VALIDATION_PROMPT = """A user asked a camera-footage assistant: "{question}"

It answered: "{answer}"

The evidence it had access to (from searching the footage log) was:
{evidence}

Independently judge whether the answer is fully supported by this evidence, without overstating, inventing details, or ignoring contradicting evidence. Respond with ONLY a JSON object: {{"valid": true or false, "note": "what's wrong, if anything"}}"""


def _parse_json(text: str, default: dict) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def validate_alert(image_path: str, condition_text: str, proposed_reason: str) -> dict:
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data},
                    },
                    {
                        "type": "text",
                        "text": ALERT_VALIDATION_PROMPT.format(
                            condition=condition_text, reason=proposed_reason
                        ),
                    },
                ],
            }
        ],
    )
    # Fail open: a validator hiccup shouldn't silently eat a real alert.
    return _parse_json(response.content[0].text, {"valid": True, "reason": "validator parse error"})


def validate_chat_answer(question: str, answer: str, evidence: list) -> dict:
    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": CHAT_VALIDATION_PROMPT.format(
                    question=question, answer=answer, evidence=json.dumps(evidence)[:8000]
                ),
            }
        ],
    )
    return _parse_json(response.content[0].text, {"valid": True, "note": ""})

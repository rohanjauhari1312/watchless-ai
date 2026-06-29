import base64
import json

import anthropic

from app.config import ANTHROPIC_API_KEY, VISION_MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

ANALYSIS_PROMPT = """Look at this camera frame and describe what you see as structured JSON only, no prose outside the JSON.

Schema:
{
  "summary": "one sentence describing the overall scene",
  "people": [
    {"description": "who they are/look like", "action": "what they're doing", "position": "where in frame"}
  ],
  "objects": [
    {"type": "object category e.g. car, dog, package", "attributes": "distinguishing details like color, size, breed", "action": "what it's doing or its state", "position": "where in frame"}
  ]
}

If there are no people or no notable objects, return empty lists for those fields. Be specific and consistent about attributes (always mention color/type for vehicles, breed/color for animals) so the same subject can be tracked across frames. Return ONLY the JSON object."""


def analyze_frame(image_path: str) -> dict:
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": ANALYSIS_PROMPT},
                ],
            }
        ],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"summary": text, "people": [], "objects": []}

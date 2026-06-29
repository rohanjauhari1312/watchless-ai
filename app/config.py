import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/watchless.db")
FRAME_SAMPLE_INTERVAL_SECONDS = int(os.environ.get("FRAME_SAMPLE_INTERVAL_SECONDS", "10"))
VISION_MODEL = os.environ.get("VISION_MODEL", "claude-haiku-4-5-20251001")

FRAMES_DIR = BASE_DIR / "data" / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

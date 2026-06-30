import json
import threading
import time
from datetime import datetime, timezone

import cv2

from app.alerts import evaluate_alerts
from app.config import FRAME_SAMPLE_INTERVAL_SECONDS, FRAMES_DIR
from app.db import SessionLocal
from app.models import Camera, Frame
from app.vision import analyze_frame

# camera_id -> threading.Event used to signal stop
_running_cameras: dict[int, threading.Event] = {}


def _process_frame(camera_id: int, frame_bgr, ts: datetime):
    image_path = FRAMES_DIR / f"camera_{camera_id}_{ts.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    cv2.imwrite(str(image_path), frame_bgr)

    analysis = analyze_frame(str(image_path))

    db = SessionLocal()
    try:
        frame = Frame(
            camera_id=camera_id,
            timestamp=ts,
            image_path=str(image_path),
            summary=analysis.get("summary", ""),
            analysis_json=json.dumps(analysis),
        )
        db.add(frame)
        db.commit()
        db.refresh(frame)
        evaluate_alerts(db, frame)
    finally:
        db.close()


def _ingest_loop(camera_id: int, source: str, stop_event: threading.Event, is_file: bool, interval: int):
    try:
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frame_interval = max(int(fps * interval), 1) if is_file and fps else None
        frame_count = 0
        last_capture_time = 0.0

        while not stop_event.is_set():
            ok, frame_bgr = cap.read()
            if not ok:
                if is_file:
                    break
                time.sleep(1)
                continue

            if is_file:
                frame_count += 1
                if frame_count % frame_interval != 0:
                    continue
                ts = datetime.now(timezone.utc)
                _process_frame(camera_id, frame_bgr, ts)
            else:
                now = time.monotonic()
                if now - last_capture_time < interval:
                    continue
                last_capture_time = now
                ts = datetime.now(timezone.utc)
                _process_frame(camera_id, frame_bgr, ts)

        cap.release()
    finally:
        _running_cameras.pop(camera_id, None)


def start_camera(camera: Camera):
    if camera.id in _running_cameras:
        return
    is_file = not str(camera.source).lower().startswith("rtsp://")
    interval = camera.interval_seconds or FRAME_SAMPLE_INTERVAL_SECONDS
    stop_event = threading.Event()
    _running_cameras[camera.id] = stop_event
    thread = threading.Thread(
        target=_ingest_loop,
        args=(camera.id, camera.source, stop_event, is_file, interval),
        daemon=True,
    )
    thread.start()


def stop_camera(camera_id: int):
    stop_event = _running_cameras.pop(camera_id, None)
    if stop_event:
        stop_event.set()


def is_camera_running(camera_id: int) -> bool:
    return camera_id in _running_cameras

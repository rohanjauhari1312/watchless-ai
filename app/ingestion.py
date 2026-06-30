import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

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


def _ingest_file(camera_id: int, source: str, stop_event: threading.Event, interval: int):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total_frames / fps if fps else 0
    base_time = datetime.now(timezone.utc)

    # Seek directly to each target position — no need to read every frame
    targets = []
    t = 0
    while t < duration_s:
        if stop_event.is_set():
            break
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame_bgr = cap.read()
        if ok:
            ts = base_time + timedelta(seconds=t)
            targets.append((frame_bgr, ts))
        t += interval

    cap.release()

    if not targets:
        return

    # Process all grabbed frames concurrently
    max_workers = min(len(targets), 5)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_process_frame, camera_id, frame_bgr, ts) for frame_bgr, ts in targets]
        for f in as_completed(futures):
            f.result()  # surface any exceptions


def _ingest_stream(camera_id: int, source: str, stop_event: threading.Event, interval: int):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        return

    last_capture_time = 0.0
    while not stop_event.is_set():
        ok, frame_bgr = cap.read()
        if not ok:
            time.sleep(1)
            continue
        now = time.monotonic()
        if now - last_capture_time >= interval:
            last_capture_time = now
            _process_frame(camera_id, frame_bgr, datetime.now(timezone.utc))

    cap.release()


def _ingest_loop(camera_id: int, source: str, stop_event: threading.Event, is_file: bool, interval: int):
    try:
        if is_file:
            _ingest_file(camera_id, source, stop_event, interval)
        else:
            _ingest_stream(camera_id, source, stop_event, interval)
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

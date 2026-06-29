import uuid
from pathlib import Path

import shutil
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.chat import answer_question
from app.config import BASE_DIR, FRAME_SAMPLE_INTERVAL_SECONDS
from app.db import get_db, init_db
from app.ingestion import is_camera_running, start_camera, stop_camera
from app.models import Alert, AlertEvent, Camera, Frame

UPLOADS_DIR = BASE_DIR / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="WatchlessAI")


@app.on_event("startup")
def on_startup():
    init_db()


# ---------- Cameras ----------

def _camera_or_404(db: Session, camera_id: int) -> Camera:
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


def _camera_dict(camera: Camera) -> dict:
    return {
        "id": camera.id,
        "name": camera.name,
        "source": camera.source,
        "active": is_camera_running(camera.id),
    }


class CameraBody(BaseModel):
    name: str
    rtsp_url: str


@app.post("/api/cameras")
def create_camera(body: CameraBody, db: Session = Depends(get_db)):
    camera = Camera(name=body.name, source=body.rtsp_url)
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return _camera_dict(camera)


@app.post("/api/cameras/upload")
def upload_camera(name: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    dest = UPLOADS_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    camera = Camera(name=name, source=str(dest))
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return _camera_dict(camera)


@app.get("/api/cameras")
def list_cameras(db: Session = Depends(get_db)):
    cameras = db.query(Camera).all()
    return [_camera_dict(c) for c in cameras]


@app.delete("/api/cameras/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = _camera_or_404(db, camera_id)
    stop_camera(camera.id)
    db.delete(camera)
    db.commit()
    return {"ok": True}


@app.post("/api/cameras/{camera_id}/start")
def start(camera_id: int, db: Session = Depends(get_db)):
    camera = _camera_or_404(db, camera_id)
    start_camera(camera)
    return _camera_dict(camera)


@app.post("/api/cameras/{camera_id}/stop")
def stop(camera_id: int, db: Session = Depends(get_db)):
    camera = _camera_or_404(db, camera_id)
    stop_camera(camera.id)
    return _camera_dict(camera)


# ---------- Frames ----------

@app.get("/api/cameras/{camera_id}/frames")
def list_frames(camera_id: int, db: Session = Depends(get_db)):
    _camera_or_404(db, camera_id)
    frames = (
        db.query(Frame)
        .filter(Frame.camera_id == camera_id)
        .order_by(Frame.timestamp.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": f.id,
            "timestamp": f.timestamp.isoformat(),
            "summary": f.summary,
            "analysis": f.analysis_json,
        }
        for f in frames
    ]


@app.get("/api/frames/{frame_id}/image")
def frame_image(frame_id: int, db: Session = Depends(get_db)):
    frame = db.query(Frame).filter(Frame.id == frame_id).first()
    if not frame or not Path(frame.image_path).exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(frame.image_path)


# ---------- Alerts ----------

class AlertBody(BaseModel):
    condition_text: str


@app.post("/api/cameras/{camera_id}/alerts")
def create_alert(camera_id: int, body: AlertBody, db: Session = Depends(get_db)):
    _camera_or_404(db, camera_id)
    alert = Alert(camera_id=camera_id, condition_text=body.condition_text)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return {"id": alert.id, "condition_text": alert.condition_text, "active": alert.active}


@app.get("/api/cameras/{camera_id}/alerts")
def list_alerts(camera_id: int, db: Session = Depends(get_db)):
    _camera_or_404(db, camera_id)
    alerts = db.query(Alert).filter(Alert.camera_id == camera_id).all()
    return [{"id": a.id, "condition_text": a.condition_text, "active": a.active} for a in alerts]


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.delete(alert)
    db.commit()
    return {"ok": True}


@app.get("/api/cameras/{camera_id}/alert-events")
def list_alert_events(camera_id: int, db: Session = Depends(get_db)):
    _camera_or_404(db, camera_id)
    events = (
        db.query(AlertEvent)
        .join(Alert)
        .filter(Alert.camera_id == camera_id)
        .order_by(AlertEvent.triggered_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": e.id,
            "alert_id": e.alert_id,
            "condition_text": e.alert.condition_text,
            "triggered_at": e.triggered_at.isoformat(),
            "reason": e.reason,
            "frame_id": e.frame_id,
        }
        for e in events
    ]


# ---------- Chat ----------

class ChatBody(BaseModel):
    question: str


@app.post("/api/cameras/{camera_id}/chat")
def chat(camera_id: int, body: ChatBody, db: Session = Depends(get_db)):
    _camera_or_404(db, camera_id)
    answer = answer_question(db, camera_id, body.question, FRAME_SAMPLE_INTERVAL_SECONDS)
    return {"answer": answer}


app.mount("/", StaticFiles(directory=str(BASE_DIR / "app" / "static"), html=True), name="static")

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    source = Column(String, nullable=False)  # rtsp:// url or local file path
    active = Column(Boolean, default=False)
    interval_seconds = Column(Integer, default=10)
    created_at = Column(DateTime, default=utcnow)

    frames = relationship("Frame", back_populates="camera", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="camera", cascade="all, delete-orphan")


class Frame(Base):
    __tablename__ = "frames"

    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=utcnow, index=True)
    image_path = Column(String, nullable=False)
    summary = Column(Text)
    analysis_json = Column(Text)  # raw structured JSON from vision model

    camera = relationship("Camera", back_populates="frames")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    condition_text = Column(String, nullable=False)
    active = Column(Boolean, default=True)
    is_agentic = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    camera = relationship("Camera", back_populates="alerts")
    events = relationship("AlertEvent", back_populates="alert", cascade="all, delete-orphan")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False, index=True)
    frame_id = Column(Integer, ForeignKey("frames.id"), nullable=False)
    triggered_at = Column(DateTime, default=utcnow)
    reason = Column(Text)

    alert = relationship("Alert", back_populates="events")

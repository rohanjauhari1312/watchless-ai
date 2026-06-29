from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_autocommit(dbapi_connection, connection_record):
    # pysqlite's default transaction handling can leave a connection holding a
    # stale read snapshot, invisible to commits made on other connections/threads
    # (e.g. the ingestion worker). Disabling its own transaction management and
    # letting SQLAlchemy issue explicit BEGIN statements keeps reads fresh.
    dbapi_connection.isolation_level = None


@event.listens_for(engine, "begin")
def _sqlite_begin(conn):
    conn.exec_driver_sql("BEGIN")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

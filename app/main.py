from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
import sqlite3, uuid, time
from pathlib import Path

app = FastAPI()

DB_PATH    = "/data/jobs.db"
UPLOAD_DIR = Path("/data/uploads")
AUDIO_DIR  = Path("/data/audio")
RESULT_DIR = Path("/data/results")

ALLOWED_EXT = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".m4v",
               ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus", ".wma"}

for d in [UPLOAD_DIR, AUDIO_DIR, RESULT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                filename TEXT,
                status TEXT DEFAULT 'pending',
                created_at REAL,
                transcript TEXT,
                summary TEXT,
                error TEXT,
                audio_duration REAL,
                started_at REAL,
                estimated_seconds INTEGER
            )
        """)
        for col, ctype in [
            ('audio_duration', 'REAL'),
            ('started_at', 'REAL'),
            ('estimated_seconds', 'INTEGER')
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ctype}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

init_db()

@app.get("/", response_class=HTMLResponse)
def index():
    with open("/app/templates/index.html") as f:
        return f.read()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Формат {ext} не поддерживается")
    dest = UPLOAD_DIR / f"{job_id}{ext}"
    # Потоковая запись чанками по 1 МБ — не загружаем файл в память
    # и не блокируем event loop на больших (до 2 ГБ) загрузках.
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (id, filename, status, created_at) VALUES (?,?,?,?)",
            (job_id, file.filename, "pending", time.time())
        )
        conn.commit()
    return {"job_id": job_id}

@app.get("/status/{job_id}")
def get_status(job_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT status, summary, error, filename, "
            "audio_duration, started_at, estimated_seconds "
            "FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Задача не найдена")
    s, summary, error, filename, dur, started, est = row
    return {"job_id": job_id, "filename": filename, "status": s,
            "summary": summary, "error": error,
            "audio_duration": dur, "started_at": started,
            "estimated_seconds": est}

@app.get("/jobs")
def list_jobs():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, filename, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [{"id": r[0], "filename": r[1], "status": r[2], "created_at": r[3]} for r in rows]

@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()
    return {"deleted": job_id}

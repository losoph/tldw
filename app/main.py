from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List, Any
import sqlite3, uuid, time, json
from pathlib import Path
from urllib.parse import urlparse

app = FastAPI()

DB_PATH    = "/data/jobs.db"
UPLOAD_DIR = Path("/data/uploads")
AUDIO_DIR  = Path("/data/audio")
RESULT_DIR = Path("/data/results")

ALLOWED_EXT = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".m4v",
               ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus", ".wma"}

# Домены, разрешённые для загрузки по ссылке (yt-dlp). Сверка по суффиксу.
ALLOWED_URL_HOSTS = ("vk.com", "vk.ru", "vkvideo.ru", "youtube.com", "youtu.be")

# Пресеты модульного саммари → набор секций (шаблоны секций — в worker.py).
# Промпты пользователю не показываются и им не редактируются (подход А).
PRESET_SECTIONS = {
    "full":     ["essence", "outline", "insights", "actions", "qa", "glossary", "navigation"],
    "express":  ["essence", "actions"],
    "konspekt": ["essence", "outline", "navigation"],
}

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
            ('estimated_seconds', 'INTEGER'),
            ('clip_start', 'REAL'),
            ('clip_end', 'REAL'),
            ('source_url', 'TEXT'),
            ('include_transcript', 'INTEGER'),
            ('sections', 'TEXT'),
            ('precheck', 'TEXT'),
            ('clips', 'TEXT'),     # JSON-список фрагментов [[start,end], ...]
            ('owner', 'TEXT'),     # логин пользователя (из nginx basic-auth) для изоляции истории
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ctype}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

init_db()

def parse_timecode(value: Optional[str]) -> Optional[float]:
    """'1:23:45' | '23:45' | '345' → секунды. Пустое значение → None."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    parts = value.split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() and p != "" for p in parts):
        raise HTTPException(400, f"Неверный таймкод «{value}» — нужен формат ЧЧ:ММ:СС, ММ:СС или секунды")
    parts = [int(p) for p in parts]
    if len(parts) == 2:
        h, m, s = 0, parts[0], parts[1]
    else:
        h, m, s = parts
    if m > 59 or s > 59:
        raise HTTPException(400, f"Неверный таймкод «{value}» — минуты и секунды должны быть < 60")
    return float(h * 3600 + m * 60 + s)

def parse_clips(raw: Any) -> list:
    """Принимает список пар [start, end] (строки-таймкоды или null) либо JSON-строку.
    Возвращает список [[cs, ce], ...] в секундах. Полностью пустые пары отбрасываются
    (пустой результат = обрабатываем видео целиком)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            raw = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "Некорректный список фрагментов")
    if not isinstance(raw, list):
        raise HTTPException(400, "Список фрагментов должен быть массивом пар «с–по»")
    clips = []
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise HTTPException(400, "Каждый фрагмент — это пара «с–по»")
        cs = parse_timecode(str(pair[0]) if pair[0] is not None else None)
        ce = parse_timecode(str(pair[1]) if pair[1] is not None else None)
        if cs is None and ce is None:
            continue
        if cs is not None and ce is not None and ce <= cs:
            raise HTTPException(400, "Таймкод «по» должен быть больше таймкода «с»")
        clips.append([cs, ce])
    return clips

def validate_options(clips_raw, preset):
    clips = parse_clips(clips_raw)
    if preset not in PRESET_SECTIONS:
        raise HTTPException(400, f"Неизвестный пресет саммари: {preset}")
    return clips

def create_job(filename, source_url, clips, include_transcript, preset, owner):
    job_id = str(uuid.uuid4())
    first = clips[0] if clips else [None, None]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (id, filename, status, created_at, source_url, "
            "clip_start, clip_end, clips, include_transcript, sections, owner) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, filename, "pending", time.time(), source_url,
             first[0], first[1], json.dumps(clips),
             1 if include_transcript else 0,
             json.dumps(PRESET_SECTIONS[preset]), owner)
        )
        conn.commit()
    return job_id

@app.get("/", response_class=HTMLResponse)
def index():
    with open("/app/templates/index.html") as f:
        return f.read()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/whoami")
def whoami(x_auth_user: Optional[str] = Header(None)):
    return {"user": x_auth_user}

@app.post("/upload")
async def upload(file: UploadFile = File(...),
                 clips: Optional[str] = Form(None),
                 include_transcript: bool = Form(False),
                 preset: str = Form("full"),
                 x_auth_user: Optional[str] = Header(None)):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Формат {ext} не поддерживается")
    parsed_clips = validate_options(clips, preset)
    job_id = create_job(file.filename, None, parsed_clips, include_transcript, preset, x_auth_user)
    dest = UPLOAD_DIR / f"{job_id}{ext}"
    # Потоковая запись чанками по 1 МБ — не загружаем файл в память
    # и не блокируем event loop на больших (до 2 ГБ) загрузках.
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    return {"job_id": job_id}

class UrlJob(BaseModel):
    url: str
    clips: Optional[List[Any]] = None
    include_transcript: bool = False
    preset: str = "full"

@app.post("/upload_url")
def upload_url(body: UrlJob, x_auth_user: Optional[str] = Header(None)):
    parsed = urlparse(body.url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "Некорректная ссылка")
    host = parsed.hostname.lower()
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_URL_HOSTS):
        raise HTTPException(400, "Поддерживаются ссылки на VK Видео и YouTube")
    parsed_clips = validate_options(body.clips, body.preset)
    job_id = create_job(body.url.strip(), body.url.strip(), parsed_clips,
                        body.include_transcript, body.preset, x_auth_user)
    return {"job_id": job_id}

@app.get("/status/{job_id}")
def get_status(job_id: str, x_auth_user: Optional[str] = Header(None)):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, summary, error, filename, transcript, "
            "audio_duration, started_at, estimated_seconds, "
            "include_transcript, precheck, source_url "
            "FROM jobs WHERE id=? AND owner IS ?", (job_id, x_auth_user)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Задача не найдена")
    return {"job_id": job_id, "filename": row["filename"], "status": row["status"],
            "summary": row["summary"], "error": row["error"],
            "audio_duration": row["audio_duration"], "started_at": row["started_at"],
            "estimated_seconds": row["estimated_seconds"],
            "precheck": row["precheck"], "source_url": row["source_url"],
            "transcript": row["transcript"] if row["include_transcript"] else None}

@app.get("/jobs")
def list_jobs(x_auth_user: Optional[str] = Header(None)):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, filename, status, created_at, source_url "
            "FROM jobs WHERE owner IS ? ORDER BY created_at DESC LIMIT 50",
            (x_auth_user,)
        ).fetchall()
    return [{"id": r[0], "filename": r[1], "status": r[2],
             "created_at": r[3], "source_url": r[4]} for r in rows]

@app.delete("/jobs/{job_id}")
def delete_job(job_id: str, x_auth_user: Optional[str] = Header(None)):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM jobs WHERE id=? AND owner IS ?", (job_id, x_auth_user))
        conn.commit()
    return {"deleted": job_id}

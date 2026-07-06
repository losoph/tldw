import sqlite3, os, time, subprocess, logging
from pathlib import Path
from openai import OpenAI
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH    = "/data/jobs.db"
UPLOAD_DIR = Path("/data/uploads")
AUDIO_DIR  = Path("/data/audio")

WHISPER_MODEL    = os.getenv("WHISPER_MODEL", "small")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
LANGUAGE         = os.getenv("LANGUAGE", "ru")

# Потоки CPU для faster-whisper: ставьте по числу ядер VPS (или чуть больше)
CPU_THREADS = int(os.getenv("CPU_THREADS", "4"))

# Real-Time Factor: сколько секунд обработки на 1 секунду аудио
# Для small int8 + beam=2 + VAD на 2-core VPS: ~2.0
RTF = float(os.getenv("RTF", "2.0"))

if not DEEPSEEK_API_KEY:
    log.warning("DEEPSEEK_API_KEY не задан в .env — саммаризация будет падать с ошибкой авторизации")

# timeout=300: не даём запросу к DeepSeek зависнуть навсегда на длинных транскриптах
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com", timeout=300.0)

log.info(f"Загрузка модели Whisper: {WHISPER_MODEL} (cpu_threads={CPU_THREADS})...")
whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS, num_workers=1)
log.info("Модель загружена. Воркер готов к работе.")

SUMMARY_PROMPT = """Ты — профессиональный аналитик контента. Перед тобой транскрипция видео или вебинара на русском языке с таймкодами.

Создай детальный структурированный конспект. НЕ пересказывай дословно — извлекай смысл, факты, структуру.

## 🎯 Суть материала
4-6 предложений: кто говорит, о чём, для кого, главный тезис и вывод.

## 📖 Конспект по блокам
Раздели на логические темы. Для каждой:
**[MM:SS] Название темы**
- Ключевые тезисы и утверждения
- Конкретные цифры, факты, термины, имена
- Примеры и кейсы

## 💡 Главные идеи и инсайты
7-10 пунктов готовых к применению знаний.

## ✅ Action Items
Задачи, рекомендации, шаги.

## ❓ Вопросы и ответы
Если есть Q&A — ключевые вопросы и ответы.

## 🔑 Глоссарий
Термины, аббревиатуры, инструменты, имена.

## 🕐 Навигация
12-15 ключевых моментов с таймкодами.

Правила: пиши на русском, только факты из транскрипции, не домысливай.

Транскрипция:
"""

def reset_stuck_jobs():
    with sqlite3.connect(DB_PATH) as conn:
        n = conn.execute(
            "UPDATE jobs SET status='error', error='Сброшено при перезапуске' "
            "WHERE status NOT IN ('done', 'error')"
        ).rowcount
        conn.commit()
    if n: log.info(f"Сброшено зависших задач: {n}")

def set_status(job_id, status, **kwargs):
    fields = ", ".join(f"{k}=?" for k in kwargs)
    vals = [status] + list(kwargs.values()) + [job_id]
    with sqlite3.connect(DB_PATH) as conn:
        q = f"UPDATE jobs SET status=?{', ' + fields if fields else ''} WHERE id=?"
        conn.execute(q, vals)
        conn.commit()

def get_audio_duration(audio_path):
    try:
        r = subprocess.run([
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(audio_path)
        ], capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def fmt_min(seconds):
    return f"{seconds/60:.1f} мин"

def process(job_id, filename):
    log.info(f"Обработка {job_id} ({filename})")

    upload_file = next((f for f in UPLOAD_DIR.iterdir() if f.stem == job_id), None)
    if not upload_file:
        set_status(job_id, "error", error="Файл загрузки не найден")
        return

    set_status(job_id, "extracting_audio")
    audio_path = AUDIO_DIR / f"{job_id}.wav"
    r = subprocess.run([
        "ffmpeg", "-i", str(upload_file),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_path), "-y"
    ], capture_output=True, text=True)
    if r.returncode != 0:
        set_status(job_id, "error", error=f"FFmpeg: {r.stderr[-400:]}")
        return

    duration = get_audio_duration(audio_path)
    estimated = int(duration * RTF)
    started = time.time()
    log.info(f"  Аудио: {fmt_min(duration)} · оценка обработки: ~{fmt_min(estimated)}")

    set_status(job_id, "transcribing",
               audio_duration=duration,
               started_at=started,
               estimated_seconds=estimated)

    try:
        segments, _ = whisper.transcribe(
            str(audio_path),
            language=LANGUAGE,
            beam_size=2,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
            initial_prompt="Транскрипция вебинара на русском языке."
        )
        lines = []
        for seg in segments:
            m, s = int(seg.start // 60), int(seg.start % 60)
            lines.append(f"[{m:02d}:{s:02d}] {seg.text.strip()}")
        transcript = "\n".join(lines)
        actual = time.time() - started
        actual_rtf = actual / duration if duration else 0
        log.info(f"  Транскрипция готова: {len(lines)} сегментов · "
                 f"факт {fmt_min(actual)} (RTF={actual_rtf:.2f}x)")
    except Exception as e:
        set_status(job_id, "error", error=f"Whisper: {e}")
        return

    set_status(job_id, "summarizing")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": SUMMARY_PROMPT + transcript[:180000]}],
            max_tokens=6000
        )
        summary = resp.choices[0].message.content
    except Exception as e:
        set_status(job_id, "error", error=f"DeepSeek: {e}")
        return

    set_status(job_id, "done", summary=summary)
    for p in [upload_file, audio_path]:
        try: p.unlink()
        except Exception: pass
    total = time.time() - started
    log.info(f"Задача {job_id} завершена за {fmt_min(total)}")

def main():
    reset_stuck_jobs()
    log.info(f"Воркер запущен (RTF={RTF}). Ожидание задач...")
    while True:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT id, filename FROM jobs WHERE status='pending' LIMIT 1"
            ).fetchone()
        if row:
            try:
                process(row[0], row[1])
            except Exception as e:
                log.error(f"Критическая ошибка в {row[0]}: {e}")
                set_status(row[0], "error", error=str(e))
        else:
            time.sleep(3)

if __name__ == "__main__":
    main()

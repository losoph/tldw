import sqlite3, os, time, subprocess, logging, json, re
from pathlib import Path
from urllib.parse import urlparse
from openai import OpenAI
from faster_whisper import WhisperModel
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH     = "/data/jobs.db"
UPLOAD_DIR  = Path("/data/uploads")
AUDIO_DIR   = Path("/data/audio")
COOKIES_DIR = Path("/data/cookies")   # netscape-формат: <домен>.txt (например vk.com.txt)
PROXIES_YML = Path("/data/proxies.yml")  # домен → URL прокси для yt-dlp
DENO_BIN    = Path("/data/bin/deno")   # JS-рантайм для YouTube (n-challenge); кладётся в volume

WHISPER_MODEL    = os.getenv("WHISPER_MODEL", "small")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
LANGUAGE         = os.getenv("LANGUAGE", "ru")

# Потоки CPU для faster-whisper: ставьте по числу ядер VPS (или чуть больше)
CPU_THREADS = int(os.getenv("CPU_THREADS", "4"))

# Real-Time Factor: сколько секунд обработки на 1 секунду аудио
# Для small int8 + beam=2 + VAD на 2-core VPS: ~2.0
RTF = float(os.getenv("RTF", "2.0"))

COOKIES_DIR.mkdir(parents=True, exist_ok=True)

if not DEEPSEEK_API_KEY:
    log.warning("DEEPSEEK_API_KEY не задан в .env — саммаризация будет падать с ошибкой авторизации")

# timeout=300: не даём запросу к DeepSeek зависнуть навсегда на длинных транскриптах
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com", timeout=300.0)

log.info(f"Загрузка модели Whisper: {WHISPER_MODEL} (cpu_threads={CPU_THREADS})...")
whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS, num_workers=1)
log.info("Модель загружена. Воркер готов к работе.")

# ── Модульное саммари ───────────────────────────────────────────────────────
# Промпт собирается из секций по полю sections задачи (пресет выбирается в UI,
# маппинг пресет → секции — в main.py). Один вызов LLM (подход А).

PROMPT_HEADER = """Ты — профессиональный аналитик контента. Перед тобой транскрипция видео или вебинара на русском языке с таймкодами.

Создай структурированный конспект строго по разделам, указанным ниже, в заданном порядке. НЕ пересказывай дословно — извлекай смысл, факты, структуру.

"""

PROMPT_FOOTER = """
Правила: пиши на русском, только факты из транскрипции, не домысливай, не добавляй разделов сверх указанных.

Транскрипция:
"""

SECTION_TEMPLATES = {
    "essence": """## 🎯 Суть материала
4-6 предложений: кто говорит, о чём, для кого, главный тезис и вывод.""",
    "outline": """## 📖 Конспект по блокам
Раздели на логические темы. Для каждой:
**[ММ:СС] Название темы**
- Ключевые тезисы и утверждения
- Конкретные цифры, факты, термины, имена
- Примеры и кейсы""",
    "insights": """## 💡 Главные идеи и инсайты
7-10 пунктов готовых к применению знаний.""",
    "actions": """## ✅ Action Items
Задачи, рекомендации, шаги.""",
    "qa": """## ❓ Вопросы и ответы
Если есть Q&A — ключевые вопросы и ответы.""",
    "glossary": """## 🔑 Глоссарий
Термины, аббревиатуры, инструменты, имена.""",
    "navigation": """## 🕐 Навигация
12-15 ключевых моментов с таймкодами.""",
}

def build_prompt(sections_json):
    try:
        keys = json.loads(sections_json) if sections_json else []
    except (TypeError, ValueError):
        keys = []
    blocks = [SECTION_TEMPLATES[k] for k in keys if k in SECTION_TEMPLATES]
    if not blocks:
        blocks = list(SECTION_TEMPLATES.values())
    return PROMPT_HEADER + "\n\n".join(blocks) + PROMPT_FOOTER

# ── Служебные ───────────────────────────────────────────────────────────────

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

def fmt_ts(seconds):
    """Таймкод для транскрипта: ММ:СС, при длительности от часа — Ч:ММ:СС."""
    t = int(seconds)
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

# ── Загрузка по ссылке (yt-dlp) ─────────────────────────────────────────────

def load_proxies():
    try:
        if PROXIES_YML.exists():
            data = yaml.safe_load(PROXIES_YML.read_text()) or {}
            if isinstance(data, dict):
                return {str(k).lower(): str(v) for k, v in data.items() if v}
    except Exception as e:
        log.warning(f"Не удалось прочитать {PROXIES_YML}: {e}")
    return {}

def match_by_domain(host, table):
    """Ищет значение по хосту с обходом суффиксов: m.vk.com → m.vk.com, vk.com."""
    parts = host.split(".")
    for i in range(len(parts) - 1):
        key = ".".join(parts[i:])
        if key in table:
            return table[key]
    return None

def find_cookies(host):
    files = {f.name[:-4].lower(): f for f in COOKIES_DIR.glob("*.txt")}
    return match_by_domain(host, files)

def friendly_download_error(stderr, host):
    tail = stderr.strip()[-300:]
    low = stderr.lower()
    if any(p in low for p in ("login", "sign in", "logged-in", "authorization",
                              "cookies", "403", "only available for registered")):
        return (f"Не удалось скачать: похоже, нужна авторизация — cookies для {host} "
                f"отсутствуют или протухли. Обновите файл data/cookies/{host}.txt "
                f"(инструкция: docs/OPERATIONS.md → «Обновление VK-cookies»). Детали: {tail}")
    if "unsupported url" in low:
        return f"Ссылка не поддерживается yt-dlp: {tail}"
    if any(p in low for p in ("video unavailable", "private video", "removed")):
        return f"Видео недоступно (удалено или приватное): {tail}"
    return f"Ошибка скачивания: {tail}"

def download_url(job_id, url, clip_start, clip_end):
    """Скачивает только аудио через yt-dlp. Возвращает (path, title) или бросает RuntimeError."""
    host = (urlparse(url).hostname or "").lower()
    title_file = AUDIO_DIR / f"{job_id}.title"
    cmd = ["yt-dlp", "-f", "bestaudio/best", "--no-playlist", "--no-progress",
           "--socket-timeout", "30",
           "-o", str(UPLOAD_DIR / f"{job_id}.%(ext)s"),
           "--print-to-file", "%(title)s", str(title_file)]
    proxy = match_by_domain(host, load_proxies())
    if proxy:
        cmd += ["--proxy", proxy]
        log.info(f"  yt-dlp: прокси для {host} из proxies.yml")
    # YouTube требует JS-рантайм для n-challenge; node yt-dlp считает unsupported,
    # поэтому deno-бинарник из volume (см. docs/OPERATIONS.md → JS-рантайм для YouTube)
    if DENO_BIN.exists():
        cmd += ["--js-runtimes", f"deno:{DENO_BIN}"]
    cookies = find_cookies(host)
    if cookies:
        cmd += ["--cookies", str(cookies)]
        log.info(f"  yt-dlp: cookies {cookies.name}")
    if clip_start is not None or clip_end is not None:
        section = f"*{int(clip_start or 0)}-{int(clip_end) if clip_end else 'inf'}"
        cmd += ["--download-sections", section]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Скачивание не уложилось в 60 минут — прервано")
    if r.returncode != 0:
        raise RuntimeError(friendly_download_error(r.stderr, host))
    path = next((f for f in UPLOAD_DIR.iterdir() if f.stem == job_id), None)
    if not path:
        raise RuntimeError("yt-dlp завершился успешно, но файл не найден")
    title = None
    try:
        title = title_file.read_text().strip().splitlines()[0]
        title_file.unlink()
    except Exception:
        pass
    return path, title

# ── Пре-чек качества (уровень 1) ────────────────────────────────────────────
# ffprobe: битрейт исходника; ffmpeg: средняя громкость + доля тишины.
# Не блокирует обработку: 🟢 молча, 🟡/🔴 — баннер в UI. Пороги ориентировочные,
# калибруются по реальным записям (см. открытые вопросы TLDW_CONTEXT).

def _bump(level, new):
    rank = {"green": 0, "yellow": 1, "red": 2}
    return new if rank[new] > rank[level] else level

def run_precheck(source_path, wav_path, duration):
    level, messages, metrics = "green", [], {}
    try:
        r = subprocess.run([
            "ffprobe", "-v", "quiet", "-select_streams", "a:0",
            "-show_entries", "stream=bit_rate", "-of", "csv=p=0", str(source_path)
        ], capture_output=True, text=True, timeout=15)
        kbps = int(r.stdout.strip()) / 1000
        metrics["audio_kbps"] = round(kbps)
        if kbps < 16:
            level = _bump(level, "red")
            messages.append(f"очень низкий битрейт аудио ({kbps:.0f} кбит/с)")
        elif kbps < 32:
            level = _bump(level, "yellow")
            messages.append(f"низкий битрейт аудио ({kbps:.0f} кбит/с)")
    except Exception:
        pass
    try:
        r = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", str(wav_path),
            "-af", "volumedetect,silencedetect=noise=-35dB:d=2",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=180)
        m = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", r.stderr)
        if m:
            mean_vol = float(m.group(1))
            metrics["mean_volume_db"] = mean_vol
            if mean_vol < -45:
                level = _bump(level, "red")
                messages.append(f"очень тихая запись (средняя громкость {mean_vol:.0f} дБ)")
            elif mean_vol < -33:
                level = _bump(level, "yellow")
                messages.append(f"тихая запись (средняя громкость {mean_vol:.0f} дБ)")
        if duration:
            silence = sum(float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", r.stderr))
            share = silence / duration
            metrics["silence_share"] = round(share, 2)
            if share > 0.75:
                level = _bump(level, "red")
                messages.append(f"файл почти целиком тишина ({share*100:.0f}%)")
            elif share > 0.45:
                level = _bump(level, "yellow")
                messages.append(f"много тишины ({share*100:.0f}% файла)")
    except Exception as e:
        log.warning(f"  Пре-чек не удался: {e}")
    if level != "green":
        log.info(f"  Пре-чек: {level} — {'; '.join(messages)}")
    return json.dumps({"level": level, "messages": messages, "metrics": metrics},
                      ensure_ascii=False)

# ── Основной пайплайн ───────────────────────────────────────────────────────

def process(job):
    job_id, filename = job["id"], job["filename"]
    clip_start, clip_end = job["clip_start"], job["clip_end"]
    log.info(f"Обработка {job_id} ({filename})")

    if job["source_url"]:
        set_status(job_id, "downloading")
        try:
            upload_file, title = download_url(job_id, job["source_url"], clip_start, clip_end)
        except RuntimeError as e:
            set_status(job_id, "error", error=str(e))
            return
        if title:
            set_status(job_id, "downloading", filename=title)
        log.info(f"  Скачано: {upload_file.name} ({title or 'без названия'})")
        # клип уже вырезан на этапе скачивания (--download-sections)
        ffmpeg_clip = []
    else:
        upload_file = next((f for f in UPLOAD_DIR.iterdir() if f.stem == job_id), None)
        if not upload_file:
            set_status(job_id, "error", error="Файл загрузки не найден")
            return
        # -ss/-to перед -i: быстрый seek без декодирования всего файла
        ffmpeg_clip = []
        if clip_start is not None:
            ffmpeg_clip += ["-ss", str(clip_start)]
        if clip_end is not None:
            ffmpeg_clip += ["-to", str(clip_end)]

    set_status(job_id, "extracting_audio")
    audio_path = AUDIO_DIR / f"{job_id}.wav"
    r = subprocess.run(
        ["ffmpeg"] + ffmpeg_clip + [
            "-i", str(upload_file),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_path), "-y"
        ], capture_output=True, text=True)
    if r.returncode != 0:
        set_status(job_id, "error", error=f"FFmpeg: {r.stderr[-400:]}")
        return

    duration = get_audio_duration(audio_path)
    precheck = run_precheck(upload_file, audio_path, duration)
    estimated = int(duration * RTF)
    started = time.time()
    log.info(f"  Аудио: {fmt_min(duration)} · оценка обработки: ~{fmt_min(estimated)}")

    set_status(job_id, "transcribing",
               audio_duration=duration,
               started_at=started,
               estimated_seconds=estimated,
               precheck=precheck)

    # Таймкоды в транскрипте смещаем к исходнику, если обрабатывается фрагмент
    offset = clip_start or 0.0
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
        lines = [f"[{fmt_ts(seg.start + offset)}] {seg.text.strip()}" for seg in segments]
        transcript = "\n".join(lines)
        actual = time.time() - started
        actual_rtf = actual / duration if duration else 0
        log.info(f"  Транскрипция готова: {len(lines)} сегментов · "
                 f"факт {fmt_min(actual)} (RTF={actual_rtf:.2f}x)")
    except Exception as e:
        set_status(job_id, "error", error=f"Whisper: {e}")
        return

    # Транскрипт сохраняем всегда (галочка в UI управляет только выдачей)
    set_status(job_id, "summarizing", transcript=transcript)
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user",
                       "content": build_prompt(job["sections"]) + transcript[:180000]}],
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
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, filename, source_url, clip_start, clip_end, sections "
                "FROM jobs WHERE status='pending' ORDER BY created_at LIMIT 1"
            ).fetchone()
        if row:
            try:
                process(row)
            except Exception as e:
                log.error(f"Критическая ошибка в {row['id']}: {e}")
                set_status(row["id"], "error", error=str(e))
        else:
            time.sleep(3)

if __name__ == "__main__":
    main()

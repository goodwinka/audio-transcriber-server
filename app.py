"""
Сервер транскрипции аудио → текст.
Поддерживаемые движки:
  vosk          — Vosk, CPU, быстро, офлайн
  faster_whisper — Faster-Whisper, CPU int8, лучшее качество (оптимально для Intel)
  openvino      — OpenVINO, Intel iGPU/CPU, требует optimum[openvino]
  gigaam        — GigaAM v3 ONNX, русский ASR, требует onnx-asr
  whisper_hf    — OpenAI Whisper через HuggingFace transformers
  ggml          — Whisper GGML через pywhispercpp
"""

import os, json, wave, subprocess, time, re
from datetime import datetime
from pathlib import Path

from flask import Flask, request, render_template, send_file, jsonify, make_response

# ── Конфигурация ────────────────────────────────────────────────
MODELS_DIR  = Path(os.environ.get("MODELS_DIR", "models"))
UPLOAD_DIR  = Path("uploads")
OUTPUT_DIR  = Path("outputs")
HISTORY_FILE = Path("history.json")
ALLOWED_EXT  = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".webm"}
MAX_FILE_MB  = 500

for d in (MODELS_DIR, UPLOAD_DIR, OUTPUT_DIR):
    d.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * 1024 * 1024
app.json.ensure_ascii = False  # Serve Cyrillic as-is in JSON responses

# ── Определение доступных движков ──────────────────────────────
_vosk_ok = _fw_ok = _ov_ok = _gigaam_ok = _whisper_hf_ok = _ggml_ok = False
_ov_devices: list[str] = []

try:
    from vosk import Model as _VoskModel, KaldiRecognizer as _KaldiRec
    _vosk_ok = True
except ImportError:
    pass

try:
    from faster_whisper import WhisperModel as _FWModel
    _fw_ok = True
except ImportError:
    pass

try:
    import openvino as _ov
    _ov_devices = _ov.Core().available_devices   # ['CPU', 'GPU', 'GPU.0', ...]
    _ov_ok = True
except ImportError:
    pass

try:
    import onnx_asr as _onnx_asr
    _gigaam_ok = True
except ImportError:
    pass

try:
    from transformers import pipeline as _hf_pipeline
    _whisper_hf_ok = True
except ImportError:
    pass

try:
    from pywhispercpp.model import Model as _GgmlModel
    _ggml_ok = True
except ImportError:
    pass

# ── Кэш загруженных моделей ─────────────────────────────────────
_cache: dict = {}

# ═══════════════════════════════════════════════════════════════
#  VOSK
# ═══════════════════════════════════════════════════════════════
VOSK_KNOWN = {
    "small-ru": {
        "name": "Русская маленькая (45 МБ, быстро)",
        "url":  "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
        "dir":  "vosk-model-small-ru-0.22",
    },
    "ru": {
        "name": "Русская большая v0.42 (1.8 ГБ, точнее)",
        "url":  "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
        "dir":  "vosk-model-ru-0.42",
    },
    "small-en": {
        "name": "English small (40 МБ)",
        "url":  "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "dir":  "vosk-model-small-en-us-0.15",
    },
}

def _vosk_model_valid(p: Path) -> bool:
    return (p / "am").is_dir() and (p / "conf").is_dir()

def _vosk_path(model_id: str) -> Path:
    info = VOSK_KNOWN.get(model_id)
    if info:
        # обратная совместимость: старая папка model/ считается small-ru
        legacy = Path("model")
        if legacy.exists() and model_id == "small-ru" and _vosk_model_valid(legacy):
            return legacy
        # Поддержка списка кандидатов (первый валидный)
        dirs = info.get("dirs") or [info["dir"]]
        for d in dirs:
            p = MODELS_DIR / "vosk" / d
            if _vosk_model_valid(p):
                return p
        return MODELS_DIR / "vosk" / dirs[0]
    return MODELS_DIR / "vosk" / model_id

def vosk_list() -> list:
    rows = []
    for mid, info in VOSK_KNOWN.items():
        rows.append({"id": mid, "name": info["name"], "available": _vosk_model_valid(_vosk_path(mid))})
    # пользовательские папки
    vosk_dir = MODELS_DIR / "vosk"
    if vosk_dir.exists():
        known_dirs = set()
        for v in VOSK_KNOWN.values():
            known_dirs.update(v.get("dirs") or [v.get("dir", "")])
        for p in vosk_dir.iterdir():
            if p.is_dir() and p.name not in known_dirs and _vosk_model_valid(p):
                rows.append({"id": p.name, "name": p.name, "available": True})
    return rows

def vosk_transcribe(wav_path: str, model_id: str) -> str:
    key = f"vosk:{model_id}"
    if key not in _cache:
        mdir = _vosk_path(model_id)
        if not mdir.exists():
            raise FileNotFoundError(
                f"Модель Vosk '{model_id}' не найдена.\n"
                f"Скачайте: {VOSK_KNOWN.get(model_id, {}).get('url', 'https://alphacephei.com/vosk/models')}\n"
                f"Распакуйте в: {mdir}"
            )
        print(f"[*] Загрузка Vosk {model_id}...")
        _cache[key] = _VoskModel(str(mdir))
        print(f"[✓] Vosk {model_id} загружена")

    rec = _KaldiRec(_cache[key], 16000)
    rec.SetWords(False)
    wf = wave.open(wav_path, "rb")
    chunks = []
    while True:
        data = wf.readframes(8000)
        if not data:
            break
        if rec.AcceptWaveform(data):
            t = json.loads(rec.Result()).get("text", "").strip()
            if t:
                chunks.append(t)
    t = json.loads(rec.FinalResult()).get("text", "").strip()
    if t:
        chunks.append(t)
    wf.close()
    return format_text(chunks)


# ═══════════════════════════════════════════════════════════════
#  FASTER-WHISPER  (CPU int8 — оптимально для Intel)
# ═══════════════════════════════════════════════════════════════
FW_MODELS = [
    {"id": "tiny",     "name": "Tiny   (~75 МБ) — максимальная скорость"},
    {"id": "base",     "name": "Base   (~145 МБ) — быстро"},
    {"id": "small",    "name": "Small  (~466 МБ) — баланс"},
    {"id": "medium",   "name": "Medium (~1.5 ГБ) — точнее"},
    {"id": "large-v3", "name": "Large-v3 (~3 ГБ) — лучшее качество"},
]
FW_CACHE = str(MODELS_DIR / "faster-whisper")

def fw_list() -> list:
    fw_dir = MODELS_DIR / "faster-whisper"
    result = []
    for m in FW_MODELS:
        local = fw_dir / m["id"]
        # HuggingFace cache format: models--Systran--faster-whisper-{id}
        hf_cache = fw_dir / f"models--Systran--faster-whisper-{m['id']}"
        downloaded = local.exists() or hf_cache.exists()
        # модели скачиваются автоматически — всегда доступны
        result.append({"id": m["id"], "name": m["name"], "available": True,
                        "downloaded": downloaded})
    return result

def fw_transcribe(wav_path: str, model_id: str, language: str = "ru") -> str:
    key = f"fw:{model_id}"
    if key not in _cache:
        print(f"[*] Загрузка Faster-Whisper {model_id} (int8)...")
        _cache[key] = _FWModel(
            model_id,
            device="cpu",
            compute_type="int8",
            download_root=FW_CACHE,
        )
        print(f"[✓] Faster-Whisper {model_id} загружена")

    lang = language if language != "auto" else None
    segments, _ = _cache[key].transcribe(wav_path, language=lang, beam_size=5)
    chunks = [s.text.strip() for s in segments if s.text.strip()]
    return format_text(chunks)


# ═══════════════════════════════════════════════════════════════
#  OPENVINO  (Intel iGPU / CPU через optimum[openvino])
# ═══════════════════════════════════════════════════════════════
OV_MODELS = [
    {"id": "whisper-tiny",   "name": "Whisper Tiny   (~75 МБ)",
     "hf": "openai/whisper-tiny"},
    {"id": "whisper-small",  "name": "Whisper Small  (~466 МБ)",
     "hf": "openai/whisper-small"},
    {"id": "whisper-medium", "name": "Whisper Medium (~1.5 ГБ)",
     "hf": "openai/whisper-medium"},
]
OV_HF = {m["id"]: m["hf"] for m in OV_MODELS}

def ov_list() -> list:
    result = []
    for m in OV_MODELS:
        local = MODELS_DIR / "openvino" / m["id"]
        result.append({"id": m["id"], "name": m["name"], "available": local.exists()})
    return result

def ov_transcribe(wav_path: str, model_id: str, device: str = "GPU",
                  language: str = "ru") -> str:
    try:
        from optimum.intel import OVModelForSpeechSeq2Seq
        from transformers import AutoProcessor, pipeline as hf_pipeline
    except ImportError:
        raise RuntimeError(
            "Для OpenVINO нужно установить:\n"
            "  pip install optimum[openvino] transformers"
        )

    key = f"ov:{model_id}:{device}"
    if key not in _cache:
        model_dir = MODELS_DIR / "openvino" / model_id
        hf_id = OV_HF.get(model_id, model_id)
        print(f"[*] Загрузка OpenVINO {model_id} → {device}...")
        if model_dir.exists():
            processor = AutoProcessor.from_pretrained(str(model_dir))
            ov_model  = OVModelForSpeechSeq2Seq.from_pretrained(str(model_dir), device=device)
        else:
            model_dir.mkdir(parents=True, exist_ok=True)
            processor = AutoProcessor.from_pretrained(hf_id)
            ov_model  = OVModelForSpeechSeq2Seq.from_pretrained(
                hf_id, export=True, device=device
            )
            ov_model.save_pretrained(str(model_dir))
            processor.save_pretrained(str(model_dir))
        _cache[key] = hf_pipeline(
            "automatic-speech-recognition",
            model=ov_model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
        )
        print(f"[✓] OpenVINO {model_id} на {device} готова")

    result = _cache[key](wav_path, generate_kwargs={"language": language})
    text = result.get("text", "").strip()
    return format_text([text] if text else [])


# ═══════════════════════════════════════════════════════════════
#  GigaAM v3 ONNX  (русский ASR через onnx-asr)
# ═══════════════════════════════════════════════════════════════
GIGAAM_MODELS = [
    {"id": "gigaam-v3-ctc",      "name": "GigaAM v3 CTC (~885 МБ)",       "hf": "gigaam-v3-ctc"},
    {"id": "gigaam-v3-rnnt",     "name": "GigaAM v3 RNN-T (~890 МБ)",     "hf": "gigaam-v3-rnnt"},
    {"id": "gigaam-v3-e2e-ctc",  "name": "GigaAM v3 E2E CTC (~886 МБ)",  "hf": "gigaam-v3-e2e-ctc"},
    {"id": "gigaam-v3-e2e-rnnt", "name": "GigaAM v3 E2E RNN-T (~892 МБ)", "hf": "gigaam-v3-e2e-rnnt"},
]
GIGAAM_DIR = MODELS_DIR / "gigaam" / "gigaam-v3-onnx"

def gigaam_list() -> list:
    result = []
    for m in GIGAAM_MODELS:
        result.append({"id": m["id"], "name": m["name"], "available": GIGAAM_DIR.exists()})
    return result

_GIGAAM_CHUNK_SEC = 40  # модель ограничена ~50 сек (5000 фреймов × 10 мс)


def _wav_chunks(wav_path: str, chunk_sec: int):
    """Разбивает WAV на временные файлы по chunk_sec секунд, возвращает пути."""
    import tempfile
    chunks = []
    with wave.open(wav_path, "rb") as wf:
        rate      = wf.getframerate()
        n_frames  = wf.getnframes()
        ch        = wf.getnchannels()
        sw        = wf.getsampwidth()
        chunk_len = rate * chunk_sec
        offset    = 0
        while offset < n_frames:
            wf.setpos(offset)
            data = wf.readframes(chunk_len)
            tmp  = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            with wave.open(tmp.name, "wb") as out:
                out.setnchannels(ch)
                out.setsampwidth(sw)
                out.setframerate(rate)
                out.writeframes(data)
            chunks.append(tmp.name)
            offset += chunk_len
    return chunks


def gigaam_transcribe(wav_path: str, model_id: str) -> str:
    if not _gigaam_ok:
        raise RuntimeError("Для GigaAM нужно установить:\n  pip install onnx-asr[cpu,hub]")
    key = f"gigaam:{model_id}"
    if key not in _cache:
        hf_id = next((m["hf"] for m in GIGAAM_MODELS if m["id"] == model_id), model_id)
        print(f"[*] Загрузка GigaAM {model_id}...")
        if GIGAAM_DIR.exists():
            _cache[key] = _onnx_asr.load_model(hf_id, str(GIGAAM_DIR))
        else:
            _cache[key] = _onnx_asr.load_model(hf_id)
        print(f"[✓] GigaAM {model_id} загружена")
    model = _cache[key]
    chunks = _wav_chunks(wav_path, _GIGAAM_CHUNK_SEC)
    try:
        parts = []
        for c in chunks:
            t = model.recognize(c)
            if t and t.strip():
                parts.append(t.strip())
    finally:
        for c in chunks:
            try:
                os.unlink(c)
            except OSError:
                pass
    return format_text(parts)


# ═══════════════════════════════════════════════════════════════
#  Whisper HF  (OpenAI Whisper через HuggingFace transformers)
# ═══════════════════════════════════════════════════════════════
WHISPER_HF_MODELS = [
    {"id": "whisper-hf-tiny",  "name": "Whisper Tiny  (~150 МБ)", "dir": "whisper-tiny"},
    {"id": "whisper-hf-base",  "name": "Whisper Base  (~290 МБ)", "dir": "whisper-base"},
    {"id": "whisper-hf-small", "name": "Whisper Small (~950 МБ)", "dir": "whisper-small"},
]
WHISPER_HF_DIR = MODELS_DIR / "whisper-hf"

def whisper_hf_list() -> list:
    result = []
    for m in WHISPER_HF_MODELS:
        local = WHISPER_HF_DIR / m["dir"]
        result.append({"id": m["id"], "name": m["name"], "available": local.exists()})
    return result

def whisper_hf_transcribe(wav_path: str, model_id: str, language: str = "ru") -> str:
    if not _whisper_hf_ok:
        raise RuntimeError("Для Whisper HF нужно установить:\n  pip install transformers torch")
    key = f"whisper_hf:{model_id}"
    if key not in _cache:
        m = next((x for x in WHISPER_HF_MODELS if x["id"] == model_id), None)
        local = WHISPER_HF_DIR / m["dir"] if m else None
        model_src = str(local) if local and local.exists() else (m["dir"] if m else model_id)
        print(f"[*] Загрузка Whisper HF {model_id}...")
        _cache[key] = _hf_pipeline("automatic-speech-recognition", model=model_src)
        print(f"[✓] Whisper HF {model_id} загружена")
    lang = language if language != "auto" else None
    generate_kwargs = {"language": lang} if lang else {}
    result = _cache[key](wav_path, generate_kwargs=generate_kwargs)
    text = result.get("text", "").strip()
    return format_text([text] if text else [])


# ═══════════════════════════════════════════════════════════════
#  GGML  (Whisper GGML через pywhispercpp)
# ═══════════════════════════════════════════════════════════════
GGML_MODELS = [
    {"id": "ggml-small", "name": "GGML Small  (~460 МБ)", "file": "ggml-small.bin"},
    {"id": "ggml-turbo", "name": "GGML Turbo  (~1.6 ГБ)", "file": "ggml-large-v3-turbo.bin"},
]
GGML_DIR = MODELS_DIR / "ggml"

def ggml_list() -> list:
    result = []
    for m in GGML_MODELS:
        result.append({"id": m["id"], "name": m["name"], "available": (GGML_DIR / m["file"]).exists()})
    return result

def _ggml_find_binary() -> str | None:
    """Ищет бинарник whisper.cpp в PATH и рядом со скриптом."""
    import shutil
    for name in ("whisper-cli", "whisper-cli.exe", "main", "main.exe"):
        found = shutil.which(name)
        if found:
            return found
    # рядом со скриптом / в подпапке
    here = Path(__file__).parent
    for rel in ("whisper-cli.exe", "main.exe", "whisper.cpp/main.exe",
                "whisper-cli", "main", "whisper.cpp/main"):
        p = here / rel
        if p.exists():
            return str(p)
    return None

def _ggml_transcribe_subprocess(wav_path: str, model_file: Path, language: str) -> str:
    """Вызывает whisper.cpp бинарник напрямую (без pywhispercpp)."""
    exe = _ggml_find_binary()
    if not exe:
        raise RuntimeError(
            "GGML требует pywhispercpp или бинарник whisper.cpp в PATH.\n"
            "  Вариант 1 (бинарник): скачайте whisper.cpp с\n"
            "    https://github.com/ggerganov/whisper.cpp/releases\n"
            "    и положите main.exe / whisper-cli.exe рядом с app.py\n"
            "  Вариант 2 (Python): pip install pywhispercpp\n"
            "    (требует CMake + Visual Studio Build Tools)"
        )
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out_base = os.path.join(tmp, "out")
        lang = language if language != "auto" else "auto"
        r = subprocess.run(
            [exe, "-m", str(model_file), "-f", wav_path,
             "-l", lang, "-otxt", "-of", out_base, "--no-prints"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        )
        out_file = out_base + ".txt"
        if os.path.exists(out_file):
            text = open(out_file, encoding="utf-8").read().strip()
            return format_text([text] if text else [])
        if r.returncode == 0 and r.stdout.strip():
            return format_text([r.stdout.strip()])
        raise RuntimeError(f"whisper.cpp ошибка (код {r.returncode}): {r.stderr[:400]}")

def ggml_transcribe(wav_path: str, model_id: str, language: str = "ru") -> str:
    m = next((x for x in GGML_MODELS if x["id"] == model_id), None)
    if not m:
        raise ValueError(f"Неизвестная GGML модель: {model_id}")
    model_file = GGML_DIR / m["file"]
    if not model_file.exists():
        raise FileNotFoundError(f"GGML файл не найден: {model_file}")

    if not _ggml_ok:
        # fallback: subprocess
        return _ggml_transcribe_subprocess(wav_path, model_file, language)

    key = f"ggml:{model_id}"
    if key not in _cache:
        print(f"[*] Загрузка GGML {model_id}...")
        _cache[key] = _GgmlModel(str(model_file), print_realtime=False, print_progress=False)
        print(f"[✓] GGML {model_id} загружена")
    lang = language if language != "auto" else None
    kwargs = {"language": lang} if lang else {}
    segments = _cache[key].transcribe(wav_path, **kwargs)
    chunks = [s.text.strip() for s in segments if s.text.strip()]
    return format_text(chunks)


# ═══════════════════════════════════════════════════════════════
#  Общие утилиты
# ═══════════════════════════════════════════════════════════════
def convert_to_wav(src: str) -> str:
    dst = src.rsplit(".", 1)[0] + "_converted.wav"
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", dst],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg ошибка: {r.stderr[:500]}")
    return dst

def format_text(chunks: list) -> str:
    sentences = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        chunk = chunk[0].upper() + chunk[1:]
        if chunk[-1] not in ".!?…":
            chunk += "."
        sentences.append(chunk)
    paragraphs = [" ".join(sentences[i:i+5]) for i in range(0, len(sentences), 5)]
    return "\n\n".join(paragraphs)

def _safe_stem(name: str) -> str:
    """Имя файла без расширения, очищенное от запрещённых символов."""
    stem = Path(name).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(". ")
    return stem or "transcription"

def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_history(entry: dict) -> None:
    h = load_history()
    h.insert(0, entry)
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
#  Flask маршруты
# ═══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route("/engines")
def engines_info():
    result = []
    if _vosk_ok:
        result.append({
            "id": "vosk", "name": "Vosk",
            "description": "Быстрый, офлайн, CPU",
            "models": vosk_list(),
        })
    if _fw_ok:
        result.append({
            "id": "faster_whisper", "name": "Faster-Whisper",
            "description": "Высокое качество, CPU int8 (оптимально для Intel CPU)",
            "models": fw_list(),
        })
    if _ov_ok:
        gpu = [d for d in _ov_devices if "GPU" in d]
        desc = (f"Intel GPU ({', '.join(_ov_devices)})"
                if gpu else f"OpenVINO CPU ({', '.join(_ov_devices)})")
        result.append({
            "id": "openvino", "name": "OpenVINO",
            "description": desc,
            "devices": _ov_devices,
            "models": ov_list(),
        })
    result.append({
        "id": "gigaam", "name": "GigaAM v3 ONNX",
        "description": "Русский ASR, ONNX" + ("" if _gigaam_ok else " (требует onnx-asr[cpu,hub])"),
        "models": gigaam_list(),
    })
    if _whisper_hf_ok or any(m["available"] for m in whisper_hf_list()):
        result.append({
            "id": "whisper_hf", "name": "Whisper HF",
            "description": "OpenAI Whisper через HuggingFace transformers",
            "models": whisper_hf_list(),
        })
    if _ggml_ok or any(m["available"] for m in ggml_list()):
        result.append({
            "id": "ggml", "name": "GGML (whisper.cpp)",
            "description": "Whisper GGML, быстро, CPU (требует pywhispercpp)",
            "models": ggml_list(),
        })
    return jsonify(result)


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "Файл не выбран"}), 400
    file = request.files["audio"]
    if not file.filename:
        return jsonify({"error": "Пустое имя файла"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"Формат {ext} не поддерживается"}), 400

    engine    = request.form.get("engine",    "vosk")
    model_id  = request.form.get("model",     "small-ru")
    language  = request.form.get("language",  "ru")
    ov_device = request.form.get("ov_device", "GPU")

    safe_name   = f"upload_{int(time.time())}{ext}"
    upload_path = str(UPLOAD_DIR / safe_name)
    file.save(upload_path)

    wav_path = None
    try:
        t0 = time.time()
        wav_path = convert_to_wav(upload_path)
        t_conv   = time.time() - t0

        if engine == "vosk":
            if not _vosk_ok:
                return jsonify({"error": "Vosk не установлен (pip install vosk)"}), 400
            text = vosk_transcribe(wav_path, model_id)
        elif engine == "faster_whisper":
            if not _fw_ok:
                return jsonify({"error": "faster-whisper не установлен"}), 400
            text = fw_transcribe(wav_path, model_id, language)
        elif engine == "openvino":
            if not _ov_ok:
                return jsonify({"error": "OpenVINO не установлен (pip install openvino optimum[openvino] transformers)"}), 400
            text = ov_transcribe(wav_path, model_id, ov_device, language)
        elif engine == "gigaam":
            text = gigaam_transcribe(wav_path, model_id)
        elif engine == "whisper_hf":
            text = whisper_hf_transcribe(wav_path, model_id, language)
        elif engine == "ggml":
            text = ggml_transcribe(wav_path, model_id, language)
        else:
            return jsonify({"error": f"Неизвестный движок: {engine}"}), 400

        t_total = time.time() - t0
        if not text.strip():
            return jsonify({"error": "Речь не распознана"}), 422

        # Имя файла = имя аудио
        stem     = _safe_stem(file.filename)
        txt_name = f"{stem}_{int(time.time())}.txt"
        txt_path = OUTPUT_DIR / txt_name
        txt_path.write_text(text, encoding="utf-8")

        try:
            wf = wave.open(wav_path, "rb")
            duration = wf.getnframes() / wf.getframerate()
            wf.close()
        except Exception:
            duration = 0

        stats = {
            "duration_sec": round(duration, 1),
            "convert_sec":  round(t_conv, 2),
            "total_sec":    round(t_total, 2),
            "speed_x":      round(duration / t_total, 1) if t_total > 0 else 0,
            "engine":       engine,
            "model":        model_id,
        }

        save_history({
            "id":            txt_name,
            "original_name": file.filename,
            "download":      f"/download/{txt_name}",
            "created_at":    datetime.now().isoformat(timespec="seconds"),
            "stats":         stats,
            "preview":       text[:200],
        })

        return jsonify({"text": text, "download": f"/download/{txt_name}", "stats": stats})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        for p in (upload_path, wav_path):
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass


@app.route("/history")
def history():
    return jsonify(load_history())


@app.route("/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    if re.search(r'[/\\]|\.\.', filename):
        return jsonify({"error": "Недопустимо"}), 400
    path = OUTPUT_DIR / filename
    if not path.exists():
        return jsonify({"error": "Файл не найден"}), 404
    path.unlink()
    h = load_history()
    h = [e for e in h if e.get("id") != filename]
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@app.route("/download/<filename>")
def download(filename):
    if re.search(r'[/\\]|\.\.', filename):
        return "Недопустимо", 400
    path = OUTPUT_DIR / filename
    if not path.exists():
        return "Файл не найден", 404
    return send_file(path, as_attachment=True, download_name=filename, mimetype='text/plain; charset=utf-8')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 47821))
    if _gigaam_ok:
        def _preload_default_gigaam():
            model_id = "gigaam-v3-e2e-ctc"
            key = f"gigaam:{model_id}"
            hf_id = next((m["hf"] for m in GIGAAM_MODELS if m["id"] == model_id), model_id)
            print(f"[*] Предзагрузка GigaAM {model_id}...")
            try:
                if GIGAAM_DIR.exists():
                    _cache[key] = _onnx_asr.load_model(hf_id, str(GIGAAM_DIR))
                else:
                    _cache[key] = _onnx_asr.load_model(hf_id)
                print(f"[✓] GigaAM {model_id} предзагружена")
            except Exception as e:
                print(f"[!] Ошибка предзагрузки GigaAM: {e}")
        import threading
        threading.Thread(target=_preload_default_gigaam, daemon=True).start()
    app.run(host="0.0.0.0", port=port, debug=False)

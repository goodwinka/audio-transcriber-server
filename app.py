"""
Сервер транскрипции аудио → текст.
Поддерживаемые движки:
  vosk          — Vosk, CPU, быстро, офлайн
  faster_whisper — Faster-Whisper, CPU int8, лучшее качество (оптимально для Intel)
  openvino      — OpenVINO, Intel iGPU/CPU, требует optimum[openvino]
"""

import os, json, wave, subprocess, time, re
from datetime import datetime
from pathlib import Path

from flask import Flask, request, render_template, send_file, jsonify

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

# ── Определение доступных движков ──────────────────────────────
_vosk_ok = _fw_ok = _ov_ok = False
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
        "name": "Русская большая v0.54 (1.8 ГБ, точнее)",
        "url":  "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
        "dirs": ["vosk-model-ru-0.54", "vosk-model-ru-0.42"],
    },
    "small-en": {
        "name": "English small (40 МБ)",
        "url":  "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "dir":  "vosk-model-small-en-us-0.15",
    },
}

def _vosk_model_valid(p: Path) -> bool:
    """Принимает как классический формат (am/ + conf/),
    так и ONNX-формат (am-onnx/ + lang/)."""
    has_am = (p / "am").is_dir() or (p / "am-onnx").is_dir()
    has_lang = (p / "conf").is_dir() or (p / "lang").is_dir()
    return has_am and has_lang

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
    return render_template("index.html")


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
    return send_file(path, as_attachment=True, download_name=filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

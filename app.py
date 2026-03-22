"""
Сервер транскрипции аудио → текст (Vosk + Flask).
Лёгкий, быстрый, для слабых машин.
"""

import os
import json
import wave
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, request, render_template, send_file, jsonify
from vosk import Model, KaldiRecognizer

# ──────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────
MODEL_PATH = os.environ.get("VOSK_MODEL", "model")  # путь к модели Vosk
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
HISTORY_FILE = Path("history.json")
ALLOWED_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".webm"}
MAX_FILE_MB = 500

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * 1024 * 1024

# Создаём папки
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# Загрузка модели (один раз при старте)
# ──────────────────────────────────────────────
print(f"[*] Загрузка модели из {MODEL_PATH}...")
if not Path(MODEL_PATH).exists():
    print(
        "[!] Модель не найдена! Скачайте русскую модель:\n"
        "    https://alphacephei.com/vosk/models\n"
        "    Рекомендуется: vosk-model-small-ru-0.22 (45 МБ, быстрая)\n"
        "    или:           vosk-model-ru-0.42 (1.8 ГБ, точная)\n"
        "    Распакуйте в папку 'model' рядом с app.py"
    )
    raise FileNotFoundError(f"Модель не найдена: {MODEL_PATH}")

model = Model(MODEL_PATH)
print("[✓] Модель загружена.")


def convert_to_wav(input_path: str) -> str:
    """Конвертация любого аудио в WAV 16kHz mono через ffmpeg."""
    wav_path = input_path.rsplit(".", 1)[0] + "_converted.wav"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
        wav_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg ошибка: {result.stderr[:500]}")
    return wav_path


def transcribe_wav(wav_path: str) -> str:
    """Транскрипция WAV файла через Vosk."""
    wf = wave.open(wav_path, "rb")

    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
        wf.close()
        raise ValueError("WAV должен быть 16kHz mono 16bit (конвертация не сработала)")

    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(False)  # не нужны таймкоды — быстрее

    chunks = []
    while True:
        data = wf.readframes(8000)  # ~0.5 сек
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text = result.get("text", "").strip()
            if text:
                chunks.append(text)

    # Финальный фрагмент
    final = json.loads(rec.FinalResult())
    text = final.get("text", "").strip()
    if text:
        chunks.append(text)

    wf.close()
    return format_text(chunks)


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_history_entry(entry: dict) -> None:
    history = load_history()
    history.insert(0, entry)  # новые — сверху
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def format_text(chunks: list[str]) -> str:
    """
    Форматирование: капитализация + точки.
    Vosk отдаёт фразы без пунктуации — добавляем точки в конце каждого фрагмента.
    """
    sentences = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Первая буква — заглавная
        chunk = chunk[0].upper() + chunk[1:]
        # Точка в конце если нет знака препинания
        if chunk[-1] not in ".!?…":
            chunk += "."
        sentences.append(chunk)

    # Собираем текст абзацами (по ~5 предложений)
    paragraphs = []
    for i in range(0, len(sentences), 5):
        paragraph = " ".join(sentences[i:i + 5])
        paragraphs.append(paragraph)

    return "\n\n".join(paragraphs)


# ──────────────────────────────────────────────
# Маршруты
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "Файл не выбран"}), 400

    file = request.files["audio"]
    if not file.filename:
        return jsonify({"error": "Пустое имя файла"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"Формат {ext} не поддерживается. Допустимые: {', '.join(ALLOWED_EXT)}"}), 400

    # Сохраняем загруженный файл
    safe_name = f"upload_{int(time.time())}{ext}"
    upload_path = str(UPLOAD_DIR / safe_name)
    file.save(upload_path)

    wav_path = None
    try:
        t0 = time.time()

        # Конвертация в WAV
        wav_path = convert_to_wav(upload_path)
        t_convert = time.time() - t0

        # Транскрипция
        text = transcribe_wav(wav_path)
        t_total = time.time() - t0

        if not text.strip():
            return jsonify({"error": "Не удалось распознать речь в файле."}), 422

        # Сохраняем результат
        txt_name = f"transcription_{int(time.time())}.txt"
        txt_path = str(OUTPUT_DIR / txt_name)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)

        # Длительность аудио
        try:
            wf = wave.open(wav_path, "rb")
            duration = wf.getnframes() / wf.getframerate()
            wf.close()
        except Exception:
            duration = 0

        stats = {
            "duration_sec": round(duration, 1),
            "convert_sec": round(t_convert, 2),
            "total_sec": round(t_total, 2),
            "speed_x": round(duration / t_total, 1) if t_total > 0 else 0,
        }

        save_history_entry({
            "id": txt_name,
            "original_name": file.filename,
            "download": f"/download/{txt_name}",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "stats": stats,
            "preview": text[:200],
        })

        return jsonify({
            "text": text,
            "download": f"/download/{txt_name}",
            "stats": stats,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        # Чистим только текущие временные файлы
        for path in (upload_path, wav_path):
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass


@app.route("/history")
def history():
    return jsonify(load_history())


@app.route("/download/<filename>")
def download(filename):
    path = OUTPUT_DIR / filename
    if not path.exists():
        return "Файл не найден", 404
    return send_file(path, as_attachment=True, download_name="transcription.txt")


# ──────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

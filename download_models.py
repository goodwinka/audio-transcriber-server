"""
Скачивает все модели для аудио-транскрипции.
Запускается автоматически из install.bat или вручную:
    python download_models.py
"""

import os
import sys
import zipfile
import urllib.request
from pathlib import Path

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "models"))
MODELS_DIR.mkdir(exist_ok=True)

def progress_hook(block_num, block_size, total_size):
    if total_size > 0:
        pct = min(100, block_num * block_size * 100 // total_size)
        done = pct // 5
        bar = "█" * done + "░" * (20 - done)
        print(f"\r  [{bar}] {pct}%", end="", flush=True)

def download_file(url: str, dest: Path):
    print(f"  Скачивание: {dest.name}")
    urllib.request.urlretrieve(url, dest, reporthook=progress_hook)
    print()  # newline after progress

def download_zip(url: str, extract_to: Path, final_name: str | None = None):
    """Скачивает zip и распаковывает. Если final_name задан — переименовывает корневую папку."""
    tmp = MODELS_DIR / "_tmp_download.zip"
    try:
        download_file(url, tmp)
        print(f"  Распаковка...")
        with zipfile.ZipFile(tmp, "r") as z:
            z.extractall(extract_to)
        # Rename extracted root dir if needed
        if final_name:
            members = [p for p in extract_to.iterdir() if p.is_dir()]
            if members:
                root = members[0]
                target = extract_to / final_name
                if not target.exists():
                    root.rename(target)
    finally:
        tmp.unlink(missing_ok=True)

def try_hf_download(repo_id: str, local_dir: Path):
    """Скачивает репозиторий с HuggingFace."""
    try:
        from huggingface_hub import snapshot_download
        print(f"  HuggingFace: {repo_id}")
        snapshot_download(repo_id=repo_id, local_dir=str(local_dir), local_dir_use_symlinks=False)
        return True
    except ImportError:
        print("  huggingface_hub не установлен, пробуем pip install...")
        os.system(f'"{sys.executable}" -m pip install huggingface_hub -q')
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=repo_id, local_dir=str(local_dir), local_dir_use_symlinks=False)
            return True
        except Exception as e:
            print(f"  ОШИБКА HF: {e}")
            return False
    except Exception as e:
        print(f"  ОШИБКА: {e}")
        return False

# ─────────────────────────────────────────────────────────────
#  VOSK
# ─────────────────────────────────────────────────────────────
VOSK_DIR = MODELS_DIR / "vosk"
VOSK_DIR.mkdir(exist_ok=True)

VOSK_MODELS = [
    {
        "id": "small-ru",
        "name": "Vosk small-ru (45 МБ, стриминг)",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
        "dir": "vosk-model-small-ru-0.22",
    },
    {
        "id": "ru",
        "name": "Vosk big-ru 0.54 (~1.8 ГБ, лучшее качество)",
        "hf": "alphacep/vosk-model-ru",
        "dir": "vosk-model-ru-0.54",
        "url_fallback": "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
        "dir_fallback": "vosk-model-ru-0.42",
    },
    {
        "id": "small-en",
        "name": "Vosk small-en (40 МБ, English)",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "dir": "vosk-model-small-en-us-0.15",
    },
]

def download_vosk_models():
    print("\n━━━ Vosk модели ━━━")
    for m in VOSK_MODELS:
        dest = VOSK_DIR / m["dir"]
        if dest.exists():
            print(f"  ✓ {m['name']} — уже есть")
            continue
        print(f"\n► {m['name']}")
        if "hf" in m:
            ok = try_hf_download(m["hf"], dest)
            if not ok and "url_fallback" in m:
                print(f"  Резерв: скачиваем с alphacephei.com...")
                dest_fb = VOSK_DIR / m["dir_fallback"]
                if not dest_fb.exists():
                    download_zip(m["url_fallback"], VOSK_DIR)
                else:
                    print(f"  ✓ Резервная модель уже есть: {dest_fb.name}")
        else:
            download_zip(m["url"], VOSK_DIR)
        if dest.exists():
            print(f"  ✓ Готово: {dest.name}")

# ─────────────────────────────────────────────────────────────
#  FASTER-WHISPER  (CTranslate2 int8, от Systran/HuggingFace)
# ─────────────────────────────────────────────────────────────
FW_CACHE = str(MODELS_DIR / "faster-whisper")
Path(FW_CACHE).mkdir(exist_ok=True)

FW_MODELS = [
    {"id": "tiny",     "hf": "Systran/faster-whisper-tiny",     "name": "Tiny     (~75 МБ)"},
    {"id": "base",     "hf": "Systran/faster-whisper-base",     "name": "Base     (~145 МБ)"},
    {"id": "small",    "hf": "Systran/faster-whisper-small",    "name": "Small    (~460 МБ)"},
    {"id": "medium",   "hf": "Systran/faster-whisper-medium",   "name": "Medium   (~1.5 ГБ)"},
    {"id": "large-v3", "hf": "Systran/faster-whisper-large-v3", "name": "Large-v3 (~3 ГБ)"},
]

def download_fw_models():
    print("\n━━━ Faster-Whisper модели (CTranslate2 int8) ━━━")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  faster-whisper не установлен, пропускаем.")
        return

    for m in FW_MODELS:
        local = Path(FW_CACHE) / m["id"]
        # HuggingFace cache format: models--Systran--faster-whisper-{id}
        hf_cache = Path(FW_CACHE) / ("models--" + m["hf"].replace("/", "--"))
        if local.exists() or hf_cache.exists():
            print(f"  ✓ {m['name']} — уже есть")
            continue
        print(f"\n► {m['name']}")
        try:
            print(f"  Загрузка {m['hf']}...")
            WhisperModel(m["hf"], device="cpu", compute_type="int8", download_root=FW_CACHE)
            # rename downloaded dir to short id
            hf_dir = Path(FW_CACHE) / ("models--" + m["hf"].replace("/", "--"))
            if not local.exists() and hf_dir.exists():
                # re-load to force cache-to-local copy
                pass
            print(f"  ✓ {m['name']} готова")
        except Exception as e:
            print(f"  ОШИБКА: {e}")

# ─────────────────────────────────────────────────────────────
#  GigaAM v3 ONNX  (ONNX-модель для русского ASR)
# ─────────────────────────────────────────────────────────────
GIGAAM_DIR = MODELS_DIR / "gigaam"
GIGAAM_DIR.mkdir(exist_ok=True)

def download_gigaam():
    print("\n━━━ GigaAM v3 ONNX ━━━")
    dest = GIGAAM_DIR / "gigaam-v3-onnx"
    if dest.exists():
        print("  ✓ GigaAM v3 ONNX — уже есть")
        return
    print("► GigaAM v3 ONNX (~300 МБ)")
    try_hf_download("istupakov/gigaam-v3-onnx", dest)
    if dest.exists():
        print("  ✓ GigaAM v3 ONNX готова")

# ─────────────────────────────────────────────────────────────
#  OpenAI Whisper (оригинальные модели через HuggingFace)
# ─────────────────────────────────────────────────────────────
WHISPER_HF_DIR = MODELS_DIR / "whisper-hf"
WHISPER_HF_DIR.mkdir(exist_ok=True)

WHISPER_HF_MODELS = [
    {"hf": "openai/whisper-tiny",  "name": "Whisper Tiny  (~150 МБ)"},
    {"hf": "openai/whisper-base",  "name": "Whisper Base  (~290 МБ)"},
    {"hf": "openai/whisper-small", "name": "Whisper Small (~950 МБ)"},
]

def download_whisper_hf():
    print("\n━━━ OpenAI Whisper (HuggingFace) ━━━")
    for m in WHISPER_HF_MODELS:
        model_id = m["hf"].split("/")[1]
        dest = WHISPER_HF_DIR / model_id
        if dest.exists():
            print(f"  ✓ {m['name']} — уже есть")
            continue
        print(f"\n► {m['name']}")
        try_hf_download(m["hf"], dest)
        if dest.exists():
            print(f"  ✓ {m['name']} готова")

# ─────────────────────────────────────────────────────────────
#  Whisper GGML (для whisper.cpp)
# ─────────────────────────────────────────────────────────────
GGML_DIR = MODELS_DIR / "ggml"
GGML_DIR.mkdir(exist_ok=True)

GGML_MODELS = [
    {
        "name": "whisper.cpp small ggml (~460 МБ)",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        "file": "ggml-small.bin",
    },
    {
        "name": "whisper.cpp turbo ggml (~1.6 ГБ)",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin",
        "file": "ggml-large-v3-turbo.bin",
    },
]

def download_ggml_models():
    print("\n━━━ GGML модели (для whisper.cpp) ━━━")
    for m in GGML_MODELS:
        dest = GGML_DIR / m["file"]
        if dest.exists():
            print(f"  ✓ {m['name']} — уже есть")
            continue
        print(f"\n► {m['name']}")
        try:
            download_file(m["url"], dest)
            print(f"  ✓ Готово: {dest.name}")
        except Exception as e:
            print(f"  ОШИБКА: {e}")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════╗
║        Загрузка всех моделей транскрипции           ║
╚══════════════════════════════════════════════════════╝
""")
    download_vosk_models()
    download_fw_models()
    download_gigaam()
    download_whisper_hf()
    download_ggml_models()
    print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Загрузка завершена! Все модели в папке models\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

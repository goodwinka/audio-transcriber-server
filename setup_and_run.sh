#!/bin/bash
set -e

echo "=== Транскрипция аудио — установка ==="

# Проверяем Python
python3 --version || { echo "❌ Python 3 не найден"; exit 1; }

# Проверяем ffmpeg
ffmpeg -version > /dev/null 2>&1 || { echo "❌ ffmpeg не найден. Установите: sudo apt install ffmpeg"; exit 1; }

# Зависимости
echo "[1/3] Установка Python-пакетов..."
pip install -r requirements.txt -q

# Модель
if [ ! -d "model" ]; then
    echo "[2/3] Скачивание модели vosk-model-small-ru-0.22 (45 МБ)..."
    wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
    unzip -q vosk-model-small-ru-0.22.zip
    mv vosk-model-small-ru-0.22 model
    rm vosk-model-small-ru-0.22.zip
    echo "[✓] Модель установлена"
else
    echo "[2/3] Модель уже на месте"
fi

# Запуск
echo "[3/3] Запуск сервера..."
echo ""
echo "  → http://localhost:5000"
echo ""
python3 app.py

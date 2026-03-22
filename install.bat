@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Транскрипция аудио — Установка

:: Переходим в папку скрипта, чтобы относительные пути (models/, .venv/) работали
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║          Транскрипция аудио — Установка             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ── [1] Python ───────────────────────────────────────────────
echo [1/9] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ОШИБКА: Python не найден.
    echo  Скачайте с https://www.python.org/downloads/
    echo  При установке поставьте галочку "Add Python to PATH"
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo  OK: %%v

:: ── [2] ffmpeg ───────────────────────────────────────────────
echo.
echo [2/9] Проверка ffmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo  ОШИБКА: ffmpeg не найден в PATH.
    echo.
    echo  Установка:
    echo    1. Скачайте ffmpeg-release-essentials.zip
    echo       с https://www.gyan.dev/ffmpeg/builds/
    echo    2. Распакуйте в C:\ffmpeg
    echo    3. Добавьте C:\ffmpeg\bin в PATH:
    echo       Пуск -^> "Переменные среды" -^> Path -^> Изменить -^> Создать
    echo    4. Перезапустите скрипт
    pause & exit /b 1
)
echo  OK: ffmpeg найден

:: ── [3] Виртуальное окружение ────────────────────────────────
echo.
echo [3/9] Виртуальное окружение (.venv)...
if exist .venv (
    echo  Уже существует, пропускаем
) else (
    python -m venv .venv
    if errorlevel 1 ( echo  ОШИБКА: venv & pause & exit /b 1 )
    echo  OK: .venv создан
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q

:: ── [4] Базовые зависимости (Flask + Vosk) ───────────────────
echo.
echo [4/9] Установка Flask + Vosk...
pip install flask==3.1.* vosk==0.3.* -q
if errorlevel 1 ( echo  ОШИБКА & pause & exit /b 1 )
echo  OK

:: ── [5] Faster-Whisper ───────────────────────────────────────
echo.
echo [5/9] Установка Faster-Whisper (CPU int8)...
pip install faster-whisper -q
if errorlevel 1 ( echo  ПРЕДУПРЕЖДЕНИЕ: не удалось установить faster-whisper ) else ( echo  OK )

:: ── [6] Intel GPU / OpenVINO ─────────────────────────────────
echo.
echo [6/9] OpenVINO (ускорение на Intel iGPU)?
echo   Требует Intel Graphics Driver. Устанавливайте если есть встроенная Intel-видеокарта.
echo.
choice /c ДН /n /m "  Установить OpenVINO? [Д/Н]: "
if errorlevel 2 (
    echo  Пропускаем OpenVINO
) else (
    echo  Установка openvino + optimum[openvino] + transformers...
    pip install openvino "optimum[openvino]" transformers -q
    if errorlevel 1 (
        echo  ПРЕДУПРЕЖДЕНИЕ: не удалось установить OpenVINO
    ) else (
        echo  OK
        echo  Проверка доступных устройств OpenVINO:
        python -c "import openvino as ov; print('  Устройства:', ov.Core().available_devices)"
    )
)

:: ── [7] GigaAM v3 ONNX ───────────────────────────────────────
echo.
echo [7/9] Установка GigaAM (onnx-asr)...
pip install "onnx-asr[cpu,hub]" -q
if errorlevel 1 ( echo  ПРЕДУПРЕЖДЕНИЕ: не удалось установить onnx-asr ) else ( echo  OK )

:: ── [8] Whisper HF + GGML ────────────────────────────────────
echo.
echo [8/9] Установка Whisper HF (transformers) и GGML (pywhispercpp)...
pip install transformers torch -q
if errorlevel 1 ( echo  ПРЕДУПРЕЖДЕНИЕ: не удалось установить transformers ) else ( echo  OK: transformers )

echo  Установка pywhispercpp (требует CMake + Visual Studio Build Tools)...
pip install pywhispercpp -q
if errorlevel 1 (
    echo  ПРЕДУПРЕЖДЕНИЕ: pywhispercpp не установлен.
    echo  Это нормально. GGML-модели можно использовать через бинарник whisper.cpp:
    echo    1. Скачайте с https://github.com/ggerganov/whisper.cpp/releases
    echo    2. Положите main.exe или whisper-cli.exe рядом с app.py
) else (
    echo  OK: pywhispercpp
)

:: ── [9] Загрузка всех моделей ────────────────────────────────
echo.
echo [9/9] Загрузка всех моделей...
echo.
echo  Будут скачаны (требуется место на диске ~10 ГБ):
echo    · Vosk small-ru streaming     (~45 МБ)
echo    · Vosk big-ru 0.54            (~1.8 ГБ)
echo    · Vosk small-en               (~40 МБ)
echo    · Faster-Whisper tiny         (~75 МБ)
echo    · Faster-Whisper base int8    (~145 МБ)
echo    · Faster-Whisper small int8   (~460 МБ)
echo    · Faster-Whisper medium int8  (~1.5 ГБ)
echo    · Faster-Whisper large-v3     (~3 ГБ)
echo    · GigaAM v3 ONNX              (~300 МБ)
echo    · Whisper tiny/base/small HF  (~1.4 ГБ)
echo    · GGML small + turbo          (~2 ГБ)
echo.
pip install huggingface_hub -q
python download_models.py
if errorlevel 1 (
    echo  ПРЕДУПРЕЖДЕНИЕ: часть моделей не скачалась. Запустите download_models.py повторно.
)

:: ── Итог ─────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║         Установка завершена!                        ║
echo  ║                                                     ║
echo  ║   Запуск сервера:  start.bat                       ║
echo  ║   Затем откройте:  http://localhost:5000            ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
pause

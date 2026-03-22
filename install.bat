@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Транскрипция аудио — Установка

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║          Транскрипция аудио — Установка             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ── [1] Python ───────────────────────────────────────────────
echo [1/6] Проверка Python...
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
echo [2/6] Проверка ffmpeg...
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
echo [3/6] Виртуальное окружение (.venv)...
if exist .venv (
    echo  Уже существует, пропускаем
) else (
    python -m venv .venv
    if errorlevel 1 ( echo  ОШИБКА: venv & pause & exit /b 1 )
    echo  OK: .venv создан
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q

:: ── [4] Базовые зависимости (Vosk + Flask) ───────────────────
echo.
echo [4/6] Установка Flask + Vosk...
pip install flask==3.1.* vosk==0.3.* -q
if errorlevel 1 ( echo  ОШИБКА & pause & exit /b 1 )
echo  OK

:: ── [5] Faster-Whisper ───────────────────────────────────────
echo.
echo [5/6] Faster-Whisper (CPU int8, лучшее качество)?
echo   Рекомендуется для серверов с Intel CPU/GPU.
echo   Первая транскрипция скачает модель (~75..466 МБ).
echo.
choice /c ДН /n /m "  Установить Faster-Whisper? [Д/Н]: "
if errorlevel 2 (
    echo  Пропускаем Faster-Whisper
) else (
    echo  Установка faster-whisper...
    pip install faster-whisper -q
    if errorlevel 1 ( echo  ПРЕДУПРЕЖДЕНИЕ: не удалось установить faster-whisper ) else ( echo  OK )
)

:: ── [6] Intel GPU / OpenVINO ─────────────────────────────────
echo.
echo [6/6] OpenVINO (ускорение на Intel iGPU)?
echo   Требует Intel Graphics Driver + ~200 МБ доп. пакетов.
echo   Позволяет запускать Whisper прямо на Intel встроенной видеокарте.
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

:: ── Воск-модель (small-ru по умолчанию) ─────────────────────
echo.
echo [доп] Vosk-модель small-ru (45 МБ)?
echo   Пропустите, если уже есть папка model\ или models\vosk\
choice /c ДН /n /m "  Скачать vosk-model-small-ru? [Д/Н]: "
if errorlevel 2 (
    echo  Пропускаем
) else (
    if exist model\ (
        echo  Папка model\ уже существует, пропускаем
    ) else (
        echo  Скачивание...
        powershell -Command "Invoke-WebRequest -Uri 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip' -OutFile 'vosk-model-small-ru-0.22.zip' -UseBasicParsing"
        if errorlevel 1 (
            echo  ОШИБКА: не удалось скачать
            echo  Скачайте вручную: https://alphacephei.com/vosk/models
            echo  Распакуйте в папку model\
        ) else (
            echo  Распаковка...
            powershell -Command "Expand-Archive -Path 'vosk-model-small-ru-0.22.zip' -DestinationPath '.' -Force"
            rename vosk-model-small-ru-0.22 model
            del vosk-model-small-ru-0.22.zip
            echo  OK: модель в папке model\
        )
    )
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

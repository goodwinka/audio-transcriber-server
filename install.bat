@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Транскрипция аудио — Установка

echo.
echo  ╔══════════════════════════════════════╗
echo  ║   Транскрипция аудио — Установка    ║
echo  ╚══════════════════════════════════════╝
echo.

:: ── Проверка Python ──────────────────────────────────────────
echo [1/5] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ОШИБКА: Python не найден.
    echo  Скачайте с https://www.python.org/downloads/
    echo  При установке поставьте галочку "Add Python to PATH"
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo  OK: %%v

:: ── Проверка ffmpeg ───────────────────────────────────────────
echo.
echo [2/5] Проверка ffmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo  ОШИБКА: ffmpeg не найден в PATH.
    echo.
    echo  Установка:
    echo    1. Скачайте ffmpeg-release-essentials.zip
    echo       с https://www.gyan.dev/ffmpeg/builds/
    echo    2. Распакуйте в C:\ffmpeg
    echo    3. Добавьте C:\ffmpeg\bin в системный PATH:
    echo       Пуск -^> "Переменные среды" -^> Path -^> Изменить -^> Создать
    echo    4. Перезапустите этот скрипт
    pause & exit /b 1
)
echo  OK: ffmpeg найден

:: ── Создание виртуального окружения ─────────────────────────
echo.
echo [3/5] Создание виртуального окружения (.venv)...
if exist .venv (
    echo  Окружение уже существует, пропускаем
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo  ОШИБКА: не удалось создать venv
        pause & exit /b 1
    )
    echo  OK: .venv создан
)

:: ── Установка зависимостей ───────────────────────────────────
echo.
echo [4/5] Установка Python-пакетов в .venv...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt
if errorlevel 1 (
    echo  ОШИБКА: не удалось установить зависимости
    pause & exit /b 1
)
echo  OK: пакеты установлены

:: ── Скачивание модели Vosk ───────────────────────────────────
echo.
echo [5/5] Проверка модели Vosk...
if exist model\ (
    echo  Модель уже на месте, пропускаем
) else (
    echo  Скачивание vosk-model-small-ru-0.22 (45 МБ^)...
    echo  Это может занять несколько минут...
    powershell -Command "& {Invoke-WebRequest -Uri 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip' -OutFile 'vosk-model-small-ru-0.22.zip' -UseBasicParsing}"
    if errorlevel 1 (
        echo  ОШИБКА: не удалось скачать модель
        echo  Скачайте вручную с https://alphacephei.com/vosk/models
        echo  и распакуйте папку как 'model' рядом с app.py
        pause & exit /b 1
    )
    echo  Распаковка...
    powershell -Command "Expand-Archive -Path 'vosk-model-small-ru-0.22.zip' -DestinationPath '.' -Force"
    rename vosk-model-small-ru-0.22 model
    del vosk-model-small-ru-0.22.zip
    echo  OK: модель установлена
)

:: ── Итог ─────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   Установка завершена успешно!          ║
echo  ║                                         ║
echo  ║   Для запуска сервера: start.bat        ║
echo  ╚══════════════════════════════════════════╝
echo.
pause

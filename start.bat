@echo off
setlocal
chcp 65001 >nul
title Транскрипция аудио

:: Переходим в папку скрипта, чтобы относительные пути (models/, .venv/) работали
cd /d "%~dp0"

:: Проверяем, что установка была выполнена
if not exist .venv\ (
    echo  Виртуальное окружение не найдено.
    echo  Сначала запустите install.bat
    pause & exit /b 1
)

if not exist model\ (
    echo  Модель Vosk не найдена.
    echo  Сначала запустите install.bat
    pause & exit /b 1
)

:: Активируем venv и запускаем сервер
call .venv\Scripts\activate.bat

echo.
echo  Сервер запускается...
echo  Откройте браузер: http://localhost:5000
echo  Для остановки нажмите Ctrl+C
echo.

python app.py

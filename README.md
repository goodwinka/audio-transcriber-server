# Транскрипция аудио — локальный сервер

Лёгкий веб-сервер для транскрипции аудиофайлов в текст.
Работает **полностью офлайн**, использует Vosk (быстрый, мало ресурсов).

---

## Быстрый старт (Windows)

### 1. Установка Python

Скачайте Python 3.9+ с https://www.python.org/downloads/
При установке обязательно поставьте галочку **"Add Python to PATH"**.

Проверьте в PowerShell:
```powershell
python --version
```

### 2. Установка ffmpeg

1. Скачайте ffmpeg с https://www.gyan.dev/ffmpeg/builds/ → раздел **release builds** → `ffmpeg-release-essentials.zip`
2. Распакуйте архив, например в `C:\ffmpeg`
3. Добавьте `C:\ffmpeg\bin` в системную переменную PATH:
   **Пуск → Изменить системные переменные среды → Переменные среды → Path → Изменить → Создать**
4. Перезапустите PowerShell и проверьте:
```powershell
ffmpeg -version
```

### 3. Установка зависимостей

Откройте PowerShell в папке с проектом:
```powershell
pip install -r requirements.txt
```

### 4. Скачивание модели Vosk

Скачайте русскую модель с https://alphacephei.com/vosk/models

| Модель | Размер | Скорость | Точность |
|--------|--------|----------|----------|
| `vosk-model-small-ru-0.22` | 45 МБ | ★★★★★ | ★★★☆☆ |
| `vosk-model-ru-0.42` | 1.8 ГБ | ★★★☆☆ | ★★★★★ |

**Для слабого сервера рекомендуется `small-ru`** — работает в ~10× быстрее реального времени.

1. Скачайте ZIP-архив модели
2. Распакуйте его в папку проекта
3. Переименуйте папку в `model` (рядом с `app.py`)

Структура должна быть такой:
```
audio-transcriber-server\
├── app.py
├── model\          ← папка модели
│   ├── am\
│   ├── conf\
│   └── ...
└── ...
```

Или задайте путь через переменную окружения:
```powershell
$env:VOSK_MODEL = "C:\path\to\model"
```

### 5. Запуск

```powershell
python app.py
```

Откройте браузер: `http://localhost:5000`

---

## Автозапуск при старте Windows (опционально)

Создайте файл `start.bat` в папке проекта:
```bat
@echo off
cd /d %~dp0
python app.py
pause
```

Чтобы запускался автоматически при входе в систему — поместите ярлык на `start.bat` в папку:
`Win+R` → `shell:startup`

---

## Форматы

Поддерживаются: WAV, MP3, OGG, FLAC, M4A, AAC, WMA, WEBM.
Всё конвертируется в WAV 16kHz mono через ffmpeg.

---

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `VOSK_MODEL` | `model` | Путь к папке модели |
| `PORT` | `5000` | Порт сервера |

Пример установки в PowerShell:
```powershell
$env:PORT = "8080"
python app.py
```

---

## Продакшн (Windows)

Для стабильной работы используйте **waitress** (WSGI-сервер для Windows):

```powershell
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

> `gunicorn` на Windows не поддерживается — используйте `waitress`.

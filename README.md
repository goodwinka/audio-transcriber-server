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

1. Скачайте `ffmpeg-release-essentials.zip` с https://www.gyan.dev/ffmpeg/builds/ (раздел **release builds**)
2. Распакуйте архив в `C:\ffmpeg`
3. Добавьте `C:\ffmpeg\bin` в системный PATH:
   **Пуск → "Изменить системные переменные среды" → Переменные среды → Path → Изменить → Создать**
4. Перезапустите PowerShell и проверьте:
```powershell
ffmpeg -version
```

### 3. Установка и запуск

```
install.bat   — установка (один раз)
start.bat     — запуск сервера
```

`install.bat` автоматически:
- создаёт виртуальное окружение `.venv`
- устанавливает зависимости внутрь `.venv`
- скачивает модель Vosk (~45 МБ)

После запуска `start.bat` откройте браузер: `http://localhost:5000`

---

## Структура проекта

```
audio-transcriber-server\
├── app.py
├── install.bat       ← установка (запустить один раз)
├── start.bat         ← запуск сервера
├── requirements.txt
├── .venv\            ← создаётся автоматически
├── model\            ← скачивается автоматически
├── outputs\          ← готовые транскрипции (.txt)
└── history.json      ← история транскрипций
```

---

## Автозапуск при входе в Windows (опционально)

Поместите ярлык на `start.bat` в папку автозагрузки:

`Win+R` → введите `shell:startup` → скопируйте туда ярлык

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

Пример установки перед запуском:
```powershell
$env:PORT = "8080"
.\.venv\Scripts\python.exe app.py
```

---

## Модели Vosk

| Модель | Размер | Скорость | Точность |
|--------|--------|----------|----------|
| `vosk-model-small-ru-0.22` | 45 МБ | ★★★★★ | ★★★☆☆ |
| `vosk-model-ru-0.42` | 1.8 ГБ | ★★★☆☆ | ★★★★★ |

Для замены модели: скачайте с https://alphacephei.com/vosk/models, распакуйте и укажите путь через `VOSK_MODEL`.

---

## Продакшн (Windows)

Для стабильной работы используйте **waitress** (WSGI-сервер, поддерживает Windows):

```powershell
.venv\Scripts\pip install waitress
.venv\Scripts\waitress-serve --host=0.0.0.0 --port=5000 app:app
```

> `gunicorn` на Windows не поддерживается.

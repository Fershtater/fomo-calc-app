# Локальный запуск FarmCalc через Poetry

## Быстрый старт

### 1. Установка Poetry (если еще не установлен)

```bash
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"
```

Или через Homebrew (macOS):
```bash
brew install poetry
```

### 2. Установка зависимостей

```bash
poetry install
```

### 3. Настройка .env файла

Скопируйте `.env.example` в `.env` и заполните необходимые переменные:

```bash
cp .env.example .env
nano .env  # или используйте ваш любимый редактор
```

**Минимально необходимые переменные:**
```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_OWNER_ID=your_user_id_here
```

### 4. Запуск

#### Вариант 1: Через скрипт run.sh

```bash
# Запустить API сервер
./run.sh api

# Запустить watcher
./run.sh watch

# Запустить Telegram polling
./run.sh telegram-poll
```

#### Вариант 2: Через Poetry напрямую

```bash
# Активировать виртуальное окружение
poetry shell

# Или запускать команды через poetry run
poetry run farmcalc --help
poetry run uvicorn farmcalc.api:app --reload
poetry run farmcalc watch
```

#### Вариант 3: Через Make

```bash
# Установить зависимости
make poetry-install

# Запустить API
make run-api

# Запустить watcher
make run-watch
```

## Основные команды

### CLI команды

```bash
# Инициализация
poetry run farmcalc init

# Предложить сделку
poetry run farmcalc propose BTC

# Статус
poetry run farmcalc status

# Запустить watcher
poetry run farmcalc watch --interval 5 --top 25
```

### Telegram команды

```bash
# Установить webhook
poetry run farmcalc telegram set-webhook --url https://your-domain.com/telegram/webhook

# Удалить webhook
poetry run farmcalc telegram delete-webhook

# Запустить long polling (для разработки)
poetry run farmcalc telegram poll

# Отправить тестовое сообщение
poetry run farmcalc telegram send-test

# Проверить статус
poetry run farmcalc telegram status
```

### API сервер

```bash
# Запустить с auto-reload (для разработки)
poetry run uvicorn farmcalc.api:app --reload --host 0.0.0.0 --port 8000

# Запустить в production режиме
poetry run uvicorn farmcalc.api:app --host 0.0.0.0 --port 8000
```

API будет доступен по адресу: http://localhost:8000

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Структура проекта

```
farmcalc/
  ├── api.py              # FastAPI приложение
  ├── main.py              # CLI точка входа
  ├── settings.py          # Настройки из env
  ├── clients/             # API клиенты
  ├── services/            # Бизнес-логика
  ├── models/              # Модели данных
  ├── storage/             # Хранение состояния
  └── ui/                  # CLI вывод
```

## Переменные окружения

Все настройки загружаются из `.env` файла. См. `.env.example` для полного списка.

**Важно:** `.env` файл должен быть в корне проекта и не должен попадать в git (добавлен в .gitignore).

## Разработка

### Установка dev зависимостей

```bash
poetry install --with dev
```

### Запуск тестов

```bash
poetry run pytest tests/ -v
```

### Линтинг и форматирование

```bash
# Проверка кода
poetry run ruff check farmcalc/ tests/

# Форматирование
poetry run black farmcalc/ tests/
```

Или через Make:
```bash
make lint
make format
```

## Troubleshooting

### Poetry не найден

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Или добавьте в `~/.bashrc` или `~/.zshrc`:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Ошибки импорта

Убедитесь, что вы активировали виртуальное окружение:
```bash
poetry shell
```

Или используйте `poetry run` перед каждой командой.

### .env файл не загружается

Убедитесь, что:
1. Файл `.env` существует в корне проекта
2. Переменные указаны в формате `KEY=value` (без пробелов вокруг `=`)
3. Нет синтаксических ошибок в файле

### Порт 8000 занят

Используйте другой порт:
```bash
poetry run uvicorn farmcalc.api:app --port 8001
```

## Production запуск

Для production используйте systemd (см. README.md) или запускайте через:

```bash
poetry run uvicorn farmcalc.api:app --host 0.0.0.0 --port 8000 --workers 4
```

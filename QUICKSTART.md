# Быстрый старт (Poetry)

## 1. Установка Poetry

```bash
# macOS/Linux
curl -sSL https://install.python-poetry.org | python3 -

# Или через Homebrew (macOS)
brew install poetry

# Добавить в PATH (добавьте в ~/.zshrc или ~/.bashrc)
export PATH="$HOME/.local/bin:$PATH"
```

## 2. Установка зависимостей

```bash
poetry install
```

## 3. Настройка .env

Убедитесь, что у вас есть `.env` файл с минимальными настройками:

```bash
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_OWNER_ID=your_user_id
```

## 4. Запуск

### API сервер:
```bash
poetry run uvicorn farmcalc.api:app --reload
```

Или через скрипт:
```bash
./run.sh api
```

### Watcher:
```bash
poetry run farmcalc watch
```

Или:
```bash
./run.sh watch
```

### CLI команды:
```bash
poetry run farmcalc --help
poetry run farmcalc status
poetry run farmcalc propose BTC
```

## Альтернатива: без Poetry

Если Poetry не установлен, можно использовать pip:

```bash
pip install -e .
uvicorn farmcalc.api:app --reload
```

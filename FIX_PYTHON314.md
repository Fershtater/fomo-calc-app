# Исправление ошибки Python 3.14

Проблема: `AttributeError: 'typing.Union' object has no attribute '__module__'`

Это известная проблема совместимости Python 3.14 с старыми версиями `httpx`/`httpcore`.

## Решение 1: Обновить зависимости

```bash
# Удалить старые версии и установить новые
poetry remove httpx httpcore
poetry add "httpx>=0.27.0"
poetry install
```

## Решение 2: Использовать Python 3.11 или 3.12

Если обновление не помогает, можно использовать более старую версию Python:

```bash
# Установить Python 3.12 через pyenv или homebrew
pyenv install 3.12.0
pyenv local 3.12.0

# Или через homebrew
brew install python@3.12

# Указать Poetry использовать Python 3.12
poetry env use python3.12
poetry install
```

## Решение 3: Обновить все зависимости

```bash
poetry update
```

Текущая версия httpx в pyproject.toml обновлена до ^0.27.0, которая должна поддерживать Python 3.14.

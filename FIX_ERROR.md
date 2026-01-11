# Исправление ошибки Python 3.14 + httpx/httpcore

## Проблема

```
AttributeError: 'typing.Union' object has no attribute '__module__' and no __dict__ for setting new attributes.
```

Это известная проблема совместимости Python 3.14 с старыми версиями `httpcore`/`httpx`.

## Решение

Я обновил версии в `pyproject.toml`:
- `httpx`: `^0.24.0` → `^0.27.0`
- Обновлены `requirements.txt`

**Теперь выполните:**

```bash
# Переустановить зависимости
poetry lock --no-update
poetry install

# Или если lock не помогает
poetry update httpx httpcore
poetry install
```

## Альтернативное решение (если не помогло)

Если проблема сохраняется, используйте Python 3.12 или 3.13:

```bash
# Установить Python 3.12 через pyenv
pyenv install 3.12.0
pyenv local 3.12.0

# Или через Homebrew
brew install python@3.12

# Указать Poetry использовать Python 3.12
poetry env use python3.12
poetry install
```

## Проверка

После обновления проверьте:

```bash
poetry run python -c "import httpx; print(httpx.__version__)"
poetry run uvicorn farmcalc.api:app --reload
```

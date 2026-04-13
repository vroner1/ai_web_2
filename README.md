## запуск

1. Запустите PostgreSQL. (например, 
docker run -d -p 5433:5432 -e POSTGRES_PASSWORD=root -e POSTGRES_DB=ai_web_db -e POSTGRES_USER=postgres postgres:16.9-alpine
https://docs.docker.com/engine/install/
)
2. Создайте `.env` с переменной `DATABASE_URL`.
3. Примените миграции:
```bash
uv run alembic upgrade head
```
4. Запустите API:
```bash
uv run uvicorn app.main:app --reload --port <..порт..>
```

## LLM mode

Сервис поддерживает два режима работы с моделью: `mock` использует встроенную `MockLLM`, а `real` подключает внешнюю LLM через OpenRouter. 
Режим выбирается в `.env` через `LLM_MODE`. 
Для mock-режима достаточно `LLM_MODE=mock`; 
Для real-режима нужно указать `LLM_MODE=real`, `LLM_PROVIDER=openrouter`, `LLM_API_KEY=<your_key>`, `LLM_MODEL=openrouter/free`, `LLM_BASE_URL=https://openrouter.ai/api/v1`. 
Запуск стандартный: `uv sync`, `uv run alembic upgrade head`, `uv run uvicorn app.main:app --reload --port 8001`. 
Эндпоинты `POST /chat` и `POST /chat/stream` работают в обоих режимах и сохраняют историю запроса, включая текст ответа, признак streaming/non-streaming, имя модели и метаданные провайдера.

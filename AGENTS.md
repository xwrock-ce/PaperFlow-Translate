# Repository Guidelines

## Project Snapshot
- Repository folder: `PaperFlow-Translate`
- Maintained Python package, CLI names, and published metadata: `pdf2zh_next` / `pdf2zh-next`
- User-facing branding in README/docs still uses `PDFMathTranslate`; do not rename runtime commands or package paths to match the repo folder.
- Supported Python range: `>=3.10,<3.14`
- Backend stack: FastAPI + Uvicorn
- Frontend stack: React 19 + TypeScript + Vite in `frontend/`
- Local WebUI is seat-based and includes seat claim, heartbeat, release, active-job binding, and per-seat service selection.
- `pdf2zh_next --gui` serves the local WebUI. From a source checkout, it will auto-run the frontend build when `frontend/dist/index.html` is missing, and will also run `npm install` if `frontend/node_modules/` is absent.

## Public Entry Points
- CLI: `pdf2zh`, `pdf2zh2`, `pdf2zh_next`, `python -m pdf2zh_next`
- Local WebUI: `pdf2zh_next --gui`
- HTTP API: `python -m pdf2zh_next.http_api`
- Asset maintenance:
  - `pdf2zh_next --warmup`
  - `pdf2zh_next --generate-offline-assets <dir>`
  - `pdf2zh_next --restore-offline-assets <path>`

## Key Paths

### Runtime And Startup
- `pdf2zh_next/main.py`: main CLI flow, startup errors, asset commands, GUI launch
- `pdf2zh_next/__main__.py`: `python -m pdf2zh_next` entry
- `pdf2zh_next/high_level.py`: shared translation pipeline and PDF validation

### WebUI And HTTP API
- `pdf2zh_next/web.py`: GUI bootstrap and frontend auto-build
- `pdf2zh_next/http_api.py`: FastAPI app, translation routes, seat lifecycle, job state, static asset serving
- `pdf2zh_next/web_schema.py`: Web response/static path helpers
- `pdf2zh_next/webui_payload.py`: frontend payload assembly
- `pdf2zh_next/web_localization.py`
- `pdf2zh_next/web_i18n.py`
- `pdf2zh_next/ui_options.py`

### Config And Engine Metadata
- `pdf2zh_next/config/main.py`
- `pdf2zh_next/config/model.py`
- `pdf2zh_next/config/cli_env_model.py`
- `pdf2zh_next/config/translate_engine_model.py`

### Translation Internals
- `pdf2zh_next/translator/translator_impl/`
- `pdf2zh_next/translator/rate_limiter/`
- `pdf2zh_next/translator/cache.py`
- `pdf2zh_next/translator/base_translator.py`
- `pdf2zh_next/translator/base_rate_limiter.py`

### Frontend
- `frontend/src/App.tsx`: app shell
- `frontend/src/components/`: WebUI sections and controls
- `frontend/src/lib/api.ts`: API client
- `frontend/src/lib/types.ts`: shared frontend payload types
- `frontend/src/lib/copy.ts`, `frontend/src/lib/i18n.ts`: copy and i18n helpers
- `frontend/src/styles/app.css`: shared styling

### Tests
- `tests/test_app_main.py`: CLI startup and control flow
- `tests/test_user_experience.py`: user-facing CLI behavior and error flows
- `tests/test_http_api.py`: FastAPI routes, streaming, static serving, payloads, and seat workflows
- `tests/test_high_level.py`: translation pipeline
- `tests/test_translator_cache.py`: translator cache behavior
- `tests/config/`: config parsing and settings models
- `test/file/`: PDF fixtures

### Docs And Deployment
- `README.md`: primary user-facing overview and quick start
- `docs/en/`: primary documentation source
- `docs/{zh,zh_TW,ja,ko,de,fr,es,it,pt,ru}/`: localized docs
- `mkdocs.yml`
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `deploy/nginx/pdf2zh-next.conf.example`
- `script/`
- `pyproject.toml`
- `uv.lock`

## Source Of Truth
- Prefer `pdf2zh_next/`, `frontend/src/`, `tests/`, `README.md`, and `docs/en/` when behavior is unclear.
- Treat localized docs as secondary unless the task explicitly targets them.
- Do not infer behavior from generated bundles, caches, `.pyc` files, or local output directories.
- Keep CLI help, README examples, docs, API responses, and frontend/backend payload contracts aligned when public behavior changes.

## Generated Or Local-Only Artifacts
- Treat these as generated, disposable, or machine-local unless the task explicitly targets them:
  - `.doctemp/`
  - `pdf2zh_files/`
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `.venv/`
  - `frontend/dist/`
  - `frontend/node_modules/`
  - `frontend/*.tsbuildinfo`
  - `**/__pycache__/`

## Development Commands
- Install Python dependencies: `uv sync`
- Run all tests: `uv run pytest .`
- Focused test runs:
  - CLI and UX: `uv run pytest tests/test_app_main.py tests/test_user_experience.py`
  - HTTP API and WebUI backend: `uv run pytest tests/test_http_api.py`
  - Translation pipeline: `uv run pytest tests/test_high_level.py`
  - Translator cache: `uv run pytest tests/test_translator_cache.py`
  - Config models: `uv run pytest tests/config/test_main.py tests/config/test_model.py`
- Lint and format:
  - `uv run ruff check .`
  - `uv run ruff format .`
- Frontend:
  - install dependencies: `cd frontend && npm install`
  - production build: `cd frontend && npm run build`
  - dev server: `cd frontend && npm run dev`
- Runtime smoke checks:
  - warm assets: `uv run pdf2zh_next --warmup`
  - local WebUI: `timeout 10 uv run pdf2zh_next --gui`
  - HTTP API: `uv run python -m pdf2zh_next.http_api`
- Packaging and docs:
  - `uv build`
  - `uv run mkdocs serve`
  - `uv run pre-commit run --all-files`

## Change Guidance
- Follow Ruff formatting and linting. The repo uses Ruff isort with single-line imports.
- Use 4-space indentation, `snake_case` for functions/modules/variables, and `PascalCase` for classes.
- Keep changes small and targeted. Avoid unrelated refactors in CLI startup, config parsing, translation engines, rate limiting, WebUI startup, HTTP API behavior, seat management, or frontend/backend contracts.
- If dependency changes affect behavior, update the matching manifests:
  - Python: `pyproject.toml` and `uv.lock`
  - Frontend: `frontend/package.json` and `frontend/package-lock.json`
- If you change WebUI fields, translation engine metadata, or browser payloads, keep `pdf2zh_next/http_api.py` and `frontend/src/lib/` in sync.
- If you change public behavior, update the matching user-facing docs in `README.md` and `docs/en/`. Update localized docs only when the task requires it.

## Validation Expectations
- Add or update tests when changing CLI parsing or startup, config models/defaults, translation flow, caching, rate limiting, HTTP API behavior, GUI/WebUI startup, static asset serving, seat management, or frontend/backend contracts.
- Prefer the narrowest relevant validation first, then run broader smoke checks for startup or integration work.
- If you touch CLI startup, argument parsing, defaults, or user-facing errors, run:
  - `uv run pytest tests/test_app_main.py tests/test_user_experience.py tests/config/test_main.py tests/config/test_model.py`
- If you touch the shared translation pipeline, run:
  - `uv run pytest tests/test_high_level.py`
- If you touch translator cache behavior, run:
  - `uv run pytest tests/test_translator_cache.py`
- If you touch HTTP API behavior, GUI/WebUI startup, static asset serving, seat workflows, or frontend/backend contracts, run:
  - `uv run pytest tests/test_http_api.py`
  - `timeout 10 uv run pdf2zh_next --gui`
- If you touch `frontend/src/`, run:
  - `cd frontend && npm run build`
- Do not modify sample PDFs under `test/file/` unless fixture changes are explicitly required.

## Contribution Hygiene
- Use concise Conventional Commit-style commit subjects.
- Keep code, tests, docs, and examples aligned with the current implementation.

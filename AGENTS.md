# Repository Guidelines

## Current Project State
- Repository directory is `PaperFlow-Translate`, but the maintained Python package, CLI names, and published package metadata are still `pdf2zh_next` / `pdf2zh-next`. Keep runtime names, docs, and examples aligned with the package, not the folder name.
- Main runtime package: `pdf2zh_next/`.
- Supported Python range: `>=3.10,<3.14`.
- Frontend stack: React 19 + TypeScript + Vite in `frontend/`.
- The browser workflow is seat-based. The React WebUI and FastAPI backend coordinate seat claiming, heartbeats, release, active-job binding, and per-seat service selection.

## Public Entry Points
- CLI: `pdf2zh`, `pdf2zh2`, `pdf2zh_next`, `python -m pdf2zh_next`
- Local GUI: `pdf2zh_next --gui`
- HTTP API: `python -m pdf2zh_next.http_api`
- Asset maintenance: `pdf2zh_next --warmup`, `--generate-offline-assets`, `--restore-offline-assets`

## Repository Layout
- Runtime entry points:
  - `pdf2zh_next/main.py`: primary CLI flow
  - `pdf2zh_next/__main__.py`: `python -m pdf2zh_next`
  - `pdf2zh_next/web.py`: local GUI startup; builds `frontend/dist/` when missing
  - `pdf2zh_next/http_api.py`: FastAPI app, translation routes, seat-management routes, job handling, and frontend asset serving
  - `pdf2zh_next/high_level.py`: shared translation pipeline and PDF validation helpers
- Configuration:
  - `pdf2zh_next/config/main.py`: CLI parser and config manager
  - `pdf2zh_next/config/model.py`: settings models
  - `pdf2zh_next/config/cli_env_model.py`: CLI and environment bridge
  - `pdf2zh_next/config/translate_engine_model.py`: translation engine metadata and UI field definitions
- Translation internals:
  - `pdf2zh_next/translator/translator_impl/`: service integrations
  - `pdf2zh_next/translator/rate_limiter/`: throttling implementations
  - `pdf2zh_next/translator/cache.py`, `base_translator.py`, `base_rate_limiter.py`: shared translator primitives
- WebUI contract helpers:
  - `pdf2zh_next/web_schema.py`
  - `pdf2zh_next/webui_payload.py`
  - `pdf2zh_next/web_localization.py`
  - `pdf2zh_next/web_i18n.py`
  - `pdf2zh_next/ui_options.py`
- Frontend:
  - `frontend/src/App.tsx`: app shell
  - `frontend/src/components/`: upload, settings, progress, preview, and download panels
  - `frontend/src/lib/`: API client, types, copy, and i18n helpers
  - `frontend/src/styles/app.css`: shared styling
- Tests:
  - `tests/test_app_main.py`: CLI startup and control flow
  - `tests/test_user_experience.py`: user-facing CLI flows and errors
  - `tests/test_http_api.py`: FastAPI routes, streaming, static serving, browser payloads, and seat management
  - `tests/test_high_level.py`: translation pipeline
  - `tests/config/`: config parsing and settings models
- Docs and packaging:
  - `docs/`: multilingual MkDocs source
  - `script/`: helper scripts and container variants
  - `Dockerfile`: container packaging
  - `test/file/`: PDF fixtures for smoke checks

## Source Of Truth
- Treat source files under `pdf2zh_next/`, `frontend/src/`, `tests/`, `README.md`, and `docs/` as the authority.
- Do not infer current behavior from generated output, cached `.pyc` files, or build artifacts.
- Keep CLI help text, README examples, docs pages, API behavior, and frontend/backend payload contracts synchronized when public behavior changes.

## Generated And Local Artifacts
- Treat these as generated or local-only unless the task explicitly targets them:
  - `.doctemp/`
  - `pdf2zh_files/`
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `.venv/`
  - `frontend/dist/`
  - `frontend/node_modules/`
  - `frontend/*.tsbuildinfo`
  - all `__pycache__/` directories
- Do not use generated output as source when updating code or docs.

## Development Commands
- Install Python dependencies: `uv sync`
- Run all tests: `uv run pytest .`
- Run focused tests:
  - CLI and UX: `uv run pytest tests/test_app_main.py tests/test_user_experience.py`
  - HTTP API and seat management: `uv run pytest tests/test_http_api.py`
  - Translation pipeline: `uv run pytest tests/test_high_level.py`
  - Config parsing and models: `uv run pytest tests/config/test_main.py tests/config/test_model.py`
- Lint and format:
  - `uv run ruff check .`
  - `uv run ruff format .`
- Frontend:
  - install/build: `cd frontend && npm install && npm run build`
  - dev server: `cd frontend && npm run dev`
- Runtime smoke checks:
  - warm assets: `uv run pdf2zh_next --warmup`
  - local GUI: `timeout 10 uv run pdf2zh_next --gui`
  - HTTP API: `uv run python -m pdf2zh_next.http_api`
  - CLI PDFs:
    - `uv run pdf2zh_next ./test/file/translate.cli.plain.text.pdf --output ./test/file`
    - `uv run pdf2zh_next ./test/file/translate.cli.text.with.figure.pdf --output ./test/file`
- Packaging and docs:
  - `uv build`
  - `uv run mkdocs serve`
  - `uv run pre-commit run --all-files`

## Change Guidance
- Follow Ruff formatting and linting. The repo uses Ruff isort with single-line imports.
- Use 4-space indentation, `snake_case` for functions/modules/variables, and `PascalCase` for classes.
- Keep changes small and targeted. Avoid unrelated refactors when touching:
  - config parsing
  - translation engines
  - rate limiting
  - CLI or GUI startup
  - translation workflow helpers
  - HTTP API behavior
  - seat management
  - frontend/backend contracts
- If behavior depends on dependency changes, update the relevant manifests:
  - Python: `pyproject.toml` and `uv.lock`
  - Frontend: `frontend/package.json` and `frontend/package-lock.json`
- If you change WebUI form fields, service metadata, or browser payloads, verify both `pdf2zh_next/http_api.py` and `frontend/src/lib/` stay in sync.
- If public behavior changes, update the matching user-facing docs:
  - `README.md`
  - relevant pages under `docs/`

## Validation Expectations
- Add or update tests when changing:
  - CLI parsing or startup
  - config models or defaults
  - translation flow, caching, or rate limiting
  - HTTP API behavior
  - GUI startup or static asset serving
  - seat-management behavior
  - frontend/backend contracts
- Prefer the narrowest relevant validation first, then broader smoke coverage for startup or integration changes.
- If you touch CLI startup, argument parsing, defaults, or user-facing errors, run:
  - `uv run pytest tests/test_app_main.py tests/test_user_experience.py tests/config/test_main.py tests/config/test_model.py`
- If you touch the shared translation pipeline, run:
  - `uv run pytest tests/test_high_level.py`
- If you touch HTTP API behavior, GUI startup, static asset serving, seat workflows, or frontend/backend contracts, run:
  - `uv run pytest tests/test_http_api.py`
  - `timeout 10 uv run pdf2zh_next --gui`
- Do not modify sample PDFs under `test/file/` unless fixture updates are explicitly required.

## Contribution Hygiene
- Use concise Conventional Commit-style commit subjects.
- Keep code, tests, docs, and examples aligned with the current implementation.

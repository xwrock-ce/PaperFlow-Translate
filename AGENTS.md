# Repository Guidelines

## Project Overview
- `pdf2zh_next/` is the main application package.
- Public entry points that should stay aligned with code, docs, and examples:
  `pdf2zh_next ...` for the CLI;
  `pdf2zh_next --gui` for the local GUI;
  `python -m pdf2zh_next.http_api` for the HTTP API.
- The current browser workflow is seat-based:
  the WebUI and HTTP API coordinate seat claiming, heartbeats, release, and per-seat engine selection.

## Project Structure
- Runtime entry points:
  `pdf2zh_next/main.py` is the primary CLI entry;
  `pdf2zh_next/__main__.py` supports `python -m pdf2zh_next`;
  `pdf2zh_next/web.py` starts the local GUI and builds the frontend when needed;
  `pdf2zh_next/http_api.py` defines the FastAPI app, translation endpoints, seat-management endpoints, and frontend asset serving;
  `pdf2zh_next/high_level.py` contains the reusable translation workflow and PDF validation helpers.
- Configuration lives under `pdf2zh_next/config/`:
  `main.py` handles CLI parsing;
  `model.py`, `cli_env_model.py`, and `translate_engine_model.py` define settings and engine metadata.
- Translation internals live under `pdf2zh_next/translator/`:
  `translator_impl/` contains engine integrations;
  `rate_limiter/` contains throttling implementations;
  `cache.py`, `base_translator.py`, and `base_rate_limiter.py` define shared translator primitives.
- WebUI contract and localization helpers live in:
  `pdf2zh_next/web_schema.py`,
  `pdf2zh_next/webui_payload.py`,
  `pdf2zh_next/web_localization.py`,
  `pdf2zh_next/web_i18n.py`,
  `pdf2zh_next/ui_options.py`.
- Shared assets and helpers live under `pdf2zh_next/assets/` and `pdf2zh_next/utils/`.
- `frontend/` is the React 19 + TypeScript + Vite WebUI:
  `frontend/src/App.tsx` is the main shell;
  `frontend/src/components/` contains page sections and panels;
  `frontend/src/lib/` contains API clients, shared types, and i18n/copy helpers;
  `frontend/src/styles/app.css` is the main stylesheet;
  `frontend/dist/` is generated output.
- Tests live under `tests/`:
  `tests/test_app_main.py` covers CLI startup;
  `tests/test_user_experience.py` covers user-facing flows and errors;
  `tests/test_http_api.py` covers FastAPI routes, streaming, and seat management;
  `tests/test_high_level.py` covers the translation pipeline;
  `tests/config/` covers config parsing and settings models.
- Fixtures and docs:
  `test/file/` contains sample PDFs for smoke checks;
  `docs/` contains the MkDocs site and localized docs;
  `script/` and the repository `Dockerfile` contain packaging and deployment helpers.

## Generated Artifacts
- Treat these as generated unless the task explicitly targets them:
  `.doctemp/`, `pdf2zh_files/`, `.pytest_cache/`, `.ruff_cache/`, `.venv/`,
  `frontend/dist/`, `frontend/node_modules/`, `frontend/*.tsbuildinfo`, and all `__pycache__/` directories.
- Do not treat generated output as source of truth unless the task is specifically about build artifacts, packaging, or fixtures.

## Development Commands
- Install Python dependencies: `uv sync`
- Run the full test suite: `uv run pytest .`
- Run focused tests:
  `uv run pytest tests/test_app_main.py tests/test_user_experience.py`
  `uv run pytest tests/test_http_api.py`
  `uv run pytest tests/test_high_level.py`
  `uv run pytest tests/config/test_main.py tests/config/test_model.py`
- Lint and format: `uv run ruff check .` and `uv run ruff format .`
- Warm up BabelDOC assets: `uv run pdf2zh_next --warmup`
- CLI smoke checks:
  `uv run pdf2zh_next ./test/file/translate.cli.plain.text.pdf --output ./test/file`
  `uv run pdf2zh_next ./test/file/translate.cli.text.with.figure.pdf --output ./test/file`
- Start the local GUI: `timeout 10 uv run pdf2zh_next --gui`
  if port `7860` is already occupied, use `--server-port <free-port>`.
- Start the HTTP API: `uv run python -m pdf2zh_next.http_api`
- Build the frontend directly: `cd frontend && npm install && npm run build`
- Build the package: `uv build`
- Preview docs locally: `uv run mkdocs serve`
- Run pre-commit hooks: `uv run pre-commit run --all-files`

## Change Guidance
- Supported Python range is `>=3.10,<3.14`.
- Follow Ruff formatting and linting. This repo uses Ruff isort with single-line imports.
- Use 4-space indentation, `snake_case` for functions/modules/variables, and `PascalCase` for classes.
- Keep changes small and targeted. Avoid unrelated refactors when touching:
  config parsing,
  translation engines,
  rate limiting,
  startup flows,
  HTTP API behavior,
  seat management,
  WebUI serving,
  frontend/backend payload contracts.
- When behavior depends on dependency changes, update the relevant manifests:
  `pyproject.toml` and `uv.lock` for Python;
  `frontend/package.json` and `frontend/package-lock.json` for frontend.
- If public behavior, onboarding guidance, screenshots, or user-facing commands change, update `README.md` and the relevant docs under `docs/`.

## Validation
- Add or update tests when changing CLI parsing, config models, translation flow, caching, rate limiting, HTTP API behavior, seat management, GUI startup, or frontend/backend contracts.
- Name tests `tests/test_*.py` or `tests/config/test_*.py`, and test functions `test_*`.
- Prefer the narrowest relevant validation first, then broader smoke coverage when startup or integration behavior changes.
- If you touch CLI startup, argument parsing, defaults, or user-facing error messages, run:
  `uv run pytest tests/test_app_main.py tests/test_user_experience.py tests/config/test_main.py tests/config/test_model.py`
- If you touch translation workflow helpers or the shared pipeline, run:
  `uv run pytest tests/test_high_level.py`
- If you touch HTTP API behavior, GUI startup, static asset serving, seat flows, or frontend/backend contracts, run:
  `uv run pytest tests/test_http_api.py`
  `timeout 10 uv run pdf2zh_next --gui`
- Do not modify sample PDFs under `test/file/` unless fixture updates are explicitly required.

## Contribution Rules
- Use concise Conventional Commit-style commit subjects.
- Keep docs, examples, and tests aligned with the current implementation.

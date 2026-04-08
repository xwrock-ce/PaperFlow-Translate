# Repository Guidelines

## Project Layout
- `pdf2zh_next/` is the main application package.
- Primary entry points:
  `main.py` provides the CLI;
  `web.py` starts the local WebUI server;
  `http_api.py` exposes the FastAPI app and HTTP endpoints;
  `high_level.py` contains the reusable translation workflow.
- Backend structure:
  `config/` stores CLI parsing and settings models;
  `translator/` stores engine implementations, caching, rate limiting, and registration;
  `assets/` stores bundled assets;
  `utils/` stores shared helpers.
- `frontend/` is the React 19 + Vite WebUI. Source lives in `frontend/src/`, and build output lives in `frontend/dist/`. When running `pdf2zh_next --gui` from a source checkout, the backend will build the frontend automatically if `frontend/dist/index.html` is missing, so `npm` must be available.
- `tests/` is the main pytest suite. `tests/config/` covers configuration models and parsing behavior.
- `test/file/` contains sample PDFs used by smoke checks and fixtures.
- `docs/` contains the MkDocs site and localized documentation. `mkdocs.yml` configures the docs build.
- `script/` plus the repository-level `Dockerfile` contain packaging and deployment helpers.
- Treat `.doctemp/`, `pdf2zh_files/`, `.pytest_cache/`, `.ruff_cache/`, `frontend/dist/`, `frontend/node_modules/`, `.venv/`, and all `__pycache__/` directories as generated artifacts unless the task explicitly targets them.

## Development Commands
- Install Python dependencies: `uv sync`
- Run the full test suite: `uv run pytest .`
- Run focused tests:
  `uv run pytest tests/test_app_main.py tests/test_user_experience.py`
  `uv run pytest tests/test_http_api.py`
  `uv run pytest tests/test_high_level.py`
- Lint and format: `uv run ruff check .` and `uv run ruff format .`
- Warm up BabelDOC assets: `uv run pdf2zh_next --warmup`
- CLI smoke checks:
  `uv run pdf2zh_next ./test/file/translate.cli.plain.text.pdf --output ./test/file`
  `uv run pdf2zh_next ./test/file/translate.cli.text.with.figure.pdf --output ./test/file`
- Start the WebUI: `timeout 10 uv run pdf2zh_next --gui`
- Start the HTTP API: `uv run python -m pdf2zh_next.http_api`
- Build the frontend directly: `cd frontend && npm install && npm run build`
- Build the package: `uv build`
- Preview docs locally: `uv run mkdocs serve`
- Run pre-commit checks: `uv run pre-commit run --all-files`

## Style
- Supported Python range is `>=3.10,<3.14`.
- Follow Ruff for formatting and linting; this repository currently prefers single-line imports.
- Use 4-space indentation, `snake_case` for functions, variables, and modules, and `PascalCase` for classes.
- Keep changes small and targeted. Avoid unrelated refactors while touching translator engines, config models, startup paths, WebUI serving, or API entry points.
- Keep docs, examples, and test commands aligned with the current public entry points:
  `pdf2zh_next ...` for CLI work;
  `pdf2zh_next --gui` for the local WebUI;
  `python -m pdf2zh_next.http_api` for the HTTP API.
- Update `pyproject.toml` when adding or removing Python dependencies. Update `frontend/package.json` and related lockfiles when changing frontend dependencies.

## Validation
- Add or update automated tests in `tests/` when changing CLI parsing, config models, translation flow, caching, rate limiting, HTTP API behavior, WebUI schema/payload handling, or startup logic.
- Name test files `tests/test_*.py` and test functions `test_*`.
- Prefer the narrowest relevant validation first; add broader smoke coverage when a change affects startup or integration paths.
- If you touch WebUI startup, static asset serving, or the frontend/backend contract, verify `uv run pytest tests/test_http_api.py` and `timeout 10 uv run pdf2zh_next --gui`.
- If you touch CLI startup, argument parsing, or user-facing error handling, verify `uv run pytest tests/test_app_main.py tests/test_user_experience.py`.
- If you touch API behavior, verify `uv run pytest tests/test_http_api.py`, and start `uv run python -m pdf2zh_next.http_api` when manual verification is needed.
- Do not modify sample PDFs under `test/file/` unless the task explicitly requires fixture updates.

## Contribution Rules
- Use concise Conventional Commit-style subjects.
- Do not treat generated artifacts as source-of-truth changes unless the task explicitly targets them.
- If onboarding copy, public commands, or surface behavior changes, update `README.md` and the relevant docs so they stay aligned with the codebase.

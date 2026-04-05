# Repository Guidelines

## Project Layout
- `pdf2zh_next/` is the main backend package.
- Key entry points:
  `main.py` provides the CLI;
  `web.py` starts the local WebUI;
  `http_api.py` provides the FastAPI service;
  `high_level.py` exposes the high-level translation workflow for integrations.
- Important subdirectories:
  `config/` contains CLI and configuration models;
  `translator/` contains translator engines, caching, rate limiting, and implementation registration;
  `assets/` stores bundled resources;
  `utils/` stores shared helpers.
- `frontend/` is the React 19 + Vite WebUI. Source code lives in `frontend/src/`, and build output lives in `frontend/dist/`. When running `pdf2zh_next --gui` from a source checkout, missing static assets may trigger a local frontend build, so `npm` must be available.
- `tests/` is the main pytest suite and covers CLI behavior, config parsing, HTTP API, high-level translation flow, startup behavior, and user-facing error handling.
- `test/` contains lightweight smoke checks and sample PDFs, with fixtures under `test/file/`.
- `docs/` contains the MkDocs site and localized documentation; English content is under `docs/en/`, with sibling directories for other locales.
- `script/` and the repository-level `Dockerfile` contain packaging, distribution, and deployment helpers.
- Treat `.doctemp/`, `pdf2zh_files/`, `.pytest_cache/`, `.ruff_cache/`, `frontend/dist/`, `frontend/node_modules/`, `.venv/`, and all `__pycache__/` directories as generated artifacts unless the task explicitly targets them.

## Development Commands
- Install dependencies: `uv sync`
- Run the full test suite: `uv run pytest .`
- Run a focused API test: `uv run pytest tests/test_http_api.py`
- Lint and format: `uv run ruff check .` and `uv run ruff format .`
- Warm up BabelDOC assets: `uv run pdf2zh_next --warmup`
- CLI smoke checks:
  `uv run pdf2zh_next ./test/file/translate.cli.plain.text.pdf --output ./test/file`
  `uv run pdf2zh_next ./test/file/translate.cli.text.with.figure.pdf --output ./test/file`
- Start the WebUI: `timeout 10 uv run pdf2zh_next --gui`
- Start the HTTP API: `uv run python -m pdf2zh_next.http_api`
- Build the frontend directly: `cd frontend && npm run build`
- Build the package: `uv build`
- Preview docs locally: `uv run mkdocs serve`
- Run pre-commit checks: `pre-commit run --all-files`

## Style
- Supported Python range is `>=3.10,<3.14`.
- Follow Ruff for formatting and linting; this repository currently prefers single-line imports.
- Use 4-space indentation, `snake_case` for functions, variables, and modules, and `PascalCase` for classes.
- Keep changes small and targeted. Do not refactor unrelated logic while touching translator engines, config models, startup paths, or API entry points.
- Keep docs, examples, and test commands aligned with actual entry points. The current WebUI entry point is `pdf2zh_next --gui`.
- Update `pyproject.toml` in the same change when adding or removing dependencies.

## Validation
- Add or update automated tests in `tests/` when changing CLI parsing, config models, translation flow, caching, rate limiting, HTTP API behavior, or WebUI startup logic.
- Name test files `tests/test_*.py` and test functions `test_*`.
- Prefer the narrowest relevant validation first; add broader smoke coverage when a change affects startup or integration paths.
- If you touch WebUI startup or static asset serving, verify `timeout 10 uv run pdf2zh_next --gui`.
- If you touch API behavior, verify `uv run pytest tests/test_http_api.py`, and start `uv run python -m pdf2zh_next.http_api` when manual verification is needed.
- Do not modify sample PDFs under `test/file/` unless the task explicitly requires fixture updates.

## Contribution Rules
- Use concise Conventional Commit-style subjects.
- Do not treat generated artifacts as source-of-truth changes unless the task explicitly targets them.
- If homepage or onboarding copy changes, update `README.md`. Avoid letting `README.md`, docs, and CLI behavior drift out of sync.

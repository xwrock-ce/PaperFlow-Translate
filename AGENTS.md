# Repository Guidelines

## Project Layout
- `pdf2zh_next/` is the backend package.
  Main entry points: `main.py` for the CLI, `web.py` for local WebUI startup, `http_api.py` for the FastAPI service, and `high_level.py` for the translation orchestration layer.
  Important areas: `config/` for argument and settings models, `translator/` for engine implementations, cache, and rate limiting, `assets/` for bundled assets, and `utils/` for shared helpers.
- `frontend/` is the React 19 + Vite WebUI. Source lives under `frontend/src/`; `dist/` is the build output used by the backend, and may be rebuilt automatically when running `pdf2zh_next --gui` from source.
- `tests/` is the maintained pytest suite. Current coverage focuses on app startup, CLI behavior, HTTP API, high-level translation flow, config parsing, and user-facing error handling.
- `test/` contains lightweight smoke checks and PDF fixtures under `test/file/` for manual or CLI translation verification.
- `docs/` holds the MkDocs site and localized docs. English content is under `docs/en/`, with additional locales in sibling directories such as `docs/zh/`, `docs/ja/`, and `docs/fr/`.
- `script/` contains packaging and distribution helpers, including Dockerfiles and Windows setup helpers.
- Treat `.doctemp/`, `pdf2zh_files/`, `.pytest_cache/`, `.ruff_cache/`, `frontend/dist/`, `frontend/node_modules/`, and `__pycache__/` as generated artifacts unless the task is explicitly about them.

## Development Commands
- `uv sync`
- `uv run pytest .`
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run pdf2zh_next --warmup`
- `uv run pdf2zh_next ./test/file/translate.cli.plain.text.pdf --output ./test/file`
- `uv run pdf2zh_next ./test/file/translate.cli.text.with.figure.pdf --output ./test/file`
- `timeout 10 uv run pdf2zh_next --gui`
- `uv run python -m pdf2zh_next.http_api`
- `uv build`
- `uv run mkdocs serve`
- `pre-commit run --all-files`

## Style
- Supported Python range is `>=3.10,<3.14`.
- Follow Ruff for formatting and linting. The repo prefers single-line imports.
- Use 4-space indentation, `snake_case` for functions, variables, and modules, and `PascalCase` for classes.
- Prefer small, targeted changes. Do not refactor unrelated areas while touching translation engines, config models, or startup paths.
- Keep docs and examples aligned with the current entry points. The WebUI startup path is `pdf2zh_next --gui`, backed by `pdf2zh_next/web.py`.

## Validation
- Add or update tests when changing CLI parsing, config models, translation flow, cache behavior, HTTP API routes, or WebUI-serving backend logic.
- Place automated tests in `tests/` with `test_*.py` files and `test_*` functions.
- Run the narrowest relevant checks locally, but prefer matching the existing smoke paths when practical.
- If you touch WebUI startup, verify `timeout 10 uv run pdf2zh_next --gui`.
- If you touch API behavior, verify `uv run pytest tests/test_http_api.py` or start the service with `uv run python -m pdf2zh_next.http_api`.
- Avoid editing PDF fixtures unless the task explicitly requires fixture changes.

## Contribution Rules
- Use concise Conventional Commit-style subjects.
- Update `pyproject.toml` in the same change when adding or removing dependencies.
- Do not treat generated frontend output or cache directories as source-of-truth changes unless the task specifically targets build artifacts.
- If homepage copy needs updates, edit `README.md`. Avoid drifting docs examples away from the actual CLI and API behavior.

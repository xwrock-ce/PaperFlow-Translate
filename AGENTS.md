# Repository Guidelines

## Project Layout
- `pdf2zh_next/` contains the application code. Key entry points are `main.py` for the CLI, `gui.py` for the Gradio UI, `http_api.py` for the HTTP API, and `high_level.py` for BabelDOC orchestration. Supporting modules live under `config/`, `translator/`, `assets/`, and `utils/`.
- `tests/` holds pytest unit tests. The current suite is small and mostly config-focused.
- `test/` and `test/file/` hold legacy smoke tests and PDF fixtures used by CI.
- `docs/en/` is the primary documentation source. Localized copies live under `docs/<locale>/`. `mkdocs.yml` drives the docs site, and `docs/index.md` is generated from `README.md` in the docs workflow.
- `script/` contains packaging and release helpers. Treat `.doctemp/`, `pdf2zh_files/`, caches, and build outputs as generated artifacts, not source files.

## Core Commands
Use `uv` for local development:

- `uv sync`
- `uv run pytest .`
- `uv run pdf2zh_next ./test/file/translate.cli.plain.text.pdf --output ./test/file`
- `uv run pdf2zh_next ./test/file/translate.cli.text.with.figure.pdf --output ./test/file`
- `timeout 10 uv run pdf2zh_next --gui` for a GUI startup smoke check
- `uv build`
- `uv run mkdocs serve`
- `uv run ruff check .`
- `uv run ruff format .`
- `pre-commit run --all-files`

## Style
- Supported Python range is `>=3.10,<3.14`.
- Use 4-space indentation, `snake_case` for functions, variables, and modules, and `PascalCase` for classes.
- Ruff is the source of truth for linting and formatting. Keep imports Ruff-compatible; the repo is configured to prefer single-line imports.
- Prefer small, focused changes over broad cross-cutting refactors unless the task clearly requires them.

## Validation
- Add or update tests when changing CLI, config, translation flow, cache behavior, or GUI-adjacent backend logic.
- Put new unit tests under `tests/` using `test_*.py` filenames and `test_*` function names.
- Before opening a PR, run the commands that match the area you changed, and prefer matching the CI smoke checks when practical.
- Avoid modifying PDF fixtures unless the task specifically requires it.

## Contribution Rules
- Use concise Conventional Commit-style subjects.
- If you add or remove dependencies, update `pyproject.toml` in the same change.
- Do not submit PRs for non-English docs, `pdf2zh_next/gui_translation.yaml`, or PDF fixture changes unless maintainers explicitly ask for them.
- If homepage docs need copy updates, edit `README.md` rather than `docs/index.md`.

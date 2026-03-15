#!/usr/bin/env python3
"""A command line tool for extracting text and images from PDF and
output it to plain text, html, xml or tags.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import babeldoc.assets.assets
from pydantic import ValidationError

from pdf2zh_next.config import ConfigManager
from pdf2zh_next.config.main import build_args_parser
from pdf2zh_next.high_level import do_translate_file_async
from pdf2zh_next.high_level import validate_pdf_file

__version__ = "2.7.1"

logger = logging.getLogger(__name__)


_CLI_QUICKSTART_HINT = (
    "Quick start:\n"
    "  pdf2zh_next --warmup\n"
    "  pdf2zh_next paper.pdf --output ./translated\n"
    "  pdf2zh_next ./papers --output ./translated\n"
    "  pdf2zh_next --gui\n"
)


def _print_cli_usage_hint() -> None:
    message = (
        "No input PDF was provided.\n"
        "Pass one or more PDF files or directories containing PDFs, or use one of: --gui, --warmup, "
        "--generate-offline-assets, --restore-offline-assets, --version.\n"
        f"{_CLI_QUICKSTART_HINT}"
    )
    print(message, file=sys.stderr, flush=True)
    parser, _ = build_args_parser()
    parser.print_help(sys.stderr)


def _build_cli_error_hint(message: str) -> str | None:
    searchable_message = message.lower()
    if (
        "--server-port" in searchable_message
        or "gradio_server_port" in searchable_message
    ):
        return None
    if any(token in searchable_message for token in ("api key", "credential", "auth")):
        return (
            "Check the selected translation engine credentials or the related "
            "environment variables, then retry."
        )
    if (
        "not a valid pdf" in searchable_message
        or "is not a pdf file" in searchable_message
        or "file does not exist" in searchable_message
        or "input path is not a file" in searchable_message
    ):
        return (
            "Pass an existing PDF file, for example: "
            "pdf2zh_next paper.pdf --output ./translated"
        )
    if "no pdf files were found in directory" in searchable_message:
        return (
            "Point to a folder that contains .pdf files, for example: "
            "pdf2zh_next ./papers --output ./translated"
        )
    if "error parsing pages parameter" in searchable_message:
        return "Use --pages like 1,2,5-7."
    if "cannot disable both dual and mono" in searchable_message:
        return (
            "Leave at least one output enabled. Do not use --no-dual and "
            "--no-mono together."
        )
    if any(
        token in searchable_message
        for token in (
            "connecterror",
            "operation not permitted",
            "no available endpoints",
            "chatproxy",
            "api1.pdf2zh-next.com",
            "api2.pdf2zh-next.com",
        )
    ):
        return (
            "The default SiliconFlowFree service could not be reached. Check "
            "the network/proxy settings, retry later, or switch to another "
            "service such as `--openai` or `--ollama`."
        )
    if any(
        token in searchable_message
        for token in ("timeout", "timed out", "connection reset", "network")
    ):
        return (
            "The translation service did not respond in time. Check the network "
            "connection or lower the concurrency settings."
        )
    if (
        "no local port was available" in searchable_message
        or "fallback port probing is blocked" in searchable_message
        or ("port" in searchable_message and "in use" in searchable_message)
    ):
        return (
            "Retry the GUI with --server-port <free-port>, or set "
            "GRADIO_SERVER_PORT before starting --gui."
        )
    return None


def _combine_cli_hints(*hints: str | None) -> str | None:
    filtered_hints: list[str] = []
    for hint in hints:
        if not hint or hint in filtered_hints:
            continue
        filtered_hints.append(hint)
    return "\n".join(filtered_hints) if filtered_hints else None


def _print_cli_error(message: str, hint: str | None = None) -> None:
    print(f"Error: {message}", file=sys.stderr)
    if hint:
        print(hint, file=sys.stderr)


def _warmup_assets() -> None:
    logger.info("Warmup babeldoc assets...")
    babeldoc.assets.assets.warmup()


def _validate_cli_input_files(input_files: set[str]) -> None:
    for file in sorted(input_files):
        validate_pdf_file(file)


def _expand_cli_input_files(
    input_files: set[str],
) -> tuple[set[str], list[tuple[Path, int]]]:
    expanded_files: set[str] = set()
    expanded_directories: list[tuple[Path, int]] = []

    for raw_path in sorted(input_files):
        candidate_path = Path(raw_path).expanduser()
        if candidate_path.is_dir():
            pdf_files = sorted(find_all_files_in_directory(candidate_path))
            if not pdf_files:
                raise ValueError(
                    f"No PDF files were found in directory: {candidate_path}"
                )
            expanded_files.update(str(file_path) for file_path in pdf_files)
            expanded_directories.append((candidate_path, len(pdf_files)))
            continue
        expanded_files.add(str(candidate_path))

    return expanded_files, expanded_directories


def find_all_files_in_directory(directory_path):
    """
    Recursively search all PDF files in the given directory and return their paths as a list.

    :param directory_path: str, the path to the directory to search
    :return: list of PDF file paths
    """
    directory_path = Path(directory_path)
    # Check if the provided path is a directory
    if not directory_path.is_dir():
        raise ValueError(f"The provided path '{directory_path}' is not a directory.")

    file_paths = []

    # Walk through the directory recursively
    for root, _, files in os.walk(directory_path):
        for file in files:
            # Check if the file is a PDF
            if file.lower().endswith(".pdf"):
                # Append the full file path to the list
                file_paths.append(Path(root) / file)

    return file_paths


async def main() -> int:
    from rich.logging import RichHandler

    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])

    try:
        settings = ConfigManager().initialize_config()
    except (ValueError, ValidationError) as e:
        _print_cli_error(
            str(e),
            _combine_cli_hints(
                _build_cli_error_hint(str(e)),
                "Run `pdf2zh_next --help` for usage details.",
            ),
        )
        return 2

    if settings.basic.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # disable httpx, openai, httpcore, http11 logs
    logging.getLogger("httpx").setLevel("CRITICAL")
    logging.getLogger("httpx").propagate = False
    logging.getLogger("openai").setLevel("CRITICAL")
    logging.getLogger("openai").propagate = False
    logging.getLogger("httpcore").setLevel("CRITICAL")
    logging.getLogger("httpcore").propagate = False
    logging.getLogger("http11").setLevel("CRITICAL")
    logging.getLogger("http11").propagate = False

    for v in logging.Logger.manager.loggerDict.values():
        if getattr(v, "name", None) is None:
            continue
        if (
            v.name.startswith("pdfminer")
            or v.name.startswith("peewee")
            or v.name.startswith("httpx")
            or "http11" in v.name
            or "openai" in v.name
            or "pdfminer" in v.name
        ):
            v.disabled = True
            v.propagate = False

    logger.debug(f"settings: {settings}")

    if settings.basic.version:
        print(f"pdf2zh-next version: {__version__}")
        return 0

    if settings.basic.generate_offline_assets:
        output_directory = Path(settings.basic.generate_offline_assets).expanduser()
        logger.info("Generating offline assets package in %s", output_directory)
        babeldoc.assets.assets.generate_offline_assets_package(output_directory)
        print(f"Offline assets package generated in: {output_directory}", flush=True)
        return 0

    if settings.basic.restore_offline_assets:
        input_path = Path(settings.basic.restore_offline_assets).expanduser()
        logger.info("Restoring offline assets package from %s", input_path)
        babeldoc.assets.assets.restore_offline_assets_package(input_path)
        print(f"Offline assets restored from: {input_path}", flush=True)
        return 0

    if settings.basic.warmup:
        _warmup_assets()
        print("BabelDOC assets are ready.", flush=True)
        return 0

    if settings.basic.gui:
        from pdf2zh_next.gui import setup_gui

        _warmup_assets()
        try:
            setup_gui(
                auth_file=settings.gui_settings.auth_file,
                welcome_page=settings.gui_settings.welcome_page,
                server_port=settings.gui_settings.server_port,
            )
        except Exception as exc:
            _print_cli_error(
                f"Failed to start GUI: {exc}",
                _build_cli_error_hint(str(exc)),
            )
            return 1
        else:
            return 0

    if not settings.basic.input_files:
        _print_cli_usage_hint()
        return 2

    try:
        (
            settings.basic.input_files,
            expanded_directories,
        ) = _expand_cli_input_files(settings.basic.input_files)
        for directory_path, pdf_count in expanded_directories:
            logger.info(
                "Resolved %s PDF file(s) from directory: %s",
                pdf_count,
                directory_path,
            )
        _validate_cli_input_files(settings.basic.input_files)
        _warmup_assets()
        error_count = await do_translate_file_async(settings, ignore_error=True)
    except Exception as e:
        if settings.basic.debug:
            logger.exception("CLI translation failed")
        else:
            logger.debug("CLI translation failed: %s", e, exc_info=True)
        _print_cli_error(
            str(e),
            _combine_cli_hints(
                _build_cli_error_hint(str(e)),
                "Run `pdf2zh_next --help` for usage details.",
            ),
        )
        return 1

    if error_count:
        _print_cli_error(
            f"Translation finished with {error_count} failed file(s).",
            "Check the logs above for the failing files.",
        )
        return 1
    return 0


def cli():
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()

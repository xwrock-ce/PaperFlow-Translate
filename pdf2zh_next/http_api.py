from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import shutil
import uuid
import warnings
from collections import Counter
from contextlib import asynccontextmanager
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal
from typing import get_args
from typing import get_origin
from urllib.parse import urlparse

import requests
import uvicorn
from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi import UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic import model_validator

from pdf2zh_next.config import ConfigManager
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.model import PDFSettings
from pdf2zh_next.config.model import TranslationSettings
from pdf2zh_next.config.translate_engine_model import GUI_PASSWORD_FIELDS
from pdf2zh_next.config.translate_engine_model import GUI_SENSITIVE_FIELDS
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA_MAP
from pdf2zh_next.const import DEFAULT_CONFIG_FILE
from pdf2zh_next.const import __version__
from pdf2zh_next.high_level import do_translate_async_stream
from pdf2zh_next.high_level import validate_pdf_file
from pdf2zh_next.web_localization import build_translation_language_options
from pdf2zh_next.web_localization import field_options
from pdf2zh_next.web_localization import localize_field_description
from pdf2zh_next.web_localization import localize_field_label
from pdf2zh_next.web_localization import normalize_ui_locale
from pdf2zh_next.web_schema import build_ui_schema
from pdf2zh_next.web_schema import drop_empty_sensitive_values

logger = logging.getLogger(__name__)

_HTTP_OUTPUT_ROOT = Path("pdf2zh_files") / "http_api"
_ARTIFACT_MANIFEST_NAME = "artifacts.json"
_SOURCE_ARTIFACT_NAME = "source"
_SOURCE_FILE_NAME = "source.pdf"
TERM_SERVICE_FOLLOW_MAIN = "Follow main translation engine"
_NON_FATAL_BABELDOC_FONT_XOBJ_PATTERN = re.compile(
    r"failed to parse font xobj id .*FT_Exception:.*invalid argument",
    re.IGNORECASE,
)
_SKLEARN_PARALLEL_WARNING_PATTERN = (
    r".*`sklearn\.utils\.parallel\.delayed` should be used with "
    r"`sklearn\.utils\.parallel\.Parallel`.*"
)
_RUNTIME_NOISE_FILTERS_CONFIGURED = False


class APIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        hint: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details


class EngineInfo(BaseModel):
    name: str
    flag: str
    support_llm: bool
    description: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    default_config_file: str
    running_jobs: int
    queued_jobs: int
    max_concurrent_jobs: int
    max_queue_size: int
    job_retention_minutes: int


class TranslationArtifact(BaseModel):
    name: str
    filename: str
    url: str
    preview_url: str | None = None
    size_bytes: int | None = None


class TranslateRequest(BaseModel):
    input_file: str | None = Field(
        default=None,
        description="Existing local PDF path on the server.",
    )
    file_url: str | None = Field(
        default=None,
        description="Direct http:// or https:// URL to a PDF file.",
    )
    service: str | None = Field(
        default=None,
        description="Translation service name, such as OpenAI or SiliconFlowFree.",
    )
    lang_in: str = Field(default="en", description="Source language code.")
    lang_out: str = Field(default="zh", description="Target language code.")
    output_dir: str | None = Field(
        default=None,
        description="Optional output directory for generated files.",
    )
    pages: str | None = Field(
        default=None,
        description="Optional page range, for example 1,3,5-7.",
    )
    no_mono: bool = Field(default=False)
    no_dual: bool = Field(default=False)
    ignore_cache: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_source(self) -> TranslateRequest:
        if bool(self.input_file) == bool(self.file_url):
            raise ValueError("Provide exactly one of `input_file` or `file_url`.")
        return self


class BrowserTranslateRequest(BaseModel):
    service: str | None = None
    lang_in: str = "en"
    lang_out: str = "zh"
    translation: dict[str, Any] = Field(default_factory=dict)
    pdf: dict[str, Any] = Field(default_factory=dict)
    engine_settings: dict[str, Any] = Field(default_factory=dict)
    seat_id: str | None = None
    lease_token: str | None = None


class WebTranslatePayload(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    source_type: str = Field(default="file", description="Either `file` or `link`.")
    file_url: str | None = Field(default=None)
    persist_settings: bool = Field(default=False)
    seat_id: str | None = None
    lease_token: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> WebTranslatePayload:
        if self.source_type not in {"file", "link"}:
            raise ValueError("`source_type` must be either `file` or `link`.")
        if self.source_type == "link" and not self.file_url:
            raise ValueError("Provide `file_url` when `source_type` is `link`.")
        return self


class WebConfigPayload(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class WebUIError(ValueError):
    """Validation error for the browser-facing WebUI payload."""


class WebUISettings(BaseModel):
    source_kind: Literal["upload", "url"] = "upload"
    file_url: str = ""
    service: str = "SiliconFlowFree"
    lang_in: str = "en"
    lang_out: str = "zh"
    page_mode: Literal["all", "first", "first5", "range"] = "all"
    page_range_text: str = ""
    only_include_translated_page: bool = False
    no_mono: bool = False
    no_dual: bool = False
    dual_translate_first: bool = False
    use_alternating_pages_dual: bool = False
    watermark_output_mode: Literal["watermarked", "no_watermark", "both"] = (
        "watermarked"
    )
    rate_limit_mode: Literal["RPM", "Concurrent Threads", "Custom"] = "Custom"
    rpm: int = 240
    concurrent_threads: int = 20
    qps: int = 4
    pool_max_workers: int | None = None
    min_text_length: int = 5
    custom_system_prompt: str = ""
    save_auto_extracted_glossary: bool = False
    enable_auto_term_extraction: bool = True
    primary_font_family: Literal["Auto", "serif", "sans-serif", "script"] = "Auto"
    skip_clean: bool = False
    disable_rich_text_translate: bool = False
    enhance_compatibility: bool = False
    split_short_lines: bool = False
    short_line_split_factor: float = 0.8
    translate_table_text: bool = True
    skip_scanned_detection: bool = False
    ignore_cache: bool = False
    ocr_workaround: bool = False
    auto_enable_ocr_workaround: bool = False
    max_pages_per_part: int | None = None
    formular_font_pattern: str = ""
    formular_char_pattern: str = ""
    merge_alternating_line_numbers: bool = True
    remove_non_formula_lines: bool = True
    non_formula_line_iou_threshold: float = 0.9
    figure_table_protection_threshold: float = 0.9
    skip_formula_offset_calculation: bool = False
    term_service: str = TERM_SERVICE_FOLLOW_MAIN
    term_rate_limit_mode: Literal["RPM", "Concurrent Threads", "Custom"] = "Custom"
    term_rpm: int = 240
    term_concurrent_threads: int = 20
    term_qps: int = 4
    term_pool_max_workers: int | None = None
    service_config: dict[str, Any] = Field(default_factory=dict)
    term_service_config: dict[str, Any] = Field(default_factory=dict)


class TranslateResponse(BaseModel):
    status: str
    request_id: str
    service: str
    input_file: str
    output_dir: str
    mono_pdf_path: str | None = None
    dual_pdf_path: str | None = None
    glossary_path: str | None = None
    mono_download_url: str | None = None
    dual_download_url: str | None = None
    glossary_download_url: str | None = None
    preview_url: str | None = None
    total_seconds: float | None = None
    token_usage: dict[str, Any] | None = None
    artifacts: dict[str, TranslationArtifact] = Field(default_factory=dict)
    downloads: dict[str, TranslationArtifact] = Field(default_factory=dict)


class HTTPServerSettings(BaseModel):
    max_concurrent_jobs: int = Field(default=4, ge=1)
    max_queue_size: int = Field(default=32, ge=1)
    max_upload_size_mb: int = Field(default=100, ge=1)
    job_retention_minutes: int = Field(default=30, ge=1)
    cleanup_interval_minutes: int = Field(default=5, ge=1)
    metadata_retention_minutes: int = Field(default=24 * 60, ge=1)
    enable_file_url: bool = Field(default=False)
    allow_local_input_file: bool = Field(default=False)
    seat_count: int = Field(default=4, ge=1)
    seat_lease_timeout_seconds: int = Field(default=120, ge=30)
    seat_heartbeat_interval_seconds: int = Field(default=25, ge=5)
    admin_force_release_token: str | None = Field(default=None)


class SeatManagementConfig(BaseModel):
    enabled: bool = True
    seat_count: int
    lease_timeout_seconds: int
    heartbeat_interval_seconds: int
    admin_force_release_enabled: bool


class SeatLoginRequest(BaseModel):
    display_name: str


class SeatLoginResponse(BaseModel):
    display_name: str


class SeatClaimRequest(BaseModel):
    display_name: str


class SeatLeaseRequest(BaseModel):
    lease_token: str


class SeatServiceRequest(BaseModel):
    lease_token: str
    service: str


class SeatForceReleaseRequest(BaseModel):
    admin_token: str


class EngineUsageSummary(BaseModel):
    service: str
    active_seats: int


class SeatSummary(BaseModel):
    seat_id: str
    status: Literal["available", "occupied", "stale"]
    occupant_name: str | None = None
    selected_service: str | None = None
    has_active_job: bool = False
    acquired_at: str | None = None
    last_heartbeat_at: str | None = None
    claimable: bool
    message: str


class SeatListResponse(BaseModel):
    seats: list[SeatSummary]
    engine_usage: list[EngineUsageSummary] = Field(default_factory=list)


class SeatClaimResponse(BaseModel):
    seat: SeatSummary
    lease_token: str
    heartbeat_interval_seconds: int
    lease_timeout_seconds: int


class JobError(BaseModel):
    code: str
    message: str
    hint: str | None = None
    details: Any = None


class JobProgress(BaseModel):
    stage: str | None = None
    overall_progress: float | None = None
    part_index: int | None = None
    total_parts: int | None = None
    stage_current: int | None = None
    stage_total: int | None = None


class JobResponse(BaseModel):
    job_id: str
    request_id: str
    status: str
    service: str
    input_file: str
    output_dir: str
    submitted_at: str
    started_at: str | None = None
    finished_at: str | None = None
    expires_at: str | None = None
    queue_position: int | None = None
    progress: JobProgress | None = None
    error: JobError | None = None
    result: TranslateResponse | None = None
    retention_seconds: int | None = None


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso8601(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _normalize_display_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise APIError(
            status_code=422,
            code="invalid_display_name",
            message="Enter a display name before continuing.",
        )
    if len(normalized) > 64:
        raise APIError(
            status_code=422,
            code="invalid_display_name",
            message="Display names must be 64 characters or fewer.",
        )
    return normalized


@dataclass
class _SeatLease:
    seat_id: str
    occupant_name: str | None = None
    selected_service: str | None = None
    lease_token: str | None = None
    acquired_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    current_job_id: str | None = None
    job_request_id: str | None = None


class SeatManager:
    def __init__(
        self,
        server_settings: HTTPServerSettings,
        job_manager: TranslationJobManager | None = None,
    ) -> None:
        self.server_settings = server_settings
        self.job_manager = job_manager
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self._started = False
        self._seats = {
            str(index): _SeatLease(seat_id=str(index))
            for index in range(1, server_settings.seat_count + 1)
        }

    async def start(self) -> None:
        if self._started:
            return
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(),
            name="seat-cleanup",
        )
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._cleanup_task, timeout=2)
        self._cleanup_task = None
        self._started = False

    def config_payload(self) -> SeatManagementConfig:
        return SeatManagementConfig(
            seat_count=self.server_settings.seat_count,
            lease_timeout_seconds=self.server_settings.seat_lease_timeout_seconds,
            heartbeat_interval_seconds=self.server_settings.seat_heartbeat_interval_seconds,
            admin_force_release_enabled=bool(
                self.server_settings.admin_force_release_token
            ),
        )

    async def login(self, display_name: str) -> SeatLoginResponse:
        return SeatLoginResponse(display_name=_normalize_display_name(display_name))

    async def list_seats(self) -> SeatListResponse:
        now = _utc_now()
        async with self._lock:
            return SeatListResponse(
                seats=[
                    self._seat_summary_unlocked(seat, now=now)
                    for seat in self._iter_seats_unlocked()
                ],
                engine_usage=self._engine_usage_unlocked(now=now),
            )

    async def claim_seat(self, seat_id: str, display_name: str) -> SeatClaimResponse:
        normalized_name = _normalize_display_name(display_name)
        now = _utc_now()
        async with self._lock:
            seat = self._get_seat_unlocked(seat_id)
            if (
                self._seat_is_expired_unlocked(seat, now=now)
                and not seat.current_job_id
            ):
                self._reset_seat_unlocked(seat)
            if self._seat_is_claimed_unlocked(seat):
                if self._seat_is_expired_unlocked(seat, now=now):
                    raise APIError(
                        status_code=409,
                        code="seat_releasing",
                        message=f"Seat {seat_id} is being released after a timeout.",
                        hint="Retry in a few seconds.",
                    )
                raise APIError(
                    status_code=409,
                    code="seat_occupied",
                    message=f"Seat {seat_id} is currently in use.",
                    hint=(
                        f"{seat.occupant_name} is using this seat."
                        if seat.occupant_name
                        else "Another user is using this seat."
                    ),
                )
            for existing in self._iter_seats_unlocked():
                if (
                    existing.seat_id != seat_id
                    and existing.lease_token
                    and existing.occupant_name == normalized_name
                ):
                    raise APIError(
                        status_code=409,
                        code="display_name_already_claimed",
                        message=(
                            f"{normalized_name} is already using seat "
                            f"{existing.seat_id}."
                        ),
                        hint="Release the current seat before claiming another one.",
                    )
            seat.occupant_name = normalized_name
            seat.selected_service = None
            seat.lease_token = uuid.uuid4().hex
            seat.acquired_at = now
            seat.last_heartbeat_at = now
            seat.current_job_id = None
            seat.job_request_id = None
            summary = self._seat_summary_unlocked(seat, now=now)
            lease_token = seat.lease_token
        return SeatClaimResponse(
            seat=summary,
            lease_token=lease_token or "",
            heartbeat_interval_seconds=self.server_settings.seat_heartbeat_interval_seconds,
            lease_timeout_seconds=self.server_settings.seat_lease_timeout_seconds,
        )

    async def heartbeat(self, seat_id: str, lease_token: str) -> SeatClaimResponse:
        now = _utc_now()
        async with self._lock:
            seat = self._require_active_lease_unlocked(seat_id, lease_token, now=now)
            seat.last_heartbeat_at = now
            summary = self._seat_summary_unlocked(seat, now=now)
        return SeatClaimResponse(
            seat=summary,
            lease_token=lease_token,
            heartbeat_interval_seconds=self.server_settings.seat_heartbeat_interval_seconds,
            lease_timeout_seconds=self.server_settings.seat_lease_timeout_seconds,
        )

    async def release_seat(self, seat_id: str, lease_token: str) -> SeatSummary:
        return await self._release_seat(seat_id, lease_token=lease_token)

    async def update_selected_service(
        self,
        seat_id: str,
        lease_token: str,
        service_name: str,
    ) -> SeatSummary:
        metadata = _resolve_service_metadata(service_name)
        async with self._lock:
            seat = self._require_active_lease_unlocked(seat_id, lease_token)
            seat.selected_service = metadata.translate_engine_type
            return self._seat_summary_unlocked(seat)

    async def force_release_seat(
        self,
        seat_id: str,
        admin_token: str,
    ) -> SeatSummary:
        expected_token = self.server_settings.admin_force_release_token
        if not expected_token:
            raise APIError(
                status_code=403,
                code="feature_disabled",
                message="Admin force release is disabled on this server.",
            )
        if admin_token != expected_token:
            raise APIError(
                status_code=403,
                code="invalid_admin_token",
                message="The admin token is invalid.",
            )
        return await self._release_seat(seat_id)

    async def reserve_job(
        self,
        *,
        seat_id: str,
        lease_token: str,
        request_id: str,
        service_name: str,
    ) -> None:
        placeholder = self._pending_job_marker(request_id)
        async with self._lock:
            seat = self._require_active_lease_unlocked(seat_id, lease_token)
            if seat.current_job_id:
                raise APIError(
                    status_code=409,
                    code="seat_job_active",
                    message=f"Seat {seat_id} already has an active translation job.",
                    hint="Wait for the current job to finish or cancel it first.",
                )
            seat.selected_service = service_name
            seat.current_job_id = placeholder
            seat.job_request_id = request_id

    async def bind_job(
        self,
        *,
        seat_id: str,
        lease_token: str,
        request_id: str,
        job_id: str,
    ) -> None:
        placeholder = self._pending_job_marker(request_id)
        async with self._lock:
            seat = self._require_active_lease_unlocked(seat_id, lease_token)
            if seat.current_job_id != placeholder:
                raise APIError(
                    status_code=409,
                    code="seat_job_reservation_missing",
                    message="The seat reservation is no longer valid.",
                    hint="Return to the lobby and claim the seat again.",
                )
            seat.current_job_id = job_id
            seat.job_request_id = request_id

    async def clear_job_reservation(
        self,
        *,
        seat_id: str,
        request_id: str,
        lease_token: str | None = None,
    ) -> None:
        placeholder = self._pending_job_marker(request_id)
        async with self._lock:
            seat = self._seats.get(seat_id)
            if seat is None:
                return
            if lease_token and seat.lease_token != lease_token:
                return
            if seat.current_job_id == placeholder:
                seat.current_job_id = None
                seat.job_request_id = None

    async def clear_job(self, seat_id: str | None, job_id: str) -> None:
        if not seat_id:
            return
        async with self._lock:
            seat = self._seats.get(seat_id)
            if seat is None:
                return
            if seat.current_job_id == job_id:
                seat.current_job_id = None
                seat.job_request_id = None
                if self._seat_is_expired_unlocked(seat):
                    self._reset_seat_unlocked(seat)

    async def cleanup_expired_seats(self) -> None:
        now = _utc_now()
        expired_targets: list[tuple[str, str]] = []
        async with self._lock:
            for seat in self._iter_seats_unlocked():
                if seat.lease_token and self._seat_is_expired_unlocked(seat, now=now):
                    expired_targets.append((seat.seat_id, seat.lease_token))
        for seat_id, lease_token in expired_targets:
            with suppress(APIError):
                await self._release_seat(
                    seat_id,
                    lease_token=lease_token,
                    allow_expired=True,
                )

    async def _release_seat(
        self,
        seat_id: str,
        *,
        lease_token: str | None = None,
        allow_expired: bool = False,
    ) -> SeatSummary:
        current_job_id: str | None = None
        async with self._lock:
            seat = self._get_seat_unlocked(seat_id)
            if lease_token is not None:
                if allow_expired:
                    if not lease_token or seat.lease_token != lease_token:
                        raise APIError(
                            status_code=409,
                            code="seat_lease_invalid",
                            message=(
                                "This seat is no longer assigned to the current "
                                "browser session."
                            ),
                            hint=(
                                "Return to the lobby and claim an available seat again."
                            ),
                        )
                else:
                    seat = self._require_active_lease_unlocked(seat_id, lease_token)
            current_job_id = seat.current_job_id
        if (
            current_job_id
            and not current_job_id.startswith("pending:")
            and self.job_manager is not None
        ):
            with suppress(APIError):
                await self.job_manager.cancel_job(current_job_id)
        async with self._lock:
            seat = self._get_seat_unlocked(seat_id)
            if lease_token is not None and seat.lease_token != lease_token:
                return self._seat_summary_unlocked(seat)
            self._reset_seat_unlocked(seat)
            return self._seat_summary_unlocked(seat)

    async def _cleanup_loop(self) -> None:
        interval = max(5, self.server_settings.seat_heartbeat_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            await self.cleanup_expired_seats()

    def _pending_job_marker(self, request_id: str) -> str:
        return f"pending:{request_id}"

    def _iter_seats_unlocked(self) -> list[_SeatLease]:
        return [self._seats[str(index)] for index in range(1, len(self._seats) + 1)]

    def _get_seat_unlocked(self, seat_id: str) -> _SeatLease:
        seat = self._seats.get(str(seat_id))
        if seat is None:
            raise APIError(
                status_code=404,
                code="seat_not_found",
                message=f"Seat {seat_id} does not exist.",
            )
        return seat

    def _seat_is_claimed_unlocked(self, seat: _SeatLease) -> bool:
        return bool(seat.lease_token)

    def _seat_is_expired_unlocked(
        self,
        seat: _SeatLease,
        *,
        now: datetime | None = None,
    ) -> bool:
        if not seat.lease_token or not seat.last_heartbeat_at:
            return False
        reference = now or _utc_now()
        return (
            reference - seat.last_heartbeat_at
        ).total_seconds() >= self.server_settings.seat_lease_timeout_seconds

    def _require_active_lease_unlocked(
        self,
        seat_id: str,
        lease_token: str,
        *,
        now: datetime | None = None,
    ) -> _SeatLease:
        seat = self._get_seat_unlocked(seat_id)
        if not lease_token or seat.lease_token != lease_token:
            raise APIError(
                status_code=409,
                code="seat_lease_invalid",
                message="This seat is no longer assigned to the current browser session.",
                hint="Return to the lobby and claim an available seat again.",
            )
        if self._seat_is_expired_unlocked(seat, now=now):
            raise APIError(
                status_code=409,
                code="seat_lease_expired",
                message="This seat lease has expired.",
                hint="Return to the lobby and claim an available seat again.",
            )
        return seat

    def _reset_seat_unlocked(self, seat: _SeatLease) -> None:
        seat.occupant_name = None
        seat.selected_service = None
        seat.lease_token = None
        seat.acquired_at = None
        seat.last_heartbeat_at = None
        seat.current_job_id = None
        seat.job_request_id = None

    def _engine_usage_unlocked(
        self,
        *,
        now: datetime | None = None,
    ) -> list[EngineUsageSummary]:
        usage: Counter[str] = Counter()
        for seat in self._iter_seats_unlocked():
            if (
                seat.lease_token
                and seat.selected_service
                and not self._seat_is_expired_unlocked(seat, now=now)
            ):
                usage[seat.selected_service] += 1
        return [
            EngineUsageSummary(service=service, active_seats=active_seats)
            for service, active_seats in sorted(
                usage.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )
        ]

    def _seat_summary_unlocked(
        self,
        seat: _SeatLease,
        *,
        now: datetime | None = None,
    ) -> SeatSummary:
        if not seat.lease_token:
            return SeatSummary(
                seat_id=seat.seat_id,
                status="available",
                selected_service=None,
                claimable=True,
                message="Available",
            )
        if self._seat_is_expired_unlocked(seat, now=now):
            return SeatSummary(
                seat_id=seat.seat_id,
                status="stale",
                occupant_name=seat.occupant_name,
                selected_service=seat.selected_service,
                has_active_job=bool(seat.current_job_id),
                acquired_at=_dt_to_iso8601(seat.acquired_at),
                last_heartbeat_at=_dt_to_iso8601(seat.last_heartbeat_at),
                claimable=False,
                message="Releasing after timeout",
            )
        return SeatSummary(
            seat_id=seat.seat_id,
            status="occupied",
            occupant_name=seat.occupant_name,
            selected_service=seat.selected_service,
            has_active_job=bool(seat.current_job_id),
            acquired_at=_dt_to_iso8601(seat.acquired_at),
            last_heartbeat_at=_dt_to_iso8601(seat.last_heartbeat_at),
            claimable=False,
            message=(
                f"In use by {seat.occupant_name}" if seat.occupant_name else "In use"
            ),
        )


class _NonFatalBabeldocNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.levelno >= logging.ERROR
            and record.name == "babeldoc.format.pdf.document_il.frontend.il_creater"
            and _NON_FATAL_BABELDOC_FONT_XOBJ_PATTERN.search(record.getMessage())
        ):
            record.levelno = logging.WARNING
            record.levelname = logging.getLevelName(logging.WARNING)
        return True


def _configure_runtime_noise_filters() -> None:
    global _RUNTIME_NOISE_FILTERS_CONFIGURED

    if _RUNTIME_NOISE_FILTERS_CONFIGURED:
        return

    warnings.filterwarnings(
        "ignore",
        message=_SKLEARN_PARALLEL_WARNING_PATTERN,
        category=UserWarning,
        module=r"sklearn\.utils\.parallel",
    )

    babeldoc_logger = logging.getLogger(
        "babeldoc.format.pdf.document_il.frontend.il_creater"
    )
    if not any(
        isinstance(existing_filter, _NonFatalBabeldocNoiseFilter)
        for existing_filter in babeldoc_logger.filters
    ):
        babeldoc_logger.addFilter(_NonFatalBabeldocNoiseFilter())

    _RUNTIME_NOISE_FILTERS_CONFIGURED = True


def _service_supports_llm(service_name: str | None) -> bool:
    metadata = TRANSLATION_ENGINE_METADATA_MAP.get(service_name or "")
    return bool(metadata and metadata.support_llm)


def _disable_auto_term_extraction_for_non_llm(settings: Any) -> bool:
    service_name = settings.translate_engine_settings.translate_engine_type
    if _service_supports_llm(service_name):
        return False

    settings.term_extraction_engine_settings = None
    if settings.translation.no_auto_extract_glossary:
        return False

    settings.translation.no_auto_extract_glossary = True
    logger.info(
        "Automatic term extraction disabled for service=%s because it does not support LLM.",
        service_name,
    )
    return True


@dataclass
class _TranslationJob:
    job_id: str
    request_id: str
    service: str
    input_file: str
    output_dir: str
    file_path: Path
    settings: Any
    seat_id: str | None = None
    status: str = "queued"
    submitted_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    result: TranslateResponse | None = None
    cancel_requested: bool = False
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    execution_task: asyncio.Task | None = None
    subscribers: set[asyncio.Queue] = field(default_factory=set)


class TranslationJobManager:
    def __init__(self, server_settings: HTTPServerSettings) -> None:
        self.server_settings = server_settings
        self.seat_manager: SeatManager | None = None
        self._jobs: dict[str, _TranslationJob] = {}
        self._request_to_job_id: dict[str, str] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._queued_job_ids: list[str] = []
        self._lock = asyncio.Lock()
        self._workers: list[asyncio.Task] = []
        self._cleanup_task: asyncio.Task | None = None
        self._started = False
        self._metrics = {
            "submitted": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
            "expired": 0,
        }

    async def start(self) -> None:
        if self._started:
            return
        _HTTP_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        self._workers = [
            asyncio.create_task(
                self._worker_loop(index), name=f"translation-worker-{index}"
            )
            for index in range(self.server_settings.max_concurrent_jobs)
        ]
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(),
            name="translation-cleanup",
        )
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
        for job in list(self._jobs.values()):
            if job.execution_task and not job.execution_task.done():
                job.cancel_requested = True
                job.execution_task.cancel()
        for worker in self._workers:
            worker.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        for task in [*self._workers, self._cleanup_task]:
            if task is None:
                continue
            with suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(task, timeout=2)
        self._workers.clear()
        self._cleanup_task = None
        self._started = False

    async def submit_job(
        self,
        *,
        request_id: str,
        service: str,
        file_path: Path,
        output_dir: Path,
        settings: Any,
        seat_id: str | None = None,
    ) -> _TranslationJob:
        async with self._lock:
            if len(self._queued_job_ids) >= self.server_settings.max_queue_size:
                raise APIError(
                    status_code=429,
                    code="queue_full",
                    message="The translation queue is full.",
                    hint="Please retry after some jobs finish.",
                )
            job = _TranslationJob(
                job_id=str(uuid.uuid4()),
                request_id=request_id,
                service=service,
                input_file=str(file_path),
                output_dir=str(output_dir),
                file_path=file_path,
                settings=settings,
                seat_id=seat_id,
            )
            self._jobs[job.job_id] = job
            self._request_to_job_id[job.request_id] = job.job_id
            self._queued_job_ids.append(job.job_id)
            self._metrics["submitted"] += 1
        await self._queue.put(job.job_id)
        await self._publish(job, self._event_payload(job, "queued"))
        return job

    async def wait_for_completion(self, job_id: str) -> _TranslationJob:
        job = await self.get_job(job_id)
        await job.done_event.wait()
        return job

    async def get_job(self, job_id: str) -> _TranslationJob:
        async with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise APIError(
                status_code=404,
                code="job_not_found",
                message="The requested job does not exist.",
            )
        return job

    async def get_job_by_request_id(self, request_id: str) -> _TranslationJob | None:
        async with self._lock:
            job_id = self._request_to_job_id.get(request_id)
            return self._jobs.get(job_id) if job_id else None

    async def list_jobs(self, *, limit: int = 50) -> list[_TranslationJob]:
        async with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item.submitted_at,
                reverse=True,
            )
        return jobs[:limit]

    async def cancel_job(self, job_id: str) -> _TranslationJob:
        job = await self.get_job(job_id)
        async with self._lock:
            if job.status == "queued":
                job.cancel_requested = True
                job.status = "cancelled"
                job.finished_at = _utc_now()
                job.expires_at = job.finished_at + timedelta(
                    minutes=self.server_settings.job_retention_minutes
                )
                if job.job_id in self._queued_job_ids:
                    self._queued_job_ids.remove(job.job_id)
                self._metrics["cancelled"] += 1
                job.done_event.set()
                event = self._event_payload(job, "cancelled")
            elif job.status == "running" and job.execution_task:
                job.cancel_requested = True
                job.execution_task.cancel()
                event = None
            else:
                event = None
        if event:
            await self._publish(job, event)
            await self._clear_job_seat(job)
        return job

    async def subscribe(self, job_id: str) -> tuple[_TranslationJob, asyncio.Queue]:
        job = await self.get_job(job_id)
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            job.subscribers.add(queue)
        await queue.put(self._event_payload(job, "snapshot"))
        return job, queue

    async def unsubscribe(self, job: _TranslationJob, queue: asyncio.Queue) -> None:
        async with self._lock:
            job.subscribers.discard(queue)

    async def build_job_response(self, job_id: str) -> JobResponse:
        job = await self.get_job(job_id)
        return self._job_response(job)

    def health_payload(self) -> dict[str, int]:
        running_jobs = sum(1 for job in self._jobs.values() if job.status == "running")
        queued_jobs = len(self._queued_job_ids)
        return {
            "running_jobs": running_jobs,
            "queued_jobs": queued_jobs,
            "max_concurrent_jobs": self.server_settings.max_concurrent_jobs,
            "max_queue_size": self.server_settings.max_queue_size,
            "job_retention_minutes": self.server_settings.job_retention_minutes,
        }

    def metrics_payload(self) -> dict[str, Any]:
        return {
            **self._metrics,
            **self.health_payload(),
        }

    async def _clear_job_seat(self, job: _TranslationJob) -> None:
        if self.seat_manager is None or not job.seat_id:
            return
        await self.seat_manager.clear_job(job.seat_id, job.job_id)

    async def cleanup_expired_jobs(self) -> None:
        now = _utc_now()
        expiration_targets: list[_TranslationJob] = []
        purge_targets: list[str] = []
        active_request_ids: set[str] = set()
        async with self._lock:
            for job in self._jobs.values():
                if job.status in {"queued", "running"}:
                    active_request_ids.add(job.request_id)
                    continue
                if (
                    job.expires_at
                    and now >= job.expires_at
                    and job.status in {"succeeded", "failed", "cancelled"}
                ):
                    expiration_targets.append(job)
                if job.finished_at and now >= job.finished_at + timedelta(
                    minutes=self.server_settings.metadata_retention_minutes
                ):
                    purge_targets.append(job.job_id)
        for job in expiration_targets:
            await self._expire_job(job)
        for orphan_dir in _HTTP_OUTPUT_ROOT.glob("*"):
            if not orphan_dir.is_dir():
                continue
            if orphan_dir.name in active_request_ids:
                continue
            try:
                modified_at = datetime.fromtimestamp(
                    orphan_dir.stat().st_mtime,
                    tz=timezone.utc,
                )
            except OSError:
                continue
            if now >= modified_at + timedelta(
                minutes=self.server_settings.job_retention_minutes
            ):
                shutil.rmtree(orphan_dir, ignore_errors=True)
        async with self._lock:
            for job_id in purge_targets:
                job = self._jobs.pop(job_id, None)
                if job is None:
                    continue
                self._request_to_job_id.pop(job.request_id, None)
                if job.job_id in self._queued_job_ids:
                    self._queued_job_ids.remove(job.job_id)

    async def _expire_job(self, job: _TranslationJob) -> None:
        output_dir = Path(job.output_dir)
        shutil.rmtree(output_dir, ignore_errors=True)
        async with self._lock:
            if job.status == "expired":
                return
            job.status = "expired"
            job.result = None
            self._metrics["expired"] += 1
        await self._publish(job, self._event_payload(job, "expired"))

    async def _cleanup_loop(self) -> None:
        interval = self.server_settings.cleanup_interval_minutes * 60
        while True:
            await asyncio.sleep(interval)
            await self.cleanup_expired_jobs()

    async def _worker_loop(self, _index: int) -> None:
        while True:
            try:
                job_id = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                job = await self.get_job(job_id)
            except APIError:
                self._queue.task_done()
                continue
            try:
                async with self._lock:
                    if job.status == "cancelled":
                        continue
                    if job.job_id in self._queued_job_ids:
                        self._queued_job_ids.remove(job.job_id)
                execution_task = asyncio.create_task(self._execute_job(job))
                job.execution_task = execution_task
                try:
                    await execution_task
                except asyncio.CancelledError:
                    if not execution_task.done():
                        execution_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await execution_task
                    raise
            finally:
                job.execution_task = None
                self._queue.task_done()

    async def _execute_job(self, job: _TranslationJob) -> None:
        started_at = _utc_now()
        async with self._lock:
            if job.cancel_requested and job.status == "cancelled":
                return
            job.status = "running"
            job.started_at = started_at
        await self._publish(job, self._event_payload(job, "running"))
        try:
            async for event in do_translate_async_stream(
                job.settings,
                job.file_path,
                raise_on_error=False,
            ):
                event_type = event.get("type")
                if event_type in {"progress_start", "progress_update", "progress_end"}:
                    async with self._lock:
                        job.progress = {
                            "stage": event.get("stage"),
                            "overall_progress": event.get("overall_progress"),
                            "part_index": event.get("part_index"),
                            "total_parts": event.get("total_parts"),
                            "stage_current": event.get("stage_current"),
                            "stage_total": event.get("stage_total"),
                        }
                    await self._publish(job, self._event_payload(job, "progress"))
                    continue
                if event_type == "error":
                    error_message = str(event.get("error", "Translation failed."))
                    async with self._lock:
                        job.status = "failed"
                        job.error = {
                            "code": "translation_failed",
                            "message": error_message,
                            "hint": _build_translation_hint(error_message),
                            "details": event.get("details"),
                        }
                        job.finished_at = _utc_now()
                        job.expires_at = job.finished_at + timedelta(
                            minutes=self.server_settings.job_retention_minutes
                        )
                        self._metrics["failed"] += 1
                        job.done_event.set()
                    await self._publish(job, self._event_payload(job, "error"))
                    await self._clear_job_seat(job)
                    return
                if event_type == "finish":
                    response = _build_translate_response(
                        settings=job.settings,
                        file_path=job.file_path,
                        request_id=job.request_id,
                        output_dir=Path(job.output_dir),
                        result=event["translate_result"],
                        token_usage=event.get("token_usage", {}),
                    )
                    async with self._lock:
                        job.status = "succeeded"
                        job.result = response
                        job.finished_at = _utc_now()
                        job.expires_at = job.finished_at + timedelta(
                            minutes=self.server_settings.job_retention_minutes
                        )
                        self._metrics["succeeded"] += 1
                        job.done_event.set()
                    await self._publish(job, self._event_payload(job, "finish"))
                    await self._clear_job_seat(job)
                    return
            async with self._lock:
                job.status = "failed"
                job.error = {
                    "code": "missing_translation_result",
                    "message": "The translation finished without a result payload.",
                }
                job.finished_at = _utc_now()
                job.expires_at = job.finished_at + timedelta(
                    minutes=self.server_settings.job_retention_minutes
                )
                self._metrics["failed"] += 1
                job.done_event.set()
            await self._publish(job, self._event_payload(job, "error"))
            await self._clear_job_seat(job)
        except asyncio.CancelledError:
            async with self._lock:
                job.status = "cancelled"
                job.finished_at = _utc_now()
                job.expires_at = job.finished_at + timedelta(
                    minutes=self.server_settings.job_retention_minutes
                )
                self._metrics["cancelled"] += 1
                job.done_event.set()
            await self._publish(job, self._event_payload(job, "cancelled"))
            await self._clear_job_seat(job)
        except Exception as exc:
            logger.exception("Job %s failed unexpectedly: %s", job.job_id, exc)
            async with self._lock:
                job.status = "failed"
                job.error = {
                    "code": "internal_error",
                    "message": "The server hit an unexpected error while processing the job.",
                    "details": str(exc),
                }
                job.finished_at = _utc_now()
                job.expires_at = job.finished_at + timedelta(
                    minutes=self.server_settings.job_retention_minutes
                )
                self._metrics["failed"] += 1
                job.done_event.set()
            await self._publish(job, self._event_payload(job, "error"))
            await self._clear_job_seat(job)

    async def _publish(self, job: _TranslationJob, event: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(job.subscribers)
        for subscriber in subscribers:
            subscriber.put_nowait(event)

    def _event_payload(self, job: _TranslationJob, event_type: str) -> dict[str, Any]:
        payload = {
            "type": event_type,
            "job": self._job_response(job).model_dump(mode="json"),
        }
        if event_type == "progress" and job.progress:
            payload.update(job.progress)
        if event_type == "finish" and job.result:
            payload["result"] = job.result.model_dump(mode="json")
        if event_type == "error" and job.error:
            payload["error"] = job.error
        return payload

    def _job_response(self, job: _TranslationJob) -> JobResponse:
        queue_position = None
        if job.status == "queued" and job.job_id in self._queued_job_ids:
            queue_position = self._queued_job_ids.index(job.job_id) + 1
        retention_seconds = None
        if job.expires_at:
            retention_seconds = max(
                0,
                int((job.expires_at - _utc_now()).total_seconds()),
            )
        progress = JobProgress(**job.progress) if job.progress else None
        error = JobError(**job.error) if job.error else None
        return JobResponse(
            job_id=job.job_id,
            request_id=job.request_id,
            status=job.status,
            service=job.service,
            input_file=job.input_file,
            output_dir=job.output_dir,
            submitted_at=_dt_to_iso8601(job.submitted_at) or "",
            started_at=_dt_to_iso8601(job.started_at),
            finished_at=_dt_to_iso8601(job.finished_at),
            expires_at=_dt_to_iso8601(job.expires_at),
            queue_position=queue_position,
            progress=progress,
            error=error,
            result=job.result,
            retention_seconds=retention_seconds,
        )


def _error_payload(
    *,
    code: str,
    message: str,
    hint: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if hint:
        payload["error"]["hint"] = hint
    if details not in (None, "", [], {}):
        payload["error"]["details"] = details
    return payload


def _api_root_payload() -> dict[str, Any]:
    return {
        "name": "PDFMathTranslate Next HTTP API",
        "version": __version__,
        "docs": "/docs",
        "healthz": "/healthz",
        "engines": "/engines",
        "translate": "/translate",
        "app": "/app",
        "app_config": "/app/config",
        "seats": "/seats",
        "ui_config": "/api/ui-config",
        "save_config": "/api/config",
        "upload_translate": "/translate/file",
        "stream_translate": "/api/translate/stream",
    }


def _build_request_validation_hint() -> str:
    return "Provide exactly one of `input_file` or `file_url`, then retry."


def _build_settings_hint(message: str) -> str | None:
    searchable_message = message.lower()
    if "api key" in searchable_message or "credential" in searchable_message:
        return (
            "Configure the selected engine in the default config file or via "
            "`PDF2ZH_*` environment variables, then retry."
        )
    if "error parsing pages parameter" in searchable_message:
        return "Use `pages` like `1,3,5-7`."
    if "cannot disable both dual and mono" in searchable_message:
        return (
            "Leave at least one output enabled by keeping `no_mono` or `no_dual` false."
        )
    if "file does not exist" in searchable_message:
        return "Pass an existing PDF path in `input_file`."
    return None


def _build_translation_hint(message: str) -> str | None:
    searchable_message = message.lower()
    if any(token in searchable_message for token in ("api key", "credential", "auth")):
        return "Check the configured translation engine credentials, then retry the request."
    if any(
        token in searchable_message
        for token in ("timeout", "timed out", "connection reset", "network")
    ):
        return (
            "The translation service did not respond in time. Check the network "
            "connection or lower the rate limit."
        )
    if "not a valid pdf" in searchable_message:
        return "Use a readable PDF file or a direct PDF download URL."
    return None


def _load_base_cli_settings() -> CLIEnvSettingsModel:
    config_manager = ConfigManager()
    default_config = config_manager._read_toml_file(DEFAULT_CONFIG_FILE)
    if default_config and not config_manager.test_config(default_config):
        logger.warning("Ignoring invalid default config file: %s", DEFAULT_CONFIG_FILE)
        default_config = {}

    env_settings = config_manager.parse_env_vars()
    merged_settings = config_manager.merge_settings([env_settings, default_config])
    if not merged_settings:
        return CLIEnvSettingsModel()
    return config_manager._build_model_from_args(CLIEnvSettingsModel, merged_settings)


def _build_full_cli_settings(settings_payload: dict[str, Any]) -> CLIEnvSettingsModel:
    config_manager = ConfigManager()
    base_settings = _load_base_cli_settings().model_dump(mode="json")
    cleaned_payload = drop_empty_sensitive_values(settings_payload)
    merged_settings = config_manager.merge_settings([cleaned_payload, base_settings])
    try:
        return config_manager._build_model_from_args(
            CLIEnvSettingsModel, merged_settings
        )
    except ValidationError as exc:
        raise APIError(
            status_code=422,
            code="invalid_translation_settings",
            message="The submitted settings are invalid.",
            details=exc.errors(),
        ) from exc


def _resolve_service_metadata(service_name: str):
    normalized_name = service_name.strip().lower()
    for metadata in TRANSLATION_ENGINE_METADATA:
        if normalized_name in {
            metadata.translate_engine_type.lower(),
            metadata.cli_flag_name.lower(),
        }:
            return metadata

    available_services = ", ".join(
        metadata.translate_engine_type for metadata in TRANSLATION_ENGINE_METADATA
    )
    raise APIError(
        status_code=400,
        code="invalid_service",
        message=f"Unsupported translation service: {service_name}",
        hint=f"Use one of: {available_services}",
    )


def _prepare_request_output_dir(
    request_id: str,
    requested_output_dir: str | None,
) -> Path:
    if requested_output_dir:
        raise APIError(
            status_code=400,
            code="feature_disabled",
            message="Custom output directories are disabled on the HTTP service.",
        )
    output_dir = _HTTP_OUTPUT_ROOT / request_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _normalize_output_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    return Path(path).as_posix()


def _download_pdf_from_url(
    file_url: str,
    output_dir: Path,
    server_settings: HTTPServerSettings,
) -> Path:
    if not server_settings.enable_file_url:
        raise APIError(
            status_code=400,
            code="feature_disabled",
            message="Remote PDF URLs are disabled on this server.",
        )
    normalized_url = file_url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise APIError(
            status_code=400,
            code="invalid_file_url",
            message="`file_url` must be a direct http:// or https:// PDF link.",
        )

    file_path = output_dir / _SOURCE_FILE_NAME
    pdf_header = b""
    total_bytes = 0
    max_bytes = server_settings.max_upload_size_mb * 1024 * 1024

    try:
        with requests.get(normalized_url, stream=True, timeout=15) as response:
            response.raise_for_status()
            with file_path.open("wb") as output_file:
                for chunk in response.iter_content(chunk_size=1024):
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise APIError(
                            status_code=413,
                            code="payload_too_large",
                            message="The downloaded PDF exceeds the server upload limit.",
                        )
                    if len(pdf_header) < 5:
                        missing = 5 - len(pdf_header)
                        pdf_header += chunk[:missing]
                    output_file.write(chunk)
    except APIError:
        file_path.unlink(missing_ok=True)
        raise
    except requests.RequestException as exc:
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=502,
            code="file_download_failed",
            message=f"Could not download the PDF from {normalized_url}.",
            hint="Check that `file_url` is reachable and points directly to a PDF file.",
            details=str(exc),
        ) from exc

    if pdf_header != b"%PDF-":
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_pdf_download",
            message="The downloaded file is not a valid PDF document.",
            hint="Use a direct PDF download URL in `file_url`.",
        )

    try:
        return validate_pdf_file(file_path)
    except (FileNotFoundError, ValueError) as exc:
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_pdf_download",
            message=str(exc),
            hint="Use a direct PDF download URL in `file_url`.",
        ) from exc


async def _save_uploaded_pdf(
    upload: UploadFile,
    output_dir: Path,
    server_settings: HTTPServerSettings,
) -> Path:
    if not upload.filename or not upload.filename.lower().endswith(".pdf"):
        raise APIError(
            status_code=400,
            code="invalid_upload",
            message="Upload a PDF file with a `.pdf` extension.",
        )

    file_path = output_dir / _SOURCE_FILE_NAME
    pdf_header = b""
    total_bytes = 0
    max_bytes = server_settings.max_upload_size_mb * 1024 * 1024

    try:
        with file_path.open("wb") as output_file:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise APIError(
                        status_code=413,
                        code="payload_too_large",
                        message="The uploaded PDF exceeds the server upload limit.",
                    )
                if len(pdf_header) < 5:
                    missing = 5 - len(pdf_header)
                    pdf_header += chunk[:missing]
                output_file.write(chunk)
    finally:
        await upload.close()

    if pdf_header != b"%PDF-":
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_upload",
            message="The uploaded file is not a valid PDF document.",
        )

    try:
        return validate_pdf_file(file_path)
    except (FileNotFoundError, ValueError) as exc:
        file_path.unlink(missing_ok=True)
        raise APIError(
            status_code=400,
            code="invalid_upload",
            message=str(exc),
        ) from exc


def _prepare_request_source(
    request: TranslateRequest,
    output_dir: Path,
    server_settings: HTTPServerSettings,
) -> Path:
    if request.input_file:
        if not server_settings.allow_local_input_file:
            raise APIError(
                status_code=400,
                code="feature_disabled",
                message="Local server file paths are disabled on this server.",
            )
        input_path = Path(request.input_file).expanduser()
        try:
            return validate_pdf_file(input_path)
        except FileNotFoundError as exc:
            raise APIError(
                status_code=400,
                code="input_file_not_found",
                message=str(exc),
                hint="Pass an existing PDF path in `input_file`.",
            ) from exc
        except ValueError as exc:
            raise APIError(
                status_code=400,
                code="invalid_input_file",
                message=str(exc),
                hint="Pass a readable PDF path in `input_file`.",
            ) from exc

    return _download_pdf_from_url(request.file_url or "", output_dir, server_settings)


def _field_type_name(annotation: Any) -> tuple[str, list[dict[str, Any]] | None]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    non_none_args = [arg for arg in args if arg is not type(None)]

    if origin is None:
        if annotation is bool:
            return "boolean", None
        if annotation is int:
            return "integer", None
        if annotation is float:
            return "number", None
        return "string", None

    if origin is Literal:
        return "select", [
            {"label": {"en": str(arg), "zh": str(arg)}, "value": str(arg)}
            for arg in non_none_args
        ]

    if origin in {list, dict, tuple, set}:
        return "string", None
    for arg in non_none_args:
        if get_origin(arg) is Literal:
            literal_values = [item for item in get_args(arg) if item is not type(None)]
            return "select", [
                {"label": {"en": str(item), "zh": str(item)}, "value": str(item)}
                for item in literal_values
            ]
    if bool in non_none_args:
        return "boolean", None
    if int in non_none_args:
        return "integer", None
    if float in non_none_args:
        return "number", None
    return "string", None


def _serialize_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _build_field_schema(model_type: type[BaseModel], field_name: str) -> dict[str, Any]:
    model_field = model_type.model_fields[field_name]
    field_type, choices = _field_type_name(model_field.annotation)
    localized_choices = field_options(field_name)
    if localized_choices:
        field_type = "select"
    if field_type == "select" and not localized_choices:
        raise ValueError(f"Missing localized WebUI choices for field `{field_name}`.")
    localized_choices = localized_choices or choices or []
    default_value = None
    if model_field.default_factory is not None:
        default_value = _serialize_default(model_field.default_factory())
    elif model_field.default is not None:
        default_value = _serialize_default(model_field.default)
    return {
        "name": field_name,
        "label": localize_field_label(field_name),
        "description": localize_field_description(field_name),
        "type": field_type,
        "required": model_field.is_required(),
        "default": default_value,
        "password": field_name in GUI_PASSWORD_FIELDS,
        "sensitive": field_name in GUI_SENSITIVE_FIELDS,
        "choices": localized_choices,
    }


def _build_model_schema(
    model_type: type[BaseModel],
    *,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_fields = exclude or set()
    return [
        _build_field_schema(model_type, field_name)
        for field_name in model_type.model_fields
        if field_name not in excluded_fields
    ]


def _build_app_config(
    server_settings: HTTPServerSettings | None = None,
) -> dict[str, Any]:
    cli_settings = _load_base_cli_settings()
    server_settings = server_settings or HTTPServerSettings()
    services = []
    for metadata in TRANSLATION_ENGINE_METADATA:
        services.append(
            {
                "name": metadata.translate_engine_type,
                "flag": metadata.cli_flag_name,
                "support_llm": metadata.support_llm,
                "description": metadata.setting_model_type.__doc__,
                "fields": _build_model_schema(
                    metadata.setting_model_type,
                    exclude={"translate_engine_type", "support_llm"},
                ),
            }
        )
    return {
        "name": "PaperFlow Translate",
        "version": __version__,
        "default_service": "SiliconFlowFree",
        "default_locale": normalize_ui_locale(cli_settings.gui_settings.ui_lang),
        "seat_management": SeatManagementConfig(
            seat_count=server_settings.seat_count,
            lease_timeout_seconds=server_settings.seat_lease_timeout_seconds,
            heartbeat_interval_seconds=server_settings.seat_heartbeat_interval_seconds,
            admin_force_release_enabled=bool(server_settings.admin_force_release_token),
        ).model_dump(mode="json"),
        "services": services,
        "translation_languages": build_translation_language_options(),
        "translation_fields": _build_model_schema(
            TranslationSettings,
            exclude={"lang_in", "lang_out", "output", "glossaries"},
        ),
        "pdf_fields": _build_model_schema(PDFSettings),
    }


def _annotation_to_service_field(
    *,
    name: str,
    description: str | None,
    annotation: Any,
    default: Any,
    secret: bool,
) -> dict[str, Any]:
    args = getattr(annotation, "__args__", ())
    if annotation is bool or bool in args:
        return {
            "name": name,
            "label": description or name,
            "control": "checkbox",
            "required": False,
            "secret": secret,
            "value_type": "boolean",
            "default": bool(default) if default is not None else False,
        }
    if annotation is int or int in args:
        return {
            "name": name,
            "label": description or name,
            "control": "number",
            "required": default is None,
            "secret": secret,
            "value_type": "integer",
            "default": default,
        }
    if annotation is float or float in args:
        return {
            "name": name,
            "label": description or name,
            "control": "number",
            "required": default is None,
            "secret": secret,
            "value_type": "number",
            "default": default,
        }
    return {
        "name": name,
        "label": description or name,
        "control": "password" if secret else "text",
        "required": default is None,
        "secret": secret,
        "value_type": "string",
        "default": default,
    }


def _build_bootstrap_services(
    _cli_settings: CLIEnvSettingsModel,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    services: list[dict[str, Any]] = []
    term_services: list[dict[str, Any]] = []
    for metadata in TRANSLATION_ENGINE_METADATA:
        fields = []
        for field_name, model_field in metadata.setting_model_type.model_fields.items():
            if field_name in {"translate_engine_type", "support_llm"}:
                continue
            fields.append(
                _annotation_to_service_field(
                    name=field_name,
                    description=model_field.description,
                    annotation=model_field.annotation,
                    default=model_field.default,
                    secret=field_name in GUI_PASSWORD_FIELDS,
                )
            )
        service = {
            "name": metadata.translate_engine_type,
            "support_llm": metadata.support_llm,
            "fields": fields,
        }
        services.append(service)
        if metadata.support_llm:
            term_services.append(service)
    return services, term_services


def _selected_service(cli_settings: CLIEnvSettingsModel) -> str:
    for metadata in TRANSLATION_ENGINE_METADATA:
        if getattr(cli_settings, metadata.cli_flag_name, False):
            return metadata.translate_engine_type
    return "SiliconFlowFree"


def _page_mode_from_pages(pages: str | None) -> tuple[str, str]:
    normalized = str(pages or "").strip()
    if not normalized:
        return "all", ""
    if normalized == "1":
        return "first", ""
    if normalized == "1,2,3,4,5":
        return "first5", ""
    return "range", normalized


def _build_bootstrap_service_config(
    cli_settings: CLIEnvSettingsModel,
    service_name: str,
) -> dict[str, Any]:
    metadata = TRANSLATION_ENGINE_METADATA_MAP.get(service_name)
    if not metadata or not metadata.cli_detail_field_name:
        return {}
    detail_settings = getattr(cli_settings, metadata.cli_detail_field_name, None)
    if detail_settings is None:
        return {}
    return {
        key: value
        for key, value in detail_settings.model_dump().items()
        if key not in {"translate_engine_type", "support_llm"}
    }


def _build_ui_bootstrap() -> dict[str, Any]:
    cli_settings = _load_base_cli_settings()
    services, term_services = _build_bootstrap_services(cli_settings)
    service = _selected_service(cli_settings)
    auto_term_extraction_enabled = (
        _service_supports_llm(service)
        and not cli_settings.translation.no_auto_extract_glossary
    )
    page_mode, page_range_text = _page_mode_from_pages(cli_settings.pdf.pages)
    return {
        "version": __version__,
        "default_service": "SiliconFlowFree",
        "settings": {
            "service": service,
            "lang_in": cli_settings.translation.lang_in,
            "lang_out": cli_settings.translation.lang_out,
            "page_mode": page_mode,
            "page_range_text": page_range_text,
            "only_include_translated_page": cli_settings.pdf.only_include_translated_page,
            "no_mono": cli_settings.pdf.no_mono,
            "no_dual": cli_settings.pdf.no_dual,
            "dual_translate_first": cli_settings.pdf.dual_translate_first,
            "use_alternating_pages_dual": cli_settings.pdf.use_alternating_pages_dual,
            "watermark_output_mode": cli_settings.pdf.watermark_output_mode,
            "qps": cli_settings.translation.qps or 4,
            "pool_max_workers": cli_settings.translation.pool_max_workers,
            "min_text_length": cli_settings.translation.min_text_length,
            "custom_system_prompt": cli_settings.translation.custom_system_prompt or "",
            "save_auto_extracted_glossary": cli_settings.translation.save_auto_extracted_glossary,
            "enable_auto_term_extraction": auto_term_extraction_enabled,
            "primary_font_family": cli_settings.translation.primary_font_family
            or "Auto",
            "skip_clean": cli_settings.pdf.skip_clean,
            "disable_rich_text_translate": cli_settings.pdf.disable_rich_text_translate,
            "enhance_compatibility": cli_settings.pdf.enhance_compatibility,
            "split_short_lines": cli_settings.pdf.split_short_lines,
            "short_line_split_factor": cli_settings.pdf.short_line_split_factor,
            "translate_table_text": cli_settings.pdf.translate_table_text,
            "skip_scanned_detection": cli_settings.pdf.skip_scanned_detection,
            "ignore_cache": cli_settings.translation.ignore_cache,
            "ocr_workaround": cli_settings.pdf.ocr_workaround,
            "auto_enable_ocr_workaround": cli_settings.pdf.auto_enable_ocr_workaround,
            "max_pages_per_part": cli_settings.pdf.max_pages_per_part,
            "formular_font_pattern": cli_settings.pdf.formular_font_pattern or "",
            "formular_char_pattern": cli_settings.pdf.formular_char_pattern or "",
            "merge_alternating_line_numbers": not cli_settings.pdf.no_merge_alternating_line_numbers,
            "remove_non_formula_lines": not cli_settings.pdf.no_remove_non_formula_lines,
            "non_formula_line_iou_threshold": cli_settings.pdf.non_formula_line_iou_threshold,
            "figure_table_protection_threshold": cli_settings.pdf.figure_table_protection_threshold,
            "skip_formula_offset_calculation": cli_settings.pdf.skip_formula_offset_calculation,
            "term_service": TERM_SERVICE_FOLLOW_MAIN,
            "term_qps": cli_settings.translation.term_qps
            or cli_settings.translation.qps
            or 4,
            "term_pool_max_workers": cli_settings.translation.term_pool_max_workers,
            "service_config": _build_bootstrap_service_config(cli_settings, service),
            "term_service_config": {},
        },
        "translation_languages": build_translation_language_options(),
        "services": services,
        "term_services": term_services,
    }


def _parse_webui_payload(raw_payload: str) -> WebUISettings:
    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise WebUIError("The WebUI payload is not valid JSON.") from exc
    return WebUISettings.model_validate(data)


def _calculate_rate_limit_params(
    rate_limit_mode: str,
    *,
    rpm: int,
    concurrent_threads: int,
    qps: int,
    pool_max_workers: int | None,
    default_qps: int = 4,
) -> tuple[int, int | None]:
    if rate_limit_mode == "RPM":
        normalized_rpm = int(rpm)
        if normalized_rpm <= 0:
            raise WebUIError("RPM must be a positive integer.")
        computed_qps = max(1, normalized_rpm // 60)
        return computed_qps, min(1000, computed_qps * 10)
    if rate_limit_mode == "Concurrent Threads":
        normalized_threads = int(concurrent_threads)
        if normalized_threads <= 0:
            raise WebUIError("Concurrent threads must be a positive integer.")
        pool_workers = min(
            1000,
            max(1, min(int(normalized_threads * 0.9), max(1, normalized_threads - 20))),
        )
        return max(1, pool_workers), pool_workers

    normalized_qps = int(qps or default_qps)
    if normalized_qps <= 0:
        raise WebUIError("QPS must be a positive integer.")
    normalized_pool = (
        int(pool_max_workers)
        if pool_max_workers is not None and int(pool_max_workers) > 0
        else None
    )
    return normalized_qps, normalized_pool


def _coerce_webui_service_config(
    service_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    metadata = TRANSLATION_ENGINE_METADATA_MAP.get(service_name)
    if not metadata or not metadata.cli_detail_field_name:
        return {}
    model_fields = metadata.setting_model_type.model_fields
    result: dict[str, Any] = {}
    for key, model_field in model_fields.items():
        if key in {"translate_engine_type", "support_llm"} or key not in values:
            continue
        raw_value = values[key]
        args = getattr(model_field.annotation, "__args__", ())
        if model_field.annotation is int or int in args:
            result[key] = int(raw_value) if raw_value not in ("", None) else None
        elif model_field.annotation is bool or bool in args:
            result[key] = bool(raw_value)
        elif model_field.annotation is float or float in args:
            result[key] = float(raw_value) if raw_value not in ("", None) else None
        else:
            result[key] = raw_value
    return result


def _coerce_model_field_value(model_field: Any, raw_value: Any) -> Any:
    annotation = model_field.annotation
    args = get_args(annotation)

    if raw_value == "":
        if model_field.default_factory is not None:
            return model_field.default_factory()
        if not model_field.is_required():
            return model_field.default
        if annotation is str or str in args:
            return ""
        return None

    if annotation is bool or bool in args:
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
        return bool(raw_value)

    if annotation is int or int in args:
        return (
            int(raw_value)
            if raw_value is not None
            else (
                model_field.default_factory()
                if model_field.default_factory is not None
                else model_field.default
            )
        )

    if annotation is float or float in args:
        return (
            float(raw_value)
            if raw_value is not None
            else (
                model_field.default_factory()
                if model_field.default_factory is not None
                else model_field.default
            )
        )

    return raw_value


def _build_settings_from_webui(
    base_settings: CLIEnvSettingsModel,
    payload: WebUISettings,
    *,
    file_path: Path | None,
    output_dir: Path | None,
    for_saved_config: bool = False,
) -> tuple[CLIEnvSettingsModel, Any]:
    translate_settings = base_settings.clone()
    del file_path
    translate_settings.basic.gui = for_saved_config
    if output_dir is not None:
        translate_settings.translation.output = str(output_dir)

    if payload.service not in TRANSLATION_ENGINE_METADATA_MAP:
        raise WebUIError(f"Unsupported translation service: {payload.service}")
    if payload.no_mono and payload.no_dual:
        raise WebUIError(
            "Select at least one output format before starting translation."
        )

    pages_map = {"all": None, "first": "1", "first5": "1,2,3,4,5", "range": None}
    pages = pages_map[payload.page_mode]
    if payload.page_mode == "range":
        pages = payload.page_range_text.strip() or None

    translate_settings.translation.lang_in = payload.lang_in
    translate_settings.translation.lang_out = payload.lang_out
    translate_settings.translation.ignore_cache = payload.ignore_cache
    translate_settings.translation.min_text_length = int(payload.min_text_length)
    translate_settings.translation.custom_system_prompt = (
        payload.custom_system_prompt.strip() or None
    )
    translate_settings.translation.save_auto_extracted_glossary = (
        payload.save_auto_extracted_glossary
    )
    translate_settings.translation.no_auto_extract_glossary = (
        not payload.enable_auto_term_extraction
    )
    translate_settings.translation.primary_font_family = (
        None if payload.primary_font_family == "Auto" else payload.primary_font_family
    )

    if payload.service != "SiliconFlowFree":
        qps, pool_max_workers = _calculate_rate_limit_params(
            payload.rate_limit_mode,
            rpm=payload.rpm,
            concurrent_threads=payload.concurrent_threads,
            qps=payload.qps,
            pool_max_workers=payload.pool_max_workers,
            default_qps=translate_settings.translation.qps or 4,
        )
        translate_settings.translation.qps = qps
        translate_settings.translation.pool_max_workers = pool_max_workers

    term_qps, term_pool_max_workers = _calculate_rate_limit_params(
        payload.term_rate_limit_mode,
        rpm=payload.term_rpm,
        concurrent_threads=payload.term_concurrent_threads,
        qps=payload.term_qps,
        pool_max_workers=payload.term_pool_max_workers,
        default_qps=translate_settings.translation.term_qps
        or translate_settings.translation.qps
        or 4,
    )
    translate_settings.translation.term_qps = term_qps
    translate_settings.translation.term_pool_max_workers = term_pool_max_workers

    translate_settings.pdf.pages = pages
    translate_settings.pdf.only_include_translated_page = (
        payload.only_include_translated_page
    )
    translate_settings.pdf.no_mono = payload.no_mono
    translate_settings.pdf.no_dual = payload.no_dual
    translate_settings.pdf.dual_translate_first = payload.dual_translate_first
    translate_settings.pdf.use_alternating_pages_dual = (
        payload.use_alternating_pages_dual
    )
    translate_settings.pdf.watermark_output_mode = payload.watermark_output_mode
    translate_settings.pdf.skip_clean = payload.skip_clean
    translate_settings.pdf.disable_rich_text_translate = (
        payload.disable_rich_text_translate
    )
    translate_settings.pdf.enhance_compatibility = payload.enhance_compatibility
    translate_settings.pdf.split_short_lines = payload.split_short_lines
    translate_settings.pdf.short_line_split_factor = float(
        payload.short_line_split_factor
    )
    translate_settings.pdf.translate_table_text = payload.translate_table_text
    translate_settings.pdf.skip_scanned_detection = payload.skip_scanned_detection
    translate_settings.pdf.ocr_workaround = payload.ocr_workaround
    translate_settings.pdf.auto_enable_ocr_workaround = (
        payload.auto_enable_ocr_workaround
    )
    translate_settings.pdf.max_pages_per_part = (
        int(payload.max_pages_per_part)
        if payload.max_pages_per_part and int(payload.max_pages_per_part) > 0
        else None
    )
    translate_settings.pdf.formular_font_pattern = (
        payload.formular_font_pattern.strip() or None
    )
    translate_settings.pdf.formular_char_pattern = (
        payload.formular_char_pattern.strip() or None
    )
    translate_settings.pdf.no_merge_alternating_line_numbers = (
        not payload.merge_alternating_line_numbers
    )
    translate_settings.pdf.no_remove_non_formula_lines = (
        not payload.remove_non_formula_lines
    )
    translate_settings.pdf.non_formula_line_iou_threshold = float(
        payload.non_formula_line_iou_threshold
    )
    translate_settings.pdf.figure_table_protection_threshold = float(
        payload.figure_table_protection_threshold
    )
    translate_settings.pdf.skip_formula_offset_calculation = (
        payload.skip_formula_offset_calculation
    )

    for metadata in TRANSLATION_ENGINE_METADATA:
        setattr(translate_settings, metadata.cli_flag_name, False)
    selected_metadata = TRANSLATION_ENGINE_METADATA_MAP[payload.service]
    setattr(translate_settings, selected_metadata.cli_flag_name, True)
    if selected_metadata.cli_detail_field_name:
        detail_settings = getattr(
            translate_settings,
            selected_metadata.cli_detail_field_name,
        )
        for key, value in _coerce_webui_service_config(
            payload.service,
            payload.service_config,
        ).items():
            setattr(detail_settings, key, value)

    settings_model = translate_settings.to_settings_model()
    _disable_auto_term_extraction_for_non_llm(settings_model)
    settings_model.validate_settings()
    return translate_settings, settings_model


def _set_translation_service(
    cli_settings: CLIEnvSettingsModel,
    *,
    service_name: str | None,
    engine_settings: dict[str, Any],
) -> None:
    if service_name:
        selected_metadata = _resolve_service_metadata(service_name)
        for metadata in TRANSLATION_ENGINE_METADATA:
            setattr(cli_settings, metadata.cli_flag_name, False)
        setattr(cli_settings, selected_metadata.cli_flag_name, True)
    else:
        selected_metadata = TRANSLATION_ENGINE_METADATA_MAP["SiliconFlowFree"]

    if not engine_settings:
        return
    if not selected_metadata.cli_detail_field_name:
        raise APIError(
            status_code=400,
            code="unexpected_engine_settings",
            message=f"{selected_metadata.translate_engine_type} does not accept engine detail settings.",
        )

    detail_model = getattr(cli_settings, selected_metadata.cli_detail_field_name)
    model_fields = type(detail_model).model_fields
    merged_settings = detail_model.model_dump()
    for field_name, raw_value in engine_settings.items():
        if field_name not in model_fields:
            raise APIError(
                status_code=400,
                code="invalid_request_field",
                message=(
                    f"Unsupported field `{field_name}` in "
                    f"`{selected_metadata.translate_engine_type}` engine settings."
                ),
            )
        merged_settings[field_name] = _coerce_model_field_value(
            model_fields[field_name],
            raw_value,
        )
    merged_settings["translate_engine_type"] = selected_metadata.translate_engine_type
    setattr(
        cli_settings,
        selected_metadata.cli_detail_field_name,
        selected_metadata.setting_model_type(**merged_settings),
    )


def _apply_overrides(
    section: Any, overrides: dict[str, Any], *, section_name: str
) -> None:
    model_fields = type(section).model_fields
    for field_name, value in overrides.items():
        if field_name not in model_fields:
            raise APIError(
                status_code=400,
                code="invalid_request_field",
                message=f"Unsupported field `{field_name}` in `{section_name}` settings.",
            )
        setattr(
            section,
            field_name,
            _coerce_model_field_value(model_fields[field_name], value),
        )


def _build_settings(
    *,
    file_path: Path,
    output_dir: Path,
    service_name: str | None,
    lang_in: str,
    lang_out: str,
    translation_overrides: dict[str, Any],
    pdf_overrides: dict[str, Any],
    engine_settings: dict[str, Any],
) -> Any:
    cli_settings = _load_base_cli_settings().clone()
    del file_path
    _set_translation_service(
        cli_settings,
        service_name=service_name,
        engine_settings=engine_settings,
    )
    cli_settings.translation.lang_in = lang_in
    cli_settings.translation.lang_out = lang_out
    cli_settings.translation.output = str(output_dir)
    _apply_overrides(
        cli_settings.translation,
        translation_overrides,
        section_name="translation",
    )
    _apply_overrides(cli_settings.pdf, pdf_overrides, section_name="pdf")

    try:
        settings = cli_settings.to_settings_model()
        _disable_auto_term_extraction_for_non_llm(settings)
        settings.validate_settings()
    except ValueError as exc:
        raise APIError(
            status_code=400,
            code="invalid_translation_settings",
            message=str(exc),
            hint=_build_settings_hint(str(exc)),
        ) from exc

    return settings


def _build_request_settings(
    request: TranslateRequest,
    *,
    file_path: Path,
    output_dir: Path,
) -> Any:
    return _build_settings(
        file_path=file_path,
        output_dir=output_dir,
        service_name=request.service,
        lang_in=request.lang_in,
        lang_out=request.lang_out,
        translation_overrides={"ignore_cache": request.ignore_cache},
        pdf_overrides={
            "pages": request.pages,
            "no_mono": request.no_mono,
            "no_dual": request.no_dual,
        },
        engine_settings={},
    )


def _build_browser_request_settings(
    request: BrowserTranslateRequest,
    *,
    file_path: Path,
    output_dir: Path,
) -> Any:
    return _build_settings(
        file_path=file_path,
        output_dir=output_dir,
        service_name=request.service,
        lang_in=request.lang_in,
        lang_out=request.lang_out,
        translation_overrides=dict(request.translation),
        pdf_overrides=dict(request.pdf),
        engine_settings=dict(request.engine_settings),
    )


def _build_web_request_settings(
    payload: WebTranslatePayload,
    *,
    file_path: Path,
    output_dir: Path,
) -> Any:
    cli_settings = _build_full_cli_settings(payload.settings).clone()
    del file_path
    cli_settings.translation.output = str(output_dir)
    try:
        settings = cli_settings.to_settings_model()
        _disable_auto_term_extraction_for_non_llm(settings)
        settings.validate_settings()
    except ValueError as exc:
        raise APIError(
            status_code=400,
            code="invalid_translation_settings",
            message=str(exc),
            hint=_build_settings_hint(str(exc)),
        ) from exc

    if payload.persist_settings:
        ConfigManager().write_user_default_config_file(cli_settings.clone())

    return settings


def _apply_server_resource_caps(
    settings: Any,
    server_settings: HTTPServerSettings,
) -> Any:
    worker_cap = max(2, os.cpu_count() or 2)
    qps_cap = max(4, worker_cap * server_settings.max_concurrent_jobs)

    settings.translation.qps = min(settings.translation.qps or qps_cap, qps_cap)
    settings.translation.term_qps = min(
        settings.translation.term_qps or settings.translation.qps,
        qps_cap,
    )

    if settings.translation.pool_max_workers is not None:
        settings.translation.pool_max_workers = min(
            settings.translation.pool_max_workers,
            worker_cap,
        )
    if settings.translation.term_pool_max_workers is not None:
        settings.translation.term_pool_max_workers = min(
            settings.translation.term_pool_max_workers,
            worker_cap,
        )

    return settings


def _artifact_manifest_path(output_dir: Path) -> Path:
    return output_dir / _ARTIFACT_MANIFEST_NAME


def _guess_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _artifact_url(
    request_id: str,
    artifact_name: str,
    *,
    disposition: Literal["attachment", "inline"] = "attachment",
) -> str:
    url = f"/requests/{request_id}/artifacts/{artifact_name}"
    if disposition == "inline":
        return f"{url}?disposition=inline"
    return url


def _build_artifact(
    *,
    name: str,
    path: Path,
    request_id: str,
) -> TranslationArtifact:
    return TranslationArtifact(
        name=name,
        filename=path.name,
        url=_artifact_url(request_id, name, disposition="attachment"),
        preview_url=_artifact_url(request_id, name, disposition="inline"),
        size_bytes=path.stat().st_size if path.exists() else None,
    )


def _build_artifacts(
    *,
    request_id: str,
    input_file_path: Path,
    result: Any,
) -> dict[str, TranslationArtifact]:
    artifacts = {
        _SOURCE_ARTIFACT_NAME: _build_artifact(
            name=_SOURCE_ARTIFACT_NAME,
            path=input_file_path,
            request_id=request_id,
        )
    }
    artifact_paths = {
        "mono": getattr(result, "mono_pdf_path", None),
        "dual": getattr(result, "dual_pdf_path", None),
        "glossary": getattr(result, "auto_extracted_glossary_path", None),
    }
    for name, raw_path in artifact_paths.items():
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        artifacts[name] = _build_artifact(name=name, path=path, request_id=request_id)
    return artifacts


def _build_downloads(
    artifacts: dict[str, TranslationArtifact],
) -> dict[str, TranslationArtifact]:
    return {
        name: artifact
        for name, artifact in artifacts.items()
        if name != _SOURCE_ARTIFACT_NAME
    }


def _write_artifact_manifest(
    output_dir: Path,
    input_file_path: Path,
    response: TranslateResponse,
) -> None:
    manifest = {
        "source_path": input_file_path.as_posix(),
        "artifacts": {
            name: {
                "path": (
                    input_file_path.as_posix()
                    if name == _SOURCE_ARTIFACT_NAME
                    else getattr(response, f"{name}_pdf_path", None)
                    or response.glossary_path
                ),
                "filename": artifact.filename,
                "content_type": _guess_content_type(
                    input_file_path
                    if name == _SOURCE_ARTIFACT_NAME
                    else Path(artifact.filename)
                ),
            }
            for name, artifact in response.artifacts.items()
        },
    }
    for name, artifact in response.artifacts.items():
        if name == _SOURCE_ARTIFACT_NAME:
            manifest["artifacts"][name]["path"] = input_file_path.as_posix()
            manifest["artifacts"][name]["content_type"] = _guess_content_type(
                input_file_path
            )
        elif name == "mono":
            manifest["artifacts"][name]["path"] = response.mono_pdf_path
            manifest["artifacts"][name]["content_type"] = "application/pdf"
        elif name == "dual":
            manifest["artifacts"][name]["path"] = response.dual_pdf_path
            manifest["artifacts"][name]["content_type"] = "application/pdf"
        elif name == "glossary":
            manifest["artifacts"][name]["path"] = response.glossary_path
            manifest["artifacts"][name]["content_type"] = _guess_content_type(
                Path(artifact.filename)
            )
    _artifact_manifest_path(output_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_artifact_manifest(output_dir: Path) -> dict[str, Any]:
    manifest_path = _artifact_manifest_path(output_dir)
    if not manifest_path.exists():
        raise APIError(
            status_code=404,
            code="artifact_manifest_not_found",
            message="No artifacts were recorded for this request.",
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _build_translate_response(
    *,
    settings: Any,
    file_path: Path,
    request_id: str,
    output_dir: Path,
    result: Any,
    token_usage: dict[str, Any] | None,
) -> TranslateResponse:
    artifacts = _build_artifacts(
        request_id=request_id,
        input_file_path=file_path,
        result=result,
    )
    response = TranslateResponse(
        status="completed",
        request_id=request_id,
        service=settings.translate_engine_settings.translate_engine_type,
        input_file=str(file_path),
        output_dir=str(settings.translation.output),
        mono_pdf_path=_normalize_output_path(getattr(result, "mono_pdf_path", None)),
        dual_pdf_path=_normalize_output_path(getattr(result, "dual_pdf_path", None)),
        glossary_path=_normalize_output_path(
            getattr(result, "auto_extracted_glossary_path", None)
        ),
        mono_download_url=artifacts.get("mono").url if "mono" in artifacts else None,
        dual_download_url=artifacts.get("dual").url if "dual" in artifacts else None,
        glossary_download_url=(
            artifacts.get("glossary").url if "glossary" in artifacts else None
        ),
        preview_url=(
            artifacts.get("mono").preview_url
            if "mono" in artifacts
            else (artifacts.get("dual").preview_url if "dual" in artifacts else None)
        ),
        total_seconds=getattr(result, "total_seconds", None),
        token_usage=token_usage or {},
        artifacts=artifacts,
        downloads=_build_downloads(artifacts),
    )
    _write_artifact_manifest(output_dir, file_path, response)
    return response


async def _translate_single_file(
    settings: Any,
    *,
    file_path: Path,
    request_id: str,
    output_dir: Path,
) -> TranslateResponse:
    last_progress: dict[str, Any] | None = None

    async for event in do_translate_async_stream(
        settings,
        file_path,
        raise_on_error=False,
    ):
        event_type = event.get("type")
        if event_type in {"progress_start", "progress_update", "progress_end"}:
            last_progress = {
                "stage": event.get("stage"),
                "overall_progress": event.get("overall_progress"),
            }
            continue

        if event_type == "error":
            error_message = str(event.get("error", "Translation failed."))
            raise APIError(
                status_code=502,
                code="translation_failed",
                message=error_message,
                hint=_build_translation_hint(error_message),
                details=event.get("details") or last_progress,
            )

        if event_type == "finish":
            return _build_translate_response(
                settings=settings,
                file_path=file_path,
                request_id=request_id,
                output_dir=output_dir,
                result=event["translate_result"],
                token_usage=event.get("token_usage", {}),
            )

    raise APIError(
        status_code=500,
        code="missing_translation_result",
        message="The translation finished without a result payload.",
    )


def _progress_message(event: dict[str, Any]) -> str:
    stage = event.get("stage") or "translation"
    part_index = event.get("part_index") or 1
    total_parts = event.get("total_parts") or 1
    return f"{stage} is running for part {part_index} of {total_parts}."


def _coerce_json_line(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")


def _require_browser_seat(
    *,
    seat_id: str | None,
    lease_token: str | None,
) -> tuple[str, str]:
    if not seat_id or not lease_token:
        raise APIError(
            status_code=409,
            code="seat_required",
            message="Claim an available seat before starting a translation.",
            hint="Return to the lobby and enter one of the four seats first.",
        )
    return seat_id, lease_token


async def _submit_translation_job(
    *,
    job_manager: TranslationJobManager,
    seat_manager: SeatManager | None,
    settings: Any,
    file_path: Path,
    request_id: str,
    output_dir: Path,
    seat_id: str | None = None,
    lease_token: str | None = None,
) -> _TranslationJob:
    capped_settings = _apply_server_resource_caps(
        settings,
        job_manager.server_settings,
    )
    if seat_manager and seat_id and lease_token:
        await seat_manager.reserve_job(
            seat_id=seat_id,
            lease_token=lease_token,
            request_id=request_id,
            service_name=capped_settings.translate_engine_settings.translate_engine_type,
        )
    try:
        job = await job_manager.submit_job(
            request_id=request_id,
            service=capped_settings.translate_engine_settings.translate_engine_type,
            file_path=file_path,
            output_dir=output_dir,
            settings=capped_settings,
            seat_id=seat_id,
        )
    except Exception:
        if seat_manager and seat_id:
            await seat_manager.clear_job_reservation(
                seat_id=seat_id,
                request_id=request_id,
                lease_token=lease_token,
            )
        raise
    if seat_manager and seat_id and lease_token:
        try:
            await seat_manager.bind_job(
                seat_id=seat_id,
                lease_token=lease_token,
                request_id=request_id,
                job_id=job.job_id,
            )
        except Exception:
            with suppress(APIError):
                await job_manager.cancel_job(job.job_id)
            raise
    logger.info(
        "Accepted translation job %s for request %s using service=%s auto_term_extraction=%s.",
        job.job_id,
        request_id,
        job.service,
        not capped_settings.translation.no_auto_extract_glossary,
    )
    return job


def _raise_for_terminal_job(job: _TranslationJob) -> TranslateResponse:
    if job.status == "succeeded" and job.result:
        return job.result
    if job.status == "cancelled":
        raise APIError(
            status_code=409,
            code="job_cancelled",
            message="The translation job was cancelled before completion.",
        )
    if job.status == "expired":
        raise APIError(
            status_code=410,
            code="job_expired",
            message="The translation job has expired and its artifacts were deleted.",
        )
    if job.error:
        raise APIError(
            status_code=502 if job.error.get("code") == "translation_failed" else 500,
            code=job.error.get("code", "internal_error"),
            message=job.error.get("message", "Translation failed."),
            hint=job.error.get("hint"),
            details=job.error.get("details"),
        )
    raise APIError(
        status_code=500,
        code="missing_translation_result",
        message="The translation finished without a result payload.",
    )


def _legacy_stream_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event.get("type")
    job_payload = event.get("job", {})
    if event_type == "progress":
        return {
            "type": "progress",
            "stage": event.get("stage"),
            "message": _progress_message(event),
            "overall_progress": event.get("overall_progress"),
            "part_index": event.get("part_index"),
            "total_parts": event.get("total_parts"),
            "stage_current": event.get("stage_current"),
            "stage_total": event.get("stage_total"),
        }
    if event_type == "error":
        return {"type": "error", "error": event.get("error")}
    if event_type == "cancelled":
        return {
            "type": "error",
            "error": {
                "code": "job_cancelled",
                "message": "The translation job was cancelled before completion.",
            },
        }
    if event_type == "expired":
        return {
            "type": "error",
            "error": {
                "code": "job_expired",
                "message": "The translation job artifacts have expired.",
            },
        }
    if event_type == "finish":
        return {"type": "finish", "result": event.get("result")}
    if event_type in {"snapshot", "queued", "running"}:
        return {
            "type": "status",
            "job": job_payload,
        }
    return None


async def _stream_job_events(
    job_manager: TranslationJobManager,
    job_id: str,
    *,
    legacy_format: bool = False,
):
    job, queue = await job_manager.subscribe(job_id)
    try:
        while True:
            event = await queue.get()
            payload = _legacy_stream_event(event) if legacy_format else event
            if payload is not None:
                yield _coerce_json_line(payload)
            if event.get("type") in {"finish", "error", "cancelled", "expired"}:
                return
    finally:
        await job_manager.unsubscribe(job, queue)


async def _stream_translation_file(
    *,
    settings: Any,
    file_path: Path,
    request_id: str,
    output_dir: Path,
):
    async for event in do_translate_async_stream(
        settings,
        file_path,
        raise_on_error=False,
    ):
        event_type = event.get("type")
        if event_type in {"progress_start", "progress_update", "progress_end"}:
            yield _coerce_json_line(
                {
                    "type": "progress",
                    "stage": event.get("stage"),
                    "message": _progress_message(event),
                    "overall_progress": event.get("overall_progress"),
                    "part_index": event.get("part_index"),
                    "total_parts": event.get("total_parts"),
                    "stage_current": event.get("stage_current"),
                    "stage_total": event.get("stage_total"),
                }
            )
            continue

        if event_type == "error":
            error_message = str(event.get("error", "Translation failed."))
            yield _coerce_json_line(
                {
                    "type": "error",
                    "error": {
                        "code": "translation_failed",
                        "message": error_message,
                        "hint": _build_translation_hint(error_message),
                        "details": event.get("details"),
                    },
                }
            )
            return

        if event_type == "finish":
            response = _build_translate_response(
                settings=settings,
                file_path=file_path,
                request_id=request_id,
                output_dir=output_dir,
                result=event["translate_result"],
                token_usage=event.get("token_usage", {}),
            )
            yield _coerce_json_line(
                {
                    "type": "finish",
                    "result": response.model_dump(mode="json"),
                }
            )
            return

    yield _coerce_json_line(
        {
            "type": "error",
            "error": {
                "code": "missing_translation_result",
                "message": "The translation finished without a result payload.",
            },
        }
    )


def _frontend_dist_dir() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent / "frontend" / "dist",
        Path(__file__).with_name("webui_dist"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _serve_frontend(app: FastAPI) -> bool:
    dist_dir = _frontend_dist_dir()
    if dist_dir is None:
        logger.warning("Frontend dist directory not found.")
        return False

    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(dist_dir / "index.html")

    return True


def create_app(
    *,
    serve_frontend: bool = False,
    include_frontend: bool | None = None,
    server_settings: HTTPServerSettings | None = None,
) -> FastAPI:
    if include_frontend is not None:
        serve_frontend = include_frontend
    server_settings = server_settings or HTTPServerSettings()
    _configure_runtime_noise_filters()
    job_manager = TranslationJobManager(server_settings)
    seat_manager = SeatManager(server_settings, job_manager=job_manager)
    job_manager.seat_manager = seat_manager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await job_manager.start()
        await seat_manager.start()
        try:
            yield
        finally:
            await seat_manager.shutdown()
            await job_manager.shutdown()

    app = FastAPI(
        title="PDFMathTranslate Next HTTP API",
        version=__version__,
        description=(
            "Minimal HTTP API for translating a single PDF with the current "
            "server configuration."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.server_settings = server_settings
    app.state.job_manager = job_manager
    app.state.seat_manager = seat_manager

    @app.exception_handler(APIError)
    async def api_error_handler(
        _request: Request,
        exc: APIError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(
                code=exc.code,
                message=exc.message,
                hint=exc.hint,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                code="request_validation_failed",
                message="The request body is invalid.",
                hint=_build_request_validation_hint(),
                details=details,
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled HTTP API error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                code="internal_error",
                message="The server hit an unexpected error while processing the request.",
            ),
        )

    if not serve_frontend:

        @app.get("/", include_in_schema=False)
        async def root() -> dict[str, Any]:
            return _api_root_payload()

    @app.get("/healthz", response_model=HealthResponse, tags=["meta"])
    async def healthz() -> HealthResponse:
        health_payload = app.state.job_manager.health_payload()
        return HealthResponse(
            status="ok",
            version=__version__,
            default_config_file=str(DEFAULT_CONFIG_FILE),
            running_jobs=health_payload["running_jobs"],
            queued_jobs=health_payload["queued_jobs"],
            max_concurrent_jobs=health_payload["max_concurrent_jobs"],
            max_queue_size=health_payload["max_queue_size"],
            job_retention_minutes=health_payload["job_retention_minutes"],
        )

    @app.get("/engines", tags=["meta"])
    async def list_engines() -> dict[str, Any]:
        return {
            "default_service": "SiliconFlowFree",
            "engines": [
                EngineInfo(
                    name=metadata.translate_engine_type,
                    flag=metadata.cli_flag_name,
                    support_llm=metadata.support_llm,
                    description=metadata.setting_model_type.__doc__,
                ).model_dump()
                for metadata in TRANSLATION_ENGINE_METADATA
            ],
        }

    @app.get("/app/config", tags=["meta"])
    async def app_config() -> dict[str, Any]:
        return _build_app_config(app.state.server_settings)

    @app.post("/seats/login", response_model=SeatLoginResponse, tags=["seats"])
    async def seat_login(payload: SeatLoginRequest) -> SeatLoginResponse:
        return await app.state.seat_manager.login(payload.display_name)

    @app.get("/seats", response_model=SeatListResponse, tags=["seats"])
    async def list_seats() -> SeatListResponse:
        return await app.state.seat_manager.list_seats()

    @app.post(
        "/seats/{seat_id}/claim",
        response_model=SeatClaimResponse,
        tags=["seats"],
    )
    async def claim_seat(
        seat_id: str,
        payload: SeatClaimRequest,
    ) -> SeatClaimResponse:
        return await app.state.seat_manager.claim_seat(seat_id, payload.display_name)

    @app.post(
        "/seats/{seat_id}/heartbeat",
        response_model=SeatClaimResponse,
        tags=["seats"],
    )
    async def heartbeat_seat(
        seat_id: str,
        payload: SeatLeaseRequest,
    ) -> SeatClaimResponse:
        return await app.state.seat_manager.heartbeat(seat_id, payload.lease_token)

    @app.post(
        "/seats/{seat_id}/release",
        response_model=SeatSummary,
        tags=["seats"],
    )
    async def release_seat(
        seat_id: str,
        payload: SeatLeaseRequest,
    ) -> SeatSummary:
        return await app.state.seat_manager.release_seat(seat_id, payload.lease_token)

    @app.post(
        "/seats/{seat_id}/service",
        response_model=SeatSummary,
        tags=["seats"],
    )
    async def update_seat_service(
        seat_id: str,
        payload: SeatServiceRequest,
    ) -> SeatSummary:
        return await app.state.seat_manager.update_selected_service(
            seat_id,
            payload.lease_token,
            payload.service,
        )

    @app.post(
        "/admin/seats/{seat_id}/force-release",
        response_model=SeatSummary,
        tags=["seats"],
    )
    async def force_release_seat(
        seat_id: str,
        payload: SeatForceReleaseRequest,
    ) -> SeatSummary:
        return await app.state.seat_manager.force_release_seat(
            seat_id,
            payload.admin_token,
        )

    @app.get("/ui/bootstrap", tags=["meta"])
    async def ui_bootstrap() -> dict[str, Any]:
        return _build_ui_bootstrap()

    @app.get("/api/ui-config", tags=["frontend"])
    async def ui_config() -> dict[str, Any]:
        return build_ui_schema(_load_base_cli_settings())

    @app.post("/api/config", tags=["frontend"])
    async def save_ui_config(payload: WebConfigPayload) -> dict[str, str]:
        cli_settings = _build_full_cli_settings(payload.settings).clone()
        ConfigManager().write_user_default_config_file(cli_settings)
        return {"status": "saved", "config_file": str(DEFAULT_CONFIG_FILE)}

    @app.post("/settings/default", tags=["frontend"])
    async def save_default_settings(payload: WebUISettings) -> dict[str, str]:
        try:
            cli_settings, _ = _build_settings_from_webui(
                _load_base_cli_settings(),
                payload,
                file_path=None,
                output_dir=None,
                for_saved_config=True,
            )
        except WebUIError as exc:
            raise APIError(
                status_code=400,
                code="invalid_translation_settings",
                message=str(exc),
            ) from exc
        ConfigManager().write_user_default_config_file(cli_settings)
        return {"status": "saved", "config_file": str(DEFAULT_CONFIG_FILE)}

    @app.get("/metrics", tags=["meta"])
    async def metrics() -> dict[str, Any]:
        return app.state.job_manager.metrics_payload()

    @app.get("/jobs", response_model=JobListResponse, tags=["jobs"])
    async def list_jobs(limit: int = 50) -> JobListResponse:
        jobs = await app.state.job_manager.list_jobs(limit=limit)
        return JobListResponse(
            jobs=[app.state.job_manager._job_response(job) for job in jobs]
        )

    @app.get("/jobs/{job_id}", response_model=JobResponse, tags=["jobs"])
    async def get_job(job_id: str) -> JobResponse:
        return await app.state.job_manager.build_job_response(job_id)

    @app.get("/jobs/{job_id}/events", tags=["jobs"])
    async def stream_job_events(job_id: str) -> StreamingResponse:
        return StreamingResponse(
            _stream_job_events(app.state.job_manager, job_id),
            media_type="application/x-ndjson",
        )

    @app.post("/jobs/{job_id}/cancel", response_model=JobResponse, tags=["jobs"])
    async def cancel_job(job_id: str) -> JobResponse:
        job = await app.state.job_manager.cancel_job(job_id)
        return app.state.job_manager._job_response(job)

    async def _wait_for_job_result(job: _TranslationJob) -> TranslateResponse:
        completed_job = await app.state.job_manager.wait_for_completion(job.job_id)
        return _raise_for_terminal_job(completed_job)

    async def _create_request_job(request: TranslateRequest) -> _TranslationJob:
        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(
            request_id,
            request.output_dir,
        )
        file_path = _prepare_request_source(request, output_dir, server_settings)
        settings = _build_request_settings(
            request,
            file_path=file_path,
            output_dir=output_dir,
        )
        return await _submit_translation_job(
            job_manager=app.state.job_manager,
            seat_manager=None,
            settings=settings,
            file_path=file_path,
            request_id=request_id,
            output_dir=output_dir,
        )

    async def _create_browser_job(
        request: BrowserTranslateRequest,
        *,
        file: UploadFile | None,
        file_url: str | None,
    ) -> _TranslationJob:
        if bool(file) == bool(file_url):
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="Provide exactly one of uploaded `file` or `file_url`.",
            )
        seat_id, lease_token = _require_browser_seat(
            seat_id=request.seat_id,
            lease_token=request.lease_token,
        )
        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, None)
        file_path = (
            await _save_uploaded_pdf(file, output_dir, server_settings)
            if file
            else _download_pdf_from_url(file_url or "", output_dir, server_settings)
        )
        settings = _build_browser_request_settings(
            request,
            file_path=file_path,
            output_dir=output_dir,
        )
        return await _submit_translation_job(
            job_manager=app.state.job_manager,
            seat_manager=app.state.seat_manager,
            settings=settings,
            file_path=file_path,
            request_id=request_id,
            output_dir=output_dir,
            seat_id=seat_id,
            lease_token=lease_token,
        )

    async def _create_webui_job(
        payload_text: str,
        *,
        file: UploadFile | None,
    ) -> _TranslationJob:
        if file is None:
            raise APIError(
                status_code=400,
                code="missing_upload",
                message="Upload a PDF file before starting translation.",
            )
        try:
            webui_payload = _parse_webui_payload(payload_text)
        except (ValidationError, WebUIError) as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message=str(exc),
            ) from exc
        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, None)
        file_path = await _save_uploaded_pdf(file, output_dir, server_settings)
        try:
            _cli_settings, settings = _build_settings_from_webui(
                _load_base_cli_settings(),
                webui_payload,
                file_path=file_path,
                output_dir=output_dir,
            )
        except WebUIError as exc:
            raise APIError(
                status_code=400,
                code="invalid_translation_settings",
                message=str(exc),
            ) from exc
        return await _submit_translation_job(
            job_manager=app.state.job_manager,
            seat_manager=None,
            settings=settings,
            file_path=file_path,
            request_id=request_id,
            output_dir=output_dir,
        )

    async def _create_frontend_job(
        payload_text: str,
        *,
        file: UploadFile | None,
    ) -> _TranslationJob:
        try:
            translate_payload = WebTranslatePayload.model_validate_json(payload_text)
        except ValidationError as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="The React translation payload is invalid.",
                details=exc.errors(),
            ) from exc
        seat_id, lease_token = _require_browser_seat(
            seat_id=translate_payload.seat_id,
            lease_token=translate_payload.lease_token,
        )
        request_id = str(uuid.uuid4())
        output_dir = _prepare_request_output_dir(request_id, None)
        if translate_payload.source_type == "link":
            file_path = _download_pdf_from_url(
                translate_payload.file_url or "",
                output_dir,
                server_settings,
            )
        else:
            if file is None:
                raise APIError(
                    status_code=400,
                    code="missing_upload",
                    message="Upload a PDF file when `source_type` is `file`.",
                )
            file_path = await _save_uploaded_pdf(file, output_dir, server_settings)
        settings = _build_web_request_settings(
            translate_payload,
            file_path=file_path,
            output_dir=output_dir,
        )
        return await _submit_translation_job(
            job_manager=app.state.job_manager,
            seat_manager=app.state.seat_manager,
            settings=settings,
            file_path=file_path,
            request_id=request_id,
            output_dir=output_dir,
            seat_id=seat_id,
            lease_token=lease_token,
        )

    async def _download_artifact_impl(
        request_id: str,
        artifact_name: str,
        disposition: Literal["attachment", "inline"] = "attachment",
    ) -> FileResponse:
        job = await app.state.job_manager.get_job_by_request_id(request_id)
        if job and job.status == "expired":
            raise HTTPException(status_code=404, detail="Artifact has expired.")
        output_dir = _HTTP_OUTPUT_ROOT / request_id
        manifest = _read_artifact_manifest(output_dir)
        artifact = manifest.get("artifacts", {}).get(artifact_name)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        file_path = Path(artifact["path"])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Artifact file not found.")
        return FileResponse(
            file_path,
            media_type=artifact.get("content_type") or _guess_content_type(file_path),
            filename=artifact.get("filename") or file_path.name,
            content_disposition_type=disposition,
        )

    @app.get("/artifacts/{request_id}/{artifact_name}", tags=["artifacts"])
    async def download_artifact(
        request_id: str,
        artifact_name: str,
        disposition: Literal["attachment", "inline"] = "attachment",
    ) -> FileResponse:
        return await _download_artifact_impl(
            request_id, artifact_name, disposition=disposition
        )

    @app.get("/requests/{request_id}/artifacts/{artifact_name}", tags=["artifacts"])
    async def download_artifact_legacy(
        request_id: str,
        artifact_name: str,
        disposition: Literal["attachment", "inline"] = "attachment",
    ) -> FileResponse:
        return await _download_artifact_impl(
            request_id, artifact_name, disposition=disposition
        )

    @app.get("/api/files/{request_id}/{artifact_name}", tags=["artifacts"])
    async def download_artifact_alias(
        request_id: str,
        artifact_name: str,
        disposition: Literal["attachment", "inline"] = "attachment",
    ) -> FileResponse:
        return await _download_artifact_impl(
            request_id, artifact_name, disposition=disposition
        )

    @app.post("/jobs", response_model=JobResponse, status_code=202, tags=["jobs"])
    async def create_job(
        payload: Annotated[str, Form()],
        file: Annotated[UploadFile | None, File()] = None,
    ) -> JobResponse:
        job = await _create_frontend_job(payload, file=file)
        return app.state.job_manager._job_response(job)

    @app.post("/translate", response_model=TranslateResponse, tags=["translation"])
    async def translate(request: TranslateRequest) -> TranslateResponse:
        job = await _create_request_job(request)
        return await _wait_for_job_result(job)

    @app.post("/translate/file", response_model=TranslateResponse, tags=["translation"])
    async def translate_file(
        file: Annotated[UploadFile | None, File()] = None,
        file_url: Annotated[str | None, Form()] = None,
        request_json: Annotated[str, Form()] = "{}",
    ) -> TranslateResponse:
        try:
            request = BrowserTranslateRequest.model_validate_json(request_json)
        except ValidationError as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="The browser translation payload is invalid.",
                details=exc.errors(),
            ) from exc

        job = await _create_browser_job(request, file=file, file_url=file_url)
        return await _wait_for_job_result(job)

    @app.post("/translate/file/stream", tags=["translation"])
    async def translate_file_stream(
        file: Annotated[UploadFile | None, File()] = None,
        file_url: Annotated[str | None, Form()] = None,
        request_json: Annotated[str, Form()] = "{}",
    ) -> StreamingResponse:
        try:
            request = BrowserTranslateRequest.model_validate_json(request_json)
        except ValidationError as exc:
            raise APIError(
                status_code=422,
                code="request_validation_failed",
                message="The browser translation payload is invalid.",
                details=exc.errors(),
            ) from exc

        job = await _create_browser_job(request, file=file, file_url=file_url)
        return StreamingResponse(
            _stream_job_events(
                app.state.job_manager,
                job.job_id,
                legacy_format=True,
            ),
            media_type="application/x-ndjson",
        )

    @app.post("/translate/upload/stream", tags=["translation"])
    async def translate_upload_stream(
        payload: Annotated[str, Form()],
        file: Annotated[UploadFile | None, File()] = None,
    ) -> StreamingResponse:
        job = await _create_webui_job(payload, file=file)

        async def legacy_stream():
            yield _coerce_json_line(
                {
                    "type": "start",
                    "request_id": job.request_id,
                    "job_id": job.job_id,
                    "service": job.service,
                }
            )
            async for line in _stream_job_events(
                app.state.job_manager,
                job.job_id,
                legacy_format=True,
            ):
                yield line

        return StreamingResponse(legacy_stream(), media_type="application/x-ndjson")

    @app.post("/api/translate/stream", tags=["frontend"])
    async def translate_stream(
        payload: Annotated[str, Form()],
        file: Annotated[UploadFile | None, File()] = None,
    ) -> StreamingResponse:
        job = await _create_frontend_job(payload, file=file)
        return StreamingResponse(
            _stream_job_events(
                app.state.job_manager,
                job.job_id,
                legacy_format=True,
            ),
            media_type="application/x-ndjson",
        )

    if serve_frontend:
        frontend_served = _serve_frontend(app)
        if not frontend_served:
            logger.warning("Frontend was requested but no build output was found.")

            @app.get("/", include_in_schema=False)
            async def root_without_frontend() -> dict[str, Any]:
                return _api_root_payload()

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("pdf2zh_next.http_api:app", host="127.0.0.1", port=8000)

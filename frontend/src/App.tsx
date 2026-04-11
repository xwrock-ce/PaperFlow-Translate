import {
  startTransition,
  type Dispatch,
  type ReactElement,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";

import { PreviewPanel } from "./components/PreviewPanel";
import { SettingsSection } from "./components/SettingsSection";
import {
  ApiError,
  cancelJob,
  claimSeat,
  fetchAppConfig,
  fetchSeats,
  forceReleaseSeat,
  heartbeatSeat,
  loginSeat,
  releaseSeat,
  streamTranslation,
  updateSeatService,
} from "./lib/api";
import {
  artifactLabel,
  pickText,
  stageLabel,
  UI_COPY,
  UI_LOCALE_STORAGE_KEY,
} from "./lib/i18n";
import type {
  AppConfig,
  ConfigField,
  EngineUsageSummary,
  PreviewArtifactName,
  SeatSession,
  SeatSummary,
  ServiceConfig,
  SourceMode,
  TranslationResult,
  UiLocale,
} from "./lib/types";

type FieldValues = Record<string, string | number | boolean | null>;
type SettingsTab = "engine" | "translation" | "pdf";
type WorkspaceSection = "overview" | "source" | "setup" | "results";
type StatusKey =
  | "loading"
  | "intro"
  | "config_unavailable"
  | "submitting"
  | "source_missing_upload"
  | "source_missing_link"
  | "credentials_required"
  | "running"
  | "cancelled"
  | "failed"
  | "completed";

interface ProgressParts {
  current: number;
  total: number;
}

interface LanguageOption {
  label: string;
  value: string;
}

interface PreviewOption {
  name: PreviewArtifactName;
  label: string;
  url: string;
}

interface DownloadOption {
  name: string;
  label: string;
  url: string;
  filename: string;
  meta: string;
}

interface SeatInventory {
  seats: SeatSummary[];
  engineUsage: EngineUsageSummary[];
}

interface ValueTextProps {
  value: string;
  className?: string;
  as?: "p" | "span" | "strong";
}

const SEAT_IDENTITY_STORAGE_KEY = "paperflow-seat-identity";
const SEAT_SESSION_STORAGE_KEY = "paperflow-seat-session";

function ValueText({
  value,
  className,
  as = "strong",
}: ValueTextProps): ReactElement {
  const Component = as;
  return (
    <Component className={className ? `value-text ${className}` : "value-text"} title={value}>
      {value}
    </Component>
  );
}

interface LocaleSwitcherProps {
  label: string;
  locale: UiLocale;
  options: {
    en: string;
    zh: string;
  };
  className?: string;
  onChange: (nextLocale: UiLocale) => void;
}

function LocaleSwitcher({
  label,
  locale,
  options,
  className,
  onChange,
}: LocaleSwitcherProps): ReactElement {
  return (
    <section
      className={className ? `locale-card ${className}` : "locale-card"}
      aria-label={label}
    >
      <span className="locale-label">{label}</span>
      <div className="locale-toggle">
        <button
          className={locale === "en" ? "toggle-active" : undefined}
          type="button"
          onClick={() => onChange("en")}
        >
          {options.en}
        </button>
        <button
          className={locale === "zh" ? "toggle-active" : undefined}
          type="button"
          onClick={() => onChange("zh")}
        >
          {options.zh}
        </button>
      </div>
    </section>
  );
}

function readStoredIdentity(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(SEAT_IDENTITY_STORAGE_KEY) ?? "";
}

function persistIdentity(value: string): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!value) {
    window.localStorage.removeItem(SEAT_IDENTITY_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(SEAT_IDENTITY_STORAGE_KEY, value);
}

function readStoredSeatSession(): SeatSession | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(SEAT_SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<SeatSession>;
    if (
      !parsed.seatId ||
      !parsed.leaseToken ||
      !parsed.occupantName
    ) {
      return null;
    }
    return {
      seatId: parsed.seatId,
      leaseToken: parsed.leaseToken,
      occupantName: parsed.occupantName,
    };
  } catch {
    return null;
  }
}

function persistSeatSession(session: SeatSession | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!session) {
    window.localStorage.removeItem(SEAT_SESSION_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(SEAT_SESSION_STORAGE_KEY, JSON.stringify(session));
}

function buildSeatPlaceholders(seatCount: number): SeatSummary[] {
  return Array.from({ length: seatCount }, (_unused, index) => ({
    seat_id: String(index + 1),
    status: "available",
    occupant_name: null,
    selected_service: null,
    has_active_job: false,
    acquired_at: null,
    last_heartbeat_at: null,
    claimable: true,
    message: "Available",
  }));
}

function syncSeatList(
  seats: SeatSummary[],
  nextSeat: SeatSummary,
  seatCount: number,
): SeatSummary[] {
  const merged = seats.length ? [...seats] : buildSeatPlaceholders(seatCount);
  const index = merged.findIndex((seat) => seat.seat_id === nextSeat.seat_id);
  if (index === -1) {
    merged.push(nextSeat);
  } else {
    merged[index] = nextSeat;
  }
  return merged.sort(
    (left, right) => Number(left.seat_id) - Number(right.seat_id),
  );
}

function summarizeEngineUsage(seats: SeatSummary[]): EngineUsageSummary[] {
  const counts = new Map<string, number>();

  for (const seat of seats) {
    if (seat.status !== "occupied" || !seat.selected_service) {
      continue;
    }
    counts.set(
      seat.selected_service,
      (counts.get(seat.selected_service) ?? 0) + 1,
    );
  }

  return Array.from(counts.entries())
    .map(([service, active_seats]) => ({ service, active_seats }))
    .sort(
      (left, right) =>
        right.active_seats - left.active_seats ||
        left.service.localeCompare(right.service),
    );
}

function buildSeatInventory(
  seats: SeatSummary[],
  engineUsage: EngineUsageSummary[] = [],
): SeatInventory {
  return {
    seats,
    engineUsage: engineUsage.length ? engineUsage : summarizeEngineUsage(seats),
  };
}

function syncSeatInventory(
  inventory: SeatInventory,
  nextSeat: SeatSummary,
  seatCount: number,
): SeatInventory {
  return buildSeatInventory(
    syncSeatList(inventory.seats, nextSeat, seatCount),
  );
}

function formatSeatTimestamp(
  value: string | null | undefined,
  locale: UiLocale,
): string {
  if (!value) {
    return locale === "zh" ? "暂无" : "Not yet";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    month: "numeric",
    day: "numeric",
  }).format(parsed);
}

function readStoredLocale(): UiLocale | null {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(UI_LOCALE_STORAGE_KEY);
  if (stored === "en" || stored === "zh") {
    return stored;
  }
  return null;
}

function detectBrowserLocale(): UiLocale {
  if (
    typeof navigator !== "undefined" &&
    navigator.language.toLowerCase().startsWith("zh")
  ) {
    return "zh";
  }
  return "en";
}

function resolveLocale(defaultLocale?: UiLocale): UiLocale {
  return readStoredLocale() ?? defaultLocale ?? detectBrowserLocale();
}

function fillTemplate(
  template: string,
  values: Record<string, number | string>,
): string {
  return template.replace(/\{(\w+)\}/g, (_match, token: string) =>
    String(values[token] ?? ""),
  );
}

function buildDefaultValues(
  fields: ConfigField[],
  presetValues: FieldValues = {},
): FieldValues {
  const values: FieldValues = {};
  for (const field of fields) {
    const presetValue = presetValues[field.name];
    if (presetValue !== null && presetValue !== undefined) {
      values[field.name] = presetValue;
      continue;
    }
    if (field.default !== null && field.default !== undefined) {
      values[field.name] = field.default;
      continue;
    }
    if (field.type === "boolean") {
      values[field.name] = false;
      continue;
    }
    values[field.name] = "";
  }
  return values;
}

function buildSubmitValues(
  fields: ConfigField[],
  values: FieldValues,
): FieldValues {
  const payload: FieldValues = {};

  for (const field of fields) {
    const rawValue = values[field.name];

    if (typeof rawValue === "number" && Number.isNaN(rawValue)) {
      payload[field.name] =
        field.default !== null && field.default !== undefined
          ? field.default
          : null;
      continue;
    }

    if (rawValue === "") {
      if (field.default !== null && field.default !== undefined) {
        payload[field.name] = field.default;
        continue;
      }
      payload[field.name] = field.required ? "" : null;
      continue;
    }

    payload[field.name] = rawValue ?? null;
  }

  return payload;
}

function getServiceConfig(
  config: AppConfig,
  serviceName: string,
): ServiceConfig | undefined {
  return config.services.find((service) => service.name === serviceName);
}

function getSourcePreviewUrl(
  sourceMode: SourceMode,
  sourcePreviewUrl: string | null,
  fileUrl: string,
): string | null {
  if (sourceMode === "upload") {
    return sourcePreviewUrl;
  }
  const normalizedUrl = fileUrl.trim();
  return normalizedUrl || null;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getSourceArtifactUrl(
  result: TranslationResult | null,
  sourcePreview: string | null,
): string | null {
  return result?.artifacts?.source?.preview_url ?? sourcePreview;
}

function getDefaultPreviewArtifact(
  result: TranslationResult | null,
  sourcePreview: string | null,
): PreviewArtifactName | null {
  if (result?.artifacts?.mono?.url) {
    return "mono";
  }
  if (result?.artifacts?.dual?.url) {
    return "dual";
  }
  if (getSourceArtifactUrl(result, sourcePreview)) {
    return "source";
  }
  return null;
}

function buildPreviewOptions(
  result: TranslationResult | null,
  sourcePreview: string | null,
  locale: UiLocale,
): PreviewOption[] {
  const options: PreviewOption[] = [];
  const sourceArtifactUrl = getSourceArtifactUrl(result, sourcePreview);
  const monoPreviewUrl =
    result?.artifacts?.mono?.preview_url ?? result?.preview_url ?? null;
  const dualPreviewUrl = result?.artifacts?.dual?.preview_url ?? null;

  if (monoPreviewUrl) {
    options.push({
      name: "mono",
      label: artifactLabel("mono", locale),
      url: monoPreviewUrl,
    });
  }

  if (dualPreviewUrl) {
    options.push({
      name: "dual",
      label: artifactLabel("dual", locale),
      url: dualPreviewUrl,
    });
  }

  if (sourceArtifactUrl) {
    options.push({
      name: "source",
      label: artifactLabel("source", locale),
      url: sourceArtifactUrl,
    });
  }

  return options;
}

const DOWNLOAD_PRIORITY: Record<string, number> = {
  mono: 0,
  dual: 1,
  glossary: 2,
};

function buildDownloadOptions(
  result: TranslationResult | null,
  locale: UiLocale,
  readyText: string,
): DownloadOption[] {
  const artifacts = result?.artifacts ? Object.values(result.artifacts) : [];

  return artifacts
    .filter((artifact) => artifact.name !== "source")
    .sort((left, right) => {
      const leftRank = DOWNLOAD_PRIORITY[left.name] ?? Number.MAX_SAFE_INTEGER;
      const rightRank = DOWNLOAD_PRIORITY[right.name] ?? Number.MAX_SAFE_INTEGER;
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
      return left.filename.localeCompare(right.filename);
    })
    .map((artifact) => ({
      name: artifact.name,
      label: artifactLabel(artifact.name, locale),
      url: artifact.url,
      filename: artifact.filename,
      meta:
        artifact.size_bytes !== null && artifact.size_bytes !== undefined
          ? formatBytes(artifact.size_bytes)
          : readyText,
    }));
}

function normalizeLanguageCode(value: string): string {
  return value.trim().replace(/_/g, "-").toLowerCase();
}

function normalizeLanguageOptions(
  options: AppConfig["translation_languages"],
  locale: UiLocale,
): LanguageOption[] {
  const normalized: LanguageOption[] = [];
  const seen = new Set<string>();

  for (const option of options) {
    const value = option.value.trim();
    if (!value || seen.has(value)) {
      continue;
    }

    const localizedLabel = pickText(option.label, locale).trim();
    const englishLabel = option.label.en.trim();

    normalized.push({
      label: localizedLabel || englishLabel || value,
      value,
    });
    seen.add(value);
  }

  return normalized;
}

function chooseLanguageCode(
  options: Array<{ value: string }>,
  ...candidates: string[]
): string {
  for (const candidate of candidates) {
    const exact = options.find(
      (option) =>
        normalizeLanguageCode(option.value) ===
        normalizeLanguageCode(candidate),
    );
    if (exact) {
      return exact.value;
    }
  }

  for (const candidate of candidates) {
    const prefix = options.find((option) =>
      normalizeLanguageCode(option.value).startsWith(
        normalizeLanguageCode(candidate),
      ),
    );
    if (prefix) {
      return prefix.value;
    }
  }

  return options[0]?.value ?? "";
}

function languageLabel(options: LanguageOption[], value: string): string {
  return options.find((option) => option.value === value)?.label || value;
}

function buildRouteLabel(
  options: LanguageOption[],
  locale: UiLocale,
  langIn: string,
  langOut: string,
): string {
  const copy = UI_COPY[locale];
  return [
    languageLabel(options, langIn),
    copy.shared.routeJoiner,
    languageLabel(options, langOut),
  ].join(" ");
}

function buildPageScopeLabel(
  pdfValues: FieldValues,
  locale: UiLocale,
): string {
  const rawPages = String(pdfValues.pages ?? "").trim();
  return rawPages || UI_COPY[locale].shared.allPages;
}

function buildOutputModeLabel(
  pdfValues: FieldValues,
  locale: UiLocale,
): string {
  const copy = UI_COPY[locale];
  const monoDisabled = Boolean(pdfValues.no_mono);
  const dualDisabled = Boolean(pdfValues.no_dual);

  if (monoDisabled && dualDisabled) {
    return copy.shared.noOutput;
  }
  if (monoDisabled) {
    return copy.shared.dualOnly;
  }
  if (dualDisabled) {
    return copy.shared.monoOnly;
  }
  return copy.shared.monoAndDual;
}

function buildSourceLabel(
  sourceMode: SourceMode,
  sourceFile: File | null,
  fileUrl: string,
  locale: UiLocale,
): string {
  const copy = UI_COPY[locale];
  if (sourceMode === "upload") {
    return sourceFile?.name ?? copy.source.waitingUpload;
  }

  const normalizedUrl = fileUrl.trim();
  if (!normalizedUrl) {
    return copy.source.waitingLink;
  }

  try {
    return new URL(normalizedUrl).host;
  } catch {
    return normalizedUrl;
  }
}

function buildMissingSecretLabels(
  fields: ConfigField[],
  values: FieldValues,
  locale: UiLocale,
): string[] {
  return fields
    .filter((field) => field.password)
    .filter((field) => {
      const value = values[field.name];
      return value === null || value === undefined || value === "";
    })
    .map((field) => pickText(field.label, locale));
}

function workspaceStateLabel(
  statusKey: StatusKey,
  sourceReady: boolean,
  locale: UiLocale,
): string {
  const copy = UI_COPY[locale].launch;
  if (
    statusKey === "failed" ||
    statusKey === "config_unavailable" ||
    statusKey === "source_missing_upload" ||
    statusKey === "source_missing_link" ||
    statusKey === "credentials_required"
  ) {
    return copy.summaryNeedsAttention;
  }
  if (statusKey === "completed") {
    return copy.summaryCompleted;
  }
  if (statusKey === "running" || statusKey === "submitting") {
    return copy.summaryRunning;
  }
  if (sourceReady) {
    return copy.summaryReady;
  }
  return copy.summaryWaiting;
}

function statusMessage(
  statusKey: StatusKey,
  locale: UiLocale,
  missingSecretLabels: string[],
  parts: ProgressParts,
  result: TranslationResult | null,
): string {
  const copy = UI_COPY[locale].progress;

  if (statusKey === "config_unavailable") {
    return copy.configUnavailable;
  }
  if (statusKey === "submitting") {
    return copy.submitting;
  }
  if (statusKey === "running" && parts.total === 0 && parts.current === 0 && !result) {
    return copy.accepted;
  }
  if (statusKey === "source_missing_upload") {
    return copy.sourceMissingUpload;
  }
  if (statusKey === "source_missing_link") {
    return copy.sourceMissingLink;
  }
  if (statusKey === "credentials_required") {
    return `${copy.credentialsRequiredPrefix} ${missingSecretLabels.join(", ")}.`;
  }
  if (statusKey === "running") {
    if (parts.total > 1) {
      return fillTemplate(copy.runningMulti, {
        current: parts.current,
        total: parts.total,
      });
    }
    return copy.runningSingle;
  }
  if (statusKey === "cancelled") {
    return copy.cancelled;
  }
  if (statusKey === "failed") {
    return copy.failed;
  }
  if (statusKey === "completed") {
    if (result?.total_seconds) {
      return fillTemplate(copy.completedTimed, {
        seconds: result.total_seconds.toFixed(2),
      });
    }
    return copy.completed;
  }
  return copy.intro;
}

function statusTone(statusKey: StatusKey): "idle" | "active" | "error" | "done" {
  if (statusKey === "completed") {
    return "done";
  }
  if (statusKey === "running" || statusKey === "submitting") {
    return "active";
  }
  if (
    statusKey === "failed" ||
    statusKey === "config_unavailable" ||
    statusKey === "source_missing_upload" ||
    statusKey === "source_missing_link" ||
    statusKey === "credentials_required"
  ) {
    return "error";
  }
  return "idle";
}

function technicalNotes(
  locale: UiLocale,
  rawStage: string | null,
  details: string | null,
): string | null {
  const notes: string[] = [];
  if (locale === "zh" && rawStage) {
    notes.push(`${UI_COPY.zh.launch.backendStageLabel}: ${rawStage}`);
  }
  if (details) {
    notes.push(details);
  }
  return notes.length ? notes.join("\n\n") : null;
}

export default function App(): ReactElement {
  const [locale, setLocale] = useState<UiLocale>(() => resolveLocale());
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [identity, setIdentity] = useState(() => readStoredIdentity());
  const [identityInput, setIdentityInput] = useState(() => readStoredIdentity());
  const [seatSession, setSeatSession] = useState<SeatSession | null>(() =>
    readStoredSeatSession(),
  );
  const [seatInventory, setSeatInventory] = useState<SeatInventory>({
    seats: [],
    engineUsage: [],
  });
  const [seatError, setSeatError] = useState<string | null>(null);
  const [seatNotice, setSeatNotice] = useState<string | null>(null);
  const [seatActionId, setSeatActionId] = useState<string | null>(null);
  const [adminToken, setAdminToken] = useState("");
  const [sourceMode, setSourceMode] = useState<SourceMode>("upload");
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [fileUrl, setFileUrl] = useState("");
  const [sourcePreviewUrl, setSourcePreviewUrl] = useState<string | null>(null);
  const [service, setService] = useState("");
  const [langIn, setLangIn] = useState("en");
  const [langOut, setLangOut] = useState("zh-CN");
  const [translationValues, setTranslationValues] = useState<FieldValues>({});
  const [pdfValues, setPdfValues] = useState<FieldValues>({});
  const [engineValues, setEngineValues] = useState<FieldValues>({});
  const [activeTab, setActiveTab] = useState<SettingsTab>("engine");
  const [activeSection, setActiveSection] =
    useState<WorkspaceSection>("overview");
  const [progress, setProgress] = useState(0);
  const [parts, setParts] = useState<ProgressParts>({ current: 1, total: 1 });
  const [statusKey, setStatusKey] = useState<StatusKey>("loading");
  const [result, setResult] = useState<TranslationResult | null>(null);
  const [selectedPreviewArtifact, setSelectedPreviewArtifact] =
    useState<PreviewArtifactName | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [technicalDetails, setTechnicalDetails] = useState<string | null>(null);
  const [rawStage, setRawStage] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const serviceDraftsRef = useRef<Record<string, FieldValues>>({});

  const copy = UI_COPY[locale];
  const seatText =
    locale === "zh"
      ? {
          loginEyebrow: "共享入口",
          loginTitle: "先登记身份，再进入翻译席位",
          loginBody:
            "每个席位同一时刻只允许一位使用者进入。进入后会持续续租，退出或超时后自动释放。",
          loginLabel: "姓名或标识",
          loginPlaceholder: "例如：张三 / lab-1",
          loginAction: "进入大厅",
          loginHint: "这里只用于标识当前使用者，不是完整账号系统。",
          lobbyEyebrow: "席位大厅",
          lobbyTitle: "选择一个空闲席位",
          lobbyBody: "已被占用的席位不可进入，除非当前使用者退出或超时释放。",
          claimAction: "进入席位",
          occupiedAction: "有人在使用",
          staleAction: "正在释放",
          activeSeat: "当前席位",
          leaveSeat: "退出席位",
          switchIdentity: "切换身份",
          adminTitle: "管理释放",
          adminLabel: "管理口令",
          adminPlaceholder: "输入管理口令后可强制释放席位",
          adminAction: "强制释放",
          heartbeatLabel: "最近心跳",
          occupantLabel: "使用者",
          engineLabel: "引擎",
          engineUnset: "未声明",
          engineOverviewTitle: "席位引擎占用",
          engineOverviewBody:
            "这里展示每个席位最近声明使用的主翻译引擎，方便后来进入的人分流。",
          engineOverviewEmpty: "当前还没有席位声明使用某个引擎。",
          engineCountLabel: "使用席位",
          engineCountValue: "{count} 个席位",
          engineBusyNotice:
            "{count} 个席位正在使用 {service}，建议优先尝试其他引擎。",
          engineCrowdedNotice:
            "{count} 个席位正在使用 {service}，该引擎当前较拥挤。",
          jobLabel: "任务",
          jobIdle: "空闲",
          jobBusy: "运行中",
          seatAvailable: "空闲",
          seatOccupied: "使用中",
          seatStale: "超时释放中",
          releasedNotice: "席位已释放。",
          leaseLost: "席位已失效，请重新进入大厅。",
          claimFirst: "请先进入一个席位，再开始翻译。",
        }
      : {
          loginEyebrow: "Shared access",
          loginTitle: "Identify yourself before entering a seat",
          loginBody:
            "Each seat only allows one active user at a time. The browser keeps the lease alive until you leave or it times out.",
          loginLabel: "Name or label",
          loginPlaceholder: "For example: Alice / lab-1",
          loginAction: "Enter lobby",
          loginHint:
            "This is only used to identify the current occupant, not as a full account system.",
          lobbyEyebrow: "Seat lobby",
          lobbyTitle: "Choose an available seat",
          lobbyBody:
            "Occupied seats stay locked until the current user leaves or the lease times out.",
          claimAction: "Enter seat",
          occupiedAction: "In use",
          staleAction: "Releasing",
          activeSeat: "Current seat",
          leaveSeat: "Leave seat",
          switchIdentity: "Change identity",
          adminTitle: "Admin release",
          adminLabel: "Admin token",
          adminPlaceholder: "Enter the admin token to force-release a seat",
          adminAction: "Force release",
          heartbeatLabel: "Last heartbeat",
          occupantLabel: "Occupant",
          engineLabel: "Engine",
          engineUnset: "Not set",
          engineOverviewTitle: "Seat engine usage",
          engineOverviewBody:
            "Each seat shows the latest main translation engine it has claimed so new arrivals can spread out.",
          engineOverviewEmpty: "No seat has claimed an engine yet.",
          engineCountLabel: "Active seats",
          engineCountValue: "{count} seats",
          engineBusyNotice:
            "{count} seats are currently using {service}. Consider another engine first.",
          engineCrowdedNotice:
            "{count} seats are currently using {service}. This engine is crowded right now.",
          jobLabel: "Job",
          jobIdle: "Idle",
          jobBusy: "Active",
          seatAvailable: "Available",
          seatOccupied: "In use",
          seatStale: "Releasing after timeout",
          releasedNotice: "Seat released.",
          leaseLost: "The seat lease expired. Return to the lobby and enter again.",
          claimFirst: "Claim a seat before starting a translation.",
        };

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(UI_LOCALE_STORAGE_KEY, locale);
    }
  }, [locale]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap(): Promise<void> {
      try {
        const nextConfig = await fetchAppConfig();
        const nextLocale = resolveLocale(nextConfig.default_locale);
        const nextLanguageOptions = normalizeLanguageOptions(
          nextConfig.translation_languages,
          nextLocale,
        );
        const initialSeatInventory = await fetchSeats()
          .then((payload) =>
            buildSeatInventory(payload.seats, payload.engine_usage),
          )
          .catch(() =>
            buildSeatInventory(
              buildSeatPlaceholders(nextConfig.seat_management.seat_count),
            ),
          );
        const storedIdentity = readStoredIdentity();
        const storedSession = readStoredSeatSession();
        let restoredSession: SeatSession | null = null;
        let restoredSeat: SeatSummary | null = null;

        if (storedSession) {
          try {
            const heartbeat = await heartbeatSeat(
              storedSession.seatId,
              storedSession.leaseToken,
            );
            restoredSeat = heartbeat.seat;
            restoredSession = {
              seatId: heartbeat.seat.seat_id,
              leaseToken: heartbeat.lease_token,
              occupantName:
                heartbeat.seat.occupant_name ?? storedSession.occupantName,
            };
            persistSeatSession(restoredSession);
          } catch {
            persistSeatSession(null);
          }
        }

        if (cancelled) {
          return;
        }

        const initialService =
          restoredSeat?.selected_service ?? nextConfig.default_service;

        startTransition(() => {
          setLocale(nextLocale);
          setConfig(nextConfig);
          setSeatInventory(
            restoredSession
              ? syncSeatInventory(
                  initialSeatInventory,
                  restoredSeat ?? initialSeatInventory.seats.find(
                    (seat) => seat.seat_id === restoredSession?.seatId,
                  ) ?? {
                    seat_id: restoredSession.seatId,
                    status: "occupied",
                    occupant_name: restoredSession.occupantName,
                    selected_service: null,
                    has_active_job: false,
                    acquired_at: null,
                    last_heartbeat_at: null,
                    claimable: false,
                    message: "In use",
                  },
                  nextConfig.seat_management.seat_count,
                )
              : initialSeatInventory,
          );
          setIdentity(restoredSession?.occupantName ?? storedIdentity);
          setIdentityInput(restoredSession?.occupantName ?? storedIdentity);
          setSeatSession(restoredSession);
          setService(initialService);
          setLangIn(chooseLanguageCode(nextLanguageOptions, "en"));
          setLangOut(chooseLanguageCode(nextLanguageOptions, "zh-CN", "zh"));
          setTranslationValues(buildDefaultValues(nextConfig.translation_fields));
          setPdfValues(buildDefaultValues(nextConfig.pdf_fields));
          setEngineValues(
            buildDefaultValues(
              getServiceConfig(nextConfig, initialService)?.fields ?? [],
            ),
          );
          setStatusKey("intro");
        });
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        setErrorCode("config_unavailable");
        setTechnicalDetails((loadError as Error).message);
        setStatusKey("config_unavailable");
      }
    }

    void bootstrap();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sourceFile) {
      setSourcePreviewUrl(null);
      return;
    }

    const objectUrl = URL.createObjectURL(sourceFile);
    setSourcePreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [sourceFile]);

  useEffect(() => {
    if (!config) {
      return;
    }

    let cancelled = false;
    async function refreshSeats(): Promise<void> {
      try {
        const nextInventory = await fetchSeats();
        if (!cancelled) {
          setSeatInventory(
            buildSeatInventory(nextInventory.seats, nextInventory.engine_usage),
          );
        }
      } catch (error) {
        if (!cancelled) {
          setSeatError((error as Error).message);
        }
      }
    }

    void refreshSeats();
    const intervalId = window.setInterval(() => {
      void refreshSeats();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [config]);

  useEffect(() => {
    if (!config || !seatSession) {
      return;
    }

    const activeSession = seatSession;
    const seatCount = config.seat_management.seat_count;
    let cancelled = false;
    async function sendHeartbeat(): Promise<void> {
      try {
        const response = await heartbeatSeat(
          activeSession.seatId,
          activeSession.leaseToken,
        );
        if (cancelled) {
          return;
        }
        setSeatInventory((currentInventory) =>
          syncSeatInventory(
            currentInventory,
            response.seat,
            seatCount,
          ),
        );
      } catch (error) {
        if (!cancelled) {
          void handleSeatLeaseLost((error as Error).message);
        }
      }
    }

    const intervalId = window.setInterval(() => {
      void sendHeartbeat();
    }, config.seat_management.heartbeat_interval_seconds * 1000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [config, seatSession]);

  useEffect(() => {
    if (!config || !seatSession || !service || isRunning) {
      return;
    }

    const activeConfig = config;
    const activeSession = seatSession;
    const activeSeat = seatInventory.seats.find(
      (seat) => seat.seat_id === activeSession.seatId,
    );
    if (activeSeat?.selected_service === service) {
      return;
    }

    let cancelled = false;
    async function syncSelectedService(): Promise<void> {
      try {
        const nextSeat = await updateSeatService(
          activeSession.seatId,
          activeSession.leaseToken,
          service,
        );
        if (!cancelled) {
          setSeatInventory((currentInventory) =>
            syncSeatInventory(
              currentInventory,
              nextSeat,
              activeConfig.seat_management.seat_count,
            ),
          );
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (
          error instanceof ApiError &&
          (error.code === "seat_lease_invalid" ||
            error.code === "seat_lease_expired" ||
            error.code === "seat_not_found")
        ) {
          await handleSeatLeaseLost(error.message);
          return;
        }
        setSeatError((error as Error).message);
      }
    }

    void syncSelectedService();
    return () => {
      cancelled = true;
    };
  }, [config, isRunning, seatInventory.seats, seatSession, service]);

  useEffect(() => {
    if (!config) {
      return;
    }

    const nextOptions = normalizeLanguageOptions(
      config.translation_languages,
      locale,
    );
    if (!nextOptions.length) {
      return;
    }

    const nextLangIn = chooseLanguageCode(nextOptions, langIn, "en");
    const nextLangOut = chooseLanguageCode(nextOptions, langOut, "zh-CN", "zh");

    if (nextLangIn !== langIn) {
      setLangIn(nextLangIn);
    }
    if (nextLangOut !== langOut) {
      setLangOut(nextLangOut);
    }
  }, [config, langIn, langOut, locale]);

  useEffect(() => {
    if (!service) {
      return;
    }
    serviceDraftsRef.current[service] = engineValues;
  }, [engineValues, service]);

  function updateFieldValues(
    setter: Dispatch<SetStateAction<FieldValues>>,
    name: string,
    value: string | number | boolean,
  ): void {
    setter((currentValues) => ({
      ...currentValues,
      [name]: value,
    }));
  }

  if (!config) {
    return (
      <div className="loading-shell">
        <div className="loading-card">
          <p className="section-eyebrow">{copy.loading.eyebrow}</p>
          <h1>{copy.loading.title}</h1>
          <p>{copy.loading.body}</p>
          {statusKey === "config_unavailable" ? (
            <details className="technical-details">
              <summary>{copy.launch.technicalDetails}</summary>
              <pre>{technicalDetails ?? copy.progress.configUnavailable}</pre>
            </details>
          ) : null}
        </div>
      </div>
    );
  }

  const appConfig = config;
  const seats = seatInventory.seats;
  const engineUsage = seatInventory.engineUsage;
  const languageOptions = normalizeLanguageOptions(
    appConfig.translation_languages,
    locale,
  );
  const activeService =
    getServiceConfig(appConfig, service) ?? appConfig.services[0];
  const sourcePreview = getSourcePreviewUrl(
    sourceMode,
    sourcePreviewUrl,
    fileUrl,
  );
  const previewOptions = buildPreviewOptions(result, sourcePreview, locale);
  const defaultPreviewArtifact = getDefaultPreviewArtifact(result, sourcePreview);
  const activePreviewArtifact = previewOptions.some(
    (option) => option.name === selectedPreviewArtifact,
  )
    ? selectedPreviewArtifact
    : defaultPreviewArtifact;
  const activePreviewOption =
    previewOptions.find((option) => option.name === activePreviewArtifact) ?? null;
  const previewTarget = activePreviewOption?.url ?? null;
  const downloadOptions = buildDownloadOptions(result, locale, copy.downloads.ready);
  const isTranslatedPreview =
    activePreviewArtifact === "mono" || activePreviewArtifact === "dual";
  const selectedFileSize = sourceFile ? formatBytes(sourceFile.size) : null;
  const missingSecretLabels = buildMissingSecretLabels(
    activeService?.fields ?? [],
    engineValues,
    locale,
  );
  const sourceReady =
    sourceMode === "upload" ? Boolean(sourceFile) : Boolean(fileUrl.trim());
  const sourceLabel = buildSourceLabel(sourceMode, sourceFile, fileUrl, locale);
  const routeLabel = buildRouteLabel(languageOptions, locale, langIn, langOut);
  const pageScopeLabel = buildPageScopeLabel(pdfValues, locale);
  const outputModeLabel = buildOutputModeLabel(pdfValues, locale);
  const currentWorkspaceState = workspaceStateLabel(
    statusKey,
    sourceReady,
    locale,
  );
  const currentStatusTone = statusTone(statusKey);
  const currentMessage = statusMessage(
    statusKey,
    locale,
    missingSecretLabels,
    parts,
    result,
  );
  const currentStage =
    statusKey === "running"
      ? stageLabel(rawStage, locale)
      : currentWorkspaceState;
  const technicalState = technicalNotes(locale, rawStage, technicalDetails);
  const sourceTransportLabel =
    sourceMode === "upload"
      ? copy.source.transportUpload
      : copy.source.transportLink;
  const langInLabel = languageLabel(languageOptions, langIn);
  const langOutLabel = languageLabel(languageOptions, langOut);
  const activeTabFields =
    activeTab === "engine"
      ? activeService?.fields ?? []
      : activeTab === "translation"
        ? appConfig.translation_fields
        : appConfig.pdf_fields;
  const currentServiceSeatCount =
    engineUsage.find((item) => item.service === service)?.active_seats ?? 0;
  const currentServiceNotice =
    currentServiceSeatCount >= 3
      ? fillTemplate(seatText.engineCrowdedNotice, {
          count: currentServiceSeatCount,
          service,
        })
      : currentServiceSeatCount >= 2
        ? fillTemplate(seatText.engineBusyNotice, {
            count: currentServiceSeatCount,
            service,
          })
        : null;

  function handleServiceChange(nextService: string): void {
    serviceDraftsRef.current[service] = engineValues;
    setService(nextService);
    const nextServiceConfig = getServiceConfig(appConfig, nextService);
    setEngineValues(
      serviceDraftsRef.current[nextService] ??
        buildDefaultValues(nextServiceConfig?.fields ?? []),
    );
  }

  function resetRunState(nextStatus: StatusKey): void {
    setErrorCode(null);
    setTechnicalDetails(null);
    setRawStage(null);
    setResult(null);
    setProgress(0);
    setParts({ current: 1, total: 1 });
    setStatusKey(nextStatus);
  }

  function resetWorkspaceState(): void {
    const initialService = appConfig.default_service;
    serviceDraftsRef.current = {};
    setSourceMode("upload");
    setSourceFile(null);
    setFileUrl("");
    setSourcePreviewUrl(null);
    setService(initialService);
    setTranslationValues(buildDefaultValues(appConfig.translation_fields));
    setPdfValues(buildDefaultValues(appConfig.pdf_fields));
    setEngineValues(
      buildDefaultValues(
        getServiceConfig(appConfig, initialService)?.fields ?? [],
      ),
    );
    setActiveTab("engine");
    setActiveSection("overview");
    setSelectedPreviewArtifact(null);
    setCurrentJobId(null);
    setIsRunning(false);
    controllerRef.current = null;
    resetRunState("intro");
  }

  async function refreshSeatInventory(): Promise<void> {
    try {
      const payload = await fetchSeats();
      setSeatInventory(buildSeatInventory(payload.seats, payload.engine_usage));
    } catch (error) {
      setSeatError((error as Error).message);
    }
  }

  async function handleSeatLeaseLost(message: string): Promise<void> {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setCurrentJobId(null);
    setIsRunning(false);
    setSeatNotice(null);
    setSeatError(message || seatText.leaseLost);
    persistSeatSession(null);
    setSeatSession(null);
    resetRunState("intro");
    await refreshSeatInventory();
  }

  async function handleIdentitySubmit(): Promise<void> {
    try {
      const payload = await loginSeat(identityInput);
      persistIdentity(payload.display_name);
      setIdentity(payload.display_name);
      setIdentityInput(payload.display_name);
      setSeatError(null);
      setSeatNotice(null);
      await refreshSeatInventory();
    } catch (error) {
      setSeatError((error as Error).message);
    }
  }

  function handleIdentityReset(): void {
    persistIdentity("");
    persistSeatSession(null);
    setIdentity("");
    setIdentityInput("");
    setSeatSession(null);
    setSeatError(null);
    setSeatNotice(null);
    resetWorkspaceState();
  }

  async function handleSeatClaim(seatId: string): Promise<void> {
    if (!identity) {
      setSeatError(seatText.claimFirst);
      return;
    }
    setSeatActionId(seatId);
    try {
      const response = await claimSeat(seatId, identity);
      const nextSession: SeatSession = {
        seatId: response.seat.seat_id,
        leaseToken: response.lease_token,
        occupantName: response.seat.occupant_name ?? identity,
      };
      persistSeatSession(nextSession);
      setSeatSession(nextSession);
      setSeatInventory((currentInventory) =>
        syncSeatInventory(
          currentInventory,
          response.seat,
          appConfig.seat_management.seat_count,
        ),
      );
      setSeatError(null);
      setSeatNotice(null);
      resetWorkspaceState();
    } catch (error) {
      setSeatError((error as Error).message);
      await refreshSeatInventory();
    } finally {
      setSeatActionId(null);
    }
  }

  async function handleLeaveSeat(): Promise<void> {
    if (!seatSession) {
      return;
    }
    const activeSession = seatSession;
    setSeatActionId(activeSession.seatId);
    controllerRef.current?.abort();
    controllerRef.current = null;
    try {
      const releasedSeat = await releaseSeat(
        activeSession.seatId,
        activeSession.leaseToken,
      );
      persistSeatSession(null);
      setSeatSession(null);
      setSeatInventory((currentInventory) =>
        syncSeatInventory(
          currentInventory,
          releasedSeat,
          appConfig.seat_management.seat_count,
        ),
      );
      setSeatError(null);
      setSeatNotice(seatText.releasedNotice);
      resetWorkspaceState();
    } catch (error) {
      if (
        error instanceof ApiError &&
        (error.code === "seat_lease_invalid" ||
          error.code === "seat_lease_expired" ||
          error.code === "seat_not_found")
      ) {
        await handleSeatLeaseLost(error.message);
      } else {
        setSeatError((error as Error).message);
      }
    } finally {
      setSeatActionId(null);
    }
  }

  async function handleForceSeatRelease(seatId: string): Promise<void> {
    if (!adminToken.trim()) {
      setSeatError(seatText.adminPlaceholder);
      return;
    }
    setSeatActionId(seatId);
    try {
      const releasedSeat = await forceReleaseSeat(seatId, adminToken.trim());
      setSeatInventory((currentInventory) =>
        syncSeatInventory(
          currentInventory,
          releasedSeat,
          appConfig.seat_management.seat_count,
        ),
      );
      if (seatSession?.seatId === seatId) {
        await handleSeatLeaseLost(seatText.leaseLost);
      } else {
        setSeatError(null);
        setSeatNotice(seatText.releasedNotice);
      }
    } catch (error) {
      setSeatError((error as Error).message);
    } finally {
      setSeatActionId(null);
    }
  }

  async function handleTranslate(): Promise<void> {
    if (isRunning) {
      return;
    }

    if (!seatSession) {
      setSeatError(seatText.claimFirst);
      return;
    }

    resetRunState("submitting");
    setSelectedPreviewArtifact(sourcePreview ? "source" : null);

    if (sourceMode === "upload" && !sourceFile) {
      setActiveSection("source");
      setStatusKey("source_missing_upload");
      return;
    }

    if (sourceMode === "link" && !fileUrl.trim()) {
      setActiveSection("source");
      setStatusKey("source_missing_link");
      return;
    }

    if (service !== "SiliconFlowFree" && missingSecretLabels.length > 0) {
      setActiveSection("setup");
      setStatusKey("credentials_required");
      return;
    }

    const controller = new AbortController();
    controllerRef.current = controller;
    setIsRunning(true);
    setActiveSection("overview");

    try {
      await streamTranslation(
        {
          sourceMode,
          file: sourceFile,
          fileUrl,
          service,
          seatId: seatSession.seatId,
          leaseToken: seatSession.leaseToken,
          uiLocale: locale,
          langIn,
          langOut,
          translation: buildSubmitValues(
            appConfig.translation_fields,
            translationValues,
          ),
          pdf: buildSubmitValues(appConfig.pdf_fields, pdfValues),
          engineSettings: buildSubmitValues(
            activeService?.fields ?? [],
            engineValues,
          ),
        },
        controller.signal,
        (event) => {
          if (event.type === "status") {
            setCurrentJobId(event.job.job_id ?? null);
            setStatusKey("running");
            setRawStage(
              event.job.status === "queued"
                ? "Queued"
                : "Waiting for translation engine",
            );
            setProgress(0);
            setParts({ current: 0, total: 0 });
            return;
          }

          if (event.type === "progress") {
            setStatusKey("running");
            setRawStage(event.stage ?? null);
            setProgress((event.overall_progress ?? 0) / 100);
            setParts({
              current: event.part_index ?? 1,
              total: event.total_parts ?? 1,
            });
            return;
          }

          if (event.type === "error") {
            const nextErrorCode = event.error.code ?? "translation_failed";
            setCurrentJobId(null);
            setErrorCode(nextErrorCode);
            setTechnicalDetails(
              [event.error.message, event.error.hint]
                .filter((value) => Boolean(value))
                .join("\n"),
            );
            setStatusKey(nextErrorCode === "job_cancelled" ? "cancelled" : "failed");
            setIsRunning(false);
            controllerRef.current = null;
            return;
          }

          if (event.type !== "finish") {
            return;
          }

          setResult(event.result);
          setCurrentJobId(null);
          setSelectedPreviewArtifact(
            getDefaultPreviewArtifact(event.result, sourcePreview),
          );
          setProgress(1);
          setStatusKey("completed");
          setIsRunning(false);
          controllerRef.current = null;
          setActiveSection("results");
        },
      );
    } catch (streamError) {
      if ((streamError as DOMException).name === "AbortError") {
        setStatusKey("cancelled");
        setCurrentJobId(null);
      } else if (
        streamError instanceof ApiError &&
        (streamError.code === "seat_lease_invalid" ||
          streamError.code === "seat_lease_expired" ||
          streamError.code === "seat_required")
      ) {
        await handleSeatLeaseLost(streamError.message);
      } else {
        setErrorCode("request_failed");
        setTechnicalDetails((streamError as Error).message);
        setStatusKey("failed");
        setCurrentJobId(null);
      }
      setIsRunning(false);
      controllerRef.current = null;
    }
  }

  async function handleCancel(): Promise<void> {
    if (currentJobId) {
      try {
        await cancelJob(currentJobId);
      } catch (error) {
        setTechnicalDetails((error as Error).message);
      }
    }
    controllerRef.current?.abort();
    controllerRef.current = null;
    setCurrentJobId(null);
  }

  function handleSwapLanguages(): void {
    setLangIn(langOut);
    setLangOut(langIn);
  }

  function handlePreviewSelect(name: PreviewArtifactName): void {
    setSelectedPreviewArtifact(name);
  }

  const visibleSeats = seats.length
    ? seats
    : buildSeatPlaceholders(appConfig.seat_management.seat_count);

  function seatStatusLabelFor(seat: SeatSummary): string {
    if (seat.status === "stale") {
      return seatText.seatStale;
    }
    if (seat.status === "occupied") {
      return seatText.seatOccupied;
    }
    return seatText.seatAvailable;
  }

  if (!identity) {
    return (
      <div className="seat-shell">
        <div className="seat-auth-card">
          <LocaleSwitcher
            className="locale-card-compact seat-locale-card"
            label={copy.localeLabel}
            locale={locale}
            options={copy.localeOptions}
            onChange={setLocale}
          />

          <p className="section-eyebrow">{seatText.loginEyebrow}</p>
          <h1>{seatText.loginTitle}</h1>
          <p className="section-copy">{seatText.loginBody}</p>

          <label className="field">
            <span className="field-label">{seatText.loginLabel}</span>
            <input
              className="field-input"
              placeholder={seatText.loginPlaceholder}
              type="text"
              value={identityInput}
              onChange={(event) => setIdentityInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void handleIdentitySubmit();
                }
              }}
            />
          </label>

          <div className="action-row">
            <button
              className="primary-button"
              type="button"
              onClick={() => void handleIdentitySubmit()}
            >
              {seatText.loginAction}
            </button>
          </div>

          <p className="section-copy">{seatText.loginHint}</p>
          {seatError ? <div className="status-callout">{seatError}</div> : null}
        </div>
      </div>
    );
  }

  if (!seatSession) {
    return (
      <div className="seat-shell">
        <div className="seat-lobby-shell">
          <header className="seat-lobby-header">
            <div>
              <p className="section-eyebrow">{seatText.lobbyEyebrow}</p>
              <h1>{seatText.lobbyTitle}</h1>
              <p className="section-copy">{seatText.lobbyBody}</p>
            </div>

            <div className="seat-lobby-toolbar">
              <span className="seat-identity-chip">{identity}</span>
              <button
                className="secondary-button"
                type="button"
                onClick={handleIdentityReset}
              >
                {seatText.switchIdentity}
              </button>
              <LocaleSwitcher
                className="locale-card-compact seat-locale-card"
                label={copy.localeLabel}
                locale={locale}
                options={copy.localeOptions}
                onChange={setLocale}
              />
            </div>
          </header>

          {seatNotice ? <div className="seat-notice">{seatNotice}</div> : null}
          {seatError ? <div className="status-callout">{seatError}</div> : null}

          <section className="seat-grid">
            {visibleSeats.map((seat) => (
              <article
                key={seat.seat_id}
                className={`seat-card seat-card-${seat.status}`}
              >
                <div className="seat-card-header">
                  <div>
                    <span className="hero-card-label">Seat {seat.seat_id}</span>
                    <h3>{seatStatusLabelFor(seat)}</h3>
                  </div>
                  <span className="seat-card-badge">{seat.message}</span>
                </div>

                <div className="meta-grid seat-meta-grid">
                  <div className="meta-item">
                    <span className="meta-label">{seatText.occupantLabel}</span>
                    <ValueText
                      value={seat.occupant_name ?? seatText.seatAvailable}
                    />
                  </div>
                  <div className="meta-item">
                    <span className="meta-label">{seatText.engineLabel}</span>
                    <ValueText
                      value={seat.selected_service ?? seatText.engineUnset}
                    />
                  </div>
                  <div className="meta-item">
                    <span className="meta-label">{seatText.heartbeatLabel}</span>
                    <ValueText
                      value={formatSeatTimestamp(seat.last_heartbeat_at, locale)}
                    />
                  </div>
                  <div className="meta-item">
                    <span className="meta-label">{seatText.jobLabel}</span>
                    <ValueText
                      value={seat.has_active_job ? seatText.jobBusy : seatText.jobIdle}
                    />
                  </div>
                </div>

                <button
                  className="primary-button seat-enter-button"
                  disabled={!seat.claimable || seatActionId !== null}
                  type="button"
                  onClick={() => void handleSeatClaim(seat.seat_id)}
                >
                  {seat.status === "available"
                    ? seatText.claimAction
                    : seat.status === "stale"
                      ? seatText.staleAction
                      : seatText.occupiedAction}
                </button>

                {appConfig.seat_management.admin_force_release_enabled ? (
                  <button
                    className="secondary-button seat-admin-button"
                    disabled={seatActionId !== null}
                    type="button"
                    onClick={() => void handleForceSeatRelease(seat.seat_id)}
                  >
                    {seatText.adminAction}
                  </button>
                ) : null}
              </article>
            ))}
          </section>

          {appConfig.seat_management.admin_force_release_enabled ? (
            <section className="panel-card seat-admin-panel">
              <div className="section-heading section-heading-compact">
                <p className="section-eyebrow">{seatText.adminTitle}</p>
                <h3>{seatText.adminTitle}</h3>
              </div>
              <label className="field">
                <span className="field-label">{seatText.adminLabel}</span>
                <input
                  className="field-input"
                  placeholder={seatText.adminPlaceholder}
                  type="password"
                  value={adminToken}
                  onChange={(event) => setAdminToken(event.target.value)}
                />
              </label>
            </section>
          ) : null}
        </div>
      </div>
    );
  }

  const noEngineFields = activeTab === "engine" && !activeTabFields.length;
  const settingsEmptyMessage = noEngineFields
    ? copy.settings.engineEmptyBody
    : copy.settings.emptyBody;
  const settingsEmptyHint = noEngineFields
    ? copy.settings.engineEmptyHint
    : undefined;
  const progressPercentLabel = `${Math.max(
    0,
    Math.min(100, Math.round(progress * 100)),
  )}%`;
  const downloadCount = result?.artifacts
    ? Object.values(result.artifacts).filter(
        (artifact) => artifact.name !== "source",
      ).length
    : 0;
  const previewStateLabel =
    activePreviewArtifact && previewTarget
      ? artifactLabel(activePreviewArtifact, locale)
      : copy.source.previewWaiting;
  const currentErrorTitle =
    statusKey === "failed" || statusKey === "config_unavailable"
      ? copy.progress.errorTitles[
          (errorCode as keyof typeof copy.progress.errorTitles) ?? "default"
        ] ?? copy.progress.errorTitles.default
      : null;
  const workspaceCopy = copy.workspace;
  const routeCompactLabel = `${langInLabel} → ${langOutLabel}`;
  const workspaceSections: Array<{
    id: WorkspaceSection;
    key: string;
    label: string;
    detail: string;
    badge: string | null;
  }> = [
    {
      id: "overview",
      key: "01",
      label: workspaceCopy.nav.overview,
      detail: currentWorkspaceState,
      badge: currentStatusTone === "active" ? progressPercentLabel : null,
    },
    {
      id: "source",
      key: "02",
      label: workspaceCopy.nav.source,
      detail: sourceTransportLabel,
      badge: sourceReady ? copy.source.previewReady : null,
    },
    {
      id: "setup",
      key: "03",
      label: workspaceCopy.nav.setup,
      detail: copy.settings.tabs[activeTab],
      badge: activeService?.fields.length ? String(activeService.fields.length) : null,
    },
    {
      id: "results",
      key: "04",
      label: workspaceCopy.nav.results,
      detail: downloadCount
        ? `${downloadCount} ${workspaceCopy.filesLabel}`
        : previewStateLabel,
      badge: downloadCount ? String(downloadCount) : null,
    },
  ];
  const mobileSections = workspaceSections.map((section) => ({
    ...section,
    mobileLabel:
      section.id === "overview"
        ? locale === "zh"
          ? "总览"
          : "Overview"
        : section.id === "source"
          ? locale === "zh"
            ? "来源"
            : "Source"
          : section.id === "setup"
            ? locale === "zh"
              ? "设置"
              : "Setup"
            : locale === "zh"
              ? "结果"
              : "Results",
  }));
  const workspaceHeaderTitle =
    activeSection === "overview"
      ? workspaceCopy.titles.overview
      : activeSection === "source"
        ? workspaceCopy.titles.source
        : activeSection === "setup"
          ? workspaceCopy.titles.setup
          : workspaceCopy.titles.results;
  const workspaceHeaderBody =
    activeSection === "overview"
      ? workspaceCopy.descriptions.overview
      : activeSection === "source"
        ? workspaceCopy.descriptions.source
        : activeSection === "setup"
          ? workspaceCopy.descriptions.setup
          : workspaceCopy.descriptions.results;
  const activeWorkspaceSection =
    workspaceSections.find((section) => section.id === activeSection) ??
    workspaceSections[0];

  function renderRouteVisual(extraClassName?: string): ReactElement {
    return (
      <div
        className={`route-visual${extraClassName ? ` ${extraClassName}` : ""}`}
        aria-label={routeLabel}
      >
        <span className="route-visual-chip">{langInLabel}</span>
        <span className="route-visual-arrow" aria-hidden="true">
          →
        </span>
        <span className="route-visual-chip">{langOutLabel}</span>
      </div>
    );
  }

  const sourcePanel = (
    <section className="panel-card source-card workspace-panel">
      <div className="route-overview source-overview">
        <div className="overview-route-shell source-route-shell">
          <span className="hero-card-label">{copy.launch.routeLabel}</span>
          {renderRouteVisual()}
        </div>

        <div className="service-banner source-service-note">
          <span className="service-banner-title">{copy.source.transportLabel}</span>
          <p>
            {sourceTransportLabel}
            {" · "}
            {copy.source.safetyValue}
          </p>
        </div>
      </div>

      <div className="mode-toggle">
        <button
          className={sourceMode === "upload" ? "mode-active" : undefined}
          type="button"
          onClick={() => setSourceMode("upload")}
        >
          {copy.source.uploadMode}
        </button>
        <button
          className={sourceMode === "link" ? "mode-active" : undefined}
          type="button"
          onClick={() => setSourceMode("link")}
        >
          {copy.source.linkMode}
        </button>
      </div>

      {sourceMode === "upload" ? (
        <label className="upload-dropzone">
          <span className="upload-title">
            {sourceFile?.name ?? copy.source.uploadEmptyTitle}
          </span>
          <span className="upload-copy">
            {sourceFile
              ? `${copy.source.uploadSelectedPrefix}${selectedFileSize ? `, ${selectedFileSize}` : ""}.`
              : copy.source.uploadEmptyBody}
          </span>
          <span className="upload-cta">{copy.source.uploadMode}</span>
          <input
            accept="application/pdf,.pdf"
            type="file"
            onChange={(event) => {
              setSourceFile(event.target.files?.[0] ?? null);
              setStatusKey("intro");
            }}
          />
        </label>
      ) : (
        <label className="field">
          <span className="field-label">{copy.source.directUrlLabel}</span>
          <input
            className="field-input"
            placeholder={copy.source.directUrlPlaceholder}
            type="url"
            value={fileUrl}
            onChange={(event) => {
              setFileUrl(event.target.value);
              setStatusKey("intro");
            }}
          />
          <p className="field-hint">{copy.source.directUrlHint}</p>
        </label>
      )}

      <div className="meta-grid source-meta-grid">
        <div className="meta-item">
          <span className="meta-label">{copy.source.previewLabel}</span>
          <ValueText value={previewStateLabel} />
        </div>
        <div className="meta-item">
          <span className="meta-label">{copy.source.transportLabel}</span>
          <ValueText value={sourceTransportLabel} />
        </div>
        <div className="meta-item">
          <span className="meta-label">{copy.source.safetyLabel}</span>
          <ValueText value={copy.source.safetyValue} />
        </div>
      </div>
    </section>
  );

  const setupPanel = (
    <section className="panel-card setup-panel workspace-panel">
      <div className="setup-composer">
        <section className="setup-primary-panel">
          <div className="setup-primary-grid">
            <div className="setup-language-panel">
              <div className="setup-panel-header">
                <span className="hero-card-label">{copy.launch.routeLabel}</span>
                <strong>{copy.route.title}</strong>
                <p>{copy.route.body}</p>
              </div>

              <div className="route-language-grid">
                <label className="field">
                  <span className="field-label">{copy.route.sourceLanguage}</span>
                  <select
                    className="field-input"
                    value={langIn}
                    onChange={(event) => setLangIn(event.target.value)}
                  >
                    {languageOptions.map((option) => (
                      <option key={`from-${option.value}`} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <button
                  className="route-swap-button"
                  type="button"
                  onClick={handleSwapLanguages}
                >
                  <span aria-hidden="true">⇄</span>
                  <span>{copy.route.swapLanguages}</span>
                </button>

                <label className="field">
                  <span className="field-label">{copy.route.targetLanguage}</span>
                  <select
                    className="field-input"
                    value={langOut}
                    onChange={(event) => setLangOut(event.target.value)}
                  >
                    {languageOptions.map((option) => (
                      <option key={`to-${option.value}`} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="setup-service-panel">
              <div className="setup-panel-header">
                <span className="hero-card-label">{copy.launch.engineLabel}</span>
                <ValueText className="value-text-wrap" value={service} />
                <p>
                  {service === "SiliconFlowFree"
                    ? copy.route.freeEngineBody
                    : copy.route.privateEngineBody}
                </p>
              </div>

              <label className="field route-service-field route-service-field-full">
                <span className="field-label">{copy.route.service}</span>
                <select
                  className="field-input"
                  value={service}
                  onChange={(event) => handleServiceChange(event.target.value)}
                >
                  {appConfig.services.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>

              {currentServiceNotice ? (
                <div className="status-callout engine-usage-alert">
                  <strong className="value-text value-text-wrap">{service}</strong>
                  <p className="section-copy">{currentServiceNotice}</p>
                </div>
              ) : null}
            </div>
          </div>

          <div className="engine-usage-shell">
            <div className="engine-usage-head">
              <strong>{seatText.engineOverviewTitle}</strong>
              <p>{seatText.engineOverviewBody}</p>
            </div>

            {engineUsage.length ? (
              <div className="engine-usage-list" aria-label={seatText.engineOverviewTitle}>
                {engineUsage.map((item) => (
                  <article
                    key={item.service}
                    className={`engine-usage-row${item.service === service ? " engine-usage-row-active" : ""}`}
                  >
                    <div className="engine-usage-row-main">
                      <ValueText className="value-text-wrap" value={item.service} />
                    </div>
                    <div className="engine-usage-row-side">
                      <strong>
                        {fillTemplate(seatText.engineCountValue, {
                          count: item.active_seats,
                        })}
                      </strong>
                      <span className="field-hint">{seatText.engineCountLabel}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="notice-card engine-usage-empty">
                <p className="notice-title">{seatText.engineOverviewTitle}</p>
                <p>{seatText.engineOverviewEmpty}</p>
              </div>
            )}
          </div>
        </section>

        <section className="setup-settings-panel">
          <div className="setup-settings-header">
            <div className="section-heading section-heading-compact">
              <p className="section-eyebrow">{copy.settings.eyebrow}</p>
              <h3>{copy.settings.titles[activeTab]}</h3>
              <p className="section-copy">{copy.settings.descriptions[activeTab]}</p>
            </div>

            <div className="settings-tabs">
              {(["engine", "translation", "pdf"] as const).map((tab) => (
                <button
                  key={tab}
                  className={activeTab === tab ? "tab-active" : undefined}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                >
                  {copy.settings.tabs[tab]}
                </button>
              ))}
            </div>
          </div>

          <SettingsSection
            title={copy.settings.titles[activeTab]}
            eyebrow={copy.settings.tabs[activeTab]}
            description={copy.settings.descriptions[activeTab]}
            emptyTitle={copy.settings.emptyTitle}
            emptyMessage={settingsEmptyMessage}
            emptyHint={settingsEmptyHint}
            locale={locale}
            fieldLabels={{
              leaveBlank: copy.field.leaveBlankSecret,
              required: copy.field.required,
              optional: copy.field.optional,
              useDefault: copy.field.useDefault,
            }}
            fields={activeTabFields}
            values={
              activeTab === "engine"
                ? engineValues
                : activeTab === "translation"
                  ? translationValues
                  : pdfValues
            }
            onChange={(name, value) => {
              if (activeTab === "engine") {
                updateFieldValues(setEngineValues, name, value);
                return;
              }
              if (activeTab === "translation") {
                updateFieldValues(setTranslationValues, name, value);
                return;
              }
              updateFieldValues(setPdfValues, name, value);
            }}
          />
        </section>
      </div>
    </section>
  );

  const previewPanel = (
    <PreviewPanel
      eyebrow={copy.preview.eyebrow}
      targetLabel={copy.preview.targetLabel}
      downloadLabel={copy.downloads.title}
      previewUrl={previewTarget}
      previewKey={activePreviewOption?.name ?? previewTarget}
      title={isTranslatedPreview ? copy.preview.translatedTitle : copy.preview.sourceTitle}
      caption={isTranslatedPreview ? copy.preview.translatedBody : copy.preview.sourceBody}
      viewerTitle={
        activePreviewOption?.label ??
        (isTranslatedPreview ? copy.preview.translatedTitle : copy.preview.sourceTitle)
      }
      options={previewOptions.map((option) => ({
        name: option.name,
        label: option.label,
      }))}
      activeOption={activePreviewArtifact}
      onSelect={handlePreviewSelect}
      downloads={downloadOptions}
      openDownloadLabel={copy.downloads.open}
      emptyDownloadText={copy.downloads.empty}
      emptyTitle={copy.preview.emptyTitle}
      emptyCaption={copy.preview.emptyBody}
    />
  );

  const overviewPanel = (
    <section className="panel-card overview-panel workspace-panel">
      <div className="overview-status-grid">
        <div className="summary-pill summary-pill-primary">
          <span className="summary-label">{copy.launch.stateLabel}</span>
          <ValueText value={currentWorkspaceState} />
          <p className="section-copy">{currentMessage}</p>
        </div>

        <div className="summary-pill">
          <span className="summary-label">{copy.launch.backendStageLabel}</span>
          <ValueText value={currentStage} />
          <p className="section-copy">{progressPercentLabel}</p>
        </div>
      </div>

      <div className="overview-route-shell">
        <span className="hero-card-label">{copy.launch.routeLabel}</span>
        {renderRouteVisual()}
      </div>

      <div className="overview-summary-grid">
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.sourceLabel}</span>
          <ValueText value={sourceLabel} />
        </div>
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.engineLabel}</span>
          <ValueText value={service} />
        </div>
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.pagesLabel}</span>
          <ValueText value={pageScopeLabel} />
        </div>
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.outputLabel}</span>
          <ValueText value={outputModeLabel} />
        </div>
      </div>
    </section>
  );

  const controlPanel = (
    <section
      className={`panel-card launch-card control-panel inspector-panel status-${currentStatusTone}`}
    >
      <div className="control-panel-top">
        <div className="section-heading section-heading-compact">
          <p className="section-eyebrow">{workspaceCopy.runTitle}</p>
          <h3>{currentWorkspaceState}</h3>
          <p className="section-copy">{currentMessage}</p>
        </div>
        <span className="status-pill">{progressPercentLabel}</span>
      </div>

      <section className="control-summary-card" aria-label={workspaceCopy.contextTitle}>
        <div className="control-summary-head">
          <span className="hero-card-label">{workspaceCopy.contextTitle}</span>
        </div>

        {renderRouteVisual("route-visual-control")}

        <div className="control-summary-meta">
          <div className="control-summary-item">
            <span className="meta-label">{copy.launch.engineLabel}</span>
            <ValueText
              as="p"
              className="control-summary-value value-text-wrap"
              value={service}
            />
          </div>
          <div className="control-summary-item">
            <span className="meta-label">{copy.source.transportLabel}</span>
            <ValueText
              as="p"
              className="control-summary-value"
              value={sourceTransportLabel}
            />
          </div>
        </div>
      </section>

      <div className="status-meter">
        <div
          className="status-meter-fill"
          style={{ transform: `scaleX(${Math.max(progress, 0.04)})` }}
        />
      </div>

      <div className="status-copy inspector-status-copy">
        <p className="status-stage">{currentStage}</p>
        <p>{copy.launch.backendStageLabel}</p>
      </div>

      {missingSecretLabels.length > 0 && service !== "SiliconFlowFree" ? (
        <div className="notice-card">
          <p className="notice-title">{copy.launch.missingCredentialsTitle}</p>
          <p>{missingSecretLabels.join(", ")}</p>
        </div>
      ) : null}

      <div className="action-row">
        <button
          className="primary-button"
          disabled={isRunning}
          type="button"
          onClick={() => void handleTranslate()}
        >
          {isRunning ? copy.launch.running : copy.launch.start}
        </button>
        <button
          className="secondary-button"
          disabled={!isRunning}
          type="button"
          onClick={() => void handleCancel()}
        >
          {copy.launch.cancel}
        </button>
        <button
          className="secondary-button"
          disabled={seatActionId !== null}
          type="button"
          onClick={() => void handleLeaveSeat()}
        >
          {seatText.leaveSeat}
        </button>
      </div>

      {currentErrorTitle ? (
        <div className="status-callout">
          <strong>{currentErrorTitle}</strong>
        </div>
      ) : null}

      {technicalState ? (
        <details className="technical-details">
          <summary>{copy.launch.technicalDetails}</summary>
          <pre>{technicalState}</pre>
        </details>
      ) : null}

      {result?.token_usage ? (
        <details className="technical-details">
          <summary>{copy.progress.tokenUsageTitle}</summary>
          <div className="token-grid">
            {Object.entries(result.token_usage).map(([scope, usage]) => (
              <div key={scope} className="token-item">
                <p className="token-scope">{scope}</p>
                <p>
                  {usage.total ?? 0} {copy.progress.tokenTotalSuffix}
                </p>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );

  const resultsPanel = (
    <div className="results-workspace">{previewPanel}</div>
  );

  let primaryContent: ReactElement;

  switch (activeSection) {
    case "source":
      primaryContent = sourcePanel;
      break;
    case "setup":
      primaryContent = setupPanel;
      break;
    case "results":
      primaryContent = resultsPanel;
      break;
    case "overview":
    default:
      primaryContent = overviewPanel;
      break;
  }

  return (
    <div className="app-shell">
      <div className="app-workbench">
        <aside className="app-sidebar">
          <div className="sidebar-brand">
            <div className="sidebar-brand-mark">PF</div>
            <div className="sidebar-brand-copy">
              <strong>{copy.appName}</strong>
              <span>{`Seat ${seatSession.seatId} · ${currentWorkspaceState}`}</span>
            </div>
          </div>

          <nav className="sidebar-nav" aria-label={workspaceCopy.nav.overview}>
            {workspaceSections.map((section) => (
              <button
                key={section.id}
                className={`sidebar-nav-item${activeSection === section.id ? " sidebar-nav-item-active" : ""}`}
                type="button"
                onClick={() => setActiveSection(section.id)}
              >
                <span className="sidebar-nav-key">{section.key}</span>
                <span className="sidebar-nav-main">
                  <span className="sidebar-nav-heading">
                    <strong>{section.label}</strong>
                    {section.badge ? (
                      <span className="sidebar-nav-badge">{section.badge}</span>
                    ) : null}
                  </span>
                  <span className="sidebar-nav-detail">{section.detail}</span>
                </span>
              </button>
            ))}
          </nav>

          <div className="sidebar-footer">
            <span className="section-eyebrow">{workspaceCopy.contextTitle}</span>
            <ValueText value={routeCompactLabel} />
          </div>
        </aside>

        <main className="app-workspace">
          <header className="workspace-topbar">
            <div className="workspace-header-main workspace-header-main-compact">
              <div className="workspace-title-block">
                <p className="section-eyebrow">{activeWorkspaceSection.label}</p>
                <h1>{workspaceHeaderTitle}</h1>
                <p className="section-copy">{workspaceHeaderBody}</p>
              </div>
            </div>

            <LocaleSwitcher
              className="locale-card-compact workspace-locale-card"
              label={copy.localeLabel}
              locale={locale}
              options={copy.localeOptions}
              onChange={setLocale}
            />
          </header>

          <div
            className={`workspace-content${activeSection === "results" ? " workspace-content-results" : ""}`}
          >
            <section className="workspace-primary">
              <div className={`workspace-paper workspace-paper-${activeSection}`}>
                {primaryContent}
              </div>
            </section>
            <aside className="workspace-secondary">
              <div className="utility-rail">{controlPanel}</div>
            </aside>
          </div>
        </main>
      </div>

      <nav className="mobile-tabbar" aria-label={workspaceCopy.nav.overview}>
        <div className="mobile-tabbar-track">
          {mobileSections.map((section) => (
            <button
              key={section.id}
              className={`mobile-tabbar-item${activeSection === section.id ? " mobile-tabbar-item-active" : ""}`}
              type="button"
              onClick={() => setActiveSection(section.id)}
            >
              <span className="mobile-tabbar-icon">
                {section.badge ?? section.key}
              </span>
              <span className="mobile-tabbar-copy">
                <strong>{section.mobileLabel}</strong>
                <span>{section.detail}</span>
              </span>
            </button>
          ))}
        </div>
      </nav>
    </div>
  );
}

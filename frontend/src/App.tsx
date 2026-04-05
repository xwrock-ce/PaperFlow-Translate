import {
  startTransition,
  type Dispatch,
  type ReactElement,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";

import { DownloadGrid } from "./components/DownloadGrid";
import { PreviewPanel } from "./components/PreviewPanel";
import { SettingsSection } from "./components/SettingsSection";
import { fetchAppConfig, streamTranslation } from "./lib/api";
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
  PreviewArtifactName,
  ServiceConfig,
  SourceMode,
  TranslationResult,
  UiLocale,
} from "./lib/types";

type FieldValues = Record<string, string | number | boolean | null>;
type SettingsTab = "engine" | "translation" | "pdf";
type WorkspaceSection = "overview" | "source" | "route" | "settings" | "results";
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
  return result?.artifacts?.source?.url ?? sourcePreview;
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

  if (result?.artifacts?.mono?.url) {
    options.push({
      name: "mono",
      label: artifactLabel("mono", locale),
      url: result.artifacts.mono.url,
    });
  }

  if (result?.artifacts?.dual?.url) {
    options.push({
      name: "dual",
      label: artifactLabel("dual", locale),
      url: result.artifacts.dual.url,
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
  const controllerRef = useRef<AbortController | null>(null);
  const serviceDraftsRef = useRef<Record<string, FieldValues>>({});

  const copy = UI_COPY[locale];

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(UI_LOCALE_STORAGE_KEY, locale);
    }
  }, [locale]);

  useEffect(() => {
    void fetchAppConfig()
      .then((nextConfig) => {
        const initialService = nextConfig.default_service;
        const nextLocale = resolveLocale(nextConfig.default_locale);
        const nextLanguageOptions = normalizeLanguageOptions(
          nextConfig.translation_languages,
          nextLocale,
        );

        startTransition(() => {
          setLocale(nextLocale);
          setConfig(nextConfig);
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
      })
      .catch((loadError: Error) => {
        setErrorCode("config_unavailable");
        setTechnicalDetails(loadError.message);
        setStatusKey("config_unavailable");
      });
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

  async function handleTranslate(): Promise<void> {
    if (isRunning) {
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
      setActiveSection("settings");
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
            setErrorCode(event.error.code ?? "translation_failed");
            setTechnicalDetails(
              [event.error.message, event.error.hint]
                .filter((value) => Boolean(value))
                .join("\n"),
            );
            setStatusKey("failed");
            setIsRunning(false);
            controllerRef.current = null;
            return;
          }

          setResult(event.result);
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
      } else {
        setErrorCode("request_failed");
        setTechnicalDetails((streamError as Error).message);
        setStatusKey("failed");
      }
      setIsRunning(false);
      controllerRef.current = null;
    }
  }

  function handleCancel(): void {
    controllerRef.current?.abort();
  }

  function handleSwapLanguages(): void {
    setLangIn(langOut);
    setLangOut(langIn);
  }

  function handlePreviewSelect(name: PreviewArtifactName): void {
    setSelectedPreviewArtifact(name);
  }

  const noEngineFields = activeTab === "engine" && !activeTabFields.length;
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
    title: string;
    description: string;
    detail: string;
    badge: string | null;
  }> = [
    {
      id: "overview",
      key: "01",
      label: workspaceCopy.nav.overview,
      title: workspaceCopy.titles.overview,
      description: workspaceCopy.descriptions.overview,
      detail: currentWorkspaceState,
      badge: currentStatusTone === "active" ? progressPercentLabel : null,
    },
    {
      id: "source",
      key: "02",
      label: workspaceCopy.nav.source,
      title: workspaceCopy.titles.source,
      description: workspaceCopy.descriptions.source,
      detail: sourceTransportLabel,
      badge: sourceReady ? copy.source.previewReady : null,
    },
    {
      id: "route",
      key: "03",
      label: workspaceCopy.nav.route,
      title: workspaceCopy.titles.route,
      description: workspaceCopy.descriptions.route,
      detail: routeCompactLabel,
      badge: null,
    },
    {
      id: "settings",
      key: "04",
      label: workspaceCopy.nav.settings,
      title: workspaceCopy.titles.settings,
      description: workspaceCopy.descriptions.settings,
      detail: copy.settings.tabs[activeTab],
      badge: activeService?.fields.length ? String(activeService.fields.length) : null,
    },
    {
      id: "results",
      key: "05",
      label: workspaceCopy.nav.results,
      title: workspaceCopy.titles.results,
      description: workspaceCopy.descriptions.results,
      detail: downloadCount
        ? `${downloadCount} ${workspaceCopy.filesLabel}`
        : previewStateLabel,
      badge: downloadCount ? String(downloadCount) : null,
    },
  ];
  const activeSectionMeta =
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
      <div className="section-heading">
        <p className="section-eyebrow">{copy.source.eyebrow}</p>
        <h2>{copy.source.title}</h2>
        <p className="section-copy">{copy.source.body}</p>
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

      <div className="meta-grid">
        <div className="meta-item">
          <span className="meta-label">{copy.source.previewLabel}</span>
          <strong>{previewStateLabel}</strong>
        </div>
        <div className="meta-item">
          <span className="meta-label">{copy.source.transportLabel}</span>
          <strong>{sourceTransportLabel}</strong>
        </div>
        <div className="meta-item">
          <span className="meta-label">{copy.source.safetyLabel}</span>
          <strong>{copy.source.safetyValue}</strong>
        </div>
      </div>
    </section>
  );

  const routePanel = (
    <section className="panel-card route-card workspace-panel">
      <div className="section-heading">
        <p className="section-eyebrow">{copy.route.eyebrow}</p>
        <h2>{copy.route.title}</h2>
        <p className="section-copy">{copy.route.body}</p>
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

      <div className="route-service-grid">
        <label className="field route-service-field">
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

        <div className="service-banner">
          <span className="service-banner-title">
            {service === "SiliconFlowFree"
              ? copy.route.freeEngineTitle
              : copy.route.privateEngineTitle}
          </span>
          <p>
            {service === "SiliconFlowFree"
              ? copy.route.freeEngineBody
              : copy.route.privateEngineBody}
          </p>
        </div>
      </div>
    </section>
  );

  const settingsPanel = (
    <section className="panel-card settings-board workspace-panel">
      <div className="section-heading">
        <p className="section-eyebrow">{copy.settings.eyebrow}</p>
        <h2>{copy.settings.titles[activeTab]}</h2>
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

      <SettingsSection
        title={copy.settings.titles[activeTab]}
        eyebrow={copy.settings.tabs[activeTab]}
        description={copy.settings.descriptions[activeTab]}
        emptyMessage={
          noEngineFields
            ? locale === "zh"
              ? "当前引擎没有额外的前端配置项。"
              : "This engine does not expose extra frontend settings."
            : undefined
        }
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
  );

  const previewPanel = (
    <PreviewPanel
      eyebrow={copy.preview.eyebrow}
      targetLabel={copy.preview.targetLabel}
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
      emptyTitle={copy.preview.emptyTitle}
      emptyCaption={copy.preview.emptyBody}
    />
  );

  const downloadsPanel = (
    <DownloadGrid
      result={result}
      eyebrow={copy.downloads.eyebrow}
      title={copy.downloads.title}
      description={copy.downloads.body}
      emptyText={copy.downloads.empty}
      readyText={copy.downloads.ready}
      openText={copy.downloads.open}
      artifactLabel={(name) => artifactLabel(name, locale)}
    />
  );

  const overviewPanel = (
    <section className="panel-card overview-panel">
      <div className="overview-copy">
        <p className="section-eyebrow">{workspaceCopy.nav.overview}</p>
        <h2>{currentWorkspaceState}</h2>
        <p className="section-copy">{currentMessage}</p>
      </div>

      <div className="overview-route-shell">
        <span className="hero-card-label">{copy.launch.routeLabel}</span>
        {renderRouteVisual()}
      </div>

      <div className="overview-summary-grid">
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.sourceLabel}</span>
          <strong>{sourceLabel}</strong>
        </div>
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.engineLabel}</span>
          <strong>{service}</strong>
        </div>
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.pagesLabel}</span>
          <strong>{pageScopeLabel}</strong>
        </div>
        <div className="summary-pill">
          <span className="summary-label">{copy.launch.outputLabel}</span>
          <strong>{outputModeLabel}</strong>
        </div>
      </div>
    </section>
  );

  const controlPanel = (
    <section className={`panel-card launch-card control-panel status-${currentStatusTone}`}>
      <div className="section-heading">
        <p className="section-eyebrow">{workspaceCopy.runTitle}</p>
        <h3>{currentWorkspaceState}</h3>
        <p className="section-copy">{currentMessage}</p>
      </div>

      <div className="status-header">
        <div className="status-copy">
          <p className="status-stage">{currentStage}</p>
          <p>{copy.launch.backendStageLabel}</p>
        </div>
        <span className="status-pill">{progressPercentLabel}</span>
      </div>

      <div className="status-meter">
        <div
          className="status-meter-fill"
          style={{ transform: `scaleX(${Math.max(progress, 0.04)})` }}
        />
      </div>

      <div className="launch-focus">
        <span className="summary-label">{copy.launch.sourceLabel}</span>
        <strong>{sourceLabel}</strong>
        <p>
          {copy.launch.routeLabel}: {routeLabel}
        </p>
      </div>

      <div className="meta-grid control-meta-grid">
        <div className="meta-item">
          <span className="meta-label">{copy.launch.engineLabel}</span>
          <strong>{service}</strong>
        </div>
        <div className="meta-item">
          <span className="meta-label">{copy.launch.pagesLabel}</span>
          <strong>{pageScopeLabel}</strong>
        </div>
        <div className="meta-item">
          <span className="meta-label">{copy.launch.outputLabel}</span>
          <strong>{outputModeLabel}</strong>
        </div>
        <div className="meta-item">
          <span className="meta-label">{workspaceCopy.previewStateLabel}</span>
          <strong>{previewStateLabel}</strong>
        </div>
        <div className="meta-item">
          <span className="meta-label">{workspaceCopy.filesLabel}</span>
          <strong>{downloadCount}</strong>
        </div>
        <div className="meta-item">
          <span className="meta-label">{copy.launch.routeLabel}</span>
          <strong>{routeCompactLabel}</strong>
        </div>
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
          onClick={handleCancel}
        >
          {copy.launch.cancel}
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
        <div className="token-card">
          <p className="token-title">{copy.progress.tokenUsageTitle}</p>
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
        </div>
      ) : null}
    </section>
  );

  const resultsPanel = (
    <div className="results-layout">
      <div className="results-preview-column">{previewPanel}</div>
      <div className="results-side-column">{downloadsPanel}</div>
    </div>
  );

  let primaryContent: ReactElement;

  switch (activeSection) {
    case "source":
      primaryContent = sourcePanel;
      break;
    case "route":
      primaryContent = routePanel;
      break;
    case "settings":
      primaryContent = settingsPanel;
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
    <div className="app-shell app-workbench">
      <aside className="app-sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-mark">PF</div>
          <div className="sidebar-brand-copy">
            <strong>{copy.appName}</strong>
            <span>{currentWorkspaceState}</span>
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
              <span className="sidebar-nav-copy">
                <strong>{section.label}</strong>
                <span>{section.detail}</span>
              </span>
              {section.badge ? (
                <span className="sidebar-nav-badge">{section.badge}</span>
              ) : null}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="section-eyebrow">{workspaceCopy.contextTitle}</span>
          <strong>{routeLabel}</strong>
          <p>{service}</p>
        </div>
      </aside>

      <main className="app-workspace">
        <header className="workspace-header">
          <div className="workspace-header-copy">
            <p className="section-eyebrow">{copy.appName}</p>
            <h1>{activeSectionMeta.title}</h1>
            <p className="header-body">{activeSectionMeta.description}</p>
          </div>

          <div className="workspace-header-side">
            <section className="locale-card" aria-label={copy.localeLabel}>
              <span className="locale-label">{copy.localeLabel}</span>
              <div className="locale-toggle">
                <button
                  className={locale === "en" ? "toggle-active" : undefined}
                  type="button"
                  onClick={() => setLocale("en")}
                >
                  {copy.localeOptions.en}
                </button>
                <button
                  className={locale === "zh" ? "toggle-active" : undefined}
                  type="button"
                  onClick={() => setLocale("zh")}
                >
                  {copy.localeOptions.zh}
                </button>
              </div>
            </section>
          </div>
        </header>

        <div
          className={`workspace-content${activeSection === "results" ? " workspace-content-results" : ""}`}
        >
          <section className="workspace-primary">{primaryContent}</section>
          <aside className="workspace-secondary">
            <div className="utility-rail">{controlPanel}</div>
          </aside>
        </div>
      </main>
    </div>
  );
}

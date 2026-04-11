export type FieldKind =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "select";

export type UiLocale = "en" | "zh";
export type PreviewArtifactName = "source" | "mono" | "dual";

export interface LocalizedText {
  en: string;
  zh: string;
}

export interface ConfigField {
  name: string;
  label: LocalizedText;
  description?: LocalizedText;
  type: FieldKind;
  required: boolean;
  default: string | number | boolean | null;
  password?: boolean;
  sensitive?: boolean;
  choices?: Array<{
    label: LocalizedText;
    value: string;
  }>;
}

export interface ServiceConfig {
  name: string;
  flag: string;
  support_llm: boolean;
  description?: string;
  fields: ConfigField[];
}

export interface AppConfig {
  name: string;
  version: string;
  default_service: string;
  default_locale?: UiLocale;
  seat_management: SeatManagementConfig;
  services: ServiceConfig[];
  translation_languages: Array<{
    label: LocalizedText;
    value: string;
  }>;
  translation_fields: ConfigField[];
  pdf_fields: ConfigField[];
}

export interface SeatManagementConfig {
  enabled: boolean;
  seat_count: number;
  lease_timeout_seconds: number;
  heartbeat_interval_seconds: number;
  admin_force_release_enabled: boolean;
}

export interface EngineUsageSummary {
  service: string;
  active_seats: number;
}

export interface SeatSummary {
  seat_id: string;
  status: "available" | "occupied" | "stale";
  occupant_name?: string | null;
  selected_service?: string | null;
  has_active_job: boolean;
  acquired_at?: string | null;
  last_heartbeat_at?: string | null;
  claimable: boolean;
  message: string;
}

export interface SeatListResponse {
  seats: SeatSummary[];
  engine_usage: EngineUsageSummary[];
}

export interface SeatClaimResponse {
  seat: SeatSummary;
  lease_token: string;
  heartbeat_interval_seconds: number;
  lease_timeout_seconds: number;
}

export interface SeatSession {
  seatId: string;
  leaseToken: string;
  occupantName: string;
}

export interface Artifact {
  name: string;
  filename: string;
  url: string;
  preview_url?: string | null;
  size_bytes?: number | null;
}

export interface TranslationResult {
  status: string;
  request_id: string;
  service: string;
  input_file: string;
  output_dir: string;
  mono_pdf_path?: string | null;
  dual_pdf_path?: string | null;
  glossary_path?: string | null;
  preview_url?: string | null;
  total_seconds?: number | null;
  token_usage?: Record<string, Record<string, number>> | null;
  artifacts?: Record<string, Artifact>;
}

export interface ProgressEvent {
  type: "progress";
  stage?: string;
  message?: string;
  overall_progress?: number;
  part_index?: number;
  total_parts?: number;
  stage_current?: number;
  stage_total?: number;
}

export interface ErrorEvent {
  type: "error";
  error: {
    code?: string;
    message: string;
    hint?: string;
    details?: unknown;
  };
}

export interface FinishEvent {
  type: "finish";
  result: TranslationResult;
}

export interface StatusEvent {
  type: "status";
  job: {
    job_id: string;
    request_id: string;
    status: string;
    queue_position?: number | null;
  };
}

export type StreamEvent = ProgressEvent | ErrorEvent | FinishEvent | StatusEvent;

export type SourceMode = "upload" | "link";

export interface SubmitPayload {
  sourceMode: SourceMode;
  file: File | null;
  fileUrl: string;
  service: string;
  seatId: string;
  leaseToken: string;
  uiLocale: UiLocale;
  langIn: string;
  langOut: string;
  translation: Record<string, string | number | boolean | null>;
  pdf: Record<string, string | number | boolean | null>;
  engineSettings: Record<string, string | number | boolean | null>;
}

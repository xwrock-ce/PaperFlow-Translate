import type {
  AppConfig,
  SeatClaimResponse,
  SeatListResponse,
  SeatSummary,
  StreamEvent,
  SubmitPayload,
} from "./types";

interface ErrorPayload {
  error?: {
    code?: string;
    message?: string;
    hint?: string;
    details?: unknown;
  };
}

export class ApiError extends Error {
  code?: string;
  hint?: string;
  details?: unknown;

  constructor(
    message: string,
    options?: {
      code?: string;
      hint?: string;
      details?: unknown;
    },
  ) {
    super(options?.hint ? `${message}\n${options.hint}` : message);
    this.name = "ApiError";
    this.code = options?.code;
    this.hint = options?.hint;
    this.details = options?.details;
  }
}

function parseNdjsonChunk(
  buffer: string,
  onEvent: (event: StreamEvent) => void,
): string {
  const lines = buffer.split("\n");
  const remainder = lines.pop() ?? "";

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    onEvent(JSON.parse(trimmed) as StreamEvent);
  }

  return remainder;
}

async function readApiError(response: Response): Promise<ApiError> {
  const maybeJson = (await response.json().catch(() => null)) as ErrorPayload | null;
  const payload = maybeJson?.error;
  return new ApiError(payload?.message ?? `HTTP ${response.status}`, {
    code: payload?.code,
    hint: payload?.hint,
    details: payload?.details,
  });
}

export async function fetchAppConfig(): Promise<AppConfig> {
  const response = await fetch("/app/config");
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as AppConfig;
}

export async function loginSeat(
  displayName: string,
): Promise<{ display_name: string }> {
  const response = await fetch("/seats/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as { display_name: string };
}

export async function fetchSeats(): Promise<SeatListResponse> {
  const response = await fetch("/seats");
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as SeatListResponse;
}

export async function claimSeat(
  seatId: string,
  displayName: string,
): Promise<SeatClaimResponse> {
  const response = await fetch(`/seats/${seatId}/claim`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as SeatClaimResponse;
}

export async function heartbeatSeat(
  seatId: string,
  leaseToken: string,
): Promise<SeatClaimResponse> {
  const response = await fetch(`/seats/${seatId}/heartbeat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ lease_token: leaseToken }),
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as SeatClaimResponse;
}

export async function releaseSeat(
  seatId: string,
  leaseToken: string,
): Promise<SeatSummary> {
  const response = await fetch(`/seats/${seatId}/release`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ lease_token: leaseToken }),
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as SeatSummary;
}

export async function updateSeatService(
  seatId: string,
  leaseToken: string,
  service: string,
): Promise<SeatSummary> {
  const response = await fetch(`/seats/${seatId}/service`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ lease_token: leaseToken, service }),
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as SeatSummary;
}

export async function forceReleaseSeat(
  seatId: string,
  adminToken: string,
): Promise<SeatSummary> {
  const response = await fetch(`/admin/seats/${seatId}/force-release`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ admin_token: adminToken }),
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
  return (await response.json()) as SeatSummary;
}

export async function cancelJob(jobId: string): Promise<void> {
  const response = await fetch(`/jobs/${jobId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await readApiError(response);
  }
}

export async function streamTranslation(
  payload: SubmitPayload,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const formData = new FormData();

  if (payload.sourceMode === "upload" && payload.file) {
    formData.append("file", payload.file);
  }
  if (payload.sourceMode === "link" && payload.fileUrl.trim()) {
    formData.append("file_url", payload.fileUrl.trim());
  }

  formData.append(
    "request_json",
    JSON.stringify({
      service: payload.service,
      seat_id: payload.seatId,
      lease_token: payload.leaseToken,
      ui_locale: payload.uiLocale,
      lang_in: payload.langIn,
      lang_out: payload.langOut,
      translation: payload.translation,
      pdf: payload.pdf,
      engine_settings: payload.engineSettings,
    }),
  );

  const response = await fetch("/translate/file/stream", {
    method: "POST",
    body: formData,
    signal,
  });

  if (!response.ok) {
    throw await readApiError(response);
  }

  if (!response.body) {
    throw new Error("Streaming response body was not available.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      buffer = parseNdjsonChunk(buffer, onEvent);
    }
  } catch (error) {
    if ((error as DOMException).name === "AbortError") {
      throw error;
    }
    throw new ApiError("The live connection to the backend was interrupted.", {
      code: "client_disconnected",
      hint: "The backend job was asked to stop because the browser lost the live stream.",
      details: error instanceof Error ? error.message : String(error),
    });
  }

  const tail = buffer.trim();
  if (tail) {
    onEvent(JSON.parse(tail) as StreamEvent);
  }
}

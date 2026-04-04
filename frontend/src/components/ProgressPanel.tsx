import type { ReactElement } from "react";

import type { TranslationResult } from "../lib/types";

interface ProgressPanelProps {
  eyebrow: string;
  title: string;
  stage: string;
  message: string;
  progress: number;
  progressLabel: string;
  statusTone: "idle" | "active" | "error" | "done";
  result: TranslationResult | null;
  errorTitle: string | null;
  technicalDetailsLabel: string;
  technicalDetails: string | null;
  meta: Array<{
    label: string;
    value: string;
  }>;
  tokenUsageTitle: string;
  tokenTotalSuffix: string;
}

export function ProgressPanel({
  eyebrow,
  title,
  stage,
  message,
  progress,
  progressLabel,
  statusTone,
  result,
  errorTitle,
  technicalDetailsLabel,
  technicalDetails,
  meta,
  tokenUsageTitle,
  tokenTotalSuffix,
}: ProgressPanelProps): ReactElement {
  return (
    <section className={`panel-card status-card status-${statusTone}`}>
      <div className="status-header">
        <div>
          <p className="section-eyebrow">{eyebrow}</p>
          <h3>{title}</h3>
        </div>
        <span className="status-pill">{progressLabel}</span>
      </div>

      <div className="status-meter">
        <div
          className="status-meter-fill"
          style={{ transform: `scaleX(${Math.max(progress, 0.04)})` }}
        />
      </div>

      <div className="status-copy">
        <p className="status-stage">{stage}</p>
        <p>{message}</p>
      </div>

      {errorTitle ? (
        <div className="status-callout">
          <strong>{errorTitle}</strong>
        </div>
      ) : null}

      {technicalDetails ? (
        <details className="technical-details">
          <summary>{technicalDetailsLabel}</summary>
          <pre>{technicalDetails}</pre>
        </details>
      ) : null}

      <div className="meta-grid status-meta-grid">
        {meta.map((item) => (
          <div key={item.label} className="meta-item status-meta-item">
            <span className="meta-label">{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      {result?.token_usage ? (
        <div className="token-card">
          <p className="token-title">{tokenUsageTitle}</p>
          <div className="token-grid">
            {Object.entries(result.token_usage).map(([scope, usage]) => (
              <div key={scope} className="token-item">
                <p className="token-scope">{scope}</p>
                <p>
                  {usage.total ?? 0} {tokenTotalSuffix}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

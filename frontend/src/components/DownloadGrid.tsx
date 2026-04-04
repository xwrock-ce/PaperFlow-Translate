import type { ReactElement } from "react";

import type { TranslationResult } from "../lib/types";

interface DownloadGridProps {
  result: TranslationResult | null;
  eyebrow: string;
  title: string;
  description: string;
  emptyText: string;
  readyText: string;
  artifactLabel: (name: string) => string;
}

function formatBytes(bytes?: number | null): string | null {
  if (!bytes) {
    return null;
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DownloadGrid({
  result,
  eyebrow,
  title,
  description,
  emptyText,
  readyText,
  artifactLabel,
}: DownloadGridProps): ReactElement {
  const artifacts = result?.artifacts ? Object.values(result.artifacts) : [];
  const downloadableArtifacts = artifacts.filter(
    (artifact) => artifact.name !== "source",
  );

  return (
    <section className="panel-card downloads-card">
      <div className="section-heading">
        <p className="section-eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
        <p className="section-copy">{description}</p>
      </div>
      {downloadableArtifacts.length ? (
        <div className="download-grid">
          {downloadableArtifacts.map((artifact) => (
            <a
              key={artifact.name}
              className="download-tile"
              href={artifact.url}
              target="_blank"
              rel="noreferrer"
            >
              <span className="download-kicker">{artifactLabel(artifact.name)}</span>
              <strong>{artifact.filename}</strong>
              <span>{formatBytes(artifact.size_bytes) ?? readyText}</span>
            </a>
          ))}
        </div>
      ) : (
        <div className="download-empty">
          <p>{emptyText}</p>
        </div>
      )}
    </section>
  );
}

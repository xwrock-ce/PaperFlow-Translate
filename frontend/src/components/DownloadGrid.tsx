import type { ReactElement } from "react";

import type { TranslationResult } from "../lib/types";

interface DownloadGridProps {
  result: TranslationResult | null;
  eyebrow: string;
  title: string;
  description: string;
  emptyText: string;
  readyText: string;
  openText: string;
  artifactLabel: (name: string) => string;
}

const DOWNLOAD_PRIORITY: Record<string, number> = {
  mono: 0,
  dual: 1,
  glossary: 2,
};

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
  openText,
  artifactLabel,
}: DownloadGridProps): ReactElement {
  const artifacts = result?.artifacts ? Object.values(result.artifacts) : [];
  const downloadableArtifacts = artifacts
    .filter((artifact) => artifact.name !== "source")
    .sort((left, right) => {
      const leftRank = DOWNLOAD_PRIORITY[left.name] ?? Number.MAX_SAFE_INTEGER;
      const rightRank = DOWNLOAD_PRIORITY[right.name] ?? Number.MAX_SAFE_INTEGER;
      if (leftRank !== rightRank) {
        return leftRank - rightRank;
      }
      return left.filename.localeCompare(right.filename);
    });
  const [primaryArtifact, ...secondaryArtifacts] = downloadableArtifacts;

  return (
    <section className="panel-card downloads-card">
      <div className="section-heading">
        <p className="section-eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
        <p className="section-copy">{description}</p>
      </div>
      {primaryArtifact ? (
        <div className="download-stack">
          <a
            className="download-primary"
            href={primaryArtifact.url}
            target="_blank"
            rel="noreferrer"
          >
            <div className="download-primary-copy">
              <span className="download-kicker">
                {artifactLabel(primaryArtifact.name)}
              </span>
              <strong>{primaryArtifact.filename}</strong>
              <span>{formatBytes(primaryArtifact.size_bytes) ?? readyText}</span>
            </div>
            <span className="download-action">{openText}</span>
          </a>

          {secondaryArtifacts.length ? (
            <div className="download-list">
              {secondaryArtifacts.map((artifact) => (
                <a
                  key={artifact.name}
                  className="download-list-item"
                  href={artifact.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <div className="download-list-copy">
                    <span className="download-kicker">
                      {artifactLabel(artifact.name)}
                    </span>
                    <strong>{artifact.filename}</strong>
                    <span>{formatBytes(artifact.size_bytes) ?? readyText}</span>
                  </div>
                  <span className="download-action">{openText}</span>
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="download-empty">
          <p>{emptyText}</p>
        </div>
      )}
    </section>
  );
}

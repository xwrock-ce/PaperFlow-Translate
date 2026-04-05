import type { ReactElement } from "react";

import type { PreviewArtifactName } from "../lib/types";

interface PreviewPanelProps {
  eyebrow: string;
  targetLabel: string;
  downloadLabel: string;
  previewUrl: string | null;
  previewKey: string | null;
  title: string;
  caption: string;
  viewerTitle: string;
  options: Array<{
    name: PreviewArtifactName;
    label: string;
  }>;
  activeOption: PreviewArtifactName | null;
  onSelect: (name: PreviewArtifactName) => void;
  downloads: Array<{
    name: string;
    label: string;
    url: string;
    filename: string;
    meta: string;
  }>;
  openDownloadLabel: string;
  emptyDownloadText: string;
  emptyTitle: string;
  emptyCaption: string;
}

export function PreviewPanel({
  eyebrow,
  targetLabel,
  downloadLabel,
  previewUrl,
  previewKey,
  title,
  caption,
  viewerTitle,
  options,
  activeOption,
  onSelect,
  downloads,
  openDownloadLabel,
  emptyDownloadText,
  emptyTitle,
  emptyCaption,
}: PreviewPanelProps): ReactElement {
  return (
    <section className="panel-card preview-card preview-window">
      <div className="preview-header-shell">
        <div className="section-heading">
          <p className="section-eyebrow">{eyebrow}</p>
          <h3>{title}</h3>
          <p className="section-copy">{caption}</p>
        </div>
        <div className="preview-toolbar-strip">
          {options.length ? (
            <div className="preview-targets" aria-label={targetLabel}>
              <span className="preview-targets-label">{targetLabel}</span>
              <div
                className="preview-targets-list"
                role="tablist"
                aria-label={targetLabel}
              >
                {options.map((option) => (
                  <button
                    key={option.name}
                    className={`preview-target-button${activeOption === option.name ? " preview-target-button-active" : ""}`}
                    type="button"
                    role="tab"
                    aria-selected={activeOption === option.name}
                    onClick={() => onSelect(option.name)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="preview-downloads" aria-label={downloadLabel}>
            <span className="preview-targets-label">{downloadLabel}</span>
            {downloads.length ? (
              <div className="preview-download-list">
                {downloads.map((download, index) => (
                  <a
                    key={download.name}
                    className={`preview-download-button${index === 0 ? " preview-download-button-primary" : ""}`}
                    href={download.url}
                    target="_blank"
                    rel="noreferrer"
                    title={download.filename}
                    aria-label={`${openDownloadLabel}: ${download.filename}`}
                  >
                    <span className="preview-download-copy">
                      <span className="preview-download-name">{download.label}</span>
                      <span className="preview-download-meta">{download.meta}</span>
                    </span>
                    <span className="preview-download-open">{openDownloadLabel}</span>
                  </a>
                ))}
              </div>
            ) : (
              <p className="preview-download-empty">{emptyDownloadText}</p>
            )}
          </div>
        </div>
      </div>
      {previewUrl ? (
        <div className="preview-viewer">
          <div className="preview-toolbar" aria-hidden="true">
            <span className="preview-toolbar-dot" />
            <span className="preview-toolbar-dot" />
            <span className="preview-toolbar-dot" />
            <span className="preview-toolbar-title">{viewerTitle}</span>
          </div>
          <iframe
            key={previewKey ?? previewUrl}
            className="preview-frame"
            src={previewUrl}
            title={viewerTitle}
          />
        </div>
      ) : (
        <div className="preview-viewer preview-viewer-empty">
          <div className="preview-toolbar" aria-hidden="true">
            <span className="preview-toolbar-dot" />
            <span className="preview-toolbar-dot" />
            <span className="preview-toolbar-dot" />
            <span className="preview-toolbar-title">{viewerTitle}</span>
          </div>
          <div className="preview-empty">
            <h4>{emptyTitle}</h4>
            <p>{emptyCaption}</p>
          </div>
        </div>
      )}
    </section>
  );
}

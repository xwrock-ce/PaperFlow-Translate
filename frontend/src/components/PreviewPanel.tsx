import type { ReactElement } from "react";

import type { PreviewArtifactName } from "../lib/types";

interface PreviewPanelProps {
  eyebrow: string;
  targetLabel: string;
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
  emptyTitle: string;
  emptyCaption: string;
}

export function PreviewPanel({
  eyebrow,
  targetLabel,
  previewUrl,
  previewKey,
  title,
  caption,
  viewerTitle,
  options,
  activeOption,
  onSelect,
  emptyTitle,
  emptyCaption,
}: PreviewPanelProps): ReactElement {
  return (
    <section className="panel-card preview-card preview-window">
      <div className="section-heading">
        <p className="section-eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
        <p className="section-copy">{caption}</p>
      </div>
      {options.length ? (
        <div className="preview-targets" aria-label={targetLabel}>
          <span className="preview-targets-label">{targetLabel}</span>
          <div className="preview-targets-list" role="tablist" aria-label={targetLabel}>
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

import type { ReactElement } from "react";

interface PreviewPanelProps {
  eyebrow: string;
  previewUrl: string | null;
  title: string;
  caption: string;
  emptyTitle: string;
  emptyCaption: string;
}

export function PreviewPanel({
  eyebrow,
  previewUrl,
  title,
  caption,
  emptyTitle,
  emptyCaption,
}: PreviewPanelProps): ReactElement {
  return (
    <section className="panel-card preview-card">
      <div className="section-heading">
        <p className="section-eyebrow">{eyebrow}</p>
        <h3>{title}</h3>
        <p className="section-copy">{caption}</p>
      </div>
      {previewUrl ? (
        <iframe className="preview-frame" src={previewUrl} title={title} />
      ) : (
        <div className="preview-empty">
          <h4>{emptyTitle}</h4>
          <p>{emptyCaption}</p>
        </div>
      )}
    </section>
  );
}

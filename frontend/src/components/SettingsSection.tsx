import type { ReactElement } from "react";

import { FieldControl } from "./FieldControl";
import type { ConfigField } from "../lib/types";
import type { UiLocale } from "../lib/types";

interface SettingsSectionProps {
  title: string;
  eyebrow: string;
  description?: string;
  fields: ConfigField[];
  locale: UiLocale;
  emptyTitle?: string;
  emptyMessage?: string;
  emptyHint?: string;
  fieldLabels: {
    leaveBlank: string;
    required: string;
    optional: string;
    useDefault: string;
  };
  values: Record<string, string | number | boolean | null>;
  onChange: (name: string, value: string | number | boolean) => void;
}

export function SettingsSection({
  title,
  eyebrow,
  description,
  fields,
  locale,
  emptyTitle,
  emptyMessage,
  emptyHint,
  fieldLabels,
  values,
  onChange,
}: SettingsSectionProps): ReactElement {
  const resolvedEmptyTitle = emptyTitle ?? title;
  const resolvedEmptyMessage = emptyMessage ?? description;

  if (!fields.length) {
    return (
      <section className="settings-card settings-card-empty" aria-label={title}>
        <div className="settings-empty-state">
          <span className="section-eyebrow">{eyebrow}</span>
          <strong>{resolvedEmptyTitle}</strong>
          {resolvedEmptyMessage ? <p className="section-copy">{resolvedEmptyMessage}</p> : null}
          {emptyHint ? <p className="field-hint">{emptyHint}</p> : null}
        </div>
      </section>
    );
  }

  return (
    <section className="settings-card" aria-label={title}>
      <div className="field-grid">
        {fields.map((field) => (
          <FieldControl
            key={field.name}
            field={field}
            locale={locale}
            labels={fieldLabels}
            value={values[field.name]}
            onChange={onChange}
          />
        ))}
      </div>
    </section>
  );
}

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
  emptyMessage?: string;
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
  emptyMessage,
  fieldLabels,
  values,
  onChange,
}: SettingsSectionProps): ReactElement {
  void title;
  void eyebrow;
  void description;

  if (!fields.length) {
    return (
      <section className="settings-card">
        {emptyMessage ? <p className="section-copy">{emptyMessage}</p> : null}
      </section>
    );
  }

  return (
    <section className="settings-card">
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

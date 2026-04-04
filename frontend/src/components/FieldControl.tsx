import type { ChangeEvent, ReactElement } from "react";

import { resolveText } from "../lib/i18n";
import type { ConfigField } from "../lib/types";
import type { UiLocale } from "../lib/types";

interface FieldControlProps {
  field: ConfigField;
  locale: UiLocale;
  labels: {
    leaveBlank: string;
    required: string;
    optional: string;
    useDefault: string;
  };
  value: string | number | boolean | null | undefined;
  onChange: (name: string, value: string | number | boolean) => void;
}

function normalizeNumber(
  event: ChangeEvent<HTMLInputElement>,
  field: ConfigField,
): number | string {
  const next = event.target.value;
  if (next === "") {
    return "";
  }
  return field.type === "integer" ? Number.parseInt(next, 10) : Number(next);
}

export function FieldControl({
  field,
  locale,
  labels,
  value,
  onChange,
}: FieldControlProps): ReactElement {
  const fieldLabel = resolveText(field.label, locale) || field.name;
  const placeholder = field.password
    ? labels.leaveBlank
    : field.required
      ? labels.required
      : labels.optional;
  const commonHint = field.description ? (
    <p className="field-hint">{resolveText(field.description, locale)}</p>
  ) : null;

  if (field.type === "boolean") {
    return (
      <label className="field field-toggle">
        <span className="field-copy">
          <span className="field-label">{fieldLabel}</span>
          {commonHint}
        </span>
        <input
          className="toggle-input"
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(field.name, event.target.checked)}
        />
      </label>
    );
  }

  if (field.type === "select" && field.choices?.length) {
    return (
      <label className="field">
        <span className="field-label">{fieldLabel}</span>
        <select
          className="field-input"
          value={String(value ?? "")}
          onChange={(event) => onChange(field.name, event.target.value)}
        >
          <option value="">{labels.useDefault}</option>
          {field.choices.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {resolveText(choice.label, locale) || choice.value}
            </option>
          ))}
        </select>
        {commonHint}
      </label>
    );
  }

  return (
    <label className="field">
      <span className="field-label">{fieldLabel}</span>
      <input
        className="field-input"
        type={
          field.password
            ? "password"
            : field.type === "integer" || field.type === "number"
              ? "number"
              : "text"
        }
        step={field.type === "number" ? "any" : undefined}
        value={value === null || value === undefined ? "" : String(value)}
        placeholder={placeholder}
        onChange={(event) =>
          onChange(
            field.name,
            field.type === "integer" || field.type === "number"
              ? normalizeNumber(event, field)
              : event.target.value,
          )
        }
      />
      {commonHint}
    </label>
  );
}

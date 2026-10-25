// iOS 8 controls. Flat, hairline-ruled, blue-on-white.
import type { ReactNode } from "react";
import { useI18n } from "../i18n";

export function Segmented<T extends string>(props: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={`segmented ${props.className ?? ""}`} role="tablist">
      {props.options.map((option) => (
        <button
          key={option.value}
          role="tab"
          aria-selected={option.value === props.value}
          className={option.value === props.value ? "on" : ""}
          onClick={() => props.onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Button(props: {
  children: ReactNode;
  onClick?: () => void;
  primary?: boolean;
  danger?: boolean;
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  const kind = props.primary ? "primary" : props.danger ? "danger" : "";
  return (
    <button
      type="button"
      className={`btn ${kind} ${props.className ?? ""}`}
      onClick={props.onClick}
      disabled={props.disabled}
      title={props.title}
    >
      {props.children}
    </button>
  );
}

/** 2px track, blue fill, no radius. Indeterminate when `value` is null. */
export function Progress({ value }: { value: number | null }) {
  if (value == null) {
    return <div className="progress indeterminate"><div className="fill" /></div>;
  }
  return (
    <div className="progress">
      <div className="fill" style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }} />
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {hint && <div className="empty-hint">{hint}</div>}
    </div>
  );
}

export function Modal(props: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <div
        className={`modal ${props.wide ? "wide" : ""}`}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label={props.title}
      >
        <header className="modal-head">
          <span className="modal-title">{props.title}</span>
          <button className="link" onClick={props.onClose}>{t("common.close")}</button>
        </header>
        <div className="modal-body">{props.children}</div>
        {props.footer && <footer className="modal-foot">{props.footer}</footer>}
      </div>
    </div>
  );
}

export function Row(props: {
  children: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`row ${props.selected ? "selected" : ""} ${props.className ?? ""}`}
      onClick={props.onClick}
    >
      {props.children}
    </div>
  );
}

import type { ReactNode } from 'react';

interface Props {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Small status indicator next to the title (active/finished, configured…). */
  status?: { ok: boolean; label: string };
  /** Right side: selects, buttons, the one primary action. */
  actions?: ReactNode;
}

/** Compact header of the current object, in the style of the reference app shell. */
export default function TopBar({ title, subtitle, status, actions }: Props) {
  return (
    <header className="topbar">
      <div className="topbar-identity">
        <h1 className="topbar-title">{title}</h1>
        {subtitle && <span className="topbar-subtitle">{subtitle}</span>}
        {status && (
          <span className="topbar-status">
            <span className={status.ok ? 'status-dot ok' : 'status-dot'} aria-hidden="true" />
            {status.label}
          </span>
        )}
      </div>
      {actions && <div className="topbar-actions">{actions}</div>}
    </header>
  );
}

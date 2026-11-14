import { html, useEffect, useState } from "./lib.js";
import { Dialog } from "./dialogs.js";
import { t } from "./i18n.js";

function percent(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.min(100, value))
    : 0;
}

export function resetCountdown(iso) {
  if (!iso) return "—";
  const remaining = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(remaining) || remaining <= 0) return t("soon");
  const days = Math.ceil(remaining / 86400000);
  if (days >= 2) return t("{count} days", { count: days });
  const hours = Math.max(1, Math.ceil(remaining / 3600000));
  return t("{count} hours", { count: hours });
}

function BudgetRing({ label, value, resetAt, size = 76, compact = false }) {
  const [countdown, setCountdown] = useState(() => resetCountdown(resetAt));
  useEffect(() => {
    setCountdown(resetCountdown(resetAt));
    const timer = setInterval(() => setCountdown(resetCountdown(resetAt)), 60000);
    return () => clearInterval(timer);
  }, [resetAt]);
  const stroke = compact ? 5 : 6;
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - percent(value) / 100);
  return html`<div class=${`budget-ring ${compact ? "compact" : ""}`} role="img" aria-label=${`${label}: ${value == null ? "—" : `${value}%`}`}>
    <div class="budget-ring-visual" style=${`--ring-size:${size}px`}>
      <svg width=${size} height=${size} viewBox="0 0 44 44" aria-hidden="true">
        <circle class="budget-ring-track" cx="22" cy="22" r=${radius} fill="none" stroke-width=${stroke} />
        <circle class="budget-ring-value" cx="22" cy="22" r=${radius} fill="none" stroke-width=${stroke} stroke-linecap="round" stroke-dasharray=${circumference} stroke-dashoffset=${offset} />
      </svg>
      <span class="budget-ring-value-label">${value == null ? "—" : `${Math.round(value)}%`}</span>
    </div>
    <strong>${label}</strong>
    <small>${countdown}</small>
  </div>`;
}

export function BudgetRings({ budget, compact = false }) {
  const value = budget || {};
  return html`<div class=${`budget-rings ${compact ? "compact" : ""}`}>
    <${BudgetRing} label=${t("Weekly")} value=${value.weekly_percent} resetAt=${value.weekly_resets_at} size=${compact ? 58 : 82} compact=${compact} />
    <${BudgetRing} label=${t("Monthly")} value=${value.monthly_percent} resetAt=${value.monthly_resets_at} size=${compact ? 58 : 82} compact=${compact} />
  </div>`;
}

export function BudgetWeekly({ budget }) {
  const value = budget || {};
  const [open, setOpen] = useState(false);
  const countdown = resetCountdown(value.weekly_resets_at);
  return html`<button
    type="button"
    class="budget-chat-widget"
    aria-label=${t("Weekly budget usage")}
    aria-expanded=${open}
    title=${t("Weekly budget usage")}
    onClick=${() => setOpen(!open)}
  >
    <${BudgetRing} label=${t("Weekly")} value=${value.weekly_percent} resetAt=${value.weekly_resets_at} size=${38} compact />
    <span class="budget-chat-percent">${value.weekly_percent == null ? "—" : `${Math.round(value.weekly_percent)}%`}</span>
    ${open && html`<span class="budget-chat-tooltip" role="tooltip">
      ${t("Weekly budget usage")}: ${value.weekly_percent == null ? "—" : `${Math.round(value.weekly_percent)}%`} · ${countdown}
    </span>`}
  </button>`;
}

export function BudgetBlockedDialog({ budget, onClose }) {
  return html`<${Dialog} title=${t("Budget limit reached")} onClose=${onClose} className="budget-blocked-dialog">
    <p class="setting-description">${t("Your current turn can finish, but new messages are blocked until a budget resets or an administrator changes your limit.")}</p>
    <${BudgetRings} budget=${budget} />
    <div class="dialog-actions"><button class="button primary" onClick=${onClose}>${t("Close")}</button></div>
  </${Dialog}>`;
}

import { t } from "./i18n.js";

let productName = "Talaria";

export function setNotificationBrand(name) {
  productName = typeof name === "string" && name.trim() ? name.trim() : "Talaria";
}

export async function showBackgroundNotification(notice) {
  if (!("serviceWorker" in navigator)) return false;
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration) return false;
  await registration.showNotification(notice.title, {
    body: notice.body,
    tag: notice.tag,
    renotify: true,
    data: { url: notice.url || location.href },
  });
  return true;
}

function appBrandName() {
  return productName;
}


const completed = "completed";
const waiting = "waiting_for_input";
const notified = new Set();

function runKey(run) {
  return run?.id || run?.requestId || null;
}

function clarificationKey(run) {
  return run?.clarification?.request_id || run?.clarification?.prompt_id || null;
}

export function notificationForTransition(previous, next, session = {}) {
  if (!next || next.uncertain || next.outcomeUnknown) return null;
  const run = runKey(next);
  if (!run || runKey(previous) !== run) return null;
  const question = clarificationKey(next);
  if (next.status === waiting && previous?.status !== waiting && question) {
    return {
      kind: "clarification",
      tag: `clarification-${question}`,
      title: t("Your agent needs input"),
      body: next.clarification.question || t("Your agent is waiting for your answer."),
    };
  }
  if (next.status === completed && previous?.status !== completed) {
    const title = session.title || appBrandName();
    return {
      kind: "completed",
      tag: `run-complete-${run}`,
      title: t("Response complete"),
      body: t("{title} is ready.", { title }),
    };
  }
  return null;
}

export function notificationPermission() {
  return typeof Notification === "function" ? Notification.permission : "unsupported";
}

export async function requestNotificationPermission() {
  if (typeof Notification !== "function") return "unsupported";
  return Notification.requestPermission();
}

export async function showNotificationForTransition(
  sid,
  previous,
  next,
  session = {},
  { focused = document.hasFocus() } = {},
) {
  const notice = notificationForTransition(previous, next, session);
  if (focused || !notice || notificationPermission() !== "granted" || notified.has(notice.tag))
    return false;
  notified.add(notice.tag);
  try {
    const shown = await showBackgroundNotification(notice);
    if (shown) return true;
  } catch {
    // Fall through to the desktop-only constructor when available.
  }
  if (typeof Notification !== "function") return false;
  const item = new Notification(notice.title, { body: notice.body, tag: notice.tag });
  item.onclick = () => {
    window.focus();
    window.dispatchEvent(new CustomEvent("talaria:notification-click", { detail: { sid } }));
    item.close();
  };
  return true;
}

export function resetNotificationHistory() {
  notified.clear();
}

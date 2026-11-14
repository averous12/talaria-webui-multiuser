import { api } from "./api.js";

export async function backgroundNotificationStatus() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return "unsupported";
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    return registration && await registration.pushManager.getSubscription() ? "granted" : "default";
  } catch {
    return "default";
  }
}

export async function enableBackgroundNotifications() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return "unsupported";
  const workerUrl = new URL("../push-sw.js", import.meta.url).pathname;
  const registration = await navigator.serviceWorker.register(workerUrl, {
    scope: new URL("./", location.href).pathname,
  });
  await navigator.serviceWorker.ready;
  const { public_key: publicKey } = await api("/push/config");
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: decodeKey(publicKey),
    });
  }
  await api("/push/subscribe", { method: "POST", body: subscription.toJSON() });
  return "granted";
}

export async function disableBackgroundNotifications() {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) {
    await api("/push/unsubscribe", {
      method: "POST",
      body: { endpoint: subscription.endpoint },
    });
    await subscription.unsubscribe();
  }
}

function decodeKey(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

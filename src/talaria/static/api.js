import { apiURL } from "./profile-context.js";
import { msg } from "./i18n.js";

export function errorMessage(value, fallback = msg("Something went wrong. Please try again.")) {
  const text = typeof value === "string" ? value : value?.message;
  return typeof text === "string" && text.trim() ? text.slice(0, 4096) : fallback;
}

let transport;
export const setTransport = (value) => { transport = value; };
export const request = (path, options) => transport
  ? transport.request(path, options) : fetch(apiURL(path), options);
export const eventSource = (path) => transport
  ? transport.events(path) : new EventSource(apiURL(path));
// Each network stream holds one of the few connections a browser allows a server.
export const streamsUseConnections = () => !transport;

let csrf = "";
export const setCSRF = (value) => {
  csrf = value;
};
export class RequestError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function uploadFile(path, file, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiURL(path));
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-Talaria-Request", "1");
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.setRequestHeader("X-Talaria-Filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new RequestError(msg("Connection interrupted. Your work is still with Hermes."), 0, "network"));
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* report status below */ }
      if (xhr.status < 200 || xhr.status >= 300)
        return reject(new RequestError(errorMessage(data?.error || data), xhr.status, data?.code));
      onProgress(100);
      resolve(data);
    };
    xhr.send(file);
  });
}

export async function api(path, options = {}) {
  let response;
  const safe = ["GET", "HEAD"].includes((options.method || "GET").toUpperCase());
  const body = options.body === undefined ? undefined : JSON.stringify(options.body);
  try {
    response = await request(path, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(safe ? {} : { "X-Talaria-Request": "1", "X-CSRF-Token": csrf }),
        ...options.headers,
      },
      body,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new RequestError(msg("Connection interrupted. Your work is still with Hermes."), 0, "offline");
  }
  let data;
  try {
    data = response.status === 204 ? {} : await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw error;
    if (response.ok) throw new RequestError(msg("The server response could not be read."), 0, "invalid_response");
    data = {};
  }
  if (!response.ok) throw new RequestError(errorMessage(data?.error), response.status, data?.code);
  return data;
}

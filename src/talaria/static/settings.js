import {
  html,
  useEffect,
  useState,
  Icon,
  readStorage,
  writeStorage,
  useMediaQuery,
} from "./lib.js";
import { api } from "./api.js";
import { Installation } from "./installation.js";
import { Dialog } from "./dialogs.js";
import { ProfileConnections } from "./profiles.js";
import { refreshAgentInfo, refreshModels, supports, fail, update, effectiveAgent } from "./store.js";
import { ReadinessNotice } from "./readiness.js";
import { msg, t } from "./i18n.js";
import { notificationPermission, requestNotificationPermission } from "./notifications.js";
import { enableBackgroundNotifications, backgroundNotificationStatus } from "./push.js";
import { LanguageSelector } from "./language.js";
import { statusLabel } from "./content.js";

const sections = [
  ["agent", "spark", msg("Your agent")],
  ["appearance", "sun", msg("Appearance")],
  ["notifications", "message", msg("Notifications")],
  ["connection", "link", msg("Connection")],
  ["installation", "monitor", msg("Talaria")],
];
const readable = (value = "") =>
  value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function Facts({ items }) {
  return html`<dl class="settings-facts">
    ${items.map(
      ([label, value]) =>
        html`<div>
          <dt>${t(label)}</dt>
          <dd>${value ?? t("Not available")}</dd>
        </div>`,
    )}
  </dl>`;
}

function Overview({ app }) {
  const info = app.agentInfo,
    model = app.defaultModel;
  const presentation = effectiveAgent(app);
  return html`<div class="agent-overview">
    <div class="agent-identity">
      <span class="agent-monogram" aria-hidden="true"><${Icon} name=${presentation.icon} size=${24} /></span>
      <div>
        <h3>${presentation.name}</h3>
        <p>${app.branding?.agent_name_mode === "brand" ? app.branding.agent_name : t("Hermes Agent")}</p>
      </div>
      <span class=${`status-badge ${app.connected ? "positive" : ""}`}
        >${app.connected ? t("Connected") : t("Offline")}</span
      >
    </div>
    <${ReadinessNotice} app=${app} compact />
    <section class="default-model-card">
      <div class="section-heading">
        <h4>${t("Default model")}</h4>
        <span class="default-badge">${t("Default")}</span>
      </div>
      <p>${model?.id || t("Not shared by Hermes")}</p>
      <small
        >${model?.providerLabel || t("Model information is not available.")}</small
      >
    </section>
    <${Facts}
      items=${[
        [msg("Hermes version"), info?.version || t("Not available")],
        [
          msg("Gateway"),
          info?.gateway_state ? statusLabel(info.gateway_state) : t("Not available"),
        ],
        [
          msg("Health"),
          info?.status === "ok"
            ? t("Healthy")
            : info?.status
              ? statusLabel(info.status)
              : t("Not available"),
        ],
      ]}
    />
    ${info?.platforms.length > 0 &&
    html`<section class="settings-section">
      <h4>${t("Channels")}</h4>
      <div class="channel-list">
        ${info.platforms.map(
          (p) =>
            html`<span
              ><i
                class=${`connection-dot ${p.state === "connected" ? "connected" : ""}`}
              />${p.name === "api_server" ? "API" : readable(p.name)}<small
                >${statusLabel(p.state)}</small
              ></span
            >`,
        )}
      </div>
    </section>`}
  </div>`;
}

function AgentPresentationEditor({ app }) {
  const current = effectiveAgent(app);
  const [name, setName] = useState(current.name);
  const [icon, setIcon] = useState(current.icon);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const icons = [
    ["spark", "Star"],
    ["orb", "Orb"],
    ["bot", "Bot"],
    ["comet", "Comet"],
    ["neural", "Neural"],
    ["beacon", "Beacon"],
    ["constellation", "Constellation"],
    ["wave", "Wave"],
    ["prism", "Prism"],
  ];
  async function save() {
    setBusy(true);
    setError("");
    try {
      const saved = await api("/agent/presentation", { method: "PATCH", body: { name, icon } });
      update({ agentPresentation: saved });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return html`<section class="setting-section agent-presentation-editor">
    <h4>${t("Agent appearance")}</h4>
    <label class="field">${t("Agent name")}<input value=${name} maxlength="80" onInput=${(e) => setName(e.target.value)} /></label>
    <div class="icon-picker" role="radiogroup" aria-label=${t("Agent icon")}>
      ${icons.map(([value, label]) => html`<button type="button" role="radio" aria-label=${t(label)} aria-checked=${icon === value} class=${`icon-choice ${icon === value ? "selected" : ""}`} onClick=${() => setIcon(value)}>
        <${Icon} name=${value} size=${21} /><span class="sr-only">${t(label)}</span>
      </button>`)}
    </div>
    ${error && html`<p class="form-error" role="alert">${t(error)}</p>`}
    <div class="setting-actions"><button class="button primary" disabled=${busy || !name.trim()} onClick=${save}>${busy ? t("Saving…") : t("Save agent appearance")}</button></div>
  </section>`;
}

function Notifications() {
  const [permission, setPermission] = useState(notificationPermission());
  const [background, setBackground] = useState("checking");
  const [backgroundError, setBackgroundError] = useState("");
  useEffect(() => {
    backgroundNotificationStatus().then(setBackground);
  }, []);
  async function enable() {
    const result = await requestNotificationPermission();
    setPermission(result);
    if (result === "granted") {
      try {
        setBackgroundError("");
        setBackground(await enableBackgroundNotifications());
      } catch (error) {
        setBackgroundError(error.message || "Background notifications could not be enabled.");
      }
    }
  }
  async function setupBackground() {
    try {
      setBackgroundError("");
      setBackground(await enableBackgroundNotifications());
    } catch (error) {
      setBackgroundError(error.message || "Background notifications could not be enabled.");
    }
  }
  const backgroundLabel = background === "granted"
    ? t("Repair background notifications")
    : t("Enable background notifications");
  const supported = permission !== "unsupported";
  const enabled = permission === "granted";
  return html`<section class="setting-section notification-settings">
    <h3>${t("Notifications")}</h3>
    <p class="setting-description">${t("Get a browser alert when a response finishes or your agent needs input.")}</p>
    ${supported && !enabled && permission !== "denied" && html`<div class="setting-actions">
      <button class="button primary" onClick=${enable}>
        <${Icon} name="message" size=${17} />${t("Enable browser notifications")}
      </button>
    </div>`}
    ${enabled && html`<div class="settings-status-group">
      <p class="settings-status positive"><span class="status-dot"></span>${t("Browser notifications are enabled.")}</p>
      <p class=${`settings-status ${background === "granted" ? "positive" : "pending"}`}><span class="status-dot"></span>${background === "granted" ? t("Background notifications are enabled.") : t("Background notifications are not connected yet.")}</p>
    </div>`}
    ${enabled && html`<div class="setting-actions">
      <button class="button secondary" onClick=${setupBackground}>
        <${Icon} name="message" size=${17} />${backgroundLabel}
      </button>
    </div>`}
    ${backgroundError && html`<p class="form-error" role="alert">${t(backgroundError)}</p>`}
    ${permission === "denied" && html`<p class="form-error" role="alert">${t("Notifications are blocked. Allow them in your browser settings.")}</p>`}
    ${!supported && html`<p class="settings-status">${t("This browser does not support native notifications.")}</p>`}
  </section>`;
}

function Appearance() {
  const [theme, setTheme] = useState(readStorage("theme", "system"));
  const [palette, setPalette] = useState(readStorage("palette", "blue"));
  function choose(key, value) {
    writeStorage(key, value);
    document.documentElement.dataset[key] = value;
    (key === "theme" ? setTheme : setPalette)(value);
  }
  return html`<section class="setting-section"><${LanguageSelector} /></section>
    <section class="setting-section">
      <h3>${t("Appearance")}</h3>
      <div class="appearance-options" role="group" aria-label=${t("Appearance")}>
        ${[
          ["system", "monitor", msg("System")],
          ["light", "sun", msg("Light")],
          ["dark", "moon", msg("Dark")],
        ].map(
          ([id, icon, label]) =>
            html`<button
              class=${`appearance-option ${theme === id ? "selected" : ""}`}
              aria-pressed=${theme === id}
              onClick=${() => choose("theme", id)}
            >
              <${Icon} name=${icon} />${t(label)}
            </button>`,
        )}
      </div>
    </section>
    <section class="setting-section">
      <h3>${t("Accent color")}</h3>
      <div class="palette-options" role="group" aria-label=${t("Accent color")}>
        ${[["blue", msg("Blue")], ["sage", msg("Sage")], ["violet", msg("Violet")], ["rose", msg("Rose")]].map(
          ([id, label]) =>
            html`<button
              class=${`palette-option ${palette === id ? "selected" : ""}`}
              aria-pressed=${palette === id}
              onClick=${() => choose("palette", id)}
            >
              <span class=${`swatch ${id}`}
                >${palette === id &&
                html`<${Icon} name="check" size=${16} />`}</span
              >${t(label)}
            </button>`,
        )}
      </div>
    </section>`;
}

function Users({ app }) {
  const [users, setUsers] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [form, setForm] = useState({ username: "", password: "", profile_id: "default" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    const [userData, profileData] = await Promise.all([api("/users"), api("/profiles")]);
    setUsers(userData.users || []);
    setProfiles(profileData.profiles || []);
  }
  useEffect(() => { refresh().catch((e) => setError(e.message)); }, []);
  if (app.user?.role !== "admin") return null;
  async function create(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/users", {
        method: "POST",
        body: { ...form, role: "user" },
      });
      setForm({ username: "", password: "", profile_id: "default" });
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function toggle(user) {
    try {
      await api(`/users/${user.id}`, { method: "PATCH", body: { enabled: !user.enabled } });
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }
  return html`<div class="users-panel">
    <section class="setting-section">
      <h3>${t("Users")}</h3>
      <p>${t("Administrators can access every Hermes profile. Each user is assigned one profile.")}</p>
      ${error && html`<p class="form-error" role="alert">${t(error)}</p>`}
      <div class="users-list">
        ${users.map((user) => html`<div class="user-row">
          <div class="user-identity">
            <span class="user-monogram" aria-hidden="true">${user.username.slice(0, 1).toUpperCase()}</span>
            <span class="user-copy"><strong>${user.username}</strong><small>${user.profile_id ? profiles.find((profile) => profile.id === user.profile_id)?.label || user.profile_id : t("All profiles")}</small></span>
          </div>
          <div class="user-actions">
            <span class=${`status-badge ${user.role === "admin" ? "positive" : ""}`}>${t(user.role)}</span>
            <button class="button secondary" disabled=${user.id === app.user.id} onClick=${() => toggle(user)}>${user.enabled ? t("Disable") : t("Enable")}</button>
          </div>
        </div>`)}
      </div>
    </section>
    <section class="setting-section">
      <h3>${t("Add user")}</h3>
      <form onSubmit=${create}>
        <label class="field">${t("Username")}<input required value=${form.username} onInput=${(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label class="field">${t("Password")}<input required type="password" value=${form.password} onInput=${(e) => setForm({ ...form, password: e.target.value })} /></label>
        <label class="field">${t("Assigned profile")}<select value=${form.profile_id} onChange=${(e) => setForm({ ...form, profile_id: e.target.value })}>${profiles.map((profile) => html`<option value=${profile.id}>${profile.label}</option>`)}</select></label>
        <button class="button primary" disabled=${busy}>${busy ? t("Creating…") : t("Add user")}</button>
      </form>
    </section>
  </div>`;
}

export function Settings({ app, onClose, initialSection = "agent" }) {
  const demo = app.environment === "demo";
  const visibleSections = app.user?.role === "admin"
    ? [...sections.slice(0, 4), ["users", "spark", msg("Users")], sections[4]]
    : sections.slice(0, 3);
  const [section, setSection] = useState(initialSection);
  const [installationRefresh, setInstallationRefresh] = useState(0);
  const mobile = useMediaQuery("(max-width: 700px)");
  useEffect(() => {
    if (mobile)
      document
        .getElementById(`settings-tab-${section}`)
        ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [section, mobile]);
  const [busy, setBusy] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  // Opening Settings refreshes quietly: flipping the button to "Refreshing…"
  // for a background read looks like the dialog is still loading.
  async function refresh({ quiet = false } = {}) {
    if (!quiet) setBusy(true);
    setRefreshFailed(false);
    const results = await Promise.allSettled([
      refreshAgentInfo(),
      ...(supports("model_options") ? [refreshModels()] : []),
    ]);
    if (results.some((r) => r.status === "rejected"))
      setRefreshFailed(true);
    if (!quiet) setBusy(false);
  }
  useEffect(() => {
    refresh({ quiet: true });
  }, []);
  return html`<${Dialog} title=${t("Settings")} onClose=${onClose} className="settings-dialog">
    <div class="settings-layout"><nav class="settings-navigation" role="tablist" aria-label=${t("Settings sections")}>${visibleSections.map(
      ([id, icon, label], index) =>
        html`<button
          id=${`settings-tab-${id}`}
          role="tab"
          aria-controls="settings-content"
          aria-selected=${section === id}
          tabindex=${section === id ? 0 : -1}
          onClick=${() => {
            setSection(id);
            if (id === "installation") setInstallationRefresh((value) => value + 1);
          }}
          onKeyDown=${(e) => {
            const next =
              e.key === "Home"
                ? 0
                : e.key === "End"
                  ? visibleSections.length - 1
                  : ["ArrowRight", "ArrowDown"].includes(e.key)
                    ? (index + 1) % visibleSections.length
                    : ["ArrowLeft", "ArrowUp"].includes(e.key)
                      ? (index + visibleSections.length - 1) % visibleSections.length
                      : null;
            if (next !== null) {
              e.preventDefault();
              setSection(visibleSections[next][0]);
              document
                .getElementById(`settings-tab-${visibleSections[next][0]}`)
                ?.focus();
            }
          }}
        >
          <${Icon} name=${icon} size=${17} /><span>${t(label)}</span>
        </button>`,
    )}</nav>
    <div key=${section} class="settings-panel" id="settings-content" role="tabpanel" aria-labelledby=${`settings-tab-${section}`} tabindex="0">
      ${refreshFailed && html`<p class="form-error" role="alert">${t("Some agent information could not be refreshed. Your other settings are still available.")}</p>`}
      ${section === "agent" && html`<${Overview} app=${app} /><${AgentPresentationEditor} app=${app} />`}
      ${section === "appearance" && html`<${Appearance} />`}
      ${section === "notifications" && html`<${Notifications} />`}
      ${section === "users" && html`<${Users} app=${app} />`}
      ${section === "installation" && html`<${Installation} key=${installationRefresh} readOnly=${demo} />`}
      ${section === "connection" && html`<${ProfileConnections} app=${app} onRefresh=${refresh} readOnly=${demo} />`}
    </div></div>
    <footer class="settings-footer"><span>${app.branding?.product_name || "Talaria"} ${app.version}</span><div>${section !== "installation" && html`<button disabled=${busy} onClick=${() => refresh()}>${busy ? t("Refreshing…") : t("Refresh information")}</button>`}${!demo && html`<button onClick=${async () => {
      try {
        await api("/logout", { method: "POST", body: {} });
        location.reload();
      } catch (e) {
        fail(e);
      }
    }}>${t("Sign out")}</button>`}</div></footer>
  </${Dialog}>`;
}

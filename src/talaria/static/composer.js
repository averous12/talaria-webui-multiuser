import {
  html,
  isIMEKey,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  Icon,
  IconButton,
  readStorage,
  writeStorage,
} from "./lib.js";
import { useCommands } from "./commands.js";
import { sendMessage, stopRun, running } from "./runs.js";
import { fail, supports, navigationVersion, state, update, effectiveAgent } from "./store.js";
import {
  prepareImage,
  beginPendingImages,
  pendingStorage,
  consumePendingImages,
  MAX_IMAGES_TOTAL,
  imageName,
} from "./attachments.js";
import { sessionReasoning, sessionModel, reasoningLabel } from "./models.js";
import { BudgetBlockedDialog } from "./budget-ui.js";
import { t, msg, formatNumber } from "./i18n.js";

// Office, Numbers and LibreOffice put a picture of the selection beside its
// text. Paste the text unless it only names the copied files or links to the image.
function pastesText(data, files) {
  const text = data?.getData("text/plain").trim() || "";
  const rest = files.reduce((left, file) => left.replace(file.name, ""), text);
  return !!rest.trim() && !/^https?:\/\/\S+$/.test(text);
}

export function Composer({
  app,
  model,
  onModel,
  onReasoning,
  draftSuggestion,
  commandActivity,
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [blockedOpen, setBlockedOpen] = useState(false);
  const [images, setImages] = useState([]);
  const [files, setFiles] = useState([]);
  const [attaching, setAttaching] = useState(false);
  const [loadingImages, setLoadingImages] = useState(true);
  const [attachmentError, setAttachmentError] = useState("");
  const [dragging, setDragging] = useState(false);
  const operation = useRef(false);
  const submission = useRef(false);
  const textarea = useRef();
  const input = useRef();
  const agentName = effectiveAgent(app).name;
  const active = running(app.active, app.lives);
  const live = app.lives[app.active];
  const displayedModel = model || app.defaultModel;
  const reasoning = sessionReasoning(app);
  const reasoningText = reasoningLabel(reasoning, sessionModel(app) || app.defaultModel);
  const sendLabel = active
    ? live.clarification ? t("Send answer") : t("Send guidance")
    : t("Send message");
  const modelTitle = displayedModel
    ? `${displayedModel.providerLabel ? displayedModel.providerLabel + " · " : ""}${displayedModel.id}`
    : "";
  const key = `draft.${app.active || "new"}`;
  const currentKey = useRef(key);
  const currentDraft = useRef(draft);
  const currentImages = useRef(images);
  const currentFiles = useRef(files);
  currentKey.current = key;
  currentDraft.current = draft;
  currentImages.current = images;
  currentFiles.current = files;
  function chooseCommand(value) {
    currentDraft.current = value;
    setDraft(value);
    writeStorage(key, value);
    textarea.current?.focus();
  }
  const commands = useCommands(app, draft, chooseCommand, { onModel, onReasoning, active }, commandActivity);
  // Before painting, so switching sessions never shows the previous draft.
  useLayoutEffect(() => {
    setDraft(readStorage(key));
    setImages([]);
    setLoadingImages(true);
    setAttachmentError("");
    let current = true;
    pendingStorage(key)
      .then((saved) => {
        if (current && Array.isArray(saved)) setImages(saved.slice(0, 4));
      })
      .catch(() => {})
      .finally(() => {
        if (current) setLoadingImages(false);
      });
    return () => {
      current = false;
    };
  }, [key]);
  useEffect(() => {
    if (live?.recovered) {
      // Admission consumed the submitted text once. A later identical draft
      // still belongs here when this recovered session is reopened.
      currentDraft.current = readStorage(key);
      setDraft(currentDraft.current);
    }
  }, [live?.recovered, live?.requestId, key]);
  useEffect(() => {
    if (!live?.recovered || loadingImages || attaching) return;
    // Retry acknowledges the original payload. Attachments prepared afterward
    // belong to the next draft, including when its text still matches the retry.
    const submitted = new Set(live.recoveredImageIds || []);
    currentImages.current = currentImages.current.filter((image) => !submitted.has(image.id));
    setImages(currentImages.current);
    consumePendingImages(key, [...submitted].map((id) => ({ id }))).catch(() => {});
  }, [live?.recovered, live?.requestId, live?.recoveredImageIds, key, loadingImages, attaching]);
  useEffect(() => {
    const restored = app.restoredDraft;
    if (restored?.key !== key) return;
    update({ restoredDraft: null });
    // Never replace what someone has typed since; the draft is saved either way.
    if (readStorage(key) !== restored.text) return;
    currentDraft.current = restored.text;
    setDraft(restored.text);
    if (restored.images?.length && !currentImages.current.length) {
      currentImages.current = restored.images;
      setImages(restored.images);
    }
  }, [app.restoredDraft, key]);
  useEffect(() => {
    if (draftSuggestion && !app.active) {
      setDraft(draftSuggestion.text);
      writeStorage(key, draftSuggestion.text);
      textarea.current?.focus();
    }
  }, [draftSuggestion, app.active, key]);
  useLayoutEffect(() => {
    const el = textarea.current;
    if (!el || CSS.supports("field-sizing", "content")) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [draft]);
  async function send(e) {
    e?.preventDefault();
    if (app.budget?.blocked) {
      setBlockedOpen(true);
      return;
    }
    const submittedDraft = currentDraft.current;
    const text = submittedDraft.trim();
    const attachments = currentImages.current;
    const fileAttachments = currentFiles.current;
    if (
      commands.busy ||
      submission.current ||
      operation.current ||
      attaching ||
      loadingImages ||
      app.loading ||
      app.budget?.blocked ||
      live?.uncertain ||
      (!text && !attachments.length && !fileAttachments.length)
    )
      return;
    const generation = navigationVersion();
    submission.current = true;
    setSending(true);
    try {
      if (await commands.submit(text, attachments)) {
        const saved = readStorage(key);
        if (currentKey.current === key && currentDraft.current === submittedDraft &&
          (!saved || saved === submittedDraft))
          chooseCommand("");
        if (readStorage(key) === submittedDraft) writeStorage(key, "");
        return;
      }
      const sid = await sendMessage(text, model, {
        images: attachments,
        files: fileAttachments,
        reasoning,
      });
      if (
        generation === navigationVersion() &&
        (currentKey.current === key || currentKey.current === `draft.${sid}`)
      ) {
        // Consume the draft before unlocking, even if the DOM has not repainted.
        currentDraft.current = "";
        currentImages.current = [];
        currentFiles.current = [];
        setDraft("");
        setImages([]);
        setFiles([]);
        textarea.current?.focus();
      }
      // A component can be replaced while admission is pending. Consume only
      // this submission; a newer composer may already have saved another draft.
      for (const savedKey of new Set([key, `draft.${sid}`])) {
        const saved = readStorage(savedKey);
        if (saved === submittedDraft || (savedKey !== key && saved === text))
          writeStorage(savedKey, "");
        consumePendingImages(savedKey, attachments).catch(() => {});
      }
    } catch (error) {
      if (error.code === "budget_exceeded") {
        setBlockedOpen(true);
        update({ budget: { ...(app.budget || {}), blocked: true } });
      } else fail(error);
    } finally {
      setSending(false);
      submission.current = false;
    }
  }
  async function attach(files) {
    if (!files.length || operation.current || submission.current || state.loading) return;
    if (active) {
      setAttachmentError(
        msg("Attachments can be sent after this response finishes."),
      );
      return;
    }
    operation.current = true;
    const finish = beginPendingImages(key);
    setAttaching(true);
    setAttachmentError("");
    try {
      const savedImages = loadingImages ? await pendingStorage(key) : images;
      const previousImages = Array.isArray(savedImages) ? savedImages : [];
      const nextImages = [...previousImages];
      const previousFiles = currentFiles.current;
      const nextFiles = [...previousFiles];
      for (const file of files) {
        if (file.type.startsWith("image/")) {
          if (nextImages.length >= 4)
            throw new Error(msg("You can attach up to four images per message."));
          nextImages.push(await prepareImage(file));
          if (
            nextImages.reduce((n, image) => n + image.size, 0) >
            MAX_IMAGES_TOTAL
          )
            throw new Error(
              msg("Images must total no more than 6 MB. Remove an image or choose smaller files."),
            );
        } else {
          if (file.size > 25 * 1024 * 1024)
            throw new Error(msg("Files must be 25 MB or smaller."));
          if (nextFiles.length >= 8)
            throw new Error(msg("You can attach up to eight files per message."));
          nextFiles.push(file);
        }
      }
      const nextText = currentKey.current === key ? currentDraft.current : readStorage(key, draft);
      if (nextImages.length !== previousImages.length)
        await pendingStorage(key, nextImages);
      if (currentKey.current === key) {
        currentImages.current = nextImages;
        currentFiles.current = nextFiles;
        setImages(nextImages);
        setFiles(nextFiles);
        if (nextText !== currentDraft.current) setDraft(nextText);
        textarea.current?.focus();
      }
    } catch (e) {
      if (currentKey.current === key) setAttachmentError(e.message);
    } finally {
      finish();
      operation.current = false;
      setAttaching(false);
    }
  }
  async function removeImage(image) {
    if (operation.current || submission.current || loadingImages || state.loading) return;
    operation.current = true;
    const finish = beginPendingImages(key);
    setAttaching(true);
    setAttachmentError("");
    const next = images.filter((item) => item.id !== image.id);
    try {
      await pendingStorage(key, next.length ? next : null);
      if (currentKey.current === key) setImages(next);
    } catch (e) {
      if (currentKey.current === key) setAttachmentError(e.message);
    } finally {
      finish();
      operation.current = false;
      setAttaching(false);
    }
  }
  return html`<form
    class=${`composer ${dragging ? "drop-active" : ""}`}
    onSubmit=${send}
    onDragOver=${(e) => {
      if ([...e.dataTransfer.types].includes("Files")) {
        e.preventDefault();
        setDragging(true);
      }
    }}
    onDragLeave=${(e) => {
      if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false);
    }}
    onDrop=${(e) => {
      e.preventDefault();
      setDragging(false);
      attach([...e.dataTransfer.files]);
    }}
  >
    ${commands.panel}
    ${files.length > 0 &&
    html`<div class="attachment-tray file-attachment-tray" aria-label=${t("File attachments")}>
      ${files.map((file) => html`<div class="attachment-chip file-attachment-chip" key=${file.name}>
        <${Icon} name="file" size=${20} /><span>${file.name}<small>${formatNumber(Math.max(1, Math.round(file.size / 1024)))} KB</small></span>
        <${IconButton} name="close" label=${t("Remove {name}", { name: file.name })} disabled=${sending || attaching || app.loading}
          onClick=${() => { const next = currentFiles.current.filter((item) => item !== file); currentFiles.current = next; setFiles(next); }} />
      </div>`)}
    </div>`}
    ${images.length > 0 &&
    html`<div class="attachment-tray" aria-label=${t("Image attachments")}>
      ${images.map(
        (image) => {
          const name = imageName(image);
          const size = formatNumber(Math.max(1, Math.round(image.size / 1024)));
          return html`<div class="attachment-chip" key=${image.id}>
            <img src=${image.url} alt=${name} /><span
              >${name}<small
                >${image.resized ? t("Resized · {size} KB", { size }) : t("{size} KB", { size })}</small
              ></span
            >
            <${IconButton}
              name="close"
              label=${t("Remove {name}", { name })}
              disabled=${sending || attaching || app.loading}
              onClick=${() => removeImage(image)}
            />
          </div>`;
        },
      )}
    </div>`}
    ${images.length > 0 &&
    html`<p class="attachment-progress">
      ${t("Some Hermes versions save only image placeholders. Talaria keeps recent originals in this browser; download images you want to keep.")}
    </p>`}
    ${attaching &&
    html`<p class="attachment-progress" role="status">
      ${t("Preparing attachments…")}
    </p>`}
    ${attachmentError &&
    html`<div class="attachment-error" role="alert">
      ${t(attachmentError)}<${IconButton}
        name="close"
        label=${t("Dismiss attachment error")}
        onClick=${() => setAttachmentError("")}
      />
    </div>`}
    <div class="composer-input">
      <textarea
        ref=${textarea}
        aria-label=${t("Message {name}", { name: agentName })}
        aria-autocomplete="list"
        aria-controls=${commands.expanded ? "command-picker" : undefined}
        aria-activedescendant=${commands.expanded ? commands.option : undefined}
        placeholder=${active && live.clarification ? t("Answer your agent’s question…")
          : active && live.approval ? t("Answer the approval request to continue…")
            : t("Message {name}", { name: agentName })}
        value=${draft}
        rows="1"
        onInput=${(e) => {
          currentDraft.current = e.target.value;
          setDraft(e.target.value);
          writeStorage(key, e.target.value);
        }}
        onKeyDown=${(e) => {
          if (isIMEKey(e) || commands.keyDown(e)) return;
          if (
            e.key === "Enter" &&
            !e.shiftKey &&
            !matchMedia("(pointer: coarse)").matches
          ) {
            e.preventDefault();
            send();
          }
        }}
        onPaste=${(e) => {
          const files = [...(e.clipboardData?.files || [])];
          if (files.length && !pastesText(e.clipboardData, files)) {
            e.preventDefault();
            attach(files);
          }
        }}
        disabled=${!app.connected}
        readOnly=${sending}
        maxlength="800000"
      />
    </div>
    <div class="composer-toolbar">
      <div class="composer-left">
        <${IconButton}
          name="plus"
          label=${t("Attach files")}
          disabled=${!app.connected ||
          app.loading ||
          active ||
          attaching ||
          sending ||
          loadingImages}
          onClick=${() => input.current?.click()}
        /><input
          ref=${input}
          type="file"
          class="sr-only"
          tabindex="-1"
          aria-label=${t("File attachment")}
          multiple
          accept="*/*"
          onChange=${(e) => {
            attach([...e.target.files]);
            e.target.value = "";
          }}
        />
        ${app.user?.role !== "user" && html`<button
          class="model-button"
          type="button"
          aria-label=${t("Choose model")}
          title=${displayedModel
            ? !model ? t("{model} · Default", { model: modelTitle }) : modelTitle
            : t("Use the default model configured in Hermes")}
          onClick=${onModel}
          disabled=${active || !app.connected}
        >
          <span class="model-caption">${displayedModel?.id || t("Configured model")}</span>
          <${Icon} name="chevron" size=${14} />
        </button>`}
        <button
          class="model-button reasoning-button"
          type="button"
          aria-label=${t("Thinking Effort")}
          aria-haspopup="dialog"
          title=${t("Thinking Effort")}
          onClick=${onReasoning}
          disabled=${active || !app.connected}
        >
          <span class="model-caption">${reasoningText}</span>
          <${Icon} name="chevron" size=${14} />
        </button>
      </div>
      <div class="composer-right">
        ${active &&
        html`<span class="working-label"
          ><span class="live-dot" />${live.status === "stopping"
            ? t("Stopping")
            : live.approval
              ? t("Awaiting approval")
              : live.clarification ? t("Your input") : t("Working")}</span
        >`}
        ${active && !draft.trim()
          ? html`<button
              type="button"
              class="send-button stop-button"
              aria-label=${t("Stop response")}
              title=${t("Stop response")}
              disabled=${!supports("run_stop") ||
              live.status === "stopping" ||
              !live.id}
              onClick=${() => stopRun(app.active).catch(fail)}
            >
              <${Icon} name="stop" size=${17} />
            </button>`
          : html`<button
              class="send-button"
              type="submit"
              aria-label=${sendLabel}
              title=${sendLabel}
              disabled=${(!draft.trim() && !images.length) ||
              sending ||
              commands.busy ||
              attaching ||
              loadingImages ||
              app.loading ||
              (active && images.length > 0) ||
              !app.connected ||
              !supports("run_submission") ||
              !supports("session_resources") ||
              live?.uncertain ||
              (active && !live.clarification && !supports("run_steer"))}
            >
              <${Icon} name="arrow" size=${19} />
            </button>`}
      </div>
    </div>
    ${blockedOpen && html`<${BudgetBlockedDialog} budget=${app.budget} onClose=${() => setBlockedOpen(false)} />`}
  </form>`;
}

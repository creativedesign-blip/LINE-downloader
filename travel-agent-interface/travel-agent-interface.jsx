import { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import "./travel-agent-interface.css";
import {
  Send,
  Sparkles,
  Search,
  Copy,
  CopyPlus,
  Check,
  AlertTriangle,
  Loader2,
  ChevronRight,
  ChevronLeft,
  Inbox,
  Zap,
  CheckCircle2,
  ArrowUpRight,
  X,
  Bell,
  Layers,
  Clock,
  Maximize2,
  ArrowRight,
  Columns2,
  Square,
  CheckSquare,
  MousePointerClick,
  Globe,
  Database,
  KeyRound,
  LogIn,
  LogOut,
  ShieldCheck,
  UserRound,
  Upload,
  FolderPlus,
  FolderOpen,
  Tag,
  Power,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";

const toAbsoluteUrl = (url) => {
  if (!url) return "";
  try {
    return new URL(url, window.location.origin).href;
  } catch {
    return url;
  }
};

const dmFullImage = (dm) => dm?.fullImage || dm?.image || "";
const dmPreviewImage = (dm) => dm?.previewImage || dmFullImage(dm);
const INTERNAL_WEB = import.meta.env.VITE_INTERNAL_WEB === "1";

function DmImage({ dm, src, alt, className = "", loading = "lazy" }) {
  const primary = src || dm?.image || "";
  const fallback = dmFullImage(dm);
  const [current, setCurrent] = useState(primary);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setCurrent(primary);
    setFailed(false);
  }, [primary]);

  if (failed) {
    return (
      <div
        className={`${className} flex items-center justify-center bg-stone-200 text-stone-500 text-[11px] text-center px-2`}
        title="Image failed to load"
      >
        ??頛憭望?
      </div>
    );
  }

  return (
    <img
      src={current}
      alt={alt || dm?.title || ""}
      className={className}
      loading={loading}
      decoding="async"
      onError={() => {
        if (fallback && current !== fallback) {
          setCurrent(fallback);
          return;
        }
        setFailed(true);
      }}
    />
  );
}

const isLocalClipboardBridgeAvailable = () =>
  ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);

const mediaIdsForItems = (items) =>
  items
    .map((dm) => dm?.mediaId || dm?.raw?.media_id)
    .filter(Boolean);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const directDownloadName = (dm, index) => {
  const rawPath = dm?.raw?.branded_path || dm?.raw?.image_path || dmFullImage(dm) || "";
  const name = String(rawPath).split(/[\\/]/).pop()?.split("?")[0];
  return name || `travel-dm-${String(index + 1).padStart(2, "0")}.jpg`;
};

async function downloadDmImagesDirectly(items) {
  const images = items
    .map((dm, index) => ({
      href: dmFullImage(dm) || dmPreviewImage(dm),
      name: directDownloadName(dm, index),
    }))
    .filter((item) => item.href);
  if (images.length === 0) {
    throw new Error("No image URLs to download.");
  }

  for (const image of images) {
    const link = document.createElement("a");
    link.href = image.href;
    link.download = image.name;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
    await sleep(120);
  }
  return true;
}

async function copyDmImagesWithBridge(items) {
  if (!isLocalClipboardBridgeAvailable()) return false;

  const mediaIds = mediaIdsForItems(items);
  if (mediaIds.length === 0) return false;

  const response = await fetch("/api/openclaw/clipboard", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_ids: mediaIds }),
  });
  const payload = await response.json();
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.error || "clipboard bridge failed");
  }
  return true;
}

async function downloadDmImagesPackage(items) {
  if (INTERNAL_WEB) {
    return downloadDmImagesDirectly(items);
  }

  const mediaIds = mediaIdsForItems(items);
  if (mediaIds.length === 0) {
    throw new Error("No image URLs to download.");
  }

  const params = new URLSearchParams();
  mediaIds.forEach((id) => params.append("media_id", id));
  const directUrl = `/api/openclaw/download?${params.toString()}`;
  if (directUrl.length < 7000) {
    const link = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    link.href = directUrl;
    link.download = `agent-dm-images-${stamp}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    return true;
  }

  const response = await fetch("/api/openclaw/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_ids: mediaIds }),
  });

  if (!response.ok) {
    let message = "銝????仃??";
    try {
      const payload = await response.json();
      message = payload?.error || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  link.href = url;
  link.download = `agent-dm-images-${stamp}.zip`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return true;
}

const formatDmForClipboard = (dm, index = 0) => {
  if (typeof dm === "string") return dm;

  const lines = [
    `${index + 1}. ${dm?.title || "?? DM"}`,
    dm?.region ? `?啣?嚗?{dm.region}` : "",
    dm?.period ? `??嚗?{dm.period}` : "",
    dm?.price ? `?寞嚗?{dm.price}` : "",
    dm?.source ? `靘?嚗?{dm.source}` : "",
    dmFullImage(dm) ? `??嚗?{toAbsoluteUrl(dmFullImage(dm))}` : "",
  ].filter(Boolean);

  return lines.join("\n");
};

const formatDmListForClipboard = (items) =>
  items.map((dm, index) => formatDmForClipboard(dm, index)).join("\n\n");

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function clipboardDiagnostics() {
  const ua = navigator.userAgent || "";
  const browser =
    /Edg\//.test(ua) ? "Edge" :
    /Chrome\//.test(ua) ? "Chrome" :
    /Firefox\//.test(ua) ? "Firefox" :
    /Safari\//.test(ua) ? "Safari" :
    "Unknown";

  return {
    protocol: window.location.protocol,
    host: window.location.host,
    secure: Boolean(window.isSecureContext),
    focused: Boolean(document.hasFocus?.()),
    visibility: document.visibilityState || "unknown",
    clipboardWrite: Boolean(navigator.clipboard?.write),
    clipboardWriteText: Boolean(navigator.clipboard?.writeText),
    clipboardItem: Boolean(window.ClipboardItem),
    htmlClipboard: Boolean(window.ClipboardItem?.supports?.("text/html") ?? true),
    pngClipboard: Boolean(window.ClipboardItem?.supports?.("image/png") ?? true),
    browser,
  };
}

function buildClipboardError(message, cause) {
  const details = clipboardDiagnostics();
  const error = new Error(message);
  error.cause = cause;
  error.clipboardDetails = details;
  return error;
}

function explainClipboardError(error) {
  const message = String(error?.message || "");
  const name = String(error?.name || "");
  const details = error?.clipboardDetails || clipboardDiagnostics();

  let reason = "?汗?冽?蝯神?亙??鞎潛倏??";
  if (!details.secure || details.protocol !== "https:") {
    reason = "?桀?銝 HTTPS嚗汗?函?甇Ｙ雯??鋆賢???";
  } else if (!details.clipboardWrite || !details.clipboardItem) {
    reason = "?汗?其??舀???芾票蝪踴??冽??啁? Chrome ??Edge??";
  } else if (!details.focused || details.visibility !== "visible" || /not focused/i.test(message)) {
    reason = "?瘝??阡?????銝銝??Ｙ征?質?嚗??湔??鋆踝?銝???閬???";
  } else if (/notallowed|permission|denied/i.test(`${name} ${message}`)) {
    reason = "?芾票蝪踵??◤?汗?冽?蝯?蝣箄?蝬脣??椰?游?閮勗鞎潛倏嚗蒂?望???亥孛?潸?鋆賬?";
  } else if (/load image|fetch|network|failed/i.test(message)) {
    reason = "??頛憭望?嚗?賣憭雯??????雯???憭芣??";
  } else if (/too large|size|memory|canvas/i.test(message)) {
    reason = "??憭芸之????憭芸之嚗汗?函瘜?亙鞎潛倏??";
  }

  return [
    reason,
    `?銵??荔?${name || "Error"} ${message}`.trim(),
    `?啣?嚗?{details.browser} / secure=${details.secure} / focus=${details.focused} / visibility=${details.visibility} / write=${details.clipboardWrite} / ClipboardItem=${details.clipboardItem} / html=${details.htmlClipboard} / png=${details.pngClipboard}`,
  ].join("\n");
}

async function blobToPng(blob) {
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(bitmap, 0, 0);

    return await new Promise((resolve, reject) => {
      canvas.toBlob((png) => {
        if (png) resolve(png);
        else reject(new Error("Cannot encode clipboard image."));
      }, "image/png");
    });
  } finally {
    bitmap.close?.();
  }
}

async function fetchImageBlobForClipboard(url) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`Cannot load image for clipboard (${response.status}).`);
    return response.blob();
  } catch (error) {
    throw buildClipboardError("??頛憭望?嚗瘜?鋆賬?", error);
  }
}

async function fetchImageBitmap(url) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`Cannot load image for clipboard (${response.status}).`);
    return createImageBitmap(await response.blob());
  } catch (error) {
    throw buildClipboardError("??頛憭望?嚗瘜?鋆賬?", error);
  }
}

async function ensurePngBlob(blob) {
  return blob.type === "image/png" ? blob : blobToPng(blob);
}

async function blobToDataUrl(blob) {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Cannot encode image as base64."));
    reader.readAsDataURL(blob);
  });
}

async function imageBlobToBase64DataUrl(blob, maxWidth = 1400) {
  const bitmap = await createImageBitmap(blob);
  try {
    const scale = Math.min(1, maxWidth / bitmap.width);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    const pngBlob = await new Promise((resolve, reject) => {
      canvas.toBlob((encoded) => {
        if (encoded) resolve(encoded);
        else reject(new Error("Cannot encode image as PNG base64."));
      }, "image/png");
    });

    const dataUrl = await blobToDataUrl(pngBlob);
    if (!dataUrl.startsWith("data:image/png;base64,")) {
      throw new Error("Image was not encoded as data:image/png;base64.");
    }
    return dataUrl;
  } finally {
    bitmap.close?.();
  }
}

const escapeHtml = (value) =>
  String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

async function htmlFromImageBlobs(blobPromises, text = "") {
  const blobs = await Promise.all(blobPromises);
  const dataUrls = await Promise.all(blobs.map((blob) => imageBlobToBase64DataUrl(blob)));
  const images = dataUrls
    .map(
      (src, index) => `
        <div style="margin:0 0 32px 0;padding:0;">
          <img src="${src}" alt="travel image ${index + 1}" style="display:block;max-width:100%;height:auto;margin:0 0 8px 0;" />
        </div>
      `
    )
    .join("");

  return `<!doctype html>
    <html>
      <body>
        ${text ? `<p style="white-space:pre-wrap;font-family:sans-serif;">${escapeHtml(text)}</p>` : ""}
        ${images}
      </body>
    </html>`;
}

async function writeHtmlImagesToClipboard(blobPromises, text = "") {
  if (!window.isSecureContext || !navigator.clipboard?.write || !window.ClipboardItem) {
    throw buildClipboardError("?汗?其??迂 HTML ???芾票蝪踴?");
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    window.focus?.();
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    throw buildClipboardError("?瘝??阡?嚗瘜?鋆?HTML ????");
  }

  const htmlPromise = htmlFromImageBlobs(blobPromises, text).then(
    (html) => new Blob([html], { type: "text/html" })
  );
  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": htmlPromise,
      }),
    ]);
  } catch (error) {
    throw buildClipboardError("HTML base64 ??撖怠?芾票蝪踹仃??", error);
  }
}

async function writeImageBlobToClipboard(blobOrPromise) {
  if (!window.isSecureContext || !navigator.clipboard?.write || !window.ClipboardItem) {
    throw buildClipboardError("?汗?其??迂???芾票蝪踴?");
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    window.focus?.();
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    throw buildClipboardError("?瘝??阡?嚗瘜?鋆賢???");
  }

  // Clipboard writes require a transient user activation. Start the write
  // immediately from the click handler and let the image work finish inside
  // the ClipboardItem promise, otherwise slower remote images can be rejected.
  const pngPromise = Promise.resolve(blobOrPromise).then(ensurePngBlob);
  try {
    await navigator.clipboard.write([
      new ClipboardItem({ "image/png": pngPromise }),
    ]);
  } catch (error) {
    throw buildClipboardError("??撖怠?芾票蝪踹仃??", error);
  }
}

async function copyImageUrlToClipboard(url) {
  await writeImageBlobToClipboard(fetchImageBlobForClipboard(url));
}

async function copyImageUrlHtmlToClipboard(url, text = "") {
  await writeHtmlImagesToClipboard([fetchImageBlobForClipboard(url)], text);
}

async function copyImageListHtmlToClipboard(items, text = "") {
  const sources = items
    .map((dm) => dmPreviewImage(dm) || dmFullImage(dm))
    .filter(Boolean);
  if (sources.length === 0) throw new Error("No images to copy.");
  await writeHtmlImagesToClipboard(sources.map((source) => fetchImageBlobForClipboard(source)), text);
}

async function composeImagesForClipboard(items) {
  const sources = items
    .map((dm) => dmPreviewImage(dm) || dmFullImage(dm))
    .filter(Boolean);
  if (sources.length === 0) throw new Error("No images to compose.");

  const bitmaps = [];
  try {
    for (const source of sources) {
      bitmaps.push(await fetchImageBitmap(source));
    }

    const maxWidth = 1200;
    const padding = 36;
    const gap = 64;
    const scaled = bitmaps.map((bitmap) => {
      const width = Math.min(maxWidth, bitmap.width);
      const scale = width / bitmap.width;
      return {
        bitmap,
        width,
        height: Math.max(1, Math.round(bitmap.height * scale)),
      };
    });
    const canvasWidth = Math.max(...scaled.map((image) => image.width)) + padding * 2;
    const canvasHeight =
      scaled.reduce((total, image) => total + image.height, 0) +
      padding * 2 +
      gap * Math.max(0, scaled.length - 1);

    const canvas = document.createElement("canvas");
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#F5F1E8";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    let top = padding;
    for (let index = 0; index < scaled.length; index += 1) {
      const image = scaled[index];
      const left = Math.round((canvasWidth - image.width) / 2);
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(left - 1, top - 1, image.width + 2, image.height + 2);
      ctx.drawImage(image.bitmap, left, top, image.width, image.height);
      ctx.strokeStyle = "#D6CFB8";
      ctx.lineWidth = 2;
      ctx.strokeRect(left - 1, top - 1, image.width + 2, image.height + 2);
      if (index < scaled.length - 1) {
        const separatorTop = top + image.height + Math.round(gap / 2);
        ctx.fillStyle = "#D6CFB8";
        ctx.fillRect(padding, separatorTop, canvasWidth - padding * 2, 2);
      }
      top += image.height + gap;
    }

    return await new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("Cannot encode composed clipboard image."));
      }, "image/png");
    });
  } finally {
    bitmaps.forEach((bitmap) => bitmap.close?.());
  }
}

async function copyDmToClipboard(dm) {
  const text = formatDmForClipboard(dm);
  const hasImage = Boolean(dmFullImage(dm));
  let imageError = null;

  try {
    if (await copyDmImagesWithBridge([dm])) return "bridge";
  } catch (error) {
    console.warn("Clipboard bridge failed.", error);
  }

  if (
    hasImage &&
    window.isSecureContext &&
    navigator.clipboard?.write &&
    window.ClipboardItem
  ) {
    try {
      await copyImageUrlToClipboard(dmFullImage(dm));
      return "image";
    } catch (error) {
      imageError = error;
      console.warn("Browser image clipboard copy failed.", error);
    }
  }

  if (
    hasImage &&
    window.isSecureContext &&
    navigator.clipboard?.write &&
    window.ClipboardItem
  ) {
    try {
      await copyImageUrlHtmlToClipboard(dmFullImage(dm), text);
      return "html";
    } catch (error) {
      imageError = error;
      console.warn("HTML image clipboard copy failed.", error);
    }
  }

  if (hasImage) {
    if (!window.isSecureContext) {
      throw buildClipboardError("?桀?銝 HTTPS嚗汗?函?甇Ｚ?鋆賢???芾票蝪踴?");
    }
    if (!navigator.clipboard?.write || !window.ClipboardItem) {
      throw buildClipboardError("?汗?其??舀???芾票蝪選?隢??Chrome ??Edge??");
    }
    throw imageError || buildClipboardError("??瘝???撖怠?芾票蝪踴?");
  }

  await copyTextToClipboard(text);
  return "text";
}

async function copyDmListToClipboard(items) {
  const hasImages = items.some((dm) => dmPreviewImage(dm) || dmFullImage(dm));
  if (hasImages) {
    await downloadDmImagesPackage(items);
    return "download";
  }

  await copyTextToClipboard(formatDmListForClipboard(items));
  return "text";
}

function getLineImagePipelineStatus(status) {
  if (status?.pipeline) {
    return {
      activeSources: Array.isArray(status?.items) ? status.items : [],
      lineFetchedDone: Boolean(status.pipeline.line_fetched_done),
      ocrDone: Boolean(status.pipeline.ocr_done),
      composedDone: Boolean(status.pipeline.composed_done),
      errorFree: Boolean(status.pipeline.error_free),
      isComplete: Boolean(status.pipeline.is_complete),
      completedStages: Number(status.pipeline.completed_stages || 0),
      totalStages: Number(status.pipeline.total_stages || 3),
      label: status.pipeline.label || "LINE????銝?",
      color: status.pipeline.is_complete ? "#16A34A" : "#D97706",
    };
  }

  const sources = Array.isArray(status?.items) ? status.items : [];
  const activeSources = sources.filter((item) => {
    const total =
      Number(item.inbox_count || 0) +
      Number(item.travel_count || 0) +
      Number(item.branded_count || 0) +
      Number(item.indexed_count || 0) +
      Number(item.other_count || 0) +
      Number(item.error_count || 0);
    return total > 0;
  });

  const hasActiveSources = activeSources.length > 0;
  const lineFetchedDone =
    hasActiveSources &&
    activeSources.every((item) => Number(item.inbox_count || 0) === 0 && Number(item.travel_count || 0) > 0);
  const ocrDone =
    hasActiveSources &&
    activeSources.every((item) => Number(item.indexed_count || 0) >= Number(item.travel_count || 0));
  const composedDone =
    hasActiveSources &&
    activeSources.every((item) => Number(item.branded_count || 0) >= Number(item.travel_count || 0));
  const errorFree =
    hasActiveSources &&
    activeSources.every((item) => Number(item.error_count || 0) === 0);
  const isComplete = lineFetchedDone && ocrDone && composedDone && errorFree;
  const completedStages = [lineFetchedDone, ocrDone, composedDone].filter(Boolean).length;

  return {
    activeSources,
    lineFetchedDone,
    ocrDone,
    composedDone,
    errorFree,
    isComplete,
    completedStages,
    totalStages: 3,
    label: isComplete ? "LINE????摰?" : "LINE????銝?",
    color: isComplete ? "#16A34A" : "#D97706",
  };
}

function formatDateTime(value) {
  if (!value) return "撠";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-TW", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function manualJobLabel(job) {
  if (job?.running) return "?瑁?銝?";
  if (job?.status === "success") return "??";
  if (job?.status === "failed") return "憭望?";
  if (job?.last_success === true) return "??";
  if (job?.last_success === false) return "憭望?";
  if (job?.status === "stale") return "銝剜";
  return "?芸銵?";
}

function jobStepLabel(status) {
  if (status === "success") return "摰?";
  if (status === "running") return "??銝?";
  if (status === "failed") return "憭望?";
  if (status === "skipped") return "?仿?";
  return "蝑?";
}

function jobStepAccent(status) {
  return status === "running" || status === "failed" || status === "stale";
}

function jobSourceLabel(source) {
  if (source === "manual") return "??";
  if (source === "scheduled") return "摰?";
  if (source === "upload") return "??銝";
  if (source === "line-auto") return "LINE ?芸??砍?";
  if (source === "test") return "皜祈岫";
  return "?芰";
}

function manualJobMessage(job) {
  if (!job) return "??瘚?????芸?敺?";
  const parts = [
    `??瘚????${manualJobLabel(job)}`,
    `??嚗?{formatDateTime(job.last_started_at)}`,
    `蝯?嚗?{formatDateTime(job.last_finished_at)}`,
  ];
  if (job.pid) parts.push(`PID嚗?{job.pid}`);
  if (job.last_error) parts.push(`?航炊嚗?{job.last_error}`);
  return parts.join("??");
}

function isJobRunning(job) {
  return Boolean(job?.running || job?.status === "running");
}

function selectManualRunJob(status) {
  const latest = status?.latest_job || null;
  const manual = status?.manual_job || null;

  if (isJobRunning(manual)) return manual;
  if (isJobRunning(latest)) return latest;
  if (latest?.trigger_source === "manual") return latest;
  return manual || latest;
}

/* ===== MAIN APP ===== */
/* ===== DADOVA LOGO COMPONENT ===== */
function DadovaLogo({ size = 32, inverted = false }) {
  // Globe icon in rounded black square ??matches "?啁????? notification icon style
  const bg = inverted ? "#F5F1E8" : "#1C1917";
  const fg = inverted ? "#1C1917" : "#F5F1E8";

  return (
    <div
      style={{
        width: size,
        height: size,
        backgroundColor: bg,
        borderRadius: size * 0.18, // soft rounded square (~6px at 32px)
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
      aria-label="DADOVA"
    >
      <Globe
        style={{
          width: size * 0.55,
          height: size * 0.55,
          color: fg,
        }}
        strokeWidth={1.75}
      />
    </div>
  );
}

/* ===== Schedule command parser =====
 * Detects natural-language schedule commands so the UI can route them to
 * the real scheduler once an Agent/RPA endpoint exists.
 * Returns: { action: 'replace' | 'add' | 'remove' | 'view', times: ["HH:MM", ...] } | null
 */
function parseScheduleCommand(query) {
  const timeRegex = /\b([01]?\d|2[0-3]):([0-5]\d)\b/g;
  const matches = [...String(query || "").matchAll(timeRegex)];
  const times = matches.map((match) => `${String(parseInt(match[1], 10)).padStart(2, "0")}:${match[2]}`);
  const text = String(query || "").toLowerCase();
  const isScheduleContext = text.includes("schedule") || query.includes("排程") || query.includes("定時") || query.includes("時間");

  if (isScheduleContext && times.length === 0) {
    return { action: "view", times: [] };
  }
  if (times.length > 0 && (query.includes("刪") || query.includes("移除") || query.includes("取消") || text.includes("remove"))) {
    return { action: "remove", times };
  }
  if (times.length > 0 && (query.includes("新增") || query.includes("加入") || query.includes("加") || text.includes("add"))) {
    return { action: "add", times };
  }
  if (times.length > 0 && (isScheduleContext || query.includes("改") || query.includes("設定") || text.includes("replace"))) {
    return { action: "replace", times };
  }
  return null;
}
function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState("admin_dadova");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const passwordInput = form.elements.namedItem("password");
    const password = passwordInput?.value || "";
    setError("");
    setSubmitting(true);
    try {
      await onLogin({ username, password });
    } catch (loginError) {
      setError(loginError.message || "\u767b\u5165\u5931\u6557\uff0c\u8acb\u7a0d\u5f8c\u518d\u8a66\u3002");
    } finally {
      if (passwordInput) {
        passwordInput.value = "";
      }
      setSubmitting(false);
    }
  };

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center px-5 py-10 grain-bg"
      style={{
        backgroundColor: "#F5F1E8",
        color: "#1C1917",
        fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600&family=Geist:wght@300;400;500;600;700&family=Noto+Serif+TC:wght@400;500;700&display=swap');
        .font-display { font-family: 'Fraunces', 'Noto Serif TC', serif; font-optical-sizing: auto; }
        .font-serif-tc { font-family: 'Noto Serif TC', serif; }
        .grain-bg { background-image: radial-gradient(circle at 1px 1px, rgba(28,25,23,0.04) 1px, transparent 0); background-size: 24px 24px; }
      `}</style>

      <div className="w-full max-w-sm">
        <div className="flex items-center gap-3 mb-8">
          <DadovaLogo size={38} />
          <div>
            <div className="font-serif-tc text-xl font-medium leading-tight">DADOVA</div>
            <div className="text-[10px] tracking-[0.18em] uppercase text-stone-500 mt-1">
              {"Dadova \u00b7 agent"}
            </div>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-lg border bg-[#FAF7EE] p-6 shadow-sm"
          style={{ borderColor: "#E5DDC8" }}
        >
          <div className="flex items-center gap-2 text-xs font-medium text-stone-500 mb-3">
            <ShieldCheck className="w-4 h-4" />
            {"\u5916\u90e8\u4ecb\u9762\u767b\u5165"}
          </div>
          <h1 className="font-serif-tc text-2xl font-medium leading-tight mb-6">
            {"\u8acb\u5148\u767b\u5165 Agent \u4ecb\u9762"}
          </h1>

          <label className="block text-xs font-medium text-stone-600 mb-2" htmlFor="login-username">
            {"\u5e33\u865f"}
          </label>
          <div className="relative mb-4">
            <UserRound className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
            <input
              id="login-username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              className="w-full rounded-md border bg-white px-10 py-3 text-sm outline-none transition-colors focus:border-stone-900"
              style={{ borderColor: "#D6CFB8" }}
              required
            />
          </div>

          <label className="block text-xs font-medium text-stone-600 mb-2" htmlFor="login-password">
            {"\u5bc6\u78bc"}
          </label>
          <div className="relative mb-5">
            <KeyRound className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              className="w-full rounded-md border bg-white px-10 py-3 text-sm outline-none transition-colors focus:border-stone-900"
              style={{ borderColor: "#D6CFB8" }}
              required
            />
          </div>

          {error && (
            <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md px-4 py-3 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 flex items-center justify-center gap-2"
            style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
            {submitting ? "\u767b\u5165\u4e2d" : "\u767b\u5165"}
          </button>
        </form>
      </div>
    </div>
  );
}

function LoginGate() {
  const [checking, setChecking] = useState(true);
  const [sessionUser, setSessionUser] = useState("");

  useEffect(() => {
    let active = true;
    fetch("/api/auth/session", { credentials: "include" })
      .then((response) => response.json())
      .then((payload) => {
        if (!active) return;
        setSessionUser(payload?.authenticated ? payload.username || "admin_dadova" : "");
      })
      .catch(() => {
        if (active) setSessionUser("");
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleLogin = async ({ username, password }) => {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.error || "\u767b\u5165\u5931\u6557");
    }
    setSessionUser(payload.username || username);
  };

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      setSessionUser("");
    }
  };

  if (checking) {
    return (
      <div
        className="min-h-screen w-full flex items-center justify-center"
        style={{ backgroundColor: "#F5F1E8", color: "#1C1917" }}
      >
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );
  }

  if (!sessionUser) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  return <TravelAgent sessionUser={sessionUser} onLogout={handleLogout} />;
}

export default function TravelAgent({ sessionUser = "admin_dadova", onLogout } = {}) {
  const [messages, setMessages] = useState([
    { id: 1, role: "agent", type: "welcome", time: "隞 09:42" },
  ]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [preview, setPreview] = useState(null); // { dm, list }
  const [compareDup, setCompareDup] = useState(null);
  const [selectMode, setSelectMode] = useState(null); // { list }
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifRead, setNotifRead] = useState(false);
  const [overview, setOverview] = useState({
    status: null,
    latest: null,
    duplicates: null,
    loading: true,
    error: null,
  });
  const [uploadFolders, setUploadFolders] = useState([]);
  const [uploadDetail, setUploadDetail] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [lineAutoEnabled, setLineAutoEnabled] = useState(true);
  const [activeWorkspace, setActiveWorkspace] = useState("chat");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [toast, setToast] = useState(null);
  const notifRef = useRef(null);
  const enterArmedRef = useRef(false);
  const enterTimerRef = useRef(null);
  const scrollRef = useRef(null);
  const manualPreviewPollRef = useRef(null);
  const inputRef = useRef(null);

  const suggestions = [
    { icon: Inbox, label: "????", prompt: "??????" },
    { icon: Zap, label: "????+OCR+??", prompt: "??????+ocr+??" },
    { icon: Search, label: "????", prompt: "??????" },
    { icon: Layers, label: "????", prompt: "??????" },
  ];

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, isThinking]);

  // Close notification panel on outside click + Esc
  useEffect(() => {
    if (!notifOpen) return;
    const onClickOutside = (e) => {
      if (notifRef.current && !notifRef.current.contains(e.target)) {
        setNotifOpen(false);
      }
    };
    const onKey = (e) => e.key === "Escape" && setNotifOpen(false);
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onKey);
    };
  }, [notifOpen]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const getTime = () => {
    const d = new Date();
    return `隞 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  const formatPrice = (value) => {
    const n = Number(value);
    return Number.isFinite(n) && n >= 5000 ? `NT$ ${n.toLocaleString()}` : "?寞敺Ⅱ隤?";
  };

  const formatPriceSummary = (item) => {
    const planPrices = Array.isArray(item.plan_prices)
      ? [...new Set(item.plan_prices.map(Number).filter((n) => Number.isFinite(n) && n >= 5000))]
      : [];
    if (planPrices.length > 1) {
      return `NT$ ${planPrices.map((n) => n.toLocaleString()).join(" / ")}`;
    }
    return formatPrice(planPrices[0] || item.price_from);
  };

  const formatPeriod = (item) => {
    const months = Array.isArray(item.months) && item.months.length
      ? `${item.months.join(", ")} ?`
      : "????";
    const indexed = item.indexed_at
      ? `?? ${new Date(item.indexed_at).toLocaleDateString("zh-TW")}`
      : "";
    return [months, indexed].filter(Boolean).join(" ? ");
  };

  const normalizeAgentItem = (item, index = 0) => {
    const countries = Array.isArray(item.countries) ? item.countries : [];
    const regions = Array.isArray(item.regions) ? item.regions : [];
    const features = Array.isArray(item.features) ? item.features : [];
    const place = [...countries, ...regions].filter(Boolean).join(" / ") || "??";
    const days = Number(item.duration_days) || 0;
    const priceSummary = formatPriceSummary(item);
    const titleParts = [place, days ? `${days} ?` : "", priceSummary];

    return {
      id: item.sidecar_path || item.branded_path || item.image_path || `openclaw-${index}`,
      image: item.thumbnail_url || item.image_url || item.branded_path || item.image_path || "",
      fullImage: item.image_url || item.branded_path || item.image_path || "",
      previewImage: item.preview_url || item.image_url || item.branded_path || item.image_path || "",
      thumbnail: item.thumbnail_url || item.image_url || item.branded_path || item.image_path || "",
      mediaId: item.media_id || "",
      title: titleParts.filter(Boolean).join(" ? "),
      region: place,
      period: formatPeriod(item),
      days,
      price: priceSummary,
      tag: features[0] || "Agent",
      keywords: [...countries, ...regions, ...features],
      highlights: [
        countries.length ? `國家：${countries.join("、")}` : "國家未定",
        regions.length ? `地區：${regions.join("、")}` : "地區未定",
        item.group_name || item.target_id ? `群組：${item.group_name || item.target_id}` : "群組未定",
      ],
      raw: item,
    };
  };

  const criteriaFromPayload = (payload, fallbackQuery) => {
    const filters = payload?.filters || {};
    const countries = filters.countries || [];
    const regions = filters.regions || [];
    const months = filters.months || [];
    const features = filters.features || [];
    const criteria = {};
    const joinedRegion = [...countries, ...regions].filter(Boolean).join(" / ");
    if (joinedRegion) criteria.region = joinedRegion;
    if (months.length > 1) criteria.months = months;
    if (months.length === 1) criteria.month = months[0];
    if (filters.duration_days) criteria.days = filters.duration_days;
    if (filters.price_min) criteria.minPrice = filters.price_min;
    if (filters.price_max) criteria.maxPrice = filters.price_max;
    if (features.length) criteria.feature = features.join(" / ");
    return criteria;
  };

  const duplicateGroupsFromPayload = (payload) => {
    const groups = Array.isArray(payload?.groups) ? payload.groups : [];
    return groups.map((group, groupIndex) => {
      const items = Array.isArray(group.items) ? group.items : [];
      const dms = items.map((item, itemIndex) => normalizeAgentItem(item, itemIndex));
      const match = group.match || {};
      const keyParts = [
        ...(match.countries || []),
        ...(match.regions || []),
        Array.isArray(match.months) && match.months.length ? `${match.months.join(", ")} ?` : "",
        match.duration_days ? `${match.duration_days} ?` : "",
        match.price_bucket ? `? NT$ ${Number(match.price_bucket).toLocaleString()}` : "",
      ].filter(Boolean);

      return {
        key: keyParts.join(" ? ") || `???? ${groupIndex + 1}`,
        groupId: group.group_id || "",
        count: group.count || dms.length,
        images: dms.map((dm) => ({
          dm,
          source: dm.source,
          time: dm.raw?.indexed_at
            ? new Date(dm.raw.indexed_at).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })
            : "敺Ⅱ隤?",
        })),
      };
    }).filter((group) => group.images.length > 0);
  };

  const refreshOverview = async () => {
    try {
      setOverview((current) => ({ ...current, loading: true, error: null }));
      const [statusRes, latestRes, duplicatesRes] = await Promise.all([
        fetch("/api/openclaw/status"),
        fetch("/api/openclaw/latest?limit=8"),
        fetch("/api/openclaw/duplicates?limit=20"),
      ]);
      const [status, latest, duplicates] = await Promise.all([
        statusRes.json(),
        latestRes.json(),
        duplicatesRes.json(),
      ]);
      setOverview({
        status,
        latest,
        duplicates,
        loading: false,
        error: status.error || latest.error || duplicates.error || null,
      });
    } catch (error) {
      setOverview((current) => ({
        ...current,
        loading: false,
        error: error.message,
      }));
    }
  };

  const refreshUploadFolders = async () => {
    const response = await fetch("/api/uploads/folders?limit=30");
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "folders failed");
    setUploadFolders(Array.isArray(payload.folders) ? payload.folders : []);
  };

  const refreshOpenclawSettings = async () => {
    const response = await fetch("/api/openclaw/settings");
    const payload = await response.json();
    if (response.ok && payload?.settings) {
      setLineAutoEnabled(Boolean(payload.settings.line_auto_enabled));
    }
  };

  const refreshUploadDetail = async (folderId) => {
    if (!folderId) return;
    const response = await fetch(`/api/uploads/folders/${folderId}`);
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "folder detail failed");
    setUploadDetail(payload);
  };

  const handleUploadImages = async ({ displayName, note, files }) => {
    if (!displayName.trim()) throw new Error("隢撓?亥??冗?迂");
    if (!files?.length) throw new Error("隢????");
    setUploading(true);
    setUploadError("");
    try {
      const folderResponse = await fetch("/api/uploads/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.trim(), note: note.trim() }),
      });
      const folderPayload = await folderResponse.json();
      if (!folderResponse.ok || !folderPayload?.ok) {
        throw new Error(folderPayload?.error || "撱箇?鞈?憭曉仃??");
      }

      const form = new FormData();
      Array.from(files).forEach((file) => form.append("images", file));
      const uploadResponse = await fetch(`/api/uploads/folders/${folderPayload.folder.id}/images`, {
        method: "POST",
        body: form,
      });
      const uploadPayload = await uploadResponse.json();
      if (!uploadResponse.ok || !uploadPayload?.ok) {
        throw new Error(uploadPayload?.error || "銝憭望?");
      }
      await refreshUploadFolders();
      await refreshUploadDetail(folderPayload.folder.id);
      refreshOverview();
      return uploadPayload;
    } finally {
      setUploading(false);
    }
  };

  const handleUploadImagesToFolder = async ({ folderId, files }) => {
    if (!folderId) throw new Error("隢???冗");
    if (!files?.length) throw new Error("隢????");
    setUploading(true);
    setUploadError("");
    try {
      const form = new FormData();
      Array.from(files).forEach((file) => form.append("images", file));
      const uploadResponse = await fetch(`/api/uploads/folders/${folderId}/images`, {
        method: "POST",
        body: form,
      });
      const uploadPayload = await uploadResponse.json();
      if (!uploadResponse.ok || !uploadPayload?.ok) {
        throw new Error(uploadPayload?.error || "銝憭望?");
      }
      await refreshUploadFolders();
      await refreshUploadDetail(folderId);
      refreshOverview();
      return uploadPayload;
    } finally {
      setUploading(false);
    }
  };

  const handleToggleLineAuto = async () => {
    const next = !lineAutoEnabled;
    const response = await fetch("/api/openclaw/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ line_auto_enabled: next }),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "settings failed");
    setLineAutoEnabled(Boolean(payload.settings.line_auto_enabled));
  };

  const handleAddManualTag = async (imageId, tag) => {
    const value = String(tag || "").trim();
    if (!value) return;
    const response = await fetch(`/api/uploads/images/${imageId}/manual-tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: value }),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "tag failed");
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id);
  };

  const handleDeleteManualTag = async (tagId) => {
    const response = await fetch(`/api/uploads/manual-tags/${tagId}`, { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "delete tag failed");
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id);
  };

  const handleUpdateManualTag = async (tagId, tag) => {
    const value = String(tag || "").trim();
    if (!value) return;
    const response = await fetch(`/api/uploads/manual-tags/${tagId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: value }),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "update tag failed");
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id);
  };

  const handleUpdateImageMetadata = async (imageId, data) => {
    const response = await fetch(`/api/uploads/images/${imageId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "update image failed");
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id);
  };

  const handleArchiveImage = async (imageId) => {
    const response = await fetch(`/api/uploads/images/${imageId}`, { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok || !payload?.ok) throw new Error(payload?.error || "archive image failed");
    if (uploadDetail?.folder?.id) {
      await refreshUploadDetail(uploadDetail.folder.id);
      await refreshUploadFolders();
    }
  };

  useEffect(() => {
    refreshOverview();
    refreshUploadFolders().catch((error) => setUploadError(error.message));
    refreshOpenclawSettings().catch(() => {});
    const id = setInterval(refreshOverview, 60_000);
    const uploadId = setInterval(() => {
      refreshUploadFolders().catch(() => {});
      if (uploadDetail?.folder?.id) refreshUploadDetail(uploadDetail.folder.id).catch(() => {});
    }, 10_000);
    return () => {
      clearInterval(id);
      clearInterval(uploadId);
      if (manualPreviewPollRef.current) manualPreviewPollRef.current.cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadDetail?.folder?.id]);

  const buildAgentResponse = (payload, query) => {
    if (payload?.error) {
      return {
        id: Date.now() + 1,
        role: "agent",
        type: "text",
        content: `Agent ??航炊嚗?{payload.error}`,
        time: getTime(),
      };
    }

    if (payload?.kind === "status") {
      return {
        id: Date.now() + 1,
        role: "agent",
        type: "status",
        status: payload,
        time: getTime(),
      };
    }

    if (payload?.kind === "duplicates") {
      const groups = duplicateGroupsFromPayload(payload);
      if (groups.length === 0) {
        return {
          id: Date.now() + 1,
          role: "agent",
          type: "text",
          content: "瘝??曉敺?????????",
          time: getTime(),
        };
      }
      return {
        id: Date.now() + 1,
        role: "agent",
        type: "duplicates",
        groups,
        time: getTime(),
      };
    }

    const items = Array.isArray(payload?.items) ? payload.items : [];
    const dms = items.map((item, index) => normalizeAgentItem(item, index));
    if (dms.length === 0) {
      return {
        id: Date.now() + 1,
        role: "agent",
        type: "text",
        content: `???????${query}?? DM?`,
        time: getTime(),
      };
    }

    if (payload?.kind === "latest") {
      return {
        id: Date.now() + 1,
        role: "agent",
        type: "daily-summary",
        query,
        dms,
        time: getTime(),
      };
    }

    return {
      id: Date.now() + 1,
      role: "agent",
      type: "results",
      query,
      criteria: criteriaFromPayload(payload, query),
      dms,
      time: getTime(),
      fallback: false,
    };
  };

  const showOverviewMessage = (payload, kind, query) => {
    if (!payload) return;
    setNotifOpen(false);
    setNotifRead(true);
    setMessages((p) => [
      ...p,
      buildAgentResponse({ ...payload, kind }, query),
    ]);
  };

  const fetchTodayCombinationPayload = async () => {
    const response = await fetch("/api/openclaw/latest?today=1&composed_only=1&limit=60");
    const payload = await response.json();
    return { ...payload, kind: "latest" };
  };

  const appendTodayCombinationPreview = async (query = "?亦?隞蝯?") => {
    const payload = await fetchTodayCombinationPayload();
    setMessages((p) => [...p, buildAgentResponse(payload, query)]);
    await refreshOverview();
  };

  const pollManualRunForPreview = async () => {
    if (manualPreviewPollRef.current) manualPreviewPollRef.current.cancelled = true;
    const token = { cancelled: false };
    manualPreviewPollRef.current = token;
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    for (let attempt = 0; attempt < 180; attempt += 1) {
      await sleep(attempt === 0 ? 8_000 : 10_000);
      if (token.cancelled) return;
      try {
        const response = await fetch("/api/openclaw/status");
        const status = await response.json();
        if (!response.ok) throw new Error(status?.error || `HTTP ${response.status}`);
        const job = selectManualRunJob(status);
        setOverview((current) => ({
          ...current,
          status,
          loading: false,
          error: status.error || current.error || null,
        }));

        if (!job || job.running || job.status === "running") continue;

        const ok = job.status === "success" || job.last_success === true;
        if (ok) {
          await appendTodayCombinationPreview("??瘚?摰?嚗??亦???");
        } else {
          setMessages((p) => [
            ...p,
            {
              id: Date.now() + 1,
              role: "agent",
              type: "text",
              content: `??????${job.last_error ? `?${job.last_error}` : ""}`,
              time: getTime(),
            },
          ]);
        }
        return;
      } catch (error) {
        if (attempt >= 2) {
          setOverview((current) => ({ ...current, loading: false, error: error.message }));
        }
      }
    }

    if (!token.cancelled) {
      setMessages((p) => [
        ...p,
        {
          id: Date.now() + 1,
          role: "agent",
          type: "text",
          content: "??瘚?隞?摰?嚗?蝔?頛詨????亦???敺?閬賬?",
          time: getTime(),
        },
      ]);
    }
  };

  const handleSend = async (text) => {
    const message = (text !== undefined ? text : input).trim();
    if (!message) return;

    setMessages((p) => [
      ...p,
      { id: Date.now(), role: "user", type: "text", content: message, time: getTime() },
    ]);
    setInput("");
    enterArmedRef.current = false;
    if (enterTimerRef.current) {
      clearTimeout(enterTimerRef.current);
      enterTimerRef.current = null;
    }
    setIsThinking(true);

    const m = message;

    if (isManualAgentRunCommand(m)) {
      try {
        const apiResponse = await fetch("/api/openclaw/run", { method: "POST" });
        const payload = await apiResponse.json();
        if (!apiResponse.ok) throw new Error(payload?.error || `HTTP ${apiResponse.status}`);
        setMessages((p) => [
          ...p,
          {
            id: Date.now() + 1,
            role: "agent",
            type: "text",
            content: payload?.ok
              ? `${payload?.started === false ? "?????????" : "???????+OCR+??"}${payload?.job ? ` ${manualJobMessage(payload.job)}` : ""}`
              : `?????????${payload?.error || "????"}`,
            time: getTime(),
          },
        ]);
        refreshOverview();
        if (payload?.ok) pollManualRunForPreview();
      } catch (error) {
        setMessages((p) => [
          ...p,
          {
            id: Date.now() + 1,
            role: "agent",
            type: "text",
            content: `??閫貊憭望?嚗?{error.message}`,
            time: getTime(),
          },
        ]);
      } finally {
        setIsThinking(false);
      }
      return;
    }

    // ===== Schedule commands take priority ??they're explicit ops =====
    const scheduleCmd = parseScheduleCommand(m);
    if (scheduleCmd) {
      const response = {
        id: Date.now() + 1,
        role: "agent",
        type: "schedule-unavailable",
        action: scheduleCmd.action,
        requestedTimes: scheduleCmd.times,
        time: getTime(),
      };
      setIsThinking(false);
      setMessages((p) => [...p, response]);
      return;
    }

    try {
      const apiResponse = await fetch("/api/openclaw/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: m, limit: 60 }),
      });
      const payload = await apiResponse.json();
      const response = buildAgentResponse(payload, m);
      setMessages((p) => [...p, response]);
    } catch (error) {
      setMessages((p) => [
        ...p,
        {
          id: Date.now() + 1,
          role: "agent",
          type: "text",
          content: `?⊥???? Agent嚗?{error.message}`,
          time: getTime(),
        },
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  // Helpers ??armed state stored in ref for synchronous read between rapid keystrokes
  const armEnter = () => {
    enterArmedRef.current = true;
    if (enterTimerRef.current) clearTimeout(enterTimerRef.current);
    enterTimerRef.current = setTimeout(() => {
      enterArmedRef.current = false;
      enterTimerRef.current = null;
    }, 1500);
  };

  const cancelArmed = () => {
    enterArmedRef.current = false;
    if (enterTimerRef.current) {
      clearTimeout(enterTimerRef.current);
      enterTimerRef.current = null;
    }
  };

  // Double-Enter to send ??IME-aware (Chinese input safe), skips empty input
  const handleKeyDown = (e) => {
    const isEnter = e.key === "Enter";
    const isComposing = e.nativeEvent.isComposing || e.keyCode === 229;

    // During IME composition: if Enter (IME-confirm), prime the arming.
    // This way Chinese users only need 1 more Enter after composition to send,
    // instead of 3 total (1 IME confirm + 2 send).
    if (isComposing) {
      if (isEnter) armEnter();
      return;
    }

    // Non-Enter or Shift+Enter: cancel armed state if user is typing/editing
    if (!isEnter || e.shiftKey) {
      if (
        enterArmedRef.current &&
        (e.key.length === 1 || e.key === "Backspace" || e.key === "Delete")
      ) {
        cancelArmed();
      }
      return;
    }

    // Real Enter (no IME, no Shift)
    e.preventDefault();

    // Empty input: don't arm or send
    if (!input.trim()) {
      cancelArmed();
      return;
    }

    if (enterArmedRef.current) {
      cancelArmed();
      handleSend();
    } else {
      armEnter();
    }
  };

  const handleCopy = async (target) => {
    const items = Array.isArray(target) ? target.filter(Boolean) : [target].filter(Boolean);
    if (items.length === 0) return false;

    try {
      const copyMode =
        items.length === 1
          ? await copyDmToClipboard(items[0])
          : await copyDmListToClipboard(items);

      if (copyMode === "text") {
        window.alert(
          "?? HTTPS ???????????????????"
        );
        return false;
      }

      if (copyMode === "download") {
        window.alert(INTERNAL_WEB ? "??????" : "????????");
      }

      if (copyMode === "download") return true;

      const copiedKey =
        items.length === 1 && typeof items[0] !== "string"
          ? items[0].id
          : items.map((dm) => (typeof dm === "string" ? dm : dm.id)).join("|");
      setCopiedId(copiedKey || "clipboard");
      setTimeout(() => setCopiedId(null), 2000);
      return true;
    } catch (error) {
      console.error("Clipboard copy failed.", error);
      window.alert(`??銴ˊ憭望?\n\n${explainClipboardError(error)}`);
      return false;
    }
  };

  const handleDuplicateReview = async (group, keepIndex = 0, action = "keep_one") => {
    const images = Array.isArray(group?.images) ? group.images : [];
    const keep = images[keepIndex]?.dm;
    const keepPath = keep?.raw?.sidecar_path || keep?.id;
    const archivePaths = images
      .filter((_, index) => index !== keepIndex)
      .map((item) => item?.dm?.raw?.sidecar_path || item?.dm?.id)
      .filter(Boolean);
    if (!group?.groupId) {
      window.alert("蝻箏???蝢斤? ID嚗瘜摮祟?詻?");
      return false;
    }
    if (action === "keep_one" && !keepPath) {
      window.alert("蝻箏?靽???頝臬?嚗瘜摮祟?詻?");
      return false;
    }
    try {
      const response = await fetch("/api/openclaw/duplicates/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          group_id: group.groupId,
          action,
          keep_sidecar_paths: action === "keep_one" ? [keepPath] : [],
          archived_sidecar_paths: action === "keep_one" ? archivePaths : [],
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload?.ok) {
        throw new Error(payload?.error || "review failed");
      }
      setMessages((current) => current.map((msg) => {
        if (msg.type !== "duplicates" || !Array.isArray(msg.groups)) return msg;
        return { ...msg, groups: msg.groups.filter((item) => item.groupId !== group.groupId) };
      }));
      setOverview((current) => {
        const groups = Array.isArray(current.duplicates?.groups)
          ? current.duplicates.groups.filter((item) => item.group_id !== group.groupId)
          : [];
        return {
          ...current,
          duplicates: current.duplicates
            ? { ...current.duplicates, groups, count: groups.length }
            : current.duplicates,
        };
      });
      setCompareDup(null);
      return true;
    } catch (error) {
      console.error("Duplicate review failed.", error);
      window.alert(`????撖拇?脣?憭望?嚗?{error.message}`);
      return false;
    }
  };

  const latestCount = Number(overview.latest?.count || 0);
  const duplicateCount = Number(overview.duplicates?.count || 0);
  const totalIndexed = Number(overview.status?.total_indexed || 0);
  const hasUnreadNotifications = !notifRead && !overview.loading && (latestCount > 0 || duplicateCount > 0);
  const linePipeline = getLineImagePipelineStatus(overview.status);
  const agentStatusLabel = overview.loading ? "LINE 圖片處理中" : linePipeline.label;
  const agentStatusColor = overview.error ? "#B91C1C" : overview.loading ? "#D97706" : linePipeline.color;
  const currentUser = sessionUser || "admin_dadova";

  return (
    <div
      className="min-h-screen w-full font-sans antialiased"
      style={{
        backgroundColor: "#F5F1E8",
        color: "#1C1917",
        fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400;1,9..144,500&family=Geist:wght@300;400;500;600;700&family=Noto+Serif+TC:wght@400;500;700&display=swap');
        .font-display { font-family: 'Fraunces', 'Noto Serif TC', serif; font-optical-sizing: auto; }
        .font-serif-tc { font-family: 'Noto Serif TC', serif; }
        @keyframes fade-up { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes slide-in { from { opacity: 0; transform: translateX(-12px); } to { opacity: 1; transform: translateX(0); } }
        @keyframes pulse-soft { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes modal-in { from { opacity: 0; transform: scale(0.96); } to { opacity: 1; transform: scale(1); } }
        @keyframes backdrop-in { from { opacity: 0; } to { opacity: 1; } }
        .animate-fade-up { animation: fade-up 0.4s ease-out; }
        .animate-slide-in { animation: slide-in 0.3s ease-out; }
        .animate-pulse-soft { animation: pulse-soft 2s ease-in-out infinite; }
        .typing-cursor { animation: blink 1s step-start infinite; }
        .animate-modal-in { animation: modal-in 0.2s ease-out; }
        .animate-backdrop-in { animation: backdrop-in 0.2s ease-out; }
        .scrollbar-thin::-webkit-scrollbar { width: 6px; }
        .scrollbar-thin::-webkit-scrollbar-track { background: transparent; }
        .scrollbar-thin::-webkit-scrollbar-thumb { background: #D6CFB8; border-radius: 3px; }
        .scrollbar-thin::-webkit-scrollbar-thumb:hover { background: #B8AC85; }
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { scrollbar-width: none; -ms-overflow-style: none; }
        .grain-bg { background-image: radial-gradient(circle at 1px 1px, rgba(28,25,23,0.04) 1px, transparent 0); background-size: 24px 24px; }
      `}</style>

      <div className="flex flex-col h-screen overflow-hidden">
        {/* MAIN */}
        <main className="flex-1 flex flex-col overflow-hidden relative">
          <header
            className="flex items-center justify-between px-6 md:px-10 py-4 border-b"
            style={{ borderColor: "#E5DDC8" }}
          >
            {/* Brand + Date */}
            <div className="flex items-center gap-5 min-w-0">
              <div className="flex items-center gap-2.5 flex-shrink-0">
                <DadovaLogo size={32} />
                <div className="hidden sm:block">
                  <div
                    className="font-serif-tc font-medium text-base leading-none tracking-tight"
                    style={{ color: "#1C1917" }}
                  >
                    憭折????
                  </div>
                  <div className="text-[9px] tracking-[0.18em] uppercase text-stone-500 mt-1">
                    Dadova 繚 agent
                  </div>
                </div>
              </div>
            </div>

            {/* Right side: status + notifications + user */}
            <div className="flex items-center gap-3 md:gap-4 flex-shrink-0">
              <div className="hidden md:flex items-center gap-1.5 text-xs text-stone-500">
                <span
                  className="w-1.5 h-1.5 rounded-full animate-pulse-soft"
                  style={{ backgroundColor: agentStatusColor }}
                />
                {agentStatusLabel}
              </div>
              <div className="relative" ref={notifRef}>
                <button
                  onClick={() => {
                    setNotifOpen((v) => !v);
                    refreshOverview();
                    if (!notifOpen) setNotifRead(true);
                  }}
                  className="relative p-2 rounded-md hover:bg-[#EFE9D8] transition-colors"
                  aria-label="?"
                >
                  <Bell className="w-4 h-4" />
                  {hasUnreadNotifications && (
                    <span
                      className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full animate-pulse-soft"
                      style={{ backgroundColor: "#B91C1C" }}
                    />
                  )}
                </button>
                {notifOpen && (
                  <NotificationPanel
                    overview={overview}
                    latestCount={latestCount}
                    duplicateCount={duplicateCount}
                    totalIndexed={totalIndexed}
                    onRefresh={refreshOverview}
                    onSelectStatus={() => showOverviewMessage(overview.status, "status", "????")}
                    onSelectNew={() => showOverviewMessage(overview.latest, "latest", "???DM")}
                    onSelectDup={() => showOverviewMessage(overview.duplicates, "duplicates", "?? DM")}
                  />
                )}
              </div>
              <div className="h-6 w-px bg-stone-300 hidden md:block" />
              <button
                onClick={onLogout}
                className="flex items-center gap-2 hover:bg-[#EFE9D8] rounded-md px-2 py-1 transition-colors"
                aria-label={onLogout ? "??" : "???"}
                title={onLogout ? "?餃" : currentUser}
              >
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0"
                  style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
                >
                  AD
                </div>
                <div className="hidden md:block text-left">
                  <div className="text-xs font-medium leading-tight">{currentUser}</div>
                  <div className="text-[10px] text-stone-500 leading-tight">???</div>
                </div>
                {onLogout && <LogOut className="hidden md:block w-3.5 h-3.5 text-stone-500" />}
              </button>
            </div>
          </header>

          <div className="flex-1 min-h-0 flex flex-col lg:flex-row overflow-hidden">
            <aside
              className={`${sidebarCollapsed ? "w-full lg:w-16" : "w-full lg:w-64"} flex-shrink-0 border-b lg:border-b-0 lg:border-r transition-all duration-200`}
              style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}
            >
              <div className={`flex items-center gap-2 border-b px-3 py-2 ${sidebarCollapsed ? "justify-between lg:justify-center" : "justify-between"}`} style={{ borderColor: "#E5DDC8" }}>
                {!sidebarCollapsed && (
                  <div className="text-[10px] tracking-[0.16em] uppercase text-stone-500">Workspace</div>
                )}
                <button
                  type="button"
                  onClick={() => setSidebarCollapsed((value) => !value)}
                  className="rounded-md border bg-white p-1.5 text-stone-700 hover:bg-[#FAF7EE]"
                  style={{ borderColor: "#E5DDC8" }}
                  aria-label={sidebarCollapsed ? "撅? workspace" : "?嗅? workspace"}
                  title={sidebarCollapsed ? "撅? workspace" : "?嗅? workspace"}
                >
                  {sidebarCollapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
                </button>
              </div>
              <SidebarNavigation
                activeWorkspace={activeWorkspace}
                lineAutoEnabled={lineAutoEnabled}
                uploadCount={uploadFolders.length}
                collapsed={sidebarCollapsed}
                onSelect={setActiveWorkspace}
                onToggleLineAuto={() => handleToggleLineAuto().catch((error) => setUploadError(error.message))}
              />
            </aside>

            {activeWorkspace === "uploads" ? (
              <section className="flex-1 min-w-0 min-h-0 overflow-y-auto scrollbar-thin grain-bg">
                <div className="max-w-6xl mx-auto px-6 md:px-10 py-8">
                  <UploadWorkspace
                    folders={uploadFolders}
                    detail={uploadDetail}
                    uploading={uploading}
                    error={uploadError}
                    onUpload={async (payload) => {
                      try {
                        return await handleUploadImages(payload);
                      } catch (error) {
                        setUploadError(error.message);
                        throw error;
                      }
                    }}
                    onUploadExisting={async (payload) => {
                      try {
                        return await handleUploadImagesToFolder(payload);
                      } catch (error) {
                        setUploadError(error.message);
                        throw error;
                      }
                    }}
                    onSelectFolder={(folder) => refreshUploadDetail(folder.id).catch((error) => setUploadError(error.message))}
                    onRefresh={() => {
                      refreshUploadFolders().catch((error) => setUploadError(error.message));
                      if (uploadDetail?.folder?.id) refreshUploadDetail(uploadDetail.folder.id).catch((error) => setUploadError(error.message));
                    }}
                    onAddTag={(imageId, tag) => handleAddManualTag(imageId, tag).catch((error) => setUploadError(error.message))}
                    onDeleteTag={(tagId) => handleDeleteManualTag(tagId).catch((error) => setUploadError(error.message))}
                    onUpdateTag={(tagId, tag) => handleUpdateManualTag(tagId, tag).catch((error) => setUploadError(error.message))}
                    onUpdateImage={(imageId, data) => handleUpdateImageMetadata(imageId, data).catch((error) => setUploadError(error.message))}
                    onArchiveImage={(imageId) => handleArchiveImage(imageId).catch((error) => setUploadError(error.message))}
                    onToast={setToast}
                  />
                </div>
              </section>
            ) : (
            <section className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
          <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin grain-bg">
            <div className="max-w-3xl mx-auto px-6 md:px-10 py-10">
              {messages.map((msg) => (
                <MessageBlock
                  key={msg.id}
                  msg={msg}
                  copiedId={copiedId}
                  onCopy={handleCopy}
                  onAction={handleSend}
                  suggestions={suggestions}
                  onPreview={(dm, list) => setPreview({ dm, list })}
                  onCompareDup={setCompareDup}
                  onReviewDup={handleDuplicateReview}
                  onSelect={(list) => setSelectMode({ list })}
                />
              ))}
              {isThinking && (
                <div className="animate-fade-up flex items-center gap-2 mt-6 text-stone-500 text-sm">
                  <Sparkles className="w-3.5 h-3.5" />
                  <span>???</span>
                  <span className="typing-cursor">?</span>
                </div>
              )}
            </div>
          </div>

          {/* INPUT */}
          <div
            className="border-t px-6 md:px-10 py-5"
            style={{ borderColor: "#E5DDC8", backgroundColor: "#F5F1E8" }}
          >
            <div className="max-w-3xl mx-auto">
              <div
                className="flex items-center gap-3 px-4 py-3 rounded-lg border bg-white transition-all"
                style={{ borderColor: "#E5DDC8" }}
              >
                <textarea
                  ref={inputRef}
                  rows="1"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="?亥岷嚗鼠? ?? 5 憭?4 憭?????DM"
                  className="flex-1 resize-none outline-none text-sm bg-transparent placeholder:text-stone-400 max-h-32 leading-relaxed text-left"
                  style={{ color: "#1C1917" }}
                />
                <button
                  onClick={() => handleSend()}
                  disabled={!input.trim()}
                  className="flex-shrink-0 p-2 rounded-md transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: input.trim() ? "#1C1917" : "#E5DDC8",
                    color: input.trim() ? "#F5F1E8" : "#A8A29E",
                  }}
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="flex items-center justify-between mt-2.5 px-1">
                <div className="text-[10px] text-stone-500">
                  ????拐? Enter ? 繚 Shift+Enter ??
                </div>
                <div className="text-[10px] text-stone-500 flex items-center gap-1.5">
                  <span className="italic font-display">Powered by</span>
                  <span className="flex items-baseline gap-1">
                    <span className="font-bold tracking-tight" style={{ color: "#2D8BC0", letterSpacing: "-0.01em" }}>
                      STARBIT
                    </span>
                    <span className="font-serif-tc" style={{ color: "#57534E" }}>
                      ?????函??
                    </span>
                  </span>
                </div>
              </div>
            </div>
          </div>
            </section>
            )}
          </div>
        </main>
      </div>

      {/* MODALS */}
      {preview && (
        <DMPreviewModal
          initial={preview.dm}
          list={preview.list}
          onClose={() => setPreview(null)}
          onCopy={handleCopy}
          copiedId={copiedId}
        />
      )}
      {compareDup && (
        <DuplicateCompareModal
          data={compareDup}
          onClose={() => setCompareDup(null)}
          onReview={handleDuplicateReview}
        />
      )}
      {selectMode && (
        <SelectionModal
          list={selectMode.list}
          onClose={() => setSelectMode(null)}
          onCopy={handleCopy}
        />
      )}
      {toast && <UploadToast toast={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

function UploadToast({ toast, onClose }) {
  const success = toast?.type === "success";
  return (
    <div className="fixed bottom-5 right-5 z-[60] max-w-sm rounded-lg border bg-white shadow-xl animate-fade-up" style={{ borderColor: success ? "#16A34A" : "#B91C1C" }}>
      <div className="flex items-start gap-3 px-4 py-3">
        {success ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-green-600" /> : <AlertTriangle className="mt-0.5 h-4 w-4 text-red-700" />}
        <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">?????</div>
          <div className="mt-0.5 text-xs text-stone-600">{toast?.message}</div>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-stone-500 hover:bg-stone-100" aria-label="???內">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

function stepLabel(status) {
  if (status === "success") return "摰?";
  if (status === "running") return "?瑁?銝?";
  if (status === "failed") return "憭望?";
  if (status === "skipped") return "?仿?";
  return "敺???";
}

function sourceLabel(source) {
  if (source === "line-auto") return "LINE ?芸??砍?";
  if (source === "upload") return "??銝";
  return source || "?芸?憿?";
}

const UPLOAD_LIMITS = {
  formats: ["JPG", "JPEG", "PNG", "WEBP"],
  extensions: [".jpg", ".jpeg", ".png", ".webp"],
  maxFileBytes: 15 * 1024 * 1024,
  maxTotalBytes: 200 * 1024 * 1024,
  maxFiles: 50,
};

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(value >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

function uploadLimitText() {
  return `${UPLOAD_LIMITS.formats.join(" / ")}??? ${formatBytes(UPLOAD_LIMITS.maxFileBytes)}??? ${UPLOAD_LIMITS.maxFiles} ? / ${formatBytes(UPLOAD_LIMITS.maxTotalBytes)}`;
}

function validateUploadFiles(files) {
  const list = Array.from(files || []);
  if (list.length === 0) return "?????";
  if (list.length > UPLOAD_LIMITS.maxFiles) return `????? ${UPLOAD_LIMITS.maxFiles} ?`;
  const total = list.reduce((sum, file) => sum + Number(file.size || 0), 0);
  if (total > UPLOAD_LIMITS.maxTotalBytes) return `??????? ${formatBytes(UPLOAD_LIMITS.maxTotalBytes)}`;
  const invalid = list.find((file) => {
    const lower = String(file.name || "").toLowerCase();
    return !UPLOAD_LIMITS.extensions.some((ext) => lower.endsWith(ext));
  });
  if (invalid) return `${invalid.name} ?????`;
  const oversized = list.find((file) => Number(file.size || 0) > UPLOAD_LIMITS.maxFileBytes);
  if (oversized) return `${oversized.name} ?? ${formatBytes(UPLOAD_LIMITS.maxFileBytes)}`;
  return "";
}

function folderProgress(folder) {
  const total = Number(folder?.image_count || 0);
  const done = Math.max(
    Number(folder?.composed_count || 0),
    Number(folder?.ocr_count || 0),
    folder?.status === "success" ? total : 0,
  );
  return { done: Math.min(done, total), total };
}

function folderStatusLabel(folder) {
  if (folder?.status === "success") return "摰?";
  if (folder?.status === "failed") return "憭望?";
  if (folder?.status === "running") return "?瑁?銝?";
  return stepLabel(folder?.current_step ? folder?.step_statuses?.[folder.current_step] : "");
}

function SidebarNavigation({ activeWorkspace, lineAutoEnabled, uploadCount, collapsed, onSelect, onToggleLineAuto }) {
  const itemClass = (name) => (
    `w-full flex items-center ${collapsed ? "justify-center px-2" : "justify-between px-3"} gap-3 rounded-md border py-2.5 text-left text-sm transition-colors ${
      activeWorkspace === name ? "bg-[#1C1917] text-[#F5F1E8]" : "bg-white text-stone-800 hover:bg-[#FAF7EE]"
    }`
  );

  return (
    <div className={`${collapsed ? "workspace-collapsed p-2" : "p-3 lg:p-4"} space-y-4`}>
      <div>
        {!collapsed && <div className="text-[10px] tracking-[0.16em] uppercase text-stone-500 mb-2">Workspace</div>}
        <div className="grid grid-cols-2 lg:grid-cols-1 gap-2">
          <button
            type="button"
            onClick={() => onSelect("chat")}
            className={itemClass("chat")}
            style={{ borderColor: activeWorkspace === "chat" ? "#1C1917" : "#E5DDC8" }}
            title="?予??"
          >
            <span className="flex items-center gap-2 min-w-0">
              <Search className="w-4 h-4 flex-shrink-0" />
              <span className="truncate">?予?亥岷</span>
            </span>
            <ChevronRight className="w-3.5 h-3.5 flex-shrink-0" />
          </button>
          <button
            type="button"
            onClick={() => onSelect("uploads")}
            className={itemClass("uploads")}
            style={{ borderColor: activeWorkspace === "uploads" ? "#1C1917" : "#E5DDC8" }}
          >
            <span className="flex items-center gap-2 min-w-0">
              <Upload className="w-4 h-4 flex-shrink-0" />
            ?? / ???????
            </span>
            <span className="text-[10px] tabular-nums">{uploadCount}</span>
          </button>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-3" style={{ borderColor: "#E5DDC8" }}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-medium">LINE ?芸???</div>
            <div className="text-[10px] text-stone-500 mt-1 leading-relaxed">
              ?敺?瘝輻??鞈?憭暹?蝔?銝虫?蝢斤??????            </div>
          </div>
          <button
            type="button"
            onClick={onToggleLineAuto}
            className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] flex-shrink-0"
            style={{
              borderColor: lineAutoEnabled ? "#16A34A" : "#B91C1C",
              color: lineAutoEnabled ? "#166534" : "#991B1B",
            }}
          >
            <Power className="w-3 h-3" />
            {lineAutoEnabled ? "?" : "?"}
          </button>
        </div>
      </div>
    </div>
  );
}

function UploadWorkspace({
  folders,
  detail,
  uploading,
  error,
  onUpload,
  onUploadExisting,
  onSelectFolder,
  onRefresh,
  onAddTag,
  onDeleteTag,
  onUpdateTag,
  onUpdateImage,
  onArchiveImage,
  onToast,
}) {
  const [uploadStage, setUploadStage] = useState(null);
  const [uploadTarget, setUploadTarget] = useState(null);
  const [view, setView] = useState("list");
  const [recentFolderId, setRecentFolderId] = useState(null);
  const selectedId = detail?.folder?.id;

  const openFolder = async (folder) => {
    await onSelectFolder(folder);
    setView("detail");
  };

  const handleCreated = async (payload) => {
    const folderId = payload?.folder?.id;
    setRecentFolderId(folderId || null);
    setUploadStage(null);
    setUploadTarget(null);
    if (folderId) await onSelectFolder({ id: folderId });
    setView("detail");
    onToast?.({ type: "success", message: "????????? OCR / ???" });
  };

  const submitUploadFiles = async ({ files }) => {
    try {
      const payload = uploadTarget?.mode === "existing"
        ? await onUploadExisting({ folderId: uploadTarget.folderId, files })
        : await onUpload({ displayName: uploadTarget.displayName, note: uploadTarget.note, files });
      await handleCreated(payload);
      return payload;
    } catch (error) {
      onToast?.({ type: "error", message: error.message || "???????????" });
      throw error;
    }
  };

  useEffect(() => {
    if (view !== "detail" || !detail?.folder?.id) return undefined;
    const progress = folderProgress(detail.folder);
    const shouldPoll = detail.folder.status === "running"
      || detail.folder.status === "pending"
      || progress.done < progress.total;
    if (!shouldPoll) return undefined;
    const timer = window.setInterval(() => onRefresh(), 4000);
    return () => window.clearInterval(timer);
  }, [view, detail?.folder?.id, detail?.folder?.status, detail?.folder?.updated_at, onRefresh]);

  return (
    <section className="space-y-4">
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        <div className="px-5 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4" style={{ backgroundColor: "#FAF7EE" }}>
          <div>
            <div className="flex items-center gap-2 text-sm font-medium">
              <FolderPlus className="w-4 h-4 text-stone-600" />
              ????
            </div>
            <div className="text-xs text-stone-500 mt-1">
              支援 {uploadLimitText()}。可建立新資料夾或追加到既有資料夾，並自動執行 OCR / 組圖 / 索引。
          </div>
          <button
            type="button"
            onClick={() => setUploadStage("target")}
            className="rounded-md px-4 py-2 text-xs font-medium flex items-center justify-center gap-1.5 flex-shrink-0"
            style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
          >
            <Upload className="w-3.5 h-3.5" />
            ?? / ???????
          </button>
      </div>
      </div>

      </div>
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        {view === "detail" && detail?.folder ? (
          <UploadFolderDetail
            detail={detail}
            onBack={() => setView("list")}
            onAddTag={onAddTag}
            onDeleteTag={onDeleteTag}
            onUpdateTag={onUpdateTag}
            onUpdateImage={onUpdateImage}
            onArchiveImage={onArchiveImage}
          />
        ) : (
          <div>
            <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#F0E9D6", backgroundColor: "#FAF7EE" }}>
              <div>
                <div className="text-sm font-medium">?????</div>
                <div className="text-xs text-stone-500 mt-0.5">??????????????????????????</div>
              </div>
              <button type="button" onClick={onRefresh} className="text-xs text-stone-500 hover:text-stone-900">??渡?</button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead style={{ backgroundColor: "#FDFBF5", color: "#78716C" }}>
                  <tr>
                    <th className="px-4 py-2 font-medium">?????</th>
                    <th className="px-4 py-2 font-medium text-right">??</th>
                    <th className="px-4 py-2 font-medium">????</th>
                    <th className="px-4 py-2 font-medium">????</th>
                    <th className="px-4 py-2 font-medium text-right">??</th>
                  </tr>
                </thead>
                <tbody>
                  {(folders || []).map((folder) => {
                    const progress = folderProgress(folder);
                    const active = selectedId === folder.id || recentFolderId === folder.id;
                    return (
                      <tr
                        key={folder.id}
                        onClick={() => openFolder(folder)}
                        className="cursor-pointer hover:bg-[#FAF7EE] transition-colors"
                        style={{
                          borderTop: "1px solid #F0E9D6",
                          backgroundColor: active ? "#FFFBEB" : "#FFF",
                        }}
                      >
                        <td className="px-4 py-3 min-w-64">
                          <div className="flex items-center gap-2 font-medium text-stone-900">
                            <FolderOpen className="w-3.5 h-3.5 text-stone-500 flex-shrink-0" />
                            <span className="truncate">{folder.display_name}</span>
                          </div>
                          <div className="text-[10px] text-stone-500 mt-0.5 truncate">{sourceLabel(folder.source)} 繚 {folder.folder_slug}</div>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="rounded px-2 py-1 text-[10px]" style={{ backgroundColor: "#F0E9D6", color: "#1C1917" }}>
                            {folderStatusLabel(folder)}
                          </span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap tabular-nums">
                          {progress.done}/{progress.total}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-stone-500">
                          {new Date(folder.updated_at || folder.created_at).toLocaleString("zh-TW")}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button type="button" className="text-xs text-stone-700 hover:text-stone-950">
                            ?亦?
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {(!folders || folders.length === 0) && (
                    <tr>
                      <td colSpan={5} className="px-5 py-8 text-center text-stone-500">
                        撠銝鞈?憭?                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {uploadStage === "target" && (
        <UploadTargetModal
          folders={folders}
          onClose={() => setUploadStage(null)}
          onNext={(target) => {
            setUploadTarget(target);
            setUploadStage("files");
          }}
        />
      )}
      {uploadStage === "files" && uploadTarget && (
        <UploadFilesModal
          target={uploadTarget}
          uploading={uploading}
          error={error}
          onBack={() => setUploadStage("target")}
          onClose={() => setUploadStage(null)}
          onSubmit={submitUploadFiles}
        />
      )}
    </section>
  );
}

function UploadTargetModal({ folders, onClose, onNext }) {
  const [targetMode, setTargetMode] = useState("new");
  const [selectedFolderId, setSelectedFolderId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [note, setNote] = useState("");
  const [localError, setLocalError] = useState("");
  const selectedFolder = (folders || []).find((folder) => String(folder.id) === String(selectedFolderId));

  const next = () => {
    if (targetMode === "new" && !displayName.trim()) {
      setLocalError("????????");
      return;
    }
    if (targetMode === "existing" && !selectedFolderId) {
      setLocalError("????????");
      return;
    }
    setLocalError("");
    onNext(targetMode === "existing"
      ? { mode: "existing", folderId: selectedFolderId, folder: selectedFolder, label: selectedFolder?.display_name || "?????" }
      : { mode: "new", displayName: displayName.trim(), note: note.trim(), label: displayName.trim() });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6 animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.45)" }}>
      <div className="w-full max-w-xl rounded-lg border bg-white shadow-xl animate-modal-in overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div>
            <div className="text-sm font-medium">???????</div>
            <div className="text-xs text-stone-500 mt-0.5">????????????????????</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#EFE9D8]" aria-label="??">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-5 space-y-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => {
                setTargetMode("new");
                setLocalError("");
              }}
              className="rounded-md border px-3 py-3 text-sm font-medium text-left"
              style={{
                borderColor: targetMode === "new" ? "#1C1917" : "#E5DDC8",
                backgroundColor: targetMode === "new" ? "#1C1917" : "#FFF",
                color: targetMode === "new" ? "#F5F1E8" : "#1C1917",
              }}
            >
              ??????
            </button>
            <button
              type="button"
              onClick={() => {
                setTargetMode("existing");
                setLocalError("");
              }}
              className="rounded-md border px-3 py-3 text-sm font-medium text-left"
              style={{
                borderColor: targetMode === "existing" ? "#1C1917" : "#E5DDC8",
                backgroundColor: targetMode === "existing" ? "#1C1917" : "#FFF",
                color: targetMode === "existing" ? "#F5F1E8" : "#1C1917",
              }}
            >
              ???????
            </button>
          </div>

          {targetMode === "new" ? (
            <>
              <label className="block">
                <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">?????</span>
                <input
                  value={displayName}
                  onChange={(event) => {
                    setDisplayName(event.target.value);
                    setLocalError("");
                  }}
                  className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: "#E5DDC8" }}
                  placeholder="?????????"
                  autoFocus
                />
              </label>
              <label className="block">
                <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">??</span>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                  style={{ borderColor: "#E5DDC8" }}
                  rows={3}
                  placeholder="???5 ???????????????"
                />
              </label>
            </>
          ) : (
            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">?????</span>
              <select
                value={selectedFolderId}
                onChange={(event) => {
                  setSelectedFolderId(event.target.value);
                  setLocalError("");
                }}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none bg-white"
                style={{ borderColor: "#E5DDC8" }}
              >
                <option value="">??????</option>
                {(folders || []).map((folder) => (
                  <option key={folder.id} value={folder.id}>
                    {folder.display_name} ? {new Date(folder.updated_at || folder.created_at).toLocaleString("zh-TW")}
                  </option>
                ))}
              </select>
              {(!folders || folders.length === 0) && (
                <div className="mt-2 text-xs text-stone-500">??????????????????????</div>
              )}
            </label>
          )}

          {localError && <div className="text-xs text-red-700">{localError}</div>}
        </div>

        <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <button type="button" onClick={onClose} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#E5DDC8" }}>
            ??
          </button>
          <button type="button" onClick={next} className="rounded-md px-3 py-2 text-xs font-medium" style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}>
            ????????
          </button>
        </div>
      </div>
    </div>
  );
}

function UploadFilesModal({ target, uploading, error, onBack, onClose, onSubmit }) {
  const [files, setFiles] = useState(null);
  const [localError, setLocalError] = useState("");
  const fileList = Array.from(files || []);
  const totalBytes = fileList.reduce((sum, file) => sum + Number(file.size || 0), 0);
  const fileMessage = files ? validateUploadFiles(files) : "";
  const canSubmit = fileList.length > 0 && !fileMessage && !uploading;

  const submit = async () => {
    const message = validateUploadFiles(files);
    if (message) {
      setLocalError(message);
      return;
    }
    setLocalError("");
    try {
      await onSubmit({ files });
    } catch (submitError) {
      setLocalError(submitError.message || "????");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6 animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.45)" }}>
      <div className="w-full max-w-xl rounded-lg border bg-white shadow-xl animate-modal-in overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div>
            <div className="text-sm font-medium">????</div>
            <div className="text-xs text-stone-500 mt-0.5">????{target?.label || "??????"}</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#EFE9D8]" aria-label="??">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-5 space-y-4">
          <div className="rounded-md border p-3 text-xs text-stone-600" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
            ???????? OCR / ?? / ?????????????????
          </div>
          <label className="block">
            <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">????</span>
            <input
              type="file"
              accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
              multiple
              onChange={(event) => {
                setFiles(event.target.files);
                setLocalError(validateUploadFiles(event.target.files));
              }}
              className="mt-1 block w-full text-xs"
            />
          </label>
          <div className="rounded-md border p-3 text-xs text-stone-600" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
            ??? {fileList.length} ????? {formatBytes(totalBytes)}
          </div>
          {fileList.length > 0 && (
            <div className="max-h-44 overflow-y-auto scrollbar-thin rounded-md border" style={{ borderColor: "#F0E9D6" }}>
              {fileList.map((file) => (
                <div key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-3 px-3 py-2 text-xs" style={{ borderTop: "1px solid #F0E9D6" }}>
                  <span className="truncate">{file.name}</span>
                  <span className="text-stone-500 flex-shrink-0">{formatBytes(file.size)}</span>
                </div>
              ))}
            </div>
          )}

          {(localError || fileMessage || error) && (
            <div className="text-xs text-red-700">{localError || fileMessage || error}</div>
          )}
        </div>

        <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <button type="button" onClick={onBack} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#E5DDC8" }}>
            ???
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="rounded-md px-3 py-2 text-xs font-medium flex items-center gap-1.5 disabled:opacity-50"
            style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
          >
            {uploading && <Loader2 className="w-3 h-3 animate-spin" />}
            ???????
          </button>
        </div>
      </div>
    </div>
  );
}

function imageFlowStatus(image) {
  if (image?.compose_status === "success" || image.branded_thumbnail_url || image.branded_url) {
    return { label: "??", detail: "OCR / ????" };
  }
  if (image?.compose_status === "running") return { label: "???", detail: "OCR ???????" };
  if (image?.compose_status === "failed") return { label: "????", detail: "???????" };
  if (image?.ocr_status === "success" || (image.system_tags || []).length > 0 || (image.ocr_tags_override || []).length > 0) {
    return { label: "????", detail: "OCR ??" };
  }
  if (image?.ocr_status === "running") return { label: "OCR ?", detail: "????????" };
  if (image?.ocr_status === "failed") return { label: "OCR ??", detail: "???????" };
  return { label: "?? OCR", detail: "????" };
}

function summarizeTags(tags, limit = 3) {
  const values = Array.isArray(tags) ? tags.map((tag) => tag?.tag || tag).filter(Boolean) : [];
  if (!values.length) return "撠";
  const visible = values.slice(0, limit).join("??");
  return values.length > limit ? `${visible} +${values.length - limit}` : visible;
}

function UploadFolderDetail({ detail, onBack, onAddTag, onDeleteTag, onUpdateTag, onUpdateImage, onArchiveImage }) {
  const [selectedImage, setSelectedImage] = useState(null);
  const folder = detail.folder;
  const images = Array.isArray(detail.images) ? detail.images : [];
  const steps = folder.step_statuses || {};
  const currentSelectedImage = images.find((image) => image.id === selectedImage?.id) || selectedImage;

  return (
    <div className="p-4">
      <button
        type="button"
        onClick={onBack}
        className="mb-3 flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-900"
      >
        <ChevronLeft className="w-3.5 h-3.5" />
        餈?鞈?憭曉?銵?      </button>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
                <div className="text-sm font-medium">?????</div>
          <div className="text-[10px] text-stone-500 mt-0.5">{folder.folder_slug}</div>
          {folder.note && <div className="text-xs text-stone-600 mt-1">{folder.note}</div>}
          {Array.isArray(folder.line_groups) && folder.line_groups.length > 0 && (
            <div className="text-[10px] text-stone-500 mt-1">???{folder.line_groups.join("?")}</div>
          )}
        </div>
        <div className="grid grid-cols-4 gap-1.5 text-xs">
          <StatusMetric label="??" value={stepLabel(steps.upload)} accent={steps.upload === "failed"} />
          <StatusMetric label="OCR" value={stepLabel(steps.ocr)} accent={steps.ocr === "failed"} />
          <StatusMetric label="蝯?" value={stepLabel(steps.compose)} accent={steps.compose === "failed"} />
          <StatusMetric label="蝝Ｗ?" value={stepLabel(steps.index)} accent={steps.index === "failed"} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <StatusMetric label="??" value={folder.image_count || images.length || 0} />
        <StatusMetric label="OCR" value={`${folder.ocr_count || 0}/${folder.image_count || images.length || 0}`} />
        <StatusMetric label="蝯?" value={`${folder.composed_count || 0}/${folder.image_count || images.length || 0}`} />
      </div>

      <div className="overflow-x-auto rounded-md border" style={{ borderColor: "#E5DDC8" }}>
        <table className="w-full text-left text-xs">
          <thead style={{ backgroundColor: "#FDFBF5", color: "#78716C" }}>
            <tr>
              <th className="px-3 py-2 font-medium text-right">??</th>
              <th className="px-3 py-2 font-medium text-right">??</th>
              <th className="px-3 py-2 font-medium">????</th>
              <th className="px-3 py-2 font-medium">????</th>
              <th className="px-3 py-2 font-medium">OCR Tags</th>
              <th className="px-3 py-2 font-medium">?? Tags</th>
              <th className="px-3 py-2 font-medium">Note</th>
              <th className="px-3 py-2 font-medium text-right">??</th>
            </tr>
          </thead>
          <tbody>
        {images.map((image) => {
          const flow = imageFlowStatus(image);
          const ocrTags = image.ocr_tags_override?.length ? image.ocr_tags_override : image.system_tags;
          return (
            <tr
              key={image.id}
              className="hover:bg-[#FAF7EE] cursor-pointer"
              onClick={() => setSelectedImage(image)}
              style={{ borderTop: "1px solid #F0E9D6" }}
            >
              <td className="px-3 py-2">
                <div className="w-14 bg-stone-100 rounded overflow-hidden" style={{ aspectRatio: "827 / 1169" }}>
                  {image.thumbnail_url ? (
                    <img src={image.thumbnail_url} alt={image.original_filename} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-[10px] text-stone-500">??</div>
                  )}
                </div>
              </td>
              <td className="px-3 py-2 min-w-48">
                <div className="font-medium text-stone-900 truncate">{image.display_name || image.original_filename}</div>
                {image.display_name && <div className="text-[10px] text-stone-500 truncate">{image.original_filename}</div>}
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-stone-500">
                {new Date(image.uploaded_at).toLocaleString("zh-TW")}
              </td>
              <td className="px-3 py-2 min-w-32">
                <div className="font-medium">{flow.label}</div>
                <div className="text-[10px] text-stone-500">{flow.detail}</div>
              </td>
              <td className="px-3 py-2 min-w-40 text-stone-700">{summarizeTags(ocrTags)}</td>
              <td className="px-3 py-2 min-w-40 text-stone-700">{summarizeTags(image.manual_tags)}</td>
              <td className="px-3 py-2 min-w-48 text-stone-600 truncate max-w-64">{image.manual_note || "?"}</td>
              <td className="px-3 py-2 text-right whitespace-nowrap">
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelectedImage(image);
                  }}
                  className="text-xs text-stone-700 hover:text-stone-950"
                >
                  ?亦? / 蝺刻摩
                </button>
              </td>
            </tr>
          );
        })}
          {images.length === 0 && (
            <tr>
              <td colSpan={8} className="px-5 py-8 text-center text-stone-500">????????</td>
            </tr>
          )}
          </tbody>
        </table>
      </div>
      {currentSelectedImage && (
        <CleanImageDetailDrawer
          image={currentSelectedImage}
          onClose={() => setSelectedImage(null)}
          onAddTag={onAddTag}
          onDeleteTag={onDeleteTag}
          onUpdateTag={onUpdateTag}
          onUpdateImage={onUpdateImage}
          onArchiveImage={onArchiveImage}
        />
      )}
    </div>
  );
}

/*
function ImageDetailDrawer({ image, onClose, onAddTag, onDeleteTag, onUpdateTag, onUpdateImage, onArchiveImage }) {
  const [displayName, setDisplayName] = useState(image.display_name || "");
  const [ocrOverride, setOcrOverride] = useState((image.ocr_tags_override || []).join("??)");
  const [referenceText, setReferenceText] = useState(image.reference_text || "");
  const [manualNote, setManualNote] = useState(image.manual_note || "");
  const [tagDraft, setTagDraft] = useState("");
  const [tagEdits, setTagEdits] = useState({});
  const rawTags = image.system_tags || [];
  const flow = imageFlowStatus(image);

  useEffect(() => {
    setDisplayName(image.display_name || "");
    setOcrOverride((image.ocr_tags_override || []).join("??)");
    setReferenceText(image.reference_text || "");
    setManualNote(image.manual_note || "");
    setTagDraft("");
    setTagEdits({});
  }, [image.id]);

  const parsedOverrideTags = () => ocrOverride
    .split(/[,\n?+/)
    .map((tag) => tag.trim())
    .filter(Boolean);

  const saveMetadata = async () => {
    await onUpdateImage(image.id, {
      display_name: displayName,
      ocr_tags_override: parsedOverrideTags(),
      reference_text: referenceText,
      manual_note: manualNote,
    });
  };

  const archive = async () => {
    if (!window.confirm("蝣箏?閬?摮撐??嚗?摮????”?梯???)) return";
    await onArchiveImage(image.id);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.35)" }}>
      <div className="w-full max-w-3xl h-full bg-white shadow-xl overflow-y-auto animate-slide-in">
        <div className="sticky top-0 z-10 px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{image.display_name || image.original_filename}</div>
                <div className="text-xs text-stone-500 mt-0.5">??????????????????????????</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#EFE9D8]" aria-label="??">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 grid lg:grid-cols-[320px_1fr] gap-5">
          <div>
            <div>
              <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-1">蝯?蝯?</div>
              {image.branded_thumbnail_url ? (
                <a href={image.branded_url || image.branded_thumbnail_url} target="_blank" rel="noreferrer" className="block rounded-md border overflow-hidden bg-stone-100" style={{ borderColor: "#E5DDC8", aspectRatio: "827 / 1169" }}>
                  <img src={image.branded_thumbnail_url} alt={`${image.original_filename} composed`} className="w-full h-full object-cover" />
                </a>
              ) : (
                <div className="rounded-md border px-3 py-8 text-center text-xs text-stone-500" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
                  蝯?撠摰?
                </div>
              )}
            </div>
          </div>

          <div className="space-y-4">
            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">憿舐內?迂</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
                style={{ borderColor: "#E5DDC8" }}
                placeholder={image.original_filename}
              />
            </label>

            <div className="rounded-md border p-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
              <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-2">OCR ?? Tags</div>
              <div className="flex flex-wrap gap-1">
                {rawTags.map((tag, idx) => (
                  <span key={`${tag.field}-${tag.tag}-${idx}`} className="rounded px-1.5 py-0.5 text-[10px]" style={{ backgroundColor: "#EEF2FF", color: "#3730A3" }}>
                    {tag.tag}
                  </span>
                ))}
                {rawTags.length === 0 && <span className="text-xs text-stone-500">撠</span>}
              </div>
            </div>

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">OCR Tag 鈭箏極靽格迤</span>
              <textarea
                value={ocrOverride}
                onChange={(event) => setOcrOverride(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                style={{ borderColor: "#E5DDC8" }}
                rows={2}
                placeholder="?????"
              />
            </label>

            <div>
              <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-2">?酉 Tags</div>
              <div className="space-y-2">
                {(image.manual_tags || []).map((tag) => (
                  <div key={tag.id} className="flex gap-2">
                    <input
                      value={tagEdits[tag.id] ?? tag.tag}
                      onChange={(event) => setTagEdits((current) => ({ ...current, [tag.id]: event.target.value }))}
                      onBlur={() => onUpdateTag(tag.id, tagEdits[tag.id] ?? tag.tag)}
                      className="min-w-0 flex-1 rounded border px-2 py-1 text-xs outline-none"
                      style={{ borderColor: "#E5DDC8" }}
                    />
                    <button type="button" onClick={() => onDeleteTag(tag.id)} className="rounded border px-2 py-1 text-xs" style={{ borderColor: "#E5DDC8" }}>
                      ?芷
                    </button>
                  </div>
                ))}
                <div className="flex gap-2">
                  <input
                    value={tagDraft}
                    onChange={(event) => setTagDraft(event.target.value)}
                    className="min-w-0 flex-1 rounded border px-2 py-1 text-xs outline-none"
                    style={{ borderColor: "#E5DDC8" }}
                    placeholder="?啣??酉 tag嚗?憒?靽"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      onAddTag(image.id, tagDraft);
                      setTagDraft("");
                    }}
                    className="rounded px-2 py-1 text-xs"
                    style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
                  >
                    ?啣?
                  </button>
                </div>
              </div>
            </div>

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">Reference ??</span>
              <textarea
                value={referenceText}
                onChange={(event) => setReferenceText(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                style={{ borderColor: "#E5DDC8" }}
                rows={4}
                placeholder="?????舀??‵?交??芯???RPA ?? LINE ??"
              />
            </label>

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">鈭箏極?酉 Note</span>
              <textarea
                value={manualNote}
                onChange={(event) => setManualNote(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                style={{ borderColor: "#E5DDC8" }}
                rows={4}
                placeholder="靘?嚗眺銝???望銝餅??澆?蝣箄?"
              />
            </label>

            <div className="flex items-center justify-between gap-3 pt-2">
              <button type="button" onClick={archive} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#B91C1C", color: "#991B1B" }}>
                撠???
              </button>
              <button type="button" onClick={saveMetadata} className="rounded-md px-4 py-2 text-xs font-medium" style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}>
                ?脣?
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

*/

function CleanImageDetailDrawer({ image, onClose, onAddTag, onDeleteTag, onUpdateTag, onUpdateImage, onArchiveImage }) {
  const [displayName, setDisplayName] = useState(image.display_name || "");
  const [ocrOverride, setOcrOverride] = useState((image.ocr_tags_override || []).join("、"));
  const [referenceText, setReferenceText] = useState(image.reference_text || "");
  const [manualNote, setManualNote] = useState(image.manual_note || "");
  const [tagDraft, setTagDraft] = useState("");
  const [tagEdits, setTagEdits] = useState({});
  const rawTags = image.system_tags || [];
  const flow = imageFlowStatus(image);

  useEffect(() => {
    setDisplayName(image.display_name || "");
    setOcrOverride((image.ocr_tags_override || []).join("、"));
    setReferenceText(image.reference_text || "");
    setManualNote(image.manual_note || "");
    setTagDraft("");
    setTagEdits({});
  }, [image.id]);

  const parsedOverrideTags = () => ocrOverride
    .split(/[,，、\n]/)
    .map((tag) => tag.trim())
    .filter(Boolean);

  const saveMetadata = async () => {
    await onUpdateImage(image.id, {
      display_name: displayName,
      ocr_tags_override: parsedOverrideTags(),
      reference_text: referenceText,
      manual_note: manualNote,
    });
  };

  const archive = async () => {
    if (!window.confirm("確定要刪除這張圖片嗎？此操作無法復原。")) return;
    await onArchiveImage(image.id);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.35)" }}>
      <div className="w-full max-w-3xl h-full bg-white shadow-xl overflow-y-auto animate-slide-in">
        <div className="sticky top-0 z-10 px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{image.display_name || image.original_filename}</div>
            <div className="text-xs text-stone-500 mt-0.5">{flow.label} · {flow.detail}</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#EFE9D8]" aria-label="關閉">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 grid lg:grid-cols-[320px_1fr] gap-5">
          <div>
            <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-1">組圖結果</div>
            {image.branded_thumbnail_url ? (
              <a href={image.branded_url || image.branded_thumbnail_url} target="_blank" rel="noreferrer" className="block rounded-md border overflow-hidden bg-stone-100" style={{ borderColor: "#E5DDC8", aspectRatio: "827 / 1169" }}>
                <img src={image.branded_thumbnail_url} alt={`${image.original_filename} composed`} className="w-full h-full object-cover" />
              </a>
            ) : (
              <div className="rounded-md border px-3 py-8 text-center text-xs text-stone-500" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
                組圖尚未完成
              </div>
            )}
          </div>

          <div className="space-y-4">
            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">圖片名稱</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
                style={{ borderColor: "#E5DDC8" }}
                placeholder={image.original_filename}
              />
            </label>

            <div className="rounded-md border p-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
              <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-2">OCR 系統 Tags</div>
              <div className="flex flex-wrap gap-1">
                {rawTags.map((tag, idx) => (
                  <span key={`${tag.field}-${tag.tag}-${idx}`} className="rounded px-1.5 py-0.5 text-[10px]" style={{ backgroundColor: "#EEF2FF", color: "#3730A3" }}>
                    {tag.tag}
                  </span>
                ))}
                {rawTags.length === 0 && <span className="text-xs text-stone-500">尚無 OCR tag</span>}
              </div>
            </div>

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">OCR Tag 人工修正</span>
              <textarea
                value={ocrOverride}
                onChange={(event) => setOcrOverride(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                style={{ borderColor: "#E5DDC8" }}
                rows={2}
                placeholder="可用逗號、頓號或換行分隔"
              />
            </label>

            <div>
              <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-2">人工備註 Tags</div>
              <div className="space-y-2">
                {(image.manual_tags || []).map((tag) => (
                  <div key={tag.id} className="flex gap-2">
                    <input
                      value={tagEdits[tag.id] ?? tag.tag}
                      onChange={(event) => setTagEdits((current) => ({ ...current, [tag.id]: event.target.value }))}
                      onBlur={() => onUpdateTag(tag.id, tagEdits[tag.id] ?? tag.tag)}
                      className="min-w-0 flex-1 rounded border px-2 py-1 text-xs outline-none"
                      style={{ borderColor: "#E5DDC8" }}
                    />
                    <button type="button" onClick={() => onDeleteTag(tag.id)} className="rounded border px-2 py-1 text-xs" style={{ borderColor: "#E5DDC8" }}>
                      刪除
                    </button>
                  </div>
                ))}
                <div className="flex gap-2">
                  <input
                    value={tagDraft}
                    onChange={(event) => setTagDraft(event.target.value)}
                    className="min-w-0 flex-1 rounded border px-2 py-1 text-xs outline-none"
                    style={{ borderColor: "#E5DDC8" }}
                    placeholder="新增人工 tag，例如促銷、買一送一"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      onAddTag(image.id, tagDraft);
                      setTagDraft("");
                    }}
                    className="rounded px-2 py-1 text-xs"
                    style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
                  >
                    新增
                  </button>
                </div>
              </div>
            </div>

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">Reference 文案</span>
              <textarea
                value={referenceText}
                onChange={(event) => setReferenceText(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                style={{ borderColor: "#E5DDC8" }}
                rows={4}
                placeholder="保留給手動輸入或後續 RPA 補入 LINE 文案"
              />
            </label>

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">人工備註 Note</span>
              <textarea
                value={manualNote}
                onChange={(event) => setManualNote(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                style={{ borderColor: "#E5DDC8" }}
                rows={4}
                placeholder="例如促銷、買一送一、活動檔期等"
              />
            </label>

            <div className="flex items-center justify-between gap-3 pt-2">
              <button type="button" onClick={archive} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#B91C1C", color: "#991B1B" }}>
                刪除圖片
              </button>
              <button type="button" onClick={saveMetadata} className="rounded-md px-4 py-2 text-xs font-medium" style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}>
                儲存
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ===================================================================== */
/* NOTIFICATION PANEL                                                     */
/* ===================================================================== */
function NotificationPanel({
  overview,
  latestCount,
  duplicateCount,
  totalIndexed,
  onRefresh,
  onSelectStatus,
  onSelectNew,
  onSelectDup,
}) {
  const latestItems = Array.isArray(overview?.latest?.items) ? overview.latest.items : [];
  const latestTime = latestItems[0]?.source_time || latestItems[0]?.indexed_at;
  const latestLabel = latestTime
    ? new Date(latestTime).toLocaleString("zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "尚無更新";
  const sourceEvents = (Array.isArray(overview?.status?.items) ? overview.status.items : [])
    .map((item) => ({
      name: item.target_id || "Agent",
      time: item.latest_indexed_at || item.latest_file_time,
      indexed: Number(item.indexed_count || 0),
    }))
    .filter((item) => item.time)
    .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
    .slice(0, 3);
  const hasAny = latestCount > 0 || duplicateCount > 0 || totalIndexed > 0 || overview?.loading || overview?.error;

  return (
    <div
      className="absolute right-0 top-full mt-2 w-80 rounded-lg border bg-white shadow-xl overflow-hidden z-40 animate-fade-up"
      style={{ borderColor: "#E5DDC8" }}
    >
      <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
        <div className="text-sm font-medium" style={{ color: "#1C1917" }}>Agent 通知</div>
        <button onClick={onRefresh} className="text-[10px] text-stone-500 hover:text-stone-900 transition-colors">
          重新整理
        </button>
      </div>

      {!hasAny ? (
        <div className="px-4 py-7 flex flex-col items-center text-center">
          <div className="w-10 h-10 rounded-md flex items-center justify-center mb-3" style={{ backgroundColor: "#F0E9D6" }}>
            <Clock className="w-4 h-4 text-stone-500" />
          </div>
          <div className="text-xs font-medium mb-1">尚無 Agent 通知</div>
          <div className="text-[10px] text-stone-500 leading-relaxed">有新圖片、重複圖片或流程異常時會顯示在這裡。</div>
        </div>
      ) : (
        <div className="max-h-80 overflow-y-auto scrollbar-thin">
          {overview?.loading && (
            <div className="w-full px-4 py-3 flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#F0E9D6" }}>
                <Loader2 className="w-3 h-3 animate-spin text-stone-500" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">正在同步 Agent</div>
                <p className="text-[11px] text-stone-600 leading-relaxed">正在讀取圖片與流程狀態。</p>
              </div>
            </div>
          )}

          {overview?.error && (
            <button onClick={onSelectStatus} className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#FEF3C7" }}>
                <AlertTriangle className="w-3 h-3" style={{ color: "#92400E" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">Agent 狀態異常</div>
                <p className="text-[11px] text-stone-600 leading-relaxed truncate">{overview.error}</p>
              </div>
            </button>
          )}

          {sourceEvents.length > 0 && (
            <div className="px-4 py-3" style={{ borderTop: "1px solid #F0E9D6", backgroundColor: "#FDFBF5" }}>
              <div className="text-xs font-medium mb-1">最近來源更新</div>
              <div className="space-y-1.5">
                {sourceEvents.map((item) => (
                  <div key={`${item.name}-${item.time}`} className="flex items-center justify-between gap-3 text-[11px] text-stone-600">
                    <span className="truncate">{item.name}</span>
                    <span className="shrink-0 tabular-nums">{item.indexed} 張</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {latestCount > 0 && (
            <button onClick={onSelectNew} className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#E0F2FE" }}>
                <Inbox className="w-3 h-3" style={{ color: "#075985" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-xs font-medium">最新圖片</span>
                  <span className="text-[10px] text-stone-500 tabular-nums">{latestLabel}</span>
                </div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  目前有 <span className="font-display italic text-base text-stone-900">{latestCount}</span> 張可查看。
                </p>
              </div>
            </button>
          )}

          {duplicateCount > 0 && (
            <button onClick={onSelectDup} className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#FEE2E2" }}>
                <Layers className="w-3 h-3" style={{ color: "#B91C1C" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-xs font-medium">重複圖片</span>
                  <span className="text-[10px] text-stone-500 tabular-nums">待處理</span>
                </div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  發現 <span className="font-display italic text-base" style={{ color: "#B91C1C" }}>{duplicateCount}</span> 組可能重複的圖片。
                </p>
              </div>
            </button>
          )}

          {totalIndexed > 0 && (
            <button onClick={onSelectStatus} className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#ECFDF5" }}>
                <CheckCircle2 className="w-3 h-3" style={{ color: "#047857" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">索引完成</div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  已索引 <span className="font-display italic text-base text-stone-900">{totalIndexed}</span> 張圖片。
                </p>
              </div>
            </button>
          )}
        </div>
      )}

      <div className="px-4 py-2 border-t flex items-center justify-between text-[10px] text-stone-500" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
        <span>通知中心</span>
        <span>{new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })}</span>
      </div>
    </div>
  );
}

function AgentStatusMessage({ status }) {
  const sources = Array.isArray(status?.items) ? status.items : [];
  const pipeline = getLineImagePipelineStatus(status);
  const totalIndexed = Number(status?.total_indexed || 0);
  const errorSources = sources.filter((item) => Number(item.error_count || 0) > 0);
  const totalTravel = sources.reduce((sum, item) => sum + Number(item.travel_count || 0), 0);
  const totalBranded = sources.reduce((sum, item) => sum + Number(item.branded_count || 0), 0);
  const manualJob = status?.latest_job || status?.manual_job;
  const manualJobStatus = manualJobLabel(manualJob);
  const jobSteps = manualJob?.steps || {};
  const pct = Math.round((pipeline.completedStages / pipeline.totalStages) * 100);
  const latestAt = sources
    .map((item) => item.latest_indexed_at || item.latest_file_time)
    .filter(Boolean)
    .sort()
    .at(-1);

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        {pipeline.isComplete ? (
          <CheckCircle2 className="w-4 h-4" style={{ color: "#16A34A" }} />
        ) : (
          <Loader2 className="w-4 h-4 animate-spin" style={{ color: "#D97706" }} />
        )}
        <span className="text-sm font-medium">{pipeline.label}</span>
      </div>
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        <div className="px-5 py-3 flex items-center justify-between border-b" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div className="flex items-center gap-2">
            <Database className="w-3.5 h-3.5 text-stone-500" />
            <span className="text-xs font-medium">LINE 圖片流程</span>
          </div>
          <span className="text-[10px] text-stone-500 tabular-nums">
            {pipeline.completedStages} / {pipeline.totalStages} 階段
          </span>
        </div>
        <div className="px-5 py-4">
          <div className="flex items-baseline justify-between mb-2">
            <div className="flex items-baseline gap-2">
              <span className="font-display italic text-3xl tabular-nums">{String(totalIndexed).padStart(2, "0")}</span>
              <span className="text-stone-400 text-sm">已 OCR / 組圖 DM</span>
            </div>
            <span className="text-xs text-stone-500 tabular-nums">{pct}%</span>
          </div>
          <div className="h-1 rounded-full overflow-hidden" style={{ backgroundColor: "#F0E9D6" }}>
            <div className="h-full transition-all duration-700 ease-out" style={{ width: `${Math.min(100, pct)}%`, backgroundColor: "#1C1917" }} />
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <StatusMetric label="抓取" value={pipeline.lineFetchedDone ? "完成" : "等待中"} accent={!pipeline.lineFetchedDone} />
            <StatusMetric label="OCR" value={pipeline.ocrDone ? "完成" : "等待中"} accent={!pipeline.ocrDone} />
            <StatusMetric label="組圖" value={pipeline.composedDone ? "完成" : "等待中"} accent={!pipeline.composedDone} />
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
            <StatusMetric label="LINE 圖片" value={totalTravel} />
            <StatusMetric label="組圖結果" value={totalBranded} />
            <StatusMetric label="異常" value={errorSources.length} accent={errorSources.length > 0} />
          </div>
          {manualJob && (
            <div className="mt-3 rounded-md border px-3 py-2.5" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
              <div className="flex items-center justify-between gap-3 mb-2">
                <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">
                  手動流程 · {jobSourceLabel(manualJob.trigger_source)}
                </span>
                <span className="text-xs font-medium" style={{ color: manualJob.running ? "#D97706" : manualJob.last_success === false || manualJob.status === "stale" ? "#B91C1C" : "#16A34A" }}>
                  {manualJobStatus}
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] text-stone-600 mb-2">
                <div>開始：{formatDateTime(manualJob.started_at || manualJob.last_started_at)}</div>
                <div>結束：{formatDateTime(manualJob.finished_at || manualJob.last_finished_at)}</div>
                <div>PID：{manualJob.pid || "無"}</div>
                <div>代碼：{manualJob.returncode ?? "尚無"}</div>
              </div>
              <div className="grid grid-cols-4 gap-1.5 text-xs">
                <StatusMetric label="RPA" value={jobStepLabel(jobSteps.rpa?.status)} accent={jobStepAccent(jobSteps.rpa?.status)} />
                <StatusMetric label="OCR" value={jobStepLabel(jobSteps.ocr?.status)} accent={jobStepAccent(jobSteps.ocr?.status)} />
                <StatusMetric label="組圖" value={jobStepLabel(jobSteps.compose?.status)} accent={jobStepAccent(jobSteps.compose?.status)} />
                <StatusMetric label="索引" value={jobStepLabel(jobSteps.index?.status)} accent={jobStepAccent(jobSteps.index?.status)} />
              </div>
              {manualJob.last_error && <div className="mt-2 text-[10px]" style={{ color: "#B91C1C" }}>{manualJob.last_error}</div>}
            </div>
          )}
          {latestAt && (
            <div className="mt-3 flex items-center gap-2">
              <span className="text-[10px] tracking-[0.2em] uppercase text-stone-500">最近更新</span>
              <span className="text-xs font-medium">{new Date(latestAt).toLocaleString("zh-TW")}</span>
            </div>
          )}
        </div>
        <div className="px-5 py-3 grid grid-cols-4 gap-1.5 border-t" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          {(sources.length ? sources : [{ target_id: "Agent", indexed_count: 0 }]).slice(0, 20).map((source, i) => {
            const hasData = Number(source.indexed_count || 0) > 0;
            const hasError = Number(source.error_count || 0) > 0;
            return (
              <div
                key={`${source.target_id || source.group_name || "source"}-${i}`}
                title={`${source.target_id || source.group_name || "Agent"}: ${source.indexed_count || 0}`}
                className="h-1 rounded-full"
                style={{ backgroundColor: hasError ? "#B91C1C" : hasData ? "#1C1917" : "#E5DDC8" }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
function StatusMetric({ label, value, accent }) {
  return (
    <div className="rounded-md px-2 py-1.5" style={{ backgroundColor: "#FAF7EE" }}>
      <div className="text-[9px] tracking-[0.15em] uppercase text-stone-400">{label}</div>
      <div className="text-sm font-medium tabular-nums" style={{ color: accent ? "#B91C1C" : "#1C1917" }}>
        {value}
      </div>
    </div>
  );
}

/* ===================================================================== */
/* RESULTS ??compact horizontal cards in a single column                  */
/* ===================================================================== */
function ResultsMessage({ query, criteria, fallback, dms, copiedId, onCopy, onPreview, onSelect }) {
  const [copiedAll, setCopiedAll] = useState(false);
  const [copiedSelected, setCopiedSelected] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const isCompact = dms.length > 6;

  const handleCopyAll = async () => {
    const ok = await onCopy(dms);
    if (!ok) return;
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2200);
  };

  const toggleSelect = (id) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectedDms = () => dms.filter((dm) => selected.has(dm.id));

  const handleCopySelected = async () => {
    const items = selectedDms();
    if (items.length === 0) return;
    const ok = await onCopy(items);
    if (!ok) return;
    setCopiedSelected(true);
    setTimeout(() => {
      setCopiedSelected(false);
      setSelected(new Set());
    }, 1800);
  };

  const clearSelection = () => setSelected(new Set());

  const chips = [];
  if (criteria?.region) chips.push({ label: "地區", value: criteria.region, key: "region" });
  if (criteria?.month) chips.push({ label: "月份", value: `${criteria.month} 月`, key: "month" });
  if (criteria?.months?.length) chips.push({ label: "月份", value: `${criteria.months.join(", ")} 月`, key: "months" });
  if (criteria?.season) chips.push({ label: "季節", value: criteria.season, key: "season" });
  if (criteria?.days) chips.push({ label: "天數", value: criteria.nights ? `${criteria.days} 天 ${criteria.nights} 夜` : `${criteria.days} 天`, key: "days" });
  if (criteria?.minPrice || criteria?.maxPrice) {
    const minPrice = criteria.minPrice ? `NT$ ${criteria.minPrice.toLocaleString()}` : null;
    const maxPrice = criteria.maxPrice ? `NT$ ${criteria.maxPrice.toLocaleString()}` : null;
    chips.push({ label: "預算", value: minPrice && maxPrice ? `${minPrice} - ${maxPrice}` : maxPrice || minPrice, key: "price" });
  }
  if (criteria?.feature) chips.push({ label: "特色", value: criteria.feature, key: "feature" });
  if (criteria?.tag) chips.push({ label: "標籤", value: criteria.tag, key: "tag" });
  if (criteria?.type) chips.push({ label: "類型", value: criteria.type, key: "type" });

  const Summary = ({ compact = false }) => (
    <>
      <p className="text-sm leading-relaxed text-stone-700 mb-1">
        {fallback ? "找不到完全符合的 DM，先列出接近條件的結果。" : "已找到符合條件的 DM。"}
        <span className="font-medium"> {dms.length} 張</span>
      </p>
      <div className={`flex items-center gap-1.5 text-[10px] text-stone-500 ${compact ? "mb-3" : ""}`}>
        <Search className="w-3 h-3" />
        <span className="truncate">查詢：{query}</span>
      </div>
    </>
  );

  const CriteriaChips = ({ className = "" }) => chips.length > 0 && (
    <div className={`rounded-md border px-3 py-2.5 ${className}`} style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
      <div className="flex items-center gap-2 mb-1.5">
        <Sparkles className="w-3 h-3 text-stone-500" />
        <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500 font-medium">搜尋條件</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <div key={chip.key} className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-white border" style={{ borderColor: "#E5DDC8" }}>
            <span className="text-[9px] tracking-[0.1em] uppercase text-stone-400">{chip.label}</span>
            <span className="text-[11px] font-medium" style={{ color: "#1C1917" }}>{chip.value}</span>
          </div>
        ))}
      </div>
    </div>
  );

  const hasSelection = selected.size > 0;

  if (isCompact) {
    const previewSet = dms.slice(0, 4);
    return (
      <div>
        <Summary compact />
        <CriteriaChips className="mb-3" />
        <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 p-3">
            {previewSet.map((dm, i) => (
              <button key={dm.id} onClick={() => onPreview(dm, dms)} className="group relative overflow-hidden rounded-md bg-stone-100" style={{ aspectRatio: "827 / 1169", animationDelay: `${i * 60}ms` }}>
                <DmImage dm={dm} alt={dm.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent p-2">
                  <div className="text-[10px] text-white/80 mb-0.5 truncate">{dm.source}</div>
                  <div className="text-[11px] text-white font-medium leading-tight line-clamp-1">{dm.title}</div>
                </div>
              </button>
            ))}
          </div>
          <button onClick={() => onSelect && onSelect(dms)} className="w-full px-4 py-3 border-t flex items-center justify-between hover:bg-[#FAF7EE] transition-colors group" style={{ borderColor: "#E5DDC8", color: "#1C1917" }}>
            <div className="flex items-center gap-2">
              <MousePointerClick className="w-3.5 h-3.5" />
              <span className="text-sm font-medium">選取要組合的圖片</span>
              <span className="text-[10px] text-stone-500">共 {dms.length} 張</span>
            </div>
            <ArrowRight className="w-3 h-3 text-stone-500 group-hover:text-stone-900 group-hover:translate-x-0.5 transition-all" />
          </button>
          <div className="border-t flex" style={{ borderColor: "#F0E9D6" }}>
            <button onClick={() => onPreview(dms[0], dms)} className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors text-stone-600 hover:text-stone-900 border-r" style={{ borderColor: "#F0E9D6" }}>
              <Maximize2 className="w-3 h-3" />
              <span className="text-[11px]">預覽第一張</span>
            </button>
            <button onClick={handleCopyAll} className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors" style={{ color: copiedAll ? "#16A34A" : "#57534E" }}>
              {copiedAll ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
              <span className="text-[11px] font-medium">{copiedAll ? `已複製 ${dms.length} 張` : `複製全部 (${dms.length})`}</span>
            </button>
          </div>
        </div>
        <p className="text-[10px] text-stone-500 leading-relaxed mt-2">可先進入選取模式，再挑出要複製或組合的圖片。</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1"><Summary /></div>
        {dms.length > 1 && !hasSelection && (
          <button onClick={handleCopyAll} className="flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium border transition-all" style={{ borderColor: copiedAll ? "#16A34A" : "#1C1917", backgroundColor: copiedAll ? "#16A34A" : "transparent", color: copiedAll ? "#F5F1E8" : "#1C1917" }}>
            {copiedAll ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
            {copiedAll ? `已複製 ${dms.length} 張` : "複製全部"}
          </button>
        )}
      </div>

      {hasSelection && (
        <div className="rounded-md px-3 py-2 mb-3 flex items-center justify-between gap-2 animate-fade-up" style={{ backgroundColor: "#1C1917" }}>
          <span className="text-[11px] text-white/80 tabular-nums">
            <span className="font-display italic text-base text-white">{selected.size}</span>
            <span className="text-white/50 ml-1">/ {dms.length}</span>
            <span className="ml-2">已選取</span>
          </span>
          <div className="flex items-center gap-1.5">
            <button onClick={clearSelection} className="px-3 py-1 rounded text-[11px] hover:bg-white/10 transition-colors" style={{ color: "#F5F1E8" }}>清除選取</button>
            <button onClick={handleCopySelected} className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium transition-all" style={{ backgroundColor: copiedSelected ? "#16A34A" : "#F5F1E8", color: copiedSelected ? "#F5F1E8" : "#1C1917" }}>
              {copiedSelected ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
              {copiedSelected ? `已複製 ${selected.size} 張` : `複製選取 ${selected.size} 張`}
            </button>
          </div>
        </div>
      )}

      {!hasSelection && <CriteriaChips className="mb-4" />}
      <div className="space-y-2">
        {dms.map((dm, i) => (
          <DMPosterCard key={dm.id} dm={dm} index={i} copied={copiedId === dm.id} onCopy={() => onCopy(dm)} onPreview={() => onPreview(dm, dms)} isSelected={selected.has(dm.id)} onToggleSelect={() => toggleSelect(dm.id)} />
        ))}
      </div>
    </div>
  );
}
function DMPosterCard({ dm, index, copied, onCopy, onPreview, isSelected, onToggleSelect }) {
  return (
    <div
      className="animate-slide-in rounded-lg border bg-white transition-all relative"
      style={{
        borderColor: isSelected ? "#1C1917" : "#E5DDC8",
        backgroundColor: isSelected ? "#FAF7EE" : "white",
        boxShadow: isSelected ? "0 0 0 1px #1C1917" : undefined,
        animationDelay: `${index * 60}ms`,
      }}
    >
      <div className="flex gap-3 p-3 items-center">
        {/* Always-visible checkbox */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect();
          }}
          className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center transition-all hover:scale-110"
          style={{
            backgroundColor: isSelected ? "#1C1917" : "transparent",
            border: isSelected ? "none" : "1.5px solid #D6CFB8",
          }}
          aria-label={isSelected ? "???詨?" : "?詨?"}
        >
          {isSelected && (
            <Check className="w-3 h-3" style={{ color: "#F5F1E8" }} strokeWidth={3} />
          )}
        </button>

        {/* Thumbnail ??always opens preview */}
        <button
          onClick={onPreview}
          className="relative flex-shrink-0 overflow-hidden rounded bg-stone-100 group"
          style={{ width: "60px", aspectRatio: "827 / 1169" }}
          aria-label="?曉之瑼Ｚ?"
        >
          <DmImage dm={dm} alt={dm.title} className="w-full h-full object-cover" />
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
            <Maximize2 className="w-3.5 h-3.5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </button>

        {/* Content ??clicking row body also toggles selection (excluding thumbnail and copy btn) */}
        <button
          onClick={onToggleSelect}
          className="flex-1 min-w-0 flex flex-col justify-between text-left cursor-pointer"
          aria-label="?詨?甇日?"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span
                className="text-[9px] tracking-wider uppercase px-1.5 py-0.5 rounded-sm flex-shrink-0"
                style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
              >
                {dm.tag}
              </span>
              <span className="text-[10px] text-stone-500 truncate">{dm.source}</span>
            </div>
            <h3 className="font-serif-tc font-medium text-sm leading-snug truncate">
              {dm.title}
            </h3>
            <div className="text-[11px] text-stone-600 truncate mt-0.5">
              {dm.region} 繚 {dm.period}
            </div>
          </div>
          <div className="flex items-baseline justify-between gap-2 mt-1.5">
            <span
              className="text-[13px] font-semibold tabular-nums"
              style={{ color: "#B91C1C" }}
            >
              {dm.days > 0 ? `${dm.days}??繚 ` : ""}
              {dm.price}
            </span>
          </div>
        </button>

        {/* Per-card quick copy ??single-DM shortcut */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onCopy();
          }}
          className="flex-shrink-0 self-center flex items-center justify-center gap-1 px-3 py-1.5 rounded-md text-[11px] font-medium transition-all whitespace-nowrap"
          style={{
            backgroundColor: copied ? "#16A34A" : "#1C1917",
            color: "#F5F1E8",
          }}
        >
          {copied ? (
            <>
              <Check className="w-3 h-3" />
              撌脰?鋆?
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              銴ˊ
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, accent, compact }) {
  return (
    <div className="flex items-baseline gap-2 min-w-0">
      <span className="text-[9px] tracking-[0.15em] uppercase text-stone-400 flex-shrink-0">
        {label}
      </span>
      <span
        className={`text-[11px] truncate ${compact ? "tabular-nums" : ""}`}
        style={{
          color: accent ? "#B91C1C" : "#1C1917",
          fontWeight: accent ? 600 : 400,
        }}
      >
        {value}
      </span>
    </div>
  );
}

/* ===================================================================== */
/* DAILY SUMMARY ??Agent latest data, original summary UI                 */
/* ===================================================================== */
/* DAILY SUMMARY                                                          */
/* ===================================================================== */
function DailySummary({ dms = [], onPreview, onSelect, onCopy }) {
  const todays = Array.isArray(dms) ? dms : [];
  const previewSet = todays.slice(0, 4);
  const [copiedAll, setCopiedAll] = useState(false);

  const handleCopyAll = async () => {
    const ok = await onCopy(todays);
    if (!ok) return;
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2500);
  };

  if (todays.length === 0) {
    return <p className="text-sm leading-relaxed text-stone-700">目前沒有今日新增 DM。</p>;
  }

  return (
    <div>
      <p className="text-sm leading-relaxed text-stone-700 mb-4">
        今日新增 <span className="font-medium">{todays.length} 張</span> DM，可直接預覽、選取或複製。
      </p>
      <div className="rounded-lg border bg-white overflow-hidden mb-4" style={{ borderColor: "#E5DDC8" }}>
        <div className="px-4 py-3 flex items-center justify-between border-b" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-stone-500" />
            <span className="text-xs font-medium">Agent 今日摘要</span>
          </div>
          <span className="text-[10px] text-stone-500">最近索引結果</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 p-3">
          {previewSet.map((dm, i) => (
            <button key={dm.id} onClick={() => onPreview(dm, todays)} className="group relative overflow-hidden rounded-md bg-stone-100" style={{ aspectRatio: "827 / 1169", animationDelay: `${i * 60}ms` }}>
              <DmImage dm={dm} alt={dm.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent p-2">
                <div className="text-[10px] text-white/80 mb-0.5 truncate">{dm.source}</div>
                <div className="text-[11px] text-white font-medium leading-tight line-clamp-1">{dm.title}</div>
              </div>
            </button>
          ))}
        </div>
        <button onClick={() => onSelect && onSelect(todays)} className="w-full px-4 py-3 border-t flex items-center justify-between hover:bg-[#FAF7EE] transition-colors group" style={{ borderColor: "#E5DDC8", color: "#1C1917" }}>
          <div className="flex items-center gap-2">
            <MousePointerClick className="w-3.5 h-3.5" />
            <span className="text-sm font-medium">選取要組合的圖片</span>
            <span className="text-[10px] text-stone-500">共 {todays.length} 張</span>
          </div>
          <ArrowRight className="w-3 h-3 text-stone-500 group-hover:text-stone-900 group-hover:translate-x-0.5 transition-all" />
        </button>
        <div className="border-t flex" style={{ borderColor: "#F0E9D6" }}>
          <button onClick={() => onPreview(todays[0], todays)} className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors text-stone-600 hover:text-stone-900 border-r" style={{ borderColor: "#F0E9D6" }}>
            <Maximize2 className="w-3 h-3" />
            <span className="text-[11px]">預覽第一張</span>
          </button>
          <button onClick={handleCopyAll} className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors" style={{ color: copiedAll ? "#16A34A" : "#57534E" }}>
            {copiedAll ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
            <span className="text-[11px] font-medium">{copiedAll ? `已複製 ${todays.length} 張` : `複製全部 (${todays.length})`}</span>
          </button>
        </div>
      </div>
      <p className="text-[10px] text-stone-500 leading-relaxed">今日摘要使用 Agent 最新索引資料，方便快速挑圖與複製。</p>
    </div>
  );
}

/* ===================================================================== */
/* SCHEDULE UNAVAILABLE MESSAGE                                           */
/* ===================================================================== */
function ScheduleUnavailableMessage({ action, requestedTimes }) {
  const times = Array.isArray(requestedTimes) ? requestedTimes : [];
  const actionLabel = action === "view" ? "查看排程" : action === "add" ? "新增排程" : action === "remove" ? "移除排程" : "排程操作";

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4" style={{ color: "#D97706" }} />
        <span className="text-sm font-medium">目前無法直接操作排程</span>
      </div>
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        <div className="px-4 py-3 border-b" style={{ borderColor: "#F0E9D6", backgroundColor: "#FAF7EE" }}>
          <div className="flex items-center gap-2 mb-1.5">
            <Clock className="w-3 h-3 text-stone-500" />
            <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500 font-medium">{actionLabel}</span>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {times.length > 0 ? times.map((time) => (
              <span key={time} className="text-xs font-medium tabular-nums px-2.5 py-1 rounded" style={{ backgroundColor: "#F5F1E8", color: "#1C1917" }}>{time}</span>
            )) : <span className="text-xs text-stone-500">未指定時間</span>}
          </div>
        </div>
        <div className="px-4 py-3">
          <p className="text-xs text-stone-600 leading-relaxed">排程需要由後端 RPA 或 Agent Web API 寫入，目前前台只顯示狀態與提示。</p>
        </div>
      </div>
    </div>
  );
}

/* ===================================================================== */
/* DUPLICATES MESSAGE                                                     */
/* ===================================================================== */
function DuplicatesMessage({ groups, onCompareDup, onReviewDup, onPreview }) {
  const dups = Array.isArray(groups) ? groups : [];

  if (dups.length === 0) {
    return <p className="text-sm leading-relaxed text-stone-700">目前沒有偵測到重複圖片。</p>;
  }

  return (
    <div>
      <p className="text-sm leading-relaxed text-stone-700 mb-4">
        發現 <span className="font-medium">{dups.length} 組</span> 可能重複圖片，可檢視、忽略或保留一張。
      </p>
      <div className="space-y-3">
        {dups.map((dup, i) => (
          <div key={i} className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
            <div className="px-4 py-3 border-b" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Layers className="w-3.5 h-3.5 text-stone-500" />
                    <span className="text-xs font-medium">{dup.key}</span>
                  </div>
                  <div className="text-[10px] text-stone-500">來源：{dup.images.map((image) => image.source).join("、")}</div>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full flex-shrink-0" style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}>{dup.count} 張相似</span>
              </div>
            </div>
            <div className="px-4 py-3 flex gap-2 overflow-x-auto">
              {dup.images.map((image, j) => (
                <button key={j} onClick={() => onPreview(image.dm, dup.images.map((item) => item.dm))} className="flex-shrink-0 relative rounded-md overflow-hidden bg-stone-100 hover:ring-2 hover:ring-stone-900 transition-all" style={{ width: "72px", aspectRatio: "827 / 1169" }}>
                  <DmImage dm={image.dm} alt={image.source} className="w-full h-full object-cover" />
                  <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-1.5 py-1">
                    <div className="text-[8px] text-white/90 truncate">{image.source}</div>
                  </div>
                </button>
              ))}
            </div>
            <div className="px-4 py-3 flex gap-2 border-t" style={{ borderColor: "#F0E9D6" }}>
              <button onClick={() => onReviewDup?.(dup, 0, "keep_one")} className="flex-1 px-3 py-1.5 rounded-md text-xs font-medium" style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}>保留一張</button>
              <button onClick={() => onReviewDup?.(dup, 0, "ignore")} className="flex-1 px-3 py-1.5 rounded-md text-xs border hover:border-stone-900 transition-colors" style={{ borderColor: "#E5DDC8" }}>忽略</button>
              <button onClick={() => onCompareDup(dup)} className="flex-1 px-3 py-1.5 rounded-md text-xs border hover:border-stone-900 transition-colors" style={{ borderColor: "#E5DDC8" }}>比較</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
/* MODALS                                                                 */
/* ===================================================================== */
function DMPreviewModal({ initial, list, onClose, onCopy, copiedId }) {
  const dmList = list && list.length > 0 ? list : [initial];
  const initialIdx = Math.max(0, dmList.findIndex((dm) => dm.id === initial.id));
  const [index, setIndex] = useState(initialIdx);
  const current = dmList[index] || initial;
  const canNavigate = dmList.length > 1;

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft" && canNavigate) setIndex((value) => (value - 1 + dmList.length) % dmList.length);
      if (event.key === "ArrowRight" && canNavigate) setIndex((value) => (value + 1) % dmList.length);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, canNavigate, dmList.length]);

  return (
    <div className="fixed inset-0 z-50 animate-backdrop-in overflow-hidden" style={{ backgroundColor: "rgba(28,25,23,0.92)" }} onClick={onClose}>
      <div className="absolute top-4 left-4 right-4 flex items-center justify-between text-xs pointer-events-none z-10">
        <div className="pointer-events-auto rounded-md bg-white/90 px-3 py-2 shadow-sm">
          <div className="font-medium text-stone-900 truncate max-w-[60vw]">{current.title}</div>
          <div className="text-[10px] text-stone-500">{index + 1} / {dmList.length}</div>
        </div>
        <button onClick={onClose} className="pointer-events-auto p-2 rounded-md bg-white/90 hover:bg-white transition-colors" aria-label="關閉預覽">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="h-full flex items-center justify-center p-5" onClick={(event) => event.stopPropagation()}>
        {canNavigate && (
          <button onClick={() => setIndex((value) => (value - 1 + dmList.length) % dmList.length)} className="absolute left-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-white/90 hover:bg-white" aria-label="上一張">
            <ChevronLeft className="w-5 h-5" />
          </button>
        )}
        <div className="max-h-[82vh] max-w-[92vw] rounded-lg overflow-hidden bg-stone-100 shadow-2xl" style={{ aspectRatio: "827 / 1169" }}>
          <DmImage dm={current} alt={current.title} className="h-full w-full object-contain bg-stone-100" loading="eager" />
        </div>
        {canNavigate && (
          <button onClick={() => setIndex((value) => (value + 1) % dmList.length)} className="absolute right-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-white/90 hover:bg-white" aria-label="下一張">
            <ChevronRight className="w-5 h-5" />
          </button>
        )}
      </div>

      <div className="absolute left-4 right-4 bottom-4 flex items-center justify-between gap-3 rounded-lg bg-white/95 px-4 py-3 shadow-xl">
        <div className="min-w-0">
          <div className="text-sm font-medium truncate">{current.source}</div>
          <div className="text-xs text-stone-500 truncate">{current.region} · {current.period}</div>
        </div>
        <button onClick={() => onCopy(current)} className="shrink-0 inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium" style={{ backgroundColor: copiedId === current.id ? "#16A34A" : "#1C1917", color: "#F5F1E8" }}>
          {copiedId === current.id ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copiedId === current.id ? "已複製" : "複製"}
        </button>
      </div>
    </div>
  );
}

function SelectionModal({ list, onClose, onCopy }) {
  const [selected, setSelected] = useState(() => new Set((list || []).map((item) => item.id)));
  const [copied, setCopied] = useState(false);
  const items = Array.isArray(list) ? list : [];

  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggle = (id) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const copySelected = async () => {
    const selectedItems = items.filter((item) => selected.has(item.id));
    const ok = await onCopy(selectedItems);
    if (!ok) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.72)" }} onClick={onClose}>
      <div className="w-full max-w-5xl max-h-[88vh] bg-white rounded-lg shadow-xl overflow-hidden animate-modal-in" onClick={(event) => event.stopPropagation()}>
        <div className="px-5 py-4 border-b flex items-center justify-between" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div>
            <div className="text-[10px] tracking-[0.2em] uppercase text-stone-500">批次選取</div>
            <div className="text-sm font-medium">已選 {selected.size} / {items.length} 張</div>
          </div>
          <button onClick={onClose} className="p-2 rounded-md hover:bg-stone-200 transition-colors" aria-label="關閉">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 overflow-y-auto max-h-[64vh] scrollbar-thin">
          {items.map((dm) => {
            const isSelected = selected.has(dm.id);
            return (
              <button key={dm.id} onClick={() => toggle(dm.id)} className="relative rounded-md border overflow-hidden text-left bg-white" style={{ borderColor: isSelected ? "#1C1917" : "#E5DDC8" }}>
                <div className="bg-stone-100" style={{ aspectRatio: "827 / 1169" }}>
                  <DmImage dm={dm} alt={dm.title} className="w-full h-full object-cover" />
                </div>
                <div className="p-2">
                  <div className="text-[11px] font-medium truncate">{dm.title}</div>
                  <div className="text-[10px] text-stone-500 truncate">{dm.source}</div>
                </div>
                {isSelected && <div className="absolute top-2 right-2 rounded-full p-1" style={{ backgroundColor: "#1C1917" }}><Check className="w-3 h-3" style={{ color: "#F5F1E8" }} /></div>}
              </button>
            );
          })}
        </div>
        <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8" }}>
          <button onClick={() => setSelected(new Set())} className="px-3 py-2 rounded-md text-xs border" style={{ borderColor: "#E5DDC8" }}>清除</button>
          <button onClick={copySelected} disabled={selected.size === 0} className="inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium disabled:opacity-50" style={{ backgroundColor: copied ? "#16A34A" : "#1C1917", color: "#F5F1E8" }}>
            {copied ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
            {copied ? "已複製" : "複製選取"}
          </button>
        </div>
      </div>
    </div>
  );
}
function DuplicateCompareModal({ data, onClose, onReview }) {
  const [keepIdx, setKeepIdx] = useState(0);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-8 animate-backdrop-in"
      style={{ backgroundColor: "rgba(28,25,23,0.85)" }}
      onClick={onClose}
    >
      <div
        className="animate-modal-in bg-white rounded-lg max-w-6xl w-full max-h-[90vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-6 py-4 border-b flex items-center justify-between"
          style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
        >
          <div>
            <div className="text-[10px] tracking-[0.2em] uppercase text-stone-500 mb-0.5">
              ??瑼Ｚ? 繚 ????瘥?
            </div>
            <h2 className="font-serif-tc font-medium text-lg">{data.key}</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-md hover:bg-stone-200 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-thin p-6">
          <p className="text-xs text-stone-600 mb-4">
            隞乩??箔???<span className="font-medium">{data.count}</span> ?冗蝢斤?????嚗?
            ?文?靘?嚗?????潛??詨????豢?靽??嚗擗?鋡急飛瑼?
          </p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {data.images.map((im, i) => {
              const selected = keepIdx === i;
              return (
                <div
                  key={i}
                  className="rounded-lg border-2 overflow-hidden transition-all cursor-pointer"
                  style={{
                    borderColor: selected ? "#1C1917" : "#E5DDC8",
                    backgroundColor: selected ? "#FAF7EE" : "white",
                  }}
                  onClick={() => setKeepIdx(i)}
                >
                  <div
                    className="relative bg-stone-100"
                    style={{ aspectRatio: "827 / 1169" }}
                  >
                    <DmImage dm={im.dm} alt={im.source} className="w-full h-full object-cover" />
                    {selected && (
                      <div
                        className="absolute top-2 right-2 w-6 h-6 rounded-full flex items-center justify-center"
                        style={{ backgroundColor: "#1C1917" }}
                      >
                        <Check className="w-3.5 h-3.5" style={{ color: "#F5F1E8" }} />
                      </div>
                    )}
                  </div>
                  <div className="px-3 py-3">
                    <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-1">
                      靘?
                    </div>
                    <div className="text-sm font-medium mb-2 truncate">{im.source}</div>
                    <div className="flex items-center gap-1.5 text-[10px] text-stone-500">
                      <Clock className="w-3 h-3" />
                      銝???隞 {im.time}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div
          className="px-6 py-4 border-t flex items-center justify-between gap-3"
          style={{ borderColor: "#E5DDC8" }}
        >
          <div className="text-xs text-stone-600">
            撠???
            <span className="font-medium ml-1">{data.images[keepIdx].source}</span>
            <span className="text-stone-400 ml-2">
              ?園? {data.images.length - 1} 隞賣飛瑼?
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-md text-xs border hover:border-stone-900 transition-colors"
              style={{ borderColor: "#E5DDC8" }}
            >
              ??
            </button>
            <button
              onClick={() => onReview?.(data, keepIdx, "ignore")}
              className="px-4 py-2 rounded-md text-xs border hover:border-stone-900 transition-colors"
              style={{ borderColor: "#E5DDC8" }}
            >
              銝??
            </button>
            <button
              onClick={() => onReview?.(data, keepIdx, "keep_one")}
              className="px-4 py-2 rounded-md text-xs font-medium"
              style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
            >
              蝣箄?靽?
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const rootElement = document.getElementById("root");
if (rootElement) {
  createRoot(rootElement).render(<LoginGate />);
}

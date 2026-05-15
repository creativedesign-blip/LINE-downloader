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
        圖片載入失敗
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
    throw new Error("沒有可下載的圖片。");
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
    let message = "下載圖片包失敗。";
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
    `${index + 1}. ${dm?.title || "旅遊 DM"}`,
    dm?.region ? `地區：${dm.region}` : "",
    dm?.period ? `期間：${dm.period}` : "",
    dm?.price ? `價格：${dm.price}` : "",
    dm?.source ? `來源：${dm.source}` : "",
    dmFullImage(dm) ? `圖片：${toAbsoluteUrl(dmFullImage(dm))}` : "",
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

  let reason = "瀏覽器拒絕寫入圖片剪貼簿。";
  if (!details.secure || details.protocol !== "https:") {
    reason = "目前不是 HTTPS，瀏覽器禁止網頁複製圖片。";
  } else if (!details.clipboardWrite || !details.clipboardItem) {
    reason = "這個瀏覽器不支援圖片剪貼簿。請用最新版 Chrome 或 Edge。";
  } else if (!details.focused || details.visibility !== "visible" || /not focused/i.test(message)) {
    reason = "頁面沒有焦點。請先點一下頁面空白處，再直接按複製，不要切換視窗。";
  } else if (/notallowed|permission|denied/i.test(`${name} ${message}`)) {
    reason = "剪貼簿權限被瀏覽器拒絕。請確認網址列左側允許剪貼簿，並由按鈕直接觸發複製。";
  } else if (/load image|fetch|network|failed/i.test(message)) {
    reason = "圖片載入失敗，可能是外網連線或圖片網址回應太慢。";
  } else if (/too large|size|memory|canvas/i.test(message)) {
    reason = "圖片太大或合成圖太大，瀏覽器無法放入剪貼簿。";
  }

  return [
    reason,
    `技術訊息：${name || "Error"} ${message}`.trim(),
    `環境：${details.browser} / secure=${details.secure} / focus=${details.focused} / visibility=${details.visibility} / write=${details.clipboardWrite} / ClipboardItem=${details.clipboardItem} / html=${details.htmlClipboard} / png=${details.pngClipboard}`,
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
    throw buildClipboardError("圖片載入失敗，無法複製。", error);
  }
}

async function fetchImageBitmap(url) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`Cannot load image for clipboard (${response.status}).`);
    return createImageBitmap(await response.blob());
  } catch (error) {
    throw buildClipboardError("圖片載入失敗，無法複製。", error);
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
    throw buildClipboardError("瀏覽器不允許 HTML 圖片剪貼簿。");
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    window.focus?.();
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    throw buildClipboardError("頁面沒有焦點，無法複製 HTML 圖片。");
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
    throw buildClipboardError("HTML base64 圖片寫入剪貼簿失敗。", error);
  }
}

async function writeImageBlobToClipboard(blobOrPromise) {
  if (!window.isSecureContext || !navigator.clipboard?.write || !window.ClipboardItem) {
    throw buildClipboardError("瀏覽器不允許圖片剪貼簿。");
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    window.focus?.();
  }
  if (document.visibilityState !== "visible" || !document.hasFocus?.()) {
    throw buildClipboardError("頁面沒有焦點，無法複製圖片。");
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
    throw buildClipboardError("圖片寫入剪貼簿失敗。", error);
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
      throw buildClipboardError("目前不是 HTTPS，瀏覽器禁止複製圖片到剪貼簿。");
    }
    if (!navigator.clipboard?.write || !window.ClipboardItem) {
      throw buildClipboardError("這個瀏覽器不支援圖片剪貼簿，請改用 Chrome 或 Edge。");
    }
    throw imageError || buildClipboardError("圖片沒有成功寫入剪貼簿。");
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
      label: status.pipeline.label || "LINE圖片處理中",
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
    label: isComplete ? "LINE圖片處理完成" : "LINE圖片處理中",
    color: isComplete ? "#16A34A" : "#D97706",
  };
}

function formatDateTime(value) {
  if (!value) return "尚無";
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
  if (job?.running) return "執行中";
  if (job?.status === "success") return "成功";
  if (job?.status === "failed") return "失敗";
  if (job?.last_success === true) return "成功";
  if (job?.last_success === false) return "失敗";
  if (job?.status === "stale") return "中斷";
  return "未執行";
}

function jobStepLabel(status) {
  if (status === "success") return "完成";
  if (status === "running") return "處理中";
  if (status === "failed") return "失敗";
  if (status === "skipped") return "略過";
  return "等待";
}

function jobStepAccent(status) {
  return status === "running" || status === "failed" || status === "stale";
}

function jobSourceLabel(source) {
  if (source === "manual") return "手動";
  if (source === "scheduled") return "定時";
  if (source === "test") return "測試";
  return "未知";
}

function manualJobMessage(job) {
  if (!job) return "手動流程狀態：未取得。";
  const parts = [
    `手動流程狀態：${manualJobLabel(job)}`,
    `開始：${formatDateTime(job.last_started_at)}`,
    `結束：${formatDateTime(job.last_finished_at)}`,
  ];
  if (job.pid) parts.push(`PID：${job.pid}`);
  if (job.last_error) parts.push(`錯誤：${job.last_error}`);
  return parts.join("。");
}

/* ===== MAIN APP ===== */
/* ===== DADOVA LOGO COMPONENT ===== */
function DadovaLogo({ size = 32, inverted = false }) {
  // Globe icon in rounded black square — matches "新組圖完成" notification icon style
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
      aria-label="大都會旅遊"
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
  // Match HH:MM pattern (24h) — accepts 1–2 digit hours, requires minutes
  const timeRegex = /\b([01]?\d|2[0-3])[:：]([0-5]\d)\b/g;
  const matches = [...query.matchAll(timeRegex)];
  const times = matches.map((m) => `${String(parseInt(m[1], 10)).padStart(2, "0")}:${m[2]}`);

  const isScheduleContext = /排程|時段|跑爬|爬取時間|爬蟲時間|執行時間|schedule/i.test(query);

  // Pure view query
  if (isScheduleContext && times.length === 0) {
    if (/查看|顯示|看看|現在|目前|當前|是什麼|什麼時候|哪些/.test(query) || /排程$/.test(query.trim())) {
      return { action: "view", times: [] };
    }
  }

  // Removal: "刪除 14:30" / "拿掉 17:30" / "移除 09:30"
  if (times.length > 0 && /刪除|拿掉|移除|刪掉|取消/.test(query)) {
    return { action: "remove", times };
  }

  // Addition: "新增 20:00" / "加上 21:30" / "再加一個 22:00"
  if (times.length > 0 && /新增|加上|加入|再加|增加|多加/.test(query)) {
    return { action: "add", times };
  }

  // Replacement: "改成 ..." / "調整為 ..." / "排程改成 ..." / explicit list
  if (times.length > 0 && (isScheduleContext || /改成|調整|改為|改|更新|設定為|設成|變成/.test(query))) {
    return { action: "replace", times };
  }

  return null;
}

function isManualAgentRunCommand(query) {
  return /手動觸發抓取\+ocr\+組圖/i.test(query.trim());
}

function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState("admin_dadova");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await onLogin({ username, password });
    } catch (loginError) {
      setError(loginError.message || "登入失敗，請稍後再試。");
    } finally {
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
            <div className="font-serif-tc text-xl font-medium leading-tight">大都會旅遊</div>
            <div className="text-[10px] tracking-[0.18em] uppercase text-stone-500 mt-1">
              Dadova · agent
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
            外部介面登入
          </div>
          <h1 className="font-serif-tc text-2xl font-medium leading-tight mb-6">
            請先登入 Agent 介面
          </h1>

          <label className="block text-xs font-medium text-stone-600 mb-2" htmlFor="login-username">
            帳號
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
            密碼
          </label>
          <div className="relative mb-5">
            <KeyRound className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
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
            {submitting ? "登入中" : "登入"}
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
      throw new Error(payload?.error || "登入失敗");
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
    { id: 1, role: "agent", type: "welcome", time: "今日 09:42" },
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
  const notifRef = useRef(null);
  const enterArmedRef = useRef(false);
  const enterTimerRef = useRef(null);
  const scrollRef = useRef(null);
  const manualPreviewPollRef = useRef(null);
  const inputRef = useRef(null);

  const suggestions = [
    { icon: Inbox, label: "查看今日新組合", prompt: "今天有哪些新組合好的圖片 DM？" },
    { icon: Zap, label: "手動觸發抓取+ocr+組圖", prompt: "手動觸發抓取+ocr+組圖" },
    { icon: Search, label: "查詢日本所有方案", prompt: "幫我找日本的所有方案" },
    { icon: Layers, label: "處理重複圖片", prompt: "顯示待審核的重複圖片清單" },
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

  const getTime = () => {
    const d = new Date();
    return `今日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  const formatPrice = (value) => {
    const n = Number(value);
    return Number.isFinite(n) && n >= 5000 ? `NT$ ${n.toLocaleString()}` : "價格待確認";
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
      ? `${item.months.join(", ")} 月`
      : "月份待確認";
    const indexed = item.indexed_at
      ? `索引 ${new Date(item.indexed_at).toLocaleDateString("zh-TW")}`
      : "";
    return [months, indexed].filter(Boolean).join(" · ");
  };

  const normalizeAgentItem = (item, index = 0) => {
    const countries = Array.isArray(item.countries) ? item.countries : [];
    const regions = Array.isArray(item.regions) ? item.regions : [];
    const features = Array.isArray(item.features) ? item.features : [];
    const place = [...countries, ...regions].filter(Boolean).join(" / ") || "旅遊";
    const days = Number(item.duration_days) || 0;
    const priceSummary = formatPriceSummary(item);
    const titleParts = [place, days ? `${days} 天` : "", priceSummary];

    return {
      id: item.sidecar_path || item.branded_path || item.image_path || `openclaw-${index}`,
      image: item.thumbnail_url || item.image_url || item.branded_path || item.image_path || "",
      fullImage: item.image_url || item.branded_path || item.image_path || "",
      previewImage: item.preview_url || item.image_url || item.branded_path || item.image_path || "",
      thumbnail: item.thumbnail_url || item.image_url || item.branded_path || item.image_path || "",
      mediaId: item.media_id || "",
      title: titleParts.filter(Boolean).join(" · "),
      region: place,
      period: formatPeriod(item),
      days,
      price: priceSummary,
      tag: features[0] || "Agent",
      keywords: [...countries, ...regions, ...features],
      highlights: [
        countries.length ? `國家：${countries.join("、")}` : "國家待確認",
        regions.length ? `地區：${regions.join("、")}` : "地區待確認",
        item.group_name || item.target_id ? `來源：${item.group_name || item.target_id}` : "來源待確認",
      ],
      source: item.group_name || item.target_id || "Agent",
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
        Array.isArray(match.months) && match.months.length ? `${match.months.join(", ")} 月` : "",
        match.duration_days ? `${match.duration_days} 天` : "",
        match.price_bucket ? `約 NT$ ${Number(match.price_bucket).toLocaleString()}` : "",
      ].filter(Boolean);

      return {
        key: keyParts.join(" · ") || `重複群組 ${groupIndex + 1}`,
        groupId: group.group_id || "",
        count: group.count || dms.length,
        images: dms.map((dm) => ({
          dm,
          source: dm.source,
          time: dm.raw?.indexed_at
            ? new Date(dm.raw.indexed_at).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })
            : "待確認",
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

  useEffect(() => {
    refreshOverview();
    const id = setInterval(refreshOverview, 60_000);
    return () => {
      clearInterval(id);
      if (manualPreviewPollRef.current) manualPreviewPollRef.current.cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const buildAgentResponse = (payload, query) => {
    if (payload?.error) {
      return {
        id: Date.now() + 1,
        role: "agent",
        type: "text",
        content: `Agent 回傳錯誤：${payload.error}`,
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
          content: "沒有找到待處理的重複圖片。",
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
        content: `沒有找到「${query}」的旅遊 DM。`,
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

  const appendTodayCombinationPreview = async (query = "查看今日組合") => {
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
        const status = await (await fetch("/api/openclaw/status")).json();
        const job = status?.latest_job || status?.manual_job;
        setOverview((current) => ({
          ...current,
          status,
          loading: false,
          error: status.error || current.error || null,
        }));

        if (!job || job.running || job.status === "running") continue;

        const ok = job.status === "success" || job.last_success === true;
        if (ok) {
          await appendTodayCombinationPreview("手動流程完成：今日組合");
        } else {
          setMessages((p) => [
            ...p,
            {
              id: Date.now() + 1,
              role: "agent",
              type: "text",
              content: `手動流程失敗，無法產生直接預覽。${job.last_error ? `錯誤：${job.last_error}` : ""}`,
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
          content: "手動流程仍未回報完成，請稍後輸入「查看今日組合」取得預覽。",
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
        setMessages((p) => [
          ...p,
          {
            id: Date.now() + 1,
            role: "agent",
            type: "text",
            content: payload?.ok
              ? `${payload?.started === false ? "手動流程已在執行中。" : "已手動觸發抓取+OCR+組圖。"}處理完成前會顯示 LINE圖片處理中。${payload?.job ? ` ${manualJobMessage(payload.job)}` : ""}`
              : `手動觸發失敗：${payload?.error || "未知錯誤"}`,
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
            content: `手動觸發失敗：${error.message}`,
            time: getTime(),
          },
        ]);
      } finally {
        setIsThinking(false);
      }
      return;
    }

    // ===== Schedule commands take priority — they're explicit ops =====
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
          content: `無法連線 Agent：${error.message}`,
          time: getTime(),
        },
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  // Helpers — armed state stored in ref for synchronous read between rapid keystrokes
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

  // Double-Enter to send — IME-aware (Chinese input safe), skips empty input
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
          "圖片沒有成功寫入剪貼簿，已改為複製文字資訊。請確認使用 HTTPS 網址，並用最新版 Chrome 或 Edge 開啟。"
        );
        return false;
      }

      if (copyMode === "download") {
        window.alert(INTERNAL_WEB ? "已開始逐張下載圖片。請查看瀏覽器下載列。" : "已下載圖片包。請解壓縮後全選圖片，拖曳到 LINE 群組或聊天視窗。");
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
      window.alert(`圖片複製失敗\n\n${explainClipboardError(error)}`);
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
      window.alert("缺少重複群組 ID，無法儲存審核。");
      return false;
    }
    if (action === "keep_one" && !keepPath) {
      window.alert("缺少保留圖片路徑，無法儲存審核。");
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
      window.alert(`重複圖片審核儲存失敗：${error.message}`);
      return false;
    }
  };

  const latestCount = Number(overview.latest?.count || 0);
  const duplicateCount = Number(overview.duplicates?.count || 0);
  const totalIndexed = Number(overview.status?.total_indexed || 0);
  const hasUnreadNotifications = !notifRead && !overview.loading && (latestCount > 0 || duplicateCount > 0);
  const linePipeline = getLineImagePipelineStatus(overview.status);
  const agentStatusLabel = overview.loading ? "LINE圖片處理中" : linePipeline.label;
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
                    大都會旅遊
                  </div>
                  <div className="text-[9px] tracking-[0.18em] uppercase text-stone-500 mt-1">
                    Dadova · agent
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
                  aria-label="通知"
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
                    onSelectStatus={() => showOverviewMessage(overview.status, "status", "資料庫狀態")}
                    onSelectNew={() => showOverviewMessage(overview.latest, "latest", "最新 DM")}
                    onSelectDup={() => showOverviewMessage(overview.duplicates, "duplicates", "重複 DM")}
                  />
                )}
              </div>
              <div className="h-6 w-px bg-stone-300 hidden md:block" />
              <button
                onClick={onLogout}
                className="flex items-center gap-2 hover:bg-[#EFE9D8] rounded-md px-2 py-1 transition-colors"
                aria-label={onLogout ? "登出" : "使用者"}
                title={onLogout ? "登出" : currentUser}
              >
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0"
                  style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
                >
                  AD
                </div>
                <div className="hidden md:block text-left">
                  <div className="text-xs font-medium leading-tight">{currentUser}</div>
                  <div className="text-[10px] text-stone-500 leading-tight">已登入</div>
                </div>
                {onLogout && <LogOut className="hidden md:block w-3.5 h-3.5 text-stone-500" />}
              </button>
            </div>
          </header>

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
                  <span>正在思考</span>
                  <span className="typing-cursor">▋</span>
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
                  placeholder="查詢：幫我找 韓國 5 天 4 夜 的圖片 DM"
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
                  連按兩下 Enter 送出 · Shift+Enter 換行
                </div>
                <div className="text-[10px] text-stone-500 flex items-center gap-1.5">
                  <span className="italic font-display">Powered by</span>
                  <span className="flex items-baseline gap-1">
                    <span className="font-bold tracking-tight" style={{ color: "#2D8BC0", letterSpacing: "-0.01em" }}>
                      STARBIT
                    </span>
                    <span className="font-serif-tc" style={{ color: "#57534E" }}>
                      思偉達應用科技
                    </span>
                  </span>
                </div>
              </div>
            </div>
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
    : "尚無時間";
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
      <div
        className="px-4 py-3 border-b flex items-center justify-between"
        style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
      >
        <div className="text-sm font-medium" style={{ color: "#1C1917" }}>
          Agent 通知
        </div>
        <button
          onClick={onRefresh}
          className="text-[10px] text-stone-500 hover:text-stone-900 transition-colors"
        >
          重新整理
        </button>
      </div>

      {!hasAny ? (
        <div className="px-4 py-7 flex flex-col items-center text-center">
          <div
            className="w-10 h-10 rounded-md flex items-center justify-center mb-3"
            style={{ backgroundColor: "#F0E9D6" }}
          >
            <Clock className="w-4 h-4 text-stone-500" />
          </div>
          <div className="text-xs font-medium mb-1">尚無 Agent 通知</div>
          <div className="text-[10px] text-stone-500 leading-relaxed">
            目前沒有新的爬圖結果。
          </div>
        </div>
      ) : (
        <div className="max-h-80 overflow-y-auto scrollbar-thin">
          {overview?.loading && (
            <div className="w-full px-4 py-3 flex gap-3" style={{ borderTop: "none" }}>
              <div
                className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "#F0E9D6" }}
              >
                <Loader2 className="w-3 h-3 animate-spin text-stone-500" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">讀取 Agent</div>
                <p className="text-[11px] text-stone-600 leading-relaxed">正在更新通知結果</p>
              </div>
            </div>
          )}

          {overview?.error && (
            <button
              onClick={onSelectStatus}
              className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3"
            >
              <div
                className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "#FEF3C7" }}
              >
                <AlertTriangle className="w-3 h-3" style={{ color: "#92400E" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">Agent 發生錯誤</div>
                <p className="text-[11px] text-stone-600 leading-relaxed truncate">{overview.error}</p>
              </div>
            </button>
          )}

          {sourceEvents.length > 0 && (
            <div
              className="px-4 py-3"
              style={{ borderTop: "1px solid #F0E9D6", backgroundColor: "#FDFBF5" }}
            >
              <div className="text-xs font-medium mb-1">系統最後更新</div>
              <div className="space-y-1.5">
                {sourceEvents.map((item) => (
                  <div key={`${item.name}-${item.time}`} className="flex items-center justify-between gap-3 text-[10px]">
                    <span className="truncate text-stone-700">{item.name}</span>
                    <span className="text-stone-500 tabular-nums flex-shrink-0">
                      {new Date(item.time).toLocaleString("zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {latestCount > 0 && (
            <button
              onClick={onSelectNew}
              className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3"
              style={{ borderTop: "1px solid #F0E9D6" }}
            >
              <div
                className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "#1C1917" }}
              >
                <Sparkles className="w-3 h-3" style={{ color: "#F5F1E8" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-xs font-medium">系統最後更新</span>
                  <span className="text-[10px] text-stone-500 tabular-nums">{latestLabel}</span>
                </div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  <span className="font-display italic text-base text-stone-900">{latestCount}</span>{" "}
                  份新組合 DM
                </p>
                <div className="flex items-center gap-1 text-[10px] text-stone-500 mt-1 group-hover:text-stone-900 transition-colors">
                  查看最新結果
                  <ArrowRight className="w-2.5 h-2.5 group-hover:translate-x-0.5 transition-transform" />
                </div>
              </div>
            </button>
          )}

          {duplicateCount > 0 && (
            <button
              onClick={onSelectDup}
              className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3"
              style={{ borderTop: "1px solid #F0E9D6" }}
            >
              <div
                className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "#FEF3C7" }}
              >
                <AlertTriangle className="w-3 h-3" style={{ color: "#92400E" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-xs font-medium">待審核重複圖片</span>
                  <span className="text-[10px] text-stone-500 tabular-nums">現在</span>
                </div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  共有 <span className="font-display italic text-base" style={{ color: "#B91C1C" }}>{duplicateCount}</span> 組待確認
                </p>
                <div className="flex items-center gap-1 text-[10px] mt-1 transition-colors group-hover:text-stone-900" style={{ color: "#B91C1C" }}>
                  查看清單
                  <ArrowRight className="w-2.5 h-2.5 group-hover:translate-x-0.5 transition-transform" />
                </div>
              </div>
            </button>
          )}

          {totalIndexed > 0 && (
            <button
              onClick={onSelectStatus}
              className="w-full px-4 py-3 text-left hover:bg-[#FAF7EE] transition-colors group flex gap-3"
              style={{ borderTop: "1px solid #F0E9D6" }}
            >
              <div
                className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                style={{ backgroundColor: "#F0E9D6" }}
              >
                <Database className="w-3 h-3 text-stone-600" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">資料庫狀態</div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  已索引 <span className="font-medium">{totalIndexed}</span> 份 DM
                </p>
              </div>
            </button>
          )}
        </div>
      )}

      <div
        className="border-t flex items-center justify-center"
        style={{
          borderColor: "#E5DDC8",
          backgroundColor: "#FAF7EE",
          minHeight: "44px",
          padding: "8px 16px",
        }}
      >
        <span className="text-[10px] text-stone-500 leading-none">
          Agent 每 60 秒更新通知
        </span>
      </div>
    </div>
  );
}

/* ===================================================================== */
/* MESSAGE BLOCK                                                          */
/* ===================================================================== */
function MessageBlock({ msg, copiedId, onCopy, onAction, suggestions, onPreview, onCompareDup, onReviewDup, onSelect }) {
  if (msg.role === "user") {
    return (
      <div className="animate-fade-up mb-8 flex justify-end">
        <div className="max-w-[80%]">
          <div className="text-[10px] text-stone-500 mb-1.5 text-right">{msg.time}</div>
          <div
            className="px-4 py-3 rounded-lg text-sm leading-relaxed"
            style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
          >
            {msg.content}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-up mb-8">
      <div className="flex items-center gap-2 mb-2">
        <DadovaLogo size={20} />
        <span className="text-xs font-medium">龍哥</span>
        <span className="text-[10px] text-stone-500">· {msg.time}</span>
      </div>
      <div className="pl-7">
        {msg.type === "welcome" && <WelcomeMessage suggestions={suggestions} onAction={onAction} />}
        {msg.type === "text" && (
          <p className="text-sm leading-relaxed text-stone-700">{msg.content}</p>
        )}
        {msg.type === "status" && <AgentStatusMessage status={msg.status} />}
        {msg.type === "results" && (
          <ResultsMessage
            query={msg.query}
            criteria={msg.criteria}
            fallback={msg.fallback}
            dms={msg.dms}
            copiedId={copiedId}
            onCopy={onCopy}
            onPreview={onPreview}
            onSelect={onSelect}
          />
        )}
        {msg.type === "daily-summary" && (
          <DailySummary
            dms={msg.dms}
            onPreview={onPreview}
            onSelect={onSelect}
            onCopy={onCopy}
          />
        )}
        {msg.type === "duplicates" && (
          <DuplicatesMessage groups={msg.groups} onCompareDup={onCompareDup} onReviewDup={onReviewDup} onPreview={onPreview} />
        )}
        {msg.type === "schedule-unavailable" && (
          <ScheduleUnavailableMessage
            action={msg.action}
            requestedTimes={msg.requestedTimes}
          />
        )}
      </div>
    </div>
  );
}

/* ===================================================================== */
/* WELCOME                                                                */
/* ===================================================================== */
function WelcomeMessage({ suggestions, onAction }) {
  return (
    <div>
      <h2 className="font-display italic text-3xl md:text-4xl leading-tight mb-1">
        早安
      </h2>
      <p className="text-sm text-stone-600 leading-relaxed mb-6 max-w-md">
        我已準備好處理今日的 Agent 查詢與圖片檢視任務。
        <br />
        以下是常用指令，或直接用自然語言告訴我您想做什麼。
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-w-xl">
        {suggestions.map((s, i) => (
          <button
            key={i}
            onClick={() => onAction(s.prompt)}
            className="group flex items-center gap-3 px-4 py-3 rounded-lg border bg-white hover:border-stone-900 transition-all text-left"
            style={{ borderColor: "#E5DDC8" }}
          >
            <s.icon className="w-3.5 h-3.5 text-stone-500 group-hover:text-stone-900 transition-colors" />
            <span className="text-sm flex-1">{s.label}</span>
            <ArrowUpRight className="w-3 h-3 text-stone-400 group-hover:text-stone-900 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all" />
          </button>
        ))}
      </div>
    </div>
  );
}

/* ===================================================================== */
/* AGENT STATUS ? real indexing state                                     */
/* ===================================================================== */
function AgentStatusMessage({ status }) {
  const sources = Array.isArray(status?.items) ? status.items : [];
  const pipeline = getLineImagePipelineStatus(status);
  const totalIndexed = Number(status?.total_indexed || 0);
  const activeSources = sources.filter((item) => Number(item.indexed_count || 0) > 0);
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
      <div
        className="rounded-lg border bg-white overflow-hidden"
        style={{ borderColor: "#E5DDC8" }}
      >
        <div
          className="px-5 py-3 flex items-center justify-between border-b"
          style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
        >
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
              <span className="font-display italic text-3xl tabular-nums">
                {String(totalIndexed).padStart(2, "0")}
              </span>
              <span className="text-stone-400 text-sm">已 OCR / 索引 DM</span>
            </div>
            <span className="text-xs text-stone-500 tabular-nums">{pct}%</span>
          </div>
          <div className="h-1 rounded-full overflow-hidden" style={{ backgroundColor: "#F0E9D6" }}>
            <div
              className="h-full transition-all duration-700 ease-out"
              style={{ width: `${Math.min(100, pct)}%`, backgroundColor: "#1C1917" }}
            />
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <StatusMetric label="抓取" value={pipeline.lineFetchedDone ? "完成" : "處理中"} accent={!pipeline.lineFetchedDone} />
            <StatusMetric label="OCR" value={pipeline.ocrDone ? "完成" : "處理中"} accent={!pipeline.ocrDone} />
            <StatusMetric label="組圖" value={pipeline.composedDone ? "完成" : "處理中"} accent={!pipeline.composedDone} />
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
            <StatusMetric label="LINE圖片" value={totalTravel} />
            <StatusMetric label="組合圖" value={totalBranded} />
            <StatusMetric label="錯誤" value={errorSources.length} accent={errorSources.length > 0} />
          </div>
          {manualJob && (
            <div
              className="mt-3 rounded-md border px-3 py-2.5"
              style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
            >
              <div className="flex items-center justify-between gap-3 mb-2">
                <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">
                  最近任務 · {jobSourceLabel(manualJob.trigger_source)}
                </span>
                <span
                  className="text-xs font-medium"
                  style={{ color: manualJob.running ? "#D97706" : manualJob.last_success === false || manualJob.status === "stale" ? "#B91C1C" : "#16A34A" }}
                >
                  {manualJobStatus}
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] text-stone-600 mb-2">
                <div>開始：{formatDateTime(manualJob.started_at || manualJob.last_started_at)}</div>
                <div>結束：{formatDateTime(manualJob.finished_at || manualJob.last_finished_at)}</div>
                <div>PID：{manualJob.pid || "無"}</div>
                <div>結果：{manualJob.returncode ?? "待完成"}</div>
              </div>
              <div className="grid grid-cols-4 gap-1.5 text-xs">
                <StatusMetric label="RPA" value={jobStepLabel(jobSteps.rpa?.status)} accent={jobStepAccent(jobSteps.rpa?.status)} />
                <StatusMetric label="OCR" value={jobStepLabel(jobSteps.ocr?.status)} accent={jobStepAccent(jobSteps.ocr?.status)} />
                <StatusMetric label="組圖" value={jobStepLabel(jobSteps.compose?.status)} accent={jobStepAccent(jobSteps.compose?.status)} />
                <StatusMetric label="索引" value={jobStepLabel(jobSteps.index?.status)} accent={jobStepAccent(jobSteps.index?.status)} />
              </div>
              {manualJob.last_error && (
                <div className="mt-2 text-[10px]" style={{ color: "#B91C1C" }}>
                  {manualJob.last_error}
                </div>
              )}
            </div>
          )}
          {latestAt && (
            <div className="mt-3 flex items-center gap-2">
              <span className="text-[10px] tracking-[0.2em] uppercase text-stone-500">??</span>
              <span className="text-xs font-medium">
                {new Date(latestAt).toLocaleString("zh-TW")}
              </span>
            </div>
          )}
        </div>
        <div
          className="px-5 py-3 grid grid-cols-4 gap-1.5 border-t"
          style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
        >
          {(sources.length ? sources : [{ target_id: "Agent", indexed_count: 0 }]).slice(0, 20).map((source, i) => {
            const hasData = Number(source.indexed_count || 0) > 0;
            const hasError = Number(source.error_count || 0) > 0;
            return (
              <div
                key={`${source.target_id || source.group_name || "source"}-${i}`}
                title={`${source.target_id || source.group_name || "Agent"}: ${source.indexed_count || 0}`}
                className="h-1 rounded-full"
                style={{
                  backgroundColor: hasError ? "#B91C1C" : hasData ? "#1C1917" : "#E5DDC8",
                }}
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
/* RESULTS — compact horizontal cards in a single column                  */
/* ===================================================================== */
function ResultsMessage({ query, criteria, fallback, dms, copiedId, onCopy, onPreview, onSelect }) {
  const [copiedAll, setCopiedAll] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [copiedSelected, setCopiedSelected] = useState(false);

  // Threshold — when results exceed this, switch to compact summary view.
  const COMPACT_THRESHOLD = 6;
  const isCompact = dms.length > COMPACT_THRESHOLD;

  const handleCopyAll = async () => {
    const ok = await onCopy(dms);
    if (!ok) return;
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2500);
  };

  const toggleSelect = (id) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleCopySelected = async () => {
    if (selected.size === 0) return;
    const selectedDms = dms.filter((dm) => selected.has(dm.id));
    const ok = await onCopy(selectedDms);
    if (!ok) return;
    setCopiedSelected(true);
    setTimeout(() => {
      setCopiedSelected(false);
      setSelected(new Set());
    }, 1800);
  };

  const clearSelection = () => setSelected(new Set());

  // Build criteria chips from extracted parameters
  const chips = [];
  if (criteria?.region) {
    chips.push({ label: "地區", value: criteria.region, key: "region" });
  }
  if (criteria?.month) {
    chips.push({ label: "月份", value: `${criteria.month} 月`, key: "month" });
  }
  if (criteria?.months?.length) {
    chips.push({ label: "月份", value: `${criteria.months.join(", ")} 月`, key: "months" });
  }
  if (criteria?.season) {
    chips.push({ label: "季節", value: criteria.season, key: "season" });
  }
  if (criteria?.days) {
    const v = criteria.nights
      ? `${criteria.days} 天 ${criteria.nights} 夜`
      : `${criteria.days} 日`;
    chips.push({ label: "天數", value: v, key: "days" });
  }
  if (criteria?.minPrice || criteria?.maxPrice) {
    const minPrice = criteria.minPrice ? `NT$ ${criteria.minPrice.toLocaleString()}` : null;
    const maxPrice = criteria.maxPrice ? `NT$ ${criteria.maxPrice.toLocaleString()}` : null;
    chips.push({
      label: criteria.minPrice && criteria.maxPrice ? "預算區間" : criteria.maxPrice ? "預算上限" : "預算下限",
      value: minPrice && maxPrice ? `${minPrice} - ${maxPrice}` : maxPrice || minPrice,
      key: "price",
    });
  }
  if (criteria?.feature) {
    chips.push({ label: "特色", value: criteria.feature, key: "feature" });
  }
  if (criteria?.tag) {
    chips.push({ label: "客群", value: criteria.tag, key: "tag" });
  }
  if (criteria?.type) {
    chips.push({ label: "類型", value: criteria.type, key: "type" });
  }

  const hasSelection = selected.size > 0;

  // ===== COMPACT VIEW — for many results =====
  if (isCompact) {
    const previewSet = dms.slice(0, 4);

    return (
      <div>
        <p className="text-sm leading-relaxed text-stone-700 mb-1">
          {fallback ? (
            <>
              未找到完全符合條件的 DM，以下為相關推薦
              <span className="font-medium"> {dms.length} 份</span>
            </>
          ) : (
            <>
              為您找到符合條件的
              <span className="font-medium"> {dms.length} 份 DM</span>
            </>
          )}
          。
        </p>
        <div className="flex items-center gap-1.5 text-[10px] text-stone-500 mb-3">
          <Search className="w-3 h-3" />
          <span className="truncate">「{query}」</span>
        </div>

        {/* Criteria chips */}
        {chips.length > 0 && (
          <div
            className="rounded-md border px-3 py-2.5 mb-3"
            style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
          >
            <div className="flex items-center gap-2 mb-1.5">
              <Sparkles className="w-3 h-3 text-stone-500" />
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500 font-medium">
                已解析條件
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {chips.map((c) => (
                <div
                  key={c.key}
                  className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-white border"
                  style={{ borderColor: "#E5DDC8" }}
                >
                  <span className="text-[9px] tracking-[0.1em] uppercase text-stone-400">
                    {c.label}
                  </span>
                  <span className="text-[11px] font-medium" style={{ color: "#1C1917" }}>
                    {c.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Compact card with thumbnails + actions */}
        <div
          className="rounded-lg border bg-white overflow-hidden"
          style={{ borderColor: "#E5DDC8" }}
        >
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 p-3">
            {previewSet.map((dm, i) => (
              <button
                key={dm.id}
                onClick={() => onPreview(dm, dms)}
                className="group relative overflow-hidden rounded-md bg-stone-100"
                style={{ aspectRatio: "827 / 1169", animationDelay: `${i * 60}ms` }}
              >
                <DmImage
                  dm={dm}
                  alt={dm.title}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                />
                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent p-2">
                  <div className="text-[10px] text-white/80 mb-0.5 truncate">{dm.source}</div>
                  <div className="text-[11px] text-white font-medium leading-tight line-clamp-1">
                    {dm.title}
                  </div>
                </div>
              </button>
            ))}
          </div>

          {/* Primary action — selective copy via modal */}
          <button
            onClick={() => onSelect && onSelect(dms)}
            className="w-full px-4 py-3 border-t flex items-center justify-between hover:bg-[#FAF7EE] transition-colors group"
            style={{ borderColor: "#E5DDC8", color: "#1C1917" }}
          >
            <div className="flex items-center gap-2">
              <MousePointerClick className="w-3.5 h-3.5" />
              <span className="text-sm font-medium">勾選下載</span>
              <span className="text-[10px] text-stone-500">
                從 {dms.length} 份中挑選任意數量
              </span>
            </div>
            <ArrowRight className="w-3 h-3 text-stone-500 group-hover:text-stone-900 group-hover:translate-x-0.5 transition-all" />
          </button>

          {/* Secondary actions */}
          <div className="border-t flex" style={{ borderColor: "#F0E9D6" }}>
            <button
              onClick={() => onPreview(dms[0], dms)}
              className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors text-stone-600 hover:text-stone-900 border-r"
              style={{ borderColor: "#F0E9D6" }}
            >
              <Maximize2 className="w-3 h-3" />
              <span className="text-[11px]">逐一瀏覽</span>
            </button>
            <button
              onClick={handleCopyAll}
              className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors"
              style={{ color: copiedAll ? "#16A34A" : "#57534E" }}
            >
              {copiedAll ? (
                <>
                  <Check className="w-3 h-3" />
                  <span className="text-[11px] font-medium">
                    已下載 {dms.length} 張
                  </span>
                </>
              ) : (
                <>
                  <CopyPlus className="w-3 h-3" />
                  <span className="text-[11px]">
                    下載圖片包 ({dms.length})
                  </span>
                </>
              )}
            </button>
          </div>
        </div>
        <p className="text-[10px] text-stone-500 leading-relaxed mt-2">
          提示：勾選下載可挑選任意張數·逐一瀏覽支援鍵盤切換與比對模式
        </p>
      </div>
    );
  }

  // ===== STANDARD VIEW — for ≤ 6 results, show full list with per-card details =====
  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-relaxed text-stone-700 mb-1">
            {fallback ? (
              <>
                未找到完全符合條件的 DM，以下為相關推薦
                <span className="font-medium"> {dms.length} 份</span>
              </>
            ) : (
              <>
                為您找到符合條件的
                <span className="font-medium"> {dms.length} 份 DM</span>
              </>
            )}
            。
          </p>
          <div className="flex items-center gap-1.5 text-[10px] text-stone-500">
            <Search className="w-3 h-3" />
            <span className="truncate">「{query}」</span>
          </div>
        </div>
        {dms.length > 1 && !hasSelection && (
          <button
            onClick={handleCopyAll}
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium border transition-all"
            style={{
              borderColor: copiedAll ? "#16A34A" : "#1C1917",
              backgroundColor: copiedAll ? "#16A34A" : "transparent",
              color: copiedAll ? "#F5F1E8" : "#1C1917",
            }}
          >
            {copiedAll ? (
              <>
                <Check className="w-3 h-3" />
                已下載 {dms.length} 張
              </>
            ) : (
              <>
                <CopyPlus className="w-3 h-3" />
                下載圖片包
              </>
            )}
          </button>
        )}
      </div>

      {/* Selection action bar — appears when ≥1 selected, replacing download area */}
      {hasSelection && (
        <div
          className="rounded-md px-3 py-2 mb-3 flex items-center justify-between gap-2 animate-fade-up"
          style={{ backgroundColor: "#1C1917" }}
        >
          <span className="text-[11px] text-white/80 tabular-nums">
            <span className="font-display italic text-base text-white">
              {selected.size}
            </span>
            <span className="text-white/50 ml-1">/ {dms.length}</span>
            <span className="ml-2">已勾選</span>
          </span>
          <div className="flex items-center gap-1.5">
            <button
              onClick={clearSelection}
              className="px-3 py-1 rounded text-[11px] hover:bg-white/10 transition-colors"
              style={{ color: "#F5F1E8" }}
            >
              清除
            </button>
            <button
              onClick={handleCopySelected}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium transition-all"
              style={{
                backgroundColor: copiedSelected ? "#16A34A" : "#F5F1E8",
                color: copiedSelected ? "#F5F1E8" : "#1C1917",
              }}
            >
              {copiedSelected ? (
                <>
                  <Check className="w-3 h-3" />
                  已下載 {selected.size} 張
                </>
              ) : (
                <>
                  <CopyPlus className="w-3 h-3" />
                  下載選取的 {selected.size} 張
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Extracted criteria chips */}
      {chips.length > 0 && !hasSelection && (
        <div
          className="rounded-md border px-3 py-2.5 mb-4"
          style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
        >
          <div className="flex items-center gap-2 mb-1.5">
            <Sparkles className="w-3 h-3 text-stone-500" />
            <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500 font-medium">
              已解析條件
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {chips.map((c) => (
              <div
                key={c.key}
                className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-white border"
                style={{ borderColor: "#E5DDC8" }}
              >
                <span className="text-[9px] tracking-[0.1em] uppercase text-stone-400">
                  {c.label}
                </span>
                <span className="text-[11px] font-medium" style={{ color: "#1C1917" }}>
                  {c.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-2">
        {dms.map((dm, i) => (
          <DMPosterCard
            key={dm.id}
            dm={dm}
            index={i}
            copied={copiedId === dm.id}
            onCopy={() => onCopy(dm)}
            onPreview={() => onPreview(dm, dms)}
            isSelected={selected.has(dm.id)}
            onToggleSelect={() => toggleSelect(dm.id)}
          />
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
          aria-label={isSelected ? "取消選取" : "選取"}
        >
          {isSelected && (
            <Check className="w-3 h-3" style={{ color: "#F5F1E8" }} strokeWidth={3} />
          )}
        </button>

        {/* Thumbnail — always opens preview */}
        <button
          onClick={onPreview}
          className="relative flex-shrink-0 overflow-hidden rounded bg-stone-100 group"
          style={{ width: "60px", aspectRatio: "827 / 1169" }}
          aria-label="放大檢視"
        >
          <DmImage dm={dm} alt={dm.title} className="w-full h-full object-cover" />
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
            <Maximize2 className="w-3.5 h-3.5 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </button>

        {/* Content — clicking row body also toggles selection (excluding thumbnail and copy btn) */}
        <button
          onClick={onToggleSelect}
          className="flex-1 min-w-0 flex flex-col justify-between text-left cursor-pointer"
          aria-label="選取此項"
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
              {dm.region} · {dm.period}
            </div>
          </div>
          <div className="flex items-baseline justify-between gap-2 mt-1.5">
            <span
              className="text-[13px] font-semibold tabular-nums"
              style={{ color: "#B91C1C" }}
            >
              {dm.days > 0 ? `${dm.days}日 · ` : ""}
              {dm.price}
            </span>
          </div>
        </button>

        {/* Per-card quick copy — single-DM shortcut */}
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
              已複製
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              複製
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
/* DAILY SUMMARY — Agent latest data, original summary UI                 */
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
    return (
      <p className="text-sm leading-relaxed text-stone-700">
        沒有找到今日新組合圖片 DM。
      </p>
    );
  }

  return (
    <div>
      <p className="text-sm leading-relaxed text-stone-700 mb-4">
        今日有
        <span className="font-medium"> {todays.length} 份新組合 </span>
        DM 已從 Agent 載入。以下為摘要：
      </p>
      <div
        className="rounded-lg border bg-white overflow-hidden mb-4"
        style={{ borderColor: "#E5DDC8" }}
      >
        <div
          className="px-4 py-3 flex items-center justify-between border-b"
          style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
        >
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-stone-500" />
            <span className="text-xs font-medium">Agent 最新組合</span>
          </div>
          <span className="text-[10px] text-stone-500">真實索引資料</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 p-3">
          {previewSet.map((dm, i) => (
            <button
              key={dm.id}
              onClick={() => onPreview(dm, todays)}
              className="group relative overflow-hidden rounded-md bg-stone-100"
              style={{ aspectRatio: "827 / 1169", animationDelay: `${i * 60}ms` }}
            >
              <DmImage
                dm={dm}
                alt={dm.title}
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
              />
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent p-2">
                <div className="text-[10px] text-white/80 mb-0.5 truncate">{dm.source}</div>
                <div className="text-[11px] text-white font-medium leading-tight line-clamp-1">
                  {dm.title}
                </div>
              </div>
            </button>
          ))}
        </div>
        <button
          onClick={() => onSelect && onSelect(todays)}
          className="w-full px-4 py-3 border-t flex items-center justify-between hover:bg-[#FAF7EE] transition-colors group"
          style={{ borderColor: "#E5DDC8", color: "#1C1917" }}
        >
          <div className="flex items-center gap-2">
            <MousePointerClick className="w-3.5 h-3.5" />
            <span className="text-sm font-medium">勾選下載</span>
            <span className="text-[10px] text-stone-500">
              從 {todays.length} 份中挑選任意數量
            </span>
          </div>
          <ArrowRight className="w-3 h-3 text-stone-500 group-hover:text-stone-900 group-hover:translate-x-0.5 transition-all" />
        </button>
        <div className="border-t flex" style={{ borderColor: "#F0E9D6" }}>
          <button
            onClick={() => onPreview(todays[0], todays)}
            className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors text-stone-600 hover:text-stone-900 border-r"
            style={{ borderColor: "#F0E9D6" }}
          >
            <Maximize2 className="w-3 h-3" />
            <span className="text-[11px]">逐一瀏覽</span>
          </button>
          <button
            onClick={handleCopyAll}
            className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#FAF7EE] transition-colors"
            style={{ color: copiedAll ? "#16A34A" : "#57534E" }}
          >
            {copiedAll ? (
              <>
                <Check className="w-3 h-3" />
                <span className="text-[11px] font-medium">
                  已下載 {todays.length} 張
                </span>
              </>
            ) : (
              <>
                <CopyPlus className="w-3 h-3" />
                <span className="text-[11px]">
                  下載圖片包 ({todays.length})
                </span>
              </>
            )}
          </button>
        </div>
      </div>
      <p className="text-[10px] text-stone-500 leading-relaxed">
        提示：勾選下載可挑選任意張數·逐一瀏覽支援鍵盤切換與比對模式
      </p>
    </div>
  );
}

/* ===================================================================== */
/* SCHEDULE UNAVAILABLE MESSAGE — no local schedule mutation               */
/* ===================================================================== */
function ScheduleUnavailableMessage({ action, requestedTimes }) {
  const times = Array.isArray(requestedTimes) ? requestedTimes : [];
  const actionLabel =
    action === "view"
      ? "????"
      : action === "add"
      ? "????"
      : action === "remove"
      ? "????"
      : "????";

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4" style={{ color: "#D97706" }} />
        <span className="text-sm font-medium">??????????</span>
      </div>
      <div
        className="rounded-lg border bg-white overflow-hidden"
        style={{ borderColor: "#E5DDC8" }}
      >
        <div
          className="px-4 py-3 border-b"
          style={{ borderColor: "#F0E9D6", backgroundColor: "#FAF7EE" }}
        >
          <div className="flex items-center gap-2 mb-1.5">
            <Clock className="w-3 h-3 text-stone-500" />
            <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500 font-medium">
              {actionLabel}
            </span>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {times.length > 0 ? (
              times.map((time) => (
                <span
                  key={time}
                  className="text-xs font-medium tabular-nums px-2.5 py-1 rounded"
                  style={{ backgroundColor: "#F5F1E8", color: "#1C1917" }}
                >
                  {time}
                </span>
              ))
            ) : (
              <span className="text-xs text-stone-500">??????</span>
            )}
          </div>
        </div>
        <div className="px-4 py-3">
          <p className="text-xs text-stone-600 leading-relaxed">
            ???????????????????????????? RPA?
            ?? Agent Web API ???????????????????????????? RPA scheduler ???
          </p>
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
    return (
      <p className="text-sm leading-relaxed text-stone-700">
        沒有找到待處理的重複圖片。
      </p>
    );
  }

  return (
    <div>
      <p className="text-sm leading-relaxed text-stone-700 mb-4">
        系統偵測到
        <span className="font-medium"> {dups.length} 組重複圖片</span>
        ，依「地區 / 期間 / 價格」判定。請選擇保留版本：
      </p>
      <div className="space-y-3">
        {dups.map((d, i) => (
          <div
            key={i}
            className="rounded-lg border bg-white overflow-hidden"
            style={{ borderColor: "#E5DDC8" }}
          >
            <div
              className="px-4 py-3 border-b"
              style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Layers className="w-3.5 h-3.5 text-stone-500" />
                    <span className="text-xs font-medium">{d.key}</span>
                  </div>
                  <div className="text-[10px] text-stone-500">
                    來源：{d.images.map((im) => im.source).join("，")}
                  </div>
                </div>
                <span
                  className="text-[10px] px-2 py-0.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
                >
                  {d.count} 份重複
                </span>
              </div>
            </div>
            {/* Thumbnails preview */}
            <div className="px-4 py-3 flex gap-2 overflow-x-auto">
              {d.images.map((im, j) => (
                <button
                  key={j}
                  onClick={() => onPreview(im.dm, d.images.map((x) => x.dm))}
                  className="flex-shrink-0 relative rounded-md overflow-hidden bg-stone-100 hover:ring-2 hover:ring-stone-900 transition-all"
                  style={{ width: "72px", aspectRatio: "827 / 1169" }}
                >
                  <DmImage dm={im.dm} alt={im.source} className="w-full h-full object-cover" />
                  <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-1.5 py-1">
                    <div className="text-[8px] text-white/90 truncate">{im.source}</div>
                  </div>
                </button>
              ))}
            </div>
            <div
              className="px-4 py-3 flex gap-2 border-t"
              style={{ borderColor: "#F0E9D6" }}
            >
              <button
                onClick={() => onReviewDup?.(d, 0, "keep_one")}
                className="flex-1 px-3 py-1.5 rounded-md text-xs font-medium"
                style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
              >
                保留最新版本
              </button>
              <button
                onClick={() => onReviewDup?.(d, 0, "ignore")}
                className="flex-1 px-3 py-1.5 rounded-md text-xs border hover:border-stone-900 transition-colors"
                style={{ borderColor: "#E5DDC8" }}
              >
                不是重複
              </button>
              <button
                onClick={() => onCompareDup(d)}
                className="flex-1 px-3 py-1.5 rounded-md text-xs border hover:border-stone-900 transition-colors"
                style={{ borderColor: "#E5DDC8" }}
              >
                逐一檢視
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ===================================================================== */
/* MODALS                                                                 */
/* ===================================================================== */
function DMPreviewModal({ initial, list, onClose, onCopy, copiedId }) {
  const dmList = list && list.length > 0 ? list : [initial];
  const initialIdx = Math.max(
    0,
    dmList.findIndex((d) => d.id === initial.id)
  );
  const [compareMode, setCompareMode] = useState(false);
  const [leftIdx, setLeftIdx] = useState(initialIdx);
  const [rightIdx, setRightIdx] = useState(
    dmList.length > 1 ? (initialIdx + 1) % dmList.length : 0
  );
  const stripRef = useRef(null);

  const leftDM = dmList[leftIdx];
  const rightDM = dmList[rightIdx];
  const canNavigate = dmList.length > 1;

  const stepLeft = (delta) =>
    setLeftIdx((i) => (i + delta + dmList.length) % dmList.length);
  const stepRight = (delta) =>
    setRightIdx((i) => (i + delta + dmList.length) % dmList.length);

  // Auto-scroll the active thumbnail into view (centered)
  useEffect(() => {
    if (compareMode) return;
    const strip = stripRef.current;
    if (!strip) return;
    const thumb = strip.querySelector(`[data-idx="${leftIdx}"]`);
    if (thumb && thumb.scrollIntoView) {
      thumb.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
    }
  }, [leftIdx, compareMode]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (compareMode) return;
      if (e.key === "ArrowLeft" && canNavigate) stepLeft(-1);
      if (e.key === "ArrowRight" && canNavigate) stepLeft(1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line
  }, [onClose, compareMode, canNavigate, dmList.length]);

  return (
    <div
      className="fixed inset-0 z-50 animate-backdrop-in overflow-hidden"
      style={{ backgroundColor: "rgba(28,25,23,0.92)" }}
      onClick={onClose}
    >
      {/* Top bar */}
      <div className="absolute top-4 left-4 right-4 flex items-center justify-between text-xs pointer-events-none z-10">
        <div
          className="pointer-events-auto flex items-center gap-2 text-white/70"
          onClick={(e) => e.stopPropagation()}
        >
          {compareMode ? (
            <span
              className="px-2 py-1 rounded-sm font-medium tracking-wider text-[10px] uppercase"
              style={{ backgroundColor: "rgba(255,255,255,0.15)", color: "#F5F1E8" }}
            >
              比對模式 · A vs B
            </span>
          ) : (
            canNavigate && (
              <span className="font-display italic text-base text-white/80 tabular-nums">
                {String(leftIdx + 1).padStart(2, "0")}
                <span className="text-white/40"> / </span>
                {String(dmList.length).padStart(2, "0")}
              </span>
            )
          )}
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          className="pointer-events-auto p-2 rounded-md hover:bg-white/10 transition-colors text-white/80 hover:text-white"
          aria-label="關閉"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {compareMode ? (
        /* ===== COMPARE MODE ===== */
        <div className="absolute inset-0 pt-14 pb-16 px-4 md:px-12 flex items-center justify-center pointer-events-none">
          <div className="animate-modal-in flex flex-col md:flex-row gap-6 w-full h-full max-w-7xl">
            <ComparePanel
              dm={leftDM}
              label="左 · A"
              idx={leftIdx}
              total={dmList.length}
              canNavigate={canNavigate}
              onPrev={() => stepLeft(-1)}
              onNext={() => stepLeft(1)}
              onCopy={() => onCopy(leftDM)}
              copied={copiedId === leftDM.id}
            />
            <ComparePanel
              dm={rightDM}
              label="右 · B"
              idx={rightIdx}
              total={dmList.length}
              canNavigate={canNavigate}
              onPrev={() => stepRight(-1)}
              onNext={() => stepRight(1)}
              onCopy={() => onCopy(rightDM)}
              copied={copiedId === rightDM.id}
            />
          </div>
          <div
            className="absolute bottom-4 left-1/2 -translate-x-1/2 pointer-events-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setCompareMode(false)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs text-white/90 hover:bg-white/10 transition-colors backdrop-blur-md"
              style={{ backgroundColor: "rgba(28,25,23,0.7)" }}
            >
              <X className="w-3 h-3" />
              退出比對模式
            </button>
          </div>
        </div>
      ) : (
        /* ===== SINGLE MODE — fixed-height layout, no internal scroll ===== */
        <div className="absolute inset-0 pt-14 pb-4 px-4 flex flex-col items-center gap-3 pointer-events-none animate-modal-in">
          {/* Image — fills remaining space */}
          <div
            className="pointer-events-auto flex-1 min-h-0 flex items-center justify-center w-full"
            onClick={(e) => e.stopPropagation()}
          >
            <DmImage
              dm={leftDM}
              src={dmPreviewImage(leftDM)}
              alt={leftDM.title}
              className="max-h-full max-w-full object-contain rounded-lg shadow-2xl"
              loading="eager"
            />
          </div>

          {/* Source name (only) */}
          <div
            className="pointer-events-auto px-4 py-1.5 rounded-full flex-shrink-0"
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: "rgba(255,255,255,0.08)" }}
          >
            <div className="flex items-center gap-2 text-xs">
              <span className="text-white/40 text-[10px] tracking-[0.2em] uppercase">
                來源
              </span>
              <span className="text-white/95 font-medium">{leftDM.source}</span>
            </div>
          </div>

          {/* Action toolbar */}
          <div
            className="pointer-events-auto flex items-center gap-2 flex-shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            {canNavigate && (
              <div
                className="flex items-center gap-0.5 px-1 py-1 rounded-full backdrop-blur-md"
                style={{ backgroundColor: "rgba(255,255,255,0.08)" }}
              >
                <button
                  onClick={() => stepLeft(-1)}
                  className="p-1.5 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-colors"
                  aria-label="上一張"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setCompareMode(true)}
                  className="px-3 py-1 rounded-full text-xs text-white/90 hover:bg-white/10 transition-colors flex items-center gap-1.5"
                >
                  <Columns2 className="w-3 h-3" />
                  比對
                </button>
                <button
                  onClick={() => stepLeft(1)}
                  className="p-1.5 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-colors"
                  aria-label="下一張"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            )}
            <button
              onClick={() => onCopy(leftDM)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-medium transition-all"
              style={{
                backgroundColor: copiedId === leftDM.id ? "#16A34A" : "#F5F1E8",
                color: copiedId === leftDM.id ? "#F5F1E8" : "#1C1917",
              }}
            >
              {copiedId === leftDM.id ? (
                <>
                  <Check className="w-3 h-3" />
                  已複製到剪貼簿
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" />
                  複製到剪貼簿
                </>
              )}
            </button>
          </div>

          {/* Thumbnail strip — for browsing many items */}
          {canNavigate && (
            <div
              className="pointer-events-auto w-full max-w-3xl flex justify-center flex-shrink-0"
              onClick={(e) => e.stopPropagation()}
            >
              <div
                ref={stripRef}
                className="flex gap-1.5 overflow-x-auto scrollbar-hide px-4 py-2 rounded-full"
                style={{
                  backgroundColor: "rgba(255,255,255,0.04)",
                  scrollSnapType: "x proximity",
                  maxWidth: "100%",
                }}
              >
                {dmList.map((dm, i) => {
                  const active = i === leftIdx;
                  return (
                    <button
                      key={`${dm.id}-${i}`}
                      data-idx={i}
                      onClick={() => setLeftIdx(i)}
                      className="flex-shrink-0 rounded overflow-hidden transition-all duration-200"
                      style={{
                        width: active ? "44px" : "30px",
                        aspectRatio: "827 / 1169",
                        scrollSnapAlign: "center",
                        opacity: active ? 1 : 0.45,
                        outline: active ? "1.5px solid #F5F1E8" : "none",
                        outlineOffset: "2px",
                      }}
                      aria-label={`第 ${i + 1} 張`}
                    >
                      <DmImage dm={dm} alt="" className="w-full h-full object-cover" />
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ComparePanel({ dm, label, idx, total, canNavigate, onPrev, onNext, onCopy, copied }) {
  return (
    <div
      className="pointer-events-auto flex-1 flex flex-col gap-3 min-w-0 min-h-0"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Top: panel label + position counter */}
      <div className="flex items-center justify-between gap-2 px-1 flex-shrink-0">
        <span className="text-[10px] tracking-[0.2em] uppercase text-white/60 font-medium">
          {label}
        </span>
        {canNavigate && (
          <div
            className="flex items-center gap-0.5 px-1 py-0.5 rounded-full"
            style={{ backgroundColor: "rgba(255,255,255,0.08)" }}
          >
            <button
              onClick={onPrev}
              className="p-1 rounded text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              aria-label="上一張"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <span className="text-[10px] font-display italic text-white/80 tabular-nums px-1.5">
              {String(idx + 1).padStart(2, "0")} / {String(total).padStart(2, "0")}
            </span>
            <button
              onClick={onNext}
              className="p-1 rounded text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              aria-label="下一張"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Image */}
      <div className="flex-1 min-h-0 flex items-center justify-center">
        <DmImage
          dm={dm}
          src={dmPreviewImage(dm)}
          alt={dm.title}
          className="max-h-full max-w-full object-contain rounded shadow-xl"
          loading="eager"
        />
      </div>

      {/* Bottom: source + copy button */}
      <div className="flex items-center justify-between gap-2 flex-shrink-0">
        <div className="flex items-center gap-2 text-xs min-w-0">
          <span className="text-white/40 text-[9px] tracking-[0.2em] uppercase flex-shrink-0">
            來源
          </span>
          <span className="text-white/90 truncate">{dm.source}</span>
        </div>
        <button
          onClick={onCopy}
          className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-medium transition-all"
          style={{
            backgroundColor: copied ? "#16A34A" : "#F5F1E8",
            color: copied ? "#F5F1E8" : "#1C1917",
          }}
        >
          {copied ? (
            <>
              <Check className="w-3 h-3" />
              已複製
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              複製
            </>
          )}
        </button>
      </div>
    </div>
  );
}

/* ===================================================================== */
/* SELECTION MODAL — pick N out of many for selective copy                */
/* ===================================================================== */
function SelectionModal({ list, onClose, onCopy }) {
  const [selected, setSelected] = useState(new Set());
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggle = (id) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(list.map((d) => d.id)));
  const clearAll = () => setSelected(new Set());
  const invert = () =>
    setSelected(new Set(list.filter((d) => !selected.has(d.id)).map((d) => d.id)));

  const handleCopy = async () => {
    if (selected.size === 0) return;
    const selectedDms = list.filter((dm) => selected.has(dm.id));
    const ok = await onCopy(selectedDms);
    if (!ok) return;
    setCopied(true);
    setTimeout(() => {
      setCopied(false);
      onClose();
    }, 1400);
  };

  const count = selected.size;
  const total = list.length;
  const allSelected = count === total;

  return (
    <div
      className="fixed inset-0 z-50 animate-backdrop-in flex items-center justify-center p-4 md:p-8"
      style={{ backgroundColor: "rgba(28,25,23,0.85)" }}
      onClick={onClose}
    >
      <div
        className="animate-modal-in bg-white rounded-lg w-full max-w-5xl flex flex-col overflow-hidden"
        style={{ maxHeight: "90vh" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-5 md:px-6 py-4 border-b flex items-center justify-between gap-4 flex-shrink-0"
          style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}
        >
          <div className="min-w-0">
            <div className="text-[10px] tracking-[0.2em] uppercase text-stone-500 mb-0.5">
              勾選下載
            </div>
            <h2 className="font-serif-tc font-medium text-base md:text-lg leading-tight">
              選擇要下載的 DM
              <span className="text-stone-500 text-xs ml-2 font-normal font-sans">
                共 {total} 份
              </span>
            </h2>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-2 rounded-md hover:bg-stone-200 transition-colors"
            aria-label="關閉"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Selection toolbar */}
        <div
          className="px-5 md:px-6 py-2.5 border-b flex items-center justify-between gap-2 flex-shrink-0"
          style={{ borderColor: "#F0E9D6", backgroundColor: "#FDFBF5" }}
        >
          <div className="flex items-center gap-1.5 text-[11px]">
            <button
              onClick={allSelected ? clearAll : selectAll}
              className="px-2.5 py-1 rounded hover:bg-stone-200 transition-colors flex items-center gap-1.5"
              style={{ color: "#1C1917" }}
            >
              {allSelected ? (
                <>
                  <Square className="w-3 h-3" />
                  全不選
                </>
              ) : (
                <>
                  <CheckSquare className="w-3 h-3" />
                  全選
                </>
              )}
            </button>
            <button
              onClick={invert}
              className="px-2.5 py-1 rounded hover:bg-stone-200 transition-colors text-stone-700"
            >
              反選
            </button>
          </div>
          <div className="text-[11px] text-stone-600 tabular-nums">
            <span className="font-display italic text-base text-stone-900">
              {count}
            </span>
            <span className="text-stone-400"> / {total}</span>
            <span className="ml-2">已勾選</span>
          </div>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-3 md:px-4 py-3 min-h-0">
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-2">
            {list.map((dm) => {
              const isSelected = selected.has(dm.id);
              return (
                <button
                  key={dm.id}
                  onClick={() => toggle(dm.id)}
                  className="relative rounded-md overflow-hidden bg-stone-100 transition-all"
                  style={{
                    aspectRatio: "827 / 1169",
                    outline: isSelected ? "2px solid #2D8BC0" : "1px solid #E5DDC8",
                    outlineOffset: isSelected ? "1px" : "0",
                  }}
                >
                  <DmImage dm={dm} alt={dm.title} className="w-full h-full object-cover" />
                  {/* Dim overlay when not selected (in select mode) */}
                  <div
                    className="absolute inset-0 transition-opacity"
                    style={{
                      backgroundColor: "rgba(0,0,0,0.35)",
                      opacity: isSelected ? 0 : count > 0 ? 0.4 : 0,
                    }}
                  />
                  {/* Checkbox indicator */}
                  <div
                    className="absolute top-1.5 right-1.5 w-5 h-5 rounded flex items-center justify-center transition-all"
                    style={{
                      backgroundColor: isSelected ? "#2D8BC0" : "rgba(255,255,255,0.85)",
                      border: isSelected ? "none" : "1px solid rgba(0,0,0,0.15)",
                    }}
                  >
                    {isSelected && (
                      <Check className="w-3 h-3" style={{ color: "#FFF" }} strokeWidth={3} />
                    )}
                  </div>
                  {/* Source caption — only visible on hover or when selected */}
                  <div
                    className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-1.5 py-1"
                    style={{ opacity: isSelected ? 1 : 0.7 }}
                  >
                    <div className="text-[8px] text-white/90 truncate">
                      {dm.source}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div
          className="px-5 md:px-6 py-3 border-t flex items-center justify-between gap-3 flex-shrink-0"
          style={{ borderColor: "#E5DDC8" }}
        >
          <div className="text-[10px] text-stone-500 hidden sm:block">
            下載圖片包後，解壓縮並全選圖片拖進 LINE 群組。
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-md text-xs border hover:border-stone-900 transition-colors"
              style={{ borderColor: "#E5DDC8" }}
            >
              取消
            </button>
            <button
              onClick={handleCopy}
              disabled={count === 0}
              className="flex items-center gap-1.5 px-4 py-2 rounded-md text-xs font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                backgroundColor: copied ? "#16A34A" : count > 0 ? "#1C1917" : "#A8A29E",
                color: "#F5F1E8",
              }}
            >
              {copied ? (
                <>
                  <Check className="w-3 h-3" />
                  已下載 {count} 張
                </>
              ) : (
                <>
                  <CopyPlus className="w-3 h-3" />
                  下載選取的 {count} 張
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ===================================================================== */
/* DUPLICATE COMPARE MODAL                                                */
/* ===================================================================== */
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
              逐一檢視 · 重複圖片比對
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
            以下為來自 <span className="font-medium">{data.count}</span> 個社群的重複圖片，
            判定依據：地區、期間、價格皆相同。請選擇保留版本，其餘將被歸檔。
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
                      來源
                    </div>
                    <div className="text-sm font-medium mb-2 truncate">{im.source}</div>
                    <div className="flex items-center gap-1.5 text-[10px] text-stone-500">
                      <Clock className="w-3 h-3" />
                      下載於 今日 {im.time}
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
            將保留：
            <span className="font-medium ml-1">{data.images[keepIdx].source}</span>
            <span className="text-stone-400 ml-2">
              其餘 {data.images.length - 1} 份歸檔
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-md text-xs border hover:border-stone-900 transition-colors"
              style={{ borderColor: "#E5DDC8" }}
            >
              取消
            </button>
            <button
              onClick={() => onReview?.(data, keepIdx, "ignore")}
              className="px-4 py-2 rounded-md text-xs border hover:border-stone-900 transition-colors"
              style={{ borderColor: "#E5DDC8" }}
            >
              不是重複
            </button>
            <button
              onClick={() => onReview?.(data, keepIdx, "keep_one")}
              className="px-4 py-2 rounded-md text-xs font-medium"
              style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
            >
              確認保留
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

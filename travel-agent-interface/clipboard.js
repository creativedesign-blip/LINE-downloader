const toAbsoluteUrl = (url) => {
  if (!url) return "";
  try {
    return new URL(url, window.location.origin).href;
  } catch {
    return url;
  }
};

export const dmFullImage = (dm) => dm?.fullImage || dm?.image || "";
export const dmPreviewImage = (dm) => dm?.previewImage || dmFullImage(dm);
const INTERNAL_WEB = import.meta.env.VITE_INTERNAL_WEB === "1";


// The /api/openclaw/clipboard endpoint pipes files into the SERVER process's
// Windows clipboard via PowerShell. For a remote browser (e.g. via Cloudflare
// tunnel) that clipboard is on the server machine, not on the user's machine,
// so the bridge silently "succeeds" while the user's clipboard stays empty.
// Restrict the bridge to either an explicit internal-web build flag or to
// loopback / link-local hosts where browser and server are the same machine.
const isLocalClipboardBridgeAvailable = () => {
  if (typeof window === "undefined") return false;
  if (INTERNAL_WEB) return true;
  return /^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/i.test(window.location.host);
};

const mediaIdsForItems = (items) =>
  items
    .map((dm) => dm?.mediaId || dm?.raw?.media_id)
    .filter(Boolean);

export const mediaIdForPath = (value) => {
  const raw = String(value || "");
  if (!raw) return "";
  try {
    const bytes = new TextEncoder().encode(raw);
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  } catch {
    return "";
  }
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const directDownloadName = (dm, index) => {
  const rawPath = dm?.raw?.branded_path || dm?.raw?.image_path || dmFullImage(dm) || "";
  const name = String(rawPath).split(/[\\/]/).pop()?.split("?")[0];
  return name || `travel-dm-${String(index + 1).padStart(2, "0")}.jpg`;
};

export async function downloadDmImagesDirectly(items) {
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

export async function downloadDmImagesPackage(items) {
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

export function explainClipboardError(error) {
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
    ctx.fillStyle = "#F9F9F9";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    let top = padding;
    for (let index = 0; index < scaled.length; index += 1) {
      const image = scaled[index];
      const left = Math.round((canvasWidth - image.width) / 2);
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(left - 1, top - 1, image.width + 2, image.height + 2);
      ctx.drawImage(image.bitmap, left, top, image.width, image.height);
      ctx.strokeStyle = "#B8D9CE";
      ctx.lineWidth = 2;
      ctx.strokeRect(left - 1, top - 1, image.width + 2, image.height + 2);
      if (index < scaled.length - 1) {
        const separatorTop = top + image.height + Math.round(gap / 2);
        ctx.fillStyle = "#B8D9CE";
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

export async function copyDmToClipboard(dm) {
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

export async function copyDmListToClipboard(items) {
  const hasImages = items.some((dm) => dmPreviewImage(dm) || dmFullImage(dm));
  if (hasImages) {
    await downloadDmImagesPackage(items);
    return "download";
  }

  await copyTextToClipboard(formatDmListForClipboard(items));
  return "text";
}

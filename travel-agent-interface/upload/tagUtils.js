export const SYSTEM_TAGS_CLEARED_SENTINEL = "__openclaw_system_tags_cleared__";

export function stepLabel(status) {
  if (status === "success") return "完成";
  if (status === "running") return "處理中";
  if (status === "failed") return "失敗";
  if (status === "skipped") return "略過";
  if (status === "pending") return "等待中";
  return "尚未開始";
}

export function sourceLabel(source) {
  if (source === "line-auto") return "LINE 自動抓取";
  if (source === "upload") return "手動上傳";
  return source || "未知來源";
}

export const UPLOAD_LIMITS = {
  formats: ["JPG", "JPEG", "PNG", "WEBP"],
  extensions: [".jpg", ".jpeg", ".png", ".webp"],
  maxFileBytes: 15 * 1024 * 1024,
  maxTotalBytes: 200 * 1024 * 1024,
  maxFiles: 50,
};

export function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(value >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (value >= 1024) return `${Math.round(value / 1024)} KB`;
  return `${value} B`;
}

export function uploadLimitText() {
  return `支援 ${UPLOAD_LIMITS.formats.join(" / ")}，單檔 ${formatBytes(UPLOAD_LIMITS.maxFileBytes)}，最多 ${UPLOAD_LIMITS.maxFiles} 張 / ${formatBytes(UPLOAD_LIMITS.maxTotalBytes)}`;
}

export function validateUploadFiles(files) {
  const list = Array.from(files || []);
  if (list.length === 0) return "請選擇圖片";
  if (list.length > UPLOAD_LIMITS.maxFiles) return `一次最多 ${UPLOAD_LIMITS.maxFiles} 張`;
  const total = list.reduce((sum, file) => sum + Number(file.size || 0), 0);
  if (total > UPLOAD_LIMITS.maxTotalBytes) return `總容量不可超過 ${formatBytes(UPLOAD_LIMITS.maxTotalBytes)}`;
  const invalid = list.find((file) => {
    const lower = String(file.name || "").toLowerCase();
    return !UPLOAD_LIMITS.extensions.some((ext) => lower.endsWith(ext));
  });
  if (invalid) return `${invalid.name} 格式不支援`;
  const oversized = list.find((file) => Number(file.size || 0) > UPLOAD_LIMITS.maxFileBytes);
  if (oversized) return `${oversized.name} 超過 ${formatBytes(UPLOAD_LIMITS.maxFileBytes)}`;
  return "";
}

export function folderProgress(folder) {
  const total = Number(folder?.image_count || 0);
  const done = Math.max(Number(folder?.composed_count || 0), Number(folder?.ocr_count || 0), folder?.status === "success" ? total : 0);
  return { done: Math.min(done, total), total };
}

export function folderStatusLabel(folder) {
  if (folder?.status === "success") return "完成";
  if (folder?.status === "failed") return "失敗";
  if (folder?.status === "running") return "處理中";
  return stepLabel(folder?.current_step ? folder?.step_statuses?.[folder.current_step] : "");
}


export function imageFlowStatus(image, folder) {
  if (image?.flow_label) return image.flow_label;
  const currentStep = folder?.current_step || "";
  const folderStatus = folder?.status || "";
  const hasOcr = image?.ocr_status === "success" || (image.system_tags || []).length > 0 || (image.ocr_tags_override || []).length > 0;
  const hasComposed = image?.compose_status === "success" || Boolean(image?.branded_thumbnail_url || image?.branded_url);

  if (hasComposed || folderStatus === "success") return "執行完成";
  if (hasOcr || currentStep === "compose" || image?.compose_status === "running") return "組合中";
  return "辨識中";
}

export function tagValues(tags) {
  const values = Array.isArray(tags) ? tags.map((tag) => tag?.tag || tag).filter(Boolean) : [];
  return [...new Set(values.map((tag) => String(tag).trim()).filter(Boolean))];
}

export function imageTagValues(image) {
  const rawOverrideTags = Array.isArray(image?.ocr_tags_override) ? image.ocr_tags_override.filter(Boolean) : [];
  const overrideTags = rawOverrideTags.filter((tag) => tag !== SYSTEM_TAGS_CLEARED_SENTINEL);
  if (rawOverrideTags.includes(SYSTEM_TAGS_CLEARED_SENTINEL)) return overrideTags;
  if (overrideTags.length) return overrideTags;
  return Array.isArray(image?.system_tags) ? image.system_tags.map((tag) => tag?.tag || tag).filter(Boolean) : [];
}

import { useEffect, useState } from "react";
import { ArrowDownToLine, Copy, Loader2, X } from "lucide-react";
import {
  copyDmToClipboard,
  downloadDmImagesDirectly,
  explainClipboardError,
  mediaIdForPath,
} from "../clipboard.js";
import TagBadgeList from "./TagBadgeList.jsx";
import {
  SYSTEM_TAGS_CLEARED_SENTINEL,
  imageFlowStatus,
  imageTagValues,
  tagValues,
} from "./tagUtils.js";

export default function CleanImageDetailDrawer({ image, onClose, onAddTag, onDeleteTag, onUpdateImage, onArchiveImage }) {
  const initialDisplayName = image.display_name || image.original_filename || "";
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [ocrTags, setOcrTags] = useState(imageTagValues(image));
  const [referenceText, setReferenceText] = useState(image.reference_text || "");
  const [tagDraft, setTagDraft] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const [copyError, setCopyError] = useState("");
  const flow = imageFlowStatus(image);
  const composedPath = image.branded_path || "";
  const composedImageUrl = image.branded_url || image.branded_thumbnail_url || "";
  const hasComposedImage = Boolean(composedImageUrl);
  const composedDm = {
    id: `upload-${image.id}`,
    mediaId: mediaIdForPath(composedPath),
    fullImage: composedImageUrl,
    image: image.branded_thumbnail_url || composedImageUrl,
    previewImage: image.branded_thumbnail_url || composedImageUrl,
    title: displayName || image.display_name || image.original_filename || "圖片",
    region: "圖片上傳",
    period: flow,
    price: "",
    source: image.original_filename || "圖片上傳",
    raw: {
      branded_path: image.branded_path,
      image_path: image.branded_path,
    },
  };

  useEffect(() => {
    setDisplayName(image.display_name || image.original_filename || "");
    setOcrTags(imageTagValues(image));
    setReferenceText(image.reference_text || "");
    setTagDraft("");
    setCopyStatus("");
    setCopyError("");
  }, [image.id]);

  const parsedOverrideTags = () => {
    const values = tagValues(ocrTags);
    const sourceTagCount = imageTagValues({ ...image, ocr_tags_override: [] }).length;
    if (!values.length && sourceTagCount > 0) return [SYSTEM_TAGS_CLEARED_SENTINEL];
    return values;
  };

  const removeOcrOverrideTag = (tagToRemove) => {
    setOcrTags((current) => current.filter((tag) => tag !== tagToRemove));
  };

  const addManualTag = () => {
    const value = tagDraft.trim();
    if (!value) return;
    onAddTag(image.id, value);
    setTagDraft("");
  };

  const saveMetadata = async () => {
    await onUpdateImage(image.id, {
      display_name: displayName,
      ocr_tags_override: parsedOverrideTags(),
      reference_text: referenceText,
    });
  };

  const archive = async () => {
    if (!window.confirm("確定要刪除這張圖片嗎？此操作無法復原。")) return;
    await onArchiveImage(image.id);
    onClose();
  };

  const copyComposedImage = async () => {
    if (!hasComposedImage) {
      setCopyStatus("error");
      setCopyError("組圖尚未完成，完成後才能複製到 LINE。");
      return;
    }
    if (!composedPath) {
      setCopyStatus("error");
      setCopyError("找不到組圖檔案路徑，剪貼簿橋接無法讀取本機檔案。");
      return;
    }
    setCopyStatus("copying");
    setCopyError("");
    try {
      await copyDmToClipboard(composedDm);
      setCopyStatus("copied");
      window.setTimeout(() => setCopyStatus(""), 2000);
    } catch (error) {
      console.error("Copy composed image failed.", error);
      setCopyStatus("error");
      setCopyError(explainClipboardError(error));
    }
  };

  const downloadComposedImage = async () => {
    if (!hasComposedImage) {
      window.alert("組圖尚未完成，完成後才能下載。");
      return;
    }
    try {
      await downloadDmImagesDirectly([composedDm]);
    } catch (error) {
      console.error("Download composed image failed.", error);
      window.alert(error.message || "下載圖片失敗");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.35)" }}>
      <div className="w-full max-w-3xl h-full bg-white shadow-xl overflow-y-auto animate-slide-in">
        <div className="sticky top-0 z-10 px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{image.display_name || image.original_filename}</div>
            <div className="text-xs text-stone-500 mt-0.5">{flow}</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#EFE9D8]" aria-label="關閉">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 grid lg:grid-cols-[320px_1fr] gap-5">
          <div>
            <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-1">組圖結果</div>
            {hasComposedImage ? (
              <a href={composedImageUrl} target="_blank" rel="noreferrer" className="block rounded-md border overflow-hidden bg-stone-100" style={{ borderColor: "#E5DDC8", aspectRatio: "827 / 1169" }}>
                <img src={composedImageUrl} alt={`${image.original_filename} composed`} className="w-full h-full object-contain" />
              </a>
            ) : (
              <div className="rounded-md border px-3 py-8 text-center text-xs text-stone-500" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
                組圖尚未完成
              </div>
            )}
            {composedImageUrl && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={copyComposedImage}
                  className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border px-3 text-xs"
                  style={{ borderColor: "#E5DDC8", color: "#292524" }}
                >
                  {copyStatus === "copying" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Copy className="w-3.5 h-3.5" />}
                  {copyStatus === "copied" ? "已複製" : copyStatus === "error" ? "複製失敗" : "複製圖片"}
                </button>
                <button
                  type="button"
                  onClick={downloadComposedImage}
                  className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border px-3 text-xs"
                  style={{ borderColor: "#E5DDC8", color: "#292524" }}
                >
                  <ArrowDownToLine className="w-3.5 h-3.5" />
                  下載圖片
                </button>
              </div>
            )}
            {!hasComposedImage && (
              <div className="mt-2 rounded-md border px-3 py-2 text-xs text-stone-600" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
                組圖完成後才可複製或下載。
              </div>
            )}
            {copyError && (
              <div className="mt-2 whitespace-pre-wrap rounded-md border px-3 py-2 text-xs text-red-700" style={{ borderColor: "#FECACA", backgroundColor: "#FEF2F2" }}>
                {copyError}
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

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">圖片貼標（系統）</span>
              <div className="mt-2 rounded-md border px-3 py-2" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
                <TagBadgeList tags={ocrTags} tone="system" emptyText="尚無圖片貼標" onRemove={removeOcrOverrideTag} />
              </div>
            </label>

            <div>
              <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500 mb-2">人工標籤</div>
              <div className="space-y-3">
                <div className="rounded-md border px-3 py-2" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>
                  <TagBadgeList
                    tags={image.manual_tags || []}
                    tone="manual"
                    emptyText="尚無人工標籤"
                    onRemove={(tag) => {
                      const matched = (image.manual_tags || []).find((item) => item.tag === tag);
                      if (matched) onDeleteTag(matched.id);
                    }}
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    value={tagDraft}
                    onChange={(event) => setTagDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        addManualTag();
                      }
                    }}
                    className="min-w-0 flex-1 h-9 rounded-md border px-3 text-sm outline-none"
                    style={{ borderColor: "#E5DDC8" }}
                    placeholder="輸入人工標籤後按 Enter 新增"
                  />
                  <button
                    type="button"
                    onClick={addManualTag}
                    className="h-9 rounded-md px-3 text-xs"
                    style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}
                  >
                    新增
                  </button>
                </div>
              </div>
            </div>

            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">來源文案 Note</span>
              <textarea
                value={referenceText}
                onChange={(event) => setReferenceText(event.target.value)}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none resize-none"
                style={{ borderColor: "#E5DDC8" }}
                rows={4}
                placeholder="[提供給 LINE 文案備註使用]"
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

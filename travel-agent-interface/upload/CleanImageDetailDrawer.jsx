import { useEffect, useState } from "react";
import { ArrowDownToLine, Copy, Loader2, X } from "lucide-react";
import {
  copyDmToClipboard,
  downloadDmImagesDirectly,
  explainClipboardError,
  mediaIdForPath,
} from "../clipboard.js";
import ImageMetadataPanel from "./ImageMetadataPanel.jsx";
import { imageFlowStatus } from "./tagUtils.js";

export default function CleanImageDetailDrawer({
  image,
  onClose,
  onAddTag,
  onDeleteTag,
  onUpdateImage,
  onArchiveImage,
  onSaved,
}) {
  const imageTitle = image.display_name || image.original_filename || "圖片";
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
    title: imageTitle,
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
    setCopyStatus("");
    setCopyError("");
  }, [image.id]);

  const archive = async () => {
    if (!window.confirm("確定要刪除這張圖片？刪除後不會出現在查詢結果。")) return;
    await onArchiveImage(image.id);
    onClose();
  };

  const copyComposedImage = async () => {
    if (!hasComposedImage) {
      setCopyStatus("error");
      setCopyError("組圖尚未完成，無法複製到 LINE。");
      return;
    }
    if (!composedPath) {
      setCopyStatus("error");
      setCopyError("找不到組圖檔案路徑，請重新處理圖片。");
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
      window.alert("組圖尚未完成，無法下載。");
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
    <div className="fixed inset-0 z-50 flex justify-end animate-backdrop-in" style={{ backgroundColor: "rgba(17,24,39,0.48)" }}>
      <style>{`
        @keyframes upload-drawer-slide-in {
          from { opacity: 0; transform: translateX(32px); }
          to { opacity: 1; transform: translateX(0); }
        }
        .animate-upload-drawer-in { animation: upload-drawer-slide-in 0.24s ease-out; }
      `}</style>
      <div className="h-full w-full max-w-3xl overflow-y-auto bg-white shadow-xl animate-upload-drawer-in">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b px-5 py-4" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{imageTitle}</div>
            <div className="mt-0.5 text-xs text-stone-500">{flow}</div>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1.5 hover:bg-[#D4EFE5]" aria-label="關閉">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid gap-5 p-5 lg:grid-cols-[320px_1fr]">
          <div>
            <div className="mb-1 text-[10px] tracking-[0.15em] uppercase text-stone-500">組圖預覽</div>
            {hasComposedImage ? (
              <a href={composedImageUrl} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-md border bg-stone-100" style={{ borderColor: "#E1F5EE", aspectRatio: "827 / 1169" }}>
                <img src={composedImageUrl} alt={`${image.original_filename} composed`} className="h-full w-full object-contain" />
              </a>
            ) : (
              <div className="rounded-md border px-3 py-8 text-center text-xs text-stone-500" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
                組圖尚未完成
              </div>
            )}
            {composedImageUrl && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={copyComposedImage}
                  className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border px-3 text-xs"
                  style={{ borderColor: "#E1F5EE", color: "#292524" }}
                >
                  {copyStatus === "copying" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Copy className="h-3.5 w-3.5" />}
                  {copyStatus === "copied" ? "已複製" : copyStatus === "error" ? "複製失敗" : "複製圖片"}
                </button>
                <button
                  type="button"
                  onClick={downloadComposedImage}
                  className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border px-3 text-xs"
                  style={{ borderColor: "#E1F5EE", color: "#292524" }}
                >
                  <ArrowDownToLine className="h-3.5 w-3.5" />
                  下載圖片
                </button>
              </div>
            )}
            {!hasComposedImage && (
              <div className="mt-2 rounded-md border px-3 py-2 text-xs text-stone-600" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
                組圖完成後才能複製或下載。
              </div>
            )}
            {copyError && (
              <div className="mt-2 whitespace-pre-wrap rounded-md border px-3 py-2 text-xs text-red-700" style={{ borderColor: "#FECACA", backgroundColor: "#FEF2F2" }}>
                {copyError}
              </div>
            )}
          </div>

          <div className="space-y-4">
            <ImageMetadataPanel
              image={{ ...image, source_kind: image.source || "upload" }}
              mode="edit"
              onAddTag={onAddTag}
              onDeleteTag={onDeleteTag}
              onUpdateImage={onUpdateImage}
              onSaved={onSaved}
            />
            <div className="flex justify-start pt-2">
              <button type="button" onClick={archive} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#B91C1C", color: "#991B1B" }}>
                刪除圖片
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

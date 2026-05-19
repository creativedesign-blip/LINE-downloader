import { useEffect, useState } from "react";
import { ChevronLeft, FolderOpen, FolderPlus, Loader2, Upload, X } from "lucide-react";
import CleanImageDetailDrawer from "./CleanImageDetailDrawer.jsx";
import TagBadgeList from "./TagBadgeList.jsx";
import {
  folderProgress,
  folderStatusLabel,
  formatBytes,
  imageFlowStatus,
  imageTagValues,
  sourceLabel,
  uploadLimitText,
  validateUploadFiles,
} from "./tagUtils.js";

export default function UploadWorkspace({ folders, detail, uploading, error, onUpload, onUploadExisting, onSelectFolder, onRefresh, onAddTag, onDeleteTag, onUpdateTag, onUpdateImage, onArchiveImage, onToast }) {
  const [uploadStage, setUploadStage] = useState(null);
  const [uploadTarget, setUploadTarget] = useState(null);
  const [view, setView] = useState("list");
  const [recentFolderId, setRecentFolderId] = useState(null);
  const selectedId = detail?.folder?.id;
  const openFolder = async (folder) => { await onSelectFolder(folder); setView("detail"); };
  const handleCreated = async (payload) => {
    const folderId = payload?.folder?.id;
    setRecentFolderId(folderId || null);
    setUploadStage(null);
    setUploadTarget(null);
    if (folderId) await onSelectFolder({ id: folderId });
    setView("detail");
    onToast?.({ type: "success", message: "圖片已上傳，開始執行 OCR / 組圖。" });
  };
  const submitUploadFiles = async ({ files }) => {
    try {
      const payload = uploadTarget?.mode === "existing" ? await onUploadExisting({ folderId: uploadTarget.folderId, files }) : await onUpload({ displayName: uploadTarget.displayName, note: uploadTarget.note, files });
      await handleCreated(payload);
      return payload;
    } catch (error) {
      onToast?.({ type: "error", message: error.message || "圖片上傳失敗" });
      throw error;
    }
  };
  useEffect(() => {
    if (view !== "detail" || !detail?.folder?.id) return undefined;
    const progress = folderProgress(detail.folder);
    const shouldPoll = detail.folder.status === "running" || detail.folder.status === "pending" || progress.done < progress.total;
    if (!shouldPoll) return undefined;
    const timer = window.setInterval(() => onRefresh(), 4000);
    return () => window.clearInterval(timer);
  }, [view, detail?.folder?.id, detail?.folder?.status, detail?.folder?.updated_at, onRefresh]);
  return (
    <section className="space-y-4">
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        <div className="px-5 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4" style={{ backgroundColor: "#FAF7EE" }}>
          <div><div className="flex items-center gap-2 text-sm font-medium"><FolderPlus className="w-4 h-4 text-stone-600" />上傳圖片</div><div className="text-xs text-stone-500 mt-1">{uploadLimitText()}。上傳後會自動執行 OCR / 組圖，並可在資料夾列表追蹤進度。</div></div>
          <button type="button" onClick={() => setUploadStage("target")} className="rounded-md px-4 py-2 text-xs font-medium flex items-center justify-center gap-1.5 flex-shrink-0" style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}><Upload className="w-3.5 h-3.5" />新增或選擇資料夾</button>
        </div>
      </div>
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
        {view === "detail" && detail?.folder ? <UploadFolderDetail detail={detail} onBack={() => setView("list")} onAddTag={onAddTag} onDeleteTag={onDeleteTag} onUpdateTag={onUpdateTag} onUpdateImage={onUpdateImage} onArchiveImage={onArchiveImage} /> : (
          <div>
            <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#F0E9D6", backgroundColor: "#FAF7EE" }}><div><div className="text-sm font-medium">資料夾結果列表</div><div className="text-xs text-stone-500 mt-0.5">查看每個批次的流程狀態、總覽進度與最後更新時間。</div></div><button type="button" onClick={onRefresh} className="text-xs text-stone-500 hover:text-stone-900">重新整理</button></div>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead style={{ backgroundColor: "#FDFBF5", color: "#78716C" }}><tr><th className="px-4 py-2 font-medium text-left">資料夾名稱</th><th className="px-4 py-2 font-medium text-left">狀態</th><th className="px-4 py-2 font-medium text-left">總覽進度</th><th className="px-4 py-2 font-medium text-left">最後更新</th><th className="px-4 py-2 font-medium text-left">操作</th></tr></thead><tbody>
              {(folders || []).map((folder) => { const progress = folderProgress(folder); const active = selectedId === folder.id || recentFolderId === folder.id; return <tr key={folder.id} onClick={() => openFolder(folder)} className="cursor-pointer hover:bg-[#FAF7EE] transition-colors" style={{ borderTop: "1px solid #F0E9D6", backgroundColor: active ? "#FFFBEB" : "#FFF" }}><td className="px-4 py-3 min-w-64 text-left"><div className="flex items-center gap-2 font-medium text-stone-900"><FolderOpen className="w-3.5 h-3.5 text-stone-500 flex-shrink-0" /><span className="truncate">{folder.display_name}</span></div><div className="text-[10px] text-stone-500 mt-0.5 truncate">{sourceLabel(folder.source)} · {folder.folder_slug}</div></td><td className="px-4 py-3 whitespace-nowrap text-left"><span className="rounded px-2 py-1 text-[10px]" style={{ backgroundColor: "#F0E9D6", color: "#1C1917" }}>{folderStatusLabel(folder)}</span></td><td className="px-4 py-3 whitespace-nowrap tabular-nums text-left">{progress.done}/{progress.total}</td><td className="px-4 py-3 whitespace-nowrap text-stone-500 text-left">{new Date(folder.updated_at || folder.created_at).toLocaleString("zh-TW")}</td><td className="px-4 py-3 text-left"><button type="button" className="text-xs text-stone-700 hover:text-stone-950">查看</button></td></tr>; })}
              {(!folders || folders.length === 0) && <tr><td colSpan={5} className="px-5 py-8 text-center text-stone-500">尚未建立圖片資料夾</td></tr>}
            </tbody></table></div>
          </div>
        )}
      </div>
      {uploadStage === "target" && <UploadTargetModal folders={folders} onClose={() => setUploadStage(null)} onNext={(target) => { setUploadTarget(target); setUploadStage("files"); }} />}
      {uploadStage === "files" && uploadTarget && <UploadFilesModal target={uploadTarget} uploading={uploading} error={error} onBack={() => setUploadStage("target")} onClose={() => setUploadStage(null)} onSubmit={submitUploadFiles} />}
    </section>
  );
}

function UploadTargetModal({ folders, onClose, onNext }) {
  const [targetMode, setTargetMode] = useState("new");
  const [selectedFolderId, setSelectedFolderId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [localError, setLocalError] = useState("");
  const selectedFolder = (folders || []).find((folder) => String(folder.id) === String(selectedFolderId));
  const next = () => {
    if (targetMode === "new" && !displayName.trim()) return setLocalError("請輸入資料夾名稱");
    if (targetMode === "existing" && !selectedFolderId) return setLocalError("請選擇既有資料夾");
    setLocalError("");
    onNext(targetMode === "existing" ? { mode: "existing", folderId: selectedFolderId, folder: selectedFolder, label: selectedFolder?.display_name || "既有資料夾" } : { mode: "new", displayName: displayName.trim(), note: "", label: displayName.trim() });
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6 animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.45)" }}><div className="w-full max-w-xl rounded-lg border bg-white shadow-xl animate-modal-in overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
      <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}><div><div className="text-sm font-medium">選擇上傳目的地</div><div className="text-xs text-stone-500 mt-0.5">先決定要建立新資料夾，或追加到既有資料夾。</div></div><button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#EFE9D8]" aria-label="關閉"><X className="w-4 h-4" /></button></div>
      <div className="px-5 py-5 space-y-4"><div className="grid grid-cols-1 gap-2 sm:grid-cols-2"><button type="button" onClick={() => { setTargetMode("new"); setLocalError(""); }} className="rounded-md border px-3 py-3 text-sm font-medium text-left" style={{ borderColor: targetMode === "new" ? "#1C1917" : "#E5DDC8", backgroundColor: targetMode === "new" ? "#1C1917" : "#FFF", color: targetMode === "new" ? "#F5F1E8" : "#1C1917" }}>建立新資料夾</button><button type="button" onClick={() => { setTargetMode("existing"); setLocalError(""); }} className="rounded-md border px-3 py-3 text-sm font-medium text-left" style={{ borderColor: targetMode === "existing" ? "#1C1917" : "#E5DDC8", backgroundColor: targetMode === "existing" ? "#1C1917" : "#FFF", color: targetMode === "existing" ? "#F5F1E8" : "#1C1917" }}>選擇既有資料夾</button></div>
        {targetMode === "new" ? <label className="block"><span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">資料夾名稱</span><input value={displayName} onChange={(event) => { setDisplayName(event.target.value); setLocalError(""); }} className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none" style={{ borderColor: "#E5DDC8" }} placeholder="例如 韓國促銷05/20" autoFocus /></label> : <label className="block"><span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">既有資料夾</span><select value={selectedFolderId} onChange={(event) => { setSelectedFolderId(event.target.value); setLocalError(""); }} className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none bg-white" style={{ borderColor: "#E5DDC8" }}><option value="">請選擇資料夾</option>{(folders || []).map((folder) => <option key={folder.id} value={folder.id}>{folder.display_name} · {new Date(folder.updated_at || folder.created_at).toLocaleString("zh-TW")}</option>)}</select>{(!folders || folders.length === 0) && <div className="mt-2 text-xs text-stone-500">目前沒有可選擇的資料夾，請先建立新資料夾。</div>}</label>}
        {localError && <div className="text-xs text-red-700">{localError}</div>}
      </div>
      <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}><button type="button" onClick={onClose} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#E5DDC8" }}>取消</button><button type="button" onClick={next} className="rounded-md px-3 py-2 text-xs font-medium" style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}>下一步：選擇圖片</button></div>
    </div></div>
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
    if (message) return setLocalError(message);
    setLocalError("");
    try { await onSubmit({ files }); } catch (submitError) { setLocalError(submitError.message || "圖片上傳失敗"); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6 animate-backdrop-in" style={{ backgroundColor: "rgba(28,25,23,0.45)" }}><div className="w-full max-w-xl rounded-lg border bg-white shadow-xl animate-modal-in overflow-hidden" style={{ borderColor: "#E5DDC8" }}>
      <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}><div><div className="text-sm font-medium">選擇圖片</div><div className="text-xs text-stone-500 mt-0.5">上傳到：{target?.label || "未命名資料夾"}</div></div><button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#EFE9D8]" aria-label="關閉"><X className="w-4 h-4" /></button></div>
      <div className="px-5 py-5 space-y-4"><div className="rounded-md border p-3 text-xs text-stone-600" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>上傳後會自動執行 OCR / 組圖 / 索引，流程狀態會顯示在資料夾詳細列表。</div><label className="block"><span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">圖片選擇器</span><input type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" multiple onChange={(event) => { setFiles(event.target.files); setLocalError(validateUploadFiles(event.target.files)); }} className="mt-1 block w-full text-xs" /></label><div className="rounded-md border p-3 text-xs text-stone-600" style={{ borderColor: "#E5DDC8", backgroundColor: "#FDFBF5" }}>已選擇 {fileList.length} 張，總容量 {formatBytes(totalBytes)}</div>{fileList.length > 0 && <div className="max-h-44 overflow-y-auto scrollbar-thin rounded-md border" style={{ borderColor: "#F0E9D6" }}>{fileList.map((file) => <div key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-3 px-3 py-2 text-xs" style={{ borderTop: "1px solid #F0E9D6" }}><span className="truncate">{file.name}</span><span className="text-stone-500 flex-shrink-0">{formatBytes(file.size)}</span></div>)}</div>}{(localError || fileMessage || error) && <div className="text-xs text-red-700">{localError || fileMessage || error}</div>}</div>
      <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E5DDC8", backgroundColor: "#FAF7EE" }}><button type="button" onClick={onBack} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#E5DDC8" }}>上一步</button><button type="button" onClick={submit} disabled={!canSubmit} className="rounded-md px-3 py-2 text-xs font-medium flex items-center gap-1.5 disabled:opacity-50" style={{ backgroundColor: "#1C1917", color: "#F5F1E8" }}>{uploading && <Loader2 className="w-3 h-3 animate-spin" />}上傳並開始處理</button></div>
    </div></div>
  );
}

function UploadFolderDetail({ detail, onBack, onAddTag, onDeleteTag, onUpdateTag, onUpdateImage, onArchiveImage }) {
  const [selectedImage, setSelectedImage] = useState(null);
  const [quickTag, setQuickTag] = useState(null);
  const folder = detail.folder;
  const images = Array.isArray(detail.images) ? detail.images : [];
  const currentSelectedImage = images.find((image) => image.id === selectedImage?.id) || selectedImage;

  const startQuickTag = (event, image, type) => {
    event.stopPropagation();
    setQuickTag({ imageId: image.id, type, value: "" });
  };

  const saveQuickTag = async (image) => {
    const value = String(quickTag?.value || "").trim();
    if (!value) {
      setQuickTag(null);
      return;
    }
    if (quickTag.type === "system") {
      const nextTags = [...new Set([...imageTagValues(image), value])];
      await onUpdateImage(image.id, { ocr_tags_override: nextTags });
    } else {
      await onAddTag(image.id, value);
    }
    setQuickTag(null);
  };

  const renderQuickTagInput = (image, type) => {
    if (quickTag?.imageId !== image.id || quickTag?.type !== type) return null;
    return (
      <input
        autoFocus
        value={quickTag.value}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => setQuickTag((current) => ({ ...(current || {}), value: event.target.value }))}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            saveQuickTag(image);
          }
          if (event.key === "Escape") {
            event.preventDefault();
            setQuickTag(null);
          }
        }}
        onBlur={() => setQuickTag(null)}
        className="mt-1 w-full rounded border px-2 py-1 text-xs outline-none"
        style={{ borderColor: "#E5DDC8" }}
        placeholder={type === "system" ? "輸入圖片貼標後按 Enter 新增" : "輸入人工標籤後按 Enter 新增"}
      />
    );
  };

  return (
    <div className="p-4">
      <button type="button" onClick={onBack} className="mb-3 flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-900"><ChevronLeft className="w-3.5 h-3.5" />回到資料夾列表</button>
      <div className="mb-4"><div className="text-sm font-medium">{folder.display_name}</div><div className="text-[10px] text-stone-500 mt-0.5">{folder.folder_slug}</div>{folder.note && <div className="text-xs text-stone-600 mt-1">{folder.note}</div>}{Array.isArray(folder.line_groups) && folder.line_groups.length > 0 && <div className="text-[10px] text-stone-500 mt-1">LINE 群組：{folder.line_groups.join("、")}</div>}</div>
      <div className="overflow-x-auto rounded-md border" style={{ borderColor: "#E5DDC8" }}>
        <table className="w-full text-left text-xs">
          <thead style={{ backgroundColor: "#FDFBF5", color: "#78716C" }}>
            <tr>
              <th className="px-3 py-2 font-medium text-left">縮圖</th>
              <th className="px-3 py-2 font-medium text-left">圖片</th>
              <th className="px-3 py-2 font-medium text-left">上傳時間</th>
              <th className="px-3 py-2 font-medium text-left">流程狀態</th>
              <th className="px-3 py-2 font-medium text-left">圖片貼標</th>
              <th className="px-3 py-2 font-medium text-left">人工標籤</th>
              <th className="px-3 py-2 font-medium text-left">來源文案</th>
              <th className="px-3 py-2 font-medium text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            {images.map((image) => {
              const flow = imageFlowStatus(image, folder);
              const ocrTags = imageTagValues(image);
              return (
                <tr key={image.id} className="hover:bg-[#FAF7EE] cursor-pointer" onClick={() => setSelectedImage(image)} style={{ borderTop: "1px solid #F0E9D6" }}>
                  <td className="px-3 py-2 text-left"><div className="w-14 bg-stone-100 rounded overflow-hidden" style={{ aspectRatio: "827 / 1169" }}>{image.thumbnail_url ? <img src={image.thumbnail_url} alt={image.original_filename} className="w-full h-full object-cover" /> : <div className="w-full h-full flex items-center justify-center text-[10px] text-stone-500">無圖</div>}</div></td>
                  <td className="px-3 py-2 min-w-48 text-left"><div className="font-medium text-stone-900 truncate">{image.display_name || image.original_filename}</div>{image.display_name && <div className="text-[10px] text-stone-500 truncate">{image.original_filename}</div>}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-stone-500 text-left">{new Date(image.uploaded_at).toLocaleString("zh-TW")}</td>
                  <td className="px-3 py-2 min-w-24 font-medium text-left">{flow}</td>
                  <td className="px-3 py-2 min-w-44 text-stone-700 text-left" onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => startQuickTag(event, image, "system")} title="雙擊新增圖片貼標"><TagBadgeList tags={ocrTags} tone="system" />{renderQuickTagInput(image, "system")}</td>
                  <td className="px-3 py-2 min-w-44 text-stone-700 text-left" onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => startQuickTag(event, image, "manual")} title="雙擊新增人工標籤"><TagBadgeList tags={image.manual_tags} tone="manual" />{renderQuickTagInput(image, "manual")}</td>
                  <td className="px-3 py-2 min-w-48 text-stone-600 truncate max-w-64 text-left">{image.reference_text || "-"}</td>
                  <td className="px-3 py-2 text-left whitespace-nowrap"><button type="button" onClick={(event) => { event.stopPropagation(); setSelectedImage(image); }} className="text-xs text-stone-700 hover:text-stone-950">查看 / 編輯</button></td>
                </tr>
              );
            })}
            {images.length === 0 && <tr><td colSpan={8} className="px-5 py-8 text-center text-stone-500">這個資料夾尚無圖片</td></tr>}
          </tbody>
        </table>
      </div>
      {currentSelectedImage && <CleanImageDetailDrawer image={currentSelectedImage} onClose={() => setSelectedImage(null)} onAddTag={onAddTag} onDeleteTag={onDeleteTag} onUpdateTag={onUpdateTag} onUpdateImage={onUpdateImage} onArchiveImage={onArchiveImage} />}
    </div>
  );
}

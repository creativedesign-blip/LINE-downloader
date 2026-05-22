import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, Download, FolderOpen, FolderPlus, Loader2, MoreHorizontal, Trash2, Upload, X } from "lucide-react";
import CleanImageDetailDrawer from "./CleanImageDetailDrawer.jsx";
import TagBadgeList from "./TagBadgeList.jsx";
import {
  SYSTEM_TAGS_CLEARED_SENTINEL,
  folderProgress,
  folderStatusLabel,
  formatBytes,
  imageFlowStatus,
  imageTagValues,
  uploadImageSizeText,
  uploadLimitText,
  validateUploadImageDimensions,
  validateUploadFiles,
} from "./tagUtils.js";

const COMPLETED_FLOW_LABEL = "執行完成";
const TAIPEI_UTC_OFFSET = "+08:00";

function taipeiDateToUtcIso(date, endOfDay = false) {
  if (!date) return "";
  const time = endOfDay ? "23:59:59" : "00:00:00";
  return new Date(`${date}T${time}${TAIPEI_UTC_OFFSET}`).toISOString().replace(".000Z", "Z");
}

function dateRangeToUploadFilters(range) {
  return {
    uploadedFrom: taipeiDateToUtcIso(range?.from),
    uploadedTo: taipeiDateToUtcIso(range?.to, true),
  };
}

function imageMatchesUploadDateRange(image, range) {
  const uploadedAt = Date.parse(image?.uploaded_at || "");
  if (!Number.isFinite(uploadedAt)) return false;
  const from = range?.from ? Date.parse(taipeiDateToUtcIso(range.from)) : null;
  const to = range?.to ? Date.parse(taipeiDateToUtcIso(range.to, true)) : null;
  if (from !== null && uploadedAt < from) return false;
  if (to !== null && uploadedAt > to) return false;
  return true;
}

export default function UploadWorkspace({
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
  onArchiveFolder,
  onDownloadFolder,
  onToast,
}) {
  const [uploadStage, setUploadStage] = useState(null);
  const [uploadTarget, setUploadTarget] = useState(null);
  const [view, setView] = useState("list");
  const [recentFolderId, setRecentFolderId] = useState(null);
  const selectedId = detail?.folder?.id;

  const openFolder = async (folder) => {
    await onSelectFolder(folder, {});
    setView("detail");
  };

  const handleCreated = async (payload) => {
    const folderId = payload?.folder?.id;
    setRecentFolderId(folderId || null);
    setUploadStage(null);
    setUploadTarget(null);
    if (folderId) await onSelectFolder({ id: folderId }, {});
    setView("detail");
    onToast?.({ type: "success", message: "上傳成功，已開始 OCR / 組圖流程。" });
  };

  const submitUploadFiles = async ({ files }) => {
    try {
      const payload =
        uploadTarget?.mode === "existing"
          ? await onUploadExisting({ folderId: uploadTarget.folderId, files })
          : await onUpload({ displayName: uploadTarget.displayName, note: "", files });
      await handleCreated(payload);
      return payload;
    } catch (uploadError) {
      onToast?.({ type: "error", message: uploadError.message || "上傳失敗" });
      throw uploadError;
    }
  };

  useEffect(() => {
    if (view !== "detail" || !detail?.folder?.id) return undefined;
    const progress = folderProgress(detail.folder);
    const shouldPoll =
      detail.folder.status === "running" ||
      detail.folder.status === "pending" ||
      progress.done < progress.total;
    if (!shouldPoll) return undefined;
    const timer = window.setInterval(() => {
      onSelectFolder(detail.folder, {}).catch(() => {});
    }, 4000);
    return () => window.clearInterval(timer);
  }, [view, detail?.folder?.id, detail?.folder?.status, detail?.folder?.updated_at, onSelectFolder]);

  return (
    <section className="space-y-4">
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
        <div className="px-5 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4" style={{ backgroundColor: "#E1F5EE" }}>
          <div>
            <div className="flex items-center gap-2 text-sm font-medium">
              <FolderPlus className="w-4 h-4 text-stone-600" />
              上傳圖片
            </div>
            <div className="text-xs text-stone-500 mt-1">
              {uploadLimitText()}。上傳後會自動執行 OCR / 組圖，完成後可下載組圖結果。
            </div>
          </div>
          <button
            type="button"
            onClick={() => setUploadStage("target")}
            className="rounded-md px-4 py-2 text-xs font-medium flex items-center justify-center gap-1.5 flex-shrink-0"
            style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
          >
            <Upload className="w-3.5 h-3.5" />
            新增或選擇資料夾
          </button>
        </div>
      </div>

      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
        {view === "detail" && detail?.folder ? (
          <UploadFolderDetail
            detail={detail}
            onBack={() => setView("list")}
            onAddTag={onAddTag}
            onDeleteTag={onDeleteTag}
            onUpdateTag={onUpdateTag}
            onUpdateImage={onUpdateImage}
            onArchiveImage={onArchiveImage}
            onArchiveFolder={onArchiveFolder}
            onDownloadFolder={onDownloadFolder}
            onToast={onToast}
          />
        ) : (
          <FolderList
            folders={folders}
            selectedId={selectedId}
            recentFolderId={recentFolderId}
            onOpen={openFolder}
            onRefresh={onRefresh}
            onArchiveFolder={onArchiveFolder}
            onToast={onToast}
          />
        )}
      </div>

      {uploadStage === "target" && (
        <UploadTargetModal
          folders={folders}
          initialFolder={view === "detail" ? detail?.folder : null}
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

function FolderList({ folders, selectedId, recentFolderId, onOpen, onRefresh, onArchiveFolder, onToast }) {
  const [openMenuId, setOpenMenuId] = useState(null);

  const archiveFolder = (event, folder, canArchive) => {
    event.stopPropagation();
    setOpenMenuId(null);
    if (!canArchive) {
      onToast?.({ type: "error", message: "資料夾仍在處理中，完成或失敗後才能移至封存。" });
      return;
    }
    if (window.confirm("此操作會將整個資料夾移至封存，30 天內不會出現在列表、查詢或下載。確定移至封存？")) {
      onArchiveFolder?.(folder.id);
    }
  };

  return (
    <div>
      <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
        <div>
          <div className="text-sm font-medium">資料夾結果列表</div>
          <div className="text-xs text-stone-500 mt-0.5">查看每個批次的流程狀態、總覽進度與最後更新時間。</div>
        </div>
        <button type="button" onClick={onRefresh} className="text-xs text-stone-500 hover:text-stone-900">
          重新整理
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead style={{ backgroundColor: "#FFFFFF", color: "#78716C" }}>
            <tr>
              <th className="px-4 py-2 font-medium text-left">資料夾名稱</th>
              <th className="px-4 py-2 font-medium text-left">狀態</th>
              <th className="px-4 py-2 font-medium text-left">總覽進度</th>
              <th className="px-4 py-2 font-medium text-left">最後更新時間</th>
              <th className="px-4 py-2 font-medium text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            {(folders || []).map((folder) => {
              const progress = folderProgress(folder);
              const active = selectedId === folder.id || recentFolderId === folder.id;
              const canArchive = Number(folder.image_count || 0) === 0 || ["success", "failed"].includes(folder.status);
              return (
                <tr
                  key={folder.id}
                  onClick={() => onOpen(folder)}
                  className="cursor-pointer hover:bg-[#E1F5EE] transition-colors"
                  style={{ borderTop: "1px solid #E1F5EE", backgroundColor: active ? "#F0FDF7" : "#FFF" }}
                >
                  <td className="px-4 py-3 min-w-64 text-left">
                    <div className="flex items-center gap-2 font-medium text-stone-900">
                      <FolderOpen className="w-3.5 h-3.5 text-stone-500 flex-shrink-0" />
                      <span className="truncate">{folder.display_name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-left">
                    <span className="rounded px-2 py-1 text-[10px]" style={{ backgroundColor: "#E1F5EE", color: "#0F6E56" }}>
                      {folderStatusLabel(folder)}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap tabular-nums text-left">{progress.done}/{progress.total}</td>
                  <td className="px-4 py-3 whitespace-nowrap text-stone-500 text-left">{new Date(folder.updated_at || folder.created_at).toLocaleString("zh-TW")}</td>
                  <td className="px-4 py-3 text-left">
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={(event) => { event.stopPropagation(); onOpen(folder); }} className="text-xs text-stone-700 hover:text-stone-950">
                        查看
                      </button>
                      <div className="relative" onClick={(event) => event.stopPropagation()}>
                        <button
                          type="button"
                          onClick={() => setOpenMenuId((current) => (current === folder.id ? null : folder.id))}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md border text-stone-600 hover:text-stone-950"
                          style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}
                          aria-label="更多資料夾操作"
                        >
                          <MoreHorizontal className="w-4 h-4" />
                        </button>
                        {openMenuId === folder.id && (
                          <div className="absolute right-0 z-20 mt-2 w-44 overflow-hidden rounded-md border bg-white py-1 shadow-lg" style={{ borderColor: "#E1F5EE" }}>
                            <button
                              type="button"
                              disabled={!canArchive}
                              onClick={(event) => archiveFolder(event, folder, canArchive)}
                              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-stone-400 disabled:hover:bg-white"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                              移至封存資料夾
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
              );
            })}
            {(!folders || folders.length === 0) && (
              <tr>
                <td colSpan={5} className="px-5 py-8 text-center text-stone-500">尚未建立圖片資料夾</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UploadTargetModal({ folders, initialFolder, onClose, onNext }) {
  const [targetMode, setTargetMode] = useState(initialFolder?.id ? "existing" : "new");
  const [selectedFolderId, setSelectedFolderId] = useState(initialFolder?.id ? String(initialFolder.id) : "");
  const [displayName, setDisplayName] = useState("");
  const [localError, setLocalError] = useState("");
  const folderOptions = useMemo(() => {
    const list = Array.isArray(folders) ? folders : [];
    if (!initialFolder?.id || list.some((folder) => String(folder.id) === String(initialFolder.id))) return list;
    return [initialFolder, ...list];
  }, [folders, initialFolder]);
  const selectedFolder = folderOptions.find((folder) => String(folder.id) === String(selectedFolderId));
  const duplicateMatches = useMemo(() => {
    const needle = displayName.trim();
    if (!needle) return [];
    return folderOptions
      .filter((folder) => (folder.display_name || "").trim() === needle && !folder.archived_at)
      .sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
  }, [displayName, folderOptions]);
  const mergeIntoExisting = (folder) => {
    setTargetMode("existing");
    setSelectedFolderId(String(folder.id));
    setLocalError("");
  };

  const next = () => {
    if (targetMode === "new" && !displayName.trim()) return setLocalError("請輸入資料夾名稱");
    if (targetMode === "existing" && !selectedFolderId) return setLocalError("請選擇既有資料夾");
    setLocalError("");
    onNext(
      targetMode === "existing"
        ? { mode: "existing", folderId: selectedFolderId, folder: selectedFolder, label: selectedFolder?.display_name || "既有資料夾" }
        : { mode: "new", displayName: displayName.trim(), note: "", label: displayName.trim() },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6 animate-backdrop-in" style={{ backgroundColor: "rgba(17,24,39,0.56)" }}>
      <div className="w-full max-w-xl rounded-lg border bg-white shadow-xl animate-modal-in overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
        <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <div>
            <div className="text-sm font-medium">選擇上傳目的地</div>
            <div className="text-xs text-stone-500 mt-0.5">建立新資料夾，或把圖片追加到既有批次。</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#D4EFE5]" aria-label="關閉">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-5 py-5 space-y-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => { setTargetMode("new"); setLocalError(""); }}
              className="rounded-md border px-3 py-3 text-sm font-medium text-left"
              style={{ borderColor: targetMode === "new" ? "#0F6E56" : "#E1F5EE", backgroundColor: targetMode === "new" ? "#0F6E56" : "#FFF", color: targetMode === "new" ? "#F9F9F9" : "#0F6E56" }}
            >
              新增資料夾
            </button>
            <button
              type="button"
              onClick={() => { setTargetMode("existing"); setLocalError(""); }}
              className="rounded-md border px-3 py-3 text-sm font-medium text-left"
              style={{ borderColor: targetMode === "existing" ? "#0F6E56" : "#E1F5EE", backgroundColor: targetMode === "existing" ? "#0F6E56" : "#FFF", color: targetMode === "existing" ? "#F9F9F9" : "#0F6E56" }}
            >
              選擇舊資料夾
            </button>
          </div>
          {targetMode === "new" ? (
            <div className="space-y-2">
              <label className="block">
                <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">資料夾名稱</span>
                <input
                  value={displayName}
                  onChange={(event) => { setDisplayName(event.target.value); setLocalError(""); }}
                  className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: duplicateMatches.length > 0 ? "#DC2626" : "#E1F5EE" }}
                  placeholder="韓國促銷05/20"
                  autoFocus
                />
              </label>
              {duplicateMatches.length > 0 && (
                <div className="rounded-md border px-3 py-2.5 text-xs" style={{ borderColor: "#DC2626", backgroundColor: "#FEE2E2", color: "#991B1B" }}>
                  <div className="font-medium mb-1.5">
                    已有 {duplicateMatches.length} 個同名「{displayName.trim()}」資料夾,請選擇併入或改名
                  </div>
                  <div className="space-y-1 mb-2">
                    {duplicateMatches.slice(0, 3).map((folder) => (
                      <div key={folder.id} className="flex items-center justify-between gap-2">
                        <span className="truncate">
                          #{folder.id} · {folder.image_count || 0} 張 · {new Date(folder.updated_at || folder.created_at).toLocaleString("zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                        </span>
                        <button
                          type="button"
                          onClick={() => mergeIntoExisting(folder)}
                          className="shrink-0 rounded px-2 py-0.5 text-[11px] font-medium"
                          style={{ backgroundColor: "#991B1B", color: "#FEE2E2" }}
                        >
                          併入此資料夾
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <label className="block">
              <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">既有資料夾</span>
              <select
                value={selectedFolderId}
                onChange={(event) => { setSelectedFolderId(event.target.value); setLocalError(""); }}
                className="mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none bg-white"
                style={{ borderColor: "#E1F5EE" }}
              >
                <option value="">請選擇資料夾</option>
                {folderOptions.map((folder) => (
                  <option key={folder.id} value={folder.id}>{folder.display_name} / {new Date(folder.updated_at || folder.created_at).toLocaleString("zh-TW")}</option>
                ))}
              </select>
              {folderOptions.length === 0 && <div className="mt-2 text-xs text-stone-500">目前沒有可追加的資料夾。</div>}
            </label>
          )}
          {localError && <div className="text-xs text-red-700">{localError}</div>}
        </div>
        <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <button type="button" onClick={onClose} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#E1F5EE" }}>取消</button>
          <button
            type="button"
            onClick={next}
            disabled={targetMode === "new" && duplicateMatches.length > 0}
            className="rounded-md px-3 py-2 text-xs font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
            title={targetMode === "new" && duplicateMatches.length > 0 ? "請先選擇併入既有資料夾或改用其他名稱" : ""}
          >
            下一步：選擇圖片
          </button>
        </div>
      </div>
    </div>
  );
}

function uploadFileKey(file, index = 0) {
  // Prefix with index so two genuinely-distinct files with the same
  // name+size+lastModified (Save-As preserves mtime, duplicate copies in
  // different folders) don't collide on React keys / dimension cache.
  return `${index}-${file?.name || ""}-${file?.size || 0}-${file?.lastModified || 0}`;
}

const UPLOAD_DIMENSION_TIMEOUT_MS = 10000;

function readUploadImageDimensions(file, signal) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      // Detach listeners and clear src so the browser aborts any in-flight
      // decode; revoke the URL so the blob slot is freed even if the user
      // changed files before this one finished.
      image.onload = null;
      image.onerror = null;
      image.src = "";
      URL.revokeObjectURL(url);
      if (timer) clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
      resolve(result);
    };
    const onAbort = () => finish({ error: "尺寸檢查已取消" });
    image.onload = () => {
      const width = image.naturalWidth || image.width || 0;
      const height = image.naturalHeight || image.height || 0;
      if (width === 0 || height === 0) {
        finish({ error: "圖片尺寸無法判讀" });
        return;
      }
      finish({ width, height });
    };
    image.onerror = () => finish({ error: "圖片無法讀取或格式損壞" });
    const timer = setTimeout(
      () => finish({ error: `圖片尺寸檢查逾時（${UPLOAD_DIMENSION_TIMEOUT_MS / 1000}s）` }),
      UPLOAD_DIMENSION_TIMEOUT_MS,
    );
    if (signal) {
      if (signal.aborted) {
        finish({ error: "尺寸檢查已取消" });
        return;
      }
      signal.addEventListener("abort", onAbort);
    }
    image.src = url;
  });
}

function UploadFilesModal({ target, uploading, error, onBack, onClose, onSubmit }) {
  const [files, setFiles] = useState(null);
  const [fileDimensions, setFileDimensions] = useState({});
  const [checkingDimensions, setCheckingDimensions] = useState(false);
  const [localError, setLocalError] = useState("");
  const fileList = Array.from(files || []);
  const totalBytes = fileList.reduce((sum, file) => sum + Number(file.size || 0), 0);
  const fileMessage = files ? validateUploadFiles(files) : "";
  const dimensionIssues = fileList
    .map((file, index) => ({ file, result: fileDimensions[uploadFileKey(file, index)] }))
    .filter((item) => item.result?.error || item.result?.message);
  const dimensionMessage = dimensionIssues[0]
    ? `${dimensionIssues[0].file.name}: ${dimensionIssues[0].result.error || dimensionIssues[0].result.message}`
    : "";
  const canSubmit = fileList.length > 0 && !fileMessage && !dimensionMessage && !checkingDimensions && !uploading;

  useEffect(() => {
    const currentFiles = Array.from(files || []);
    // AbortController lets the cleanup actually stop in-flight Image decodes
    // and revoke their object URLs; the old `let cancelled` flag only blocked
    // setState but kept bitmaps alive in memory until the browser GC'd them.
    const controller = new AbortController();
    if (currentFiles.length === 0 || validateUploadFiles(files)) {
      // Don't clear prior dimensions — if the user trims an over-limit
      // selection back to valid, the per-file checks we already did for the
      // files that didn't change are still meaningful.
      setCheckingDimensions(false);
      return () => controller.abort();
    }
    setFileDimensions({});
    setCheckingDimensions(true);
    Promise.all(
      currentFiles.map(async (file, index) => {
        const key = uploadFileKey(file, index);
        const dimensions = await readUploadImageDimensions(file, controller.signal);
        if (dimensions.error) return [key, dimensions];
        const message = validateUploadImageDimensions(dimensions.width, dimensions.height);
        return [key, { ...dimensions, message }];
      })
    ).then((entries) => {
      if (controller.signal.aborted) return;
      setFileDimensions(Object.fromEntries(entries));
      setCheckingDimensions(false);
    });
    return () => controller.abort();
  }, [files]);

  const submit = async () => {
    const message = validateUploadFiles(files);
    if (message) return setLocalError(message);
    if (checkingDimensions) return setLocalError("正在檢查圖片尺寸，請稍候。");
    if (dimensionMessage) return setLocalError(dimensionMessage);
    setLocalError("");
    try {
      await onSubmit({ files });
    } catch (submitError) {
      setLocalError(submitError.message || "上傳失敗");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4 py-6 animate-backdrop-in" style={{ backgroundColor: "rgba(17,24,39,0.56)" }}>
      <div className="w-full max-w-xl rounded-lg border bg-white shadow-xl animate-modal-in overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
        <div className="px-5 py-4 border-b flex items-center justify-between gap-3" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <div>
            <div className="text-sm font-medium">選擇圖片</div>
            <div className="text-xs text-stone-500 mt-0.5">上傳到：{target?.label || "圖片資料夾"}</div>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-[#D4EFE5]" aria-label="關閉">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-5 py-5 space-y-4">
          <div className="rounded-md border p-3 text-xs text-stone-600" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
            上傳後會依序執行 OCR / 組圖 / 索引，列表會顯示每張圖的目前進度。
          </div>
          <label className="block">
            <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">圖片檔案</span>
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
          <div className="rounded-md border p-3 text-xs text-stone-600" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
            已選 {fileList.length} 張，總大小 {formatBytes(totalBytes)}
          </div>
          {fileList.length > 0 && (
            <div className="max-h-44 overflow-y-auto scrollbar-thin rounded-md border" style={{ borderColor: "#E1F5EE" }}>
              {fileList.map((file, index) => {
                const fileKey = uploadFileKey(file, index);
                const result = fileDimensions[fileKey];
                const issue = result?.error || result?.message || "";
                const dimensions = result?.width && result?.height ? `${result.width}x${result.height}px` : checkingDimensions ? "檢查中" : "";
                return (
                  <div key={fileKey} className="px-3 py-2 text-xs" style={{ borderTop: "1px solid #E1F5EE" }}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate">{file.name}</span>
                      <span className="text-stone-500 flex-shrink-0">{[dimensions, formatBytes(file.size)].filter(Boolean).join(" · ")}</span>
                    </div>
                    {issue && <div className="mt-1 text-[11px] text-red-700">{issue}</div>}
                  </div>
                );
              })}
            </div>
          )}
          {checkingDimensions && <div className="text-xs text-stone-500">正在檢查圖片尺寸，最低需求：{uploadImageSizeText()}。</div>}
          {(localError || fileMessage || dimensionMessage || error) && <div className="text-xs text-red-700">{localError || fileMessage || dimensionMessage || error}</div>}
        </div>
        <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <button type="button" onClick={onBack} className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "#E1F5EE" }}>上一步</button>
          <button type="button" onClick={submit} disabled={!canSubmit} className="rounded-md px-3 py-2 text-xs font-medium flex items-center gap-1.5 disabled:opacity-50" style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}>
            {uploading && <Loader2 className="w-3 h-3 animate-spin" />}
            上傳並開始處理
          </button>
        </div>
      </div>
    </div>
  );
}

function UploadFolderDetail({
  detail,
  onBack,
  onAddTag,
  onDeleteTag,
  onUpdateTag,
  onUpdateImage,
  onArchiveImage,
  onArchiveFolder,
  onDownloadFolder,
  onToast,
}) {
  const [selectedImage, setSelectedImage] = useState(null);
  const [quickTag, setQuickTag] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [draftDateRange, setDraftDateRange] = useState({ from: "", to: "" });
  const [folderMenuOpen, setFolderMenuOpen] = useState(false);
  const folder = detail.folder;
  const allImages = Array.isArray(detail.images) ? detail.images : [];
  const invalidDateRange = Boolean(draftDateRange.from && draftDateRange.to && draftDateRange.from > draftDateRange.to);
  const images = useMemo(
    () => {
      if (invalidDateRange) return [];
      if (!draftDateRange.from && !draftDateRange.to) return allImages;
      return allImages.filter((image) => imageMatchesUploadDateRange(image, draftDateRange));
    },
    [allImages, draftDateRange.from, draftDateRange.to, invalidDateRange],
  );
  const currentSelectedImage = images.find((image) => image.id === selectedImage?.id) || selectedImage;
  const currentUploadFilters = useMemo(() => dateRangeToUploadFilters(draftDateRange), [draftDateRange.from, draftDateRange.to]);
  const downloadableIds = useMemo(
    () => images.filter((image) => imageFlowStatus(image, folder) === COMPLETED_FLOW_LABEL && image.branded_path).map((image) => image.id),
    [images, folder],
  );
  const selectedDownloadableIds = selectedIds.filter((id) => downloadableIds.includes(id));
  const allDownloadableSelected = downloadableIds.length > 0 && selectedDownloadableIds.length === downloadableIds.length;

  useEffect(() => {
    setSelectedIds([]);
  }, [draftDateRange.from, draftDateRange.to, folder.id]);

  useEffect(() => {
    if (!selectedImage) return;
    if (!images.some((image) => image.id === selectedImage.id)) {
      setSelectedImage(null);
    }
  }, [images, selectedImage]);

  const startQuickTag = (event, image, type) => {
    event.stopPropagation();
    if (type !== "manual") return;
    setQuickTag({ imageId: image.id, type, value: "" });
  };

  const saveQuickTag = async (image) => {
    const value = String(quickTag?.value || "").trim();
    if (!value) {
      setQuickTag(null);
      return;
    }
    await onAddTag(image.id, value);
    setQuickTag(null);
  };

  const removeSystemTag = async (image, tagToRemove) => {
    const ok = window.confirm("刪除後此圖片貼標不會再參與搜尋，且無法復原。確定刪除？");
    if (!ok) return;
    const currentTags = imageTagValues(image);
    const nextTags = currentTags.filter((tag) => tag !== tagToRemove);
    const sourceTagCount = imageTagValues({ ...image, ocr_tags_override: [] }).length;
    await onUpdateImage(image.id, {
      ocr_tags_override: !nextTags.length && sourceTagCount > 0 ? [SYSTEM_TAGS_CLEARED_SENTINEL] : nextTags,
    });
  };

  const toggleImage = (image) => {
    if (!downloadableIds.includes(image.id)) return;
    setSelectedIds((current) => current.includes(image.id) ? current.filter((id) => id !== image.id) : [...current, image.id]);
  };

  const downloadSelection = async () => {
    const imageIds = selectedDownloadableIds.length ? selectedDownloadableIds : downloadableIds;
    if (!imageIds.length) {
      onToast?.({ type: "error", message: "沒有已完成的組圖可下載。" });
      return;
    }
    await onDownloadFolder?.(folder.id, { ...currentUploadFilters, imageIds });
    onToast?.({ type: "success", message: `已開始下載 ${imageIds.length} 張組圖。` });
  };

  const archiveCurrentFolder = async () => {
    setFolderMenuOpen(false);
    const canArchive = Number(folder.image_count || 0) === 0 || ["success", "failed"].includes(folder.status);
    if (!canArchive) {
      onToast?.({ type: "error", message: "資料夾仍在處理中，完成或失敗後才能移至封存。" });
      return;
    }
    if (!window.confirm("此操作會將整個資料夾移至封存，30 天內不會出現在列表、查詢或下載。確定移至封存？")) return;
    await onArchiveFolder?.(folder.id);
    onBack();
    onToast?.({ type: "success", message: "資料夾已移至封存，30 天後永久清理。" });
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
        style={{ borderColor: "#E1F5EE" }}
        placeholder="輸入人工標籤，按 Enter 新增"
      />
    );
  };

  return (
    <div className="p-4">
      <button type="button" onClick={onBack} className="mb-3 flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-900">
        <ChevronLeft className="w-3.5 h-3.5" />
        返回資料夾列表
      </button>

      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex min-h-8 items-center gap-2">
            <div className="flex min-h-8 items-center text-base font-semibold leading-6 text-stone-950">{folder.display_name}</div>
            <div className="relative flex-shrink-0">
              <button
                type="button"
                onClick={() => setFolderMenuOpen((current) => !current)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-stone-500 hover:bg-stone-100 hover:text-stone-950"
                aria-label="更多資料夾操作"
              >
                <MoreHorizontal className="w-4 h-4" />
              </button>
              {folderMenuOpen && (
                <div className="absolute left-0 z-20 mt-2 w-44 overflow-hidden rounded-md border bg-white py-1 shadow-lg" style={{ borderColor: "#E1F5EE" }}>
                  <button
                    type="button"
                    onClick={archiveCurrentFolder}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-700 hover:bg-red-50"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    封存資料夾
                  </button>
                </div>
              )}
            </div>
          </div>
          {Array.isArray(folder.line_groups) && folder.line_groups.length > 0 && (
            <div className="text-[10px] text-stone-500 mt-1">LINE 群組：{folder.line_groups.join("、")}</div>
          )}
        </div>
        <div className="flex w-full flex-col gap-2 xl:w-auto xl:items-end">
          <div className="hidden">
            <button
              type="button"
              onClick={downloadSelection}
              disabled={!downloadableIds.length}
              className="rounded-md px-3 py-2 text-xs font-medium inline-flex items-center gap-1.5 disabled:opacity-50"
              style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
            >
              <Download className="w-3.5 h-3.5" />
              下載圖片
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={() => setFolderMenuOpen((current) => !current)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border text-stone-600 hover:text-stone-950"
                style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}
                aria-label="更多資料夾操作"
              >
                <MoreHorizontal className="w-4 h-4" />
              </button>
              {folderMenuOpen && (
                <div className="absolute right-0 z-20 mt-2 w-44 overflow-hidden rounded-md border bg-white py-1 shadow-lg" style={{ borderColor: "#E1F5EE" }}>
                  <button
                    type="button"
                    onClick={archiveCurrentFolder}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-700 hover:bg-red-50"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    封存資料夾
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="w-full bg-white xl:w-auto">
            <div className="grid gap-2 sm:grid-cols-[minmax(0,160px)_minmax(0,160px)_auto_auto] sm:items-end">
              <label className="block text-[10px] font-medium text-stone-500">
                上傳起日
                <input
                  type="date"
                  value={draftDateRange.from}
                  onChange={(event) => setDraftDateRange((current) => ({ ...current, from: event.target.value }))}
                  className="mt-1 block h-8 w-full rounded-md border px-2 text-xs text-stone-900 outline-none focus:ring-2"
                  style={{ borderColor: "#E1F5EE", "--tw-ring-color": "#E1F5EE" }}
                />
              </label>
              <label className="block text-[10px] font-medium text-stone-500">
                上傳迄日
                <input
                  type="date"
                  value={draftDateRange.to}
                  onChange={(event) => setDraftDateRange((current) => ({ ...current, to: event.target.value }))}
                  className="mt-1 block h-8 w-full rounded-md border px-2 text-xs text-stone-900 outline-none focus:ring-2"
                  style={{ borderColor: "#E1F5EE", "--tw-ring-color": "#E1F5EE" }}
                />
              </label>
              <button
                type="button"
                onClick={() => setDraftDateRange({ from: "", to: "" })}
                className="h-8 rounded-md border px-3 text-xs font-medium text-stone-500 hover:text-stone-900"
                style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}
              >
                清除條件
              </button>
              <button
                type="button"
                onClick={downloadSelection}
                disabled={!downloadableIds.length}
                className="h-8 rounded-md px-3 text-xs font-medium inline-flex items-center justify-center gap-1.5 disabled:opacity-50"
                style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
              >
                <Download className="w-3.5 h-3.5" />
                下載圖片
              </button>
            </div>
            {invalidDateRange && (
              <div className="mt-1 text-[10px] text-red-700">上傳起日不可晚於上傳迄日</div>
            )}
          </div>
        </div>
      </div>

      <div className="mb-3 text-xs text-stone-500">
        目前顯示 {images.length} / {allImages.length} 張；可下載組圖 {downloadableIds.length} 張。
      </div>

      <div className="overflow-x-auto rounded-md border" style={{ borderColor: "#E1F5EE" }}>
        <table className="w-full text-left text-xs">
          <thead style={{ backgroundColor: "#FFFFFF", color: "#78716C" }}>
            <tr>
              <th className="px-3 py-2 font-medium text-left align-middle">
                <input
                  type="checkbox"
                  checked={allDownloadableSelected}
                  disabled={!downloadableIds.length}
                  onChange={() => setSelectedIds(allDownloadableSelected ? [] : downloadableIds)}
                />
              </th>
              <th className="px-3 py-2 font-medium text-left align-middle">圖片</th>
              <th className="px-3 py-2 font-medium text-left align-middle">檔名</th>
              <th className="px-3 py-2 font-medium text-left align-middle">流程狀態</th>
              <th className="px-3 py-2 font-medium text-left align-middle">圖片貼標</th>
              <th className="px-3 py-2 font-medium text-left align-middle">人工標籤</th>
              <th className="px-3 py-2 font-medium text-left align-middle">上傳時間</th>
              <th className="px-3 py-2 font-medium text-left align-middle">操作</th>
            </tr>
          </thead>
          <tbody>
            {images.map((image) => {
              const flow = imageFlowStatus(image, folder);
              const ocrTags = imageTagValues(image);
              const canOpenDetail = flow === COMPLETED_FLOW_LABEL;
              const canDownload = downloadableIds.includes(image.id);
              return (
                <tr
                  key={image.id}
                  className={`${canOpenDetail ? "cursor-pointer hover:bg-[#E1F5EE]" : "cursor-not-allowed opacity-70"} transition-colors`}
                  onClick={() => {
                    if (canOpenDetail) setSelectedImage(image);
                  }}
                  style={{ borderTop: "1px solid #E1F5EE" }}
                >
                  <td className="px-3 py-2 text-left align-middle" onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(image.id)}
                      disabled={!canDownload}
                      onChange={() => toggleImage(image)}
                    />
                  </td>
                  <td className="px-3 py-2 text-left align-middle">
                    <div className="w-14 bg-stone-100 rounded overflow-hidden" style={{ aspectRatio: "827 / 1169" }}>
                      {image.thumbnail_url ? (
                        <img src={image.thumbnail_url} alt={image.original_filename} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-[10px] text-stone-500">無圖</div>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 min-w-48 text-left align-middle">
                    <div className="font-medium text-stone-900 truncate">{image.display_name || image.original_filename}</div>
                    {image.display_name && <div className="text-[10px] text-stone-500 truncate">{image.original_filename}</div>}
                  </td>
                  <td className="px-3 py-2 min-w-24 font-medium text-left align-middle">{flow}</td>
                  <td className="px-3 py-2 min-w-44 text-stone-700 text-left align-middle" onClick={(event) => event.stopPropagation()}>
                    <TagBadgeList
                      tags={ocrTags}
                      tone="system"
                      emptyText="尚無圖片貼標"
                      onRemove={canOpenDetail ? (tag) => removeSystemTag(image, tag).catch(() => {}) : undefined}
                    />
                  </td>
                  <td
                    className="px-3 py-2 min-w-44 text-stone-700 text-left align-middle"
                    onClick={(event) => event.stopPropagation()}
                    onDoubleClick={canOpenDetail ? (event) => startQuickTag(event, image, "manual") : undefined}
                    title={canOpenDetail ? "雙擊新增人工標籤" : "流程完成後才能新增標籤"}
                  >
                    <TagBadgeList
                      tags={image.manual_tags}
                      tone="manual"
                      emptyText="尚無人工標籤"
                      onRemove={canOpenDetail ? (tag) => {
                        const matched = (image.manual_tags || []).find((item) => item.tag === tag);
                        if (matched) onDeleteTag(matched.id);
                      } : undefined}
                    />
                    {canOpenDetail && renderQuickTagInput(image, "manual")}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-stone-500 text-left align-middle">{new Date(image.uploaded_at).toLocaleString("zh-TW")}</td>
                  <td className="px-3 py-2 text-left whitespace-nowrap align-middle">
                    <button
                      type="button"
                      disabled={!canOpenDetail}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (canOpenDetail) setSelectedImage(image);
                      }}
                      className="text-xs text-stone-700 hover:text-stone-950 disabled:cursor-not-allowed disabled:text-stone-400"
                    >
                      {canOpenDetail ? "查看 / 編輯" : "尚未完成"}
                    </button>
                  </td>
                </tr>
              );
            })}
            {images.length === 0 && (
              <tr>
                <td colSpan={8} className="px-5 py-8 text-center text-stone-500">目前篩選條件內沒有圖片</td>
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
          onSaved={() => {
            onToast?.({ type: "success", message: "圖片備註已儲存。" });
            setSelectedImage(null);
          }}
        />
      )}
    </div>
  );
}

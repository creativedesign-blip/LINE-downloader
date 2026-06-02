import { ChevronRight, Power, Search, Upload } from "lucide-react";

export default function SidebarNavigation({ activeWorkspace, lineAutoEnabled, lineAutoLoading = false, uploadCount, collapsed, onSelect, onToggleLineAuto }) {
  const lineAutoReady = !lineAutoLoading && typeof lineAutoEnabled === "boolean";
  const isLineAutoEnabled = lineAutoReady ? lineAutoEnabled : false;
  const lineAutoStatus = lineAutoReady ? (isLineAutoEnabled ? "啟動中" : "停用中") : "讀取中";
  const lineAutoAction = isLineAutoEnabled ? "停用排程" : "啟動排程";
  const lineAutoDescription = !lineAutoReady
    ? "正在讀取 LINE 自動抓圖設定。"
    : isLineAutoEnabled
    ? "系統會依排程自動抓 LINE 圖片，並送進 OCR / 組圖流程。"
    : "目前不會自動抓 LINE 圖片，手動上傳流程不受影響。";
  const lineAutoTooltip = !lineAutoReady
    ? "正在讀取 LINE 自動抓圖設定。"
    : isLineAutoEnabled
    ? "停用後，LINE 自動抓圖不會定時執行；手動上傳流程不受影響。"
    : "啟動後，LINE 自動抓圖會依排程執行，並建立 LINE 自動爬取資料夾。";
  const lineAutoColor = !lineAutoReady ? "#57534E" : isLineAutoEnabled ? "#0F6E56" : "#991B1B";
  const lineAutoBorder = !lineAutoReady ? "#D6D3D1" : isLineAutoEnabled ? "#1D9E75" : "#FCA5A5";
  const lineAutoBg = !lineAutoReady ? "#F5F5F4" : isLineAutoEnabled ? "#E1F5EE" : "#FEF2F2";
  const lineAutoDot = !lineAutoReady ? "#A8A29E" : isLineAutoEnabled ? "#1D9E75" : "#B91C1C";
  const itemClass = (name) => `w-full flex items-center ${collapsed ? "justify-center px-2" : "justify-between px-3"} gap-3 rounded-md border py-2.5 text-left text-sm transition-colors ${activeWorkspace === name ? "bg-[#0F6E56] text-[#F9F9F9]" : "bg-white text-stone-800 hover:bg-[#E1F5EE]"}`;
  return (
    <div className={`${collapsed ? "workspace-collapsed p-2" : "p-3 lg:p-4"} space-y-4`}>
      <div>
        <div className={`${collapsed ? "grid grid-cols-1 gap-2" : "grid grid-cols-2 lg:grid-cols-1 gap-2"}`}>
          <button type="button" onClick={() => onSelect("chat")} className={itemClass("chat")} style={{ borderColor: activeWorkspace === "chat" ? "#0F6E56" : "#E1F5EE" }} title="查詢圖片" aria-label="查詢圖片">
            {collapsed ? <Search className="w-4 h-4 flex-shrink-0" /> : <span className="flex items-center gap-2 min-w-0"><Search className="w-4 h-4 flex-shrink-0" /><span className="truncate">查詢圖片</span></span>}
            {!collapsed && <ChevronRight className="w-3.5 h-3.5 flex-shrink-0" />}
          </button>
          <button type="button" onClick={() => onSelect("uploads")} className={itemClass("uploads")} style={{ borderColor: activeWorkspace === "uploads" ? "#0F6E56" : "#E1F5EE" }} title="圖片上傳" aria-label="圖片上傳">
            {collapsed ? <Upload className="w-4 h-4 flex-shrink-0" /> : <span className="flex items-center gap-2 min-w-0"><Upload className="w-4 h-4 flex-shrink-0" /><span className="truncate">圖片上傳</span></span>}
            {!collapsed && <span className="text-[10px] tabular-nums">{uploadCount}</span>}
          </button>
        </div>
      </div>
      <div className={`rounded-lg border bg-white ${collapsed ? "p-2" : "p-3"}`} style={{ borderColor: "#E1F5EE" }}>
        {collapsed ? (
          <button
            type="button"
            onClick={onToggleLineAuto}
            disabled={!lineAutoReady}
            title={`LINE 自動抓圖：目前${lineAutoStatus}。${lineAutoTooltip}`}
            aria-label={`LINE 自動抓圖目前${lineAutoStatus}，${lineAutoAction}`}
            className="relative flex w-full items-center justify-center rounded-md border px-1.5 py-2 transition-colors disabled:cursor-wait"
            style={{ borderColor: lineAutoBorder, backgroundColor: lineAutoBg, color: lineAutoColor }}
          >
            <Power className="h-4 w-4 flex-shrink-0" />
            <span
              className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: lineAutoDot }}
            />
          </button>
        ) : (
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs font-medium text-stone-900">LINE 自動抓圖</div>
                <div className="mt-1 text-[10px] leading-relaxed text-stone-500">{lineAutoDescription}</div>
              </div>
              <div
                className="inline-flex flex-shrink-0 items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-medium"
                style={{ borderColor: lineAutoBorder, backgroundColor: lineAutoBg, color: lineAutoColor }}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: lineAutoDot }}
                />
                {lineAutoStatus}
              </div>
            </div>
            <button
              type="button"
              onClick={onToggleLineAuto}
              disabled={!lineAutoReady}
              title={lineAutoTooltip}
              aria-label={`LINE 自動抓圖目前${lineAutoStatus}，${lineAutoAction}`}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border px-2 py-2 text-[11px] font-medium transition-colors hover:bg-[#F9F9F9] disabled:cursor-wait disabled:opacity-70"
              style={{ borderColor: lineAutoBorder, color: lineAutoColor }}
            >
              <Power className="h-3.5 w-3.5 flex-shrink-0" />
              <span>{lineAutoAction}</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

import { ChevronRight, Power, Search, Upload } from "lucide-react";

export default function SidebarNavigation({ activeWorkspace, lineAutoEnabled, uploadCount, collapsed, onSelect, onToggleLineAuto }) {
  const lineAutoAction = lineAutoEnabled ? "停用" : "啟動";
  const lineAutoTooltip = lineAutoEnabled
    ? "停用後，LINE 自動抓圖不會定時執行；手動上傳流程不受影響。"
    : "啟動後，LINE 自動抓圖會依排程執行，並建立 LINE 自動爬取資料夾。";
  const itemClass = (name) => `w-full flex items-center ${collapsed ? "justify-center px-2" : "justify-between px-3"} gap-3 rounded-md border py-2.5 text-left text-sm transition-colors ${activeWorkspace === name ? "bg-[#1C1917] text-[#F5F1E8]" : "bg-white text-stone-800 hover:bg-[#FAF7EE]"}`;
  return (
    <div className={`${collapsed ? "workspace-collapsed p-2" : "p-3 lg:p-4"} space-y-4`}>
      <div>
        <div className={`${collapsed ? "grid grid-cols-1 gap-2" : "grid grid-cols-2 lg:grid-cols-1 gap-2"}`}>
          <button type="button" onClick={() => onSelect("chat")} className={itemClass("chat")} style={{ borderColor: activeWorkspace === "chat" ? "#1C1917" : "#E5DDC8" }} title="查詢圖片" aria-label="查詢圖片">
            {collapsed ? <Search className="w-4 h-4 flex-shrink-0" /> : <span className="flex items-center gap-2 min-w-0"><Search className="w-4 h-4 flex-shrink-0" /><span className="truncate">查詢圖片</span></span>}
            {!collapsed && <ChevronRight className="w-3.5 h-3.5 flex-shrink-0" />}
          </button>
          <button type="button" onClick={() => onSelect("uploads")} className={itemClass("uploads")} style={{ borderColor: activeWorkspace === "uploads" ? "#1C1917" : "#E5DDC8" }} title="圖片上傳" aria-label="圖片上傳">
            {collapsed ? <Upload className="w-4 h-4 flex-shrink-0" /> : <span className="flex items-center gap-2 min-w-0"><Upload className="w-4 h-4 flex-shrink-0" /><span className="truncate">圖片上傳</span></span>}
            {!collapsed && <span className="text-[10px] tabular-nums">{uploadCount}</span>}
          </button>
        </div>
      </div>
      <div className={`rounded-lg border bg-white ${collapsed ? "p-2" : "p-3"}`} style={{ borderColor: "#E5DDC8" }}>
        <div className={`flex ${collapsed ? "items-center justify-center" : "items-start justify-between"} gap-3`}>
          {!collapsed && <div><div className="text-xs font-medium">LINE 自動抓圖</div><div className="text-[10px] text-stone-500 mt-1 leading-relaxed">啟用後會依排程自動抓圖，並走同一套資料夾與 OCR / 組圖流程。</div></div>}
          <button type="button" onClick={onToggleLineAuto} title={lineAutoTooltip} aria-label={`LINE 自動抓圖：${lineAutoAction}`} className={`flex items-center justify-center gap-1.5 rounded-md border text-[10px] flex-shrink-0 ${collapsed ? "w-full px-1.5 py-2" : "px-2 py-1"}`} style={{ borderColor: lineAutoEnabled ? "#16A34A" : "#B91C1C", color: lineAutoEnabled ? "#166534" : "#991B1B" }}><Power className="w-3 h-3" />{lineAutoAction}</button>
        </div>
      </div>
    </div>
  );
}

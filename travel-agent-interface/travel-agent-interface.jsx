import { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
if (typeof window !== "undefined") window.__OPENCLAW_BUILD__ = "2026-05-20T15:15";
import "./travel-agent-interface.css";
import {
  copyDmListToClipboard,
  copyDmToClipboard,
  dmFullImage,
  dmPreviewImage,
  explainClipboardError,
} from "./clipboard.js";
import { openclawApi, uploadApi } from "./api/openclawClient.js";
import SidebarNavigation from "./upload/SidebarNavigation.jsx";
import UploadWorkspace from "./upload/UploadWorkspace.jsx";
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
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
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
} from "lucide-react";

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
      label: status.pipeline.label || "LINE 圖片處理中",
      color: status.pipeline.is_complete ? "#1D9E75" : "#D97706",
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
    label: isComplete ? "LINE 圖片處理完成" : "LINE 圖片處理中",
    color: isComplete ? "#1D9E75" : "#D97706",
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
  if (job?.status === "success") return "完成";
  if (job?.status === "failed") return "失敗";
  if (job?.last_success === true) return "完成";
  if (job?.last_success === false) return "失敗";
  if (job?.status === "stale") return "中斷";
  return "尚未執行";
}

function jobStepLabel(status) {
  if (status === "success") return "完成";
  if (status === "running") return "執行中";
  if (status === "failed") return "失敗";
  if (status === "skipped") return "略過";
  return "等待中";
}

function jobStepAccent(status) {
  return status === "running" || status === "failed" || status === "stale";
}

function jobSourceLabel(source) {
  if (source === "manual") return "手動";
  if (source === "scheduled") return "排程";
  if (source === "test") return "測試";
  return "未知";
}

function manualJobMessage(job) {
  if (!job) return "手動流程狀態尚未建立。";
  const parts = [
    `手動流程狀態：${manualJobLabel(job)}`,
    `開始：${formatDateTime(job.last_started_at)}`,
    `結束：${formatDateTime(job.last_finished_at)}`,
  ];
  if (job.pid) parts.push(`PID：${job.pid}`);
  if (job.last_error) parts.push(`錯誤：${job.last_error}`);
  return parts.join("，");
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
  // Globe icon in rounded black square, aligned with the notification icon style.
  const bg = inverted ? "#F9F9F9" : "#0F6E56";
  const fg = inverted ? "#0F6E56" : "#F9F9F9";

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

function isManualAgentRunCommand(query) {
  const text = String(query || "");
  const lower = text.toLowerCase();
  const phrases = [
    "手動觸發", "手動流程", "手動執行", "手動抓圖", "手動跑",
    "重新跑", "再跑一次", "再抓一次", "立刻執行", "立即執行",
    "觸發抓圖", "觸發 OCR", "觸發組圖",
  ];
  return phrases.some((p) => text.includes(p))
    || lower.includes("manual run")
    || lower.includes("trigger run")
    || lower.includes("rerun pipeline");
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
  if (times.length > 0 && (query.includes("刪除") || query.includes("移除") || query.includes("取消") || text.includes("remove"))) {
    return { action: "remove", times };
  }
  if (times.length > 0 && (query.includes("加上") || query.includes("新增") || query.includes("加入") || text.includes("add"))) {
    return { action: "add", times };
  }
  if (times.length > 0 && (isScheduleContext || query.includes("設為") || query.includes("替換") || query.includes("改為") || text.includes("replace"))) {
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
        backgroundColor: "#F9F9F9",
        color: "#0F6E56",
        fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600&family=Geist:wght@300;400;500;600;700&family=Noto+Serif+TC:wght@400;500;700&display=swap');
        .font-display { font-family: 'Fraunces', 'Noto Serif TC', serif; font-optical-sizing: auto; }
        .font-serif-tc { font-family: 'Noto Serif TC', serif; }
        .grain-bg { background-image: radial-gradient(circle at 1px 1px, rgba(15,110,86,0.035) 1px, transparent 0); background-size: 24px 24px; }
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
          className="rounded-lg border bg-[#E1F5EE] p-6 shadow-sm"
          style={{ borderColor: "#E1F5EE" }}
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
              style={{ borderColor: "#B8D9CE" }}
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
              style={{ borderColor: "#B8D9CE" }}
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
            style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
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
        style={{ backgroundColor: "#F9F9F9", color: "#0F6E56" }}
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
    { id: 1, role: "agent", type: "welcome", time: "09:42" },
  ]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [chatRequest, setChatRequest] = useState(null);
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
  const scrollRef = useRef(null);
  const manualPreviewPollRef = useRef(null);
  const inputRef = useRef(null);

  const suggestions = [
    { icon: Inbox, label: "今日新增", prompt: "查看今日新增的旅遊圖片 DM" },
    { icon: Zap, label: "手動流程", prompt: "手動觸發抓取+OCR+組圖" },
    { icon: Search, label: "查詢日本方案", prompt: "幫我找日本的所有方案" },
    { icon: Layers, label: "重複圖片", prompt: "檢查重複圖片" },
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
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  const formatPrice = (value) => {
    const n = Number(value);
    return Number.isFinite(n) && n >= 5000 ? `NT$ ${n.toLocaleString()}` : "價格未標示";
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
      ? `${item.months.join(", ")}月`
      : "月份未標示";
    const indexed = item.indexed_at
      ? `索引 ${new Date(item.indexed_at).toLocaleDateString("zh-TW")}`
      : "";
    return [months, indexed].filter(Boolean).join(" · ");
  };

  const normalizeAgentItem = (item, index = 0) => {
    const countries = Array.isArray(item.countries) ? item.countries : [];
    const regions = Array.isArray(item.regions) ? item.regions : [];
    const features = Array.isArray(item.features) ? item.features : [];
    const place = [...countries, ...regions].filter(Boolean).join(" / ") || "未分類";
    const days = Number(item.duration_days) || 0;
    const priceSummary = formatPriceSummary(item);
    const titleParts = [place, days ? `${days}天` : "", priceSummary];

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
        countries.length ? `國家：${countries.join("、")}` : "國家未標示",
        regions.length ? `地區：${regions.join("、")}` : "地區未標示",
        item.group_name || item.target_id ? `來源：${item.group_name || item.target_id}` : "來源未標示",
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
        Array.isArray(match.months) && match.months.length ? `${match.months.join(", ")}月` : "",
        match.duration_days ? `${match.duration_days}天` : "",
        match.price_bucket ? `NT$ ${Number(match.price_bucket).toLocaleString()}` : "",
      ].filter(Boolean);

      return {
        key: keyParts.join(" · ") || `重複圖片 ${groupIndex + 1}`,
        groupId: group.group_id || "",
        count: group.count || dms.length,
        images: dms.map((dm) => ({
          dm,
          source: dm.source,
          time: dm.raw?.indexed_at
            ? new Date(dm.raw.indexed_at).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })
            : "時間未標示",
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
    setUploadFolders(await uploadApi.listFolders(30));
  };

  const refreshOpenclawSettings = async () => {
    const payload = await openclawApi.getSettings();
    if (payload?.settings) {
      setLineAutoEnabled(Boolean(payload.settings.line_auto_enabled));
    }
  };

  const refreshUploadDetail = async (folderId, filters = {}) => {
    if (!folderId) return;
    setUploadDetail(await uploadApi.getFolder(folderId, filters));
  };

  const handleUploadImages = async ({ displayName, note, files }) => {
    if (!displayName.trim()) throw new Error("請輸入資料夾名稱");
    if (!files?.length) throw new Error("請選擇圖片");
    setUploading(true);
    setUploadError("");
    try {
      const uploadPayload = await uploadApi.uploadToNewFolder({ displayName, note, files });
      await refreshUploadFolders();
      await refreshUploadDetail(uploadPayload.folder.id);
      refreshOverview();
      return uploadPayload;
    } finally {
      setUploading(false);
    }
  };

  const handleUploadImagesToFolder = async ({ folderId, files }) => {
    if (!folderId) throw new Error("請選擇資料夾");
    if (!files?.length) throw new Error("請選擇圖片");
    setUploading(true);
    setUploadError("");
    try {
      const uploadPayload = await uploadApi.uploadToExistingFolder({ folderId, files });
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
    const payload = await openclawApi.updateSettings({ line_auto_enabled: next });
    setLineAutoEnabled(Boolean(payload.settings.line_auto_enabled));
  };

  const handleAddManualTag = async (imageId, tag, filters = {}) => {
    const value = String(tag || "").trim();
    if (!value) return;
    await uploadApi.addManualTag(imageId, value);
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id, filters);
  };

  const handleDeleteManualTag = async (tagId, filters = {}) => {
    await uploadApi.deleteManualTag(tagId);
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id, filters);
  };

  const handleUpdateManualTag = async (tagId, tag, filters = {}) => {
    const value = String(tag || "").trim();
    if (!value) return;
    await uploadApi.updateManualTag(tagId, value);
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id, filters);
  };

  const handleUpdateImageMetadata = async (imageId, data, filters = {}) => {
    await uploadApi.updateImage(imageId, data);
    if (uploadDetail?.folder?.id) await refreshUploadDetail(uploadDetail.folder.id, filters);
  };

  const handleArchiveImage = async (imageId, filters = {}) => {
    await uploadApi.archiveImage(imageId);
    if (uploadDetail?.folder?.id) {
      await refreshUploadDetail(uploadDetail.folder.id, filters);
      await refreshUploadFolders();
    }
  };

  const handleArchiveFolder = async (folderId) => {
    await uploadApi.archiveFolder(folderId);
    setUploadDetail(null);
    await refreshUploadFolders();
  };

  const handleDownloadFolder = async (folderId, filters = {}) => {
    await uploadApi.downloadFolder(folderId, filters);
  };

  useEffect(() => {
    refreshOverview();
    refreshUploadFolders().catch((error) => setUploadError(error.message));
    refreshOpenclawSettings().catch(() => {});
    const id = setInterval(refreshOverview, 60_000);
    const uploadId = setInterval(() => {
      refreshUploadFolders().catch(() => {});
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
        content: `Agent 查詢失敗：${payload.error}`,
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
          content: "目前沒有找到重複圖片。",
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
        content: `沒有找到「${query}」相關方案。`,
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

    if (dms.length > 6) {
      return {
        id: Date.now() + 1,
        role: "agent",
        type: "results-light",
        query,
        criteria: criteriaFromPayload(payload, query),
        dms,
        time: getTime(),
        fallback: false,
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

  const appendTodayCombinationPreview = async (query = "今日新增組圖") => {
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
          await appendTodayCombinationPreview("手動流程已完成，顯示今日新增組圖");
        } else {
          setMessages((p) => [
            ...p,
            {
              id: Date.now() + 1,
              role: "agent",
              type: "text",
              content: `手動流程失敗，請檢查後端紀錄。${job.last_error ? `錯誤：${job.last_error}` : ""}`,
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
          content: "手動流程仍在處理中，請稍後重新查詢今日新增組圖。",
          time: getTime(),
        },
      ]);
    }
  };

  const handleSend = async (textOrEvent) => {
    if (textOrEvent?.preventDefault) textOrEvent.preventDefault();
    if (isThinking) return;
    const message = (typeof textOrEvent === "string" ? textOrEvent : input).trim();
    if (!message) return;

    setMessages((p) => [
      ...p,
      { id: Date.now(), role: "user", type: "text", content: message, time: getTime() },
    ]);
    setInput("");
    setIsThinking(true);

    const m = message;
    setChatRequest({ query: m, startedAt: Date.now() });
    setToast({ type: "success", message: `已送出查詢：${m}` });

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
              ? `${payload?.started === false ? "手動流程已在執行中。" : "已手動觸發抓取、OCR 與組圖。"}${payload?.job ? ` ${manualJobMessage(payload.job)}` : ""}`
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
        setChatRequest(null);
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
      setChatRequest(null);
      setMessages((p) => [...p, response]);
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 20_000);
    try {
      const apiResponse = await fetch("/api/openclaw/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: m, limit: 60 }),
        signal: controller.signal,
      });
      const responseText = await apiResponse.text();
      const payload = responseText ? JSON.parse(responseText) : {};
      const timing = {
        query: m,
        status: apiResponse.status,
        durationMs: apiResponse.headers.get("X-OpenClaw-Duration-Ms"),
        resultCount: apiResponse.headers.get("X-OpenClaw-Result-Count"),
        serverPid: apiResponse.headers.get("X-OpenClaw-Server-Pid"),
        debug: payload?.debug || null,
        receivedAt: new Date().toISOString(),
      };
      window.__openclawLastChatTiming = timing;
      console.info("[OpenClaw chat timing]", timing);
      if (!apiResponse.ok) throw new Error(payload?.error || `HTTP ${apiResponse.status}`);
      const response = buildAgentResponse(payload, m);
      setMessages((p) => [...p, response]);
      const count = Number(payload?.count || payload?.debug?.result_count || 0);
      setToast({ type: "success", message: `已取得 ${count} 筆結果` });
    } catch (error) {
      const errorMessage =
        error?.name === "AbortError"
          ? "查詢逾時，請稍後再試。"
          : error.message;
      setMessages((p) => [
        ...p,
        {
          id: Date.now() + 1,
          role: "agent",
          type: "text",
          content: `Agent 查詢失敗：${errorMessage}`,
          time: getTime(),
        },
      ]);
      setToast({ type: "error", message: `查詢失敗：${errorMessage}` });
    } finally {
      window.clearTimeout(timeoutId);
      setIsThinking(false);
      setChatRequest(null);
    }
  };

  // Helpers ??armed state stored in ref for synchronous read between rapid keystrokes
  // Double-Enter to send, IME-aware for Chinese input.
  const handleKeyDown = (e) => {
    if (e.key !== "Enter") return;
    if (e.shiftKey) return;
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    e.currentTarget.form?.requestSubmit();
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
          "瀏覽器無法直接複製圖片，已改為複製文字內容。若要複製圖片，請使用 HTTPS 頁面或剪貼簿橋接功能。"
        );
        return false;
      }

      if (copyMode === "download") {
        // Multi-DM action is now an explicit "下載全部" button — no surprise,
        // no need to alert. The browser's own download bar confirms the action.
        return true;
      }

      const copiedKey =
        items.length === 1 && typeof items[0] !== "string"
          ? items[0].id
          : items.map((dm) => (typeof dm === "string" ? dm : dm.id)).join("|");
      setCopiedId(copiedKey || "clipboard");
      setTimeout(() => setCopiedId(null), 2000);
      return true;
    } catch (error) {
      console.error("Clipboard copy failed.", error);
      window.alert(`複製圖片失敗\n\n${explainClipboardError(error)}`);
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
      window.alert("缺少重複圖片群組 ID，請重新整理後再試。");
      return false;
    }
    if (action === "keep_one" && !keepPath) {
      window.alert("缺少要保留的圖片路徑，請重新整理後再試。");
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
      window.alert(`重複圖片審核失敗：${error.message}`);
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
        backgroundColor: "#F9F9F9",
        color: "#0F6E56",
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
        .scrollbar-thin::-webkit-scrollbar-thumb { background: #B8D9CE; border-radius: 3px; }
        .scrollbar-thin::-webkit-scrollbar-thumb:hover { background: #1D9E75; }
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { scrollbar-width: none; -ms-overflow-style: none; }
        .grain-bg { background-image: radial-gradient(circle at 1px 1px, rgba(15,110,86,0.035) 1px, transparent 0); background-size: 24px 24px; }
      `}</style>

      <div className="flex flex-col h-screen overflow-hidden">
        {/* MAIN */}
        <main className="flex-1 flex flex-col overflow-hidden relative">
          <header
            className="flex items-center justify-between px-6 md:px-10 py-4 border-b"
            style={{ borderColor: "#E1F5EE" }}
          >
            {/* Brand + Date */}
            <div className="flex items-center gap-5 min-w-0">
              <div className="flex items-center gap-2.5 flex-shrink-0">
                <DadovaLogo size={32} />
                <div className="hidden sm:block">
                  <div
                    className="font-serif-tc font-medium text-base leading-none tracking-tight"
                    style={{ color: "#0F6E56" }}
                  >
                    旅遊圖片工作台
                  </div>
                  <div className="text-[9px] tracking-[0.18em] uppercase text-stone-500 mt-1">
                    Dadova Travel Agent
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
                  className="relative p-2 rounded-md hover:bg-[#D4EFE5] transition-colors"
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
                    onSelectStatus={() => showOverviewMessage(overview.status, "status", "流程狀態")}
                    onSelectNew={() => showOverviewMessage(overview.latest, "latest", "今日新增")}
                    onSelectDup={() => showOverviewMessage(overview.duplicates, "duplicates", "重複圖片")}
                  />
                )}
              </div>
              <div className="h-6 w-px bg-stone-300 hidden md:block" />
              <button
                onClick={onLogout}
                className="flex items-center gap-2 hover:bg-[#D4EFE5] rounded-md px-2 py-1 transition-colors"
                aria-label={onLogout ? "登出" : "使用者"}
                title={onLogout ? "登出系統" : currentUser}
              >
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0"
                  style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
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

          <div className="flex-1 min-h-0 flex flex-col lg:flex-row overflow-hidden">
            <aside
              className={`${sidebarCollapsed ? "w-full lg:w-16" : "w-full lg:w-64"} flex-shrink-0 border-b lg:border-b-0 lg:border-r transition-all duration-200`}
              style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}
            >
              <div className={`flex items-center gap-2 border-b px-3 py-2 ${sidebarCollapsed ? "justify-between lg:justify-center" : "justify-between"}`} style={{ borderColor: "#E1F5EE" }}>
                {!sidebarCollapsed && (
                  <div className="text-[10px] tracking-[0.16em] uppercase text-stone-500">Workspace</div>
                )}
                {sidebarCollapsed && (
                  <div className="lg:hidden text-xs font-medium text-stone-700">
                    {activeWorkspace === "uploads" ? "圖片上傳" : "查詢圖片"}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setSidebarCollapsed((value) => !value)}
                  className="rounded-md border bg-white p-1.5 text-stone-700 hover:bg-[#E1F5EE]"
                  style={{ borderColor: "#E1F5EE" }}
                  aria-label={sidebarCollapsed ? "展開 workspace" : "收合 workspace"}
                  title={sidebarCollapsed ? "展開 workspace" : "收合 workspace"}
                >
                  <span className="lg:hidden">
                    {sidebarCollapsed ? <Menu className="w-4 h-4" /> : <X className="w-4 h-4" />}
                  </span>
                  <span className="hidden lg:block">
                    {sidebarCollapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
                  </span>
                </button>
              </div>
              <div className={sidebarCollapsed ? "hidden lg:block" : "block"}>
                <SidebarNavigation
                  activeWorkspace={activeWorkspace}
                  lineAutoEnabled={lineAutoEnabled}
                  uploadCount={uploadFolders.length}
                  collapsed={sidebarCollapsed}
                  onSelect={setActiveWorkspace}
                  onToggleLineAuto={() => handleToggleLineAuto().catch((error) => setUploadError(error.message))}
                />
              </div>
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
                    onSelectFolder={(folder, filters) => refreshUploadDetail(folder.id, filters).catch((error) => setUploadError(error.message))}
                    onRefresh={() => {
                      refreshUploadFolders().catch((error) => setUploadError(error.message));
                      if (uploadDetail?.folder?.id) refreshUploadDetail(uploadDetail.folder.id).catch((error) => setUploadError(error.message));
                    }}
                    onAddTag={(imageId, tag, filters) => handleAddManualTag(imageId, tag, filters).catch((error) => setUploadError(error.message))}
                    onDeleteTag={(tagId, filters) => handleDeleteManualTag(tagId, filters).catch((error) => setUploadError(error.message))}
                    onUpdateTag={(tagId, tag, filters) => handleUpdateManualTag(tagId, tag, filters).catch((error) => setUploadError(error.message))}
                    onUpdateImage={async (imageId, data, filters) => {
                      try {
                        await handleUpdateImageMetadata(imageId, data, filters);
                      } catch (error) {
                        setUploadError(error.message);
                        throw error;
                      }
                    }}
                    onArchiveImage={(imageId, filters) => handleArchiveImage(imageId, filters).catch((error) => setUploadError(error.message))}
                    onArchiveFolder={(folderId) => handleArchiveFolder(folderId).catch((error) => setUploadError(error.message))}
                    onDownloadFolder={(folderId, filters) => handleDownloadFolder(folderId, filters).catch((error) => setUploadError(error.message))}
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
                  <span>{chatRequest?.query ? `查詢中：${chatRequest.query}` : "查詢中"}</span>
                  <span className="typing-cursor">...</span>
                </div>
              )}
            </div>
          </div>

          {/* INPUT */}
          <div
            className="border-t px-6 md:px-10 py-5"
            style={{ borderColor: "#E1F5EE", backgroundColor: "#F9F9F9" }}
          >
            <div className="max-w-3xl mx-auto">
              <form
                onSubmit={handleSend}
                className="flex items-center gap-3 px-4 py-3 rounded-lg border bg-white transition-all"
                style={{ borderColor: "#E1F5EE" }}
              >
                <textarea
                  ref={inputRef}
                  rows="1"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="輸入需求，例如：幫我找日本的所有方案"
                  className="flex-1 resize-none outline-none text-sm bg-transparent placeholder:text-stone-400 max-h-32 leading-relaxed text-left"
                  style={{ color: "#0F6E56" }}
                />
                <button
                  type="submit"
                  disabled={isThinking || !input.trim()}
                  className="flex-shrink-0 inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: !isThinking && input.trim() ? "#0F6E56" : "#E1F5EE",
                    color: !isThinking && input.trim() ? "#F9F9F9" : "#A8A29E",
                  }}
                >
                  <Send className="w-3.5 h-3.5" />
                  送出
                </button>
              </form>
              <div className="flex items-center justify-between mt-2.5 px-1">
                <div className="text-[10px] text-stone-500">
                  Enter 送出，Shift+Enter 換行
                </div>
                <div className="text-[10px] text-stone-500 flex items-center gap-1.5">
                  <span className="italic font-display">Powered by</span>
                  <span className="flex items-baseline gap-1">
                    <span className="font-bold tracking-tight" style={{ color: "#1D9E75", letterSpacing: "-0.01em" }}>
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
    <div className="fixed bottom-5 right-5 z-[60] max-w-sm rounded-lg border bg-white shadow-xl animate-fade-up" style={{ borderColor: success ? "#1D9E75" : "#B91C1C" }}>
      <div className="flex items-start gap-3 px-4 py-3">
        {success ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-green-600" /> : <AlertTriangle className="mt-0.5 h-4 w-4 text-red-700" />}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{success ? "上傳成功" : "上傳失敗"}</div>
          <div className="mt-0.5 text-xs text-stone-600">{toast?.message}</div>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-stone-500 hover:bg-stone-100" aria-label="關閉通知">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

/* ===================================================================== */
/* NOTIFICATION PANEL                                                     */
/* ===================================================================== */
function MessageBlock({
  msg,
  copiedId,
  onCopy,
  onAction,
  suggestions,
  onPreview,
  onCompareDup,
  onReviewDup,
  onSelect,
}) {
  const isUser = msg.role === "user";

  const renderContent = () => {
    if (msg.type === "welcome") {
      return <WelcomeMessage suggestions={suggestions} onAction={onAction} />;
    }
    if (msg.type === "status") {
      return <AgentStatusMessage status={msg.status} />;
    }
    if (msg.type === "results") {
      return (
        <ResultsMessage
          query={msg.query}
          criteria={msg.criteria}
          fallback={msg.fallback}
          dms={msg.dms || []}
          copiedId={copiedId}
          onCopy={onCopy}
          onPreview={onPreview}
          onSelect={onSelect}
        />
      );
    }
    if (msg.type === "results-light") {
      return (
        <ResultsLightMessage
          query={msg.query}
          dms={msg.dms || []}
          onPreview={onPreview}
          onSelect={onSelect}
        />
      );
    }
    if (msg.type === "daily-summary") {
      return (
        <DailySummary
          dms={msg.dms || []}
          onPreview={onPreview}
          onSelect={onSelect}
          onCopy={onCopy}
        />
      );
    }
    if (msg.type === "duplicates") {
      return (
        <DuplicatesMessage
          groups={msg.groups || []}
          onCompareDup={onCompareDup}
          onReviewDup={onReviewDup}
          onPreview={onPreview}
        />
      );
    }
    if (msg.type === "schedule-unavailable") {
      return <ScheduleUnavailableMessage action={msg.action} requestedTimes={msg.requestedTimes} />;
    }
    return <p className="whitespace-pre-wrap leading-relaxed">{msg.content || ""}</p>;
  };

  return (
    <div className={`mb-6 flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[92%] ${isUser ? "text-right" : "text-left"}`}>
        <div
          className={`rounded-lg border px-4 py-3 text-sm shadow-sm ${isUser ? "text-white" : "bg-white text-stone-800"}`}
          style={{
            backgroundColor: isUser ? "#0F6E56" : "#FFFFFF",
            borderColor: isUser ? "#0F6E56" : "#E1F5EE",
          }}
        >
          {renderContent()}
        </div>
        {msg.time && (
          <div className={`mt-1 text-[10px] text-stone-500 ${isUser ? "pr-1" : "pl-1"}`}>
            {msg.time}
          </div>
        )}
      </div>
    </div>
  );
}

function WelcomeMessage({ suggestions = [], onAction }) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-stone-500" />
        <span className="text-sm font-medium">DADOVA Agent</span>
      </div>
      <p className="mb-4 text-sm leading-relaxed text-stone-700">
        你可以查詢旅遊 DM、查看最新 OCR 與組圖結果，也可以切換到圖片上傳 workspace 管理手動上傳圖片。
      </p>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {suggestions.map((item, index) => {
          const Icon = item.icon || ArrowUpRight;
          return (
            <button
              key={`${item.label}-${index}`}
              type="button"
              onClick={() => onAction?.(item.prompt)}
              className="group flex items-center gap-3 rounded-lg border bg-white px-4 py-3 text-left transition-all hover:border-stone-900"
              style={{ borderColor: "#E1F5EE" }}
            >
              <Icon className="h-3.5 w-3.5 text-stone-500 transition-colors group-hover:text-stone-900" />
              <span className="min-w-0 flex-1 text-sm">{item.label}</span>
              <ArrowUpRight className="h-3 w-3 text-stone-400 transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-stone-900" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

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
      style={{ borderColor: "#E1F5EE" }}
    >
      <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
        <div className="text-sm font-medium" style={{ color: "#0F6E56" }}>Agent 通知</div>
        <button onClick={onRefresh} className="text-[10px] text-stone-500 hover:text-stone-900 transition-colors">
          重新整理
        </button>
      </div>

      {!hasAny ? (
        <div className="px-4 py-7 flex flex-col items-center text-center">
          <div className="w-10 h-10 rounded-md flex items-center justify-center mb-3" style={{ backgroundColor: "#E1F5EE" }}>
            <Clock className="w-4 h-4 text-stone-500" />
          </div>
          <div className="text-xs font-medium mb-1">沒有 Agent 通知</div>
          <div className="text-[10px] text-stone-500 leading-relaxed">重新整理後會顯示最新流程狀態。</div>
        </div>
      ) : (
        <div className="max-h-80 overflow-y-auto scrollbar-thin">
          {overview?.loading && (
            <div className="w-full px-4 py-3 flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#E1F5EE" }}>
                <Loader2 className="w-3 h-3 animate-spin text-stone-500" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">正在同步 Agent</div>
                <p className="text-[11px] text-stone-600 leading-relaxed">正在讀取最新流程狀態。</p>
              </div>
            </div>
          )}

          {overview?.error && (
            <button onClick={onSelectStatus} className="w-full px-4 py-3 text-left hover:bg-[#E1F5EE] transition-colors group flex gap-3">
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
            <div className="px-4 py-3" style={{ borderTop: "1px solid #E1F5EE", backgroundColor: "#FFFFFF" }}>
              <div className="text-xs font-medium mb-1">資料來源概況</div>
              <div className="space-y-1.5">
                {sourceEvents.map((item) => (
                  <div key={`${item.name}-${item.time}`} className="flex items-center justify-between gap-3 text-[11px] text-stone-600">
                    <span className="truncate">{item.name}</span>
                    <span className="shrink-0 tabular-nums">{item.indexed} 筆</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {latestCount > 0 && (
            <button onClick={onSelectNew} className="w-full px-4 py-3 text-left hover:bg-[#E1F5EE] transition-colors group flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#E1F5EE" }}>
                <Inbox className="w-3 h-3" style={{ color: "#0F6E56" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-xs font-medium">最新圖片</span>
                  <span className="text-[10px] text-stone-500 tabular-nums">{latestLabel}</span>
                </div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  找到 <span className="font-display italic text-base text-stone-900">{latestCount}</span> 筆今日新增組圖。
                </p>
              </div>
            </button>
          )}

          {duplicateCount > 0 && (
            <button onClick={onSelectDup} className="w-full px-4 py-3 text-left hover:bg-[#E1F5EE] transition-colors group flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#FEE2E2" }}>
                <Layers className="w-3 h-3" style={{ color: "#B91C1C" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-xs font-medium">重複圖片</span>
                  <span className="text-[10px] text-stone-500 tabular-nums">待審核</span>
                </div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  目前有 <span className="font-display italic text-base" style={{ color: "#B91C1C" }}>{duplicateCount}</span> 組可能重複的圖片。
                </p>
              </div>
            </button>
          )}

          {totalIndexed > 0 && (
            <button onClick={onSelectStatus} className="w-full px-4 py-3 text-left hover:bg-[#E1F5EE] transition-colors group flex gap-3">
              <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#F9F9F9" }}>
                <CheckCircle2 className="w-3 h-3" style={{ color: "#0F6E56" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium mb-0.5">索引完成</div>
                <p className="text-[11px] text-stone-600 leading-relaxed">
                  已索引 <span className="font-display italic text-base text-stone-900">{totalIndexed}</span> 筆圖片資料。
                </p>
              </div>
            </button>
          )}
        </div>
      )}

      <div className="px-4 py-2 border-t flex items-center justify-between text-[10px] text-stone-500" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
        <span>通知更新</span>
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
          <CheckCircle2 className="w-4 h-4" style={{ color: "#1D9E75" }} />
        ) : (
          <Loader2 className="w-4 h-4 animate-spin" style={{ color: "#D97706" }} />
        )}
        <span className="text-sm font-medium">{pipeline.label}</span>
      </div>
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
        <div className="px-5 py-3 flex items-center justify-between border-b" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
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
          <div className="h-1 rounded-full overflow-hidden" style={{ backgroundColor: "#E1F5EE" }}>
            <div className="h-full transition-all duration-700 ease-out" style={{ width: `${Math.min(100, pct)}%`, backgroundColor: "#0F6E56" }} />
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
            <div className="mt-3 rounded-md border px-3 py-2.5" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
              <div className="flex items-center justify-between gap-3 mb-2">
                <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500">
                  手動流程 · {jobSourceLabel(manualJob.trigger_source)}
                </span>
                <span className="text-xs font-medium" style={{ color: manualJob.running ? "#D97706" : manualJob.last_success === false || manualJob.status === "stale" ? "#B91C1C" : "#1D9E75" }}>
                  {manualJobStatus}
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] text-stone-600 mb-2">
                <div>開始：{formatDateTime(manualJob.started_at || manualJob.last_started_at)}</div>
                <div>結束：{formatDateTime(manualJob.finished_at || manualJob.last_finished_at)}</div>
                <div>PID：{manualJob.pid || "--"}</div>
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
              <span className="text-[10px] tracking-[0.2em] uppercase text-stone-500">最新更新</span>
              <span className="text-xs font-medium">{new Date(latestAt).toLocaleString("zh-TW")}</span>
            </div>
          )}
        </div>
        <div className="px-5 py-3 grid grid-cols-4 gap-1.5 border-t" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          {(sources.length ? sources : [{ target_id: "Agent", indexed_count: 0 }]).slice(0, 20).map((source, i) => {
            const hasData = Number(source.indexed_count || 0) > 0;
            const hasError = Number(source.error_count || 0) > 0;
            return (
              <div
                key={`${source.target_id || source.group_name || "source"}-${i}`}
                title={`${source.target_id || source.group_name || "Agent"}: ${source.indexed_count || 0}`}
                className="h-1 rounded-full"
                style={{ backgroundColor: hasError ? "#B91C1C" : hasData ? "#0F6E56" : "#E1F5EE" }}
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
    <div className="rounded-md px-2 py-1.5" style={{ backgroundColor: "#E1F5EE" }}>
      <div className="text-[9px] tracking-[0.15em] uppercase text-stone-400">{label}</div>
      <div className="text-sm font-medium tabular-nums" style={{ color: accent ? "#B91C1C" : "#0F6E56" }}>
        {value}
      </div>
    </div>
  );
}

function ResultsLightMessage({ query, dms, onPreview, onSelect }) {
  const items = Array.isArray(dms) ? dms : [];
  const previewItems = items.slice(0, 5);

  return (
    <div>
      <div className="mb-3">
        <p className="text-sm leading-relaxed text-stone-700 mb-1">
          找到 <span className="font-medium" style={{ color: "#0F6E56" }}>{items.length}</span> 筆相關方案。
        </p>
        <div className="flex items-center gap-1.5 text-[10px] text-stone-500">
          <Search className="w-3 h-3" />
          <span className="truncate">查詢：{query}</span>
        </div>
      </div>
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
        <div className="divide-y" style={{ borderColor: "#E1F5EE" }}>
          {previewItems.map((dm) => (
            <button
              key={dm.id}
              onClick={() => onPreview?.(dm, items)}
              className="w-full px-4 py-3 text-left hover:bg-[#E1F5EE] transition-colors"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-stone-800 truncate">{dm.title}</div>
                  <div className="mt-0.5 text-[11px] text-stone-500 truncate">{dm.source} · {dm.period}</div>
                </div>
                <div className="shrink-0 text-xs font-semibold" style={{ color: "#B91C1C" }}>{dm.price}</div>
              </div>
            </button>
          ))}
        </div>
        <button
          onClick={() => onSelect?.(items)}
          className="w-full px-4 py-3 border-t flex items-center justify-between hover:bg-[#E1F5EE] transition-colors group"
          style={{ borderColor: "#E1F5EE", color: "#0F6E56" }}
        >
          <div className="flex items-center gap-2">
            <MousePointerClick className="w-3.5 h-3.5" />
            <span className="text-sm font-medium">展開完整結果</span>
            <span className="text-[10px] text-stone-500">{items.length} 筆</span>
          </div>
          <ArrowRight className="w-3 h-3 text-stone-500 group-hover:text-stone-900 group-hover:translate-x-0.5 transition-all" />
        </button>
      </div>
      <p className="text-[10px] text-stone-500 leading-relaxed mt-2">
        先顯示前幾筆結果，點擊可查看完整列表並批次下載圖片包。
      </p>
    </div>
  );
}

/* ===================================================================== */
/* RESULTS compact horizontal cards in a single column                    */
/* ===================================================================== */
function ResultsMessage({ query, criteria, fallback, dms, copiedId, onCopy, onPreview, onSelect }) {
  const [copiedAll, setCopiedAll] = useState(false);
  const [copiedSelected, setCopiedSelected] = useState(false);
  const [selected, setSelected] = useState(new Set());

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
    chips.push({ label: "價格", value: minPrice && maxPrice ? `${minPrice} - ${maxPrice}` : maxPrice || minPrice, key: "price" });
  }
  if (criteria?.feature) chips.push({ label: "特色", value: criteria.feature, key: "feature" });
  if (criteria?.tag) chips.push({ label: "標籤", value: criteria.tag, key: "tag" });
  if (criteria?.type) chips.push({ label: "類型", value: criteria.type, key: "type" });

  const Summary = () => (
    <>
      <p className="text-sm leading-relaxed text-stone-700 mb-1">
        {fallback ? "找不到完全符合的 DM，先顯示相近結果。" : "已找到符合條件的 DM："}
        <span className="font-medium"> {dms.length} 筆</span>
      </p>
      <div className="flex items-center gap-1.5 text-[10px] text-stone-500">
        <Search className="w-3 h-3" />
        <span className="truncate">查詢：{query}</span>
      </div>
    </>
  );

  const CriteriaChips = ({ className = "" }) => chips.length > 0 && (
    <div className={`rounded-md border px-3 py-2.5 ${className}`} style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
      <div className="flex items-center gap-2 mb-1.5">
        <Sparkles className="w-3 h-3 text-stone-500" />
        <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500 font-medium">查詢條件</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <div key={chip.key} className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-white border" style={{ borderColor: "#E1F5EE" }}>
            <span className="text-[9px] tracking-[0.1em] uppercase text-stone-400">{chip.label}</span>
            <span className="text-[11px] font-medium" style={{ color: "#0F6E56" }}>{chip.value}</span>
          </div>
        ))}
      </div>
    </div>
  );

  const hasSelection = selected.size > 0;

  return (
    <div>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1"><Summary /></div>
        {dms.length > 1 && !hasSelection && (
          <button onClick={handleCopyAll} className="flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium border transition-all" style={{ borderColor: copiedAll ? "#1D9E75" : "#0F6E56", backgroundColor: copiedAll ? "#1D9E75" : "transparent", color: copiedAll ? "#F9F9F9" : "#0F6E56" }}>
            {copiedAll ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
            {copiedAll ? `已下載 ${dms.length} 筆` : "下載全部"}
          </button>
        )}
      </div>

      {hasSelection && (
        <div className="rounded-md px-3 py-2 mb-3 flex items-center justify-between gap-2 animate-fade-up" style={{ backgroundColor: "#0F6E56" }}>
          <span className="text-[11px] text-white/80 tabular-nums">
            <span className="font-display italic text-base text-white">{selected.size}</span>
            <span className="text-white/50 ml-1">/ {dms.length}</span>
            <span className="ml-2">已選取</span>
          </span>
          <div className="flex items-center gap-1.5">
            <button onClick={clearSelection} className="px-3 py-1 rounded text-[11px] hover:bg-white/10 transition-colors" style={{ color: "#F9F9F9" }}>清除選取</button>
            <button onClick={handleCopySelected} className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[11px] font-medium transition-all" style={{ backgroundColor: copiedSelected ? "#1D9E75" : "#F9F9F9", color: copiedSelected ? "#F9F9F9" : "#0F6E56" }}>
              {copiedSelected ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
              {copiedSelected ? `已下載 ${selected.size} 筆` : `下載選取 ${selected.size} 筆`}
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
        borderColor: isSelected ? "#0F6E56" : "#E1F5EE",
        backgroundColor: isSelected ? "#E1F5EE" : "white",
        boxShadow: isSelected ? "0 0 0 1px #0F6E56" : undefined,
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
            backgroundColor: isSelected ? "#0F6E56" : "transparent",
            border: isSelected ? "none" : "1.5px solid #B8D9CE",
          }}
          aria-label={isSelected ? "取消選取" : "選取"}
        >
          {isSelected && (
            <Check className="w-3 h-3" style={{ color: "#F9F9F9" }} strokeWidth={3} />
          )}
        </button>

        {/* Thumbnail ??always opens preview */}
        <button
          onClick={onPreview}
          className="relative flex-shrink-0 overflow-hidden rounded bg-stone-100 group"
          style={{ width: "60px", aspectRatio: "827 / 1169" }}
          aria-label="開啟預覽"
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
          aria-label="切換選取"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span
                className="text-[9px] tracking-wider uppercase px-1.5 py-0.5 rounded-sm flex-shrink-0"
                style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
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

        {/* Per-card quick copy ??single-DM shortcut */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onCopy();
          }}
          className="flex-shrink-0 self-center flex items-center justify-center gap-1 px-3 py-1.5 rounded-md text-[11px] font-medium transition-all whitespace-nowrap"
          style={{
            backgroundColor: copied ? "#1D9E75" : "#0F6E56",
            color: "#F9F9F9",
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
          color: accent ? "#B91C1C" : "#0F6E56",
          fontWeight: accent ? 600 : 400,
        }}
      >
        {value}
      </span>
    </div>
  );
}

/* ===================================================================== */
/* DAILY SUMMARY Agent latest data, original summary UI                   */
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
        今日新增 <span className="font-medium">{todays.length} 筆</span> DM，可預覽、全選或下載圖片包；單張可直接複製到 LINE 對話框。
      </p>
      <div className="rounded-lg border bg-white overflow-hidden mb-4" style={{ borderColor: "#E1F5EE" }}>
        <div className="px-4 py-3 flex items-center justify-between border-b" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-stone-500" />
            <span className="text-xs font-medium">Agent 今日新增</span>
          </div>
          <span className="text-[10px] text-stone-500">最新索引結果</span>
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
        <button onClick={() => onSelect && onSelect(todays)} className="w-full px-4 py-3 border-t flex items-center justify-between hover:bg-[#E1F5EE] transition-colors group" style={{ borderColor: "#E1F5EE", color: "#0F6E56" }}>
          <div className="flex items-center gap-2">
            <MousePointerClick className="w-3.5 h-3.5" />
            <span className="text-sm font-medium">查看完整結果</span>
            <span className="text-[10px] text-stone-500">共 {todays.length} 筆</span>
          </div>
          <ArrowRight className="w-3 h-3 text-stone-500 group-hover:text-stone-900 group-hover:translate-x-0.5 transition-all" />
        </button>
        <div className="border-t flex" style={{ borderColor: "#E1F5EE" }}>
          <button onClick={() => onPreview(todays[0], todays)} className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#E1F5EE] transition-colors text-stone-600 hover:text-stone-900 border-r" style={{ borderColor: "#E1F5EE" }}>
            <Maximize2 className="w-3 h-3" />
            <span className="text-[11px]">預覽第一筆</span>
          </button>
          <button onClick={handleCopyAll} className="flex-1 px-4 py-2.5 flex items-center justify-center gap-1.5 hover:bg-[#E1F5EE] transition-colors" style={{ color: copiedAll ? "#1D9E75" : "#57534E" }}>
            {copiedAll ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
            <span className="text-[11px] font-medium">{copiedAll ? `已下載 ${todays.length} 筆` : `下載全部 (${todays.length})`}</span>
          </button>
        </div>
      </div>
      <p className="text-[10px] text-stone-500 leading-relaxed">今日新增資料由 Agent 索引結果產生，可直接預覽或下載圖片包。</p>
    </div>
  );
}

/* ===================================================================== */
/* SCHEDULE UNAVAILABLE MESSAGE                                           */
/* ===================================================================== */
function ScheduleUnavailableMessage({ action, requestedTimes }) {
  const times = Array.isArray(requestedTimes) ? requestedTimes : [];
  const actionLabel = action === "view" ? "查看排程" : action === "add" ? "新增排程" : action === "remove" ? "移除排程" : "設定排程";

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4" style={{ color: "#D97706" }} />
        <span className="text-sm font-medium">目前未啟用排程設定</span>
      </div>
      <div className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
        <div className="px-4 py-3 border-b" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <div className="flex items-center gap-2 mb-1.5">
            <Clock className="w-3 h-3 text-stone-500" />
            <span className="text-[10px] tracking-[0.15em] uppercase text-stone-500 font-medium">{actionLabel}</span>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {times.length > 0 ? times.map((time) => (
              <span key={time} className="text-xs font-medium tabular-nums px-2.5 py-1 rounded" style={{ backgroundColor: "#F9F9F9", color: "#0F6E56" }}>{time}</span>
            )) : <span className="text-xs text-stone-500">尚未指定時間</span>}
          </div>
        </div>
        <div className="px-4 py-3">
          <p className="text-xs text-stone-600 leading-relaxed">目前前台不直接修改排程；需要時請使用手動觸發抓取、OCR 與組圖流程。</p>
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
    return <p className="text-sm leading-relaxed text-stone-700">目前沒有需要審核的重複圖片。</p>;
  }

  return (
    <div>
      <p className="text-sm leading-relaxed text-stone-700 mb-4">
        發現 <span className="font-medium">{dups.length} 組</span> 可能重複圖片，可預覽後選擇保留或忽略。
      </p>
      <div className="space-y-3">
        {dups.map((dup, i) => (
          <div key={i} className="rounded-lg border bg-white overflow-hidden" style={{ borderColor: "#E1F5EE" }}>
            <div className="px-4 py-3 border-b" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Layers className="w-3.5 h-3.5 text-stone-500" />
                    <span className="text-xs font-medium">{dup.key}</span>
                  </div>
                  <div className="text-[10px] text-stone-500">來源：{dup.images.map((image) => image.source).join(" / ")}</div>
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
            <div className="px-4 py-3 flex gap-2 border-t" style={{ borderColor: "#E1F5EE" }}>
              <button onClick={() => onReviewDup?.(dup, 0, "keep_one")} className="flex-1 px-3 py-1.5 rounded-md text-xs font-medium" style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}>保留第一張</button>
              <button onClick={() => onReviewDup?.(dup, 0, "ignore")} className="flex-1 px-3 py-1.5 rounded-md text-xs border hover:border-stone-900 transition-colors" style={{ borderColor: "#E1F5EE" }}>忽略</button>
              <button onClick={() => onCompareDup(dup)} className="flex-1 px-3 py-1.5 rounded-md text-xs border hover:border-stone-900 transition-colors" style={{ borderColor: "#E1F5EE" }}>比較</button>
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
    <div className="fixed inset-0 z-50 animate-backdrop-in overflow-hidden" style={{ backgroundColor: "rgba(17,24,39,0.88)" }} onClick={onClose}>
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
        <button onClick={() => onCopy(current)} className="shrink-0 inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium" style={{ backgroundColor: copiedId === current.id ? "#1D9E75" : "#0F6E56", color: "#F9F9F9" }}>
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
  const [visibleCount, setVisibleCount] = useState(20);
  const visibleItems = items.slice(0, visibleCount);
  const remainingCount = Math.max(0, items.length - visibleItems.length);

  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    setVisibleCount(20);
  }, [items.length]);

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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-backdrop-in" style={{ backgroundColor: "rgba(17,24,39,0.68)" }} onClick={onClose}>
      <div className="w-full max-w-5xl max-h-[88vh] bg-white rounded-lg shadow-xl overflow-hidden animate-modal-in" onClick={(event) => event.stopPropagation()}>
        <div className="px-5 py-4 border-b flex items-center justify-between" style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}>
          <div>
            <div className="text-[10px] tracking-[0.2em] uppercase text-stone-500">選取圖片</div>
            <div className="text-sm font-medium">已選取 {selected.size} / {items.length} 筆</div>
          </div>
          <button onClick={onClose} className="p-2 rounded-md hover:bg-stone-200 transition-colors" aria-label="關閉">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5 overflow-y-auto max-h-[64vh] scrollbar-thin">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {visibleItems.map((dm) => {
              const isSelected = selected.has(dm.id);
              return (
                <button key={dm.id} onClick={() => toggle(dm.id)} className="relative rounded-md border overflow-hidden text-left bg-white" style={{ borderColor: isSelected ? "#0F6E56" : "#E1F5EE" }}>
                  <div className="bg-stone-100" style={{ aspectRatio: "827 / 1169" }}>
                    <DmImage dm={dm} alt={dm.title} className="w-full h-full object-cover" />
                  </div>
                  <div className="p-2">
                    <div className="text-[11px] font-medium truncate">{dm.title}</div>
                    <div className="text-[10px] text-stone-500 truncate">{dm.source}</div>
                  </div>
                  {isSelected && <div className="absolute top-2 right-2 rounded-full p-1" style={{ backgroundColor: "#0F6E56" }}><Check className="w-3 h-3" style={{ color: "#F9F9F9" }} /></div>}
                </button>
              );
            })}
          </div>
          {remainingCount > 0 && (
            <div className="mt-4 flex justify-center">
              <button
                onClick={() => setVisibleCount((value) => value + 20)}
                className="rounded-md border px-4 py-2 text-xs font-medium transition-colors hover:bg-[#E1F5EE]"
                style={{ borderColor: "#B8D9CE", color: "#0F6E56" }}
              >
                顯示更多 {Math.min(20, remainingCount)} 筆
              </button>
            </div>
          )}
        </div>
        <div className="px-5 py-4 border-t flex items-center justify-between gap-3" style={{ borderColor: "#E1F5EE" }}>
          <button onClick={() => setSelected(new Set())} className="px-3 py-2 rounded-md text-xs border" style={{ borderColor: "#E1F5EE" }}>清除</button>
          <button onClick={copySelected} disabled={selected.size === 0} className="inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium disabled:opacity-50" style={{ backgroundColor: copied ? "#1D9E75" : "#0F6E56", color: "#F9F9F9" }}>
            {copied ? <Check className="w-3 h-3" /> : <CopyPlus className="w-3 h-3" />}
            {copied ? "已下載" : "下載選取"}
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
      style={{ backgroundColor: "rgba(17,24,39,0.78)" }}
      onClick={onClose}
    >
      <div
        className="animate-modal-in bg-white rounded-lg max-w-6xl w-full max-h-[90vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-6 py-4 border-b flex items-center justify-between"
          style={{ borderColor: "#E1F5EE", backgroundColor: "#E1F5EE" }}
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
            以下為來自 <span className="font-medium">{data.count}</span> 個社群的重複圖片,
            判定依據:地區、期間、價格皆相同。請選擇保留版本,其餘將被歸檔。
          </p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {data.images.map((im, i) => {
              const selected = keepIdx === i;
              return (
                <div
                  key={i}
                  className="rounded-lg border-2 overflow-hidden transition-all cursor-pointer"
                  style={{
                    borderColor: selected ? "#0F6E56" : "#E1F5EE",
                    backgroundColor: selected ? "#E1F5EE" : "white",
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
                        style={{ backgroundColor: "#0F6E56" }}
                      >
                        <Check className="w-3.5 h-3.5" style={{ color: "#F9F9F9" }} />
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
          style={{ borderColor: "#E1F5EE" }}
        >
          <div className="text-xs text-stone-600">
            將保留:
            <span className="font-medium ml-1">{data.images[keepIdx].source}</span>
            <span className="text-stone-400 ml-2">
              其餘 {data.images.length - 1} 份歸檔
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-md text-xs border hover:border-stone-900 transition-colors"
              style={{ borderColor: "#E1F5EE" }}
            >
              取消
            </button>
            <button
              onClick={() => onReview?.(data, keepIdx, "ignore")}
              className="px-4 py-2 rounded-md text-xs border hover:border-stone-900 transition-colors"
              style={{ borderColor: "#E1F5EE" }}
            >
              不是重複
            </button>
            <button
              onClick={() => onReview?.(data, keepIdx, "keep_one")}
              className="px-4 py-2 rounded-md text-xs font-medium"
              style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
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

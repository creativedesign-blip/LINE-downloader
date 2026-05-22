import { tagValues } from "./tagUtils.js";

export default function TagBadgeList({ tags, emptyText = "雙擊新增", tone = "system", onRemove }) {
  const values = tagValues(tags);
  if (!values.length) return <span className="text-xs leading-4 text-stone-400">{emptyText}</span>;
  const badgeStyle = tone === "manual"
    ? { backgroundColor: "#F9F9F9", borderColor: "#1D9E75", color: "#0F6E56" }
    : { backgroundColor: "#E1F5EE", borderColor: "#1D9E75", color: "#0F6E56" };
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((tag) => (
        <span key={tag} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] leading-4" style={badgeStyle}>
          {tag}
          {onRemove && (
            <button type="button" onClick={() => onRemove(tag)} className="ml-0.5 text-current opacity-70 hover:opacity-100" aria-label={`刪除 ${tag}`}>
              ×
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

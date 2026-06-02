import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import TagBadgeList from "./TagBadgeList.jsx";
import {
  SYSTEM_TAGS_CLEARED_SENTINEL,
  imageTagValues,
  tagValues,
} from "./tagUtils.js";

export function formatMetadataDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-TW", { hour12: false });
}

export function metadataSourceKindLabel(sourceKind) {
  if (sourceKind === "upload" || sourceKind === "upload_catalog") return "上傳圖片";
  if (sourceKind === "line" || sourceKind === "line-auto") return "LINE 自動爬取";
  return "未知來源";
}

export function preferredMetadataTime(image) {
  const sourceKind = image?.source_kind || image?.sourceKind || image?.source || "";
  if (sourceKind === "upload" || sourceKind === "upload_catalog") {
    return image?.uploaded_at || image?.source_time || image?.indexed_at || "";
  }
  return image?.source_time || image?.uploaded_at || image?.indexed_at || "";
}

function emptyValue(value) {
  return value ? String(value) : "未提供";
}

function DetailRow({ label, value }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-2 text-xs">
      <div className="text-stone-500">{label}</div>
      <div className="min-w-0 break-words text-stone-900">{emptyValue(value)}</div>
    </div>
  );
}

function SectionTitle({ children }) {
  return <div className="text-[10px] tracking-[0.15em] uppercase text-stone-500">{children}</div>;
}

export default function ImageMetadataPanel({
  image,
  mode = "view",
  showManualNote,
  systemTagField = "ocr_tags_override",
  onAddTag,
  onDeleteTag,
  onUpdateImage,
  onSaved,
}) {
  const editable = mode === "edit";
  const shouldShowManualNote = showManualNote ?? editable;
  const [ocrTags, setOcrTags] = useState(imageTagValues(image));
  const [manualTags, setManualTags] = useState(tagValues(image?.manual_tags || []));
  const [referenceText, setReferenceText] = useState(image?.reference_text || "");
  const [manualNote, setManualNote] = useState(image?.manual_note || "");
  const [tagDraft, setTagDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setOcrTags(imageTagValues(image));
    setManualTags(tagValues(image?.manual_tags || []));
    setReferenceText(image?.reference_text || "");
    setManualNote(image?.manual_note || "");
    setTagDraft("");
    setSaving(false);
  }, [image?.id, image?.image_id, image?.source_key]);

  const parsedOverrideTags = () => {
    const values = tagValues(ocrTags);
    const sourceTagCount = imageTagValues({ ...image, ocr_tags_override: [] }).length;
    if (!values.length && sourceTagCount > 0) return [SYSTEM_TAGS_CLEARED_SENTINEL];
    return values;
  };

  const removeOcrOverrideTag = (tagToRemove) => {
    if (!editable) return;
    setOcrTags((current) => current.filter((tag) => tag !== tagToRemove));
  };

  const addManualTag = () => {
    if (!editable) return;
    const value = tagDraft.trim();
    if (!value) return;
    if (onAddTag) {
      onAddTag(image.id || image.image_id, value);
    } else {
      setManualTags((current) => current.includes(value) ? current : [...current, value]);
    }
    setTagDraft("");
  };
  const removeManualTag = (tag) => {
    if (!editable) return;
    if (onDeleteTag) {
      const matched = (image?.manual_tags || []).find((item) => item.tag === tag);
      if (matched) onDeleteTag(matched.id);
      return;
    }
    setManualTags((current) => current.filter((value) => value !== tag));
  };

  const saveMetadata = async () => {
    if (!editable || !onUpdateImage) return;
    const persistedManualTags = onAddTag || onDeleteTag ? image?.manual_tags || [] : manualTags;
    setSaving(true);
    try {
      await onUpdateImage(image.id || image.image_id, {
        [systemTagField]: parsedOverrideTags(),
        manual_tags: tagValues(persistedManualTags),
        reference_text: referenceText,
        manual_note: manualNote,
      });
      setSaving(false);
      onSaved?.();
    } catch (error) {
      setSaving(false);
      throw error;
    }
  };

  const sourceKind = image?.source_kind || image?.sourceKind || image?.source || "";
  const sourceType = metadataSourceKindLabel(sourceKind);
  const sourceName = image?.source_label || image?.group_name || image?.target_id || image?.folder_name || image?.folder_slug || "";
  const sourceTime = formatMetadataDateTime(preferredMetadataTime(image));
  const filename = image?.original_filename || image?.display_name || "";

  return (
    <div className="space-y-5">
      <section className="space-y-2 border-b pb-4" style={{ borderColor: "#E1F5EE" }}>
        <SectionTitle>來源區</SectionTitle>
        <DetailRow label="來源類型" value={sourceType} />
        <DetailRow label="來源名稱" value={sourceName} />
        <DetailRow label="時間" value={sourceTime} />
        <DetailRow label="檔名" value={filename} />
      </section>

      <section className="space-y-4 border-b pb-4" style={{ borderColor: "#E1F5EE" }}>
        <SectionTitle>標籤區</SectionTitle>
        <div>
          <div className="mb-2 text-xs font-medium text-stone-900">系統標籤</div>
          <div className="rounded-md border px-3 py-2" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
            <TagBadgeList
              tags={ocrTags}
              tone="system"
              emptyText="尚無系統標籤"
              onRemove={editable ? removeOcrOverrideTag : undefined}
            />
          </div>
        </div>

        <div>
          <div className="mb-2 text-xs font-medium text-stone-900">人工標籤</div>
          <div className="space-y-3">
            <div className="rounded-md border px-3 py-2" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
              <TagBadgeList
                tags={onAddTag || onDeleteTag ? image?.manual_tags || [] : manualTags}
                tone="manual"
                emptyText="尚無人工標籤"
                onRemove={editable ? removeManualTag : undefined}
              />
            </div>
            {editable && (
              <div className="flex gap-2">
                <input
                  value={tagDraft}
                  onChange={(event) => setTagDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      if (event.nativeEvent.isComposing || event.keyCode === 229) return; // IME 組字中
                      event.preventDefault();
                      addManualTag();
                    }
                  }}
                  className="min-w-0 flex-1 h-9 rounded-md border px-3 text-sm outline-none"
                  style={{ borderColor: "#E1F5EE" }}
                  placeholder="輸入人工標籤後按 Enter"
                />
                <button
                  type="button"
                  onClick={addManualTag}
                  className="h-9 rounded-md px-3 text-xs"
                  style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
                >
                  新增
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <SectionTitle>文案區</SectionTitle>
        <label className="block">
          <span className="text-xs font-medium text-stone-900">來源文案</span>
          {editable ? (
            <textarea
              value={referenceText}
              onChange={(event) => setReferenceText(event.target.value)}
              className="mt-2 w-full rounded-md border px-3 py-2 text-sm leading-relaxed outline-none resize-y"
              style={{ borderColor: "#E1F5EE", minHeight: "10rem" }}
              rows={8}
              placeholder="貼上原始 LINE 文案或補充說明"
            />
          ) : (
            <div className="mt-2 min-h-24 whitespace-pre-wrap rounded-md border px-3 py-2 text-sm leading-relaxed text-stone-800" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
              {referenceText || "未提供"}
            </div>
          )}
        </label>

        {shouldShowManualNote && (
          <label className="block">
            <span className="text-xs font-medium text-stone-900">人工備註</span>
            {editable ? (
              <textarea
                value={manualNote}
                onChange={(event) => setManualNote(event.target.value)}
                className="mt-2 w-full rounded-md border px-3 py-2 text-sm leading-relaxed outline-none resize-y"
                style={{ borderColor: "#E1F5EE", minHeight: "6rem" }}
                rows={4}
                placeholder="補充搜尋線索、注意事項或修正說明"
              />
            ) : (
              <div className="mt-2 min-h-16 whitespace-pre-wrap rounded-md border px-3 py-2 text-sm leading-relaxed text-stone-800" style={{ borderColor: "#E1F5EE", backgroundColor: "#FFFFFF" }}>
                {manualNote || "未提供"}
              </div>
            )}
          </label>
        )}
      </section>

      {editable && (
        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={saveMetadata}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-60"
            style={{ backgroundColor: "#0F6E56", color: "#F9F9F9" }}
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {saving ? "儲存中" : "儲存"}
          </button>
        </div>
      )}
    </div>
  );
}

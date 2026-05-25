async function readJson(response, fallbackMessage) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.error || fallbackMessage);
  }
  return payload;
}

function imageFormData(files) {
  const form = new FormData();
  Array.from(files || []).forEach((file) => form.append("images", file));
  return form;
}

export const uploadApi = {
  async listFolders(limit = 30) {
    const response = await fetch(`/api/uploads/folders?limit=${limit}`);
    const payload = await readJson(response, "folders failed");
    return Array.isArray(payload.folders) ? payload.folders : [];
  },

  async getFolder(folderId, filters = {}) {
    const params = new URLSearchParams();
    if (filters.uploadedFrom) params.set("uploaded_from", filters.uploadedFrom);
    if (filters.uploadedTo) params.set("uploaded_to", filters.uploadedTo);
    const query = params.toString();
    const response = await fetch(`/api/uploads/folders/${folderId}${query ? `?${query}` : ""}`);
    return readJson(response, "folder detail failed");
  },

  async createFolder({ displayName, note = "" }) {
    const response = await fetch("/api/uploads/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName.trim(), note: String(note || "").trim() }),
    });
    return readJson(response, "建立資料夾失敗");
  },

  async uploadImages(folderId, files) {
    const response = await fetch(`/api/uploads/folders/${folderId}/images`, {
      method: "POST",
      body: imageFormData(files),
    });
    return readJson(response, "圖片上傳失敗");
  },

  async uploadToNewFolder({ displayName, note = "", files }) {
    const folderPayload = await this.createFolder({ displayName, note });
    const uploadPayload = await this.uploadImages(folderPayload.folder.id, files);
    return { ...uploadPayload, folder: folderPayload.folder };
  },

  async uploadToExistingFolder({ folderId, files }) {
    return this.uploadImages(folderId, files);
  },

  async addManualTag(imageId, tag) {
    const response = await fetch(`/api/uploads/images/${imageId}/manual-tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: String(tag || "").trim() }),
    });
    return readJson(response, "tag failed");
  },

  async deleteManualTag(tagId) {
    const response = await fetch(`/api/uploads/manual-tags/${tagId}`, { method: "DELETE" });
    return readJson(response, "delete tag failed");
  },

  async updateManualTag(tagId, tag) {
    const response = await fetch(`/api/uploads/manual-tags/${tagId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: String(tag || "").trim() }),
    });
    return readJson(response, "update tag failed");
  },

  async updateImage(imageId, data) {
    const response = await fetch(`/api/uploads/images/${imageId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    return readJson(response, "update image failed");
  },

  async archiveImage(imageId) {
    const response = await fetch(`/api/uploads/images/${imageId}`, { method: "DELETE" });
    return readJson(response, "archive image failed");
  },

  async archiveFolder(folderId) {
    const response = await fetch(`/api/uploads/folders/${folderId}`, { method: "DELETE" });
    return readJson(response, "archive folder failed");
  },

  async retryFolder(folderId) {
    const response = await fetch(`/api/uploads/folders/${folderId}/retry`, { method: "POST" });
    return readJson(response, "retry folder failed");
  },

  async markFolderFailed(folderId) {
    const response = await fetch(`/api/uploads/folders/${folderId}/mark-failed`, { method: "POST" });
    return readJson(response, "mark folder failed");
  },

  async downloadFolder(folderId, filters = {}) {
    const response = await fetch(`/api/uploads/folders/${folderId}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_ids: filters.imageIds || [],
        uploaded_from: filters.uploadedFrom || "",
        uploaded_to: filters.uploadedTo || "",
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.error || "download folder failed");
    }
    const blob = await response.blob();
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `upload-folder-${folderId}-${stamp}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return { ok: true };
  },
};

export const openclawApi = {
  async getSettings() {
    const response = await fetch("/api/openclaw/settings");
    return response.json();
  },

  async updateSettings(settings) {
    const response = await fetch("/api/openclaw/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    return readJson(response, "settings failed");
  },
};

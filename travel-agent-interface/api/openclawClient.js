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

  async getFolder(folderId) {
    const response = await fetch(`/api/uploads/folders/${folderId}`);
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

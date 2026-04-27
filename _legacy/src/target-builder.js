const path = require('path');

function safeId(value) {
  const cleaned = String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
  return cleaned || `group-${Date.now()}`;
}

function buildTargetFromPage(summary, { id, label } = {}) {
  const resolvedId = safeId(id);
  const primaryName = summary.chatroomName
    || summary.selectedChatTitle
    || summary.headerTexts?.[0]
    || resolvedId;
  const displayLabel = label || primaryName || resolvedId;
  const groupName = primaryName || displayLabel;
  const headerTexts = [
    summary.chatroomName,
    summary.selectedChatTitle,
    ...(summary.headerTexts || []),
  ].filter(Boolean).slice(0, 8);
  const urlHost = (() => {
    try {
      return new URL(summary.url).hostname;
    } catch {
      return 'line.me';
    }
  })();

  return {
    id: resolvedId,
    label: displayLabel,
    groupName,
    downloadDir: path.join('downloads', resolvedId, 'inbox'),
    travelDir: path.join('downloads', resolvedId, 'travel'),
    otherDir: path.join('downloads', resolvedId, 'other'),
    errorDir: path.join('downloads', resolvedId, 'error'),
    pageFingerprint: {
      titleIncludes: summary.title || 'LINE',
      urlIncludes: urlHost,
    },
    groupFingerprint: {
      chatId: summary.chatId || '',
      chatroomName: summary.chatroomName || '',
      selectedChatTitle: summary.selectedChatTitle || '',
      selectedChatDescription: summary.selectedChatDescription || '',
      headerText: summary.chatroomName || summary.selectedChatTitle || headerTexts[0] || '',
      subtitleText: summary.selectedChatDescription || headerTexts[1] || '',
      headerTexts,
      avatarUrl: summary.avatarUrl || '',
    },
    enabled: true,
  };
}

module.exports = {
  safeId,
  buildTargetFromPage,
};

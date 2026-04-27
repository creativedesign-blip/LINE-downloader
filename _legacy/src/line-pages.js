function normalizeText(value) {
  return (value || '').replace(/\s+/g, ' ').trim();
}

async function inspectPage(page) {
  const summary = await page.evaluate(() => {
    const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
    const getChatId = () => {
      const hash = window.location.hash || '';
      const match = hash.match(/#\/chats\/([^/?#]+)/);
      return match ? decodeURIComponent(match[1]) : '';
    };
    const isVisible = element => {
      if (!element) return false;
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' &&
        style.display !== 'none' &&
        rect.width > 0 &&
        rect.height > 0;
    };

    const getChatroomName = () => {
      const selectors = [
        '[class*="chatroomHeader-module__name"]',
        '[class*="chatroomHeader-module__button_name"]',
        '[class*="chatroomHeader-module__info"]',
      ];
      for (const selector of selectors) {
        const el = document.querySelector(selector);
        const text = normalize(el && (el.innerText || el.textContent));
        if (text) return text;
      }
      return '';
    };

    const getSelectedChatItem = () => {
      const items = Array.from(document.querySelectorAll('[class*="chatlistItem-module__chatlist_item"]'));
      const active = items.find(el => el.getAttribute('aria-current') === 'true') || null;
      if (!active) return null;
      const titleEl =
        active.querySelector('[class*="chatlistItem-module__title_box"]') ||
        active.querySelector('strong') ||
        active.querySelector('[class*="chatlistItem-module__text"]');
      const descEl = active.querySelector('[class*="chatlistItem-module__description"]');
      return {
        title: normalize(titleEl && (titleEl.innerText || titleEl.textContent)),
        description: normalize(descEl && (descEl.innerText || descEl.textContent)),
        text: normalize(active.innerText || active.textContent),
      };
    };

    const getVisibleChatTitles = () => {
      const titles = [];
      const seen = new Set();
      const titleEls = Array.from(document.querySelectorAll('[class*="chatlistItem-module__title_box"]'));
      for (const el of titleEls) {
        if (!isVisible(el)) continue;
        const rect = el.getBoundingClientRect();
        if (rect.left >= window.innerWidth * 0.55) continue;
        const text = normalize(el.innerText || el.textContent);
        if (!text || seen.has(text)) continue;
        seen.add(text);
        titles.push(text);
        if (titles.length >= 12) break;
      }
      return titles;
    };

    const nodes = Array.from(document.querySelectorAll('body *'));
    const texts = [];
    const seen = new Set();

    for (const el of nodes) {
      if (!isVisible(el)) continue;
      const rect = el.getBoundingClientRect();
      if (rect.top > 260 || rect.bottom < 0) continue;
      const text = normalize(el.innerText || el.textContent || '');
      if (!text || text.length > 80 || seen.has(text)) continue;
      seen.add(text);
      texts.push(text);
      if (texts.length >= 12) break;
    }

    const image = Array.from(document.images).find(img => {
      const rect = img.getBoundingClientRect();
      return rect.top <= 260 && rect.bottom >= 0 && img.src;
    });

    const selectedChat = getSelectedChatItem();

    return {
      title: document.title || '',
      url: location.href,
      chatId: getChatId(),
      chatroomName: getChatroomName(),
      selectedChatTitle: selectedChat ? selectedChat.title : '',
      selectedChatDescription: selectedChat ? selectedChat.description : '',
      selectedChatText: selectedChat ? selectedChat.text : '',
      visibleChatTitles: getVisibleChatTitles(),
      headerTexts: texts,
      avatarUrl: image ? image.currentSrc || image.src : '',
    };
  });

  return {
    page,
    title: normalizeText(summary.title),
    url: summary.url,
    chatId: normalizeText(summary.chatId),
    chatroomName: normalizeText(summary.chatroomName),
    selectedChatTitle: normalizeText(summary.selectedChatTitle),
    selectedChatDescription: normalizeText(summary.selectedChatDescription),
    selectedChatText: normalizeText(summary.selectedChatText),
    visibleChatTitles: Array.isArray(summary.visibleChatTitles) ? summary.visibleChatTitles.map(normalizeText).filter(Boolean) : [],
    headerTexts: Array.isArray(summary.headerTexts) ? summary.headerTexts.map(normalizeText).filter(Boolean) : [],
    avatarUrl: summary.avatarUrl || '',
  };
}

function isLikelyLinePage(summary) {
  const haystack = `${summary.title} ${summary.url}`.toLowerCase();
  return haystack.includes('line') || haystack.includes('line.me');
}

async function getLinePages(browser) {
  const pages = [];
  for (const context of browser.contexts()) {
    for (const page of context.pages()) {
      const summary = await inspectPage(page);
      if (isLikelyLinePage(summary)) {
        pages.push(summary);
      }
    }
  }
  return pages;
}

function overlapCount(left = [], right = []) {
  const rightSet = new Set(right.map(value => value.toLowerCase()));
  let count = 0;
  for (const item of left) {
    if (rightSet.has(item.toLowerCase())) {
      count += 1;
    }
  }
  return count;
}

function scoreTargetMatch(summary, target) {
  let score = 0;
  const titleIncludes = target.pageFingerprint?.titleIncludes || '';
  const urlIncludes = target.pageFingerprint?.urlIncludes || '';
  const groupName = target.groupName || '';
  const headerText = target.groupFingerprint?.headerText || '';
  const headerTexts = target.groupFingerprint?.headerTexts || [];
  const subtitleText = target.groupFingerprint?.subtitleText || '';
  const chatId = target.groupFingerprint?.chatId || '';
  const chatroomName = target.groupFingerprint?.chatroomName || '';
  const selectedChatTitle = target.groupFingerprint?.selectedChatTitle || '';
  const selectedChatDescription = target.groupFingerprint?.selectedChatDescription || '';

  if (titleIncludes && summary.title.includes(titleIncludes)) score += 3;
  if (urlIncludes && summary.url.includes(urlIncludes)) score += 3;
  if (chatId && summary.chatId === chatId) score += 100;
  if (chatroomName && summary.chatroomName === chatroomName) score += 25;
  if (selectedChatTitle && summary.selectedChatTitle === selectedChatTitle) score += 20;
  if (selectedChatDescription && summary.selectedChatDescription === selectedChatDescription) score += 6;
  if (groupName && (summary.chatroomName.includes(groupName) || summary.selectedChatTitle.includes(groupName) || summary.headerTexts.some(text => text.includes(groupName)))) score += 12;
  if (headerText && (summary.chatroomName === headerText || summary.selectedChatTitle === headerText || summary.headerTexts.some(text => text === headerText))) score += 10;
  if (subtitleText && (summary.selectedChatDescription === subtitleText || summary.headerTexts.some(text => text === subtitleText))) score += 8;
  score += overlapCount(summary.headerTexts, headerTexts) * 5;
  score += overlapCount(summary.visibleChatTitles, headerTexts) * 2;
  return score;
}

function describePage(summary, index) {
  const chatLabel = summary.chatroomName || summary.selectedChatTitle;
  const headerPreview = chatLabel || summary.headerTexts.slice(0, 3).join(' | ') || '(no visible header text)';
  const detail = summary.selectedChatDescription || summary.headerTexts.slice(1, 3).join(' | ');
  const idPreview = summary.chatId ? ` [chatId:${summary.chatId}]` : '';
  return `[${index}] ${summary.title || '(untitled)'} | ${summary.url}${idPreview}\n    ${headerPreview}${detail ? ` | ${detail}` : ''}`;
}

module.exports = {
  inspectPage,
  getLinePages,
  scoreTargetMatch,
  describePage,
};

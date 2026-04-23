// Per-process 單一掃描分頁：所有 target 共用，依序導航。
// Operator 自己開的 LINE 分頁不受影響（我們只持有自己 new 出來的分頁 ref）。

const { getLinePages } = require('./line-pages');

let scannerPage = null;
let navChain = Promise.resolve();
let browserSubscribedFor = null;

function getLineExtensionIdFromUrl(url) {
  const match = String(url || '').match(/^chrome-extension:\/\/([^/]+)\/index\.html/i);
  return match ? match[1] : '';
}

function getLineExtensionId(target, pages = []) {
  const configured = target?.pageFingerprint?.urlIncludes || '';
  if (/^[a-z]{32}$/i.test(configured)) return configured;
  for (const page of pages) {
    const id = getLineExtensionIdFromUrl(page.url);
    if (id) return id;
  }
  return '';
}

function getTargetChatUrl(target, pages = []) {
  const chatId = target.groupFingerprint?.chatId || '';
  if (!chatId) {
    throw new Error(`Target "${target.id}" has no chatId.`);
  }
  const extensionId = getLineExtensionId(target, pages);
  if (!extensionId) {
    throw new Error('LINE Chrome extension page not found. Open LINE in the automation Chrome first.');
  }
  return `chrome-extension://${extensionId}/index.html#/chats/${encodeURIComponent(chatId)}`;
}

function getLineHomeUrl(pages = []) {
  for (const page of pages) {
    const extensionId = getLineExtensionIdFromUrl(page.url);
    if (extensionId) {
      return `chrome-extension://${extensionId}/index.html#/chats`;
    }
  }
  return 'https://line.me/R/';
}

function withNavLock(fn) {
  const next = navChain.then(fn, fn);
  navChain = next.catch(() => {});
  return next;
}

function urlMatchesChatId(currentUrl, chatId) {
  if (!currentUrl || !chatId) return false;
  return currentUrl.includes(chatId) || currentUrl.includes(encodeURIComponent(chatId));
}

function subscribeDisconnect(browser) {
  if (browserSubscribedFor === browser) return;
  browserSubscribedFor = browser;
  browser.once('disconnected', () => {
    scannerPage = null;
    browserSubscribedFor = null;
  });
}

async function ensureScannerPage(browser) {
  if (scannerPage && !scannerPage.isClosed()) return scannerPage;
  const context = browser.contexts()[0];
  if (!context) throw new Error('No Chrome browser context found.');
  scannerPage = await context.newPage();
  scannerPage.once('close', () => { scannerPage = null; });
  subscribeDisconnect(browser);
  return scannerPage;
}

async function navigateToTarget(browser, target, options = {}) {
  return withNavLock(async () => {
    const pages = await getLinePages(browser);
    const url = getTargetChatUrl(target, pages);
    const chatId = target.groupFingerprint?.chatId || '';
    const page = await ensureScannerPage(browser);

    const needsNav = !urlMatchesChatId(page.url() || '', chatId);
    if (needsNav) {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      // chrome-extension SPA 的 hash change 不觸發 network load，domcontentloaded 立刻回來。
      // 等 React 把舊 chat 拆掉、新 chat 的訊息容器 render 出來。
      await page.waitForFunction(
        expected => location.hash.includes(expected),
        chatId,
        { timeout: 10000 }
      );
      await page.waitForSelector('[class*="chatroom"], [class*="message"]', { timeout: 10000 });
    }
    if (options.focus) {
      await page.bringToFront();
    }
    return { page, url, chatId, navigated: needsNav };
  });
}

async function closeScannerTab() {
  if (scannerPage && !scannerPage.isClosed()) {
    try { await scannerPage.close(); } catch {}
  }
  scannerPage = null;
}

module.exports = {
  navigateToTarget,
  closeScannerTab,
  getLineHomeUrl,
  getLineExtensionIdFromUrl,
};

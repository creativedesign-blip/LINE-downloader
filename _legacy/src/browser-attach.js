const { chromium } = require('playwright');

const DEFAULT_CDP_URL = 'http://127.0.0.1:9333';

const sharedBrowsers = new Map();
const inFlight = new Map();

function buildConnectError(cdpUrl, error) {
  return new Error(
    `無法連到 Chromium CDP: ${cdpUrl}\n` +
    '請先用支援 remote debugging 的方式啟動 Chrome/Chromium，例如：\n' +
    'chrome.exe --remote-debugging-port=9333\n' +
    `原始錯誤: ${error.message}`
  );
}

async function getSharedBrowser(cdpUrl = DEFAULT_CDP_URL) {
  const existing = sharedBrowsers.get(cdpUrl);
  if (existing && existing.isConnected()) return existing;
  if (existing) sharedBrowsers.delete(cdpUrl);

  const pending = inFlight.get(cdpUrl);
  if (pending) return pending;

  const connection = (async () => {
    try {
      const browser = await chromium.connectOverCDP(cdpUrl);
      browser.on('disconnected', () => {
        if (sharedBrowsers.get(cdpUrl) === browser) {
          sharedBrowsers.delete(cdpUrl);
        }
      });
      sharedBrowsers.set(cdpUrl, browser);
      return browser;
    } catch (error) {
      throw buildConnectError(cdpUrl, error);
    } finally {
      inFlight.delete(cdpUrl);
    }
  })();
  inFlight.set(cdpUrl, connection);
  return connection;
}

async function connectBrowser(cdpUrl = DEFAULT_CDP_URL) {
  return getSharedBrowser(cdpUrl);
}

async function closeSharedBrowsers() {
  const all = [...sharedBrowsers.values()];
  sharedBrowsers.clear();
  await Promise.allSettled(all.map(browser => browser.close()));
}

module.exports = {
  DEFAULT_CDP_URL,
  connectBrowser,
  getSharedBrowser,
  closeSharedBrowsers,
};

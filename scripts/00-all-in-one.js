/* =====================================================================
 * LINE Chrome 擴充 — 圖片批次下載（無 UI，純後台 scan + download）
 * ---------------------------------------------------------------------
 * 五個來源：IndexedDB / Cache Storage / OPFS / performance / DOM
 * 流程：scan → dedup (fp + aliases) → 過濾 MIN_SIZE → deselect by seenKeys → download
 * 對外 API：window.__LDL_RUN__({ seenKeys }) — 回傳最終 state 快照
 * State：window.__LDL_STATE__（bridge 讀取用）
 * ===================================================================== */
(() => {
  if (window.__LINE_DL_ACTIVE__) return;
  window.__LINE_DL_ACTIVE__ = true;

  // 兩邊必須同步：bridge 注入時塞 window.__LDL_PHASES__ / __LDL_SCAN_PROFILES__，值來自 _legacy/src/phases.js
  const PHASES = window.__LDL_PHASES__ || {
    IDLE: 'idle',
    SCANNING: 'scanning',
    READY: 'ready',
    EMPTY: 'empty',
    DOWNLOADING: 'downloading',
    DONE: 'done',
    ERROR: 'error',
  };
  const SCAN_PROFILES = window.__LDL_SCAN_PROFILES__ || {
    FULL: 'full',
    WATCH_FAST: 'watch-fast',
  };
  const AUTOMATION_MODE = !!window.__LDL_AUTOMATION__;
  const DEFAULT_SCAN_PROFILE = window.__LDL_SCAN_PROFILE__ || SCAN_PROFILES.FULL;

  window.__LDL_STATE__ = {
    phase: PHASES.IDLE,
    automation: AUTOMATION_MODE,
    scanProfile: DEFAULT_SCAN_PROFILE,
    error: null,
    candidateCount: 0,
    selectedCount: 0,
    downloadedCount: 0,
    failedCount: 0,
    summaryCounts: { idb: 0, cache: 0, opfs: 0, perf: 0, dom: 0, deduped: 0 },
    gridSourceCounts: {},
    selectedKeys: [],
    downloadedKeys: [],
    failedKeys: [],
    failedDetails: [],
    savedFiles: [],
    cycleStartedAt: null,
    completedAt: null,
  };

  const CONFIG = {
    MIN_SIZE: 150,
    DOWNLOAD_DELAY_MS: 250,
    WORK_CHUNK_SIZE: 12,
    FILENAME_PREFIX: 'line',
    EXCLUDE_URL_SUBSTRINGS: [],
    MIN_BLOB_SIZE: 512,
  };

  function setRuntimeState(patch) {
    Object.assign(window.__LDL_STATE__, patch);
    return window.__LDL_STATE__;
  }

  // ---------- 工具 ----------
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  function yieldToUI() {
    return new Promise(resolve => {
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => resolve());
      else setTimeout(resolve, 0);
    });
  }

  function inferImageMime(bytes) {
    if (!bytes || bytes.length < 12) return null;
    if (bytes[0] === 0xFF && bytes[1] === 0xD8 && bytes[2] === 0xFF) return 'image/jpeg';
    if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4E && bytes[3] === 0x47 &&
        bytes[4] === 0x0D && bytes[5] === 0x0A && bytes[6] === 0x1A && bytes[7] === 0x0A) return 'image/png';
    if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x38) return 'image/gif';
    if (bytes[0] === 0x42 && bytes[1] === 0x4D) return 'image/bmp';
    if (bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
        bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) return 'image/webp';
    return null;
  }

  // ---------- 掃描：IndexedDB ----------
  async function scanIndexedDB(lightMode) {
    const results = [];
    if (lightMode) return results;
    if (!indexedDB.databases) return results;
    const dbs = await indexedDB.databases();
    for (const { name } of dbs) {
      if (!name) continue;
      let db;
      try {
        db = await new Promise((resolve, reject) => {
          const req = indexedDB.open(name);
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => reject(req.error);
          req.onblocked = () => reject(new Error('blocked'));
        });
      } catch { continue; }
      const stores = Array.from(db.objectStoreNames);
      for (const storeName of stores) {
        try {
          const tx = db.transaction(storeName, 'readonly');
          const store = tx.objectStore(storeName);
          await new Promise((resolve) => {
            const req = store.openCursor();
            req.onsuccess = () => {
              const cursor = req.result;
              if (!cursor) return resolve();
              try { walkForBlobs(cursor.value, blob => {
                if (blob.size < CONFIG.MIN_BLOB_SIZE) return;
                const typeOk = blob.type ? blob.type.startsWith('image/') : true;
                if (!typeOk) return;
                results.push({ blob, source: `idb:${name}/${storeName}` });
              }, new Set()); } catch {}
              cursor.continue();
            };
            req.onerror = () => resolve();
          });
        } catch {}
      }
      try { db.close(); } catch {}
    }
    return results;
  }

  function walkForBlobs(v, cb, visited) {
    if (!v || typeof v !== 'object') return;
    if (visited.has(v)) return;
    visited.add(v);
    if (v instanceof Blob) { cb(v); return; }
    if (v instanceof ArrayBuffer) {
      const bytes = new Uint8Array(v);
      const mime = inferImageMime(bytes);
      if (!mime) return;
      cb(new Blob([bytes], { type: mime }));
      return;
    }
    if (ArrayBuffer.isView(v)) {
      const bytes = new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
      const mime = inferImageMime(bytes);
      if (!mime) return;
      cb(new Blob([bytes], { type: mime }));
      return;
    }
    if (Array.isArray(v)) { for (const x of v) walkForBlobs(x, cb, visited); return; }
    for (const k of Object.keys(v)) {
      try { walkForBlobs(v[k], cb, visited); } catch {}
    }
  }

  // ---------- 掃描：Cache Storage（watch-fast 也掃；LINE 原圖多半在這）----------
  async function scanCacheStorage() {
    const results = [];
    if (!window.caches) return results;
    const names = await caches.keys();
    for (const name of names) {
      const cache = await caches.open(name);
      const reqs = await cache.keys();
      for (const req of reqs) {
        try {
          const resp = await cache.match(req);
          if (!resp) continue;
          const ct = (resp.headers.get('content-type') || '').toLowerCase();
          const looksImage = ct.startsWith('image/');
          const ambiguousType = !ct || ct.includes('octet-stream') || ct.startsWith('application/');
          if (!looksImage && !ambiguousType) continue;
          const rawBlob = await resp.blob();
          if (rawBlob.size < CONFIG.MIN_BLOB_SIZE) continue;
          let blob = rawBlob;
          if (!looksImage) {
            const head = new Uint8Array(await rawBlob.slice(0, 12).arrayBuffer());
            const sniffed = inferImageMime(head);
            if (!sniffed) continue;
            blob = new Blob([await rawBlob.arrayBuffer()], { type: sniffed });
          }
          results.push({ blob, source: `cache:${name}`, url: req.url });
        } catch {}
      }
    }
    return results;
  }

  // ---------- 掃描：Performance Resources（對應 DevTools Application → Images）----------
  function scanPerformanceUrls() {
    const results = [];
    if (!performance || !performance.getEntriesByType) return results;
    const entries = performance.getEntriesByType('resource');
    const imageExt = /\.(jpe?g|png|gif|webp|bmp)(\?.*)?$/i;
    const seen = new Set();
    for (const e of entries) {
      const url = e.name;
      if (!url || url.startsWith('data:')) continue;
      const isImg = e.initiatorType === 'img' || imageExt.test(url);
      if (!isImg) continue;
      const lower = url.toLowerCase();
      if (CONFIG.EXCLUDE_URL_SUBSTRINGS.some(p => lower.includes(p))) continue;
      if (seen.has(url)) continue;
      seen.add(url);
      results.push({ blob: null, url, source: 'perf' });
    }
    return results;
  }

  // ---------- 掃描：OPFS ----------
  async function scanOPFS(lightMode) {
    const results = [];
    if (lightMode) return results;
    if (!navigator.storage || !navigator.storage.getDirectory) return results;
    let root;
    try { root = await navigator.storage.getDirectory(); } catch { return results; }
    async function walk(dir, prefix) {
      for await (const [name, handle] of dir.entries()) {
        const fullPath = prefix + '/' + name;
        if (handle.kind === 'directory') {
          try { await walk(handle, fullPath); } catch {}
        } else if (handle.kind === 'file') {
          if (!/\.(jpe?g|png|gif|webp|bmp)$/i.test(name)) continue;
          try {
            const file = await handle.getFile();
            if (file.size < CONFIG.MIN_BLOB_SIZE) continue;
            results.push({ blob: file, source: `opfs:${fullPath}` });
          } catch {}
        }
      }
    }
    try { await walk(root, ''); } catch {}
    return results;
  }

  // ---------- 掃描：DOM ----------
  function scanDOM() {
    const out = [];
    const seen = new Set();
    const root = findChatScroller() || document.body;
    const push = item => {
      if (!item || !item.url || seen.has(item.url)) return;
      seen.add(item.url);
      out.push(item);
    };

    for (const img of root.querySelectorAll('img')) {
      const rect = img.getBoundingClientRect();
      const w = img.naturalWidth || rect.width;
      const h = img.naturalHeight || rect.height;
      if (w < CONFIG.MIN_SIZE || h < CONFIG.MIN_SIZE) continue;
      const src = img.currentSrc || img.src;
      if (!src || src.startsWith('data:')) continue;
      const lower = src.toLowerCase();
      if (CONFIG.EXCLUDE_URL_SUBSTRINGS.some(p => lower.includes(p))) continue;
      push({ url: src, w: Math.round(w), h: Math.round(h), source: 'dom' });
    }

    for (const el of root.querySelectorAll('*')) {
      const rect = el.getBoundingClientRect();
      if (rect.width < CONFIG.MIN_SIZE || rect.height < CONFIG.MIN_SIZE) continue;
      const bg = getComputedStyle(el).backgroundImage;
      if (!bg || bg === 'none') continue;
      const matches = bg.matchAll(/url\(["']?([^"')]+)["']?\)/g);
      for (const match of matches) {
        const src = match[1];
        if (!src || src.startsWith('data:')) continue;
        const lower = src.toLowerCase();
        if (CONFIG.EXCLUDE_URL_SUBSTRINGS.some(p => lower.includes(p))) continue;
        push({ url: src, w: Math.round(rect.width), h: Math.round(rect.height), source: 'dom' });
      }
    }
    return out;
  }

  function findChatScroller() {
    const all = document.querySelectorAll('div, section, main, ul, ol');
    const cand = [];
    for (const el of all) {
      const rect = el.getBoundingClientRect();
      if (rect.width < 300 || rect.height < 300) continue;
      const st = getComputedStyle(el);
      if ((st.overflowY === 'auto' || st.overflowY === 'scroll') &&
          el.scrollHeight > el.clientHeight + 40) {
        cand.push({ el, area: rect.width * rect.height });
      }
    }
    if (!cand.length) return null;
    cand.sort((a, b) => b.area - a.area);
    return cand[0].el;
  }

  // ---------- 整理：指紋去重 + 尺寸過濾 ----------
  async function mergeAndDedupCandidates(collected) {
    const raw = [];
    for (const src of [...collected.idb, ...collected.cache, ...collected.opfs, ...collected.perf]) {
      raw.push({ blob: src.blob || null, url: src.url || null, source: src.source });
    }
    for (const src of collected.dom) {
      raw.push({ blob: null, url: src.url, source: src.source, w: src.w, h: src.h });
    }

    // 同一張圖可能同時被多個來源撈到（Cache 有 url、DOM 有 url、blob fp 跟 url fp 格式不同）；
    // 用 aliasIndex 把 url 版本指向 blob primary，seenKeys 才能跨來源命中。
    const byFp = new Map();
    const aliasIndex = new Map();
    const resolvePrimary = fp => {
      if (byFp.has(fp)) return fp;
      const via = aliasIndex.get(fp);
      if (via && byFp.has(via)) return via;
      return null;
    };
    for (let i = 0; i < raw.length; i++) {
      const r = raw[i];
      try {
        const primaryFp = r.blob ? await fingerprintBlob(r.blob) : 'url:' + r.url;
        const altFp = r.blob && r.url ? 'url:' + r.url : null;
        let existing = resolvePrimary(primaryFp) || (altFp && resolvePrimary(altFp));
        if (existing) {
          const prev = byFp.get(existing);
          if (r.blob && !prev.blob && existing !== primaryFp) {
            const merged = Array.from(new Set([existing, ...prev.fpAliases, altFp].filter(Boolean)))
              .filter(fp => fp !== primaryFp);
            byFp.delete(existing);
            byFp.set(primaryFp, { ...r, fp: primaryFp, fpAliases: merged });
            for (const fp of merged) aliasIndex.set(fp, primaryFp);
            aliasIndex.set(existing, primaryFp);
          } else {
            const additions = [altFp, primaryFp !== existing ? primaryFp : null].filter(Boolean);
            for (const fp of additions) {
              if (!prev.fpAliases.includes(fp) && fp !== existing) prev.fpAliases.push(fp);
              aliasIndex.set(fp, existing);
            }
          }
        } else {
          const aliases = altFp ? [altFp] : [];
          byFp.set(primaryFp, { ...r, fp: primaryFp, fpAliases: aliases });
          if (altFp) aliasIndex.set(altFp, primaryFp);
        }
      } catch {}
      if ((i + 1) % CONFIG.WORK_CHUNK_SIZE === 0) await yieldToUI();
    }

    const unique = [];
    let decoded = 0;
    for (const c of byFp.values()) {
      decoded++;
      try {
        if (c.blob) {
          const dims = await decodeBlobDims(c.blob);
          if (!dims) continue;
          if (dims.w < CONFIG.MIN_SIZE || dims.h < CONFIG.MIN_SIZE) continue;
          c.w = dims.w; c.h = dims.h;
          c.sizeKB = Math.round(c.blob.size / 1024);
        } else if ((!c.w || !c.h) && c.url) {
          const dims = await decodeUrlDims(c.url);
          if (dims) { c.w = dims.w; c.h = dims.h; }
          else continue;
        }
        if (!c.w || !c.h) continue;
        if (c.w < CONFIG.MIN_SIZE || c.h < CONFIG.MIN_SIZE) continue;
        unique.push(c);
      } catch {}
      if (decoded % CONFIG.WORK_CHUNK_SIZE === 0) await yieldToUI();
    }

    // 有 blob 的排前面（品質高），其次大圖優先
    unique.sort((a, b) => {
      if (!!b.blob !== !!a.blob) return b.blob ? 1 : -1;
      return (b.w * b.h) - (a.w * a.h);
    });
    return unique;
  }

  async function decodeBlobDims(blob) {
    try {
      if (typeof createImageBitmap === 'function') {
        const bmp = await createImageBitmap(blob);
        const d = { w: bmp.width, h: bmp.height };
        bmp.close && bmp.close();
        return d;
      }
    } catch {}
    return new Promise((resolve) => {
      const img = new Image();
      const url = URL.createObjectURL(blob);
      img.onload = () => { URL.revokeObjectURL(url); resolve({ w: img.naturalWidth, h: img.naturalHeight }); };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
      img.src = url;
    });
  }

  function decodeUrlDims(url) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
      img.onerror = () => resolve(null);
      img.src = url;
    });
  }

  async function fingerprintBlob(blob) {
    const head = blob.slice(0, 256);
    const ab = await head.arrayBuffer();
    const bytes = new Uint8Array(ab);
    let hash = 5381;
    for (let i = 0; i < bytes.length; i++) hash = ((hash << 5) + hash + bytes[i]) | 0;
    return `${blob.size}:${blob.type}:${hash}`;
  }

  // ---------- 下載 ----------
  function candidateFullResUrls(src) {
    const urls = [];
    try {
      const u = new URL(src, location.href);
      urls.push(u.toString());
      if (u.pathname.endsWith('/preview')) {
        const u2 = new URL(u); u2.pathname = u2.pathname.replace(/\/preview$/, '');
        urls.push(u2.toString());
      }
      if (u.searchParams.has('type')) {
        const u3 = new URL(u); u3.searchParams.delete('type');
        urls.push(u3.toString());
      }
      if (/preview|thumbnail/i.test(u.pathname)) {
        const u4 = new URL(u); u4.pathname = u4.pathname.replace(/preview|thumbnail/gi, 'original');
        urls.push(u4.toString());
      }
    } catch { urls.push(src); }
    return [...new Set(urls.reverse())];
  }

  function extFromMime(mime) {
    if (!mime) return 'jpg';
    if (mime.includes('png')) return 'png';
    if (mime.includes('gif')) return 'gif';
    if (mime.includes('webp')) return 'webp';
    if (mime.includes('bmp')) return 'bmp';
    return 'jpg';
  }

  function saveToDownloads(name, blob) {
    // automation 時 Playwright page.on('download') 會接到這個 <a>.click() 觸發的下載事件
    const u = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = u; a.download = name;
    a.rel = 'noopener'; a.style.display = 'none';
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(u); a.remove(); }, 1000);
  }

  async function downloadOne(cand, idx, ts) {
    const sourceTag = (cand.source || 'dom').split(':')[0];
    if (cand.blob) {
      try {
        const ext = extFromMime(cand.blob.type);
        const name = `${CONFIG.FILENAME_PREFIX}_${ts}_${String(idx).padStart(4, '0')}_${sourceTag}.${ext}`;
        saveToDownloads(name, cand.blob);
        return { ok: true, name, sourceTag };
      } catch (e) {
        return { ok: false, reason: `blob save failed: ${e && e.message ? e.message : String(e)}` };
      }
    }
    const src = cand.url;
    if (!src) return { ok: false, reason: 'missing source URL' };
    const tryList = src.startsWith('blob:') ? [src] : candidateFullResUrls(src);
    const reasons = [];
    for (const url of tryList) {
      try {
        const resp = await fetch(url, { credentials: 'include' });
        if (!resp.ok) { reasons.push(`${url} HTTP ${resp.status}`); continue; }
        const blob = await resp.blob();
        if (blob.size < 1024) { reasons.push(`${url} too small: ${blob.size} bytes`); continue; }
        if (blob.type && !blob.type.startsWith('image/')) { reasons.push(`${url} not image: ${blob.type}`); continue; }
        const ext = extFromMime(blob.type);
        const name = `${CONFIG.FILENAME_PREFIX}_${ts}_${String(idx).padStart(4, '0')}_${sourceTag}.${ext}`;
        saveToDownloads(name, blob);
        return { ok: true, name, sourceTag };
      } catch (e) {
        reasons.push(`${url} ${e && e.message ? e.message : String(e)}`);
      }
    }
    return { ok: false, reason: reasons.join(' | ') || 'all URL attempts failed' };
  }

  // ---------- 對外主入口 ----------
  window.__LDL_RUN__ = async ({ seenKeys = [], scanProfile = DEFAULT_SCAN_PROFILE } = {}) => {
    const lightMode = scanProfile === SCAN_PROFILES.WATCH_FAST;
    const seenSet = new Set(Array.isArray(seenKeys) ? seenKeys.filter(Boolean) : []);
    setRuntimeState({
      phase: PHASES.SCANNING,
      scanProfile,
      error: null,
      candidateCount: 0,
      selectedCount: 0,
      downloadedCount: 0,
      failedCount: 0,
      selectedKeys: [],
      downloadedKeys: [],
      failedKeys: [],
      failedDetails: [],
      savedFiles: [],
      summaryCounts: { idb: 0, cache: 0, opfs: 0, perf: 0, dom: 0, deduped: 0 },
      cycleStartedAt: Date.now(),
      completedAt: null,
    });

    let candidates = [];
    try {
      const [idb, cache, opfs] = await Promise.all([
        scanIndexedDB(lightMode).catch(e => { console.warn('[LDL] scanIDB', e); return []; }),
        scanCacheStorage().catch(e => { console.warn('[LDL] scanCache', e); return []; }),
        scanOPFS(lightMode).catch(e => { console.warn('[LDL] scanOPFS', e); return []; }),
      ]);
      const dom = scanDOM();
      const perf = scanPerformanceUrls();
      const collected = { idb, cache, opfs, perf, dom };
      candidates = await mergeAndDedupCandidates(collected);

      const gridSourceCounts = candidates.reduce((acc, c) => {
        const tag = String(c.source || 'dom').split(':')[0].toLowerCase();
        acc[tag] = (acc[tag] || 0) + 1;
        return acc;
      }, {});

      setRuntimeState({
        summaryCounts: {
          idb: idb.length, cache: cache.length, opfs: opfs.length,
          perf: perf.length, dom: dom.length, deduped: candidates.length,
        },
        gridSourceCounts,
        candidateCount: candidates.length,
      });

      if (!candidates.length) {
        setRuntimeState({ phase: PHASES.EMPTY, completedAt: Date.now() });
        return { ...window.__LDL_STATE__ };
      }
    } catch (e) {
      setRuntimeState({
        phase: PHASES.ERROR,
        error: e && e.message ? e.message : String(e),
        completedAt: Date.now(),
      });
      return { ...window.__LDL_STATE__ };
    }

    // 過濾：seenKeys 命中（比對 fp 與 fpAliases）就跳過
    const selected = candidates.filter(c => {
      if (c.fp && seenSet.has(c.fp)) return false;
      if (Array.isArray(c.fpAliases)) {
        for (const a of c.fpAliases) if (seenSet.has(a)) return false;
      }
      return true;
    });
    setRuntimeState({
      selectedCount: selected.length,
      selectedKeys: selected.map(c => c.fp).filter(Boolean),
      phase: selected.length ? PHASES.READY : PHASES.EMPTY,
    });

    if (!selected.length) {
      setRuntimeState({ completedAt: Date.now() });
      return { ...window.__LDL_STATE__ };
    }

    setRuntimeState({ phase: PHASES.DOWNLOADING });
    const TS = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    let ok = 0, fail = 0;
    const downloadedKeys = [];
    const failedKeys = [];
    const failedDetails = [];
    const savedFiles = [];
    for (let i = 0; i < selected.length; i++) {
      const c = selected[i];
      const result = await downloadOne(c, i + 1, TS);
      const keys = [c.fp, ...(c.fpAliases || [])].filter(Boolean);
      if (result.ok) {
        ok++;
        for (const k of keys) downloadedKeys.push(k);
        savedFiles.push({
          name: result.name || '',
          sourceTag: result.sourceTag || '',
          url: c.url || '',
          fp: c.fp || '',
          fpAliases: c.fpAliases || [],
        });
      } else {
        fail++;
        for (const k of keys) failedKeys.push(k);
        failedDetails.push({
          key: c.fp || '', source: c.source || '',
          url: c.url || '', reason: result.reason || 'unknown',
        });
      }
      setRuntimeState({ downloadedCount: ok, failedCount: fail, downloadedKeys, failedKeys, failedDetails, savedFiles });
      await sleep(CONFIG.DOWNLOAD_DELAY_MS);
    }

    setRuntimeState({
      phase: PHASES.DONE,
      completedAt: Date.now(),
    });
    return { ...window.__LDL_STATE__ };
  };
})();

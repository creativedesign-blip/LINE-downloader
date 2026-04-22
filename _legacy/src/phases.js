const DOWNLOADER_PHASES = {
  IDLE: 'idle',
  SCANNING: 'scanning',
  READY: 'ready',
  EMPTY: 'empty',
  DOWNLOADING: 'downloading',
  DONE: 'done',
  ERROR: 'error',
};

const SCAN_PROFILES = {
  FULL: 'full',
  WATCH_FAST: 'watch-fast',
};

module.exports = {
  DOWNLOADER_PHASES,
  SCAN_PROFILES,
};

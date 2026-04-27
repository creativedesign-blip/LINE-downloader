const { spawn } = require('child_process');
const path = require('path');

const { ROOT_DIR, resolveProjectPath } = require('./config');

const FILTER_SCRIPT = path.join(ROOT_DIR, 'filter', 'filter.py');

const CONCURRENCY = Math.max(1, Number(process.env.LINE_CLASSIFY_CONCURRENCY) || 1);
const queue = [];
let active = 0;

function runClassifier(target, options = {}) {
  return new Promise((resolve, reject) => {
    queue.push({ target, options, resolve, reject });
    drain();
  });
}

function drain() {
  while (active < CONCURRENCY && queue.length) {
    const job = queue.shift();
    active += 1;
    executeClassifier(job.target, job.options)
      .then(job.resolve, job.reject)
      .finally(() => {
        active -= 1;
        drain();
      });
  }
}

function executeClassifier(target, options) {
  const pythonBin = options.python || 'python';
  const inputDir = resolveProjectPath(target.downloadDir);
  const travelDir = resolveProjectPath(target.travelDir);
  const otherDir = resolveProjectPath(target.otherDir);
  const errorDir = target.errorDir
    ? resolveProjectPath(target.errorDir)
    : path.join(path.dirname(travelDir), 'error');

  return new Promise((resolve, reject) => {
    const args = [
      FILTER_SCRIPT,
      '--input-dir', inputDir,
      '--travel-dir', travelDir,
      '--other-dir', otherDir,
      '--error-dir', errorDir,
    ];

    const child = spawn(pythonBin, args, {
      cwd: ROOT_DIR,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', chunk => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', chunk => {
      stderr += chunk.toString();
    });
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) {
        reject(new Error(`分類器失敗（exit ${code}）\n${stderr || stdout}`));
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

module.exports = {
  runClassifier,
};

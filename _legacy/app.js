#!/usr/bin/env node
const controller = require('./src/controller');
const { closeSharedBrowsers } = require('./src/browser-attach');

const PERSISTENT_COMMANDS = new Set(['watch']);

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const options = {};
  for (let i = 0; i < rest.length; i += 1) {
    const token = rest[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = rest[i + 1];
    if (!next || next.startsWith('--')) {
      options[key] = true;
      continue;
    }
    options[key] = next;
    i += 1;
  }
  return { command, options };
}

function printUsage() {
  console.log(`Usage:
  node app.js pages [--cdp-url http://127.0.0.1:9333]
  node app.js bind --target metro [--label "大都會"] [--page 0] [--cdp-url http://127.0.0.1:9333]
  node app.js list
  node app.js run --target metro [--useState true] [--cdp-url http://127.0.0.1:9333] [--python python]
  node app.js run-all [--cdp-url http://127.0.0.1:9333] [--python python]
  node app.js watch --target metro [--interval-sec 10800] [--full-scan-every 6] [--cdp-url http://127.0.0.1:9333] [--python python]

Notes:
  - Chrome/Chromium must already be running with --remote-debugging-port=9333.
  - Keep the LINE Web browser open and logged in.
  - watch re-scans on an interval and only downloads unseen images for that target.
  - watch uses DOM/performance fast scans between full storage scans.`);
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  let shouldCleanup = !PERSISTENT_COMMANDS.has(command);
  try {
    switch (command) {
      case 'pages':
        await controller.listPages(options);
        break;
      case 'bind':
        await controller.bindTarget(options);
        break;
      case 'list':
        await controller.listTargets();
        break;
      case 'run':
        await controller.runTarget(options);
        break;
      case 'run-all':
        await controller.runAllTargets(options);
        break;
      case 'watch':
        await controller.watchTarget(options);
        break;
      case 'help':
      case '--help':
      case '-h':
      case undefined:
        printUsage();
        break;
      default:
        console.error(`Unknown command: ${command}`);
        printUsage();
        process.exitCode = 1;
    }
  } catch (error) {
    console.error(error.message || error);
    process.exitCode = 1;
  }
  if (shouldCleanup) {
    try { await closeSharedBrowsers(); } catch {}
    process.exit(process.exitCode || 0);
  }
}

main();

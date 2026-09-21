'use strict';
const fs = require('node:fs');

function emit(phase) {
  const nonce = process.env.MARKER_NONCE || '';
  const run = process.env.GITHUB_RUN_ID || '';
  const attempt = process.env.GITHUB_RUN_ATTEMPT || '';
  if (!/^[0-9a-f]{64}$/.test(nonce) || !/^[1-9][0-9]*$/.test(run) ||
      !/^[1-9][0-9]*$/.test(attempt) || !/^[a-z][a-z0-9-]{0,63}$/.test(phase)) {
    throw new Error('Invalid initialization marker identity');
  }
  fs.writeFileSync('/dev/ttyS0', `\nBROKKR_ADMISSION_EXEC_V1:${nonce}:${run}:${attempt}:${phase}\n`);
}
module.exports = { emit };

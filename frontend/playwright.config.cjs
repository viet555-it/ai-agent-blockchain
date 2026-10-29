const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/e2e', workers: 1, timeout: 45000,
  use: { baseURL: process.env.APP_ORIGIN, headless: true, screenshot: 'only-on-failure' },
  reporter: [['list'], ['json', { outputFile: '../.phase3/wallet-e2e/results.json' }]],
});

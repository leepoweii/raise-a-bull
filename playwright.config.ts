import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: 'http://127.0.0.1:8766',
    headless: true,
  },
  // Don't start server — tests expect it to be running already
  // Start with: ADMIN_PASSWORD=demo123 uv run uvicorn raisebull.main:app --port 8766
});

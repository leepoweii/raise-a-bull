/**
 * E2E tests for the Audit Log dashboard page.
 *
 * Requires a running server:
 *   ADMIN_PASSWORD=demo123 uv run uvicorn raisebull.main:app --port 8766
 *
 * Run:
 *   npx playwright test tests/e2e/audit.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';

const PASSWORD = process.env.ADMIN_PASSWORD || 'demo123';

async function login(page: Page) {
  await page.goto('/admin/');
  await expect(page.locator('input[type="password"]')).toBeVisible({ timeout: 5000 });
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button:has-text("LOGIN")');
  await page.waitForURL(/\/#\/(status|chat)/, { timeout: 5000 });
}

test.describe('Audit Log page', () => {
  test('page loads with default 7-day data', async ({ page }) => {
    await login(page);
    // Navigate to Audit via nav link
    await page.click('a:has-text("Audit")');
    // Wait for the table to render (at least one row from the login itself).
    // Use toBeVisible on a specific row rather than toHaveCount(1) — the audit
    // log may already contain heartbeat / settings entries from prior runs, so
    // asserting exactly 1 row would be nondeterministic.
    await expect(page.locator('table tbody tr:has-text("login.success")').first()).toBeVisible({ timeout: 5000 });
  });

  test('category filter narrows results', async ({ page }) => {
    await login(page);
    await page.click('a:has-text("Audit")');
    await expect(page.locator('table tbody tr:has-text("login.success")').first()).toBeVisible({ timeout: 5000 });

    // Uncheck the Auth → login.success checkbox
    await page.uncheck('input[type="checkbox"][value="login.success"]');
    await expect(page.locator('table tbody tr:has-text("login.success")')).toHaveCount(0);
  });
});

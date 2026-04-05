/**
 * E2E tests for admin dashboard.
 *
 * Requires a running server:
 *   ADMIN_PASSWORD=demo123 ... uv run uvicorn raisebull.main:app --port 8766
 *
 * Run:
 *   npx playwright test tests/e2e/dashboard.spec.ts
 */
import { test, expect, type Page } from '@playwright/test';

const PASSWORD = 'demo123';

// Helper: login and return authenticated page
async function login(page: Page) {
  await page.goto('/admin/');
  // Should redirect to login — wait for password input
  await expect(page.locator('input[type="password"]')).toBeVisible({ timeout: 5000 });
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button:has-text("LOGIN")');
  // Wait for redirect away from login
  await page.waitForURL(/\/#\/(status|chat)/, { timeout: 5000 });
}

test.describe('Auth', () => {
  test('redirects to login when not authenticated', async ({ page }) => {
    await page.goto('/admin/');
    // Login page should show password input
    await expect(page.locator('input[type="password"]')).toBeVisible({ timeout: 3000 });
  });

  test('login with correct password succeeds', async ({ page }) => {
    await login(page);
    // Should see sidebar header
    await expect(page.locator('.sidebar-header')).toBeVisible();
    await expect(page.locator('.sidebar-header')).toContainText('raise-a-bull', { ignoreCase: true });
  });

  test('login with wrong password shows error', async ({ page }) => {
    await page.goto('/admin/');
    await page.fill('input[type="password"]', 'wrongpass');
    await page.click('button:has-text("LOGIN")');
    // Should stay on login page
    await expect(page.locator('input[type="password"]')).toBeVisible({ timeout: 3000 });
  });
});

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('all sidebar links navigate correctly', async ({ page }) => {
    const pages = ['Chat', 'Status', 'Context', 'Skills', 'Credentials', 'Heartbeat', 'Permissions', 'Settings'];
    for (const name of pages) {
      await page.click(`.sidebar-nav a:has-text("${name}")`);
      await expect(page).toHaveURL(new RegExp(`#/${name.toLowerCase()}`));
    }
  });
});

test.describe('Status Page', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('shows agent status cards', async ({ page }) => {
    await page.click('a:has-text("Status")');
    // Check card titles (not values which may match "Agent" text elsewhere)
    await expect(page.locator('.card-title:has-text("Agent")')).toBeVisible();
    await expect(page.locator('text=DISCORD BOT')).toBeVisible();
    await expect(page.locator('text=SESSIONS')).toBeVisible();
  });
});

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('loads default settings', async ({ page }) => {
    await page.click('a:has-text("Settings")');
    await expect(page.locator('text=AGENT NAME')).toBeVisible();
    await expect(page.locator('text=MODEL')).toBeVisible();
    const nameInput = page.locator('input').first();
    await expect(nameInput).toHaveValue('Agent');
  });
});

test.describe('Web Chat', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.click('a:has-text("Chat")');
  });

  test('creates new session', async ({ page }) => {
    await page.click('button:has-text("NEW CHAT")');
    // Should show chat input textarea
    await expect(page.locator('textarea')).toBeVisible({ timeout: 3000 });
    // Delete button should be visible (session selected)
    await expect(page.locator('button:has-text("DELETE")')).toBeVisible({ timeout: 3000 });
  });

  test('sends message and receives SSE response', async ({ page }) => {
    await page.click('button:has-text("NEW CHAT")');
    await expect(page.locator('textarea')).toBeVisible({ timeout: 3000 });

    await page.fill('textarea', 'What is 2+2? Just the number.');
    await page.click('button:has-text("SEND")');

    // Wait for user bubble
    await expect(page.locator('.chat-bubble-user')).toBeVisible({ timeout: 5000 });

    // Wait for assistant bubble (real MiniMax, may take 10-20s)
    await expect(page.locator('.chat-bubble-assistant:not(.chat-loading)')).toBeVisible({ timeout: 30000 });

    // Should contain the answer
    await expect(page.locator('.chat-bubble-assistant:not(.chat-loading)').last()).toContainText('4', { timeout: 5000 });
  });

  test('message body uses content field not message field', async ({ page }) => {
    // Regression test: frontend was sending { message: msg } but backend expects { content: msg }
    await page.click('button:has-text("NEW CHAT")');
    await expect(page.locator('textarea')).toBeVisible({ timeout: 3000 });

    let requestBody: any = null;
    await page.route('**/api/chat/*/messages', async (route, request) => {
      requestBody = JSON.parse(request.postData() || '{}');
      await route.continue();
    });

    await page.fill('textarea', 'test');
    await page.click('button:has-text("SEND")');
    await page.waitForTimeout(2000);

    expect(requestBody).not.toBeNull();
    expect(requestBody.content).toBe('test');
    expect(requestBody.message).toBeUndefined();
  });

  test('messages persist after response completes', async ({ page }) => {
    // Regression test: selectSession() was clearing in-memory messages after SSE
    await page.click('button:has-text("NEW CHAT")');
    await expect(page.locator('textarea')).toBeVisible({ timeout: 3000 });

    await page.fill('textarea', 'Say OK');
    await page.click('button:has-text("SEND")');

    // Wait for both bubbles
    await expect(page.locator('.chat-bubble-assistant:not(.chat-loading)')).toBeVisible({ timeout: 30000 });
    await page.waitForTimeout(2000);

    // Both should still be visible (not cleared)
    await expect(page.locator('.chat-bubble-user')).toBeVisible();
    await expect(page.locator('.chat-bubble-assistant:not(.chat-loading)')).toBeVisible();
  });

  test('delete session works', async ({ page }) => {
    await page.click('button:has-text("NEW CHAT")');
    await expect(page.locator('button:has-text("DELETE")')).toBeVisible({ timeout: 3000 });

    page.on('dialog', dialog => dialog.accept());
    await page.click('button:has-text("DELETE")');
    await page.waitForTimeout(1000);

    // Chat area should show placeholder
    await expect(page.locator('text=Select a session')).toBeVisible({ timeout: 3000 });
  });
});

test.describe('File Upload', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.click('a:has-text("Chat")');
    await page.click('button:has-text("NEW CHAT")');
    await expect(page.locator('textarea')).toBeVisible({ timeout: 3000 });
  });

  test('file picker shows preview bar', async ({ page }) => {
    // Select a file via the hidden input
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'test.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Hello from file upload test'),
    });

    // Preview bar should appear with filename
    await expect(page.locator('.chat-file-preview')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('.chat-file-item')).toContainText('test.txt');
  });

  test('remove file from preview bar', async ({ page }) => {
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'remove-me.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('temporary'),
    });

    await expect(page.locator('.chat-file-item')).toBeVisible({ timeout: 3000 });

    // Click the remove button (✕)
    await page.click('.chat-file-remove');

    // Preview bar should disappear
    await expect(page.locator('.chat-file-preview')).not.toBeVisible({ timeout: 3000 });
  });

  test('send file with text and receive response', async ({ page }) => {
    // Add file
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'data.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('product,price\n高粱酒,580\n貢糖,120'),
    });

    await expect(page.locator('.chat-file-item')).toBeVisible({ timeout: 3000 });

    // Type text
    await page.fill('textarea', '最貴的是什麼？只回答名稱。');

    // Send
    await page.click('button:has-text("SEND")');

    // User bubble should show file attachment
    await expect(page.locator('.chat-bubble-user')).toContainText('data.csv', { timeout: 5000 });

    // Preview bar should be gone after send
    await expect(page.locator('.chat-file-preview')).not.toBeVisible();

    // Wait for assistant response (real LLM, may take 10-30s)
    await expect(page.locator('.chat-bubble-assistant:not(.chat-loading)')).toBeVisible({ timeout: 30000 });

    // Should contain the answer
    await expect(page.locator('.chat-bubble-assistant:not(.chat-loading)').last()).toContainText('高粱酒', { timeout: 5000 });
  });

  test('send button enabled when file selected without text', async ({ page }) => {
    // Initially send button should be disabled (no text, no files)
    await expect(page.locator('button:has-text("SEND")')).toBeDisabled();

    // Add file
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: 'note.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Some content'),
    });

    // Send button should now be enabled (file present, even without text)
    await expect(page.locator('button:has-text("SEND")')).toBeEnabled({ timeout: 3000 });
  });

  test('multiple files show in preview', async ({ page }) => {
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles([
      { name: 'file1.txt', mimeType: 'text/plain', buffer: Buffer.from('one') },
      { name: 'file2.txt', mimeType: 'text/plain', buffer: Buffer.from('two') },
    ]);

    // Both files should appear in preview
    const items = page.locator('.chat-file-item');
    await expect(items).toHaveCount(2, { timeout: 3000 });
    await expect(items.nth(0)).toContainText('file1.txt');
    await expect(items.nth(1)).toContainText('file2.txt');
  });
});

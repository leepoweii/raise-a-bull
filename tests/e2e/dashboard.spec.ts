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

  test('renders every _ALLOWED_KEYS field', async ({ page }) => {
    // Regression guard — commits up through af1e70d left 4 of 10 _ALLOWED_KEYS
    // entries API-editable but UI-invisible. This test asserts every key has a
    // matching x-model binding on the rendered page. If someone adds a new key
    // to _ALLOWED_KEYS without a form-group block, this test fails immediately.
    //
    // Keep in sync with _ALLOWED_KEYS in src/raisebull/admin/routes_settings.py
    // (the unit test tests/unit/test_settings_form.py enforces the structural
    // match server-side; this e2e adds the rendered-DOM check).
    await page.click('a:has-text("Settings")');
    const expectedKeys = [
      'agent_name',
      'model',
      'max_steps',
      'auto_reply_timeout',
      'session_idle_timeout',
      'heartbeat_interval',
      'buffer_time',
      'nightly_compact_hour',
      'nightly_compact_threshold',
      'line_trigger_prefix',
    ];
    for (const key of expectedKeys) {
      const field = page.locator(`[x-model="settings.${key}"]`);
      await expect(field, `missing form field for settings.${key}`).toBeVisible();
    }
    // Exactly 10 form fields — not 6, not 11 — so we notice drift in either direction.
    const allBindings = await page.locator('[x-model^="settings."]').count();
    expect(allBindings).toBe(expectedKeys.length);
  });

  test('nightly_compact_threshold round-trips through save button', async ({ page }) => {
    // End-to-end proof that the UI can edit the new field, save it via the
    // actual button click, and the value persists across a page reload.
    // Would have caught the af1e70d bug (hand-coded form missing the field)
    // and any future regression that drops the input from the rendered HTML.
    await page.click('a:has-text("Settings")');
    const input = page.locator('[x-model="settings.nightly_compact_threshold"]');
    await expect(input).toBeVisible();
    // Pick a distinctive sentinel value unlikely to collide with a real config
    await input.fill('31337');
    await page.click('button:has-text("Save")');
    // Alpine's save() awaits the PUT then sets saved=true — wait for the
    // restart-notice to appear as the confirmation signal
    await expect(page.locator('.restart-notice')).toBeVisible({ timeout: 5000 });
    // Reload and re-navigate — value must still be 31337
    await page.reload();
    await page.click('a:has-text("Settings")');
    const reloadedInput = page.locator('[x-model="settings.nightly_compact_threshold"]');
    await expect(reloadedInput).toHaveValue('31337');
    // Clean up: restore a sensible default so subsequent tests / live usage don't
    // inherit the sentinel. We can't reuse the Save button + .restart-notice
    // visibility check because the notice is already visible from the first
    // save (Alpine's `saved` stays true), so a second `toBeVisible` returns
    // immediately without proving the PUT finished. Instead, wait for the
    // actual HTTP response to complete and then reload to confirm persistence.
    await reloadedInput.fill('50000');
    const saveResponse = page.waitForResponse(
      (resp) => resp.url().includes('/admin/api/settings') && resp.request().method() === 'PUT'
    );
    await page.click('button:has-text("Save")');
    await saveResponse;
    await page.reload();
    await page.click('a:has-text("Settings")');
    await expect(
      page.locator('[x-model="settings.nightly_compact_threshold"]')
    ).toHaveValue('50000');
  });

  test('invalid threshold surfaces error toast', async ({ page }) => {
    // Pin the contract: the generic app.js api() helper routes any response
    // body with an `error` key to showToast(..., 'error'). The routes_settings.py
    // 400 validator returns the canonical message for ANY non-positive int
    // (non-numeric, zero, negative, empty, whitespace). End-to-end: setting an
    // invalid value and clicking Save must display that message in the toast.
    //
    // Why -100 instead of "abc": settings.html uses <input type="number"> which
    // both Playwright's fill() and the browser refuse to accept non-numeric
    // strings. -100 is a valid number string (passes fill() and the input) but
    // is rejected by the PUT validator (n <= 0), exercising the same canonical
    // error path as any other invalid value.
    //
    // Previously settings.js:47 only handled result.ok (and ignored the null
    // return from api() on 400), but app.js's api() helper already centralizes
    // the showToast on data.error, so the toast DOES appear — this test locks
    // that behavior in.
    await page.click('a:has-text("Settings")');
    const input = page.locator('[x-model="settings.nightly_compact_threshold"]');
    await expect(input).toBeVisible();
    await input.fill('-100');
    await page.click('button:has-text("Save")');
    // Toast element uses .toast class and is populated by app.js showToast().
    // Must contain the canonical error message from routes_settings.py.
    await expect(page.locator('.toast')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('.toast')).toContainText(
      'nightly_compact_threshold must be a positive integer'
    );
    // Critically: .restart-notice must NOT appear — Alpine's saved=true only
    // fires on a successful PUT, and a 400 should keep it false.
    await expect(page.locator('.restart-notice')).not.toBeVisible();
    // Clean up: api() returned null, so local Alpine state still shows "-100"
    // but the file on disk is unchanged. Reload drops the local garbage.
    await page.reload();
    await page.click('a:has-text("Settings")');
    await expect(
      page.locator('[x-model="settings.nightly_compact_threshold"]')
    ).not.toHaveValue('-100');
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

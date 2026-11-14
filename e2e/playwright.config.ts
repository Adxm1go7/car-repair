import { defineConfig, devices } from '@playwright/test'

// Runs against the Compose stack, which must already be up (`docker compose up --build -d --wait`).
export default defineConfig({
  testDir: './tests',
  // One browser at a time: tests share one database, and two bookings racing for the
  // same first free time would (correctly) leave one of them "just taken".
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // A real (test mode) Stripe payment: typing into Stripe's form and Stripe confirming it
  // can take a while, well past the default 30 seconds on a slow run.
  timeout: 90_000,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:8080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})

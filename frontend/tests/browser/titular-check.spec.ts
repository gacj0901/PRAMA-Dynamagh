import { test, expect } from "@playwright/test";
import fixture from "../fixtures/receipt.json";
const path = `/titular-check/${"a".repeat(64)}-prama-dynamagh`;

for (const width of [360, 390, 430, 1280]) test(`gated receipt at ${width}px, no horizontal overflow`, async ({ page }) => {
  const reads: string[] = [];
  await page.setViewportSize({ width, height: 900 });
  await page.route("**/*", async route => {
    const url = route.request().url();
    if (url.startsWith("https://challenges.cloudflare.com/")) return route.fulfill({ contentType: "text/javascript", body: `window.turnstile={render(el,options){const b=document.createElement('button');b.textContent='Fixture human challenge';b.onclick=()=>options.callback('fixture-token');el.append(b);return 'widget';},remove(){}};` });
    if (url.includes("/api/")) {
      reads.push(route.request().method()+" "+new URL(url).pathname);
      const value = url.endsWith("/config") ? { site_key: "fixture-site" } : url.endsWith("/challenge") ? { access_token: "fixture-grant" } : fixture;
      return route.fulfill({ json: value });
    }
    if (!url.startsWith("http://127.0.0.1:4179")) return route.abort();
    return route.continue();
  });
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "TITULAR CHECK", exact: true })).toBeVisible();
  await expect(page.getByText("PERMIT", { exact: true })).toHaveCount(0);
  expect(reads).toEqual(["GET /api/v1/titular-check/config"]);
  await page.getByRole("button", { name: "Fixture human challenge" }).click();
  await expect(page.getByText("PERMIT", { exact: true })).toBeVisible();
  const layout = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, viewport: window.innerWidth, receipt: document.querySelector(".tc-receipt")!.getBoundingClientRect().toJSON() }));
  expect(layout.scroll).toBeLessThanOrEqual(width);
  expect(layout.receipt.width).toBeLessThanOrEqual(460);
  expect(Math.abs(layout.receipt.x + layout.receipt.width / 2 - width / 2)).toBeLessThanOrEqual(1);
  expect(await page.locator(".tc-hash").textContent()).toBe(fixture.response_hash);
  reads.length=0;
  await page.getByRole("button", { name: "VERIFY AGAIN" }).click();
  await expect(page.getByRole("button", { name: "VERIFY AGAIN" })).toBeVisible();
  expect(reads).toEqual(["GET /api/v1" + path]);
  await page.screenshot({ path: `test-results/titular-check-${width}.png`, fullPage: true });
});

test("root and operator still render the original console", async ({ page }) => {
  await page.route("**/api/**", route => route.fulfill({ status: 503, json: {} }));
  for (const path of ["/", "/operator/"]) {
    await page.goto(path);
    await expect(page.getByText("PROCESS CONSOLE", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "TITULAR CHECK", exact: true })).toHaveCount(0);
  }
});

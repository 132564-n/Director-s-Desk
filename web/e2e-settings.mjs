import assert from "node:assert/strict";
import { chromium } from "playwright-core";

// Mock only settings endpoints: never overwrite the user's saved keys or projects.
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let settings = await (await fetch("http://127.0.0.1:8000/settings/models")).json();
  // Start with demo assignments independent of any real user settings.
  settings.providers = [{ id: "demo", label: "本地演示团队", kind: "demo", base_url: "", api_key_env: "", api_key_set: false }];
  settings.assignments = settings.assignments.map(a => ({ ...a, provider_id: "demo", model: "deterministic-v1" }));
  let savedKey = "";
  await page.route("**/settings/models**", async route => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-methods": "GET,PUT,POST,OPTIONS", "access-control-allow-headers": "content-type" } });
    }
    if (request.url().endsWith("/test")) {
      assert.equal(savedKey, "test-only-not-a-real-key");
      return route.fulfill({ json: { ok: true, message: "模拟连接成功" }, headers: { "access-control-allow-origin": "*" } });
    }
    if (request.method() === "PUT") {
      settings = request.postDataJSON();
      settings.providers = settings.providers.map(p => {
        const { api_key, ...publicProvider } = p;
        if (api_key !== undefined) savedKey = api_key;
        return { ...publicProvider, api_key_set: p.kind !== "demo" && !!savedKey };
      });
    }
    return route.fulfill({ json: settings, headers: { "access-control-allow-origin": "*" } });
  });
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  await page.getByRole("link", { name: /团队 API 配置/ }).click();
  await page.getByRole("button", { name: "＋ 添加兼容接口" }).click();
  const provider = page.locator(".provider-card").last();
  await provider.getByLabel("显示名称").fill("测试供应商");
  await provider.getByLabel(/Base URL/).fill("https://model.example/v1");
  await provider.locator('input[type="password"]').fill("test-only-not-a-real-key");
  await page.getByLabel("测试供应商测试模型").fill("test-model");
  assert.equal(await page.locator(".assignment-row > select").count(), 9);
  assert.equal(await page.locator(".profile-select select").count(), 9);
  await page.locator(".assignment-row > select").first().selectOption({ label: "测试供应商" });
  await page.locator(".assignment-row input").first().fill("test-model");
  const writerProfile = page.locator(".assignment-row", { hasText: "编剧" }).locator(".profile-select select");
  await writerProfile.selectOption("rigorous");
  assert.equal(await writerProfile.inputValue(), "rigorous");
  await page.getByRole("button", { name: "保存并测试连接" }).click();
  await page.getByRole("status").filter({ hasText: "模拟连接成功" }).waitFor();
  assert.equal(await provider.locator('input[type="password"]').inputValue(), "");
  assert.equal(savedKey, "test-only-not-a-real-key");
  await page.reload({ waitUntil: "networkidle" });
  assert.equal(await provider.locator('input[type="password"]').inputValue(), "");
  await page.getByRole("button", { name: "保存团队配置" }).click();
  await page.getByRole("status").waitFor();
  assert.equal(savedKey, "test-only-not-a-real-key");
  await page.getByRole("button", { name: "清除已保存密钥（保存后生效）" }).click();
  await page.getByRole("button", { name: "保存团队配置" }).click();
  await page.getByRole("status").waitFor();
  assert.equal(savedKey, "");
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Settings overflows at ${width}`);
  }
  assert.deepEqual(errors, []);
  console.log("PASS: settings navigation, 9 assignments and work profiles, save/test, secret not echoed, preserve/clear, responsive widths; endpoints mocked, user data unchanged.");
} finally {
  await browser.close();
}

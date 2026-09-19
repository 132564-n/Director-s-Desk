import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

const browser = await chromium.launch({
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1500, height: 960 } });
page.setDefaultTimeout(15000);
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(error.message));

const projectId = `e2e-chat-${Date.now()}`;
const screenshots = join(process.cwd(), "..", "data", "screenshots");
await mkdir(screenshots, { recursive: true });

try {
  console.log("E2E: open");
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  await page.locator(".drawer-label button").click();
  await page.locator('input[name="title"]').fill("群聊验收项目");
  await page.locator('input[name="id"]').fill(projectId);
  await page.locator('input[name="duration"]').fill("180");
  await page.getByRole("button", { name: "建立并组建团队" }).click();

  await page.locator(".conversation-sheet").waitFor();
  await page.locator('.conversation-sheet input[name="title"]').fill("开场钩子创作会");
  await page.locator('.conversation-sheet textarea[name="goal"]').fill("讨论前三秒钩子并形成可确认大纲");
  await page.getByRole("button", { name: "进入群聊" }).click();
  await page.getByRole("heading", { name: "开场钩子创作会" }).waitFor();
  console.log("E2E: conversation", projectId);

  await page.locator(".autonomy-switch").click();
  await page.locator(".composer-body textarea").fill("请讨论故事开场与镜头节奏，各自给出专业意见");
  await page.locator(".send-button").click();
  await page.waitForFunction(() => document.querySelectorAll(".chat-message.agent").length >= 2);
  await page.waitForFunction(() => document.querySelector(".run-ticket")?.textContent?.includes("本轮结束"));
  console.log("E2E: discussion");

  const agentNames = await page.locator(".chat-message.agent .message-column > header b").allTextContents();
  if (new Set(agentNames).size < 2) throw new Error("Agent 发言未按独立角色展示");

  await page.getByRole("button", { name: "生成提案" }).click();
  await page.locator(".composer-body textarea").fill("请综合刚才意见，生成可确认的故事大纲");
  await page.locator(".send-button").click();
  await page.locator(".proposal-card").waitFor();
  await page.getByRole("button", { name: "采纳为草案" }).click();
  await page.getByRole("button", { name: "确认正式版本" }).waitFor();
  await page.getByRole("button", { name: "确认正式版本" }).click();
  await page.locator(".artifact-ticket").waitFor();
  console.log("E2E: proposal confirmed");

  await page.locator(".shelf-header .icon-button").click();
  await page.waitForFunction(() => !document.querySelector(".chat-shell")?.classList.contains("right-open"));
  await page.locator(".shelf-trigger").click();
  await page.waitForFunction(() => document.querySelector(".chat-shell")?.classList.contains("right-open"));
  await page.locator(".desktop-collapse").click();
  await page.waitForFunction(() => !document.querySelector(".chat-shell")?.classList.contains("left-open"));
  await page.locator(".sidebar-trigger").click();
  await page.waitForTimeout(300);

  await page.screenshot({ path: join(screenshots, "chat-workbench-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  if (await page.locator(".drawer-scrim").isVisible()) {
    await page.locator(".drawer-scrim").evaluate((element) => element.click());
    await page.waitForFunction(() => {
      const shell = document.querySelector(".chat-shell");
      return shell && !shell.classList.contains("left-open") && !shell.classList.contains("right-open");
    });
  }
  await page.locator(".sidebar-trigger").click();
  await page.waitForFunction(() => document.querySelector(".chat-shell")?.classList.contains("left-open"));
  await page.waitForTimeout(300);
  console.log("E2E: mobile drawer", await page.locator(".conversation-drawer").evaluate((element) => ({
    rect: element.getBoundingClientRect().toJSON(),
    transform: getComputedStyle(element).transform,
    position: getComputedStyle(element).position,
    zIndex: getComputedStyle(element).zIndex,
  })));
  await page.screenshot({ path: join(screenshots, "chat-workbench-mobile.png"), fullPage: true });
  console.log("E2E: screenshots");

  if (consoleErrors.length) throw new Error(`浏览器控制台错误：${consoleErrors.join(" | ")}`);
  console.log(JSON.stringify({
    projectId,
    agentNames: [...new Set(agentNames)],
    screenshots: ["chat-workbench-desktop.png", "chat-workbench-mobile.png"],
    consoleErrors: 0,
  }));
} finally {
  await browser.close();
}

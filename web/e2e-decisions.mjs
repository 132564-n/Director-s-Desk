import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});

const now = new Date().toISOString();
const decision = {
  id: "decision-1",
  episode_id: "project-1",
  conversation_id: "conversation-1",
  source_message_id: "message-director",
  question: "第一集结尾停在哪里？",
  context: "两个方向都成立，需要创作者拍板。",
  category: "story_timeline",
  scope: "episode",
  options: [
    { id: "option-light", label: "灯重新点亮", description: "主题完成闭环", impact: "温暖收束", risk: "悬念较弱", recommended: true },
    { id: "option-dawn", label: "破晓钟响", description: "以时间变化收束", impact: "仪式感更强", risk: "扩大时间跨度", recommended: false },
  ],
  status: "pending",
  created_at: now,
  resolved_at: null,
  selected_option_id: null,
  resolved_value: "",
  revision: 1,
  history: [],
  affected_artifacts: [],
};
const conversation = {
  id: "conversation-1", episode_id: "project-1", title: "主题会", goal: "确定第一集主题",
  members: ["总导演", "编剧", "连续性审校"], template: "剧情会", created_at: now,
  updated_at: now, status: "waiting", pinned: false, archived: false, active_turn_id: null,
  max_rounds: 6, proposals: {}, decisions: { [decision.id]: decision },
  messages: [
    { id: "message-system", kind: "system", content: "会话已建立。", created_at: now, sender_name: "系统", sender_role: null, model: "", round: 0, reply_to: null, attachment_ids: [], proposal_id: null, discarded: false },
    { id: "message-director", kind: "director_decision", content: "两个方向都成立，请用户拍板。", created_at: now, sender_name: "总导演", sender_role: "总导演", model: "deepseek-flash", round: 3, reply_to: null, attachment_ids: [], proposal_id: null, discarded: false },
  ],
};
const shelf = { proposals: [], decisions: [decision], artifacts: [], assets: [] };
const episodes = [{ id: "project-1", title: "长安不夜城", target_duration_seconds: 240, active_stage: "outline", stage_statuses: { outline: "ready", script: "blocked", direction: "blocked" } }];

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  await page.route("http://127.0.0.1:8000/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = { "access-control-allow-origin": "*", "content-type": "application/json" };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    if (url.pathname.endsWith("/decisions/decision-1/resolve")) {
      const body = request.postDataJSON();
      decision.status = body.action === "confirm" ? "confirmed" : body.action === "reject" ? "rejected" : "deferred";
      decision.selected_option_id = body.option_id;
      decision.resolved_value = body.option_id === "option-light" ? "灯重新点亮：主题完成闭环" : body.custom_value;
      decision.resolved_at = new Date().toISOString();
      conversation.status = "complete";
      return route.fulfill({ json: conversation, headers });
    }
    if (url.pathname === "/episodes") return route.fulfill({ json: episodes, headers });
    if (url.pathname === "/conversations") return route.fulfill({ json: [conversation], headers });
    if (url.pathname === "/conversations/conversation-1") return route.fulfill({ json: conversation, headers });
    if (url.pathname === "/episodes/project-1/shelf") return route.fulfill({ json: shelf, headers });
    return route.fulfill({ status: 404, json: { detail: "mock route missing" }, headers });
  });

  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  const inline = page.locator(".message-feed .decision-card");
  const inbox = page.locator(".decision-inbox .decision-card");
  await inline.waitFor();
  await inbox.waitFor();
  assert.equal(await page.getByText("第一集结尾停在哪里？").count(), 2);
  await inline.locator(".decision-options label").filter({ hasText: "灯重新点亮" }).click();
  await inline.getByRole("button", { name: "确认并写入事实库" }).click();
  await page.getByText("已写入项目事实").waitFor();
  await page.locator(".memory-ticket").filter({ hasText: "灯重新点亮" }).waitFor();

  await page.setViewportSize({ width: 390, height: 667 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Mobile page overflows horizontally");
  assert.deepEqual(errors, []);
  console.log("PASS: inline decision, decision inbox, confirmation sync, confirmed memory, mobile width; user data unchanged.");
} finally {
  await browser.close();
}

import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const outputDir = path.resolve("e2e-output");
await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
});

const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(`console: ${message.text()}`);
});
page.on("pageerror", (error) => errors.push(`page: ${error.message}`));

const projectId = `mist-city-${Date.now()}`;

try {
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "先让故事站稳， 再让镜头开口。" }).waitFor();
  await page.screenshot({ path: path.join(outputDir, "01-dashboard.png"), fullPage: true });

  await page.getByRole("button", { name: /建立新单集/ }).first().click();
  await page.getByLabel("单集名称").fill("雾城来信 · 验收集");
  await page.getByLabel("项目编号").fill(projectId);
  await page.getByLabel("目标时长（秒）").fill("240");
  await page.getByLabel("单镜头上限（可选）").fill("3");
  await page.getByLabel("提示词语言").selectOption("bilingual");
  await page.getByRole("button", { name: "建立导演案" }).click();
  await page.waitForURL(`**/episodes/${projectId}`);
  await page.getByText("雾城来信 · 验收集").waitFor();

  await page.getByRole("button", { name: "团队配置" }).click();
  await page.getByRole("heading", { name: "团队模型配置" }).waitFor();
  const assignments = await page.locator(".assignment-row").count();
  if (assignments !== 9) throw new Error(`Agent 模型分配数量错误: ${assignments}`);
  await page.getByRole("button", { name: "保存团队配置" }).click();
  await page.getByText("模型分配已保存").waitFor();

  await page.getByRole("button", { name: /资产库/ }).click();
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  );
  await page.getByLabel("选择资产图片").setInputFiles({
    name: "lin-wu.png",
    mimeType: "image/png",
    buffer: png,
  });
  await page.getByLabel("资产名称").fill("林雾定妆");
  await page.getByLabel("类型").selectOption("character");
  await page.getByLabel("初始规则").selectOption("locked");
  await page.getByRole("button", { name: "上传到资产库" }).click();
  await page.getByRole("heading", { name: "林雾定妆" }).waitFor();
  await page.getByPlaceholder(/描述必须保留/).fill("黑色短发，灰色风衣，左眼下有一颗小痣，冷静克制");
  await page.getByRole("button", { name: "确认并锁定描述" }).click();
  await page.getByText("已确认").waitFor();

  await page.getByRole("button", { name: "制作台" }).click();
  await completeStage(page, "outline", "故事大纲", "提交大纲审批");
  await page.getByRole("button", { name: /分场剧本/ }).click();
  await completeStage(page, "script", "分场剧本", "提交剧本审批");
  await page.getByRole("button", { name: /导演执行包/ }).click();
  await page.getByRole("button", { name: "召集团队生成草案" }).click();
  await page.getByText("团队草案已生成").waitFor();
  const durations = await page.locator('input[type="number"]').evaluateAll(
    (inputs) => inputs.map((input) => input.value),
  );
  if (!durations.length || durations.some((value) => Number(value) > 3)) {
    throw new Error(`镜头时长限制未生效: ${durations.join(",")}`);
  }
  await page.screenshot({ path: path.join(outputDir, "02-direction-workspace.png"), fullPage: true });
  await page.getByRole("button", { name: /提交执行包审批/ }).click();
  await page.getByText("待审批").first().waitFor();
  await page.getByPlaceholder("审批说明或修改意见").fill("执行包验收通过");
  await page.getByRole("button", { name: "确认通过" }).click();
  await page.getByText("已通过").first().waitFor();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /导出执行包/ }).click();
  const exported = await download;
  await exported.saveAs(path.join(outputDir, "director-package.zip"));
  await page.screenshot({ path: path.join(outputDir, "03-approved.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  await page.screenshot({ path: path.join(outputDir, "04-mobile-dashboard.png"), fullPage: true });

  if (errors.length) throw new Error(`浏览器出现错误:\n${errors.join("\n")}`);
  console.log(JSON.stringify({ projectId, screenshots: 4, exported: true, errors: 0 }));
} finally {
  await browser.close();
}

async function completeStage(page, stage, heading, submitLabel) {
  await page.getByRole("heading", { name: heading, exact: true }).waitFor();
  await page.getByRole("button", { name: "召集团队生成草案" }).click();
  await page.getByText("团队草案已生成").waitFor();
  await page.getByRole("button", { name: new RegExp(submitLabel) }).click();
  await page.getByText("待审批").first().waitFor();
  await page.getByPlaceholder("审批说明或修改意见").fill(`${stage} 阶段验收通过`);
  await page.getByRole("button", { name: "确认通过" }).click();
  await page.getByText("已通过").first().waitFor();
}

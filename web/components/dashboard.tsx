"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, createEpisode, listEpisodes } from "@/lib/api";
import type { EpisodeSummary, StageKey, StageStatus } from "@/lib/types";

const STAGES: Array<{ key: StageKey; label: string }> = [
  { key: "outline", label: "故事大纲" },
  { key: "script", label: "分场剧本" },
  { key: "direction", label: "导演执行包" },
];

const STATUS_LABELS: Record<StageStatus, string> = {
  ready: "待制作",
  in_review: "待审批",
  changes_requested: "需修改",
  approved: "已通过",
  stale: "需复审",
  blocked: "未解锁",
};

export function Dashboard() {
  const router = useRouter();
  const [episodes, setEpisodes] = useState<EpisodeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setEpisodes(await listEpisodes());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取项目");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const title = String(form.get("title") ?? "").trim();
    const id = String(form.get("id") ?? "").trim();
    const maxValue = String(form.get("maxShotDuration") ?? "").trim();
    setCreating(true);
    setError("");
    try {
      await createEpisode({
        id,
        title,
        targetDuration: Number(form.get("targetDuration")),
        maxShotDuration: maxValue ? Number(maxValue) : null,
        promptLanguage: form.get("promptLanguage") as "zh" | "en" | "bilingual",
      });
      router.push(`/episodes/${encodeURIComponent(id)}`);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "创建失败");
      setCreating(false);
    }
  }

  return (
    <main className="dashboard-shell">
      <header className="masthead">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <div><b>片场</b><span>AI 导演工作台</span></div>
        </div>
        <div className="local-badge"><span /> 本地工作区</div>
      </header>

      <section className="dashboard-hero">
        <div className="hero-copy">
          <p className="eyebrow">DIRECTOR&apos;S LEDGER · 001</p>
          <h1>先让故事站稳，<br /><em>再让镜头开口。</em></h1>
          <p className="hero-intro">
            九位专业 Agent 围绕同一份项目事实协作。你把握方向，
            总导演组织提案、质疑与定稿。
          </p>
          <button className="primary-action" onClick={() => setShowCreate(true)}>
            建立新单集 <span aria-hidden="true">↗</span>
          </button>
        </div>
        <div className="production-slate" aria-label="制作流程">
          <div className="slate-top"><span>一集一案</span><span>三次确认</span></div>
          <div className="slate-sequence">
            {STAGES.map((stage, index) => (
              <div className="slate-step" key={stage.key}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{stage.label}</strong>
                <small>{index === 0 ? "方向" : index === 1 ? "叙事" : "执行"}</small>
              </div>
            ))}
          </div>
          <p>每次上游改动，都会让相关下游重新亮起复审灯。</p>
        </div>
      </section>

      <section className="project-ledger">
        <div className="section-heading">
          <div><span>正在制作</span><h2>项目场记簿</h2></div>
          <button className="text-action" onClick={() => setShowCreate(true)}>＋ 新建单集</button>
        </div>

        {error ? <div className="error-banner" role="alert">{error}</div> : null}
        {loading ? <div className="loading-block">正在翻阅场记簿…</div> : null}
        {!loading && episodes.length === 0 ? (
          <button className="empty-project" onClick={() => setShowCreate(true)}>
            <span className="empty-cross" aria-hidden="true">＋</span>
            <strong>还没有单集</strong>
            <small>从一句故事创意开始建立第一份导演案</small>
          </button>
        ) : null}
        <div className="project-grid">
          {episodes.map((episode, projectIndex) => (
            <Link className="project-card" href={`/episodes/${episode.id}`} key={episode.id}>
              <div className="project-index">A{String(projectIndex + 1).padStart(2, "0")}</div>
              <div className="project-title-row">
                <div><small>{episode.target_duration_seconds} 秒目标时长</small><h3>{episode.title}</h3></div>
                <span className="open-arrow">↗</span>
              </div>
              <div className="mini-stage-track">
                {STAGES.map((stage) => (
                  <div key={stage.key} data-status={episode.stage_statuses[stage.key]}>
                    <span /><small>{stage.label}</small>
                    <b>{STATUS_LABELS[episode.stage_statuses[stage.key]]}</b>
                  </div>
                ))}
              </div>
            </Link>
          ))}
        </div>
      </section>

      {showCreate ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowCreate(false)}>
          <section className="create-sheet" role="dialog" aria-modal="true" aria-labelledby="create-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="sheet-heading">
              <div><span>NEW PRODUCTION</span><h2 id="create-title">建立新单集</h2></div>
              <button aria-label="关闭" onClick={() => setShowCreate(false)}>×</button>
            </div>
            <form onSubmit={handleCreate}>
              <label><span>单集名称</span><input name="title" required placeholder="例如：雾城来信" autoFocus /></label>
              <label><span>项目编号</span><input name="id" required pattern="[A-Za-z0-9][A-Za-z0-9_\-]{0,63}" placeholder="例如：mist-city-01" /><small>使用英文、数字、短横线或下划线</small></label>
              <div className="form-pair">
                <label><span>目标时长（秒）</span><input name="targetDuration" type="number" min="1" defaultValue="240" required /></label>
                <label><span>单镜头上限（可选）</span><input name="maxShotDuration" type="number" min="0.1" step="0.1" placeholder="默认不限制" /></label>
              </div>
              <label><span>提示词语言</span><select name="promptLanguage" defaultValue="zh"><option value="zh">中文</option><option value="en">英文</option><option value="bilingual">中英双语</option></select></label>
              <div className="sheet-actions"><button type="button" className="secondary-action" onClick={() => setShowCreate(false)}>取消</button><button className="primary-action" disabled={creating}>{creating ? "正在建档…" : "建立导演案"}</button></div>
            </form>
          </section>
        </div>
      ) : null}
    </main>
  );
}

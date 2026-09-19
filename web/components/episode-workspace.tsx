"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AgentRoom } from "@/components/agent-room";
import { AssetLibrary } from "@/components/asset-library";
import { StageEditor } from "@/components/stage-editor";
import { StageRail } from "@/components/stage-rail";
import { TeamSettings } from "@/components/team-settings";
import {
  ApiError,
  approveStage,
  confirmAsset,
  downloadExport,
  draftStage,
  getEpisode,
  requestChanges,
  submitDirection,
  submitOutline,
  submitScript,
  uploadAsset,
} from "@/lib/api";
import type {
  AssetKind,
  AssetPolicy,
  DirectionPayload,
  DraftResult,
  OutlinePayload,
  ScriptPayload,
  StageKey,
  WorkflowView,
} from "@/lib/types";

export function EpisodeWorkspace({ episodeId }: { episodeId: string }) {
  const [workflow, setWorkflow] = useState<WorkflowView | null>(null);
  const [selectedStage, setSelectedStage] = useState<StageKey>("outline");
  const [view, setView] = useState<"production" | "assets" | "settings">("production");
  const [drafts, setDrafts] = useState<Partial<Record<StageKey, DraftResult>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const result = await getEpisode(episodeId);
      setWorkflow(result);
      setSelectedStage(result.active_stage ?? "direction");
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法打开项目");
    }
  }, [episodeId]);

  useEffect(() => { void load(); }, [load]);

  async function perform(operation: () => Promise<WorkflowView>, clearDraft?: StageKey) {
    setBusy(true); setError("");
    try {
      const result = await operation();
      setWorkflow(result);
      if (clearDraft) setDrafts((current) => ({ ...current, [clearDraft]: undefined }));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "操作失败");
    } finally { setBusy(false); }
  }

  async function handleDraft() {
    setBusy(true); setError("");
    try {
      const result = await draftStage(episodeId, selectedStage);
      setDrafts((current) => ({ ...current, [selectedStage]: result }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "生成草案失败");
    } finally { setBusy(false); }
  }

  function handleSubmit(payload: OutlinePayload | ScriptPayload | DirectionPayload) {
    const operation = selectedStage === "outline"
      ? () => submitOutline(episodeId, payload as OutlinePayload)
      : selectedStage === "script"
        ? () => submitScript(episodeId, payload as ScriptPayload)
        : () => submitDirection(episodeId, payload as DirectionPayload);
    void perform(operation, selectedStage);
  }

  if (!workflow) {
    return <main className="workspace-loading"><div className="brand-mark"><i /><i /><i /></div><p>{error || "正在布置片场…"}</p><Link href="/">返回项目场记簿</Link></main>;
  }

  const episode = workflow.episode;
  const statuses = {
    outline: episode.stages.outline.status,
    script: episode.stages.script.status,
    direction: episode.stages.direction.status,
  };

  return (
    <main className="workspace-shell">
      <header className="workspace-topbar">
        <Link className="compact-brand" href="/"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><b>片场</b></Link>
        <div className="episode-ident"><span>EPISODE</span><b>{episode.title}</b><small>{episode.settings.target_duration_seconds} 秒 · {episode.settings.prompt_language === "zh" ? "中文提示词" : episode.settings.prompt_language === "en" ? "英文提示词" : "中英双语"}</small></div>
        <nav className="workspace-tabs"><button className={view === "production" ? "active" : ""} onClick={() => setView("production")}>制作台</button><button className={view === "assets" ? "active" : ""} onClick={() => setView("assets")}>资产库 <span>{Object.keys(episode.assets).length}</span></button><button className={view === "settings" ? "active" : ""} onClick={() => setView("settings")}>团队配置</button></nav>
        <button className="export-action" onClick={() => void downloadExport(episodeId, episode.title)}>导出执行包 ↧</button>
      </header>
      {error ? <div className="workspace-error" role="alert"><span>{error}</span><button onClick={() => setError("")}>×</button></div> : null}
      <div className="workspace-grid">
        <StageRail statuses={statuses} selected={selectedStage} onSelect={(stage) => { setSelectedStage(stage); setView("production"); }} />
        {view === "production" ? (
          <StageEditor
            stage={selectedStage}
            state={episode.stages[selectedStage]}
            draft={drafts[selectedStage] ?? null}
            busy={busy}
            onDraft={() => void handleDraft()}
            onSubmit={handleSubmit}
            onApprove={(note) => void perform(() => approveStage(episodeId, selectedStage, note), selectedStage)}
            onRequestChanges={(note) => void perform(() => requestChanges(episodeId, selectedStage, note))}
          />
        ) : view === "assets" ? (
          <AssetLibrary
            assets={Object.values(episode.assets)}
            busy={busy}
            onUpload={(input: { file: File; name: string; kind: AssetKind; policy: AssetPolicy }) => void perform(() => uploadAsset(episodeId, input))}
            onConfirm={(assetId, input) => void perform(() => confirmAsset(episodeId, assetId, input))}
          />
        ) : <TeamSettings />}
        {view === "production" ? <AgentRoom stage={selectedStage} draft={drafts[selectedStage] ?? null} /> : view === "assets" ? <AssetRules /> : <ModelRules />}
      </div>
    </main>
  );
}

function AssetRules() {
  return (
    <aside className="asset-rules"><div className="panel-kicker"><span>ASSET RULES</span><i>项目事实</i></div><h2>先确认，再引用</h2><p>上传图片后，补充机器可执行的视觉描述，并决定它是锁定资产还是参考资产。</p><dl><div><dt>锁定资产</dt><dd>角色定妆、固定服装、核心场景。提示词不得擅自改变。</dd></div><div><dt>参考资产</dt><dd>只提供构图、色彩或质感方向，允许导演团队提出调整。</dd></div></dl></aside>
  );
}

function ModelRules() {
  return (
    <aside className="asset-rules"><div className="panel-kicker"><span>MODEL RULES</span><i>本地安全</i></div><h2>模型可换，流程不变</h2><p>不同角色可以使用不同厂商与模型，制作状态机和项目事实不会因此改变。</p><dl><div><dt>密钥隔离</dt><dd>可在网页填写密钥，在本机加密保存、不回显；也支持环境变量。</dd></div><div><dt>手动分配</dt><dd>首版不自动选择模型，便于复现结果、控制成本并定位问题。</dd></div><div><dt>演示适配器</dt><dd>默认使用本地演示团队。切换真实接口后，缺少密钥会明确报错。</dd></div></dl></aside>
  );
}

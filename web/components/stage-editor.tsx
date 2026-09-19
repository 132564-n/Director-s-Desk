"use client";

import { FormEvent, useState } from "react";
import type {
  DirectionPayload,
  DraftResult,
  OutlinePayload,
  ScenePayload,
  ScriptPayload,
  ShotPayload,
  StageKey,
  StageState,
} from "@/lib/types";

const STAGE_COPY: Record<StageKey, { kicker: string; title: string; intro: string }> = {
  outline: {
    kicker: "GATE 01 · DIRECTION",
    title: "故事大纲",
    intro: "确定这一集为何值得看。审批后，编剧才能进入分场。",
  },
  script: {
    kicker: "GATE 02 · NARRATIVE",
    title: "分场剧本",
    intro: "让每一场都有明确行动与信息变化，再交给分镜导演。",
  },
  direction: {
    kicker: "GATE 03 · EXECUTION",
    title: "导演执行包",
    intro: "镜头、提示词、配音与音乐方案在这里汇合并接受最终审批。",
  },
};

export function StageEditor({
  stage,
  state,
  draft,
  busy,
  onDraft,
  onSubmit,
  onApprove,
  onRequestChanges,
}: {
  stage: StageKey;
  state: StageState;
  draft: DraftResult | null;
  busy: boolean;
  onDraft: () => void;
  onSubmit: (payload: OutlinePayload | ScriptPayload | DirectionPayload) => void;
  onApprove: (note: string) => void;
  onRequestChanges: (note: string) => void;
}) {
  const copy = STAGE_COPY[stage];
  const payload = draft?.artifact ?? state.artifact?.payload ?? null;
  const editorKey = `${stage}-${state.artifact?.revision ?? 0}-${draft ? "draft" : "saved"}`;

  if (state.status === "blocked") {
    return (
      <section className="stage-editor locked-editor">
        <div className="lock-glyph" aria-hidden="true">Ⅱ</div>
        <p>{copy.kicker}</p><h1>{copy.title}尚未解锁</h1>
        <span>请先完成并批准上一个阶段。制作顺序是项目事实的一部分。</span>
      </section>
    );
  }

  return (
    <section className="stage-editor">
      <header className="editor-heading">
        <div><p>{copy.kicker}</p><h1>{copy.title}</h1><span>{copy.intro}</span></div>
        <div className={`status-ticket status-${state.status}`}>
          <small>STATUS</small><b>{statusText(state.status)}</b>
        </div>
      </header>

      {state.review_note ? <div className="review-note"><b>上一轮意见</b><span>{state.review_note}</span></div> : null}

      <div className="draft-toolbar">
        <div><b>{draft ? "团队草案已生成" : state.artifact ? `当前为第 ${state.artifact.revision} 版` : "等待第一版草案"}</b><span>{draft ? "会审意见已同步到右侧，可编辑后提交。" : "演示团队会根据已批准内容生成可编辑草案。"}</span></div>
        <button className="secondary-action" onClick={onDraft} disabled={busy}>{busy ? "团队工作中…" : draft ? "重新生成草案" : "召集团队生成草案"}</button>
      </div>

      {stage === "outline" ? (
        <OutlineEditor key={editorKey} initial={payload as OutlinePayload | null} disabled={busy} onSubmit={onSubmit} />
      ) : null}
      {stage === "script" ? (
        <ScriptEditor key={editorKey} initial={payload as ScriptPayload | null} disabled={busy} onSubmit={onSubmit} />
      ) : null}
      {stage === "direction" ? (
        <DirectionEditor key={editorKey} initial={payload as DirectionPayload | null} disabled={busy} onSubmit={onSubmit} />
      ) : null}

      {state.status === "in_review" ? (
        <ReviewBar busy={busy} onApprove={onApprove} onRequestChanges={onRequestChanges} />
      ) : null}
    </section>
  );
}

function OutlineEditor({ initial, disabled, onSubmit }: { initial: OutlinePayload | null; disabled: boolean; onSubmit: (payload: OutlinePayload) => void }) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [logline, setLogline] = useState(initial?.logline ?? "");
  const [beats, setBeats] = useState(initial?.beats.join("\n") ?? "");
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({ title, logline, beats: beats.split("\n").map((item) => item.trim()).filter(Boolean) });
  }
  return (
    <form className="artifact-form" onSubmit={submit}>
      <label><span>大纲标题</span><input value={title} onChange={(event) => setTitle(event.target.value)} required placeholder="给这一版故事一个工作标题" /></label>
      <label><span>一句话故事</span><textarea value={logline} onChange={(event) => setLogline(event.target.value)} required rows={3} placeholder="主角、目标、阻力与代价" /></label>
      <label><span>故事节拍</span><textarea value={beats} onChange={(event) => setBeats(event.target.value)} required rows={8} placeholder="每行一个节拍，按发生顺序填写" /><small>每行一个节拍。审批后将按节拍生成场次。</small></label>
      <SubmitRow disabled={disabled} label="提交大纲审批" />
    </form>
  );
}

function ScriptEditor({ initial, disabled, onSubmit }: { initial: ScriptPayload | null; disabled: boolean; onSubmit: (payload: ScriptPayload) => void }) {
  const [scenes, setScenes] = useState<ScenePayload[]>(initial?.scenes ?? []);
  function update(index: number, patch: Partial<ScenePayload>) {
    setScenes((current) => current.map((scene, position) => position === index ? { ...scene, ...patch } : scene));
  }
  function addScene() {
    setScenes((current) => [...current, { id: `scene-${current.length + 1}`, heading: "", action: "", dialogue: [] }]);
  }
  return (
    <form className="artifact-form" onSubmit={(event) => { event.preventDefault(); onSubmit({ scenes }); }}>
      <div className="form-section-title"><div><span>SCENE LIST</span><b>{scenes.length} 个场次</b></div><button type="button" className="text-action" onClick={addScene}>＋ 添加场次</button></div>
      {scenes.length === 0 ? <div className="form-empty">先生成团队草案，或手动添加第一个场次。</div> : null}
      <div className="scene-list">
        {scenes.map((scene, index) => (
          <article className="scene-card" key={`${scene.id}-${index}`}>
            <header><span>SC {String(index + 1).padStart(2, "0")}</span><input aria-label="场次标题" value={scene.heading} required onChange={(event) => update(index, { heading: event.target.value })} /><button type="button" aria-label="删除场次" onClick={() => setScenes((current) => current.filter((_, position) => position !== index))}>×</button></header>
            <label><span>动作与事件</span><textarea value={scene.action} required rows={4} onChange={(event) => update(index, { action: event.target.value })} /></label>
            <label><span>对白（每行一句）</span><textarea value={scene.dialogue.join("\n")} rows={3} onChange={(event) => update(index, { dialogue: event.target.value.split("\n").filter(Boolean) })} /></label>
          </article>
        ))}
      </div>
      <SubmitRow disabled={disabled || scenes.length === 0} label="提交剧本审批" />
    </form>
  );
}

function DirectionEditor({ initial, disabled, onSubmit }: { initial: DirectionPayload | null; disabled: boolean; onSubmit: (payload: DirectionPayload) => void }) {
  const [shots, setShots] = useState<ShotPayload[]>(initial?.shots ?? []);
  function update(index: number, patch: Partial<ShotPayload>) {
    setShots((current) => current.map((shot, position) => position === index ? { ...shot, ...patch } : shot));
  }
  return (
    <form className="artifact-form" onSubmit={(event) => { event.preventDefault(); onSubmit({ shots }); }}>
      <div className="form-section-title"><div><span>SHOT LIST</span><b>{shots.length} 个分镜</b></div><small>镜头时长将在后端再次硬校验</small></div>
      {shots.length === 0 ? <div className="form-empty">召集分镜团队生成第一版执行包。</div> : null}
      <div className="shot-list">
        {shots.map((shot, index) => (
          <details className="shot-card" open={index === 0} key={`${shot.id}-${index}`}>
            <summary><span>{String(index + 1).padStart(2, "0")}</span><b>{shot.title}</b><small>{shot.estimated_duration_seconds} 秒 · {shot.camera || "未设置机位"}</small></summary>
            <div className="shot-fields">
              <div className="form-pair"><label><span>镜头名称</span><input value={shot.title} onChange={(event) => update(index, { title: event.target.value })} /></label><label><span>预计时长（秒）</span><input type="number" min="0.1" step="0.1" value={shot.estimated_duration_seconds} onChange={(event) => update(index, { estimated_duration_seconds: Number(event.target.value) })} /></label></div>
              <label><span>画面描述</span><textarea rows={3} value={shot.visual_description} onChange={(event) => update(index, { visual_description: event.target.value })} /></label>
              <label><span>标准提示词</span><textarea rows={4} value={shot.standard_prompt} onChange={(event) => update(index, { standard_prompt: event.target.value })} /></label>
              <div className="form-pair"><label><span>机位与运镜</span><input value={shot.camera} onChange={(event) => update(index, { camera: event.target.value })} /></label><label><span>对白</span><input value={shot.dialogue} onChange={(event) => update(index, { dialogue: event.target.value })} /></label></div>
              <div className="form-pair"><label><span>配音指导</span><input value={shot.voice_direction} onChange={(event) => update(index, { voice_direction: event.target.value })} /></label><label><span>音乐指导</span><input value={shot.music_direction} onChange={(event) => update(index, { music_direction: event.target.value })} /></label></div>
            </div>
          </details>
        ))}
      </div>
      <SubmitRow disabled={disabled || shots.length === 0} label="提交执行包审批" />
    </form>
  );
}

function SubmitRow({ disabled, label }: { disabled: boolean; label: string }) {
  return <div className="submit-row"><span>提交后进入人工审批，仍可退回修改。</span><button className="primary-action" disabled={disabled}>{label} <span aria-hidden="true">→</span></button></div>;
}

function ReviewBar({ busy, onApprove, onRequestChanges }: { busy: boolean; onApprove: (note: string) => void; onRequestChanges: (note: string) => void }) {
  const [note, setNote] = useState("");
  return (
    <div className="review-bar">
      <div><span>YOUR DECISION</span><b>这一版是否可以进入下一阶段？</b></div>
      <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="审批说明或修改意见" />
      <button className="reject-action" disabled={busy || !note.trim()} onClick={() => onRequestChanges(note)}>退回修改</button>
      <button className="approve-action" disabled={busy} onClick={() => onApprove(note)}>确认通过</button>
    </div>
  );
}

function statusText(status: StageState["status"]) {
  return ({ ready: "制作中", in_review: "待审批", changes_requested: "需修改", approved: "已通过", stale: "需复审", blocked: "未解锁" })[status];
}

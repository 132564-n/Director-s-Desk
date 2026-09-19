import type { DraftResult, StageKey } from "@/lib/types";

const ALL_AGENTS = ["总导演", "策划", "编剧", "分镜导演", "美术指导", "提示词工程师", "连续性审校", "配音指导", "音乐指导"];

export function AgentRoom({ stage, draft }: { stage: StageKey; draft: DraftResult | null }) {
  const participants = new Set(draft?.participants ?? []);
  return (
    <aside className="agent-room">
      <div className="panel-kicker"><span>AGENT ROOM</span><i>{draft ? "会审完成" : "待召集"}</i></div>
      <h2>导演会审室</h2>
      <p className="agent-room-intro">总导演按当前阶段召集相关角色，最多完成两轮讨论。</p>
      <div className="agent-roster">
        {ALL_AGENTS.map((agent) => (
          <div key={agent} className={participants.has(agent) ? "called" : ""}>
            <span>{agent.slice(0, 1)}</span><b>{agent}</b><small>{participants.has(agent) ? "本轮参与" : "候场"}</small>
          </div>
        ))}
      </div>
      <div className="discussion-log">
        <div className="discussion-heading"><b>会审记录</b><span>{draft?.discussion.length ?? 0} 条</span></div>
        {draft ? draft.discussion.map((message, index) => (
          <article key={`${message.agent}-${index}`}>
            <header><b>{message.agent}</b><span>ROUND {message.round}</span></header>
            <p>{message.message}</p>
          </article>
        )) : (
          <div className="quiet-state">生成当前阶段草案后，会审意见会留在这里。</div>
        )}
      </div>
      <div className="stage-rule"><span>当前阶段</span><b>{stage === "outline" ? "故事大纲" : stage === "script" ? "分场剧本" : "导演执行包"}</b></div>
    </aside>
  );
}

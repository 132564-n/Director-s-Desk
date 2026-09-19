import type { StageKey, StageStatus } from "@/lib/types";

const STAGES: Array<{ key: StageKey; label: string; caption: string }> = [
  { key: "outline", label: "故事大纲", caption: "方向确认" },
  { key: "script", label: "分场剧本", caption: "叙事确认" },
  { key: "direction", label: "导演执行包", caption: "执行确认" },
];

const STATUS_LABEL: Record<StageStatus, string> = {
  ready: "可以开始",
  in_review: "等待审批",
  changes_requested: "需要修改",
  approved: "已确认",
  stale: "需要复审",
  blocked: "尚未解锁",
};

export function StageRail({
  statuses,
  selected,
  onSelect,
}: {
  statuses: Record<StageKey, StageStatus>;
  selected: StageKey;
  onSelect: (stage: StageKey) => void;
}) {
  return (
    <nav className="stage-rail" aria-label="制作阶段">
      <div className="rail-label"><span>场</span><span>记</span><span>轨</span></div>
      <div className="rail-frames">
        {STAGES.map((stage, index) => {
          const status = statuses[stage.key];
          return (
            <button
              key={stage.key}
              className={selected === stage.key ? "active" : ""}
              data-status={status}
              onClick={() => onSelect(stage.key)}
            >
              <span className="frame-number">{String(index + 1).padStart(2, "0")}</span>
              <span className="frame-copy"><b>{stage.label}</b><small>{stage.caption}</small></span>
              <span className="frame-status">{STATUS_LABEL[status]}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

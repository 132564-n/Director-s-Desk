"use client";

import Link from "next/link";
import {
  FormEvent,
  PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  API_URL,
  ApiError,
  createConversation,
  createEpisode,
  getConversation,
  getEpisodeShelf,
  listConversations,
  listEpisodes,
  sendChatMessage,
  stopConversation,
  updateConversation,
  updateProposal,
  uploadAsset,
} from "@/lib/api";
import type {
  AgentRole,
  Conversation,
  EpisodeShelf,
  EpisodeSummary,
  Proposal,
  StageKey,
} from "@/lib/types";

const ROLES: AgentRole[] = [
  "总导演",
  "策划",
  "编剧",
  "分镜导演",
  "美术指导",
  "提示词工程师",
  "连续性审校",
  "配音指导",
  "音乐指导",
];

const ROLE_INITIALS: Record<AgentRole, string> = {
  总导演: "导",
  策划: "策",
  编剧: "编",
  分镜导演: "镜",
  美术指导: "美",
  提示词工程师: "提",
  连续性审校: "审",
  配音指导: "声",
  音乐指导: "乐",
};

const STAGE_LABELS: Record<StageKey, string> = {
  outline: "故事大纲",
  script: "分场剧本",
  direction: "导演执行包",
};

const PROPOSAL_STATUS = {
  pending: "待处理",
  adopted: "已采纳草案",
  confirmed: "正式版本",
  revision_requested: "待修改",
  discarded: "已废弃",
} as const;

const STATUS_LABEL = {
  idle: "待开麦",
  running: "讨论中",
  waiting: "等待确认",
  complete: "本轮结束",
  failed: "运行失败",
  stopped: "已停止",
} as const;

const LAYOUT_KEY = "director.chat.layout.v1";

function timeLabel(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function proposalSummary(proposal: Proposal) {
  if (proposal.stage === "outline" && "logline" in proposal.payload) {
    return proposal.payload.logline;
  }
  if (proposal.stage === "script" && "scenes" in proposal.payload) {
    return `${proposal.payload.scenes.length} 场戏，已包含动作与对白。`;
  }
  if (proposal.stage === "direction" && "shots" in proposal.payload) {
    return `${proposal.payload.shots.length} 个镜头，含画面、提示词、配音与音乐指令。`;
  }
  return "结构化提案已就绪。";
}

export function ChatWorkbench() {
  const [episodes, setEpisodes] = useState<EpisodeSummary[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [activeEpisodeId, setActiveEpisodeId] = useState("");
  const [shelf, setShelf] = useState<EpisodeShelf | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [leftWidth, setLeftWidth] = useState(292);
  const [rightWidth, setRightWidth] = useState(330);
  const [showNewConversation, setShowNewConversation] = useState(false);
  const [showNewProject, setShowNewProject] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadShelf = useCallback(async (episodeId: string) => {
    if (!episodeId) return;
    try {
      setShelf(await getEpisodeShelf(episodeId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "资产架读取失败");
    }
  }, []);

  const selectConversation = useCallback(
    async (conversation: Conversation) => {
      setActiveConversation(conversation);
      setActiveEpisodeId(conversation.episode_id);
      localStorage.setItem("director.chat.last", conversation.id);
      await loadShelf(conversation.episode_id);
    },
    [loadShelf],
  );

  const bootstrap = useCallback(async () => {
    try {
      const [episodeRows, conversationRows] = await Promise.all([
        listEpisodes(),
        listConversations(),
      ]);
      setEpisodes(episodeRows);
      setConversations(conversationRows);
      const lastId = localStorage.getItem("director.chat.last");
      const selected =
        conversationRows.find((item) => item.id === lastId && !item.archived) ??
        conversationRows.find((item) => !item.archived) ??
        null;
      if (selected) {
        setActiveConversation(selected);
        setActiveEpisodeId(selected.episode_id);
        await loadShelf(selected.episode_id);
      } else if (episodeRows[0]) {
        setActiveEpisodeId(episodeRows[0].id);
        await loadShelf(episodeRows[0].id);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "工作台连接失败");
    } finally {
      setLoading(false);
    }
  }, [loadShelf]);

  useEffect(() => {
    const isMobile = window.matchMedia("(max-width: 760px)").matches;
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (raw) {
      try {
        const saved = JSON.parse(raw) as {
          leftOpen?: boolean;
          rightOpen?: boolean;
          leftWidth?: number;
          rightWidth?: number;
        };
        setLeftOpen(isMobile ? false : (saved.leftOpen ?? true));
        setRightOpen(isMobile ? false : (saved.rightOpen ?? true));
        setLeftWidth(saved.leftWidth ?? 292);
        setRightWidth(saved.rightWidth ?? 330);
      } catch {
        localStorage.removeItem(LAYOUT_KEY);
      }
    } else if (isMobile) {
      setLeftOpen(false);
      setRightOpen(false);
    }
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    localStorage.setItem(
      LAYOUT_KEY,
      JSON.stringify({ leftOpen, rightOpen, leftWidth, rightWidth }),
    );
  }, [leftOpen, rightOpen, leftWidth, rightWidth]);

  useEffect(() => {
    if (!activeConversation || activeConversation.status !== "running") return;
    const id = window.setInterval(async () => {
      try {
        const current = await getConversation(activeConversation.id);
        setActiveConversation(current);
        setConversations((items) =>
          items.map((item) => (item.id === current.id ? current : item)),
        );
        if (current.status !== "running") await loadShelf(current.episode_id);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "讨论状态刷新失败");
      }
    }, 800);
    return () => window.clearInterval(id);
  }, [activeConversation, loadShelf]);

  const beginResize = (
    side: "left" | "right",
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    const startX = event.clientX;
    const startWidth = side === "left" ? leftWidth : rightWidth;
    const move = (pointer: PointerEvent) => {
      const delta = pointer.clientX - startX;
      const next = Math.min(430, Math.max(236, startWidth + (side === "left" ? delta : -delta)));
      if (side === "left") setLeftWidth(next);
      else setRightWidth(next);
    };
    const end = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", end);
  };

  const resizeWithKeyboard = (
    side: "left" | "right",
    event: React.KeyboardEvent<HTMLDivElement>,
  ) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const visualDelta = event.key === "ArrowRight" ? 16 : -16;
    if (side === "left") {
      setLeftWidth((width) => Math.min(430, Math.max(236, width + visualDelta)));
    } else {
      setRightWidth((width) => Math.min(430, Math.max(236, width - visualDelta)));
    }
  };

  const refreshConversation = async (conversation: Conversation) => {
    setActiveConversation(conversation);
    const rows = await listConversations();
    setConversations(rows);
  };

  const handleConversationUpdate = async (
    conversation: Conversation,
    input: { title?: string; pinned?: boolean; archived?: boolean },
  ) => {
    try {
      const updated = await updateConversation(conversation.id, input);
      setConversations((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      if (activeConversation?.id === updated.id) setActiveConversation(updated);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话更新失败");
    }
  };

  const filteredConversations = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("zh-CN");
    return conversations.filter(
      (item) =>
        item.episode_id === activeEpisodeId &&
        (showArchived ? item.archived : !item.archived) &&
        (!needle || `${item.title} ${item.goal}`.toLocaleLowerCase("zh-CN").includes(needle)),
    );
  }, [activeEpisodeId, conversations, search, showArchived]);

  const activeEpisode = episodes.find((item) => item.id === activeEpisodeId) ?? null;

  if (loading) {
    return (
      <main className="chat-loading">
        <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
        <p>正在接通导演组频道…</p>
      </main>
    );
  }

  return (
    <main
      className={`chat-shell ${leftOpen ? "left-open" : ""} ${rightOpen ? "right-open" : ""}`}
      style={{
        "--left-width": `${leftWidth}px`,
        "--right-width": `${rightWidth}px`,
      } as React.CSSProperties}
    >
      <a className="skip-link" href="#chat-main">跳到聊天内容</a>
      {error ? (
        <div className="chat-error" role="alert">
          <span>{error}</span><button onClick={() => setError("")}>关闭</button>
        </div>
      ) : null}

      <aside className="conversation-drawer" aria-label="项目与会话">
        <header className="drawer-brand">
          <div className="brand-lockup compact">
            <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
            <div><b>片场</b><span>制片对讲台</span></div>
          </div>
          <button className="icon-button desktop-collapse" onClick={() => setLeftOpen(false)} aria-label="收起左侧栏">‹</button>
        </header>

        <section className="project-switcher">
          <Link className="api-settings-link" href="/settings">⚙ 团队 API 配置</Link>
          <div className="drawer-label"><span>制作项目</span><button aria-label="新建项目" onClick={() => setShowNewProject(true)}>＋</button></div>
          <div className="project-strip">
            {episodes.map((episode, index) => (
              <button
                key={episode.id}
                className={episode.id === activeEpisodeId ? "active" : ""}
                aria-pressed={episode.id === activeEpisodeId}
                onClick={() => {
                  setActiveEpisodeId(episode.id);
                  const first = conversations.find(
                    (item) => item.episode_id === episode.id && !item.archived,
                  );
                  setActiveConversation(first ?? null);
                  void loadShelf(episode.id);
                }}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><b>{episode.title}</b><small>{episode.target_duration_seconds} 秒 · {episode.active_stage ? STAGE_LABELS[episode.active_stage] : "已完成"}</small></div>
              </button>
            ))}
          </div>
        </section>

        <section className="conversation-index">
          <div className="conversation-tools">
            <label><span aria-hidden="true">⌕</span><input aria-label="搜索本集会话" autoComplete="off" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索本集会话…" /></label>
            <button className="new-chat-button" onClick={() => setShowNewConversation(true)} disabled={!activeEpisodeId}>＋ 新建会话</button>
          </div>
          <div className="conversation-list" role="list">
            {filteredConversations.map((conversation) => (
              <article
                role="listitem"
                key={conversation.id}
                className={activeConversation?.id === conversation.id ? "active" : ""}
              >
                <button className="conversation-main" aria-current={activeConversation?.id === conversation.id ? "page" : undefined} onClick={() => void selectConversation(conversation)}>
                  <span className={`status-lamp ${conversation.status}`} />
                  <span className="conversation-copy">
                    <b>{conversation.pinned ? "◆ " : ""}{conversation.title}</b>
                    <small>{conversation.goal}</small>
                  </span>
                  <time>{dateLabel(conversation.updated_at)}</time>
                </button>
                <div className="conversation-actions">
                  <button aria-label={conversation.pinned ? "取消置顶" : "置顶"} title={conversation.pinned ? "取消置顶" : "置顶"} onClick={() => void handleConversationUpdate(conversation, { pinned: !conversation.pinned })}>◇</button>
                  <button aria-label="重命名会话" title="重命名" onClick={() => {
                    const title = window.prompt("会话名称", conversation.title);
                    if (title?.trim()) void handleConversationUpdate(conversation, { title });
                  }}>✎</button>
                  <button aria-label={conversation.archived ? "恢复会话" : "归档会话"} title={conversation.archived ? "恢复" : "归档"} onClick={() => void handleConversationUpdate(conversation, { archived: !conversation.archived })}>{conversation.archived ? "↥" : "⌄"}</button>
                </div>
              </article>
            ))}
            {filteredConversations.length === 0 ? (
              <button className="empty-conversation" onClick={() => setShowNewConversation(true)}>
                <span>＋</span><b>{showArchived ? "没有已归档会话" : "为本集开一场创作会"}</b>
              </button>
            ) : null}
          </div>
          <button className="archive-toggle" onClick={() => setShowArchived((value) => !value)}>
            {showArchived ? "← 返回当前会话" : "▣ 查看归档"}
          </button>
        </section>
        <div
          className="resize-handle right-edge"
          role="separator"
          aria-label="调整会话栏宽度"
          aria-orientation="vertical"
          aria-valuemin={236}
          aria-valuemax={430}
          aria-valuenow={leftWidth}
          tabIndex={0}
          onPointerDown={(event) => beginResize("left", event)}
          onKeyDown={(event) => resizeWithKeyboard("left", event)}
        />
      </aside>

      <section className="chat-stage" id="chat-main">
        <header className="chat-header">
          <button className="icon-button sidebar-trigger" onClick={() => setLeftOpen((value) => !value)} aria-label={leftOpen ? "收起会话栏" : "打开会话栏"}>☰</button>
          <div className="channel-title">
            <p>{activeEpisode?.title ?? "尚未建立项目"} / GROUP CHANNEL</p>
            <h1>{activeConversation?.title ?? "导演组候场区"}</h1>
            <span>{activeConversation?.goal ?? "新建项目和会话后，九位专业 Agent 会在这里独立发言。"}</span>
          </div>
          {activeConversation ? (
            <div className="channel-presence">
              <div className="avatar-stack" aria-label="会话成员">
                {activeConversation.members.slice(0, 6).map((role) => (
                  <span key={role} data-role={role} title={role}>{ROLE_INITIALS[role]}</span>
                ))}
                {activeConversation.members.length > 6 ? <i>+{activeConversation.members.length - 6}</i> : null}
              </div>
              <span className={`run-ticket ${activeConversation.status}`} role="status"><i />{STATUS_LABEL[activeConversation.status]}</span>
            </div>
          ) : null}
          <button className="icon-button shelf-trigger" onClick={() => setRightOpen((value) => !value)} aria-label={rightOpen ? "收起资产架" : "打开资产架"}>▤</button>
        </header>

        {activeConversation ? (
          <ChatChannel
            key={activeConversation.id}
            conversation={activeConversation}
            shelf={shelf}
            onConversation={refreshConversation}
            onShelf={() => loadShelf(activeConversation.episode_id)}
            onError={setError}
          />
        ) : (
          <section className="channel-empty">
            <div className="empty-signal"><span /><span /><span /></div>
            <p>DIRECTOR CHANNEL / OFF AIR</p>
            <h2>{episodes.length ? "这集还没有创作会" : "先建立第一部漫剧"}</h2>
            <span>{episodes.length ? "选择团队成员，给这场讨论一个清楚目标。" : "项目事实、群聊讨论和生成资产都会留在本地工作区。"}</span>
            <button onClick={() => episodes.length ? setShowNewConversation(true) : setShowNewProject(true)}>
              {episodes.length ? "发起创作会" : "建立新项目"} ↗
            </button>
          </section>
        )}
      </section>

      <aside className="asset-drawer" aria-label="资产架">
        <div
          className="resize-handle left-edge"
          role="separator"
          aria-label="调整资产架宽度"
          aria-orientation="vertical"
          aria-valuemin={236}
          aria-valuemax={430}
          aria-valuenow={rightWidth}
          tabIndex={0}
          onPointerDown={(event) => beginResize("right", event)}
          onKeyDown={(event) => resizeWithKeyboard("right", event)}
        />
        <header className="shelf-header">
          <div><p>PRODUCTION SHELF</p><h2>本集资产架</h2></div>
          <button className="icon-button" onClick={() => setRightOpen(false)} aria-label="收起资产架">›</button>
        </header>
        <AssetShelf
          episodeId={activeEpisodeId}
          shelf={shelf}
          onChanged={() => loadShelf(activeEpisodeId)}
          onError={setError}
        />
      </aside>

      <button className="drawer-scrim" aria-label="关闭侧栏" onClick={() => { setLeftOpen(false); setRightOpen(false); }} />

      {showNewConversation ? (
        <NewConversationDialog
          episodeId={activeEpisodeId}
          onClose={() => setShowNewConversation(false)}
          onCreated={async (conversation) => {
            setShowNewConversation(false);
            setConversations(await listConversations());
            await selectConversation(conversation);
          }}
          onError={setError}
        />
      ) : null}

      {showNewProject ? (
        <NewProjectDialog
          busy={busy}
          onClose={() => setShowNewProject(false)}
          onSubmit={async (event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            setBusy(true);
            try {
              const id = String(data.get("id"));
              await createEpisode({
                id,
                title: String(data.get("title")),
                targetDuration: Number(data.get("duration")),
                maxShotDuration: data.get("shotLimit") ? Number(data.get("shotLimit")) : null,
                promptLanguage: data.get("language") as "zh" | "en" | "bilingual",
              });
              const rows = await listEpisodes();
              setEpisodes(rows);
              setActiveEpisodeId(id);
              setShowNewProject(false);
              setShowNewConversation(true);
            } catch (reason) {
              setError(reason instanceof Error ? reason.message : "项目创建失败");
            } finally {
              setBusy(false);
            }
          }}
        />
      ) : null}
    </main>
  );
}

function ChatChannel({
  conversation,
  shelf,
  onConversation,
  onShelf,
  onError,
}: {
  conversation: Conversation;
  shelf: EpisodeShelf | null;
  onConversation: (conversation: Conversation) => Promise<void>;
  onShelf: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<"discuss" | "proposal">("discuss");
  const [autonomous, setAutonomous] = useState(false);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const [awayFromLatest, setAwayFromLatest] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  const scrollToLatest = useCallback((behavior: ScrollBehavior = "smooth") => {
    const feed = feedRef.current;
    if (!feed) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    feed.scrollTo({
      top: feed.scrollHeight,
      behavior: reduceMotion ? "auto" : behavior,
    });
    setAwayFromLatest(false);
  }, []);

  useEffect(() => {
    if (!awayFromLatest) scrollToLatest(conversation.messages.length > 1 ? "smooth" : "auto");
  }, [awayFromLatest, conversation.messages.length, scrollToLatest]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    let content = message.trim();
    if (!content || conversation.status === "running") return;
    let sendMode = mode;
    if (content.startsWith("/讨论")) {
      sendMode = "discuss";
      content = content.replace(/^\/讨论\s*/, "");
    } else if (content.startsWith("/生成草案")) {
      sendMode = "proposal";
      content = content.replace(/^\/生成草案\s*/, "");
    } else if (content.startsWith("/审校")) {
      content = `@连续性审校 ${content.replace(/^\/审校\s*/, "")}`;
    } else if (content.startsWith("/总结")) {
      content = `请总结本轮共识和少数意见。${content.replace(/^\/总结\s*/, "")}`;
    }
    const mentions = conversation.members.filter((role) => content.includes(`@${role}`));
    setAwayFromLatest(false);
    setSending(true);
    try {
      const running = await sendChatMessage(conversation.id, {
        content,
        mode: sendMode,
        autonomous,
        mentions,
        attachmentIds: attachments,
      });
      setMessage("");
      setAttachments([]);
      await onConversation(running);
    } catch (reason) {
      onError(reason instanceof ApiError ? reason.message : "消息发送失败");
    } finally {
      setSending(false);
    }
  };

  const proposalById = conversation.proposals;
  const messagesById = new Map(conversation.messages.map((item) => [item.id, item]));

  return (
    <>
      <div className="message-pane">
        <div
          className="message-feed"
          ref={feedRef}
          role="log"
          aria-label="导演组消息记录"
          aria-live="polite"
          aria-relevant="additions text"
          tabIndex={0}
          onScroll={(event) => {
            const feed = event.currentTarget;
            setAwayFromLatest(feed.scrollHeight - feed.clientHeight - feed.scrollTop > 96);
          }}
        >
        <div className="feed-date"><span />本地制作记录 · {new Date(conversation.created_at).toLocaleDateString("zh-CN")}<span /></div>
        {conversation.messages.map((item) => {
          if (item.kind === "system") {
            return <div className="system-message" key={item.id}><span>场记</span>{item.content}</div>;
          }
          const reply = item.reply_to ? messagesById.get(item.reply_to) : null;
          const proposal = item.proposal_id ? proposalById[item.proposal_id] : null;
          return (
            <article className={`chat-message ${item.kind}`} key={item.id}>
              <div className="message-avatar" data-role={item.sender_role ?? "你"}>
                {item.sender_role ? ROLE_INITIALS[item.sender_role] : "我"}
              </div>
              <div className="message-column">
                <header>
                  <b>{item.sender_name}</b>
                  {item.sender_role ? <span>{item.model || "本地模型"}</span> : null}
                  {item.round ? <i>R{item.round}</i> : null}
                  <time>{timeLabel(item.created_at)}</time>
                </header>
                <div className="message-paper">
                  {reply ? <div className="reply-chip">回复 {reply.sender_name} · {reply.content.slice(0, 36)}</div> : null}
                  <p>{item.content}</p>
                  {item.attachment_ids.length ? <div className="message-attachments">▧ 引用了 {item.attachment_ids.length} 项资产</div> : null}
                </div>
                {proposal ? (
                  <ProposalCard
                    proposal={proposal}
                    busy={conversation.status === "running"}
                    onAction={async (action) => {
                      try {
                        const updated = await updateProposal(conversation.id, proposal.id, action);
                        await onConversation(updated);
                        await onShelf();
                      } catch (reason) {
                        onError(reason instanceof Error ? reason.message : "提案操作失败");
                      }
                    }}
                  />
                ) : null}
              </div>
            </article>
          );
        })}
        {conversation.status === "running" ? (
          <div className="agent-typing">
            <span className="typing-bars"><i /><i /><i /></span>
            导演组正在交换意见，完成的发言会逐条送达
          </div>
        ) : null}
        </div>
        {awayFromLatest ? (
          <button className="jump-latest" onClick={() => scrollToLatest("auto")}>
            跳到最新消息 ↓
          </button>
        ) : null}
      </div>

      <form className="chat-composer" onSubmit={submit}>
        <div className="composer-toolbar">
          <div className="mode-switch" role="group" aria-label="输出模式">
            <button type="button" className={mode === "discuss" ? "active" : ""} onClick={() => setMode("discuss")}>讨论</button>
            <button type="button" className={mode === "proposal" ? "active" : ""} onClick={() => setMode("proposal")}>生成提案</button>
          </div>
          <label className="autonomy-switch">
            <input type="checkbox" checked={autonomous} onChange={(event) => setAutonomous(event.target.checked)} />
            <span />Agent 自主讨论
          </label>
          {conversation.status === "running" ? (
            <button type="button" className="stop-run" onClick={async () => {
              try { await onConversation(await stopConversation(conversation.id)); }
              catch (reason) { onError(reason instanceof Error ? reason.message : "停止失败"); }
            }}>■ 停止本轮</button>
          ) : null}
        </div>
        <div className="mention-row">
          {conversation.members.filter((role) => role !== "总导演").slice(0, 7).map((role) => (
            <button type="button" key={role} onClick={() => setMessage((value) => `${value}${value ? " " : ""}@${role} `)}>@{role}</button>
          ))}
        </div>
        <div className="composer-body">
          <textarea
            aria-label="给导演组发送消息"
            autoComplete="off"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="给导演组下达任务，输入 @ 指定角色，或使用 /生成草案…"
            disabled={conversation.status === "running"}
            rows={3}
          />
          <button className="send-button" disabled={!message.trim() || sending || conversation.status === "running"}>
            <span>{sending ? "发送中" : mode === "proposal" ? "交付任务" : "发送"}</span><i>↗</i>
          </button>
        </div>
        <div className="composer-foot">
          <span>/讨论　/生成草案　/审校　/总结</span>
          <div className="asset-attach-list">
            {(shelf?.assets ?? []).filter((asset) => asset.confirmed).slice(0, 4).map((asset) => (
              <label key={asset.id} title={asset.name}>
                <input
                  type="checkbox"
                  checked={attachments.includes(asset.id)}
                  onChange={(event) => setAttachments((items) => event.target.checked ? [...items, asset.id] : items.filter((id) => id !== asset.id))}
                />
                ▧ {asset.name}
              </label>
            ))}
          </div>
        </div>
      </form>
    </>
  );
}

function ProposalCard({
  proposal,
  busy,
  onAction,
}: {
  proposal: Proposal;
  busy: boolean;
  onAction: (action: "adopt" | "confirm" | "revise") => Promise<void>;
}) {
  return (
    <section className="proposal-card">
      <header><span>PROPOSAL / {STAGE_LABELS[proposal.stage]}</span><i data-status={proposal.status}>{PROPOSAL_STATUS[proposal.status]}</i></header>
      <h3>{proposal.title}</h3>
      <p>{proposalSummary(proposal)}</p>
      <details><summary>查看结构内容</summary><pre>{JSON.stringify(proposal.payload, null, 2)}</pre></details>
      <footer>
        {proposal.status === "pending" || proposal.status === "revision_requested" ? <button disabled={busy} onClick={() => void onAction("adopt")}>采纳为草案</button> : null}
        {proposal.status === "adopted" ? <button className="confirm" disabled={busy} onClick={() => void onAction("confirm")}>确认正式版本</button> : null}
        {proposal.status !== "confirmed" ? <button className="quiet" disabled={busy} onClick={() => void onAction("revise")}>要求修改</button> : null}
      </footer>
    </section>
  );
}

function AssetShelf({
  episodeId,
  shelf,
  onChanged,
  onError,
}: {
  episodeId: string;
  shelf: EpisodeShelf | null;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const pending = shelf?.proposals.filter((item) => item.status !== "confirmed") ?? [];
  const confirmed = shelf?.artifacts ?? [];
  const assets = shelf?.assets ?? [];

  return (
    <div className="shelf-scroll">
      <section className="shelf-group">
        <header><span>待办提案</span><b>{String(pending.length).padStart(2, "0")}</b></header>
        {pending.map((proposal) => (
          <article className="shelf-proposal" key={proposal.id}>
            <i data-status={proposal.status}>{PROPOSAL_STATUS[proposal.status]}</i>
            <b>{proposal.title}</b>
            <small>{STAGE_LABELS[proposal.stage]} · {dateLabel(proposal.created_at)}</small>
          </article>
        ))}
        {!pending.length ? <p className="shelf-empty">没有等待处理的提案</p> : null}
      </section>

      <section className="shelf-group">
        <header><span>正式版本</span><b>{String(confirmed.length).padStart(2, "0")}</b></header>
        {confirmed.map((artifact) => (
          <Link className="artifact-ticket" href={`/episodes/${encodeURIComponent(episodeId)}`} key={`${artifact.stage}-${artifact.revision}`}>
            <span>{artifact.stage === "outline" ? "文" : artifact.stage === "script" ? "场" : "镜"}</span>
            <div><b>{STAGE_LABELS[artifact.stage]}</b><small>REV.{artifact.revision} · {artifact.author}</small></div>
            <i>↗</i>
          </Link>
        ))}
        {!confirmed.length ? <p className="shelf-empty">正式版本会在确认后归档于此</p> : null}
      </section>

      <section className="shelf-group asset-shelf-group">
        <header><span>参考资产</span><b>{String(assets.length).padStart(2, "0")}</b></header>
        <div className="shelf-assets">
          {assets.map((asset) => (
            <article key={asset.id}>
              <div className="shelf-thumb">
                {asset.source_path ? <img src={`${API_URL}/media/${asset.source_path}`} alt={asset.name} width={320} height={240} loading="lazy" /> : <span>{asset.name.slice(0, 1)}</span>}
                <i className={asset.confirmed ? "confirmed" : "pending"}>{asset.confirmed ? "锁定" : "待确认"}</i>
              </div>
              <b>{asset.name}</b><small>{asset.kind} · {asset.policy}</small>
            </article>
          ))}
        </div>
        {episodeId ? (
          <form className="shelf-upload" onSubmit={async (event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const file = data.get("file");
            if (!(file instanceof File) || !file.size) return;
            setUploading(true);
            try {
              await uploadAsset(episodeId, {
                file,
                name: String(data.get("name")),
                kind: "style",
                policy: "reference",
              });
              event.currentTarget.reset();
              await onChanged();
            } catch (reason) {
              onError(reason instanceof Error ? reason.message : "资产上传失败");
            } finally {
              setUploading(false);
            }
          }}>
            <label><input aria-label="选择资产图片" name="file" type="file" accept="image/png,image/jpeg,image/webp,image/gif" required /><span>＋ 放入图片</span></label>
            <input aria-label="资产名称" autoComplete="off" name="name" required placeholder="资产名称…" />
            <button disabled={uploading}>{uploading ? "上传中" : "加入资产架"}</button>
          </form>
        ) : null}
      </section>
    </div>
  );
}

function NewConversationDialog({
  episodeId,
  onClose,
  onCreated,
  onError,
}: {
  episodeId: string;
  onClose: () => void;
  onCreated: (conversation: Conversation) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [members, setMembers] = useState<AgentRole[]>(ROLES);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return (
    <div className="modal-backdrop chat-modal" onMouseDown={onClose}>
      <section className="create-sheet conversation-sheet" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="sheet-heading"><div><span>OPEN A CHANNEL</span><h2>发起创作会</h2></div><button type="button" aria-label="关闭新建会话窗口" onClick={onClose}>×</button></div>
        <form onSubmit={async (event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          setCreating(true);
          try {
            await onCreated(await createConversation({
              episodeId,
              title: String(data.get("title")),
              goal: String(data.get("goal")),
              template: String(data.get("template")),
              members,
            }));
          } catch (reason) {
            onError(reason instanceof Error ? reason.message : "会话创建失败");
          } finally {
            setCreating(false);
          }
        }}>
          <div className="form-pair">
            <label><span>会话名称</span><input name="title" autoComplete="off" required placeholder="例如：开场钩子会…" /></label>
            <label><span>会议模板</span><select name="template" defaultValue="自由讨论"><option>自由讨论</option><option>剧情会</option><option>分镜会</option><option>审校会</option></select></label>
          </div>
          <label><span>本轮目标</span><textarea name="goal" autoComplete="off" required rows={2} placeholder="只解决一个具体问题，结果会更清楚…" /></label>
          <fieldset className="member-picker"><legend>参会成员 · 总导演固定在场</legend>{ROLES.map((role) => (
            <label key={role} className={members.includes(role) ? "selected" : ""}>
              <input type="checkbox" checked={members.includes(role)} disabled={role === "总导演"} onChange={(event) => setMembers((items) => event.target.checked ? [...items, role] : items.filter((item) => item !== role))} />
              <span data-role={role}>{ROLE_INITIALS[role]}</span><b>{role}</b>
            </label>
          ))}</fieldset>
          <div className="sheet-actions"><button type="button" className="secondary-action" onClick={onClose}>取消</button><button className="primary-action" disabled={creating || members.length < 2}>{creating ? "正在开台…" : "进入群聊"}</button></div>
        </form>
      </section>
    </div>
  );
}

function NewProjectDialog({
  busy,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return (
    <div className="modal-backdrop chat-modal" onMouseDown={onClose}>
      <section className="create-sheet" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="sheet-heading"><div><span>NEW PRODUCTION</span><h2>建立漫剧项目</h2></div><button type="button" aria-label="关闭新建项目窗口" onClick={onClose}>×</button></div>
        <form onSubmit={(event) => void onSubmit(event)}>
          <div className="form-pair"><label><span>单集名称</span><input name="title" autoComplete="off" required placeholder="雾城来信 · 第一集…" /></label><label><span>项目编号</span><input name="id" autoComplete="off" spellCheck={false} required pattern="[A-Za-z0-9][A-Za-z0-9_\-]{0,63}" placeholder="mist-city-01…" /></label></div>
          <div className="form-pair"><label><span>目标时长（秒）</span><input name="duration" type="number" min="1" defaultValue="240" required /></label><label><span>单镜头上限</span><input name="shotLimit" type="number" min="0.1" step="0.1" placeholder="默认不限制" /></label></div>
          <label><span>提示词语言</span><select name="language" defaultValue="zh"><option value="zh">中文</option><option value="en">英文</option><option value="bilingual">中英双语</option></select></label>
          <div className="sheet-actions"><button type="button" className="secondary-action" onClick={onClose}>取消</button><button className="primary-action" disabled={busy}>{busy ? "正在建档…" : "建立并组建团队"}</button></div>
        </form>
      </section>
    </div>
  );
}

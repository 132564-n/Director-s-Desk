import type {
  AssetKind,
  AssetPolicy,
  AgentRole,
  Conversation,
  DirectionPayload,
  DraftResult,
  EpisodeShelf,
  EpisodeSummary,
  ModelSettings,
  OutlinePayload,
  ScriptPayload,
  StageKey,
  WorkflowView,
} from "@/lib/types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(body?.detail ?? `请求失败（${response.status}）`, response.status);
  }
  return response.json() as Promise<T>;
}

export function listEpisodes() {
  return request<EpisodeSummary[]>("/episodes");
}

export function listConversations(episodeId?: string) {
  const query = episodeId ? `?episode_id=${encodeURIComponent(episodeId)}` : "";
  return request<Conversation[]>(`/conversations${query}`);
}

export function getConversation(id: string) {
  return request<Conversation>(`/conversations/${encodeURIComponent(id)}`);
}

export function createConversation(input: {
  episodeId: string;
  title: string;
  goal: string;
  members: AgentRole[];
  template: string;
}) {
  return request<Conversation>("/conversations", {
    method: "POST",
    body: JSON.stringify({
      episode_id: input.episodeId,
      title: input.title,
      goal: input.goal,
      members: input.members,
      template: input.template,
    }),
  });
}

export function updateConversation(
  id: string,
  input: { title?: string; pinned?: boolean; archived?: boolean },
) {
  return request<Conversation>(`/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function sendChatMessage(
  id: string,
  input: {
    content: string;
    mode: "discuss" | "proposal";
    autonomous: boolean;
    mentions: AgentRole[];
    attachmentIds: string[];
  },
) {
  return request<Conversation>(`/conversations/${encodeURIComponent(id)}/messages`, {
    method: "POST",
    body: JSON.stringify({
      content: input.content,
      mode: input.mode,
      autonomous: input.autonomous,
      mentions: input.mentions,
      attachment_ids: input.attachmentIds,
    }),
  });
}

export function stopConversation(id: string) {
  return request<Conversation>(`/conversations/${encodeURIComponent(id)}/stop`, {
    method: "POST",
  });
}

export function updateProposal(
  conversationId: string,
  proposalId: string,
  action: "adopt" | "confirm" | "revise",
) {
  return request<Conversation>(
    `/conversations/${encodeURIComponent(conversationId)}/proposals/${encodeURIComponent(proposalId)}/${action}`,
    { method: "POST" },
  );
}

export function getEpisodeShelf(id: string) {
  return request<EpisodeShelf>(`/episodes/${encodeURIComponent(id)}/shelf`);
}

export function getModelSettings() {
  return request<ModelSettings>("/settings/models");
}

export function testModelConnection(providerId: string, model: string) {
  return request<{ ok: boolean; message: string }>("/settings/models/test", {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId, model }),
  });
}

export function updateModelSettings(settings: ModelSettings) {
  return request<ModelSettings>("/settings/models", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

export function getEpisode(id: string) {
  return request<WorkflowView>(`/episodes/${encodeURIComponent(id)}`);
}

export function createEpisode(input: {
  id: string;
  title: string;
  targetDuration: number;
  maxShotDuration: number | null;
  promptLanguage: "zh" | "en" | "bilingual";
}) {
  return request<WorkflowView>("/episodes", {
    method: "POST",
    body: JSON.stringify({
      id: input.id,
      title: input.title,
      settings: {
        target_duration_seconds: input.targetDuration,
        max_shot_duration_seconds: input.maxShotDuration,
        prompt_language: input.promptLanguage,
      },
      assets: [],
    }),
  });
}

export function draftStage(id: string, stage: StageKey) {
  return request<DraftResult>(`/episodes/${encodeURIComponent(id)}/draft/${stage}`, {
    method: "POST",
  });
}

export function submitOutline(id: string, payload: OutlinePayload) {
  return request<WorkflowView>(`/episodes/${encodeURIComponent(id)}/outline`, {
    method: "POST",
    body: JSON.stringify({ ...payload, author: "导演团队" }),
  });
}

export function submitScript(id: string, payload: ScriptPayload) {
  return request<WorkflowView>(`/episodes/${encodeURIComponent(id)}/script`, {
    method: "POST",
    body: JSON.stringify({ ...payload, author: "导演团队" }),
  });
}

export function submitDirection(id: string, payload: DirectionPayload) {
  return request<WorkflowView>(`/episodes/${encodeURIComponent(id)}/direction`, {
    method: "POST",
    body: JSON.stringify({ ...payload, author: "导演团队" }),
  });
}

export function approveStage(id: string, stage: StageKey, note: string) {
  return request<WorkflowView>(
    `/episodes/${encodeURIComponent(id)}/stages/${stage}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ reviewer: "用户", note }),
    },
  );
}

export function requestChanges(id: string, stage: StageKey, note: string) {
  return request<WorkflowView>(
    `/episodes/${encodeURIComponent(id)}/stages/${stage}/request-changes`,
    {
      method: "POST",
      body: JSON.stringify({ reviewer: "用户", note }),
    },
  );
}

export function uploadAsset(
  id: string,
  input: { file: File; name: string; kind: AssetKind; policy: AssetPolicy },
) {
  const body = new FormData();
  body.set("file", input.file);
  body.set("name", input.name);
  body.set("kind", input.kind);
  body.set("policy", input.policy);
  return request<WorkflowView>(`/episodes/${encodeURIComponent(id)}/assets`, {
    method: "POST",
    body,
  });
}

export function confirmAsset(
  id: string,
  assetId: string,
  input: { description: string; policy: AssetPolicy },
) {
  return request<WorkflowView>(
    `/episodes/${encodeURIComponent(id)}/assets/${encodeURIComponent(assetId)}/confirm`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export async function downloadExport(id: string, title: string) {
  const response = await fetch(`${API_URL}/episodes/${encodeURIComponent(id)}/export`);
  if (!response.ok) throw new ApiError("导出失败", response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${title}-导演执行包.zip`;
  anchor.click();
  URL.revokeObjectURL(url);
}

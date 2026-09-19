export type StageKey = "outline" | "script" | "direction";
export type StageStatus =
  | "ready"
  | "in_review"
  | "changes_requested"
  | "approved"
  | "stale"
  | "blocked";

export type AssetPolicy = "locked" | "reference";
export type AssetKind = "character" | "location" | "prop" | "style";

export interface ProjectSettings {
  target_duration_seconds: number;
  prompt_language: "zh" | "en" | "bilingual";
  max_shot_duration_seconds: number | null;
}

export interface Asset {
  id: string;
  name: string;
  kind: AssetKind;
  policy: AssetPolicy;
  confirmed: boolean;
  description: string;
  source_path: string;
  mime_type: string;
}

export interface OutlinePayload {
  title: string;
  logline: string;
  beats: string[];
}

export interface ScenePayload {
  id: string;
  heading: string;
  action: string;
  dialogue: string[];
}

export interface ScriptPayload {
  scenes: ScenePayload[];
}

export interface ShotPayload {
  id: string;
  scene_id: string;
  title: string;
  estimated_duration_seconds: number;
  visual_description: string;
  standard_prompt: string;
  asset_ids: string[];
  camera: string;
  dialogue: string;
  voice_direction: string;
  music_direction: string;
}

export interface DirectionPayload {
  shots: ShotPayload[];
}

export type ArtifactPayload = OutlinePayload | ScriptPayload | DirectionPayload;

export interface VersionedArtifact {
  stage: StageKey;
  revision: number;
  author: string;
  payload: ArtifactPayload & { stage?: StageKey };
  submitted_at: string;
}

export interface StageState {
  status: StageStatus;
  artifact: VersionedArtifact | null;
  review_note: string;
}

export interface Episode {
  id: string;
  title: string;
  settings: ProjectSettings;
  assets: Record<string, Asset>;
  stages: Record<StageKey, StageState>;
  approvals: Array<{
    stage: StageKey;
    revision: number;
    reviewer: string;
    note: string;
    approved_at: string;
  }>;
}

export interface WorkflowView {
  episode: Episode;
  active_stage: StageKey | null;
  complete: boolean;
}

export interface EpisodeSummary {
  id: string;
  title: string;
  target_duration_seconds: number;
  active_stage: StageKey | null;
  stage_statuses: Record<StageKey, StageStatus>;
}

export interface DiscussionMessage {
  agent: string;
  round: number;
  message: string;
}

export interface DraftResult {
  stage: StageKey;
  participants: string[];
  discussion: DiscussionMessage[];
  artifact: (ArtifactPayload & { stage: StageKey });
}

export interface ProviderSettings {
  id: string;
  label: string;
  kind: "demo" | "openai_compatible";
  base_url: string;
  api_key_env: string;
  api_key_set?: boolean;
  api_key?: string;
}

export interface AgentModelSettings {
  role: string;
  provider_id: string;
  model: string;
}

export interface ModelSettings {
  providers: ProviderSettings[];
  assignments: AgentModelSettings[];
}

export type AgentRole =
  | "总导演"
  | "策划"
  | "编剧"
  | "分镜导演"
  | "美术指导"
  | "提示词工程师"
  | "连续性审校"
  | "配音指导"
  | "音乐指导";

export type ConversationStatus =
  | "idle"
  | "running"
  | "waiting"
  | "complete"
  | "failed"
  | "stopped";

export type MessageKind = "user" | "agent" | "system" | "director_decision";
export type ProposalStatus =
  | "pending"
  | "adopted"
  | "confirmed"
  | "revision_requested"
  | "discarded";

export type DecisionStatus = "pending" | "confirmed" | "deferred" | "rejected" | "needs_review";
export type FactScope = "project" | "episode";
export type FactCategory =
  | "theme_audience"
  | "world_rule"
  | "character"
  | "story_timeline"
  | "scene_prop"
  | "visual_asset"
  | "shot_duration"
  | "voice_music"
  | "production_constraint"
  | "open_question";

export interface DecisionOption {
  id: string;
  label: string;
  description: string;
  impact: string;
  risk: string;
  recommended: boolean;
}

export interface DecisionRevision {
  revision: number;
  status: DecisionStatus;
  resolved_value: string;
  selected_option_id: string | null;
  changed_at: string;
}

export interface DecisionCard {
  id: string;
  episode_id: string;
  conversation_id: string;
  source_message_id: string;
  question: string;
  context: string;
  category: FactCategory;
  scope: FactScope;
  options: DecisionOption[];
  status: DecisionStatus;
  created_at: string;
  resolved_at: string | null;
  selected_option_id: string | null;
  resolved_value: string;
  revision: number;
  history: DecisionRevision[];
  affected_artifacts: StageKey[];
}

export interface ChatMessage {
  id: string;
  kind: MessageKind;
  content: string;
  created_at: string;
  sender_name: string;
  sender_role: AgentRole | null;
  model: string;
  round: number;
  reply_to: string | null;
  attachment_ids: string[];
  proposal_id: string | null;
  discarded: boolean;
}

export interface Proposal {
  id: string;
  stage: StageKey;
  title: string;
  payload: ArtifactPayload;
  status: ProposalStatus;
  source_message_id: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  episode_id: string;
  title: string;
  goal: string;
  members: AgentRole[];
  template: string;
  created_at: string;
  updated_at: string;
  status: ConversationStatus;
  pinned: boolean;
  archived: boolean;
  messages: ChatMessage[];
  proposals: Record<string, Proposal>;
  decisions: Record<string, DecisionCard>;
  active_turn_id: string | null;
  max_rounds: number;
}

export interface ShelfArtifact {
  stage: StageKey;
  revision: number;
  author: string;
  payload: ArtifactPayload;
  submitted_at: string;
}

export interface EpisodeShelf {
  proposals: Proposal[];
  decisions: DecisionCard[];
  artifacts: ShelfArtifact[];
  assets: Asset[];
}

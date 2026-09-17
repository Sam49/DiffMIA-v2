export type Role = "ADMIN" | "RESEARCHER" | "VIEWER";
export type ExperimentStatusValue = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type ClassificationValue =
  | "LOW_EVIDENCE"
  | "NORMAL"
  | "ELEVATED"
  | "POSSIBLE_CONTAMINATION"
  | "HIGH_CONTAMINATION_SIGNAL";

export interface User {
  id: number;
  username: string;
  email: string;
  role: Role;
  is_active: boolean;
  auth_provider?: string;
  email_verified?: boolean;
  /** True when a Google identity is attached to the account. */
  google_linked?: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
  verification?: {
    required: boolean;
    development_token?: string | null;
  } | null;
}

export interface ErrorBody {
  error: string;
  message: string;
  request_id?: string;
}

export interface ModelInfo {
  id: number;
  name: string;
  display_name: string;
  provider: "mock" | "transformers" | "openai_compatible" | "deepseek" | string;
  model_id: string;
  description: string;
  config_json?: string;
  is_active: boolean;
  is_mock?: boolean;
  supports_logprobs?: boolean;
}

export interface DatasetInfo {
  id: number;
  name: string;
  description: string;
  source_format: string;
  content_hash: string;
  item_count: number;
  created_at?: string;
}

export interface DatasetItemInfo {
  id: number;
  dataset_id: number;
  external_id: string;
  dataset_name: string;
  problem_statement: string;
  code: string;
  language: string;
  metadata_json: string;
  content_hash: string;
  position: number;
}

export interface ExperimentSummary {
  id: number;
  name: string;
  description: string;
  created_by: number;
  model_id: number;
  dataset_id: number;
  dataset_hash: string;
  model_version: string;
  mutation_count: number;
  mutation_seed: number;
  mutation_strength: number;
  mutation_strategy: string;
  temperature: number;
  max_tokens: number;
  batch_size: number;
  device: string;
  config_json: string;
  status: ExperimentStatusValue;
  current_stage: string;
  progress_message: string;
  total_items: number;
  processed_items: number;
  error_code: string;
  error_message: string;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  model_name?: string;
  dataset_name?: string;
}

export interface ExperimentDetail extends ExperimentSummary {
  model: ModelInfo | null;
  dataset: {
    id: number;
    name: string;
    description: string;
    source_format: string;
    content_hash: string;
    item_count: number;
  } | null;
  created_by_user: string;
}

export interface Analysis {
  snippet_id: number;
  external_id: string;
  dataset_name: string;
  problem_statement: string;
  code: string;
  language: string;
  metadata_json: string;
  original_loss: number | null;
  original_token_count: number | null;
  mean_mutation_loss: number | null;
  median_mutation_loss: number | null;
  std_mutation_loss: number | null;
  mutation_count_used: number;
  mutation_count_requested: number;
  contamination_index: number | null;
  abs_loss_delta: number | null;
  rel_loss_delta: number | null;
  z_score: number | null;
  z_score_global: number | null;
  effect_size: number | null;
  percentile_rank: number | null;
  classification: ClassificationValue;
  classification_reason: string;
  flagged: boolean;
  extra_json: string;
}

export interface Distribution {
  label: string;
  values: number[];
  histogram_x: number[];
  histogram_y: number[];
  kde_x: number[];
  kde_y: number[];
}

export interface ExperimentStats {
  analyzed_count: number;
  flagged_count: number;
  high_signal_count: number;
  low_evidence_count: number;
  failed_snippets: number;
  mean_ci: number | null;
  median_ci: number | null;
  std_ci: number | null;
  mean_z: number | null;
  mean_original_loss: number | null;
  mean_mutation_loss: number | null;
  total_items?: number;
  epsilon: number;
}

export interface Conclusion {
  verdict:
    | "NO_DATA"
    | "NO_MATERIAL_SIGNAL"
    | "ELEVATED_DIFFERENTIAL_SIGNAL"
    | "STRONG_DIFFERENTIAL_SIGNAL"
    | string;
  evidence_level: string;
  flagged_share: number;
  headline: string;
  observations: string[];
  caveats: string[];
  corroboration: string[];
  narrative_markdown: string;
}

export interface ResultsBundle {
  experiment: ExperimentDetail;
  stats: ExperimentStats;
  analyses: Analysis[];
  classifications: Record<string, number>;
  distributions: Record<string, Distribution>;
  pairs: [number, number][];
  conclusion?: Conclusion;
  disclaimer?: string;
}

export interface MutationInfo {
  id: number;
  experiment_id: number;
  snippet_id: number;
  mutation_index: number;
  seed: number;
  original_code: string;
  mutated_code: string;
  language: string;
  mapping_json: string;
  validation_status: string;
  validation_score: number;
}

export interface MutationMapping {
  seed: number;
  mapping: Record<string, string>;
  attempts?: number;
}

export interface Paged<T> {
  items: T[];
  total: number;
  offset?: number;
  limit?: number;
}

export interface DemoStatus {
  mode: string;
  model_ready: boolean;
  dataset_ready: boolean;
  mock_model: string;
  hint: string;
}

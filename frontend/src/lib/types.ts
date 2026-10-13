export type Project = {
  id: number;
  name: string;
  description?: string | null;
  target_category?: string | null;
  home_label_cn?: string | null;
  home_label_en?: string | null;
  settings: Record<string, unknown>;
  created_at: string;
};

export type Job = {
  id: number;
  project_id: number;
  job_type: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED" | "CANCEL_REQUESTED";
  progress: number;
  total_items: number;
  processed_items: number;
  error_count: number;
  params: Record<string, unknown>;
  result?: Record<string, unknown>;
  message?: string | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  crawl?: { processed_urls: number; discovered_urls: number; error_count: number; skipped_robots: number; status: string };
};

export type CategoryNode = {
  id: number;
  external_id?: string | null;
  url?: string | null;
  name_cn: string;
  name_en?: string | null;
  parent_name?: string | null;
  depth: number;
  breadcrumb_cn: string;
  breadcrumb_en?: string | null;
  children_count: number;
  product_count?: number | null;
  is_inferred: boolean;
  is_root: boolean;
};

export type TreeNode = {
  id: number;
  name_cn?: string;
  name?: string;
  name_en?: string | null;
  url?: string | null;
  depth: number;
  is_inferred: boolean;
  product_count?: number | null;
  match_type?: string | null;
  source?: string | null;
  children: TreeNode[];
};

export type Candidate = { node_id: number; name: string; breadcrumb: string; score: number; signals: string[] };

export type Srp = {
  id: number;
  keyword: string;
  url?: string | null;
  h1?: string | null;
  keyword_en?: string | null;
  keyword_en_generated?: string | null;
  en_source?: string | null;
  search_volume?: number | null;
  product_count?: number | null;
  core_product?: string | null;
  modifiers: string[];
  canonical_concept?: string | null;
  matched_node_id?: number | null;
  matched_category?: string | null;
  matched_category_url?: string | null;
  matched_category_breadcrumb?: string | null;
  match_method?: string | null;
  score?: number | null;
  confidence?: number | null;
  confidence_band?: string | null;
  candidates: Candidate[];
  breadcrumb_cn?: string | null;
  breadcrumb_en?: string | null;
  duplicate_intent?: string | null;
  recommended_action?: string | null;
  potential_gap: boolean;
  reason?: string | null;
  review_status?: string | null;
};

export type LinkChange = { label: string; relevance: number; irrelevant?: boolean; relevant?: boolean; new_page?: boolean };

export type Audit = {
  id: number;
  node_id: number;
  category_name: string;
  category_url?: string | null;
  current_breadcrumb_cn: string;
  current_breadcrumb_en?: string | null;
  current_parent?: string | null;
  issues: string[];
  action: string;
  recommended_parent?: string | null;
  recommended_parent_status?: string | null;
  recommended_breadcrumb_cn?: string | null;
  recommended_breadcrumb_en?: string | null;
  current_score: number;
  recommended_score: number;
  score_breakdown: { current?: Record<string, number>; recommended?: Record<string, number> };
  current_ancestors: string[];
  recommended_ancestors: string[];
  links_removed: LinkChange[];
  links_added: LinkChange[];
  linking_improvement?: string | null;
  linking_explanation?: string | null;
  reason?: string | null;
  confidence: number;
  evidence: Record<string, unknown>;
  review_status?: string | null;
};

export type Competitor = {
  id: number;
  name: string;
  start_url: string;
  target_category?: string | null;
  max_urls: number;
  max_depth: number;
  include_patterns: string[];
  exclude_patterns: string[];
  render_js: boolean;
  crawl_delay?: number | null;
  status: string;
  categories: number;
  last_crawl?: { id: number; status: string; processed_urls: number; discovered_urls: number; error_count: number; skipped_robots: number; started_at?: string; completed_at?: string } | null;
  last_job?: Job | null;
};

export type CrawlPage = {
  id: number;
  competitor_id: number;
  url: string;
  status_code?: number | null;
  canonical?: string | null;
  indexability?: string | null;
  title?: string | null;
  h1?: string | null;
  breadcrumb_text?: string | null;
  depth: number;
  parent_url?: string | null;
  anchor_text?: string | null;
  internal_links_count: number;
  child_category_links: { url: string; text: string }[];
  product_link_count: number;
  page_type?: string | null;
  category_confidence?: number | null;
  category_name?: string | null;
  error?: string | null;
};

export type CompetitorCategory = {
  id: number;
  competitor_id: number;
  name: string;
  url?: string | null;
  parent_name?: string | null;
  depth: number;
  breadcrumb: string;
  children_names: string[];
  hierarchy_source?: string | null;
  is_inferred: boolean;
};

export type CompetitorMapping = {
  id: number;
  competitor: string;
  competitor_category: string;
  competitor_breadcrumb: string;
  competitor_url?: string | null;
  match_type: string;
  my_category?: string | null;
  my_breadcrumb?: string | null;
  my_url?: string | null;
  parent_maps_to?: string | null;
  score?: number | null;
  confidence?: number | null;
  method?: string | null;
  reason?: string | null;
  review_status?: string | null;
};

export type GapChild = {
  id: number;
  name_cn: string;
  name_en?: string | null;
  status: string;
  existing_url?: string | null;
  existing_breadcrumb?: string | null;
  suggested_breadcrumb_cn?: string | null;
  suggested_breadcrumb_en?: string | null;
  supporting_srps: { keyword: string; search_volume?: number | null }[];
  search_volume: number;
};

export type Gap = {
  id: number;
  gap_type: string;
  parent_name_cn?: string | null;
  parent_name_en?: string | null;
  parent_status?: string | null;
  main_name_cn?: string | null;
  main_name_en?: string | null;
  main_status?: string | null;
  existing_url?: string | null;
  current_breadcrumb_cn?: string | null;
  suggested_breadcrumb_cn?: string | null;
  suggested_breadcrumb_en?: string | null;
  supporting_srps: { keyword: string; search_volume?: number | null; product_count?: number | null; match?: string }[];
  srp_count: number;
  combined_search_volume: number;
  product_count?: number | null;
  competitor_evidence: Record<string, { name: string; breadcrumb: string; url?: string | null }[]>;
  competitor_count: number;
  score: number;
  score_breakdown: Record<string, number>;
  priority?: string | null;
  confidence: number;
  reason?: string | null;
  recommended_action?: string | null;
  links_added: string[];
  links_removed: string[];
  linking_improvement?: string | null;
  en_source?: string | null;
  review_status?: string | null;
  children: GapChild[];
};

export type Synonym = {
  id: number;
  alias: string;
  canonical: string;
  preferred_node_id?: number | null;
  preferred_category_name?: string | null;
  notes?: string | null;
  approved_by?: string | null;
  source: string;
};

export type ReviewItem = {
  entity_type: EntityType;
  id: number;
  title: string;
  status?: string | null;
  confidence?: number | null;
  current?: string | null;
  recommended?: string | null;
  reason?: string | null;
  kind?: string | null;
  priority?: string | null;
  search_volume?: number | null;
  linking?: string | null;
  candidates?: Candidate[];
};

export type EntityType = "srp" | "audit" | "gap" | "competitor_mapping";

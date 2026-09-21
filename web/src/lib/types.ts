export type Recommendation = "Go" | "Conditional Go" | "No-Go"

export interface Pricing {
  summary: string
  source_ids: string[]
  verified: boolean
}

export interface Competitor {
  name: string
  positioning: string
  target_customers: string
  key_features: string[]
  pricing: Pricing
  source_ids: string[]
}

export interface MarketSignal {
  statement: string
  interpretation: string
  source_ids: string[]
}

export interface MarketAnalysis {
  executive_summary: string
  market_signals: MarketSignal[]
  competitors: Competitor[]
  opportunities: string[]
  barriers: string[]
  recommendation: Recommendation
  confidence: number
  rationale: string[]
  risks: string[]
  next_steps: string[]
  limitations: string[]
}

export interface CoverageSummary {
  unique_sources: number
  official_sources: number
  claim_count: number
  pricing_claims: number
  low_coverage: boolean
}

export interface Source {
  id: string
  url: string
  title: string
  domain: string
  source_type: "official" | "research" | "media" | "other"
  accessed_at: string
  query_id: string
}

export interface QualityResult {
  passed: boolean
  issues: Array<{ code: string; message: string; fatal: boolean }>
}

export interface ReportResponse {
  run_id: string
  topic: string
  generated_at: string
  report_path: string
  analysis: MarketAnalysis
  coverage: CoverageSummary
  sources: Source[]
  quality: QualityResult
  stats: Record<string, unknown>
  warnings: string[]
  report_markdown: string
}

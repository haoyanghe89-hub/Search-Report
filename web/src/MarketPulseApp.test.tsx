import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import MarketPulseApp from "@/MarketPulseApp"
import type { ReportResponse } from "@/lib/types"

const report: ReportResponse = {
  run_id: "run_test",
  topic: "AI meeting notes tools",
  generated_at: "2026-09-17T02:00:00Z",
  report_path: "reports/test.md",
  analysis: {
    executive_summary: "市场存在付费需求，但进入需要差异化。",
    market_signals: [{ statement: "存在公开价格", interpretation: "市场成熟", source_ids: ["S1"] }],
    competitors: [{
      name: "Acme",
      positioning: "会议助手",
      target_customers: "团队",
      key_features: ["转录"],
      pricing: { summary: "$20/month", source_ids: ["S1"], verified: true },
      source_ids: ["S1"],
    }],
    opportunities: ["垂直场景"],
    barriers: ["竞争激烈"],
    recommendation: "Conditional Go",
    confidence: 0.78,
    rationale: ["需求存在", "已经付费", "需要差异化"],
    risks: ["获客成本"],
    next_steps: ["完成访谈"],
    limitations: [],
  },
  coverage: { unique_sources: 1, official_sources: 1, claim_count: 3, pricing_claims: 1, low_coverage: true },
  sources: [{
    id: "S1",
    url: "https://example.com/pricing",
    title: "Acme pricing",
    domain: "example.com",
    source_type: "official",
    accessed_at: "2026-09-17T02:00:00Z",
    query_id: "q1",
  }],
  quality: { passed: true, issues: [] },
  stats: {},
  warnings: [],
  report_markdown: "# report",
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("MarketPulse app", () => {
  it("shows the initial research prompt", () => {
    render(<MarketPulseApp />)
    expect(screen.getByRole("heading", { name: /把一个产品方向/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "生成报告" })).toBeInTheDocument()
  })

  it("submits a topic and renders a structured report", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(report), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    const user = userEvent.setup()
    render(<MarketPulseApp />)

    await user.click(screen.getByRole("button", { name: "生成报告" }))

    expect(await screen.findByText("CONDITIONAL GO")).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "核心结论" })).toHaveAttribute(
      "aria-selected",
      "true",
    )
    await user.click(screen.getByRole("tab", { name: "竞品对比" }))
    expect(screen.getByRole("heading", { name: "竞品对比" })).toBeInTheDocument()
    await user.click(screen.getByRole("tab", { name: "证据来源" }))
    expect(screen.getByText("Acme pricing")).toBeInTheDocument()
  })
})

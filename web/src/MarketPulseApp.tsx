import { useEffect, useState, type FormEvent } from "react"
import { ActivityIcon, AlertTriangleIcon, SearchIcon } from "lucide-react"

import { LoadingReport } from "@/components/loading-report"
import { ReportView } from "@/components/report-view"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { generateReport } from "@/lib/api"
import type { ReportResponse } from "@/lib/types"

type Status = "idle" | "loading" | "success" | "error"

function MarketPulseApp() {
  const [topic, setTopic] = useState("AI meeting notes tools")
  const [status, setStatus] = useState<Status>("idle")
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [error, setError] = useState("")
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (status !== "loading") return
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [status])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const cleaned = topic.trim()
    if (cleaned.length < 2) {
      setError("请输入至少 2 个字符的产品方向或关键词。")
      setStatus("error")
      return
    }

    setStatus("loading")
    setError("")
    setElapsed(0)
    try {
      const data = await generateReport({ topic: cleaned, competitor_limit: 5 })
      setReport(data)
      setStatus("success")
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "报告生成失败，请稍后重试。")
      setStatus("error")
    }
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="wordmark" href="#top" aria-label="MarketPulse 首页">
          <span className="wordmark-mark" aria-hidden="true"><ActivityIcon /></span>
          <span>MarketPulse</span>
        </a>
        <span className="header-note">AI 市场可行性研究</span>
      </header>

      <main id="top" className="page-main">
        <section className="hero-copy" aria-labelledby="page-title">
          <p className="eyebrow">PRODUCT INTELLIGENCE / 01</p>
          <h1 id="page-title">把一个产品方向，变成可讨论的市场决策。</h1>
          <p>
            MarketPulse 自动检索全球英文公开网页，核验竞品与价格，再由 DeepSeek
            输出中文决策备忘录。
          </p>
        </section>

        <Card>
          <CardContent>
            <form onSubmit={handleSubmit} aria-label="生成市场报告">
              <FieldGroup>
                <Field data-invalid={status === "error" && !report}>
                  <FieldLabel htmlFor="topic">产品方向或关键词</FieldLabel>
                  <div className="research-controls">
                    <Input
                      id="topic"
                      value={topic}
                      onChange={(event) => setTopic(event.target.value)}
                      placeholder="例如：AI meeting notes tools"
                      autoComplete="off"
                      disabled={status === "loading"}
                      aria-invalid={status === "error" && !report}
                    />
                    <Button type="submit" disabled={status === "loading"}>
                      {status === "loading" ? (
                        <Spinner data-icon="inline-start" />
                      ) : (
                        <SearchIcon data-icon="inline-start" />
                      )}
                      {status === "loading" ? "研究中" : "生成报告"}
                    </Button>
                  </div>
                  <FieldDescription>
                    单次运行约需 1–5 分钟；报告将保留来源链接与证据覆盖提示。
                  </FieldDescription>
                </Field>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>

        {status === "error" && (
          <Alert variant="destructive">
            <AlertTriangleIcon aria-hidden="true" />
            <AlertTitle>本次研究未完成</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {status === "loading" && <LoadingReport elapsed={elapsed} />}
        {status !== "loading" && report && <ReportView report={report} />}

        {status === "idle" && !report && (
          <Empty className="empty-report">
            <EmptyHeader>
              <EmptyMedia variant="icon"><SearchIcon aria-hidden="true" /></EmptyMedia>
              <EmptyTitle>等待第一个研究方向</EmptyTitle>
              <EmptyDescription>
                提交关键词后，这里会依次呈现决策结论、市场信号、竞品、定价与证据来源。
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </main>

      <footer className="site-footer">
        <span>MarketPulse Agent</span>
        <span>公开网页研究 · DeepSeek 分析 · 中文报告</span>
      </footer>
    </div>
  )
}

export default MarketPulseApp

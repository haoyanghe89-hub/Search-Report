import {
  ArrowUpRightIcon,
  CheckCircle2Icon,
  FileTextIcon,
  Globe2Icon,
  LightbulbIcon,
  ShieldAlertIcon,
  TagIcon,
} from "lucide-react"

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { Recommendation, ReportResponse } from "@/lib/types"

const verdictMeta: Record<
  Recommendation,
  { label: string; helper: string; badge: "default" | "secondary" | "destructive" }
> = {
  Go: { label: "GO", helper: "建议进入", badge: "default" },
  "Conditional Go": {
    label: "CONDITIONAL GO",
    helper: "满足条件后进入",
    badge: "secondary",
  },
  "No-Go": { label: "NO-GO", helper: "暂不建议进入", badge: "destructive" },
}

const sourceLabels = {
  official: "官方",
  research: "研究",
  media: "媒体",
  other: "其他",
}

function Citations({ ids }: { ids: string[] }) {
  return (
    <span className="citation-list" aria-label={`来源 ${ids.join("、")}`}>
      {ids.map((id) => <span className="citation-chip" key={id}>{id}</span>)}
    </span>
  )
}

function SectionHeading({
  index,
  title,
  description,
}: {
  index: string
  title: string
  description: string
}) {
  return (
    <div className="section-heading">
      <span>{index}</span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  )
}

function observedPriceRange(report: ReportResponse) {
  const values = report.analysis.competitors.flatMap((competitor) =>
    [...competitor.pricing.summary.matchAll(/(?:\$|USD\s*)(\d+(?:\.\d+)?)/gi)].map(
      (match) => Number(match[1]),
    ),
  )
  if (!values.length) return null
  return { min: Math.min(...values), max: Math.max(...values) }
}

export function ReportView({ report }: { report: ReportResponse }) {
  const meta = verdictMeta[report.analysis.recommendation]
  const priceRange = observedPriceRange(report)
  const generatedAt = new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(report.generated_at))

  return (
    <article className="report" aria-label={`${report.topic} 市场可行性报告`}>
      <div className="report-meta">
        <span>{generatedAt}</span>
        <span>{report.run_id}</span>
      </div>

      <Tabs defaultValue="decision" className="report-tabs">
        <TabsList variant="line" className="report-tab-list" aria-label="报告章节">
          <TabsTrigger value="decision">核心结论</TabsTrigger>
          <TabsTrigger value="market">市场概览</TabsTrigger>
          <TabsTrigger value="competitors">竞品对比</TabsTrigger>
          <TabsTrigger value="pricing">定价区间</TabsTrigger>
          <TabsTrigger value="sources">证据来源</TabsTrigger>
          <TabsTrigger value="actions">行动建议</TabsTrigger>
        </TabsList>

        <TabsContent value="decision" className="report-tab-panel">
          <section className="decision-panel" data-verdict={report.analysis.recommendation}>
            <div className="decision-stamp" aria-label={`结论：${meta.helper}`}>
              <span>{meta.label}</span>
              <small>{meta.helper}</small>
            </div>
            <div className="decision-copy">
              <div className="decision-kicker">
                <Badge variant={meta.badge}>核心结论</Badge>
                <span>置信度 {Math.round(report.analysis.confidence * 100)}%</span>
              </div>
              <h2>{report.topic}</h2>
              <p>{report.analysis.executive_summary}</p>
              <Separator />
              <ul className="rationale-list">
                {report.analysis.rationale.map((item) => (
                  <li key={item}><CheckCircle2Icon aria-hidden="true" />{item}</li>
                ))}
              </ul>
            </div>
          </section>

          {report.coverage.low_coverage && (
            <Alert>
              <ShieldAlertIcon aria-hidden="true" />
              <AlertTitle>证据覆盖较低</AlertTitle>
              <AlertDescription>
                当前结论可用于方向筛选，不宜直接作为投资决策；建议补充一手访谈与付费数据。
              </AlertDescription>
            </Alert>
          )}
        </TabsContent>

        <TabsContent value="market" className="report-tab-panel">
          <section>
            <SectionHeading index="01" title="市场概览" description="需求信号、机会窗口与进入阻力" />
            <div className="market-layout">
              <Card>
                <CardHeader>
                  <CardTitle>公开市场信号</CardTitle>
                  <CardDescription>{report.analysis.market_signals.length} 条可追溯判断</CardDescription>
                  <CardAction><Globe2Icon aria-hidden="true" /></CardAction>
                </CardHeader>
                <CardContent>
                  <div className="signal-list">
                    {report.analysis.market_signals.map((signal) => (
                      <article key={signal.statement}>
                        <div className="signal-title">
                          <strong>{signal.statement}</strong>
                          <Citations ids={signal.source_ids} />
                        </div>
                        <p>{signal.interpretation}</p>
                      </article>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <div className="coverage-stack">
                <Card size="sm">
                  <CardHeader>
                    <CardTitle>研究覆盖</CardTitle>
                    <CardDescription>本轮检索的证据构成</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <dl className="coverage-grid">
                      <div><dt>来源</dt><dd>{report.coverage.unique_sources}</dd></div>
                      <div><dt>官方</dt><dd>{report.coverage.official_sources}</dd></div>
                      <div><dt>事实</dt><dd>{report.coverage.claim_count}</dd></div>
                      <div><dt>定价</dt><dd>{report.coverage.pricing_claims}</dd></div>
                    </dl>
                  </CardContent>
                </Card>
                <Card size="sm">
                  <CardHeader><CardTitle>机会 / 阻力</CardTitle></CardHeader>
                  <CardContent>
                    <div className="opportunity-block">
                      <h3><LightbulbIcon aria-hidden="true" />机会</h3>
                      <ul>{report.analysis.opportunities.map((item) => <li key={item}>{item}</li>)}</ul>
                    </div>
                    <Separator />
                    <div className="opportunity-block risk">
                      <h3><ShieldAlertIcon aria-hidden="true" />阻力</h3>
                      <ul>{report.analysis.barriers.map((item) => <li key={item}>{item}</li>)}</ul>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          </section>
        </TabsContent>

        <TabsContent value="competitors" className="report-tab-panel">
          <section>
            <SectionHeading index="02" title="竞品对比" description="定位、目标客群、关键能力与公开价格" />
            <Card>
              <CardContent>
                <div className="table-scroll">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>竞品</TableHead>
                        <TableHead>定位 / 客群</TableHead>
                        <TableHead>关键能力</TableHead>
                        <TableHead>公开定价</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {report.analysis.competitors.map((competitor) => (
                        <TableRow key={competitor.name}>
                          <TableCell>
                            <strong>{competitor.name}</strong>
                            <Citations ids={competitor.source_ids} />
                          </TableCell>
                          <TableCell>
                            <span>{competitor.positioning}</span>
                            <small>{competitor.target_customers}</small>
                          </TableCell>
                          <TableCell>
                            <div className="feature-list">
                              {competitor.key_features.map((feature) => (
                                <Badge key={feature} variant="outline">{feature}</Badge>
                              ))}
                            </div>
                          </TableCell>
                          <TableCell>
                            <span>{competitor.pricing.summary}</span>
                            <Badge variant={competitor.pricing.verified ? "default" : "secondary"}>
                              {competitor.pricing.verified ? "已核验" : "待核验"}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </section>
        </TabsContent>

        <TabsContent value="pricing" className="report-tab-panel">
          <section>
            <SectionHeading index="03" title="定价区间" description="保留原始计费口径，避免虚假的统一换算" />
            <div className="pricing-layout">
              <div className="price-observation">
                <TagIcon aria-hidden="true" />
                <span>观测到的 USD 价格点</span>
                <strong>{priceRange ? `$${priceRange.min} — $${priceRange.max}` : "未形成可比较区间"}</strong>
                <small>不同产品的用户、席位与计费周期可能不同</small>
              </div>
              <div className="pricing-list">
                {report.analysis.competitors.map((competitor) => (
                  <div key={competitor.name}>
                    <strong>{competitor.name}</strong>
                    <span>{competitor.pricing.summary}</span>
                    <Citations ids={competitor.pricing.source_ids} />
                  </div>
                ))}
              </div>
            </div>
          </section>
        </TabsContent>

        <TabsContent value="sources" className="report-tab-panel">
          <section>
            <SectionHeading index="04" title="证据来源" description="逐条回到原始网页核验上下文" />
            <Card>
              <CardHeader>
                <CardTitle>{report.sources.length} 个公开来源</CardTitle>
                <CardDescription>链接按研究抓取时的标题与分类展示</CardDescription>
                <CardAction><FileTextIcon aria-hidden="true" /></CardAction>
              </CardHeader>
              <CardContent>
                <Accordion>
                  {report.sources.map((source) => (
                    <AccordionItem key={source.id} value={source.id}>
                      <AccordionTrigger>
                        <span className="source-trigger">
                          <Badge variant="outline">{source.id}</Badge>
                          <span>{source.title}</span>
                        </span>
                      </AccordionTrigger>
                      <AccordionContent>
                        <div className="source-details">
                          <div>
                            <Badge variant="secondary">{sourceLabels[source.source_type]}</Badge>
                            <span>{source.domain}</span>
                            <span>{new Date(source.accessed_at).toLocaleDateString("zh-CN")}</span>
                          </div>
                          <a href={source.url} target="_blank" rel="noreferrer">
                            打开原始网页 <ArrowUpRightIcon aria-hidden="true" />
                          </a>
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>
          </section>
        </TabsContent>

        <TabsContent value="actions" className="report-tab-panel">
          <section>
            <SectionHeading index="05" title="下一步验证" description="把市场判断转成低成本、可证伪的行动" />
            <div className="next-step-list">
              {report.analysis.next_steps.map((step, index) => (
                <div key={step}><span>{String(index + 1).padStart(2, "0")}</span><p>{step}</p></div>
              ))}
            </div>
            {report.analysis.limitations.length > 0 && (
              <Alert>
                <ShieldAlertIcon aria-hidden="true" />
                <AlertTitle>研究局限</AlertTitle>
                <AlertDescription>{report.analysis.limitations.join("；")}</AlertDescription>
              </Alert>
            )}
          </section>
        </TabsContent>
      </Tabs>
    </article>
  )
}

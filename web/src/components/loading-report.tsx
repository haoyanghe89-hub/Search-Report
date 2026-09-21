import { Clock3Icon } from "lucide-react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"

const phases = [
  { at: 0, label: "规划市场、竞品与定价搜索" },
  { at: 5, label: "搜索全球英文公开网页" },
  { at: 20, label: "读取并筛选可引用页面" },
  { at: 55, label: "整理来源与事实证据" },
  { at: 85, label: "DeepSeek 正在分析市场" },
  { at: 150, label: "执行质量检查并生成报告" },
]

function estimatedProgress(elapsed: number) {
  if (elapsed < 5) return 8 + elapsed * 2
  if (elapsed < 20) return 18 + (elapsed - 5) * 1.2
  if (elapsed < 55) return 36 + (elapsed - 20) * 0.7
  if (elapsed < 85) return 61 + (elapsed - 55) * 0.5
  if (elapsed < 150) return 76 + (elapsed - 85) * 0.2
  return Math.min(94, 89 + (elapsed - 150) * 0.03)
}

export function LoadingReport({ elapsed }: { elapsed: number }) {
  const phase = [...phases].reverse().find((item) => elapsed >= item.at) ?? phases[0]
  const progress = Math.round(estimatedProgress(elapsed))

  return (
    <section aria-live="polite" aria-label="报告生成进度">
      <Card>
        <CardHeader>
          <div className="loading-title">
            <span className="icon-spot" aria-hidden="true"><Clock3Icon /></span>
            <div>
              <CardTitle>{phase.label}</CardTitle>
              <CardDescription>已运行 {elapsed} 秒，进度为阶段估算</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="progress-meta">
            <span>研究进度</span>
            <span>{progress}%</span>
          </div>
          <Progress value={progress} />
          <div className="loading-skeletons" aria-hidden="true">
            <Skeleton className="h-24 w-full" />
            <div className="loading-skeleton-grid">
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          </div>
        </CardContent>
      </Card>
    </section>
  )
}

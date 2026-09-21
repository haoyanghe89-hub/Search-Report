import type { ReportResponse } from "@/lib/types"

interface GenerateReportRequest {
  topic: string
  competitor_limit: number
}

export async function generateReport(
  payload: GenerateReportRequest,
): Promise<ReportResponse> {
  const response = await fetch("/api/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // Keep the HTTP fallback when the server returns a non-JSON error page.
    }
    throw new Error(message)
  }

  return (await response.json()) as ReportResponse
}

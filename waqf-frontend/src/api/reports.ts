import { apiClient } from "@/api/client";
import type { AuditThroughputStats, ReviewAction, WaqfDocument } from "@/types/domain";

/**
 * Real backend calls for the Reports page (see app/routers/reports.py).
 * Replaces src/data/mockDocuments.ts's getThroughputStats/getStatusBreakdown/
 * getConfidenceDistribution/getCorrectionsHistory — response shapes were
 * designed to match those mocks 1:1, so this is a straight swap.
 */

export interface StatusBreakdownEntry {
  status: WaqfDocument["status"];
  count: number;
}

export interface ConfidenceDistributionEntry {
  band: "high" | "medium" | "low";
  count: number;
}

export interface CorrectionHistoryEntry {
  reviewId: string;
  documentId: string;
  filename: string;
  reviewerId: string;
  action: ReviewAction;
  notes: string | null;
  reviewedAt: string;
  durationSeconds: number | null;
}

/** GET /reports/throughput — the Wk-12 demo-gate headline number. */
export async function getThroughputStats(): Promise<AuditThroughputStats> {
  const { data } = await apiClient.get<AuditThroughputStats>("/reports/throughput");
  return data;
}

/** GET /reports/status-breakdown — document counts by pipeline status. */
export async function getStatusBreakdown(): Promise<StatusBreakdownEntry[]> {
  const { data } = await apiClient.get<StatusBreakdownEntry[]>("/reports/status-breakdown");
  return data;
}

/** GET /reports/confidence-distribution — document counts bucketed into high/medium/low bands. */
export async function getConfidenceDistribution(): Promise<ConfidenceDistributionEntry[]> {
  const { data } = await apiClient.get<ConfidenceDistributionEntry[]>("/reports/confidence-distribution");
  return data;
}

/** GET /reports/corrections — reviewer decisions joined with the document they applied to. */
export async function getCorrectionsHistory(): Promise<CorrectionHistoryEntry[]> {
  const { data } = await apiClient.get<CorrectionHistoryEntry[]>("/reports/corrections");
  return data;
}

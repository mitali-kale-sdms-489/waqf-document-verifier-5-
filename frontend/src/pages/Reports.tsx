import { useEffect, useState } from "react";
import { format } from "date-fns";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Clock, Gauge, Loader2, ShieldCheck, TrendingUp } from "lucide-react";
import {
  getConfidenceDistribution,
  getCorrectionsHistory,
  getStatusBreakdown,
  getThroughputStats,
  type ConfidenceDistributionEntry,
  type CorrectionHistoryEntry,
  type StatusBreakdownEntry,
} from "@/api/reports";
import type { AuditThroughputStats, DocumentStatus, ReviewAction } from "@/types/domain";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  uploaded: "Uploaded",
  processing: "Processing",
  extracted: "Awaiting review",
  validated: "Awaiting review",
  reviewed: "Reviewed",
  approved: "Approved",
  flagged: "Flagged",
};

const CONFIDENCE_COLORS: Record<ConfidenceDistributionEntry["band"], string> = {
  high: "#2F5D50", // registry-green
  medium: "#B08D3E", // brass
  low: "#A64B3C", // rust
};

const ACTION_BADGE: Record<ReviewAction, "success" | "warning" | "danger"> = {
  approve: "success",
  correct: "warning",
  flag: "danger",
};

const ACTION_LABEL: Record<ReviewAction, string> = {
  approve: "Approved",
  correct: "Corrected",
  flag: "Flagged",
};

export function Reports() {
  const [throughput, setThroughput] = useState<AuditThroughputStats | null>(null);
  const [statusBreakdown, setStatusBreakdown] = useState<StatusBreakdownEntry[]>([]);
  const [confidenceDist, setConfidenceDist] = useState<ConfidenceDistributionEntry[]>([]);
  const [corrections, setCorrections] = useState<CorrectionHistoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getThroughputStats(),
      getStatusBreakdown(),
      getConfidenceDistribution(),
      getCorrectionsHistory(),
    ]).then(([t, s, c, r]) => {
      if (cancelled) return;
      setThroughput(t);
      setStatusBreakdown(s);
      setConfidenceDist(c);
      setCorrections(r);
      setIsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const statusChartData = statusBreakdown.map((s) => ({ name: STATUS_LABEL[s.status], count: s.count }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl">Reports</h1>
        <p className="text-sm text-muted-foreground">
          Throughput, seeded-error catch rate, and corrections history. Visible to the Supervisor role only.
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-24 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading reports…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={TrendingUp}
              label="Records / hour"
              value={String(throughput?.documentsPerHour ?? "—")}
              sub={`vs. ${throughput?.manualBaselinePerHour ?? "—"}/hr manual baseline`}
              tone="registry-green"
            />
            <StatCard
              icon={ShieldCheck}
              label="Seeded-error catch rate"
              value={
                throughput ? `${Math.round(throughput.seededErrorCatchRate * 100)}%` : "—"
              }
              sub="Synthetic test documents flagged correctly"
              tone="brass"
            />
            <StatCard
              icon={Clock}
              label="Avg. review time"
              value={throughput ? `${throughput.avgReviewSeconds}s` : "—"}
              sub="Per document, approve or correct"
              tone="petrol-ink"
            />
            <StatCard
              icon={Gauge}
              label="Speed-up vs. manual"
              value={
                throughput && throughput.manualBaselinePerHour > 0
                  ? `${(throughput.documentsPerHour / throughput.manualBaselinePerHour).toFixed(1)}×`
                  : "—"
              }
              sub="Documents per hour, pipeline vs. manual"
              tone="rust"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Documents by status</CardTitle>
              </CardHeader>
              <CardContent className="h-64">
                {statusChartData.length === 0 ? (
                  <EmptyChartState />
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={statusChartData} margin={{ left: -20 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E4DD" />
                      <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={50} />
                      <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: "#E2E4DD" }}
                        cursor={{ fill: "rgba(27,58,58,0.06)" }}
                      />
                      <Bar dataKey="count" fill="#1B3A3A" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Confidence distribution</CardTitle>
              </CardHeader>
              <CardContent className="h-64 flex items-center">
                {confidenceDist.every((c) => c.count === 0) ? (
                  <EmptyChartState />
                ) : (
                  <>
                    <ResponsiveContainer width="60%" height="100%">
                      <PieChart>
                        <Pie
                          data={confidenceDist}
                          dataKey="count"
                          nameKey="band"
                          innerRadius={50}
                          outerRadius={80}
                          paddingAngle={2}
                        >
                          {confidenceDist.map((entry) => (
                            <Cell key={entry.band} fill={CONFIDENCE_COLORS[entry.band]} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: "#E2E4DD" }} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="flex-1 space-y-2">
                      {confidenceDist.map((entry) => (
                        <div key={entry.band} className="flex items-center gap-2 text-xs">
                          <span
                            className="h-2.5 w-2.5 rounded-full shrink-0"
                            style={{ backgroundColor: CONFIDENCE_COLORS[entry.band] }}
                          />
                          <span className="capitalize text-muted-foreground">{entry.band}</span>
                          <span className="font-tabular ml-auto">{entry.count}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Corrections &amp; review history</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {corrections.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  No reviews submitted yet — approvals, corrections, and flags will appear here.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-t border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="px-6 py-3 font-medium">Document</th>
                        <th className="px-6 py-3 font-medium">Reviewer</th>
                        <th className="px-6 py-3 font-medium">Action</th>
                        <th className="px-6 py-3 font-medium">Notes</th>
                        <th className="px-6 py-3 font-medium">Duration</th>
                        <th className="px-6 py-3 font-medium text-right">Reviewed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {corrections.map((c) => (
                        <tr key={c.reviewId} className="border-t border-border hover:bg-muted/50">
                          <td className="px-6 py-3 font-tabular">{c.filename}</td>
                          <td className="px-6 py-3 text-muted-foreground">{c.reviewerId}</td>
                          <td className="px-6 py-3">
                            <Badge variant={ACTION_BADGE[c.action]}>{ACTION_LABEL[c.action]}</Badge>
                          </td>
                          <td className="px-6 py-3 text-muted-foreground max-w-xs truncate" title={c.notes ?? undefined}>
                            {c.notes ?? "—"}
                          </td>
                          <td className="px-6 py-3 font-tabular text-muted-foreground">
                            {c.durationSeconds !== null ? `${c.durationSeconds}s` : "—"}
                          </td>
                          <td className="px-6 py-3 text-right font-tabular text-muted-foreground">
                            {format(new Date(c.reviewedAt), "d MMM yyyy, HH:mm")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function EmptyChartState() {
  return (
    <div className="w-full h-full flex items-center justify-center text-sm text-muted-foreground">
      Not enough data yet.
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: typeof Clock;
  label: string;
  value: string;
  sub: string;
  tone: "brass" | "registry-green" | "rust" | "petrol-ink";
}) {
  return (
    <Card>
      <CardContent className="p-5 space-y-3">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
              tone === "brass" && "bg-brass/15 text-brass",
              tone === "registry-green" && "bg-registry-green/15 text-registry-green",
              tone === "rust" && "bg-rust/15 text-rust",
              tone === "petrol-ink" && "bg-primary/10 text-primary"
            )}
          >
            <Icon className="h-4 w-4" strokeWidth={1.75} />
          </div>
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
        <p className="font-tabular text-2xl leading-none">{value}</p>
        <p className="text-[11px] text-muted-foreground">{sub}</p>
      </CardContent>
    </Card>
  );
}

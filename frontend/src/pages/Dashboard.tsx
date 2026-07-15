import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  FileUp,
  Flag,
  Gauge,
  Loader2,
  MessageSquareWarning,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { getAllDocuments, getDashboardStats, getFlagReason, type DashboardStats } from "@/api/documents";
import {
  SCRIPT_TYPE_LABELS,
  SCRIPT_TYPE_SHORT_LABELS,
  confidenceBand,
  type DocumentStatus,
  type WaqfDocument,
} from "@/types/domain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
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

const STATUS_BADGE: Record<DocumentStatus, "default" | "secondary" | "success" | "warning" | "danger"> = {
  uploaded: "secondary",
  processing: "secondary",
  extracted: "warning",
  validated: "warning",
  reviewed: "success",
  approved: "success",
  flagged: "danger",
};

const CONFIDENCE_BADGE = {
  high: "success",
  medium: "warning",
  low: "danger",
} as const;

/** Simplified 3-way status bucket used by the dashboard filter, per the
 *  design brief (Pending / Approved / Flagged) — collapses the finer-grained
 *  pipeline statuses (uploaded/processing/extracted/validated/reviewed) into
 *  the three states a person actually cares about at a glance. */
type StatusFilter = "all" | "pending" | "approved" | "flagged";

const PENDING_STATUSES: DocumentStatus[] = ["uploaded", "processing", "extracted", "validated"];
const APPROVED_STATUSES: DocumentStatus[] = ["approved", "reviewed"];

function matchesStatusFilter(status: DocumentStatus, filter: StatusFilter): boolean {
  if (filter === "all") return true;
  if (filter === "pending") return PENDING_STATUSES.includes(status);
  if (filter === "approved") return APPROVED_STATUSES.includes(status);
  return status === "flagged";
}

type ScriptFilter = "all" | WaqfDocument["scriptType"];

export function Dashboard() {
  const { user, isElevated } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [documents, setDocuments] = useState<WaqfDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [previewDoc, setPreviewDoc] = useState<WaqfDocument | null>(null);

  const [flagDoc, setFlagDoc] = useState<WaqfDocument | null>(null);
  const [flagReason, setFlagReason] = useState<{ reason: string | null; reviewerId: string; reviewedAt: string } | null>(
    null
  );
  const [isFlagReasonLoading, setIsFlagReasonLoading] = useState(false);

  // --- Search & filters ---
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [scriptFilter, setScriptFilter] = useState<ScriptFilter>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([getDashboardStats(), getAllDocuments()]).then(([s, docs]) => {
      if (cancelled) return;
      setStats(s);
      setDocuments(docs);
      setIsLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function openFlagReason(doc: WaqfDocument) {
    setFlagDoc(doc);
    setIsFlagReasonLoading(true);
    getFlagReason(doc.id).then((result) => {
      setFlagReason(result);
      setIsFlagReasonLoading(false);
    });
  }

  const hasActiveFilters =
    searchQuery.trim() !== "" || statusFilter !== "all" || scriptFilter !== "all" || dateFrom !== "" || dateTo !== "";

  function clearFilters() {
    setSearchQuery("");
    setStatusFilter("all");
    setScriptFilter("all");
    setDateFrom("");
    setDateTo("");
  }

  const filteredDocuments = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const from = dateFrom ? new Date(`${dateFrom}T00:00:00`) : null;
    const to = dateTo ? new Date(`${dateTo}T23:59:59.999`) : null;

    return documents.filter((doc) => {
      if (query && !doc.filename.toLowerCase().includes(query)) return false;
      if (!matchesStatusFilter(doc.status, statusFilter)) return false;
      if (scriptFilter !== "all" && doc.scriptType !== scriptFilter) return false;
      const uploadedAt = new Date(doc.uploadedAt);
      if (from && uploadedAt < from) return false;
      if (to && uploadedAt > to) return false;
      return true;
    });
  }, [documents, searchQuery, statusFilter, scriptFilter, dateFrom, dateTo]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-2xl">Registry</h1>
          <p className="text-sm text-muted-foreground">
            Welcome back, {user?.full_name}. Documents in the verification pipeline.
          </p>
        </div>
        {!isElevated && (
          <Button asChild className="gap-2">
            <Link to="/upload">
              <FileUp className="h-4 w-4" /> Upload document
            </Link>
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Clock}
          label="Pending review"
          value={stats ? String(stats.pendingReview) : undefined}
          tone="brass"
        />
        <StatCard
          icon={CheckCircle2}
          label="Approved today"
          value={stats ? String(stats.approvedToday) : undefined}
          tone="registry-green"
        />
        <StatCard
          icon={Flag}
          label="Flagged"
          value={stats ? String(stats.flagged) : undefined}
          tone="rust"
        />
        <StatCard
          icon={Gauge}
          label="Avg. confidence"
          value={stats?.avgConfidence != null ? `${Math.round(stats.avgConfidence * 100)}%` : "—"}
          tone="petrol-ink"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent documents</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {/* Search & filters toolbar */}
          <div className="px-6 pb-4 flex flex-wrap items-end gap-3 border-b border-border">
            <div className="space-y-1.5 flex-1 min-w-[200px]">
              <label className="text-xs font-medium text-muted-foreground">Search</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by filename…"
                  className="pl-9"
                />
              </div>
            </div>

            <div className="space-y-1.5 w-40">
              <label className="text-xs font-medium text-muted-foreground">Status</label>
              <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="approved">Approved</SelectItem>
                  <SelectItem value="flagged">Flagged</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5 w-44">
              <label className="text-xs font-medium text-muted-foreground">Language/Script</label>
              <Select value={scriptFilter} onValueChange={(v) => setScriptFilter(v as ScriptFilter)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All scripts</SelectItem>
                  <SelectItem value="urdu_nastaliq">Urdu · Nastaliq</SelectItem>
                  <SelectItem value="marathi_devanagari">Marathi · Devanagari</SelectItem>
                  <SelectItem value="english_latin">English · Latin</SelectItem>
                  <SelectItem value="hindi_devanagari">Hindi · Devanagari</SelectItem>
                  <SelectItem value="sanskrit_devanagari">Sanskrit · Devanagari</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">From</label>
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="w-[9.5rem] font-tabular"
                max={dateTo || undefined}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">To</label>
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="w-[9.5rem] font-tabular"
                min={dateFrom || undefined}
              />
            </div>

            {hasActiveFilters && (
              <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" onClick={clearFilters}>
                <X className="h-3.5 w-3.5" /> Clear filters
              </Button>
            )}
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading documents…
            </div>
          ) : documents.length === 0 ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              No documents yet — upload one to get started.
            </div>
          ) : filteredDocuments.length === 0 ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              No documents match your search and filters.
              <div className="mt-3">
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-t border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-6 py-3 font-medium">Filename</th>
                    <th className="px-6 py-3 font-medium">Script</th>
                    <th className="px-6 py-3 font-medium">DPDP</th>
                    <th className="px-6 py-3 font-medium">Status</th>
                    <th className="px-6 py-3 font-medium">Confidence</th>
                    <th className="px-6 py-3 font-medium">Uploaded</th>
                    <th className="px-6 py-3 font-medium text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDocuments.map((doc) => {
                    const band = doc.overallConfidence !== null ? confidenceBand(doc.overallConfidence) : null;
                    const needsReview = doc.status === "extracted" || doc.status === "validated";
                    const isFlagged = doc.status === "flagged";
                    return (
                      <tr key={doc.id} className="border-t border-border hover:bg-muted/50">
                        <td className="px-6 py-3 font-tabular">{doc.filename}</td>
                        <td className="px-6 py-3 text-muted-foreground">
                          {SCRIPT_TYPE_SHORT_LABELS[doc.scriptType]}
                          {doc.isSynthetic && (
                            <Badge variant="outline" className="ml-2">
                              Seeded
                            </Badge>
                          )}
                        </td>
                        <td className="px-6 py-3">
                          {doc.dpdpStatus === "compliant" ? (
                            <Badge variant="outline" className="gap-1" title={doc.dpdpReason ?? undefined}>
                              <ShieldCheck className="h-3 w-3 text-registry-green" /> Compliant
                            </Badge>
                          ) : (
                            <Badge variant="danger" className="gap-1" title={doc.dpdpReason ?? undefined}>
                              <AlertTriangle className="h-3 w-3" /> Needs review
                            </Badge>
                          )}
                        </td>
                        <td className="px-6 py-3">
                          {isFlagged ? (
                            <button
                              type="button"
                              onClick={() => openFlagReason(doc)}
                              className="inline-flex items-center gap-1.5 rounded-full hover:opacity-80 transition-opacity"
                              title="See why this document was flagged"
                            >
                              <Badge variant={STATUS_BADGE[doc.status]}>{STATUS_LABEL[doc.status]}</Badge>
                              <MessageSquareWarning className="h-3.5 w-3.5 text-rust" />
                            </button>
                          ) : (
                            <Badge variant={STATUS_BADGE[doc.status]}>{STATUS_LABEL[doc.status]}</Badge>
                          )}
                        </td>
                        <td className="px-6 py-3">
                          {band ? (
                            <Badge variant={CONFIDENCE_BADGE[band]} className="font-tabular">
                              {Math.round((doc.overallConfidence ?? 0) * 100)}%
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-6 py-3 text-muted-foreground font-tabular">
                          {format(new Date(doc.uploadedAt), "d MMM yyyy, HH:mm")}
                        </td>
                        <td className="px-6 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              className="gap-1.5"
                              onClick={() => setPreviewDoc(doc)}
                            >
                              <Eye className="h-3.5 w-3.5" /> Preview
                            </Button>
                            {needsReview && isElevated && (
                              <Button asChild size="sm" variant="outline">
                                <Link to={`/review/${doc.id}`}>Review</Link>
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={previewDoc !== null} onOpenChange={(open) => !open && setPreviewDoc(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="font-tabular">{previewDoc?.filename}</DialogTitle>
            <DialogDescription>
              {previewDoc && SCRIPT_TYPE_LABELS[previewDoc.scriptType]}
              {" · "}
              Uploaded {previewDoc ? format(new Date(previewDoc.uploadedAt), "d MMM yyyy, HH:mm") : ""}
            </DialogDescription>
          </DialogHeader>
          {previewDoc && (
            <div className="flex">
              <DocumentPreview doc={previewDoc} minHeightClassName="min-h-[420px]" />
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={flagDoc !== null} onOpenChange={(open) => !open && setFlagDoc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Flag className="h-4 w-4 text-rust" /> Flagged for review
            </DialogTitle>
            <DialogDescription className="font-tabular">{flagDoc?.filename}</DialogDescription>
          </DialogHeader>
          {isFlagReasonLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading reason…
            </div>
          ) : flagReason?.reason ? (
            <div className="space-y-3">
              <div className="rounded-md border border-rust/30 bg-rust/5 p-4 text-sm text-foreground whitespace-pre-wrap">
                {flagReason.reason}
              </div>
              <p className="text-xs text-muted-foreground">
                Flagged by {flagReason.reviewerId} on{" "}
                {format(new Date(flagReason.reviewedAt), "d MMM yyyy, HH:mm")}
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground py-2">
              No reason was recorded for this flag.
            </p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Clock;
  label: string;
  value?: string;
  tone: "brass" | "registry-green" | "rust" | "petrol-ink";
}) {
  return (
    <Card>
      <CardContent className="p-5 flex items-center gap-4">
        <div
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
            tone === "brass" && "bg-brass/15 text-brass",
            tone === "registry-green" && "bg-registry-green/15 text-registry-green",
            tone === "rust" && "bg-rust/15 text-rust",
            tone === "petrol-ink" && "bg-primary/10 text-primary"
          )}
        >
          <Icon className="h-5 w-5" strokeWidth={1.75} />
        </div>
        <div>
          <p className="font-tabular text-2xl leading-none">{value ?? "—"}</p>
          <p className="text-xs text-muted-foreground mt-1">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import toast from "react-hot-toast";
import {
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Eye,
  FileUp,
  Flag,
  Gauge,
  Languages,
  Loader2,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import {
  getAllDocuments,
  getDashboardStats,
  getFlagReason,
  getTranslateLanguages,
  pollDocumentUntilReady,
  reuploadDocument,
  translateText,
  type DashboardStats,
  type SupportedLanguage,
} from "@/api/documents";
import {
  MAX_REUPLOAD_ATTEMPTS,
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
  reviewed: "Accepted",
  approved: "Accepted",
  flagged: "Flagged",
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

const REUPLOAD_ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp", "image/tiff", "application/pdf"];
const REUPLOAD_ACCEPTED_EXT = ".png,.jpg,.jpeg,.webp,.tif,.tiff,.pdf";
const REUPLOAD_MAX_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB — matches Upload.tsx

function isReuploadAcceptedFile(file: File): boolean {
  if (REUPLOAD_ACCEPTED_TYPES.includes(file.type)) return true;
  return /\.(png|jpe?g|webp|tif|tiff|pdf)$/i.test(file.name);
}

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

  // --- Reupload (from the flag dialog) ---
  const reuploadInputRef = useRef<HTMLInputElement>(null);
  const [isReuploading, setIsReuploading] = useState(false);
  const [reuploadError, setReuploadError] = useState<string | null>(null);

  // --- Flag reason translation ---
  const [translateLanguages, setTranslateLanguages] = useState<SupportedLanguage[]>([]);
  const [selectedLanguage, setSelectedLanguage] = useState<string>("");
  const [translatedReason, setTranslatedReason] = useState<string | null>(null);
  const [isTranslating, setIsTranslating] = useState(false);
  const [translateError, setTranslateError] = useState<string | null>(null);

  // --- Search & filters ---
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [scriptFilter, setScriptFilter] = useState<ScriptFilter>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  // Neither picker should allow a future date, and From can't be after To.
  const today = useMemo(() => format(new Date(), "yyyy-MM-dd"), []);
  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 10;

  useEffect(() => {
    let cancelled = false;
    Promise.all([getDashboardStats(), getAllDocuments()]).then(([s, docs]) => {
      if (cancelled) return;
      setStats(s);
      setDocuments(docs);
      setIsLoading(false);
    });
    getTranslateLanguages().then((langs) => {
      if (!cancelled) setTranslateLanguages(langs);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function openFlagReason(doc: WaqfDocument) {
    setFlagDoc(doc);
    setIsFlagReasonLoading(true);
    setReuploadError(null);
    // Reset any translation left over from a previously opened flag.
    setSelectedLanguage("");
    setTranslatedReason(null);
    setTranslateError(null);
    getFlagReason(doc.id).then((result) => {
      setFlagReason(result);
      setIsFlagReasonLoading(false);
    });
  }

  function handleReuploadInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !flagDoc) return;
    if (!isReuploadAcceptedFile(file)) {
      setReuploadError("Unsupported file type. Use JPG, PNG, TIFF, WEBP, or PDF.");
      return;
    }
    if (file.size > REUPLOAD_MAX_SIZE_BYTES) {
      setReuploadError("File is larger than the 25 MB limit.");
      return;
    }

    const documentId = flagDoc.id;
    setReuploadError(null);
    setIsReuploading(true);
    reuploadDocument(documentId, file)
      .then(async ({ document: processingDoc }) => {
        // The file is saved and OCR is queued (status="processing") the
        // moment this resolves — reflect that right away, then poll by id
        // until the background OCR pass actually finishes. Without this,
        // the dialog would say "queued for review" and then just sit on
        // "processing" forever until someone manually refreshes the page.
        setDocuments((prev) => prev.map((d) => (d.id === documentId ? processingDoc : d)));
        setFlagDoc(processingDoc);

        const detail = await pollDocumentUntilReady(documentId, {
          intervalMs: 2500,
          timeoutMs: 5 * 60 * 1000,
        });

        if (!detail) {
          // Not a failure — OCR is just taking longer than usual. The
          // record is already safely saved; leave it as "processing" and
          // let the person check back rather than blocking the dialog.
          toast(`${file.name} is still processing — check back on the Dashboard shortly.`, { icon: "⏳" });
          return;
        }

        const finalDoc = detail.document;
        setDocuments((prev) => prev.map((d) => (d.id === documentId ? finalDoc : d)));
        setFlagDoc(finalDoc);
        getDashboardStats().then(setStats);

        if (finalDoc.status === "flagged") {
          toast(`${file.name} uploaded, but OCR still couldn't process it — flagged again.`, { icon: "⚠️" });
        } else {
          toast.success(`${file.name} reuploaded and queued for review.`);
        }
      })
      .catch((err) => {
        const status = (err as { response?: { status?: number } }).response?.status;
        const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        const message =
          status === 409
            ? detail ?? `${MAX_REUPLOAD_ATTEMPTS} attempts done. Please visit the office.`
            : detail ?? "Reupload failed. Try again.";
        setReuploadError(message);
        toast.error(message);
      })
      .finally(() => {
        setIsReuploading(false);
      });
  }

  function handleTranslateLanguageChange(languageCode: string) {
    setSelectedLanguage(languageCode);
    setTranslatedReason(null);
    setTranslateError(null);
    if (!languageCode || !flagReason?.reason) return;
    setIsTranslating(true);
    translateText(flagReason.reason, languageCode)
      .then((translated) => {
        setTranslatedReason(translated);
      })
      .catch(() => {
        setTranslateError("Couldn't translate this reason. Please try again.");
      })
      .finally(() => {
        setIsTranslating(false);
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

  // Filters changing means the result set changed shape — always land back
  // on page 1 rather than showing an empty page 3 of a 1-page result.
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, statusFilter, scriptFilter, dateFrom, dateTo]);

  const totalPages = Math.max(1, Math.ceil(filteredDocuments.length / PAGE_SIZE));
  const pageSafe = Math.min(currentPage, totalPages);
  const paginatedDocuments = filteredDocuments.slice((pageSafe - 1) * PAGE_SIZE, pageSafe * PAGE_SIZE);

  const reuploadAttemptsLeft = flagDoc ? Math.max(0, MAX_REUPLOAD_ATTEMPTS - flagDoc.reuploadCount) : 0;

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

      <div className="rounded-lg bg-foreground/[0.08] p-4">
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
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>Recent documents</CardTitle>
          {filteredDocuments.length > 0 && (
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <span className="font-tabular">
                Page {pageSafe} of {totalPages}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 w-8 p-0"
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={pageSafe <= 1}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 w-8 p-0"
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={pageSafe >= totalPages}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0">
          {/* Search & filters toolbar */}
          <div className="px-6 pb-4 flex flex-col gap-3 border-b border-border">
            {/* Row 1: Search, From, To */}
            <div className="flex flex-wrap items-end gap-3">
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

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">From</label>
                <Input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-[9.5rem] font-tabular"
                  max={dateTo && dateTo < today ? dateTo : today}
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
                  max={today}
                />
              </div>
            </div>

            {/* Row 2: Status, Language/Script */}
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1.5 w-40">
                <label className="text-xs font-medium text-muted-foreground">Status</label>
                <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All statuses</SelectItem>
                    <SelectItem value="pending">Pending</SelectItem>
                    <SelectItem value="approved">Accepted</SelectItem>
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

              {hasActiveFilters && (
                <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground" onClick={clearFilters}>
                  <X className="h-3.5 w-3.5" /> Clear filters
                </Button>
              )}
            </div>
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
              <table className="w-full text-sm table-fixed">
                <thead>
                  <tr className="border-t border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-6 py-3 font-medium w-20">S.No</th>
                    <th className="px-6 py-3 font-medium w-[20%]">Script</th>
                    <th className="px-6 py-3 font-medium w-[18%]">Confidence</th>
                    <th className="px-6 py-3 font-medium w-[26%]">Uploaded</th>
                    <th className="px-6 py-3 font-medium text-right w-[18%]">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedDocuments.map((doc, index) => {
                    const band = doc.overallConfidence !== null ? confidenceBand(doc.overallConfidence) : null;
                    const needsReview = doc.status === "extracted" || doc.status === "validated";
                    const isFlagged = doc.status === "flagged";
                    const serialNo = (pageSafe - 1) * PAGE_SIZE + index + 1;
                    return (
                      <tr key={doc.id} className="border-t border-border hover:bg-muted/50">
                        <td className="px-6 py-3 text-muted-foreground font-tabular">
                          <span className="group relative inline-flex cursor-default items-center gap-1.5">
                            {isFlagged ? (
                              <button
                                type="button"
                                onClick={() => openFlagReason(doc)}
                                className="inline-flex items-center hover:opacity-80 transition-opacity"
                                title="See why this document was flagged"
                                aria-label={STATUS_LABEL[doc.status]}
                              >
                                <span aria-hidden="true">🚩</span>
                              </button>
                            ) : APPROVED_STATUSES.includes(doc.status) ? (
                              <span aria-label={STATUS_LABEL[doc.status]} title={STATUS_LABEL[doc.status]}>
                                ✅
                              </span>
                            ) : needsReview ? (
                              <span title={STATUS_LABEL[doc.status]}>
                                <Clock className="h-3.5 w-3.5 text-brass" strokeWidth={2} aria-label={STATUS_LABEL[doc.status]} />
                              </span>
                            ) : (
                              <span title={STATUS_LABEL[doc.status]}>
                                <Clock className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} aria-label={STATUS_LABEL[doc.status]} />
                              </span>
                            )}
                            {serialNo}
                            <span
                              className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden whitespace-nowrap rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs font-normal normal-case text-popover-foreground shadow-md group-hover:block"
                              role="tooltip"
                            >
                              {doc.filename}
                            </span>
                          </span>
                        </td>
                        <td className="px-6 py-3 text-muted-foreground">
                          {SCRIPT_TYPE_SHORT_LABELS[doc.scriptType]}
                          {doc.isSynthetic && (
                            <Badge variant="outline" className="ml-2">
                              Seeded
                            </Badge>
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
                            {!isElevated && (
                              <Button
                                size="sm"
                                variant="outline"
                                className="gap-1.5"
                                onClick={() => setPreviewDoc(doc)}
                              >
                                <Eye className="h-3.5 w-3.5" /> Preview
                              </Button>
                            )}
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
                Flagged by supervisor on{" "}
                {format(new Date(flagReason.reviewedAt), "d MMM yyyy, HH:mm")}
              </p>

              <div className="flex items-center gap-2 pt-1">
                <Languages className="h-4 w-4 text-muted-foreground shrink-0" />
                <Select value={selectedLanguage} onValueChange={handleTranslateLanguageChange}>
                  <SelectTrigger className="h-8 text-xs w-[200px]">
                    <SelectValue placeholder="Translate to…" />
                  </SelectTrigger>
                  <SelectContent>
                    {translateLanguages.map((lang) => (
                      <SelectItem key={lang.code} value={lang.code}>
                        {lang.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedLanguage && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 gap-1.5 text-xs"
                    disabled={isTranslating}
                    onClick={() => handleTranslateLanguageChange(selectedLanguage)}
                  >
                    {isTranslating ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Languages className="h-3.5 w-3.5" />
                    )}
                    Translate
                  </Button>
                )}
              </div>

              {isTranslating ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Translating…
                </div>
              ) : translateError ? (
                <p className="text-xs text-destructive">{translateError}</p>
              ) : translatedReason ? (
                <div className="rounded-md border border-registry-green/30 bg-registry-green/5 p-4 text-sm text-foreground whitespace-pre-wrap">
                  <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    {translateLanguages.find((l) => l.code === selectedLanguage)?.label ?? "Translation"}
                  </p>
                  {translatedReason}
                </div>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground py-2">
              No reason was recorded for this flag.
            </p>
          )}

          {flagDoc && (
            <div className="space-y-2 border-t border-border pt-3">
              <input
                ref={reuploadInputRef}
                type="file"
                accept={REUPLOAD_ACCEPTED_EXT}
                className="hidden"
                onChange={handleReuploadInputChange}
              />

              {isReuploading && flagDoc.status === "processing" ? (
                <div className="flex items-center gap-2 rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                  Uploaded — extracting fields…
                </div>
              ) : !isReuploading && flagDoc.status !== "flagged" ? (
                <div className="flex items-center gap-2 rounded-md bg-registry-green/10 px-3 py-2 text-xs text-registry-green">
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                  Document reuploaded — queued for review again.
                </div>
              ) : reuploadAttemptsLeft <= 0 ? (
                <div className="flex items-start gap-2 rounded-md bg-rust/10 px-3 py-2">
                  <Building2 className="h-4 w-4 text-rust shrink-0 mt-0.5" />
                  <p className="text-xs text-rust leading-snug">
                    3 attempts done. Please visit the office with the original document for
                    in-person verification.
                  </p>
                </div>
              ) : (
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    {reuploadAttemptsLeft} attempt{reuploadAttemptsLeft === 1 ? "" : "s"} remaining
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 gap-1.5 text-xs"
                    disabled={isReuploading}
                    onClick={() => reuploadInputRef.current?.click()}
                  >
                    {isReuploading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RotateCcw className="h-3.5 w-3.5" />
                    )}
                    {isReuploading ? "Uploading…" : "Reupload document"}
                  </Button>
                </div>
              )}

              {reuploadError && <p className="text-xs text-destructive">{reuploadError}</p>}
            </div>
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

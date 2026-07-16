import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import toast from "react-hot-toast";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Flag,
  Loader2,
  Pencil,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
import { getDocument, getQueue, revalidateDocument, submitReview } from "@/api/documents";
import {
  FIELD_LABELS,
  SCRIPT_TYPE_LABELS,
  confidenceBand,
  isMandatoryField,
  type ExtractedField,
  type ValidationResult,
  type WaqfDocument,
} from "@/types/domain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const CONFIDENCE_BADGE: Record<ReturnType<typeof confidenceBand>, "success" | "warning" | "danger"> = {
  high: "success",
  medium: "warning",
  low: "danger",
};

const VALIDATION_ICON: Record<ValidationResult["result"], { Icon: typeof CheckCircle2; className: string }> = {
  pass: { Icon: CheckCircle2, className: "text-registry-green" },
  warning: { Icon: AlertTriangle, className: "text-brass" },
  fail: { Icon: XCircle, className: "text-rust" },
};

export function Review() {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [queue, setQueue] = useState<WaqfDocument[]>([]);
  const [current, setCurrent] = useState<WaqfDocument | null>(null);
  const [fields, setFields] = useState<ExtractedField[]>([]);
  const [validations, setValidations] = useState<ValidationResult[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRevalidating, setIsRevalidating] = useState(false);
  const [flagOpen, setFlagOpen] = useState(false);
  const [flagReason, setFlagReason] = useState("");
  const [startedAt, setStartedAt] = useState<number>(Date.now());

  useEffect(() => {
    getQueue().then(setQueue);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      const q = queue.length ? queue : await getQueue();
      if (!queue.length) setQueue(q);
      const targetId = documentId ?? q[0]?.id;
      if (!targetId) {
        setCurrent(null);
        setIsLoading(false);
        return;
      }
      const record = await getDocument(targetId);
      if (cancelled) return;
      if (record) {
        setCurrent(record.document);
        setFields(record.fields);
        setValidations(record.validations);
        setEdits({});
        setStartedAt(Date.now());
      }
      setIsLoading(false);
    }
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, queue.length]);

  const queueIndex = useMemo(
    () => (current ? queue.findIndex((d) => d.id === current.id) : -1),
    [current, queue]
  );

  const goTo = useCallback(
    (index: number) => {
      const next = queue[index];
      if (next) navigate(`/review/${next.id}`);
    },
    [queue, navigate]
  );

  function advanceAfterAction() {
    const remaining = queue.filter((d) => d.id !== current?.id);
    setQueue(remaining);
    const next = remaining[queueIndex] ?? remaining[0];
    if (next) {
      navigate(`/review/${next.id}`);
    } else {
      navigate("/review");
    }
  }

  async function handleApprove() {
    if (!current) return;
    setIsSubmitting(true);
    try {
      const durationSeconds = Math.round((Date.now() - startedAt) / 1000);
      const hasCorrections = Object.keys(edits).length > 0;
      await submitReview(current.id, hasCorrections ? "correct" : "approve", {
        corrections: hasCorrections ? edits : undefined,
        durationSeconds,
      });
      toast.success(
        hasCorrections ? `${current.filename} corrected and approved.` : `${current.filename} approved.`
      );
      advanceAfterAction();
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleFlag() {
    if (!current) return;
    setIsSubmitting(true);
    try {
      const durationSeconds = Math.round((Date.now() - startedAt) / 1000);
      await submitReview(current.id, "flag", { notes: flagReason, durationSeconds });
      toast(`${current.filename} flagged for supervisor review.`, { icon: "🚩" });
      setFlagOpen(false);
      setFlagReason("");
      advanceAfterAction();
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRevalidate() {
    if (!current) return;
    setIsRevalidating(true);
    try {
      const fresh = await revalidateDocument(current.id);
      setValidations(fresh);
      toast.success(
        fresh.length ? "Validation results refreshed." : "Re-run complete — still no results (check rule config)."
      );
    } catch {
      toast.error("Couldn't re-run validation. Try again.");
    } finally {
      setIsRevalidating(false);
    }
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!current || isSubmitting || flagOpen) return;
      const tag = (e.target as HTMLElement)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA";
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        handleApprove();
      } else if (!typing && e.key.toLowerCase() === "f") {
        setFlagOpen(true);
      } else if (!typing && e.key === "ArrowRight") {
        goTo(queueIndex + 1);
      } else if (!typing && e.key === "ArrowLeft") {
        goTo(queueIndex - 1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, isSubmitting, flagOpen, queueIndex, edits]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-sm text-muted-foreground gap-2">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading review queue…
      </div>
    );
  }

  if (!current) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="font-display text-2xl">Review</h1>
          <p className="text-sm text-muted-foreground">Scan vs. extracted fields, side by side.</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-12 text-center text-sm text-muted-foreground">
          <CheckCircle2 className="h-8 w-8 mx-auto mb-3 text-registry-green" />
          Queue is clear — nothing waiting for review right now.
        </div>
      </div>
    );
  }

  const band = current.overallConfidence !== null ? confidenceBand(current.overallConfidence) : "low";
  const failCount = validations.filter((v) => v.result === "fail").length;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-display text-2xl">Review</h1>
          <p className="text-sm text-muted-foreground">
            Scan vs. extracted fields, side by side. Signed in as {user?.full_name}.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            onClick={() => goTo(queueIndex - 1)}
            disabled={queueIndex <= 0}
            aria-label="Previous document"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="font-tabular text-sm text-muted-foreground px-2">
            {queueIndex + 1} of {queue.length}
          </span>
          <Button
            variant="outline"
            size="icon"
            onClick={() => goTo(queueIndex + 1)}
            disabled={queueIndex >= queue.length - 1}
            aria-label="Next document"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap rounded-lg border border-border bg-card px-4 py-3">
        <span className="font-tabular text-sm font-medium">{current.filename}</span>
        <Badge variant="outline">
          {SCRIPT_TYPE_LABELS[current.scriptType]}
        </Badge>
        {current.isSynthetic && <Badge variant="warning">Seeded test document</Badge>}
        {current.previewUrl && <Badge variant="outline">Uploaded from device</Badge>}
        {current.dpdpStatus === "compliant" ? (
          <Badge variant="outline" className="gap-1" title={current.dpdpReason ?? undefined}>
            <ShieldCheck className="h-3 w-3 text-registry-green" /> DPDP compliant
          </Badge>
        ) : (
          <Badge variant="danger" className="gap-1" title={current.dpdpReason ?? undefined}>
            <AlertTriangle className="h-3 w-3" /> DPDP: needs review
          </Badge>
        )}
        <Badge variant={CONFIDENCE_BADGE[band]}>
          {current.overallConfidence !== null
            ? `${Math.round(current.overallConfidence * 100)}% confidence`
            : "No score"}
        </Badge>
        {failCount > 0 && (
          <Badge variant="danger">
            {failCount} validation {failCount === 1 ? "issue" : "issues"}
          </Badge>
        )}
      </div>

      {current.extractionNotes && (
        <details className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium text-muted-foreground select-none">
            Extraction diagnostics
          </summary>
          <ul className="mt-2 space-y-1 list-disc pl-5 text-xs text-muted-foreground">
            {current.extractionNotes
              .split("\n")
              .filter(Boolean)
              .map((note, i) => (
                <li key={i}>{note}</li>
              ))}
          </ul>
        </details>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <DocumentPreview doc={current} />

        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-5 space-y-4">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              Extracted fields
            </h2>
            <div className="space-y-3">
              {fields.map((field) => {
                const fieldBand = confidenceBand(field.confidence);
                const mandatory = isMandatoryField(field.fieldName);
                const value = edits[field.fieldName] ?? field.fieldValue ?? "";
                const isEdited = edits[field.fieldName] !== undefined;
                return (
                  <div key={field.id} className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <label
                        htmlFor={field.id}
                        className="text-xs font-medium text-foreground flex items-center gap-1"
                      >
                        {FIELD_LABELS[field.fieldName]}
                        {mandatory && <span className="text-rust">*</span>}
                      </label>
                      <Badge variant={CONFIDENCE_BADGE[fieldBand]} className="font-tabular">
                        {Math.round(field.confidence * 100)}%
                      </Badge>
                    </div>
                    <div className="relative">
                      <Input
                        id={field.id}
                        value={value}
                        placeholder={field.fieldValue === null ? "Not extracted — enter manually" : undefined}
                        onChange={(e) =>
                          setEdits((prev) => ({ ...prev, [field.fieldName]: e.target.value }))
                        }
                        className={cn(
                          "font-tabular pr-8",
                          fieldBand === "low" && "border-rust/50 focus-visible:ring-rust",
                          fieldBand === "medium" && "border-brass/50"
                        )}
                      />
                      {isEdited && (
                        <Pencil className="h-3.5 w-3.5 text-brass absolute right-2.5 top-1/2 -translate-y-1/2" />
                      )}
                    </div>
                    {!isEdited && field.fieldValueEn && (
                      <p className="text-xs text-muted-foreground italic pl-0.5">
                        {field.fieldValueEn}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                Validation results
              </h2>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleRevalidate}
                disabled={isRevalidating || isSubmitting}
                className="gap-1.5 h-7 px-2 text-xs text-muted-foreground"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", isRevalidating && "animate-spin")} />
                Re-run validation
              </Button>
            </div>
            {validations.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No validation results on record for this document yet — try "Re-run validation" above.
              </p>
            ) : (
              <ul className="space-y-2">
                {validations.map((v) => {
                  const { Icon, className } = VALIDATION_ICON[v.result];
                  return (
                    <li key={v.id} className="flex items-start gap-2 text-sm">
                      <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", className)} />
                      <span>
                        <span className="font-medium capitalize">{v.ruleName.replace(/_/g, " ")}</span>
                        <span className="text-muted-foreground"> — {v.message}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={handleApprove} disabled={isSubmitting} className="gap-2">
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              {Object.keys(edits).length ? "Save corrections & approve" : "Approve"}
              <kbd className="ml-1 text-[10px] font-tabular opacity-70">Ctrl+↵</kbd>
            </Button>
            <Button
              variant="destructive"
              disabled={isSubmitting}
              onClick={() => setFlagOpen(true)}
              className="gap-2"
            >
              <Flag className="h-4 w-4" />
              Flag
              <kbd className="ml-1 text-[10px] font-tabular opacity-70">F</kbd>
            </Button>
          </div>
        </div>
      </div>

      <Dialog open={flagOpen} onOpenChange={setFlagOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Flag for supervisor review</DialogTitle>
            <DialogDescription>
              Explain why {current.filename} needs a second look. This routes it to the
              supervisor queue instead of closing it out.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            autoFocus
            placeholder="e.g. Survey number illegible in scan, mutawalli name conflicts with register…"
            value={flagReason}
            onChange={(e) => setFlagReason(e.target.value)}
            rows={4}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setFlagOpen(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleFlag}
              disabled={isSubmitting || flagReason.trim().length === 0}
              className="gap-2"
            >
              {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Flag document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

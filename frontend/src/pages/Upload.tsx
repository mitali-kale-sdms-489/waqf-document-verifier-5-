import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Loader2,
  ScanSearch,
  ShieldCheck,
  UploadCloud,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { getAllDocuments, uploadDocument } from "@/api/documents";
import type { WaqfDocument } from "@/types/domain";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp", "image/tiff", "application/pdf"];
const ACCEPTED_EXT = ".png,.jpg,.jpeg,.webp,.tif,.tiff,.pdf";
const MAX_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB

// How long after we started an upload we're still willing to believe a
// just-appeared document on the list is *this* upload rather than an
// unrelated one the same user kicked off separately.
const RECONCILE_WINDOW_MS = 5 * 60 * 1000;
const RECONCILE_ATTEMPTS = 4;
const RECONCILE_DELAY_MS = 2500;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * A failed upload response doesn't necessarily mean a failed upload: the
 * backend runs OCR synchronously and can easily still be working (or have
 * already committed) after the browser has given up on the connection —
 * that's *why* this bug shows a client-side error but the record is on the
 * Dashboard after a manual refresh. Rather than rely on getting a timeout
 * number exactly right (which a proxy/network hiccup can defeat anyway),
 * poll the documents list for a few seconds after a failure and see if the
 * upload actually landed — matched by filename + uploader + recency, since
 * there's no upload id to key off of when the original request never got a
 * response. Returns the matching document if found, otherwise null.
 */
async function reconcileAfterFailedUpload(
  filename: string,
  uploaderEmail: string | undefined,
  uploadStartedAt: number
): Promise<WaqfDocument | null> {
  if (!uploaderEmail) return null;
  for (let attempt = 0; attempt < RECONCILE_ATTEMPTS; attempt++) {
    await sleep(RECONCILE_DELAY_MS);
    try {
      const docs = await getAllDocuments();
      const match = docs.find(
        (d) =>
          d.filename === filename &&
          d.uploadedBy === uploaderEmail &&
          Math.abs(new Date(d.uploadedAt).getTime() - uploadStartedAt) < RECONCILE_WINDOW_MS
      );
      if (match) return match;
    } catch {
      // Reconciliation check itself failed (e.g. still offline) — just
      // retry on the next attempt rather than giving up early.
    }
  }
  return null;
}

type UploadState = "uploading" | "reconciling" | "done" | "error";

interface UploadItem {
  key: string;
  file: File;
  localPreviewUrl: string | null;
  state: UploadState;
  progress: number;
  errorMessage?: string;
  document?: WaqfDocument;
}

function isAcceptedFile(file: File): boolean {
  if (ACCEPTED_TYPES.includes(file.type)) return true;
  // Some browsers report an empty type for .tiff — fall back to extension.
  return /\.(png|jpe?g|webp|tif|tiff|pdf)$/i.test(file.name);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function Upload() {
  const { isElevated, user } = useAuth();
  const [items, setItems] = useState<UploadItem[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const itemsRef = useRef<UploadItem[]>([]);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  // Revoke local object URLs for files we made previews for, on unmount.
  useEffect(() => {
    return () => {
      itemsRef.current.forEach((item) => {
        if (item.localPreviewUrl) URL.revokeObjectURL(item.localPreviewUrl);
      });
    };
  }, []);

  const processFiles = useCallback(
    (fileList: FileList | File[]) => {
      const files = Array.from(fileList);
      if (files.length === 0) return;

      files.forEach((file) => {
        const key = `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

        if (!isAcceptedFile(file)) {
          setItems((prev) => [
            ...prev,
            {
              key,
              file,
              localPreviewUrl: null,
              state: "error",
              progress: 0,
              errorMessage: "Unsupported file type. Use JPG, PNG, TIFF, WEBP, or PDF.",
            },
          ]);
          toast.error(`${file.name}: unsupported file type`);
          return;
        }
        if (file.size > MAX_SIZE_BYTES) {
          setItems((prev) => [
            ...prev,
            {
              key,
              file,
              localPreviewUrl: null,
              state: "error",
              progress: 0,
              errorMessage: "File is larger than the 25 MB limit.",
            },
          ]);
          toast.error(`${file.name}: exceeds 25 MB limit`);
          return;
        }

        const localPreviewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
        setItems((prev) => [
          ...prev,
          { key, file, localPreviewUrl, state: "uploading", progress: 0 },
        ]);

        // Simulate a realistic progress bar while the real upload + OCR
        // request (POST /documents/upload) is in flight server-side.
        const uploadStartedAt = Date.now();
        let progress = 0;
        const tick = setInterval(() => {
          progress = Math.min(progress + 10 + Math.random() * 20, 90);
          setItems((prev) => prev.map((it) => (it.key === key ? { ...it, progress } : it)));
        }, 150);

        uploadDocument(file)
          .then(({ document: doc }) => {
            clearInterval(tick);
            setItems((prev) =>
              prev.map((it) => (it.key === key ? { ...it, state: "done", progress: 100, document: doc } : it))
            );
            if (doc.dpdpStatus === "needs_review") {
              toast(`${file.name} queued, but DPDP compliance needs a supervisor's review.`, { icon: "⚠️" });
            } else if (doc.status === "flagged") {
              toast(`${file.name} uploaded, but OCR couldn't process it — flagged for review.`, { icon: "⚠️" });
            } else {
              toast.success(`${file.name} uploaded, DPDP-checked, and queued for review.`);
            }
          })
          .catch((err) => {
            clearInterval(tick);
            // No `response` at all means the request never got a reply from
            // the server — a client-side timeout, a dropped connection, or
            // an intermediary (dev proxy/reverse proxy) closing the socket
            // mid-request. In every one of those cases the backend can
            // still finish processing and commit the document after the
            // browser has already given up on the request, which is why
            // uploads that show as failed here can still show up on the
            // Dashboard a moment later. A real 4xx/5xx *with* a response
            // (bad file type, DB error, etc.) is a genuine failure — no
            // document was created, so reconciliation would correctly find
            // nothing and we go straight to the error state for those.
            const hasResponse = Boolean((err as { response?: unknown }).response);
            const message = hasResponse
              ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
                "Upload failed. Try again."
              : "Lost connection before the server replied — checking whether it finished anyway…";

            if (hasResponse) {
              setItems((prev) =>
                prev.map((it) => (it.key === key ? { ...it, state: "error", errorMessage: message } : it))
              );
              toast.error(`${file.name}: ${message}`);
              return;
            }

            // No response: don't commit to "failed" yet — check the
            // Dashboard ourselves instead of making the user do it.
            setItems((prev) =>
              prev.map((it) => (it.key === key ? { ...it, state: "reconciling", errorMessage: message } : it))
            );
            reconcileAfterFailedUpload(file.name, user?.email, uploadStartedAt).then((found) => {
              if (found) {
                setItems((prev) =>
                  prev.map((it) => (it.key === key ? { ...it, state: "done", progress: 100, document: found } : it))
                );
                toast.success(`${file.name} did finish uploading — connection just dropped before we heard back.`);
              } else {
                const finalMessage =
                  "Lost connection before the server replied, and it doesn't look like the upload went " +
                  "through — please try again.";
                setItems((prev) =>
                  prev.map((it) => (it.key === key ? { ...it, state: "error", errorMessage: finalMessage } : it))
                );
                toast.error(`${file.name}: ${finalMessage}`);
              }
            });
          });
      });
    },
    []
  );

  function handleBrowseChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files) processFiles(e.target.files);
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    dragCounter.current = 0;
    setIsDragging(false);
    if (e.dataTransfer.files?.length) processFiles(e.dataTransfer.files);
  }

  function handleDragEnter(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    dragCounter.current += 1;
    setIsDragging(true);
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setIsDragging(false);
    }
  }

  function removeItem(key: string) {
    setItems((prev) => {
      const target = prev.find((it) => it.key === key);
      if (target?.localPreviewUrl) URL.revokeObjectURL(target.localPreviewUrl);
      return prev.filter((it) => it.key !== key);
    });
  }

  const doneCount = items.filter((it) => it.state === "done").length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl">Upload</h1>
        <p className="text-sm text-muted-foreground">
          Submit a scanned record from this device for OCR and extraction. Each upload is
          automatically checked for DPDP compliance once extraction completes.
        </p>
      </div>

      <div
        onDragEnter={handleDragEnter}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "rounded-lg border-2 border-dashed bg-card p-16 text-center transition-colors",
          isDragging ? "border-primary bg-primary/5" : "border-border"
        )}
      >
        <UploadCloud
          className={cn("h-10 w-10 mx-auto mb-3", isDragging ? "text-primary" : "text-muted-foreground")}
          strokeWidth={1.5}
        />
        <p className="text-sm font-medium">
          Drag and drop scans here, or{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="text-primary underline underline-offset-4 hover:no-underline"
          >
            browse this device
          </button>
        </p>
        <p className="mt-1.5 text-xs text-muted-foreground">
          JPG, PNG, TIFF, WEBP, or PDF · up to 25 MB each · multiple files supported
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXT}
          multiple
          className="hidden"
          onChange={handleBrowseChange}
        />
      </div>

      {items.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              This session ({doneCount}/{items.length} complete)
            </h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((item) => (
              <div key={item.key} className="relative rounded-lg border border-border bg-card overflow-hidden">
                <button
                  type="button"
                  onClick={() => removeItem(item.key)}
                  className="absolute right-2 top-2 z-10 rounded-full bg-ink/60 p-1 text-white hover:bg-ink/80"
                  aria-label={`Remove ${item.file.name}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>

                <div className="h-36 bg-stone-dark flex items-center justify-center overflow-hidden">
                  {item.localPreviewUrl ? (
                    <img
                      src={item.localPreviewUrl}
                      alt={`Preview of ${item.file.name}`}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <FileText className="h-10 w-10 text-muted-foreground" strokeWidth={1.5} />
                  )}
                </div>

                <div className="p-3 space-y-2">
                  <p className="text-xs font-tabular truncate" title={item.file.name}>
                    {item.file.name}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{formatBytes(item.file.size)}</p>

                  {item.state === "uploading" && (
                    <div className="space-y-1">
                      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full bg-primary transition-all duration-150"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                      <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                        <Loader2 className="h-3 w-3 animate-spin" /> Uploading &amp; extracting…
                      </p>
                    </div>
                  )}

                  {item.state === "reconciling" && (
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <Loader2 className="h-3 w-3 animate-spin" /> {item.errorMessage}
                    </p>
                  )}

                  {item.state === "error" && (
                    <p className="text-[11px] text-rust">{item.errorMessage}</p>
                  )}

                  {item.state === "done" && item.document && (
                    <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="success" className="gap-1">
                          <CheckCircle2 className="h-3 w-3" /> Queued
                        </Badge>
                        {item.document.dpdpStatus === "compliant" ? (
                          <Badge variant="outline" className="gap-1" title={item.document.dpdpReason ?? undefined}>
                            <ShieldCheck className="h-3 w-3 text-registry-green" /> DPDP compliant
                          </Badge>
                        ) : (
                          <Badge variant="danger" className="gap-1" title={item.document.dpdpReason ?? undefined}>
                            <AlertTriangle className="h-3 w-3" /> DPDP: needs review
                          </Badge>
                        )}
                      </div>
                      {isElevated && (
                        <Button asChild size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs">
                          <Link to={`/review/${item.document.id}`}>
                            <ScanSearch className="h-3 w-3" /> Review
                          </Link>
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

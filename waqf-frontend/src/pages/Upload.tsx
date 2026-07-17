import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import toast from "react-hot-toast";
import {
  CheckCircle2,
  FileText,
  Loader2,
  RotateCcw,
  ScanSearch,
  UploadCloud,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { pollDocumentUntilReady, uploadDocument } from "@/api/documents";
import type { WaqfDocument } from "@/types/domain";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp", "image/tiff", "application/pdf"];
const ACCEPTED_EXT = ".png,.jpg,.jpeg,.webp,.tif,.tiff,.pdf";
const MAX_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB

// How many reupload attempts to show for a flagged document. This is
// purely informational — reuploading is never actually blocked, the
// count just ticks down (floors at 0) so the user has a sense of how
// many tries are typical before escalating to a supervisor.
const STARTING_REUPLOAD_ATTEMPTS = 2;

// How long we're willing to keep polling GET /documents/{id} for OCR to
// finish before we stop and just point the user at the Dashboard. The
// document itself was already created (status="processing") the moment
// uploadDocument() resolved, so there's nothing to retry here even if OCR
// takes longer than this — it's still safely queued either way.
const POLL_INTERVAL_MS = 2500;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

type UploadState = "uploading" | "processing" | "slow" | "done" | "error";

interface UploadItem {
  key: string;
  file: File;
  localPreviewUrl: string | null;
  state: UploadState;
  progress: number;
  errorMessage?: string;
  document?: WaqfDocument;
  /** Only set once a document comes back flagged; ticks down (floors at 0)
   *  each time the user hits "Reupload" for this item. Informational only —
   *  reuploading is never blocked. */
  remainingAttempts?: number;
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
  const { isElevated } = useAuth();
  const [items, setItems] = useState<UploadItem[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  // Per-item hidden file inputs used to trigger a reupload for one specific
  // flagged item without disturbing the rest of the session's items.
  const reuploadInputRefs = useRef<Map<string, HTMLInputElement>>(new Map());

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

  /** Uploads `file` for an already-existing item `key`, tracks progress,
   *  and polls until OCR settles. Shared by both a fresh drop/browse pick
   *  and a "Reupload" on an existing flagged item. */
  const runUpload = useCallback((key: string, file: File) => {
    let progress = 0;
    const tick = setInterval(() => {
      progress = Math.min(progress + 10 + Math.random() * 20, 90);
      setItems((prev) => prev.map((it) => (it.key === key ? { ...it, progress } : it)));
    }, 150);

    uploadDocument(file)
      .then(async ({ document: doc }) => {
        clearInterval(tick);
        // The document exists now (status="processing") — OCR runs as
        // a background task server-side. Poll by id (exact, no
        // filename/timing ambiguity) until it lands somewhere final.
        setItems((prev) =>
          prev.map((it) => (it.key === key ? { ...it, state: "processing", progress: 100, document: doc } : it))
        );

        const detail = await pollDocumentUntilReady(doc.id, {
          intervalMs: POLL_INTERVAL_MS,
          timeoutMs: POLL_TIMEOUT_MS,
        });

        if (!detail) {
          // Still processing after the poll window — not a failure,
          // just slower than usual (e.g. a local OCR engine under
          // load). The record is safely on the Dashboard already.
          setItems((prev) =>
            prev.map((it) =>
              it.key === key
                ? {
                    ...it,
                    state: "slow",
                    errorMessage:
                      "Still processing in the background — this is taking longer than usual. Check the Dashboard in a bit; no need to re-upload.",
                  }
                : it
            )
          );
          toast(`${file.name} is still processing — check the Dashboard shortly.`, { icon: "⏳" });
          return;
        }

        const finalDoc = detail.document;
        let attemptsLeftForToast = STARTING_REUPLOAD_ATTEMPTS;
        setItems((prev) =>
          prev.map((it) => {
            if (it.key !== key) return it;
            const isFlagged = finalDoc.status === "flagged";
            // First time this item is flagged, start the counter at 2.
            // Reuploading an already-flagged item ticks it down instead
            // (see reuploadItem) — this branch only covers a fresh flag.
            const remainingAttempts = isFlagged ? it.remainingAttempts ?? STARTING_REUPLOAD_ATTEMPTS : it.remainingAttempts;
            attemptsLeftForToast = remainingAttempts ?? STARTING_REUPLOAD_ATTEMPTS;
            return {
              ...it,
              state: "done",
              progress: 100,
              document: finalDoc,
              remainingAttempts,
            };
          })
        );
        if (finalDoc.status === "flagged") {
          toast(`${file.name} uploaded, but OCR couldn't process it — flagged for review.`, { icon: "⚠️" });
          toast(`${attemptsLeftForToast} upload${attemptsLeftForToast === 1 ? "" : "s"} left for ${file.name}.`, {
            icon: "🔁",
          });
        } else {
          toast.success(`${file.name} uploaded and queued for review.`);
        }
      })
      .catch((err) => {
        clearInterval(tick);
        // The upload request itself now only has to save the file and
        // create a DB row, so it should return in well under a second
        // — a failure here is a real failure (bad file, DB error, auth,
        // or a genuine network drop before the fast request completed),
        // not the old "OCR was still running" ambiguity. No
        // reconciliation step is needed: nothing slow happened yet, so
        // there's nothing to have silently finished in the background.
        const hasResponse = Boolean((err as { response?: unknown }).response);
        const message = hasResponse
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
            "Upload failed. Try again."
          : "Lost connection before the upload finished. Try again.";

        setItems((prev) => prev.map((it) => (it.key === key ? { ...it, state: "error", errorMessage: message } : it)));
        toast.error(`${file.name}: ${message}`);
      });
  }, []);

  const processFiles = useCallback(
    (fileList: FileList | File[]) => {
      const files = Array.from(fileList);
      if (files.length === 0) return;

      for (const file of files) {
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
          continue;
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
          continue;
        }

        const localPreviewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
        setItems((prev) => [...prev, { key, file, localPreviewUrl, state: "uploading", progress: 0 }]);
        runUpload(key, file);
      }
    },
    [runUpload]
  );

  /** Reuploads a fresh file into an existing (flagged) item's slot,
   *  ticking its remaining-attempts counter down — never blocking, just
   *  informational. */
  function reuploadItem(key: string, file: File) {
    setItems((prev) =>
      prev.map((it) => {
        if (it.key !== key) return it;
        if (it.localPreviewUrl) URL.revokeObjectURL(it.localPreviewUrl);
        const localPreviewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
        return {
          ...it,
          file,
          localPreviewUrl,
          state: "uploading",
          progress: 0,
          errorMessage: undefined,
          document: undefined,
          remainingAttempts: Math.max(0, (it.remainingAttempts ?? STARTING_REUPLOAD_ATTEMPTS) - 1),
        };
      })
    );
    runUpload(key, file);
  }

  function handleReuploadInputChange(key: string, e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!isAcceptedFile(file)) {
      toast.error(`${file.name}: unsupported file type`);
      return;
    }
    if (file.size > MAX_SIZE_BYTES) {
      toast.error(`${file.name}: exceeds 25 MB limit`);
      return;
    }
    reuploadItem(key, file);
  }

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
          Submit a scanned record from this device for OCR and extraction.
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
        {items.length > 0 && doneCount === items.length ? (
          <CheckCircle2 className="h-10 w-10 mx-auto mb-3 text-forest" strokeWidth={1.5} />
        ) : (
          <UploadCloud
            className={cn("h-10 w-10 mx-auto mb-3", isDragging ? "text-primary" : "text-muted-foreground")}
            strokeWidth={1.5}
          />
        )}

        {items.length > 0 ? (
          <p className="text-sm font-medium">
            {doneCount === items.length
              ? `${items.length} document${items.length === 1 ? "" : "s"} uploaded and extracted`
              : `${doneCount}/${items.length} uploaded — processing…`}
            {" · "}
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="text-primary underline underline-offset-4 hover:no-underline"
            >
              add more
            </button>
          </p>
        ) : (
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
        )}
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
                {item.state !== "done" && (
                  <button
                    type="button"
                    onClick={() => removeItem(item.key)}
                    className="absolute right-2 top-2 z-10 rounded-full bg-ink/60 p-1 text-white hover:bg-ink/80"
                    aria-label={`Remove ${item.file.name}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
                {item.state === "done" && (
                  <div
                    className="absolute right-2 top-2 z-10 rounded-full bg-forest/90 p-1 text-white"
                    aria-label="Extraction complete"
                    title="Extraction complete"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  </div>
                )}

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
                        <Loader2 className="h-3 w-3 animate-spin" /> Uploading…
                      </p>
                    </div>
                  )}

                  {item.state === "processing" && (
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <Loader2 className="h-3 w-3 animate-spin" /> Uploaded — extracting fields…
                    </p>
                  )}

                  {item.state === "slow" && (
                    <p className="text-[11px] text-muted-foreground">{item.errorMessage}</p>
                  )}

                  {item.state === "error" && (
                    <p className="text-[11px] text-rust">{item.errorMessage}</p>
                  )}

                  {item.state === "done" && item.document && (
                    <div className="space-y-2 pt-0.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        {item.document.status === "flagged" ? (
                          <Badge variant="danger" className="gap-1">
                            <RotateCcw className="h-3 w-3" /> Flagged
                          </Badge>
                        ) : (
                          <Badge variant="success" className="gap-1">
                            <CheckCircle2 className="h-3 w-3" /> Queued
                          </Badge>
                        )}
                        {isElevated && (
                          <Button asChild size="sm" variant="outline" className="h-7 gap-1 px-2 text-xs">
                            <Link to={`/review/${item.document.id}`}>
                              <ScanSearch className="h-3 w-3" /> Review
                            </Link>
                          </Button>
                        )}
                      </div>

                      {item.document.status === "flagged" && (
                        <div className="flex items-center justify-between gap-2 rounded-md bg-muted/60 px-2 py-1.5">
                          <p className="text-[11px] text-muted-foreground">
                            {item.remainingAttempts ?? STARTING_REUPLOAD_ATTEMPTS} upload
                            {(item.remainingAttempts ?? STARTING_REUPLOAD_ATTEMPTS) === 1 ? "" : "s"} left
                          </p>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 gap-1 px-2 text-xs"
                            onClick={() => reuploadInputRefs.current.get(item.key)?.click()}
                          >
                            <RotateCcw className="h-3 w-3" /> Reupload
                          </Button>
                          <input
                            ref={(el) => {
                              if (el) reuploadInputRefs.current.set(item.key, el);
                              else reuploadInputRefs.current.delete(item.key);
                            }}
                            type="file"
                            accept={ACCEPTED_EXT}
                            className="hidden"
                            onChange={(e) => handleReuploadInputChange(item.key, e)}
                          />
                        </div>
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

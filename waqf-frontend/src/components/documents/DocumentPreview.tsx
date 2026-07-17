import { cn } from "@/lib/utils";
import type { WaqfDocument } from "@/types/domain";
import { SCRIPT_TYPE_LABELS } from "@/types/domain";

function ScriptFacsimile({
  scriptType,
  className,
  minHeightClassName = "min-h-[480px]",
}: {
  scriptType: WaqfDocument["scriptType"];
  className?: string;
  minHeightClassName?: string;
}) {
  const isUrdu = scriptType === "urdu_nastaliq";
  const isEnglish = scriptType === "english_latin";
  // Seeded demo records have no real scan behind them — a stylised
  // facsimile stands in for the scan viewer. Real uploads render the
  // actual image/PDF below instead.
  const lines = isUrdu
    ? ["وقف نامہ برائے جائیداد", "متولی کا نام: _______________", "سروے نمبر: _______  رقبہ: _______", "تاریخ اندراج: _______________"]
    : isEnglish
    ? ["Waqf Property Registration", "Mutawalli name: _______________", "Survey no: _______  Extent: _______", "Registration date: _______________"]
    : ["वक्फ नोंदणी दस्तऐवज", "मुतवल्लीचे नाव: _______________", "सर्वे क्रमांक: _______  क्षेत्रफळ: _______", "नोंदणी तारीख: _______________"];

  return (
    <div
      className={cn(
        "relative flex-1 rounded-lg border border-border bg-[#F6F1E4] p-8 overflow-hidden",
        minHeightClassName,
        className
      )}
    >
      <div className="absolute inset-3 border border-ink/10 rounded" />
      <div
        className={cn(
          "relative h-full flex flex-col justify-center gap-6 text-ink/70 font-display",
          isUrdu ? "items-end text-right" : "items-start text-left"
        )}
        dir={isUrdu ? "rtl" : "ltr"}
      >
        {lines.map((line, i) => (
          <p key={i} className="text-lg leading-relaxed">
            {line}
          </p>
        ))}
      </div>
      <span className="absolute bottom-3 right-4 text-[10px] font-tabular text-ink/40 uppercase tracking-wide">
        Facsimile preview · {SCRIPT_TYPE_LABELS[scriptType]}
      </span>
    </div>
  );
}

/** Renders the person's own uploaded scan (image or PDF) when one exists;
 *  falls back to the stylised facsimile for seeded demo records. Shared by
 *  the Review workspace and the read-only preview dialog on the Dashboard. */
export function DocumentPreview({
  doc,
  className,
  minHeightClassName = "min-h-[480px]",
}: {
  doc: WaqfDocument;
  className?: string;
  minHeightClassName?: string;
}) {
  if (doc.previewUrl && doc.mimeType?.startsWith("image/")) {
    return (
      <div
        className={cn(
          "relative flex-1 rounded-lg border border-border bg-stone-dark overflow-hidden flex items-center justify-center",
          minHeightClassName,
          className
        )}
      >
        <img
          src={doc.previewUrl}
          alt={`Scan of ${doc.filename}`}
          className="h-full max-h-full w-full object-contain"
        />
        <span className="absolute bottom-3 right-4 text-[10px] font-tabular text-ink/50 uppercase tracking-wide bg-white/70 rounded px-1.5 py-0.5">
          Uploaded scan
        </span>
      </div>
    );
  }

  if (doc.previewUrl && doc.mimeType === "application/pdf") {
    return (
      <div
        className={cn(
          "relative flex-1 rounded-lg border border-border bg-stone-dark overflow-hidden flex flex-col",
          minHeightClassName,
          className
        )}
      >
        <iframe title={`PDF preview of ${doc.filename}`} src={doc.previewUrl} className="flex-1 w-full" />
        <div className="flex items-center justify-between gap-2 border-t border-border bg-card px-3 py-2">
          <span className="text-[11px] font-tabular text-muted-foreground uppercase tracking-wide">
            Uploaded PDF
          </span>
          <a
            href={doc.previewUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-primary underline underline-offset-4 hover:no-underline"
          >
            Open in new tab
          </a>
        </div>
      </div>
    );
  }

  return (
    <ScriptFacsimile scriptType={doc.scriptType} className={className} minHeightClassName={minHeightClassName} />
  );
}

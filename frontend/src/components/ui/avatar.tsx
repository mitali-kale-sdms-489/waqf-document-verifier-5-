import { cn } from "@/lib/utils";

function getInitials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

interface AvatarProps {
  fullName: string;
  className?: string;
}

export function Avatar({ fullName, className }: AvatarProps) {
  return (
    <div
      className={cn(
        "flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-semibold",
        className
      )}
      aria-hidden
    >
      {getInitials(fullName)}
    </div>
  );
}

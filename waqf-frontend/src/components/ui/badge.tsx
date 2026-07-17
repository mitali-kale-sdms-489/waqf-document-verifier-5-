import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        // Confidence bands (architecture doc §8: green ≥0.9, amber 0.6–0.9, red <0.6)
        success: "border-transparent bg-registry-green/15 text-registry-green",
        // Distinct clear-green used only for "Accepted" documents, kept
        // separate from `success` (which also backs the high-confidence
        // band badge) so the two can be styled independently.
        accepted: "border-transparent bg-green-100 text-green-700",
        warning: "border-transparent bg-brass/15 text-brass",
        danger: "border-transparent bg-rust/15 text-rust",
        // Role badges (Header) — named by permission level, not role label
        roleElevated: "border-transparent bg-brass text-white",
        roleStandard: "border-transparent bg-primary text-primary-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

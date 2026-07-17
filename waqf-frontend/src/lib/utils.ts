import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge conditional class names and resolve Tailwind conflicts.
 * Standard shadcn/ui helper — used by every UI primitive.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

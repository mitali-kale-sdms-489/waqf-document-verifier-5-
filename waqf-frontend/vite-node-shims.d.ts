/**
 * Minimal ambient declarations for the two Node.js globals vite.config.ts
 * needs (`path.resolve`, `__dirname`). This project doesn't have
 * @types/node installed — run `npm install -D @types/node` and delete this
 * file if/when that becomes available; it's a more complete substitute.
 */
declare module "path" {
  export function resolve(...paths: string[]): string;
}
declare const __dirname: string;

import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 text-center px-4">
      <p className="font-mono text-sm text-muted-foreground">404</p>
      <h1 className="font-display text-2xl">No record at this address</h1>
      <p className="text-sm text-muted-foreground max-w-sm">
        The page you're looking for doesn't exist. Check the URL, or return to
        the registry.
      </p>
      <Link
        to="/dashboard"
        className="mt-2 text-sm font-medium text-primary underline underline-offset-4"
      >
        Back to registry
      </Link>
    </div>
  );
}

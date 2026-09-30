"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Route-level error boundary. React renders this instead of the page subtree
 * whenever rendering or data loading throws — so no crash ever whitescreens
 * the app. Each route segment can override it with its own error.tsx.
 */
export default function GlobalRouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surfaced in the browser console/devtools for real debugging.
    console.error("Route error boundary caught:", error);
  }, [error]);

  return (
    <div className="mx-auto w-full max-w-md px-4 py-24">
      <div
        className="rounded-xl border border-rose-500/30 bg-card/70 p-8 text-center"
        role="alert"
      >
        <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-rose-400" />
        <h1 className="text-lg font-semibold">Something went wrong</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          An unexpected error interrupted this page. Your data is safe — try
          again.
        </p>
        {error.digest && (
          <p className="mt-2 font-mono text-xs text-muted-foreground/60">
            ref: {error.digest}
          </p>
        )}
        <Button variant="outline" className="mt-5" onClick={reset}>
          <RefreshCw className="size-4" /> Try again
        </Button>
      </div>
    </div>
  );
}

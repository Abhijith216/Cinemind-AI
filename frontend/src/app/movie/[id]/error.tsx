"use client";

import { Link2Off, RefreshCw } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

/**
 * Movie-page boundary: covers unknown movie ids (404-ish renders) and
 * backend failures during server components — the page never whitescreens.
 */
export default function MovieError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto w-full max-w-md px-4 py-24">
      <div
        className="rounded-xl border border-rose-500/30 bg-card/70 p-8 text-center"
        role="alert"
      >
        <Link2Off className="mx-auto mb-3 h-8 w-8 text-rose-400" />
        <h1 className="text-lg font-semibold">Movie not found or unavailable</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          The backend may be down, or that movie id doesn't exist in the
          catalog.
        </p>
        <div className="mt-5 flex justify-center gap-3">
          <Button variant="outline" onClick={reset}>
            <RefreshCw className="size-4" /> Retry
          </Button>
          <Link
            href="/"
            className="inline-flex h-10 items-center rounded-lg border border-border px-5 text-sm hover:bg-secondary/60"
          >
            Back to Discover
          </Link>
        </div>
      </div>
    </div>
  );
}

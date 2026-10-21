"use client";

import { Link2Off, RefreshCw } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

/**
 * Temporary movie-loading failures. Missing movies use not-found.tsx.
 */
export default function MovieError() {
  return (
    <div className="cinema-shell flex min-h-[calc(100dvh-11rem)] items-center justify-center py-16">
      <div
        className="cinema-surface w-full max-w-xl rounded-[1.5rem] p-8 text-center sm:p-12"
        role="alert"
      >
        <Link2Off className="mx-auto mb-3 h-8 w-8 text-rose-400" />
        <h1 className="cinema-display text-3xl sm:text-4xl">Movie details are unavailable</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          We could not reach the movie catalog. Try again in a moment.
        </p>
        <div className="mt-5 flex justify-center gap-3">
          <form method="get" aria-label="Retry loading this movie">
            <Button type="submit" variant="outline">
              <RefreshCw className="size-4" /> Retry
            </Button>
          </form>
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

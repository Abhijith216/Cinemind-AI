"use client";

import { Suspense, useEffect, useState } from "react";
import { Film, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { RequireAuth } from "@/components/require-auth";
import { TasteEvolutionChart } from "@/components/taste-evolution-chart";
import { api, ApiError, type TasteSnapshotOut } from "@/lib/api";

function arcSummary(snapshots: TasteSnapshotOut[]): string {
  if (snapshots.length === 0) return "";
  const first = snapshots[0]?.dominant_genres[0];
  const last = snapshots[snapshots.length - 1]?.dominant_genres[0];
  if (!first || !last) return "";
  if (snapshots.length === 1 || first === last) {
    return `Consistently drawn to ${first.toLowerCase()}.`;
  }
  return `Mostly ${first.toLowerCase()} → now ${last.toLowerCase()}.`;
}

function TasteEvolutionContent() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  // ?user= wins (demo/inspection); otherwise the signed-in user's id.
  const userId = searchParams.get("user") ?? user?.id ?? null;

  const [snapshots, setSnapshots] = useState<TasteSnapshotOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    setSnapshots(null);
    setError(null);
    api.users
      .tasteEvolution(userId)
      .then((data) => {
        if (!cancelled) setSnapshots(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? `${err.status}: ${err.message}`
              : "Couldn't reach the backend. Is it running on :8000?",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Taste evolution</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          How your dominant genres and themes shift month to month.
        </p>
        {snapshots && snapshots.length > 0 && (
          <p className="mt-2 text-sm text-amber-300">{arcSummary(snapshots)}</p>
        )}
      </header>

      {error && (
        <p className="text-sm text-rose-400" role="alert">
          {error}
        </p>
      )}

      {snapshots === null && !error && (
        <div
          className="flex items-center justify-center gap-2 py-24 text-sm text-muted-foreground"
          role="status"
        >
          <Loader2 className="size-4 animate-spin" />
          Loading your taste timeline…
        </div>
      )}

      {/* New-user empty state: real backend response of [], not an error. */}
      {snapshots !== null && snapshots.length === 0 && (
        <div className="rounded-lg border border-dashed border-border/60 bg-card/40 p-10 text-center">
          <Film className="mx-auto mb-3 h-8 w-8 text-primary/70" />
          <p className="font-medium">Your timeline starts with your first ratings</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
            Each month, CineMind snapshots the genres and themes you rated
            highest. Rate a few movies in{" "}
            <Link
              href="/chat"
              className="text-primary underline-offset-4 hover:underline"
            >
              Chat
            </Link>{" "}
            and your arc appears here.
          </p>
        </div>
      )}

      {snapshots !== null && snapshots.length > 0 && (
        <TasteEvolutionChart snapshots={snapshots} />
      )}
    </div>
  );
}

export default function TasteEvolutionPage() {
  return (
    <RequireAuth>
      <Suspense fallback={null}>
        <TasteEvolutionContent />
      </Suspense>
    </RequireAuth>
  );
}

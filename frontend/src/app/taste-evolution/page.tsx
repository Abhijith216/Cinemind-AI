"use client";

import { useEffect, useState } from "react";
import { Film, Loader2 } from "lucide-react";
import Link from "next/link";

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
  const userId = user?.id ?? null;
  const [revision, setRevision] = useState(0);

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
              : "Couldn’t load your taste timeline. Please try again.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId, revision]);

  return (
    <div className="cinema-shell max-w-5xl py-10 sm:py-16">
      <header className="mb-12 rounded-[1.5rem] border border-border bg-[#1b1516] p-7 sm:p-12">
        <p className="cinema-eyebrow mb-4">Your movie history</p>
        <h1 className="cinema-display text-5xl sm:text-6xl">Taste evolution</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Your favorite genres and themes each month, weighted by movies you rated 7 or higher. Updates automatically when you save or change a rating.
        </p>
        <Link href="/profile" className="mt-3 inline-block text-sm text-primary underline">← Back to My Taste and ratings</Link>
        {snapshots && snapshots.length > 0 && (
          <p className="mt-2 text-sm text-amber-300">{arcSummary(snapshots)}</p>
        )}
      </header>

      {error && (
        <p className="text-sm text-rose-400" role="alert">
          {error}
          {" "}<button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Try again</button>
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
        <div className="cinema-surface rounded-[1.5rem] p-10 text-center">
          <Film className="mx-auto mb-3 h-8 w-8 text-primary/70" />
          <p className="font-medium">Your timeline starts with movies you love</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
            Give a movie 7 or higher in{" "}
            <Link
              href="/profile"
              className="text-primary underline-offset-4 hover:underline"
            >
              My Taste
            </Link>{" "}
            and your first month appears here. More months will show how your preferences change.
          </p>
        </div>
      )}

      {snapshots !== null && snapshots.length > 0 && (
        <div className="space-y-6">
          {snapshots.length === 1 && <p className="rounded-lg border border-border bg-card/40 p-4 text-sm text-muted-foreground">Your first month is ready. As you rate movies in future months, you’ll see the changes side by side.</p>}
          <ul aria-label="Monthly taste history" className="space-y-3">{snapshots.map((snapshot) => <li key={snapshot.month} className="rounded-xl border border-border bg-card/50 p-5"><h2 className="font-semibold">{new Date(`${snapshot.month}-01T12:00:00Z`).toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" })}</h2><p className="mt-2 text-sm"><span className="text-muted-foreground">Genres: </span>{snapshot.dominant_genres.join(", ") || "None yet"}</p><p className="mt-1 text-sm"><span className="text-muted-foreground">Themes: </span>{snapshot.dominant_themes.join(", ") || "None yet"}</p></li>)}</ul>
          {snapshots.length > 1 && <TasteEvolutionChart snapshots={snapshots} />}
        </div>
      )}
    </div>
  );
}

export default function TasteEvolutionPage() {
  return (
    <RequireAuth>
      <TasteEvolutionContent />
    </RequireAuth>
  );
}

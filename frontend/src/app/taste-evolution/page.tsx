"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { TasteEvolutionChart } from "@/components/taste-evolution-chart";
import { api, ApiError, type TasteSnapshotOut } from "@/lib/api";

const USER_STORAGE_KEY = "cinemind.user_id";

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
  const searchParams = useSearchParams();
  const userParam = searchParams.get("user");
  const [userId, setUserId] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<TasteSnapshotOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  // Resolve the user: ?user= param wins, else the remembered demo user.
  useEffect(() => {
    if (userParam) {
      window.localStorage.setItem(USER_STORAGE_KEY, userParam);
      setUserId(userParam);
      return;
    }
    const saved = window.localStorage.getItem(USER_STORAGE_KEY);
    if (saved) setUserId(saved);
  }, [userParam]);

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
              : "Failed to load taste evolution.",
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

      {!userId && (
        <form
          className="mb-6 flex max-w-md gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.trim().length === 0) return;
            window.localStorage.setItem(USER_STORAGE_KEY, draft.trim());
            setUserId(draft.trim());
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Paste a user id (demo backend prints one)"
            className="flex-1 rounded-md border border-border bg-card px-3 py-2 text-sm"
            aria-label="User id"
          />
          <button
            type="submit"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            Load
          </button>
        </form>
      )}

      {error && (
        <p className="text-sm text-rose-400" role="alert">
          {error}
        </p>
      )}

      {snapshots === null && !error && userId && (
        <p className="text-sm text-muted-foreground">Loading your taste timeline…</p>
      )}

      {snapshots && <TasteEvolutionChart snapshots={snapshots} />}
    </div>
  );
}

export default function TasteEvolutionPage() {
  return (
    <Suspense fallback={null}>
      <TasteEvolutionContent />
    </Suspense>
  );
}

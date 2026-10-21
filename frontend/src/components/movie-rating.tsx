"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";

export function MovieRating({ movieId, initialScore, onSaved }: {
  movieId: string;
  initialScore?: number | null;
  onSaved?: () => void;
}) {
  const { user, hydrated } = useAuth();
  const userId = user?.id;
  const [score, setScore] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const sending = useRef(false);

  useEffect(() => {
    setSaved(null); setError(null); setScore(initialScore?.toString() ?? "");
    if (!userId || initialScore !== undefined) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    api.ratings.get(movieId, controller.signal).then((rating) => {
      if (!controller.signal.aborted) setScore(rating?.score.toString() ?? "");
    }).catch(() => {
      if (!controller.signal.aborted) setError("Couldn’t load your rating. Please try again.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [movieId, userId, initialScore, reload]);

  if (!hydrated) return <p role="status" className="text-sm text-muted-foreground">Loading your rating…</p>;
  if (!user) return <p className="text-sm text-muted-foreground">
    <Link className="text-primary underline" href={`/login?next=${encodeURIComponent(`/movie/${movieId}`)}`}>Sign in to rate this movie</Link>
    {" "}and build your personal taste profile.
  </p>;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!user || !score || sending.current) return;
    sending.current = true; setPending(true); setError(null); setSaved(null);
    try {
      const rating = await api.ratings.create({ user_id: user.id, movie_id: movieId, score: Number(score) });
      setSaved(rating.score);
      onSaved?.();
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 401
        ? "Sign in again to save your rating."
        : "Your rating wasn’t saved. Please try again.");
    } finally { sending.current = false; setPending(false); }
  }

  return <form onSubmit={(event) => void save(event)} className="space-y-3" aria-label="Rate this movie">
    <label className="block text-sm font-medium">Your rating
      <select aria-label="Your rating" value={score} disabled={loading || pending}
        onChange={(event) => { setScore(event.target.value); setSaved(null); }}
        className="mt-2 block h-11 w-full rounded-lg border border-border bg-background px-3 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <option value="">Choose a score</option>
        {Array.from({ length: 10 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}/10{value === 1 ? " · Hated it" : value === 5 ? " · Mixed feelings" : value === 10 ? " · Loved it" : ""}</option>)}
      </select>
    </label>
    <p className="text-xs leading-relaxed text-muted-foreground">7–10 builds your likes, 1–4 signals what to avoid, and 5–6 stays neutral. You can change your score anytime.</p>
    <Button type="submit" disabled={loading || pending || !score}>{pending ? "Saving…" : "Save rating"}</Button>
    {loading && <p role="status" className="text-sm text-muted-foreground">Loading your saved rating…</p>}
    {saved !== null && <p role="status" className="text-sm text-primary">Saved {saved}/10. <Link href="/profile" className="underline">Your taste profile is updated.</Link></p>}
    {error && <div role="alert" className="text-sm text-rose-400">{error} <button type="button" className="underline" onClick={() => setReload((value) => value + 1)}>Reload rating</button></div>}
  </form>;
}

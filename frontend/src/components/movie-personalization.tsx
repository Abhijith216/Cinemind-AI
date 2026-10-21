"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { MovieRating } from "@/components/movie-rating";
import { RecommendationGraphView } from "@/components/recommendation-graph-view";
import { api, type RecommendationGraph } from "@/lib/api";

export function MoviePersonalization({ movieId }: { movieId: string }) {
  const { user } = useAuth();
  const userId = user?.id;
  const [revision, setRevision] = useState(0);
  const [graph, setGraph] = useState<RecommendationGraph | null>(null);
  const [error, setError] = useState(false);
  const [graphOwner, setGraphOwner] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setGraph(null); setError(false);
    if (!userId) return;
    api.movies.recommendationGraph(movieId, userId).then((data) => {
      if (!cancelled) { setGraph(data); setGraphOwner(userId); }
    }).catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [userId, movieId, revision]);
  return <div className="space-y-14">
    <section className="cinema-surface rounded-[1.5rem] p-7 sm:p-10" aria-label="Your movie rating">
      <p className="cinema-eyebrow mb-4">Make it yours</p>
      <h2 className="mb-5 text-2xl font-semibold tracking-tight">Seen it? Add it to My Taste.</h2>
      <MovieRating key={userId ?? "anonymous"} movieId={movieId} onSaved={() => setRevision((value) => value + 1)} />
    </section>
    {user && <section aria-label="Connections to your favorites">
      <h2 className="mb-2 text-2xl font-semibold tracking-tight">Connections to your favorites</h2>
      <p className="mb-4 text-sm text-muted-foreground">Real genres and themes shared with movies you rated highly.</p>
      {graph && graphOwner === userId && <RecommendationGraphView graph={graph} />}
      {error && <p className="text-sm text-muted-foreground">Couldn’t load your connections. <button type="button" className="text-primary underline" onClick={() => setRevision((value) => value + 1)}>Try again</button></p>}
      {!graph && !error && <p role="status" className="text-sm text-muted-foreground">Finding your movie connections…</p>}
    </section>}
  </div>;
}

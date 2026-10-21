"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Film, Search, Sparkles } from "lucide-react";

import { useAuth } from "@/components/auth-provider";
import { RequireAuth } from "@/components/require-auth";
import { MovieRating } from "@/components/movie-rating";
import { MovieCard, type MatchedAttributeGroup } from "@/components/movie-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, ApiError, type MovieOut, type TasteDashboardOut, type TasteRecommendationOut, type RatedMovieOut } from "@/lib/api";

function tasteGroups(movie: TasteRecommendationOut): MatchedAttributeGroup[] {
  const groups: MatchedAttributeGroup[] = [
    { label: "Genres you enjoy", kind: "genre", items: movie.matched_attributes.genres },
    { label: "Themes you enjoy", kind: "theme", items: movie.matched_attributes.themes },
    { label: "Movies you enjoyed", kind: "loved", items: movie.matched_attributes.loved_movie_overlaps.map((match) => match.label) },
  ];
  return groups.filter((group) => group.items.length > 0);
}

function ProfileContent() {
  const { user } = useAuth();
  const userId = user?.id;
  const [dashboard, setDashboard] = useState<TasteDashboardOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<MovieOut[] | null>(null);
  const [selected, setSelected] = useState<MovieOut | null>(null);
  const [history, setHistory] = useState<RatedMovieOut[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const historyController = useRef<AbortController | null>(null);
  const searchController = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!userId) return;
    const controller = new AbortController();
    setError(null); setLoading(true);
    api.users.tasteDashboard(userId, controller.signal).then((data) => {
      if (!controller.signal.aborted) { setDashboard(data); setHistory(data.ratings); setHistoryError(null); }
    }).catch((failure) => {
      if (!controller.signal.aborted) setError(failure instanceof ApiError && failure.status === 401
        ? "Your session expired. Sign in again to see your taste profile."
        : "Couldn’t load your taste profile. Please try again.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [userId, revision]);
  useEffect(() => () => searchController.current?.abort(), []);
  useEffect(() => () => historyController.current?.abort(), []);

  async function loadOlder() {
    if (historyLoading || removing) return;
    const controller = new AbortController();
    historyController.current?.abort(); historyController.current = controller;
    setHistoryLoading(true); setHistoryError(null);
    try {
      const page = await api.ratings.history(history.length, controller.signal);
      if (!controller.signal.aborted) setHistory((current) => {
        const existing = new Set(current.map((rating) => rating.id));
        return [...current, ...page.items.filter((rating) => !existing.has(rating.id))];
      });
    } catch { if (!controller.signal.aborted) setHistoryError("Couldn’t load older ratings. Try again."); }
    finally { if (!controller.signal.aborted) setHistoryLoading(false); }
  }

  async function removeRating(movieId: string) {
    setRemoving(movieId); setHistoryError(null);
    try {
      await api.ratings.remove(movieId);
      setHistory((current) => current.filter((rating) => rating.movie.id !== movieId));
      if (selected?.id === movieId) setSelected(null);
      setConfirmRemove(null); setRevision((value) => value + 1);
    } catch { setHistoryError("Couldn’t remove that rating. Please try again."); }
    finally { setRemoving(null); }
  }

  async function findMovies(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim() || searching) return;
    const controller = new AbortController();
    searchController.current?.abort(); searchController.current = controller;
    setSearching(true); setSearchError(null); setResults(null);
    try {
      const data = await api.search.discover({ query: query.trim(), limit: 6 }, controller.signal);
      if (!controller.signal.aborted) setResults(data.results.map((item) => item.movie));
    } catch {
      if (!controller.signal.aborted) setSearchError("Couldn’t search the catalog. Please try again.");
    } finally { if (!controller.signal.aborted) setSearching(false); }
  }

  const profile = dashboard?.profile;
  const selectedScore = history.find((rating) => rating.movie.id === selected?.id)?.score;
  return <div className="space-y-14">
    <header className="relative overflow-hidden rounded-[1.75rem] border border-border bg-[#1b1516] px-7 py-12 sm:px-12 sm:py-16">
      <div className="pointer-events-none absolute -right-20 -top-24 size-96 rounded-full bg-primary/10 blur-3xl" aria-hidden="true" />
      <p className="cinema-eyebrow mb-4">Your personal movie journal</p>
      <h1 className="cinema-display relative text-5xl sm:text-6xl">My Taste</h1>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">Rate the movies you’ve seen. We’ll build your likes, notice your favorite themes, and find more films that share them. Your scores stay in your account.</p>
      <Link href="/taste-evolution" className="mt-3 inline-block text-sm text-primary underline-offset-4 hover:underline">See how your taste evolves →</Link>
    </header>
    {loading && <p role="status" className="text-sm text-muted-foreground">Updating your taste profile…</p>}
    {error && <div role="alert" className="rounded-xl border border-rose-500/30 p-4 text-sm text-rose-300">{error} <button className="underline" type="button" onClick={() => setRevision((value) => value + 1)}>Try again</button> · <Link href="/login?next=%2Fprofile" className="underline">Sign in</Link></div>}
    {dashboard && <section className="grid grid-cols-2 gap-3 sm:grid-cols-3" aria-label="Your rating summary">
      <div className="rounded-xl border border-border bg-card/50 p-4"><p className="text-2xl font-semibold">{dashboard.total_ratings}</p><p className="text-xs text-muted-foreground">Movies rated</p></div>
      <div className="rounded-xl border border-border bg-card/50 p-4"><p className="text-2xl font-semibold">{dashboard.average_score === null ? "—" : `${dashboard.average_score.toFixed(1)}/10`}</p><p className="text-xs text-muted-foreground">Your average score</p></div>
      <div className="rounded-xl border border-border bg-card/50 p-4"><p className="text-2xl font-semibold">{profile?.favorite_themes.length ?? 0}</p><p className="text-xs text-muted-foreground">Favorite themes</p></div>
    </section>}
    <section aria-labelledby="rate-heading" className="cinema-surface rounded-[1.5rem] p-6 sm:p-9">
      <h2 id="rate-heading" className="flex items-center gap-2 text-xl font-semibold"><Film className="size-5 text-primary" />{dashboard?.total_ratings ? "Rate another movie" : "Start with a movie you’ve seen"}</h2>
      <p className="mt-2 text-sm text-muted-foreground">Search for a title, then give it a score from 1 to 10. A few honest ratings are enough to start.</p>
      <form aria-label="Find a movie to rate" onSubmit={(event) => void findMovies(event)} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label className="flex-1"><span className="sr-only">Movie title</span><input value={query} onChange={(event) => setQuery(event.target.value)} required maxLength={1000} placeholder="Search a movie you’ve watched…" className="h-11 w-full rounded-lg border border-border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></label>
        <Button type="submit" disabled={searching || !query.trim()}><Search className="size-4" />{searching ? "Searching…" : "Find movie"}</Button>
      </form>
      {searchError && <p role="alert" className="mt-3 text-sm text-rose-300">{searchError}</p>}
      {results?.length === 0 && <p role="status" className="mt-3 text-sm text-muted-foreground">No movies found. Try the full title or a different spelling.</p>}
      {results && results.length > 0 && <ul aria-label="Movies to rate" className="mt-4 divide-y divide-border rounded-lg border border-border">
        {results.map((movie) => <li key={movie.id} className="flex items-center justify-between gap-3 p-3"><div><p className="font-medium">{movie.title}</p><p className="text-xs text-muted-foreground">{movie.release_year} · {movie.genres.slice(0, 2).join(", ")}</p></div><Button type="button" variant="outline" aria-label={`Rate ${movie.title}`} onClick={() => setSelected(movie)}>Rate</Button></li>)}
      </ul>}
      {selected && <div className="mt-5 space-y-3 rounded-lg border border-primary/30 bg-background/50 p-4" aria-label={`Rating ${selected.title}`}>
        <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{selected.title}</h3><button type="button" className="text-xs text-muted-foreground underline" onClick={() => setSelected(null)}>Close rating</button></div>
        <MovieRating key={selected.id} movieId={selected.id} initialScore={selectedScore} onSaved={() => setRevision((value) => value + 1)} />
      </div>}
    </section>
    {dashboard && <section aria-label="Your preferences" className="grid gap-4 md:grid-cols-3">
      {[
        { title: "You like", tags: profile?.likes ?? [], empty: "Movies rated 7–10 add their genres and themes here." },
        { title: "Favorite themes", tags: profile?.favorite_themes ?? [], empty: "Themes from movies you enjoy will appear here." },
        { title: "Less your thing", tags: profile?.dislikes ?? [], empty: "Movies rated 1–4 help us understand what to avoid." },
      ].map((group) => <div key={group.title} className="rounded-xl border border-border bg-card/40 p-5"><h2 className="mb-3 font-semibold">{group.title}</h2><div className="flex flex-wrap gap-2">{group.tags.length ? group.tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>) : <p className="text-sm leading-relaxed text-muted-foreground">{group.empty}</p>}</div></div>)}
    </section>}
    {dashboard && <section aria-label="Movies for your taste">
      <h2 className="flex items-center gap-2 text-xl font-semibold"><Sparkles className="size-5 text-primary" />More your kind of movie</h2>
      <p className="mt-2 text-sm text-muted-foreground">Based on genres and themes from your ratings of 7–10, balanced against your ratings of 1–4. Movies you’ve rated are left out.</p>
      {dashboard.recommendations.length ? <div className="mt-4 flex gap-4 overflow-x-auto pb-3">{dashboard.recommendations.map((movie) => <MovieCard key={movie.id} movieId={movie.id} title={movie.title} year={movie.release_year} runtime={movie.runtime} rating={movie.vote_average} overview={movie.overview} posterUrl={movie.poster_path ? `https://image.tmdb.org/t/p/w500${movie.poster_path}` : null}
        explanation={movie.explanation}
        matched={tasteGroups(movie)}
        className="shrink-0" />)}</div>
        : <p className="mt-4 rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">{dashboard.total_ratings ? "No unrated matches from your current preferences yet. Rate a few more movies you enjoyed to broaden your suggestions." : "Rate a movie you enjoyed 7 or higher to start finding similar films."}</p>}
    </section>}
    {dashboard && history.length > 0 && <section aria-labelledby="history-heading">
      <h2 id="history-heading" className="text-xl font-semibold">Your recent ratings</h2>
      <p className="mt-1 text-xs text-muted-foreground">Showing {history.length} of {dashboard.total_ratings} ratings. Editing or removing a score updates your preferences.</p>
      <ul className="mt-4 divide-y divide-border rounded-xl border border-border bg-card/40">{history.map((rating) => <li key={rating.id} className="flex flex-wrap items-center justify-between gap-3 p-4"><div><Link href={`/movie/${rating.movie.id}`} className="font-medium hover:text-primary">{rating.movie.title}</Link><p className="mt-1 text-xs text-muted-foreground">{rating.movie.release_year} · Rated {new Date(rating.rated_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</p></div><div className="flex flex-wrap items-center gap-3"><span className="font-semibold text-primary">{rating.score}/10</span><Button variant="outline" type="button" aria-label={`Edit rating for ${rating.movie.title}`} onClick={() => { setSelected(rating.movie); document.getElementById("rate-heading")?.scrollIntoView?.({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); }}>Edit</Button><Button variant="ghost" type="button" disabled={loading || historyLoading || removing !== null} aria-label={`Remove rating for ${rating.movie.title}`} onClick={() => setConfirmRemove(rating.movie.id)}>Remove</Button></div>
        {confirmRemove === rating.movie.id && <div className="w-full space-y-2 rounded-lg border border-border p-3"><p className="text-sm">Remove your rating for {rating.movie.title}? Its influence on your taste will be cleared.</p><div className="flex gap-2"><Button type="button" disabled={removing !== null} onClick={() => void removeRating(rating.movie.id)}>{removing ? "Removing…" : "Confirm removal"}</Button><Button variant="outline" type="button" disabled={removing !== null} onClick={() => setConfirmRemove(null)}>Cancel</Button></div></div>}
      </li>)}</ul>
      {historyError && <p role="alert" className="mt-3 text-sm text-rose-300">{historyError}</p>}
      {history.length < dashboard.total_ratings && <Button type="button" variant="outline" className="mt-4" disabled={historyLoading || loading || removing !== null} onClick={() => void loadOlder()}>{historyLoading ? "Loading ratings…" : "Load older ratings"}</Button>}
    </section>}
  </div>;
}

export default function ProfilePage() {
  const { user } = useAuth();
  return <RequireAuth><div className="cinema-shell max-w-6xl py-10 sm:py-16"><ProfileContent key={user?.id} /></div></RequireAuth>;
}

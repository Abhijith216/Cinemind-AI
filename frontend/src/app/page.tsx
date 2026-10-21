"use client";

import { ArrowRight, LoaderCircle, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { DiscoverChapters } from "@/components/discover-chapters";
import { MovieCard } from "@/components/movie-card";
import { RotatingText } from "@/components/rotating-text";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, ApiError, type DiscoverResponse, type SearchRequest } from "@/lib/api";

const SUGGESTIONS = [
  "Something like Interstellar but not about space",
  "A cozy comfort movie with witty dialogue",
  "Mind-bending, emotional, under two hours",
];
const HEADLINE_WORDS = ["mood", "feeling", "story", "world"];
const GENRES = [
  "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama",
  "Family", "Fantasy", "History", "Horror", "Music", "Mystery", "Romance",
  "Science Fiction", "Thriller", "War", "Western",
];
const SELECT_STYLE = "mt-1 h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";

export default function DiscoverPage() {
  const [query, setQuery] = useState("");
  const [genre, setGenre] = useState("");
  const [maxRuntime, setMaxRuntime] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<DiscoverResponse | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const lastRequest = useRef<SearchRequest | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function search(payload: SearchRequest) {
    if (controller.current) return;
    const activeController = new AbortController();
    controller.current = activeController;
    lastRequest.current = payload;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const result = await api.search.discover(
        payload,
        AbortSignal.any([activeController.signal, AbortSignal.timeout(45_000)]),
      );
      if (!activeController.signal.aborted) setResponse(result);
    } catch (failure) {
      if (!activeController.signal.aborted) {
        setError(failure instanceof ApiError ? failure.message
          : "We could not reach the movie catalog. Please try again.");
      }
    } finally {
      if (!activeController.signal.aborted) setLoading(false);
      controller.current = null;
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) {
      inputRef.current?.focus();
      return;
    }
    void search({
      query: query.trim(), limit: 12,
      filters: {
        genres: genre ? [genre] : [],
        max_runtime: maxRuntime ? Number(maxRuntime) : null,
      },
    });
  }

  return (
    <div className="w-full max-w-full overflow-x-clip">
      <section className="cinema-hero relative isolate flex min-h-[690px] items-center overflow-hidden border-b cinema-rule py-20 sm:min-h-[740px] sm:py-28" aria-labelledby="discover-title">
        <div className="cinema-shell relative z-10">
          <p className="cinema-eyebrow">For the film you need tonight</p>
          <h1 id="discover-title" className="cinema-display mt-6 max-w-5xl text-[clamp(3.5rem,7vw,7.5rem)]">
            Describe the <RotatingText texts={HEADLINE_WORDS} />.
          </h1>
          <p className="mt-7 max-w-lg text-base leading-relaxed text-foreground/75 sm:text-lg">
            Find your next film by title, genre, theme, or a movie you loved. Every pick comes with its reasons.
          </p>

          <Card className="cinema-surface mt-12 max-w-3xl rounded-[1.5rem] shadow-[0_28px_80px_rgba(0,0,0,.5)]">
            <CardContent className="p-5 sm:p-7">
              <form onSubmit={submit} aria-label="Find movies">
                <label htmlFor="movie-request" className="text-sm font-medium">What would you like to watch?</label>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <Input id="movie-request" ref={inputRef} value={query}
                    onChange={(event) => setQuery(event.target.value)} maxLength={1000}
                    placeholder="Try a title, a theme, or 'like Interstellar'..."
                    aria-describedby="search-help" disabled={loading} required />
                  <Button type="submit" disabled={loading || !query.trim()} className="h-11 shrink-0 px-6">
                    {loading ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                      : <Search className="size-4" aria-hidden="true" />}
                    {loading ? "Finding movies…" : "Find movies"}
                  </Button>
                </div>
                <div className="mt-5 grid grid-cols-2 gap-3 border-t cinema-rule pt-5">
                  <label className="text-xs text-muted-foreground">Genre
                    <select value={genre} onChange={(event) => setGenre(event.target.value)}
                      className={SELECT_STYLE} disabled={loading}>
                      <option value="">Any genre</option>
                      {GENRES.map((value) => <option key={value}>{value}</option>)}
                    </select>
                  </label>
                  <label className="text-xs text-muted-foreground">Maximum runtime
                    <select value={maxRuntime} onChange={(event) => setMaxRuntime(event.target.value)}
                      className={SELECT_STYLE} disabled={loading}>
                      <option value="">Any length</option>
                      <option value="90">90 minutes</option>
                      <option value="120">2 hours</option>
                      <option value="150">2½ hours</option>
                      <option value="180">3 hours</option>
                    </select>
                  </label>
                </div>
                <div className="mt-4 flex flex-wrap gap-2" aria-label="Search suggestions">
                  {SUGGESTIONS.map((suggestion) => (
                    <button key={suggestion} type="button" disabled={loading}
                      onClick={() => { setQuery(suggestion); inputRef.current?.focus(); }}
                      className="rounded-full border border-border px-3 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:border-primary/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
                      {suggestion}
                    </button>
                  ))}
                </div>
                <p id="search-help" className="mt-5 text-xs leading-relaxed text-muted-foreground">
                  Search the movie catalog by title or meaning. Try constraints like &quot;no horror&quot; and &quot;under two hours&quot;.
                </p>
              </form>
            </CardContent>
          </Card>
        </div>
      </section>

      <div role="status" aria-live="polite" className="cinema-shell">
        {loading && <p className="mt-8 text-sm text-muted-foreground">Searching the movie catalog…</p>}
      </div>
      {error && (
        <div role="alert" className="cinema-shell mt-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-500/30 bg-rose-500/5 p-4">
          <p className="text-sm text-rose-300">{error}</p>
          <Button variant="outline" size="sm" onClick={() => { if (lastRequest.current) void search(lastRequest.current); }}>Try again</Button>
        </div>
      )}
      {response && (
        <section className="cinema-shell py-20 md:py-28" aria-label="Movie search results">
          <div className="mb-8" role="status" aria-live="polite">
            <h2 className="cinema-display text-3xl sm:text-4xl">
              {response.results.length ? `${response.results.length} movies to explore` : "No matches this time"}
            </h2>
            <p className="mt-3 break-words text-sm text-muted-foreground">For “{response.query}”</p>
          </div>
          {response.results.length === 0 ? (
            <Card className="cinema-surface"><CardContent className="py-10 text-center">
              <p className="text-muted-foreground">Try a specific title, a broader theme, or fewer filters.</p>
              <p className="mt-2 text-sm text-muted-foreground">Some titles may not be available. Try another title or clear the filters.</p>
              <Button variant="outline" className="mt-4" onClick={() => {
                setGenre(""); setMaxRuntime(""); inputRef.current?.focus();
              }}>Adjust search</Button>
            </CardContent></Card>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {response.results.map(({ movie, explanation, matched_terms }) => (
                <article key={movie.id} className="flex min-w-0 flex-col">
                  <MovieCard title={movie.title} year={movie.release_year} rating={movie.vote_average}
                    runtime={movie.runtime} overview={movie.overview}
                    posterUrl={movie.poster_path ? `https://image.tmdb.org/t/p/w500${movie.poster_path}` : null}
                    explanation={explanation}
                    matched={matched_terms.length ? [{ label: "Matching metadata", kind: "theme", items: matched_terms }] : []}
                    className="w-full flex-1" />
                  <Link href={`/movie/${movie.id}`} className="mt-3 w-fit rounded text-sm text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    Explore {movie.title} →
                  </Link>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      <DiscoverChapters />
      <section className="cinema-shell border-t cinema-rule py-24 md:py-36" aria-labelledby="closing-title">
        <p className="cinema-eyebrow">The next good film starts here</p>
        <div className="mt-5 flex flex-col justify-between gap-8 md:flex-row md:items-end">
          <h2 id="closing-title" className="cinema-display max-w-4xl text-4xl sm:text-5xl md:text-6xl">A story worth your evening is waiting.</h2>
          <Link href="/chat" className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-6 font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Explore with chat <ArrowRight className="size-4" /></Link>
        </div>
      </section>
    </div>
  );
}

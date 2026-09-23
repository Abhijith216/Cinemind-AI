import { RecommendationGraphView } from "@/components/recommendation-graph-view";
import { api, type MovieOut, type RecommendationGraph } from "@/lib/api";

interface MoviePageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ user?: string }>;
}

export default async function MoviePage({ params, searchParams }: MoviePageProps) {
  const { id } = await params;
  const { user } = await searchParams;

  let movie: MovieOut | null = null;
  let graph: RecommendationGraph | null = null;
  let error: string | null = null;
  try {
    movie = await api.movies.get(id);
    graph = await api.movies.recommendationGraph(id, user ?? null);
  } catch {
    error = "Could not load this movie. Is the backend running?";
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8">
      {error && <p className="text-sm text-rose-400">{error}</p>}

      {movie && (
        <>
          <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">{movie.title}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {[movie.release_year, movie.runtime ? `${movie.runtime} min` : null]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {movie.overview && (
                <p className="mt-3 max-w-2xl text-sm leading-relaxed text-foreground/80">
                  {movie.overview}
                </p>
              )}
            </div>
            {typeof movie.vote_average === "number" && (
              <span className="w-fit rounded-full border border-amber-500/40 px-3 py-1 text-sm text-amber-300">
                ★ {movie.vote_average.toFixed(1)}
              </span>
            )}
          </header>

          <section aria-label="Why this recommendation">
            <h2 className="mb-1 text-sm font-medium tracking-wide text-muted-foreground uppercase">
              Why this — grounded in your ratings
            </h2>
            <p className="mb-4 text-xs text-muted-foreground">
              Edges show the genres and themes this movie actually shares with
              the movies you rated highest.
            </p>
            {graph && <RecommendationGraphView graph={graph} />}
          </section>
        </>
      )}
    </div>
  );
}

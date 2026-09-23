import { MovieCard, type MatchedAttributeGroup } from "@/components/movie-card";

export type { MatchedAttributeGroup };

export interface MovieCardData {
  movieId: string;
  title: string;
  year?: number | null;
  rating?: number | null;
  posterUrl?: string | null;
  explanation?: string | null;
  matched?: MatchedAttributeGroup[];
}

/**
 * Horizontal scroll strip of recommendations — rendered directly under an
 * assistant message that carried search results.
 */
export function MovieCardRow({ movies }: { movies: MovieCardData[] }) {
  if (movies.length === 0) return null;
  return (
    <div
      className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2"
      role="list"
      aria-label="Recommended movies"
    >
      {movies.map((movie) => (
        <div key={movie.movieId} role="listitem" className="shrink-0">
          <MovieCard {...movie} />
        </div>
      ))}
    </div>
  );
}

import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Clock3, Star } from "lucide-react";

import { MoviePersonalization } from "@/components/movie-personalization";
import { MoviePoster } from "@/components/movie-poster";
import { api, ApiError, type MovieOut } from "@/lib/api";

interface MoviePageProps {
  params: Promise<{ id: string }>;
}

export default async function MoviePage({ params }: MoviePageProps) {
  const { id } = await params;
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id)) {
    notFound();
  }
  let movie: MovieOut;
  try {
    movie = await api.movies.get(id);
  } catch (failure) {
    if (failure instanceof ApiError && [404, 422].includes(failure.status)) notFound();
    throw new Error("Movie details are temporarily unavailable. Please try again.");
  }

  return (
    <div className="cinema-shell max-w-6xl py-10 sm:py-16">
      <Link href="/" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden="true" /> Back to Discover
      </Link>
          <header className="mt-8 grid items-center gap-10 border-b cinema-rule pb-16 md:grid-cols-[minmax(0,360px)_1fr] md:gap-16">
            <MoviePoster title={movie.title} posterUrl={movie.poster_path ? `https://image.tmdb.org/t/p/w500${movie.poster_path}` : null} eager className="aspect-[2/3] w-full max-w-sm rounded-[1.5rem] border border-border shadow-[0_30px_80px_rgba(0,0,0,.35)]" />
            <div>
              <p className="cinema-eyebrow">The film</p>
              <h1 className="cinema-display mt-5 max-w-4xl text-5xl sm:text-6xl lg:text-7xl">{movie.title}</h1>
              <div className="mt-7 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
                {movie.release_year && <span>{movie.release_year}</span>}
                {movie.runtime && <span className="inline-flex items-center gap-1.5"><Clock3 className="size-4" aria-hidden="true" />{movie.runtime} min</span>}
                {typeof movie.vote_average === "number" && <span className="inline-flex items-center gap-1.5 text-primary"><Star className="size-4" aria-hidden="true" />{movie.vote_average.toFixed(1)}</span>}
              </div>
              {movie.genres.length > 0 && <div className="mt-6 flex flex-wrap gap-2">{movie.genres.map((genre) => <span key={genre} className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">{genre}</span>)}</div>}
              {movie.overview && <p className="mt-9 max-w-2xl text-base leading-relaxed text-foreground/80">{movie.overview}</p>}
            </div>
          </header>
          <div className="py-16"><MoviePersonalization movieId={movie.id} /></div>
    </div>
  );
}

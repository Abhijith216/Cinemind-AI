import Link from "next/link";
import { Film } from "lucide-react";

export default function MovieNotFound() {
  return (
    <div className="cinema-shell flex min-h-[calc(100dvh-11rem)] items-center justify-center py-16">
      <section className="cinema-surface w-full max-w-xl rounded-[1.5rem] p-8 text-center sm:p-12">
        <Film className="mx-auto mb-4 size-8 text-primary" aria-hidden="true" />
        <h1 className="cinema-display text-3xl sm:text-4xl">Movie not found</h1>
        <p className="mt-4 text-sm leading-relaxed text-muted-foreground">This movie link is invalid or the film is no longer in the catalog. Search for another title in Discover.</p>
        <Link href="/" className="mt-6 inline-flex h-11 items-center justify-center rounded-xl bg-primary px-5 text-sm font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Back to Discover</Link>
      </section>
    </div>
  );
}

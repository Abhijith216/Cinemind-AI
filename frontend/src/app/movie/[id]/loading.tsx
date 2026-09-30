export default function MovieLoading() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8">
      <div className="h-9 w-64 animate-pulse rounded-lg bg-secondary/50" />
      <div className="mt-3 h-4 w-40 animate-pulse rounded bg-secondary/30" />
      <div className="mt-4 h-20 w-full max-w-2xl animate-pulse rounded bg-secondary/30" />
      <div className="mt-10 h-4 w-72 animate-pulse rounded bg-secondary/30" />
      <div className="mt-6 h-72 w-full animate-pulse rounded-xl bg-secondary/20" />
    </div>
  );
}

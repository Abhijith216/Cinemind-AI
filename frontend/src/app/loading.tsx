export default function HomeLoading() {
  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-16">
      <div className="h-10 w-72 animate-pulse rounded-lg bg-secondary/50" />
      <div className="mt-4 h-5 w-96 animate-pulse rounded bg-secondary/30" />
      <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="h-24 animate-pulse rounded-xl bg-secondary/30" />
        <div className="h-24 animate-pulse rounded-xl bg-secondary/30" />
        <div className="h-24 animate-pulse rounded-xl bg-secondary/30" />
      </div>
    </div>
  );
}

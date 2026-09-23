import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default async function MovieDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-16">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        <ArrowLeft className="h-4 w-4" /> Back to Discover
      </Link>

      <h1 className="mt-6 text-3xl font-bold tracking-tight">Movie</h1>
      <p className="mt-2 text-muted-foreground">
        Detail, grounded explanation, and the &ldquo;why&rdquo; graph for one
        title.
      </p>

      <Card className="mt-8 border-dashed bg-card/50">
        <CardHeader>
          <CardTitle className="text-lg">Movie detail view lands here</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Route param:{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">{id}</code>
          </p>
          <p>
            Will render{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              api.movies.get()
            </code>{" "}
            with the personality radar (nine 0–100 traits) and{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              api.movies.recommendationGraph()
            </code>{" "}
            drawing movie ↔ shared attributes ↔ your rated movies.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

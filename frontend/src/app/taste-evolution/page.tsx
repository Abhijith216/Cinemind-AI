import { LineChart } from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function TasteEvolutionPage() {
  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-16">
      <Link
        href="/profile"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
      >
        ← My Taste
      </Link>

      <h1 className="mt-6 text-3xl font-bold tracking-tight">Taste evolution</h1>
      <p className="mt-2 text-muted-foreground">
        Your dominant genres and themes, month by month.
      </p>

      <Card className="mt-8 border-dashed bg-card/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <LineChart className="h-5 w-5 text-primary" />
            Evolution chart lands here
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Will render{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              api.users.tasteEvolution()
            </code>{" "}
            — the{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              TasteSnapshotOut[]
            </code>{" "}
            monthly rows from{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              taste_snapshots
            </code>{" "}
            — as a timeline of dominant genres/themes.
          </p>
          <p>
            Seed snapshots with{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              python -m app.services.taste_profile --user-id …
            </code>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

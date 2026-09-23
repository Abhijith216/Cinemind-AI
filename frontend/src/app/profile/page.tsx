import { Film } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function ProfilePage() {
  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-16">
      <h1 className="text-3xl font-bold tracking-tight">My Taste</h1>
      <p className="mt-2 text-muted-foreground">
        What your ratings say you love — and what to avoid.
      </p>

      <Card className="mt-8 border-dashed bg-card/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Film className="h-5 w-5 text-primary" />
            Taste profile view lands here
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Will render{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
              api.users.tasteProfile()
            </code>{" "}
            as like / dislike / theme chips:
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge>likes</Badge>
            <Badge variant="accent">favorite themes</Badge>
            <Badge variant="outline">dislikes</Badge>
          </div>
          <p>
            How your taste shifts over time? That&rsquo;s the{" "}
            <Link
              href="/taste-evolution"
              className="text-primary underline-offset-4 hover:underline"
            >
              taste evolution chart →
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import Link from "next/link";

import { MoviePoster } from "@/components/movie-poster";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * One attribute bucket of the structured "why" payload (Phase 7's
 * MatchedAttributes). `kind` drives the chip styling.
 */
export interface MatchedAttributeGroup {
  label: string;
  kind: "genre" | "theme" | "trait" | "loved" | "intent";
  items: string[];
}

export interface MovieCardProps {
  movieId?: string;
  title: string;
  year?: number | null;
  runtime?: number | null;
  overview?: string | null;
  rating?: number | null;
  posterUrl?: string | null;
  /** 1-3 sentence explanation (Phase 7) shown directly on the card. */
  explanation?: string | null;
  /** Structured matches behind the explanation, revealed by "Why this?". */
  matched?: MatchedAttributeGroup[];
  className?: string;
}

const KIND_STYLES: Record<MatchedAttributeGroup["kind"], string> = {
  genre: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  theme: "bg-violet-500/10 text-violet-300 ring-violet-500/30",
  trait: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  loved: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  intent: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
};

export function MovieCard({ movieId, title, year, runtime, overview, rating, posterUrl, explanation, matched, className }: MovieCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasMatches = (matched?.length ?? 0) > 0;

  return (
    <Card
      className={cn(
        "group flex w-72 shrink-0 flex-col gap-3 overflow-hidden rounded-[1.25rem] border-border/80 bg-card/95 transition-[border-color,transform,box-shadow] duration-300 hover:-translate-y-1 hover:border-primary/45 hover:shadow-[0_20px_50px_rgba(0,0,0,.28)]",
        explanation && "border-primary/25",
        className,
      )}
    >
      <CardContent className="flex flex-col gap-3 p-0">
        <MoviePoster title={title} posterUrl={posterUrl} className="cinema-card-image h-72 w-full" />

        <div className="px-5 pt-2">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-lg leading-tight font-semibold tracking-tight">
              {movieId ? <Link href={`/movie/${movieId}`} className="rounded hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{title}</Link> : title}
            </h3>
            {typeof rating === "number" && (
              <Badge variant="outline" className="shrink-0 border-amber-500/40 text-amber-300">
                ★ {rating.toFixed(1)}
              </Badge>
            )}
          </div>
          {(typeof year === "number" || typeof runtime === "number") && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {[year, runtime ? `${runtime} min` : null].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>

        {overview && <p className="line-clamp-3 px-5 text-sm leading-relaxed text-muted-foreground">{overview}</p>}

        {/* The key differentiator: the grounded explanation right on the card. */}
        {explanation ? (
          <p className="px-5 text-sm leading-relaxed text-foreground/85">{explanation}</p>
        ) : (
          <p className="px-5 text-sm text-muted-foreground italic">No explanation available yet.</p>
        )}

        {hasMatches && (
          <div className="mx-5 mb-5 border-t border-border/60 pt-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setExpanded((open) => !open)}
              aria-expanded={expanded}
              className="-ml-2 gap-1 text-xs text-amber-300 hover:text-amber-200"
            >
              {expanded ? "Hide why" : "Why this?"}
              <ChevronDown className={cn("size-4 transition-transform", expanded && "rotate-180")} />
            </Button>
            {expanded && (
              <div className="mt-2 flex flex-col gap-2 pb-1">
                {matched!.map((group) => (
                  <div key={group.label}>
                    <p className="mb-1 text-[10px] tracking-wider text-muted-foreground uppercase">
                      {group.label}
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {group.items.map((rawItem) => {
                        // Personality traits arrive as snake_case keys.
                        const item =
                          group.kind === "trait"
                            ? rawItem.replace(/_/g, " ")
                            : rawItem;
                        return (
                          <Badge
                            key={`${group.label}-${rawItem}`}
                            className={cn("font-normal", KIND_STYLES[group.kind])}
                          >
                            {item}
                          </Badge>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

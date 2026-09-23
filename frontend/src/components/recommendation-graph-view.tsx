"use client";

import { useMemo } from "react";
import Link from "next/link";

import type { RecommendationGraph } from "@/lib/api";

interface RecommendationGraphViewProps {
  graph: RecommendationGraph;
}

interface SeedNode {
  id: string;
  title: string;
  score: number | null;
  sharedGenres: string[];
  sharedKeywords: string[];
}

const TARGET_X = 430;
const SEED_X = 40;
const CANVAS_W = 640;
const NODE_H = 46;
const GAP = 18;
const TOP_Y = 60;

function seedNodes(graph: RecommendationGraph): SeedNode[] {
  const byId = new Map(graph.edges.map((edge) => [edge.to_movie_id, edge]));
  return graph.rated_movies.map((movie) => {
    const edge = byId.get(movie.id);
    return {
      id: movie.id,
      title: movie.title,
      score: movie.score,
      sharedGenres: edge?.shared_genres ?? [],
      sharedKeywords: edge?.shared_keywords ?? [],
    };
  });
}

/**
 * "Why you're seeing this" — the movie's own liked-movie graph rendered as a
 * node diagram: your highly-rated movies (left) connect to the recommended
 * movie (right) through the concrete genres/keywords they actually share.
 */
export function RecommendationGraphView({ graph }: RecommendationGraphViewProps) {
  const seeds = useMemo(() => seedNodes(graph), [graph]);
  const height = TOP_Y + seeds.length * (NODE_H + GAP) + 20;

  const seedPositions = seeds.map((seed, index) => ({
    ...seed,
    y: TOP_Y + index * (NODE_H + GAP),
  }));

  if (graph.note) {
    return (
      <p className="rounded-lg border border-dashed border-border/60 p-6 text-sm text-muted-foreground">
        {graph.note}
      </p>
    );
  }
  if (seeds.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <svg
        role="img"
        aria-label={`Why graph: ${graph.movie.title} connected to your rated movies`}
        viewBox={`0 0 ${CANVAS_W} ${height}`}
        className="h-auto w-full min-w-[560px]"
      >
        {/* Edges first so nodes render on top. */}
        {seedPositions.map((seed) => {
          const targetY = height / 2;
          const path = `M ${SEED_X + 170} ${seed.y + NODE_H / 2}
                        C ${SEED_X + 280} ${seed.y + NODE_H / 2},
                          ${TARGET_X - 110} ${targetY},
                          ${TARGET_X} ${targetY}`;
          return (
            <g key={seed.id}>
              <path
                d={path.replace(/\s+/g, " ")}
                fill="none"
                stroke="hsl(38 92% 55% / 0.35)"
                strokeWidth={1.5}
              />
              {(seed.sharedGenres.length > 0 || seed.sharedKeywords.length > 0) && (
                <text
                  x={(SEED_X + 170 + TARGET_X) / 2}
                  y={(seed.y + NODE_H / 2 + height / 2) / 2 - 6}
                  textAnchor="middle"
                  fontSize={10}
                  fill="hsl(40 20% 92% / 0.55)"
                >
                  {[
                    seed.sharedGenres.slice(0, 2).join(", "),
                    seed.sharedKeywords.slice(0, 2).join(", "),
                  ]
                    .filter((part) => part.length > 0)
                    .join(" · ")}
                </text>
              )}
            </g>
          );
        })}

        {/* Seed nodes: the user's highly-rated movies. */}
        {seedPositions.map((seed) => (
          <g key={seed.id}>
            <rect
              x={SEED_X}
              y={seed.y}
              width={170}
              height={NODE_H}
              rx={10}
              className="fill-card stroke-border"
            />
            <text x={SEED_X + 12} y={seed.y + 19} fontSize={12} className="fill-foreground">
              {seed.title.length > 22 ? `${seed.title.slice(0, 21)}…` : seed.title}
            </text>
            <text
              x={SEED_X + 12}
              y={seed.y + 35}
              fontSize={11}
              className="fill-amber-300"
            >
              {seed.score !== null ? `★ ${seed.score.toFixed(0)}/10 · your rating` : "rated"}
            </text>
          </g>
        ))}

        {/* Target node: the recommended movie. */}
        <g>
          <rect
            x={TARGET_X}
            y={height / 2 - 32}
            width={180}
            height={64}
            rx={12}
            className="fill-card stroke-amber-500/50"
            strokeWidth={1.5}
          />
          <text
            x={TARGET_X + 90}
            y={height / 2 - 10}
            textAnchor="middle"
            fontSize={13}
            className="fill-foreground font-semibold"
          >
            {graph.movie.title.length > 24
              ? `${graph.movie.title.slice(0, 23)}…`
              : graph.movie.title}
          </text>
          <text
            x={TARGET_X + 90}
            y={height / 2 + 10}
            textAnchor="middle"
            fontSize={11}
            className="fill-muted-foreground"
          >
            {graph.movie.release_year ?? ""}
          </text>
          <text
            x={TARGET_X + 90}
            y={height / 2 + 26}
            textAnchor="middle"
            fontSize={9}
            className="fill-amber-300/80 tracking-widest uppercase"
          >
            recommended
          </text>
        </g>

        {/* Column captions. */}
        <text x={SEED_X} y={30} fontSize={10} className="fill-muted-foreground tracking-widest uppercase">
          You loved
        </text>
        <text x={TARGET_X} y={30} fontSize={10} className="fill-muted-foreground tracking-widest uppercase">
          Why this
        </text>
      </svg>

      <div className="mt-3 flex flex-wrap gap-2">
        {graph.rated_movies.map((movie) => (
          <Link
            key={movie.id}
            href={`/movie/${movie.id}`}
            className="text-xs text-muted-foreground underline decoration-border underline-offset-2 hover:text-amber-300"
          >
            {movie.title}
          </Link>
        ))}
      </div>
    </div>
  );
}

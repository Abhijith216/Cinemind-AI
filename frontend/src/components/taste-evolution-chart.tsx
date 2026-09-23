"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TasteSnapshotOut } from "@/lib/api";

interface TasteEvolutionChartProps {
  snapshots: TasteSnapshotOut[];
}

interface ChartPoint {
  month: string;
  label: string;
  [tag: string]: number | string;
}

/** Tag rank (1-based) in a snapshot -> 0-100 "influence" value. */
function rankToInfluence(rank: number): number {
  return 100 - (rank - 1) * 20;
}

/** Amber-family shades for genre lines (order-stable). */
const GENRE_STROKES = [
  "hsl(38 92% 55%)",
  "hsl(45 90% 62%)",
  "hsl(28 85% 58%)",
  "hsl(52 80% 60%)",
  "hsl(20 80% 55%)",
];

/** Violet-family shades for theme lines (order-stable). */
const THEME_STROKES = [
  "hsl(265 85% 70%)",
  "hsl(280 80% 72%)",
  "hsl(250 85% 72%)",
  "hsl(290 75% 70%)",
  "hsl(240 80% 75%)",
];

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function monthLabel(month: string): string {
  const [year, mon] = month.split("-");
  const index = Number.parseInt(mon ?? "1", 10) - 1;
  return `${MONTH_NAMES[index] ?? mon ?? month} ${year}`;
}

function buildSeries(snapshots: TasteSnapshotOut[]): {
  points: ChartPoint[];
  genres: string[];
  themes: string[];
} {
  const genres: string[] = [];
  const themes: string[] = [];
  const points: ChartPoint[] = snapshots.map((snapshot) => {
    const point: ChartPoint = { month: snapshot.month, label: monthLabel(snapshot.month) };
    snapshot.dominant_genres.forEach((tag, index) => {
      if (!genres.includes(tag)) genres.push(tag);
      point[tag] = rankToInfluence(index + 1);
    });
    snapshot.dominant_themes.forEach((tag, index) => {
      if (!themes.includes(tag)) themes.push(tag);
      point[tag] = rankToInfluence(index + 1);
    });
    return point;
  });
  return { points, genres, themes };
}

export function TasteEvolutionChart({ snapshots }: TasteEvolutionChartProps) {
  const { points, genres, themes } = useMemo(() => buildSeries(snapshots), [snapshots]);

  if (snapshots.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border/60 p-10 text-center text-sm text-muted-foreground">
        No taste history yet — rate a few movies and run the monthly snapshot job.
      </div>
    );
  }

  const tooltipStyle = {
    backgroundColor: "hsl(240 9% 7%)",
    border: "1px solid hsl(40 20% 20%)",
    borderRadius: "8px",
    fontSize: "12px",
  } as const;

  return (
    <div className="flex flex-col gap-8">
      <section aria-label="Dominant genres over time">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-amber-300 uppercase">
          Dominant genres
        </h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="hsl(40 20% 92% / 0.06)" vertical={false} />
              <XAxis dataKey="label" stroke="hsl(40 20% 92% / 0.45)" fontSize={12} />
              <YAxis
                domain={[0, 100]}
                ticks={[100, 80, 60, 40, 20]}
                stroke="hsl(40 20% 92% / 0.45)"
                fontSize={12}
                tickFormatter={(value: number) =>
                  `#${Math.max(1, Math.round((100 - value) / 20) + 1)}`
                }
              />
              <Tooltip contentStyle={tooltipStyle} />
              {genres.map((tag, index) => (
                <Line
                  key={tag}
                  type="monotone"
                  dataKey={tag}
                  stroke={GENRE_STROKES[index % GENRE_STROKES.length]}
                  strokeWidth={2}
                  connectNulls
                  dot={{ r: 2.5 }}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                />
              ))}
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section aria-label="Dominant themes over time">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-violet-300 uppercase">
          Dominant themes
        </h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="hsl(40 20% 92% / 0.06)" vertical={false} />
              <XAxis dataKey="label" stroke="hsl(40 20% 92% / 0.45)" fontSize={12} />
              <YAxis
                domain={[0, 100]}
                ticks={[100, 80, 60, 40, 20]}
                stroke="hsl(40 20% 92% / 0.45)"
                fontSize={12}
                tickFormatter={(value: number) =>
                  `#${Math.max(1, Math.round((100 - value) / 20) + 1)}`
                }
              />
              <Tooltip contentStyle={tooltipStyle} />
              {themes.map((tag, index) => (
                <Line
                  key={tag}
                  type="monotone"
                  dataKey={tag}
                  stroke={THEME_STROKES[index % THEME_STROKES.length]}
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  connectNulls
                  dot={{ r: 2.5 }}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                />
              ))}
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}

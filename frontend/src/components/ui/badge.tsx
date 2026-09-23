import * as React from "react";

import { cn } from "@/lib/utils";

type Variant = "default" | "outline" | "accent";

const STYLES: Record<Variant, string> = {
  default: "border-transparent bg-primary/15 text-primary",
  outline: "border-border text-muted-foreground",
  accent: "border-transparent bg-accent text-accent-foreground",
};

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: Variant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
        STYLES[variant],
        className,
      )}
      {...props}
    />
  );
}

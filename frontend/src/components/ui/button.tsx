import * as React from "react";

import { cn } from "@/lib/utils";

type Variant = "default" | "secondary" | "ghost" | "outline";
type Size = "default" | "sm" | "lg" | "icon";

const VARIANTS: Record<Variant, string> = {
  default:
    "bg-primary text-primary-foreground shadow-[0_0_24px_hsl(var(--glow)/0.25)] hover:bg-primary/90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  ghost: "hover:bg-secondary/70 hover:text-foreground",
  outline:
    "border border-border bg-transparent hover:bg-secondary/60 hover:text-foreground",
};

const SIZES: Record<Size, string> = {
  default: "h-10 px-5 text-sm",
  sm: "h-8 rounded-md px-3 text-xs",
  lg: "h-12 rounded-xl px-7 text-base",
  icon: "h-9 w-9",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";

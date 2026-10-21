"use client";

import { AnimatePresence, motion, MotionConfig, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";

interface RotatingTextProps {
  texts: readonly string[];
  rotationInterval?: number;
  staggerDuration?: number;
  className?: string;
}

/** A small React Bits RotatingText integration for the Discover headline. */
export function RotatingText({
  texts,
  rotationInterval = 2800,
  staggerDuration = 0.025,
  className = "",
}: RotatingTextProps) {
  const [index, setIndex] = useState(0);
  const reduceMotion = useReducedMotion();
  const active = texts[index % texts.length] ?? "";
  const letters = useMemo(() => Array.from(active), [active]);

  useEffect(() => {
    if (reduceMotion || texts.length < 2) return;
    const timer = window.setTimeout(() => setIndex((value) => (value + 1) % texts.length), rotationInterval);
    return () => window.clearTimeout(timer);
  }, [index, reduceMotion, rotationInterval, texts.length]);

  return (
    <MotionConfig reducedMotion="user">
      <span className={`text-rotate text-primary ${className}`}>
        <span className="text-rotate-sr-only" aria-live="off">{active}</span>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={active} className="text-rotate-word" aria-hidden="true">
            {letters.map((letter, position) => (
              <motion.span
                key={`${active}-${position}`}
                className="text-rotate-element"
                initial={reduceMotion ? false : { y: "100%", opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={reduceMotion ? undefined : { y: "-110%", opacity: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 25, delay: position * staggerDuration }}
              >
                {letter === " " ? "\u00a0" : letter}
              </motion.span>
            ))}
          </motion.span>
        </AnimatePresence>
      </span>
    </MotionConfig>
  );
}

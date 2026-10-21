"use client";

import { useRef, useState } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { ArrowLeft, ArrowRight, MessageSquareText, SlidersHorizontal, Sparkles } from "lucide-react";
import Link from "next/link";

if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
  gsap.registerPlugin(useGSAP, ScrollTrigger);
}

const prompts = [
  { title: "Follow a feeling", text: "Something hopeful after a difficult week, with a little wonder." },
  { title: "Follow a favorite", text: "The emotional scale of Interstellar, but grounded on Earth." },
  { title: "Follow a constraint", text: "A clever mystery, no horror, and under two hours." },
];
const lanes = [
  { title: "A feeling", detail: "Start with the atmosphere you want to be in." },
  { title: "A favorite", detail: "Name a film you loved and follow what made it linger." },
  { title: "A boundary", detail: "Set the time, genre, or subject that matters tonight." },
];

export function DiscoverChapters() {
  const section = useRef<HTMLElement>(null);
  const pinned = useRef<HTMLDivElement>(null);
  const [activePrompt, setActivePrompt] = useState(0);
  const [activeLane, setActiveLane] = useState(0);
  const prompt = prompts[activePrompt]!;

  useGSAP(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = gsap.matchMedia();
    media.add("(min-width: 1024px) and (prefers-reduced-motion: no-preference)", () => {
      if (section.current && pinned.current) {
        ScrollTrigger.create({
          trigger: section.current,
          start: "top top+=120",
          end: "bottom bottom-=120",
          pin: pinned.current,
          pinSpacing: false,
        });
      }
      gsap.utils.toArray<HTMLElement>(".cinema-stack-card").forEach((card) => {
        gsap.fromTo(card, { y: 72, scale: 0.92, opacity: 0.35 }, {
          y: 0, scale: 1, opacity: 1, ease: "none",
          scrollTrigger: { trigger: card, start: "top 90%", end: "top 48%", scrub: true },
        });
      });
    });
    return () => media.revert();
  }, { scope: section });

  return (
    <div className="cinema-shell">
      <section className="py-24 md:py-36" aria-labelledby="way-heading">
        <div className="mb-10 flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <p className="cinema-eyebrow">A better way to choose</p>
            <h2 id="way-heading" className="cinema-display mt-4 max-w-4xl text-4xl sm:text-5xl md:text-6xl">Start anywhere. End with a film that fits.</h2>
          </div>
          <p className="max-w-xs text-sm leading-relaxed text-muted-foreground">A title, an atmosphere, or one small detail can be enough to begin.</p>
        </div>
        <div className="grid grid-flow-dense gap-3 md:grid-cols-2 md:grid-rows-2">
          <div className="group cinema-surface relative min-h-72 overflow-hidden rounded-[1.5rem] p-7 md:col-span-2 md:p-9">
            <div className="absolute inset-0 opacity-20 transition-transform duration-700 group-hover:scale-105" style={{ backgroundImage: "url('/cinema-hero.webp')", backgroundSize: "cover", backgroundPosition: "center 60%" }} aria-hidden="true" />
            <div className="absolute inset-0 bg-gradient-to-r from-background via-background/85 to-transparent" aria-hidden="true" />
            <div className="relative flex h-full flex-col justify-between">
              <SlidersHorizontal className="size-7 text-primary" aria-hidden="true" />
              <div><h3 className="max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">Find a film for <span className="inline-block h-8 w-20 rounded-full bg-cover bg-center align-middle sm:h-10 sm:w-28" style={{ backgroundImage: "url('/cinema-hero.webp')" }} aria-hidden="true" /> right now.</h3><p className="mt-3 max-w-lg text-sm leading-relaxed text-muted-foreground">Search by story, mood, title, genre, or runtime. Every result shows why it belongs in your shortlist.</p></div>
            </div>
          </div>
          <Link href="/chat" className="group cinema-surface flex min-h-64 flex-col justify-between overflow-hidden rounded-[1.5rem] p-7 transition-colors hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <MessageSquareText className="size-7 text-neon transition-transform duration-700 group-hover:scale-105" aria-hidden="true" />
            <div><h3 className="text-2xl font-semibold tracking-tight">Talk it through</h3><p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">Refine the feeling in conversation and uncover another angle.</p><span className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-primary">Open chat <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" /></span></div>
          </Link>
          <Link href="/profile" className="group cinema-surface flex min-h-64 flex-col justify-between overflow-hidden rounded-[1.5rem] p-7 transition-colors hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Sparkles className="size-7 text-primary transition-transform duration-700 group-hover:scale-105" aria-hidden="true" />
            <div><h3 className="text-2xl font-semibold tracking-tight">Keep your taste</h3><p className="mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">Rate what you watch and see the genres and themes that stay with you.</p><span className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-primary">See My Taste <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" /></span></div>
          </Link>
        </div>
      </section>

      <section className="border-t cinema-rule py-24 md:py-36" aria-labelledby="lanes-heading">
        <p className="cinema-eyebrow">Begin with one detail</p>
        <h2 id="lanes-heading" className="cinema-display mt-4 max-w-4xl text-4xl sm:text-5xl">The right film can start with almost anything.</h2>
        <div className="mt-10 flex flex-col gap-3 lg:h-80 lg:flex-row">
          {lanes.map((lane, index) => (
            <button key={lane.title} type="button" aria-expanded={activeLane === index}
              onMouseEnter={() => setActiveLane(index)} onFocus={() => setActiveLane(index)} onClick={() => setActiveLane(index)}
              className={`group relative flex min-h-48 flex-col justify-end overflow-hidden rounded-[1.25rem] border p-7 text-left transition-[flex,border-color] duration-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:min-h-0 ${activeLane === index ? "border-primary/50 lg:flex-[2.2]" : "border-border lg:flex-1"}`}>
              <span className="absolute inset-0 bg-cover bg-center opacity-25 transition-transform duration-700 group-hover:scale-105" style={{ backgroundImage: "url('/cinema-hero.webp')", backgroundPosition: `${30 + index * 25}% center` }} aria-hidden="true" />
              <span className="absolute inset-0 bg-gradient-to-t from-background via-background/55 to-transparent" aria-hidden="true" />
              <span className="relative text-2xl font-semibold tracking-tight">{lane.title}</span>
              <span className="relative mt-2 max-w-xs text-sm leading-relaxed text-foreground/70">{lane.detail}</span>
            </button>
          ))}
        </div>
      </section>

      <section ref={section} className="grid gap-12 border-t cinema-rule py-24 md:py-36 lg:grid-cols-[.8fr_1.2fr] lg:gap-20" aria-labelledby="steps-heading">
        <div className="self-start lg:h-full">
          <div ref={pinned}>
            <p className="cinema-eyebrow">From thought to watchlist</p>
            <h2 id="steps-heading" className="cinema-display mt-4 max-w-xl text-4xl sm:text-5xl md:text-6xl">A search that understands the details.</h2>
            <p className="mt-6 max-w-sm text-muted-foreground">Give CineMind a little context. It brings back films from the catalog with a reason for each choice.</p>
          </div>
        </div>
        <div className="space-y-8 lg:space-y-28">
          {[
            { title: "Say what stays with you", text: "Describe a scene, a pace, a genre, or the last movie you could not stop thinking about." },
            { title: "Shape the shortlist", text: "Add a runtime or genre, and rule out what you do not want tonight." },
            { title: "Know why it fits", text: "Each film comes with matching details so the choice feels yours." },
          ].map((step, index) => <div key={step.title} className="cinema-stack-card cinema-surface relative min-h-64 rounded-[1.5rem] p-8 lg:sticky lg:top-28 lg:min-h-72 lg:p-10" style={{ zIndex: index + 1 }}><span className="font-mono text-sm text-primary/80">0{index + 1}</span><h3 className="mt-12 text-2xl font-semibold tracking-tight sm:text-3xl">{step.title}</h3><p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">{step.text}</p></div>)}
        </div>
      </section>

      <section className="border-t cinema-rule py-24 md:py-36" aria-labelledby="prompt-heading">
        <div className="flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
          <div><p className="cinema-eyebrow">A little inspiration</p><h2 id="prompt-heading" className="cinema-display mt-4 max-w-3xl text-4xl sm:text-5xl">There is no perfect way to ask.</h2></div>
          <div className="flex gap-2"><button type="button" onClick={() => setActivePrompt((value) => (value + prompts.length - 1) % prompts.length)} aria-label="Previous example" className="grid size-11 place-items-center rounded-full border border-border text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="size-4" /></button><button type="button" onClick={() => setActivePrompt((value) => (value + 1) % prompts.length)} aria-label="Next example" className="grid size-11 place-items-center rounded-full border border-border text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowRight className="size-4" /></button></div>
        </div>
        <div className="mt-10 overflow-hidden rounded-[1.5rem] border border-border bg-[#191416] p-8 sm:p-12" aria-live="polite"><p className="cinema-eyebrow">{prompt.title}</p><p className="mt-8 max-w-4xl text-2xl leading-snug font-medium tracking-tight text-foreground sm:text-4xl">“{prompt.text}”</p><p className="mt-9 text-xs text-muted-foreground">Example {activePrompt + 1} of {prompts.length}</p></div>
      </section>
    </div>
  );
}

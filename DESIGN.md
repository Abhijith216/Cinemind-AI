# CineMind design system

CineMind feels like entering a screening room to find a film for the moment. The interface is editorial, quiet, and useful: the movie search and explanations lead; atmospheric art supports them.

## Foundations

- **Type:** Geist for interface and display. Large headings have tight tracking and a wide measure; body copy stays readable at 15–18 px. Avoid narrow, multi-line display text.
- **Color:** near-black ink `#0b0a0b`, warm ivory `#f5efe6`, amber `#f1ad55`, muted lavender `#b79acc`, and subdued charcoal surfaces. Amber identifies action; lavender is a sparse accent. Text and buttons must maintain strong contrast.
- **Surfaces:** large but restrained radii, fine warm borders, soft projector-like radial light, and a subtle grain layer. Cards have clear hierarchy without heavy glass effects.
- **Imagery:** use real TMDb posters for films and `/cinema-hero.webp` for the Discover hero. Never imply the generated hero is a real film still. Crop images decisively and keep text over a dark wash.
- **Spacing:** 24–32 px inside controls and cards; 96–160 px between major editorial sections on desktop. Compact only where a task requires it, such as chat and forms.

## Page architecture

- **Discover:** asymmetrical cinema hero, immediate search, results, a dense three-card explanation of the product, and a closing action. “Describe the …” rotates through meaningful discovery words. Search is always easier to find than decorative content.
- **Chat:** focused conversation canvas with the composer always available. The AI connection state, restore state, retries, and movie cards remain visible and actionable.
- **My Taste:** personal journal layout with a clear rating entry point, summary, preferences, recommendations, and history. Account-only data stays behind the existing server authorization.
- **Movie:** poster and title lead, followed by synopsis, rating, and personalized graph.
- **Account:** simple, legible sign-in and registration with clear mode and error states.

## Motion and interaction

- Use short masked transitions for rotating headline text and subtle card hover movement.
- Use GSAP scroll pinning and card stacking for the Discover editorial sections only on wide screens that do not request reduced motion.
- Under `prefers-reduced-motion: reduce`, show static end states, disable automatic text rotation and scroll effects, and use no smooth scrolling.
- Keyboard focus must be visible; hover must never be the only way to reveal important information. Live regions announce search, chat, and error changes.

## Component rules

- Keep the existing Lucide icon set consistently across the current app.
- Movie cards must give the film title, image or honest poster fallback, metadata, explanation, and direct detail access.
- Avoid decorative section numbering and empty bento cells. The Discover feature grid uses `grid-flow-dense`: a card spanning two columns plus two one-column cards fills two rows exactly.
- Button labels state the action. External service failures get honest, retryable messages.

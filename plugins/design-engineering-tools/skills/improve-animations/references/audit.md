# Animation audit bar

Check purpose and frequency, easing and duration, physical origin,
interruptibility, GPU-friendly properties, reduced motion, hover capability,
token cohesion, and missed opportunities. Flag `ease-in` on responsive UI,
durations over 300ms without rationale, `transition: all`, `scale(0)`, layout
property animation, trigger-anchored overlays with center origin, and motion on
keyboard or very frequent actions. Distinguish evidence-backed defects from
subjective feel checks.

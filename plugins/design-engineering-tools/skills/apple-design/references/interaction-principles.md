# Interaction principles

Use Pointer Events and pointer capture for drags. Preserve grab offset and
recent velocity. Start a new interaction from the visible position, carrying
velocity where the motion library supports it. Prefer critically damped springs
for ordinary UI and add bounce only after momentum-bearing gestures.

Use `transform` and `opacity` for animation. Keep interfaces responsive during
transitions, make input reversible, and provide a reduced-motion alternative
that retains state clarity while removing travel or bounce.

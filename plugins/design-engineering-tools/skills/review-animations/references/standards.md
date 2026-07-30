# Review standards

Avoid motion for keyboard and 100+/day actions. Use responsive easing and keep
ordinary UI motion under 300ms unless context justifies otherwise. Triggered
popovers scale from their trigger; avoid `scale(0)`, `transition: all`, and
layout-property animation. Rapidly toggled and gesture-driven motion must
retarget smoothly. Honor `prefers-reduced-motion`, gate hover effects to fine
pointers, and use `transform` and `opacity` for common UI animation.

# app/styles

Global styles are split by responsibility and imported once in [`../layout.tsx`](../layout.tsx), in this order:

1. `tokens.css` — colors, surfaces, typography, shadows;
2. `base.css` — reset, body, selection policy, focus, base headings;
3. `layout.css` — app shell, header/footer, home, diagnosis and card page layout;
4. `components.css` — intake form, probe, progress, diagnosis card, side rail;
5. `responsive.css` — breakpoints and reduced-motion overrides.

Rules:

- Do not add `@import` between these files; keep the explicit import order in `layout.tsx`.
- Put a new shared component's visual rules in `components.css`; put its page placement in `layout.css`.
- If a page grows its own visual language, add a route-level CSS Module beside that page rather than expanding `layout.css`.
- ReactBits vendor CSS stays under `components/reactbits/` and is not edited here.
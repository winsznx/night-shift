/**
 * Sidebar icons, drawn from the operational vocabulary rather than a generic icon set.
 *
 * Inline SVG on purpose: seven 16px glyphs do not justify a dependency, and shipping
 * them as code keeps them on the same token system as everything else. Each one inherits
 * `currentColor`, so the active and hover states in the nav drive the icon too.
 */

type IconProps = { className?: string };

function Svg({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className ?? "h-4 w-4 shrink-0"}
      aria-hidden
    >
      {children}
    </svg>
  );
}

/** Overview: the estate at a glance, four zones. */
export function IconOverview(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </Svg>
  );
}

/** Incidents: something crossed a threshold. */
export function IconIncident(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 2.2 14.4 13H1.6L8 2.2Z" />
      <path d="M8 6.4v3" />
      <path d="M8 11.4h.01" />
    </Svg>
  );
}

/** Freezers: a temperature reading, which is the only thing a freezer really is here. */
export function IconFreezer(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M6.4 8.8V3.6a1.6 1.6 0 0 1 3.2 0v5.2a3 3 0 1 1-3.2 0Z" />
      <path d="M8 10.4v-4" />
    </Svg>
  );
}

/** Capacity: slots, filled and free. */
export function IconCapacity(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="2" y="2.5" width="12" height="11" rx="1.4" />
      <path d="M2 6.5h12" />
      <path d="M2 10h12" />
      <path d="M6 2.5v11" />
    </Svg>
  );
}

/** Fleet: a commander and the specialists it delegates to. */
export function IconFleet(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="3.4" r="1.7" />
      <circle cx="3.2" cy="12.4" r="1.7" />
      <circle cx="12.8" cy="12.4" r="1.7" />
      <path d="M8 5.1v3.1M8 8.2 4.2 11M8 8.2 11.8 11" />
    </Svg>
  );
}

/** Drills: a revision under test, passing or not. */
export function IconDrills(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 1.8 13.4 4v4.1c0 3-2.3 5.2-5.4 6.1-3.1-.9-5.4-3.1-5.4-6.1V4L8 1.8Z" />
      <path d="M5.9 7.9 7.4 9.4l2.9-3" />
    </Svg>
  );
}

/** Evidence: a sealed document. */
export function IconEvidence(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3.4 2.2h6l3.2 3.2v8.4H3.4V2.2Z" />
      <path d="M9.2 2.2v3.4h3.4" />
      <circle cx="8" cy="10.2" r="1.9" />
    </Svg>
  );
}

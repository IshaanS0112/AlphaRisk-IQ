import type { ReactNode } from "react";

export function Panel({
  title,
  subtitle,
  right,
  children,
}: {
  title?: string;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel p-5">
      {(title || right) && (
        <header className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title && (
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-1 text-xs text-muted">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const colour = {
    neutral: "text-slate-100",
    good: "text-good",
    warn: "text-warn",
    bad: "text-bad",
  }[tone];
  return (
    <div className="rounded-md border border-edge bg-ink p-3">
      <div className="label">{label}</div>
      <div className={`stat text-xl ${colour}`}>{value}</div>
      {hint && <div className="mt-1 text-[11px] leading-snug text-muted">{hint}</div>}
    </div>
  );
}

export function Chip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "accent";
}) {
  const classes = {
    neutral: "border-edge text-muted",
    good: "border-good/40 text-good",
    warn: "border-warn/40 text-warn",
    bad: "border-bad/40 text-bad",
    accent: "border-accent/40 text-accent",
  }[tone];
  return <span className={`chip ${classes}`}>{children}</span>;
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 border-l-2 border-edge pl-3 text-xs leading-relaxed text-muted">
      {children}
    </p>
  );
}

/** The provenance banner. Deliberately impossible to miss. */
export function ProvenanceBanner({ provenance }: { provenance?: string }) {
  if (!provenance || provenance === "REAL_MARKET_DATA") return null;
  return (
    <div className="rounded-md border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn">
      <strong className="font-semibold">Synthetic price data.</strong> These figures
      demonstrate the calculations and say nothing about any real asset. Run{" "}
      <code className="font-mono text-xs">backend/scripts/fetch_prices.py</code> to load
      real market data, then recompute.
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">
      {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

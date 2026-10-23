interface AuthCardProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}

/** Centered card used by the login and register pages. */
export function AuthCard({ title, subtitle, children, footer }: AuthCardProps) {
  return (
    <main className="relative overflow-hidden px-4 py-8 sm:py-20">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-[380px] max-w-2xl rounded-full bg-gradient-to-r from-accent/25 via-cyan/15 to-accent/25 blur-3xl"
      />
      <div className="relative mx-auto max-w-md">
        <h1 className="text-center text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-2 text-center text-muted">{subtitle}</p>}
        <div className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:mt-8 sm:p-8">{children}</div>
        <p className="mt-6 text-center text-sm text-muted">{footer}</p>
      </div>
    </main>
  );
}

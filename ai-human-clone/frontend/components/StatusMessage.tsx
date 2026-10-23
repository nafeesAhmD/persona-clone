interface StatusMessageProps {
  title: string;
  body?: string;
  children?: React.ReactNode;
}

/** Centered placeholder for loading, empty and error states. */
export function StatusMessage({ title, body, children }: StatusMessageProps) {
  return (
    <div role="status" className="mx-auto max-w-md px-4 py-16 text-center sm:py-24">
      <h1 className="text-lg font-semibold">{title}</h1>
      {body && <p className="mt-2 text-sm text-muted">{body}</p>}
      {children && <div className="mt-4 text-sm">{children}</div>}
    </div>
  );
}

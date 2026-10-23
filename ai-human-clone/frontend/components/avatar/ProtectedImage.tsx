"use client";

import { useEffect, useState } from "react";

import { loadMedia } from "@/lib/api";

interface ProtectedImageProps {
  src: string;
  alt: string;
  className?: string;
  onClick?: (event: React.MouseEvent<HTMLImageElement>) => void;
}

/** An image served only with the session cookie (e.g. an avatar), shown via an object URL. */
export function ProtectedImage({ src, alt, className, onClick }: ProtectedImageProps) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    loadMedia(src)
      .then((loaded) => {
        if (cancelled) return URL.revokeObjectURL(loaded);
        objectUrl = loaded;
        setUrl(loaded);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);

  if (!url) return <div className={className} aria-label={alt} role="img" />;
  // eslint-disable-next-line @next/next/no-img-element -- a local object URL
  return <img src={url} alt={alt} className={className} onClick={onClick} />;
}

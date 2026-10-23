"use client";

import { useEffect, useRef } from "react";

import { fillHeight } from "@/lib/chatState";

/**
 * Sizes an element to fill the screen from where it starts down to the bottom of the
 * *visible* viewport. CSS (100dvh + interactive-widget=resizes-content) already handles
 * Android; iOS Safari ignores interactive-widget and only shrinks the visual viewport when
 * the keyboard opens, so this follows window.visualViewport to keep a bottom composer
 * above the keyboard. Give the element a CSS height (e.g. h-[calc(100dvh-4rem)]) as the
 * first-paint fallback.
 */
export function useViewportFill<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const viewport = window.visualViewport;
    let frame = 0;

    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const top = element.getBoundingClientRect().top + window.scrollY;
        const next = `${fillHeight(window.innerHeight, viewport?.height ?? null, top)}px`;
        if (element.style.height !== next) element.style.height = next;
        // iOS may have scrolled the page to reveal the focused input; the panel now fits, so undo it.
        if (viewport && viewport.height < window.innerHeight && window.scrollY > 0) window.scrollTo(0, 0);
      });
    };

    update();
    viewport?.addEventListener("resize", update);
    window.addEventListener("resize", update);
    window.addEventListener("orientationchange", update);
    // Bars above the element (banner, top bar) can change height.
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    if (element.parentElement) observer?.observe(element.parentElement);

    return () => {
      cancelAnimationFrame(frame);
      viewport?.removeEventListener("resize", update);
      window.removeEventListener("resize", update);
      window.removeEventListener("orientationchange", update);
      observer?.disconnect();
      element.style.height = "";
    };
  }, []);

  return ref;
}

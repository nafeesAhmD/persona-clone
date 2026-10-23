import type { Metadata } from "next";
import { Fragment } from "react";

import { ApiStatus } from "@/components/ApiStatus";
import { RobotMascot } from "@/components/RobotMascot";

export const metadata: Metadata = {
  title: "AI Human Clone — Chat with your expert, instantly",
  description:
    "AI Human Clone is an always-available stand-in that answers like the real person, trained on their knowledge — and hands you to them when needed.",
};

const STEPS = [
  { title: "Create your profile", body: "Add your name, profession, skills, language and how you like to communicate." },
  { title: "Upload your knowledge", body: "Share notes, documents and projects you want your clone to draw on." },
  { title: "AI learns your information", body: "Your content is indexed so the clone can find relevant facts when it answers." },
  { title: "Talk with your digital clone", body: "Visitors chat with an AI clearly labelled as your clone, not you." },
];

const STATS = [
  {
    value: "10K+",
    label: "Questions Answered",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-4 w-4"
        aria-hidden
      >
        <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
      </svg>
    ),
  },
  {
    value: "1",
    label: "Expert",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-4 w-4"
        aria-hidden
      >
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="m17 11 2 2 4-4" />
      </svg>
    ),
  },
  {
    value: "<1s",
    label: "Instant Replies",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-4 w-4"
        aria-hidden
      >
        <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
  },
];

const PARTNERS = ["Bright Academy", "City Pharmacy", "AutoCare Garage", "Mentorly", "Nova Labs"];

function HeroIllustration() {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-md lg:max-w-lg" aria-hidden>
      {/* soft glow */}
      <div className="absolute inset-10 rounded-full bg-accent/30 blur-3xl" />

      {/* decorative dotted ring */}
      <svg
        viewBox="0 0 400 400"
        className="absolute inset-0 h-full w-full animate-spin [animation-duration:55s] opacity-80"
      >
        <circle
          cx="200"
          cy="200"
          r="186"
          fill="none"
          stroke="var(--color-border)"
          strokeWidth="3"
          strokeDasharray="1 16"
          strokeLinecap="round"
        />
      </svg>

      {/* orbit ring with satellite dot */}
      <div className="absolute inset-9 animate-spin [animation-duration:24s]">
        <div className="relative h-full w-full rounded-full border border-accent/35">
          <span className="absolute -top-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full bg-accent shadow-[0_0_16px_4px_rgba(255,107,53,0.45)]" />
          <span className="absolute -right-1 top-2/3 h-2 w-2 rounded-full bg-accent-soft/80" />
        </div>
      </div>

      {/* main floating illustration: robot mascot that looks at the cursor */}
      <RobotMascot className="absolute inset-0" />

      {/* floating mini chat bubble */}
      <div
        className="absolute bottom-6 left-0 animate-float rounded-2xl border border-border bg-surface-raised p-3 shadow-xl"
        style={{ animationDelay: "1.6s" }}
      >
        <div className="flex gap-1.5">
          <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
          <span
            className="h-2 w-2 animate-pulse rounded-full bg-accent/70"
            style={{ animationDelay: "0.2s" }}
          />
          <span
            className="h-2 w-2 animate-pulse rounded-full bg-accent/40"
            style={{ animationDelay: "0.4s" }}
          />
        </div>
      </div>

      {/* floating AI pill */}
      <div
        className="absolute bottom-12 right-0 flex animate-float items-center gap-1.5 rounded-full border border-border bg-surface-raised px-3 py-1.5 text-xs font-semibold text-accent-soft shadow-xl"
        style={{ animationDelay: "0.8s" }}
      >
        <svg viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
          <path d="M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4L12 2z" />
        </svg>
        AI stand-in
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <main>
      {/* ============ HERO ============ */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-40 left-1/2 h-[440px] w-[860px] -translate-x-1/2 rounded-full bg-accent/20 blur-3xl"
        />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pb-24 pt-14 sm:px-6 lg:grid-cols-2 lg:gap-8 lg:pt-24">
          {/* left side */}
          <div>
            <h1 className="text-4xl font-bold leading-[1.08] tracking-tight sm:text-5xl lg:text-6xl">
              Chat with <span className="text-accent">AI Human Clone</span>
            </h1>
            <p className="mt-4 text-lg font-semibold text-accent sm:text-xl">
              Real expertise, instant answers.
            </p>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted sm:text-base">
              AI Human Clone is an always-available stand-in that answers the way the real person
              would — trained on their knowledge, projects and writing style — and connects you to
              them whenever you need.
            </p>

            {/* search bar */}
            <form
              action="/clone/demo"
              method="get"
              className="mt-8 flex w-full max-w-lg items-center gap-2 rounded-full border border-border bg-surface-raised p-1.5 pl-5 shadow-[0_8px_30px_rgba(0,0,0,0.35)] focus-within:border-accent"
            >
              <label htmlFor="ask" className="sr-only">
                Ask AI Human Clone anything
              </label>
              <input
                id="ask"
                name="q"
                placeholder="Ask AI Human Clone anything..."
                autoComplete="off"
                className="min-w-0 flex-1 bg-transparent text-sm outline-none! placeholder:text-muted"
              />
              <button
                type="submit"
                className="rounded-full bg-accent px-6 py-2.5 text-sm font-semibold text-ink transition hover:bg-accent/90"
              >
                Search
              </button>
            </form>

            {/* stat cards */}
            <div className="mt-8 grid max-w-lg grid-cols-3 gap-3 sm:gap-4">
              {STATS.map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-2xl border border-border bg-surface-raised/70 p-3 backdrop-blur sm:p-4"
                >
                  <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/15 text-accent sm:h-9 sm:w-9">
                    {stat.icon}
                  </span>
                  <p className="mt-3 text-xl font-bold tracking-tight sm:text-2xl">{stat.value}</p>
                  <p className="mt-0.5 text-[11px] leading-tight text-muted sm:text-xs">
                    {stat.label}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* right side */}
          <HeroIllustration />
        </div>
      </section>

      {/* ============ PARTNER LOGO STRIP ============ */}
      <div className="relative bg-strip pb-24 pt-10">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-4 gap-y-3 px-4 text-sm sm:px-6">
          {PARTNERS.map((name, index) => (
            <Fragment key={name}>
              {index > 0 && (
                <span aria-hidden className="h-1 w-1 rounded-full bg-muted/40" />
              )}
              <span className="flex items-center gap-2 font-medium text-muted">
                <span
                  aria-hidden
                  className="grid h-6 w-6 place-items-center rounded-md bg-accent/15 text-[10px] font-bold text-accent-soft"
                >
                  {name.charAt(0)}
                </span>
                {name}
              </span>
            </Fragment>
          ))}
        </div>

        {/* wave dividing this strip from the section below */}
        <svg
          aria-hidden
          viewBox="0 0 1440 56"
          preserveAspectRatio="none"
          className="absolute inset-x-0 bottom-0 h-14 w-full"
        >
          <path
            d="M0 24 C 240 56, 480 0, 720 16 C 960 32, 1200 56, 1440 24 L 1440 56 L 0 56 Z"
            fill="var(--color-surface)"
          />
        </svg>
      </div>

      {/* ============ FEATURES ============ */}
      <section id="features" className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <p className="text-center text-xs font-semibold uppercase tracking-[0.2em] text-accent">
          How it works
        </p>
        <h2 className="mt-3 text-center text-2xl font-bold tracking-tight sm:text-3xl">
          Your expert, always available
        </h2>
        <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, index) => (
            <li
              key={step.title}
              className="rounded-2xl border border-border bg-surface-raised p-6 transition hover:border-accent/40"
            >
              <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent/15 font-semibold text-accent-soft">
                {index + 1}
              </span>
              <h3 className="mt-4 font-semibold">{step.title}</h3>
              <p className="mt-2 text-sm text-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* ============ FOOTER ============ */}
      <footer id="about" className="border-t border-border py-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 text-xs text-muted sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold text-white">
              AI Human Clone — a consent-based AI stand-in
            </p>
            <p className="mt-1.5 leading-relaxed">
              Answers are AI-generated from information the owner shared. It is not the real person
              and won&apos;t know anything it wasn&apos;t taught — complex or urgent matters are
              handed over to the human directly. Only create a clone of yourself, with consent.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-4">
            <span>Clone Me · Phase 0 preview</span>
            <ApiStatus />
          </div>
        </div>
      </footer>
    </main>
  );
}

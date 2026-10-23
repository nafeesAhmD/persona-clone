"use client";

import { type KeyboardEvent, useState } from "react";

import { inputClass } from "@/components/FormField";

const MAX_SKILLS = 30;
const MAX_SKILL_LENGTH = 50;

interface SkillsInputProps {
  id: string;
  skills: string[];
  onChange: (skills: string[]) => void;
}

/** Type a skill and press Enter (or comma) to add it; click × to remove. */
export function SkillsInput({ id, skills, onChange }: SkillsInputProps) {
  const [draft, setDraft] = useState("");
  const [hint, setHint] = useState<string | null>(null);

  function add(raw: string) {
    const skill = raw.replace(/,/g, " ").split(/\s+/).filter(Boolean).join(" ");
    setDraft("");
    if (!skill) return;
    if (skill.length > MAX_SKILL_LENGTH) return setHint(`Skills can be at most ${MAX_SKILL_LENGTH} characters.`);
    if (skills.some((s) => s.toLowerCase() === skill.toLowerCase())) return setHint(`"${skill}" is already added.`);
    if (skills.length >= MAX_SKILLS) return setHint(`You can add up to ${MAX_SKILLS} skills.`);
    setHint(null);
    onChange([...skills, skill]);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add(draft);
    } else if (event.key === "Backspace" && !draft && skills.length > 0) {
      onChange(skills.slice(0, -1));
    }
  }

  return (
    <div>
      <div className="flex gap-2">
        <input
          id={id}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          autoComplete="off"
          enterKeyHint="enter"
          aria-label="Add a skill"
          aria-describedby={hint ? `${id}-hint` : undefined}
          placeholder="Type a skill and press Enter"
          className={inputClass}
        />
        <button
          type="button"
          onClick={() => add(draft)}
          className="min-h-11 shrink-0 rounded-xl border border-border px-4 text-sm hover:border-accent"
        >
          Add
        </button>
      </div>
      {hint && (
        <p id={`${id}-hint`} role="status" className="mt-1.5 text-sm text-amber-300">
          {hint}
        </p>
      )}
      {skills.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Added skills">
          {skills.map((skill) => (
            <li
              key={skill}
              className="flex items-center gap-1 rounded-full border border-accent/40 bg-accent/10 py-0.5 pl-3 pr-0.5 text-sm text-accent-soft"
            >
              {skill}
              <button
                type="button"
                onClick={() => onChange(skills.filter((s) => s !== skill))}
                aria-label={`Remove ${skill}`}
                className="-my-1 grid h-10 w-10 place-items-center rounded-full text-base sm:my-0 sm:h-8 sm:w-8 text-accent-soft/80 hover:bg-accent/20 hover:text-white"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

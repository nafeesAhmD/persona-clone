import { cn } from "@/lib/utils";

interface Choice<T extends string> {
  value: T;
  label: string;
  description?: string;
}

interface ChoiceGroupProps<T extends string> {
  name: string;
  label: string;
  choices: Choice<T>[];
  value: T | null;
  onChange: (value: T) => void;
  columns?: 2 | 3 | 5;
}

const COLUMN_CLASSES = { 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 5: "sm:grid-cols-3 lg:grid-cols-5" };

/** Radio buttons styled as selectable cards. */
export function ChoiceGroup<T extends string>({ name, label, choices, value, onChange, columns = 3 }: ChoiceGroupProps<T>) {
  return (
    <fieldset>
      <legend className="sr-only">{label}</legend>
      <div className={cn("grid grid-cols-1 gap-3", COLUMN_CLASSES[columns])}>
        {choices.map((choice) => {
          const selected = choice.value === value;
          return (
            <label
              key={choice.value}
              className={cn(
                // Focus ring only for keyboard users, not after a mouse click.
                "relative flex min-h-11 cursor-pointer flex-col justify-center rounded-xl border px-4 py-3 pr-9 transition has-[input:focus-visible]:ring-2 has-[input:focus-visible]:ring-accent/60",
                selected ? "border-accent bg-accent/10" : "border-border bg-surface hover:border-accent/50",
              )}
            >
              <input
                type="radio"
                name={name}
                value={choice.value}
                checked={selected}
                onChange={() => onChange(choice.value)}
                className="sr-only"
              />
              {/* A check mark too, so the selection doesn't rely on colour alone. */}
              {selected && (
                <span aria-hidden="true" className="absolute right-3 top-3 text-sm text-accent-soft">
                  ✓
                </span>
              )}
              <span className={cn("block text-sm font-medium", selected && "text-accent-soft")}>{choice.label}</span>
              {choice.description && <span className="mt-0.5 block text-xs text-muted">{choice.description}</span>}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

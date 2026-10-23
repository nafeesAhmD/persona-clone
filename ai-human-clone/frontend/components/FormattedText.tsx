import { Fragment } from "react";

interface FormattedTextProps {
  text: string;
}

const BOLD = /(\*\*[^*\n]+\*\*)/g;
const BULLET = /^(\s*)[*-]\s+/;

/**
 * Renders the small subset of Markdown models typically use in chat
 * (**bold** and "* " / "- " bullets) without injecting any HTML.
 */
export function FormattedText({ text }: FormattedTextProps) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, lineIndex) => {
        const content = line.replace(BULLET, "$1• ");
        return (
          <Fragment key={lineIndex}>
            {content.split(BOLD).map((part, partIndex) =>
              part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
                <strong key={partIndex} className="font-semibold text-white">
                  {part.slice(2, -2)}
                </strong>
              ) : (
                <Fragment key={partIndex}>{part}</Fragment>
              ),
            )}
            {lineIndex < lines.length - 1 && "\n"}
          </Fragment>
        );
      })}
    </>
  );
}

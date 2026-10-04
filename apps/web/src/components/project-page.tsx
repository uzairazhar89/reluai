import type { ReactNode } from "react";

/** The twelve sections every project page uses, in order (from the portfolio brief). */
export const PROJECT_SECTIONS = [
  ["problem", "Problem"],
  ["why", "Why it matters"],
  ["solution", "Solution"],
  ["architecture", "Architecture"],
  ["implementation", "Technical implementation"],
  ["demo", "Live demonstration"],
  ["results", "Results"],
  ["failure-handling", "Failure handling"],
  ["deployment", "Deployment"],
  ["cost", "Cost"],
  ["limitations", "Limitations"],
  ["source", "Source code"],
] as const;

export type SectionId = (typeof PROJECT_SECTIONS)[number][0];

export function ProjectToc() {
  return (
    <nav aria-label="On this page" className="hidden lg:block">
      <ol className="sticky top-24 space-y-1.5 text-sm">
        {PROJECT_SECTIONS.map(([id, title], i) => (
          <li key={id} className="flex gap-3">
            <span className="num w-5 text-right text-faint">{i + 1}</span>
            <a href={`#${id}`} className="text-muted hover:text-text">
              {title}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function ProjectSection({ id, children }: { id: SectionId; children: ReactNode }) {
  const index = PROJECT_SECTIONS.findIndex(([sid]) => sid === id);
  const title = PROJECT_SECTIONS[index]?.[1] ?? id;
  return (
    <section
      id={id}
      aria-labelledby={`${id}-h`}
      className="scroll-mt-24 border-t border-line pt-10"
    >
      <h2 id={`${id}-h`} className="heading flex items-baseline gap-3 text-xl">
        <span className="num text-base text-faint">{index + 1}</span>
        {title}
      </h2>
      <div className="mt-5 space-y-4 text-muted [&_strong]:font-semibold [&_strong]:text-text">
        {children}
      </div>
    </section>
  );
}

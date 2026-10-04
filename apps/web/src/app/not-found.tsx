import Link from "next/link";

import { ButtonLink } from "@/components/button-link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-3xl px-5 pt-20 sm:px-8 md:pt-28">
      <p className="num text-muted">404</p>
      <h1 className="display mt-3 text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">
        There is no page at this address.
      </h1>
      <p className="mt-5 max-w-[56ch] text-lg text-muted">
        This site was rebuilt in October 2026 and older demo links were retired. The current
        projects are listed on the projects page.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <ButtonLink href="/projects">See projects</ButtonLink>
        <ButtonLink href="/" variant="secondary">
          Go to the homepage
        </ButtonLink>
      </div>
      <p className="mt-10 text-sm text-faint">
        Expected something here?{" "}
        <Link href="/hire" className="underline">
          Let me know
        </Link>
        .
      </p>
    </div>
  );
}

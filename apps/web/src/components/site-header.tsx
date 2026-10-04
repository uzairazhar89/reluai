import Link from "next/link";

import { nav } from "@/lib/site";

import { ButtonLink } from "./button-link";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-line/70 bg-ink/90 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-5 sm:px-8">
        <Link href="/" className="display text-lg tracking-tight" aria-label="Uzair Azhar, home">
          Uzair Azhar
        </Link>

        <nav aria-label="Main" className="hidden items-center gap-7 md:flex">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-sm text-muted transition-colors hover:text-text"
            >
              {item.label}
            </Link>
          ))}
          <ButtonLink href="/hire" size="sm">
            Hire me
          </ButtonLink>
        </nav>

        {/* No-JS mobile menu */}
        <details className="group relative md:hidden">
          <summary className="flex h-10 cursor-pointer list-none items-center rounded-sm px-3 text-sm text-muted ring-1 ring-line [&::-webkit-details-marker]:hidden">
            Menu
          </summary>
          <nav
            aria-label="Main"
            className="absolute right-0 top-12 w-56 rounded-md border border-line bg-surface p-2 shadow-xl"
          >
            {[...nav, { href: "/hire", label: "Hire me" }].map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="block rounded-sm px-3 py-2.5 text-base text-text hover:bg-surface-2"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </details>
      </div>
    </header>
  );
}

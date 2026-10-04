import Link from "next/link";

import { site } from "@/lib/site";

const links = [
  { href: "/projects", label: "Projects" },
  { href: "/hire", label: "Hire me" },
  { href: "/data", label: "Data and licences" },
  { href: "/privacy", label: "Privacy" },
  { href: "/status", label: "Status" },
];

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-12 sm:px-8 md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="max-w-sm">
          <p className="display text-lg">Uzair Azhar</p>
          <p className="mt-2 text-sm text-muted">
            Python, data and AI engineer. Every demo on this site runs on a single 2 vCPU / 8 GB
            server with no paid APIs, and every number comes from a recorded run.
          </p>
        </div>
        <nav aria-label="Footer" className="text-sm">
          <ul className="space-y-2">
            {links.map((l) => (
              <li key={l.href}>
                <Link href={l.href} className="text-muted hover:text-text">
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="text-sm">
          <ul className="space-y-2">
            <li>
              <a href={`mailto:${site.email}`} className="text-muted hover:text-text">
                {site.email}
              </a>
            </li>
            <li>
              <a href={site.github} className="text-muted hover:text-text" rel="me">
                GitHub
              </a>
            </li>
            <li>
              <a href={site.linkedin} className="text-muted hover:text-text" rel="me">
                LinkedIn
              </a>
            </li>
            <li>
              <a href={site.repo} className="text-muted hover:text-text">
                Source code of this site
              </a>
            </li>
          </ul>
        </div>
      </div>
      <div className="mx-auto max-w-6xl px-5 pb-10 text-xs text-faint sm:px-8">
        <p>
          © {new Date().getFullYear()} Uzair Azhar. Code under the MIT licence; third-party data
          keeps its own licence (see{" "}
          <Link href="/data" className="underline">
            Data and licences
          </Link>
          ).
        </p>
      </div>
    </footer>
  );
}

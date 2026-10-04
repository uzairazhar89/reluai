import type { MetadataRoute } from "next";

import { liveProjects } from "@/content/projects";
import { site } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const pages: [string, number][] = [
    ["/", 1],
    ["/projects", 0.9],
    ...liveProjects.map((p): [string, number] => [`/projects/${p.slug}`, 0.9]),
    ["/hire", 0.8],
    ["/data", 0.5],
    ["/status", 0.3],
    ["/privacy", 0.2],
  ];
  return pages.map(([path, priority]) => ({
    url: new URL(path, site.url).toString(),
    priority,
  }));
}

import type { MetadataRoute } from "next";

import { site } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  // Staging and preview builds set NEXT_PUBLIC_SITE_URL to their own origin; keep them out of indexes.
  const production = new URL(site.url).hostname === site.domain;
  return {
    rules: production
      ? { userAgent: "*", allow: "/", disallow: ["/api/"] }
      : { userAgent: "*", disallow: "/" },
    sitemap: production ? new URL("/sitemap.xml", site.url).toString() : undefined,
  };
}

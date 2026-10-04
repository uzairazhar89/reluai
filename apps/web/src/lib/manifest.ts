import "server-only";

import { readFileSync } from "node:fs";
import path from "node:path";

import { parse } from "yaml";

/**
 * The artifact manifest (artifacts/manifest.yaml) is the single record of every third-party
 * dataset the site uses. The /data page is rendered from it at build time, so the page and
 * the verified fetch in the data package can never disagree.
 */
export interface ManifestSource {
  kind: string;
  role: "canonical" | "mirror";
  url: string;
  sha256?: string;
  max_bytes?: number;
  notes?: string;
}

export interface ManifestDataset {
  id: string;
  title: string;
  publisher: string;
  homepage: string;
  doi?: string;
  description: string;
  real_data: boolean;
  modifications?: string[];
  licence: { name: string; url: string; attribution: string; notes?: string };
  sources: ManifestSource[];
  checks: {
    rows?: number;
    columns?: string[];
    min_timestamp?: string;
    max_timestamp?: string;
    content_sha256?: string;
  };
  used_by: string[];
}

export interface Manifest {
  version: number;
  datasets: ManifestDataset[];
}

export function manifestPath(): string {
  return (
    process.env.RELUAI_MANIFEST ??
    path.join(process.cwd(), "..", "..", "artifacts", "manifest.yaml")
  );
}

export function loadManifest(file = manifestPath()): Manifest {
  const doc = parse(readFileSync(file, "utf8")) as Manifest;
  if (!doc || !Array.isArray(doc.datasets)) {
    throw new Error(`Invalid manifest at ${file}: no datasets list`);
  }
  return doc;
}

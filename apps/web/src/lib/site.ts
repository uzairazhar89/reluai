/** Site-wide facts used in metadata, structured data and the footer. */
export const site = {
  name: "Uzair Azhar",
  domain: "reluai.cloud",
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "https://reluai.cloud",
  title: "Uzair Azhar: Python, data and AI engineer",
  description:
    "Python, data and computer-vision engineering: production-style pipelines, AI applications " +
    "and APIs with live demos running on real data.",
  email: "uzairazhar@gmail.com",
  github: "https://github.com/uzairazhar89",
  repo: "https://github.com/uzairazhar89/reluai",
  linkedin: "https://www.linkedin.com/in/uzairazhar",
} as const;

export const nav = [
  { href: "/projects", label: "Projects" },
  { href: "/#how-i-work", label: "How I work" },
  { href: "/data", label: "Data" },
  { href: "/status", label: "Status" },
] as const;

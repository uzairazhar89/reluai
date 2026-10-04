import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

type Variant = "primary" | "secondary" | "quiet";
type Size = "sm" | "md";

const base =
  "inline-flex items-center justify-center gap-2 rounded-sm font-medium transition-colors " +
  "disabled:cursor-not-allowed disabled:opacity-50";
const variants: Record<Variant, string> = {
  primary: "bg-text text-ink hover:bg-white",
  secondary: "text-text ring-1 ring-line-strong hover:bg-surface-2",
  quiet: "text-link underline-offset-4 hover:underline",
};
const sizes: Record<Size, string> = {
  sm: "h-9 px-3.5 text-sm",
  md: "h-11 px-5 text-base",
};

export function buttonClasses(variant: Variant = "primary", size: Size = "md"): string {
  return `${base} ${variants[variant]} ${variant === "quiet" ? "" : sizes[size]}`;
}

interface Props extends Omit<ComponentProps<typeof Link>, "className"> {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
  external?: boolean;
}

export function ButtonLink({
  variant = "primary",
  size = "md",
  external,
  children,
  ...rest
}: Props) {
  const className = buttonClasses(variant, size);
  if (external) {
    return (
      <a href={String(rest.href)} className={className} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  }
  return (
    <Link {...rest} className={className}>
      {children}
    </Link>
  );
}

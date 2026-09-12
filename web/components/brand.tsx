import Link from "next/link";

export function Brand({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 font-medium tracking-tight">
      <span aria-hidden className="size-2.5 rounded-full bg-primary" />
      Lanka Link
    </Link>
  );
}

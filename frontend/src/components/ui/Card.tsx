import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("glass rounded-2xl", className)} {...rest} />;
}

import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-5 animate-spin text-ember-500", className)} />;
}

export function FullPageSpinner() {
  return (
    <div className="grid min-h-dvh place-items-center">
      <Spinner className="size-7" />
    </div>
  );
}

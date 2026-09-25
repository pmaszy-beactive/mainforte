import { useEffect, useRef } from "react";
import { MessageSquareDashed } from "lucide-react";
import type { Bubble as BubbleT } from "@/hooks/useEventStream";
import { Bubble } from "./Bubble";

export function MessageList({ bubbles, empty }: { bubbles: BubbleT[]; empty: string }) {
  const end = useRef<HTMLDivElement>(null);
  const last = bubbles[bubbles.length - 1];
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [bubbles.length, last?.text]);

  if (bubbles.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center text-fog-700">
        <MessageSquareDashed className="size-8 opacity-60" />
        <p className="max-w-sm text-sm">{empty}</p>
      </div>
    );
  }
  return (
    <div className="flex-1 space-y-3 overflow-y-auto px-4 py-5 md:px-8">
      {bubbles.map((b) => (
        <Bubble key={b.id} bubble={b} />
      ))}
      <div ref={end} />
    </div>
  );
}

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { BlockedTask } from "@/hooks/useEventStream";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

/** One task-blocked prompt: shows the stage's `reason` and a text box that resumes the task via
 * POST .../tasks/{id}/input. Cleared optimistically on success (the task.completed/failed/blocked
 * event for the next stage will also reconcile it via useEventStream). */
export function TaskBlockedBanner({ workspaceId, task, onResolved }: { workspaceId: string; task: BlockedTask; onResolved: () => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");

  const submit = useMutation({
    mutationFn: () => api.tasks.input(workspaceId, task.taskId, text),
    onSuccess: () => onResolved(),
  });

  return (
    <div className="mb-2 rounded-xl border border-ember-500/30 bg-ember-500/10 px-3.5 py-2.5">
      <div className="flex items-start gap-2 text-sm text-ember-200">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <span>{task.reason}</span>
      </div>
      <form
        className="mt-2 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim() || submit.isPending) return;
          submit.mutate();
        }}
      >
        <Input
          className="h-9"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("chat.taskBlockedPlaceholder")}
          disabled={submit.isPending}
          autoFocus
        />
        <Button type="submit" size="sm" disabled={!text.trim()} loading={submit.isPending}>
          {t("chat.taskBlockedSubmit")}
        </Button>
      </form>
      {submit.isError && <p className="mt-1.5 text-xs text-red-300">{(submit.error as Error).message}</p>}
    </div>
  );
}

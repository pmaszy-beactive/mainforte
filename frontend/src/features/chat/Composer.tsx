import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Paperclip, SendHorizontal, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { useUi } from "@/stores/ui";
import { useAttachments } from "@/stores/attachments";
import { cn } from "@/lib/cn";
import { AttachmentTray } from "./AttachmentTray";

interface Props {
  workspaceId: string | null;
  threadId: string;
  draftKey: string;
  streaming: boolean;
  stopping?: boolean;
  onStop: () => void;
  onSend: (text: string, attachmentLocalIds: string[]) => void;
}

const ACCEPT = "image/*,text/*,.pdf,.csv,.json,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip";
const DRAFT_SAVE_DEBOUNCE_MS = 1500;

export function Composer({ workspaceId, threadId, draftKey, streaming, stopping, onStop, onSend }: Props) {
  const { t } = useTranslation();
  const text = useUi((s) => s.drafts[draftKey] ?? "");
  const setDraft = useUi((s) => s.setDraft);
  const add = useAttachments((s) => s.add);
  const items = useAttachments((s) => s.items);
  const [localIds, setLocalIds] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [justSent, setJustSent] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const disabled = !workspaceId;
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Fetch-on-mount server backstop: only seeds the draft when this device has nothing local yet,
  // so a stale/older server value never clobbers an in-progress local edit.
  const { data: serverDraft } = useQuery({
    queryKey: ["draft", workspaceId, threadId],
    queryFn: () => api.drafts.get(workspaceId!, threadId),
    enabled: !!workspaceId,
    staleTime: Infinity,
  });
  useEffect(() => {
    if (serverDraft?.text && !useUi.getState().drafts[draftKey]) {
      setDraft(draftKey, serverDraft.text);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverDraft, draftKey]);

  const saveDraft = (value: string) => {
    if (!workspaceId) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      api.drafts.save(workspaceId, threadId, value).catch(() => {});
    }, DRAFT_SAVE_DEBOUNCE_MS);
  };

  // Auto-grow the textarea with content instead of scrolling inside a fixed box.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  // Bridge the gap between hitting Enter and `streaming` flipping true (event-stream
  // round-trip): without this the Send button gives no feedback for a beat.
  useEffect(() => {
    if (streaming) setJustSent(false);
  }, [streaming]);

  const addFiles = (files: FileList | File[] | null | undefined) => {
    if (!workspaceId || !files) return;
    const ids = Array.from(files).map((f) => add(workspaceId, f));
    if (ids.length) setLocalIds((l) => [...l, ...ids]);
  };

  const uploading = localIds.some((id) => items[id]?.status === "uploading");
  const canSend = !disabled && !uploading && (text.trim().length > 0 || localIds.length > 0);

  const submit = () => {
    if (!canSend) return;
    onSend(text.trim(), localIds.filter((id) => items[id]));
    setDraft(draftKey, "");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    if (workspaceId) api.drafts.save(workspaceId, threadId, "").catch(() => {});
    setLocalIds([]);
    setJustSent(true);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files ?? []);
    if (files.length) {
      e.preventDefault();
      addFiles(files);
    }
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!dragging) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn("glass rounded-2xl p-2 transition focus-within:border-ember-500/40", dragging && "border-ember-500/60 bg-ember-500/5")}
    >
      {dragging && <div className="px-2.5 pb-1 text-xs text-ember-300">{t("chat.dropHint")}</div>}
      <AttachmentTray localIds={localIds} onRemove={(id) => setLocalIds((l) => l.filter((x) => x !== id))} />
      <div className="flex items-end gap-1.5">
        <input ref={fileInput} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
        <Button size="md" variant="ghost" onClick={() => fileInput.current?.click()} disabled={disabled} aria-label={t("chat.attach")} title={t("chat.attach")}>
          <Paperclip className="size-4" />
        </Button>
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          disabled={disabled}
          onChange={(e) => {
            setDraft(draftKey, e.target.value);
            saveDraft(e.target.value);
          }}
          onKeyDown={onKey}
          onPaste={onPaste}
          placeholder={t("chat.placeholder")}
          className="max-h-64 min-h-[2.5rem] flex-1 resize-none overflow-y-auto bg-transparent px-2 py-2 text-sm placeholder:text-fog-700 disabled:opacity-50"
        />
        {streaming ? (
          <Button size="md" variant="danger" onClick={onStop} loading={stopping} aria-label={t("chat.stop")} title={t("chat.stop")}>
            <Square className="size-3.5 fill-current" /> <span className="hidden sm:inline">{t("chat.stop")}</span>
          </Button>
        ) : (
          <Button size="md" onClick={submit} disabled={!canSend || justSent} loading={justSent} aria-label={t("chat.send")}>
            <SendHorizontal className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

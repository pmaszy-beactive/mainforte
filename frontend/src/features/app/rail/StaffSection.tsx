import { useState } from "react";
import { Hash, UserPlus, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { RailItem, RailSection } from "./RailSection";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/features/auth/useAuthActions";
import { api } from "@/lib/api";
import { useUi } from "@/stores/ui";

// Bots/personas arrive in P1. Shell: global channel pinned + empty bot list + invite.
export function StaffSection({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const wsId = useUi((s) => s.workspaceId);
  const active = useUi((s) => s.activeThreadId);
  const setThread = useUi((s) => s.setThread);
  const bots: { id: string; name: string; role: string }[] = [];

  const [inviting, setInviting] = useState(false);
  const [email, setEmail] = useState("");

  const addMember = useMutation({
    mutationFn: () => api.workspaces.addMember(wsId!, { email: email.trim(), role: "member" }),
    onSuccess: () => {
      setInviting(false);
      setEmail("");
    },
  });

  const goGlobal = () => {
    setThread(null);
    nav("/app");
  };

  const openInvite = () => {
    addMember.reset();
    setInviting(true);
  };

  const invite = (
    <button
      className="rounded-md p-1 text-fog-500 hover:bg-white/5 hover:text-fog-100 ring-focus"
      aria-label={t("app.staff.invite")}
      title={t("app.staff.invite")}
      onClick={openInvite}
    >
      <UserPlus className="size-3.5" />
    </button>
  );

  return (
    <RailSection title={t("app.staff.title")} collapsed={collapsed} action={invite}>
      <RailItem collapsed={collapsed} icon={<Hash className="size-4" />} label={t("app.staff.global")} active={active === null} onClick={goGlobal} />
      <div className="mt-1 space-y-0.5">
        {bots.map((b) => (
          <RailItem key={b.id} collapsed={collapsed} icon={<Users className="size-4" />} label={b.name} active={active === b.id} onClick={() => setThread(b.id)} />
        ))}
      </div>
      {!collapsed && inviting && (
        <form
          className="mt-2 space-y-1.5 rounded-xl border border-white/10 bg-ink-950/60 p-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (email.trim() && wsId) addMember.mutate();
          }}
        >
          <input
            autoFocus
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t("app.staff.invitePlaceholder")}
            className="block h-8 w-full rounded-lg border border-white/10 bg-ink-900/60 px-2.5 text-xs"
          />
          {addMember.isError && (
            <p className="text-xs text-red-300">{errorMessage(addMember.error, t("common.error"))}</p>
          )}
          <div className="flex items-center gap-1.5">
            <Button type="submit" size="sm" className="flex-1" loading={addMember.isPending} disabled={!email.trim()}>
              {t("app.staff.inviteSubmit")}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setInviting(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      )}
      {!collapsed && bots.length === 0 && (
        <div className="mt-2">
          <EmptyState
            icon={<Users className="size-5" />}
            title={t("app.staff.empty")}
            hint={t("app.staff.emptyHint")}
            action={
              <Button size="sm" variant="outline" className="mt-1" onClick={openInvite}>
                <UserPlus className="size-3.5" /> {t("app.staff.invite")}
              </Button>
            }
          />
        </div>
      )}
    </RailSection>
  );
}

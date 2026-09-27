import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { AdminBastionJenkinsSettings } from "@/lib/types";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

type FormState = {
  bastion_host: string;
  bastion_port: string;
  bastion_username: string;
  bastion_ssh_key: string;
  jenkins_host: string;
  jenkins_port: string;
  jenkins_username: string;
  jenkins_ssh_key: string;
  jenkins_provision_job: string;
  jenkins_destroy_job: string;
};

const EMPTY_FORM: FormState = {
  bastion_host: "",
  bastion_port: "",
  bastion_username: "",
  bastion_ssh_key: "",
  jenkins_host: "",
  jenkins_port: "",
  jenkins_username: "",
  jenkins_ssh_key: "",
  jenkins_provision_job: "",
  jenkins_destroy_job: "",
};

function fromData(data: AdminBastionJenkinsSettings): FormState {
  return {
    bastion_host: data.bastion_host ?? "",
    bastion_port: data.bastion_port?.toString() ?? "",
    bastion_username: data.bastion_username ?? "",
    bastion_ssh_key: "",
    jenkins_host: data.jenkins_host ?? "",
    jenkins_port: data.jenkins_port?.toString() ?? "",
    jenkins_username: data.jenkins_username ?? "",
    jenkins_ssh_key: "",
    jenkins_provision_job: data.jenkins_provision_job ?? "",
    jenkins_destroy_job: data.jenkins_destroy_job ?? "",
  };
}

export default function SettingsTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "settings", "bastion-jenkins"], queryFn: api.admin.bastionJenkinsSettings });

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  useEffect(() => {
    if (q.data) setForm(fromData(q.data));
  }, [q.data]);

  const save = useMutation({
    mutationFn: () =>
      api.admin.setBastionJenkinsSettings({
        bastion_host: form.bastion_host || null,
        bastion_port: form.bastion_port ? Number(form.bastion_port) : null,
        bastion_username: form.bastion_username || null,
        bastion_ssh_key: form.bastion_ssh_key || null,
        jenkins_host: form.jenkins_host || null,
        jenkins_port: form.jenkins_port ? Number(form.jenkins_port) : null,
        jenkins_username: form.jenkins_username || null,
        jenkins_ssh_key: form.jenkins_ssh_key || null,
        jenkins_provision_job: form.jenkins_provision_job || null,
        jenkins_destroy_job: form.jenkins_destroy_job || null,
      }),
    onSuccess: (data) => {
      qc.setQueryData(["admin", "settings", "bastion-jenkins"], data);
      setForm(fromData(data));
    },
  });

  const set = (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <div className="space-y-6">
      <form
        className="glass space-y-4 rounded-2xl p-5"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div>
          <h2 className="text-sm font-semibold text-fog-100">{t("admin.settings.bastionJenkins.title")}</h2>
          <p className="mt-1 text-xs text-fog-500">{t("admin.settings.bastionJenkins.description")}</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t("admin.settings.bastionJenkins.bastionHost")} value={form.bastion_host} onChange={set("bastion_host")} />
          <Input
            label={t("admin.settings.bastionJenkins.bastionPort")}
            type="number"
            value={form.bastion_port}
            onChange={set("bastion_port")}
          />
          <Input label={t("admin.settings.bastionJenkins.bastionUsername")} value={form.bastion_username} onChange={set("bastion_username")} />
        </div>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("admin.settings.bastionJenkins.bastionSshKey")}</span>
          <textarea
            rows={4}
            value={form.bastion_ssh_key}
            onChange={set("bastion_ssh_key")}
            placeholder={q.data?.bastion_ssh_key ? t("admin.settings.bastionJenkins.keyAlreadySet") : t("admin.settings.bastionJenkins.keyNotSet")}
            className="block w-full rounded-xl border border-white/10 bg-ink-950/60 px-3.5 py-2.5 font-mono text-xs text-fog-100 placeholder:text-fog-700 focus:border-ember-500/60 focus:ring-2 focus:ring-ember-500/20"
          />
          <span className="block text-xs text-fog-700">{t("admin.settings.bastionJenkins.keyHint")}</span>
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t("admin.settings.bastionJenkins.jenkinsHost")} value={form.jenkins_host} onChange={set("jenkins_host")} />
          <Input
            label={t("admin.settings.bastionJenkins.jenkinsPort")}
            type="number"
            value={form.jenkins_port}
            onChange={set("jenkins_port")}
          />
          <Input label={t("admin.settings.bastionJenkins.jenkinsUsername")} value={form.jenkins_username} onChange={set("jenkins_username")} />
        </div>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium uppercase tracking-wider text-fog-500">{t("admin.settings.bastionJenkins.jenkinsSshKey")}</span>
          <textarea
            rows={4}
            value={form.jenkins_ssh_key}
            onChange={set("jenkins_ssh_key")}
            placeholder={q.data?.jenkins_ssh_key ? t("admin.settings.bastionJenkins.keyAlreadySet") : t("admin.settings.bastionJenkins.keyNotSet")}
            className="block w-full rounded-xl border border-white/10 bg-ink-950/60 px-3.5 py-2.5 font-mono text-xs text-fog-100 placeholder:text-fog-700 focus:border-ember-500/60 focus:ring-2 focus:ring-ember-500/20"
          />
          <span className="block text-xs text-fog-700">{t("admin.settings.bastionJenkins.keyHint")}</span>
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t("admin.settings.bastionJenkins.provisionJob")} value={form.jenkins_provision_job} onChange={set("jenkins_provision_job")} />
          <Input label={t("admin.settings.bastionJenkins.destroyJob")} value={form.jenkins_destroy_job} onChange={set("jenkins_destroy_job")} />
        </div>

        <div className="flex items-center gap-3 pt-2">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
          {save.isSuccess && <span className="text-xs text-emerald-300">{t("common.saved")}</span>}
          {save.error && <span className="text-xs text-red-300">{save.error.message}</span>}
        </div>
      </form>

      <p className="text-xs text-fog-700">{t("common.comingSoon")}</p>
    </div>
  );
}

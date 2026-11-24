"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { CodeEditor } from "@/components/code-editor";
import { CodeView } from "@/components/code-view";
import { JobProgress } from "@/components/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useZones } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";
import { useI18n } from "@/lib/i18n";

type Plan = components["schemas"]["NewComposePlanOut"];
type Deployed = components["schemas"]["DeployOut"];

const LABS_ZONE = "security-labs";
const section = "surface grid gap-4 rounded-xl border p-5";
const EXAMPLE = "services:\n  web:\n    image: nginx:1.29-alpine\n    ports:\n      - \"8080:80\"\n";

/** Your own compose file as a new app (admin: it runs as written, after the checks).
 *  `labs`: a target of the Cybersecurity module, placed in the Labo zone. */
export function NewCompose({ labs = false }: { labs?: boolean }) {
  const { t, errorMessage } = useI18n();
  const { data: zones } = useZones();
  const [name, setName] = useState("");
  const [zone, setZone] = useState("");
  const [text, setText] = useState(EXAMPLE);
  const [plan, setPlan] = useState<Plan | null>(null);
  const body = () => ({ name, zone: zone || null, compose_yaml: text, labs });
  const check = useMutation({
    mutationFn: () => api<Plan>("/apps/compose/plan", { method: "POST", body: body() }),
    onSuccess: setPlan,
  });
  const deploy = useMutation({ mutationFn: () => api<Deployed>("/apps/compose", { method: "POST", body: body() }) });
  const reset = () => setPlan(null);

  if (deploy.data) {
    return (
      <div className={section}>
        <JobProgress jobId={deploy.data.job.id} />
        <Button asChild className="justify-self-start">
          <Link href={labs ? "/labs/dashboard/" : `/app/?id=${deploy.data.app.id}`}>
            {t(labs ? "nav.labs.dashboard" : "deploy.goToApp")}
          </Link>
        </Button>
      </div>
    );
  }
  const ready = plan && plan.problems.length === 0 && plan.conflicts.length === 0;
  return (
    <div className="grid max-w-4xl gap-4">
      <p className="text-sm text-muted-foreground">{t(labs ? "ownCompose.introLabs" : "ownCompose.intro")}</p>
      <section className={section}>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor="compose-name">{t("deploy.name")}</Label>
            <Input id="compose-name" value={name} maxLength={100} required onChange={(e) => (setName(e.target.value), reset())} />
          </div>
          {!labs && (
            <div className="grid gap-1.5">
              <Label htmlFor="compose-zone">{t("deploy.zone")}</Label>
              <Select id="compose-zone" value={zone} onChange={(e) => (setZone(e.target.value), reset())}>
                <option value="">{t("dashboard.unclassified")}</option>
                {zones?.filter((z) => z.slug !== LABS_ZONE).map((z) => (
                  <option key={z.slug} value={z.slug}>{z.name}</option>
                ))}
              </Select>
            </div>
          )}
        </div>
        <CodeEditor
          language="yaml"
          label={t("ownCompose.file")}
          value={text}
          height="22rem"
          onChange={(next) => (setText(next), reset())}
          onSave={() => !check.isPending && name.trim() && check.mutate()}
        />
        <p className="text-xs text-muted-foreground">{t("ownCompose.rules")}</p>
      </section>

      {plan && plan.problems.length > 0 && (
        <Alert tone="danger">
          <p className="font-medium">{t("compose.problems")}</p>
          <ul className="list-disc pl-5">
            {plan.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Alert>
      )}
      {plan?.conflicts.map((c) => (
        <Alert key={`${c.port}/${c.protocol}`} tone="danger">
          {t("deploy.conflict", { port: c.port, protocol: c.protocol, owner: c.used_by })}
        </Alert>
      ))}
      {ready && (
        <section className={section}>
          <Alert tone="info">{t("ownCompose.ok", { slug: plan.slug })}</Alert>
          <CodeView code={plan.compose_yaml} />
        </section>
      )}
      {(check.error ?? deploy.error) && <Alert tone="danger">{errorMessage(check.error ?? deploy.error)}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" loading={check.isPending} disabled={check.isPending || !name.trim()} onClick={() => check.mutate()}>
          {t("compose.check")}
        </Button>
        <Button loading={deploy.isPending} disabled={!ready || deploy.isPending} onClick={() => deploy.mutate()}>
          {t("ownCompose.deploy")}
        </Button>
      </div>
    </div>
  );
}

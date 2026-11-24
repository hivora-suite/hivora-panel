"use client";

import { PageHeader } from "@/components/app-shell";
import { KillChain } from "@/features/killchain/killchain";
import { LabTabs } from "@/features/killchain/lab-tabs";
import { useI18n } from "@/lib/i18n";

export default function LabsPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("labs.title")} />
      <LabTabs />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("labs.intro")}</p>
      <KillChain />
    </>
  );
}

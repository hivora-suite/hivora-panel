"use client";

import { PageHeader } from "@/components/app-shell";
import { LabDashboard } from "@/features/killchain/lab-dashboard";
import { LabTabs } from "@/features/killchain/lab-tabs";
import { useI18n } from "@/lib/i18n";

export default function LabDashboardPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("labs.dash.title")} />
      <LabTabs />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("labs.dash.intro")}</p>
      <LabDashboard />
    </>
  );
}

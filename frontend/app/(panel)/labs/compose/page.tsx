"use client";

import { PageHeader } from "@/components/app-shell";
import { NewCompose } from "@/features/apps/new-compose";
import { LabTabs } from "@/features/killchain/lab-tabs";
import { useI18n } from "@/lib/i18n";

export default function LabComposePage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("ownCompose.titleLabs")} />
      <LabTabs />
      <NewCompose labs />
    </>
  );
}

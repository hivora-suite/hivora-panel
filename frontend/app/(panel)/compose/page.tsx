"use client";

import { PageHeader } from "@/components/app-shell";
import { NewCompose } from "@/features/apps/new-compose";
import { useI18n } from "@/lib/i18n";

export default function OwnComposePage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("ownCompose.title")} />
      <NewCompose />
    </>
  );
}

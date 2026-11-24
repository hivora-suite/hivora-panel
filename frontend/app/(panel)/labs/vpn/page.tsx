"use client";

import { PageHeader } from "@/components/app-shell";
import { LabTabs } from "@/features/killchain/lab-tabs";
import { LabVpn } from "@/features/killchain/lab-vpn";
import { useI18n } from "@/lib/i18n";

export default function LabVpnPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("labs.vpn.title")} />
      <LabTabs />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("labs.vpn.intro")}</p>
      <LabVpn />
    </>
  );
}

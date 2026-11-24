"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/app-shell";
import { LabTabs } from "@/features/killchain/lab-tabs";
import { LabStudents } from "@/features/killchain/lab-vpn";
import { useI18n } from "@/lib/i18n";

function Focused() {
  return <LabStudents focus={useSearchParams().get("lab")} />;
}

export default function LabStudentsPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("labs.students.title")} />
      <LabTabs />
      <p className="mb-6 max-w-2xl text-sm text-muted-foreground">{t("labs.students.intro")}</p>
      <Suspense>
        <Focused />
      </Suspense>
    </>
  );
}

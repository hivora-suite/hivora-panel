"use client";

import { Bug, Crosshair, KeyRound, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const TABS: { href: string; label: MessageKey; icon: typeof Bug }[] = [
  { href: "/labs/", label: "nav.killchain", icon: Crosshair },
  { href: "/labs/dashboard/", label: "nav.labs.dashboard", icon: Bug },
  { href: "/labs/students/", label: "nav.labs.students", icon: Users },
  { href: "/labs/vpn/", label: "nav.labs.vpn", icon: KeyRound },
];

/** The labs pages, one click apart. */
export function LabTabs() {
  const { t } = useI18n();
  const path = usePathname().replace(/\/?$/, "/");
  return (
    <nav aria-label={t("labs.title")} className="mb-6 flex gap-1 overflow-x-auto border-b">
      {TABS.map(({ href, label, icon: Icon }) => {
        const on = path === href;
        return (
          <Link key={href} href={href} aria-current={on ? "page" : undefined}
            className={cn("-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors",
              on ? "border-(--nav-labs) font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            <Icon className="size-4" /> {t(label)}
          </Link>
        );
      })}
    </nav>
  );
}

"use client";

import { Gamepad2, ShieldHalf } from "lucide-react";

import { useSession } from "@/components/app-shell";
import { CodeView } from "@/components/code-view";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSystemInfo } from "@/lib/api/hooks";
import { useI18n } from "@/lib/i18n";

/** The optional modules, turned on or off by the installer (install.env, never by the panel):
 *  their state, and for admins the command that switches each one. */
export function ModulesCard() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: info } = useSystemInfo();
  if (!info) return null;
  const modules = [
    { key: "games", icon: Gamepad2, on: info.games, flag: info.games ? "--no-games" : "--games" },
    { key: "labs", icon: ShieldHalf, on: info.labs, flag: info.labs ? "--no-labs" : "--labs" },
  ] as const;
  return (
    <Card className="xl:col-span-2">
      <CardHeader>
        <CardTitle>{t("modules.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        <p className="text-muted-foreground">{t("modules.intro")}</p>
        <div className="grid gap-3">
          {modules.map((m) => (
            <div key={m.key} className="grid content-start gap-2 rounded-xl border p-4">
              <div className="flex items-center gap-2">
                <m.icon className="size-4 text-muted-foreground" />
                <span className="font-medium">{t(`modules.${m.key}`)}</span>
                <Badge className={m.on ? "ml-auto border-ok/40 bg-ok/10 text-ok" : "ml-auto border-border bg-muted text-muted-foreground"}>
                  {t(m.on ? "modules.on" : "modules.off")}
                </Badge>
              </div>
              <p className="text-muted-foreground">{t(`modules.${m.key}.help`)}</p>
              {can("admin") && info.installer && (
                <div className="grid gap-1">
                  <span className="text-muted-foreground">{t(m.on ? "modules.howOff" : "modules.howOn")}</span>
                  <CodeView code={`${info.installer} --yes ${m.flag}`} className="[&_pre]:break-all [&_pre]:whitespace-pre-wrap" />
                </div>
              )}
            </div>
          ))}
        </div>
        {can("admin") && <p className="text-xs text-muted-foreground">{t(info.installer ? "modules.note" : "modules.noInstaller")}</p>}
      </CardContent>
    </Card>
  );
}

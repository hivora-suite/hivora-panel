"use client";

import { Bug, ChevronDown, Crosshair, ExternalLink, Loader2, Power, RotateCw, ShieldCheck, ShieldOff, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { useSession } from "@/components/app-shell";
import { useTrackJob } from "@/components/job-toasts";
import { studentsHref } from "@/features/killchain/lab-vpn";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Label, Switch } from "@/components/ui/input";
import { TileSkeletons } from "@/components/ui/skeleton";
import { useAddressing, useApps, useBulkAppAction, useBulkRemoveApps, useLabsVpn, useSystemInfo, useTemplates } from "@/lib/api/hooks";
import type { App, AppStatus, LabsVpnLab, TemplateSummary } from "@/lib/api/client";
import { useAppMetrics, useLiveStatus } from "@/lib/realtime";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// Above this inbound rate, the bug reddens and shakes: the target is being hit right now.
// ponytail: plain threshold on inbound bytes, not an IDS; raise it if a lab is chatty.
const ATTACK_BPS = 40_000;

const RUNNING: AppStatus[] = ["healthy", "starting", "degraded"];
const DOT: Record<AppStatus, string> = {
  healthy: "bg-ok", starting: "bg-warn", degraded: "bg-warn",
  stopped: "bg-idle", error: "bg-danger", missing: "bg-idle",
};

type LabInfo = { name: string; phase: string; difficulty: "easy" | "medium" | "hard" };

/** Whether the lab is behind the labs VPN, with its students: a shortcut to its VPN group. */
function VpnBadge({ vpn, slug }: { vpn: { enabled: boolean; lab: LabsVpnLab | undefined } | null; slug: string }) {
  const { t } = useI18n();
  if (!vpn) return null;
  if (!vpn.enabled) {
    return (
      <Link href="/labs/vpn/" className="inline-flex items-center gap-1 rounded-md border border-border bg-muted px-1.5 py-0.5 text-muted-foreground hover:text-foreground" title={t("labs.vpn.lanHint")}>
        <ShieldOff className="size-3" /> {t("labs.vpn.lan")}
      </Link>
    );
  }
  const n = vpn.lab?.students ?? 0;
  const on = vpn.lab?.online ?? 0;
  return (
    <Link href={studentsHref(slug)} className="inline-flex items-center gap-1 rounded-md border border-ok/40 bg-ok/10 px-1.5 py-0.5 text-ok hover:underline">
      <ShieldCheck className="size-3" /> {t("labs.vpn.badge", { n, online: on })}
    </Link>
  );
}

type Vpn = { enabled: boolean; lab: LabsVpnLab | undefined } | null;

/** One copy of a target, as a compact line inside its group. */
function Row({ app, ip, vpn, selectable, selected, onToggle }: { app: App; ip: string | null; vpn: Vpn; selectable: boolean; selected: boolean; onToggle: () => void }) {
  const { t } = useI18n();
  const status = useLiveStatus(app.slug, app.status);
  const running = RUNNING.includes(status);
  const samples = useAppMetrics(app.slug, running);
  const rx = samples.at(-1)?.net_rx_bps ?? 0;
  const attacked = running && rx >= ATTACK_BPS;

  return (
    <li className={cn("flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5", attacked && "bg-danger/10", selected && "bg-(--nav-labs)/5")}>
      {selectable && (
        <input type="checkbox" checked={selected} onChange={onToggle}
          aria-label={t("labs.dash.select", { name: app.name })}
          className="size-4 shrink-0 cursor-pointer accent-(--nav-labs)" />
      )}
      <Bug className={cn("size-4 shrink-0", attacked ? "bug-attack text-danger" : running ? "text-ok" : "text-muted-foreground")} aria-label={t(attacked ? "labs.bug.attack" : running ? "labs.bug.live" : "labs.bug.idle")} />
      <span className="min-w-0 flex-1 truncate font-medium">{app.name}</span>
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className={cn("size-2 rounded-full", DOT[status])} />
        {t(`status.${status}` as MessageKey)}
      </span>
      <Badge className="border-border bg-muted font-mono text-xs">{ip ?? "—"}</Badge>
      <span className="text-xs"><VpnBadge vpn={vpn} slug={app.slug} /></span>
      <Link href={`/app/?id=${app.id}`} className="flex items-center gap-1 text-sm text-(--nav-labs) hover:underline">
        <ExternalLink className="size-3.5" /> {t("labs.open")}
      </Link>
    </li>
  );
}

/** Every copy of one target, in one block: its header (count, phase, difficulty, select all)
 *  and the copies as lines. Folds with the browser's own <details>. */
function Group({ name, icon, lab, apps, running, children, selectable, picked, onPick }: {
  name: string; icon: string | null | undefined; lab: LabInfo | null; apps: App[]; running: number;
  children: React.ReactNode; selectable: boolean; picked: number; onPick: (on: boolean) => void;
}) {
  const { t } = useI18n();
  const all = picked === apps.length;
  return (
    <details open className="surface group overflow-hidden rounded-2xl border">
      <summary className="flex cursor-pointer list-none items-center gap-3 p-4 [&::-webkit-details-marker]:hidden">
        {selectable && (
          <input type="checkbox" checked={all} ref={(el) => { if (el) el.indeterminate = picked > 0 && !all; }}
            onChange={(e) => onPick(e.target.checked)} onClick={(e) => e.stopPropagation()}
            aria-label={t("labs.dash.selectGroup", { name })}
            className="size-4 shrink-0 cursor-pointer accent-(--nav-labs)" />
        )}
        <AppIcon src={icon} name={name} className="size-10 rounded-xl" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-semibold">{name}</h3>
          <p className="text-xs text-muted-foreground">{t("labs.dash.group.count", { n: apps.length, running })}</p>
        </div>
        <div className="hidden flex-wrap gap-1.5 text-xs sm:flex">
          {lab && <Badge className="border-(--nav-labs)/40 bg-(--nav-labs)/10 text-(--nav-labs)">{t(`labs.phase.${lab.phase}` as MessageKey)}</Badge>}
          {lab && <Badge className="border-border bg-muted text-muted-foreground">{t(`labs.diff.${lab.difficulty}` as MessageKey)}</Badge>}
        </div>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <ul className="divide-y border-t">{children}</ul>
    </details>
  );
}

/** Confirm removing the selected targets: lists them, "also delete data" off by default. */
function BulkDeleteDialog({ apps, onDone }: { apps: App[]; onDone: () => void }) {
  const { t } = useI18n();
  const remove = useBulkRemoveApps();
  const track = useTrackJob();
  const [open, setOpen] = useState(false);
  const [removeData, setRemoveData] = useState(false);
  const run = async () => {
    (await remove.mutateAsync({ ids: apps.map((a) => a.id), removeData })).forEach((j) => track(j.id));
    setOpen(false);
    onDone();
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setRemoveData(false); }}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="text-danger"><Trash2 /> {t("labs.dash.bulk.delete")}</Button>
      </DialogTrigger>
      <DialogContent title={t("labs.dash.bulk.deleteTitle", { n: apps.length })} description={t("labs.dash.bulk.deleteSub")} closeLabel={t("common.close")}>
        <ul className="max-h-48 overflow-y-auto rounded-lg border bg-muted/30 p-2 text-sm">
          {apps.map((a) => <li key={a.id} className="truncate px-1 py-0.5 font-mono">{a.name}</li>)}
        </ul>
        <Label className="flex items-center gap-2 text-sm">
          <Switch checked={removeData} onChange={(e) => setRemoveData(e.target.checked)} />
          {t("labs.dash.bulk.removeData")}
        </Label>
        <div className="flex justify-end">
          <Button variant="destructive" onClick={run} disabled={remove.isPending}>
            {remove.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />} {t("labs.dash.bulk.deleteConfirm", { n: apps.length })}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function LabDashboard() {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: info } = useSystemInfo();
  const { data: apps, isLoading } = useApps();
  const { data: templates } = useTemplates();
  const { data: addressing } = useAddressing();
  const { data: vpn } = useLabsVpn(info?.labs ?? false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const act = useBulkAppAction();
  const track = useTrackJob();

  const labTemplates = useMemo(() => {
    const m = new Map<string, LabInfo>();
    for (const tp of (templates ?? []) as (TemplateSummary & { lab: LabInfo | null })[]) {
      if (tp.category === "security-lab" && tp.lab) m.set(tp.slug, { ...tp.lab, name: tp.name });
    }
    return m;
  }, [templates]);

  // app_id -> its container IP, read from the addressing plan (no hand-picked range).
  const ips = useMemo(() => {
    const m = new Map<number, string>();
    for (const z of addressing?.zones ?? []) {
      for (const r of z.rows) {
        if (r.app_id != null && !m.has(r.app_id)) m.set(r.app_id, r.actual ?? r.planned);
      }
    }
    return m;
  }, [addressing]);

  const labApps = (apps ?? []).filter((a) => a.template != null && labTemplates.has(a.template));
  // One group per target template, the biggest first.
  const groups = [...Map.groupBy(labApps, (a) => a.template as string)].sort((a, b) => b[1].length - a[1].length);

  if (info && !info.labs) return <p className="text-muted-foreground">{t("labs.off")}</p>;
  if (isLoading) return <TileSkeletons label={t("common.loading")} />;
  if (labApps.length === 0) {
    return (
      <div className="surface flex items-center gap-3 rounded-2xl border p-6 text-muted-foreground">
        <Crosshair className="size-5" /> {t("labs.dash.empty")}
      </div>
    );
  }

  const selectable = can("operator"); // stop/restart/delete need operator; a viewer only reads
  const chosen = labApps.filter((a) => selected.has(a.id));
  const allOn = chosen.length === labApps.length && labApps.length > 0;
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const setAll = (on: boolean) => setSelected(on ? new Set(labApps.map((a) => a.id)) : new Set());
  const bulk = async (action: "stop" | "restart") => {
    (await act.mutateAsync({ ids: chosen.map((a) => a.id), action })).forEach((j) => track(j.id));
    setSelected(new Set());
  };

  return (
    <div className="flex flex-col gap-4">
      {selectable && (
        <div className="surface flex flex-wrap items-center gap-3 rounded-2xl border p-3">
          <Label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" checked={allOn} ref={(el) => { if (el) el.indeterminate = chosen.length > 0 && !allOn; }}
              onChange={(e) => setAll(e.target.checked)} className="size-4 cursor-pointer accent-(--nav-labs)" />
            {chosen.length > 0 ? t("labs.dash.bulk.selected", { n: chosen.length }) : t("labs.dash.bulk.all")}
          </Label>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={chosen.length === 0 || act.isPending} onClick={() => bulk("stop")}>
              {act.isPending ? <Loader2 className="animate-spin" /> : <Power />} {t("labs.dash.bulk.stop")}
            </Button>
            <Button variant="outline" size="sm" disabled={chosen.length === 0 || act.isPending} onClick={() => bulk("restart")}>
              <RotateCw /> {t("labs.dash.bulk.restart")}
            </Button>
            {chosen.length > 0 && <BulkDeleteDialog apps={chosen} onDone={() => setSelected(new Set())} />}
          </div>
        </div>
      )}
      <div className="stagger flex flex-col gap-4">
        {groups.map(([tpl, list]) => {
          const lab = labTemplates.get(tpl) ?? null;
          return (
            <Group key={tpl} name={lab?.name ?? tpl} icon={list[0].icon_url} lab={lab} apps={list}
              running={list.filter((a) => RUNNING.includes(a.status)).length}
              selectable={selectable} picked={list.filter((a) => selected.has(a.id)).length}
              onPick={(on) => setSelected((sel) => { const n = new Set(sel); list.forEach((a) => (on ? n.add(a.id) : n.delete(a.id))); return n; })}>
              {list.map((a) => (
                <Row key={a.id} app={a} ip={ips.get(a.id) ?? null}
                  vpn={vpn ? { enabled: vpn.enabled, lab: vpn.labs.find((l) => l.slug === a.slug) } : null}
                  selectable={selectable} selected={selected.has(a.id)} onToggle={() => toggle(a.id)} />
              ))}
            </Group>
          );
        })}
      </div>
    </div>
  );
}

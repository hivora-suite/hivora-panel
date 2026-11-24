"use client";

import { Download, ExternalLink, KeyRound, Loader2, QrCode, Search, ShieldCheck, Shuffle, Trash2, UserMinus, UserPlus, Users, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TBody, TEmpty, Td, Th, THead, Tr } from "@/components/ui/table";
import { useSession } from "@/components/app-shell";
import { useTrackJob } from "@/components/job-toasts";
import { useCreateLabsStudents, useDeleteLabsStudent, useDisableLabsVpn, useDistributeLabs, useEnableLabsVpn, useLabsVpn, useSetStudentLabs, useSystemInfo, useUnassignLabs } from "@/lib/api/hooks";
import type { LabsVpnLab, LabsVpnStatus, LabsVpnStudent } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const BASE = "/api/v1/labs/vpn";
const cfgUrl = (id: number) => `${BASE}/students/${id}/config`;
const qrUrl = (id: number) => `${BASE}/students/${id}/qr`;
/** The class export: per student, a folder with their .conf and a .txt naming their targets. */
const zipUrl = (lang: string, lab?: string) => `${BASE}/configs.zip?lang=${lang}${lab ? `&lab=${encodeURIComponent(lab)}` : ""}`;
/** The students page, filtered on a lab or not. */
export const studentsHref = (lab?: string | null) => (lab ? `/labs/students/?lab=${encodeURIComponent(lab)}` : "/labs/students/");

const Dot = ({ on, title }: { on: boolean; title: string }) => (
  <span className={cn("inline-block size-2 shrink-0 rounded-full", on ? "bg-ok" : "bg-idle")} title={title} />
);

/** One lab: who is on it, who is connected, and its shortcuts. Clicking it opens its students. */
function LabCard({ lab }: { lab: LabsVpnLab }) {
  const { t, lang } = useI18n();
  return (
    <div className="surface flex flex-col gap-3 rounded-2xl border p-4">
      <Link href={studentsHref(lab.slug)} className="flex items-start justify-between gap-2 hover:[&_.font-semibold]:underline">
        <span className="min-w-0">
          <span className="block truncate font-semibold">{lab.name}</span>
          <span className="font-mono text-xs text-muted-foreground">{lab.ip}</span>
        </span>
        <Badge className="shrink-0 border-(--nav-labs)/40 bg-(--nav-labs)/10 text-(--nav-labs)">
          <Users className="size-3" /> {lab.students}
        </Badge>
      </Link>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Dot on={lab.online > 0} title={t("labs.vpn.online")} />
        {t("labs.vpn.onlineCount", { n: lab.online, total: lab.students })}
      </p>
      <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <Link href={`/app/?id=${lab.app_id}`} className="inline-flex items-center gap-1 text-(--nav-labs) hover:underline">
          <ExternalLink className="size-3.5" /> {t("labs.open")}
        </Link>
        {lab.students > 0 && (
          <a href={zipUrl(lang, lab.slug)} download className="inline-flex items-center gap-1 text-(--nav-labs) hover:underline">
            <Download className="size-3.5" /> {t("labs.vpn.zip")}
          </a>
        )}
      </div>
    </div>
  );
}

/** The class roster: paste names, one per line. */
function Roster() {
  const { t } = useI18n();
  const create = useCreateLabsStudents();
  const [text, setText] = useState("");
  const names = text.split(/[\n,;]/).map((n) => n.trim()).filter(Boolean);
  return (
    <form
      className="surface grid gap-3 rounded-2xl border p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (names.length) create.mutate(names, { onSuccess: () => setText("") });
      }}
    >
      <label htmlFor="roster" className="flex items-center gap-2 font-semibold">
        <UserPlus className="size-4 text-(--nav-labs)" /> {t("labs.vpn.roster")}
      </label>
      <textarea
        id="roster" rows={5} value={text} onChange={(e) => setText(e.target.value)}
        placeholder={t("labs.vpn.rosterHint")} spellCheck={false}
        className="field w-full rounded-md border border-input px-3 py-2 font-mono text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring"
      />
      {create.isError && <p className="text-xs text-danger">{t("labs.vpn.rosterError")}</p>}
      <Button type="submit" disabled={create.isPending || names.length === 0} className="justify-self-start">
        {create.isPending ? <Loader2 className="animate-spin" /> : <UserPlus />} {t("labs.vpn.addStudents", { n: names.length })}
      </Button>
    </form>
  );
}

function StudentRow({ student, labs, focus }: { student: LabsVpnStudent; labs: LabsVpnLab[]; focus: string | null }) {
  const { t } = useI18n();
  const set = useSetStudentLabs();
  const del = useDeleteLabsStudent();
  const toggle = (slug: string, on: boolean) =>
    set.mutate({ id: student.id, labs: on ? [...student.labs, slug] : student.labs.filter((s) => s !== slug) });
  return (
    <Tr>
      <Td>
        <span className="flex items-center gap-2">
          <Dot on={student.online} title={t(student.online ? "labs.vpn.online" : "labs.vpn.offline")} />
          <span className="truncate font-mono">{student.name}</span>
          {student.labs.length === 0 && <Badge className="border-warn/40 bg-warn/10 text-warn">{t("labs.vpn.noLab")}</Badge>}
        </span>
      </Td>
      {labs.map((lab) => (
        <Td key={lab.slug} className={cn("text-center", focus === lab.slug && "bg-(--nav-labs)/5")}>
          <input
            type="checkbox" className="size-4 accent-(--nav-labs)" disabled={set.isPending}
            checked={student.labs.includes(lab.slug)} onChange={(e) => toggle(lab.slug, e.target.checked)}
            aria-label={t("labs.vpn.assign", { student: student.name, lab: lab.name })}
          />
        </Td>
      ))}
      <Td>
        <span className="flex items-center justify-end gap-1">
          <Button asChild variant="ghost" size="icon" aria-label={t("labs.vpn.config")}>
            <a href={cfgUrl(student.id)} download={`${student.name}.conf`}><Download /></a>
          </Button>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={t("labs.vpn.qr")}><QrCode /></Button>
            </DialogTrigger>
            <DialogContent title={student.name} description={t("labs.vpn.qrTitle")} closeLabel={t("common.close")} className="max-w-sm">
              <img src={qrUrl(student.id)} alt={t("labs.vpn.qr")} className="mx-auto size-64 rounded-lg bg-white p-3" />
            </DialogContent>
          </Dialog>
          <Button
            variant="ghost" size="icon" aria-label={t("labs.vpn.delete")} disabled={del.isPending}
            onClick={() => window.confirm(t("labs.vpn.deleteConfirm", { name: student.name })) && del.mutate(student.id)}
          >
            <Trash2 className="text-danger" />
          </Button>
        </span>
      </Td>
    </Tr>
  );
}

/** Shared by both pages: labs off, loading, or the VPN not enabled yet (admin enables it). */
function VpnGate({ children }: { children: (status: LabsVpnStatus) => ReactNode }) {
  const { t } = useI18n();
  const { can } = useSession();
  const { data: info } = useSystemInfo();
  const { data: status, isLoading } = useLabsVpn(info?.labs ?? false);
  const enable = useEnableLabsVpn();
  const track = useTrackJob();

  if (info && !info.labs) return <p className="text-muted-foreground">{t("labs.off")}</p>;
  if (isLoading || !status) return <Loader2 className="animate-spin text-muted-foreground" aria-label={t("common.loading")} />;
  if (status.enabled) return children(status);
  return (
    <div className="surface mx-auto grid max-w-lg justify-items-center gap-4 rounded-2xl border p-8 text-center">
      <ShieldCheck className="size-10 text-(--nav-labs)" />
      <h2 className="text-xl font-semibold">{t("labs.vpn.title")}</h2>
      <p className="text-sm text-muted-foreground">{t("labs.vpn.enableHint")}</p>
      {can("admin") ? (
        <Button onClick={() => enable.mutate(undefined, { onSuccess: (r) => r.job_id && track(r.job_id) })} disabled={enable.isPending}>
          {enable.isPending ? <Loader2 className="animate-spin" /> : <KeyRound />} {t("labs.vpn.enable")}
        </Button>
      ) : (
        <p className="text-xs text-muted-foreground">{t("labs.vpn.adminOnly")}</p>
      )}
    </div>
  );
}

/** The VPN: its state, the labs it reaches (each with its students), and every config. */
/** Admin only: remove the VPN. The targets publish on the host again; student configs die.
 *  The request stays open until the VPN is actually gone, so one click is one outcome. */
function DisableVpn() {
  const { t } = useI18n();
  const { can } = useSession();
  const disable = useDisableLabsVpn();
  const [open, setOpen] = useState(false);
  if (!can("admin")) return null;
  const run = async () => {
    try {
      await disable.mutateAsync();
      setOpen(false); // the VPN is gone: VpnGate drops back to the enable screen
    } catch { /* keep the dialog open and show the reason */ }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!disable.isPending) setOpen(o); }}>
      <DialogTrigger asChild>
        <button type="button" className="inline-flex items-center gap-1 text-danger hover:underline">
          <X className="size-3.5" /> {t("labs.vpn.disable")}
        </button>
      </DialogTrigger>
      <DialogContent title={t("labs.vpn.disable")} description={t("labs.vpn.disableHint")} closeLabel={t("common.close")}>
        {disable.isPending && <p className="text-sm text-muted-foreground">{t("labs.vpn.disabling")}</p>}
        {disable.error instanceof Error && !disable.isPending && <p className="text-sm text-danger">{t("labs.vpn.disableBusy")}</p>}
        <div className="flex justify-end">
          <Button variant="destructive" onClick={run} disabled={disable.isPending}>
            {disable.isPending ? <Loader2 className="animate-spin" /> : <X />} {t("labs.vpn.disable")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function LabVpn() {
  const { t, lang } = useI18n();
  return (
    <VpnGate>
      {({ running, host, labs, students }) => (
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Badge className={cn("border", running ? "border-ok/40 bg-ok/10 text-ok" : "border-idle/40 bg-muted text-muted-foreground")}>
              <Dot on={running} title="" /> {t(running ? "labs.vpn.running" : "labs.vpn.stopped")}
            </Badge>
            {host && <span className="font-mono text-xs text-muted-foreground">{host}</span>}
            <span className="text-xs text-muted-foreground">
              {t("labs.vpn.summary", { students: students.length, online: students.filter((s) => s.online).length, labs: labs.length })}
            </span>
            <span className="ml-auto flex flex-wrap gap-4 text-xs">
              <Link href={studentsHref()} className="inline-flex items-center gap-1 text-(--nav-labs) hover:underline">
                <Users className="size-3.5" /> {t("labs.vpn.manageStudents")}
              </Link>
              {students.length > 0 && (
                <a href={zipUrl(lang)} download className="inline-flex items-center gap-1 text-(--nav-labs) hover:underline">
                  <Download className="size-3.5" /> {t("labs.vpn.zipAll")}
                </a>
              )}
              <DisableVpn />
            </span>
          </div>
          {labs.length === 0 ? (
            <p className="surface rounded-2xl border p-4 text-sm text-muted-foreground">
              {t("labs.vpn.noLabs")} <Link href="/labs/" className="text-(--nav-labs) hover:underline">{t("nav.killchain")}</Link>
            </p>
          ) : (
            <div className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {labs.map((l) => <LabCard key={l.slug} lab={l} />)}
            </div>
          )}
        </div>
      )}
    </VpnGate>
  );
}

/** The class: roster, distribution, and the students × labs table. Nothing else. */
export function LabStudents({ focus }: { focus: string | null }) {
  return <VpnGate>{(status) => <Students status={status} focus={focus} />}</VpnGate>;
}

function Students({ status: { labs, students }, focus }: { status: LabsVpnStatus; focus: string | null }) {
  const { t, lang } = useI18n();
  const router = useRouter();
  const distribute = useDistributeLabs();
  const unassign = useUnassignLabs();
  const [query, setQuery] = useState("");
  const [onlyUnassigned, setOnlyUnassigned] = useState(false);

  const focusLab = labs.find((l) => l.slug === focus) ?? null;
  const unassigned = students.filter((s) => s.labs.length === 0).length;
  const assigned = students.length - unassigned;
  const q = query.trim().toLowerCase();
  const shown = students.filter((s) =>
    (!focusLab || s.labs.includes(focusLab.slug)) && (!onlyUnassigned || s.labs.length === 0) && (!q || s.name.toLowerCase().includes(q)));
  const setFocus = (slug: string | null) => router.replace(studentsHref(slug === focus ? null : slug));

  return (
    <div className="flex flex-col gap-4">
      {/* The class export: one zip to put on a drive, a folder per student. */}
      <div className="surface flex flex-wrap items-center gap-3 rounded-2xl border p-4">
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{t("labs.students.export")}</p>
          <p className="text-xs text-muted-foreground">{t("labs.students.exportHint")}</p>
        </div>
        {students.length > 0 ? (
          <Button asChild>
            <a href={zipUrl(lang)} download><Download /> {t("labs.students.exportButton")}</a>
          </Button>
        ) : (
          <Button disabled><Download /> {t("labs.students.exportButton")}</Button>
        )}
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-[20rem_1fr]">
        <div className="grid gap-4">
          <Roster />
          <div className="surface grid gap-2 rounded-2xl border p-4">
            <p className="font-semibold">{t("labs.vpn.distribute")}</p>
            <p className="text-xs text-muted-foreground">{t("labs.vpn.distributeHint", { n: unassigned })}</p>
            <Button variant="outline" className="justify-self-start" disabled={distribute.isPending || unassigned === 0 || labs.length === 0} onClick={() => distribute.mutate(undefined)}>
              {distribute.isPending ? <Loader2 className="animate-spin" /> : <Shuffle />} {t("labs.vpn.distribute")}
            </Button>
            <Button
              variant="outline" className="justify-self-start text-danger" disabled={unassign.isPending || assigned === 0}
              onClick={() => window.confirm(t("labs.vpn.unassignConfirm", { n: assigned })) && unassign.mutate(undefined)}
            >
              {unassign.isPending ? <Loader2 className="animate-spin" /> : <UserMinus />} {t("labs.vpn.unassign")}
            </Button>
          </div>
        </div>

        <div className="surface min-w-0 overflow-hidden rounded-2xl border">
          <div className="flex flex-wrap items-center gap-2 border-b p-3">
            <div className="relative min-w-40 flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("labs.vpn.search")} className="pl-8" aria-label={t("labs.vpn.search")} />
            </div>
            <label className="flex items-center gap-2 text-xs">
              <input type="checkbox" className="accent-(--nav-labs)" checked={onlyUnassigned} onChange={(e) => setOnlyUnassigned(e.target.checked)} />
              {t("labs.vpn.onlyUnassigned")}
            </label>
            {focusLab && (
              <Badge className="border-(--nav-labs)/40 bg-(--nav-labs)/10 text-(--nav-labs)">
                {focusLab.name}
                <button type="button" onClick={() => setFocus(null)} aria-label={t("common.close")}><X className="size-3" /></button>
              </Badge>
            )}
          </div>
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <Tr>
                  <Th>{t("labs.vpn.student")}</Th>
                  {labs.map((l) => (
                    <Th key={l.slug} className={cn("text-center whitespace-nowrap", focus === l.slug && "text-(--nav-labs)")}>
                      <button type="button" onClick={() => setFocus(l.slug)} className="hover:underline">{l.name}</button>
                    </Th>
                  ))}
                  <Th><span className="sr-only">{t("labs.vpn.actions")}</span></Th>
                </Tr>
              </THead>
              <TBody>
                {shown.length === 0 && <TEmpty colSpan={labs.length + 2}>{t(students.length ? "labs.vpn.noMatch" : "labs.vpn.noUsers")}</TEmpty>}
                {shown.map((s) => <StudentRow key={s.id} student={s} labs={labs} focus={focus} />)}
              </TBody>
            </Table>
          </div>
        </div>
      </div>
    </div>
  );
}

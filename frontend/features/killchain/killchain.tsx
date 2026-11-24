"use client";

import { ChevronRight, Crosshair, ExternalLink, Flag, HardDriveDownload, Hammer, Loader2, RadioTower, Rocket, Search, Send, ShieldAlert, SlidersHorizontal, X } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";

import { AppIcon } from "@/components/app-icon";
import { useTrackJob } from "@/components/job-toasts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { TileSkeletons } from "@/components/ui/skeleton";
import { useDeployBatch, useDeployCapacity, useLabsVpn, usePlanBatch, useSystemInfo, useTemplate, useTemplates, type BatchItem, type BatchResult } from "@/lib/api/hooks";
import { GeneratedForm, initialValues, type FieldDef, type Values } from "@/features/deploy/generated-form";
import type { BatchPlanItem, TemplateSummary } from "@/lib/api/client";
import { useI18n, type Localized, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Phase = "recon" | "weaponization" | "delivery" | "exploitation" | "installation" | "c2" | "actions";
type Difficulty = "easy" | "medium" | "hard";
type LabInfo = { phase: Phase; cves: string[]; os: string[]; tech: string[]; difficulty?: Difficulty | null; summary: Localized; needs_vpn?: boolean };
type Lab = TemplateSummary & { lab: LabInfo };

const PHASES: { key: Phase; icon: typeof Search }[] = [
  { key: "recon", icon: Search },
  { key: "weaponization", icon: Hammer },
  { key: "delivery", icon: Send },
  { key: "exploitation", icon: Crosshair },
  { key: "installation", icon: HardDriveDownload },
  { key: "c2", icon: RadioTower },
  { key: "actions", icon: Flag },
];

// The tags that name a kind of flaw; the others are families (cms, database…).
const VULNS = [
  "sql-injection", "deserialization", "expression-injection", "ssti", "environment-injection", "xxe", "ssrf", "path-traversal",
  "file-upload", "file-deletion", "auth-bypass", "hard-coding", "info-disclosure", "xss", "privilege-escalation", "dos", "rce",
] as const;
const isVuln = (tag: string) => (VULNS as readonly string[]).includes(tag);

const DIFF: Record<Difficulty, string> = {
  easy: "border-ok/40 bg-ok/10 text-ok",
  medium: "border-warn/40 bg-warn/10 text-warn",
  hard: "border-danger/40 bg-danger/10 text-danger",
};

function isLab(tp: TemplateSummary): tp is Lab {
  return tp.category === "security-lab" && tp.lab != null;
}

/** The deploy menu: choose how many copies, tune the container, preview IPs/ports, confirm. */
function DeployMenu({ tp }: { tp: Lab }) {
  const { t } = useI18n();
  const plan = usePlanBatch();
  const deploy = useDeployBatch();
  const track = useTrackJob();
  const { data: cap } = useDeployCapacity(tp.slug, true);
  const { data: detail } = useTemplate(tp.slug);
  const max = cap?.max_copies ?? 25;
  const [count, setCount] = useState(1);
  const [preview, setPreview] = useState<BatchPlanItem[]>([]);
  const [results, setResults] = useState<BatchResult[] | null>(null);

  // The container settings worth tuning at creation: every form field except the port (it is
  // auto-assigned per copy). Each copy gets the same values.
  const fields = useMemo(() => {
    const form = detail?.form as { basic?: FieldDef[]; advanced?: FieldDef[] } | undefined;
    return [...(form?.basic ?? []), ...(form?.advanced ?? [])].filter((f) => f.type !== "port");
  }, [detail]);
  const [values, setValues] = useState<Values>({});
  useEffect(() => { if (fields.length) setValues(initialValues(fields)); }, [fields]);
  const inputs = useMemo(() => JSON.stringify(values), [values]);

  // Never let the quantity exceed what the host can take.
  useEffect(() => { if (count > max) setCount(max); }, [max, count]);

  useEffect(() => {
    setResults(null);
    const h = setTimeout(() => plan.mutate({ template: tp.slug, count, inputs: JSON.parse(inputs) }, { onSuccess: setPreview }), 250);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count, tp.slug, inputs]);

  const conflicts = preview.some((p) => p.conflicts.length > 0);
  const confirm = async () => {
    const items: BatchItem[] = preview.map((p) => ({ template: tp.slug, name: p.name, inputs: p.inputs as Record<string, unknown> }));
    const results = await deploy.mutateAsync(items);
    results.forEach((r) => r.app && track(r.app.job.id));
    setResults(results);
  };

  return (
    <DialogContent title={t("labs.deploy.title", { name: tp.name })} description={t("labs.deploy.sub")} closeLabel={t("common.close")} className="max-w-2xl">
      <div className="flex items-center gap-3">
        <label htmlFor={`qty-${tp.slug}`} className="text-sm font-medium">{t("labs.deploy.quantity")}</label>
        <Input id={`qty-${tp.slug}`} type="number" min={1} max={max} value={count}
          onChange={(e) => setCount(Math.max(1, Math.min(max, Number(e.target.value) || 1)))} className="w-24" />
        {cap && <span className="text-xs text-muted-foreground">{t("labs.deploy.max", { n: max, mem: cap.memory_each_mb, cpus: cap.cpus })}</span>}
      </div>

      {fields.length > 0 && !results && (
        <div className="rounded-xl border p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("labs.deploy.customize")}</p>
          <GeneratedForm fields={fields} values={values} errors={{}} onChange={(id, v) => setValues((s) => ({ ...s, [id]: v }))} />
        </div>
      )}

      <div className="rounded-xl border">
        <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 border-b bg-muted/40 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <span>{t("labs.deploy.col.name")}</span><span>{t("labs.deploy.col.ports")}</span><span>{t("labs.deploy.col.ip")}</span>
        </div>
        {plan.isPending && preview.length === 0 ? (
          <p className="flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> {t("common.loading")}</p>
        ) : (
          <ul className="max-h-64 overflow-y-auto">
            {preview.map((p) => {
              const res = results?.find((r) => r.app?.app.name === p.name);
              return (
                <li key={p.name} className="grid grid-cols-[1fr_auto_auto] items-center gap-x-4 border-b px-3 py-2 text-sm last:border-0">
                  <span className="truncate font-mono">
                    {p.name}
                    {res && (res.ok
                      ? <Link href={`/app/?id=${res.app?.app.id}`} className="ml-2 text-ok hover:underline">✓</Link>
                      : <span className="ml-2 text-danger">✗ {res.error}</span>)}
                  </span>
                  <span className="font-mono text-xs">{p.ports.map((pt) => pt.host_port ?? "—").join(", ") || "—"}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {p.ips.join(" · ") || "—"}
                    {p.conflicts.length > 0 && <Badge className="ml-2 border-danger/40 bg-danger/10 text-danger">{t("labs.deploy.conflict")}</Badge>}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-muted-foreground">
          {results ? t("labs.deploy.result", { ok: results.filter((r) => r.ok).length, total: results.length }) : conflicts ? t("labs.deploy.hasConflict") : ""}
        </span>
        {results ? (
          <DialogClose asChild><Button variant="outline">{t("common.close")}</Button></DialogClose>
        ) : (
          <Button onClick={confirm} disabled={deploy.isPending || conflicts || preview.length === 0}>
            {deploy.isPending ? <Loader2 className="animate-spin" /> : <Rocket />} {t("labs.deploy.confirm", { n: count })}
          </Button>
        )}
      </div>
    </DialogContent>
  );
}

/** A family tag in words (cms → CMS), or as it is when the panel has no name for it. */
function useFamily() {
  const { t } = useI18n();
  return (tag: string) => {
    const key = `labs.family.${tag}` as MessageKey;
    const word = t(key);
    return word === key ? tag : word; // t gives the key back when it has no text
  };
}

function LabCard({ tp, vpnOn }: { tp: Lab; vpnOn: boolean }) {
  const { t, l } = useI18n();
  const family = useFamily();
  const { lab } = tp;
  const blocked = Boolean(lab.needs_vpn) && !vpnOn; // a target to scan: only behind the labs VPN
  return (
    <div className="surface flex flex-col gap-3 rounded-2xl border p-4">
      <div className="flex items-start gap-3">
        <AppIcon src={tp.icon_url} name={tp.name} className="size-11 rounded-xl" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-semibold">{tp.name}</h3>
            {lab.difficulty && <Badge className={cn("border", DIFF[lab.difficulty])}>{t(`labs.diff.${lab.difficulty}` as MessageKey)}</Badge>}
            {lab.needs_vpn && <Badge className="border-(--nav-labs)/40 bg-(--nav-labs)/10 text-(--nav-labs)">{t("labs.needsVpn")}</Badge>}
          </div>
          {/* The flaw in plain words; the source's own title below (to find it in its docs). */}
          <p className="text-sm font-medium text-(--nav-labs)">{l(lab.summary) || l(tp.description)}</p>
          {l(lab.summary) && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{l(tp.description)}</p>}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {lab.os.map((o) => <Badge key={o} className="border-border bg-muted">{o}</Badge>)}
        {tp.arch.length === 1 && (
          <Badge className={cn("border", tp.compatible ? "border-border bg-muted" : "border-warn/50 text-warn")}
            title={tp.compatible ? undefined : t("catalog.incompatibleHelp")}>
            {t(`catalog.only.${tp.arch[0]}` as MessageKey)}
          </Badge>
        )}
        {lab.tech.filter((x) => !isVuln(x)).map((x) => <Badge key={x} className="border-border bg-muted text-muted-foreground">{family(x)}</Badge>)}
        {lab.cves.map((c) => (
          <a key={c} href={`https://nvd.nist.gov/vuln/detail/${c}`} target="_blank" rel="noreferrer">
            <Badge className="border-danger/40 bg-danger/10 font-mono text-danger hover:underline">{c}</Badge>
          </a>
        ))}
      </div>
      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        {/* The guide is long: it opens in its own tab, as a document. */}
        <Button asChild variant="ghost" size="sm" className="gap-1.5 text-(--nav-labs)">
          <a href={`/solution/?lab=${tp.slug}`} target="_blank" rel="noopener"><ExternalLink /> {t("labs.doc.open")}</a>
        </Button>
        {!tp.compatible ? (
          <Button variant="outline" size="sm" disabled title={t("catalog.incompatibleHelp")}><Rocket /> {t("catalog.incompatible")}</Button>
        ) : blocked ? (
          <Button asChild variant="outline" size="sm" className="text-(--nav-labs)">
            <Link href="/labs/vpn"><ShieldAlert /> {t("labs.needsVpn.enable")}</Link>
          </Button>
        ) : (
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm"><Rocket /> {t("labs.deploy")}</Button>
            </DialogTrigger>
            <DeployMenu tp={tp} />
          </Dialog>
        )}
      </div>
    </div>
  );
}

export function KillChain() {
  const { t, l } = useI18n();
  const family = useFamily();
  const { data: info } = useSystemInfo();
  const { data: templates, isLoading } = useTemplates();
  const { data: vpn } = useLabsVpn();
  const [phase, setPhase] = useState<Phase | null>(null);
  const [os, setOs] = useState("all");
  const [tech, setTech] = useState("all"); // a family
  const [vuln, setVuln] = useState("all");
  const [diff, setDiff] = useState("all");
  const [cve, setCve] = useState("all"); // "all" | "with" | "without" | a year
  const [q, setQ] = useState("");
  const [more, setMore] = useState(false); // the extra filters, folded by default
  const reset = () => { setPhase(null); setOs("all"); setTech("all"); setVuln("all"); setDiff("all"); setCve("all"); setQ(""); };

  const labs = useMemo(() => (templates ?? []).filter(isLab), [templates]);
  const counts = useMemo(() => {
    const c = {} as Record<Phase, number>;
    for (const p of PHASES) c[p.key] = labs.filter((tp) => tp.lab.phase === p.key).length;
    return c;
  }, [labs]);
  const allOs = useMemo(() => [...new Set(labs.flatMap((tp) => tp.lab.os))], [labs]);
  const allTech = useMemo(() => [...new Set(labs.flatMap((tp) => tp.lab.tech.filter((x) => !isVuln(x))))].sort(), [labs]);
  const allVulns = VULNS.filter((v) => labs.some((tp) => tp.lab.tech.includes(v)));
  const allDiff = (["easy", "medium", "hard"] as const).filter((d) => labs.some((tp) => tp.lab.difficulty === d));
  // CVE-2021-44228 -> "2021", newest first.
  const allYears = useMemo(() => [...new Set(labs.flatMap((tp) => tp.lab.cves.map((c) => c.split("-")[1])))].sort().reverse(), [labs]);
  // The filters in use, as removable chips (the phase and search show where they are set).
  const active = [
    diff !== "all" && { key: "diff", label: t(`labs.diff.${diff}` as MessageKey), clear: () => setDiff("all") },
    cve !== "all" && { key: "cve", label: cve === "with" ? t("labs.filter.cveWith") : cve === "without" ? t("labs.filter.cveWithout") : t("labs.filter.cveYear", { year: cve }), clear: () => setCve("all") },
    vuln !== "all" && { key: "vuln", label: t(`labs.vuln.${vuln}` as MessageKey), clear: () => setVuln("all") },
    tech !== "all" && { key: "tech", label: family(tech), clear: () => setTech("all") },
    os !== "all" && { key: "os", label: os, clear: () => setOs("all") },
  ].filter((f): f is { key: string; label: string; clear: () => void } => !!f);
  const cveOk = (cves: string[]) =>
    cve === "all" || (cve === "with" ? cves.length > 0 : cve === "without" ? cves.length === 0 : cves.some((c) => c.split("-")[1] === cve));
  const needle = q.trim().toLowerCase();

  const shown = labs.filter(
    (tp) => (!phase || tp.lab.phase === phase) && (os === "all" || tp.lab.os.includes(os)) && (tech === "all" || tp.lab.tech.includes(tech))
      && (vuln === "all" || tp.lab.tech.includes(vuln))
      && (diff === "all" || tp.lab.difficulty === diff) && cveOk(tp.lab.cves)
      && (!needle || [tp.name, tp.slug, l(tp.description), l(tp.lab.summary), ...tp.lab.cves, ...tp.lab.tech].some((s) => s.toLowerCase().includes(needle))),
  );

  if (info && !info.labs) return <p className="text-muted-foreground">{t("labs.off")}</p>;

  return (
    <div className="flex flex-col gap-6">
      {/* The kill chain, as one line of chips (each filters by its phase), then one toolbar. */}
      <div className="surface grid gap-3 rounded-2xl border p-3">
        <div className="flex items-center gap-1 overflow-x-auto pb-0.5">
          {PHASES.map((p, i) => {
            const on = phase === p.key;
            const n = counts[p.key];
            return (
              <Fragment key={p.key}>
                {i > 0 && <ChevronRight aria-hidden className="size-3.5 shrink-0 text-muted-foreground/50" />}
                <button type="button" onClick={() => setPhase(on ? null : p.key)} aria-pressed={on}
                  className={cn("flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                    on ? "border-(--nav-labs) bg-(--nav-labs) text-white"
                      : n > 0 ? "border-(--nav-labs)/40 text-foreground hover:bg-(--nav-labs)/10" : "border-border text-muted-foreground")}>
                  <p.icon className="size-3.5" />
                  {t(`labs.phase.${p.key}` as MessageKey)}
                  {n > 0 && <span className={cn("font-mono", on ? "text-white/80" : "text-(--nav-labs)")}>{n}</span>}
                </button>
              </Fragment>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search aria-hidden className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("labs.filter.search")} aria-label={t("labs.filter.search")} className="h-9 pl-8" />
          </div>
          <Button variant={more ? "default" : "outline"} size="sm" aria-expanded={more} onClick={() => setMore((m) => !m)}>
            <SlidersHorizontal /> {t("labs.filter.more")}
            {active.length > 0 && <span className="rounded-full bg-(--nav-labs) px-1.5 text-[11px] text-white">{active.length}</span>}
          </Button>
          <span className="text-sm whitespace-nowrap text-muted-foreground">{t("labs.filter.count", { n: shown.length, total: labs.length })}</span>
        </div>
        {more && (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <Select value={vuln} onChange={(e) => setVuln(e.target.value)} aria-label={t("labs.filter.vuln")} className="h-9">
              <option value="all">{t("labs.filter.vuln")}</option>
              {allVulns.map((v) => <option key={v} value={v}>{t(`labs.vuln.${v}` as MessageKey)}</option>)}
            </Select>
            <Select value={diff} onChange={(e) => setDiff(e.target.value)} aria-label={t("labs.filter.diff")} className="h-9">
              <option value="all">{t("labs.filter.diff")}</option>
              {allDiff.map((d) => <option key={d} value={d}>{t(`labs.diff.${d}` as MessageKey)}</option>)}
            </Select>
            <Select value={cve} onChange={(e) => setCve(e.target.value)} aria-label={t("labs.filter.cve")} className="h-9">
              <option value="all">{t("labs.filter.cve")}</option>
              <option value="with">{t("labs.filter.cveWith")}</option>
              <option value="without">{t("labs.filter.cveWithout")}</option>
              {allYears.map((y) => <option key={y} value={y}>{t("labs.filter.cveYear", { year: y })}</option>)}
            </Select>
            <Select value={tech} onChange={(e) => setTech(e.target.value)} aria-label={t("labs.filter.tech")} className="h-9">
              <option value="all">{t("labs.filter.tech")}</option>
              {allTech.map((x) => <option key={x} value={x}>{family(x)}</option>)}
            </Select>
            <Select value={os} onChange={(e) => setOs(e.target.value)} aria-label={t("labs.filter.os")} className="h-9">
              <option value="all">{t("labs.filter.os")}</option>
              {allOs.map((o) => <option key={o} value={o}>{o}</option>)}
            </Select>
          </div>
        )}
        {active.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {active.map((f) => (
              <button key={f.key} type="button" onClick={f.clear} aria-label={t("labs.filter.remove", { name: f.label })}
                className="flex items-center gap-1 rounded-md border border-(--nav-labs)/40 bg-(--nav-labs)/10 px-2 py-0.5 text-xs text-(--nav-labs) hover:bg-(--nav-labs)/20">
                {f.label} <X className="size-3" />
              </button>
            ))}
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={reset}>{t("labs.filter.reset")}</Button>
          </div>
        )}
      </div>

      {isLoading ? (
        <TileSkeletons label={t("common.loading")} />
      ) : shown.length === 0 ? (
        <div className="surface flex items-center gap-3 rounded-2xl border p-6 text-muted-foreground">
          <ShieldAlert className="size-5" /> {t("labs.empty")}
        </div>
      ) : (
        // Like the catalog: what runs on this machine first, the other architectures below.
        [
          { key: "compatible", items: shown.filter((tp) => tp.compatible) },
          { key: "others", items: shown.filter((tp) => !tp.compatible) },
        ].map(({ key, items }) => items.length > 0 && (
          <details key={key} open className="group">
            <summary className="mb-3 flex cursor-pointer list-none items-center gap-2 text-lg font-semibold">
              <ChevronRight aria-hidden className="size-4 transition-transform group-open:rotate-90" />
              {t(`labs.section.${key}` as MessageKey, { arch: info ? t(`arch.${info.arch}` as MessageKey) : "" })}
              <span className="font-mono text-sm font-normal text-muted-foreground">{items.length}</span>
            </summary>
            <div className={cn("stagger grid gap-4 md:grid-cols-2 xl:grid-cols-3", key === "others" && "opacity-70")}>
              {items.map((tp) => <LabCard key={tp.slug} tp={tp} vpnOn={Boolean(vpn?.enabled)} />)}
            </div>
          </details>
        ))
      )}
    </div>
  );
}

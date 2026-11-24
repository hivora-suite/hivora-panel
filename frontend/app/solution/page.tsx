"use client";

import { ListTree, Loader2, Minus, Plus, Printer, ShieldAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { parseSolution, SolutionDoc } from "@/features/killchain/solution-doc";
import { ApiError } from "@/lib/api/client";
import { useTemplate } from "@/lib/api/hooks";
import { LANGS, useI18n, type Localized, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type LabInfo = { phase: string; cves: string[]; difficulty?: string | null; solution: Localized };

const ZOOMS = [70, 80, 90, 100, 110, 125, 150, 175, 200];

/** A lab's solution in its own tab, laid out like a PDF reader; printing gives a clean PDF. */
function Reader() {
  const { t, l, lang, setLang } = useI18n();
  const router = useRouter();
  const slug = useSearchParams().get("lab") ?? "";
  // Only this lab (a few KB), not the whole catalog with every guide (over 1 MB).
  const { data: tp, error, isPending } = useTemplate(slug);
  const [zoom, setZoom] = useState(100);
  const [toc, setToc] = useState(true);

  const lab = tp?.lab as LabInfo | null | undefined;
  const blocks = useMemo(() => parseSolution(l(lab?.solution)), [lab, l]);
  const headings = blocks.filter((b) => b.kind === "h");
  const both = !!lab && typeof lab.solution === "object" && LANGS.every((x) => lab.solution && typeof lab.solution === "object" && lab.solution[x]);

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace("/login/");
  }, [error, router]);
  useEffect(() => {
    if (tp) document.title = `${tp.name} · ${t("labs.solution.title")}`;
  }, [tp, t]);

  const step = (d: number) => setZoom((z) => ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, ZOOMS.indexOf(z) + d))]);
  const bar = "flex size-8 items-center justify-center rounded-md text-zinc-300 hover:bg-white/10 hover:text-white disabled:opacity-40";

  return (
    <div className="min-h-screen bg-zinc-600 text-zinc-100 print:bg-white">
      {/* The toolbar, as in a PDF reader. */}
      <header className="sticky top-0 z-10 flex h-12 items-center gap-2 border-b border-black/40 bg-zinc-800 px-3 shadow-md print:hidden">
        <button type="button" className={cn(bar, toc && "bg-white/10 text-white")} onClick={() => setToc((v) => !v)}
          aria-pressed={toc} aria-label={t("labs.doc.toc")} title={t("labs.doc.toc")} disabled={headings.length === 0}>
          <ListTree className="size-4" />
        </button>
        <div className="min-w-0 flex-1 truncate text-sm">
          <span className="font-medium text-white">{tp?.name ?? slug}</span>
          <span className="ml-2 text-zinc-400">{t("labs.solution.title")}</span>
        </div>
        {both && (
          <div className="flex rounded-md bg-black/30 p-0.5 text-xs">
            {LANGS.map((x) => (
              <button key={x} type="button" onClick={() => setLang(x)} aria-pressed={lang === x}
                className={cn("rounded px-2 py-1 uppercase", lang === x ? "bg-white/15 text-white" : "text-zinc-400 hover:text-white")}>{x}</button>
            ))}
          </div>
        )}
        <div className="flex items-center gap-0.5 rounded-md bg-black/30 px-0.5">
          <button type="button" className={bar} onClick={() => step(-1)} disabled={zoom === ZOOMS[0]} aria-label={t("labs.doc.zoomOut")} title={t("labs.doc.zoomOut")}><Minus className="size-4" /></button>
          <button type="button" className="w-12 text-center font-mono text-xs text-zinc-200" onClick={() => setZoom(100)} title={t("labs.doc.zoomReset")}>{zoom} %</button>
          <button type="button" className={bar} onClick={() => step(1)} disabled={zoom === ZOOMS[ZOOMS.length - 1]} aria-label={t("labs.doc.zoomIn")} title={t("labs.doc.zoomIn")}><Plus className="size-4" /></button>
        </div>
        <button type="button" onClick={() => window.print()} className="flex h-8 items-center gap-1.5 rounded-md bg-white/10 px-3 text-sm text-white hover:bg-white/20" disabled={!lab}>
          <Printer className="size-4" /> <span className="hidden sm:inline">{t("labs.doc.print")}</span>
        </button>
      </header>

      <div className="flex">
        {toc && headings.length > 0 && (
          <nav aria-label={t("labs.doc.toc")} className="sticky top-12 hidden h-[calc(100vh-3rem)] w-64 shrink-0 overflow-y-auto border-r border-black/30 bg-zinc-700 p-3 text-sm lg:block print:hidden">
            <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">{t("labs.doc.toc")}</p>
            {headings.map((h) => h.kind === "h" && (
              <a key={h.id} href={`#${h.id}`} className={cn("block truncate rounded px-2 py-1 text-zinc-200 hover:bg-white/10 hover:text-white", h.level === 2 && "pl-5 text-zinc-400")}>{h.text}</a>
            ))}
          </nav>
        )}

        <main className="flex-1 overflow-x-auto px-4 py-8 print:p-0">
          {isPending && slug ? (
            <p className="flex items-center justify-center gap-2 text-zinc-300"><Loader2 className="size-4 animate-spin" /> {t("common.loading")}</p>
          ) : !lab ? (
            <p className="flex items-center justify-center gap-2 text-zinc-200"><ShieldAlert className="size-5" /> {error ? t("labs.doc.error") : t("labs.doc.missing")}</p>
          ) : (
            // The paper sheet: A4 wide, always light like a printed page.
            <article style={{ zoom: zoom / 100 }}
              className="mx-auto min-h-[297mm] w-full max-w-[210mm] bg-white px-[18mm] py-[16mm] font-sans text-[15px] text-zinc-800 shadow-[0_4px_24px_rgba(0,0,0,0.45)] print:max-w-none print:p-0 print:shadow-none print:[zoom:1]">
              <header className="mb-6 border-b-2 border-zinc-900 pb-4">
                <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
                  {t(`labs.phase.${lab.phase}` as MessageKey)}{lab.difficulty && ` · ${t(`labs.diff.${lab.difficulty}` as MessageKey)}`}
                </p>
                <h1 className="mt-1 text-3xl font-bold text-zinc-900">{tp?.name}</h1>
                {lab.cves.length > 0 && <p className="mt-1 font-mono text-sm text-red-700">{lab.cves.join(" · ")}</p>}
              </header>
              {blocks.length > 0 ? <SolutionDoc blocks={blocks} /> : <p className="text-zinc-500">{t("labs.solution.none")}</p>}
            </article>
          )}
        </main>
      </div>
    </div>
  );
}

export default function SolutionPage() {
  return (
    <Suspense>
      <Reader />
    </Suspense>
  );
}

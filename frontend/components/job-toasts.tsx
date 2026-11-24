"use client";

import { ChevronDown, CircleCheck, CircleX, LoaderCircle, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { JobProgress } from "@/components/job-progress";
import { Button } from "@/components/ui/button";
import { useJob } from "@/lib/api/hooks";
import { useI18n, type MessageKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const CLOSE_AFTER_MS = 5_000; // after the job ends well; a failure stays until closed
const LEAVE_MS = 560; // the slide out, then the stack closes the gap
const SUMMARY_FROM = 3; // from this many pop-ups, one summary stands for them (unfolds on a click)

type Tracked = { id: number; onFinished?: (status: string) => void };
type Track = (jobId: number, onFinished?: (status: string) => void) => void;

const JobToastsContext = createContext<Track>(() => {});

/** Follow a job in a pop-up (bottom right, over the page): `track(jobId, onFinished?)`. */
export const useTrackJob = () => useContext(JobToastsContext);

/** The jobs started from the panel's pages, each in a pop-up stacked over the page (nothing
 *  moves): closed by its button, or 5 s after the job succeeded (paused while hovered). */
export function JobToasts({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [jobs, setJobs] = useState<Tracked[]>([]);
  const track = useCallback<Track>((id, onFinished) => {
    setJobs((list) => (list.some((j) => j.id === id) ? list : [...list, { id, onFinished }]));
  }, []);
  const [ends, setEnds] = useState<Record<number, string>>({}); // job id -> its final status
  const [expanded, setExpanded] = useState(false);
  const close = useCallback((id: number) => setJobs((list) => list.filter((j) => j.id !== id)), []);
  const ended = useCallback((id: number, status: string) => setEnds((e) => ({ ...e, [id]: status })), []);
  const closeAll = useCallback(() => { setJobs([]); setEnds({}); setExpanded(false); }, []);
  const summary = jobs.length >= SUMMARY_FROM;
  return (
    <JobToastsContext.Provider value={track}>
      {children}
      <section
        aria-label={t("job.toasts")}
        className="pointer-events-none fixed inset-x-4 bottom-4 z-50 grid justify-items-end sm:inset-x-auto sm:right-6 sm:bottom-6"
      >
        {/* The pop-ups stay mounted when folded: they keep following their job (and close). */}
        <div className={cn("grid max-h-[70vh] w-full justify-items-end overflow-y-auto", summary && !expanded && "hidden")}>
          {jobs.map((j) => (
            <JobToast key={j.id} job={j} hold={summary} onClose={() => close(j.id)} onEnded={(st) => ended(j.id, st)} />
          ))}
        </div>
        {summary && (
          <JobSummary
            statuses={jobs.map((j) => ends[j.id])}
            expanded={expanded}
            onToggle={() => setExpanded((x) => !x)}
            onCloseAll={closeAll}
          />
        )}
      </section>
    </JobToastsContext.Provider>
  );
}

/** One line for many jobs: how many run, succeeded, failed; a bar of how many are done. */
function JobSummary({ statuses, expanded, onToggle, onCloseAll }: {
  statuses: (string | undefined)[]; expanded: boolean; onToggle: () => void; onCloseAll: () => void;
}) {
  const { t } = useI18n();
  const running = statuses.filter((s) => s === undefined).length;
  const failed = statuses.filter((s) => s === "failed" || s === "interrupted").length;
  const ok = statuses.length - running - failed;
  const done = Math.round(((statuses.length - running) / statuses.length) * 100);
  // All went well: the whole stack goes after the usual delay. A failure keeps it.
  const allOk = running === 0 && failed === 0;
  useEffect(() => {
    if (!allOk) return;
    const timer = setTimeout(onCloseAll, CLOSE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [allOk, onCloseAll]);
  return (
    <div role="status" className="surface pointer-events-auto mt-3 grid w-full gap-3 rounded-xl border p-4 shadow-lg sm:w-96">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 font-medium">
          {running > 0 ? (
            <LoaderCircle aria-hidden className="size-4 animate-spin text-primary" />
          ) : failed > 0 ? (
            <CircleX aria-hidden className="size-5 text-danger" />
          ) : (
            <CircleCheck aria-hidden className="size-5 text-ok" />
          )}
          {t("job.summary.title", { n: statuses.length })}
        </span>
        <span className="flex gap-1">
          <Button variant="ghost" size="icon" className="size-8" aria-expanded={expanded}
            aria-label={t(expanded ? "job.summary.fold" : "job.summary.unfold")} onClick={onToggle}>
            <ChevronDown className={cn("transition-transform", !expanded && "rotate-180")} />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" aria-label={t("job.summary.closeAll")} onClick={onCloseAll}>
            <X />
          </Button>
        </span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <span className="text-muted-foreground">{t("job.summary.running", { n: running })}</span>
        <span className="text-ok">{t("job.summary.ok", { n: ok })}</span>
        {failed > 0 && <span className="text-danger">{t("job.summary.failed", { n: failed })}</span>}
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn("h-full transition-[width] duration-500", failed > 0 ? "bg-danger" : "bg-primary")} style={{ width: `${done}%` }} />
      </div>
    </div>
  );
}

// `hold`: under a summary, a pop-up does not close by itself (the summary closes them all).
function JobToast({ job, hold, onClose, onEnded }: { job: Tracked; hold: boolean; onClose: () => void; onEnded: (status: string) => void }) {
  const { t } = useI18n();
  const { data } = useJob(job.id);
  const [ended, setEnded] = useState<string | null>(null);
  const [open, setOpen] = useState(false); // its room in the stack, grown after mount
  const [leaving, setLeaving] = useState(false);
  const [paused, setPaused] = useState(false);
  const remaining = useRef(CLOSE_AFTER_MS);
  const ok = ended === "succeeded" || ended === "cancelled";

  useEffect(() => {
    const frame = requestAnimationFrame(() => setOpen(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  const leave = useCallback(() => {
    setLeaving(true);
    setTimeout(onClose, LEAVE_MS);
  }, [onClose]);
  // The countdown (a timer, so it holds with reduced motion too): paused while hovered.
  useEffect(() => {
    if (!ok || hold || paused || leaving) return;
    const started = Date.now();
    const timer = setTimeout(leave, remaining.current);
    return () => {
      clearTimeout(timer);
      remaining.current -= Date.now() - started;
    };
  }, [ok, hold, paused, leaving, leave]);

  const title = data ? t(`job.kind.${data.kind}` as MessageKey) : t("common.loading");
  return (
    // Its room in the stack grows and shrinks (grid rows 0fr <-> 1fr): the others glide.
    <div
      className={cn(
        "grid w-full transition-[grid-template-rows,margin] duration-[420ms] ease-(--ease-spring) sm:w-96",
        open && !leaving ? "mt-3 grid-rows-[1fr]" : "mt-0 grid-rows-[0fr]",
        leaving && "delay-150",
      )}
    >
      <div className="min-h-0">
        <div
          role="status"
          aria-label={title}
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          onFocus={() => setPaused(true)}
          onBlur={() => setPaused(false)}
          className={cn(
            "surface pointer-events-auto relative grid gap-3 overflow-hidden rounded-xl border p-4 shadow-lg",
            "transition-[translate,box-shadow] duration-300 ease-(--ease-spring) hover:-translate-y-1 hover:shadow-xl",
            leaving ? "animate-toast-out" : ended === "failed" || ended === "interrupted" ? "animate-shake" : "animate-toast-in",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <span className="flex items-center gap-2 font-medium">
              {ended === null ? (
                <LoaderCircle aria-hidden className="size-4 animate-spin text-primary" />
              ) : ok ? (
                <CircleCheck aria-hidden className="animate-pop size-5 text-ok" />
              ) : (
                <CircleX aria-hidden className="animate-pop size-5 text-danger" />
              )}
              {title}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="-mt-1.5 -mr-2 size-8 transition-transform duration-300 ease-(--ease-spring) hover:rotate-90 hover:scale-110 active:scale-90"
              aria-label={t("common.close")}
              onClick={leave}
            >
              <X />
            </Button>
          </div>
          <JobProgress
            jobId={job.id}
            compact
            onFinished={(status) => {
              setEnded(status);
              onEnded(status);
              job.onFinished?.(status);
            }}
          />
          {ok && (
            <div
              aria-hidden
              className="absolute inset-x-0 bottom-0 h-1 origin-left bg-primary/60 animate-[hv-countdown_linear_forwards]"
              style={{ animationDuration: `${CLOSE_AFTER_MS}ms`, animationPlayState: paused ? "paused" : "running" }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

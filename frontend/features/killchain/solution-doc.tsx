"use client";

import { Check, Copy } from "lucide-react";
import { Fragment, type ReactNode } from "react";

import { useCopy } from "@/components/copy";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/**
 * A lab's solution, a small line format (templates hold no Markdown engine):
 * `# ` / `## ` headings, consecutive `$ ` lines one command block, `- ` / `* ` / `1. ` list
 * items, anything else a paragraph. Inline: `code`, **bold**, <url>, bare URLs, CVE ids.
 */
export type Block =
  | { kind: "h"; level: 1 | 2; text: string; id: string }
  | { kind: "code"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "p"; text: string };

export function parseSolution(text: string): Block[] {
  const blocks: Block[] = [];
  let n = 0;
  for (const raw of text.replace(/\r/g, "").split("\n")) {
    const line = raw.trimEnd();
    const last = blocks[blocks.length - 1];
    const item = /^\s*(?:([-*])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (!line.trim()) continue;
    if (/^#{1,6} /.test(line)) {
      const level = line.startsWith("## ") ? 2 : 1;
      blocks.push({ kind: "h", level, text: line.replace(/^#+ /, ""), id: `s${n++}` });
    } else if (line.startsWith("$ ") || line === "$") {
      const cmd = line.slice(2);
      if (last?.kind === "code") last.text += `\n${cmd}`;
      else blocks.push({ kind: "code", text: cmd });
    } else if (item) {
      const ordered = !item[1];
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(item[3]);
      else blocks.push({ kind: "list", ordered, items: [item[3]] });
    } else {
      blocks.push({ kind: "p", text: line });
    }
  }
  return blocks;
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|<(https?:\/\/[^>\s]+)>|(https?:\/\/[^\s<>)]+[^\s<>).,;:!?'"])|\b(CVE-\d{4}-\d{4,})\b/g;

function Inline({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let at = 0;
  for (const m of text.matchAll(INLINE)) {
    const i = m.index ?? 0;
    if (i > at) out.push(text.slice(at, i));
    const [, code, bold, angled, bare, cve] = m;
    const link = angled ?? bare;
    if (code) out.push(<code key={i} className="rounded bg-current/10 px-1 py-0.5 font-mono text-[0.88em]">{code.slice(1, -1)}</code>);
    else if (bold) out.push(<strong key={i} className="font-semibold">{bold.slice(2, -2)}</strong>);
    else if (link) out.push(<a key={i} href={link} target="_blank" rel="noreferrer" className="break-all text-sky-600 underline underline-offset-2 hover:text-sky-500">{link}</a>);
    else if (cve) out.push(<a key={i} href={`https://nvd.nist.gov/vuln/detail/${cve}`} target="_blank" rel="noreferrer" className="font-mono text-red-600 underline underline-offset-2">{cve}</a>);
    at = i + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return <>{out}</>;
}

function CodeBlock({ text }: { text: string }) {
  const { t } = useI18n();
  const { copied, copy, bubble } = useCopy();
  return (
    <div className="group relative break-inside-avoid">
      <pre className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3 font-mono text-[0.85em] leading-relaxed text-zinc-100 print:whitespace-pre-wrap print:border-zinc-300 print:bg-zinc-50 print:text-zinc-900">
        <code>{text}</code>
      </pre>
      <div className="absolute top-2 right-2 print:hidden">
        {bubble}
        <button type="button" onClick={() => copy(text)} aria-label={t("labs.doc.copy")} title={t("labs.doc.copy")}
          className="flex items-center gap-1 rounded-md bg-white/10 px-2 py-1 text-xs text-zinc-200 opacity-70 transition hover:bg-white/20 hover:opacity-100">
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </button>
      </div>
    </div>
  );
}

/** The solution as a document: on a paper sheet (the reader) or inline (the lab card). */
export function SolutionDoc({ blocks, className }: { blocks: Block[]; className?: string }) {
  return (
    <div className={cn("grid gap-3 leading-relaxed", className)}>
      {blocks.map((b, i) => (
        <Fragment key={i}>
          {b.kind === "h" ? (
            b.level === 1 ? (
              <h2 id={b.id} className="mt-6 scroll-mt-20 border-b border-current/15 pb-1.5 text-[1.35em] font-semibold first:mt-0">
                <Inline text={b.text} />
              </h2>
            ) : (
              <h3 id={b.id} className="mt-3 scroll-mt-20 text-[1.1em] font-semibold"><Inline text={b.text} /></h3>
            )
          ) : b.kind === "code" ? (
            <CodeBlock text={b.text} />
          ) : b.kind === "list" ? (
            b.ordered ? (
              <ol className="grid list-decimal gap-1 pl-6">{b.items.map((x, j) => <li key={j}><Inline text={x} /></li>)}</ol>
            ) : (
              <ul className="grid list-disc gap-1 pl-6">{b.items.map((x, j) => <li key={j}><Inline text={x} /></li>)}</ul>
            )
          ) : (
            <p><Inline text={b.text} /></p>
          )}
        </Fragment>
      ))}
    </div>
  );
}

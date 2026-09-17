import { Link } from "wouter";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

interface Props {
  title: string;
  icon?: ReactNode;
  href?: string;
  linkLabel?: string;
  children: ReactNode;
}

/** Card wrapper for dashboard sections. If `href` is set, header shows a
 * "View all →" link to that route. */
export function SectionCard({ title, icon, href, linkLabel = "View all", children }: Props) {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-slate-200 font-semibold">{title}</h2>
        </div>
        {href && (
          <Link
            href={href}
            className="text-xs text-slate-400 hover:text-emerald-400 transition-colors inline-flex items-center gap-1"
          >
            {linkLabel} <ArrowRight className="w-3 h-3" />
          </Link>
        )}
      </div>
      {children}
    </div>
  );
}

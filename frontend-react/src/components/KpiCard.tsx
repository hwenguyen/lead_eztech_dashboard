import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  color?: 'navy' | 'blue' | 'gold' | 'green' | 'amber' | 'purple' | 'indigo' | 'cyan' | 'rose' | 'teal';
  trend?: number; // percentage change
  highlight?: boolean;
}

const colorMap = {
  navy: {
    icon: 'bg-slate-100 text-navy border border-slate-200/80',
    dot: 'bg-navy',
    accent: 'text-slate-500',
  },
  blue: {
    icon: 'bg-eztech-light text-eztech border border-eztech-border/60',
    dot: 'bg-eztech',
    accent: 'text-eztech',
  },
  gold: {
    icon: 'bg-gold-light text-gold-dark border border-gold-border/80',
    dot: 'bg-gold',
    accent: 'text-gold-dark',
  },
  green: {
    icon: 'bg-emerald-50/80 text-emerald-600 border border-emerald-200/60',
    dot: 'bg-emerald-500',
    accent: 'text-emerald-600',
  },
  amber: {
    icon: 'bg-gold-light text-gold-dark border border-gold-border/80',
    dot: 'bg-gold',
    accent: 'text-gold-dark',
  },
  purple: {
    icon: 'bg-eztech-light text-eztech border border-eztech-border/60',
    dot: 'bg-eztech',
    accent: 'text-slate-500',
  },
  indigo: {
    icon: 'bg-slate-100 text-navy border border-slate-200/80',
    dot: 'bg-navy',
    accent: 'text-slate-500',
  },
  cyan: {
    icon: 'bg-eztech-light text-eztech border border-eztech-border/60',
    dot: 'bg-eztech',
    accent: 'text-eztech',
  },
  rose: {
    icon: 'bg-rose-50 text-rose-600 border border-rose-200/60',
    dot: 'bg-rose-500',
    accent: 'text-rose-600',
  },
  teal: {
    icon: 'bg-gold-light text-gold-dark border border-gold-border/80',
    dot: 'bg-gold',
    accent: 'text-gold-dark',
  },
};

export function KpiCard({ title, value, subtitle, icon, color = 'blue', trend, highlight = false }: KpiCardProps) {
  const c = colorMap[color] || colorMap.blue;
  return (
    <div
      className={cn(
        "group relative bg-white rounded-xl border p-4 shadow-card hover:shadow-card-hover transition-all duration-200 flex flex-col justify-between gap-3",
        highlight
          ? "border-gold/50 bg-gradient-to-b from-white to-gold-light/25"
          : "border-slate-200/80 hover:border-eztech/30"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-500 truncate">
          {title}
        </span>
        {icon && (
          <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-transform duration-200 group-hover:scale-105", c.icon)}>
            {icon}
          </div>
        )}
      </div>

      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <div className="text-2xl sm:text-[26px] font-bold text-navy tracking-tight tabular-nums leading-none">
            {value}
          </div>
          {subtitle && (
            <p className="text-[11px] font-medium text-slate-500 mt-1.5 flex items-center gap-1.5 truncate">
              <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", c.dot)} />
              <span className="truncate">{subtitle}</span>
            </p>
          )}
        </div>

        {trend !== undefined && (
          <div
            className={cn(
              "text-[11px] font-semibold px-2 py-0.5 rounded-md tabular-nums shrink-0",
              trend >= 0
                ? "bg-emerald-50 text-emerald-700 border border-emerald-200/60"
                : "bg-rose-50 text-rose-700 border border-rose-200/60"
            )}
          >
            {trend >= 0 ? '↑' : '↓'} {Math.abs(trend).toFixed(1)}%
          </div>
        )}
      </div>
    </div>
  );
}

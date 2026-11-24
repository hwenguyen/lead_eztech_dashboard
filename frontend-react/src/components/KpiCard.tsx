import React from 'react';
import { cn } from '../utils/format';

interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  subtitleTone?: 'neutral' | 'positive' | 'negative';
  icon?: React.ReactNode;
  color?: 'navy' | 'blue' | 'gold' | 'green' | 'amber' | 'purple' | 'indigo' | 'cyan' | 'rose' | 'teal';
  trend?: number; // percentage change
  highlight?: boolean;
  onClick?: () => void;
  active?: boolean;
  tooltip?: string;
}

const colorMap = {
  navy: {
    icon: 'bg-brand-50 text-navy border border-brand-200/70',
    dot: 'bg-navy dark:bg-sky-400',
  },
  blue: {
    icon: 'bg-brand-100 text-brand-600 border border-brand-200',
    dot: 'bg-brand-500',
  },
  gold: {
    icon: 'bg-gold-100 text-gold-700 border border-gold-300',
    dot: 'bg-gold-500',
  },
  green: {
    icon: 'bg-emerald-50/80 text-emerald-600 border border-emerald-200/60',
    dot: 'bg-emerald-500',
  },
  amber: {
    icon: 'bg-gold-light text-gold-dark border border-gold-border/80',
    dot: 'bg-gold',
  },
  purple: {
    icon: 'bg-purple-50 text-purple-600 border border-purple-200',
    dot: 'bg-purple-500',
  },
  indigo: {
    icon: 'bg-indigo-50 text-indigo-600 border border-indigo-200',
    dot: 'bg-indigo-500',
  },
  cyan: {
    icon: 'bg-sky-50 text-sky-700 border border-sky-200',
    dot: 'bg-sky-500',
  },
  rose: {
    icon: 'bg-rose-50 text-rose-600 border border-rose-200/60',
    dot: 'bg-rose-500',
  },
  teal: {
    icon: 'bg-emerald-50 text-emerald-700 border border-emerald-200/80',
    dot: 'bg-teal-500',
  },
};

export const KpiCard = React.memo(function KpiCard({
  title,
  value,
  subtitle,
  subtitleTone = 'neutral',
  icon,
  color = 'blue',
  trend,
  highlight = false,
  onClick,
  active = false,
  tooltip,
}: KpiCardProps) {
  const c = colorMap[color] || colorMap.blue;
  const activeRing = active
    ? color === 'gold'
      ? 'ring-2 ring-gold-500 border-gold-500'
      : 'ring-2 ring-brand-500 border-brand-500'
    : '';
  const subtitleDotClass =
    subtitleTone === 'positive'
      ? 'bg-emerald-500'
      : subtitleTone === 'negative'
      ? 'bg-rose-500'
      : c.dot;
  const subtitleTextClass =
    subtitleTone === 'positive'
      ? 'text-emerald-700'
      : subtitleTone === 'negative'
      ? 'text-rose-600'
      : 'text-slate-500';
  return (
    <div
      title={tooltip}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-pressed={onClick ? active : undefined}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={cn(
        'group relative bg-white rounded-2xl border p-4 shadow-card hover:shadow-card-hover transition-all duration-200 flex flex-col gap-3',
        highlight
          ? 'border-gold-400/80 bg-gradient-to-b from-white to-gold-50/40 dark:from-slate-900 dark:to-amber-950/30 shadow-sm'
          : 'border-slate-200/80 hover:border-brand-400/50',
        onClick && 'cursor-pointer select-none active:scale-[0.985]',
        activeRing
      )}
    >
      <div className="flex items-center justify-between gap-2 min-h-[32px]">
        <span
          title={title}
          className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-500 truncate min-w-0"
        >
          {title}
        </span>
        {icon && (
          <div
            aria-hidden="true"
            className={cn(
              'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-transform duration-200 group-hover:scale-105',
              c.icon
            )}
          >
            {icon}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
        <div className="text-2xl sm:text-[26px] font-bold text-navy tracking-tight tabular-nums leading-none">
          {value}
        </div>

        {trend !== undefined && (
          <div
            className={cn(
              'text-[11px] font-semibold px-1.5 py-0.5 rounded-md tabular-nums shrink-0 leading-tight',
              trend > 0
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/60'
                : trend < 0
                ? 'bg-rose-50 text-rose-700 border border-rose-200/60'
                : 'bg-slate-100 text-slate-600 border border-slate-200/70'
            )}
          >
            {trend > 0 ? '↑' : trend < 0 ? '↓' : '—'} {Math.abs(trend).toFixed(1)}%
          </div>
        )}
      </div>

      <div className="mt-auto min-h-[16px] flex items-center">
        {subtitle && (
          <p
            title={subtitle}
            className={cn('text-[11px] font-medium flex items-center gap-1.5 truncate w-full', subtitleTextClass)}
          >
            <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', subtitleDotClass)} aria-hidden="true" />
            <span className="truncate">{subtitle}</span>
          </p>
        )}
      </div>
    </div>
  );
});

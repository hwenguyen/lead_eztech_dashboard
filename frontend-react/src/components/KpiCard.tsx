
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
  color?: 'blue' | 'green' | 'amber' | 'purple';
  trend?: number; // percentage change
}

const colorMap = {
  blue: { bg: 'bg-blue-50', icon: 'bg-blue-100 text-blue-600', text: 'text-blue-600' },
  green: { bg: 'bg-emerald-50', icon: 'bg-emerald-100 text-emerald-600', text: 'text-emerald-600' },
  amber: { bg: 'bg-amber-50', icon: 'bg-amber-100 text-amber-600', text: 'text-amber-600' },
  purple: { bg: 'bg-purple-50', icon: 'bg-purple-100 text-purple-600', text: 'text-purple-600' },
};

export function KpiCard({ title, value, subtitle, icon, color = 'blue', trend }: KpiCardProps) {
  const c = colorMap[color];
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-sm hover:shadow-md transition-all duration-200 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-500">{title}</span>
        {icon && (
          <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", c.icon)}>
            {icon}
          </div>
        )}
      </div>
      <div className="flex items-end justify-between">
        <div>
          <div className="text-3xl font-bold text-gray-900 tracking-tight">{value}</div>
          {subtitle && <p className={cn("text-xs font-medium mt-1", c.text)}>{subtitle}</p>}
        </div>
        {trend !== undefined && (
          <div className={cn(
            "text-xs font-semibold px-2 py-1 rounded-full",
            trend >= 0 ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-500"
          )}>
            {trend >= 0 ? '↑' : '↓'} {Math.abs(trend).toFixed(1)}%
          </div>
        )}
      </div>
    </div>
  );
}

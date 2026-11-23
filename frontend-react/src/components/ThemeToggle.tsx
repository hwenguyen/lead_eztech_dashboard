import { Sun, Moon } from 'lucide-react';
import { useTheme } from '../utils/theme';

interface ThemeToggleProps {
  className?: string;
}

export function ThemeToggle({ className = '' }: ThemeToggleProps) {
  const { isDark, setScheme } = useTheme();

  return (
    <div
      role="group"
      aria-label="Chuyển đổi giao diện Sáng / Tối"
      className={`theme-segmented inline-flex items-center p-0.5 rounded-xl border border-slate-200/90 dark:border-slate-700 bg-slate-100/90 dark:bg-slate-800/90 shadow-sm ${className}`}
    >
      <button
        type="button"
        onClick={() => setScheme('light')}
        aria-pressed={!isDark}
        title="Chuyển sang giao diện Sáng"
        className="theme-seg-btn theme-seg-light inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer"
      >
        <Sun className="w-3.5 h-3.5" aria-hidden="true" />
        <span>Sáng</span>
      </button>
      <button
        type="button"
        onClick={() => setScheme('dark')}
        aria-pressed={isDark}
        title="Chuyển sang giao diện Tối"
        className="theme-seg-btn theme-seg-dark inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer"
      >
        <Moon className="w-3.5 h-3.5" aria-hidden="true" />
        <span>Tối</span>
      </button>
    </div>
  );
}

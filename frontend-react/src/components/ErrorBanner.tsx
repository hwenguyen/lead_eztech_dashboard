import { AlertCircle, RefreshCw } from 'lucide-react';

interface ErrorBannerProps {
  message: string | null;
  onRetry?: () => void;
  className?: string;
}

export function ErrorBanner({ message, onRetry, className = '' }: ErrorBannerProps) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className={`bg-rose-50 border border-rose-200 text-rose-700 rounded-xl px-4 py-3 text-xs flex flex-wrap items-center justify-between gap-2 shadow-sm ${className}`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" aria-hidden="true" />
        <span className="font-medium break-words">{message}</span>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-[11px] font-semibold bg-white hover:bg-rose-100 text-rose-700 border border-rose-300 transition-colors cursor-pointer shrink-0"
        >
          <RefreshCw className="w-3 h-3" aria-hidden="true" />
          <span>Thử lại</span>
        </button>
      )}
    </div>
  );
}

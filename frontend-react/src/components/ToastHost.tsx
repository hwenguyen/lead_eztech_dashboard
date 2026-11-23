import { useEffect, useState } from 'react';
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-react';
import { subscribeAppToast, type ToastMessage } from '../utils/toast';

export function ToastHost() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
    const timers = new Map<number, number>();
    const unsubscribe = subscribeAppToast((msg) => {
      setToasts((prev) => [...prev.slice(-3), msg]);
      const t = window.setTimeout(() => {
        setToasts((prev) => prev.filter((item) => item.id !== msg.id));
        timers.delete(msg.id);
      }, 4000);
      timers.set(msg.id, t);
    });
    return () => {
      unsubscribe();
      timers.forEach((t) => window.clearTimeout(t));
      timers.clear();
    };
  }, []);

  const dismiss = (id: number) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  };

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="fixed bottom-4 right-4 z-[90] flex flex-col gap-2 max-w-sm w-[calc(100vw-2rem)] pointer-events-none"
    >
      {toasts.map((t) => {
        const tone =
          t.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
            : t.type === 'error'
            ? 'bg-rose-50 border-rose-200 text-rose-800'
            : t.type === 'warning'
            ? 'bg-amber-50 border-amber-200 text-amber-800'
            : 'bg-white border-slate-200 text-navy';
        const Icon =
          t.type === 'success'
            ? CheckCircle2
            : t.type === 'error'
            ? AlertCircle
            : t.type === 'warning'
            ? AlertTriangle
            : Info;
        return (
          <div
            key={t.id}
            role={t.type === 'error' ? 'alert' : 'status'}
            className={`pointer-events-auto flex items-start gap-2.5 px-3.5 py-2.5 rounded-xl border shadow-lg text-xs font-medium ${tone}`}
          >
            <Icon className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
            <span className="flex-1 leading-relaxed break-words">{t.text}</span>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Đóng thông báo"
              className="p-0.5 rounded opacity-70 hover:opacity-100 transition-opacity cursor-pointer"
            >
              <X className="w-3.5 h-3.5" aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

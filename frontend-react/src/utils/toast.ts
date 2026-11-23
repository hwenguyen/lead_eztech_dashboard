export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface ToastMessage {
  id: number;
  text: string;
  type: ToastType;
}

const TOAST_EVENT = 'eztech-app-toast';
let _nextId = 1;

export function showAppToast(text: string, type: ToastType = 'info') {
  if (typeof window === 'undefined') return;
  const detail: ToastMessage = { id: _nextId++, text, type };
  window.dispatchEvent(new CustomEvent<ToastMessage>(TOAST_EVENT, { detail }));
}

export function subscribeAppToast(handler: (msg: ToastMessage) => void): () => void {
  const listener = (e: Event) => {
    const custom = e as CustomEvent<ToastMessage>;
    if (custom.detail) handler(custom.detail);
  };
  window.addEventListener(TOAST_EVENT, listener);
  return () => window.removeEventListener(TOAST_EVENT, listener);
}

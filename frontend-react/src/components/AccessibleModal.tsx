import React, { useEffect, useRef } from 'react';

interface AccessibleModalProps {
  isOpen: boolean;
  onClose: () => void;
  labelledBy?: string;
  ariaLabel?: string;
  children: React.ReactNode;
  overlayClassName?: string;
  contentClassName?: string;
  closeOnBackdrop?: boolean;
}

/**
 * Accessible modal overlay supporting Escape close, backdrop dismiss, body scroll lock,
 * role="dialog", aria-modal="true", and focus restoration on close.
 */
export function AccessibleModal({
  isOpen,
  onClose,
  labelledBy,
  ariaLabel,
  children,
  overlayClassName = 'fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto',
  contentClassName,
  closeOnBackdrop = true,
}: AccessibleModalProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
      }
    };
    window.addEventListener('keydown', onKeyDown);

    // Move focus into dialog container if no child auto-focused
    const raf = requestAnimationFrame(() => {
      const node = containerRef.current;
      if (node && !node.contains(document.activeElement)) {
        node.focus();
      }
    });

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = prevOverflow;
      previousFocusRef.current?.focus?.();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className={overlayClassName}
      onMouseDown={(e) => {
        if (closeOnBackdrop && e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={!labelledBy ? ariaLabel : undefined}
        tabIndex={-1}
        className="w-full flex items-center justify-center focus:outline-none"
        onMouseDown={(e) => {
          if (closeOnBackdrop && e.target === e.currentTarget) {
            onClose();
          }
        }}
      >
        {contentClassName ? <div className={contentClassName}>{children}</div> : children}
      </div>
    </div>
  );
}

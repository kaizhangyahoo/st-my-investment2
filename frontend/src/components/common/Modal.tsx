import React, { useEffect, useRef } from 'react';

interface ModalProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onDismiss: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export const Modal: React.FC<ModalProps> = ({
  open,
  title,
  subtitle,
  onDismiss,
  children,
  footer,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const panel = panelRef.current;
    panel?.querySelector<HTMLElement>(FOCUSABLE)?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onDismiss();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;

      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null
      );
      if (items.length === 0) return;

      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused.current?.focus();
    };
  }, [open, onDismiss]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" aria-hidden="true" />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative w-full max-w-3xl max-h-[85vh] flex flex-col bg-surface-container-low rounded-xl border border-surface-container shadow-2xl"
      >
        <div className="p-space-md border-b border-surface-container/60 flex items-start gap-space-sm">
          <span className="material-symbols-outlined text-[22px] text-secondary mt-0.5">
            rule_settings
          </span>
          <div>
            <h2 className="font-headline-md text-headline-md text-on-surface font-semibold">
              {title}
            </h2>
            {subtitle && (
              <span className="font-body-sm text-body-sm text-on-surface-variant block mt-0.5">
                {subtitle}
              </span>
            )}
          </div>
        </div>

        <div className="p-space-md overflow-y-auto flex-1">{children}</div>

        {footer && (
          <div className="p-space-md border-t border-surface-container/60 flex items-center justify-end gap-space-sm">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};

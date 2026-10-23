import { RefObject, useEffect, useRef } from 'react';

interface FocusTrapOptions {
  skipEscape?: () => boolean;
}

export function useFocusTrap(
  active: boolean,
  containerRef: RefObject<any>,
  onClose: () => void,
  options: FocusTrapOptions = {},
) {
  const closeRef = useRef(onClose);
  const skipEscapeRef = useRef(options.skipEscape);

  useEffect(() => {
    closeRef.current = onClose;
    skipEscapeRef.current = options.skipEscape;
  }, [onClose, options.skipEscape]);

  useEffect(() => {
    if (!active) return;
    const container = containerRef.current as HTMLElement | null;
    if (!container) return;

    const previous = document.activeElement as HTMLElement | null;
    const focusable = () =>
      Array.from(
        container.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.getClientRects().length > 0);

    const preferred = container.querySelector<HTMLElement>('[data-autofocus]');
    (preferred || focusable()[0] || container).focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (skipEscapeRef.current?.()) return;
        event.preventDefault();
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true);
      previous?.focus();
    };
  }, [active, containerRef]);
}

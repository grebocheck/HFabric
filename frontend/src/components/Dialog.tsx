import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

let scrollLockDepth = 0;
let previousBodyOverflow = "";

function lockDocumentScroll() {
  if (scrollLockDepth === 0) {
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  scrollLockDepth += 1;
}

function unlockDocumentScroll() {
  scrollLockDepth = Math.max(0, scrollLockDepth - 1);
  if (scrollLockDepth === 0) document.body.style.overflow = previousBodyOverflow;
}

export function Dialog({
  open,
  title,
  children,
  onClose,
  closeOnBackdrop = true,
  closeOnEscape = true,
  initialFocusRef,
  overlayClassName = "",
  panelClassName = "",
  titleClassName = "text-base font-semibold text-ui-strong",
}: {
  open: boolean;
  title: ReactNode;
  children: ReactNode;
  onClose?: () => void;
  closeOnBackdrop?: boolean;
  closeOnEscape?: boolean;
  initialFocusRef?: RefObject<HTMLElement | null>;
  overlayClassName?: string;
  panelClassName?: string;
  titleClassName?: string;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    lockDocumentScroll();
    const frame = requestAnimationFrame(() => {
      const target = initialFocusRef?.current
        ?? panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)
        ?? panelRef.current;
      target?.focus();
    });
    return () => {
      cancelAnimationFrame(frame);
      unlockDocumentScroll();
      previouslyFocused?.focus();
    };
  }, [initialFocusRef, open]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && closeOnEscape && onClose) {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
    ).filter((element) => !element.hasAttribute("disabled") && element.tabIndex !== -1);
    if (focusable.length === 0) {
      event.preventDefault();
      panelRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const handleBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (
      closeOnBackdrop
      && onClose
      && event.target === event.currentTarget
    ) {
      onClose();
    }
  };

  return (
    /* Backdrop clicks are intentionally limited to the backdrop itself. */
    <div
      role="presentation"
      className={`fixed inset-0 z-50 flex min-w-0 items-center justify-center overflow-y-auto bg-black/70 p-3 backdrop-blur-sm sm:p-4 ${overlayClassName}`}
      onMouseDown={handleBackdrop}
    >
      {/* A dialog is a composite widget; keyboard handling implements its focus trap. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className={`max-h-[calc(100dvh-1.5rem)] min-w-0 overflow-hidden rounded-lg border border-line bg-surface shadow-popover sm:max-h-[calc(100dvh-2rem)] ${panelClassName}`}
      >
        <h2 id={titleId} className={titleClassName}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

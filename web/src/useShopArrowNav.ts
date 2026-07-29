import { useEffect } from "react";

/**
 * Arrow-key navigation for the shop lists (Shops, TCG Shops List, New Shops List).
 *
 *   detail modal open  → ←/↑ previous shop, →/↓ next shop, in the order shown
 *   modal closed       → ↑/↓ move a highlight down the list, Enter opens it
 *
 * "The order shown" is whatever the page is currently rendering, so arrowing
 * respects the active filters / AI results and never jumps to a hidden shop.
 * Stops at the first and last row rather than wrapping — wrapping past the end
 * makes it easy to lose your place in a long list.
 *
 * Ignored while typing in a field (so the arrows still move the text caret) and
 * whenever a modifier is held (leaves browser shortcuts alone).
 */
export function useShopArrowNav<T extends { id: number }>(opts: {
  items: T[];
  selected: T | null;
  setSelected: (s: T) => void;
  cursor: number;
  setCursor: (n: number) => void;
}) {
  const { items, selected, setSelected, cursor, setCursor } = opts;

  useEffect(() => {
    function isTyping(target: EventTarget | null): boolean {
      const el = target as HTMLElement | null;
      if (!el || !el.tagName) return false;
      return /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable;
    }

    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      if (isTyping(e.target)) return;
      if (!items.length) return;

      const back = e.key === "ArrowLeft" || e.key === "ArrowUp";
      const fwd = e.key === "ArrowRight" || e.key === "ArrowDown";
      if (!back && !fwd && e.key !== "Enter") return;

      // Modal open: step straight to the neighbouring shop.
      if (selected) {
        if (!back && !fwd) return;
        const i = items.findIndex(s => s.id === selected.id);
        if (i === -1) return;              // showing a shop that's been filtered out
        const next = i + (fwd ? 1 : -1);
        if (next < 0 || next >= items.length) return;
        e.preventDefault();
        setSelected(items[next]);
        setCursor(next);
        return;
      }

      if (e.key === "Enter") {
        if (cursor >= 0 && cursor < items.length) {
          e.preventDefault();
          setSelected(items[cursor]);
        }
        return;
      }

      // No modal: move the highlight, keeping it on screen.
      e.preventDefault();
      const next = cursor < 0
        ? 0
        : Math.min(items.length - 1, Math.max(0, cursor + (fwd ? 1 : -1)));
      setCursor(next);
      document.querySelector(`[data-shop-id="${items[next].id}"]`)
        ?.scrollIntoView({ block: "nearest" });
    }

    // Capture phase, on document: fires before any component handler that might
    // stop propagation on its way up.
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [items, selected, setSelected, cursor, setCursor]);
}

/** Outline for the arrow-key highlight on a list row. */
export const shopCursorStyle = {
  boxShadow: "inset 0 0 0 2px rgba(96,165,250,0.9)",
  borderRadius: 10,
} as const;

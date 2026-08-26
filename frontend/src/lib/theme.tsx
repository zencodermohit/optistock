/**
 * Which theme is showing, and who decided.
 *
 * Three stored values, two possible appearances. "system" is not a third look
 * -- it means "whatever the OS is doing, including when that changes while I
 * am sitting here", and it is the default because an operations screen someone
 * opens at 6am should not be the only white rectangle on a dark desktop.
 *
 * The resolved value is written to <html data-theme> as "light" or "dark",
 * never "system". index.css keys off that attribute, so the stylesheet never
 * has to know about the third state and the palette exists in exactly one
 * place. The same write happens in an inline script in index.html before the
 * bundle loads -- see there for why.
 *
 * The toggle in the top bar flips between light and dark. Choosing either one
 * leaves "system" behind deliberately: a person reaching for that button is
 * overriding their OS on purpose, and silently re-following it at sunset would
 * undo a choice they just made.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemeChoice = "light" | "dark" | "system";
export type Appearance = "light" | "dark";

const STORAGE_KEY = "optistock:theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

/** What the OS is asking for right now. */
function systemAppearance(): Appearance {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

/**
 * The stored choice, or "system" when there isn't a usable one.
 *
 * Wrapped because localStorage throws rather than returning null in a private
 * window and under some enterprise policies, and a theme preference is not
 * worth a blank screen.
 */
function storedChoice(): ThemeChoice {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

function resolve(choice: ThemeChoice): Appearance {
  return choice === "system" ? systemAppearance() : choice;
}

/**
 * Put the appearance on <html>, and animate the swap only while it happens.
 *
 * The transition class is added around the change and taken off again, because
 * leaving a global colour transition on would also animate every table row
 * that changes on hover.
 */
function apply(appearance: Appearance, animate: boolean) {
  const root = document.documentElement;
  if (root.dataset.theme === appearance) return;

  if (
    animate &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    root.classList.add("theme-switching");
    window.setTimeout(() => root.classList.remove("theme-switching"), 220);
  }
  root.dataset.theme = appearance;
  // Keeps the browser chrome on mobile from staying the other theme's colour.
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", appearance === "dark" ? "#0a1020" : "#f5f7fb");
}

interface ThemeValue {
  /** What the user chose, including "system". */
  choice: ThemeChoice;
  /** What is actually on screen. */
  appearance: Appearance;
  setChoice: (next: ThemeChoice) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(storedChoice);
  const [appearance, setAppearance] = useState<Appearance>(() =>
    resolve(storedChoice()),
  );

  // Follow the OS, but only while the user has not overridden it.
  useEffect(() => {
    if (choice !== "system") return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = () => {
      const next = systemAppearance();
      setAppearance(next);
      apply(next, true);
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    try {
      if (next === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A theme that does not survive a reload still beats a crash.
    }
    const resolved = resolve(next);
    setAppearance(resolved);
    apply(resolved, true);
  }, []);

  // The inline script has already stamped the attribute; this only matters if
  // it did not run, or if the stored value changed in another tab.
  useEffect(() => {
    apply(appearance, false);
  }, [appearance]);

  const value = useMemo<ThemeValue>(
    () => ({
      choice,
      appearance,
      setChoice,
      toggle: () => setChoice(appearance === "dark" ? "light" : "dark"),
    }),
    [choice, appearance, setChoice],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) {
    throw new Error("useTheme must be used inside a ThemeProvider");
  }
  return value;
}

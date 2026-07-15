import { createContext, useContext, type ReactNode } from 'react';

/**
 * Light-only no-op preservado para retrocompatibilidade. O design router
 * (TP-Link) usa apenas o tema claro; mantemos a API antes utilizada por
 * componentes externos para não quebrar imports.
 */

type Theme = 'light';

interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState>({ theme: 'light', toggle: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  return <ThemeContext.Provider value={{ theme: 'light', toggle: () => {} }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  return useContext(ThemeContext);
}

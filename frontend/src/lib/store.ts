import { create } from "zustand";

type UIState = {
  orgId: string | null;
  setOrg: (id: string) => void;
  theme: "light" | "dark" | "system";
  setTheme: (t: UIState["theme"]) => void;
};

export const useUI = create<UIState>((set) => ({
  orgId: null,
  setOrg: (orgId) => set({ orgId }),
  theme: "system",
  setTheme: (theme) => {
    try { localStorage.setItem("spark.theme", theme); } catch { /* ignore */ }
    if (typeof document !== "undefined") {
      if (theme === "system") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", theme);
    }
    set({ theme });
  },
}));

export type Theme = "dark" | "light";

export const DEFAULT_THEME: Theme = "light";
export const THEME_STORAGE_KEY = "arsia-independent-theme";

// Run before the first paint; all values are application-owned constants.
export const THEME_INITIALIZATION_SCRIPT = `(function(){var theme="${DEFAULT_THEME}";try{var saved=localStorage.getItem("${THEME_STORAGE_KEY}");if(saved==="light"||saved==="dark")theme=saved;}catch(e){}var root=document.documentElement;root.dataset.theme=theme;root.classList.toggle("dark",theme==="dark");root.classList.toggle("light",theme==="light");root.style.colorScheme=theme;})()`;

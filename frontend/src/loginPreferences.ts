import type { Credentials } from "./api";

const USERNAME_KEY = "gomate.rememberedUsername";
const PREFERENCES_KEY = "gomate.loginPreferences";

export function loginPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem(PREFERENCES_KEY) || "null");
    return {
      rememberCredentials: value?.rememberCredentials !== false,
      keepSignedIn: value?.keepSignedIn !== false,
    };
  } catch {
    return { rememberCredentials: true, keepSignedIn: true };
  }
}

export function rememberedUsername(): string {
  try {
    return localStorage.getItem(USERNAME_KEY) || "";
  } catch {
    return "";
  }
}

export function saveLoginPreferences(
  credentials: Credentials,
  rememberCredentials: boolean,
  keepSignedIn: boolean,
) {
  try {
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify({ rememberCredentials, keepSignedIn }));
    if (rememberCredentials) localStorage.setItem(USERNAME_KEY, credentials.username);
    else localStorage.removeItem(USERNAME_KEY);
  } catch {
    // Browser storage restrictions do not prevent login.
  }
  if (!rememberCredentials) return;
  type PasswordConstructor = new (data: { id: string; password: string }) => Credential;
  const Constructor = (window as Window & { PasswordCredential?: PasswordConstructor }).PasswordCredential;
  if (!window.isSecureContext || !Constructor || !navigator.credentials?.store) return;
  try {
    // Passwords go only to the browser's password manager, never web storage.
    void navigator.credentials.store(new Constructor({
      id: credentials.username, password: credentials.password,
    })).catch(() => {});
  } catch {
    // Autofill remains available through standard form autocomplete attributes.
  }
}

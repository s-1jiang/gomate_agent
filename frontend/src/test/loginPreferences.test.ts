import { expect, it, vi } from "vitest";
import { loginPreferences, rememberedUsername, saveLoginPreferences } from "../loginPreferences";

const credentials = { username: "tester", password: "password-private-canary" };

function passwordManager(store: ReturnType<typeof vi.fn>) {
  const constructor = vi.fn(function (this: { id: string; password: string }, value: typeof credentials & { id: string }) {
    this.id = value.id;
    this.password = value.password;
  });
  const testNavigator = Object.create(navigator);
  Object.defineProperty(testNavigator, "credentials", { value: { store } });
  vi.stubGlobal("navigator", testNavigator);
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("PasswordCredential", constructor);
  return constructor;
}

it("stores credentials only in the browser manager, while web storage contains the account and preferences", async () => {
  const store = vi.fn().mockResolvedValue(undefined);
  const constructor = passwordManager(store);
  saveLoginPreferences(credentials, true, true);
  expect(constructor).toHaveBeenCalledWith({ id: credentials.username, password: credentials.password });
  expect(store).toHaveBeenCalledOnce();
  expect(rememberedUsername()).toBe("tester");
  expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(credentials.password);
  expect(loginPreferences()).toEqual({ rememberCredentials: true, keepSignedIn: true });
});

it("does not request password storage when remembering credentials is unchecked", () => {
  const store = vi.fn().mockResolvedValue(undefined);
  passwordManager(store);
  localStorage.setItem("gomate.rememberedUsername", "old_user");
  saveLoginPreferences(credentials, false, false);
  expect(store).not.toHaveBeenCalled();
  expect(rememberedUsername()).toBe("");
  expect(loginPreferences()).toEqual({ rememberCredentials: false, keepSignedIn: false });
});

it("allows login preferences to be saved when the browser declines password storage", async () => {
  passwordManager(vi.fn().mockRejectedValue(new DOMException("Declined", "NotAllowedError")));
  expect(() => saveLoginPreferences(credentials, true, true)).not.toThrow();
  await Promise.resolve();
  expect(rememberedUsername()).toBe("tester");
});

it("continues when web storage is blocked or a preference record is malformed", () => {
  localStorage.setItem("gomate.loginPreferences", "invalid JSON");
  expect(loginPreferences().keepSignedIn).toBe(true);
  const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("Blocked", "SecurityError");
  });
  expect(() => saveLoginPreferences(credentials, true, true)).not.toThrow();
  write.mockRestore();
});

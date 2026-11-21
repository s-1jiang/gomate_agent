import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
  value() {
    this.setAttribute("open", "");
  },
});
Object.defineProperty(HTMLDialogElement.prototype, "close", {
  value() {
    this.removeAttribute("open");
  },
});
Element.prototype.scrollIntoView = vi.fn();
afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

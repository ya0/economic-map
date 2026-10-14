import { describe, expect, it } from "vitest";
import { eventName } from "../src/track";

describe("eventName", () => {
  it("names the control and its choice, never typed text", () => {
    expect(eventName({ id: "ind", tagName: "SELECT", value: "gdp_pc" }, "change")).toBe("set/ind/gdp_pc");
    expect(eventName({ id: "globe", tagName: "INPUT", type: "checkbox", checked: true }, "change")).toBe("set/globe/on");
    expect(eventName({ id: "q", tagName: "INPUT", type: "search", value: "secret" }, "change")).toBe("set/q");
    expect(eventName({ id: "smooth", tagName: "INPUT", type: "radio" }, "change")).toBe("set/smooth");
    expect(eventName({ id: "export-btn", tagName: "BUTTON" }, "click")).toBe("click/export-btn");
    expect(eventName({ id: "smopts", tagName: "DETAILS", open: true }, "toggle")).toBe("open/smopts");
  });
  it("ignores closing, elements without an id and clicks on anything but a button", () => {
    expect(eventName({ id: "sd", tagName: "DETAILS", open: false }, "toggle")).toBe("");
    expect(eventName({ id: "", tagName: "BUTTON" }, "click")).toBe("");
    expect(eventName({ id: "map", tagName: "DIV" }, "click")).toBe("");
  });
});

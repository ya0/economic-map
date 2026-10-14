import { describe, expect, it } from "vitest";
import { type Box, MIN, resize, sizeKm, toBounds } from "../src/frame";

const A: [number, number] = [1000, 600], box: Box = [300, 200, 700, 500];

describe("resize", () => {
  it("moves one edge or two, the others stay", () => {
    expect(resize(box, "e", 800, 0, A)).toEqual([300, 200, 800, 500]);
    expect(resize(box, "nw", 250, 100, A)).toEqual([250, 100, 700, 500]);
  });
  it("keeps the minimum size and stays inside the map", () => {
    expect(resize(box, "e", 100, 0, A)).toEqual([300, 200, 300 + MIN, 500]);
    expect(resize(box, "nw", -50, -50, A)).toEqual([0, 0, 700, 500]);
    expect(resize(box, "se", 5000, 5000, A)).toEqual([300, 200, 1000, 600]);
  });
  it("locks the aspect: a corner keeps the opposite corner, an edge keeps the centre line", () => {
    expect(resize(box, "se", 700, 300, A, 2)).toEqual([300, 200, 700, 400]);
    expect(resize(box, "e", 600, 0, A, 2)).toEqual([300, 275, 600, 425]);
    expect(resize(box, "s", 0, 300, A, 2)).toEqual([400, 200, 600, 300]);
  });
  it("shrinks a locked frame that does not fit the map", () => {
    const [l, t, r, b] = resize(box, "se", 5000, 300, A, 4);
    expect([r - l, b - t]).toEqual([700, 175]);
    const [l2, t2, r2, b2] = resize(box, "e", 5000, 0, A, 4);
    expect([r2 - l2, b2 - t2]).toEqual([700, 175]);
    expect(t2).toBe(275 - 12.5);
  });
});

describe("toBounds and sizeKm", () => {
  it("normalises: west < east, within the Mercator world, three decimals", () => {
    expect(toBounds([5.123456, 55.98765], [15.5, 47.1])).toEqual([5.123, 47.1, 15.5, 55.988]);
    expect(toBounds([-200, 89], [190, -89])).toEqual([-180, -85, 180, 85]);
  });
  it("measures km at the centre latitude", () => {
    expect(sizeKm([0, -5, 10, 5])).toEqual([1110, 1110]);
    expect(sizeKm([0, 59, 10, 61])).toEqual([560, 220]); // 10 degrees at 60 degrees north: half the equatorial width
  });
});

import { describe, expect, it } from "vitest";

import { buildPhysicsStepPayload } from "./physics-step";

const base = {
  step: "F - mu*N = m*a",
  unit: "",
  unitsText: "",
  valuesText: "",
  expectedText: "",
  toleranceText: "",
  absoluteToleranceText: "",
};

describe("buildPhysicsStepPayload", () => {
  it("builds an equation payload with units and numeric values", () => {
    const result = buildPhysicsStepPayload({
      ...base,
      unitsText: "F=N\nm=kg\na=m/s^2\nmu=",
      valuesText: "F=10\nm=2\na=3\nmu=0.2",
    });

    expect(result).toEqual({
      text: "F - mu*N = m*a",
      data: {
        equation: "F - mu*N = m*a",
        units: { F: "N", m: "kg", a: "m/s^2", mu: "" },
        values: { F: 10, m: 2, a: 3, mu: 0.2 },
      },
    });
  });

  it("turns a bare quantity into an expression and needs a result unit", () => {
    const missing = buildPhysicsStepPayload({
      ...base,
      step: "m*a",
    });
    expect("error" in missing && missing.error).toContain("结果单位");

    const result = buildPhysicsStepPayload({
      ...base,
      step: "m*a",
      unit: "N",
      unitsText: "m=kg\na=m/s^2",
    });
    expect(result).toMatchObject({
      data: {
        expression: "m*a",
        unit: "N",
        units: { m: "kg", a: "m/s^2" },
      },
    });
  });

  it("accepts a dimensionless unit written as an empty value", () => {
    const result = buildPhysicsStepPayload({
      ...base,
      unitsText: "mu=",
    });

    expect(result).toMatchObject({ data: { units: { mu: "" } } });
  });

  it("adds a declared result and a relative tolerance", () => {
    const result = buildPhysicsStepPayload({
      ...base,
      unit: "N",
      unitsText: "F=N\nm=kg\na=m/s^2\nmu=",
      valuesText: "F=10\nm=2\na=3\nmu=0.2",
      expectedText: "6",
      toleranceText: "1",
    });

    expect(result).toMatchObject({
      data: {
        equation: "F - mu*N = m*a",
        unit: "N",
        expected: { value: 6, unit: "N" },
        tolerance: { relative: 0.01 },
      },
    });
  });

  it("turns a ± result into a declared uncertainty", () => {
    const result = buildPhysicsStepPayload({
      ...base,
      unit: "m/s",
      expectedText: "6.32±0.01",
    });

    expect(result).toMatchObject({
      data: {
        expected: { value: 6.32, uncertainty: 0.01, unit: "m/s" },
      },
    });
  });

  it("turns [lower, upper] into an interval, including a Chinese comma", () => {
    const result = buildPhysicsStepPayload({
      ...base,
      unit: "m/s",
      expectedText: "[6.3，6.4]",
    });

    expect(result).toMatchObject({
      data: {
        expected: { lower: 6.3, upper: 6.4, unit: "m/s" },
      },
    });
  });

  it("adds an absolute tolerance, alone or with a relative one", () => {
    const absoluteOnly = buildPhysicsStepPayload({
      ...base,
      unit: "N",
      expectedText: "6",
      absoluteToleranceText: "0.05",
    });
    expect(absoluteOnly).toMatchObject({
      data: { tolerance: { absolute: 0.05 } },
    });

    const both = buildPhysicsStepPayload({
      ...base,
      unit: "N",
      expectedText: "6",
      toleranceText: "1",
      absoluteToleranceText: "0.05",
    });
    expect(both).toMatchObject({
      data: { tolerance: { relative: 0.01, absolute: 0.05 } },
    });
  });

  it("rejects a declared result without a unit and an out-of-range tolerance", () => {
    expect(
      buildPhysicsStepPayload({ ...base, expectedText: "6" }),
    ).toMatchObject({ error: expect.stringContaining("结果单位") });

    expect(
      buildPhysicsStepPayload({ ...base, unit: "N", toleranceText: "1" }),
    ).toMatchObject({ error: expect.stringContaining("你写的结果") });

    expect(
      buildPhysicsStepPayload({
        ...base,
        unit: "N",
        expectedText: "6",
        toleranceText: "101",
      }),
    ).toMatchObject({ error: expect.stringContaining("0 到 100") });

    expect(
      buildPhysicsStepPayload({ ...base, unit: "N", expectedText: "six" }),
    ).toMatchObject({ error: expect.stringContaining("要写数字") });

    expect(
      buildPhysicsStepPayload({
        ...base,
        unit: "N",
        expectedText: "6",
        absoluteToleranceText: "-0.1",
      }),
    ).toMatchObject({ error: expect.stringContaining("绝对容差") });
  });

  it("rejects malformed result ranges before calling the API", () => {
    expect(
      buildPhysicsStepPayload({
        ...base,
        unit: "m/s",
        expectedText: "[6.4, 6.3]",
      }),
    ).toMatchObject({ error: expect.stringContaining("下限") });

    expect(
      buildPhysicsStepPayload({
        ...base,
        unit: "m/s",
        expectedText: "6±-1",
      }),
    ).toMatchObject({ error: expect.stringContaining("不确定度") });

    expect(
      buildPhysicsStepPayload({
        ...base,
        unit: "m/s",
        expectedText: "[6.3]",
      }),
    ).toMatchObject({ error: expect.stringContaining("区间") });

    expect(
      buildPhysicsStepPayload({
        ...base,
        unit: "m/s",
        expectedText: "6±0.1±0.2",
      }),
    ).toMatchObject({ error: expect.stringContaining("只写一个") });
  });

  it("rejects malformed unit and numeric lines before calling the API", () => {
    expect(
      buildPhysicsStepPayload({ ...base, unitsText: "m kg" }),
    ).toMatchObject({ error: expect.stringContaining("符号=单位") });

    expect(
      buildPhysicsStepPayload({ ...base, valuesText: "m=two" }),
    ).toMatchObject({ error: expect.stringContaining("要写数字") });
  });

  it("rejects duplicate symbols and multiple equals signs", () => {
    expect(
      buildPhysicsStepPayload({ ...base, unitsText: "m=kg\nm=kg" }),
    ).toMatchObject({ error: expect.stringContaining("写了两次") });

    expect(
      buildPhysicsStepPayload({ ...base, step: "F = m*a = m*g" }),
    ).toMatchObject({ error: expect.stringContaining("只支持一个等号") });
  });
});
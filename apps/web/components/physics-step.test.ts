import { describe, expect, it } from "vitest";

import { buildPhysicsStepPayload } from "./physics-step";

const base = {
  step: "F - mu*N = m*a",
  unit: "",
  unitsText: "",
  valuesText: "",
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
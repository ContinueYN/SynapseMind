/**
 * Turn the physics step-check form into the `data` payload the API expects.
 *
 * The backend owns every semantic decision (units, dimensions, numeric
 * replay). This module only checks the *shape* of what the student typed, so a
 * malformed key=value line becomes a local error instead of a confusing
 * `unknown` from the server. It never evaluates the formula.
 */

const SYMBOL = /^[A-Za-z_][A-Za-z0-9_]*$/;

export interface PhysicsStepFields {
  step: string;
  unit: string;
  unitsText: string;
  valuesText: string;
  expectedText: string;
  toleranceText: string;
}

export type PhysicsStepPayload =
  | { text: string; data: Record<string, unknown> }
  | { error: string };

function entries(raw: string): string[] {
  return raw
    .split(/[\n,，;；]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function splitPair(entry: string): { key: string; value: string } | null {
  const at = entry.indexOf("=");
  if (at < 0) return null;
  return {
    key: entry.slice(0, at).trim(),
    value: entry.slice(at + 1).trim(),
  };
}

function parseUnits(raw: string): { units: Record<string, string> } | { error: string } {
  const units: Record<string, string> = {};
  for (const entry of entries(raw)) {
    const pair = splitPair(entry);
    if (!pair) {
      return { error: `单位要写成 符号=单位，例如 m=kg；读不懂「${entry}」。` };
    }
    if (!SYMBOL.test(pair.key)) {
      return { error: `符号「${pair.key || entry}」不合法；用字母开头，例如 m、mu、theta。` };
    }
    if (pair.key in units) {
      return { error: `符号「${pair.key}」的单位写了两次。` };
    }
    units[pair.key] = pair.value;
  }
  return { units };
}

function parseValues(raw: string): { values: Record<string, number> } | { error: string } {
  const values: Record<string, number> = {};
  for (const entry of entries(raw)) {
    const pair = splitPair(entry);
    if (!pair) {
      return { error: `数值要写成 符号=数字，例如 m=2；读不懂「${entry}」。` };
    }
    if (!SYMBOL.test(pair.key)) {
      return { error: `符号「${pair.key || entry}」不合法；用字母开头，例如 m、mu、theta。` };
    }
    if (pair.key in values) {
      return { error: `符号「${pair.key}」的数值写了两次。` };
    }
    if (!pair.value) {
      return { error: `符号「${pair.key}」的数值不能为空。` };
    }
    const number = Number(pair.value);
    if (!Number.isFinite(number)) {
      return { error: `符号「${pair.key}」的数值要写数字，例如 2、0.5、1e-3。` };
    }
    values[pair.key] = number;
  }
  return { values };
}

export function buildPhysicsStepPayload(fields: PhysicsStepFields): PhysicsStepPayload {
  const text = fields.step.trim().replace(/\s+/g, " ");
  if (!text) return { error: "先写这一步的等式或表达式。" };
  if ((text.match(/=/g) ?? []).length > 1) {
    return { error: "这一步只支持一个等号；先把要检查的关系拆出来。" };
  }

  const unit = fields.unit.trim();
  const isEquation = text.includes("=");
  if (!isEquation && !unit) {
    return { error: "只写一个量时，要填它的结果单位，例如 N。" };
  }
  if (fields.expectedText.trim() && !unit) {
    return { error: "填了「你写的结果」时，要填结果单位，例如 N。" };
  }

  const parsedUnits = parseUnits(fields.unitsText);
  if ("error" in parsedUnits) return parsedUnits;
  const parsedValues = parseValues(fields.valuesText);
  if ("error" in parsedValues) return parsedValues;

  let expected: { value: number; unit: string } | null = null;
  if (fields.expectedText.trim()) {
    const value = Number(fields.expectedText.trim());
    if (!Number.isFinite(value)) {
      return { error: "「你写的结果」要写数字，例如 6、0.5、1e-3。" };
    }
    expected = { value, unit };
  }

  let tolerance: { relative: number } | null = null;
  if (fields.toleranceText.trim()) {
    const percent = Number(fields.toleranceText.trim());
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
      return { error: "相对容差要写 0 到 100 之间的数字，单位是 %。" };
    }
    tolerance = { relative: percent / 100 };
  }

  const data: Record<string, unknown> = {
    [isEquation ? "equation" : "expression"]: text,
    units: parsedUnits.units,
  };
  if (unit) data.unit = unit;
  if (Object.keys(parsedValues.values).length > 0) {
    data.values = parsedValues.values;
  }
  if (expected) data.expected = expected;
  if (tolerance) data.tolerance = tolerance;
  return { text, data };
}
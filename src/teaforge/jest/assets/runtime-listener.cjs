"use strict";

const fs = require("fs");

const evidencePath = process.env.TEAFORGE_JEST_EVIDENCE_PATH;
const originalExpect = global.expect;
const MAX_VALUE_LENGTH = 4096;
const DEFAULT_MAX_ASSERTIONS = 5000;
const DEFAULT_MAX_EVIDENCE_BYTES = 5 * 1024 * 1024;
const WARNING_RESERVE_BYTES = 512;

const positiveInteger = (value, fallback) => {
  const parsed = Number.parseInt(value || "", 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
};

const maxAssertions = positiveInteger(
  process.env.TEAFORGE_JEST_MAX_ASSERTIONS,
  DEFAULT_MAX_ASSERTIONS,
);
const maxEvidenceBytes = positiveInteger(
  process.env.TEAFORGE_JEST_MAX_EVIDENCE_BYTES,
  DEFAULT_MAX_EVIDENCE_BYTES,
);
const sensitiveKey = /(?:password|passwd|secret|token|authorization|cookie|api[_-]?key|session)/i;
const secretTextPatterns = [
  /\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi,
  /\bsk-[A-Za-z0-9_-]{16,}\b/g,
  /\bAKIA[A-Z0-9]{16}\b/g,
  /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g,
];

if (evidencePath && typeof originalExpect === "function") {
  let assertionCount = 0;
  let limitWarningWritten = false;

  const redactText = (value) => {
    let redacted = value;
    for (const pattern of secretTextPatterns) {
      redacted = redacted.replace(pattern, "[REDACTED]");
    }
    return redacted;
  };

  const render = (value) => {
    const seen = new WeakSet();
    let rendered;
    try {
      rendered = JSON.stringify(value, (key, nested) => {
        if (key && sensitiveKey.test(key)) return "[REDACTED]";
        if (typeof nested === "bigint") return `${nested.toString()}n`;
        if (typeof nested === "function") return `[Function ${nested.name || "anonymous"}]`;
        if (typeof nested === "symbol") return nested.toString();
        if (typeof nested === "string") return redactText(nested);
        if (nested instanceof Error) {
          return { name: nested.name, message: nested.message };
        }
        if (nested && typeof nested === "object") {
          if (seen.has(nested)) return "[Circular]";
          seen.add(nested);
        }
        return nested;
      });
    } catch (_error) {
      rendered = redactText(String(value));
    }
    if (rendered === undefined) rendered = redactText(String(value));
    if (rendered.length > MAX_VALUE_LENGTH) {
      return `${rendered.slice(0, MAX_VALUE_LENGTH)}…[truncated]`;
    }
    return rendered;
  };

  const currentEvidenceBytes = () => {
    try {
      return fs.statSync(evidencePath).size;
    } catch (error) {
      if (error && error.code === "ENOENT") return 0;
      throw error;
    }
  };

  const appendPayload = (payload, reserveBytes = 0) => {
    const line = `${JSON.stringify(payload)}\n`;
    const lineBytes = Buffer.byteLength(line, "utf8");
    if (currentEvidenceBytes() + lineBytes + reserveBytes > maxEvidenceBytes) {
      return false;
    }
    fs.appendFileSync(evidencePath, line, "utf8");
    return true;
  };

  const writeLimitWarning = (message) => {
    if (limitWarningWritten) return;
    limitWarningWritten = true;
    appendPayload({
      schema_version: 1,
      kind: "warning",
      code: "evidence-limit-reached",
      message,
    });
  };

  const writeEvidence = ({ actual, expected, matcher, modifiers, passed, error }) => {
    if (assertionCount >= maxAssertions) {
      writeLimitWarning(
        `Jest evidence was capped at ${maxAssertions} assertion records.`,
      );
      return;
    }
    const state = typeof originalExpect.getState === "function" ? originalExpect.getState() : {};
    const payload = {
      schema_version: 1,
      kind: "assertion",
      test_name: state.currentTestName || "",
      test_path: state.testPath || "",
      matcher,
      expected: expected.map(render),
      actual: render(actual),
      passed,
      negated: modifiers.includes("not"),
      promise_mode: modifiers.includes("resolves")
        ? "resolves"
        : modifiers.includes("rejects")
          ? "rejects"
          : "",
      error: error ? `${error.name || "Error"}: matcher failed; inspect expected and actual evidence.` : "",
    };
    if (!appendPayload(payload, WARNING_RESERVE_BYTES)) {
      writeLimitWarning(
        `Jest evidence reached its ${maxEvidenceBytes}-byte limit and was truncated.`,
      );
      return;
    }
    assertionCount += 1;
  };

  const observedPromiseValue = async (actual, modifiers) => {
    if (modifiers.includes("resolves")) return Promise.resolve(actual);
    if (modifiers.includes("rejects")) {
      try {
        return await Promise.resolve(actual);
      } catch (error) {
        return error;
      }
    }
    return actual;
  };

  const wrapExpectation = (expectation, actual, modifiers = []) => new Proxy(expectation, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver);
      if (typeof value === "function") {
        const matcher = String(property);
        return (...expected) => {
          let observedActual = actual;
          let matcherTarget = target;
          let matcherFunction = value;
          if (typeof actual === "function" && matcher.startsWith("toThrow")) {
            const observedFunction = (...args) => {
              try {
                const result = actual(...args);
                observedActual = result;
                return result;
              } catch (error) {
                observedActual = error;
                throw error;
              }
            };
            matcherTarget = originalExpect(observedFunction);
            for (const modifier of modifiers) matcherTarget = matcherTarget[modifier];
            matcherFunction = matcherTarget[property];
          }
          try {
            const result = Reflect.apply(matcherFunction, matcherTarget, expected);
            if (result && typeof result.then === "function") {
              return Promise.resolve(result).then(
                async (resolved) => {
                  const observed = await observedPromiseValue(observedActual, modifiers);
                  writeEvidence({ actual: observed, expected, matcher, modifiers, passed: true });
                  return resolved;
                },
                async (error) => {
                  const observed = await observedPromiseValue(observedActual, modifiers);
                  writeEvidence({ actual: observed, expected, matcher, modifiers, passed: false, error });
                  throw error;
                },
              );
            }
            writeEvidence({ actual: observedActual, expected, matcher, modifiers, passed: true });
            return result;
          } catch (error) {
            writeEvidence({ actual: observedActual, expected, matcher, modifiers, passed: false, error });
            throw error;
          }
        };
      }
      if (value && typeof value === "object") {
        return wrapExpectation(value, actual, [...modifiers, String(property)]);
      }
      return value;
    },
  });

  global.expect = new Proxy(originalExpect, {
    apply(target, thisArg, args) {
      const expectation = Reflect.apply(target, thisArg, args);
      return wrapExpectation(expectation, args[0]);
    },
  });
}

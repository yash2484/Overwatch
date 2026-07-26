// jest-dom matchers (toBeInTheDocument, toHaveFocus, ...) for component tests. Pure-function
// suites (the evidence join, reducers) don't need these, but wiring it once keeps future
// component tests honest without per-file imports.
import "@testing-library/jest-dom/vitest";

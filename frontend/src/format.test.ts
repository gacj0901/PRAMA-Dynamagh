import { describe, expect, it } from "vitest";
import { shortId, stateTone } from "./format";

describe("operator display helpers", () => {
  it("shortens opaque identifiers without changing their ending", () => {
    expect(shortId("0x1234567890abcdef", 6)).toBe("0x1234…cdef");
  });

  it("maps persisted terminal states to a semantic display tone", () => {
    expect(stateTone("TICKETED")).toBe("good");
    expect(stateTone("LOCAL_ONLY")).toBe("warn");
    expect(stateTone("FAILED")).toBe("bad");
  });
});

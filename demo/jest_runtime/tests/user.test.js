const { createUser, getUser } = require("../src/user");

describe("legacy user tests", () => {
  test("captures runtime values from variables", () => {
    expect(globalThis.teaForgeDemoSetupLoaded).toBe(true);
    const input = { name: "tea", age: 20, password: globalThis.teaForgeDemoPassword };
    const expected = { id: 1, name: input.name, age: input.age, password: input.password };
    const actual = createUser(input);

    expect(actual).toEqual(expected);
    expect(actual.name).not.toBe("coffee");
  });

  test("captures resolved values", async () => {
    const actual = Promise.resolve(createUser({ name: "matcha", age: 30 }));
    await expect(actual).resolves.toEqual({ id: 1, name: "matcha", age: 30 });
  });

  test("rejects a missing user name", () => {
    expect(() => createUser({ age: 20 })).toThrow("name required");
  });

  test("captures thrown expectations", () => {
    expect(() => getUser(404)).toThrow("not found");
  });

  test("gets an existing user", () => {
    expect(getUser(1)).toEqual({ id: 1, name: "tea" });
  });
});

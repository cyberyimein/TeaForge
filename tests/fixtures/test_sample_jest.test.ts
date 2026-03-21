import { createUser, getUser } from "./jest_sample/src/user";

test("create user normal", () => {
    const input = { name: "tea", age: 20 };
    const result = createUser(input);

    expect(result.name).toBe("tea");
    expect(result.age).toBe(20);
});

test.each([
    ["a", 0],
    ["tea-max", 120],
])("create user boundary age %s %d", (name, age) => {
    const result = createUser({ name, age });

    expect(result.age).toBe(age);
});

test("get user exceptional not found", () => {
    expect(() => getUser(404)).toThrow("not found");
});
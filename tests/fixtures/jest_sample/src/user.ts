export function createUser(input: { name: string; age: number }) {
    if (!input.name) {
        throw new Error("name required");
    }
    return {
        id: 1,
        name: input.name,
        age: input.age,
    };
}

export function getUser(id: number) {
    if (id === 404) {
        throw new Error("not found");
    }
    return {
        id,
        name: "tea",
    };
}
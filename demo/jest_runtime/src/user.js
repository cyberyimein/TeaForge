function createUser(input) {
  if (!input.name) {
    throw new Error("name required");
  }
  return { id: 1, name: input.name, age: input.age, password: input.password };
}

function getUser(id) {
  if (id === 404) {
    throw new Error("not found");
  }
  return { id, name: "tea" };
}

module.exports = { createUser, getUser };

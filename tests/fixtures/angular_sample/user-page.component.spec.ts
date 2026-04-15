import { render, screen } from "@testing-library/angular";
import { UserPageComponent } from "./user-page.component";

describe("UserPage", () => {
    const save = { emit: jest.fn() };
    const router = { navigateByUrl: jest.fn(), navigate: jest.fn() };

    beforeEach(() => {
        jest.clearAllMocks();
    });

    it("user page submit normal", async () => {
        await render(UserPageComponent);
        await router.navigateByUrl("/users/new");
        component.form.setValue({ name: "tea", quantity: 1 });
        submitButton.click();

        expect(save.emit).toHaveBeenCalledWith({ name: "tea", quantity: 1 });
        expect(messageEl.textContent).toContain("saved");
        expect(router.navigate).toHaveBeenCalledWith(["/done"], { queryParams: { id: 1 } });
    });

    it("user page validation on blur", async () => {
        await render(UserPageComponent);
        await router.navigateByUrl("/users/new");
        emailInput.dispatchEvent(new FocusEvent("focus"));
        emailInput.dispatchEvent(new Event("blur"));

        expect(screen.getByRole("alert")).toHaveTextContent("入力エラー");
    });
});
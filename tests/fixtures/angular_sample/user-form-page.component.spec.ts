import { render, fireEvent, screen } from "@testing-library/angular";
import { UserFormPageComponent } from "./user-form-page.component";

describe("UserFormPage", () => {
    const userFormService = { loadPreset: () => ({ email: "preset@example.com" }) };

    it("user form page shows validation error", async () => {
        jest.spyOn(userFormService, "loadPreset").mockResolvedValue({ email: "preset@example.com" });
        await render(UserFormPageComponent);
        await router.navigateByUrl("/users/form");
        component.form.patchValue({ email: "bad-mail" });
        fireEvent.focus(emailInput);
        fireEvent.blur(emailInput);

        expect(screen.getByRole("alert")).toHaveTextContent("入力エラー");
    });
});
export class UserFormPageComponent {
    submit(email: string) {
        if (!email.includes("@")) {
            return { status: "invalid" };
        }
        return { status: "ok" };
    }
}
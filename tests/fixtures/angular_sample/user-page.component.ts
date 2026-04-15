export class UserPageComponent {
    loading = false;

    submitForm(name: string, quantity: number) {
        if (!name) {
            return { status: "invalid" };
        }
        if (quantity < 1) {
            return { status: "invalid" };
        }
        return { status: "saved", id: 1 };
    }

    navigateToDetail(id: number) {
        if (id <= 0) {
            return "/error";
        }
        return `/detail?id=${id}`;
    }
}
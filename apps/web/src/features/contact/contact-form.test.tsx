import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ContactForm } from "./contact-form";

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

async function fillAndSend() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Name"), "Ada Lovelace");
  await user.type(screen.getByLabelText("Email"), "ada@example.com");
  await user.type(screen.getByLabelText("Message"), "We need help with our monthly sales data.");
  await user.click(screen.getByRole("button", { name: "Send message" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("ContactForm", () => {
  it("posts the message and confirms", async () => {
    const fetchMock = respond(202, { received: true });
    vi.stubGlobal("fetch", fetchMock);
    render(<ContactForm />);
    await fillAndSend();
    expect(await screen.findByText("Message sent.")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/contact");
    expect(JSON.parse(init.body)).toMatchObject({
      name: "Ada Lovelace",
      email: "ada@example.com",
      topic: "full_time",
      company: null,
      website: null,
    });
  });

  it("maps validation errors onto fields", async () => {
    vi.stubGlobal(
      "fetch",
      respond(422, { code: "validation_error", errors: [{ loc: ["body", "email"] }] }),
    );
    render(<ContactForm />);
    await fillAndSend();
    expect(await screen.findByText("Enter an email address I can reply to.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("offers the email address when the limit is reached", async () => {
    vi.stubGlobal("fetch", respond(429, { code: "quota_exceeded" }));
    render(<ContactForm />);
    await fillAndSend();
    expect(await screen.findByText(/email uzairazhar@gmail.com instead/)).toBeInTheDocument();
  });

  it("keeps the honeypot away from people and assistive technology", () => {
    render(<ContactForm />);
    const trap = document.querySelector('input[name="website"]');
    expect(trap).toHaveAttribute("tabindex", "-1");
    expect(trap?.closest("[aria-hidden]")).not.toBeNull();
  });
});

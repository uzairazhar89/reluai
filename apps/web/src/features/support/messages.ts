import { ApiError } from "@/lib/api/client";

function minutes(seconds: number | undefined): string {
  if (!seconds) return "a few minutes";
  const m = Math.max(1, Math.ceil(seconds / 60));
  return m === 1 ? "1 minute" : `${m} minutes`;
}

/** What went wrong with a conversation request, and what to do next. */
export function supportErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "quota_exceeded":
        return `You have reached the hourly limit for this demo. You can continue in ${minutes(error.retryAfter)}.`;
      case "awaiting_approval":
        return "A refund is waiting for your decision as supervisor. Approve or reject it first.";
      case "conversation_not_found":
        return "This conversation has expired (they are kept for a day). Start a new one.";
      case "conversation_finished":
        return "This conversation has reached its message limit. Start a new one.";
      case "not_your_conversation":
        return "Only the visitor who started this conversation can continue it.";
      case "orders_unavailable":
        return "The order data is not available on the server right now. Try again later.";
      case "validation_error":
        return "Messages need to be between 3 and 600 characters.";
    }
    if (error.status === 429)
      return "Too many requests from your connection. Wait a minute and try again.";
    if (error.status === 0 || error.status >= 500) {
      return "The support agent is not responding right now. Try again in a minute.";
    }
    return error.message;
  }
  return "The request did not reach the server. Check your connection and try again.";
}

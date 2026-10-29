import { ApiError } from "@/lib/api/client";

function minutes(seconds: number | undefined): string {
  if (!seconds) return "a few minutes";
  const m = Math.max(1, Math.ceil(seconds / 60));
  return m === 1 ? "1 minute" : `${m} minutes`;
}

/** What went wrong with a "Try it" request, and what to do next. */
export function benchErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "quota_exceeded":
        return `You have reached the hourly limit for this demo. You can continue in ${minutes(error.retryAfter)}.`;
      case "not_an_image":
        return "This file is not a photo the server can read. Try a JPEG, PNG or WebP.";
      case "unsupported":
        return "Only JPEG, PNG and WebP photos can be classified.";
      case "too_many_pixels":
        return "This photo has too many pixels (the limit is 25 megapixels). Try a smaller one.";
      case "too_large":
        return "Photos can be up to 5 MB.";
      case "empty_file":
        return "The file is empty.";
      case "busy":
        return "The server is busy with other work. Try again in a minute.";
      case "timeout":
        return "The run took too long and was stopped. Try again in a minute.";
      case "not_built":
        return "The benchmark models are not installed on the server right now.";
    }
    if (error.status === 429)
      return "Too many requests from your connection. Wait a minute and try again.";
    if (error.status === 413) return "Photos can be up to 5 MB.";
    if (error.status === 0 || error.status >= 500) {
      return "The benchmark service is not responding right now. Try again in a minute.";
    }
    return error.message;
  }
  return "The request did not reach the server. Check your connection and try again.";
}

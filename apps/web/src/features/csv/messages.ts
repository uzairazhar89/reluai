import { ApiError } from "@/lib/api/client";

function minutes(seconds: number | undefined): string {
  if (!seconds) return "a few minutes";
  const m = Math.max(1, Math.ceil(seconds / 60));
  return m === 1 ? "1 minute" : `${m} minutes`;
}

/** What went wrong with a question, and what to do about it. */
export function askErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "quota_exceeded":
        return `Each visitor can ask 60 questions per hour, and you have used them. You can ask again in ${minutes(error.retryAfter)}.`;
      case "busy":
        return "The analyst is answering another visitor's question. Try again in a few seconds.";
      case "upload_not_found":
        return "Your file has been deleted: uploads are kept for one hour. Upload it again to keep asking.";
      case "dataset_unavailable":
        return "The retailer table is not available on the server right now. Try again later.";
      case "validation_error":
        return "Questions need to be between 3 and 300 characters.";
    }
    if (error.status === 429)
      return "Too many requests from your connection. Wait a minute and try again.";
    if (error.status === 0 || error.status >= 500) {
      return "The analyst is not responding right now. Try again in a minute.";
    }
    return error.message;
  }
  return "The request did not reach the server. Check your connection and try again.";
}

/** Upload problems: the server's messages are already written for visitors. */
export function uploadErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "quota_exceeded") {
      return `Each visitor can upload 10 files per hour. You can upload another in ${minutes(error.retryAfter)}.`;
    }
    if (error.status === 413) return "Files can be up to 2 MB.";
    if (error.status === 0 || error.status >= 500) {
      return "The upload did not complete because the server is not responding. Try again in a minute.";
    }
    return error.message;
  }
  return "The upload did not reach the server. Check your connection and try again.";
}

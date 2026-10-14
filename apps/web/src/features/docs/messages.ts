import { ApiError } from "@/lib/api/client";

function minutes(seconds: number | undefined): string {
  if (!seconds) return "a few minutes";
  const m = Math.max(1, Math.ceil(seconds / 60));
  return m === 1 ? "1 minute" : `${m} minutes`;
}

/** What went wrong with a documents request, and what to do next. */
export function docsErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "quota_exceeded":
        return `You have reached the hourly limit for this demo. You can continue in ${minutes(error.retryAfter)}.`;
      case "too_large":
      case "not_a_pdf":
      case "empty_file":
        return error.message;
      case "busy":
        return "The server is busy reading other documents. Try again in a minute.";
      case "invoice_not_found":
        return "This sample invoice is no longer available; reload the page for the current set.";
      case "document_not_found":
        return "This document has expired or was deleted. Uploads are kept for an hour; upload it again.";
      case "not_your_document":
        return "Only the visitor who uploaded this document can open it.";
      case "not_ready":
        return "The document is still being read. Ask again when it is ready.";
      case "sample_unavailable":
        return "The sample document is not available on the server right now.";
      case "validation_error":
        return "Questions need to be between 2 and 300 characters.";
    }
    if (error.status === 429)
      return "Too many requests from your connection. Wait a minute and try again.";
    if (error.status === 413) return "PDFs can be up to 10 MB.";
    if (error.status === 0 || error.status >= 500) {
      return "The document service is not responding right now. Try again in a minute.";
    }
    return error.message;
  }
  return "The request did not reach the server. Check your connection and try again.";
}

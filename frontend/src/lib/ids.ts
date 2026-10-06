/** Client message / attachment ids: UUID v4 (36 chars, within the API's 8–64 limit). */
export function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

const CROCKFORD_32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/**
 * A client-generated thread id: every thread_id column server-side is varchar(26), sized for the
 * backend's own ULIDs (mainforte.ids.new_id) -- a newId() UUID (36 chars) silently overflows it
 * (StringDataRightTruncation on the client_messages insert, which rolls back the whole post, so
 * the message looks "sent" on the client but the server never actually persists it). This isn't a
 * real ULID (no embedded timestamp -- nothing here needs it to sort), just a same-length,
 * same-charset random id so it fits the column exactly like a server-generated one would.
 */
export function newThreadId(): string {
  const bytes = new Uint8Array(26);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") crypto.getRandomValues(bytes);
  else for (let i = 0; i < 26; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => CROCKFORD_32[b % 32]).join("");
}

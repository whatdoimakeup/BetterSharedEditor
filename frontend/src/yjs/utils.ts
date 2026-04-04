/**
 * Yjs state encoding/decoding utilities.
 */

/**
 * Encode binary Yjs state to base64 string for API transport.
 */
export function encode_yjs_state(state: Uint8Array): string {
  // Convert Uint8Array to base64
  let binary = "";
  const bytes = new Uint8Array(state);
  const chunkSize = 8192;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk as unknown as number[]);
  }
  return btoa(binary);
}

/**
 * Decode base64 string back to Uint8Array Yjs state.
 */
export function decode_yjs_state(stateB64: string): Uint8Array {
  const binary = atob(stateB64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

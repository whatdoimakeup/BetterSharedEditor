/**
 * Yjs state encoding/decoding helpers.
 */

export function encode_yjs_state(state: Uint8Array): string {
  let binary = "";
  const chunkSize = 8192;

  for (let i = 0; i < state.length; i += chunkSize) {
    const chunk = state.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
}

export function decode_yjs_state(stateB64: string): Uint8Array {
  const binary = atob(stateB64);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}

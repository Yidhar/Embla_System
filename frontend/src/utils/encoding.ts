export const decoder = new TextDecoder('utf-8')

export function decodeBase64(base64: string) {
  const binaryString = atob(base64)
  const bytes = new Uint8Array(binaryString.length)

  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i)
  }

  return decoder.decode(bytes)
}

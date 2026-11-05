// Criptografia no navegador (Web Crypto). Espelha uai_data/crypto.py, passo a passo:
//   senha → PBKDF2 → AES-GCM abre a chave privada RSA → RSA-OAEP abre a chave do painel → AES-GCM abre os dados.
const enc = new TextEncoder();

export const fromB64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
export const fromB64u = (s) => fromB64(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4));
export const toB64u = (bytes) =>
  btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

/** Nome do arquivo de login: o mesmo cálculo de builder.auth_name() no Python. */
export async function authFileName(salt, login) {
  const digest = await crypto.subtle.digest('SHA-256', enc.encode(`${salt}:${login.toLowerCase()}`));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

/** Abre a chave privada do usuário. Senha errada lança erro (a verificação é o próprio AES-GCM). */
export async function unlockPrivateKey(auth, password) {
  const base = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: fromB64(auth.kdf.salt), iterations: auth.kdf.iter, hash: 'SHA-256' },
    base, { name: 'AES-GCM', length: 256 }, false, ['decrypt'],
  );
  const blob = fromB64(auth.priv);
  const der = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: blob.slice(0, 12), additionalData: enc.encode('uai-private-key') }, key, blob.slice(12),
  );
  return crypto.subtle.importKey('pkcs8', der, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['decrypt']);
}

/** Abre uma chave de painel embrulhada com a chave pública do usuário. Devolve os 32 bytes crus. */
export async function unwrapKey(privateKey, wrappedB64) {
  return new Uint8Array(await crypto.subtle.decrypt({ name: 'RSA-OAEP' }, privateKey, fromB64(wrappedB64)));
}

const aesKey = (raw) => crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['decrypt']);

async function gunzip(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Formato do arquivo: [flag 1B][iv 12B][ciphertext+tag]; a flag (1 = gzip) é autenticada. */
export async function decrypt(raw, buffer) {
  const blob = new Uint8Array(buffer);
  const flag = blob.slice(0, 1);
  const plain = new Uint8Array(await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: blob.slice(1, 13), additionalData: flag }, await aesKey(raw), blob.slice(13),
  ));
  return flag[0] === 1 ? gunzip(plain) : plain;
}

export async function decryptJson(raw, buffer) {
  return JSON.parse(new TextDecoder().decode(await decrypt(raw, buffer)));
}

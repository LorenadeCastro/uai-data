// Abre o site gerado pelo Python usando o MESMO código do navegador (crypto.js + data.js).
import { readFileSync } from 'node:fs';
import { authFileName, decryptJson, unlockPrivateKey, unwrapKey } from '../src/uai_data/web/crypto.js';
import { aggregate } from '../src/uai_data/web/data.js';

const [site, user, password, cardId] = process.argv.slice(2);
const read = (p) => readFileSync(`${site}/${p}`);
const cfg = JSON.parse(read('config.json'));
const name = await authFileName(cfg.salt, user);
const auth = JSON.parse(read(`auth/${name}.json`));
const priv = await unlockPrivateKey(auth, password);
const me = await decryptJson(await unwrapKey(priv, auth.keys['@me']), read(`auth/${name}.me.bin`));
const dash = me.dashboards[0];
const key = await unwrapKey(priv, auth.keys[dash.id]);
const spec = await decryptJson(key, read(`d/${dash.id}/spec.bin`));
const card = spec.cards.find((c) => c.id === cardId);
const payload = await decryptJson(key, read(`c/${dash.id}/${cardId}.bin`));
console.log(JSON.stringify({
  title: spec.title,
  all: aggregate(payload, card, {}),
  y2025: aggregate(payload, card, { ano: new Set(['2025']) }),
}));
